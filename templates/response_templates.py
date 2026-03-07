import os
import json

# Define the absolute path to the templates file
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TEMPLATES_FILE = os.path.join(DATA_DIR, "templates.json")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Default templates to fall back on or initialize the file with
DEFAULT_TEMPLATES: dict[str, str] = {
    "hospital_covered": (
        "Your policy covers {coverage_pct} of treatment costs at {hospital_name}, "
        "up to a maximum of {max_limit}."
    ),
    "hospital_not_in_network": (
        "{hospital_name} is not within your network. "
        "Out-of-pocket costs will apply. "
        "Your nearest in-network facility is {nearest_network_hospital}."
    ),
    "treatment_covered": (
        "{treatment_type} is covered under your plan at {coverage_pct}, "
        "with a benefit limit of {limit} per year."
    ),
    "treatment_not_covered": (
        "{treatment_type} is not covered under your current {plan_name} plan."
    ),
    "deductible_status": (
        "Your annual deductible is {deductible_amount}. "
        "You have {deductible_remaining} remaining before full coverage activates."
    ),
    "claim_limit_remaining": (
        "You have {remaining_limit} remaining in your {benefit_category} "
        "benefit for this policy year."
    ),
    "identity_prompt": (
        "I need to verify your identity. "
        "Could you please provide your {missing_field}?"
    ),
    "identity_failed": (
        "I'm sorry, but I was unable to verify your identity with the information provided. "
        "Unfortunately, I cannot proceed with your request as an unverified user. "
        "Please have your Member ID, registered email, and date of birth ready and call us back. "
        "Thank you for your understanding."
    ),
    "fallback_human": (
        "I wasn't able to find a clear answer for your query. "
        "Let me transfer you to a specialist right away."
    ),
    "greeting": (
        "Thank you for calling InsureCo. "
        "To get started, please state your alphanumeric Member ID, your registered email address, and your date of birth."
    ),
    "farewell": (
        "Thank you for calling InsureCo. "
        "Is there anything else I can help you with today?"
    ),
}

# The active loaded templates dictionary
TEMPLATES: dict[str, str] = {}


def _load_templates():
    """Load templates from disk, or create the file with defaults if missing."""
    global TEMPLATES
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
                TEMPLATES = json.load(f)
        except Exception as e:
            print(f"[Error] Failed to load {TEMPLATES_FILE}: {e}")
            TEMPLATES = DEFAULT_TEMPLATES.copy()
    else:
        TEMPLATES = DEFAULT_TEMPLATES.copy()
        _save_templates()


def _save_templates():
    """Save the current TEMPLATES dictionary to disk."""
    try:
        with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
            json.dump(TEMPLATES, f, indent=4)
    except Exception as e:
        print(f"[Error] Failed to save {TEMPLATES_FILE}: {e}")


def fill_template(key: str, **kwargs) -> str:
    """
    Return a filled template string.

    Args:
        key: Key in TEMPLATES dict.
        **kwargs: Values to substitute into the template.

    Returns:
        Filled string, or the fallback_human template if key not found.
    """
    if not TEMPLATES:
        _load_templates()

    template = TEMPLATES.get(key, TEMPLATES.get("fallback_human", "I wasn't able to find a clear answer for your query."))
    try:
        return template.format(**kwargs)
    except KeyError as e:
        # Gracefully handle missing substitution values
        return TEMPLATES.get("fallback_human", "I wasn't able to find a clear answer for your query.")

def get_all_templates() -> dict[str, str]:
    if not TEMPLATES:
       _load_templates()
    return TEMPLATES

def upsert_template(key: str, value: str) -> None:
    """Add a new template or update an existing one."""
    if not TEMPLATES:
        _load_templates()
    TEMPLATES[key] = value
    _save_templates()

# Initialize on module load
_load_templates()
