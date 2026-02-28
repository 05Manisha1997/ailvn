"""
config/settings.py
Central configuration using Pydantic Settings.
All values come from environment variables / .env file.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from typing import Literal


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_secret_key: str = "change-me-to-random-32-char-string"
    log_level: str = "INFO"
    max_call_duration_seconds: int = 1800

    # ── Azure Speech ──────────────────────────────────
    azure_speech_key: str = ""
    azure_speech_region: str = "eastus"
    azure_speech_language: str = "en-US"

    # ── Azure OpenAI ──────────────────────────────────
    azure_openai_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment_name: str = "gpt-4o"
    azure_openai_embedding_deployment: str = "text-embedding-ada-002"
    use_local_llm: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"

    # ── Azure Communication Services ──────────────────
    azure_comm_connection_string: str = ""
    azure_comm_sender_email: str = ""

    # ── Azure Cosmos DB ───────────────────────────────
    cosmos_db_endpoint: str = ""
    cosmos_db_key: str = ""
    cosmos_db_database: str = "voice_navigator"
    cosmos_db_container_calls: str = "calls"
    cosmos_db_container_templates: str = "response_templates"

    # ── Azure Blob Storage ────────────────────────────
    azure_storage_connection_string: str = ""
    azure_storage_container_docs: str = "voice-nav-docs"

    # ── Cosmos DB Session Storage (Temporary) ─────────
    cosmos_db_container_sessions: str = "sessions"
    cosmos_db_session_ttl_seconds: int = 3600

    # ── ChromaDB ──────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_persist_directory: str = "./chroma_data"

    # ── ElevenLabs ────────────────────────────────────
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model_id: str = "eleven_turbo_v2"

    # ── Twilio ────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    use_twilio_lookup: bool = False

    # ── Genesys Cloud ─────────────────────────────────
    genesys_client_id: str = ""
    genesys_client_secret: str = ""
    genesys_environment: str = "mypurecloud.com"
    genesys_queue_id: str = ""
    genesys_vip_queue_id: str = ""

    # ── AI/RAG Tuning ─────────────────────────────────
    intent_confidence_threshold: float = 0.75
    rag_top_k_chunks: int = 5
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 50
    summary_max_tokens: int = 500

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
