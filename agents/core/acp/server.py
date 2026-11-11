"""The ACP agent: an editor's coding-agent protocol projected onto Nerva's hub (G11).

``nerva acp`` runs this over its stdio. It speaks ACP to the editor and the hub's own
routes to the hub, through a :class:`Backend` (``agents/cli/acp_hub.py`` is the HTTP one,
tests inject a fake):

* ``initialize`` / ``authenticate`` — protocol version 1; no authentication methods (the
  process runs as the owner, with the owner's hub credential from the environment).
* ``session/new`` — the editor's ``cwd`` must be an absolute directory (:mod:`.paths`);
  the hub opens a conversation of its own for it (never the HUD's shared one) and binds
  the turn's file tools and project files to that folder, inside the owner's file roots.
  ``mcpServers`` are remembered, not started: see *MCP servers* below.
* ``session/prompt`` — the prompt runs as one ordinary hub turn (``POST /chat/stream``):
  the same router, agents, kernel, tool loop and audit as the HUD. Tokens stream back as
  ``agent_message_chunk``; the hub's bounded tool events become ``tool_call`` cards; the
  ``todo`` checklist becomes the plan panel; slash commands go to the hub's command
  registry exactly as typed in the HUD (advertised with ``available_commands_update``).
* ``session/cancel`` — closes the turn's stream; the hub cancels a turn whose client went
  away (``/chat/stream`` reaps its runner on disconnect). The prompt answers ``cancelled``.

**Permissions (H543).** A turn that needs the owner queues an approval card on the hub and
stops — that is Nerva's ordinary approval path, kernel and tier rules included. For each
card *this turn* queued, the editor is sent ``session/request_permission`` with the real
diff (the file's current text — the editor's own buffer when it offers ``fs/read_text_file``
— against the exact bytes the write would leave) or the exact command. The answer is
posted to ``POST /autonomy/tasks/{id}/decision``, the route the HUD's card and
``nerva approvals`` use; "always" exists only where the hub itself offers a reusable
consent for that card and is posted to the hub's consent route. There is no local
approval state and no bypass: no answer, a timeout, a cancel or a closed editor all
**reject** the card. An irreversible card is marked as such and never offered "always";
the hub still applies its own tier rules when the accept arrives.

**MCP servers (H545).** A server the editor hands over on ``session/new`` is a new MCP
server for Nerva, so it needs the owner's consent like any other: at the session's first
prompt the editor is asked (command, arguments and environment *names* shown), and only an
accepted server is registered — on the hub, for this session only, through the hub's MCP
client with its trust tier, tool filters, approval cards and egress rules. It is never
saved, it is offered to no other conversation, and it is removed when the session ends.

What this module never does: run a tool, write a file, or decide an approval by itself.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import PROTOCOL_VERSION, render
from .jsonrpc import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    ConnectionClosed,
    JsonRpcConnection,
    RpcError,
)
from .paths import AcpPathError, confine, read_text, session_root

logger = logging.getLogger("nerva.acp")

#: The hub's ``ChatRequest.message`` bound.
MAX_PROMPT_CHARS = 4096
#: Prompt blocks one ``session/prompt`` may carry.
MAX_PROMPT_BLOCKS = 64
#: Embedded resources one prompt may attach, and their size (the hub's attachment bounds).
MAX_ATTACHMENTS = 8
MAX_ATTACHMENT_CHARS = 64_000
#: Sessions one editor process may hold open.
MAX_SESSIONS = 16
#: MCP servers one session may be handed.
MAX_SESSION_MCP = 8
MAX_MCP_ARGS = 64
MAX_MCP_ENV = 32
MAX_MCP_TEXT = 4096
#: Default seconds the editor has to answer one permission request before it is a reject.
DEFAULT_PERMISSION_TIMEOUT = 300.0
#: How long an accepted card is followed until the hub reports it done.
DEFAULT_RESULT_WAIT = 120.0
#: How often the editor's sessions renew their lease on the hub (the hub's lease is
#: ``agents.core.acp.sessions.LEASE_SECONDS``).
DEFAULT_LEASE_INTERVAL = 60.0
#: Hub commands an editor thread does not offer: they move the hub's conversation, and in
#: an editor a fresh conversation is a fresh thread.
_SESSION_COMMANDS = frozenset({"new", "reset", "undo"})
_COMMAND_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_]*)(?:\s|$)")
_MCP_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_TERMINAL = {"done", "failed", "rejected", "quarantined", "expired"}


class BackendRefused(Exception):
    """The hub refused (a status worth telling the owner about)."""

    def __init__(self, status: int, reason: str = "") -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.reason = reason


class Backend(Protocol):
    """The hub, as the ACP agent uses it. Every method maps to an existing hub route."""

    async def open_session(self, cwd: str) -> str: ...
    async def close_session(self, session_id: str) -> None: ...
    async def commands(self) -> list[dict[str, Any]]: ...
    async def stream_turn(self, session_id: str, message: str, on_event: Any,
                          cancel: asyncio.Event, *,
                          attachments: list[dict[str, str]]) -> dict[str, Any] | None: ...
    async def approvals(self) -> list[dict[str, Any]]: ...
    async def decide(self, task_id: int, action: str, reason: str | None) -> str: ...
    async def consent(self, task_id: int, revision: str, choice: str) -> str: ...
    async def task_status(self, task_id: int) -> str | None: ...
    async def answer_question(self, prompt_id: str, answer: str | None) -> bool: ...
    async def add_session_mcp(self, session_id: str, server: dict[str, Any]) -> dict[str, Any]: ...
    async def todo(self, session_id: str) -> list[dict[str, Any]]: ...
    async def renew(self, session_id: str) -> None: ...


@dataclass
class _Session:
    id: str
    root: Path
    #: The hub conversation this editor session runs in. It starts as ``id`` and changes
    #: only when the hub refused a closed one and a new one was opened (G11 review M3).
    hub: str = ""
    pending_mcp: list[dict[str, Any]] = field(default_factory=list)
    running: bool = False
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    #: Cards asked about and not yet decided — rejected if the editor goes away.
    open_cards: set[int] = field(default_factory=set)
    tool_calls: dict[str, str] = field(default_factory=dict)
    closed: bool = False

    def __post_init__(self) -> None:
        if not self.hub:
            self.hub = self.id


class AcpServer:
    def __init__(self, backend: Backend, *, version: str = "",
                 permission_timeout: float = DEFAULT_PERMISSION_TIMEOUT,
                 result_wait: float = DEFAULT_RESULT_WAIT, poll_interval: float = 1.0,
                 lease_interval: float = DEFAULT_LEASE_INTERVAL) -> None:
        self.backend = backend
        self.version = version
        self.permission_timeout = max(0.05, float(permission_timeout))
        self.result_wait = max(0.0, float(result_wait))
        self.poll_interval = max(0.01, float(poll_interval))
        #: Seconds between lease renewals (0 = none, for tests that drive no hub).
        self.lease_interval = max(0.0, float(lease_interval))
        self.conn: JsonRpcConnection | None = None
        self.client_caps: dict[str, Any] = {}
        self.initialized = False
        self.sessions: dict[str, _Session] = {}

    # ── wiring ───────────────────────────────────────────────────────────────

    def connect(self, reader: Any, writer: Any) -> JsonRpcConnection:
        self.conn = JsonRpcConnection(reader, writer, on_request=self.handle_request,
                                      on_notification=self.handle_notification)
        return self.conn

    async def serve(self, reader: Any, writer: Any) -> None:
        conn = self.connect(reader, writer)
        beat = asyncio.ensure_future(self.heartbeat()) if self.lease_interval > 0 else None
        try:
            await conn.serve()
        finally:
            if beat is not None:
                beat.cancel()
            await self.shutdown()

    async def shutdown(self) -> None:
        """The editor went away: reject what it was asked and never answered, and close
        every hub session (which removes its session-scoped MCP servers)."""
        for session in list(self.sessions.values()):
            session.cancel.set()
            await self._reject_open(session, "the editor closed before answering")
            await self._close(session)
        self.sessions.clear()

    async def _close(self, session: _Session) -> None:
        if session.closed:
            return
        session.closed = True
        try:
            await self.backend.close_session(session.hub)
        except Exception:  # noqa: BLE001 - teardown is best effort, and logged
            logger.warning("ACP session %s could not be closed on the hub", session.id)

    async def _notify(self, session: _Session, update: dict[str, Any]) -> None:
        if self.conn is None:
            return
        try:
            await self.conn.notify("session/update", {"sessionId": session.id, "update": update})
        except ConnectionClosed:
            session.cancel.set()

    async def _say(self, session: _Session, text: str) -> None:
        await self._notify(session, {"sessionUpdate": "agent_message_chunk",
                                     "content": {"type": "text", "text": text}})

    # ── dispatch ─────────────────────────────────────────────────────────────

    async def handle_request(self, method: str, params: Any) -> Any:
        if method == "initialize":
            return self._initialize(params)
        if not self.initialized:
            raise RpcError(INVALID_REQUEST, "initialize first")
        if method == "authenticate":
            return {}
        if method == "session/new":
            return await self._new_session(params)
        if method == "session/prompt":
            return await self._prompt(params)
        if method in ("session/load", "session/set_mode", "session/set_model"):
            raise RpcError(METHOD_NOT_FOUND, f"{method} is not supported")
        raise RpcError(METHOD_NOT_FOUND, "method not found")

    async def handle_notification(self, method: str, params: Any) -> None:
        if method == "session/cancel" and isinstance(params, dict):
            session = self.sessions.get(params.get("sessionId"))
            if session is not None:
                session.cancel.set()

    def _initialize(self, params: Any) -> dict[str, Any]:
        params = params if isinstance(params, dict) else {}
        caps = params.get("clientCapabilities")
        self.client_caps = caps if isinstance(caps, dict) else {}
        self.initialized = True
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "agentCapabilities": {
                "loadSession": False,
                "promptCapabilities": {"image": False, "audio": False, "embeddedContext": True},
                "mcpCapabilities": {"http": False, "sse": False},
            },
            "authMethods": [],
            "agentInfo": {"name": "nerva", "title": "Nerva", "version": self.version or "dev"},
        }

    def _can_read_buffer(self) -> bool:
        fs = self.client_caps.get("fs")
        return isinstance(fs, dict) and fs.get("readTextFile") is True

    # ── session/new ──────────────────────────────────────────────────────────

    async def _new_session(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "params must be an object")
        if len(self.sessions) >= MAX_SESSIONS:
            raise RpcError(INVALID_REQUEST, "too many open sessions")
        try:
            root = session_root(params.get("cwd"))
        except AcpPathError as exc:
            raise RpcError(INVALID_PARAMS, f"cwd refused: {exc.reason}") from None
        servers = self._mcp_servers(params.get("mcpServers", []))
        try:
            session_id = await self.backend.open_session(str(root))
        except BackendRefused as exc:
            raise RpcError(INVALID_REQUEST, _hub_refusal("the hub did not open a session", exc)) from None
        session = _Session(id=session_id, root=root, pending_mcp=servers)
        self.sessions[session_id] = session
        asyncio.ensure_future(self._advertise_commands(session))
        return {"sessionId": session_id}

    def _mcp_servers(self, raw: Any) -> list[dict[str, Any]]:
        """Validate the editor's ``mcpServers`` (stdio only — HTTP is not advertised)."""
        if raw is None:
            return []
        if not isinstance(raw, list) or len(raw) > MAX_SESSION_MCP:
            raise RpcError(INVALID_PARAMS, f"mcpServers: at most {MAX_SESSION_MCP} servers")
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in raw:
            if not isinstance(entry, dict):
                raise RpcError(INVALID_PARAMS, "mcpServers: each server is an object")
            if entry.get("type") not in (None, "stdio"):
                raise RpcError(INVALID_PARAMS, "mcpServers: only stdio servers are supported")
            name, command = entry.get("name"), entry.get("command")
            if not isinstance(name, str) or not _MCP_NAME_RE.fullmatch(name) or name in seen:
                raise RpcError(INVALID_PARAMS, "mcpServers: a name is 1-32 of letters, digits, - and _, unique")
            if not isinstance(command, str) or not command.strip() or len(command) > MAX_MCP_TEXT \
                    or "\x00" in command:
                raise RpcError(INVALID_PARAMS, f"mcpServers.{name}: command must be a non-empty string")
            args = entry.get("args") or []
            if (not isinstance(args, list) or len(args) > MAX_MCP_ARGS
                    or not all(isinstance(a, str) and len(a) <= MAX_MCP_TEXT and "\x00" not in a for a in args)):
                raise RpcError(INVALID_PARAMS, f"mcpServers.{name}: args must be strings")
            env_raw = entry.get("env") or []
            if not isinstance(env_raw, list) or len(env_raw) > MAX_MCP_ENV:
                raise RpcError(INVALID_PARAMS, f"mcpServers.{name}: env is a list of name/value pairs")
            env: dict[str, str] = {}
            for pair in env_raw:
                if (not isinstance(pair, dict) or not isinstance(pair.get("name"), str)
                        or not _ENV_NAME_RE.fullmatch(pair["name"]) or not isinstance(pair.get("value"), str)
                        or len(pair["value"]) > MAX_MCP_TEXT or "\x00" in pair["value"]):
                    raise RpcError(INVALID_PARAMS, f"mcpServers.{name}: env is a list of name/value pairs")
                env[pair["name"]] = pair["value"]
            seen.add(name)
            out.append({"name": name, "command": command, "args": list(args), "env": env})
        return out

    async def _advertise_commands(self, session: _Session) -> None:
        await asyncio.sleep(0)   # after the session/new answer is on the wire
        try:
            commands = await self.backend.commands()
        except Exception:  # noqa: BLE001 - an editor without completion still works
            logger.info("hub command catalog unavailable")
            return
        available = []
        for row in commands if isinstance(commands, list) else []:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) \
                    or name in _SESSION_COMMANDS:
                continue
            item: dict[str, Any] = {"name": name, "description": render.safe_line(row.get("description"), 200)}
            usage = render.safe_line(row.get("usage"), 120)
            if usage:
                item["input"] = {"hint": usage}
            available.append(item)
        await self._notify(session, {"sessionUpdate": "available_commands_update",
                                     "availableCommands": available[:100]})

    # ── session/prompt ───────────────────────────────────────────────────────

    def _session(self, params: Any) -> _Session:
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "params must be an object")
        session = self.sessions.get(params.get("sessionId"))
        if session is None or session.closed:
            raise RpcError(INVALID_PARAMS, "unknown session")
        return session

    def _prompt_text(self, session: _Session, blocks: Any) -> str:
        """The owner's message only (see :meth:`_prompt_parts`)."""
        return self._prompt_parts(session, blocks)[0]

    def _prompt_parts(self, session: _Session, blocks: Any) -> tuple[str, list[dict[str, str]]]:
        """``(message, attachments)``. The message is what the owner typed plus ``@file:``
        references to files of the session's folder. Any other content the editor embeds
        (a fetched page, an untitled buffer) is never put in the owner's words: it goes as
        an attachment, which the hub fences as content and which taints the turn
        (G11 review M2). A file outside the session's folder is left out either way."""
        if not isinstance(blocks, list) or not blocks or len(blocks) > MAX_PROMPT_BLOCKS:
            raise RpcError(INVALID_PARAMS, "prompt must be a non-empty list of content blocks")
        parts: list[str] = []
        attachments: list[dict[str, str]] = []
        for block in blocks:
            if not isinstance(block, dict):
                raise RpcError(INVALID_PARAMS, "prompt blocks are objects")
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif kind == "resource_link":
                parts.append(self._reference(session, block.get("uri"), block.get("name")))
            elif kind == "resource" and isinstance(block.get("resource"), dict):
                resource = block["resource"]
                uri = resource.get("uri")
                if isinstance(uri, str) and uri.startswith("file://"):
                    # Inside the folder: an @file: reference the hub reads under its own
                    # scope. Outside: left out, exactly like a resource link.
                    parts.append(self._reference(session, uri, None))
                elif isinstance(resource.get("text"), str) and resource["text"]:
                    if len(attachments) >= MAX_ATTACHMENTS:
                        raise RpcError(INVALID_PARAMS, f"at most {MAX_ATTACHMENTS} embedded resources")
                    text = resource["text"]
                    if len(text) > MAX_ATTACHMENT_CHARS:
                        raise RpcError(INVALID_PARAMS,
                                       f"an embedded resource is over {MAX_ATTACHMENT_CHARS} characters")
                    attachments.append({"name": render.safe_line(uri or "untitled", 200) or "untitled",
                                        "text": text})
            else:
                raise RpcError(INVALID_PARAMS, f"prompt block type {render.safe_line(kind, 32)!r} is not supported")
        text = "\n".join(part for part in parts if part).strip()
        if not text:
            raise RpcError(INVALID_PARAMS, "the prompt is empty")
        if len(text) > MAX_PROMPT_CHARS:
            raise RpcError(INVALID_PARAMS, f"the prompt is over {MAX_PROMPT_CHARS} characters; "
                                           "attach large files as references instead of pasting them")
        return text, attachments

    @staticmethod
    def _reference(session: _Session, uri: Any, name: Any, *, quiet: bool = False) -> str:
        """A ``file://`` link inside the session folder becomes Nerva's ``@file:`` reference
        (the hub reads it under its own file scope); anything else is named, not fetched."""
        if isinstance(uri, str) and uri.startswith("file://"):
            from urllib.parse import unquote, urlsplit

            try:
                path = confine(session.root, unquote(urlsplit(uri).path))
            except (AcpPathError, ValueError):
                return "" if quiet else f"(a file outside this session's folder was left out: {render.safe_line(name or uri, 120)})"
            return f'@file:"{path}"' if " " in str(path) else f"@file:{path}"
        if quiet:
            return ""
        return render.safe_line(name or uri or "", 200)

    async def _prompt(self, params: Any) -> dict[str, Any]:
        session = self._session(params)
        if session.running:
            raise RpcError(INVALID_REQUEST, "a prompt is already running in this session")
        text, attachments = self._prompt_parts(session, params.get("prompt"))
        session.running = True
        session.cancel = asyncio.Event()
        try:
            if session.pending_mcp:
                await self._consent_mcp(session)
            if session.cancel.is_set():
                return {"stopReason": "cancelled"}
            command = _COMMAND_RE.match(text)
            if command and command.group(1).lower() in _SESSION_COMMANDS:
                await self._say(session, "This editor thread is its own Nerva conversation; start a "
                                         "new thread in the editor for a fresh one.")
                return {"stopReason": "end_turn"}
            end = await self._run_turn(session, text, attachments)
            if session.cancel.is_set():
                return {"stopReason": "cancelled"}
            await self._decide_cards(session, (end or {}).get("pending_approvals"))
            return {"stopReason": "cancelled" if session.cancel.is_set() else "end_turn"}
        finally:
            await self._reject_open(session, "the editor turn ended before an answer")
            session.running = False

    async def _run_turn(self, session: _Session, text: str,
                        attachments: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
        streamed = {"any": False}

        async def on_event(event: dict[str, Any]) -> None:
            kind = event.get("type")
            if kind == "token" and isinstance(event.get("text"), str) and event["text"]:
                streamed["any"] = True
                await self._say(session, event["text"])
            elif kind == "tool" and isinstance(event.get("event"), dict):
                await self._tool_event(session, event["event"])
            elif kind == "clarify":
                await self._clarify(session, event)

        for attempt in (1, 2):
            try:
                end = await self.backend.stream_turn(session.hub, text, on_event, session.cancel,
                                                     attachments=attachments or [])
                break
            except BackendRefused as exc:
                if exc.status == 410 and attempt == 1 and await self._reopen(session):
                    continue
                await self._say(session, _hub_refusal("The hub refused this turn", exc))
                return None
        if end and not streamed["any"] and isinstance(end.get("text"), str) and end["text"]:
            await self._say(session, end["text"])
        for call_id, state in list(session.tool_calls.items()):
            if state in ("pending", "in_progress"):
                # The turn ended (or was cancelled) with this call unfinished.
                await self._notify(session, {"sessionUpdate": "tool_call_update", "toolCallId": call_id,
                                             "status": "failed"})
        session.tool_calls.clear()
        return end

    async def _reopen(self, session: _Session) -> bool:
        """The hub no longer holds this editor session (a restart, an expired lease): its
        conversation is refused rather than run unbound. Open a new one for the same folder
        and say so; the earlier history and the session's MCP servers do not carry over."""
        try:
            session.hub = await self.backend.open_session(str(session.root))
        except BackendRefused as exc:
            await self._say(session, _hub_refusal("The hub closed this editor session and did not "
                                                  "open a new one", exc))
            session.closed = True
            return False
        await self._say(session, "The hub had closed this editor session (a restart or an expired "
                                 "lease), so this thread now runs in a new Nerva conversation for the "
                                 "same folder. Earlier messages and editor MCP servers did not carry over.\n\n")
        return True

    async def heartbeat(self) -> None:
        """Renew every open session's lease on the hub while the editor is connected, so a
        session (and its MCP servers) ends soon after this process does."""
        while True:
            await asyncio.sleep(self.lease_interval)
            for session in list(self.sessions.values()):
                if session.closed:
                    continue
                try:
                    await self.backend.renew(session.hub)
                except BackendRefused as exc:
                    if exc.status in (404, 410):
                        logger.info("hub dropped editor session %s; reopened at its next prompt", session.id)
                except Exception:  # noqa: BLE001 - a missed beat is retried on the next one
                    logger.debug("lease renewal failed", exc_info=True)

    async def _tool_event(self, session: _Session, event: dict[str, Any]) -> None:
        name = str(event.get("event") or "")
        if name == "todo_updated":
            try:
                plan = await self.backend.todo(session.hub)
            except Exception:  # noqa: BLE001 - the plan panel is a view
                return
            await self._notify(session, {"sessionUpdate": "plan", "entries": render.plan_entries(plan)})
            return
        if name not in ("tool_requested", "tool_started", "tool_result", "tool_failed"):
            return
        raw_id = render.safe_line(event.get("call_id"), 64)
        if not raw_id:
            return
        call_id = f"tool-{raw_id}"
        status = render.tool_status(event)
        if call_id not in session.tool_calls:
            if len(session.tool_calls) >= 512:
                return
            session.tool_calls[call_id] = status
            await self._notify(session, {"sessionUpdate": "tool_call", "toolCallId": call_id,
                                         "title": render.tool_title(event.get("tool")),
                                         "kind": render.tool_kind(event.get("tool")), "status": status})
            return
        session.tool_calls[call_id] = status
        await self._notify(session, {"sessionUpdate": "tool_call_update", "toolCallId": call_id,
                                     "status": status})

    async def _clarify(self, session: _Session, event: dict[str, Any]) -> None:
        """A question the turn asks the owner. With choices it is put to the editor as a
        choice; without, it cannot be typed into a permission dialog, so it is shown and
        skipped (the model is told it was not answered)."""
        prompt_id = event.get("id")
        if not isinstance(prompt_id, str) or not re.fullmatch(r"[0-9a-f]{32}", prompt_id):
            return
        question = render.safe_line(event.get("question"), 600)
        choices = [render.safe_line(c, 120) for c in (event.get("choices") or []) if isinstance(c, str)][:8]
        answer: str | None = None
        if choices and not event.get("multi_select"):
            options = [{"optionId": f"choice-{i}", "name": c or f"choice {i + 1}", "kind": "allow_once"}
                       for i, c in enumerate(choices)]
            options.append({"optionId": "skip", "name": "Skip", "kind": "reject_once"})
            call = {"toolCallId": f"question-{prompt_id[:12]}", "title": f"Nerva asks: {question}",
                    "kind": "think", "status": "pending",
                    "content": [render.text_block(question)]}
            selected = await self._ask(session, call, options)
            if selected and selected.startswith("choice-"):
                answer = choices[int(selected.split("-", 1)[1])]
        else:
            await self._say(session, f"\n\nNerva asked: {question} — this question needs a typed "
                                     "answer, which an editor thread cannot give; it was skipped.\n\n")
        try:
            await self.backend.answer_question(prompt_id, answer)
        except Exception:  # noqa: BLE001 - the turn's own timeout still ends the wait
            logger.info("clarify answer not delivered")

    # ── permissions (H543) ───────────────────────────────────────────────────

    async def _ask(self, session: _Session, tool_call: dict[str, Any],
                   options: list[dict[str, Any]]) -> str | None:
        """One ``session/request_permission``: the selected optionId, or None for a cancel,
        a timeout, an error answer or a closed editor (every one of which is a no)."""
        if self.conn is None or session.cancel.is_set():
            return None
        request = asyncio.ensure_future(self.conn.request(
            "session/request_permission",
            {"sessionId": session.id, "toolCall": tool_call, "options": options}))
        cancelled = asyncio.ensure_future(session.cancel.wait())
        try:
            done, _ = await asyncio.wait({request, cancelled}, timeout=self.permission_timeout,
                                         return_when=asyncio.FIRST_COMPLETED)
        finally:
            cancelled.cancel()
        if request not in done:
            request.cancel()
            return None
        try:
            result = request.result()
        except (RpcError, ConnectionClosed, asyncio.CancelledError):
            return None
        outcome = result.get("outcome") if isinstance(result, dict) else None
        if not isinstance(outcome, dict) or outcome.get("outcome") != "selected":
            return None
        selected = outcome.get("optionId")
        allowed = {o["optionId"] for o in options}
        return selected if selected in allowed else None

    async def _draw(self, session: _Session, card: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """The real before/after of a file card, or (None, why-not).

        The "before" is the file **on disk**, which is what the hub's write replaces
        (G11 review). When the editor offers its buffer and the buffer differs (unsaved
        changes), the owner is told: those changes are not in the diff and the write
        replaces the disk file. The card's path is the absolute path the hub stored at
        intake, so the diff names the file that is written."""
        tool, raw_path, new_text = render.card_target(card)
        if raw_path is None or new_text is None:
            return None, None
        try:
            path = confine(session.root, raw_path)
        except AcpPathError:
            return None, f"Target is outside this session's folder: {render.safe_line(raw_path, 300)}"
        try:
            old = await asyncio.to_thread(read_text, path)
        except AcpPathError as exc:
            return None, f"The current file could not be read ({exc.reason}); compare before accepting."
        note = None
        if self._can_read_buffer() and self.conn is not None and old is not None:
            try:
                answer = await self.conn.request("fs/read_text_file",
                                                 {"sessionId": session.id, "path": str(path)}, timeout=10.0)
                buffer = answer.get("content") if isinstance(answer, dict) else None
            except (RpcError, TimeoutError, ConnectionClosed):
                buffer = None
            if isinstance(buffer, str) and buffer != old:
                note = ("The editor has unsaved changes to this file. The diff is against the file "
                        "on disk, which the write replaces; the unsaved changes are not in it.")
        if len(new_text) > render.MAX_DIFF_CHARS or (old is not None and len(old) > render.MAX_DIFF_CHARS):
            return None, "The change is too large to draw here; review it in the HUD before accepting."
        return {"path": str(path), "oldText": old, "newText": new_text}, note

    async def _decide_cards(self, session: _Session, pending: Any) -> None:
        ids = [i for i in (pending if isinstance(pending, list) else []) if type(i) is int and i > 0][:32]
        if not ids:
            return
        try:
            listing = await self.backend.approvals()
        except BackendRefused as exc:
            if exc.status in (401, 403):
                await self._say(session, "\n\nThis turn queued approvals, and only the owner's admin "
                                         "credential can decide them; they stay queued for the HUD or "
                                         "`nerva approvals`.\n")
            else:
                await self._say(session, "\n\nThe approval queue could not be read; the cards stay "
                                         "queued for the HUD.\n")
            return
        cards = {c.get("id"): c for c in listing if isinstance(c, dict)}
        for task_id in ids:
            if session.cancel.is_set():
                break
            card = cards.get(task_id)
            if card is None:
                continue   # decided elsewhere already (the HUD, another surface)
            await self._decide_one(session, card)

    async def _decide_one(self, session: _Session, card: dict[str, Any]) -> None:
        task_id = card["id"]
        diff, note = await self._draw(session, card)
        call = render.card_tool_call(card, diff=diff, note=note)
        options = render.permission_options(card)
        await self._notify(session, {"sessionUpdate": "tool_call", **call})
        session.open_cards.add(task_id)
        selected = await self._ask(session, call, options)
        if selected is None:
            reason = "cancelled in the editor" if session.cancel.is_set() else "no answer from the editor"
            await self._reject(session, task_id, reason)
            await self._card_done(session, call, "failed", f"Rejected ({reason}).")
            return
        if selected == "reject":
            await self._reject(session, task_id, "rejected in the editor")
            await self._card_done(session, call, "failed", "Rejected in the editor.")
            return
        session.open_cards.discard(task_id)
        try:
            if selected in ("consent_session", "consent_always"):
                offer = render.consent_offer(card)
                state = await self.backend.consent(task_id, offer["revision"] if offer else "",
                                                   "session" if selected == "consent_session" else "always")
            else:
                state = await self.backend.decide(task_id, "accept", "accepted in the editor")
        except BackendRefused as exc:
            await self._card_done(session, call, "failed",
                                  _hub_refusal("The hub did not apply the accept", exc) + " It stays queued.")
            return
        await self._notify(session, {"sessionUpdate": "tool_call_update", "toolCallId": call["toolCallId"],
                                     "status": "in_progress"})
        final = await self._follow(task_id, state)
        if final == "done":
            await self._card_done(session, call, "completed", "Accepted; the hub ran it.")
        elif final in _TERMINAL:
            await self._card_done(session, call, "failed", f"Accepted; the hub reports it {final}.")
        else:
            await self._card_done(session, call, "completed",
                                  f"Accepted; the hub has it as {render.safe_line(final or 'queued', 40)}.")

    async def _follow(self, task_id: int, state: str | None) -> str | None:
        deadline = asyncio.get_running_loop().time() + self.result_wait
        while state not in _TERMINAL and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(self.poll_interval)
            try:
                state = await self.backend.task_status(task_id)
            except Exception:  # noqa: BLE001 - following is a courtesy, not authority
                break
        return state

    async def _card_done(self, session: _Session, call: dict[str, Any], status: str, text: str) -> None:
        await self._notify(session, {"sessionUpdate": "tool_call_update", "toolCallId": call["toolCallId"],
                                     "status": status, "content": [*call["content"], render.text_block(text)]})

    async def _reject(self, session: _Session, task_id: int, reason: str) -> None:
        session.open_cards.discard(task_id)
        try:
            await self.backend.decide(task_id, "reject", reason)
        except Exception:  # noqa: BLE001 - a card that cannot be rejected stays queued, never runs
            logger.warning("approval #%s could not be rejected; it stays queued", task_id)

    async def _reject_open(self, session: _Session, reason: str) -> None:
        for task_id in sorted(session.open_cards):
            await self._reject(session, task_id, reason)

    # ── MCP servers (H545) ───────────────────────────────────────────────────

    async def _consent_mcp(self, session: _Session) -> None:
        servers, session.pending_mcp = session.pending_mcp, []
        for server in servers:
            if session.cancel.is_set():
                return
            env_names = ", ".join(sorted(server["env"])) or "none"
            command = shlex.join([server["command"], *server["args"]])   # as the hub registers it
            call = {
                "toolCallId": f"mcp-{server['name']}-{secrets.token_hex(4)}",
                "title": render.safe_line(f"Connect MCP server '{server['name']}' for this session"),
                "kind": "execute", "status": "pending",
                "content": [
                    render.text_block("The editor asks Nerva to start this MCP server for this session "
                                      "only. It runs as you, in the session folder; its tools are offered "
                                      "only to this conversation, behind Nerva's MCP trust tier and approval "
                                      "cards, and it is removed when the session ends."),
                    render.text_block("```\n" + render.safe_block(command, 2000) + "\n```"),
                    render.text_block(f"Environment variables set: {render.safe_line(env_names, 600)}"),
                ],
            }
            options = [{"optionId": "connect", "name": "Connect for this session", "kind": "allow_once"},
                       {"optionId": "skip", "name": "Do not connect", "kind": "reject_once"}]
            await self._notify(session, {"sessionUpdate": "tool_call", **call})
            selected = await self._ask(session, call, options)
            if selected != "connect":
                await self._card_done(session, call, "failed", "Not connected.")
                continue
            try:
                result = await self.backend.add_session_mcp(session.hub, server)
            except BackendRefused as exc:
                await self._card_done(session, call, "failed", _hub_refusal("The hub refused it", exc))
                continue
            tools = result.get("tools") if isinstance(result, dict) else None
            count = len(tools) if isinstance(tools, list) else 0
            connected = bool(isinstance(result, dict) and result.get("connected"))
            await self._card_done(session, call, "completed" if connected else "failed",
                                  f"Connected; {count} tool(s) offered to this conversation."
                                  if connected else "Registered, but it did not connect; it is retried at "
                                                    "the next turn and removed with the session.")


def _hub_refusal(lead: str, exc: BackendRefused) -> str:
    reason = render.safe_line(exc.reason, 200)
    if exc.status in (401, 403):
        return f"{lead}: the hub needs the owner's credential (JARVIS_ADMIN_TOKEN) for this."
    return f"{lead} (HTTP {exc.status}{': ' + reason if reason else ''})."


__all__ = ["AcpServer", "Backend", "BackendRefused", "DEFAULT_PERMISSION_TIMEOUT", "MAX_PROMPT_CHARS"]
