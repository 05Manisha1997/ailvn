"""
ai_service.py
LLM-based intent classification for transcribed caller speech, Cosmos logging,
optional webhook to a downstream service, and mapping to portal/RAG intents.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings

logger = logging.getLogger(__name__)

# Labels the classifier must return verbatim (one line).
CLASSIFIER_INTENT_LABELS: tuple[str, ...] = (
    "Coverage Verification",
    "Claims Status Inquiry",
    "Network Search",
    "Benefits Explanation",
    "Prescription/Formulary Check",
    "Coordination of Benefits",
    "High-Deductible/Accumulator Inquiry",
    "Update Personal Information",
    "Appealing a Denial",
    "Tax/Enrollment Documentation",
    "Small Talk - Greeting",
    "Small Talk - Thanks",
    "Small Talk - Goodbye",
    "Small Talk - How Are You",
    "Small Talk - Weather",
    "Small Talk - Wait",
)

# Map LLM labels → CallOrchestrator / response_portal.py template keys (ACS audio path).
PORTAL_INTENT_BY_CLASSIFIER: dict[str, str] = {
    "Coverage Verification": "PRODUCT_INFO",
    "Claims Status Inquiry": "RECENT_TRANSACTIONS",
    "Network Search": "PRODUCT_INFO",
    "Benefits Explanation": "PRODUCT_INFO",
    "Prescription/Formulary Check": "PRODUCT_INFO",
    "Coordination of Benefits": "BILLING_QUERY",
    "High-Deductible/Accumulator Inquiry": "ACCOUNT_BALANCE",
    "Update Personal Information": "TECH_SUPPORT",
    "Appealing a Denial": "COMPLAINT",
    "Tax/Enrollment Documentation": "BILLING_QUERY",
    "Small Talk - Greeting": "GENERAL_QUERY",
    "Small Talk - Thanks": "GENERAL_QUERY",
    "Small Talk - Goodbye": "GOODBYE",
    "Small Talk - How Are You": "GENERAL_QUERY",
    "Small Talk - Weather": "GENERAL_QUERY",
    "Small Talk - Wait": "GENERAL_QUERY",
}

# InsurancePortal / Cosmos ``response_templates`` keys (simulator REST path via agents.tasks).
INSURANCE_TEMPLATE_BY_CLASSIFIER: dict[str, str] = {
    "Coverage Verification": "csr_coverage_verification",
    "Claims Status Inquiry": "csr_claims_status_inquiry",
    "Network Search": "csr_network_search",
    "Benefits Explanation": "csr_benefits_explanation_oop",
    "Prescription/Formulary Check": "csr_prescription_formulary",
    "Coordination of Benefits": "csr_coordination_of_benefits",
    "High-Deductible/Accumulator Inquiry": "csr_high_deductible_accumulator",
    "Update Personal Information": "csr_update_personal_info",
    "Appealing a Denial": "csr_appeal_denial",
    "Tax/Enrollment Documentation": "csr_tax_enrollment_docs",
    "Small Talk - Greeting": "smalltalk_greeting",
    "Small Talk - Thanks": "smalltalk_thanks",
    "Small Talk - Goodbye": "smalltalk_goodbye",
    "Small Talk - How Are You": "smalltalk_how_are_you",
    "Small Talk - Weather": "smalltalk_weather",
    "Small Talk - Wait": "smalltalk_wait",
}


def map_llm_intent_to_insurance_template(raw: str) -> str:
    """Cosmos insurance template key for scripted CSR / small talk (simulator / tasks)."""
    s = (raw or "").strip()
    if s in INSURANCE_TEMPLATE_BY_CLASSIFIER:
        return INSURANCE_TEMPLATE_BY_CLASSIFIER[s]
    low = s.lower()
    for k, v in INSURANCE_TEMPLATE_BY_CLASSIFIER.items():
        if k.lower() == low:
            return v
    return "fallback_human"


def map_llm_intent_to_portal(raw: str) -> str:
    """Normalize LLM output to a portal/RAG intent key."""
    s = (raw or "").strip()
    if s in PORTAL_INTENT_BY_CLASSIFIER:
        return PORTAL_INTENT_BY_CLASSIFIER[s]
    low = s.lower()
    for k, v in PORTAL_INTENT_BY_CLASSIFIER.items():
        if k.lower() == low:
            return v
    return "GENERAL_QUERY"


def _chat_client_and_model():
    """Prefer Azure OpenAI, then OpenAI.com, then local Ollama (OpenAI-compatible)."""
    if settings.use_local_llm:
        from openai import OpenAI

        return (
            OpenAI(
                base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
                api_key="ollama",
            ),
            settings.ollama_model,
        )
    if (settings.azure_openai_key or "").strip() and (settings.azure_openai_endpoint or "").strip():
        from openai import AzureOpenAI

        return (
            AzureOpenAI(
                api_key=settings.azure_openai_key,
                azure_endpoint=settings.azure_openai_endpoint.rstrip("/"),
                api_version=settings.azure_openai_api_version,
            ),
            settings.azure_openai_deployment_name,
        )
    okey = (settings.openai_api_key or "").strip()
    if okey:
        from openai import OpenAI

        return OpenAI(api_key=okey), "gpt-4o"
    raise RuntimeError(
        "No LLM for intent classification: configure Azure OpenAI, OPENAI_API_KEY, or USE_LOCAL_LLM."
    )


try:
    from openai import APIConnectionError, RateLimitError
except ImportError:
    RateLimitError = Exception  # type: ignore[misc, assignment]
    APIConnectionError = Exception  # type: ignore[misc, assignment]


@retry(
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(5),
)
def classify_intent_with_retry(user_text: str) -> str:
    """
    Classify caller text into exactly one of CLASSIFIER_INTENT_LABELS using the configured LLM.
    """
    client, model = _chat_client_and_model()
    allowed = ", ".join(CLASSIFIER_INTENT_LABELS)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    f"Select exactly one intent from this list: {allowed}. "
                    "Reply with ONLY the intent name, nothing else."
                ),
            },
            {"role": "user", "content": f"Classify this insurance member utterance:\n{user_text}"},
        ],
        temperature=0.0,
        timeout=12.0,
    )
    label = (response.choices[0].message.content or "").strip()
    if label in CLASSIFIER_INTENT_LABELS:
        return label
    low = label.lower()
    for allowed in CLASSIFIER_INTENT_LABELS:
        if allowed.lower() == low:
            return allowed
    raise ValueError(f"Unsupported classifier label: {label}")


_intent_log_container = None


def _get_intent_log_container():
    global _intent_log_container
    if _intent_log_container is not None:
        return _intent_log_container
    from azure.cosmos import PartitionKey

    from config.azure_clients import get_cosmos_client

    dbn = (settings.cosmos_db_database or "").strip() or "voice_navigator"
    client = get_cosmos_client()
    db = client.get_database_client(dbn)
    _intent_log_container = db.create_container_if_not_exists(
        id=settings.cosmos_db_container_calls,
        partition_key=PartitionKey(path="/call_id"),
    )
    return _intent_log_container


def save_intent_to_cosmos(
    user_text: str,
    intent_label: str,
    *,
    call_id: str,
) -> Optional[str]:
    """
    Append an intent-classification record to the Cosmos `calls` container (partition: call_id).
    Returns the new item id, or None if Cosmos is unavailable.
    """
    try:
        ctr = _get_intent_log_container()
        evt_id = str(uuid.uuid4())
        portal_intent = map_llm_intent_to_portal(intent_label)
        body: dict[str, Any] = {
            "id": evt_id,
            "call_id": call_id,
            "type": "intent_classification",
            "user_text": (user_text or "")[:8000],
            "intent": intent_label,
            "intent_portal": portal_intent,
            "intent_insurance_template": map_llm_intent_to_insurance_template(intent_label),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        ctr.upsert_item(body)
        return evt_id
    except Exception as e:
        logger.warning("intent_cosmos_save_failed", error=str(e))
        return None


def notify_next_service(
    intent: str,
    user_input_text: str,
    call_id: Optional[str],
) -> dict[str, Any]:
    """
    Optional HTTP POST to INTENT_SERVICE_URL when operators want an external system notified
    after classification (in addition to in-process RAG in CallOrchestrator).
    """
    url = (settings.intent_service_url or "").strip()
    if not url:
        return {"notified": False, "reason": "intent_service_url not set"}
    headers = {"Content-Type": "application/json"}
    if (settings.intent_service_api_key or "").strip():
        headers["Authorization"] = f"Bearer {settings.intent_service_api_key.strip()}"
    payload = {
        "intent": intent,
        "intent_portal": map_llm_intent_to_portal(intent),
        "intent_insurance_template": map_llm_intent_to_insurance_template(intent),
        "user_text": user_input_text,
        "call_id": call_id,
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        return {
            "notified": True,
            "status_code": r.status_code,
            "body_preview": (r.text or "")[:500],
        }
    except Exception as e:
        logger.warning("intent_webhook_failed", error=str(e))
        return {"notified": False, "error": str(e)}


def run_pipeline(user_input_text: str, *, call_id: str = "cli-test") -> dict[str, Any]:
    """CLI / test harness: classify, persist, optional webhook."""
    logger.info("pipeline_start", call_id=call_id)
    try:
        intent = classify_intent_with_retry(user_input_text)
        logger.info("pipeline_intent", intent=intent)
        evt = save_intent_to_cosmos(user_input_text, intent, call_id=call_id)
        api_result = notify_next_service(intent, user_input_text, call_id)
        return {
            "status": "Success",
            "intent": intent,
            "intent_portal": map_llm_intent_to_portal(intent),
            "call_id": evt or call_id,
            "api_response": api_result,
        }
    except Exception as e:
        logger.exception("pipeline_failed")
        return {"status": "Error", "message": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample = (
        "I need to check the status of my physical therapy claim from last week."
    )
    print(run_pipeline(sample))
