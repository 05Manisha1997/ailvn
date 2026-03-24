"""
portal/insurance_portal.py

Cosmos-backed portal service for insurance response templates/intents.
Falls back to in-memory defaults when Cosmos is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import re

from config import settings


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
        template="I wasn't able to find a clear answer for your query. Let me transfer you to a specialist right away.",
    ),
}


class InsurancePortal:
    def __init__(self):
        self._cache: dict[str, InsuranceTemplate] = {}
        self._container = None
        self._init_storage()
        self._load_templates()

    def _init_storage(self):
        try:
            if not settings.cosmos_endpoint or not settings.cosmos_key:
                return
            from azure.cosmos import CosmosClient, PartitionKey

            client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
            db = client.create_database_if_not_exists(id=settings.cosmos_database)
            self._container = db.create_container_if_not_exists(
                id="response_templates",
                partition_key=PartitionKey(path="/intent"),
            )
        except Exception:
            self._container = None

    def _load_templates(self):
        self._cache = dict(DEFAULT_INSURANCE_TEMPLATES)
        if not self._container:
            return
        try:
            items = list(self._container.read_all_items())
            if not items:
                for t in DEFAULT_INSURANCE_TEMPLATES.values():
                    self._container.upsert_item({**asdict(t), "id": t.intent})
                return
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
        except Exception:
            self._cache = dict(DEFAULT_INSURANCE_TEMPLATES)

    def list_templates(self) -> dict[str, InsuranceTemplate]:
        return self._cache

    def get_template(self, intent: str) -> InsuranceTemplate:
        return self._cache.get(intent) or self._cache["fallback_human"]

    def save_template(self, intent: str, template: str, voice_id: Optional[str] = None):
        key = intent.strip()
        obj = InsuranceTemplate(
            intent=key,
            template=template.strip(),
            voice_id=voice_id,
            created_at=self._cache.get(key).created_at if key in self._cache else "",
        )
        self._cache[key] = obj
        if self._container:
            self._container.upsert_item({**asdict(obj), "id": obj.intent})

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
