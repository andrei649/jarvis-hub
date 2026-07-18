"""
tts.py — Text-to-speech via edge-tts (Microsoft Edge, online, high quality).
Falls back to Kokoro or pyttsx3 if available.
"""

import logging
import re
import tempfile
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from .sentence_stream import split_sentences

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

PERSONA_VOICE_CONSENT_CATEGORY = "voice"
PERSONA_VOICE_CONSENT_KEY = "persona_voice_consent"
PERSONA_VOICE_CONSENT_MESSAGE = (
    "Cloned/persona voice playback requires recorded owner consent; using default voice."
)
PERSONA_VOICE_MARKERS = ("xtts", "elevenlabs", "fish")

# Fish Audio S-series models understand inline square-bracket emotion tags
# ([calm], [amused], …). Every other backend would read them aloud, so the
# known tags are stripped before synthesis everywhere except the Fish path.
EMOTION_TAGS = (
    "calm", "amused", "excited", "cheerful", "serious", "sad", "angry",
    "surprised", "delighted", "whisper", "confident", "warm",
)
_EMOTION_TAG_RE = re.compile(r"\[(?:" + "|".join(EMOTION_TAGS) + r")\]\s*", re.IGNORECASE)


def strip_emotion_tags(text: str) -> str:
    """Remove known ``[emotion]`` tags; unknown bracketed text is left alone."""
    if not isinstance(text, str) or "[" not in text:
        return text
    return _EMOTION_TAG_RE.sub("", text).strip()


def is_persona_or_cloned_voice(voice: str | None) -> bool:
    """Whether a requested voice can represent a cloned/persona voice."""
    if not isinstance(voice, str):
        return False
    normalized = voice.lower()
    return any(marker in normalized for marker in PERSONA_VOICE_MARKERS)


def voice_persona_consent_granted(consent_getter: Optional[Callable[[], bool]] = None) -> bool:
    """Read persisted owner consent; fail closed when settings are unavailable."""
    if consent_getter is not None:
        return bool(consent_getter())
    try:
        try:
            from core.settings_db import get_value
        except Exception:
            from agents.core.settings_db import get_value
        return bool(get_value(PERSONA_VOICE_CONSENT_CATEGORY, PERSONA_VOICE_CONSENT_KEY, False))
    except Exception:
        logger.warning("Could not read voice persona consent; defaulting to off", exc_info=True)
        return False


def voice_persona_consent_status(
    consent_getter: Optional[Callable[[], bool]] = None,
) -> dict[str, object]:
    granted = voice_persona_consent_granted(consent_getter)
    return {
        "required": True,
        "granted": granted,
        "allowed": granted,
        "setting": f"{PERSONA_VOICE_CONSENT_CATEGORY}.{PERSONA_VOICE_CONSENT_KEY}",
        "message": None if granted else PERSONA_VOICE_CONSENT_MESSAGE,
    }


class TTSEngine:
    VOICE_MAP = {
        "ro": "ro-RO-EmilNeural",
        "en": "en-GB-RyanNeural",
        "en-us": "en-US-GuyNeural",
    }

    def __init__(
        self,
        default_voice: str = "en-GB-RyanNeural",
        default_lang: str = "en",
        consent_getter: Optional[Callable[[], bool]] = None,
    ):
        self.default_voice = default_voice
        self.default_lang = default_lang
        self._consent_getter = consent_getter
        self.last_consent_status: dict[str, object] = {
            "required": False,
            "granted": True,
            "allowed": True,
            "message": None,
        }
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"TTS Engine ready (edge={HAS_EDGE}, kokoro={HAS_KOKORO})")

    def _safe_default_voice(self, lang: str = None) -> str:
        candidate = self.VOICE_MAP.get(lang) or self.default_voice
        if not is_persona_or_cloned_voice(candidate):
            return candidate
        fallback = self.VOICE_MAP.get(lang) or self.VOICE_MAP.get(self.default_lang)
        if fallback and not is_persona_or_cloned_voice(fallback):
            return fallback
        return "en-GB-RyanNeural"

    def _persona_voice_allowed(self, requested_voice: str, lang: str = None) -> bool:
        fallback = self._safe_default_voice(lang)
        granted = voice_persona_consent_granted(self._consent_getter)
        self.last_consent_status = {
            "required": True,
            "granted": granted,
            "allowed": granted,
            "requested_voice": requested_voice,
            "fallback_voice": fallback,
            "setting": f"{PERSONA_VOICE_CONSENT_CATEGORY}.{PERSONA_VOICE_CONSENT_KEY}",
            "message": None if granted else PERSONA_VOICE_CONSENT_MESSAGE,
        }
        if not granted:
            logger.warning(
                "Blocked cloned/persona voice %r without owner consent; using %r",
                requested_voice,
                fallback,
            )
        return granted

    async def speak(self, text: str, voice: str = None, lang: str = None) -> Optional[str]:
        """Synthesize speech, return path to audio file, or None."""
        v = voice or self.VOICE_MAP.get(lang, self.default_voice)
        self.last_consent_status = {
            "required": False,
            "granted": True,
            "allowed": True,
            "requested_voice": v,
            "fallback_voice": None,
            "message": None,
        }

        if is_persona_or_cloned_voice(v) and not self._persona_voice_allowed(v, lang):
            v = self._safe_default_voice(lang)

        # Fish Audio (cloned voice + inline [emotion] tags) runs first so the
        # tags survive; every backend below gets tag-stripped text.
        if isinstance(v, str) and "fish" in v.lower():
            res = await self._speak_fish(text, v)
            if res:
                return res
            v = self._safe_default_voice(lang)

        text = strip_emotion_tags(text)

        # H5.1 Local XTTS / ElevenLabs voice cloning integrations
        if v == "xtts" or (isinstance(v, str) and v.startswith("xtts:")) or (isinstance(v, str) and "xtts" in v.lower()):
            res = await self._speak_xtts(text, v)
            if res:
                return res
            v = self._safe_default_voice(lang)

        if v == "elevenlabs" or (isinstance(v, str) and v.startswith("elevenlabs:")) or (isinstance(v, str) and "elevenlabs" in v.lower()):
            res = await self._speak_elevenlabs(text, v)
            if res:
                return res
            v = self._safe_default_voice(lang)

        if HAS_EDGE:
            return await self._speak_edge(text, v)
        elif HAS_KOKORO:
            return await self._speak_kokoro(text, v)
        else:
            logger.warning("No TTS backend available. Install: pip install edge-tts")
            return None

    async def speak_stream(
        self, text: str, voice: str = None, lang: str = None,
    ) -> AsyncIterator[tuple[int, str, Optional[str]]]:
        """Sentence-level streaming synthesis (H5.16).

        Splits `text` into sentences and synthesizes them one at a time, yielding
        ``(index, sentence, audio_path)`` as each chunk is ready — so a caller can
        start playback after the first sentence instead of waiting for the whole
        reply. `audio_path` is None for a sentence that failed to synthesize (the
        stream continues; the caller decides whether to skip or fall back).

        The segmentation is the pure `split_sentences`; only the per-chunk synthesis
        here touches a backend. Falls back to a single chunk if there's no boundary.
        """
        sentences = split_sentences(text)
        for idx, sentence in enumerate(sentences):
            try:
                path = await self.speak(sentence, voice=voice, lang=lang)
            except Exception as e:  # pragma: no cover - defensive; per-chunk isolation
                logger.warning(f"sentence {idx} TTS failed ({e}); continuing")
                path = None
            yield idx, sentence, path

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

    async def _speak_fish(self, text: str, voice: str) -> Optional[str]:
        """Fish Audio TTS (https://fish.audio) — cloned voices + inline [emotion] tags.

        Voice forms: ``fish`` (reference voice from FISH_AUDIO_VOICE_ID) or
        ``fish:<reference_id>``. The model header is FISH_AUDIO_MODEL (default
        ``s1``); S-series models honor square-bracket emotion tags, so the text
        is passed through unstripped.
        """
        import os

        import httpx
        api_key = os.environ.get("FISH_AUDIO_API_KEY")
        if not api_key:
            logger.warning("FISH_AUDIO_API_KEY not configured. Falling back to edge-tts.")
            return None

        reference_id = os.environ.get("FISH_AUDIO_VOICE_ID", "")
        if isinstance(voice, str) and ":" in voice:
            parts = voice.split(":", 1)
            if len(parts) > 1 and parts[1]:
                reference_id = parts[1]

        model = os.environ.get("FISH_AUDIO_MODEL", "s1")
        url = os.environ.get("FISH_AUDIO_URL", "https://api.fish.audio/v1/tts")
        out_path = TEMP_DIR / f"response_fish_{abs(hash(text))}.mp3"
        payload: dict = {"text": text, "format": "mp3"}
        if reference_id:
            payload["reference_id"] = reference_id

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "model": model,
                })
                if resp.status_code == 200:
                    out_path.write_bytes(resp.content)
                    logger.info(f"Fish Audio TTS saved: {out_path}")
                    return str(out_path)
                logger.warning(f"Fish Audio API returned status code {resp.status_code}")
        except Exception as e:
            logger.warning(f"Fish Audio TTS failed ({e}). Falling back to edge-tts.")
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
