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
        "Great news — {hospital_name} is covered under your plan. "
        "Your policy covers {coverage_pct} of the treatment costs there, "
        "up to a maximum benefit of {max_limit}. "
        "Please don't hesitate to call us if you need any more details before your visit."
    ),
    "hospital_not_in_network": (
        "I understand this might not be the answer you were hoping for — "
        "{hospital_name} is unfortunately not within your current network. "
        "Out-of-pocket costs would apply if you go there. "
        "The closest in-network facility to you is {nearest_network_hospital}, "
        "which should be able to provide the same level of care fully covered."
    ),
    "treatment_covered": (
        "Good news — {treatment_type} is included in your plan. "
        "You're covered at {coverage_pct}, and your annual benefit limit for this is {limit}. "
        "I hope that gives you some peace of mind."
    ),
    "treatment_not_covered": (
        "I'm sorry to have to share this — {treatment_type} isn't covered under your "
        "current {plan_name} plan. If you'd like, I can check whether an upgrade "
        "or alternative treatment option might be available. Just let me know."
    ),
    "deductible_status": (
        "Your annual deductible is {deductible_amount}. "
        "You currently have {deductible_remaining} remaining before your full coverage kicks in. "
        "Once that's met, we take care of the rest — so you're well on your way."
    ),
    "claim_limit_remaining": (
        "You have {remaining_limit} remaining in your {benefit_category} benefit for this policy year. "
        "If you're planning ahead for upcoming treatments, that should give you a good idea of what's available."
    ),
    "identity_prompt": (
        "To make sure I'm speaking with the right person and protecting your account, "
        "could you please provide your {missing_field}? I appreciate your patience with this."
    ),
    "identity_failed": (
        "I'm really sorry — I wasn't able to verify your identity with the information provided, "
        "and I want to make sure your account stays protected. "
        "When you're ready to try again, please have your Member ID, "
        "registered email address, and date of birth to hand. "
        "Our team is always here to help. Thank you so much for your understanding."
    ),
    "fallback_human": (
        "I want to make sure you get exactly the right answer for this. "
        "Let me connect you with one of our specialists who can help you further — "
        "please hold for just a moment."
    ),
    "greeting": (
        "Hello, and thank you so much for calling InsureCo! "
        "I'm your AI assistant, and I'm here to help with any questions about your policy. "
        "To get started and protect your privacy, "
        "could you please share your Member ID, registered email address, and date of birth?"
    ),
    "farewell": (
        "It's been a pleasure helping you today. "
        "Is there anything else I can assist you with before you go? "
        "We're always here if you need us — take care, and have a wonderful day!"
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
 
