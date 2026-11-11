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
Up / Down              history (persistent, owner-only file, ``--no-history`` off)
paste                  bracketed paste: a multi-line paste is one draft, not N turns
=====================  ==========================================================

Client commands (never sent to the hub): ``/edit``, ``/image PATH``, ``/paste-image``,
``/switch [N|id|new]`` (your sessions, ``GET /sessions``), ``/model [N|id]`` (the hub's
local models; switching is the owner's admin route and is refused otherwise),
``/queue [clear|drop N]``, ``/keys``, ``/exit``. Everything else — ``/help``, ``/recap``,
any hub command — goes to the hub as a message, where the command plane judges it.

A message typed while a turn runs is queued and sent, in order, when the turn ends.

Security: nothing the hub or the model writes is ever executed here; their text is
stripped of control sequences before it is drawn. The editor is the owner's own
``$VISUAL``/``$EDITOR`` argv (no shell). A line that looks like a key or token is kept
out of the history file.
"""

from __future__ import annotations

import collections
import contextlib
import json
import os
import re
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
    "/queue": "messages waiting for the running turn; /queue clear, /queue drop N",
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
EXIT_ARM_SECONDS = 3.0
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
                refs: Callable[[str], list[str]] | None = None) -> list[str]:
    """Candidates for the word *text* that starts at *begin* in *line*.

    A ``/word`` at the start of the line completes from the hub's commands and this
    client's own; ``@file:prefix`` anywhere completes from *refs* (the hub's scope)."""
    if text.startswith("/") and not line[:begin].strip():
        names = sorted(set(commands) | set(LOCAL_COMMANDS))
        return [name for name in names if name.startswith(text)]
    if text.startswith("@file:") and refs is not None:
        prefix = text[len("@file:"):]
        return [f"@file:{ref}" for ref in refs(prefix)]
    if text.startswith("@") and "@file:".startswith(text):
        return ["@file:"]
    return []


# ── history ──────────────────────────────────────────────────────────────────

def history_path(environ: Mapping[str, str]) -> Path:
    from agents.core.paths import data_path

    return data_path("cli", "chat_history.jsonl")


def load_history(path: Path, limit: int = HISTORY_LIMIT) -> list[str]:
    """Entries of the history file, oldest first (one JSON string per line, so a
    multi-line message stays one entry). A file someone else can read is not trusted
    to be ours: it is re-permissioned, not skipped, and a broken line is ignored."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    with contextlib.suppress(OSError):
        if path.stat().st_mode & 0o077:
            os.chmod(path, 0o600)
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
    """Append one entry (owner-only file, 0600); the file is cut to *limit* entries."""
    from .chat_prompts import looks_like_secret

    if not entry.strip() or looks_like_secret(entry):
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.chmod(path, 0o600)
        entries = load_history(path, limit=limit * 2)
        if len(entries) > limit:
            temp = path.with_name(path.name + ".tmp")
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in entries[-limit:])
            os.replace(temp, path)
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
        self.history_file = history_path(ctx.environ) if history else None
        self._reader = reader or input
        self._rl = readline_module
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self.queue: collections.deque[Outgoing] = collections.deque()
        self.asks: collections.deque[tuple[str, Any]] = collections.deque()
        self.running = False
        self.stopped = False
        self.exit_armed_at: float | None = None
        self.staged_images: list[str] = []
        self.staged_clipboard = False
        self.commands: list[str] = []
        self.continued: list[str] = []
        self._draft_at_interrupt = ""
        self._prefill = ""
        self._reading = False
        self._worker: threading.Thread | None = None

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
        rows = reply.get("commands") if isinstance(reply, dict) else None
        names = []
        for row in rows if isinstance(rows, list) else []:
            command = row.get("command") if isinstance(row, dict) else None
            if isinstance(command, str) and re.fullmatch(r"/[a-z0-9][a-z0-9_-]{0,63}", command):
                names.append(command)
        self.commands = names

    def file_refs(self, prefix: str) -> list[str]:
        from .client import HubError

        try:
            reply = self.ctx.client().get(f"/api/context-refs?prefix={quote(prefix[:1024], safe='')}")
        except HubError:
            return []
        items = reply.get("items") if isinstance(reply, dict) else None
        refs = []
        for item in items if isinstance(items, list) else []:
            ref = item.get("ref") if isinstance(item, dict) else None
            if isinstance(ref, str) and ref and not any(ord(c) < 32 for c in ref):
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
                                         commands=self.commands, refs=self.file_refs)
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
        self._reading = True
        try:
            return self._reader(prompt)
        except EOFError:
            return None
        except KeyboardInterrupt:
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
        from .client import HubError

        body = {"session_id": self.session_id} if self.session_id else {}
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
            self.say("(stopping the turn…)")
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
            self.session_id = None
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
            self.say("switched; the running turn finishes in its own conversation")
        self.session_id = chosen
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
            if self._rl is not None:
                from .chat_prompts import looks_like_secret

                if not looks_like_secret(text):
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
                while not self.queue and not self.stopped:
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
        from .chat_prompts import POLL_SECONDS, _pending, _PollRefused, _post_turn
        from .client import HubError, HubUnavailable

        if item.images or item.clipboard_image:
            self.vision_turn(item)
            return
        body: dict[str, Any] = {"message": item.message}
        if self.session_id:
            body["session_id"] = self.session_id
        if self.agent:
            body["agent"] = self.agent
        if self.reasoning:
            body["reasoning"] = self.reasoning
        client = self.ctx.client()
        box: dict[str, Any] = {}

        def post() -> None:
            try:
                box["reply"] = _post_turn(client, body)
            except BaseException as exc:  # noqa: BLE001 — handed to this thread
                box["error"] = exc

        poster = threading.Thread(target=post, name="nerva-chat-post", daemon=True)
        poster.start()
        seen: set[str] = set()
        polling = True
        while poster.is_alive():
            poster.join(POLL_SECONDS)
            if not poster.is_alive() or not polling:
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
                        self.asks.append(("question", question))
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
        self.show_reply(box.get("reply"))

    def show_reply(self, reply: Any) -> None:
        from .nerva import _pending_ids, _recall_lines

        if not isinstance(reply, dict):
            self.say("the hub's reply is malformed")
            return
        returned = reply.get("session_id")
        if isinstance(returned, str) and _SESSION_ID.match(returned):
            self.session_id = returned
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
                self.asks.append(("approvals", list(pending)))
            self.say(f"! this turn queued {len(pending)} approval(s) — press Enter to decide them here")

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
                kind, payload = self.asks.popleft()
            try:
                if kind == "question":
                    if payload.get("kind") == "secret":
                        _answer_secret(self.ctx, self.ctx.client(), payload,
                                       self.ctx.secret_reader or _getpass(self.ctx), self.session_id)
                    else:
                        _answer_clarify(self.ctx, self.ctx.client(), payload, self.session_id)
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
        line = self.read_line(self.prompt())
        if line is None:
            if self.running:
                self.interrupt()
            return False
        if self.stopped:
            return False
        if line.strip():
            self.exit_armed_at = None
        kind, text = route_line(line)
        if kind == "empty":
            return True
        if kind == "continue":
            self.continued.append(text)
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
        try:
            while not self.stopped:
                try:
                    if not self.step():
                        break
                except KeyboardInterrupt:      # Ctrl+C outside the prompt (an HTTP call, a menu)
                    self.on_ctrl_c("")
        finally:
            with self._wake:
                self.stopped = True
                dropped = len(self.queue)
                self._wake.notify_all()
            if dropped:
                self.say(f"{dropped} queued message(s) were not sent")
            if previous is not None:
                signal.signal(signal.SIGINT, previous)
        return 0


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
