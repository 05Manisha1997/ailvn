"""
orchestrator/call_orchestrator.py

Central call lifecycle manager.

Manages the complete flow:
  CALL_START → VALIDATE_PHONE → VERIFY_IDENTITY → QUERY_LOOP
    → INTENT_DETECT → RAG_FETCH → RESPOND → (loop)
    → TRANSFER_AGENT or CALL_END → SEND_SUMMARY

This is the main entry point called by the FastAPI WebSocket handler.
"""
import asyncio
from enum import Enum
from typing import Optional, AsyncGenerator
from dataclasses import dataclass

from services.phone_validator import get_phone_validator
from services.speech_service import get_speech_service
from services.verification_service import get_verification_service, VerificationStatus
from services.tts_service import get_tts_service
from services.email_service import get_email_service
from memory.session_memory import get_session_memory
from rag.pipeline import get_rag_pipeline
from portal.response_portal import get_response_portal
from agents.crew_orchestrator import get_crew
from utils.logger import get_call_logger

# RAG fact extraction helper
import re


class CallState(str, Enum):
    INIT = "init"
    VALIDATING_PHONE = "validating_phone"
    VERIFYING_IDENTITY = "verifying_identity"
    QUERY_LOOP = "query_loop"
    LIVE_AGENT_TRANSFER = "live_agent_transfer"
    ENDING = "ending"
    ENDED = "ended"


@dataclass
class CallEvent:
    event_type: str   # "audio_chunk" | "call_end" | "transfer_request"
    data: bytes = b""
    metadata: dict = None


class CallOrchestrator:
    """
    Orchestrates a complete call from start to finish.
    
    Usage:
        orch = CallOrchestrator(caller_phone="+14155552671", caller_email="user@example.com")
        async for audio_chunk in orch.run(event_generator):
            stream_to_caller(audio_chunk)
    """

    LIVE_AGENT_PHRASES = [
        "speak to agent", "talk to agent", "human agent", "live agent",
        "representative", "speak to someone", "real person", "talk to someone",
        "transfer me", "connect me to", "operator"
    ]

    END_PHRASES = ["goodbye", "bye", "end call", "hang up", "that's all", "that will be all"]

    def __init__(
        self,
        caller_phone: str,
        caller_email: Optional[str] = None,
        call_source: str = "genesis",   # "genesis" | "azure_comm" | "direct"
    ):
        self.caller_phone = caller_phone
        self.caller_email = caller_email
        self.call_source = call_source
        self.state = CallState.INIT

        # Services
        self.phone_validator = get_phone_validator()
        self.speech_service = get_speech_service()
        self.verification_service = get_verification_service()
        self.tts_service = get_tts_service()
        self.email_service = get_email_service()
        self.session_memory = get_session_memory()
        self.rag_pipeline = get_rag_pipeline()
        self.portal = get_response_portal()
        self.crew = get_crew()

        self.session = None
        self.log = None

    async def run(
        self,
        audio_event_generator: AsyncGenerator[CallEvent, None],
    ) -> AsyncGenerator[bytes, None]:
        """
        Main async generator. Consumes audio events, yields TTS audio chunks.
        This drives the entire call lifecycle.
        """
        # Step 1: Initialize session
        self.session = self.session_memory.create_session(self.caller_phone)
        self.log = get_call_logger(self.session.call_id, phone=self.caller_phone)
        self.log.info("call_started", source=self.call_source)

        # Step 2: Validate phone number
        async for audio in self._phase_validate_phone():
            yield audio

        # Step 3: Verify identity
        if self.state != CallState.ENDING:
            async for audio in self._phase_verify_identity(audio_event_generator):
                yield audio

        # Step 4: Query loop
        if self.state == CallState.QUERY_LOOP:
            async for audio in self._phase_query_loop(audio_event_generator):
                yield audio

        # Step 5: End call
        async for audio in self._phase_end_call():
            yield audio

    # ── Phase 1: Phone Validation ─────────────────────────────────────────────

    async def _phase_validate_phone(self) -> AsyncGenerator[bytes, None]:
        self.state = CallState.VALIDATING_PHONE

        validation = self.phone_validator.validate(self.caller_phone)
        if validation.is_valid:
            self.log.info("phone_valid", e164=validation.e164)
            greeting = (
                f"Welcome to Voice Navigator. "
                f"We detected your number as {validation.national_format}. "
                f"To verify your identity, please say your full name."
            )
        else:
            self.log.warning("phone_invalid", error=validation.error)
            greeting = (
                "Welcome to Voice Navigator. "
                "We could not detect your phone number. "
                "Please say your 10-digit phone number now."
            )

        async for chunk in self.tts_service.synthesize_streaming(greeting):
            yield chunk

    # ── Phase 2: Identity Verification ────────────────────────────────────────

    async def _phase_verify_identity(
        self,
        audio_event_generator: AsyncGenerator[CallEvent, None],
    ) -> AsyncGenerator[bytes, None]:
        self.state = CallState.VERIFYING_IDENTITY

        verification_session = self.verification_service.start_session(self.caller_phone)
        step = "name"

        async for event in audio_event_generator:
            if event.event_type == "call_end":
                self.state = CallState.ENDING
                return

            if event.event_type != "audio_chunk":
                continue

            # Transcribe user speech
            transcript = self.speech_service.recognize_once(event.data)
            if not transcript.text:
                response = "I didn't catch that. Could you please repeat?"
                async for chunk in self.tts_service.synthesize_streaming(response):
                    yield chunk
                continue

            user_text = transcript.text
            self.log.info("verification_input", step=step, text=user_text[:50])

            # Check for live agent request during verification
            if self._wants_live_agent(user_text):
                self.state = CallState.LIVE_AGENT_TRANSFER
                return

            # Verify this step
            result = self.verification_service.verify_identity(
                verification_session, user_text, step
            )

            if result.success and result.next_step == "proceed":
                # Verification complete
                self.session_memory.set_verified(
                    self.session.call_id,
                    verification_session.caller_name or "Customer",
                    verification_session.caller_id or "",
                )
                response = (
                    f"Thank you, {verification_session.caller_name}. "
                    "Your identity has been verified. How can I help you today?"
                )
                async for chunk in self.tts_service.synthesize_streaming(response):
                    yield chunk
                self.state = CallState.QUERY_LOOP
                return

            elif result.success and result.next_step == "ask_dob":
                step = "dob"
                response = "Thank you. Now please say your date of birth."
                async for chunk in self.tts_service.synthesize_streaming(response):
                    yield chunk

            elif result.next_step == "send_otp":
                # OTP fallback
                otp_result = self.verification_service.send_otp(verification_session)
                async for chunk in self.tts_service.synthesize_streaming(otp_result.message):
                    yield chunk
                step = "otp"

            else:
                # Failed — prompt retry
                async for chunk in self.tts_service.synthesize_streaming(result.message):
                    yield chunk

                if verification_session.status == VerificationStatus.LOCKED:
                    self.state = CallState.ENDING
                    return

    # ── Phase 3: Query Loop ───────────────────────────────────────────────────

    async def _phase_query_loop(
        self,
        audio_event_generator: AsyncGenerator[CallEvent, None],
    ) -> AsyncGenerator[bytes, None]:
        self.state = CallState.QUERY_LOOP
        current_intent = None

        async for event in audio_event_generator:
            if event.event_type == "call_end":
                self.state = CallState.ENDING
                return

            if event.event_type != "audio_chunk":
                continue

            # Transcribe
            transcript = self.speech_service.recognize_once(event.data)
            user_text = transcript.text
            if not user_text:
                continue

            self.log.info("user_query", text=user_text[:100])

            # Check for special phrases
            if self._wants_live_agent(user_text):
                self.state = CallState.LIVE_AGENT_TRANSFER
                transfer_msg = (
                    "Of course, let me connect you to a live agent now. "
                    "I'll pass along everything we've discussed so you won't need to repeat yourself."
                )
                async for chunk in self.tts_service.synthesize_streaming(transfer_msg):
                    yield chunk
                return

            if self._wants_to_end(user_text):
                self.state = CallState.ENDING
                return

            # Get intent (quick classification before full crew processing)
            session = self.session_memory.get_session(self.session.call_id)
            conversation = [
                {"user_text": t.user_text, "bot_response": t.bot_response}
                for t in (session.conversation if session else [])
            ]

            # Detect intent change → trigger new RAG fetch
            from agents.crew_orchestrator import get_llm
            quick_intent = self._quick_classify_intent(user_text)
            intent_changed = quick_intent != current_intent

            if intent_changed or not session.temp_doc_ids:
                # Fetch documents for this intent
                self.log.info("fetching_docs_for_intent", intent=quick_intent)
                doc_sources = self.portal.get_doc_sources(quick_intent)

                if doc_sources:
                    collection_name, doc_metadata = self.rag_pipeline.ingest_for_call(
                        call_id=self.session.call_id,
                        intent=quick_intent,
                        sources=doc_sources,
                    )
                    # Accumulate in session (previous docs kept alongside new ones)
                    self.session_memory.add_temp_docs(
                        self.session.call_id,
                        [collection_name],
                        doc_metadata[:10],  # Cap metadata stored
                    )
                current_intent = quick_intent

            # Retrieve relevant chunks
            rag_chunks = self.rag_pipeline.retrieve(self.session.call_id, user_text)
            rag_context = self.rag_pipeline.assemble_context(rag_chunks)

            # Extract structured facts from RAG context for template filling
            rag_facts = self._extract_rag_facts(rag_context, user_text)

            # Get response template
            template = self.portal.get_template(quick_intent)

            # Check sub-routes
            sub_route = self.portal.resolve_sub_route(template, rag_facts)

            if sub_route:
                response_text = self.portal.fill_template(
                    type('T', (), {'template': sub_route.response_override})(),
                    rag_facts
                )
                # Handle next_intent from sub_route
                if sub_route.next_intent:
                    quick_intent = sub_route.next_intent
            else:
                # Run through full CrewAI crew for response building
                crew_result = self.crew.process_turn(
                    user_text=user_text,
                    conversation_history=conversation,
                    rag_context=rag_context,
                    response_template=template.template,
                    sub_routes=[{"id": sr.route_id, "label": sr.label} for sr in template.sub_routes],
                )
                response_text = crew_result["response"]
                quick_intent = crew_result["intent"]

            # Store turn in session
            self.session_memory.add_turn(
                call_id=self.session.call_id,
                user_text=user_text,
                intent=quick_intent,
                intent_confidence=0.85,
                bot_response=response_text,
                doc_ids_used=[c.doc_id for c in rag_chunks],
            )

            # Synthesize and stream response
            voice_id = template.voice_id  # Per-intent voice override
            async for chunk in self.tts_service.synthesize_streaming(response_text, voice_id=voice_id):
                yield chunk

            self.log.info("turn_complete", intent=quick_intent, response_len=len(response_text))

    # ── Phase 4: Call End & Summary ───────────────────────────────────────────

    async def _phase_end_call(self) -> AsyncGenerator[bytes, None]:
        session = self.session_memory.get_session(self.session.call_id)
        if not session:
            return

        is_live_transfer = self.state == CallState.LIVE_AGENT_TRANSFER

        if is_live_transfer:
            # Get full context for agent
            agent_context = self.session_memory.get_full_context_for_agent(
                self.session.call_id
            )
            # In production: push to Genesys via API
            self._transfer_to_genesys(agent_context)
            self.log.info("transferred_to_live_agent")
        else:
            # Normal goodbye
            goodbye = "Thank you for calling. You'll receive a summary email shortly. Goodbye!"
            async for chunk in self.tts_service.synthesize_streaming(goodbye):
                yield chunk

        # End session
        ended_session = self.session_memory.end_session(self.session.call_id)

        # Generate and send summary
        if self.caller_email and ended_session:
            await self._send_summary(ended_session, is_live_transfer)

        # Cleanup temp docs
        self.rag_pipeline.cleanup_call(self.session.call_id)

        self.state = CallState.ENDED
        self.log.info("call_ended", state=self.state)

    async def _send_summary(self, session, is_live_transfer: bool):
        """Generate AI summary and email it to the caller."""
        try:
            conversation_dicts = [
                {
                    "turn": t.turn_number,
                    "user_text": t.user_text,
                    "bot_response": t.bot_response,
                    "intent": t.intent,
                    "timestamp": t.timestamp,
                }
                for t in session.conversation
            ]

            ai_summary = self.crew.generate_summary(
                caller_name=session.caller_name or "Customer",
                caller_phone=session.caller_phone,
                conversation=conversation_dicts,
                intent_history=session.intent_history,
                doc_metadata=session.temp_doc_metadata,
                agent_name=session.agent_id,
            )

            self.email_service.send_call_summary(
                to_email=self.caller_email,
                caller_name=session.caller_name or "Customer",
                caller_phone=session.caller_phone,
                call_id=session.call_id,
                intent_history=session.intent_history,
                conversation_turns=len(session.conversation),
                ai_summary=ai_summary,
                documents_referenced=[m.get("source", "doc") for m in session.temp_doc_metadata],
                agent_name=session.agent_id,
                is_resolved=not is_live_transfer,
            )
        except Exception as e:
            self.log.error("summary_email_failed", error=str(e))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _wants_live_agent(self, text: str) -> bool:
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in self.LIVE_AGENT_PHRASES)

    def _wants_to_end(self, text: str) -> bool:
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in self.END_PHRASES)

    def _quick_classify_intent(self, text: str) -> str:
        """
        Fast keyword-based intent classification.
        Used for doc-fetch decisions before full CrewAI processing.
        For accuracy, CrewAI does the definitive classification.
        """
        text_lower = text.lower()
        rules = {
            "ACCOUNT_BALANCE": ["balance", "how much", "account balance", "funds"],
            "RECENT_TRANSACTIONS": ["transaction", "last purchase", "recent", "history", "spent"],
            "COMPLAINT": ["complaint", "issue", "problem", "wrong", "unhappy", "angry", "dispute"],
            "PRODUCT_INFO": ["product", "offer", "rate", "interest", "savings", "plan"],
            "BILLING_QUERY": ["bill", "invoice", "charge", "payment due", "overdue"],
            "TECH_SUPPORT": ["not working", "error", "can't login", "access", "password", "locked"],
            "TRANSFER_AGENT": ["agent", "human", "representative", "speak to"],
            "LOAN_QUERY": ["loan", "mortgage", "emi", "repayment", "borrow"],
            "GOODBYE": ["bye", "goodbye", "thank you that's all"],
        }
        for intent, keywords in rules.items():
            if any(kw in text_lower for kw in keywords):
                return intent
        return "GENERAL_QUERY"

    def _extract_rag_facts(self, rag_context: str, user_text: str) -> dict:
        """
        Extract structured key-value facts from RAG context.
        In production: use an LLM extraction call or structured documents.
        This simple version does regex/heuristic extraction.
        """
        facts = {}

        # Mock extraction for demo — replace with LLM-based extraction
        patterns = {
            "balance": r"balance[:\s]+(\$?[\d,]+\.?\d*)",
            "last_txn": r"last transaction[:\s]+(.+?)(?:\n|$)",
            "ticket_id": r"ticket[:\s#]+(\w+)",
            "wait_time": r"wait time[:\s]+(.+?)(?:\n|$)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, rag_context, re.IGNORECASE)
            if match:
                facts[key] = match.group(1).strip()

        # Fallbacks for template slots
        defaults = {
            "balance": "$2,450.00",
            "last_txn": "Amazon $45.99",
            "last_txn_date": "yesterday",
            "overdraft_amount": "$0.00",
            "ticket_id": "TKT-" + self.session.call_id[:6].upper(),
            "resolution_time": "24 hours",
            "wait_time": "3 minutes",
            "reference_id": "REF-" + self.session.call_id[:8].upper(),
            "department": "customer service",
            "response": rag_context[:100] if rag_context else "I'll look into that for you.",
        }
        # Fill missing keys with defaults
        for key, default in defaults.items():
            if key not in facts:
                facts[key] = default

        return facts

    def _transfer_to_genesys(self, context: dict):
        """
        Transfer call to Genesys Cloud with full context.
        In production: use Genesys Cloud API to:
          1. Initiate transfer to agent queue
          2. Send context via Interaction Widget / screen-pop
          3. Share document SAS URLs
        """
        import json
        self.log.info("genesys_transfer_initiated", context_keys=list(context.keys()))

        # Production implementation would use:
        # from genesys_cloud_client import ApiClient, ConversationsApi
        # conversations_api.post_conversations_call_transfer(...)
        # with context payload for screen-pop
        pass
