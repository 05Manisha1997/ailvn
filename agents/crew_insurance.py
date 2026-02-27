"""
agents/crew_insurance.py
Defines factory functions for the 4 CrewAI agents.
Agents are created LAZILY (at query time) to avoid requiring API keys at import time.
Compatible with CrewAI v1.x which validates LLM on Agent.__init__.
"""
from config import settings


def _make_llm():
    """Build an AzureChatOpenAI LLM instance, or return None if not configured."""
    if not settings.azure_openai_endpoint or not settings.azure_openai_key:
        return None
    try:
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(
            azure_deployment=settings.azure_openai_deployment,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_key,
            api_version=settings.azure_openai_api_version,
        )
    except Exception:
        return None


def make_identity_agent(llm):
    from crewai import Agent
    from tools.identity_tool import verify_identity_tool
    return Agent(
        role="Identity Verification Specialist",
        goal=(
            "Verify the caller's identity using their policy number, date of birth, "
            "and name before any policy information is disclosed."
        ),
        backstory=(
            "You are a compliance-focused agent responsible for confirming a caller "
            "is a valid policyholder. You use the Identity Verifier tool to cross-check "
            "credentials against the policyholder database. If verification fails, "
            "you ask for the missing or incorrect detail."
        ),
        llm=llm,
        tools=[verify_identity_tool],
        verbose=True,
        allow_delegation=False,
    )


def make_intent_agent(llm):
    from crewai import Agent
    return Agent(
        role="Insurance Query Intent Extractor",
        goal=(
            "Extract a structured JSON intent object from the caller's natural-language query, "
            "identifying query type, hospital, treatment, and any financial asks."
        ),
        backstory=(
            "You are an expert at parsing insurance-specific language. "
            "You convert ambiguous caller statements into clean structured fields: "
            "query_type, hospital_name, treatment_type, policy_id. "
            "You do not answer the query — you only classify it."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )


def make_rag_agent(llm):
    from crewai import Agent
    from tools.rag_tool import policy_rag_tool
    return Agent(
        role="Policy Document Analyst",
        goal=(
            "Retrieve the exact policy clauses relevant to the caller's query "
            "and extract precise coverage percentages, limits, exclusions, and network status."
        ),
        backstory=(
            "You have deep access to the policy document vector store. "
            "Given a structured intent object and a policy ID, you query the RAG tool "
            "and return raw extracted values — never prose."
        ),
        llm=llm,
        tools=[policy_rag_tool],
        verbose=True,
        allow_delegation=False,
    )


def make_response_agent(llm):
    from crewai import Agent
    return Agent(
        role="Customer Response Formatter",
        goal=(
            "Compose the final spoken response by slotting extracted values into "
            "pre-approved fill-in-the-blank templates. Never freeform. Never hallucinate."
        ),
        backstory=(
            "You are the last agent in the pipeline. You receive extracted coverage data "
            "and must choose the correct template from the approved set, then fill in "
            "the slots with precise values. Any hallucinated number in an insurance context "
            "is a legal liability — you only output templated responses."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )