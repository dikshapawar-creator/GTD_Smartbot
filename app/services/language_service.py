"""
Language detection and translation service.
Uses langdetect and deep-translator.
"""
import logging
from langdetect import detect, DetectorFactory
from deep_translator import GoogleTranslator

logger = logging.getLogger(__name__)

# Ensure deterministic language detection
DetectorFactory.seed = 0

def detect_and_translate(text: str) -> tuple[str, str]:
    """
    Detects language of input text. If not English, translates it to English.
    Returns a tuple of (detected_language_code, translated_text).
    """
    if not text or not text.strip():
        return "en", text
        
    # Quick fix for short texts being misclassified by langdetect (e.g. 'hi', 'hello' -> 'sw')
    # If it's a very short message containing only basic ASCII, it's overwhelmingly likely English
    # in this context, or at least not worth translating.
    if len(text.split()) <= 3 and all(ord(c) < 128 for c in text.strip()):
        return "en", text
        
    try:
        lang_code = detect(text)
        
        if lang_code != "en":
            translated_text = GoogleTranslator(source=lang_code, target='en').translate(text)
            return lang_code, translated_text
            
        return "en", text
    except Exception as e:
        logger.warning(f"Failed to detect or translate language: {e}. Falling back to default.")
        return "en", text
