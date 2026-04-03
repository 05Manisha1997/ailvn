"""
main.py – FastAPI application entry point for the AI Voice Navigator for Insurance.
"""
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from call_handler import router as call_router
from portal.portal_routes import portal_router
from utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm Cosmos client, seed defaults if container is empty, log status for operators.
    from portal.insurance_portal import get_insurance_portal

    portal = get_insurance_portal()
    merge = portal.upsert_missing_default_templates()
    logger.info("startup_cosmos", **portal.cosmos_diagnostics(), templates_merge=merge)
    yield


app = FastAPI(
    title="AI Voice Navigator for Insurance",
    description=(
        "An AI-powered voice call system that verifies caller identity, "
        "extracts insurance query intent, retrieves policy info via RAG, "
        "and responds using fill-in-the-blank templates via ElevenLabs TTS."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS – allow dashboard frontend ─────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(call_router, tags=["Call Handling"])
app.include_router(portal_router)

# ── Serve frontend static files ──────────────────────────────────────────────
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")

portal_admin_dir = os.path.join(os.path.dirname(__file__), "portal_ui")
if os.path.exists(portal_admin_dir):
    app.mount(
        "/portal",
        StaticFiles(directory=portal_admin_dir, html=True),
        name="portal_admin",
    )


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "AI Voice Navigator for Insurance",
        "version": "1.0.0",
        "status": "running",
        "dashboard": "/app",
        "response_portal_ui": "/portal",
        "response_portal_api": "/portal/v1",
        "live_agent_handoffs": "/portal/v1/live-agent/handoffs",
        "docs": "/docs",
    }


@app.get("/health", tags=["Root"])
async def health():
    from portal.insurance_portal import get_insurance_portal

    p = get_insurance_portal()
    d = p.cosmos_diagnostics()
    return {
        "status": "healthy",
        "cosmos_templates_connected": d.get("client_connected", False),
        "cosmos_templates_count": d.get("item_count"),
        "cosmos_status_url": "/portal/v1/cosmos-status",
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
