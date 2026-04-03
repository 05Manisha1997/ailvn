"""
portal/insurance_portal.py

Cosmos-backed portal service for insurance response templates/intents.
Falls back to in-memory defaults when Cosmos is unavailable.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from config import settings
from utils.logger import logger


@dataclass
class InsuranceTemplate:
    intent: str
    template: str
    voice_id: Optional[str] = None
    enabled: bool = True
    doc_sources: list[dict] = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if self.doc_sources is None:
            self.doc_sources = []
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


DEFAULT_INSURANCE_TEMPLATES: dict[str, InsuranceTemplate] = {
    "hospital_covered": InsuranceTemplate(
        intent="hospital_covered",
        template="Your policy covers {rag.coverage_pct} of treatment costs at {rag.hospital_name}, up to a maximum of {rag.max_limit}.",
    ),
    "hospital_not_in_network": InsuranceTemplate(
        intent="hospital_not_in_network",
        template="{rag.hospital_name} is not within your network. Out-of-pocket costs may apply. Your nearest in-network facility is {rag.nearest_network_hospital}.",
    ),
    "treatment_covered": InsuranceTemplate(
        intent="treatment_covered",
        template="{rag.treatment_type} is covered under your plan at {rag.coverage_pct}, with a benefit limit of {rag.limit} per year.",
    ),
    "treatment_not_covered": InsuranceTemplate(
        intent="treatment_not_covered",
        template="{rag.treatment_type} is not covered under your current {rag.plan_name} plan.",
    ),
    "deductible_status": InsuranceTemplate(
        intent="deductible_status",
        template="Your annual deductible is {rag.deductible_amount}. You have {rag.deductible_remaining} remaining before full coverage activates.",
    ),
    "claim_limit_remaining": InsuranceTemplate(
        intent="claim_limit_remaining",
        template="You have {rag.remaining_limit} remaining in your {rag.benefit_category} benefit for this policy year.",
    ),
    "insurance_claim_status": InsuranceTemplate(
        intent="insurance_claim_status",
        template="Your claim {rag.claim_id} is currently {rag.claim_status}. Last update: {rag.last_update}.",
    ),
    "insurance_claim_documents": InsuranceTemplate(
        intent="insurance_claim_documents",
        template="To process your claim, please upload {rag.required_documents}. You can submit these through the member portal.",
    ),
    "insurance_claim_timeline": InsuranceTemplate(
        intent="insurance_claim_timeline",
        template="Claim processing usually takes {rag.processing_time}. Your expected completion date is {rag.expected_date}.",
    ),
    "fallback_human": InsuranceTemplate(
        intent="fallback_human",
        template=(
            "I'm not fully confident I have the right answer for you on that. "
            "If you'd like, you can choose below to have a team member take over — "
            "they'll see this conversation on their screen so you won't have to repeat everything."
        ),
    ),
    "request_live_agent": InsuranceTemplate(
        intent="request_live_agent",
        template=(
            "I'll get you through to a team member. They'll see this conversation on the portal "
            "with full context."
        ),
    ),
}


def _csr_smalltalk_seed_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "csr_smalltalk_seed.json")


def _templates_from_json_seed() -> list[InsuranceTemplate]:
    """CSR + small-talk rows for Cosmos only — not merged into DEFAULT_INSURANCE_TEMPLATES."""
    path = _csr_smalltalk_seed_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        logger.warning("csr_smalltalk_seed_read_failed", path=path, error=str(e))
        return []
    out: list[InsuranceTemplate] = []
    for row in payload.get("templates") or []:
        if not row.get("intent") or row.get("template") is None:
            continue
        out.append(
            InsuranceTemplate(
                intent=str(row["intent"]).strip(),
                template=str(row["template"]),
                voice_id=row.get("voice_id"),
                enabled=bool(row.get("enabled", True)),
                doc_sources=list(row.get("doc_sources") or []),
            )
        )
    return out


def _upsert_json_seed_missing(container, existing: set) -> int:
    """Insert seed JSON templates whose intent id is not yet in ``existing``."""
    added = 0
    for t in _templates_from_json_seed():
        if t.intent not in existing:
            container.upsert_item({**asdict(t), "id": t.intent})
            existing.add(t.intent)
            added += 1
    return added


class InsurancePortal:
    def __init__(self):
        self._cache: dict[str, InsuranceTemplate] = {}
        self._container = None
        self._last_init_error: Optional[str] = None
        self._init_storage()
        self._load_templates()

    def _container_id(self) -> str:
        return settings.cosmos_db_container_templates

    def _init_storage(self):
        self._last_init_error = None
        try:
            if not settings.cosmos_endpoint or not settings.cosmos_key:
                logger.warning(
                    "insurance_portal_cosmos_skipped",
                    reason="cosmos endpoint or key empty in settings",
                    cosmos_env_keys=sorted(k for k in os.environ if "cosmos" in k.lower()),
                )
                return
            from azure.cosmos import PartitionKey

            from config.azure_clients import get_cosmos_client

            db_name = (
                (settings.cosmos_database or settings.cosmos_db_database or "voice_navigator").strip()
                or "voice_navigator"
            )
            client = get_cosmos_client()
            db = client.create_database_if_not_exists(id=db_name)
            self._container = db.create_container_if_not_exists(
                id=self._container_id(),
                partition_key=PartitionKey(path="/intent"),
            )
            logger.info(
                "insurance_portal_cosmos_ready",
                database=db_name,
                container=self._container_id(),
            )
        except Exception as e:
            self._container = None
            self._last_init_error = str(e)
            logger.warning("insurance_portal_cosmos_init_failed", error=str(e))

    def _overlay_smalltalk_from_seed(self) -> None:
        """Prefer bundled small-talk strings (e.g. AILVN branding) over stale Cosmos copies."""
        for t in _templates_from_json_seed():
            if str(t.intent).startswith("smalltalk_"):
                self._cache[t.intent] = t

    def _load_templates(self):
        self._cache = dict(DEFAULT_INSURANCE_TEMPLATES)
        # CSR + small-talk from JSON seed (Cosmos upserts the same rows when DB is empty).
        # Without Cosmos, these intents were missing and smalltalk_* fell through to fallback_human.
        for t in _templates_from_json_seed():
            self._cache.setdefault(t.intent, t)
        if not self._container:
            self._overlay_smalltalk_from_seed()
            return
        try:
            items = list(self._container.read_all_items())
            if not items:
                for t in DEFAULT_INSURANCE_TEMPLATES.values():
                    self._container.upsert_item({**asdict(t), "id": t.intent})
                existing_ids = {i.get("intent") or i.get("id") for i in self._container.read_all_items()}
                seed_added = _upsert_json_seed_missing(self._container, existing_ids)
                items = list(self._container.read_all_items())
                logger.info(
                    "insurance_portal_cosmos_seeded_defaults",
                    count=len(items),
                    csr_smalltalk_seed_added=seed_added,
                    container=self._container_id(),
                )
            for item in items:
                self._cache[item["intent"]] = InsuranceTemplate(
                    intent=item["intent"],
                    template=item["template"],
                    voice_id=item.get("voice_id"),
                    enabled=item.get("enabled", True),
                    doc_sources=item.get("doc_sources", []),
                    created_at=item.get("created_at", ""),
                    updated_at=item.get("updated_at", ""),
                )
        except Exception as e:
            logger.warning("insurance_portal_cosmos_load_failed", error=str(e))
            self._cache = dict(DEFAULT_INSURANCE_TEMPLATES)
            for t in _templates_from_json_seed():
                self._cache.setdefault(t.intent, t)
        self._overlay_smalltalk_from_seed()

    def cosmos_diagnostics(self, include_env_name_list: bool = False) -> dict:
        """For /portal/v1/cosmos-status — explains why Data Explorer may look empty."""
        ep = (settings.cosmos_endpoint or "").strip()
        out: dict = {
            "endpoint_configured": bool(ep and settings.cosmos_key),
            "database_id": settings.cosmos_database or settings.cosmos_db_database,
            "container_id": self._container_id(),
            "client_connected": self._container is not None,
            "last_init_error": self._last_init_error,
            "cosmos_related_env_var_names": sorted(
                k for k in os.environ if "cosmos" in k.lower()
            ),
            "azure_container_apps_env_names": (
                "Azure Container Apps only allows a-z, A-Z, 0-9, and underscore in env var NAMES. "
                "Names with hyphens (e.g. cosmos-db-key) are rejected or never injected — use "
                "COSMOS_DB_ENDPOINT and COSMOS_DB_KEY instead."
            ),
        }
        if include_env_name_list:
            out["process_env_var_names"] = sorted(os.environ.keys())
        if ep:
            try:
                out["endpoint_host"] = urlparse(ep).hostname
            except Exception:
                out["endpoint_host"] = None
        if not out["endpoint_configured"]:
            out["hint"] = (
                "Set environment variables named exactly COSMOS_DB_ENDPOINT and COSMOS_DB_KEY "
                "(underscores, no hyphens). Map secrets to those names in Container App → "
                "Containers → Environment variables. Then use /portal/v1/cosmos-status?debug_env=1 "
                "to confirm those names appear under process_env_var_names."
            )
            return out
        if not self._container:
            out["hint"] = (
                "Keys are set but the SDK could not open the database/container. "
                "Confirm Core (SQL) API account, key is valid, and check app logs for the error above."
            )
            return out
        try:
            out["item_count"] = len(list(self._container.read_all_items()))
        except Exception as e:
            out["read_error"] = str(e)
        return out

    def seed_defaults_if_empty(self) -> dict:
        """Upsert built-in templates when the container has no items (idempotent if already populated)."""
        if not self._container:
            return {"ok": False, "error": "cosmos_not_connected", "diagnostics": self.cosmos_diagnostics()}
        try:
            items = list(self._container.read_all_items())
            if items:
                self._load_templates()
                return {"ok": True, "seeded": False, "item_count": len(items)}
            for t in DEFAULT_INSURANCE_TEMPLATES.values():
                self._container.upsert_item({**asdict(t), "id": t.intent})
            self._load_templates()
            n = len(list(self._container.read_all_items()))
            logger.info("insurance_portal_manual_seed", item_count=n)
            return {"ok": True, "seeded": True, "item_count": n}
        except Exception as e:
            logger.warning("insurance_portal_seed_failed", error=str(e))
            return {"ok": False, "error": str(e)}

    def upsert_missing_default_templates(self) -> dict:
        """
        Upsert missing legacy defaults (RAG slots) and missing rows from ``data/csr_smalltalk_seed.json``.
        Does not overwrite existing Cosmos documents.
        """
        if not self._container:
            return {"ok": False, "error": "cosmos_not_connected"}
        try:
            existing = {i.get("intent") or i.get("id") for i in self._container.read_all_items()}
            added = 0
            for t in DEFAULT_INSURANCE_TEMPLATES.values():
                if t.intent not in existing:
                    self._container.upsert_item({**asdict(t), "id": t.intent})
                    existing.add(t.intent)
                    added += 1
            added += _upsert_json_seed_missing(self._container, existing)
            self._load_templates()
            n = len(list(self._container.read_all_items()))
            logger.info("insurance_portal_upsert_missing", added=added, total=n)
            return {"ok": True, "added": added, "item_count": n}
        except Exception as e:
            logger.warning("insurance_portal_upsert_missing_failed", error=str(e))
            return {"ok": False, "error": str(e)}

    def list_templates(self) -> dict[str, InsuranceTemplate]:
        return self._cache

    def get_template(self, intent: str) -> InsuranceTemplate:
        return self._cache.get(intent) or self._cache["fallback_human"]

    def save_template(
        self,
        intent: str,
        template: str,
        voice_id: Optional[str] = None,
        enabled: bool = True,
        doc_sources: Optional[list] = None,
    ):
        key = intent.strip()
        prev = self._cache.get(key)
        sources: list = []
        if doc_sources is not None:
            sources = list(doc_sources)
        elif prev and prev.doc_sources:
            sources = list(prev.doc_sources)
        prev_voice = prev.voice_id if prev else None
        obj = InsuranceTemplate(
            intent=key,
            template=template.strip(),
            voice_id=voice_id if voice_id is not None else prev_voice,
            enabled=enabled,
            doc_sources=sources,
            created_at=(prev.created_at if prev and prev.created_at else datetime.utcnow().isoformat()),
            updated_at=datetime.utcnow().isoformat(),
        )
        self._cache[key] = obj
        if self._container:
            self._container.upsert_item({**asdict(obj), "id": obj.intent})

    def delete_template(self, intent: str) -> None:
        key = intent.strip()
        if key in self._cache:
            del self._cache[key]
        if self._container:
            try:
                self._container.delete_item(item=key, partition_key=key)
            except Exception:
                pass

    def fill_template(self, intent: str, rag_values: dict, fallback: str = "information not available") -> str:
        template = self.get_template(intent).template

        def _replace(match):
            slot = match.group(1)
            val = rag_values.get(slot)
            return str(val) if val not in (None, "") else fallback

        return re.sub(r"\{rag\.(\w+)\}", _replace, template)


_portal: Optional[InsurancePortal] = None


def get_insurance_portal() -> InsurancePortal:
    global _portal
    if _portal is None:
        _portal = InsurancePortal()
    return _portal
