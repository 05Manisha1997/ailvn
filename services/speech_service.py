"""
services/speech_service.py

Phase 2 & 3 — Voice Capture, Noise Removal & Speech-to-Text

Uses Azure Cognitive Services Speech SDK:
- Built-in noise suppression (no extra cost)
- Continuous recognition for natural conversation flow
- Supports streaming audio from WebSocket/PSTN bridge
"""
import asyncio
import io
from typing import AsyncGenerator, Optional, Callable
from dataclasses import dataclass

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


class SpeechService:
    """
    Wraps Azure Speech SDK for:
    - Real-time STT with noise suppression
    - One-shot recognition (for short verification inputs)
    - Continuous recognition (for open queries)
    """

    def __init__(self):
        self._speech_config = get_speech_config()

    def recognize_once(self, audio_data: bytes) -> TranscriptResult:
        """
        Recognize a single utterance from raw PCM audio bytes.
        Used for: phone number capture, verification responses.
        Returns the recognized text and confidence.
        """
        import azure.cognitiveservices.speech as speechsdk

        # Push audio stream from bytes
        stream = speechsdk.audio.PushAudioInputStream(
            stream_format=speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000,
                bits_per_sample=16,
                channels=1,
            )
        )
        stream.write(audio_data)

        audio_config = speechsdk.audio.AudioConfig(stream=stream)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self._speech_config,
            audio_config=audio_config,
        )

        result = recognizer.recognize_once()
        stream.close()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return TranscriptResult(
                text=result.text,
                confidence=result.confidence if hasattr(result, "confidence") else 0.9,
                duration_ms=result.duration // 10000,  # ticks to ms
                is_final=True,
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
        Yields TranscriptResult for each recognized phrase.

        Args:
            audio_stream_generator: Async generator yielding PCM audio chunks
            on_interim: Optional callback for interim (non-final) results
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
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self._speech_config,
            audio_config=audio_config,
        )

        def on_recognized(evt):
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                result_queue.put_nowait(TranscriptResult(
                    text=evt.result.text,
                    confidence=getattr(evt.result, "confidence", 0.9),
                    duration_ms=evt.result.duration // 10000,
                    is_final=True,
                ))

        def on_recognizing(evt):
            if on_interim and evt.result.text:
                on_interim(evt.result.text)

        def on_session_stopped(evt):
            stop_event.set()

        recognizer.recognized.connect(on_recognized)
        recognizer.recognizing.connect(on_recognizing)
        recognizer.session_stopped.connect(on_session_stopped)
        recognizer.canceled.connect(on_session_stopped)

        recognizer.start_continuous_recognition()

        # Push audio chunks into the stream
        async def feed_audio():
            async for chunk in audio_stream_generator:
                push_stream.write(chunk)
            push_stream.close()

        asyncio.create_task(feed_audio())

        # Yield results as they arrive
        while not stop_event.is_set() or not result_queue.empty():
            try:
                result = result_queue.get_nowait()
                yield result
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.05)

        recognizer.stop_continuous_recognition()


class MockSpeechService:
    """
    Mock STT for local development / testing without Azure credentials.
    Returns canned responses based on input length.
    """

    def recognize_once(self, audio_data: bytes) -> TranscriptResult:
        # Simulate different responses based on audio size
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
        )

    async def recognize_continuous(self, audio_stream_generator, on_interim=None):
        yield TranscriptResult(
            text="What is my current account balance and recent transactions?",
            confidence=0.92,
            duration_ms=3500,
            is_final=True,
        )


def get_speech_service() -> SpeechService:
    """Returns real or mock service based on config."""
    if not settings.azure_speech_key:
        logger.warning("azure_speech_key_missing", fallback="MockSpeechService")
        return MockSpeechService()
    return SpeechService()
