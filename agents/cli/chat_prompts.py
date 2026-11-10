"""Mid-turn prompts for `nerva chat` (H226): clarify questions, secret entry, approvals.

Nothing here is a second mechanism. While `POST /chat` runs, the turn's clarify and
secret prompts wait in the hub's pending-input runtime, bound to the credential that
started the turn; this module finds them with ``GET /chat/pending`` and answers them
with ``POST /chat/pending/{id}/answer``, the routes the HUD's non-streaming turn uses.

* A clarify answer is the owner's typed text. The hub hands it to the turn through the
  clarify tool, which is registered ``untrusted_output``: the loop fences it as data and
  raises the turn's taint, exactly as for a HUD answer.
* A secret is read with ``getpass`` (never echoed), sent only to the admin-guarded
  secret broker route (``POST /api/secrets/broker``, the HUD's Secrets panel route),
  and never to the turn: the pending prompt is answered with the marker ``"stored"``,
  which the hub accepts only once the broker holds the name. The value is never
  printed, logged, written to the usage receipt or put in the conversation.
* Confirmations and sudo-class commands are approval cards in Nerva: a turn that
  needs one queues it and stops. `nerva chat` shows each card it queued and decides it
  through ``POST /autonomy/tasks/{id}/decision`` (admin-guarded), the route the HUD's
  decision inbox and `nerva approvals` use. There is no local bypass and no batch accept.

Only an interactive terminal is asked: with stdin piped (a script), nothing is read.
"""

from __future__ import annotations

import getpass
import inspect
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from .client import HubError, carries_secrets

#: How often the pending list is read while the turn runs.
POLL_SECONDS = 0.5
#: How long a turn that may wait on the owner is allowed to take: the hub's clarify
#: window is an hour by default, and the turn itself runs on either side of it.
TURN_TIMEOUT_SECONDS = 3 * 3600.0
_MAX_ATTEMPTS = 3
_CANCEL = {"/cancel", "!cancel", "/skip"}


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


def _clean(text: Any, width: int) -> str:
    from .nerva import _plain

    return _plain(text, width)


def _clean_block(text: Any, width: int = 4096) -> str:
    from .nerva import _answer_text

    return _answer_text(text)[:width]


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


def _answer_clarify(ctx, client, question: dict) -> str:
    prompt_id = str(question.get("id", ""))
    choices = [str(c) for c in (question.get("choices") or []) if isinstance(c, str)][:4]
    multi = question.get("multi_select") is True
    _say(ctx)
    _say(ctx, "? " + _clean_block(question.get("question", "")))
    for index, choice in enumerate(choices, 1):
        _say(ctx, f"  {index}. {_clean(choice, 300)}")
    if choices:
        how = ("numbers or labels separated by commas" if multi else "a number or a label")
        _say(ctx, f"  Answer with {how}, or type your own answer. /cancel declines.")
    else:
        _say(ctx, "  Type your answer. /cancel declines.")
    path = f"/chat/pending/{quote(prompt_id, safe='')}/answer"
    for _ in range(_MAX_ATTEMPTS):
        text = _readline(ctx, "answer> ")
        if text is None or text.strip().casefold() in _CANCEL:
            status, _ = _post(client, path, {"cancel": True})
            _say(ctx, "  declined; the turn continues without an answer")
            return "cancelled" if status == 200 else "gone"
        text = text.strip()
        if not text:
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
            _say(ctx, "  this question is no longer waiting (answered elsewhere, or timed out)")
            return "gone"
        if status in (401, 403):
            _say(ctx, "  this terminal's credential cannot answer this question")
            return "refused"
        _say(ctx, "  not accepted; try again")
    status, _ = _post(client, path, {"cancel": True})
    _say(ctx, "  no usable answer; declined")
    return "cancelled"


def _answer_secret(ctx, client, question: dict, read_secret: Callable[[str], str]) -> str:
    prompt_id = str(question.get("id", ""))
    name = _clean(question.get("name", ""), 128)
    path = f"/chat/pending/{quote(prompt_id, safe='')}/answer"
    _say(ctx)
    _say(ctx, f"! The turn asks you to store the secret {name}.")
    reason = _clean_block(question.get("question", ""), 1024).strip()
    if reason:
        _say(ctx, f"  why: {reason}")
    base = getattr(client, "base_url", "")
    if not carries_secrets(str(base)):
        _post(client, path, {"cancel": True})
        _say(ctx, "  declined: the hub is reached over plain http on another machine, so a "
                  "secret is not sent from here — store it on the hub's machine "
                  "(the HUD's Secrets panel), then ask again")
        return "cancelled"
    _say(ctx, "  The value is not shown as you type. It goes only to the hub's secret store; "
              "the conversation sees the name, never the value. An empty line declines.")
    try:
        value = read_secret(f"{name}: ")
    except (EOFError, KeyboardInterrupt, OSError):
        value = ""
    if not value:
        _post(client, path, {"cancel": True})
        _say(ctx, "  declined; nothing was stored")
        return "cancelled"
    try:
        status, _ = _post(client, "/api/secrets/broker", {"name": question.get("name", ""), "value": value})
    finally:
        value = ""  # noqa: F841 — drop the only local reference as soon as it is sent
    if status != 200:
        _post(client, path, {"cancel": True})
        if status in (401, 403):
            _say(ctx, "  not stored: only the owner can store a secret (this terminal has no "
                      "admin credential)")
        else:
            _say(ctx, f"  not stored: the hub refused (HTTP {status})")
        return "refused"
    status, _ = _post(client, path, {"answer": "stored"})
    if status == 200:
        _say(ctx, f"  stored {name}; the turn continues")
        return "answered"
    _say(ctx, f"  stored {name}, but the question was no longer waiting")
    return "gone"


def _pending(client, session_id: str | None) -> list[dict] | None:
    path = "/chat/pending" + (f"?session_id={quote(session_id, safe='')}" if session_id else "")
    try:
        reply = client.get(path)
    except HubError as exc:
        return None if exc.status in (404, 405) else []
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
    session_id = body.get("session_id") if isinstance(body.get("session_id"), str) else None
    while True:
        worker.join(POLL_SECONDS)
        if not worker.is_alive():
            break
        if not polling:
            continue
        questions = _pending(client, session_id)
        if questions is None:
            polling = False  # an older hub without the pending routes
            continue
        for question in questions:
            prompt_id = str(question.get("id", ""))
            if not prompt_id or prompt_id in seen:
                continue
            seen.add(prompt_id)
            if question.get("kind") == "secret":
                _answer_secret(ctx, client, question, reader)
            else:
                _answer_clarify(ctx, client, question)
    if "error" in box:
        raise box["error"]
    return box.get("reply")


def _render_card(ctx, task: dict) -> None:
    flag = "reversible" if task.get("reversible") else "IRREVERSIBLE"
    _say(ctx)
    _say(ctx, f"! approval #{_clean(task.get('id', '?'), 20)}  tier {_clean(task.get('tier_name') or task.get('risk_tier', '?'), 20)}"
              f"  {flag}  {_clean(task.get('kind', '?'), 80)}")
    _say(ctx, f"  {_clean(task.get('title', ''), 400)}")
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    for key in ("command", "cmd", "argv", "path", "url"):
        if key in payload:
            value = payload[key]
            shown = " ".join(str(v) for v in value) if isinstance(value, list) else value
            _say(ctx, f"  {key}: {_clean(shown, 600)}")
            break
    rollback = task.get("rollback")
    if isinstance(rollback, dict) and rollback.get("description"):
        _say(ctx, f"  rollback: {_clean(rollback.get('description'), 300)}")


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
        _render_card(ctx, task)
        choice = None
        for _ in range(_MAX_ATTEMPTS):
            text = _readline(ctx, "  [a]ccept, [r]eject, [d]efer, or Enter to leave it queued> ")
            if text is None or not text.strip():
                break
            choice = actions.get(text.strip().casefold())
            if choice is not None:
                break
            _say(ctx, "  type a, r or d")
        if choice is None:
            _say(ctx, f"  #{task_id} stays queued — `nerva approvals`")
            continue
        status, reply = _post(client, f"/autonomy/tasks/{task_id}/decision", {"action": choice})
        if status == 200:
            state = (reply or {}).get("task", {}).get("status", "done") if isinstance(reply, dict) else "done"
            _say(ctx, f"  #{task_id} {choice}ed → {_clean(state, 40)}")
            decided[task_id] = choice
        elif status in (401, 403):
            _say(ctx, f"  #{task_id} not decided: only the owner can; it stays queued")
        else:
            _say(ctx, f"  #{task_id} not decided (HTTP {status}); it stays queued")
    return decided
