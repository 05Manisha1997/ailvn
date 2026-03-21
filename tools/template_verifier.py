"""
tools/template_verifier.py
Uses Azure OpenAI to clean up and verify new response templates provided by users.
"""
from pydantic import BaseModel, Field
import json

class TemplateVerificationResult(BaseModel):
    clean_template: str = Field(description="The cleaned, professional template string with clear JSON-style bracket placeholders.")
    intent_key: str = Field(description="The intent key format in snake_case.")

async def verify_and_fix_template(intent_key: str, proposed_template: str) -> str:
    """
    Sends the user's proposed template to the LLM to format it professionally and ensure valid brackets.
    Returns the cleaned template string.
    """
    # Import locally to avoid issues if LLM isn't configured
    from agents.crew_insurance import _make_llm
    
    llm = _make_llm()
    if not llm:
        # Fallback if no LLM configured (e.g. demo mode) - just return it mostly untouched
        return proposed_template.strip()
        
    prompt = f"""
You are an expert conversational AI designer for an insurance company.
A user has proposed a new response template for the intent '{intent_key}'.
The proposed template is: "{proposed_template}"

Rewrite this to be a single, professional spoken sentence with clear JSON-style bracket placeholders (e.g. {{amount}}, {{hospital_name}}) for any dynamic data.
DO NOT include greetings, pleasantries, or conversational filler.
DO NOT wrap the response in quotes.
Output a JSON object with 'clean_template' and 'intent_key' matching the schema.
    """

    try:
        # Call LangChain LLM with structured output
        llm_with_structure = llm.with_structured_output(TemplateVerificationResult)
        result = llm_with_structure.invoke(prompt)
        return result.clean_template
    except Exception as e:
        print(f"[Verifier Error] Failed to clean template: {e}")
        # If it fails, fallback to something safe
        return proposed_template.strip()
