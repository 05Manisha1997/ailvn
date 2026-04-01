"""
config/azure_clients.py
Lazy-initialized Azure SDK client factories.
Import these instead of creating clients inline.
"""
from __future__ import annotations

import re
from functools import lru_cache
from config.settings import get_settings

settings = get_settings()


def _strip_wrapping_quotes(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1].strip()
    return s


def _normalize_cosmos_account_key(raw: str) -> str:
    """
    Cosmos account keys are base64 and normally end with '=' padding.
    Some env loaders or copy-paste drops or duplicates '='; strip all trailing
    padding and re-apply the correct amount so the SDK always gets valid base64.
    """
    key = _strip_wrapping_quotes(raw or "")
    if key.startswith("\ufeff"):
        key = key.lstrip("\ufeff")
    key = "".join(key.split())
    key = key.rstrip("=")
    if not key:
        return key
    rem = len(key) % 4
    if rem:
        key += "=" * (4 - rem)
    return key


def _cosmos_connection_string_from_parts(endpoint: str, account_key: str) -> str:
    ep = _strip_wrapping_quotes(endpoint or "")
    if ep.startswith("\ufeff"):
        ep = ep.lstrip("\ufeff")
    ep = ep.strip()
    key = _normalize_cosmos_account_key(account_key)
    if not ep or not key:
        raise ValueError("COSMOS_DB_ENDPOINT and COSMOS_DB_KEY must be set")
    if not ep.endswith("/"):
        ep += "/"
    return f"AccountEndpoint={ep};AccountKey={key};"


def _cosmos_connection_string_from_full(raw: str) -> str:
    """Rebuild connection string with a normalized AccountKey (fixes padding / bad paste)."""
    conn = "".join(_strip_wrapping_quotes(raw or "").split())
    ep_m = re.search(r"AccountEndpoint=([^;]+)", conn, flags=re.I)
    key_m = re.search(r"AccountKey=([^;]+)", conn, flags=re.I)
    if not ep_m or not key_m:
        raise ValueError("Cosmos connection string must include AccountEndpoint and AccountKey")
    ep = ep_m.group(1).strip()
    key = _normalize_cosmos_account_key(key_m.group(1))
    if not ep.endswith("/"):
        ep += "/"
    return f"AccountEndpoint={ep};AccountKey={key};"


def _resolve_cosmos_connection_string() -> str:
    s = get_settings()
    dedicated = _strip_wrapping_quotes(s.cosmos_db_connection_string or "")
    if dedicated and "accountendpoint=" in dedicated.lower() and "accountkey=" in dedicated.lower():
        return _cosmos_connection_string_from_full(dedicated)

    ep_raw = (s.cosmos_db_endpoint or "").strip()
    key_raw = (s.cosmos_db_key or "").strip()
    if "accountendpoint=" in ep_raw.lower() and "accountkey=" in ep_raw.lower():
        return _cosmos_connection_string_from_full(ep_raw)
    return _cosmos_connection_string_from_parts(ep_raw, key_raw)


@lru_cache()
def get_speech_config():
    """Azure Speech SDK config with noise suppression enabled."""
    import azure.cognitiveservices.speech as speechsdk
    config = speechsdk.SpeechConfig(
        subscription=settings.azure_speech_key,
        region=settings.azure_speech_region,
    )
    config.speech_recognition_language = settings.azure_speech_language
    # Enable noise suppression (built-in, no extra cost)
    config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "5000"
    )
    config.set_service_property(
        "speechcontext-PhraseDetection.EETW.enabled", "true",
        speechsdk.ServicePropertyChannel.UriQueryParameter
    )
    # Noise suppression mode: Low=1, High=2
    config.set_property(
        speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "500"
    )
    return config


@lru_cache()
def get_openai_client():
    """Azure OpenAI or Ollama client depending on USE_LOCAL_LLM."""
    if settings.use_local_llm:
        from openai import OpenAI
        return OpenAI(
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",  # Ollama doesn't need a real key
        )
    else:
        from openai import AzureOpenAI
        return AzureOpenAI(
            api_key=settings.azure_openai_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )


@lru_cache()
def get_cosmos_client():
    """Azure Cosmos DB client (connection string avoids URL/credential parse issues)."""
    from azure.cosmos import CosmosClient

    conn = _resolve_cosmos_connection_string()
    return CosmosClient.from_connection_string(conn)


@lru_cache()
def get_cosmos_containers():
    """Returns (calls_container, templates_container)."""
    client = get_cosmos_client()
    db = client.get_database_client(settings.cosmos_db_database)
    calls = db.get_container_client(settings.cosmos_db_container_calls)
    templates = db.get_container_client(settings.cosmos_db_container_templates)
    return calls, templates


@lru_cache()
def get_blob_service_client():
    """Azure Blob Storage client."""
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(
        settings.azure_storage_connection_string
    )


def get_chroma_client():
    """ChromaDB client (HTTP client pointing to Docker container)."""
    import chromadb
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
    )
