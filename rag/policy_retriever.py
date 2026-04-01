"""
rag/policy_retriever.py
Route C - policy clause retrieval used by simulator/task flow.
"""
from __future__ import annotations

from tools.rag_tool import _search_azure, _search_demo_kb


def retrieve_policy_clauses(
    query: str,
    policy_id: str,
    intent: str,
    top_k: int = 3,
) -> dict:
    """
    Retrieve policy clauses from Azure AI Search (if configured), else demo KB.
    Returns {clauses, source, intent}.
    """
    pid = (policy_id or "").strip().upper()
    azure = _search_azure(query=query, policy_id=pid, top_k=top_k)
    if azure:
        return {"clauses": azure[:top_k], "source": "azure_ai_search", "intent": intent}
    demo = _search_demo_kb(query=query, policy_id=pid, top_k=top_k)
    return {"clauses": demo[:top_k], "source": "demo_kb", "intent": intent}

