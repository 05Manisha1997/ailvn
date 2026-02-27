"""
main.py – FastAPI application entry point for the AI Voice Navigator for Insurance.
"""
import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from call_handler import router as call_router

app = FastAPI(
    title="AI Voice Navigator for Insurance",
    description=(
        "An AI-powered voice call system that verifies caller identity, "
        "extracts insurance query intent, retrieves policy info via RAG, "
        "and responds using fill-in-the-blank templates via ElevenLabs TTS."
    ),
    version="1.0.0",
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

# ── Serve frontend static files ──────────────────────────────────────────────
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "AI Voice Navigator for Insurance",
        "version": "1.0.0",
        "status": "running",
        "dashboard": "/app",
        "docs": "/docs",
    }


@app.get("/health", tags=["Root"])
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
