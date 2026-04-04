"""
rag/policy_retriever.py
Route C - policy clause retrieval used by simulator/task flow.
"""
from __future__ import annotations

from tools.rag_tool import _search_azure, _search_dynamic_kb
from rag.db_retriever import get_member_data


def retrieve_policy_clauses(
    query: str,
    policy_id: str,
    intent: str,
    top_k: int = 3,
) -> dict:
    """
    Retrieve policy clauses from Azure AI Search (if configured), else Azure Blob.
    Returns {clauses, source, intent}.
    """
    pid = (policy_id or "").strip().upper()
    member = get_member_data(pid) or {}
    plan_type = member.get("plan_type", "")
    azure = _search_azure(query=query, plan_type=plan_type, top_k=top_k)
    if azure:
        return {"clauses": azure[:top_k], "source": "azure_ai_search", "intent": intent}
    demo = _search_dynamic_kb(query=query, plan_type=plan_type, top_k=top_k)
    return {"clauses": demo[:top_k], "source": "azure_blob_storage", "intent": intent}

