"""
config/azure_clients.py
Lazy-initialized Azure SDK client factories.
Import these instead of creating clients inline.
"""
from functools import lru_cache
from config.settings import get_settings

settings = get_settings()


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
            api_version="2024-02-01",
        )


@lru_cache()
def get_cosmos_client():
    """Azure Cosmos DB client."""
    from azure.cosmos import CosmosClient
    return CosmosClient(
        url=settings.cosmos_db_endpoint,
        credential=settings.cosmos_db_key,
    )


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
