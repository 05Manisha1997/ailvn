"""
api/main.py

FastAPI application entry point.
Handles:
- WebSocket endpoint for real-time call audio streaming
- REST endpoints for portal admin (CRUD templates)
- Webhook endpoints for Azure Communication Services events
"""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config.settings import get_settings
from utils.logger import logger
from portal.portal_routes import portal_router
from call_handler import router as call_router

settings = get_settings()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("voice_navigator_starting", env=settings.app_env)
    # Warm up LLM client on startup
    try:
        from config.azure_clients import get_openai_client
        get_openai_client()
        logger.info("llm_client_ready")
    except Exception as e:
        logger.warning("llm_warmup_failed", error=str(e))
    yield
    logger.info("voice_navigator_shutting_down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Voice Navigator API",
    version="1.0.0",
    description="AI-powered voice call navigation system",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portal_router)
app.include_router(call_router, tags=["Call Handling"])


# ── Health Check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "voice-navigator", "env": settings.app_env}


# ── Frontend Static Mount ─────────────────────────────────────────────────────
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")

portal_admin_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "portal_ui")
if os.path.exists(portal_admin_dir):
    app.mount(
        "/portal",
        StaticFiles(directory=portal_admin_dir, html=True),
        name="portal_admin",
    )


@app.get("/")
async def root():
    return {
        "service": "voice-navigator",
        "status": "running",
        "dashboard": "/app",
        "response_portal_ui": "/portal",
        "response_portal_api": "/portal/v1",
        "docs": "/docs",
    }


# ── WebSocket: Real-Time Call Handler ─────────────────────────────────────────

@app.websocket("/ws/call")
async def call_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time call audio streaming.
    
    Protocol:
    1. Client connects and sends JSON handshake:
       {"event": "start", "caller_phone": "+14155552671", "caller_email": "user@example.com"}
    2. Client streams audio chunks as binary frames (PCM 16kHz mono 16-bit)
    3. Server sends audio chunks back as binary frames (MP3)
    4. Client sends {"event": "end"} to terminate the call
    5. Server sends {"event": "call_ended"} and closes

    This WebSocket acts as the bridge between Azure Communication Services
    (or any compatible telephony front-end) and the Voice Navigator orchestrator.
    """
    await websocket.accept()
    logger.info("websocket_connected", client=str(websocket.client))

    caller_phone = None
    caller_email = None

    try:
        # Wait for handshake
        handshake = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)

        if handshake.get("event") != "start":
            await websocket.send_json({"error": "Expected 'start' event"})
            await websocket.close()
            return

        caller_phone = handshake.get("caller_phone", "unknown")
        caller_email = handshake.get("caller_email")

        await websocket.send_json({
            "event": "call_accepted",
            "message": f"Call started for {caller_phone}",
        })

        # Build audio event generator from WebSocket frames
        async def audio_event_generator():
            from orchestrator.call_orchestrator import CallEvent
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive(), timeout=settings.max_call_duration_seconds
                    )
                    if message["type"] == "websocket.disconnect":
                        yield CallEvent(event_type="call_end")
                        return
                    elif message["type"] == "websocket.receive":
                        data = message.get("bytes") or message.get("text")
                        if isinstance(data, str):
                            evt = json.loads(data)
                            if evt.get("event") == "end":
                                yield CallEvent(event_type="call_end")
                                return
                        elif isinstance(data, bytes):
                            yield CallEvent(event_type="audio_chunk", data=data)
                except asyncio.TimeoutError:
                    logger.warning("call_timeout", phone=caller_phone)
                    yield CallEvent(event_type="call_end")
                    return
                except Exception as e:
                    logger.error("ws_receive_error", error=str(e))
                    yield CallEvent(event_type="call_end")
                    return

        # Run orchestrator
        from orchestrator.call_orchestrator import CallOrchestrator
        orchestrator = CallOrchestrator(
            caller_phone=caller_phone,
            caller_email=caller_email,
        )

        async for audio_chunk in orchestrator.run(audio_event_generator()):
            await websocket.send_bytes(audio_chunk)

        await websocket.send_json({"event": "call_ended"})

    except WebSocketDisconnect:
        logger.info("websocket_disconnected", phone=caller_phone)
    except Exception as e:
        logger.error("websocket_error", error=str(e), phone=caller_phone)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── Webhooks ──────────────────────────────────────────────────────────────────

@app.post("/webhooks/azure-call")
async def azure_call_webhook(payload: dict):
    """
    Webhook for Azure Communication Services call events.
    """
    event_type = payload.get("type", "")
    logger.info("azure_call_webhook", event=event_type)
    return {"status": "received"}


# ── Portal Admin API ──────────────────────────────────────────────────────────

@app.get("/api/templates")
async def list_templates():
    """List all response templates."""
    from portal.response_portal import get_response_portal, DEFAULT_TEMPLATES
    portal = get_response_portal()
    templates = {}
    for intent in DEFAULT_TEMPLATES:
        t = portal.get_template(intent)
        templates[intent] = {
            "intent": t.intent,
            "template": t.template,
            "sub_routes": [
                {"id": sr.route_id, "label": sr.label, "condition": sr.condition}
                for sr in t.sub_routes
            ],
            "doc_sources": t.doc_sources,
            "enabled": t.enabled,
        }
    return templates


@app.get("/api/templates/{intent}")
async def get_template(intent: str):
    """Get a specific response template."""
    from portal.response_portal import get_response_portal
    portal = get_response_portal()
    t = portal.get_template(intent.upper())
    if not t:
        raise HTTPException(status_code=404, detail=f"Template not found: {intent}")
    return {
        "intent": t.intent,
        "template": t.template,
        "sub_routes": [vars(sr) for sr in t.sub_routes],
        "doc_sources": t.doc_sources,
    }


@app.put("/api/templates/{intent}")
async def update_template(intent: str, body: dict):
    """Update a response template (admin portal action)."""
    from portal.response_portal import get_response_portal, ResponseTemplate, SubRoute
    portal = get_response_portal()

    sub_routes = [
        SubRoute(**sr) for sr in body.get("sub_routes", [])
    ]
    template = ResponseTemplate(
        intent=intent.upper(),
        template=body["template"],
        voice_id=body.get("voice_id"),
        sub_routes=sub_routes,
        doc_sources=body.get("doc_sources", []),
        enabled=body.get("enabled", True),
    )
    portal.save_template(template)
    return {"status": "updated", "intent": intent.upper()}


@app.get("/api/calls/{call_id}")
async def get_call(call_id: str):
    """Get call session details."""
    from memory.session_memory import get_session_memory
    mem = get_session_memory()
    session = mem.get_session(call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call not found")
    return {
        "call_id": session.call_id,
        "caller_phone": session.caller_phone,
        "caller_name": session.caller_name,
        "is_verified": session.is_verified,
        "current_intent": session.current_intent,
        "intent_history": session.intent_history,
        "turn_count": len(session.conversation),
        "started_at": session.started_at,
        "ended_at": session.ended_at,
    }


@app.get("/api/calls/{call_id}/context")
async def get_call_context(call_id: str):
    """Get full call context (used for live agent handoff)."""
    from memory.session_memory import get_session_memory
    mem = get_session_memory()
    context = mem.get_full_context_for_agent(call_id)
    if not context:
        raise HTTPException(status_code=404, detail="Call context not found")
    return context


@app.post("/api/calls/{call_id}/transfer")
async def trigger_transfer(call_id: str):
    """Manually trigger live agent transfer for a call."""
    from memory.session_memory import get_session_memory
    mem = get_session_memory()
    session = mem.request_live_agent(call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call not found")
    return {"status": "transfer_requested", "call_id": call_id}


# ── Run directly ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
        log_level=settings.log_level.lower(),
    )
