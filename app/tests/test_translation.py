import asyncio
import os
from dotenv import load_dotenv

# Load .env to get API key if available
load_dotenv()

from app.services.language_service import engine

async def test_detection():
    print("Testing Language Detection and Translation...")
    texts = [
        "Hola, necesito ayuda con mis importaciones",
        "Hello, I need some help",
        "Je voudrais voir les données d'exportation"
    ]
    
    for t in texts:
        print(f"\nInput: {t}")
        res = await engine.detect_and_translate(t)
        print(f"Detected: {res.get('detected_language')}")
        print(f"Translated: {res.get('translated_text')}")

async def test_bidirectional():
    print("\nTesting Bidirectional Translation...")
    text = "Our team will contact you soon."
    languages = ["Spanish", "French", "German"]
    
    for lang in languages:
        print(f"\nTarget Language: {lang}")
        res = await engine.translate_to_client(text, lang)
        print(f"To Client: {res}")

if __name__ == "__main__":
    asyncio.run(test_detection())
    asyncio.run(test_bidirectional())
