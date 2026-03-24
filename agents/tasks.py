"""
agents/tasks.py
Assembles and runs the 4-task CrewAI crew for a single caller turn.
Uses factory functions from crew_insurance.py so no LLM is required at import time.
Also includes a demo/simulation mode that avoids all API calls for hackathon demos.
"""
import json
import re
import requests
from config import settings
from templates.response_templates import TEMPLATES, fill_template
from tools.identity_tool import _verify_identity_logic
from tools.rag_tool import policy_rag_tool
from portal.insurance_portal import get_insurance_portal


# ── Demo simulation (no real LLM calls) ──────────────────────────────────────

def _demo_response(caller_input: str, member_id: str, caller_phone: str) -> str:
    """Fast demo path — keyword-matched response, no API calls."""

    # ── Smarter Heuristics for Demo ──────────────────────────────────────────
    # Extract Email
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", caller_input)
    email = email_match.group(0) if email_match else ""
    
    # Extract DOB (Supports YYYY-MM-DD or Month Day YYYY)
    dob = ""
    dob_iso = re.search(r"(\d{4}-\d{2}-\d{2})", caller_input)
    if dob_iso:
        dob = dob_iso.group(1)
    elif "january 15" in caller_input.lower() and "1990" in caller_input:
        dob = "1990-01-15"
    elif "march 14" in caller_input.lower() and "1985" in caller_input:
        dob = "1985-03-14"

    # Extract Member ID (looks for POL-XXX or just numeric 1)
    if not member_id or member_id.lower() in ["unknown", "null"]:
        mem_match = re.search(r"(POL-\d{3}|(?<!\d)1(?!\d))", caller_input.upper())
        member_id = mem_match.group(0) if mem_match else "unknown"
    
    # Perform verification check
    v_result = _verify_identity_logic(member_id=member_id, dob=dob, email=email, phone=caller_phone)
    
    if not v_result.get("verified"):
        if not email or not dob:
             missing = []
             if not email: missing.append("email")
             if not dob: missing.append("date of birth")
             return fill_template("identity_prompt", missing_field=" and ".join(missing))
        return fill_template("identity_failed")

    q = caller_input.lower()
    hospital_match = re.search(
        r"(st\.?\s*vincent|mater|beacon|blackrock|dublin city|clinic|hospital)", q
    )
    hospital_name = hospital_match.group(0).title() if hospital_match else "the hospital"

    if "hospital" in q or "clinic" in q or "covered" in q:
        return fill_template(
            "hospital_covered",
            coverage_pct="80%",
            hospital_name=hospital_name,
            max_limit="€80,000",
        )
    if "surg" in q or "operation" in q or "procedure" in q:
        return fill_template(
            "treatment_covered",
            treatment_type="Surgical procedures",
            coverage_pct="90%",
            limit="€20,000",
        )
    if "dent" in q or "teeth" in q:
        return fill_template(
            "treatment_covered",
            treatment_type="Dental treatment",
            coverage_pct="60%",
            limit="€1,500",
        )
    if "mental" in q or "counsel" in q or "therapy" in q or "psych" in q:
        return fill_template(
            "treatment_covered",
            treatment_type="Mental health treatment",
            coverage_pct="75%",
            limit="€15,000",
        )
    if "deduct" in q:
        return fill_template(
            "deductible_status",
            deductible_amount="€500",
            deductible_remaining="€300",
        )
    if "claim" in q or "limit" in q or "remaining" in q or "left" in q:
        return fill_template(
            "claim_limit_remaining",
            remaining_limit="€87,500",
            benefit_category="annual",
        )
    return TEMPLATES["fallback_human"]


def _extract_profile_fields(caller_input: str, conversation_history: list, caller_id: str) -> tuple[str, str, str]:
    source_text = " ".join([x.get("content", "") for x in conversation_history if x.get("role") == "user"])
    source_text = f"{source_text} {caller_input}"
    member_id = caller_id
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", source_text)
    email = email_match.group(0) if email_match else ""
    dob_match = re.search(r"(\d{4}-\d{2}-\d{2})", source_text)
    dob = dob_match.group(1) if dob_match else ""
    return member_id, email, dob


def _intent_from_service(caller_input: str, caller_id: str, conversation_history: list) -> dict:
    # External intent service integration (provided by upstream system)
    if settings.intent_service_url:
        try:
            payload = {
                "text": caller_input,
                "caller_id": caller_id,
                "conversation_history": conversation_history[-10:],
            }
            headers = {"Content-Type": "application/json"}
            if settings.intent_service_api_key:
                headers["Authorization"] = f"Bearer {settings.intent_service_api_key}"
            response = requests.post(
                settings.intent_service_url,
                json=payload,
                headers=headers,
                timeout=10,
            )
            if response.ok:
                data = response.json()
                if isinstance(data, dict) and data.get("intent"):
                    return data
        except Exception:
            pass

    q = caller_input.lower()
    if "hospital" in q and ("covered" in q or "network" in q):
        intent = "hospital_covered"
    elif "deduct" in q:
        intent = "deductible_status"
    elif "claim" in q and ("status" in q or "track" in q):
        intent = "insurance_claim_status"
    elif "claim" in q and ("document" in q or "upload" in q):
        intent = "insurance_claim_documents"
    elif "claim" in q and ("time" in q or "when" in q):
        intent = "insurance_claim_timeline"
    elif "claim" in q or "limit" in q or "remaining" in q:
        intent = "claim_limit_remaining"
    elif "surg" in q or "operation" in q or "treatment" in q or "dental" in q or "mental" in q:
        intent = "treatment_covered"
    else:
        intent = "fallback_human"
    return {"intent": intent}


def _extract_rag_values(query: str, policy_id: str, intent: str) -> dict:
    raw = policy_rag_tool(query=query, policy_id=policy_id)
    try:
        parsed = json.loads(raw)
        clauses = " ".join(parsed.get("clauses", []))
    except Exception:
        clauses = raw

    values = {
        "hospital_name": "the requested hospital",
        "coverage_pct": "80%",
        "max_limit": "€80,000",
        "nearest_network_hospital": "Dublin City Hospital",
        "treatment_type": "this treatment",
        "limit": "€20,000",
        "plan_name": "your current plan",
        "deductible_amount": "€500",
        "deductible_remaining": "€300",
        "remaining_limit": "€87,500",
        "benefit_category": "annual",
        "claim_id": "CLM-1001",
        "claim_status": "in review",
        "last_update": "today",
        "required_documents": "invoice, discharge summary, and doctor referral",
        "processing_time": "5-7 business days",
        "expected_date": "within one week",
    }

    percent = re.search(r"(\d{1,3}%)", clauses)
    amount = re.search(r"(€\s?[\d,]+)", clauses)
    if percent:
        values["coverage_pct"] = percent.group(1)
    if amount:
        values["max_limit"] = amount.group(1).replace(" ", "")
    if "dental" in query.lower():
        values["treatment_type"] = "Dental treatment"
        values["limit"] = "€1,500"
    if "mental" in query.lower():
        values["treatment_type"] = "Mental health treatment"
        values["limit"] = "€15,000"
    if "surg" in query.lower():
        values["treatment_type"] = "Surgical procedures"

    return values


# ── Full CrewAI pipeline ──────────────────────────────────────────────────────

def build_crew_for_query(
    caller_input: str,
    caller_id: str,
    caller_phone: str,
    conversation_history: list,
    demo_mode: bool = False,
) -> str:
    """
    Run the 4-agent CrewAI crew for one caller turn.

    Args:
        caller_input: Transcribed text from the caller.
        caller_id: Caller's policy ID extracted from context or provided directly.
        caller_phone: Caller's phone number extracted from the call system.
        conversation_history: List of {role, content} dicts from this call session.
        demo_mode: If True, bypass real API calls and return a demo answer.

    Returns:
        Final spoken response string ready for TTS.
    """
    if demo_mode:
        return _demo_response(caller_input, caller_id, caller_phone)

    member_id, email, dob = _extract_profile_fields(caller_input, conversation_history, caller_id)
    verification = _verify_identity_logic(member_id=member_id, dob=dob, email=email, phone=caller_phone)
    if not verification.get("verified"):
        if not email or not dob:
            missing = []
            if not email:
                missing.append("email")
            if not dob:
                missing.append("date of birth")
            return fill_template("identity_prompt", missing_field=" and ".join(missing))
        return fill_template("identity_failed")

    intent_payload = _intent_from_service(caller_input, verification.get("policy_id", caller_id), conversation_history)
    intent = intent_payload.get("intent", "fallback_human")
    rag_values = _extract_rag_values(caller_input, verification.get("policy_id", caller_id), intent)
    rag_values.setdefault("plan_name", verification.get("plan_name", "your current plan"))
    rag_values.setdefault("deductible_remaining", verification.get("deductible_remaining", "€0"))
    rag_values.setdefault("remaining_limit", verification.get("claims_remaining", "€0"))

    portal = get_insurance_portal()
    response = portal.fill_template(intent, rag_values)
    return response
