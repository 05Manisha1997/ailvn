"""
agents/tasks.py
Assembles and runs the 4-task CrewAI crew for a single caller turn.
Uses factory functions from crew_insurance.py so no LLM is required at import time.
Also includes a demo/simulation mode that avoids all API calls for hackathon demos.
"""
import json
import re
from templates.response_templates import TEMPLATES, fill_template


# ── Demo simulation (no real LLM calls) ──────────────────────────────────────

def _demo_response(caller_input: str, member_id: str, caller_phone: str) -> str:
    """Fast demo path — keyword-matched response, no API calls."""
    from tools.identity_tool import _verify_identity_logic
    
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
    from agents.crew_insurance import _make_llm, make_identity_agent, make_intent_agent, make_rag_agent, make_response_agent

    llm = _make_llm()

    if demo_mode or llm is None:
        return _demo_response(caller_input, caller_id, caller_phone)

    # Build fresh agent instances for this query (required by CrewAI v1.x)
    from crewai import Task, Crew, Process

    identity_agent = make_identity_agent(llm)
    intent_agent   = make_intent_agent(llm)
    rag_agent      = make_rag_agent(llm)
    response_agent = make_response_agent(llm)

    # ── Task 1: Identity Verification ──────────────────────────────────────
    verify_task = Task(
        description=f"""
        Caller Phone (Automatic): {caller_phone}
        Conversation so far: {json.dumps(conversation_history, indent=2)}

        Use the Identity Verifier tool to verify this caller.
        Extract the alphanumeric member_id, email, and date of birth from the conversation history.
        Pass the 'null' or empty string if a field is not yet provided.
        The 'phone' argument MUST be exactly: {caller_phone}
        """,
        expected_output=(
            "JSON: verified (bool), policy_id, member_name, plan_name, "
            "deductible_remaining, claims_remaining. "
            "If not verified: verified=False and reason. Mention if information is missing."
        ),
        agent=identity_agent,
    )

    # ── Task 2: Intent Extraction ───────────────────────────────────────────
    intent_task = Task(
        description=f"""
        Caller said: "{caller_input}"
        Prior verification result is in context.

        Extract structured intent as JSON with these fields:
        - query_type: one of [coverage_check, hospital_eligibility, claim_limit, deductible, treatment_check, other]
        - hospital_name: if mentioned, else null
        - treatment_type: if mentioned, else null
        - policy_id: from the verification result
        """,
        expected_output="JSON: query_type, hospital_name, treatment_type, policy_id",
        agent=intent_agent,
        context=[verify_task],
    )

    # ── Task 3: RAG Policy Retrieval ────────────────────────────────────────
    rag_task = Task(
        description="""
        Using the structured intent from context, call the Policy RAG Retriever tool
        with the caller's query and policy_id.

        Extract from the returned clauses:
        - coverage_pct (e.g. 80%)
        - max_limit (e.g. €80,000)
        - hospital_in_network (true/false if hospital was asked)
        - nearest_network_hospital (if out of network)
        - benefit_limit (annual cap)
        - exclusions (list any mentioned)

        Return ONLY raw values. No prose.
        """,
        expected_output=(
            "JSON: coverage_pct, max_limit, hospital_in_network, "
            "nearest_network_hospital, benefit_limit, exclusions"
        ),
        agent=rag_agent,
        context=[intent_task],
    )

    # ── Task 4: Response Formatting ─────────────────────────────────────────
    format_task = Task(
        description=f"""
        Use ONLY the templates below. Fill in slots from the RAG context.
        Pick the template that best matches the query_type.

        Available templates:
        {json.dumps(TEMPLATES, indent=2)}

        Output a single, complete sentence ready to be spoken aloud to the caller.
        Do not add greetings, disclaimers, or additional sentences.
        """,
        expected_output="Single spoken sentence filled from the correct template.",
        agent=response_agent,
        context=[rag_task],
    )

    crew = Crew(
        agents=[identity_agent, intent_agent, rag_agent, response_agent],
        tasks=[verify_task, intent_task, rag_task, format_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()
    return str(result)
