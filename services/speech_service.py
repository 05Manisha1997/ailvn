"""
services/speech_service.py
 
Phase 2 & 3 — Voice Capture, Noise Removal & Speech-to-Text
 
Uses Azure Cognitive Services Speech SDK:
- Built-in noise suppression (no extra cost)
- Continuous recognition for natural conversation flow
- Supports streaming audio from WebSocket/PSTN bridge
- Multilingual Auto-Detect (up to 4 candidate languages)
"""
import asyncio
import io
from typing import AsyncGenerator, Optional, Callable
from dataclasses import dataclass, field
 
from config.settings import get_settings
from config.azure_clients import get_speech_config
from utils.logger import logger
 
settings = get_settings()
 
 
@dataclass
class TranscriptResult:
    text: str
    confidence: float
    duration_ms: int
    is_final: bool
    language: str = "en-US"   # BCP-47 detected language code
 
 
class SpeechService:
    """
    Wraps Azure Speech SDK for:
    - Real-time STT with noise suppression
    - One-shot recognition (for short verification inputs)
    - Continuous recognition (for open queries)
    - Multilingual Auto-Detect (en-US, es-ES, fr-FR, de-DE)
    """
 
    # Azure standard endpoint supports max 4 candidate languages
    CANDIDATE_LANGUAGES = ["en-US", "es-ES", "fr-FR", "de-DE"]
 
    def __init__(self):
        self._speech_config = get_speech_config()
 
    def recognize_once(self, audio_data: bytes) -> TranscriptResult:
        """
        Recognize a single utterance from raw PCM audio bytes.
        Used for: phone number capture, verification responses.
        Returns the recognized text, confidence, and detected language.
        """
        import azure.cognitiveservices.speech as speechsdk
 
        stream = speechsdk.audio.PushAudioInputStream(
            stream_format=speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000,
                bits_per_sample=16,
                channels=1,
            )
        )
        stream.write(audio_data)
 
        audio_config = speechsdk.audio.AudioConfig(stream=stream)
 
        # Multilingual auto-detection
        auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.CANDIDATE_LANGUAGES
        )
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self._speech_config,
            auto_detect_source_language_config=auto_detect_config,
            audio_config=audio_config,
        )
 
        result = recognizer.recognize_once()
        stream.close()
 
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            # Extract detected language
            try:
                lang_result = speechsdk.AutoDetectSourceLanguageResult(result)
                language = lang_result.language or "en-US"
            except Exception:
                language = "en-US"
 
            # Extract confidence from JSON result
            try:
                import json
                props_json = result.properties.get(
                    speechsdk.PropertyId.SpeechServiceResponse_JsonResult
                )
                data = json.loads(props_json) if props_json else {}
                confidence = data.get("NBest", [{}])[0].get("Confidence", 0.9)
            except Exception:
                confidence = getattr(result, "confidence", 0.9)
 
            return TranscriptResult(
                text=result.text,
                confidence=float(confidence),
                duration_ms=result.duration // 10000 if hasattr(result, "duration") else 0,
                is_final=True,
                language=language,
            )
        elif result.reason == speechsdk.ResultReason.NoMatch:
            logger.warning("stt_no_match", details=str(result.no_match_details))
            return TranscriptResult(text="", confidence=0.0, duration_ms=0, is_final=True)
        else:
            raise RuntimeError(f"Speech recognition failed: {result.reason}")
 
    async def recognize_continuous(
        self,
        audio_stream_generator: AsyncGenerator[bytes, None],
        on_interim: Optional[Callable[[str], None]] = None,
    ) -> AsyncGenerator[TranscriptResult, None]:
        """
        Continuously transcribes audio from an async generator.
        Used for: open-ended user queries post-verification.
        Yields TranscriptResult for each recognized phrase (with language).
        """
        import azure.cognitiveservices.speech as speechsdk
 
        result_queue: asyncio.Queue[TranscriptResult] = asyncio.Queue()
        stop_event = asyncio.Event()
 
        push_stream = speechsdk.audio.PushAudioInputStream(
            stream_format=speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000,
                bits_per_sample=16,
                channels=1,
            )
        )
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.CANDIDATE_LANGUAGES
        )
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self._speech_config,
            auto_detect_source_language_config=auto_detect_config,
            audio_config=audio_config,
        )
 
        def on_recognized(evt):
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                try:
                    lang_result = speechsdk.AutoDetectSourceLanguageResult(evt.result)
                    language = lang_result.language or "en-US"
                except Exception:
                    language = "en-US"
 
                result_queue.put_nowait(TranscriptResult(
                    text=evt.result.text,
                    confidence=0.9,
                    duration_ms=evt.result.duration // 10000 if hasattr(evt.result, "duration") else 0,
                    is_final=True,
                    language=language,
                ))
 
        def on_recognizing(evt):
            if on_interim and evt.result.text:
                on_interim(evt.result.text)
 
        def on_session_stopped(evt):
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(stop_event.set)
            else:
                stop_event.set()
 
        recognizer.recognized.connect(on_recognized)
        recognizer.recognizing.connect(on_recognizing)
        recognizer.session_stopped.connect(on_session_stopped)
        recognizer.canceled.connect(on_session_stopped)
 
        # Start recognition in an executor thread (non-blocking)
        await asyncio.to_thread(recognizer.start_continuous_recognition)
 
        # Feed audio asynchronously
        async def feed_audio():
            try:
                async for chunk in audio_stream_generator:
                    push_stream.write(chunk)
            except Exception as e:
                logger.error("audio_feed_error", error=str(e))
            finally:
                push_stream.close()
 
        feed_task = asyncio.create_task(feed_audio())
 
        try:
            while not stop_event.is_set():
                try:
                    result = await asyncio.wait_for(result_queue.get(), timeout=0.1)
                    yield result
                except asyncio.TimeoutError:
                    if feed_task.done() and result_queue.empty():
                        await asyncio.sleep(0.5)  # Allow Azure to flush final chunks
                        break
                    continue
        finally:
            await asyncio.to_thread(recognizer.stop_continuous_recognition)
            # Drain any buffered results
            while not result_queue.empty():
                yield result_queue.get_nowait()
 
 
class MockSpeechService:
    """
    Mock STT for local development / testing without Azure credentials.
    Returns canned responses based on input length.
    """
 
    def recognize_once(self, audio_data: bytes) -> TranscriptResult:
        responses = [
            "My phone number is 415 555 2671",
            "Yes, my name is John Smith",
            "I want to check my account balance",
        ]
        idx = len(audio_data) % len(responses)
        return TranscriptResult(
            text=responses[idx],
            confidence=0.95,
            duration_ms=2000,
            is_final=True,
            language="en-US",
        )
 
    async def recognize_continuous(self, audio_stream_generator, on_interim=None):
        yield TranscriptResult(
            text="What is my current account balance and recent transactions?",
            confidence=0.92,
            duration_ms=3500,
            is_final=True,
            language="en-US",
        )
 
 
def get_speech_service() -> SpeechService:
    """Returns real or mock service based on config."""
    if not settings.azure_speech_key:
        logger.warning("azure_speech_key_missing", fallback="MockSpeechService")
        return MockSpeechService()
    return SpeechService()
 