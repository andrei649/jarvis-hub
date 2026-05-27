"""
tts.py — Text-to-speech via edge-tts (Microsoft Edge, online, high quality).
Falls back to Kokoro or pyttsx3 if available.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.voice.tts")

try:
    import edge_tts
    HAS_EDGE = True
except ImportError:
    HAS_EDGE = False

try:
    import kokoro_tts
    HAS_KOKORO = False
except ImportError:
    HAS_KOKORO = False

TEMP_DIR = Path(tempfile.gettempdir()) / "cabinet_tts"


class TTSEngine:
    VOICE_MAP = {
        "ro": "ro-RO-EmilNeural",
        "en": "en-GB-RyanNeural",
        "en-us": "en-US-GuyNeural",
    }

    def __init__(self, default_voice: str = "en-GB-RyanNeural", default_lang: str = "en"):
        self.default_voice = default_voice
        self.default_lang = default_lang
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"TTS Engine ready (edge={HAS_EDGE}, kokoro={HAS_KOKORO})")

    async def speak(self, text: str, voice: str = None, lang: str = None) -> Optional[str]:
        """Synthesize speech, return path to audio file, or None."""
        v = voice or self.VOICE_MAP.get(lang, self.default_voice)

        if HAS_EDGE:
            return await self._speak_edge(text, v)
        elif HAS_KOKORO:
            return await self._speak_kokoro(text, v)
        else:
            logger.warning("No TTS backend available. Install: pip install edge-tts")
            return None

    async def _speak_edge(self, text: str, voice: str) -> str:
        out_path = TEMP_DIR / f"response_{abs(hash(text))}.mp3"
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(out_path))
            logger.info(f"TTS saved: {out_path}")
            return str(out_path)
        except Exception as e:
            logger.error(f"Edge TTS error: {e}")
            return None

    async def _speak_kokoro(self, text: str, voice: str) -> str:
        out_path = TEMP_DIR / f"response_{abs(hash(text))}.wav"
        try:
            import kokoro_tts as kokoro
            kokoro.tts(text, voice=voice, output=out_path)
            return str(out_path)
        except Exception as e:
            logger.error(f"Kokoro TTS error: {e}")
            return None
