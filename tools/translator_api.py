import asyncio
from typing import Optional
from langdetect import detect, DetectorFactory
from deep_translator import GoogleTranslator

# To ensure consistent language detection
DetectorFactory.seed = 0

class LanguageTranslator:
    def __init__(self):
        pass

    async def detect_language(self, text: str) -> str:
        """
        Detects the language of the given text.
        Returns the ISO 639-1 language code (e.g., 'en', 'es', 'fr').
        Uses asyncio.to_thread to prevent blocking the event loop.
        """
        if not text or not text.strip():
            return 'en'
        try:
            lang_code = await asyncio.to_thread(detect, text)
            return lang_code
        except Exception as e:
            print(f"[LanguageTranslator] Error detecting language for text '{text}': {e}")
            return 'en'

    async def translate_text(self, text: str, target_lang: str) -> Optional[str]:
        """
        Translates the given text to the target language.
        Returns the translated string.
        Uses asyncio.to_thread to prevent blocking the event loop.
        """
        if not text or not text.strip() or target_lang == 'en' and await self.detect_language(text) == 'en':
             return text
        try:
            translator = GoogleTranslator(source='auto', target=target_lang)
            translated = await asyncio.to_thread(translator.translate, text)
            return translated
        except Exception as e:
            print(f"[LanguageTranslator] Error translating text to {target_lang}: {e}")
            return text

# Global instance for easy importing
translator = LanguageTranslator()
