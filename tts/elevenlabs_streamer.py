"""
tts/elevenlabs_streamer.py
Streams ElevenLabs TTS audio (PCM 16 kHz) back over a WebSocket connection using the official SDK.
Falls back to silent no-op when ElevenLabs key is not configured.
"""
import asyncio
from typing import AsyncGenerator
from config import settings

try:
    from elevenlabs.client import AsyncElevenLabs
except ImportError:
    AsyncElevenLabs = None

# Initialize the async client
elevenlabs_client = None
if settings.elevenlabs_api_key and AsyncElevenLabs:
    elevenlabs_client = AsyncElevenLabs(
        api_key=settings.elevenlabs_api_key
    )

async def stream_tts_to_call(text: str, websocket) -> None:
    """
    Stream ElevenLabs TTS audio bytes directly back to the caller's WebSocket.

    Args:
        text: The spoken response text to synthesize.
        websocket: FastAPI / Starlette WebSocket instance.
    """
    if not elevenlabs_client:
        # No key — log and skip (demo mode without audio output)
        print(f"[TTS-DEMO] Would speak: {text}")
        return

    try:
        audio_stream = elevenlabs_client.text_to_speech.convert_as_stream(
            voice_id=settings.elevenlabs_voice_id,
            text=text,
            model_id="eleven_turbo_v2",       # Lowest latency model
            output_format="pcm_16000",        # Format expected by Azure ACS
            voice_settings={
                "stability": 0.75,
                "similarity_boost": 0.85,
                "style": 0.2,
                "use_speaker_boost": True,
            }
        )
        
        async for chunk in audio_stream:
            if chunk:
                await websocket.send_bytes(chunk)
                
    except Exception as e:
        print(f"[TTS] Streaming error: {e}")

async def synthesize_to_bytes(text: str) -> bytes:
    """
    Synthesize text to audio bytes (non-streaming) for use in REST endpoints.
    Returns empty bytes if ElevenLabs is not configured.
    """
    if not elevenlabs_client:
        return b""

    try:
        generator = elevenlabs_client.text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_id,
            text=text,
            model_id="eleven_turbo_v2",
            output_format="mp3_44100_128",
            voice_settings={
                "stability": 0.75,
                "similarity_boost": 0.85,
            }
        )
        
        chunks = []
        async for chunk in generator:
            if chunk:
                chunks.append(chunk)

        return b"".join(chunks)

    except Exception as e:
        print(f"[TTS] Synthesis error: {e}")
        return b""
