"""
config/settings.py
Single settings model for the whole app. Each Azure resource should be set once;
duplicate legacy env names (e.g. COSMOS_ENDPOINT vs COSMOS_DB_ENDPOINT) are accepted as aliases.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip_env_quotes(val: str) -> str:
    v = (val or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1].strip()
    return v


def _plausible_cosmos_endpoint(val: str) -> bool:
    """Reject doc placeholders (e.g. acct.documents.azure.com) that often override a real .env URL."""
    v = _strip_env_quotes(val or "").strip().lower()
    if not v or ".documents.azure.com" not in v:
        return False
    if "://acct.documents.azure.com" in v or v.startswith("https://acct."):
        return False
    if "<account>" in v or "your-account" in v or "example.documents" in v:
        return False
    return True


def _plausible_cosmos_account_key(val: str) -> bool:
    """
    Ignore shell-wide placeholders (e.g. COSMOS_DB_KEY=secret) that would override
    a real key from .env and break Cosmos SDK with 'Incorrect padding'.
    """
    v = _strip_env_quotes(val or "")
    if len(v) < 40:
        return False
    if v.lower() in frozenset(
        {"secret", "changeme", "placeholder", "your-key-here", "<key>", "none"}
    ):
        return False
    return True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_secret_key: str = "change-me-to-random-32-char-string"
    log_level: str = "INFO"
    max_call_duration_seconds: int = 1800
    debug: bool = False

    # ── Azure Communication Services ─────────────────
    acs_connection_string: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ACS_CONNECTION_STRING",
            "AZURE_COMM_CONNECTION_STRING",
        ),
    )
    acs_callback_base_url: str = Field(
        default="http://localhost:8000",
        validation_alias="ACS_CALLBACK_BASE_URL",
    )
    azure_comm_sender_email: str = ""
    sendgrid_api_key: str = ""

    # ── Azure OpenAI ─────────────────────────────────
    azure_openai_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment_name: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices(
            "AZURE_OPENAI_DEPLOYMENT_NAME",
            "AZURE_OPENAI_DEPLOYMENT",
        ),
    )
    azure_openai_embedding_deployment: str = Field(
        default="text-embedding-ada-002",
        validation_alias=AliasChoices(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME",
        ),
    )
    azure_openai_api_version: str = Field(
        default="2024-08-01-preview",
        validation_alias="AZURE_OPENAI_API_VERSION",
    )
    use_local_llm: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"
    # Public OpenAI API (optional; prefer Azure OpenAI when configured)
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai-api-key"),
    )

    # ── Azure AI Search ──────────────────────────────
    azure_search_endpoint: str = ""
    azure_search_key: str = ""
    azure_search_index: str = "insurance-policies"

    # ── Azure Cosmos DB ─────────────────────────────
    # Azure Container Apps often only allows lowercase + hyphens for env names.
    # Prefer: cosmos-db-endpoint, cosmos-db-key, cosmos-db-database, …
    cosmos_db_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "cosmos-db-endpoint",
            "COSMOS_DB_ENDPOINT",
            "COSMOS_ENDPOINT",
            "COSMOS-DB-ENDPOINT",
        ),
    )
    cosmos_db_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "cosmos-db-key",
            "COSMOS_DB_KEY",
            "COSMOS_KEY",
            "COSMOS-DB-KEY",
        ),
    )
    cosmos_db_connection_string: str = Field(
        default="",
        validation_alias=AliasChoices(
            "cosmos-db-connection-string",
            "COSMOS_DB_CONNECTION_STRING",
        ),
    )
    cosmos_db_database: str = Field(
        default="voice_navigator",
        validation_alias=AliasChoices(
            "cosmos-db-database",
            "COSMOS_DB_DATABASE",
        ),
    )
    cosmos_db_container_calls: str = Field(
        default="calls",
        validation_alias=AliasChoices(
            "cosmos-db-container-calls",
            "COSMOS_DB_CONTAINER_CALLS",
        ),
    )
    cosmos_db_container_templates: str = Field(
        default="response_templates",
        validation_alias=AliasChoices(
            "cosmos-db-container-templates",
            "COSMOS_DB_CONTAINER_TEMPLATES",
        ),
    )
    cosmos_db_container_sessions: str = Field(
        default="sessions",
        validation_alias=AliasChoices(
            "cosmos-db-container-sessions",
            "COSMOS_DB_CONTAINER_SESSIONS",
        ),
    )
    cosmos_db_session_ttl_seconds: int = 3600

    # Legacy names: policy / identity DB (can match cosmos_db_database)
    cosmos_database: str = Field(
        default="",
        validation_alias=AliasChoices("cosmos-database", "COSMOS_DATABASE"),
    )
    cosmos_container: str = Field(
        default="policyholders",
        validation_alias=AliasChoices("cosmos-container", "COSMOS_CONTAINER"),
    )

    # ── Azure Blob Storage ───────────────────────────
    azure_storage_connection_string: str = ""
    azure_storage_container_docs: str = "voice-nav-docs"

    # ── ChromaDB ────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_persist_directory: str = "./chroma_data"

    # ── Azure Speech ─────────────────────────────────
    azure_speech_key: str = ""
    azure_speech_region: str = "eastus"
    azure_speech_language: str = "en-US"

    # ── Azure Cognitive (ACS automation) ───────────
    azure_cognitive_endpoint: str = ""

    # ── External intent service ─────────────────────
    intent_service_url: str = ""
    intent_service_api_key: str = ""

    # ── ElevenLabs ───────────────────────────────────
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model_id: str = "eleven_turbo_v2"

    # ── Twilio ───────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    use_twilio_lookup: bool = False

    # ── Genesys Cloud ────────────────────────────────
    genesys_client_id: str = ""
    genesys_client_secret: str = ""
    genesys_environment: str = "mypurecloud.com"
    genesys_queue_id: str = ""
    genesys_vip_queue_id: str = ""

    # ── AI / RAG tuning ─────────────────────────────
    intent_confidence_threshold: float = 0.75
    rag_top_k_chunks: int = 5
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 50
    summary_max_tokens: int = 500

    @field_validator("cosmos_db_key", mode="after")
    @classmethod
    def recover_cosmos_db_key_from_dotenv_if_stub(cls, v: str) -> str:
        """When OS env overrides .env with a short placeholder (e.g. secret), use .env key."""
        s = _strip_env_quotes(str(v or ""))
        if _plausible_cosmos_account_key(s):
            return s
        try:
            from dotenv import dotenv_values

            p = Path(".env")
            if p.is_file():
                fv = dotenv_values(p)
                for fk in ("COSMOS_DB_KEY", "COSMOS_KEY"):
                    raw = fv.get(fk)
                    if raw and _plausible_cosmos_account_key(str(raw)):
                        return _strip_env_quotes(str(raw))
        except Exception:
            pass
        return s

    @field_validator("cosmos_db_endpoint", mode="after")
    @classmethod
    def recover_cosmos_db_endpoint_from_dotenv_if_stub(cls, v: str) -> str:
        """When OS env overrides .env with a template host (e.g. acct.documents.azure.com), use .env."""
        s = _strip_env_quotes(str(v or "")).strip()
        if _plausible_cosmos_endpoint(s):
            return s
        try:
            from dotenv import dotenv_values

            p = Path(".env")
            if p.is_file():
                fv = dotenv_values(p)
                for fk in ("COSMOS_DB_ENDPOINT", "COSMOS_ENDPOINT"):
                    raw = fv.get(fk)
                    if raw and _plausible_cosmos_endpoint(str(raw)):
                        return _strip_env_quotes(str(raw)).strip()
        except Exception:
            pass
        return s

    @staticmethod
    def _normalize_env_key(key: str) -> str:
        return key.strip().lower().replace("-", "_")

    @model_validator(mode="after")
    def merge_cosmos_from_os_environ(self) -> Settings:
        """
        Azure Container Apps often injects only lowercase hyphenated names.
        Read Cosmos-related keys directly from os.environ (normalized) so values are never dropped.
        Process env wins over .env / pydantic alias quirks when the same logical key is set.
        """
        updates: dict = {}
        for raw_key, raw_val in os.environ.items():
            nk = self._normalize_env_key(raw_key)
            val = (raw_val or "").strip()
            if not val:
                continue
            if nk in ("cosmos_db_endpoint", "cosmos_endpoint"):
                if not _plausible_cosmos_endpoint(val):
                    continue
                updates["cosmos_db_endpoint"] = val
            elif nk in ("cosmos_db_key", "cosmos_key"):
                if not _plausible_cosmos_account_key(val):
                    continue
                updates["cosmos_db_key"] = val
            elif nk == "cosmos_db_connection_string":
                updates["cosmos_db_connection_string"] = val
            elif nk == "cosmos_db_database":
                updates["cosmos_db_database"] = val
            elif nk == "cosmos_database":
                updates["cosmos_database"] = val
            elif nk == "cosmos_db_container_templates":
                updates["cosmos_db_container_templates"] = val
            elif nk == "cosmos_db_container_calls":
                updates["cosmos_db_container_calls"] = val
            elif nk == "cosmos_db_container_sessions":
                updates["cosmos_db_container_sessions"] = val
            elif nk == "cosmos_container":
                updates["cosmos_container"] = val

        if updates:
            return self.model_copy(update=updates)
        return self

    @model_validator(mode="after")
    def align_cosmos_database_defaults(self) -> Settings:
        if not self.cosmos_database.strip():
            return self.model_copy(update={"cosmos_database": self.cosmos_db_database})
        return self

    @property
    def azure_comm_connection_string(self) -> str:
        """Same ACS resource as ``acs_connection_string`` (email/SMS SDK paths)."""
        return self.acs_connection_string

    @property
    def azure_openai_deployment(self) -> str:
        """Alias for code that expects ``azure_openai_deployment`` (chat deployment name)."""
        return self.azure_openai_deployment_name

    @property
    def cosmos_endpoint(self) -> str:
        """Alias for modules that use ``cosmos_endpoint``."""
        return self.cosmos_db_endpoint

    @property
    def cosmos_key(self) -> str:
        """Alias for modules that use ``cosmos_key``."""
        return self.cosmos_db_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
