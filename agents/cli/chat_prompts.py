"""Mid-turn prompts for `nerva chat` (H226): clarify questions, secret entry, approvals.

Nothing here is a second mechanism. While `POST /chat` runs, the turn's clarify and
secret prompts wait in the hub's pending-input runtime, bound to the credential that
started the turn; this module finds them with ``GET /chat/pending`` and answers them
with ``POST /chat/pending/{id}/answer``, the routes the HUD's non-streaming turn uses.

* A clarify answer is the owner's typed text. The hub hands it to the turn through the
  clarify tool, which is registered ``untrusted_output``: the loop fences it as data and
  raises the turn's taint, exactly as for a HUD answer. An answer that looks like a key
  or token is not sent: a secret never travels as an answer.
* A secret is read with ``getpass`` (never echoed), sent only to the admin-guarded
  secret broker route (``POST /api/secrets/broker``, the HUD's Secrets panel route),
  and never to the turn: the pending prompt is answered with the marker ``"stored"``,
  which the hub accepts only once the broker holds the name. The value is never
  printed, logged, written to the usage receipt or put in the conversation.
* Confirmations and sudo-class commands are approval cards in Nerva: a turn that
  needs one queues it and stops. `nerva chat` shows each card it queued and decides it
  through ``POST /autonomy/tasks/{id}/decision`` (admin-guarded), the route the HUD's
  decision inbox and `nerva approvals` use. There is no local bypass and no batch accept.

Every string the model or the hub wrote is untrusted on the terminal (G4 review M2/M3):
it is stripped of control, format (bidi, zero-width), separator, surrogate and
private-use characters, and every line of it is drawn behind a fixed gutter (``│``), so
it can never pose as a line Nerva itself prints. Nerva's own lines start at column 0.

Only an interactive terminal is asked: with stdin piped (a script), nothing is read.
"""

from __future__ import annotations

import getpass
import inspect
import json
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from .client import HubError, carries_secrets

#: How often the pending list is read while the turn runs.
POLL_SECONDS = 0.5
#: How long a turn that may wait on the owner is allowed to take: the hub's clarify
#: window is an hour by default, plus the turn on either side of it.
TURN_TIMEOUT_SECONDS = 75 * 60.0
#: How often a long turn says it is still running.
STILL_WAITING_SECONDS = 60.0
_MAX_ATTEMPTS = 3
_CANCEL = {"/cancel", "!cancel", "/skip"}
GUTTER = "  │ "
_SECRET_NAME = re.compile(r"[A-Z][A-Z0-9_]{1,127}\Z")
#: Common key and token shapes. Not exhaustive: the hub's own scanner runs as well.
_KEY_SHAPES = re.compile(
    r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{6,}|\bgh[pousr]_[A-Za-z0-9]{10,}|\bxox[abpr]-[A-Za-z0-9-]{8,}"
    r"|\bAKIA[0-9A-Z]{12,}|\bAIza[0-9A-Za-z_-]{20,}|\bglpat-[A-Za-z0-9_-]{10,}|\beyJ[A-Za-z0-9_-]{10,}\."
)


def card_safe(text: Any) -> str:
    """One line with no control, format, separator, surrogate or private-use character
    (the rule of agents.core.subagents.card_safe, kept here so the CLI imports no hub
    module): no ANSI, no bidi override, no zero-width mark, whitespace collapsed."""
    kept = []
    for char in str("" if text is None else text):
        kept.append(" " if unicodedata.category(char) in _UNSAFE_CATEGORIES else char)
    return " ".join("".join(kept).split())


#: card_safe's rule: control (C0/C1), format (bidi, zero-width, BOM), line/paragraph
#: separator, surrogate and private-use characters.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs", "Co"})


def terminal_unsafe(text: Any) -> bool:
    """Whether *text* holds a character card_safe would remove — for a hub string that
    must be drawn exactly or not at all (a completion candidate the hub must resolve)."""
    return any(unicodedata.category(char) in _UNSAFE_CATEGORIES for char in str("" if text is None else text))


def _bounded(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def untrusted_lines(text: Any, *, width: int = 300, max_lines: int = 12) -> list[str]:
    """Model-written text as gutter lines: each source line made card-safe, bounded."""
    raw = str("" if text is None else text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_bounded(card_safe(line), width) for line in raw.split("\n")]
    lines = [line for line in lines if line] or [""]
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["…"]
    return [GUTTER + line for line in lines]


def looks_like_secret(text: str) -> bool:
    """Whether a typed answer looks like a key or token (never sent as an answer)."""
    if _KEY_SHAPES.search(text):
        return True
    try:
        from agents.core.security.scanner import SecretScanner, looks_like_high_entropy_secret

        if any(looks_like_high_entropy_secret(token) for token in text.split()):
            return True
        return bool(SecretScanner().scan(text).findings)
    except Exception:
        return False


def _say(ctx, text: str = "") -> None:
    try:
        ctx.err.write(text + "\n")
        ctx.err.flush()
    except (AttributeError, OSError, ValueError, UnicodeEncodeError):
        pass


def _readline(ctx, prompt: str) -> str | None:
    """One line from the terminal, or None at end of input."""
    try:
        ctx.err.write(prompt)
        ctx.err.flush()
    except (AttributeError, OSError, ValueError):
        pass
    try:
        line = ctx.inp.readline()
    except (OSError, ValueError):
        return None
    if not line:
        return None
    return line.rstrip("\r\n")


def _bare(label: str) -> str:
    stripped = label.strip()
    suffix = "(recommended)"
    return stripped[: -len(suffix)].strip() if stripped.casefold().endswith(suffix) else stripped


def _is_choice(text: str, choices: list[str], multi: bool) -> bool:
    """Whether *text* names offered choices (numbers or labels); else it is an own answer."""
    tokens = [t.strip() for t in (text.split(",") if multi and "," in text else
                                  text.split() if multi and all(p.isdigit() for p in text.split())
                                  else [text])]
    if not tokens or not all(tokens):
        return False
    labels = [_bare(c).casefold() for c in choices]
    for token in tokens:
        if token.isdigit():
            if not 1 <= int(token) <= len(choices):
                return False
        elif _bare(token).casefold() not in labels:
            return False
    return True


def _post(client, path: str, body: Any) -> tuple[int, Any]:
    try:
        return 200, client.post(path, body)
    except HubError as exc:
        return exc.status, exc.reason


def _origin_line(question: dict, session_id: str | None) -> str:
    asked_in = card_safe(question.get("session_id", ""))[:128]
    if session_id is None and asked_in:
        return f"  (asked by the turn in conversation {asked_in})"
    return ""


def _answer_clarify(ctx, client, question: dict, session_id: str | None = None) -> str:
    prompt_id = str(question.get("id", ""))
    choices = [str(c) for c in (question.get("choices") or []) if isinstance(c, str)][:4]
    multi = question.get("multi_select") is True
    _say(ctx)
    _say(ctx, "? The turn asks a question (its words, between the bars):")
    origin = _origin_line(question, session_id)
    if origin:
        _say(ctx, origin)
    for line in untrusted_lines(question.get("question", "")):
        _say(ctx, line)
    for index, choice in enumerate(choices, 1):
        _say(ctx, f"{GUTTER}{index}. {_bounded(card_safe(choice), 300)}")
    if choices:
        how = ("numbers or labels separated by commas" if multi else "a number or a label")
        _say(ctx, f"Answer with {how}, or type your own answer. /cancel declines.")
    else:
        _say(ctx, "Type your answer. /cancel declines.")
    _say(ctx, "Never type a password or key here: Nerva asks for secrets only with its own "
              "'Nerva needs the key' prompt, which does not show what you type.")
    path = f"/chat/pending/{quote(prompt_id, safe='')}/answer"
    for _ in range(_MAX_ATTEMPTS):
        text = _readline(ctx, "answer> ")
        if text is None or text.strip().casefold() in _CANCEL:
            status, _ = _post(client, path, {"cancel": True})
            _say(ctx, "declined; the turn continues without an answer")
            return "cancelled" if status == 200 else "gone"
        text = text.strip()
        if not text:
            continue
        if looks_like_secret(text):
            _say(ctx, "not sent: that looks like a key or token, and an answer goes into the "
                      "conversation. Type something else, or /cancel")
            continue
        body: dict[str, Any]
        if not choices or _is_choice(text, choices, multi):
            body = {"answer": text}
        else:
            body = {"answer": text, "other": True}
        status, _ = _post(client, path, body)
        if status == 200:
            return "answered"
        if status == 404:
            _say(ctx, "this question is no longer waiting (answered elsewhere, or timed out)")
            return "gone"
        if status in (401, 403):
            _say(ctx, "this terminal's credential cannot answer this question")
            return "refused"
        _say(ctx, "not accepted; try again")
    _post(client, path, {"cancel": True})
    _say(ctx, "no usable answer; declined")
    return "cancelled"


def _answer_secret(ctx, client, question: dict, read_secret: Callable[[str], str],
                   session_id: str | None = None) -> str:
    prompt_id = str(question.get("id", ""))
    raw_name = question.get("name", "")
    path = f"/chat/pending/{quote(prompt_id, safe='')}/answer"
    if not isinstance(raw_name, str) or not _SECRET_NAME.match(raw_name):
        _post(client, path, {"cancel": True})
        _say(ctx, "declined a secret request with an invalid name")
        return "cancelled"
    name = raw_name
    _say(ctx)
    _say(ctx, f"! Nerva needs the key {name} for a skill you installed.")
    origin = _origin_line(question, session_id)
    if origin:
        _say(ctx, origin)
    reason = _bounded(card_safe(question.get("question", "")), 300)
    if reason:
        _say(ctx, "  the turn says (its words, not Nerva's):")
        _say(ctx, GUTTER + reason)
    base = getattr(client, "base_url", "")
    if not carries_secrets(str(base)):
        _post(client, path, {"cancel": True})
        _say(ctx, "declined: the hub is reached over plain http on another machine, so a "
                  "secret is not sent from here — store it on the hub's machine "
                  "(the HUD's Secrets panel), then ask again")
        return "cancelled"
    _say(ctx, f"Type the value of {name}. It is not shown, goes only to the hub's secret "
              "store, and the conversation sees the name, never the value. Never type a "
              "Nerva token here. An empty line declines.")
    try:
        value = read_secret(f"{name}: ")
    except (EOFError, KeyboardInterrupt, OSError):
        value = ""
    if not value:
        _post(client, path, {"cancel": True})
        _say(ctx, "declined; nothing was stored")
        return "cancelled"
    try:
        status, _ = _post(client, "/api/secrets/broker", {"name": name, "value": value})
    finally:
        value = ""  # noqa: F841 — drop the only local reference as soon as it is sent
    if status != 200:
        _post(client, path, {"cancel": True})
        if status in (401, 403):
            _say(ctx, "not stored: only the owner can store a secret (this terminal has no "
                      "admin credential)")
        elif status == 409:
            _say(ctx, "not stored: your administrator manages this configuration")
        else:
            _say(ctx, f"not stored: the hub refused (HTTP {status})")
        return "refused"
    status, _ = _post(client, path, {"answer": "stored"})
    if status == 200:
        _say(ctx, f"stored {name}; the turn continues")
        return "answered"
    _say(ctx, f"stored {name}, but the question was no longer waiting")
    return "gone"


class _PollRefused(Exception):
    pass


def _pending(client, session_id: str | None) -> list[dict] | None:
    """The live questions; None on an older hub without the routes. A refusal (401,
    403, 429) is raised so the owner sees it instead of a silent wait."""
    path = "/chat/pending" + (f"?session_id={quote(session_id, safe='')}" if session_id else "")
    try:
        reply = client.get(path)
    except HubError as exc:
        if exc.status in (404, 405):
            return None
        if exc.status in (401, 403, 429):
            raise _PollRefused(exc.status) from None
        return []
    questions = reply.get("questions") if isinstance(reply, dict) else None
    return [q for q in questions if isinstance(q, dict)] if isinstance(questions, list) else []


def _post_turn(client, body: dict) -> Any:
    post = client.post
    try:
        accepts_timeout = "timeout" in inspect.signature(post).parameters
    except (TypeError, ValueError):
        accepts_timeout = False
    if accepts_timeout:
        return post("/chat", body, timeout=TURN_TIMEOUT_SECONDS)
    return post("/chat", body)


def run_turn(ctx, body: dict, *, read_secret: Callable[[str], str] | None = None) -> Any:
    """``POST /chat`` while answering the turn's questions on this terminal."""
    client = ctx.client()
    reader = read_secret or (lambda prompt: getpass.getpass(prompt, stream=ctx.err))
    box: dict[str, Any] = {}

    def turn() -> None:
        try:
            box["reply"] = _post_turn(client, body)
        except BaseException as exc:  # handed to the caller's thread unchanged
            box["error"] = exc

    worker = threading.Thread(target=turn, name="nerva-chat-turn", daemon=True)
    worker.start()
    seen: set[str] = set()
    polling = True
    backoff_until = 0.0
    started = last_note = time.monotonic()
    session_id = body.get("session_id") if isinstance(body.get("session_id"), str) else None
    while True:
        worker.join(POLL_SECONDS)
        if not worker.is_alive():
            break
        now = time.monotonic()
        if now - last_note >= STILL_WAITING_SECONDS:
            last_note = now
            _say(ctx, f"… still waiting for the turn ({int((now - started) // 60)} min; Ctrl-C stops waiting)")
        if not polling or now < backoff_until:
            continue
        try:
            questions = _pending(client, session_id)
        except _PollRefused as refused:
            status = refused.args[0]
            if status == 429:
                _say(ctx, "the hub is rate-limiting this terminal; questions are checked again in 10 s")
                backoff_until = now + 10.0
            else:
                _say(ctx, f"this terminal cannot read the turn's questions (HTTP {status}); "
                          "they will wait until they time out")
                polling = False
            continue
        if questions is None:
            polling = False  # an older hub without the pending routes
            continue
        for question in questions:
            prompt_id = str(question.get("id", ""))
            if not prompt_id or prompt_id in seen:
                continue
            seen.add(prompt_id)
            if question.get("kind") == "secret":
                _answer_secret(ctx, client, question, reader, session_id)
            else:
                _answer_clarify(ctx, client, question, session_id)
    if "error" in box:
        raise box["error"]
    return box.get("reply")


def _payload_summary(payload: dict) -> list[str]:
    for key in ("command", "cmd", "argv", "path", "url"):
        if key in payload:
            value = payload[key]
            shown = " ".join(str(v) for v in value) if isinstance(value, list) else value
            return [f"{key}:", GUTTER + _bounded(card_safe(shown), 600)]
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return ["payload:", GUTTER + _bounded(card_safe(text), 600)] if payload else []


def render_card(ctx, task: dict) -> None:
    """One approval card. Nerva's own words at column 0; hub and model text card-safe."""
    flag = "reversible" if task.get("reversible") else "IRREVERSIBLE"
    tier = card_safe(task.get("tier_name") or task.get("risk_tier", "?"))[:20]
    _say(ctx)
    _say(ctx, f"! approval #{card_safe(task.get('id', '?'))[:20]}  tier {tier}  {flag}  "
              f"kind {card_safe(task.get('kind', '?'))[:80]}")
    _say(ctx, "title:")
    _say(ctx, GUTTER + _bounded(card_safe(task.get("title", "")), 400))
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    for line in _payload_summary(payload):
        _say(ctx, line)
    origin = card_safe(task.get("origin", ""))[:40]
    if origin:
        tainted = origin in {"inbound", "recall:untrusted"} or "untrusted" in origin
        _say(ctx, f"origin: {origin}" + ("  (asked by a turn that read untrusted content)" if tainted else ""))
    mode = task.get("approval_mode")
    if isinstance(mode, dict) and mode.get("mode"):
        _say(ctx, f"approval mode: {card_safe(mode.get('mode'))[:20]}")
    if task.get("consent_offer"):
        _say(ctx, "a reusable consent is offered for this card: decide it with `nerva approvals consent`")
    rollback = task.get("rollback")
    if isinstance(rollback, dict) and rollback.get("description"):
        _say(ctx, "rollback:")
        _say(ctx, GUTTER + _bounded(card_safe(rollback.get("description")), 300))


def decide_queued(ctx, pending_ids: list[Any]) -> dict[int, str]:
    """Show each approval card this turn queued and decide it here, one at a time."""
    ids = [i for i in pending_ids if type(i) is int and i > 0]
    if not ids:
        return {}
    client = ctx.client()
    try:
        listing = client.get("/autonomy/approvals")
    except HubError as exc:
        if exc.status in (401, 403):
            _say(ctx, "approvals need the owner's admin credential; they stay queued — "
                      "the owner decides them with `nerva approvals` or the HUD")
        return {}
    cards = {t.get("id"): t for t in ((listing or {}).get("pending") or []) if isinstance(t, dict)}
    decided: dict[int, str] = {}
    actions = {"a": "accept", "accept": "accept", "r": "reject", "reject": "reject",
               "d": "defer", "defer": "defer"}
    for task_id in ids:
        task = cards.get(task_id)
        if task is None:
            continue
        render_card(ctx, task)
        choice = None
        for _ in range(_MAX_ATTEMPTS):
            text = _readline(ctx, "[a]ccept, [r]eject, [d]efer, or Enter to leave it queued> ")
            if text is None or not text.strip():
                break
            choice = actions.get(text.strip().casefold())
            if choice is not None:
                break
            _say(ctx, "type a, r or d")
        if choice is None:
            _say(ctx, f"#{task_id} stays queued — `nerva approvals`")
            continue
        status, reply = _post(client, f"/autonomy/tasks/{task_id}/decision", {"action": choice})
        if status == 200:
            state = (reply or {}).get("task", {}).get("status", "done") if isinstance(reply, dict) else "done"
            _say(ctx, f"#{task_id} {choice}ed → {card_safe(state)[:40]}")
            decided[task_id] = choice
        elif status in (401, 403):
            _say(ctx, f"#{task_id} not decided: only the owner can; it stays queued")
        else:
            _say(ctx, f"#{task_id} not decided (HTTP {status}); it stays queued")
    return decided

#: The earlier private name, kept for callers that used it.
_render_card = render_card
