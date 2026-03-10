"""
database/cosmos_client.py
Cosmos DB client wrapper for policyholder profile reads/writes.
"""
import json
from typing import Optional
from config import settings

try:
    from azure.cosmos import CosmosClient, exceptions as cosmos_exceptions
    COSMOS_AVAILABLE = True
except ImportError:
    COSMOS_AVAILABLE = False


class PolicyholderDB:
    """Wraps Azure Cosmos DB for policyholder CRUD."""

    def __init__(self):
        self._client = None
        self._container = None
        if COSMOS_AVAILABLE and settings.cosmos_endpoint and settings.cosmos_key:
            try:
                self._client = CosmosClient(
                    settings.cosmos_endpoint, credential=settings.cosmos_key
                )
                db = self._client.get_database_client(settings.cosmos_database)
                self._container = db.get_container_client(settings.cosmos_container)
            except Exception as e:
                print(f"Warning: Could not initialize Cosmos DB client: {e}")
                self._client = None
                self._container = None

    def get_policyholder(self, policy_id: str) -> Optional[dict]:
        """Retrieve a policyholder by policy ID."""
        if self._container is None:
            return None
        try:
            return self._container.read_item(
                item=policy_id, partition_key=policy_id
            )
        except Exception:
            return None

    def upsert_policyholder(self, record: dict) -> dict:
        """Create or update a policyholder record."""
        if self._container is None:
            raise RuntimeError("Cosmos DB not configured")
        return self._container.upsert_item(record)

    def list_policyholders(self, limit: int = 100) -> list[dict]:
        """List all policyholders (for admin/dashboard use)."""
        if self._container is None:
            return []
        query = f"SELECT * FROM c OFFSET 0 LIMIT {limit}"
        return list(
            self._container.query_items(
                query=query, enable_cross_partition_query=True
            )
        )


# Singleton instance
db = PolicyholderDB()
