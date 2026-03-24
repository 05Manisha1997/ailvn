"""
memory/session_memory.py

Cosmos DB-backed session memory for call state (temporary storage).
All data is automatically deleted when TTL expires (call ends).
Stores: verification state, conversation turns, intent history,
        temporary RAG document references.
TTL: Handled by Cosmos DB's built-in TTL feature.
"""
import uuid
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict, field

from config.settings import get_settings
from config.azure_clients import get_cosmos_client
from utils.logger import logger

settings = get_settings()


@dataclass
class ConversationTurn:
    turn_number: int
    user_text: str
    intent: str
    intent_confidence: float
    bot_response: str
    doc_ids_used: list[str]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CallSession:
    call_id: str
    caller_phone: str
    caller_name: Optional[str] = None
    caller_id: Optional[str] = None
    is_verified: bool = False
    current_intent: Optional[str] = None
    intent_history: list[str] = field(default_factory=list)
    conversation: list[ConversationTurn] = field(default_factory=list)
    temp_doc_ids: list[str] = field(default_factory=list)   # ChromaDB collection IDs
    temp_doc_metadata: list[dict] = field(default_factory=list)
    is_live_agent_requested: bool = False
    agent_id: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ended_at: Optional[str] = None


class SessionMemory:
    """
    Manages call sessions in Cosmos DB with automatic TTL expiry.
    Document ID: {call_id}
    TTL: COSMOS_DB_SESSION_TTL_SECONDS (default 3600 = 1 hour)
    Container: cosmos_db_container_sessions
    """

    def __init__(self):
        client = get_cosmos_client()
        db = client.get_database_client(settings.cosmos_db_database)
        self._container = db.get_container_client(settings.cosmos_db_container_sessions)
        self._ttl = settings.cosmos_db_session_ttl_seconds

    def create_session(self, caller_phone: str) -> CallSession:
        """Create a new call session and persist to Cosmos DB."""
        call_id = str(uuid.uuid4())
        session = CallSession(call_id=call_id, caller_phone=caller_phone)
        self._save(session)
        logger.info("session_created", call_id=call_id, phone=caller_phone)
        return session

    def get_session(self, call_id: str) -> Optional[CallSession]:
        """Load a session from Cosmos DB."""
        try:
            item = self._container.read_item(item=call_id, partition_key=call_id)
            # Deserialize nested dataclasses
            item["conversation"] = [ConversationTurn(**t) for t in item.get("conversation", [])]
            return CallSession(**item)
        except Exception as e:
            logger.debug("session_not_found", call_id=call_id, error=str(e))
            return None

    def save_session(self, session: CallSession):
        """Persist session updates to Cosmos DB (resets TTL)."""
        self._save(session)

    def _save(self, session: CallSession):
        """Save session document with TTL."""
        data = asdict(session)
        # Convert dataclass objects to dicts for serialization
        data["conversation"] = [asdict(t) for t in session.conversation]
        # Add Cosmos DB required fields
        data["id"] = session.call_id
        # Set TTL in seconds (Cosmos DB will delete after this time from last write)
        data["ttl"] = self._ttl
        
        try:
            self._container.upsert_item(body=data)
        except Exception as e:
            logger.error("session_save_failed", call_id=session.call_id, error=str(e))
            raise

    def add_turn(
        self,
        call_id: str,
        user_text: str,
        intent: str,
        intent_confidence: float,
        bot_response: str,
        doc_ids_used: list[str],
    ) -> Optional[CallSession]:
        """Append a conversation turn to the session."""
        session = self.get_session(call_id)
        if not session:
            return None

        turn = ConversationTurn(
            turn_number=len(session.conversation) + 1,
            user_text=user_text,
            intent=intent,
            intent_confidence=intent_confidence,
            bot_response=bot_response,
            doc_ids_used=doc_ids_used,
        )
        session.conversation.append(turn)

        # Detect intent change and log
        if session.current_intent and session.current_intent != intent:
            logger.info("intent_changed",
                        call_id=call_id,
                        from_intent=session.current_intent,
                        to_intent=intent)

        session.current_intent = intent
        if intent not in session.intent_history:
            session.intent_history.append(intent)

        self._save(session)
        return session

    def add_temp_docs(self, call_id: str, doc_ids: list[str], metadata: list[dict]):
        """
        Register temporary document IDs (ChromaDB collection entries).
        These accumulate across intent changes and are cleared on call end.
        """
        session = self.get_session(call_id)
        if not session:
            return
        # Append new doc IDs (keep previous ones from earlier intents)
        for doc_id in doc_ids:
            if doc_id not in session.temp_doc_ids:
                session.temp_doc_ids.append(doc_id)
        session.temp_doc_metadata.extend(metadata)
        self._save(session)
        logger.info("temp_docs_added",
                    call_id=call_id,
                    new_count=len(doc_ids),
                    total_count=len(session.temp_doc_ids))

    def set_verified(self, call_id: str, caller_name: str, caller_id: str):
        """Mark caller as verified after identity check passes."""
        session = self.get_session(call_id)
        if session:
            session.is_verified = True
            session.caller_name = caller_name
            session.caller_id = caller_id
            self._save(session)

    def request_live_agent(self, call_id: str) -> Optional[CallSession]:
        """Flag session for live agent transfer."""
        session = self.get_session(call_id)
        if session:
            session.is_live_agent_requested = True
            self._save(session)
        return session

    def end_session(self, call_id: str) -> Optional[CallSession]:
        """
        Mark session as ended.
        Note: Cosmos DB TTL will automatically delete after COSMOS_DB_SESSION_TTL_SECONDS.
        We keep the data briefly for summary generation.
        """
        session = self.get_session(call_id)
        if session:
            session.ended_at = datetime.utcnow().isoformat()
            self._save(session)
            logger.info("session_ended", call_id=call_id)
        return session

    def get_full_context_for_agent(self, call_id: str) -> dict:
        """
        Returns complete context package for live agent handoff.
        Includes: caller details, full transcript, all RAG documents,
                  intent history, and verification status.
        """
        session = self.get_session(call_id)
        if not session:
            return {}

        return {
            "call_id": call_id,
            "caller": {
                "phone": session.caller_phone,
                "name": session.caller_name,
                "id": session.caller_id,
                "verified": session.is_verified,
            },
            "call_duration_turns": len(session.conversation),
            "intent_journey": session.intent_history,
            "current_intent": session.current_intent,
            "transcript": [
                {
                    "turn": t.turn_number,
                    "caller": t.user_text,
                    "bot": t.bot_response,
                    "intent": t.intent,
                    "time": t.timestamp,
                }
                for t in session.conversation
            ],
            "documents_referenced": session.temp_doc_metadata,
            "started_at": session.started_at,
        }


_memory: Optional[SessionMemory] = None


def get_session_memory() -> SessionMemory:
    global _memory
    if _memory is None:
        _memory = SessionMemory()
    return _memory
