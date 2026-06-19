"""
tts.py — Text-to-speech via edge-tts (Microsoft Edge, online, high quality).
Falls back to Kokoro or pyttsx3 if available.
"""

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

        # H5.1 Local XTTS / ElevenLabs voice cloning integrations
        if v == "xtts" or (isinstance(v, str) and v.startswith("xtts:")) or (isinstance(v, str) and "xtts" in v.lower()):
            res = await self._speak_xtts(text, v)
            if res:
                return res
            v = "ro-RO-EmilNeural" if lang == "ro" else self.default_voice

        if v == "elevenlabs" or (isinstance(v, str) and v.startswith("elevenlabs:")) or (isinstance(v, str) and "elevenlabs" in v.lower()):
            res = await self._speak_elevenlabs(text, v)
            if res:
                return res
            v = "ro-RO-EmilNeural" if lang == "ro" else self.default_voice

        if HAS_EDGE:
            return await self._speak_edge(text, v)
        elif HAS_KOKORO:
            return await self._speak_kokoro(text, v)
        else:
            logger.warning("No TTS backend available. Install: pip install edge-tts")
            return None

    async def _speak_xtts(self, text: str, voice: str) -> Optional[str]:
        import httpx
        import os
        url = os.environ.get("XTTS_SERVER_URL", "http://localhost:8020/api/tts")
        speaker_wav = os.environ.get("XTTS_SPEAKER_WAV", "data/voice_clone/andrei.wav")
        out_path = TEMP_DIR / f"response_xtts_{abs(hash(text))}.wav"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json={
                    "text": text,
                    "speaker_wav": speaker_wav,
                    "language": "ro" if "ro" in voice.lower() else "en"
                })
                if resp.status_code == 200:
                    out_path.write_bytes(resp.content)
                    logger.info(f"XTTS Cloned Voice TTS saved: {out_path}")
                    return str(out_path)
                logger.warning(f"XTTS server returned status code {resp.status_code}")
        except Exception as e:
            logger.warning(f"Local XTTS server not available ({e}). Falling back to edge-tts.")
        return None

    async def _speak_elevenlabs(self, text: str, voice: str) -> Optional[str]:
        import httpx
        import os
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            logger.warning("ELEVENLABS_API_KEY not configured. Falling back to edge-tts.")
            return None
            
        voice_id = "pNInz6obpgq5ok2wIBG1"  # Default cloned/custom voice id
        if isinstance(voice, str) and ":" in voice:
            parts = voice.split(":")
            if len(parts) > 1 and parts[1]:
                voice_id = parts[1]
                
        out_path = TEMP_DIR / f"response_eleven_{abs(hash(text))}.mp3"
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json={
                    "text": text,
                    "model_id": "eleven_monolingual_v1",
                    "voice_settings": {
                        "stability": 0.75,
                        "similarity_boost": 0.75
                    }
                }, headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json"
                })
                if resp.status_code == 200:
                    out_path.write_bytes(resp.content)
                    logger.info(f"ElevenLabs TTS saved: {out_path}")
                    return str(out_path)
                logger.warning(f"ElevenLabs API returned status code {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.warning(f"ElevenLabs TTS failed ({e}). Falling back to edge-tts.")
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
