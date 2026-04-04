"""
In-memory queue of simulator / voice sessions escalated to human agents.
Portal dashboard lists pending items with full conversation context for handoff.
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

MAX_HANDOFFS = 200

_lock = threading.Lock()
_store: dict[str, dict[str, Any]] = {}
_order: list[str] = []


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_issue_summary(
    history: list[dict[str, Any]],
    portal_intent: Optional[str],
    caller_phone: str,
    simulated_member_id: str,
    verified: bool,
) -> str:
    lines = [
        "=== AILVN live agent handoff ===",
        f"When: {_utc_iso()}",
        f"Simulated / detected phone (CLID): {caller_phone or '—'}",
        f"Policyholder / member ID (dropdown): {simulated_member_id or '—'}",
        f"Identity verified (member + DOB): {'yes' if verified else 'no'}",
        f"Last portal / pipeline intent: {portal_intent or '—'}",
        "",
        "Conversation (oldest → newest):",
    ]
    for m in (history or [])[-24:]:
        role = (m.get("role") or "").strip()
        text = (m.get("content") or "").strip()
        if not text:
            continue
        who = "Member" if role == "user" else "AILVN" if role == "assistant" else role
        lines.append(f"  • {who}: {text}")
    return "\n".join(lines)


def _extract_email_from_history(history: list[dict[str, Any]]) -> str:
    """Last user message containing an email wins (e.g. typed in chat)."""
    for m in reversed(history or []):
        if (m.get("role") or "") != "user":
            continue
        mm = _EMAIL_RE.search(str(m.get("content") or ""))
        if mm:
            return mm.group(0).strip()
    return ""


def _resolve_customer_contact(
    *,
    conversation_history: list[dict[str, Any]],
    simulated_member_id: str,
    customer_email: str,
    customer_name: str,
) -> tuple[str, str]:
    email = (customer_email or "").strip()
    name = (customer_name or "").strip()
    mid = (simulated_member_id or "").strip()
    if mid and (not email or not name):
        try:
            from database.cosmos_client import db

            ph = db.get_policyholder(mid)
            if ph:
                if not email:
                    email = (ph.get("email") or "").strip()
                if not name:
                    name = (ph.get("name") or "").strip()
        except Exception:
            pass
    if not email:
        email = _extract_email_from_history(conversation_history)
    return email, name


def create_handoff(
    *,
    conversation_history: list[dict[str, Any]],
    caller_phone: str = "",
    simulated_member_id: str = "",
    verified: bool = False,
    portal_intent: Optional[str] = None,
    reason: str = "user_requested",
    source: str = "simulator",
    customer_email: str = "",
    customer_name: str = "",
) -> dict[str, Any]:
    issue_summary = _build_issue_summary(
        conversation_history,
        portal_intent,
        caller_phone,
        simulated_member_id,
        verified,
    )
    c_email, c_name = _resolve_customer_contact(
        conversation_history=conversation_history,
        simulated_member_id=simulated_member_id,
        customer_email=customer_email,
        customer_name=customer_name,
    )
    with _lock:
        hid = str(uuid.uuid4())
        rec = {
            "id": hid,
            "created_at": _utc_iso(),
            "status": "pending",
            "source": source,
            "caller_phone": caller_phone or "",
            "simulated_member_id": simulated_member_id or "",
            "verified": verified,
            "portal_intent": portal_intent,
            "reason": reason,
            "conversation_history": list(conversation_history or []),
            "issue_summary": issue_summary,
            "customer_email": c_email,
            "customer_name": c_name,
            "claimed_by": None,
            "claimed_at": None,
        }
        _store[hid] = rec
        _order.insert(0, hid)
        while len(_order) > MAX_HANDOFFS:
            old = _order.pop()
            _store.pop(old, None)
        return {**rec, "conversation_history": list(rec["conversation_history"])}


def list_handoffs(status: Optional[str] = None) -> list[dict[str, Any]]:
    with _lock:
        out: list[dict[str, Any]] = []
        for hid in _order:
            r = _store.get(hid)
            if not r:
                continue
            if status and r.get("status") != status:
                continue
            out.append(
                {
                    "id": r["id"],
                    "created_at": r["created_at"],
                    "status": r["status"],
                    "source": r.get("source"),
                    "caller_phone": r.get("caller_phone"),
                    "simulated_member_id": r.get("simulated_member_id"),
                    "verified": r.get("verified"),
                    "portal_intent": r.get("portal_intent"),
                    "reason": r.get("reason"),
                    "claimed_by": r.get("claimed_by"),
                    "claimed_at": r.get("claimed_at"),
                    "has_customer_email": bool((r.get("customer_email") or "").strip()),
                    "preview": (r.get("issue_summary") or "")[:280],
                }
            )
        return out


def get_handoff(handoff_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        r = _store.get(handoff_id)
        if not r:
            return None
        return {**r, "conversation_history": list(r.get("conversation_history") or [])}


def claim_handoff(handoff_id: str, agent_name: str) -> Optional[dict[str, Any]]:
    with _lock:
        r = _store.get(handoff_id)
        if not r or r.get("status") != "pending":
            return None
        r["status"] = "claimed"
        r["claimed_by"] = (agent_name or "Agent").strip() or "Agent"
        r["claimed_at"] = _utc_iso()
        return {**r, "conversation_history": list(r.get("conversation_history") or [])}


def resolve_handoff(handoff_id: str) -> bool:
    with _lock:
        r = _store.get(handoff_id)
        if not r:
            return False
        r["status"] = "resolved"
        r["resolved_at"] = _utc_iso()
        return True
