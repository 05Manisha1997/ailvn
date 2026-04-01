"""
navigator.py
InsuranceVoiceNavigator — main call session orchestrator.
Handles STT (Azure Speech), CrewAI pipeline, and TTS (ElevenLabs) in a loop.
"""
import asyncio
import json
from config import settings
from agents.tasks import build_crew_for_query
from tts.elevenlabs_streamer import stream_tts_to_call
from templates.response_templates import fill_template, TEMPLATES

try:
    import azure.cognitiveservices.speech as speechsdk
    SPEECH_AVAILABLE = True
except ImportError:
    SPEECH_AVAILABLE = False


class InsuranceVoiceNavigator:
    """
    Manages a single call session end-to-end:
    1. Greet the caller with TTS
    2. Receive audio → STT transcription
    3. Run CrewAI 4-agent pipeline
    4. TTS response back to caller
    5. Repeat until call ends
    """

    def __init__(self, call_id: str, caller_phone: str = "unknown", demo_mode: bool = True):
        self.call_id = call_id
        self.caller_phone = caller_phone
        self.demo_mode = demo_mode or not settings.azure_speech_key
        self.conversation_history: list[dict] = []
        self.verified = False
        self.policy_id: str | None = None
        self.member_name: str | None = None

        if SPEECH_AVAILABLE and settings.azure_speech_key:
            self.speech_config = speechsdk.SpeechConfig(
                subscription=settings.azure_speech_key,
                region=settings.azure_speech_region,
            )
            # Enable continuous language identification
            self.speech_config.set_property(speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous")
        else:
            self.speech_config = None

    async def run(self, websocket) -> None:
        """Main event loop — listen, process, respond."""
        # Greet the caller
        greeting = TEMPLATES["greeting"]
        await stream_tts_to_call(greeting, websocket)
        self._add_to_history("assistant", greeting)

        while True:
            try:
                # Receive audio chunk from caller (raw PCM bytes from ACS)
                audio_data = await asyncio.wait_for(
                    websocket.receive_bytes(), timeout=30.0
                )
            except asyncio.TimeoutError:
                farewell = TEMPLATES["farewell"]
                await stream_tts_to_call(farewell, websocket)
                break
            except Exception:
                break

            # Short bridge message while CrewAI runs
            await stream_tts_to_call(
                "Let me check that for you, one moment please.", websocket
            )

            # STT
            transcribed_text = await self._transcribe(audio_data)
            if not transcribed_text:
                continue

            self._add_to_history("user", transcribed_text)

            # Run CrewAI (in executor to avoid blocking the event loop)
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

            final_response = turn.response_text

            self._add_to_history("assistant", final_response)

            vid = turn.portal_render.voice_id if turn.portal_render else None
            await stream_tts_to_call(final_response, websocket, voice_id=vid)

    async def _transcribe(self, audio_bytes: bytes) -> str:
        """Azure STT for real-time transcription. Returns empty string on failure."""
        if not SPEECH_AVAILABLE or self.speech_config is None:
            return ""
        try:
            audio_stream = speechsdk.audio.PushAudioInputStream()
            audio_config = speechsdk.audio.AudioConfig(stream=audio_stream)
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=self.speech_config,
                audio_config=audio_config,
            )
            audio_stream.write(audio_bytes)
            audio_stream.close()
            result = recognizer.recognize_once()
            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                return result.text
        except Exception as e:
            print(f"[STT] Error: {e}")
        return ""

    def _add_to_history(self, role: str, content: str) -> None:
        self.conversation_history.append({"role": role, "content": content})
        # Keep last 20 turns to avoid context bloat
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
