"""Email policyholder a transcript summary when a self-service session ends (e.g. simulator clear)."""
from __future__ import annotations

import html
import uuid
from typing import Any, Optional

from services.email_service import get_email_service
from services.live_agent_queue import policyholder_contact_from_db
from utils.logger import logger


def _build_transcript_block(history: list[dict[str, Any]]) -> str:
    lines = [
        "=== Conversation transcript ===",
        "",
    ]
    for m in (history or [])[-40:]:
        role = (m.get("role") or "").strip()
        text = (m.get("content") or "").strip()
        if not text:
            continue
        who = "You" if role == "user" else "AILVN assistant" if role == "assistant" else role
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def send_conversation_end_summary_email(
    *,
    conversation_history: list[dict[str, Any]],
    caller_phone: str,
    simulated_member_id: str,
    last_portal_intent: Optional[str] = None,
    org_name: str = "AILVN",
) -> tuple[bool, Optional[str]]:
    """
    Returns (sent, skip_reason). Email/name come from policyholder DB (Cosmos) only.
    """
    hist = list(conversation_history or [])
    if len(hist) < 2:
        return False, "conversation_too_short"

    has_exchange = any(m.get("role") == "user" for m in hist) and any(
        m.get("role") == "assistant" for m in hist
    )
    if not has_exchange:
        return False, "conversation_too_short"

    email, name = policyholder_contact_from_db(simulated_member_id or "")
    if not email:
        return False, "no_customer_email"

    transcript = _build_transcript_block(hist)
    transcript_safe = html.escape(transcript)
    ai_summary = (
        '<pre style="white-space:pre-wrap;font-size:13px;font-family:system-ui,sans-serif;">'
        f"{transcript_safe}</pre>"
        '<p style="margin-top:14px;color:#555;">This is a record of your recent session with our virtual assistant. '
        "If anything looks wrong, contact us using the details on your policy.</p>"
    )

    intent_key = (last_portal_intent or "").strip() or "self_service_session"
    intent_history = [intent_key]

    svc = get_email_service()
    session_ref = str(uuid.uuid4())
    ok = svc.send_call_summary(
        to_email=email,
        caller_name=name or "Member",
        caller_phone=caller_phone or "",
        call_id=session_ref,
        intent_history=intent_history,
        conversation_turns=max(1, len(hist) // 2),
        ai_summary=ai_summary,
        documents_referenced=[],
        agent_name=None,
        is_resolved=True,
        next_steps="",
        org_name=org_name,
    )
    if not ok:
        logger.warning("conversation_summary_email_failed", to=email, session_ref=session_ref)
        return False, "email_provider_failed_or_unconfigured"
    logger.info("conversation_summary_email_sent", to=email, session_ref=session_ref)
    return True, None
