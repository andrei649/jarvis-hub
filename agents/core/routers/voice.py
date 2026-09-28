"""Voice endpoints — TTS, sentence-level streaming TTS, STT, capabilities (extracted from web.py, CLN-3).

Covers the browser-facing voice loop's server side:
- `POST /tts` — synthesize a whole reply to MP3 (edge-tts).
- `POST /tts/stream` — H5.16 sentence-level streaming (opt-in `voice.sentence_streaming`,
  default off → 409); frames one sentence's audio at a time so playback starts after #1.
- `POST /api/voice/stt` — transcribe a raw browser MediaRecorder blob via local Whisper.
- `GET /api/voice/capabilities` — honest report of what the host's voice engines can do.
- `GET /api/voice/listening` + `/stream` — H222: whether a mic path is open, read-only.
- `GET|POST /api/admin/voice/commands` — H613: the TTS/STT command providers (admin-only;
  a set waits for a human in the Decision Inbox, a clear applies at once).

The `_STT_ENGINE` singleton + `_stt_engine()` accessor and the `TTSRequest` model /
`_tts_stream_enabled()` helper are voice-only (no external use, no test rebinds them),
so they move here with the domain. No orchestrator dependency.
"""

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["voice"])


# ── TTS endpoint ─────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str = Field(..., max_length=4096)
    lang: str = "ro"
    # "xtts" (cloned), "elevenlabs", "piper:<model>", "command", or an edge voice; None = default chain
    voice: Optional[str] = None


#: The ``X-Nerva-Speech`` value of a 204 from ``/tts``: the text normalised to nothing.
NOTHING_TO_SAY = "nothing_to_say"
#: What ``/tts`` answers when no server-side TTS path exists at all.
NO_TTS = ("no TTS engine: edge-tts not installed. Run: pip install edge-tts — or, for Piper, pip install "
          "piper-tts and put a voice's <name>.onnx with its <name>.onnx.json in <data>/voice/piper (or the "
          "directory voice.piper_model_dir names). With voice.local_only on, only Piper, Kokoro or XTTS speak.")
_MEDIA_TYPES = {".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac", ".mp3": "audio/mpeg"}


def _media_type(path: str) -> str:
    """The audio type of a synthesized file, by its suffix (Piper and commands write wav)."""
    return _MEDIA_TYPES.get(Path(str(path)).suffix.lower(), "audio/mpeg")


@router.post("/tts", dependencies=[Depends(user_guard)])
async def tts_endpoint(req: TTSRequest):
    """Synthesize text to speech and return MP3 audio."""
    try:
        # Warm the optional voice stack off the event loop first (see
        # `_voice_engines`). After it, this import is a sys.modules hit.
        await _voice_engines()
        from core.voice.tts import TTSEngine, tts_available
        if not await asyncio.to_thread(tts_available):
            return JSONResponse({"error": NO_TTS}, status_code=503)
        from core.settings_db import get_value
        engine = TTSEngine(default_voice=get_value("voice", "tts_voice", "en-GB-RyanNeural"))
        # H526: a reply with nothing worth saying (all code, emoji or reasoning) is an
        # answer — 204 with the reason — not a synthesis failure for the client to retry.
        if not engine.speech_for(req.text, voice=req.voice, lang=req.lang):
            return Response(status_code=204, headers={"X-Nerva-Speech": NOTHING_TO_SAY,
                                                      "Cache-Control": "no-cache"})
        audio_path = await engine.speak(req.text, voice=req.voice, lang=req.lang)
        if not audio_path:
            return JSONResponse({"error": "TTS synthesis failed"}, status_code=500)
        return FileResponse(
            audio_path,
            media_type=_media_type(audio_path),
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

    await _voice_engines()  # heavy import off the loop; see `_voice_engines`
    from core.voice.tts import TTSEngine, tts_available

    if not _tts_stream_enabled():
        return JSONResponse(
            {"error": "sentence streaming disabled. Enable voice.sentence_streaming.",
             "enabled": False},
            status_code=409,
        )
    if not await asyncio.to_thread(tts_available):
        return JSONResponse({"error": NO_TTS}, status_code=503)
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
# Guards the lazy build below. While `_stt_engine()` was called directly from an
# async handler, the check-then-act was accidentally safe: nothing between the
# `is None` test and the assignment awaits, so the event loop could not interleave
# another request. Moving the call to `asyncio.to_thread` — which is what stops it
# freezing the loop — made it genuinely concurrent, and two simultaneous STT
# requests would each see None and load a SECOND Whisper model onto the GPU.
_STT_ENGINE_LOCK = threading.Lock()


def _stt_engine():
    """Lazily build and cache one Whisper engine (model load is expensive).

    BLOCKING, and expensively so: `STTEngine.__init__` calls `_init_model()`,
    which imports torch, probes CUDA, and loads the whole Whisper model onto the
    GPU. Call it through `asyncio.to_thread` from async code — never directly, or
    the first spoken word freezes every other request for the length of a model
    load. Stays synchronous so the existing `patch.object(..., "_stt_engine")`
    test seams keep working unchanged.

    Exactly one engine is ever built: the double-checked lock means concurrent
    callers pay for one model load, not one each.
    """
    global _STT_ENGINE
    if _STT_ENGINE is not None:
        return _STT_ENGINE
    with _STT_ENGINE_LOCK:
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

    await _voice_engines()  # heavy import off the loop; see `_voice_engines`
    from core.voice.stt import HAS_WHISPER

    from agents.core.voice import local_providers
    # H613: the approved STT command transcribes when Whisper is absent — as
    # voice.stt_engine allows (whisper: only Whisper; command: only the command).
    if not await asyncio.to_thread(local_providers.stt_available, bool(HAS_WHISPER)):
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
        # Off the loop: the first call here loads Whisper onto the GPU.
        engine = await asyncio.to_thread(_stt_engine)
        if await asyncio.to_thread(engine._use_command):
            # The command path copies the bytes into its own private run directory.
            text = await engine.transcribe_async(data, language=lang)
        else:
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
                f.write(data)
                tmp = f.name
            text = await engine.transcribe_async(tmp, language=lang)
        # 0.24 — opt-in dictation cleanup: strip fillers/stutters + apply spoken
        # punctuation. Sentinel transcripts ([silence], [STT unavailable]) pass
        # through untouched, and the removal counts stay inspectable.
        if get_value("voice", "dictation_cleanup", False) and text and not local_providers.is_stt_sentinel(text):
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


# Which server-side voice engines this process has. Derived purely from module
# imports, so it cannot change while the process runs — probe once, then serve
# from here.
#
# It used to be probed inline, per request. `core.voice.stt` does
# `from faster_whisper import WhisperModel` at module scope, which drags in
# ctranslate2 and the CUDA runtime; `core.voice.tts` similarly pulls edge-tts and
# kokoro. On a box where those ARE installed (the GPU host this ships for — not
# CI, where the ImportError returns in milliseconds and hides the cost) that
# import is seconds of synchronous work executed directly on the event loop.
# Nothing else can run during it: a single first hit on this route stalls every
# other in-flight request, which is why routes with no I/O of their own were
# observed hanging alongside it.
_caps_cache: dict | None = None
_caps_lock = asyncio.Lock()


def _probe_voice_engines() -> dict:
    """Import the optional voice stacks and report what is present. BLOCKING."""
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
    return {
        "has_whisper": bool(HAS_WHISPER),
        "has_edge": bool(HAS_EDGE),
        "has_kokoro": bool(HAS_KOKORO),
        # Kept as a callable, not a value: consent is revocable, so it must be
        # read fresh on every request even though the import result is cached.
        "consent_fn": voice_persona_consent_status,
    }


async def _voice_engines() -> dict:
    """`_probe_voice_engines()` off the event loop, once per process."""
    global _caps_cache
    if _caps_cache is None:
        async with _caps_lock:  # concurrent first hits pay for one import, not N
            if _caps_cache is None:
                _caps_cache = await asyncio.to_thread(_probe_voice_engines)
    return _caps_cache


@router.get("/api/voice/capabilities")
async def voice_capabilities():
    """What the voice loop can ACTUALLY do on this host — drives the HUD honestly.

    (The browser always has a fully-local `speechSynthesis` fallback for TTS, which the
    HUD knows about; this reports only the server-side engines.)
    """
    engines = await _voice_engines()
    has_whisper = engines["has_whisper"]
    has_edge = engines["has_edge"]
    has_kokoro = engines["has_kokoro"]
    consent_fn = engines["consent_fn"]
    xtts = bool(os.getenv("XTTS_SERVER_URL"))
    eleven = bool(os.getenv("ELEVENLABS_API_KEY"))
    fish = bool(os.getenv("FISH_AUDIO_API_KEY"))
    local = await asyncio.to_thread(_local_providers_state, bool(has_whisper))     # H613: read per request
    piper, command = local["piper"], local["command"]
    tts_command = command['tts']['ready']
    stt_command = local['selected_stt_ready']
    named_tts = [row['selector'] for row in local['named']['tts'] if row['ready']]
    stt_selector = local['selected_stt_provider'] or 'command'
    local_only = local["local_only"]
    # voice.local_only: only Piper, Kokoro or XTTS speak (never edge, ElevenLabs, Fish or the
    # TTS command, whose locality the hub cannot check).
    tts = (bool(xtts or has_kokoro or piper["available"]) if local_only
           else bool(has_edge or has_kokoro or xtts or eleven or fish or piper["available"] or tts_command or named_tts))
    return nocache_json({
        "stt": local["stt"],                           # as voice.stt_engine allows: Whisper and/or the command
        "tts": tts,
        # an on-device TTS path exists (the command is not counted: its locality is not checked)
        "tts_local": bool(xtts or has_kokoro or piper["available"]),
        "local_only": local_only,
        "persona_voice": (
            consent_fn()
            if consent_fn else
            {"required": True, "granted": False, "allowed": False, "message": "voice consent status unavailable"}
        ),
        "providers": {
            "stt": ("faster-whisper" if has_whisper and local["stt_mode"] != "command"
                    else (stt_selector if stt_command and local["stt_mode"] != "whisper" else None)),
            "xtts": xtts, "elevenlabs": eleven, "fish_audio": fish,
            "edge_tts": has_edge, "kokoro": has_kokoro,
            "piper": piper, "command": command, "named": local["named"],
            "named_error": local["provider_store_error"],
        },
        # the voice picker: the Piper models, and the command provider when it is ready
        "voices": piper["voices"] + (["command"] if tts_command else []) + named_tts,
    })


def _local_providers_state(has_whisper: bool = False) -> dict:
    """H613 — Piper (package or binary, and its models), the command providers, the
    owner's selectors (voice.local_only, voice.stt_engine) and whether STT is available
    under them, now."""
    from agents.core.voice import local_providers

    selected = local_providers.selected_stt_provider()
    if selected is None:
        selected_status = local_providers.command_status('stt')
    else:
        # Named metadata readiness catches store failures and avoids content hashing;
        # actual transcription retains the full-content runtime rechecks.
        ready = local_providers.command_ready('stt', provider_id=selected, verify_content=False)
        selected_status = {'ready': ready.ok, 'reason': ready.reason}
    from agents.core.voice.provider_store import ProviderStoreError
    try:
        named = {side: local_providers.named_command_status(side) for side in local_providers.SIDES}
        store_error = None
    except ProviderStoreError:
        named = {side: [] for side in local_providers.SIDES}
        store_error = 'provider_store_unavailable'
    mode = local_providers.stt_mode()
    stt = (local_providers.stt_available(has_whisper) if selected is None else
           bool((has_whisper and mode != 'command') or (selected_status['ready'] and mode != 'whisper')))
    return {'provider_store_error': store_error, 'named': named, 'selected_stt_provider': selected, 'selected_stt_ready': selected_status['ready'],
            "piper": local_providers.piper_status(),
            "command": {side: local_providers.command_status(side) for side in local_providers.SIDES},
            "local_only": local_providers.local_only(), "stt_mode": mode, "stt": stt}


# ── H613: the TTS / STT command providers (admin-only) ───────────

#: A command is at most 64 elements of at most 4000 characters: a body past this is not one.
VOICE_COMMAND_MAX_BODY = 300_000


class VoiceCommandBody(BaseModel):
    """``{side, argv}`` asks for a command; ``{side, clear: true}`` clears one. Nothing
    else: a missing or empty argv without ``clear`` (a typo, a bare dry run) is a 422, not
    a clear, and an unknown key is refused."""
    model_config = ConfigDict(extra="forbid")

    side: str = Field(..., max_length=8)                   # "tts" or "stt"
    argv: Optional[list[str]] = Field(None, max_length=64)
    provider_id: Optional[StrictStr] = None
    clear: bool = False                                    # the only way to clear a side
    dry_run: bool = False                                  # validate / preview; never writes


@router.get("/api/admin/voice/commands", dependencies=[Depends(admin_guard)])
async def voice_commands_status():
    """Per side: configured, armed (``JARVIS_VOICE_COMMANDS``), safe mode, ready (and why
    not), the approved program and fingerprint, and the request waiting for a decision."""
    from agents.core.voice import command_settings

    return nocache_json(await asyncio.to_thread(command_settings.status, get_orch()))


@router.post("/api/admin/voice/commands", dependencies=[Depends(admin_guard)])
async def voice_commands_write(request: Request):
    """Ask for a TTS or STT command provider, or clear one. A set or a change is never
    written here: it goes to the Decision Inbox as an irreversible-tier card naming the
    program and its argv (202), and a human's accept writes it. A clear applies at once
    and is audited. Same-origin JSON only (the admin guard trusts loopback)."""
    from agents.core.routers.admin import _bounded_body, _refuse_cross_site_write
    from agents.core.voice import command_settings

    refused = _refuse_cross_site_write(request)
    if refused is not None:
        return refused
    raw = await _bounded_body(request, VOICE_COMMAND_MAX_BODY)
    if raw is None:
        return nocache_json({"error": "request body too large"}, status_code=413)
    try:
        body = VoiceCommandBody.model_validate(json.loads(raw or b"null"))
    except Exception:  # noqa: BLE001 — malformed JSON or a body that is not this shape
        return nocache_json({"error": "expected {side: tts|stt, argv: [strings], dry_run?} or "
                                      "{side: tts|stt, clear: true, dry_run?}"}, status_code=422)
    if body.side not in command_settings.KEYS:
        return nocache_json({"error": "side: tts or stt"}, status_code=422)
    from agents.core.voice.provider_store import valid_provider_id
    if body.provider_id is not None and not valid_provider_id(body.provider_id):
        return nocache_json({'error': 'invalid_provider_id'}, status_code=422)
    orch = get_orch()
    named_kwargs = {} if body.provider_id is None else {'provider_id': body.provider_id}
    if body.clear:
        if body.argv:
            return nocache_json({"error": "clear takes no argv: send {side, clear: true}"}, status_code=422)
        if body.dry_run:                                   # a dry run never writes
            return nocache_json({"ok": True, "dry_run": True, "side": body.side, "would_clear": True, **named_kwargs})
        status, answer = await command_settings.clear(orch, body.side, **named_kwargs)
    elif not body.argv:
        return nocache_json({"error": "argv: a list of strings, the program first — to clear the command, "
                                      "send {side, clear: true}"}, status_code=422)
    else:
        status, answer = await command_settings.request(orch, body.side, list(body.argv), dry_run=body.dry_run, **named_kwargs)
    return nocache_json(answer, status_code=status)


# ── H222: listening state (read-only) ────────────────────────────

LISTENING_TICK = 0.25          # seconds between reads of the in-process state
LISTENING_KEEPALIVE = 60       # idle ticks between keepalive comments (15 s)


@router.get("/api/voice/listening", dependencies=[Depends(user_guard)])
async def voice_listening():
    """Whether the hub or a satellite is listening now: each source's state, the loudest
    one and ``mic_open``. Nothing here can open or close a mic."""
    from agents.core.voice import listening

    return nocache_json(listening.snapshot())


async def listening_events(read=None, *, sleep=asyncio.sleep, tick: float = LISTENING_TICK,
                           keepalive_every: int = LISTENING_KEEPALIVE, max_iterations: Optional[int] = None):
    """SSE frames: the state once, then again every time ``seq`` moves; keepalives between."""
    if read is None:
        from agents.core.voice import listening

        read = listening.snapshot
    last = None
    idle = 0
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        snap = read()
        if snap.get("seq") != last:
            last = snap.get("seq")
            idle = 0
            yield f"data: {json.dumps({'type': 'listening', **snap})}\n\n"
        else:
            idle += 1
            if keepalive_every and idle % keepalive_every == 0:
                yield ": keepalive\n\n"
        await sleep(tick)


@router.get("/api/voice/listening/stream", dependencies=[Depends(user_guard)])
async def voice_listening_stream():
    """Every change of the listening state, as server-sent events (read-only)."""
    return StreamingResponse(
        listening_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── H247: who holds the microphone ───────────────────────────────

class MicArmBody(BaseModel):
    surface: str = Field(..., max_length=16)      # "hud" or "mobile"; the host pipeline arms itself
    client: str = Field(..., max_length=64)
    take_over: bool = False


class MicSurfaceBody(BaseModel):
    surface: str = Field(..., max_length=81)      # "<kind>:<client>", as a lease names it
    take_over: bool = False


_LOOPBACK = {"127.0.0.1", "::1"}


def _mic_device(request: Request, kind: str, client: str) -> str:
    """The microphone a surface would open. A browser the hub sees on loopback runs on
    the hub's own machine and shares its microphone; one elsewhere, and every phone,
    has its own. The client address is the one a trusted proxy vouches for."""
    if kind == "mobile":
        return f"mobile:{client}"
    from agents.core.routers._deps import _web

    host = _web()._real_client_host(request)
    return "host" if host in _LOOPBACK else f"remote:hud:{client}"


def _mic_refusal(refused) -> JSONResponse:
    status = {"not_consented": 403, "mic_busy": 409}.get(refused.code, 429)
    body = {"error": refused.code, "detail": refused.message}
    if refused.holder:
        body["holder"] = refused.holder
    return nocache_json(body, status_code=status)


@router.get("/api/voice/mic", dependencies=[Depends(user_guard)])
async def voice_mic_status():
    """H247 — which surface holds each device's microphone, the paused leases and the
    kinds the owner allows to arm (``voice.mic_surfaces``)."""
    from agents.core.voice import mic

    return nocache_json(mic.ARBITER.status())


@router.post("/api/voice/mic/arm", dependencies=[Depends(user_guard)])
async def voice_mic_arm(body: MicArmBody, request: Request):
    """Arm (or renew) a HUD's or a phone's microphone lease. 403 when the owner has not
    allowed the kind, 409 naming the holder when the device's microphone is held (unless
    ``take_over``). A browser or phone renews within 45 s, or its lease lapses."""
    from agents.core.voice import mic

    if body.surface not in ("hud", "mobile"):
        return nocache_json({"error": "only a hud or mobile surface arms here"}, status_code=422)
    try:
        lease = mic.ARBITER.arm(body.surface, body.client, device=_mic_device(request, body.surface, body.client),
                                take_over=body.take_over)
    except ValueError as err:
        return nocache_json({"error": str(err)}, status_code=422)
    except mic.MicRefused as refused:
        return _mic_refusal(refused)
    return nocache_json({"ok": True, "lease": lease})


@router.post("/api/voice/mic/pause", dependencies=[Depends(user_guard)])
async def voice_mic_pause(body: MicSurfaceBody):
    """Close a surface's microphone but keep its lease (the host pipeline too)."""
    from agents.core.voice import mic

    lease = mic.ARBITER.pause(body.surface)
    if lease is None:
        return nocache_json({"error": "no such lease"}, status_code=404)
    return nocache_json({"ok": True, "lease": lease})


@router.post("/api/voice/mic/resume", dependencies=[Depends(user_guard)])
async def voice_mic_resume(body: MicSurfaceBody):
    """Arm a paused lease again; consent and the device's holder are asked again."""
    from agents.core.voice import mic

    try:
        lease = mic.ARBITER.resume(body.surface, take_over=body.take_over)
    except mic.MicRefused as refused:
        return _mic_refusal(refused)
    if lease is None:
        return nocache_json({"error": "no such lease"}, status_code=404)
    return nocache_json({"ok": True, "lease": lease})


@router.post("/api/voice/mic/stop", dependencies=[Depends(user_guard)])
async def voice_mic_stop(body: MicSurfaceBody):
    """Release a surface's lease."""
    from agents.core.voice import mic

    return nocache_json({"ok": True, "stopped": mic.ARBITER.stop(body.surface)})
