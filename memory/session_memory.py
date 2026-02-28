"""
memory/session_memory.py

Redis-backed session memory for call state.
All data is automatically deleted when TTL expires (call ends).
Stores: verification state, conversation turns, intent history,
        temporary RAG document references.
"""
import json
import uuid
from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, asdict, field

from config.settings import get_settings
from config.azure_clients import get_redis_client
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
    Manages call sessions in Redis with automatic TTL expiry.
    Key pattern: session:{call_id}
    TTL: REDIS_SESSION_TTL_SECONDS (default 1 hour)
    """

    KEY_PREFIX = "session"
    DOCS_KEY_PREFIX = "docs"

    def __init__(self):
        self._redis = get_redis_client()
        self._ttl = settings.redis_session_ttl_seconds

    def _session_key(self, call_id: str) -> str:
        return f"{self.KEY_PREFIX}:{call_id}"

    def _docs_key(self, call_id: str) -> str:
        return f"{self.DOCS_KEY_PREFIX}:{call_id}"

    def create_session(self, caller_phone: str) -> CallSession:
        """Create a new call session and persist to Redis."""
        call_id = str(uuid.uuid4())
        session = CallSession(call_id=call_id, caller_phone=caller_phone)
        self._save(session)
        logger.info("session_created", call_id=call_id, phone=caller_phone)
        return session

    def get_session(self, call_id: str) -> Optional[CallSession]:
        """Load a session from Redis."""
        raw = self._redis.get(self._session_key(call_id))
        if not raw:
            return None
        data = json.loads(raw)
        # Deserialize nested dataclasses
        data["conversation"] = [ConversationTurn(**t) for t in data.get("conversation", [])]
        return CallSession(**data)

    def save_session(self, session: CallSession):
        """Persist session updates to Redis (resets TTL)."""
        self._save(session)

    def _save(self, session: CallSession):
        data = asdict(session)
        self._redis.setex(
            self._session_key(session.call_id),
            self._ttl,
            json.dumps(data),
        )

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
        Note: Redis TTL handles actual cleanup.
        We keep the data briefly for summary generation.
        """
        session = self.get_session(call_id)
        if session:
            session.ended_at = datetime.utcnow().isoformat()
            self._save(session)
            # Reduce TTL to 10 minutes post-call (enough for summary)
            self._redis.expire(self._session_key(call_id), 600)
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
