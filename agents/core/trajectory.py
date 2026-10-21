"""H652 — full-turn trajectories, saved per session and exported as ShareGPT.

``training/prepare_data.py`` turns a learning-log trace into one user/assistant pair: no
system prompt, no tool calls, no tool results. That is not the turn the model actually
ran, and a fine-tune built from it never sees a tool call. Hermes saves the whole turn
(``save_trajectories``) in the ShareGPT shape its batch runner and trainers read; this is
that, for Nerva.

**What is captured.** One record per model turn that :meth:`Agent.generate_response`
completes on a bound session: the system prompt the model saw (the tool loop's guided
one when the loop ran, re-noted when a fold rebuilds it), the **tool definitions it was
offered** (name, description, parameters — the union over the turn, since an H672
compaction fold can refresh the offer mid-turn; a name's latest definition wins), the
prompt, every assistant step with the tool calls it made, every steering message sent
mid-turn, every tool result the loop fed back (as the model read it: fenced,
deduplicated, with its stall notice), the final reply and the loop's exit reason. A
plain (tool-less) turn is captured too, as system / human / gpt, with the prompt as it
was sent — steering folded into it included.

**Off by default.** ``NERVA_SAVE_TRAJECTORIES=1`` turns it on, as ``save_trajectories``
is off by default in Hermes. Tool results can carry what the owner read through the
hub, so keeping them is the owner's decision, not a side effect of chatting.

**Bounded and scrubbed.** Every text is cut to a bounded window first, passed through the
log redaction scanner (API keys, bearer tokens, private keys) and clipped to
:data:`MAX_TEXT_CHARS`; a tool list stops at :data:`MAX_TOOLS`; a step list
stops at :data:`MAX_STEPS`; a session's file stops growing at
:data:`MAX_SESSION_BYTES` (the turn is skipped and logged once, never truncated
mid-line). Images are never kept, only their count.

**Where.** ``<data root>/trajectories/<session_id>.jsonl``, one JSON object per line, owner-only
(directory ``0700``, file created ``0600`` before a byte is written; a wider one is narrowed). A
permanent session delete (``session_archive``) backs the file up with the rest of the
session and removes it.

**Export.** :func:`to_sharegpt` renders one record in the Hermes trajectory shape —
``{"conversations": [{"from": "system"|"human"|"gpt"|"tool", "value": …}], …}``: the
system value carries the offered tools as a ``<tools>[{name, description, parameters,
required: null}]</tools>`` block (Hermes' ``format_tools_for_system_message`` shape),
every gpt value starts with a ``<think>`` block (empty: reasoning text is not kept),
each call is ``<tool_call>{json}</tool_call>``, and the results of one step's calls
are joined by newlines in one ``tool`` value as ``<tool_response>{json}</tool_response>``
blocks. :func:`to_messages` renders the OpenAI ``{"messages": [...], "tools": [...]}``
row ``training/sft_grpo.py`` reads (``tools`` is what chat templates render). ``GET
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
import os
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
#: Tool definitions kept for one turn.
MAX_TOOLS = 256
#: Characters past MAX_TEXT_CHARS the redaction scanner still sees, so a secret that
#: straddles the cut is redacted before the clip, and the scanner never walks an
#: unbounded text on the event loop.
_SCAN_MARGIN = 4_096
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
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


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
    original = len(text)
    text = _redactor.redact_text(text[:MAX_TEXT_CHARS + _SCAN_MARGIN])
    if original > MAX_TEXT_CHARS or len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + f"\n…[truncated {max(original, len(text)) - MAX_TEXT_CHARS} chars]"
    return text


def _scrub_schema(value: Any) -> dict[str, Any]:
    """A tool's parameter schema, redacted and bounded; one that no longer parses after
    the clip is kept as an empty object schema rather than as broken JSON."""
    try:
        parsed = json.loads(_scrub(json.dumps(value if isinstance(value, Mapping) else {}, ensure_ascii=False)))
    except (TypeError, ValueError):
        parsed = None
    return parsed if isinstance(parsed, dict) else {"type": "object", "properties": {}}


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
    #: OpenAI-shape specs (``{"type": "function", "function": {...}}``), one per name.
    tools: list[dict[str, Any]] = field(default_factory=list)

    def note_prompt(self, prompt: Any) -> None:
        """The prompt the model was actually sent (the plain path folds steering into it)."""
        if isinstance(prompt, str):
            self.prompt = prompt

    def note_tools(self, specs: Any) -> None:
        """The tools offered on this request. Called at the top of the loop and again when
        a compaction fold refreshes the offer: the union is kept (a tool withdrawn later
        was still offered, and may have been called, earlier) and a name's latest
        definition wins."""
        for spec in specs or ():
            as_openai = getattr(spec, "as_openai", None)
            row = as_openai() if callable(as_openai) else spec
            function = row.get("function") if isinstance(row, Mapping) else None
            if not isinstance(function, Mapping) or not function.get("name"):
                continue
            entry = {"type": "function", "function": {
                "name": str(function["name"]), "description": str(function.get("description") or ""),
                "parameters": function.get("parameters") or {"type": "object", "properties": {}}}}
            for index, existing in enumerate(self.tools):
                if existing["function"]["name"] == entry["function"]["name"]:
                    self.tools[index] = entry
                    break
            else:
                if len(self.tools) < MAX_TOOLS:
                    self.tools.append(entry)

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
            "tools": [{"name": _scrub(tool["function"]["name"]),
                       "description": _scrub(tool["function"]["description"]),
                       "parameters": _scrub_schema(tool["function"]["parameters"])}
                      for tool in self.tools],
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


def note_tools(specs: Any) -> None:
    recorder = _active.get()
    if recorder is not None:
        try:
            recorder.note_tools(specs)
        except Exception:
            logger.debug("trajectory note failed", exc_info=True)


def note_prompt(prompt: Any) -> None:
    recorder = _active.get()
    if recorder is not None:
        try:
            recorder.note_prompt(prompt)
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
        if size == 0:  # removed (forget-me, a session delete) or never written: warn afresh
            _full_warned.discard(session_id)
        if size + len(line) > MAX_SESSION_BYTES:
            if session_id not in _full_warned:
                _full_warned.add(session_id)
                logger.warning("trajectory file for session %s is full (%d bytes); turns are not saved",
                               session_id, MAX_SESSION_BYTES)
            return False
        _append_private(path, line)
    return True


def _append_private(path: Path, data: bytes) -> None:
    """Append *data* owner-only: the directory is ``0700`` and the file is created ``0600``
    before a byte lands (a saved system prompt, conversation and tool results are as
    private as the session snapshots ``atomic_write_json`` writes ``0600``). A file or
    directory an earlier version left wider is narrowed; a symlink is never followed."""
    directory = path.parent
    directory.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    with suppress(OSError):
        if directory.stat().st_mode & 0o777 != PRIVATE_DIR_MODE:
            os.chmod(directory, PRIVATE_DIR_MODE)
    # O_BINARY: on Windows a low-level fd defaults to text mode (``\n`` -> ``\r\n``), which
    # would break the LF format and the exact MAX_SESSION_BYTES accounting in save().
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, PRIVATE_FILE_MODE)
    try:
        if hasattr(os, "fchmod"):
            with suppress(OSError):
                if os.fstat(fd).st_mode & 0o777 != PRIVATE_FILE_MODE:
                    os.fchmod(fd, PRIVATE_FILE_MODE)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)


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


def _tools(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The record's offered tools; a v1 row written before they were captured has none."""
    tools = record.get("tools")
    if not isinstance(tools, list):
        return []
    return [tool for tool in tools if isinstance(tool, Mapping) and tool.get("name")]


#: Hermes' uniform-schema rule: every gpt value carries a think block, empty when no
#: reasoning was kept (Nerva does not keep provider reasoning text).
_EMPTY_THINK = "<think>\n</think>\n"


def _tools_block(tools: list[Mapping[str, Any]]) -> str:
    """Hermes' ``format_tools_for_system_message`` shape: ``required`` is ``null``."""
    rows = [{"name": tool.get("name", ""), "description": tool.get("description", ""),
             "parameters": tool.get("parameters") or {}, "required": None} for tool in tools]
    return ("You may call one or more functions to assist with the user query. The function "
            "signatures are within <tools></tools> XML tags:\n<tools>\n"
            + json.dumps(rows, ensure_ascii=False)
            + "\n</tools>\nFor each function call return a JSON object with the function name "
            "and arguments within <tool_call></tool_call> XML tags.")


def _metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("id", "session_id", "agent_id", "model", "exit_reason", "completed")} | {
        "timestamp": record.get("ts")}


def to_sharegpt(record: Mapping[str, Any]) -> dict[str, Any]:
    """One record in the Hermes trajectory shape (``conversations`` of from/value)."""
    conversations: list[dict[str, str]] = []
    system = [record["system"]] if record.get("system") else []
    tools = _tools(record)
    if tools:
        system.append(_tools_block(tools))
    if system:
        conversations.append({"from": "system", "value": "\n\n".join(system)})
    conversations.append({"from": "human", "value": record.get("prompt", "")})
    for step in record.get("steps") or []:
        if step.get("role") == "assistant":
            parts = [step["content"]] if step.get("content") else []
            parts += [f"<tool_call>\n{_call_json(call)}\n</tool_call>" for call in step.get("tool_calls") or []]
            conversations.append({"from": "gpt", "value": _EMPTY_THINK + "\n".join(parts)})
        elif step.get("role") == "tool":
            response = f"<tool_response>\n{_response_json(step)}\n</tool_response>"
            if conversations[-1]["from"] == "tool":  # one step's parallel results: one message
                conversations[-1]["value"] += "\n" + response
            else:
                conversations.append({"from": "tool", "value": response})
        elif step.get("role") == "user":
            conversations.append({"from": "human", "value": step.get("content", "")})
    conversations.append({"from": "gpt", "value": _EMPTY_THINK + (record.get("reply") or "")})
    return {"conversations": conversations, **_metadata(record)}


def to_messages(record: Mapping[str, Any]) -> dict[str, Any]:
    """One record as OpenAI chat messages — the ``{"messages": [...]}`` SFT row
    ``training/prepare_data.py`` writes and ``training/sft_grpo.py`` reads, tool calls kept,
    plus the offered ``tools`` column TRL/HF chat templates render tool definitions from."""
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
    tools = [{"type": "function", "function": {"name": tool.get("name", ""), "description": tool.get("description", ""),
                                               "parameters": tool.get("parameters") or {}}}
             for tool in _tools(record)]
    return {"messages": messages, "tools": tools, **_metadata(record)}


def export(session_id: str, *, fmt: str = "sharegpt", completed_only: bool = False,
           limit: int = MAX_EXPORT_RECORDS) -> list[dict[str, Any]]:
    if fmt not in FORMATS:
        raise ValueError("unknown format")
    render = to_sharegpt if fmt == "sharegpt" else to_messages
    return [render(row) for row in load(session_id, limit=limit)
            if not completed_only or row.get("completed")]


def to_jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
