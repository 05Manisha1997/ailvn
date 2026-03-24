"""Central configuration — loaded once at startup from environment / .env file."""
import os
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # Azure Communication Services
    acs_connection_string: str = Field(default="", env="ACS_CONNECTION_STRING")
    acs_callback_base_url: str = Field(default="http://localhost:8000", env="ACS_CALLBACK_BASE_URL")

    # Azure OpenAI
    azure_openai_endpoint: str = Field(default="", env="AZURE_OPENAI_ENDPOINT")
    azure_openai_key: str = Field(default="", env="AZURE_OPENAI_KEY")
    azure_openai_deployment: str = Field(default="gpt-4o", env="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_embedding_deployment: str = Field(
        default="text-embedding-3-large", env="AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
    )
    azure_openai_api_version: str = Field(
        default="2024-08-01-preview", env="AZURE_OPENAI_API_VERSION"
    )

    # Azure AI Search
    azure_search_endpoint: str = Field(default="", env="AZURE_SEARCH_ENDPOINT")
    azure_search_key: str = Field(default="", env="AZURE_SEARCH_KEY")
    azure_search_index: str = Field(default="insurance-policies", env="AZURE_SEARCH_INDEX")

    # Azure Cosmos DB
    cosmos_endpoint: str = Field(default="", env="COSMOS_ENDPOINT")
    cosmos_key: str = Field(default="", env="COSMOS_KEY")
    cosmos_database: str = Field(default="insurance_db", env="COSMOS_DATABASE")
    cosmos_container: str = Field(default="policyholders", env="COSMOS_CONTAINER")

    # Azure Speech
    azure_speech_key: str = Field(default="", env="AZURE_SPEECH_KEY")
    azure_speech_region: str = Field(default="eastus", env="AZURE_SPEECH_REGION")

    # External Intent Service
    intent_service_url: str = Field(default="", env="INTENT_SERVICE_URL")
    intent_service_api_key: str = Field(default="", env="INTENT_SERVICE_API_KEY")

    # Azure Cognitive Services
    azure_cognitive_endpoint: str = Field(default="", env="AZURE_COGNITIVE_ENDPOINT")

    # ElevenLabs
    elevenlabs_api_key: str = Field(default="", env="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(
        default="21m00Tcm4TlvDq8ikWAM", env="ELEVENLABS_VOICE_ID"
    )

    # App
    app_host: str = Field(default="0.0.0.0", env="APP_HOST")
    app_port: int = Field(default=8000, env="APP_PORT")
    debug: bool = Field(default=True, env="DEBUG")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
