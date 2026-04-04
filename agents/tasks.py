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
    member_data: Optional[dict] = None


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
    """Convert common spoken words to digits for robust STT parsing."""
    if not text:
        return ""
    # Removed "o" and "oh" from here to prevent P-O-L -> P-0-L conversion
    mapping = {
        "zero": "0", "naught": "0",
        "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8",
        "nine": "9", "ten": "10"
    }
    # Handle "double" and "triple"
    text = re.sub(r"double\s+(\w+)", r"\1 \1", text, flags=re.IGNORECASE)
    text = re.sub(r"triple\s+(\w+)", r"\1 \1 \1", text, flags=re.IGNORECASE)

    out = text
    for word, digit in mapping.items():
        out = re.sub(rf"\b{word}\b", digit, out, flags=re.IGNORECASE)
    return out


def _canonical_member_id_from_text(text: str) -> str:
    """
    Tolerant parsing for Member ID:
    - POL-001, P O L 001, Paul 001, Policy 1
    """
    if not text:
        return "unknown"
    
    # 1. Fix phonetic variants of "POL" before digit conversion
    # Handles "P O L", "P 0 L", "P.O.L", "Paul", etc.
    prepared = re.sub(r"\b(p\s*[o0]\s*l|paul|pole|bowl|pull|poll|role|pol)\b", "POL", text, flags=re.IGNORECASE)
    prepared = _speech_words_to_digits(prepared).upper()
    
    # 2. Extract digits following "POL" or keywords
    compact = re.sub(r"[^A-Z0-9]", "", prepared)
    m = re.search(r"POL(\d{1,3})", compact)
    if m:
        return f"POL-{int(m.group(1)):03d}"
    
    # Fallback to general digit extraction near keywords
    m2 = re.search(r"(?:policy|member|number|is|id|i d)\D*(\d{1,3})\b", prepared.lower())
    if m2:
        return f"POL-{int(m2.group(1)):03d}"

    #Standalone 3-digit number
    m3 = re.search(r"\b(\d{1,3})\b", prepared)
    if m3:
         return f"POL-{int(m3.group(1)):03d}"

    return "unknown"


def _canonical_dob_from_text(text: str) -> str:
    """
    Flexible DOB parsing handles:
    - 1985 the 14th of March
    - March 14 1985
    """
    if not text:
        return ""
    
    months = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12"
    }
    
    prepared = text.lower()
    prepared = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", prepared)
    
    # 1. Month Name search (e.g. "1985 the 14 of march")
    for m_name, m_num in months.items():
        if m_name in prepared:
            m_year = re.search(r"\b((?:19|20)\d{2})\b", prepared)
            # Find the day digit strictly within 12 chars of the month name
            # This avoids picking up the "001" from the Member ID
            m_day = re.search(rf"\b([12]\d|3[01]|0?[1-9])\b(?:\s+(?:of|the))?\s+{m_name}|{m_name}\s+(?:the\s+)?\b([12]\d|3[01]|0?[1-9])\b", prepared)
            
            if m_year:
                day_val = m_day.group(1) or m_day.group(2) if m_day else "01"
                return f"{m_year.group(1)}-{m_num}-{int(day_val):02d}"

    # 2. Digital format search
    prepared_digits = _speech_words_to_digits(prepared)
    
    m = re.search(r"\b(19|20)\d{2}[-/\s](0?[1-9]|1[0-2])[-/\s](0?[1-9]|[12]\d|3[01])\b", prepared_digits)
    if m:
        nums = re.findall(r"\d+", m.group(0))
        return f"{int(nums[0]):04d}-{int(nums[1]):02d}-{int(nums[2]):02d}"

    m2 = re.search(r"\b(0?[1-9]|[12]\d|3[01])[-/\s](0?[1-9]|1[0-2])[-/\s]((?:19|20)\d{2})\b", prepared_digits)
    if m2:
        nums = re.findall(r"\d+", m2.group(0))
        return f"{int(nums[2]):04d}-{int(nums[1]):02d}-{int(nums[0]):02d}"

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

def _generate_with_tools(caller_input: str, conversation_history: list, member_data: dict) -> str:
    from ai_service import _chat_client_and_model
    import json
    
    try:
        client, model = _chat_client_and_model()
    except Exception:
        return "I'm having trouble connecting to my knowledge base right now. Can you try again later?"
        
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_member_policy_details",
                "description": "Fetches real-time balances and limits for the member, such as deductible and claims used/remaining.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "member_id": {"type": "string", "description": "The member ID (e.g. POL-001)"}
                    },
                    "required": ["member_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_hospital_coverage",
                "description": "Queries the policy knowledge base to check coverage rules for a specific hospital or treatment.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hospital_name": {"type": "string", "description": "Name of the hospital or treatment"},
                        "policy_type": {"type": "string", "description": "Policy type (e.g., 'comprehensive')"},
                        "member_id": {"type": "string", "description": "The specific member ID (e.g. POL-001)"}
                    },
                    "required": ["hospital_name", "policy_type", "member_id"]
                }
            }
        }
    ]
    
    plan_name = member_data.get('plan_name') or member_data.get('plan_type')
    system_prompt = (
        "You are a remarkably warm, empathetic, and professional AI health insurance assistant for InsureCo. "
        "Your priority is to make the member feel heard, understood, and cared for. "
        "Use a natural, conversational tone—avoid sounding like a robot or a search engine."
        "\n\nGuidelines for a Personalised, Human Experience:\n"
        f"1. PERSONALISATION: Address the member by their name, {member_data.get('member_name')}, at the start of your response when appropriate. "
        "2. EMPATHY & WARMTH: If the member is asking about medical procedures or health concerns, respond with genuine empathy (e.g., 'I understand that's a lot to deal with...'). "
        "3. BRIDGING PHRASES: If you are looking up information, start your sentence with a warm 'bridging' phrase that makes the interaction feel live. "
        "   Example: 'Certainly, let me check those policy details for you... alright, I see here that...' "
        "4. SMALL TALK: If they ask how you are, respond warmly and briefly (e.g., 'I'm doing wonderful, thank you for asking! How can I make your day easier?'). "
        "5. FLOW: Keep responses cohesive and under 50 words. Avoid bullet points; speak in complete, friendly sentences.\n\n"
        "Member Info for Context:\n"
        f"- Name: {member_data.get('member_name')}\n"
        f"- Member ID: {member_data.get('policy_id')}\n"
        f"- Current Plan: {member_data.get('plan_name')} (Type: {member_data.get('plan_type')})\n"
        "\nTools available:\n"
        "- get_member_policy_details: For specific balances/deductibles.\n"
        "- search_hospital_coverage: For rules/percentages in the policy knowledge base.\n"
    )
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history[-6:]:
        if msg.get("role") in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": caller_input})
    
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=0.7
    )
    
    message = response.choices[0].message
    if message.tool_calls:
        messages.append(message)
        for tool_call in message.tool_calls:
            try:
                args = json.loads(tool_call.function.arguments)
            except Exception:
                args = {}
            if tool_call.function.name == "get_member_policy_details":
                mid = args.get("member_id", member_data.get("policy_id"))
                from rag.db_retriever import get_member_data as get_mem
                res = get_mem(mid) or {}
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": tool_call.function.name, "content": json.dumps(res)})
            elif tool_call.function.name == "search_hospital_coverage":
                h_name = args.get("hospital_name", caller_input)
                p_type = args.get("policy_type", plan_name)
                m_id = args.get("member_id", member_data.get("policy_id"))
                from tools.rag_tool import policy_rag_tool
                res_raw = policy_rag_tool(query=h_name, plan_type=p_type, member_id=m_id)
                # LLM expects a list or string, policy_rag_tool returns a JSON string
                import json
                try:
                    res_json = json.loads(res_raw)
                    tool_result = res_json.get("clauses", [])
                except Exception:
                    tool_result = res_raw
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": tool_call.function.name, "content": json.dumps(tool_result)})

        
        response2 = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5
        )
        return response2.choices[0].message.content or "I couldn't find an answer to that right now."
        
    return message.content or "I couldn't find an answer to that right now."

def build_crew_for_query(
    caller_input: str,
    caller_id: str,
    caller_phone: str,
    conversation_history: list,
    demo_mode: bool = False,
    member_data: dict = None,
) -> CrewTurnResult:

    """
    Run verification → intent → RAG value extraction → portal render (Cosmos templates).

    Returns:
        CrewTurnResult with ``response_text`` for TTS/summary and optional ``portal_render`` metadata.
    """
    if demo_mode:
        return CrewTurnResult(response_text=_demo_response(caller_input, caller_id, caller_phone))

    if member_data and member_data.get("verified"):
        verification = member_data
    else:
        member_id, email, dob = _extract_profile_fields(caller_input, conversation_history, caller_id)
        verification = _verify_identity_logic(member_id=member_id, dob=dob, email=email, phone=caller_phone)
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

    if _is_identity_only_utterance(caller_input) and not (member_data and member_data.get("verified")):
        name = verification.get("member_name", "there")
        return CrewTurnResult(
            response_text=(
                f"Thanks {name}, your identity is verified. "
                "How can I help with your policy today?"
            ),
            member_data=verification
        )

    intent_payload = _intent_from_service(caller_input, verification.get("policy_id", caller_id), conversation_history)
    intent = intent_payload.get("intent", "fallback_human")

    # ── Interactive Interjection / Fast Path Small Talk ──────────────────────
    if intent.startswith("smalltalk_"):
        name = verification.get("member_name", "")
        base_resp = fill_template(intent)
        full_resp = f"Of course, {name}. {base_resp}" if name else base_resp
        return CrewTurnResult(response_text=full_resp, member_data=verification)

    rag_values = _extract_rag_values(caller_input, verification.get("policy_id", caller_id), intent)
    rag_values.setdefault("plan_name", verification.get("plan_name", "your current plan"))
    rag_values.setdefault("deductible_remaining", verification.get("deductible_remaining", "€0"))
    rag_values.setdefault("remaining_limit", verification.get("claims_remaining", "€0"))

    rendered = render_portal_response(intent, rag_values)
    
    # Override static templated response with dynamic AI tool-called response
    final_text = _generate_with_tools(caller_input, conversation_history, verification)
    rendered.rendered_text = final_text

    return CrewTurnResult(response_text=final_text, portal_render=rendered, member_data=verification)

