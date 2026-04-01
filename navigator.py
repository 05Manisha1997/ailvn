"""
navigator.py
InsuranceVoiceNavigator — main call session orchestrator.
 
Handles:
  - STT (Azure Speech with multilingual auto-detect)
  - CrewAI / RAG agent pipeline
  - TTS (ElevenLabs → Azure Neural fallback) with empathetic delivery
 
Voice Philosophy:
  Every phrase the AI speaks is designed to feel warm, personal and unhurried.
  Bridge messages reassure the caller while processing happens in the background.
  The system passes the detected language code to the TTS layer so responses
  can be synthesised in the caller's own language where supported.
"""
import asyncio
import random
from config import settings
from agents.tasks import build_crew_for_query
from tts.elevenlabs_streamer import stream_tts_to_call
from templates.response_templates import fill_template, TEMPLATES
 
try:
    import azure.cognitiveservices.speech as speechsdk
    SPEECH_AVAILABLE = True
except ImportError:
    SPEECH_AVAILABLE = False
 
# ── Empathetic bridge phrases (spoken while the AI pipeline runs) ─────────────
# Varied so the caller never hears the same holding phrase twice in a row.
_BRIDGE_PHRASES = [
    "Of course, just a moment while I look that up for you.",
    "Absolutely, let me check your policy details right now.",
    "Sure thing — I won't keep you waiting long.",
    "I appreciate your patience — pulling that information up now.",
    "Great question. Give me just a second to find that for you.",
    "Let me take a look at that for you right away.",
]
 
# ── Empathetic clarification prompts (when STT returns nothing) ───────────────
_CLARIFY_PHRASES = [
    "I'm sorry, I didn't quite catch that. Could you say that again, please?",
    "Apologies, it seems the line was a little unclear. Could you repeat that for me?",
    "I want to make sure I get this right — could you say that one more time?",
]
 
 
class InsuranceVoiceNavigator:
    """
    Manages a single call session end-to-end:
      1. Greet the caller with a warm, personal TTS message
      2. Receive audio → Azure STT transcription (multilingual)
      3. Play an empathetic bridge phrase while the agent pipeline runs
      4. Stream the AI response back to the caller via TTS
      5. Repeat until call ends or timeout
    """
 
    def __init__(self, call_id: str, caller_phone: str = "unknown", demo_mode: bool = True):
        self.call_id = call_id
        self.caller_phone = caller_phone
        self.demo_mode = demo_mode or not settings.azure_speech_key
        self.conversation_history: list[dict] = []
        self.verified = False
        self.policy_id: str | None = None
        self.member_name: str | None = None
        self._last_bridge_idx: int = -1        # Avoids repeating the same bridge phrase
        self._detected_lang: str = "en-US"     # Updated after each STT result
 
        if SPEECH_AVAILABLE and settings.azure_speech_key:
            self.speech_config = speechsdk.SpeechConfig(
                subscription=settings.azure_speech_key,
                region=settings.azure_speech_region,
            )
            # Continuous language identification — detects mid-call language switches
            self.speech_config.set_property(
                speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
                "Continuous",
            )
        else:
            self.speech_config = None
 
    # ── Public entrypoint ─────────────────────────────────────────────────────
 
    async def run(self, websocket) -> None:
        """Main event loop — listen, process, respond."""
        # Warm greeting
        greeting = TEMPLATES.get("greeting", "Thank you for calling InsureCo. How can I help you today?")
        await stream_tts_to_call(greeting, websocket, lang_code=self._detected_lang)
        self._add_to_history("assistant", greeting)
 
        while True:
            # ── Receive raw PCM audio from caller ─────────────────────────────
            try:
                audio_data = await asyncio.wait_for(
                    websocket.receive_bytes(), timeout=30.0
                )
            except asyncio.TimeoutError:
                farewell = TEMPLATES.get(
                    "farewell",
                    "It seems things have gone quiet. Thank you for calling InsureCo — take care!",
                )
                await stream_tts_to_call(farewell, websocket, lang_code=self._detected_lang)
                break
            except Exception:
                break
 
            # ── STT transcription ──────────────────────────────────────────────
            transcribed_text, detected_lang = await self._transcribe(audio_data)
            if detected_lang:
                self._detected_lang = detected_lang
 
            if not transcribed_text:
                # Politely ask for a repeat — rotate through clarification phrases
                clarify = random.choice(_CLARIFY_PHRASES)
                await stream_tts_to_call(clarify, websocket, lang_code=self._detected_lang)
                continue
 
            self._add_to_history("user", transcribed_text)
 
            # ── Empathetic bridge while AI pipeline runs ───────────────────────
            bridge = self._next_bridge_phrase()
            await stream_tts_to_call(bridge, websocket, lang_code=self._detected_lang)
 
            # ── Run CrewAI / RAG pipeline in thread executor ───────────────────
            loop = asyncio.get_event_loop()
            turn = await loop.run_in_executor(
                None,
                lambda: build_crew_for_query(
                    caller_input=transcribed_text,
                    caller_id=self.policy_id or self.call_id,
                    caller_phone=self.caller_phone,
                    conversation_history=self.conversation_history,
                    demo_mode=self.demo_mode,
                ),
            )
 
            final_response = turn.response_text if hasattr(turn, "response_text") else str(turn)
            self._add_to_history("assistant", final_response)
 
            # Use specific voice_id from portal render if available
            vid = turn.portal_render.voice_id if (hasattr(turn, "portal_render") and turn.portal_render) else None
            await stream_tts_to_call(
                final_response, websocket, voice_id=vid, lang_code=self._detected_lang
            )
 
    # ── Internal helpers ──────────────────────────────────────────────────────
 
    async def _transcribe(self, audio_bytes: bytes) -> tuple[str, str]:
        """
        Azure STT with multilingual auto-detect.
        Returns (transcribed_text, detected_language_code).
        Returns ("", "") on failure.
        """
        if not SPEECH_AVAILABLE or self.speech_config is None:
            return "", ""
        try:
            audio_stream = speechsdk.audio.PushAudioInputStream(
                stream_format=speechsdk.audio.AudioStreamFormat(
                    samples_per_second=16000,
                    bits_per_sample=16,
                    channels=1,
                )
            )
            audio_config = speechsdk.audio.AudioConfig(stream=audio_stream)
 
            # Multilingual auto-detect
            auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=["en-US", "es-ES", "fr-FR", "de-DE"]
            )
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=self.speech_config,
                auto_detect_source_language_config=auto_detect_config,
                audio_config=audio_config,
            )
 
            audio_stream.write(audio_bytes)
            audio_stream.close()
 
            result = await asyncio.to_thread(recognizer.recognize_once)
 
            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                # Extract detected language
                try:
                    lang_result = speechsdk.AutoDetectSourceLanguageResult(result)
                    language = lang_result.language or "en-US"
                except Exception:
                    language = "en-US"
                return result.text, language
 
        except Exception as e:
            print(f"[STT] Error during transcription: {e}")
        return "", ""
 
    def _next_bridge_phrase(self) -> str:
        """Returns a bridge phrase, avoiding the same one as last time."""
        available = [i for i in range(len(_BRIDGE_PHRASES)) if i != self._last_bridge_idx]
        idx = random.choice(available)
        self._last_bridge_idx = idx
        return _BRIDGE_PHRASES[idx]
 
    def _add_to_history(self, role: str, content: str) -> None:
        self.conversation_history.append({"role": role, "content": content})
        # Keep last 20 turns to avoid context bloat
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
 