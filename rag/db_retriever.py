"""
rag/db_retriever.py
Route D - member database lookup for RAG slot filling.
"""
from __future__ import annotations

from database.cosmos_client import db
from rag.blob_client import fetch_members

# Small local fallback for demo/offline.
DEMO_MEMBERS: dict[str, dict] = {
    "POL-001": {
        "member_id": "POL-001",
        "name": "Sarah O'Brien",
        "plan_name": "PremiumCare Plus",
        "plan_type": "comprehensive",
        "deductible": 500,
        "deductible_used": 200,
        "annual_limit": 80000,
        "claims_used": 12500,
        "network_tier": 1,
    },
    "POL-002": {
        "member_id": "POL-002",
        "name": "James Murphy",
        "plan_name": "StandardCare",
        "plan_type": "standard",
        "deductible": 1000,
        "deductible_used": 800,
        "annual_limit": 50000,
        "claims_used": 7800,
        "network_tier": 2,
    },
}


def get_member_data(member_id: str) -> dict | None:
    """
    Read policyholder financial/plan data used by portal templates.
    Cosmos first, then demo fallback.
    """
    key = (member_id or "").strip().upper()
    if not key:
        return None

    raw = db.get_policyholder(key) if db._container is not None else None
    
    # Next, try Blob Storage
    if raw is None:
        blob_members = fetch_members()
        if blob_members:
            raw = blob_members.get(key)

    # Finally, fallback to DEMO_MEMBERS
    if raw is None:
        raw = DEMO_MEMBERS.get(key)
    
    if raw is None:
        return None

    deductible = int(raw.get("deductible", 0) or 0)
    deductible_used = int(raw.get("deductible_used", 0) or 0)
    annual_limit = int(raw.get("annual_limit", 0) or 0)
    claims_used = int(raw.get("claims_used", 0) or 0)
    deductible_remaining = max(0, deductible - deductible_used)
    claims_remaining = max(0, annual_limit - claims_used)

    return {
        "member_id": raw.get("member_id") or raw.get("mem_id") or raw.get("id") or key,
        "name": raw.get("name", ""),
        "plan_name": raw.get("plan_name", ""),
        "plan_type": raw.get("plan_type", ""),
        "network_tier": int(raw.get("network_tier", 0) or 0),
        "deductible_total": f"EUR {deductible:,.0f}",
        "deductible_remaining": f"EUR {deductible_remaining:,.0f}",
        "deductible_met": deductible_remaining <= 0,
        "annual_limit": f"EUR {annual_limit:,.0f}",
        "claims_used": f"EUR {claims_used:,.0f}",
        "claims_remaining": f"EUR {claims_remaining:,.0f}",
        "benefit_summary": raw.get("benefit_summary", {}),
    }

