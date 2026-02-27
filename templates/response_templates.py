"""
templates/response_templates.py
Fill-in-the-blank response templates – the ONLY strings ever spoken to callers.
The LLM extracts values; it never authors free-form responses.
"""

TEMPLATES: dict[str, str] = {
    # ── Coverage & Hospital ───────────────────────────────────────────────────
    "hospital_covered": (
        "Your policy covers {coverage_pct} of treatment costs at {hospital_name}, "
        "up to a maximum of {max_limit}."
    ),
    "hospital_not_in_network": (
        "{hospital_name} is not within your network. "
        "Out-of-pocket costs will apply. "
        "Your nearest in-network facility is {nearest_network_hospital}."
    ),
    # ── Treatment ────────────────────────────────────────────────────────────
    "treatment_covered": (
        "{treatment_type} is covered under your plan at {coverage_pct}, "
        "with a benefit limit of {limit} per year."
    ),
    "treatment_not_covered": (
        "{treatment_type} is not covered under your current {plan_name} plan."
    ),
    # ── Financials ────────────────────────────────────────────────────────────
    "deductible_status": (
        "Your annual deductible is {deductible_amount}. "
        "You have {deductible_remaining} remaining before full coverage activates."
    ),
    "claim_limit_remaining": (
        "You have {remaining_limit} remaining in your {benefit_category} "
        "benefit for this policy year."
    ),
    # ── Identity & Fallback ───────────────────────────────────────────────────
    "identity_prompt": (
        "I need to verify your identity. "
        "Could you please provide your {missing_field}?"
    ),
    "identity_failed": (
        "I'm sorry, I was unable to verify your identity with the information provided. "
        "Please call back with your policy number and date of birth ready."
    ),
    "fallback_human": (
        "I wasn't able to find a clear answer for your query. "
        "Let me transfer you to a specialist right away."
    ),
    "greeting": (
        "Thank you for calling InsureCo. "
        "Please state your policy number and date of birth to begin."
    ),
    "farewell": (
        "Thank you for calling InsureCo. "
        "Is there anything else I can help you with today?"
    ),
}


def fill_template(key: str, **kwargs) -> str:
    """
    Return a filled template string.

    Args:
        key: Key in TEMPLATES dict.
        **kwargs: Values to substitute into the template.

    Returns:
        Filled string, or the fallback_human template if key not found.
    """
    template = TEMPLATES.get(key, TEMPLATES["fallback_human"])
    try:
        return template.format(**kwargs)
    except KeyError as e:
        # Gracefully handle missing substitution values
        return TEMPLATES["fallback_human"]
