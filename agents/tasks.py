"""
agents/tasks.py
Assembles and runs the 4-task CrewAI crew for a single caller turn.
Uses factory functions from crew_insurance.py so no LLM is required at import time.
Also includes a demo/simulation mode that avoids all API calls for hackathon demos.
"""
from __future__ import annotations

import re
import requests
from dataclasses import dataclass
from typing import Optional

from config import settings
from ai_service import classify_intent_with_retry, map_llm_intent_to_insurance_template
from templates.response_templates import TEMPLATES, fill_template
from tools.identity_tool import _verify_identity_logic
from rag.db_retriever import get_member_data
from rag.policy_retriever import retrieve_policy_clauses
from portal.portal_render import PortalRenderResult, render_portal_response


@dataclass
class CrewTurnResult:
    """One simulator / voice turn: spoken text plus portal metadata for TTS routing."""

    response_text: str
    portal_render: Optional[PortalRenderResult] = None


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
    if not member_id or member_id.lower() in ["unknown", "null", "__sim__", "sim"]:
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


def _is_sim_caller_id(caller_id: str) -> bool:
    return (caller_id or "").strip().upper() in ("", "__SIM__", "UNKNOWN", "SIM", "DEMO-001")


def _speech_words_to_digits(text: str) -> str:
    """Convert common spoken number words to digits for robust STT parsing."""
    if not text:
        return ""
    mapping = {
        "zero": "0",
        "oh": "0",
        "o": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
    }
    out = text
    for word, digit in mapping.items():
        out = re.sub(rf"\b{word}\b", digit, out, flags=re.IGNORECASE)
    return out


def _canonical_member_id_from_text(text: str) -> str:
    """
    Accept common spoken/typed variants:
    - POL-001
    - pol 001
    - p o l 001
    - p-o-l/001
    and normalize to POL-001.
    """
    if not text:
        return "unknown"
    # Spelled-out letters P-O-L must run before _speech_words_to_digits, which maps
    # standalone "o" -> "0" and would break "p o l" into P0L (not POL).
    t = re.sub(r"\bP\s*[-]?\s*O\s*[-]?\s*L\b", "POL", text, flags=re.IGNORECASE)
    upper = _speech_words_to_digits(t).upper()
    # Keep only alnum so "p o l-001" becomes "POL001".
    compact = re.sub(r"[^A-Z0-9]", "", upper)
    # Capture only the first 1-3 digits immediately following POL.
    # Avoid accidental capture from trailing DOB digits in the same utterance.
    m = re.search(r"POL(\d{1,3})", compact)
    if not m:
        return "unknown"
    return f"POL-{int(m.group(1)):03d}"


def _canonical_dob_from_text(text: str) -> str:
    """
    Parse DOB from tolerant variants and normalize to YYYY-MM-DD:
    - 1985-03-14, 1985/03/14, 1985 03 14
    - spoken chunky digits: "1985 03 14"
    - year + glued month/day: "1985 0314"
    """
    if not text:
        return ""
    prepared = _speech_words_to_digits(text)
    # 1) Standard separated date forms.
    m = re.search(r"\b(19|20)\d{2}[-/\s](0?[1-9]|1[0-2])[-/\s](0?[1-9]|[12]\d|3[01])\b", prepared)
    if m:
        year = m.group(0)[0:4]
        nums = re.findall(r"\d+", m.group(0))
        if len(nums) >= 3:
            return f"{int(nums[0]):04d}-{int(nums[1]):02d}-{int(nums[2]):02d}"

    # 1b) Year, space, then 4-digit MMDD (common typing/STT: "1985 0314").
    m15 = re.search(
        r"\b((?:19|20)\d{2})\s+(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b",
        prepared,
    )
    if m15:
        return (
            f"{int(m15.group(1)):04d}-"
            f"{int(m15.group(2)):02d}-"
            f"{int(m15.group(3)):02d}"
        )

    # 2) Fully compact numeric stream (e.g. from noisy STT around symbols/spaces).
    digits = re.sub(r"\D", "", prepared)
    m2 = re.search(r"(19|20)\d{2}(0[1-9]|1[0-2])([0-2]\d|3[01])", digits)
    if m2:
        ymd = m2.group(0)
        return f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"
    return ""


def _extract_profile_fields(caller_input: str, conversation_history: list, caller_id: str) -> tuple[str, str, str]:
    source_text = " ".join([x.get("content", "") for x in conversation_history if x.get("role") == "user"])
    source_text = f"{source_text} {caller_input}"

    if _is_sim_caller_id(caller_id):
        member_id = _canonical_member_id_from_text(source_text)
    else:
        member_id = (caller_id or "").strip() or "unknown"

    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", source_text)
    email = email_match.group(0) if email_match else ""

    dob = _canonical_dob_from_text(source_text)
    if not dob:
        # e.g. March 14 1985 / 14 March 1985
        if re.search(r"march\s+14", source_text.lower()) and "1985" in source_text:
            dob = "1985-03-14"
        elif re.search(r"january\s+15", source_text.lower()) and "1990" in source_text:
            dob = "1990-01-15"

    return member_id, email, dob


def _is_identity_only_utterance(text: str) -> bool:
    """
    True when caller input looks like verification details only
    (member id / dob / email / phone) and not an actual insurance question.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    has_member = bool(re.search(r"\bpol-\d{3}\b", t))
    has_dob = bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", t))
    has_email = bool(re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", t))
    has_phone = bool(re.search(r"(\+?\d[\d\-\s]{7,}\d)", t))
    if not (has_member or has_dob or has_email or has_phone):
        return False
    # If the user asks a real benefits question in same message, do not treat as identity-only.
    question_markers = (
        "covered",
        "coverage",
        "claim",
        "deductible",
        "benefit",
        "network",
        "hospital",
        "surgery",
        "mri",
        "copay",
        "co-pay",
        "policy",
    )
    return not any(w in t for w in question_markers)


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

    # Primary in-process classifier (OpenAI/Azure/Ollama via ai_service.py).
    # Falls through to rule-based heuristics if the model is unavailable.
    try:
        llm_label = classify_intent_with_retry(caller_input or "")
        mapped_intent = map_llm_intent_to_insurance_template(llm_label)
        if mapped_intent:
            return {"intent": mapped_intent, "intent_label": llm_label, "source": "llm"}
    except Exception:
        pass

    q = caller_input.lower()
    sq = q.strip()

    # ── Scripted CSR scenarios (Cosmos templates: csr_*) — specific phrases first ──
    if "1095" in q or ("tax" in q and "coverage" in q and ("form" in q or "prove" in q)):
        intent = "csr_tax_enrollment_docs"
    elif ("denied" in q or "denial" in q) and (
        "appeal" in q or "medically necessary" in q or "brace" in q or "fight" in q
    ):
        intent = "csr_appeal_denial"
    elif ("married" in q or "husband" in q or "wife" in q) and (
        "primary" in q or "secondary" in q or "which insurance" in q or "two" in q and "plan" in q
    ):
        intent = "csr_coordination_of_benefits"
    elif ("dermatologist" in q or "pediatric" in q) and (
        "zip" in q or "mile" in q or "60601" in q or "provider" in q or "taking new" in q
    ):
        intent = "csr_network_search"
    elif ("physical therapy" in q or "physiotherapy" in q) and (
        "claim" in q or "reimbursement" in q or "week" in q or "haven't" in q or "havent" in q
    ):
        intent = "csr_claims_status_inquiry"
    elif "mri" in q or "downtown imaging" in q or ("imaging" in q and "referral" in q):
        intent = "csr_coverage_verification"
    elif ("prevent" in q and "care" in q) or "preventative" in q or "preventive" in q:
        if "50" in q or "co-pay" in q or "copay" in q or "owe" in q or "bill" in q:
            intent = "csr_benefits_explanation_oop"
    elif "zyloprim" in q or ("formulary" in q and ("drug" in q or "tier" in q or "gout" in q)):
        intent = "csr_prescription_formulary"
    elif "moved" in q and ("address" in q or "mailing" in q or "id card" in q):
        intent = "csr_update_personal_info"
    elif "deductible" in q and (
        "how much more" in q
        or "remaining" in q
        or "hit my" in q
        or "before insurance" in q
        or "accumulator" in q
    ):
        intent = "csr_high_deductible_accumulator"
    # ── Small talk (short utterances) ──
    elif len(sq) <= 48 and (
        sq in ("hi", "hello", "hey", "good morning", "good afternoon", "good evening")
        or sq.startswith(("hi ", "hello ", "hey "))
    ):
        intent = "smalltalk_greeting"
    elif "how are you" in q or "how's it going" in q or "how is it going" in q:
        intent = "smalltalk_how_are_you"
    elif len(sq) < 100 and (
        sq.startswith("thank")
        or " thank you" in q
        or sq == "thanks"
        or sq.startswith("thanks ")
    ):
        intent = "smalltalk_thanks"
    elif any(x in sq for x in ("goodbye", "bye", "that's all", "that is all", "have a good day")):
        intent = "smalltalk_goodbye"
    elif "weather" in q and any(x in q for x in ("nice", "cold", "hot", "rain", "sunny", "bad")):
        intent = "smalltalk_weather"
    elif any(x in q for x in ("hold on", "one moment", "give me a second", "wait a moment")):
        intent = "smalltalk_wait"
    # ── Legacy RAG-friendly intents ──
    elif "hospital" in q and ("covered" in q or "network" in q):
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
    """
    Merge Route D member facts + Route C policy clauses into portal slot values.
    """
    member = get_member_data(policy_id) or {}
    policy = retrieve_policy_clauses(query=query, policy_id=policy_id, intent=intent, top_k=3)
    clauses_list = policy.get("clauses", [])
    clauses = " ".join(clauses_list)

    values = {
        "hospital_name": "the requested hospital",
        "coverage_pct": "80%",
        "max_limit": "EUR 80,000",
        "nearest_network_hospital": "Dublin City Hospital",
        "treatment_type": "this treatment",
        "limit": "EUR 20,000",
        "plan_name": member.get("plan_name", "your current plan"),
        "deductible_amount": member.get("deductible_total", "EUR 500"),
        "deductible_remaining": member.get("deductible_remaining", "EUR 300"),
        "remaining_limit": member.get("claims_remaining", "EUR 87,500"),
        "benefit_category": "annual",
        "claim_id": "CLM-1001",
        "claim_status": "in review",
        "last_update": "today",
        "required_documents": "invoice, discharge summary, and doctor referral",
        "processing_time": "5-7 business days",
        "expected_date": "within one week",
        "plan_type": member.get("plan_type", ""),
        "rag_source": policy.get("source", "demo_kb"),
    }

    percent = re.search(r"(\d{1,3}%)", clauses)
    amount = re.search(r"(€\s?[\d,]+|EUR\s?[\d,]+)", clauses, re.IGNORECASE)
    if percent:
        values["coverage_pct"] = percent.group(1)
    if amount:
        values["max_limit"] = amount.group(1).replace(" ", "")
    if "dental" in query.lower():
        values["treatment_type"] = "Dental treatment"
        values["limit"] = "EUR 1,500"
    if "mental" in query.lower():
        values["treatment_type"] = "Mental health treatment"
        values["limit"] = "EUR 15,000"
    if "surg" in query.lower():
        values["treatment_type"] = "Surgical procedures"
    if "physio" in query.lower() or "physical therapy" in query.lower():
        values["treatment_type"] = "Physiotherapy"

    return values


# ── Full CrewAI pipeline ──────────────────────────────────────────────────────

def build_crew_for_query(
    caller_input: str,
    caller_id: str,
    caller_phone: str,
    conversation_history: list,
    demo_mode: bool = False,
) -> CrewTurnResult:
    """
    Run verification → intent → RAG value extraction → portal render (Cosmos templates).

    Returns:
        CrewTurnResult with ``response_text`` for TTS/summary and optional ``portal_render`` metadata.
    """
    if demo_mode:
        return CrewTurnResult(response_text=_demo_response(caller_input, caller_id, caller_phone))

    member_id, email, dob = _extract_profile_fields(caller_input, conversation_history, caller_id)
    strict_sim_verify = _is_sim_caller_id(caller_id)
    verification = _verify_identity_logic(
        member_id=member_id,
        dob=dob,
        email=email,
        phone=caller_phone,
        require_member_and_dob=strict_sim_verify,
    )
    if not verification.get("verified"):
        # Call simulator: phone comes from selected policyholder; user must type member ID + DOB.
        if _is_sim_caller_id(caller_id) and not (caller_phone or "").strip():
            return CrewTurnResult(
                response_text=(
                    "Select a simulated caller from the dropdown so we can detect your phone number. "
                    "Then provide your member ID and date of birth in YYYY-MM-DD format."
                )
            )
        if _is_sim_caller_id(caller_id) and (caller_phone or "").strip():
            need: list[str] = []
            if member_id == "unknown":
                need.append("member ID (for example POL-001)")
            if not dob:
                need.append("date of birth in YYYY-MM-DD format")
            if need:
                return CrewTurnResult(
                    response_text=fill_template(
                        "identity_prompt",
                        missing_field=" and ".join(need),
                    )
                )
            return CrewTurnResult(response_text=fill_template("identity_failed"))
        if not email or not dob:
            missing = []
            if not email:
                missing.append("email")
            if not dob:
                missing.append("date of birth")
            return CrewTurnResult(
                response_text=fill_template("identity_prompt", missing_field=" and ".join(missing))
            )
        return CrewTurnResult(response_text=fill_template("identity_failed"))

    if _is_identity_only_utterance(caller_input):
        name = verification.get("member_name", "there")
        return CrewTurnResult(
            response_text=(
                f"Thanks {name}, your identity is verified. "
                "How can I help with your policy today?"
            )
        )

    intent_payload = _intent_from_service(caller_input, verification.get("policy_id", caller_id), conversation_history)
    intent = intent_payload.get("intent", "fallback_human")
    rag_values = _extract_rag_values(caller_input, verification.get("policy_id", caller_id), intent)
    rag_values.setdefault("plan_name", verification.get("plan_name", "your current plan"))
    rag_values.setdefault("deductible_remaining", verification.get("deductible_remaining", "€0"))
    rag_values.setdefault("remaining_limit", verification.get("claims_remaining", "€0"))

    rendered = render_portal_response(intent, rag_values)
    return CrewTurnResult(response_text=rendered.rendered_text, portal_render=rendered)
