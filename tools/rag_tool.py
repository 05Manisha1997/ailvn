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

import functools
from rag.blob_client import fetch_policy_kb

@functools.lru_cache(maxsize=1)
def _get_cached_policy_kb() -> list[dict]:
    """Fetch KB from blob storage and cache it for 1 hour (simulated by lru_cache for now)."""
    kb = fetch_policy_kb()
    return kb if kb else []

def _search_dynamic_kb(query: str, plan_type: str, top_k: int = 3) -> list[str]:
    """Search over the dynamic knowledge base loaded from Blob Storage."""
    kb = _get_cached_policy_kb()
    if not kb:
        return ["Error: Could not load policy knowledge base from Azure Storage."]
        
    query_lower = query.lower()
    plan_type_lower = (plan_type or "").lower()
    scored = []
    
    for doc in kb:
        # Personalization: filter by plan type if provided
        doc_plan = str(doc.get("plan_type", "")).lower()
        if plan_type_lower and doc_plan and plan_type_lower not in doc_plan and doc_plan not in plan_type_lower:
            continue
            
        # Basic keyword scoring
        content = doc.get("content", "").lower()
        keywords = doc.get("keywords", [])
        score = sum(2 for kw in keywords if str(kw).lower() in query_lower)
        if any(word in content for word in query_lower.split()):
            score += 1
            
        if score > 0:
            scored.append((score, doc))
            
    scored.sort(key=lambda x: x[0], reverse=True)
    
    results = [
        f"[{d.get('section', 'General')}]: {d.get('content', '')}"
        for _, d in scored[:top_k]
    ]
    
    if not results:
        return [f"No specific clause found for '{query}' under your {plan_type} plan in the policy documents."]
        
    return results



def _search_azure(query: str, plan_type: str, top_k: int = 3) -> list[str] | None:
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
        # Apply OData filter using the policy_type (e.g. 'Company Care Plus' or 'comprehensive')
        filter_expr = f"applicable_policies/any(p: p eq '{plan_type}')" if plan_type else None
        
        results = search_client.search(
            search_text=query,
            vector_queries=[vector_query],
            filter=filter_expr,
            select=["content", "section_title", "coverage_type"],
            top=top_k,
        )
        extracted = [f"[{r['section_title']}]: {r['content']}" for r in results]
        return extracted if extracted else None
    except Exception:
        return None


@tool("Policy RAG Retriever")
def policy_rag_tool(query: str, plan_type: str, member_id: str = "unknown") -> str:
    """
    Retrieve relevant policy clauses for a given query and plan type.
    
    Args:
        query: Insurance-related question.
        plan_type: Plan type (e.g. 'comprehensive').
        member_id: The member's specific ID (e.g. 'POL-001').
    """
    azure_results = _search_azure(query, plan_type)
    if azure_results:
        clauses = azure_results
    else:
        # Pass the member_id to the dynamic lookup so it can fetch their specific .txt file if needed
        kb = fetch_policy_kb(member_id=member_id)
        if not kb:
            clauses = ["Error: Could not load policy knowledge for this member."]
        else:
            clauses = _search_dynamic_kb_from_loaded(query, plan_type, kb)

    return json.dumps({
        "plan_type": plan_type,
        "query": query,
        "member_id": member_id,
        "clauses": clauses,
        "source": "azure_ai_search" if azure_results else "azure_blob_storage",
    })

def _search_dynamic_kb_from_loaded(query: str, plan_type: str, kb: list[dict], top_k: int = 3) -> list[str]:
    query_lower = (query or "").lower()
    scored = []
    
    for doc in kb:
        content = str(doc.get("content", "")).lower()
        title = str(doc.get("section", "")).lower()
        keywords = [str(k).lower() for k in doc.get("keywords", [])]
        
        score = sum(3 for kw in keywords if kw in query_lower)
        if any(word in content or word in title for word in query_lower.split()):
            score += 1
            
        if score > 0 or len(kb) == 1: # Always return if it's the only (member-specific) file
            scored.append((score, doc))
            
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [f"[{d.get('section', 'General')}]: {d.get('content', '')}" for _, d in scored[:top_k]]
    return results if results else [f"No matches found for '{query}' in the policy document."]


