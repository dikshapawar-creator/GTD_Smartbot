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
        
    # ⚡ OPTIMIZATION: skip detection/translation for most common English messages
    # If text is ASCII and contains common English words or is very short, assume English.
    text_stripped = text.strip()
    is_ascii = all(ord(c) < 128 for c in text_stripped)
    
    if is_ascii:
        # Common English greeting/fallback words
        common_en = {'hi', 'hello', 'hey', 'thanks', 'thank', 'yes', 'no', 'ok', 'okay', 'help', 'bye'}
        words = text_stripped.lower().split()
        if len(words) <= 2 and any(w in common_en for w in words):
            return "en", text
        
        # If it's a bit longer but still pure ASCII and looks like normal English, skip to save latency
        if len(text_stripped) < 20: 
            return "en", text
            
    try:
        # Only perform heavy detection if it's not obviously English
        lang_code = detect(text)
        
        if lang_code != "en":
            logger.info(f"Translating from {lang_code} to en...")
            translated_text = GoogleTranslator(source=lang_code, target='en').translate(text)
            return lang_code, translated_text
            
        return "en", text
    except Exception as e:
        logger.warning(f"Failed to detect or translate language: {e}. Falling back to default.")
        return "en", text
