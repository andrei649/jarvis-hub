"""Voice endpoints — TTS, sentence-level streaming TTS, STT, capabilities (extracted from web.py, CLN-3).

Covers the browser-facing voice loop's server side:
- `POST /tts` — synthesize a whole reply to MP3 (edge-tts).
- `POST /tts/stream` — H5.16 sentence-level streaming (opt-in `voice.sentence_streaming`,
  default off → 409); frames one sentence's audio at a time so playback starts after #1.
- `POST /api/voice/stt` — transcribe a raw browser MediaRecorder blob via local Whisper.
- `GET /api/voice/capabilities` — honest report of what the host's voice engines can do.

The `_STT_ENGINE` singleton + `_stt_engine()` accessor and the `TTSRequest` model /
`_tts_stream_enabled()` helper are voice-only (no external use, no test rebinds them),
so they move here with the domain. No orchestrator dependency.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["voice"])


# ── TTS endpoint ─────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str = Field(..., max_length=4096)
    lang: str = "ro"
    voice: Optional[str] = None   # "xtts" (cloned), "elevenlabs", or an edge voice; None = default chain


@router.post("/tts", dependencies=[Depends(user_guard)])
async def tts_endpoint(req: TTSRequest):
    """Synthesize text to speech and return MP3 audio."""
    try:
        from core.voice.tts import HAS_EDGE, TTSEngine
        if not HAS_EDGE:
            return JSONResponse(
                {"error": "edge-tts not installed. Run: pip install edge-tts"},
                status_code=503,
            )
        from core.settings_db import get_value
        engine = TTSEngine(default_voice=get_value("voice", "tts_voice", "en-GB-RyanNeural"))
        audio_path = await engine.speak(req.text, voice=req.voice, lang=req.lang)
        if not audio_path:
            return JSONResponse({"error": "TTS synthesis failed"}, status_code=500)
        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache"},
        )
    except Exception:
        logger.exception("TTS error")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)


# ── Sentence-level streaming TTS (H5.16) ─────────────────────────
#
# `/tts` synthesizes the whole reply before any audio comes back, so the user waits
# for the full message. `/tts/stream` splits the reply into sentences and streams each
# one's audio as soon as it's synthesized, so playback can start after sentence #1.
# Opt-in: gated by the `voice.sentence_streaming` setting (default off — back-compat).
#
# Wire framing (one frame per sentence, in order):
#   <json-header>\n<raw-audio-bytes>
# where the header is a single-line JSON object
#   {"idx": int, "text": str, "lang": str, "bytes": int, "done": bool}
# and exactly `bytes` audio bytes follow. A terminal frame {"done": true, "bytes": 0}
# (no audio) closes the stream. A sentence that failed to synthesize gets bytes:0 and
# is skipped by the client. This is multipart-free (no python-multipart) like /tts.

def _tts_stream_enabled() -> bool:
    """Whether sentence-level streaming TTS is turned on (default off)."""
    from core.settings_db import get_value
    return bool(get_value("voice", "sentence_streaming", False))


@router.post("/tts/stream", dependencies=[Depends(user_guard)])
async def tts_stream_endpoint(req: TTSRequest):
    """Stream sentence-by-sentence TTS audio frames (opt-in). See module comment."""
    import json as _json

    from core.voice.tts import HAS_EDGE, TTSEngine

    if not _tts_stream_enabled():
        return JSONResponse(
            {"error": "sentence streaming disabled. Enable voice.sentence_streaming.",
             "enabled": False},
            status_code=409,
        )
    if not HAS_EDGE:
        return JSONResponse(
            {"error": "edge-tts not installed. Run: pip install edge-tts"},
            status_code=503,
        )
    from core.settings_db import get_value
    engine = TTSEngine(default_voice=get_value("voice", "tts_voice", "en-GB-RyanNeural"))

    async def _gen():
        try:
            async for idx, sentence, path in engine.speak_stream(
                req.text, voice=req.voice, lang=req.lang,
            ):
                audio = b""
                if path:
                    try:
                        # Offload the per-chunk disk read so reading one sentence's
                        # audio doesn't block the event loop mid-stream (audit A4).
                        audio = await asyncio.to_thread(Path(path).read_bytes)
                    except Exception:
                        logger.warning("tts/stream: cannot read chunk %s", path)
                        audio = b""
                header = _json.dumps({
                    "idx": idx, "text": sentence, "lang": req.lang,
                    "bytes": len(audio), "done": False,
                })
                yield header.encode("utf-8") + b"\n" + audio
        except Exception:
            logger.exception("tts/stream error")
        # Terminal frame.
        yield _json.dumps({"idx": -1, "text": "", "lang": req.lang, "bytes": 0,
                           "done": True}).encode("utf-8") + b"\n"

    return StreamingResponse(
        _gen(),
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── STT endpoint (browser mic → local Whisper) ───────────────────
#
# The voice engines (Whisper/edge-tts/XTTS) were built for Howard — a mic wired to
# the server. The HUD runs in a browser, so the loop is: browser captures audio
# (getUserMedia/MediaRecorder) → POSTs the blob here → local Whisper transcribes →
# normal /chat/stream. Honest degradation: if faster-whisper isn't installed we 503
# with an install hint — never a fabricated transcript.

_STT_ENGINE = None


def _stt_engine():
    """Lazily build and cache one Whisper engine (model load is expensive)."""
    global _STT_ENGINE
    if _STT_ENGINE is None:
        from core.settings_db import get_value
        from core.voice.stt import STTEngine
        _STT_ENGINE = STTEngine(model_size=get_value("voice", "stt_model_size", "medium"))
    return _STT_ENGINE


@router.post("/api/voice/stt", dependencies=[Depends(user_guard)])
async def stt_endpoint(request: Request, lang: Optional[str] = Query(None)):
    """Transcribe a raw audio body (browser MediaRecorder blob) via local Whisper.

    Raw body (not multipart) keeps this dependency-free — no python-multipart needed.
    Language falls back to the /admin `voice.stt_language` setting when the caller
    doesn't pass ?lang=.
    """
    import tempfile

    from core.voice.stt import HAS_WHISPER
    if not HAS_WHISPER:
        return JSONResponse(
            {"error": "faster-whisper not installed. Run: pip install faster-whisper", "stt": False},
            status_code=503,
        )
    from core.settings_db import get_value
    lang = lang or get_value("voice", "stt_language", "ro")
    tmp = None
    try:
        data = await request.body()
        if not data:
            return JSONResponse({"error": "empty audio"}, status_code=400)
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(data)
            tmp = f.name
        text = await _stt_engine().transcribe_async(tmp, language=lang)
        # 0.24 — opt-in dictation cleanup: strip fillers/stutters + apply spoken
        # punctuation. Sentinel transcripts ([silence], [STT unavailable]) pass
        # through untouched, and the removal counts stay inspectable.
        if get_value("voice", "dictation_cleanup", False) and text and not text.startswith("["):
            from core.voice.dictation import clean_dictation
            cleaned = clean_dictation(text, lang=lang)
            return nocache_json({"text": cleaned["text"], "lang": lang,
                                 "dictation": {"cleaned": True, "removed": cleaned["removed"]}})
        return nocache_json({"text": text, "lang": lang})
    except Exception:
        logger.exception("STT error")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except Exception:
                pass


@router.get("/api/voice/capabilities")
async def voice_capabilities():
    """What the voice loop can ACTUALLY do on this host — drives the HUD honestly.

    (The browser always has a fully-local `speechSynthesis` fallback for TTS, which the
    HUD knows about; this reports only the server-side engines.)
    """
    from core.voice.stt import HAS_WHISPER
    try:
        from core.voice.tts import HAS_EDGE, voice_persona_consent_status
    except Exception:
        HAS_EDGE = False
        voice_persona_consent_status = None
    try:
        from core.voice.tts import HAS_KOKORO
    except Exception:
        HAS_KOKORO = False
    xtts = bool(os.getenv("XTTS_SERVER_URL"))
    eleven = bool(os.getenv("ELEVENLABS_API_KEY"))
    return nocache_json({
        "stt": bool(HAS_WHISPER),                       # local Whisper available
        "tts": bool(HAS_EDGE or HAS_KOKORO or xtts or eleven),
        "tts_local": bool(xtts or HAS_KOKORO),          # an on-device TTS path exists
        "persona_voice": (
            voice_persona_consent_status()
            if voice_persona_consent_status else
            {"required": True, "granted": False, "allowed": False, "message": "voice consent status unavailable"}
        ),
        "providers": {
            "stt": "faster-whisper" if HAS_WHISPER else None,
            "xtts": xtts, "elevenlabs": eleven, "edge_tts": bool(HAS_EDGE), "kokoro": bool(HAS_KOKORO),
        },
    })
