"""
tools/rag_tool.py
CrewAI tool – hybrid vector + keyword search against Azure AI Search.
Falls back to an in-memory demo knowledge base when Azure Search is not configured.
"""
import json
try:
    from crewai.tools import tool
except Exception:
    # Allow non-Crew runtime imports (e.g., API-only mode)
    def tool(_name):
        def _decorator(func):
            return func
        return _decorator
from config import settings

# ── Demo knowledge base (used when Azure Search is not configured) ────────────
DEMO_POLICY_KB: list[dict] = [
    {
        "policy_id": "POL-001",
        "section": "Hospital Coverage",
        "content": (
            "PremiumCare Plus covers 80% of inpatient and outpatient treatment costs "
            "at all in-network hospitals, up to an annual maximum of €80,000. "
            "Covered hospitals include: St. Vincent's, Mater Private, Beacon Hospital, "
            "Blackrock Clinic, and Dublin City Hospital."
        ),
        "coverage_type": "hospital",
        "keywords": ["hospital", "coverage", "inpatient", "outpatient", "network"],
    },
    {
        "policy_id": "POL-001",
        "section": "Surgery Benefits",
        "content": (
            "Surgical procedures under PremiumCare Plus are covered at 90% "
            "with a per-procedure limit of €20,000. Pre-authorisation is required "
            "for elective procedures exceeding €5,000."
        ),
        "coverage_type": "surgery",
        "keywords": ["surgery", "surgical", "procedure", "operation"],
    },
    {
        "policy_id": "POL-001",
        "section": "Mental Health",
        "content": (
            "Mental health inpatient cover is included up to 100 days per annum "
            "at 75% of costs, capped at €15,000. Outpatient counselling is covered "
            "for up to 20 sessions per year at €75 per session."
        ),
        "coverage_type": "mental_health",
        "keywords": ["mental health", "counselling", "therapy", "psychiatry"],
    },
    {
        "policy_id": "POL-002",
        "section": "Hospital Coverage",
        "content": (
            "StandardCare covers 70% of hospital costs at in-network facilities, "
            "up to €40,000 per year. Out-of-network hospitals are covered at 50%."
        ),
        "coverage_type": "hospital",
        "keywords": ["hospital", "coverage", "inpatient", "network"],
    },
    {
        "policy_id": "POL-002",
        "section": "Dental",
        "content": (
            "Dental cover under StandardCare: routine check-ups covered at 100% "
            "(2 per year). Restorative work covered at 60% up to €1,500 per year. "
            "Orthodontics are excluded."
        ),
        "coverage_type": "dental",
        "keywords": ["dental", "teeth", "orthodontic", "check-up"],
    },
    {
        "policy_id": "POL-003",
        "section": "Hospital Coverage",
        "content": (
            "BasicCare provides semi-private room cover at 60% of costs up to €15,000 "
            "per year. Only hospitals in the Tier 1 network are covered. "
            "Private room upgrades are not included."
        ),
        "coverage_type": "hospital",
        "keywords": ["hospital", "semi-private", "basic", "tier 1"],
    },
]


def _search_demo_kb(query: str, policy_id: str, top_k: int = 3) -> list[str]:
    """Simple keyword-based fallback search over the demo KB."""
    query_lower = query.lower()
    scored = []
    for doc in DEMO_POLICY_KB:
        if doc["policy_id"].upper() != policy_id.upper():
            continue
        score = sum(1 for kw in doc["keywords"] if kw in query_lower)
        if score > 0 or any(kw in query_lower for kw in ["cover", "hospital", "claim"]):
            scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        f"[{d['section']}]: {d['content']}"
        for _, d in scored[:top_k]
    ] or [
        f"[General]: No specific clause found for this query under policy {policy_id}. "
        "Please consult your full policy document."
    ]


def _search_azure(query: str, policy_id: str, top_k: int = 3) -> list[str] | None:
    """Attempt Azure AI Search hybrid retrieval; return None if not configured."""
    if not settings.azure_search_endpoint or not settings.azure_search_key:
        return None
    try:
        from azure.search.documents import SearchClient
        from azure.search.documents.models import VectorizedQuery
        from azure.core.credentials import AzureKeyCredential
        from openai import AzureOpenAI

        oai = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_key,
            api_version=settings.azure_openai_api_version,
        )
        embedding_response = oai.embeddings.create(
            input=query,
            model=settings.azure_openai_embedding_deployment,
        )
        query_vector = embedding_response.data[0].embedding

        search_client = SearchClient(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_index,
            credential=AzureKeyCredential(settings.azure_search_key),
        )
        vector_query = VectorizedQuery(
            vector=query_vector,
            k_nearest_neighbors=top_k,
            fields="content_vector",
        )
        results = search_client.search(
            search_text=query,
            vector_queries=[vector_query],
            filter=f"policy_id eq '{policy_id}'",
            select=["content", "section_title", "coverage_type"],
            top=top_k,
        )
        extracted = [f"[{r['section_title']}]: {r['content']}" for r in results]
        return extracted if extracted else None
    except Exception:
        return None


@tool("Policy RAG Retriever")
def policy_rag_tool(query: str, policy_id: str) -> str:
    """
    Retrieve relevant policy clauses for a given query and policy ID.
    Searches Azure AI Search (hybrid vector + keyword) or falls back to
    the built-in demo knowledge base.

    Args:
        query: The insurance-related question (e.g. 'Is surgery at Beacon Hospital covered?').
        policy_id: The policyholder's policy ID (e.g. 'POL-001').

    Returns:
        JSON string with a list of relevant policy clause excerpts.
    """
    azure_results = _search_azure(query, policy_id)
    if azure_results:
        clauses = azure_results
    else:
        clauses = _search_demo_kb(query, policy_id)

    return json.dumps({
        "policy_id": policy_id,
        "query": query,
        "clauses": clauses,
        "source": "azure_ai_search" if azure_results else "demo_kb",
    })
