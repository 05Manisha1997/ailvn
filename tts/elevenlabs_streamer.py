"""
tts/elevenlabs_streamer.py
 
Streams TTS audio back over a WebSocket connection.
 
Primary:  ElevenLabs (eleven_turbo_v2) — low latency, empathetic voice
Fallback: Azure Neural TTS with SSML — warm, personal, natural-paced
 
Voice tuning for empathy:
  - stability=0.42  → slight variability so it doesn't sound flat/robotic
  - similarity_boost=0.80 → stays true to the chosen voice persona
  - style=0.40        → adds natural expressiveness and emotional inflection
  - use_speaker_boost → enhances clarity over phone-quality audio
"""
import asyncio
from typing import Optional
from config import settings
 
try:
    from elevenlabs.client import AsyncElevenLabs
    from elevenlabs import VoiceSettings
except ImportError:
    AsyncElevenLabs = None
    VoiceSettings = None
 
# ── Empathetic voice parameters ───────────────────────────────────────────────
# These are tuned to sound warm, caring, and human — not robotic or corporate.
EMPATHY_VOICE_SETTINGS = {
    "stability": 0.42,           # Slight variability → avoids flat monotone
    "similarity_boost": 0.80,    # Stays true to the voice persona
    "style": 0.40,               # Adds emotional expressiveness
    "use_speaker_boost": True,   # Enhances clarity on phone audio
}
 
# Initialize the async ElevenLabs client once
elevenlabs_client = None
if settings.elevenlabs_api_key and AsyncElevenLabs:
    elevenlabs_client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
 
 
def _build_ssml(text: str, lang_code: str = "en-US") -> str:
    """
    Wraps plain text in Azure SSML with empathy-enhancing markup:
    - A gentle 250ms pause at the start (shows attentiveness)
    - A 350ms pause after the greeting clause
    - Prosody rate "95%" → slightly slower = easier to follow on a phone call
    - Voice: en-US-JennyNeural (warm, empathetic insurance/support voice)
    """
    voice_name = "en-US-JennyNeural"
 
    # Escape any bare XML-unsafe chars in the text
    safe_text = (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
 
    return f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{lang_code}">
  <voice name="{voice_name}">
    <mstts:express-as style="customerservice" styledegree="1.5">
      <prosody rate="95%" pitch="-1%">
        <break time="250ms"/>
        {safe_text}
        <break time="150ms"/>
      </prosody>
    </mstts:express-as>
  </voice>
</speak>"""
 
 
async def _azure_tts_fallback(text: str, lang_code: str = "en-US") -> bytes:
    """Azure Neural TTS fallback using SSML for empathetic delivery."""
    try:
        import azure.cognitiveservices.speech as speechsdk
 
        speech_config = speechsdk.SpeechConfig(
            subscription=settings.azure_speech_key,
            region=settings.azure_speech_region,
        )
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
        )
 
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=None
        )
        ssml = _build_ssml(text, lang_code)
        result = await asyncio.to_thread(
            lambda: synthesizer.speak_ssml_async(ssml).get()
        )
 
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return result.audio_data
        else:
            print(f"[TTS-Azure] Failed: {result.reason}")
            return b""
    except Exception as e:
        print(f"[TTS-Azure] Error: {e}")
        return b""
 
 
async def stream_tts_to_call(
    text: str,
    websocket,
    *,
    voice_id: Optional[str] = None,
    lang_code: str = "en-US",
) -> None:
    """
    Stream TTS audio bytes directly back to the caller's WebSocket.
    Tries ElevenLabs first (low latency, empathetic), then Azure Neural TTS.
 
    Args:
        text:      The spoken response text to synthesize.
        websocket: FastAPI / Starlette WebSocket instance.
        voice_id:  Override ElevenLabs voice ID (optional).
        lang_code: BCP-47 language code e.g. "en-US", "fr-FR" (for Azure fallback).
    """
    if not text.strip():
        return
 
    # ── ElevenLabs (primary) ─────────────────────────────────────────────────
    if elevenlabs_client:
        try:
            vid = voice_id or settings.elevenlabs_voice_id
            audio_stream = elevenlabs_client.text_to_speech.convert_as_stream(
                voice_id=vid,
                text=text,
                model_id="eleven_turbo_v2",   # Lowest latency model
                output_format="pcm_16000",     # Direct PCM for ACS WebSocket
                voice_settings=EMPATHY_VOICE_SETTINGS,
            )
            async for chunk in audio_stream:
                if chunk:
                    await websocket.send_bytes(chunk)
            return
        except Exception as e:
            print(f"[TTS-ElevenLabs] Error, falling back to Azure: {e}")
 
    # ── Azure Neural TTS (fallback) ──────────────────────────────────────────
    if settings.azure_speech_key:
        audio = await _azure_tts_fallback(text, lang_code)
        chunk_size = 4096
        for i in range(0, len(audio), chunk_size):
            await websocket.send_bytes(audio[i : i + chunk_size])
            await asyncio.sleep(0)
        return
 
    # ── No TTS configured ────────────────────────────────────────────────────
    print(f"[TTS-DEMO] Would speak: {text}")
 
 
async def synthesize_to_bytes(
    text: str,
    *,
    voice_id: Optional[str] = None,
    lang_code: str = "en-US",
) -> bytes:
    """
    Synthesize text to audio bytes (non-streaming) for REST endpoints.
    Returns empty bytes if neither service is configured.
    """
    if not text.strip():
        return b""
 
    # ElevenLabs (primary)
    if elevenlabs_client:
        try:
            vid = voice_id or settings.elevenlabs_voice_id
            generator = elevenlabs_client.text_to_speech.convert(
                voice_id=vid,
                text=text,
                model_id="eleven_turbo_v2",
                output_format="mp3_44100_128",
                voice_settings=EMPATHY_VOICE_SETTINGS,
            )
            chunks = []
            async for chunk in generator:
                if chunk:
                    chunks.append(chunk)
            return b"".join(chunks)
        except Exception as e:
            print(f"[TTS-ElevenLabs] Synthesis error: {e}")
 
    # Azure fallback
    if settings.azure_speech_key:
        return await _azure_tts_fallback(text, lang_code)
 
    return b""
 