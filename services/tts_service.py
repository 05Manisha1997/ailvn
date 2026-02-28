"""
services/tts_service.py

Phase 7 — Text-to-Speech (Voice Synthesis)

Primary:  ElevenLabs API (10,000 chars/month free)
Fallback: Azure Cognitive Services TTS (500,000 chars/month free)

Returns PCM audio bytes that are streamed back to Genesis/caller.
"""
import asyncio
import io
from typing import AsyncGenerator, Optional
from enum import Enum

from config.settings import get_settings
from utils.logger import logger

settings = get_settings()


class TTSProvider(str, Enum):
    ELEVENLABS = "elevenlabs"
    AZURE = "azure"


class TTSService:
    """
    Unified TTS service with automatic provider fallback.
    ElevenLabs is used first for ultra-realistic speech.
    Azure TTS kicks in as overflow/fallback.
    """

    def __init__(self):
        self._elevenlabs_chars_used = 0
        self._monthly_limit = 10_000  # ElevenLabs free tier

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        provider: Optional[TTSProvider] = None,
    ) -> bytes:
        """
        Convert text to speech audio bytes.
        Returns MP3 audio suitable for streaming to Genesis.
        """
        if not text.strip():
            return b""

        voice_id = voice_id or settings.elevenlabs_voice_id

        # Choose provider
        if provider == TTSProvider.AZURE:
            return self._azure_tts(text)

        # Auto-select: ElevenLabs if within limits
        if (
            self._elevenlabs_chars_used + len(text) <= self._monthly_limit
            and settings.elevenlabs_api_key
        ):
            try:
                audio = self._elevenlabs_tts(text, voice_id)
                self._elevenlabs_chars_used += len(text)
                logger.info("tts_elevenlabs",
                            chars=len(text),
                            total_used=self._elevenlabs_chars_used)
                return audio
            except Exception as e:
                logger.warning("elevenlabs_failed_falling_back", error=str(e))

        # Fallback to Azure TTS
        return self._azure_tts(text)

    def _elevenlabs_tts(self, text: str, voice_id: str) -> bytes:
        """
        ElevenLabs API call.
        Free tier: 10,000 chars/month.
        Model: eleven_turbo_v2 (lowest latency, best for real-time calls).
        """
        from elevenlabs.client import ElevenLabs
        from elevenlabs import VoiceSettings

        client = ElevenLabs(api_key=settings.elevenlabs_api_key)

        audio_generator = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=settings.elevenlabs_model_id,
            voice_settings=VoiceSettings(
                stability=0.5,
                similarity_boost=0.75,
                style=0.0,
                use_speaker_boost=True,
            ),
            output_format="mp3_44100_128",
        )

        # Collect generator into bytes
        return b"".join(audio_generator)

    def _azure_tts(self, text: str) -> bytes:
        """
        Azure Cognitive Services TTS.
        Free: 500,000 characters/month.
        Uses neural voices for natural-sounding speech.
        """
        import azure.cognitiveservices.speech as speechsdk

        speech_config = speechsdk.SpeechConfig(
            subscription=settings.azure_speech_key,
            region=settings.azure_speech_region,
        )
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
        )
        # Use neural voice — sounds natural
        speech_config.speech_synthesis_voice_name = "en-US-JennyNeural"

        # Synthesize to memory stream
        audio_stream = speechsdk.audio.AudioOutputStream.create_pull_audio_output_stream()
        audio_config = speechsdk.audio.AudioConfig(stream=audio_stream)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        result = synthesizer.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            logger.info("tts_azure", chars=len(text))
            return result.audio_data
        else:
            raise RuntimeError(f"Azure TTS failed: {result.reason}")

    async def synthesize_streaming(
        self,
        text: str,
        voice_id: Optional[str] = None,
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream TTS audio chunks for low-latency playback.
        Useful for long responses — starts playing while still generating.
        Uses ElevenLabs streaming API.
        """
        if not settings.elevenlabs_api_key:
            # Non-streaming fallback
            audio = self._azure_tts(text)
            chunk_size = 4096
            for i in range(0, len(audio), chunk_size):
                yield audio[i:i + chunk_size]
            return

        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=settings.elevenlabs_api_key)
        voice_id = voice_id or settings.elevenlabs_voice_id

        # ElevenLabs streaming
        audio_stream = client.text_to_speech.convert_as_stream(
            voice_id=voice_id,
            text=text,
            model_id=settings.elevenlabs_model_id,
            output_format="mp3_44100_128",
        )

        for chunk in audio_stream:
            if chunk:
                yield chunk
                await asyncio.sleep(0)  # Yield control to event loop


class MockTTSService:
    """Mock TTS for development without API keys."""

    def synthesize(self, text: str, voice_id=None, provider=None) -> bytes:
        # Return silent audio bytes (1 second of silence)
        logger.debug("mock_tts", text_preview=text[:50])
        return b"\x00" * 16000 * 2  # 1 sec at 16kHz, 16-bit

    async def synthesize_streaming(self, text: str, voice_id=None):
        yield b"\x00" * 4096


def get_tts_service():
    if not settings.elevenlabs_api_key and not settings.azure_speech_key:
        logger.warning("no_tts_keys_using_mock")
        return MockTTSService()
    return TTSService()
