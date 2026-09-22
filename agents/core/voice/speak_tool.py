"""speak_tool.py — H313: the model decides to say one thing aloud, in one room.

Hermes's ``text_to_speech`` turns text into an audio file the platform plays.
Nerva already speaks a turn's *reply* (the voice pipeline, the spoken-reply
channel); what was missing is a model that decides to speak a specific thing,
at a specific moment, on a specific room's device — "tell the kitchen dinner is
ready" while the answer to the owner stays text.

The ``speak`` ToolRPC tool is that decision, and nothing more:

* **Privileged, so gated.** Speaking into a room is a present effect on the
  house, not a read. The tool is registered ``gated=True`` with trusted
  execution: a call produces an ask-tier approval card, and only the durable,
  human-accepted ``toolrpc.speak`` row runs it. Being gated also keeps it off
  every posture but the owner's own (``tool_profiles``): inbound channels,
  guests and unattended turns are never offered it.
* **The kernel sees the effect.** The approved run synthesizes the clip on the
  host's own TTS engine (:class:`SpokenReply`, the owner's configured voice)
  and hands it to ``CapabilityActionAPI.perform("action:media.present")`` in
  ``announce`` mode — the same facade ``POST /api/media/present`` uses — so the
  Action Kernel authorizes the present itself (kill switch, budget, policy,
  audit). The tool never touches a driver; the Media Director does, after the
  kernel. Because the owner already accepted this exact row, a kernel ``QUEUE``
  on the present is honoured as that approval (the ``desktop_run`` rule); a
  ``DENY`` is final.
* **The card names the device.** A room target is resolved at proposal time to
  that room's announce-capable default device, so the owner approves the
  speaker that will talk, not a word the model chose. ``presence:auto`` stays a
  sentinel the Media Director resolves when the clip is played.
* **Default-off.** Registered only while ``JARVIS_MEDIA_DIRECTOR`` is on, and
  every call re-checks it. Presenting also needs the unified action API and
  the kernel on, an owner media root (``JARVIS_MEDIA_ROOTS``) to hold the clip,
  and a wired driver for the device — each missing piece is a named refusal.
* **Bounded.** The text is capped at the spoken-reply limit (refused, not
  truncated, so the model knows), code and links are not read aloud, and the
  clip spool under the media root keeps at most :data:`MAX_SPOOL_CLIPS` files.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import re
import time
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agents.core.channels.spoken_reply import (
    MAX_SPOKEN_CHARS,
    REASON_NO_TTS,
    SpokenReply,
    speakable,
)
from agents.core.media_director import MediaError, media_director_enabled
from agents.core.tool_rpc import ToolRPCValidationError

logger = logging.getLogger("jarvis.voice.speak_tool")

SPEAK_TOOL = "speak"
SPEAK_KIND = f"toolrpc.{SPEAK_TOOL}"
CAPABILITY_ID = f"tool:{SPEAK_TOOL}"
PRESENT_CAPABILITY = "action:media.present"
ANNOUNCE = "announce"
PRESENCE_TARGET = "presence:auto"
MAX_TARGET_CHARS = 120
URGENCIES = ("normal", "high")
#: The languages :class:`TTSEngine.VOICE_MAP` has a voice for. Omitted, the owner's
#: configured voice speaks. Kept literal so registering the tool does not import the
#: optional speech backends (a test pins it to the engine's own map).
SPEAK_LANGS = ("en", "en-us", "ro")
SPOOL_DIRNAME = ".nerva-speak"
MAX_SPOOL_CLIPS = 16

REASON_DISABLED = "media_director_disabled"
REASON_UNAVAILABLE = "media_director_unavailable"
REASON_BAD_TEXT = "invalid_text"
REASON_EMPTY = "nothing_to_say"
REASON_TOO_LONG = "text_too_long"
REASON_BAD_TARGET = "invalid_target"
REASON_UNRESOLVED = "target_unresolved"
REASON_AMBIGUOUS = "ambiguous_room_media_target"
REASON_NO_ANNOUNCE = "unsupported_mode"
REASON_BAD_URGENCY = "invalid_urgency"
REASON_BAD_LANG = "unsupported_lang"
REASON_EXTRA_ARG = "unexpected_argument"
REASON_APPROVAL = "approval_required"
REASON_NO_ROOT = "media_root_unconfigured"
REASON_TTS_UNAVAILABLE = "tts_unavailable"
REASON_AUDIO_FORMAT = "unsupported_audio_format"
REASON_SPOOL = "speak_spool_unwritable"
REASON_KERNEL_DENIED = "kernel_denied"
REASON_NO_DRIVER = "no_media_driver"
REASON_PRESENT_REFUSED = "present_refused"
REASON_PRESENT_FAILED = "present_failed"

#: Facade refusals that are the facade's own, not the kernel's verdict.
_FACADE_REASONS = frozenset({
    "unknown_capability", "invalid_context", "invalid_params", "implementation_unbound",
    "capability_mismatch", "kernel_unavailable", "kernel_error",
})
_MACHINE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_AUDIO_SUFFIX = {
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/mp4": ".m4a",
}
_ARG_KEYS = frozenset({"text", "target", "urgency", "lang"})
_MAX_DETAIL = 200

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "maxLength": MAX_SPOKEN_CHARS,
            "description": "What to say aloud: plain prose, one short announcement.",
        },
        "target": {
            "type": "string",
            "maxLength": MAX_TARGET_CHARS,
            "description": (
                "A registered device id, a room name (its announce speaker), or "
                f"{PRESENCE_TARGET} for the room the owner is in."
            ),
        },
        "urgency": {
            "type": "string",
            "enum": list(URGENCIES),
            "description": "high may interrupt media already playing there; default normal.",
        },
        "lang": {
            "type": "string",
            "enum": list(SPEAK_LANGS),
            "description": "Voice language; omit for the owner's configured voice.",
        },
    },
    "required": ["text", "target"],
    "additionalProperties": False,
}

DESCRIPTION = (
    "Say a short text aloud on one room's speaker (announce mode); "
    "human approval required."
)


def default_speaker() -> SpokenReply:
    """The host's own TTS engine with the owner's configured voice (the ``/tts`` one)."""
    return SpokenReply()


def _refuse(reason: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "reason": reason, **extra}


def _clean_target(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ToolRPCValidationError(REASON_BAD_TARGET)
    target = raw.strip()
    if (
        not target
        or len(raw) > MAX_TARGET_CHARS
        or target != raw
        or any(unicodedata.category(char).startswith("C") for char in target)
    ):
        raise ToolRPCValidationError(REASON_BAD_TARGET)
    return target


def _announce_device(director: Any, target: str) -> str:
    """The device id that will speak for *target*, or a named refusal.

    A device id is taken as named; anything else is a room, resolved to its one
    announce-capable default through the registry's pure lookup (no driver is
    reached). ``presence:auto`` is left for the Media Director to resolve at play
    time, when where the owner *is* can actually be known.
    """
    if target == PRESENCE_TARGET:
        return target
    registry = director.registry
    device = registry.get(target)
    if device is not None:
        if ANNOUNCE not in device.supports:
            raise ToolRPCValidationError(REASON_NO_ANNOUNCE)
        return device.id
    try:
        return registry.resolve_room_default(target, mode=ANNOUNCE).id
    except MediaError as exc:
        if exc.reason == REASON_AMBIGUOUS:
            raise ToolRPCValidationError(REASON_AMBIGUOUS) from None
    in_room = [row for row in registry.list() if row.get("room") == target]
    raise ToolRPCValidationError(REASON_NO_ANNOUNCE if in_room else REASON_UNRESOLVED)


class SpeakTool:
    """Preflight (proposal and execution) and the approved handler of ``speak``.

    ``director`` returns the process-wide :class:`MediaDirector` (the one the media
    routes use, so the owner's device registry and session board apply);
    ``approved_task`` returns the durable row the trusted executor is running;
    ``authorizer`` is the bound Action Kernel (``None`` refuses honestly);
    ``interrupt_budget`` returns the autonomy interrupt budget a high-urgency
    present spends when it cuts into media already playing.
    """

    def __init__(
        self,
        *,
        director: Callable[[], Any],
        approved_task: Callable[[], Any],
        authorizer: Callable | None,
        interrupt_budget: Callable[[], Any] = lambda: None,
        speaker: Callable[[], SpokenReply] | None = None,
    ) -> None:
        self._director = director
        self._approved_task = approved_task
        self._authorizer = authorizer
        self._interrupt_budget = interrupt_budget
        self._speaker = speaker

    # ── preflight: runs at proposal (no card on refusal) and again at execution ──

    def _get_director(self) -> Any:
        if not media_director_enabled():
            raise ToolRPCValidationError(REASON_DISABLED)
        try:
            director = self._director()
        except Exception:
            logger.warning("speak: media director unavailable", exc_info=True)
            director = None
        if director is None:
            raise ToolRPCValidationError(REASON_UNAVAILABLE)
        return director

    def preflight(self, args: Mapping[str, Any]) -> dict[str, Any]:
        if set(args) - _ARG_KEYS:
            raise ToolRPCValidationError(REASON_EXTRA_ARG)
        text = args.get("text")
        if not isinstance(text, str):
            raise ToolRPCValidationError(REASON_BAD_TEXT)
        if len(text) > MAX_SPOKEN_CHARS:
            raise ToolRPCValidationError(REASON_TOO_LONG)
        if not speakable(text):
            raise ToolRPCValidationError(REASON_EMPTY)
        target = _clean_target(args.get("target"))
        urgency = args.get("urgency", "normal")
        if urgency not in URGENCIES:
            raise ToolRPCValidationError(REASON_BAD_URGENCY)
        clean: dict[str, Any] = {"text": text, "urgency": urgency}
        if "lang" in args:
            if args["lang"] not in SPEAK_LANGS:
                raise ToolRPCValidationError(REASON_BAD_LANG)
            clean["lang"] = args["lang"]
        clean["target"] = _announce_device(self._get_director(), target)
        return clean

    # ── the approved run ─────────────────────────────────────────────────────

    def _durably_approved(self, kernel: Callable) -> Callable:
        """The kernel, with a QUEUE on *this* present read as the accepted row.

        Only reached from the trusted executor after the durable ``toolrpc.speak``
        row was accepted by a human, so a second card for the same effect would be
        a duplicate ask. DENY — kill switch, budget, loop breaker — stays final.
        """
        from agents.core.kernel import Decision, Verdict

        async def authorize(action, capability=None):
            decision = kernel(action, capability=capability)
            if inspect.isawaitable(decision):
                decision = await decision
            if (
                isinstance(decision, Decision)
                and decision.verdict is Verdict.QUEUE
                and getattr(action, "kind", "") == "media.present"
            ):
                return Decision(
                    Verdict.GRANT, reason="durably_approved", tier=decision.tier,
                    card=decision.card, task_id=decision.task_id,
                )
            return decision

        return authorize

    async def execute(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Synthesize, spool under the media root, present via the kernel-mediated facade."""
        task = self._approved_task()
        if task is None or getattr(task, "kind", None) != SPEAK_KIND:
            return _refuse(REASON_APPROVAL)
        try:
            director = self._get_director()
        except ToolRPCValidationError as exc:
            return _refuse(exc.reason)
        roots = tuple(getattr(director, "local_roots", ()) or ())
        if not roots:
            return _refuse(REASON_NO_ROOT)

        speaker = (self._speaker or default_speaker)()
        audio = await speaker(args["text"], lang=str(args.get("lang") or ""))
        if not audio.ok:
            reason = REASON_TTS_UNAVAILABLE if audio.reason == REASON_NO_TTS else audio.reason
            return _refuse(reason or REASON_TTS_UNAVAILABLE)
        suffix = _AUDIO_SUFFIX.get(audio.mime)
        if suffix is None:
            return _refuse(REASON_AUDIO_FORMAT)
        try:
            clip = await asyncio.to_thread(_spool, Path(roots[0]), audio.data, audio.sha256, suffix)
        except OSError:
            logger.warning("speak: clip spool under the media root is unwritable")
            return _refuse(REASON_SPOOL)

        outcome = await self._present(director, task, args, clip)
        if outcome.get("ok") is not True:
            with contextlib.suppress(OSError):
                clip.unlink()
            return outcome
        return {
            **outcome,
            "chars": audio.chars,
            "backend": audio.backend,
            "sha256": audio.sha256,
        }

    async def _present(self, director: Any, task: Any, args: Mapping[str, Any],
                       clip: Path) -> dict[str, Any]:
        from agents.core.capability_actions import CapabilityActionAPI, PerformContext
        from agents.core.media_director import register_media_capability

        kernel = self._authorizer
        api = CapabilityActionAPI(
            authorizer=self._durably_approved(kernel) if callable(kernel) else None,
        )
        try:
            budget = self._interrupt_budget()
        except Exception:
            budget = None
        register_media_capability(api, director, interrupt_budget=budget)
        origin = getattr(task, "origin", None)
        result = await api.perform(
            PRESENT_CAPABILITY,
            {
                "content": {"type": "local", "value": str(clip)},
                "target": args["target"],
                "mode": ANNOUNCE,
                "privacy": "household",
                "urgency": args.get("urgency", "normal"),
            },
            PerformContext(
                agent=str(getattr(task, "agent", "") or "jarvis"),
                title=f"speak on {args['target']}",
                origin=origin if isinstance(origin, str) and origin else "generated",
            ),
        )
        if result.status == "disabled":
            return _refuse(result.reason)
        if result.status == "queued":
            return _refuse(REASON_APPROVAL)
        if result.status == "refused":
            if result.reason in _FACADE_REASONS:
                return _refuse(result.reason)
            return _refuse(REASON_KERNEL_DENIED, detail=str(result.reason)[:_MAX_DETAIL])
        if result.status != "completed" or not isinstance(result.output, Mapping):
            return _refuse(REASON_PRESENT_FAILED)
        output = result.output
        if output.get("ok") is not True:
            return _director_refusal(output)
        return {
            "ok": True,
            "device": output.get("device"),
            "mode": ANNOUNCE,
            "verified": output.get("verified") is True,
            "verification": output.get("verification"),
        }


def _director_refusal(output: Mapping[str, Any]) -> dict[str, Any]:
    """The Media Director's refusal, by a machine name the model can act on."""
    if output.get("state") == "no_driver":
        return _refuse(REASON_NO_DRIVER)
    reason = output.get("reason")
    if isinstance(reason, str) and _MACHINE_REASON.fullmatch(reason):
        return _refuse(reason)
    return _refuse(REASON_PRESENT_REFUSED, detail=str(reason or "")[:_MAX_DETAIL])


def _spool(root: Path, data: bytes, digest: str, suffix: str) -> Path:
    """Write one clip under ``<media root>/.nerva-speak`` and keep the spool bounded.

    The folder must be a real directory inside the root (a planted symlink out of
    it is refused, not followed). The file is owner-only and lands atomically.
    """
    base = root.resolve()
    folder = base / SPOOL_DIRNAME
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink() or not folder.resolve().is_relative_to(base):
        raise OSError("speak spool escapes the media root")
    name = f"speak-{time.time_ns()}-{(digest or 'clip')[:12]}{suffix}"
    final = folder / name
    partial = folder / f".{name}.part"
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(partial, final)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise
    _prune(folder, keep=MAX_SPOOL_CLIPS)
    return final


def _prune(folder: Path, *, keep: int) -> None:
    clips = sorted(
        (p for p in folder.glob("speak-*") if p.suffix in _AUDIO_SUFFIX.values() and p.is_file()),
        key=lambda p: p.name,
    )
    for old in clips[:-keep] if len(clips) > keep else ():
        with contextlib.suppress(OSError):
            old.unlink()


def register_speak_tool(
    server: Any,
    *,
    director: Callable[[], Any],
    approved_task: Callable[[], Any],
    authorizer: Callable | None,
    interrupt_budget: Callable[[], Any] = lambda: None,
    enabled: bool | None = None,
) -> list[str]:
    """Register ``speak`` on a ToolRPC server. Default-off: returns ``[]`` and
    touches nothing unless ``JARVIS_MEDIA_DIRECTOR`` is on (or ``enabled=True``)."""
    on = media_director_enabled() if enabled is None else bool(enabled)
    if not on:
        return []
    tool = SpeakTool(
        director=director,
        approved_task=approved_task,
        authorizer=authorizer,
        interrupt_budget=interrupt_budget,
    )
    server.register_tool(
        SPEAK_TOOL,
        tool.execute,
        gated=True,
        description=DESCRIPTION,
        input_schema=INPUT_SCHEMA,
        capability_id=CAPABILITY_ID,
        preflight=tool.preflight,
        trusted_execution=True,
    )
    return [SPEAK_TOOL]


__all__ = [
    "CAPABILITY_ID", "INPUT_SCHEMA", "MAX_SPOOL_CLIPS", "MAX_TARGET_CHARS",
    "PRESENCE_TARGET", "SPEAK_KIND", "SPEAK_LANGS", "SPEAK_TOOL", "SPOOL_DIRNAME",
    "SpeakTool", "URGENCIES", "default_speaker", "register_speak_tool",
]
