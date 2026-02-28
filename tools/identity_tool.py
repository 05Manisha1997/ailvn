"""
tools/identity_tool.py
CrewAI tool – verifies a caller's identity against the Cosmos DB policyholders container.
Falls back to an in-memory store when Cosmos DB is not configured (demo mode).
"""
import os
import json
from crewai.tools import tool
from config import settings

# ── In-memory demo policyholders (used when Cosmos is not configured) ────────
DEMO_POLICYHOLDERS: dict[str, dict] = {
    "POL-001": {
        "policy_id": "POL-001",
        "name": "Joshua",
        "dob": "1985-03-14",
        "plan_name": "PremiumCare Plus",
        "plan_type": "comprehensive",
        "deductible": 500,
        "deductible_used": 200,
        "annual_limit": 100000,
        "claims_used": 12500,
    },
    "POL-002": {
        "policy_id": "POL-002",
        "name": "James George",
        "dob": "1972-07-22",
        "plan_name": "StandardCare",
        "plan_type": "standard",
        "deductible": 1000,
        "deductible_used": 800,
        "annual_limit": 50000,
        "claims_used": 7800,
    },
    "POL-003": {
        "policy_id": "POL-003",
        "name": "Jonah",
        "dob": "1990-11-05",
        "plan_name": "BasicCare",
        "plan_type": "basic",
        "deductible": 2000,
        "deductible_used": 0,
        "annual_limit": 25000,
        "claims_used": 1200,
    },
}


def _get_policyholder_from_cosmos(policy_id: str) -> dict | None:
    """Attempt Cosmos DB lookup; return None if not configured."""
    if not settings.cosmos_endpoint or not settings.cosmos_key:
        return None
    try:
        from azure.cosmos import CosmosClient
        client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
        db = client.get_database_client(settings.cosmos_database)
        container = db.get_container_client(settings.cosmos_container)
        item = container.read_item(item=policy_id, partition_key=policy_id)
        return item
    except Exception:
        return None


def _get_policyholder(policy_id: str) -> dict | None:
    cosmos_result = _get_policyholder_from_cosmos(policy_id)
    if cosmos_result:
        return cosmos_result
    return DEMO_POLICYHOLDERS.get(policy_id.upper())


@tool("Identity Verifier")
def verify_identity_tool(policy_id: str, dob: str, name: str) -> str:
    """
    Verify a caller's identity by cross-checking their policy number, date of birth,
    and name against the policyholder database.

    Args:
        policy_id: The caller's policy number (e.g. POL-001).
        dob: Date of birth in YYYY-MM-DD format.
        name: Caller's full name.
        In action, it must be registered phone number, unique member id, and dob

    Returns:
        JSON string with fields: verified (bool), policy_id, member_name, plan_name,
        plan_type, deductible_remaining, claims_remaining.
    """
    record = _get_policyholder(policy_id)

    if not record:
        return json.dumps({
            "verified": False,
            "reason": f"No policyholder found with ID {policy_id}",
        })

    # Normalise DOB comparison (strip dashes / spaces)
    stored_dob = record.get("dob", "").replace("-", "")
    provided_dob = dob.replace("-", "").replace("/", "").strip()

    # Name fuzzy match – just check first token (last name) case-insensitively
    stored_name_parts = record.get("name", "").lower().split()
    provided_name_parts = name.lower().split()
    name_match = any(p in stored_name_parts for p in provided_name_parts)

    if stored_dob != provided_dob or not name_match:
        return json.dumps({
            "verified": False,
            "reason": "Name or date of birth does not match our records.",
        })

    deductible_remaining = record["deductible"] - record.get("deductible_used", 0)
    claims_remaining = record["annual_limit"] - record.get("claims_used", 0)

    return json.dumps({
        "verified": True,
        "policy_id": record["policy_id"],
        "member_name": record["name"],
        "plan_name": record["plan_name"],
        "plan_type": record["plan_type"],
        "deductible_remaining": f"€{deductible_remaining:,.0f}",
        "claims_remaining": f"€{claims_remaining:,.0f}",
        "annual_limit": f"€{record['annual_limit']:,.0f}",
    })
