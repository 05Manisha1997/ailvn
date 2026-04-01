"""
database/cosmos_client.py
Cosmos DB client wrapper for policyholder profile reads/writes (verification source of truth).
"""
from __future__ import annotations

from typing import ClassVar, Optional

from config import settings

try:
    from azure.cosmos import PartitionKey
    from config.azure_clients import get_cosmos_client

    COSMOS_AVAILABLE = True
except ImportError:
    COSMOS_AVAILABLE = False
    get_cosmos_client = None  # type: ignore


def _database_id() -> str:
    return (
        (settings.cosmos_database or settings.cosmos_db_database or "voice_navigator").strip()
        or "voice_navigator"
    )


def _cosmos_credentials_present() -> bool:
    """True if endpoint+key or a full connection string is configured."""
    conn = (getattr(settings, "cosmos_db_connection_string", None) or "").strip()
    if conn and "accountkey=" in conn.lower():
        return True
    ep = (settings.cosmos_endpoint or "").strip()
    key = (settings.cosmos_key or "").strip()
    if "accountendpoint=" in ep.lower() and "accountkey=" in ep.lower():
        return True
    return bool(ep and key)


class PolicyholderDB:
    """Wraps Azure Cosmos DB for policyholder CRUD (container: settings.cosmos_container)."""

    last_init_error: ClassVar[Optional[str]] = None

    def __init__(self):
        self._container = None
        PolicyholderDB.last_init_error = None
        if not COSMOS_AVAILABLE or not get_cosmos_client:
            PolicyholderDB.last_init_error = "Azure Cosmos SDK not installed"
            return
        if not _cosmos_credentials_present():
            PolicyholderDB.last_init_error = "Missing COSMOS_DB_ENDPOINT + COSMOS_DB_KEY (or COSMOS_DB_CONNECTION_STRING)"
            return
        try:
            client = get_cosmos_client()
            database = client.create_database_if_not_exists(id=_database_id())
            self._container = database.create_container_if_not_exists(
                id=settings.cosmos_container,
                partition_key=PartitionKey(path="/member_id"),
            )
        except Exception as e:
            PolicyholderDB.last_init_error = str(e)
            print(f"Warning: Could not initialize policyholders Cosmos container: {e}")
            self._container = None

    def get_policyholder(self, member_id: str) -> Optional[dict]:
        """Retrieve a policyholder by member_id (id and partition value)."""
        if self._container is None:
            return None
        key = member_id.strip().upper()
        if not key:
            return None
        try:
            return self._container.read_item(item=key, partition_key=key)
        except Exception:
            return None

    def find_by_email_and_dob(self, email: str, dob: str) -> Optional[dict]:
        """Cross-partition lookup for verification when member_id is unknown."""
        if self._container is None or not email or not dob:
            return None
        em = email.lower().strip()
        d_clean = dob.strip()
        query = "SELECT * FROM c WHERE LOWER(c.email) = @em AND c.dob = @dob"
        params = [{"name": "@em", "value": em}, {"name": "@dob", "value": d_clean}]
        try:
            it = self._container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
            for doc in it:
                return doc
        except Exception:
            return None
        return None

    def upsert_policyholder(self, record: dict) -> dict:
        if self._container is None:
            raise RuntimeError("Cosmos DB not configured")
        return self._container.upsert_item(record)

    def list_policyholders(self, limit: int = 100) -> list[dict]:
        if self._container is None:
            return []
        query = f"SELECT * FROM c OFFSET 0 LIMIT {int(limit)}"
        return list(
            self._container.query_items(query=query, enable_cross_partition_query=True)
        )


db = PolicyholderDB()
