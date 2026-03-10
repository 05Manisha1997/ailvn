"""
call_handler.py
FastAPI router for:
  - POST /incoming-call       : Azure ACS webhook to answer incoming PSTN calls
  - WS   /audio-stream/{call_id} : Bidirectional audio WebSocket
  - POST /simulate            : REST endpoint to simulate a caller turn (no real call needed)
  - POST /tts                 : Convert text → audio bytes (ElevenLabs or browser fallback)
  - GET  /calls               : Active calls list for the dashboard
  - GET  /analytics           : Analytics data for the dashboard
"""
import asyncio
import json
import uuid
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
import shutil
import os
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import settings
from navigator import InsuranceVoiceNavigator
from agents.tasks import build_crew_for_query
from tts.elevenlabs_streamer import synthesize_to_bytes
from tools.translator_api import translator
from tools.template_verifier import verify_and_fix_template
from templates.response_templates import get_all_templates, upsert_template

router = APIRouter()

# ── In-memory call registry (replace with Redis in production) ───────────────
_active_calls: dict[str, dict] = {}


# ────────────────────────────────────────────────────────────────────────────
#  Models
# ────────────────────────────────────────────────────────────────────────────

class SimulateRequest(BaseModel):
    caller_id: str = "POL-001"
    caller_phone: str = "+353-87-111-2233"
    message: str
    conversation_history: list = []
    demo_mode: bool = True


class SimulateResponse(BaseModel):
    caller_id: str
    user_message: str
    agent_response: str
    conversation_history: list
    elapsed_ms: int


# ────────────────────────────────────────────────────────────────────────────
#  ACS Webhook — Incoming Call
# ────────────────────────────────────────────────────────────────────────────

@router.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Webhook triggered by Azure Communication Services when a call arrives."""
    try:
        from azure.communication.callautomation import CallAutomationClient
        from azure.communication.callautomation.models import MediaStreamingOptions

        event_data = await request.json()
        call_connection_id = event_data.get("callConnectionId", str(uuid.uuid4()))

        _active_calls[call_connection_id] = {
            "id": call_connection_id,
            "started_at": datetime.utcnow().isoformat(),
            "status": "connecting",
            "caller_id": event_data.get("from", "unknown"),
        }

        if settings.acs_connection_string:
            call_client = CallAutomationClient.from_connection_string(
                settings.acs_connection_string
            )
            media_streaming = MediaStreamingOptions(
                transport_url=(
                    f"{settings.acs_callback_base_url}"
                    f"/audio-stream/{call_connection_id}"
                ),
                transport_type="websocket",
                content_type="audio/pcm",
                channel_type="mixed",
            )
            call_client.answer_call(
                incoming_call_context=event_data["incomingCallContext"],
                cognitive_services_endpoint=settings.azure_cognitive_endpoint,
                media_streaming=media_streaming,
            )

        return {"status": "answered", "call_id": call_connection_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ────────────────────────────────────────────────────────────────────────────
#  WebSocket Audio Stream
# ────────────────────────────────────────────────────────────────────────────

@router.websocket("/audio-stream/{call_id}")
async def audio_stream(websocket: WebSocket, call_id: str):
    """Bidirectional PCM audio WebSocket fed by Azure ACS media streaming."""
    await websocket.accept()
    _active_calls[call_id] = _active_calls.get(call_id, {})
    _active_calls[call_id]["status"] = "active"
    caller_phone = _active_calls[call_id].get("caller_id", "unknown")

    navigator = InsuranceVoiceNavigator(call_id=call_id, caller_phone=caller_phone)
    try:
        await navigator.run(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        _active_calls.pop(call_id, None)


# ────────────────────────────────────────────────────────────────────────────
#  REST Simulate Endpoint (no real call needed)
# ────────────────────────────────────────────────────────────────────────────

@router.post("/simulate", response_model=SimulateResponse)
async def simulate_call_turn(body: SimulateRequest):
    """
    Simulate a single caller turn through the full CrewAI pipeline.
    Used by the frontend Call Simulator view and for integration testing.
    """
    start = time.monotonic()

    # Determine original language
    detected_lang = await translator.detect_language(body.message)
    
    # Translate to English for CrewAI
    if detected_lang != "en":
        english_input = await translator.translate_text(body.message, target_lang="en")
    else:
        english_input = body.message

    loop = asyncio.get_event_loop()
    agent_response = await loop.run_in_executor(
        None,
        lambda: build_crew_for_query(
            caller_input=english_input,
            caller_id=body.caller_id,
            caller_phone=body.caller_phone,
            conversation_history=body.conversation_history,
            demo_mode=body.demo_mode,
        ),
    )

    # Translate back to caller's language
    if detected_lang != "en":
        final_response = await translator.translate_text(agent_response, target_lang=detected_lang)
    else:
        final_response = agent_response

    updated_history = body.conversation_history + [
        {"role": "user", "content": body.message},
        {"role": "assistant", "content": final_response},
    ]
    elapsed_ms = int((time.monotonic() - start) * 1000)

    return SimulateResponse(
        caller_id=body.caller_id,
        user_message=body.message,
        agent_response=final_response,
        conversation_history=updated_history,
        elapsed_ms=elapsed_ms,
    )


class TTSRequest(BaseModel):
    text: str


@router.post("/tts")
async def generate_tts(body: TTSRequest):
    """
    Generate audio bytes for a text string.
    If ElevenLabs is not configured, returns a flag so the frontend can fallback
    to browser-native SpeechSynthesis.
    """
    audio_bytes = await synthesize_to_bytes(body.text)
    if not audio_bytes:
        # Signal to frontend to use browser TTS
        return JSONResponse(content={"fallback": True})
    
    from fastapi.responses import Response
    return Response(content=audio_bytes, media_type="audio/mpeg")


# ────────────────────────────────────────────────────────────────────────────
#  Template APIs
# ────────────────────────────────────────────────────────────────────────────

class TemplateRequest(BaseModel):
    intent_key: str
    template: str

@router.get("/templates")
async def list_templates():
    """Return all current response templates."""
    return get_all_templates()

@router.post("/templates")
async def add_template(body: TemplateRequest):
    """Clean a user-submitted template and save it."""
    clean_text = await verify_and_fix_template(body.intent_key, body.template)
    upsert_template(body.intent_key, clean_text)
    return {"status": "success", "clean_template": clean_text, "intent_key": body.intent_key}


@router.post("/index-policy")
async def index_policy(
    policy_id: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Receive a PDF file and index it into Azure AI Search.
    """
    from indexer.policy_indexer import index_policy_document
    
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Save temporary file
    temp_dir = "tmp"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{file.filename}")
    
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Run indexing pipeline
        index_policy_document(temp_path, policy_id)
        
        return {"status": "success", "message": f"Policy {policy_id} indexed successfully."}
    except Exception as e:
        print(f"[Indexing Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ────────────────────────────────────────────────────────────────────────────
#  Dashboard APIs
# ────────────────────────────────────────────────────────────────────────────

@router.get("/calls")
async def list_active_calls():
    """Return list of currently active calls for the dashboard."""
    return {"calls": list(_active_calls.values()), "total": len(_active_calls)}


@router.get("/analytics")
async def get_analytics():
    """Return demo analytics data for the dashboard."""
    return {
        "calls_today": 47,
        "avg_resolution_ms": 2840,
        "resolution_rate": 0.91,
        "transferred_to_human": 0.09,
        "intent_breakdown": {
            "coverage_check": 18,
            "hospital_eligibility": 12,
            "claim_limit": 8,
            "deductible": 5,
            "treatment_check": 3,
            "other": 1,
        },
        "hourly_calls": [2, 1, 0, 0, 0, 0, 1, 3, 5, 7, 6, 4, 3, 5, 4, 2, 2, 1, 1, 0, 0, 0, 0, 0],
    }
