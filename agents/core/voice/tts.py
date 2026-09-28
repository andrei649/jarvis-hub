"""
tts.py — Text-to-speech via edge-tts (Microsoft Edge, online, high quality).
Falls back to Kokoro or pyttsx3 if available.

H613 — two local paths (``local_providers``): ``piper:<model>`` (and bare ``piper``)
voices run Piper, and ``command`` voices run the owner's approved TTS command provider.
Both sit after the persona/cloned-voice consent gate, which is unchanged: a Piper model
or a command voice whose name happens to contain ``xtts``/``elevenlabs``/``fish`` still
needs consent (the gate matches by substring and fails closed), and with consent it goes
to Piper or the command, never to Fish or XTTS. Bare ``piper`` (a model picked by
language) never picks a model the gate would flag unless consent is granted.

When ``voice.tts_voice`` is a Piper or command voice, it is the voice a request with only
a language gets too (the HUD, spoken replies, the voice channel); bare ``piper`` picks the
model for that language. Any failure falls back to the built-in safe default — an edge /
Kokoro voice for the language, never the local voice that just failed.

``voice.local_only`` keeps speech on this machine: Piper, Kokoro or XTTS. Edge,
ElevenLabs, Fish and the TTS command are never called then (the hub cannot check where
a command sends the text), and availability reports say so.
"""

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from . import local_providers
from .sentence_stream import split_sentences
from .speech_text import for_speech, speech_lang

logger = logging.getLogger("jarvis.voice.tts")

try:
    import edge_tts
    HAS_EDGE = True
except ImportError:
    HAS_EDGE = False

try:
    import kokoro_tts
    HAS_KOKORO = True
except ImportError:
    HAS_KOKORO = False

TEMP_DIR = Path(tempfile.gettempdir()) / "cabinet_tts"

PERSONA_VOICE_CONSENT_CATEGORY = "voice"
PERSONA_VOICE_CONSENT_KEY = "persona_voice_consent"
PERSONA_VOICE_CONSENT_MESSAGE = (
    "Cloned/persona voice playback requires recorded owner consent; using default voice."
)
PERSONA_VOICE_MARKERS = ("xtts", "elevenlabs", "fish")


def local_voice_kind(voice: object) -> str | None:
    """``"piper"`` for ``piper`` / ``piper:<model>``, ``"command"`` for ``command`` /
    ``command:…`` (the part after the colon is ignored), else None (H613)."""
    if not isinstance(voice, str):
        return None
    lowered = voice.strip().lower()
    for kind in ("piper", "command", "provider"):
        if lowered == kind or lowered.startswith(kind + ":"):
            return kind
    return None


def tts_available() -> bool:
    """Whether a server-side TTS path exists for the owner's settings (H613): edge, Kokoro,
    Piper with a model, a ready command provider, or a configured XTTS / ElevenLabs / Fish.
    With ``voice.local_only`` only Piper, Kokoro or XTTS count."""
    from agents.core.env_config import env_str

    if local_providers.local_only():
        return bool(HAS_KOKORO or env_str("XTTS_SERVER_URL") or local_providers.piper_status()["available"])
    if HAS_EDGE or HAS_KOKORO:
        return True
    if any(env_str(name) for name in ("XTTS_SERVER_URL", "ELEVENLABS_API_KEY", "FISH_AUDIO_API_KEY")):
        return True
    try:
        named = any(row["ready"] for row in local_providers.named_command_status("tts"))
    except Exception:
        named = False
    return bool(local_providers.piper_status()["available"] or local_providers.command_ready("tts").ok or named)

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
        """The built-in voice a failure (or a blocked voice) falls back to: the configured
        default when it is an edge / Kokoro voice, else the edge voice for the language
        (the request's, else the default Piper model's, else the default language's).
        Never a persona/cloned voice and never a Piper or command voice (H613): those are
        what just failed, and edge / Kokoro cannot speak them."""
        candidate = self.VOICE_MAP.get(lang) or self.default_voice
        if not is_persona_or_cloned_voice(candidate) and not local_voice_kind(candidate):
            return candidate
        fallback = (self.VOICE_MAP.get(lang) or self.VOICE_MAP.get(local_providers.model_lang(self.default_voice))
                    or self.VOICE_MAP.get(self.default_lang))
        if fallback and not is_persona_or_cloned_voice(fallback):
            return fallback
        return "en-GB-RyanNeural"

    def _voice_for(self, voice: str = None, lang: str = None) -> str:
        """The voice a request speaks with: the one it names, else the owner's Piper or
        command voice (``voice.tts_voice``) whatever the language, else the edge voice for
        the language, else the default (H613)."""
        if voice:
            return voice
        if local_voice_kind(self.default_voice):
            return self.default_voice
        return self.VOICE_MAP.get(lang, self.default_voice)

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

    def speech_for(self, text: str, voice: str = None, lang: str = None) -> str:
        """*text* as it should be heard with this voice and language (H526)."""
        v = self._voice_for(voice, lang)
        return for_speech(text, lang=speech_lang(lang, v, default=self.default_lang))

    async def speak(self, text: str, voice: str = None, lang: str = None) -> Optional[str]:
        """Synthesize speech, return path to audio file, or None.

        Every caller's text is normalised first (H526, :func:`speech_text.for_speech`:
        no reasoning, code, markup, emoji or unread symbols); nothing left to say is no
        synthesis at all."""
        v = self._voice_for(voice, lang)
        named = None
        if local_voice_kind(v) == "provider":
            from .provider_registry import speech_registry
            try:
                named = speech_registry("tts").get("tts", v[len("provider:"):])
            except Exception:
                return None
            if named is None:
                return None
        text = for_speech(text, lang=speech_lang(lang, v, default=self.default_lang))
        if not text:
            logger.info("TTS: nothing to say after normalising the reply")
            return None
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

        # H613 — read now: the owner can flip it at any time.
        local_only = local_providers.local_only()
        tried_piper = None
        # H613 — Piper and command voices, after the consent gate and before Fish.
        kind = local_voice_kind(v)
        if kind in {"command", "provider"} and local_only:
            # The hub cannot check where a command sends the text: local_only never runs it.
            logger.info("voice.local_only: the TTS command is not used; speaking with a local engine")
            kind, v = None, self._safe_default_voice(lang)
        if kind:
            spoken = strip_emotion_tags(text)
            if not spoken:
                return None
            if kind == "provider":
                res = await named.synthesize(spoken, lang, temp_dir=TEMP_DIR, default_lang=self.default_lang)
            else:
                res = await (self._speak_piper(spoken, v, lang) if kind == "piper" else self._speak_command(spoken, lang))
            if res:
                return res
            tried_piper = v if kind == "piper" else None
            v = self._safe_default_voice(lang)

        # Fish Audio (cloned voice + inline [emotion] tags) runs first so the
        # tags survive; every backend below gets tag-stripped text.
        if isinstance(v, str) and "fish" in v.lower():
            res = None if local_only else await self._speak_fish(text, v)
            if res:
                return res
            v = self._safe_default_voice(lang)

        text = strip_emotion_tags(text)
        if not text:                    # the reply was only emotion tags: nothing to say
            return None

        # H5.1 Local XTTS / ElevenLabs voice cloning integrations
        if v == "xtts" or (isinstance(v, str) and v.startswith("xtts:")) or (isinstance(v, str) and "xtts" in v.lower()):
            res = await self._speak_xtts(text, v)
            if res:
                return res
            v = self._safe_default_voice(lang)

        if v == "elevenlabs" or (isinstance(v, str) and v.startswith("elevenlabs:")) or (isinstance(v, str) and "elevenlabs" in v.lower()):
            res = None if local_only else await self._speak_elevenlabs(text, v)
            if res:
                return res
            v = self._safe_default_voice(lang)

        if local_only:                  # H613: Piper, then Kokoro; never a cloud voice
            # The Piper model that already failed above is not run again (verify round, N3).
            again = tried_piper is None or not await asyncio.to_thread(self._same_piper_pick, tried_piper, lang)
            res = await self._speak_piper(text, "piper", lang) if again else None
            if res:
                return res
            if HAS_KOKORO:
                return await self._speak_kokoro(text, v)
            logger.warning("voice.local_only: no local TTS engine answered (install piper-tts or kokoro)")
            return None
        if HAS_EDGE:
            return await self._speak_edge(text, v)
        elif HAS_KOKORO:
            return await self._speak_kokoro(text, v)
        res = await self._speak_piper(text, "piper", lang)
        if res:
            return res
        logger.warning("No TTS backend available. Install: pip install edge-tts (or piper-tts)")
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
        # Normalised whole first (H526), so a code block or a reasoning block that spans
        # sentences is dropped whole instead of being read a line at a time.
        sentences = split_sentences(self.speech_for(text, voice=voice, lang=lang))
        for idx, sentence in enumerate(sentences):
            try:
                path = await self.speak(sentence, voice=voice, lang=lang)
            except Exception as e:  # pragma: no cover - defensive; per-chunk isolation
                logger.warning(f"sentence {idx} TTS failed ({e}); continuing")
                path = None
            yield idx, sentence, path

    def _same_piper_pick(self, tried: str, lang: str = None) -> bool:
        """Whether bare ``piper`` would pick the model the voice *tried* named (verify round, N3)."""
        if ":" not in tried:
            return True
        allow = voice_persona_consent_granted(self._consent_getter)
        pick_lang = lang or local_providers.model_lang(self.default_voice) or self.default_lang
        return local_providers.pick_piper_model(pick_lang, allow_persona=allow) == tried.split(":", 1)[1]

    async def _speak_piper(self, text: str, voice: str, lang: str = None) -> Optional[str]:
        """Piper (H613): ``piper:<model>``, or bare ``piper`` (a model picked by language:
        the request's, else the default Piper model's, else the default language). Bare
        ``piper`` never picks a model the consent gate would flag unless consent is granted."""
        bare = local_voice_kind(voice) == "piper" and ":" not in voice
        allow = voice_persona_consent_granted(self._consent_getter) if bare else False
        pick_lang = lang or local_providers.model_lang(self.default_voice) or self.default_lang
        return await local_providers.speak_piper(text, voice, pick_lang, temp_dir=TEMP_DIR, allow_persona=allow)

    async def _speak_command(self, text: str, lang: str = None) -> Optional[str]:
        """The owner's approved TTS command provider (H613). The voice's ``command:…``
        suffix is never used: the argv is exactly the approved one."""
        return await local_providers.speak_command(text, lang, temp_dir=TEMP_DIR,
                                                   default_lang=self.default_lang)

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
