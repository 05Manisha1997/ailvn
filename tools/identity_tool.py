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
    "1": {
        "mem_id": "1",
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
    },
    "POL-001": {
        "mem_id": "POL-001",
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
    },
}


def _get_policyholder_from_cosmos(member_id: str) -> dict | None:
    """Attempt Cosmos DB lookup; return None if not configured."""
    if not settings.cosmos_endpoint or not settings.cosmos_key:
        return None
    try:
        from azure.cosmos import CosmosClient
        client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
        db = client.get_database_client(settings.cosmos_database)
        container = db.get_container_client(settings.cosmos_container)
        item = container.read_item(item=member_id, partition_key=member_id)
        return item
    except Exception:
        return None


def _get_policyholder(member_id: str) -> dict | None:
    cosmos_result = _get_policyholder_from_cosmos(member_id)
    if cosmos_result:
        return cosmos_result
    return DEMO_POLICYHOLDERS.get(member_id.upper())


def _verify_identity_logic(member_id: str, dob: str, email: str, phone: str) -> dict:
    """Core verification logic returning a dictionary."""
    record = _get_policyholder(member_id)

    if not record:
        return {
            "verified": False,
            "reason": f"No member found with ID {member_id}",
        }

    # Normalise DOB comparison (strip dashes / spaces / slashes)
    stored_dob = record.get("dob", "").replace("-", "").replace(" ", "").replace("/", "")
    provided_dob = dob.replace("-", "").replace("/", "").replace(" ", "").strip()

    # Normalise Email comparison
    stored_email = record.get("email", "").lower().strip()
    provided_email = email.lower().strip()

    # Normalise Phone comparison (strip everything but digits and +)
    def clean_phone(p):
        return "".join(c for c in p if c.isdigit() or c == "+")

    stored_phone = clean_phone(record.get("phone", ""))
    provided_phone = clean_phone(phone)

    if stored_dob != provided_dob or stored_email != provided_email or stored_phone != provided_phone:
        return {
            "verified": False,
            "reason": "Provided details do not match our records.",
        }

    deductible_remaining = record["deductible"] - record.get("deductible_used", 0)
    claims_remaining = record["annual_limit"] - record.get("claims_used", 0)

    return {
        "verified": True,
        "policy_id": record["mem_id"],
        "member_name": record["name"],
        "plan_name": record["plan_name"],
        "plan_type": record["plan_type"],
        "deductible_remaining": f"€{deductible_remaining:,.0f}",
        "claims_remaining": f"€{claims_remaining:,.0f}",
        "annual_limit": f"€{record['annual_limit']:,.0f}",
    }


@tool("Identity Verifier")
def verify_identity_tool(member_id: str, dob: str, email: str, phone: str) -> str:
    """
    Verify a caller's identity by cross-checking their member ID, date of birth,
    email, and phone number against the customer database.

    Args:
        member_id: Alphanumeric member ID.
        dob: Date of birth in YYYY-MM-DD format.
        email: Caller's registered email address.
        phone: Caller's phone number (extracted automatically).

    Returns:
        JSON string with fields: verified (bool), policy_id, member_name, plan_name,
        plan_type, deductible_remaining, claims_remaining.
    """
    result = _verify_identity_logic(member_id, dob, email, phone)
    return json.dumps(result)
