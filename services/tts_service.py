"""
services/tts_service.py
 
Phase 7 — Text-to-Speech (Voice Synthesis)
 
Primary:  ElevenLabs API  — eleven_turbo_v2, tuned for empathy
Fallback: Azure Neural TTS — en-US-JennyNeural via SSML
             (warm pacing, customer-service style, gentle pauses)
 
Returns MP3/PCM audio bytes that are streamed back to the caller.
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
        ElevenLabs API call — tuned for empathetic, human-sounding delivery.
        - stability=0.42   : slight natural variability, avoids flat monotone
        - similarity_boost=0.80 : stays close to the chosen voice persona
        - style=0.40       : expressiveness that conveys warmth and care
        - use_speaker_boost: improves clarity on phone-quality audio
        """
        from elevenlabs.client import ElevenLabs
        from elevenlabs import VoiceSettings
 
        client = ElevenLabs(api_key=settings.elevenlabs_api_key)
 
        audio_generator = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=settings.elevenlabs_model_id,
            voice_settings=VoiceSettings(
                stability=0.36,
                similarity_boost=0.76,
                style=0.52,
                use_speaker_boost=True,
            ),
            output_format="mp3_44100_128",
        )
 
        return b"".join(audio_generator)
 
    def _azure_tts(self, text: str, lang_code: str = "en-US") -> bytes:
        """
        Azure Neural TTS with SSML for empathetic, natural-paced delivery.
        Voice: en-US-JennyNeural (warm, caring, ideal for support calls)
        Style: customerservice — attentive and helpful
        Prosody: 95% rate + gentle pauses = easier to follow on a phone call
        """
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
 
        # Escape XML-unsafe chars before injecting into SSML
        safe_text = (
            text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;")
        )
        ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{lang_code}">
  <voice name="en-US-AvaNeural">
    <mstts:express-as style="friendly" styledegree="1.2">
      <prosody rate="100%" pitch="+2%">
        <break time="90ms"/>{safe_text}<break time="90ms"/>
      </prosody>
    </mstts:express-as>
  </voice>
</speak>"""
 
        result = synthesizer.speak_ssml_async(ssml).get()
 
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            logger.info("tts_azure_ssml", chars=len(text), lang=lang_code)
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
        from elevenlabs import VoiceSettings
 
        client = ElevenLabs(api_key=settings.elevenlabs_api_key)
        voice_id = voice_id or settings.elevenlabs_voice_id
        vset = VoiceSettings(
            stability=0.36,
            similarity_boost=0.76,
            style=0.52,
            use_speaker_boost=True,
        )
 
        # ElevenLabs streaming
        audio_stream = client.text_to_speech.convert_as_stream(
            voice_id=voice_id,
            text=text,
            model_id=settings.elevenlabs_model_id,
            voice_settings=vset,
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
 