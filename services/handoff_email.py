"""Send post-handoff summary email when an agent marks a transfer resolved."""
from __future__ import annotations

import html
from typing import Any, Optional

from services.email_service import get_email_service
from utils.logger import logger


def send_handoff_closure_email(
    rec: dict[str, Any],
    resolution_notes: Optional[str] = None,
    org_name: str = "AILVN",
) -> tuple[bool, Optional[str]]:
    """
    Returns (sent, skip_reason). skip_reason set when not sent (no email, provider, etc.).
    """
    to_email = (rec.get("customer_email") or "").strip()
    if not to_email:
        return False, "no_customer_email"

    notes = (resolution_notes or "").strip()
    if notes:
        notes_block = (
            '<div style="margin-top:16px"><h3 style="color:#1E3A5F;font-size:14px;">'
            "Message from your agent</h3><p>"
            + html.escape(notes).replace("\n", "<br/>")
            + "</p></div>"
        )
    else:
        notes_block = (
            '<p style="margin-top:12px;color:#555;">Your conversation with our team has been closed. '
            "If you need anything further, please contact us using the details on your policy.</p>"
        )

    summary_safe = html.escape(rec.get("issue_summary") or "")
    ai_summary = (
        '<pre style="white-space:pre-wrap;font-size:13px;font-family:system-ui,sans-serif;">'
        f"{summary_safe}</pre>{notes_block}"
    )

    hist = rec.get("portal_intent")
    intent_history = [str(hist)] if hist else ["live_agent_handoff"]

    turns = len(rec.get("conversation_history") or [])
    agent = rec.get("claimed_by")

    svc = get_email_service()
    ok = svc.send_call_summary(
        to_email=to_email,
        caller_name=(rec.get("customer_name") or "").strip() or "Member",
        caller_phone=rec.get("caller_phone") or "",
        call_id=rec.get("id") or "handoff",
        intent_history=intent_history,
        conversation_turns=max(1, turns // 2),
        ai_summary=ai_summary,
        documents_referenced=[],
        agent_name=agent if agent else None,
        is_resolved=True,
        next_steps="",
        org_name=org_name,
    )
    if not ok:
        logger.warning("handoff_closure_email_failed", to=to_email, handoff_id=rec.get("id"))
        return False, "email_provider_failed_or_unconfigured"
    logger.info("handoff_closure_email_sent", to=to_email, handoff_id=rec.get("id"))
    return True, None
