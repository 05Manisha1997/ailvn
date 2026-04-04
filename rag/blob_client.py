import os
import json
from config.settings import get_settings
from azure.storage.blob import BlobServiceClient
try:
    from azure.identity import DefaultAzureCredential
except ImportError:
    DefaultAzureCredential = None

settings = get_settings()
_client = None

def _get_blob_service_client():
    """Initializes and returns the BlobServiceClient, preferring Managed Identity (DefaultAzureCredential)."""
    global _client
    if _client:
        return _client

    conn_str = settings.azure_storage_connection_string
    if conn_str:
        try:
            _client = BlobServiceClient.from_connection_string(conn_str)
            print(f"[BlobClient] Successfully initialized with Connection String.")
            return _client
        except Exception as e:
            print(f"[BlobClient] Failed to initialize with connection string: {e}")

    # Fallback to Managed Identity (DefaultAzureCredential)
    account_name = settings.azure_storage_account_name or "voicenavigatorstg01"
    url = f"https://{account_name}.blob.core.windows.net"

    if DefaultAzureCredential:
        try:
            cred = DefaultAzureCredential()
            _client = BlobServiceClient(account_url=url, credential=cred)
            print(f"[BlobClient] Successfully initialized with Managed Identity: {url}")
            return _client
        except Exception as e:
            print(f"[BlobClient] Failed to initialize with Managed Identity: {e}")
            _client = None
    
    return None


def fetch_json_blob(container_name: str, blob_name: str) -> list | dict | None:
    """Download and parse a JSON blob from Azure Blob Storage."""
    svc = _get_blob_service_client()
    if not svc:
        return None
    try:
        blob_client = svc.get_blob_client(container=container_name, blob=blob_name)
        data = blob_client.download_blob().readall()
        return json.loads(data)
    except Exception as e:
        print(f"[BlobClient] Failed to fetch {blob_name} from {container_name}: {e}")
        return None


def list_blobs(container_name: str) -> list[str]:
    """List all blobs in a container."""
    svc = _get_blob_service_client()
    if not svc:
        return []
    try:
        container_client = svc.get_container_client(container=container_name)
        return [b.name for b in container_client.list_blobs()]
    except Exception as e:
        print(f"[BlobClient] Failed to list blobs in {container_name}: {e}")
        return []


def fetch_blob_text(container_name: str, blob_name: str) -> str | None:
    """Download a text blob from Azure Blob Storage."""
    svc = _get_blob_service_client()
    if not svc:
        return None
    try:
        blob_client = svc.get_blob_client(container=container_name, blob=blob_name)
        data = blob_client.download_blob().readall()
        return data.decode("utf-8")
    except Exception as e:
        print(f"[BlobClient] Failed to fetch {blob_name} text from {container_name}: {e}")
        return None


def fetch_policy_kb(member_id: str = None) -> list[dict] | None:
    """
    Fetch policy knowledge. If member_id is provided, look for a specific member .txt file
    as a fallback if the general JSON isn't found.
    """
    container = settings.azure_storage_container_docs or "rag-docs"
    
    # 1. Try general JSON first
    json_data = fetch_json_blob(container, "policy_kb.json")
    if json_data:
        return json_data

    # 2. Try specific member file if member_id is valid
    if member_id and member_id != "unknown":
        # Formats: POL-001.txt or POL001.txt
        for suffix in [".txt", ".json"]:
            filename = f"{member_id}{suffix}"
            text = fetch_blob_text(container, filename)
            if text:
                # Wrap it in a structure matching our RAG tool's expectations
                return [{"section": "Individual Policy", "content": text, "keywords": ["coverage", "hospital", "surgery", "benefit"]}]

    return None



def fetch_members() -> dict[str, dict] | None:
    """Fetch the members dataset from Blob Storage."""
    container = settings.azure_storage_container_docs or "rag-docs"
    data = fetch_json_blob(container, "members.json")
    if data is None:
        return None
    if isinstance(data, list):
        return {
            str(item.get("member_id") or item.get("policy_id") or item.get("id", "")).upper(): item
            for item in data
        }
    return data
