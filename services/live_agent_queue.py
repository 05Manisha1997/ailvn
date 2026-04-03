"""
In-memory queue of simulator / voice sessions escalated to human agents.
Portal dashboard lists pending items with full conversation context for handoff.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

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


def create_handoff(
    *,
    conversation_history: list[dict[str, Any]],
    caller_phone: str = "",
    simulated_member_id: str = "",
    verified: bool = False,
    portal_intent: Optional[str] = None,
    reason: str = "user_requested",
    source: str = "simulator",
) -> dict[str, Any]:
    issue_summary = _build_issue_summary(
        conversation_history,
        portal_intent,
        caller_phone,
        simulated_member_id,
        verified,
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
