# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Language Detection and Translation Utilities

Provides language detection and English translation for research documents.
Used by extraction pipelines to handle non-English PDFs.

Dependencies:
    pip install langdetect deep-translator
"""

from typing import Dict, Any

# Language code to human-readable name mapping (covers most scientific literature languages)
LANGUAGE_NAMES = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "fa": "Persian", "fi": "Finnish", "fr": "French",
    "gu": "Gujarati", "he": "Hebrew", "hi": "Hindi", "hr": "Croatian",
    "hu": "Hungarian", "id": "Indonesian", "it": "Italian", "ja": "Japanese",
    "kn": "Kannada", "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian",
    "mk": "Macedonian", "ml": "Malayalam", "mr": "Marathi", "ne": "Nepali",
    "nl": "Dutch", "no": "Norwegian", "pa": "Punjabi", "pl": "Polish",
    "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sk": "Slovak",
    "sl": "Slovenian", "so": "Somali", "sq": "Albanian", "sv": "Swedish",
    "sw": "Swahili", "ta": "Tamil", "te": "Telugu", "th": "Thai",
    "tl": "Filipino", "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu",
    "vi": "Vietnamese", "zh-cn": "Chinese (Simplified)", "zh-tw": "Chinese (Traditional)",
}

# Characters per chunk for translation.
# Google's free endpoint is unreliable above ~3000 chars, especially for CJK scripts.
_CHUNK_SIZE = 2500


def detect_language(text: str) -> Dict[str, Any]:
    """
    Detect the language of a text sample.

    Samples the first 1500 characters (after stripping markdown page headers)
    to keep detection fast and accurate.

    Args:
        text: Text to detect language for (typically extracted markdown)

    Returns:
        Dict with:
            - language_code: ISO 639-1 code (e.g., "ko", "fr")
            - language_name: Human-readable name (e.g., "Korean", "French")
            - confidence: Detection confidence 0.0-1.0
            - is_english: True if detected as English
            - detection_failed: True if detection could not be performed
    """
    try:
        from langdetect import detect_langs
        from langdetect import DetectorFactory

        # Make detection deterministic
        DetectorFactory.seed = 42

        # Strip markdown headers (## Page N) before sampling — they're always English
        # and would skew detection toward English for foreign-language docs
        import re
        clean_text = re.sub(r'^##\s+Page\s+\d+\s*$', '', text, flags=re.MULTILINE)
        clean_text = re.sub(r'^#\s+.+$', '', clean_text, flags=re.MULTILINE)
        clean_text = clean_text.strip()

        if len(clean_text) < 20:
            return {
                "language_code": "en",
                "language_name": "English",
                "confidence": 0.0,
                "is_english": True,
                "detection_failed": True
            }

        # Sample from 3 positions: start, ~30%, ~70%
        # Bilingual papers (e.g. Korean journals) often have an English abstract at the
        # top followed by a Korean body — single-position sampling hits the English part.
        total = len(clean_text)
        sample_size = 800
        positions = [0, int(total * 0.30), int(total * 0.70)]
        samples = [clean_text[p:p + sample_size] for p in positions if clean_text[p:p + sample_size].strip()]

        # Detect each sample and collect non-English votes
        non_english_votes = []
        for s in samples:
            r = detect_langs(s)
            if r and r[0].lang != "en" and r[0].prob > 0.5:
                non_english_votes.append((r[0].lang, r[0].prob))

        if non_english_votes:
            # Take the most confident non-English result
            lang_code, confidence = max(non_english_votes, key=lambda x: x[1])
        else:
            # All samples detected as English — use first sample result
            r = detect_langs(samples[0])
            lang_code = r[0].lang
            confidence = r[0].prob

        confidence = round(confidence, 3)
        language_name = LANGUAGE_NAMES.get(lang_code, lang_code.upper())
        is_english = lang_code == "en"

        return {
            "language_code": lang_code,
            "language_name": language_name,
            "confidence": confidence,
            "is_english": is_english,
            "detection_failed": False
        }

    except Exception as e:
        print(f"[LanguageUtils] Detection failed: {e}")
        return {
            "language_code": "en",
            "language_name": "English",
            "confidence": 0.0,
            "is_english": True,
            "detection_failed": True
        }


def translate_to_english(text: str, source_language: str) -> Dict[str, Any]:
    """
    Translate text to English using Google Translate (via deep-translator).

    Chunks the text to handle documents exceeding the per-request character limit.
    On failure, returns the original text so extraction can still proceed
    (degraded quality, but not a hard failure).

    Args:
        text: Full text to translate
        source_language: ISO 639-1 language code (e.g., "ko", "fr")

    Returns:
        Dict with:
            - translated_text: English text (original text if translation failed)
            - translation_note: Human-readable note for the report/UI
            - success: True if translation succeeded
            - error_message: Description of failure if success=False
    """
    try:
        from deep_translator import GoogleTranslator

        language_name = LANGUAGE_NAMES.get(source_language, source_language.upper())

        # Split into chunks to stay within Google Translate's per-request limit
        chunks = _split_into_chunks(text, _CHUNK_SIZE)
        translated_chunks = []

        import time
        from langdetect import detect

        translator = GoogleTranslator(source=source_language, target="en")

        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                translated_chunks.append(chunk)
                continue

            # Skip chunks already in English — bilingual documents often mix languages
            try:
                chunk_lang = detect(chunk[:500])
                if chunk_lang == "en":
                    translated_chunks.append(chunk)
                    continue
            except Exception:
                pass  # If detection fails, proceed with translation

            # Retry up to 3 times with backoff — Google's free endpoint rate-limits rapid requests
            for attempt in range(3):
                try:
                    translated_chunk = translator.translate(chunk)
                    translated_chunks.append(translated_chunk or chunk)
                    break
                except Exception as chunk_err:
                    if attempt < 2:
                        wait = 2 + attempt  # 2s, 3s
                        print(f"[LanguageUtils] Chunk {i+1} attempt {attempt+1} failed, retrying in {wait}s: {chunk_err}")
                        time.sleep(wait)
                    else:
                        raise  # Re-raise on final attempt

            # Pause between translated chunks to avoid rate limiting
            if i < len(chunks) - 1:
                time.sleep(1.0)

        translated_text = "\n".join(translated_chunks)

        print(f"[LanguageUtils] Translated {len(chunks)} chunk(s) from {language_name} to English")

        return {
            "translated_text": translated_text,
            "translation_note": f"Translated from {language_name}",
            "success": True,
            "error_message": None
        }

    except Exception as e:
        language_name = LANGUAGE_NAMES.get(source_language, source_language.upper())
        print(f"[LanguageUtils] Translation from {language_name} failed: {e}. Proceeding with original text.")

        return {
            "translated_text": text,
            "translation_note": f"Translation from {language_name} attempted but failed — extracted from original",
            "success": False,
            "error_message": str(e)
        }


def _split_into_chunks(text: str, chunk_size: int) -> list:
    """
    Split text into chunks of at most chunk_size characters, breaking on newlines
    where possible to avoid cutting mid-sentence.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break

        # Find the last newline within the chunk window
        split_at = text.rfind('\n', 0, chunk_size)
        if split_at == -1:
            # No newline found — hard cut at chunk_size
            split_at = chunk_size

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip('\n')

    return chunks
