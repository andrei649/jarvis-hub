"""H652 — full-turn trajectories, saved per session and exported as ShareGPT.

``training/prepare_data.py`` turns a learning-log trace into one user/assistant pair: no
system prompt, no tool calls, no tool results. That is not the turn the model actually
ran, and a fine-tune built from it never sees a tool call. Hermes saves the whole turn
(``save_trajectories``) in the ShareGPT shape its batch runner and trainers read; this is
that, for Nerva.

**What is captured.** One record per model turn that :meth:`Agent.generate_response`
completes on a bound session: the system prompt the model saw (the tool loop's guided
one when the loop ran), the prompt, every assistant step with the tool calls it made,
every steering message the owner sent mid-turn, every tool result the loop fed back (as the model read it: fenced, deduplicated, with
its stall notice), the final reply and the loop's exit reason. A plain (tool-less) turn
is captured too, as system / human / gpt.

**Off by default.** ``NERVA_SAVE_TRAJECTORIES=1`` turns it on, as ``save_trajectories``
is off by default in Hermes. Tool results can carry what the owner read through the
hub, so keeping them is the owner's decision, not a side effect of chatting.

**Bounded and scrubbed.** Every text is passed through the log redaction scanner (API
keys, bearer tokens, private keys) and clipped to :data:`MAX_TEXT_CHARS`; a step list
stops at :data:`MAX_STEPS`; a session's file stops growing at
:data:`MAX_SESSION_BYTES` (the turn is skipped and logged once, never truncated
mid-line). Images are never kept, only their count.

**Where.** ``<data root>/trajectories/<session_id>.jsonl``, one JSON object per line. A
permanent session delete (``session_archive``) backs the file up with the rest of the
session and removes it.

**Export.** :func:`to_sharegpt` renders one record in the Hermes trajectory shape —
``{"conversations": [{"from": "system"|"human"|"gpt"|"tool", "value": …}], …}`` with
each call as ``<tool_call>{json}</tool_call>`` and each result as
``<tool_response>{json}</tool_response>`` — and :func:`to_messages` in the OpenAI
``{"messages": [...]}`` shape ``training/sft_grpo.py`` reads. ``GET
/sessions/{id}/trajectories`` (admin) and ``nerva sessions export <id> --sharegpt``
serve them.

**Wiring.** ``Agent.generate_response`` opens the turn's recorder with :func:`capture`;
``AgentToolRuntime`` notes its system prompt, steps and exit reason into whichever
recorder is active (the loop runs in a copied context, which shares the recorder object).
A nested turn — a sub-agent answering inside a tool call — opens a recorder of its own and
is saved as its own record, so it never folds into its caller's steps. A turn that raises
writes nothing; a turn on no session writes nothing (there is nothing to export it under).
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .env_config import env_flag

logger = logging.getLogger("jarvis.trajectory")

ENV_FLAG = "NERVA_SAVE_TRAJECTORIES"
FORMAT_VERSION = 1
#: Per text (system prompt, prompt, a step's content, a call's arguments, the reply).
MAX_TEXT_CHARS = 32_000
#: Assistant + tool messages kept for one turn.
MAX_STEPS = 400
#: A session's trajectory file stops growing here.
MAX_SESSION_BYTES = 16 * 1024 * 1024
#: Records one export returns at most.
MAX_EXPORT_RECORDS = 1000
#: Exits the loop reports for a turn that ended on the model's own answer.
COMPLETED_EXITS = frozenset({"", "model_response"})
FORMATS = ("sharegpt", "messages")

_active: ContextVar[TrajectoryRecorder | None] = ContextVar("nerva_trajectory", default=None)
_write_lock = threading.Lock()
_full_warned: set[str] = set()


def capture_enabled() -> bool:
    return env_flag(ENV_FLAG, False)


def trajectory_dir() -> Path:
    from .paths import data_path

    return data_path("trajectories")


def path_for(session_id: str) -> Path:
    return trajectory_dir() / f"{session_id}.jsonl"


# ── scrubbing ────────────────────────────────────────────────────────────────


_redactor: Any = None


def _scrub(value: Any) -> str:
    """Text, redacted and clipped. A redactor that fails keeps the turn out (raises)."""
    global _redactor
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    if _redactor is None:
        from .security.log_redaction import SecretRedactionFilter

        _redactor = SecretRedactionFilter()
    text = _redactor.redact_text(text)
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + f"\n…[truncated {len(text) - MAX_TEXT_CHARS} chars]"
    return text


# ── the recorder ─────────────────────────────────────────────────────────────


@dataclass
class TrajectoryRecorder:
    agent_id: str
    model: str
    system: str
    prompt: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    reply: str | None = None
    exit_reason: str = ""
    dropped_steps: int = 0

    def note_system(self, system: Any) -> None:
        """The system prompt the model was actually sent (the tool loop's guided one)."""
        if isinstance(system, str) and system:
            self.system = system

    def note_message(self, message: Mapping[str, Any]) -> None:
        """One assistant step (with its tool calls), one tool result, or one mid-turn
        steering message from the owner, as the model read it on its next request."""
        if not isinstance(message, Mapping):
            return
        role = message.get("role")
        if role not in ("assistant", "tool", "user"):
            return
        if len(self.steps) >= MAX_STEPS:
            self.dropped_steps += 1
            return
        step: dict[str, Any] = {"role": role, "content": message.get("content") or ""}
        if role == "assistant":
            calls = []
            for call in message.get("tool_calls") or []:
                function = call.get("function") if isinstance(call, Mapping) else None
                if not isinstance(function, Mapping):
                    continue
                calls.append({"id": str(call.get("id") or ""), "name": str(function.get("name") or ""),
                              "arguments": function.get("arguments") or "{}"})
            step["tool_calls"] = calls
        elif role == "tool":
            step["tool_call_id"] = str(message.get("tool_call_id") or "")
            images = message.get("images")
            if isinstance(images, list) and images:
                step["images"] = len(images)
        self.steps.append(step)

    def note_exit(self, reason: Any) -> None:
        self.exit_reason = str(getattr(reason, "value", reason) or "")

    def finish(self, reply: Any) -> None:
        self.reply = reply if isinstance(reply, str) else ("" if reply is None else str(reply))

    def to_record(self, session_id: str) -> dict[str, Any]:
        names = {call["id"]: call["name"] for step in self.steps if step["role"] == "assistant"
                 for call in step["tool_calls"]}
        steps = []
        for step in self.steps:
            out = {**step, "content": _scrub(step["content"])}
            if step["role"] == "assistant":
                out["tool_calls"] = [{**call, "arguments": _scrub(call["arguments"])}
                                     for call in step["tool_calls"]]
            elif step["role"] == "tool":
                out["name"] = names.get(step["tool_call_id"], "")
            steps.append(out)
        return {
            "v": FORMAT_VERSION,
            "id": uuid.uuid4().hex,
            "ts": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            "agent_id": str(self.agent_id or ""),
            "model": str(self.model or ""),
            "system": _scrub(self.system),
            "prompt": _scrub(self.prompt),
            "steps": steps,
            "dropped_steps": self.dropped_steps,
            "reply": _scrub(self.reply),
            "exit_reason": self.exit_reason,
            "completed": self.exit_reason in COMPLETED_EXITS,
        }


def active_recorder() -> TrajectoryRecorder | None:
    return _active.get()


def note_system(system: Any) -> None:
    """Hooks for the tool loop: never raise into a turn."""
    recorder = _active.get()
    if recorder is not None:
        try:
            recorder.note_system(system)
        except Exception:
            logger.debug("trajectory note failed", exc_info=True)


def note_message(message: Mapping[str, Any]) -> None:
    recorder = _active.get()
    if recorder is not None:
        try:
            recorder.note_message(message)
        except Exception:
            logger.debug("trajectory note failed", exc_info=True)


def note_exit(reason: Any) -> None:
    recorder = _active.get()
    if recorder is not None:
        try:
            recorder.note_exit(reason)
        except Exception:
            logger.debug("trajectory note failed", exc_info=True)


@contextmanager
def capture(*, agent_id: Any, model: Any, system: Any, prompt: Any) -> Iterator[TrajectoryRecorder | None]:
    """Open this turn's recorder (``None`` when capture is off).

    The record is written when the block exits normally and
    :meth:`TrajectoryRecorder.finish` was called; an exception writes nothing and
    propagates unchanged.
    """
    if not capture_enabled():
        yield None
        return
    recorder = TrajectoryRecorder(agent_id=str(agent_id or ""), model=str(model or ""),
                                  system=system if isinstance(system, str) else "",
                                  prompt=prompt if isinstance(prompt, str) else str(prompt or ""))
    token = _active.set(recorder)
    try:
        yield recorder
    finally:
        _active.reset(token)
    if recorder.reply is None:
        return
    from .llm.request_context import current_session

    session_id = current_session()
    try:
        save(session_id, recorder)
    except Exception:
        logger.warning("trajectory not saved", exc_info=True)


# ── the store ────────────────────────────────────────────────────────────────


def save(session_id: str | None, recorder: TrajectoryRecorder) -> bool:
    """Append one record to the session's file. ``False`` when nothing was written."""
    from .validation import is_valid_session_id

    if not is_valid_session_id(session_id):
        return False
    record = recorder.to_record(session_id)
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    path = path_for(session_id)
    with _write_lock:
        size = path.stat().st_size if path.exists() else 0
        if size + len(line) > MAX_SESSION_BYTES:
            if session_id not in _full_warned:
                _full_warned.add(session_id)
                logger.warning("trajectory file for session %s is full (%d bytes); turns are not saved",
                               session_id, MAX_SESSION_BYTES)
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as handle:
            handle.write(line)
    return True


def load(session_id: str, *, limit: int = MAX_EXPORT_RECORDS) -> list[dict[str, Any]]:
    """The session's records, oldest first (a torn or foreign line is skipped)."""
    from .validation import is_valid_session_id

    if not is_valid_session_id(session_id):
        raise ValueError("invalid session_id")
    path = path_for(session_id)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("v") == FORMAT_VERSION and isinstance(row.get("steps"), list):
                rows.append(row)
    return rows[-max(1, min(int(limit), MAX_EXPORT_RECORDS)):]


def forget(session_id: str) -> bool:
    from .validation import is_valid_session_id

    if not is_valid_session_id(session_id):
        return False
    try:
        path_for(session_id).unlink()
    except FileNotFoundError:
        return False
    _full_warned.discard(session_id)
    return True


# ── export formats ───────────────────────────────────────────────────────────


def _call_json(call: Mapping[str, Any]) -> str:
    arguments: Any = call.get("arguments") or "{}"
    if isinstance(arguments, str):
        with suppress(ValueError):  # a redacted/clipped argument string stays the string it is
            arguments = json.loads(arguments)
    return json.dumps({"name": call.get("name", ""), "arguments": arguments}, ensure_ascii=False)


def _response_json(step: Mapping[str, Any]) -> str:
    content: Any = step.get("content", "")
    with suppress(ValueError, TypeError):
        content = json.loads(content)
    return json.dumps({"tool_call_id": step.get("tool_call_id", ""), "name": step.get("name", ""),
                       "content": content}, ensure_ascii=False)


def _metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("id", "session_id", "agent_id", "model", "exit_reason", "completed")} | {
        "timestamp": record.get("ts")}


def to_sharegpt(record: Mapping[str, Any]) -> dict[str, Any]:
    """One record in the Hermes trajectory shape (``conversations`` of from/value)."""
    conversations: list[dict[str, str]] = []
    if record.get("system"):
        conversations.append({"from": "system", "value": record["system"]})
    conversations.append({"from": "human", "value": record.get("prompt", "")})
    for step in record.get("steps") or []:
        if step.get("role") == "assistant":
            parts = [step["content"]] if step.get("content") else []
            parts += [f"<tool_call>\n{_call_json(call)}\n</tool_call>" for call in step.get("tool_calls") or []]
            conversations.append({"from": "gpt", "value": "\n".join(parts)})
        elif step.get("role") == "tool":
            conversations.append({"from": "tool", "value": f"<tool_response>\n{_response_json(step)}\n</tool_response>"})
        elif step.get("role") == "user":
            conversations.append({"from": "human", "value": step.get("content", "")})
    conversations.append({"from": "gpt", "value": record.get("reply", "")})
    return {"conversations": conversations, **_metadata(record)}


def to_messages(record: Mapping[str, Any]) -> dict[str, Any]:
    """One record as OpenAI chat messages — the ``{"messages": [...]}`` SFT row
    ``training/prepare_data.py`` writes and ``training/sft_grpo.py`` reads, tool calls kept."""
    messages: list[dict[str, Any]] = []
    if record.get("system"):
        messages.append({"role": "system", "content": record["system"]})
    messages.append({"role": "user", "content": record.get("prompt", "")})
    for step in record.get("steps") or []:
        if step.get("role") == "assistant":
            messages.append({"role": "assistant", "content": step.get("content", ""), "tool_calls": [
                {"id": call.get("id", ""), "type": "function",
                 "function": {"name": call.get("name", ""), "arguments": call.get("arguments", "{}")}}
                for call in step.get("tool_calls") or []]})
        elif step.get("role") == "tool":
            messages.append({"role": "tool", "tool_call_id": step.get("tool_call_id", ""),
                             "name": step.get("name", ""), "content": step.get("content", "")})
        elif step.get("role") == "user":
            messages.append({"role": "user", "content": step.get("content", "")})
    messages.append({"role": "assistant", "content": record.get("reply", "")})
    return {"messages": messages, **_metadata(record)}


def export(session_id: str, *, fmt: str = "sharegpt", completed_only: bool = False,
           limit: int = MAX_EXPORT_RECORDS) -> list[dict[str, Any]]:
    if fmt not in FORMATS:
        raise ValueError("unknown format")
    render = to_sharegpt if fmt == "sharegpt" else to_messages
    return [render(row) for row in load(session_id, limit=limit)
            if not completed_only or row.get("completed")]


def to_jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
