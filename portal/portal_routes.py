"""
portal/portal_routes.py

REST API for response portal: CRUD templates in Cosmos + render endpoint for orchestrators.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from portal.insurance_portal import get_insurance_portal
from portal.portal_render import extract_rag_slots, render_portal_response

portal_router = APIRouter(prefix="/portal/v1", tags=["Response Portal"])


@portal_router.get("/cosmos-status")
async def portal_cosmos_status(
    debug_env: bool = Query(
        default=False,
        description="If true, lists all environment variable NAMES seen by the process (no values).",
    ),
):
    """
    Why Data Explorer looks empty: missing env vars, wrong account, or connection failure.
    Open this URL in a browser after deploy to verify Cosmos wiring.
    """
    return get_insurance_portal().cosmos_diagnostics(include_env_name_list=debug_env)


@portal_router.post("/seed-defaults")
async def portal_seed_defaults():
    """
    If Cosmos is connected but ``response_templates`` has zero items, upserts built-in intents.
    Safe to call multiple times (no-op when data already exists).
    """
    result = get_insurance_portal().seed_defaults_if_empty()
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result)
    return result


@portal_router.post("/upsert-missing-templates")
async def portal_upsert_missing_templates():
    """
    Upsert missing legacy defaults plus any intents from ``data/csr_smalltalk_seed.json`` not yet in Cosmos.
    CSR/small-talk wording is not stored in Python — only in DB (and optional JSON bootstrap).
    """
    result = get_insurance_portal().upsert_missing_default_templates()
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result)
    return result


class RenderRequest(BaseModel):
    intent: str = Field(..., description="Detected intent key (e.g. hospital_covered)")
    rag_values: dict[str, Any] = Field(default_factory=dict)
    fallback: str = "information not available"


class RenderResponse(BaseModel):
    intent: str
    rendered_text: str
    template_raw: str
    slots_requested: list[str]
    slots_filled: dict[str, Any]
    voice_id: Optional[str] = None


@portal_router.post("/render", response_model=RenderResponse)
async def portal_render(body: RenderRequest):
    """
    After intent classification and RAG, call this to merge DB template with RAG slot values.
    Downstream services (TTS, summary) should consume ``rendered_text``.
    """
    result = render_portal_response(
        body.intent.strip(),
        body.rag_values,
        fallback=body.fallback,
    )
    return RenderResponse(
        intent=result.intent,
        rendered_text=result.rendered_text,
        template_raw=result.template_raw,
        slots_requested=result.slots_requested,
        slots_filled=result.slots_filled,
        voice_id=result.voice_id,
    )


class TemplateCreateBody(BaseModel):
    intent: str
    template: str
    voice_id: Optional[str] = None
    enabled: bool = True
    doc_sources: list[dict] = Field(default_factory=list)


class TemplateUpdateBody(BaseModel):
    template: str
    voice_id: Optional[str] = None
    enabled: bool = True
    doc_sources: Optional[list[dict]] = None


@portal_router.get("/templates")
async def portal_list_templates():
    """All intents and templates from Cosmos (cached)."""
    portal = get_insurance_portal()
    out: dict[str, Any] = {}
    for key, t in portal.list_templates().items():
        out[key] = {
            "intent": t.intent,
            "template": t.template,
            "voice_id": t.voice_id,
            "enabled": t.enabled,
            "doc_sources": t.doc_sources or [],
            "slots": extract_rag_slots(t.template),
            "created_at": t.created_at,
            "updated_at": t.updated_at,
        }
    return out


@portal_router.get("/templates/{intent}")
async def portal_get_template(intent: str):
    portal = get_insurance_portal()
    all_t = portal.list_templates()
    key = intent.strip()
    t = all_t.get(key) or all_t.get(key.lower())
    if not t:
        raise HTTPException(status_code=404, detail=f"Unknown intent: {intent}")
    return {
        "intent": t.intent,
        "template": t.template,
        "voice_id": t.voice_id,
        "enabled": t.enabled,
        "doc_sources": t.doc_sources or [],
        "slots": extract_rag_slots(t.template),
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


@portal_router.put("/templates/{intent}")
async def portal_put_template(intent: str, body: TemplateUpdateBody):
    portal = get_insurance_portal()
    portal.save_template(
        intent.strip(),
        body.template,
        voice_id=body.voice_id,
        enabled=body.enabled,
        doc_sources=body.doc_sources,
    )
    return {"status": "updated", "intent": intent.strip()}


@portal_router.post("/templates")
async def portal_create_template(body: TemplateCreateBody):
    key = body.intent.strip()
    if not key:
        raise HTTPException(status_code=400, detail="intent is required")
    portal = get_insurance_portal()
    if key in portal.list_templates():
        raise HTTPException(status_code=409, detail=f"Intent already exists: {key}")
    portal.save_template(
        key,
        body.template,
        voice_id=body.voice_id,
        enabled=body.enabled,
        doc_sources=body.doc_sources,
    )
    return {"status": "created", "intent": key}


@portal_router.delete("/templates/{intent}")
async def portal_delete_template(intent: str):
    key = intent.strip()
    if key in ("fallback_human",):
        raise HTTPException(status_code=400, detail="Cannot delete protected intent")
    portal = get_insurance_portal()
    portal.delete_template(key)
    return {"status": "deleted", "intent": key}
