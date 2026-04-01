"""
tools/identity_tool.py
CrewAI tool – verifies a caller's identity against the Cosmos DB policyholders container.
Falls back to an in-memory store when Cosmos DB is not configured (demo mode).
"""
from __future__ import annotations

import json

try:
    from crewai.tools import tool
except Exception:
    # Allow non-Crew runtime imports (e.g., API-only mode)
    def tool(_name):
        def _decorator(func):
            return func

        return _decorator

from config import settings

# ── In-memory demo policyholders (used when Cosmos is not configured) ────────
DEMO_POLICYHOLDERS: dict[str, dict] = {
    "1": {
        "mem_id": "1",
        "member_id": "1",
        "policy_number": "1",
        "name": "John Smith",
        "email": "john.smith1@email.com",
        "dob": "1990-01-15",
        "phone": "+353871234501",
        "plan_name": "PremiumCare Plus",
        "plan_type": "comprehensive",
        "deductible": 500,
        "deductible_used": 200,
        "annual_limit": 100000,
        "claims_used": 12500,
        "security_question_1": "What city were you born in?",
        "security_answer_1": "Dublin",
        "security_question_2": "What is your mother's maiden name?",
        "security_answer_2": "Murphy",
    },
    "POL-001": {
        "mem_id": "POL-001",
        "member_id": "POL-001",
        "policy_number": "POL-001",
        "name": "Joshua",
        "email": "joshua@email.com",
        "dob": "1985-03-14",
        "phone": "+353-87-111-2233",
        "plan_name": "PremiumCare Plus",
        "plan_type": "comprehensive",
        "deductible": 500,
        "deductible_used": 200,
        "annual_limit": 100000,
        "claims_used": 12500,
        "security_question_1": "What city were you born in?",
        "security_answer_1": "Cork",
        "security_question_2": "What is your mother's maiden name?",
        "security_answer_2": "Walsh",
    },
}

_DEMO_CACHE: dict[str, dict] | None = None


def _demo_policyholders() -> dict[str, dict]:
    """
    Demo fallback members when Cosmos is unavailable.
    Keep POL-001/Joshua override, but include synthetic POL-002.. for simulator parity.
    """
    global _DEMO_CACHE
    if _DEMO_CACHE is not None:
        return _DEMO_CACHE
    merged = dict(DEMO_POLICYHOLDERS)
    try:
        from database.seed_data import build_synthetic_policyholders

        for row in build_synthetic_policyholders(20):
            key = (row.get("member_id") or row.get("mem_id") or row.get("id") or "").upper()
            if not key:
                continue
            # Preserve explicit hardcoded overrides (e.g., POL-001 Joshua).
            merged.setdefault(key, row)
    except Exception:
        pass
    _DEMO_CACHE = merged
    return merged


def _record_member_key(record: dict) -> str:
    # Prefer canonical member_id (POL-xxx) over legacy mem_id.
    return (record.get("member_id") or record.get("mem_id") or "").strip().upper()


def _norm_member_token(val: str) -> str:
    """Normalize member identifier for tolerant equality checks."""
    return "".join(ch for ch in (val or "").upper() if ch.isalnum())


def _get_policyholder(member_id: str) -> dict | None:
    mid = member_id.strip().upper() if member_id else ""
    if not mid or mid in ("UNKNOWN", "NULL"):
        return None
    try:
        from database.cosmos_client import db

        cosmos_result = db.get_policyholder(mid)
        if cosmos_result:
            return cosmos_result
    except Exception:
        pass
    return _demo_policyholders().get(mid)


def _normalize_dob(dob: str) -> str:
    return dob.replace("-", "").replace("/", "").replace(" ", "").strip()


def _dob_for_cosmos_query(dob: str) -> str:
    """Prefer YYYY-MM-DD for Cosmos equality on c.dob."""
    raw = dob.strip()
    if "/" in raw and len(raw.split("/")) == 3:
        a, b, c = raw.split("/")
        if len(c) == 4:
            return f"{c}-{a.zfill(2)}-{b.zfill(2)}"
        if len(a) == 4:
            return f"{a}-{b.zfill(2)}-{c.zfill(2)}"
    return raw


def _find_by_email_dob(email: str, dob: str) -> dict | None:
    provided_email = email.lower().strip()
    if not provided_email or not dob:
        return None
    dob_query = _dob_for_cosmos_query(dob)
    try:
        from database.cosmos_client import db

        hit = db.find_by_email_and_dob(provided_email, dob_query)
        if hit:
            return hit
    except Exception:
        pass
    provided_norm = _normalize_dob(dob)
    for v in _demo_policyholders().values():
        stored_email = v.get("email", "").lower().strip()
        stored_norm = _normalize_dob(v.get("dob", ""))
        if stored_email == provided_email and stored_norm == provided_norm:
            return v
    return None


def _norm_sec(s: str) -> str:
    return " ".join(s.lower().strip().split())


def _verify_identity_logic(
    member_id: str,
    dob: str,
    email: str,
    phone: str,
    security_answer_1: str = "",
    security_answer_2: str = "",
) -> dict:
    """Core verification logic returning a dictionary."""
    record = None

    if member_id and member_id.lower() not in ("", "unknown", "null"):
        record = _get_policyholder(member_id)

    if not record and email and dob:
        record = _find_by_email_dob(email, dob)

    if not record:
        return {
            "verified": False,
            "reason": f"No member found with ID {member_id} or provided details.",
        }

    stored_dob = _normalize_dob(record.get("dob", ""))
    provided_dob = _normalize_dob(dob)

    stored_email = record.get("email", "").lower().strip()
    provided_email = email.lower().strip()

    def clean_phone(p: str) -> str:
        return "".join(c for c in p if c.isdigit() or c == "+")

    stored_phone = clean_phone(record.get("phone", ""))
    provided_phone = clean_phone(phone)

    mem_key = _record_member_key(record)
    mid_in = member_id.strip().upper() if member_id else ""
    in_norm = _norm_member_token(mid_in)
    candidate_ids = {
        _norm_member_token(str(record.get("member_id", ""))),
        _norm_member_token(str(record.get("mem_id", ""))),
        _norm_member_token(str(record.get("policy_number", ""))),
        _norm_member_token(str(record.get("id", ""))),
    }
    candidate_ids.discard("")
    id_match = bool(
        mid_in
        and mid_in not in ("UNKNOWN", "NULL")
        and in_norm
        and in_norm in candidate_ids
    )

    email_dob_match = stored_email == provided_email and stored_dob == provided_dob
    id_dob_match = id_match and bool(provided_dob) and stored_dob == provided_dob
    phone_id_match = id_match and stored_phone == provided_phone

    security_ok = False
    if security_answer_1 and security_answer_2:
        security_ok = _norm_sec(security_answer_1) == _norm_sec(
            record.get("security_answer_1", "")
        ) and _norm_sec(security_answer_2) == _norm_sec(record.get("security_answer_2", ""))

    if email_dob_match or id_dob_match or phone_id_match or (security_ok and id_match):
        pass
    else:
        return {
            "verified": False,
            "reason": "Provided details do not match our records.",
        }

    deductible = int(record.get("deductible", 0) or 0)
    deductible_used = int(record.get("deductible_used", 0) or 0)
    annual_limit = int(record.get("annual_limit", 0) or 0)
    claims_used = int(record.get("claims_used", 0) or 0)

    deductible_remaining = max(0, deductible - deductible_used)
    claims_remaining = max(0, annual_limit - claims_used)

    return {
        "verified": True,
        "policy_id": mem_key or record.get("policy_number", ""),
        "member_name": record.get("name", ""),
        "plan_name": record.get("plan_name", ""),
        "plan_type": record.get("plan_type", ""),
        "deductible_remaining": f"€{deductible_remaining:,.0f}",
        "claims_remaining": f"€{claims_remaining:,.0f}",
        "annual_limit": f"€{annual_limit:,.0f}",
    }


@tool("Identity Verifier")
def verify_identity_tool(
    member_id: str,
    dob: str,
    email: str,
    phone: str,
    security_answer_1: str = "",
    security_answer_2: str = "",
) -> str:
    """
    Verify a caller's identity by cross-checking their member ID, date of birth,
    email, and phone number against the customer database. Optionally verify two
    security answers when the agent collects them.

    Args:
        member_id: Alphanumeric member ID (e.g. POL-001).
        dob: Date of birth in YYYY-MM-DD format.
        email: Caller's registered email address.
        phone: Caller's phone number (extracted automatically).
        security_answer_1: Optional answer to security question 1.
        security_answer_2: Optional answer to security question 2.

    Returns:
        JSON string with fields: verified (bool), policy_id, member_name, plan_name,
        plan_type, deductible_remaining, claims_remaining.
    """
    result = _verify_identity_logic(
        member_id, dob, email, phone, security_answer_1, security_answer_2
    )
    return json.dumps(result)
