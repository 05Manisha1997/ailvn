"""
tts/elevenlabs_streamer.py
Streams ElevenLabs TTS audio (PCM 16 kHz) back over a WebSocket connection.
Falls back to silent no-op when ElevenLabs key is not configured.
"""
import httpx
import asyncio
from config import settings


async def stream_tts_to_call(text: str, websocket) -> None:
    """
    Stream ElevenLabs TTS audio bytes directly back to the caller's WebSocket.

    Args:
        text: The spoken response text to synthesize.
        websocket: FastAPI / Starlette WebSocket instance.
    """
    if not settings.elevenlabs_api_key:
        # No key — log and skip (demo mode without audio output)
        print(f"[TTS-DEMO] Would speak: {text}")
        return

    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech"
        f"/{settings.elevenlabs_voice_id}/stream"
    )
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",       # Lowest latency model
        "voice_settings": {
            "stability": 0.75,
            "similarity_boost": 0.85,
            "style": 0.2,
            "use_speaker_boost": True,
        },
        "output_format": "pcm_16000",         # Format expected by Azure ACS
    }

    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(chunk_size=4096):
                await websocket.send_bytes(chunk)


async def synthesize_to_bytes(text: str) -> bytes:
    """
    Synthesize text to audio bytes (non-streaming) for use in REST endpoints.
    Returns empty bytes if ElevenLabs is not configured.
    """
    if not settings.elevenlabs_api_key:
        return b""

    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech"
        f"/{settings.elevenlabs_voice_id}"
    )
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.75,
            "similarity_boost": 0.85,
        },
        "output_format": "mp3_44100_128",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content
