"""H224 — `nerva chat -i`: the interactive terminal chat and its keyboard model.

Built on the standard library's GNU readline (prompt_toolkit is not a dependency of
this repository, and the CLI stays stdlib-only). What each key does:

=====================  ==========================================================
Ctrl+C                 clear the draft; on an empty draft while a turn runs, stop
                       that turn (``POST /chat/interrupt``, the caller's own turn
                       only); idle and empty, arm exit — a second Ctrl+C exits
Ctrl+D                 exit (on an empty line, readline's rule)
Enter                  submit
Alt+Enter, Shift+Enter newline in the draft (Shift+Enter where the terminal sends
                       a distinct sequence: kitty/CSI-u ``ESC[13;2u`` or xterm's
                       modifyOtherKeys ``ESC[27;2;13~``); a trailing ``\\`` also
                       continues the message on the next line
Ctrl+X Ctrl+E, /edit   compose in ``$VISUAL``/``$EDITOR`` (owner-only 0600 temp
                       file, removed afterwards); the text comes back as the draft
Ctrl+L                 redraw (clear the screen, keep the draft)
Esc Esc                discard the draft (Ctrl+Y brings it back: it is killed, not lost)
Tab / Shift+Tab        cycle completions: the hub's slash commands
                       (``GET /api/commands``, what this credential may run), this
                       client's own commands, and ``@file:`` paths
                       (``GET /api/context-refs``)
Up / Down              history (persistent, owner-only file in the user's config
                       dir; ``--no-history`` or ``NERVA_CHAT_HISTORY=off`` keeps none)
paste                  bracketed paste: a multi-line paste is one draft, not N turns
=====================  ==========================================================

Client commands (never sent to the hub): ``/edit``, ``/image PATH``, ``/paste-image``,
``/switch [N|id|new]`` (your sessions, ``GET /sessions``), ``/model [N|id]`` (the hub's
local models; switching is the owner's admin route and is refused otherwise),
``/queue [clear|drop N]``, ``/copy`` (the last answer, OSC 52), ``/where`` (directory, git
branch, battery), ``/keys``, ``/exit``. Everything else — ``/help``, ``/recap``,
any hub command — goes to the hub as a message, where the command plane judges it.

A message typed while a turn runs is queued and sent, in order, when the turn ends.

H223 — the turn is streamed (``POST /chat/stream``): the answer is drawn line by line as
its tokens arrive, with a one-line tool trail, while the prompt stays open. The turn's
questions still come through ``GET /chat/pending`` (header ``X-Nerva-Pending: poll``) and
Ctrl+C still stops it (``POST /chat/interrupt``, the turn's own id). A hub without the
stream route gets ``POST /chat``. ``nerva chat -i "first message" [--image PATH]`` sends a
first message on start; a clean exit, and an exit on an internal error, print how to
resume the conversation (``nerva chat -i -r ID``).

Security: nothing the hub or the model writes is ever executed here; their text is
stripped of control sequences, C1 controls and bidi/zero-width characters before it is
drawn. The editor is the owner's own ``$VISUAL``/``$EDITOR`` argv (no shell). A line that
looks like a key, a token or a stated password/PIN is kept out of the history file,
which is never followed through a symlink.
"""

from __future__ import annotations

import collections
import contextlib
import json
import os
import re
import shutil
import signal
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

#: Client-side commands. A hub command of the same name is shadowed in this client
#: only (``/sessions``, ``/new`` and the rest are the hub's and are not here).
LOCAL_COMMANDS: dict[str, str] = {
    "/edit": "compose the message in $VISUAL/$EDITOR (also Ctrl+X Ctrl+E)",
    "/image": "attach an image file to the next message (it goes to the vision model)",
    "/paste-image": "attach the clipboard's image to the next message",
    "/switch": "list your sessions; /switch N, /switch <id> or /switch new",
    "/model": "list the hub's local models; /model N or /model <id> switches (owner only)",
    "/queue": "messages waiting for the running turn; /queue clear, /queue drop N, /queue edit N",
    "/copy": "copy the last answer to the clipboard (OSC 52; the terminal must allow it)",
    "/where": "this terminal: working directory, git branch and battery",
    "/keys": "the keyboard reference",
    "/exit": "leave (also /quit, Ctrl+D, or Ctrl+C twice)",
    "/quit": "leave",
}

#: What /keys prints.
KEY_HELP: tuple[str, ...] = (
    "Enter            send",
    "Alt+Enter        newline (Shift+Enter too, where the terminal sends it apart); a trailing \\ continues",
    "Ctrl+C           clear the draft · stop the running turn · press twice to exit",
    "Ctrl+D           exit",
    "Ctrl+X Ctrl+E    compose in $VISUAL/$EDITOR (also /edit)",
    "Ctrl+L           redraw",
    "Esc Esc          discard the draft (Ctrl+Y brings it back)",
    "Tab / Shift+Tab  cycle completions: /commands and @file: paths",
    "Up / Down        history",
    "Ctrl+A/E/W/U/K/Y and the other readline chords edit the line",
    *(f"{name:<16} {text}" for name, text in LOCAL_COMMANDS.items()),
)

HISTORY_LIMIT = 1000
#: H235: what /copy can carry, and the battery warning's level and polling interval.
COPY_LIMIT = 64_000
BATTERY_WARN = 15
BATTERY_POLL_SECONDS = 60.0
EXIT_ARM_SECONDS = 3.0
#: Tab asks the hub for ``@file:`` paths with this budget; an unreachable hub is not
#: asked again for COMPLETION_BACKOFF seconds, so Tab never freezes the prompt.
COMPLETION_TIMEOUT = 1.0
COMPLETION_BACKOFF = 30.0
#: The variable that turns the history file off (``NERVA_`` or ``JARVIS_`` spelling).
HISTORY_ENV = "JARVIS_CHAT_HISTORY"
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")

#: readline bindings (GNU syntax). Each is data, so a test can read the table.
READLINE_BINDINGS: tuple[str, ...] = (
    "set enable-bracketed-paste on",
    "set editing-mode emacs",
    "set show-all-if-ambiguous on",
    # newline in the draft: Alt+Enter, and Shift+Enter where the terminal can say so
    r'"\e\r": "\C-v\C-j"',
    r'"\e\n": "\C-v\C-j"',
    r'"\e[13;2u": "\C-v\C-j"',
    r'"\e[27;2;13~": "\C-v\C-j"',
    # Ctrl+X Ctrl+E: hand the draft to /edit
    r'"\C-x\C-e": "\C-a/edit \C-j"',
    # Esc Esc: discard the draft into the kill ring
    r'"\e\e": kill-whole-line',
    # Tab / Shift+Tab cycle completions
    r'"\t": menu-complete',
    r'"\e[Z": menu-complete-backward',
    r'"\C-l": clear-screen',
)


# ── key policy (pure) ────────────────────────────────────────────────────────

def ctrl_c_action(draft: str, *, turn_running: bool, exit_armed: bool) -> str:
    """What Ctrl+C means now, in Hermes' order: ``clear`` a draft; else ``interrupt``
    a running turn; else ``exit`` when already armed; else ``arm`` the exit."""
    if draft:
        return "clear"
    if turn_running:
        return "interrupt"
    return "exit" if exit_armed else "arm"


def route_line(line: str) -> tuple[str, str]:
    """``(kind, rest)``: ``("local", "/cmd args")`` for a client command, ``("empty", "")``,
    ``("continue", text)`` for a line ending in a backslash, or ``("send", text)``."""
    if not line.strip():
        return "empty", ""
    if line.endswith("\\") and not line.endswith("\\\\"):
        return "continue", line[:-1]
    head = line.strip().split(maxsplit=1)[0]
    if head in LOCAL_COMMANDS:
        return "local", line.strip()
    return "send", line


def completions(text: str, *, line: str, begin: int, commands: Iterable[str],
                refs: Callable[[str], list[str]] | None = None,
                described: Iterable[tuple[str, str]] = ()) -> list[str]:
    """Candidates for the word *text* that starts at *begin* in *line*.

    A ``/word`` at the start of the line completes from the hub's commands and this
    client's own; when no name starts with it, the closest names by name and
    *described* description are offered instead (H231/H235, ``agents.core.fuzzy_match``:
    ``/sesion`` → ``/sessions``, ``/quota`` → ``/usage``). ``@file:prefix`` anywhere
    completes from *refs* (the hub's scope)."""
    if text.startswith("/") and not line[:begin].strip():
        names = sorted(set(commands) | set(LOCAL_COMMANDS))
        matches = [name for name in names if name.startswith(text)]
        if matches or len(text) < 3:
            return matches
        from agents.core.fuzzy_match import rank

        catalog = dict.fromkeys(names, "")
        catalog.update(LOCAL_COMMANDS)
        catalog.update({name: text for name, text in described if name in catalog})
        return rank(text, catalog.items(), limit=5)
    if text.startswith("@file:") and refs is not None:
        # The hub's refs are whole references already (``@file:path``, quoted when the
        # path has a space): used as they are, never prefixed again.
        prefix = text[len("@file:"):]
        return [ref for ref in refs(prefix) if ref.startswith("@file:")]
    if text.startswith("@") and "@file:".startswith(text):
        return ["@file:"]
    return []


# ── history ──────────────────────────────────────────────────────────────────

def history_path(environ: Mapping[str, str]) -> Path:
    """The history file in the user's own config directory — not the hub's data root,
    so it is in no hub backup: ``$XDG_CONFIG_HOME/nerva``, ``%APPDATA%\\Nerva`` on
    Windows, ``~/Library/Application Support/Nerva`` on macOS, else ``~/.config/nerva``.
    Read from *environ* (the CLI's own environment), never from the hub's settings."""
    import sys

    def absolute(name: str) -> Path | None:
        value = (environ.get(name) or "").strip()
        return Path(value) if value and os.path.isabs(value) else None

    home = absolute("HOME") or absolute("USERPROFILE") or Path(os.path.expanduser("~"))
    xdg = absolute("XDG_CONFIG_HOME")
    if xdg is not None:
        base = xdg / "nerva"
    elif sys.platform == "win32":
        base = (absolute("APPDATA") or home / "AppData" / "Roaming") / "Nerva"
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support" / "Nerva"
    else:
        base = home / ".config" / "nerva"
    return base / "chat_history.jsonl"


def history_enabled(environ: Mapping[str, str]) -> bool:
    """``NERVA_CHAT_HISTORY=off`` (or ``JARVIS_CHAT_HISTORY``) keeps no history file;
    unset or anything unrecognised keeps it (the default)."""
    from agents.core.env_config import resolve_spellings, truthy

    value, _ = resolve_spellings(environ, HISTORY_ENV)
    return truthy(value, True)


#: A password, passcode, passphrase or PIN stated in plain words ("my pin is 4821",
#: "password: hunter2", "parola este ..."): kept out of the history like a token.
_STATED_SECRET = re.compile(
    r"\b(?:pin(?:\s*code)?|pass(?:word|code|phrase)|passwd|pwd|parol[aă]|codul?\s+pin)s?\b"
    r"[^\n]{0,40}?(?:\bis\b|\bwas\b|\beste\b|\be\b|[:=])\s*\S",
    re.IGNORECASE)


def keep_out_of_history(entry: str) -> bool:
    """Whether *entry* must not be remembered: a key/token shape, or a stated secret."""
    from .chat_prompts import looks_like_secret

    return bool(_STATED_SECRET.search(entry)) or looks_like_secret(entry)


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _refuse_link(path: Path) -> None:
    """A history path (or its folder) that is a symlink is not ours to follow."""
    if path.is_symlink() or path.parent.is_symlink():
        raise OSError(f"{path} is a symbolic link; the history is not kept there")


def load_history(path: Path, limit: int = HISTORY_LIMIT) -> list[str]:
    """Entries of the history file, oldest first (one JSON string per line, so a
    multi-line message stays one entry). A file someone else can read is not trusted
    to be ours: it is re-permissioned, not skipped, and a broken line is ignored. A
    symlinked path is refused (``O_NOFOLLOW``), so the history never reads another file."""
    try:
        _refuse_link(path)
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    except OSError:
        return []
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            with contextlib.suppress(OSError):
                if os.fstat(handle.fileno()).st_mode & 0o077 and hasattr(os, "fchmod"):
                    os.fchmod(handle.fileno(), 0o600)
            raw = handle.read()
    except (OSError, UnicodeDecodeError):
        return []
    entries: list[str] = []
    for row in raw.splitlines():
        try:
            value = json.loads(row)
        except ValueError:
            continue
        if isinstance(value, str) and value.strip():
            entries.append(value)
    return entries[-limit:]


def append_history(path: Path, entry: str, limit: int = HISTORY_LIMIT) -> bool:
    """Append one entry (owner-only file, 0600); the file is cut to *limit* entries.

    Never through a symlink: the file is opened ``O_NOFOLLOW``, and the trimmed copy is
    written to a fresh ``O_CREAT|O_EXCL|O_NOFOLLOW`` 0600 file that is then renamed over it."""
    if not entry.strip() or keep_out_of_history(entry):
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _refuse_link(path)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _NOFOLLOW, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        entries = load_history(path, limit=limit * 2)
        if len(entries) > limit:
            import secrets

            temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in entries[-limit:])
                os.replace(temp, path)
            except OSError:
                with contextlib.suppress(OSError):
                    os.unlink(temp)
                raise
        return True
    except OSError:
        return False


# ── editor ───────────────────────────────────────────────────────────────────

def compose_in_editor(environ: Mapping[str, str], draft: str, *, err: Any,
                      run: Callable[[list[str], str], int] | None = None) -> str | None:
    """The owner's ``$VISUAL``/``$EDITOR`` on *draft* in an owner-only (0600) temporary
    file that is removed afterwards; the saved text, or None (said why) when it failed."""
    import tempfile

    from .nerva import _editor_argv, _editor_failure, _plain, _run_editor

    argv = _editor_argv(environ)
    fd, temporary = tempfile.mkstemp(prefix="nerva-chat-", suffix=".md")   # 0600 by mkstemp
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(draft)
        try:
            status = (run or _run_editor)(argv, temporary)
        except OSError as exc:
            err.write(f"editor {_plain(argv[0], 80)} {_editor_failure(exc)} — set $VISUAL or $EDITOR\n")
            return None
        if status != 0:
            err.write(f"editor exited {status}; the draft is unchanged\n")
            return None
        return Path(temporary).read_text(encoding="utf-8").rstrip("\n")
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


# ── the REPL ─────────────────────────────────────────────────────────────────

@dataclass
class Outgoing:
    message: str
    images: list[str] = field(default_factory=list)
    clipboard_image: bool = False


class Repl:
    """One interactive chat. The main thread reads the keyboard; one worker thread
    runs turns, one at a time, from the queue. Questions a turn asks (clarify,
    secrets) and approval cards it queued are answered on the main thread."""

    def __init__(self, ctx, *, session_id: str | None = None, agent: str | None = None,
                 reasoning: str | None = None, history: bool = True,
                 reader: Callable[[str], str] | None = None, readline_module: Any = None) -> None:
        self.ctx = ctx
        self.session_id = session_id
        self.agent = agent
        self.reasoning = reasoning
        self.history_file = history_path(ctx.environ) if history and history_enabled(ctx.environ) else None
        self._reader = reader or input
        self._rl = readline_module
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self.queue: collections.deque[Outgoing] = collections.deque()
        #: (kind, payload, session) — the session is the asking turn's, not the current one
        self.asks: collections.deque[tuple[str, Any, str | None]] = collections.deque()
        self.running = False
        #: The turn on the wire: its session and turn id as sent, the switch generation
        #: it was sent in, its kind. A /switch during it never retargets Ctrl+C (review M2)
        #: and is not undone by its reply (review M3).
        self.inflight: dict[str, Any] | None = None
        self._generation = 0
        #: Ctrl+C stopped a turn: queued messages wait for the next Enter (review m5).
        self.queue_held = False
        self._refs_down_until = 0.0
        self.stopped = False
        self.exit_armed_at: float | None = None
        self.staged_images: list[str] = []
        self.staged_clipboard = False
        self.commands: list[str] = []
        #: (command, card-safe description) from the hub's catalog, for fuzzy completion
        self.described: list[tuple[str, str]] = []
        self.continued: list[str] = []
        self._draft_at_interrupt = ""
        self._prefill = ""
        self._reading = False
        self._ctrl_c_read = False
        self._worker: threading.Thread | None = None
        #: H223: None until a turn tried ``/chat/stream``; False when the hub has no stream
        #: route (every later turn uses ``POST /chat``).
        self._stream_ok: bool | None = None
        self._startup: Outgoing | None = None
        #: H235: the last answer (for /copy), and the battery's last reading and warning
        self.last_answer = ""
        self._battery_checked = 0.0
        self._battery_warned: int | None = None

    # output -----------------------------------------------------------------
    def say(self, text: str = "") -> None:
        with self._lock:
            stream = self.ctx.err
            try:
                if self._reading:
                    stream.write("\r\x1b[K")
                stream.write(text + "\n")
                stream.flush()
            except (OSError, ValueError, AttributeError):
                return
            if self._reading and self._rl is not None:
                with contextlib.suppress(Exception):
                    self._rl.redisplay()

    def answer(self, text: str) -> None:
        from .nerva import _answer_text

        with self._lock:
            if self._reading:
                with contextlib.suppress(OSError, ValueError):
                    self.ctx.err.write("\r\x1b[K")
            try:
                self.ctx.out.write(_answer_text(text).rstrip("\n") + "\n")
                self.ctx.out.flush()
            except (OSError, ValueError):
                pass
            if self._reading and self._rl is not None:
                with contextlib.suppress(Exception):
                    self._rl.redisplay()

    # setup ------------------------------------------------------------------
    def load_catalog(self) -> None:
        from .client import HubError

        try:
            reply = self.ctx.client().get("/api/commands")
        except HubError:
            return
        from .chat_prompts import card_safe

        rows = reply.get("commands") if isinstance(reply, dict) else None
        names = []
        described = []
        for row in rows if isinstance(rows, list) else []:
            command = row.get("command") if isinstance(row, dict) else None
            if isinstance(command, str) and re.fullmatch(r"/[a-z0-9][a-z0-9_-]{0,63}", command):
                names.append(command)
                described.append((command, card_safe(row.get("description"))[:200]))
        self.commands = names
        self.described = described

    def file_refs(self, prefix: str) -> list[str]:
        """The hub's ``@file:`` references for *prefix* (``GET /api/context-refs``), as the
        hub wrote them. Asked with a short budget; an unreachable hub is not asked again
        for a while, so Tab never freezes the prompt. A reference with a control, bidi or
        zero-width character is dropped, not drawn (and not "fixed": it would not resolve)."""
        from .chat_prompts import terminal_unsafe
        from .client import HubError, HubUnavailable

        if time.monotonic() < self._refs_down_until:
            return []
        path = f"/api/context-refs?prefix={quote(prefix[:1024], safe='')}"
        client = self.ctx.client()
        request = getattr(client, "request", None)
        try:
            if callable(request) and _accepts(request, "timeout"):
                reply = request("GET", path, timeout=COMPLETION_TIMEOUT)
            else:
                reply = client.get(path)
        except HubUnavailable:
            self._refs_down_until = time.monotonic() + COMPLETION_BACKOFF
            return []
        except HubError:
            return []
        items = reply.get("items") if isinstance(reply, dict) else None
        refs = []
        for item in items if isinstance(items, list) else []:
            ref = item.get("ref") if isinstance(item, dict) else None
            if isinstance(ref, str) and ref.startswith("@file:") and len(ref) <= 2048 \
                    and not terminal_unsafe(ref):
                refs.append(ref)
        return refs[:200]

    def install_readline(self) -> None:
        rl = self._rl
        if rl is None:
            return
        libedit = "libedit" in (getattr(rl, "__doc__", "") or "")
        with contextlib.suppress(Exception):
            rl.set_auto_history(False)
        rl.set_completer_delims(" \t\n\"'")
        if libedit:
            rl.parse_and_bind("bind ^I rl_complete")
        else:
            for binding in READLINE_BINDINGS:
                rl.parse_and_bind(binding)
        state: dict[str, list[str]] = {}

        def complete(text: str, index: int) -> str | None:
            if index == 0:
                line = rl.get_line_buffer()
                state["c"] = completions(text, line=line, begin=rl.get_begidx(),
                                         commands=self.commands, refs=self.file_refs,
                                         described=self.described)
            options = state.get("c", [])
            return options[index] if index < len(options) else None

        rl.set_completer(complete)
        if self.history_file is not None:
            for entry in load_history(self.history_file):
                rl.add_history(entry)

        def prefill() -> None:
            if self._prefill:
                rl.insert_text(self._prefill)
                self._prefill = ""
                rl.redisplay()

        rl.set_pre_input_hook(prefill)

    # the keyboard -----------------------------------------------------------
    def _on_sigint(self, signum, frame) -> None:
        draft = ""
        if self._rl is not None:
            with contextlib.suppress(Exception):
                draft = self._rl.get_line_buffer()
        self._draft_at_interrupt = draft
        raise KeyboardInterrupt

    def read_line(self, prompt: str) -> str | None:
        """One line; None at end of input. Ctrl+C is handled here (never raised)."""
        self._draft_at_interrupt = ""
        self._ctrl_c_read = False
        self._reading = True
        try:
            return self._reader(prompt)
        except EOFError:
            return None
        except KeyboardInterrupt:
            self._ctrl_c_read = True
            self.on_ctrl_c(self._draft_at_interrupt)
            return ""
        finally:
            self._reading = False

    def on_ctrl_c(self, draft: str) -> str:
        armed = self.exit_armed_at is not None and time.monotonic() - self.exit_armed_at < EXIT_ARM_SECONDS
        action = ctrl_c_action(draft or "".join(self.continued), turn_running=self.running, exit_armed=armed)
        if action == "clear":
            self.continued = []
            self.exit_armed_at = None
            self.say("(draft cleared)")
        elif action == "interrupt":
            self.exit_armed_at = None
            self.interrupt()
        elif action == "exit":
            self.stopped = True
        else:
            self.exit_armed_at = time.monotonic()
            self.say("(press Ctrl+C again to exit, or Ctrl+D)")
        return action

    def interrupt(self) -> None:
        """Stop the turn on the wire — the one that was sent, in the session it was sent
        to, whatever /switch did since (review M2). Nothing is sent when no turn is, and a
        request always names the turn (its session, or the turn id sent with it)."""
        from .client import HubError

        with self._lock:
            turn = dict(self.inflight) if self.inflight else None
        if turn is None:
            self.say("(nothing to stop)")
            return
        if turn.get("kind") == "vision":
            self.say("an image turn cannot be stopped from here; it finishes on its own")
            return
        body = {key: turn[key] for key in ("session_id", "turn_id") if turn.get(key)}
        if not body:
            self.say("this turn cannot be stopped yet (the hub has not named its conversation); "
                     "it finishes on its own")
            return
        try:
            reply = self.ctx.client().post("/chat/interrupt", body)
        except HubError as exc:
            if exc.status in (404, 405):
                self.say("this hub cannot stop a turn; it will finish on its own")
            elif exc.status in (401, 403):
                self.say("this terminal's credential cannot stop the turn")
            else:
                self.say(f"the turn was not stopped (HTTP {exc.status})")
            return
        count = reply.get("interrupted") if isinstance(reply, dict) else None
        if type(count) is int and count > 0:
            with self._lock:
                if self.inflight is not None and self.inflight.get("turn_id") == turn.get("turn_id"):
                    self.inflight["stopped"] = True
                # the stopped turn's questions are moot; approvals already queued stay
                kept = [ask for ask in self.asks if ask[0] != "question"]
                self.asks.clear()
                self.asks.extend(kept)
                held = len(self.queue)
                self.queue_held = held > 0
            self.say("(stopping the turn… a step that is already running may still finish)")
            if held:
                self.say(f"({held} queued message(s) held: Enter sends them, /queue clear drops them)")
        else:
            self.say("(nothing to stop: the turn had already finished)")

    # client commands --------------------------------------------------------
    def local(self, line: str) -> None:
        head, _, rest = line.partition(" ")
        rest = rest.strip()
        if head in ("/exit", "/quit"):
            self.stopped = True
        elif head == "/keys":
            for text in KEY_HELP:
                self.say(text)
        elif head == "/edit":
            text = compose_in_editor(self.ctx.environ, rest, err=self.ctx.err)
            if text is not None:
                self._prefill = text
                if self._rl is None and text.strip():
                    self.submit(text)
        elif head == "/image":
            self.stage_image(rest)
        elif head == "/paste-image":
            self.staged_clipboard = True
            self.say("the clipboard's image goes with your next message (to the vision model)")
        elif head == "/queue":
            self.queue_command(rest)
        elif head == "/switch":
            self.switch(rest)
        elif head == "/model":
            self.model(rest)
        elif head == "/copy":
            self.copy_answer()
        elif head == "/where":
            for line in self.where_lines():
                self.say(line)

    # where it runs (H235) ---------------------------------------------------
    def where_lines(self) -> list[str]:
        from . import term_info

        def absolute(name: str) -> Path | None:
            value = (self.ctx.environ.get(name) or "").strip()
            return Path(value) if value and os.path.isabs(value) else None

        try:
            cwd = Path.cwd()
        except OSError:
            return ["working directory: (gone)"]
        branch = term_info.git_branch(cwd)
        charge = term_info.battery()
        parts = [term_info.cwd_label(cwd, absolute("HOME") or absolute("USERPROFILE")),
                 f"git {branch}" if branch else "not in a git repository"]
        if charge is not None:
            parts.append(charge.label())
        return [" · ".join(parts)]

    def copy_answer(self) -> None:
        from . import term_info
        from .nerva import _answer_text

        text = _answer_text(self.last_answer).strip("\n")
        if not text:
            self.say("no answer to copy yet")
            return
        sequence = term_info.osc52(text, self.ctx.environ)
        if sequence is None:
            self.say("the last answer is too long to copy through the terminal")
            return
        with self._lock:
            try:
                self.ctx.out.write(sequence)
                self.ctx.out.flush()
            except (OSError, ValueError):
                return
        self.say(f"copied {len(text):,} characters (OSC 52: a terminal that does not allow it ignores this)")

    def check_battery(self, *, now: float | None = None) -> None:
        """Battery polling: at most once a minute, a warning when the battery is
        discharging at or below BATTERY_WARN %, again for every 5 points it drops."""
        from . import term_info

        now = time.monotonic() if now is None else now
        if now - self._battery_checked < BATTERY_POLL_SECONDS:
            return
        self._battery_checked = now
        charge = term_info.battery()
        if charge is None or charge.charging or charge.percent > BATTERY_WARN:
            self._battery_warned = None
            return
        if self._battery_warned is not None and charge.percent > self._battery_warned - 5:
            return
        self._battery_warned = charge.percent
        self.say(f"battery {charge.percent}% and discharging")

    def stage_image(self, path: str) -> None:
        from .nerva import VISION_MAX_IMAGES, _plain, _read_image

        if not path:
            self.say("usage: /image PATH")
            return
        path = os.path.expanduser(path.strip().strip("'\""))
        raw, why = _read_image(path)
        if raw is None:
            self.say(f"not attached: {_plain(why, 200)}")
            return
        if len(self.staged_images) + 1 > VISION_MAX_IMAGES:
            self.say(f"one turn carries up to {VISION_MAX_IMAGES} images")
            return
        self.staged_images.append(path)
        self.say(f"attached {_plain(os.path.basename(path), 80)}; it goes with your next message "
                 "to the vision model (not to an agent or this conversation)")

    def queue_command(self, rest: str) -> None:
        from .nerva import _plain

        with self._lock:
            if rest == "clear":
                dropped = len(self.queue)
                self.queue.clear()
                self.say(f"dropped {dropped} queued message(s)")
                return
            if rest.startswith("edit"):
                # H225: take a queued message back into the draft to change it; it is
                # sent again (at the end of the queue) when Enter is pressed.
                arg = rest[4:].strip()
                if arg.isdigit() and 1 <= int(arg) <= len(self.queue):
                    item = self.queue[int(arg) - 1]
                    del self.queue[int(arg) - 1]
                    self._prefill = item.message
                    self.staged_images = [*item.images, *self.staged_images]
                    self.staged_clipboard = self.staged_clipboard or item.clipboard_image
                    self.say(f"queued message {arg} is back in your draft" if self._rl is not None else
                             f"queued message {arg} was taken out of the queue: {_plain(item.message, 300)}")
                else:
                    self.say("usage: /queue edit N")
                return
            if rest.startswith("drop"):
                arg = rest[4:].strip()
                if arg.isdigit() and 1 <= int(arg) <= len(self.queue):
                    del self.queue[int(arg) - 1]
                    self.say(f"dropped queued message {arg}")
                else:
                    self.say("usage: /queue drop N")
                return
            if not self.queue:
                self.say("nothing queued")
            for index, item in enumerate(self.queue, 1):
                self.say(f"  {index}. {_plain(item.message, 100)}")

    def switch(self, rest: str) -> None:
        from .chat_prompts import card_safe
        from .client import HubError

        if rest == "new":
            with self._lock:
                self.session_id = None
                self._generation += 1
            self.say("the next message starts in the hub's current conversation "
                     "(send /new to start a fresh one)")
            return
        try:
            listing = self.ctx.client().get("/sessions")
        except HubError as exc:
            self.say(f"cannot list your sessions (HTTP {exc.status})")
            return
        rows = [r for r in ((listing or {}).get("sessions") or []) if isinstance(r, dict)] \
            if isinstance(listing, dict) else []
        ids = []
        for row in rows:
            sid = row.get("resume_id") or row.get("session_id") or row.get("id")
            if isinstance(sid, str) and _SESSION_ID.match(sid):
                ids.append((sid, card_safe(row.get("title") or "")[:60]))
        if not rest:
            if not ids:
                self.say("no sessions")
            for index, (sid, title) in enumerate(ids, 1):
                mark = "*" if sid == self.session_id else " "
                self.say(f" {mark}{index:>2}. {sid}  {title}")
            self.say("/switch N or /switch <id> continues that conversation")
            return
        chosen = None
        if rest.isdigit() and 1 <= int(rest) <= len(ids):
            chosen = ids[int(rest) - 1][0]
        elif any(sid == rest for sid, _ in ids):
            chosen = rest
        if chosen is None:
            self.say("not one of your sessions; /switch lists them")
            return
        if self.running:
            self.say("switched; the running turn finishes in its own conversation "
                     "(Ctrl+C still stops it)")
        with self._lock:
            self.session_id = chosen
            self._generation += 1
        self.say(f"now in {chosen}")

    def model(self, rest: str) -> None:
        from .chat_prompts import card_safe
        from .client import HubError

        client = self.ctx.client()
        try:
            listing = client.get("/api/models/local")
        except HubError as exc:
            if exc.status in (401, 403):
                self.say("only the owner picks the model (this terminal has no admin credential)")
            else:
                self.say(f"cannot list the models (HTTP {exc.status})")
            return
        rows = [r for r in ((listing or {}).get("models") or []) if isinstance(r, dict)] \
            if isinstance(listing, dict) else []
        pickable = [(card_safe(r.get("id"))[:120], card_safe(r.get("provider"))[:20], r.get("active") is True)
                    for r in rows
                    if isinstance(r.get("id"), str) and r.get("provider") in ("lm-studio", "ollama")
                    and r.get("available") is not False]
        if not rest:
            if not pickable:
                self.say("no local model the hub can switch to")
            for index, (mid, provider, active) in enumerate(pickable, 1):
                self.say(f" {'*' if active else ' '}{index:>2}. {mid}  ({provider})")
            if pickable:
                self.say("/model N or /model <id> switches (the hub's own switch, for the owner)")
            return
        chosen = None
        if rest.isdigit() and 1 <= int(rest) <= len(pickable):
            chosen = pickable[int(rest) - 1]
        else:
            chosen = next((row for row in pickable if row[0] == rest), None)
        if chosen is None:
            self.say("not one of the listed models")
            return
        try:
            reply = client.post("/api/models/local/switch", {"model": chosen[0], "provider": chosen[1]})
        except HubError as exc:
            self.say("only the owner picks the model" if exc.status in (401, 403)
                     else f"not switched (HTTP {exc.status})")
            return
        self.say(f"model: {card_safe((reply or {}).get('active') or chosen[0])[:120]}")

    # turns ------------------------------------------------------------------
    def submit(self, text: str) -> None:
        from .nerva import CHAT_MAX_CHARS

        if len(text) > CHAT_MAX_CHARS:
            self.say(f"not sent: {len(text):,} characters, and one turn carries up to {CHAT_MAX_CHARS:,}")
            self._prefill = text
            return
        if self.history_file is not None:
            append_history(self.history_file, text)
            if self._rl is not None and not keep_out_of_history(text):
                with contextlib.suppress(Exception):
                    self._rl.add_history(text)
        item = Outgoing(text, list(self.staged_images), self.staged_clipboard)
        self.staged_images, self.staged_clipboard = [], False
        with self._wake:
            busy = self.running or bool(self.queue)
            self.queue.append(item)
            self._wake.notify_all()
        if busy:
            self.say(f"(queued: {len(self.queue)} waiting for the running turn)")

    def _work(self) -> None:
        while True:
            with self._wake:
                while (not self.queue or self.queue_held) and not self.stopped:
                    self._wake.wait(0.5)
                if self.stopped:
                    return
                item = self.queue.popleft()
                self.running = True
            try:
                self.run_turn(item)
            except Exception as exc:  # noqa: BLE001 — a turn failing never ends the chat
                from .nerva import _plain

                self.say(f"the turn failed: {_plain(exc, 200)}")
            finally:
                with self._wake:
                    self.running = False
                    self._wake.notify_all()

    def run_turn(self, item: Outgoing) -> None:
        import secrets

        with self._lock:
            session, generation = self.session_id, self._generation
            self.inflight = {"session_id": session, "turn_id": None, "generation": generation,
                             "kind": "vision" if item.images or item.clipboard_image else "chat",
                             "stopped": False}
        try:
            if item.images or item.clipboard_image:
                self.vision_turn(item)
                return
            self._chat_turn(item, session, generation, secrets.token_hex(16))
        finally:
            with self._lock:
                self.inflight = None

    def _chat_turn(self, item: Outgoing, session: str | None, generation: int, turn_id: str) -> None:
        from .chat_prompts import POLL_SECONDS, TURN_TIMEOUT_SECONDS, _pending, _PollRefused
        from .client import HubError, HubUnavailable

        body: dict[str, Any] = {"message": item.message}
        if session:
            body["session_id"] = session
        if self.agent:
            body["agent"] = self.agent
        if self.reasoning:
            body["reasoning"] = self.reasoning
        client = self.ctx.client()
        if (self._stream_ok is not False and callable(getattr(client, "stream", None))
                and self._stream_turn(client, body, session, generation, turn_id)):
            return
        box: dict[str, Any] = {}
        # The turn id goes in a header (an older hub ignores it; the body's schema is
        # strict): before the hub names the conversation, Ctrl+C names the turn by it.
        post_kwargs: dict[str, Any] = {}
        if _accepts(client.post, "timeout"):
            post_kwargs["timeout"] = TURN_TIMEOUT_SECONDS
        if _accepts(client.post, "headers"):
            post_kwargs["headers"] = {"X-Nerva-Turn-Id": turn_id}
            with self._lock:
                if self.inflight is not None:
                    self.inflight["turn_id"] = turn_id

        def post() -> None:
            try:
                box["reply"] = client.post("/chat", body, **post_kwargs)
            except BaseException as exc:  # noqa: BLE001 — handed to this thread
                box["error"] = exc

        poster = threading.Thread(target=post, name="nerva-chat-post", daemon=True)
        poster.start()
        seen: set[str] = set()
        polling = True
        while poster.is_alive():
            poster.join(POLL_SECONDS)
            if not poster.is_alive() or not polling or (self.inflight or {}).get("stopped"):
                continue
            try:
                questions = _pending(client, body.get("session_id"))
            except _PollRefused:
                polling = False
                continue
            if questions is None:
                polling = False
                continue
            for question in questions:
                prompt_id = str(question.get("id", ""))
                if prompt_id and prompt_id not in seen:
                    seen.add(prompt_id)
                    with self._lock:
                        self.asks.append(("question", question, session))
                    self.say("? the turn asks you something — press Enter to answer it")
        if "error" in box:
            exc = box["error"]
            if isinstance(exc, HubUnavailable):
                self.say("no hub is reachable; the message was not sent")
            elif isinstance(exc, HubError):
                from .nerva import _plain

                self.say(f"the hub refused the turn (HTTP {exc.status}): {_plain(exc.reason, 200)}")
            else:
                raise exc
            return
        self.show_reply(box.get("reply"), generation=generation)

    def show_reply(self, reply: Any, *, generation: int | None = None, streamed: bool = False) -> None:
        """Draw a turn's reply. The conversation the hub names becomes this chat's only
        when the user has not switched since the turn was sent (review M3). *streamed*:
        the answer was already drawn as it arrived; only what follows it is drawn here."""
        from .nerva import _pending_ids, _recall_lines

        if not isinstance(reply, dict):
            self.say("the hub's reply is malformed")
            return
        if isinstance(reply.get("reply"), str):
            self.last_answer = reply["reply"][:COPY_LIMIT]
        returned = reply.get("session_id")
        if isinstance(returned, str) and _SESSION_ID.match(returned):
            with self._lock:
                if generation is None or generation == self._generation:
                    self.session_id = returned
        if not streamed:
            for line in _recall_lines(reply):
                self.say(line)
            self.answer(str(reply.get("reply", "")))
        for notice in reply.get("notices") or []:
            if isinstance(notice, dict) and isinstance(notice.get("text"), str):
                from .chat_prompts import card_safe

                self.say(f"ℹ {card_safe(notice['text'])[:300]}")
        pending, _ = _pending_ids(reply.get("pending_approvals"))
        if pending:
            with self._lock:
                self.asks.append(("approvals", list(pending), None))
            self.say(f"! this turn queued {len(pending)} approval(s) — press Enter to decide them here")

    # streamed turns (H223) -------------------------------------------------
    def _stream_turn(self, client: Any, body: dict[str, Any], session: str | None,
                     generation: int, turn_id: str) -> bool:
        """Run the turn over ``POST /chat/stream``; False (nothing sent) when the hub has
        no stream route, so the caller falls back to ``POST /chat``."""
        from .chat_prompts import TURN_TIMEOUT_SECONDS
        from .client import HubError, HubUnavailable

        with self._lock:
            if self.inflight is not None:
                self.inflight["turn_id"] = turn_id
        done = threading.Event()
        watcher = threading.Thread(target=self._watch_questions,
                                   args=(client, body.get("session_id"), session, done),
                                   name="nerva-chat-questions", daemon=True)
        feed = AnswerFeed(self.answer)
        reply: dict[str, Any] | None = None
        events = client.stream("/chat/stream", {**body, "tool_events": True}, timeout=TURN_TIMEOUT_SECONDS,
                               headers={"X-Nerva-Turn-Id": turn_id, "X-Nerva-Pending": "poll"})
        started = False
        try:
            for event in events:
                if not started:
                    started = True
                    self._stream_ok = True
                    watcher.start()
                kind = event.get("type")
                if kind == "token" and isinstance(event.get("text"), str):
                    feed.feed(event["text"])
                elif kind == "tool":
                    line = tool_line(event.get("event"))
                    if line:
                        feed.flush()
                        self.say(line)
                elif kind == "clarify" and isinstance(event.get("id"), str):
                    # A hub that ignored the poll header asks in the stream instead.
                    with self._lock:
                        self.asks.append(("question", event, session))
                    self.say("? the turn asks you something — press Enter to answer it")
                elif kind == "end":
                    reply = {"reply": event.get("text"), "session_id": event.get("session_id"),
                             "pending_approvals": event.get("pending_approvals"),
                             "notices": event.get("notices"), "outcome": event.get("outcome")}
                    break
        except HubError as exc:
            if not started and exc.status in (404, 405):
                self._stream_ok = False
                return False
            feed.flush()
            if isinstance(exc, HubUnavailable):
                self.say("no hub is reachable; the message was not sent" if not started
                         else "the hub went away during the turn")
            else:
                from .nerva import _plain

                self.say(f"the hub refused the turn (HTTP {exc.status}): {_plain(exc.reason, 200)}")
            return True
        finally:
            done.set()
            close = getattr(events, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    close()
            if watcher.is_alive():
                watcher.join(2)
        drew = feed.close()
        if reply is None:
            self.say("the turn's stream ended without its end; the answer may be incomplete")
            return True
        if not drew:
            text = reply.get("reply")
            if isinstance(text, str) and text:
                self.answer(text)
        from .nerva import _recall_lines

        for line in _recall_lines(reply):
            self.say(line)
        self.show_reply(reply, generation=generation, streamed=True)
        return True

    def _watch_questions(self, client: Any, asked_session: str | None, session: str | None,
                         done: threading.Event) -> None:
        """Poll ``GET /chat/pending`` while a streamed turn runs; hand each new question
        to the keyboard thread once (as the ``POST /chat`` path does)."""
        from . import chat_prompts

        seen: set[str] = set()
        while not done.wait(chat_prompts.POLL_SECONDS):
            if (self.inflight or {}).get("stopped"):
                continue
            try:
                questions = chat_prompts._pending(client, asked_session)
            except chat_prompts._PollRefused:
                return
            if questions is None:
                return
            for question in questions:
                prompt_id = str(question.get("id", ""))
                if prompt_id and prompt_id not in seen:
                    seen.add(prompt_id)
                    with self._lock:
                        self.asks.append(("question", question, session))
                    self.say("? the turn asks you something — press Enter to answer it")

    def vision_turn(self, item: Outgoing) -> None:
        import argparse

        from .nerva import _vision_turn

        ns = argparse.Namespace(image=item.images, clipboard_image=item.clipboard_image, agent=None,
                                session=None, reasoning=None, remote_vision=None, json=False,
                                confirm_expensive=False, acknowledge_training=False)
        try:
            _vision_turn(ns, self.ctx, item.message, finish=lambda code, **_: code, oneshot=False)
        except Exception as exc:  # noqa: BLE001
            from .nerva import _plain

            self.say(f"the image turn failed: {_plain(exc, 200)}")

    def answer_asks(self) -> None:
        from .chat_prompts import _answer_clarify, _answer_secret, decide_queued

        while True:
            with self._lock:
                if not self.asks:
                    return
                kind, payload, session = self.asks.popleft()
            try:
                if kind == "question":
                    if payload.get("kind") == "secret":
                        _answer_secret(self.ctx, self.ctx.client(), payload,
                                       self.ctx.secret_reader or _getpass(self.ctx), session)
                    else:
                        _answer_clarify(self.ctx, self.ctx.client(), payload, session)
                else:
                    decide_queued(self.ctx, payload)
            except KeyboardInterrupt:
                self.say("(skipped)")

    # main loop --------------------------------------------------------------
    def prompt(self) -> str:
        if self.continued:
            return "… "
        return "nerva (running)> " if self.running else "nerva> "

    def step(self) -> bool:
        """Read and handle one line; False at end of input."""
        self.answer_asks()
        self.check_battery()
        line = self.read_line(self.prompt())
        if line is None:
            if self.running:
                self.interrupt()
            return False
        if self.stopped:
            return False
        try:
            return self._handle(line)
        finally:
            if not self._ctrl_c_read:
                self.release_queue()      # any Enter lets held messages go (review m5)

    def _handle(self, line: str) -> bool:
        if line.strip():
            self.exit_armed_at = None
        kind, text = route_line(line)
        if kind == "empty":
            return True
        if kind == "continue":
            self.continued.append(text)
            return True
        if self.continued and kind == "local":
            # A client command (Ctrl+X Ctrl+E's "/edit", /exit, ...) acts on the
            # backslash-continued draft; it is never sent half-written (review m6).
            head, _, rest = text.partition(" ")
            draft = "\n".join([*self.continued, *([rest] if rest.strip() else [])])
            if head == "/edit":
                self.continued = []
                self.local(f"/edit {draft}")
            elif head in ("/exit", "/quit"):
                self.continued = []
                self.say("(the unsent draft was discarded)")
                self.local(head)
            else:
                self.local(text)          # the draft stays; the prompt still says "…"
            return True
        if self.continued:
            text = "\n".join([*self.continued, line])
            self.continued = []
            kind = "send"
        if kind == "local":
            self.local(text)
        else:
            self.submit(text)
        return True

    def release_queue(self) -> None:
        with self._wake:
            if not self.queue_held:
                return
            self.queue_held = False
            self._wake.notify_all()

    def run(self) -> int:
        self.load_catalog()
        self.install_readline()
        previous = None
        if threading.current_thread() is threading.main_thread():
            previous = signal.signal(signal.SIGINT, self._on_sigint)
        self._worker = threading.Thread(target=self._work, name="nerva-chat-turns", daemon=True)
        self._worker.start()
        self.say("Nerva chat. Enter sends · Alt+Enter newline · Ctrl+C clears / stops / exits · "
                 "/keys for the rest")
        with contextlib.suppress(Exception):      # where it runs: never a reason not to start
            for line in self.where_lines():
                self.say(line)
        code = 0
        try:
            self.send_startup()
            while not self.stopped:
                try:
                    if not self.step():
                        break
                except KeyboardInterrupt:      # Ctrl+C outside the prompt (an HTTP call, a menu)
                    self.on_ctrl_c("")
        except Exception as exc:  # noqa: BLE001 — H223: a client bug ends the chat, never the terminal
            from .nerva import _plain

            code = 1
            self.say(f"the chat stopped on an internal error ({_plain(type(exc).__name__, 60)}: "
                     f"{_plain(exc, 160)}); the conversation is kept on the hub")
        finally:
            with self._wake:
                self.stopped = True
                dropped = len(self.queue)
                self._wake.notify_all()
            if dropped:
                self.say(f"{dropped} queued message(s) were not sent")
            if previous is not None:
                signal.signal(signal.SIGINT, previous)
            self.say_resume_hint()
        return code

    def start_with(self, message: str | None = None, images: Iterable[str] = (),
                   clipboard_image: bool = False) -> bool:
        """H223 — what ``nerva chat -i MESSAGE [--image PATH] [--clipboard-image]`` sends
        first; False (said why) when an image cannot be attached."""
        before = len(self.staged_images)
        wanted = list(images)
        for path in wanted:
            self.stage_image(path)
        if len(self.staged_images) - before != len(wanted):
            return False
        self.staged_clipboard = self.staged_clipboard or clipboard_image
        if message is not None and message.strip():
            self._startup = Outgoing(message)
        elif self.staged_images or self.staged_clipboard:
            self.say("the image(s) go with your first message")
        return True

    def send_startup(self) -> None:
        if self._startup is not None:
            message, self._startup = self._startup.message, None
            self.say(f"> {card_safe_line(message)}")
            self.submit(message)

    def say_resume_hint(self) -> None:
        """H223 — how to come back to this conversation (the hub keeps it)."""
        with self._lock:
            session = self.session_id
        if isinstance(session, str) and _SESSION_ID.match(session):
            self.say(f"resume this conversation: nerva chat -i -r {session}")


class AnswerFeed:
    """H223 — a streamed answer, drawn a whole line at a time so the open prompt is
    redrawn under it (never mid-word): a line is drawn at its newline, or at the last
    space once it is as wide as the terminal. Each piece goes through the caller's
    *draw* (``Repl.answer``), which strips control, escape, bidi and zero-width
    characters — an escape split across two tokens has lost its ESC before it is drawn."""

    def __init__(self, draw: Callable[[str], None], width: int | None = None) -> None:
        self._draw = draw
        self._width = max(20, width or shutil.get_terminal_size((100, 24)).columns - 1)
        self._buffer = ""
        self.drew = False

    def feed(self, text: str) -> None:
        self._buffer += text
        while True:
            head, newline, rest = self._buffer.partition("\n")
            if newline:
                self._emit(head)
                self._buffer = rest
                continue
            if len(self._buffer) < self._width:
                return
            cut = self._buffer.rfind(" ", 0, self._width)
            cut = cut if cut > 0 else self._width
            self._emit(self._buffer[:cut])
            self._buffer = self._buffer[cut:].lstrip(" ")

    def flush(self) -> None:
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""

    def close(self) -> bool:
        """Draw what is left; whether anything was drawn at all."""
        self.flush()
        return self.drew

    def _emit(self, line: str) -> None:
        self.drew = True
        self._draw(line)


_TOOL_MARKS = {"tool_start": "⋯", "tool_end": "✓", "tool_error": "✗"}


def tool_line(event: Any) -> str | None:
    """One line of the turn's tool trail (H223), from a stream ``tool`` event the hub
    already cut to event/tool/call id/status; heartbeats and unknown events draw nothing.
    The names are the hub's, made card-safe and bounded."""
    from .chat_prompts import card_safe

    if not isinstance(event, dict):
        return None
    kind = event.get("event")
    mark = _TOOL_MARKS.get(kind) if isinstance(kind, str) else None
    tool = card_safe(event.get("tool"))[:60]
    if mark is None or not tool:
        return None
    status = card_safe(event.get("status"))[:40]
    if kind == "tool_end" and status and status not in ("ok", "success", "done"):
        mark = "✗"
    return f"  {mark} {tool}" + (f" ({status})" if status and kind != "tool_start" else "")


def card_safe_line(text: str, width: int = 120) -> str:
    from .chat_prompts import card_safe

    line = card_safe(text)
    return line if len(line) <= width else line[: width - 1] + "…"


def _accepts(function: Any, name: str) -> bool:
    """Whether *function* takes the keyword *name* (a test's fake client may not)."""
    import inspect

    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(p.kind is p.VAR_KEYWORD for p in parameters.values())


def _getpass(ctx) -> Callable[[str], str]:
    import getpass

    return lambda prompt: getpass.getpass(prompt, stream=ctx.err)


def load_readline() -> Any:
    """The readline module, or None where there is none (Windows without pyreadline)."""
    try:
        import readline
    except ImportError:
        return None
    return readline
