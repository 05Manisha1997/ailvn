"""
portal/portal_routes.py

REST API for response portal: CRUD templates in Cosmos + render endpoint for orchestrators.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from portal.insurance_portal import get_insurance_portal
from portal.portal_render import extract_rag_slots, render_portal_response
from services.handoff_email import send_handoff_closure_email
from services.live_agent_queue import (
    claim_handoff,
    create_handoff,
    get_handoff,
    list_handoffs,
    resolve_handoff,
)

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


class LiveAgentHandoffCreate(BaseModel):
    conversation_history: list[dict] = Field(default_factory=list)
    caller_phone: str = ""
    simulated_member_id: str = ""
    verified: bool = False
    portal_intent: Optional[str] = None
    reason: str = "user_requested"
    source: str = "simulator"
    customer_email: str = ""
    customer_name: str = ""


@portal_router.post("/live-agent/handoffs")
async def portal_create_live_handoff(body: LiveAgentHandoffCreate):
    """
    Queue a session for a live agent. Call from the simulator (or telephony bridge later).
    Agents open context from GET /live-agent/handoffs/{id}.
    """
    rec = create_handoff(
        conversation_history=body.conversation_history,
        caller_phone=body.caller_phone,
        simulated_member_id=body.simulated_member_id,
        verified=body.verified,
        portal_intent=body.portal_intent,
        reason=body.reason,
        source=body.source,
        customer_email=body.customer_email or "",
        customer_name=body.customer_name or "",
    )
    return {"status": "queued", "handoff": rec}


class HandoffResolveBody(BaseModel):
    resolution_notes: Optional[str] = Field(
        default=None,
        max_length=4000,
        description="Included in the customer summary email when resolved.",
    )


@portal_router.get("/live-agent/handoffs")
async def portal_list_live_handoffs(
    status: Optional[str] = Query(
        None,
        description="Filter: pending | claimed | resolved (omit for all)",
    ),
):
    return {"handoffs": list_handoffs(status=status)}


@portal_router.get("/live-agent/handoffs/{handoff_id}")
async def portal_get_live_handoff(handoff_id: str):
    rec = get_handoff(handoff_id.strip())
    if not rec:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return rec


@portal_router.post("/live-agent/handoffs/{handoff_id}/claim")
async def portal_claim_live_handoff(
    handoff_id: str,
    body: dict = Body(default_factory=dict),
):
    agent_name = (body or {}).get("agent_name") or "Agent"
    rec = claim_handoff(handoff_id.strip(), str(agent_name))
    if not rec:
        raise HTTPException(
            status_code=400,
            detail="Handoff not found or not pending",
        )
    return {"status": "claimed", "handoff": rec}


@portal_router.post("/live-agent/handoffs/{handoff_id}/resolve")
async def portal_resolve_live_handoff(
    handoff_id: str,
    body: HandoffResolveBody = Body(default_factory=HandoffResolveBody),
):
    """
    Mark handoff resolved. If ``customer_email`` is on file and email (ACS or SendGrid) is configured,
    sends the conversation summary plus optional ``resolution_notes`` to the customer.
    """
    hid = handoff_id.strip()
    rec = get_handoff(hid)
    if not rec:
        raise HTTPException(status_code=404, detail="Handoff not found")
    if rec.get("status") == "resolved":
        return {
            "status": "already_resolved",
            "id": hid,
            "email_sent": False,
            "email_skipped_reason": "already_resolved",
        }
    if not resolve_handoff(hid):
        raise HTTPException(status_code=404, detail="Handoff not found")

    sent, skip_reason = send_handoff_closure_email(
        rec,
        resolution_notes=body.resolution_notes,
    )
    return {
        "status": "resolved",
        "id": hid,
        "email_sent": sent,
        "email_skipped_reason": None if sent else skip_reason,
    }


@portal_router.delete("/templates/{intent}")
async def portal_delete_template(intent: str):
    key = intent.strip()
    if key in ("fallback_human", "request_live_agent"):
        raise HTTPException(status_code=400, detail="Cannot delete protected intent")
    portal = get_insurance_portal()
    portal.delete_template(key)
    return {"status": "deleted", "intent": key}
