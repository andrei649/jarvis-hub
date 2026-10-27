"""
webhooks.py — H10.8 Inbound Webhook Triggers · H16.4 Signed ambient sources.

A token-authenticated inbound trigger: ``POST /api/webhooks/{id}`` activates a
pre-configured agent (or workflow) with the request payload as input. External
systems (n8n, GitHub, cron services) can poke a Jarvis agent without holding any
Jarvis credentials beyond a per-webhook token.

H16.4 adds **signed sources**: a webhook can be created with ``signed=True``,
which provisions an HMAC signing secret. Inbound requests must then carry an
``X-Signature-256: sha256=<hmac>`` header computed over the raw body — a
cryptographically attested source (GitHub/Stripe-style), rather than a bearer
token that travels in the URL.

H153 gives a hook what a Hermes subscription carries: an event list (a delivery
whose event is not on it is skipped, never run) and a prompt template that decides
what the agent reads. ``delivery_event`` and ``render_prompt`` are the two halves.

The H153 review added the rest: where a delivery goes (``deliver``: the log, or one of
the owner's own channels that something receives; ``deliver_only`` skips the agent), a
description, :class:`ReceiverSwitch`, which reads the platform switch so that it fails
closed, and :class:`PushLimit`, which caps how often one hook may push.

H039 closes the Hermes row: a declarative **payload filter** (``filter``: ``{path, op,
value}`` rules over the JSON payload, all of which must hold; ``filter_verdict``) in place
of Hermes' ``--script`` transform, which ran owner code over attacker-controlled text and
was deliberately not copied; and a **test delivery** (``WebhookStore.sample_delivery``):
a sample for the hook's event, signed exactly as a sender must, that the route runs
through the receive path dry.

File-backed store (JSON under ``memory_logs/webhooks.json``), pure-Python and
offline-testable. Tokens/signatures are compared with constant-time checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional, Union

from agents.core.paths import data_path

from .persistence import JsonStore

logger = logging.getLogger("jarvis.webhooks")

DEFAULT_PATH = data_path("webhooks.json")

# H153 — where a delivery names its event: the sender's header first (GitHub,
# GitLab, Bitbucket, then two generic spellings), else the payload's own field.
EVENT_HEADERS = ("x-github-event", "x-gitlab-event", "x-event-key", "x-event-type", "x-webhook-event")
EVENT_FIELDS = ("event", "type")
MAX_EVENTS = 32
MAX_EVENT_NAME = 64
MAX_PROMPT = 2_000
MAX_FIELD = 4_000        # one placeholder's value
MAX_RENDERED = 16_000    # the whole rendered prompt
MAX_DELIVERED_EVENT = 256   # an event name a delivery carries, read (never cut to match)
MAX_DESCRIPTION = 500
_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)\}")

# H153 review — where a delivery goes (Hermes' "Deliver to"). The log keeps the reply in
# the sender's response and the session; every other destination is one of the owner's
# own direct-send channels that something receives, reached through the audited
# send_to_target. A name is matched exactly: "Telegram" is not a destination.
DELIVER_LOG = "log"
#: The owner's channels a delivery can reach. ``web`` is a direct-send channel too, but
#: nothing in the hub connects a client to it, so a push there would never arrive.
DELIVER_CHANNELS: tuple[str, ...] = ("telegram", "voice", "ntfy")
DELIVER_CHOICES: tuple[str, ...] = (DELIVER_LOG, *DELIVER_CHANNELS)
#: The channels that reach the owner's pocket or ears (all of them): quiet hours hold them.
PUSH_CHANNELS = frozenset(DELIVER_CHANNELS)
#: Destinations a Hermes subscription (or an earlier build) offers that a hook refuses, and why.
REFUSED_DESTINATIONS = {
    "email": "email is never an outbound side effect of an inbound delivery "
             "(the rule ChannelManager.send keeps)",
    "github_comment": "a GitHub comment writes to someone else's system: the hook's agent "
                      "proposes it through governed write-back, one approval each",
    "discord": "Discord is a reply-only transport here, with no home channel to address",
    "slack": "Slack is a reply-only transport here, with no home channel to address",
    "web": "the HUD has no receiver for a pushed message yet (nothing connects a client to "
           "the web channel), so a delivery there would never arrive; with log the reply "
           "stays in the hook's session",
}
DELIVER_ONLY_NEEDS_A_CHANNEL = ("deliver only needs a channel: with log the sender's text "
                                "would go nowhere")


def destination_problem(value) -> str:
    """"" when *value* is a destination a hook may deliver to, else why not."""
    if isinstance(value, str) and value in DELIVER_CHOICES:
        return ""
    name = value.strip().lower() if isinstance(value, str) else ""
    reason = REFUSED_DESTINATIONS.get(name)
    if reason:
        return f"deliver={name} is not offered: {reason}"
    return f"deliver is one of {', '.join(DELIVER_CHOICES)}"


def delivery_problem(deliver, deliver_only) -> str:
    """"" when a hook may keep this pair, else why not: deliver-only runs no turn, so
    with the log as its destination the text would be kept nowhere."""
    return DELIVER_ONLY_NEEDS_A_CHANNEL if deliver_only is True and deliver == DELIVER_LOG else ""


def compute_signature(secret: str, body: Union[bytes, str]) -> str:
    """HMAC-SHA256 of *body* under *secret*, as ``sha256=<hexdigest>``."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _event_name(value, limit: int = MAX_DELIVERED_EVENT) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch if ch.isprintable() else " " for ch in value[:limit * 4]).strip()[:limit]


def delivery_event(headers, payload) -> str:
    """The event a delivery names (H153): the sender's header, else the payload's
    ``event`` or ``type`` string; "" when it names none. Printable and bounded, but never
    cut to the subscription limit: a name longer than any subscription matches none."""
    for name in EVENT_HEADERS:
        found = _event_name(headers.get(name)) if headers is not None else ""
        if found:
            return found
    if isinstance(payload, dict):
        for key in EVENT_FIELDS:
            found = _event_name(payload.get(key))
            if found:
                return found
    return ""


def normalize_events(events) -> list[str]:
    """An event list as stored: stripped, and each name once whatever its ASCII case
    (the first spelling is kept)."""
    out: list[str] = []
    seen: set[str] = set()
    for item in events or []:
        name = str(item).strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def event_subscribed(events: list[str], event: str) -> bool:
    """Whether *event* is on the list; names match ignoring case (``str.lower``, not
    Unicode case folding, so "STRAßE" is not "strasse")."""
    wanted = event.lower()
    return any(name.lower() == wanted for name in events)


def _encode_capped(node, limit: int) -> str:
    """*node* as the template shows it — a string as is, anything else as JSON — cut at
    *limit*. The JSON is produced piece by piece and the encoder stops once *limit* is
    reached, so a megabyte-sized subtree costs what the cap shows, not what it holds."""
    if isinstance(node, str):
        return node[:limit]
    out: list[str] = []
    size = 0
    for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(node):
        out.append(chunk)
        size += len(chunk)
        if size >= limit:
            break
    return "".join(out)[:limit]


def _read_path(payload, event: str, path: str) -> tuple[bool, object]:
    """``(found, value)`` for a template or filter path: ``event`` is the delivery's
    event, ``payload`` (alone, or as a prefix) the whole body, and ``a.b.0`` reads the
    JSON payload by key and list index. Nothing else is read: no attribute, and a path
    that leads nowhere is ``(False, None)``."""
    if path == "event":
        return True, event
    node = payload
    parts = path.split(".")
    if parts[0] == "payload":
        parts = parts[1:]
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False, None
    return True, node


def render_prompt(template: str, payload, event: str) -> str:
    """Fill a hook's prompt template (H153). ``{a.b.0}`` reads the JSON payload by
    key and list index, ``{event}`` is the delivery's event and ``{payload}`` the
    whole body; ``{payload.a.b}`` reads the payload too, which reaches a key the
    template reserves (a payload's own ``event``). Nothing else is read: no attribute,
    format spec or conversion, and a value that is missing is empty. A string is used
    as is and anything else as JSON. There is no escape for a literal ``{name}``.

    The work is bounded by the caps, not only the output: each path is read once per
    render, a value is encoded only as far as :data:`MAX_FIELD`, and substitution
    stops once the text reaches :data:`MAX_RENDERED`."""
    cache: dict[str, str] = {}

    def value(path: str) -> str:
        if path in cache:
            return cache[path]
        _found, node = _read_path(payload, event, path)
        text = "" if node is None else _encode_capped(node, MAX_FIELD)
        cache[path] = text
        return text

    out: list[str] = []
    size = 0
    last = 0
    for match in _PLACEHOLDER.finditer(template):
        literal = template[last:match.start()]
        out.append(literal)
        size += len(literal)
        last = match.end()
        if size >= MAX_RENDERED:
            break
        text = value(match.group(1))
        out.append(text)
        size += len(text)
    else:
        out.append(template[last:])
    return "".join(out)[:MAX_RENDERED]


def extract_input(payload) -> str:
    """Derive the agent input text from an arbitrary JSON payload."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("text", "message", "prompt", "input", "body"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)


# H039 — the payload filter. Hermes' ``--script`` ran an owner-supplied transform over
# the inbound payload, which is attacker-controlled text; it was not copied. A hook gets
# a list of declarative rules instead, all of which must hold (AND) for a delivery to go
# on; a rule reads one path of the payload (as a template placeholder does) and compares
# it. There is deliberately no regex op: a pattern over attacker-controlled text can be made
# to backtrack for as long as the sender likes (an alternation repeated in sequence doubles
# the work per group), and the filter runs on the event loop before anything is
# authenticated twice. Every op here is a comparison, a substring or prefix/suffix test, a
# membership test or a one-``*`` glob, each linear in what it reads, with no backtracking.
# A rule stored by the first build with ``op: matches`` is no longer valid, so the hook's
# filter reads as unreadable and filters every delivery (fail closed) until it is rewritten.
FILTER_OPS: tuple[str, ...] = ("eq", "ne", "contains", "startswith", "endswith", "glob", "in", "exists", "missing")
MAX_FILTER_RULES = 16
MAX_FILTER_PATH = 128
MAX_FILTER_VALUE = 256      # a rule's text value, or one member of an ``in`` list
MAX_FILTER_IN = 32          # members of an ``in`` list
_RULE_PATH = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")
_SCALARS = (str, int, float, bool, type(None))


def _scalar_ok(value) -> bool:
    return isinstance(value, _SCALARS) and (not isinstance(value, str) or len(value) <= MAX_FILTER_VALUE)


def rule_problem(rule) -> str:
    """"" when *rule* is one a hook may keep, else why not."""
    if not isinstance(rule, dict):
        return "a rule is an object with path, op and value"
    extra = sorted(set(rule) - {"path", "op", "value"})
    if extra:
        return f"unknown field {extra[0]!r} (a rule has path, op and value)"
    path = rule.get("path")
    if not isinstance(path, str) or len(path) > MAX_FILTER_PATH or not _RULE_PATH.match(path):
        return f"path is a dotted key path of 1 to {MAX_FILTER_PATH} characters, such as repository.full_name or commits.0.message"
    op = rule.get("op")
    if op not in FILTER_OPS:
        return f"op is one of {', '.join(FILTER_OPS)}"
    value = rule.get("value")
    if op in ("exists", "missing"):
        return f"{op} takes no value" if value is not None else ""
    if "value" not in rule:
        return f"{op} needs a value"
    if op in ("eq", "ne"):
        if not _scalar_ok(value):
            return f"value is text of at most {MAX_FILTER_VALUE} characters, a number, true, false or null"
    elif op == "contains":
        if not isinstance(value, str) or not value or len(value) > MAX_FILTER_VALUE:
            return f"value is text of 1 to {MAX_FILTER_VALUE} characters"
    elif op == "in":
        if (not isinstance(value, list) or not value or len(value) > MAX_FILTER_IN
                or not all(_scalar_ok(item) for item in value)):
            return f"value is a list of 1 to {MAX_FILTER_IN} texts, numbers, booleans or nulls"
    elif op in ("startswith", "endswith"):
        if not isinstance(value, str) or not value or len(value) > MAX_FILTER_VALUE:
            return f"value is text of 1 to {MAX_FILTER_VALUE} characters"
    elif op == "glob":
        if not isinstance(value, str) or not value or len(value) > MAX_FILTER_VALUE:
            return f"value is a pattern of 1 to {MAX_FILTER_VALUE} characters"
        if value.count("*") > 1:
            return "a glob has at most one * (it stands for any run of characters)"
    return ""


def filter_problem(rules) -> str:
    """"" when *rules* is a filter a hook may keep, else why not (the first rule at fault)."""
    if not isinstance(rules, list):
        return "filter is a list of rules"
    if len(rules) > MAX_FILTER_RULES:
        return f"filter holds at most {MAX_FILTER_RULES} rules"
    for index, rule in enumerate(rules):
        problem = rule_problem(rule)
        if problem:
            return f"rule {index + 1}: {problem}"
    return ""


def normalize_filter(rules) -> list[dict]:
    """A valid filter as stored: each rule's path, op and (when the op takes one) value."""
    out = []
    for rule in rules or []:
        kept = {"path": rule["path"], "op": rule["op"]}
        if rule["op"] not in ("exists", "missing"):
            kept["value"] = rule["value"]
        out.append(kept)
    return out


def describe_rule(rule: dict) -> str:
    """One rule as the owner wrote it: ``sender.login eq "alice"``, ``commits exists``."""
    text = f"{rule.get('path')} {rule.get('op')}"
    if rule.get("op") not in ("exists", "missing") and "value" in rule:
        text += " " + json.dumps(rule["value"], ensure_ascii=False)
    return _event_name(text, 120)


def _scalar_equal(a, b) -> bool:
    """JSON equality: a bool is never a number, a number is never its text."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def _shown(found: bool, node) -> str:
    if not found:
        return "the field is missing"
    text = json.dumps(node[:81], ensure_ascii=False) if isinstance(node, str) else _encode_capped(node, 80)
    return "the value is " + (text if len(text) <= 80 else text[:80] + "…")


def _rule_holds(rule: dict, payload, event: str) -> tuple[bool, str]:
    """Whether one rule holds over the delivery, and why not when it does not."""
    found, node = _read_path(payload, event, rule["path"])
    op, value = rule["op"], rule.get("value")
    if op == "exists":
        return found, "the field is missing"
    if op == "missing":
        return not found, "the field is present"
    if op == "eq":
        return found and _scalar_equal(node, value), _shown(found, node)
    if op == "ne":
        return not found or not _scalar_equal(node, value), _shown(found, node)
    if op == "in":
        return found and any(_scalar_equal(node, item) for item in value), _shown(found, node)
    if op == "contains":
        if isinstance(node, str):
            return value in node, _shown(found, node)
        if isinstance(node, list):
            return any(_scalar_equal(item, value) for item in node), _shown(found, node)
        if isinstance(node, dict):
            return value in node, _shown(found, node)
        return False, _shown(found, node)
    # startswith, endswith and glob read the field's text: a string as is, a number as its
    # JSON, anything else never (a list or object has no text to compare).
    if not found:
        return False, _shown(found, node)
    if isinstance(node, str):
        subject = node
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        subject = json.dumps(node)
    else:
        return False, _shown(found, node)
    return _text_test(op, value, subject), _shown(found, node)


def _text_test(op: str, value: str, subject: str) -> bool:
    """startswith / endswith / glob over *subject*, in time linear in the two lengths: a
    glob holds at most one ``*``, so it is a prefix and a suffix that must not overlap."""
    if op == "startswith":
        return subject.startswith(value)
    if op == "endswith":
        return subject.endswith(value)
    head, star, tail = value.partition("*")
    if not star:
        return subject == head
    return len(subject) >= len(head) + len(tail) and subject.startswith(head) and subject.endswith(tail)


def filter_verdict(rules: list[dict], payload, event: str) -> str:
    """"" when every rule holds over the delivery (an empty filter always does), else
    which rule turned it away and why: ``rule 2 (ref eq "refs/heads/main"): the value is
    "refs/heads/dev"``. Rules are checked in order and the first that fails answers."""
    for index, rule in enumerate(rules):
        holds, why = _rule_holds(rule, payload, event)
        if not holds:
            return f"rule {index + 1} ({describe_rule(rule)}): {why}"
    return ""


RECEIVER_TTL = 1.0   # seconds a state read from the store is used without re-reading
#: Seconds a caller with nothing known waits for the read that is running (the first one
#: after a start). A burst that arrives while it runs waits for its answer instead of
#: being refused (H153 fourth review); a read slower than this still refuses, closed.
#: At most this many callers wait for a receiver's first read at a time; the rest are
#: refused, closed, at once, so a burst on a slow fresh receiver cannot park every worker
#: thread of the default executor (review-H153e MINOR-2). The wait comes before any
#: authentication, so the waiters can be anyone.
RECEIVER_FIRST_READ_WAITERS = 4
RECEIVER_FIRST_READ_WAIT = 2.0


class ReceiverSwitch:
    """H153 review — the platform switch (setting ``webhooks.receiver_enabled``), read so
    that it fails closed.

    ``settings_db.get_value`` turns every store error into the default, which for this
    on-by-default switch meant a receiver the owner had switched off came back on when
    the store could not be read. Here:

    - only a literal true is on; a row that is missing is the declared default (on);
    - a store that cannot be read leaves the last state read or written in force, and
      a receiver never read then is ``None``: the trigger refuses it with its own reason;
    - a state is used for :data:`RECEIVER_TTL` before the store is read again, so a
      flood costs one read a second; a write in this process
      (``settings_db.put_category``, the settings route) is seen at once, and one from
      another process (``nerva config set``) within the TTL;
    - the store is read by one caller at a time: while a read runs (a locked store takes
      SQLite's busy timeout), every other caller gets the last state at once instead of
      reading too, so a burst of deliveries cannot hold every worker thread; a caller
      with no state known yet (the first read after a start) waits for that read, at
      most :attr:`first_read_wait` seconds, and is refused, closed, after that; at most
      :data:`RECEIVER_FIRST_READ_WAITERS` threads wait at once, and any other is refused,
      closed, at once; :meth:`astate`, which the router uses, waits on the event loop and
      holds no thread, so a burst of deliveries at start waits for the read and is served;
    - a write, a reset or another store wakes the waiters: the state is known (or not
      theirs to wait for) without the read;
    - a read that a write, a reset or another store overtook while it ran is dropped;
    - :meth:`state` blocks on SQLite: call it off the event loop, or await :meth:`astate`.
    """

    def __init__(self, ttl: float = RECEIVER_TTL, clock=time.monotonic) -> None:
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._generation = 0
        self._reader: Optional[object] = None
        self._landed = threading.Event()
        self._waiting = 0
        self.first_read_wait = RECEIVER_FIRST_READ_WAIT
        self.reset()

    def reset(self) -> None:
        """Forget everything; a read still running when this lands is dropped."""
        with self._lock:
            self._known: Optional[bool] = None
            self._fresh_until = float("-inf")
            self._generation += 1
            self._reader = None
            self._source = ""
            self._landed.set()                    # a waiter has nothing left to wait for

    def expire(self) -> None:
        """The next :meth:`state` reads the store; the last state stays the fallback, and a
        read already running (which may predate what expired it) is dropped."""
        with self._lock:
            self._fresh_until = float("-inf")
            self._generation += 1

    def written(self, value) -> None:
        """A write in this process: its value is the state, at once."""
        with self._lock:
            self._known = value is True
            self._generation += 1
            self._fresh_until = self._clock() + self._ttl
            self._source = self._store_path()
            self._landed.set()                    # the state is known: wake the waiters

    @staticmethod
    def _store_path() -> str:
        from agents.core import settings_db

        return str(getattr(settings_db, "DB_PATH", ""))

    def _claim(self, *, count_waiter: bool):
        """What a caller does now, decided under the lock with no I/O: ``("known", state)``,
        ``("wait", event)`` (nothing known, a read is running) or ``("read", ticket)`` (this
        caller reads the store). A sync waiter past :data:`RECEIVER_FIRST_READ_WAITERS` is
        answered ``("known", None)``: refused, closed, at once."""
        source = self._store_path()
        with self._lock:
            if source != self._source:            # another settings store: nothing known
                self._known, self._fresh_until, self._source = None, float("-inf"), source
                self._generation += 1             # a read of the old store must not land
                self._landed.set()                # nor keep anyone waiting on it
            if self._clock() < self._fresh_until:
                return "known", self._known
            if self._reader is not None:
                if self._known is not None:
                    return "known", self._known   # the last state, at once
                if count_waiter:
                    if self._waiting >= RECEIVER_FIRST_READ_WAITERS:
                        return "known", None      # enough threads wait already: closed
                    self._waiting += 1
                return "wait", self._landed       # nothing known: wait for the running read
            reader = self._reader = object()
            done = self._landed = threading.Event()
            return "read", (self._generation, reader, done)

    def _run_read(self, ticket) -> Optional[bool]:
        from agents.core import settings_db

        generation, reader, done = ticket
        try:
            return self._read(settings_db, generation)
        finally:
            with self._lock:
                if self._reader is reader:
                    self._reader = None
            done.set()

    def state(self) -> Optional[bool]:
        """True on, False off, None never read and unreadable now (or its first read did
        not land within :attr:`first_read_wait`). Blocks: call it off the event loop, or
        use :meth:`astate`."""
        kind, value = self._claim(count_waiter=True)
        if kind == "known":
            return value
        if kind == "read":
            return self._run_read(value)
        try:
            value.wait(self.first_read_wait)
        finally:
            with self._lock:
                self._waiting -= 1
        with self._lock:
            return self._known

    async def astate(self) -> Optional[bool]:
        """:meth:`state` for the event loop. The claim is made on the loop, so a burst that
        arrives together has one reader, and a caller waiting for the first read waits on
        the loop, holding no worker thread (review-H153e MINOR-2): only the read itself runs
        off it."""
        import asyncio

        kind, value = self._claim(count_waiter=False)
        if kind == "known":
            return value
        if kind == "read":
            return await asyncio.to_thread(self._run_read, value)
        deadline = time.monotonic() + self.first_read_wait
        while not value.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        with self._lock:
            return self._known

    def _read(self, settings_db, generation: int) -> Optional[bool]:
        try:
            found, value = settings_db.read_setting("webhooks", "receiver_enabled")
        except settings_db.SettingsUnreadable as exc:
            with self._lock:
                known = self._known
                if generation == self._generation:
                    self._fresh_until = self._clock() + self._ttl   # one retry a second
            logger.warning("webhook receiver: the settings store cannot be read (%s); %s", exc,
                           "keeping it off" if known is False else "keeping it on" if known else
                           "refusing deliveries until it can be read")
            return known
        with self._lock:
            if generation == self._generation:    # nothing overtook this read while it ran
                self._known = (value is True) if found else True
                self._fresh_until = self._clock() + self._ttl
            return self._known


#: The process-wide receiver state the trigger reads.
RECEIVER = ReceiverSwitch()


PUSH_LIMIT = 30          # pushes one hook may make in PUSH_WINDOW seconds
PUSH_WINDOW = 3_600.0


class PushLimit:
    """At most *limit* pushes per hook in any *window* seconds (H153 review).

    A hook's sender decides how often it posts, and a push lands on the owner's phone
    or speaker, so each hook gets its own allowance; a push over it is recorded on the
    hook with the reason, never sent. The count is per process and starts empty at
    boot; every attempt counts, whether or not the channel took it."""

    def __init__(self, limit: int = PUSH_LIMIT, window: float = PUSH_WINDOW, clock=time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._lock = threading.Lock()
        self._sent: dict[str, deque] = {}

    def allow(self, hook_id: str) -> bool:
        """Count one push for *hook_id*, or say no when its allowance is spent."""
        now = self._clock()
        with self._lock:
            sent = self._sent.setdefault(str(hook_id), deque())
            while sent and now - sent[0] >= self.window:
                sent.popleft()
            if len(sent) >= self.limit:
                return False
            sent.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._sent.clear()


#: The process-wide push allowance the trigger spends.
PUSHES = PushLimit()


def _on_settings_change(category, values) -> None:
    if category is None:                          # a reseed: read the store again
        RECEIVER.expire()
    elif category == "webhooks" and isinstance(values, dict) and "receiver_enabled" in values:
        RECEIVER.written(values["receiver_enabled"])


def _listen_for_settings_changes() -> None:
    from agents.core import settings_db

    settings_db.on_change(_on_settings_change)


_listen_for_settings_changes()


class WebhookStore(JsonStore):
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return self._hooks

    def _deserialize(self, raw) -> None:
        self._hooks = raw if isinstance(raw, dict) else {}

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create(self, target: str, target_type: str = "agent", name: str = "",
               signed: bool = False, events=None, prompt: str = "", *,
               deliver: str = DELIVER_LOG, deliver_only: bool = False, description: str = "",
               filter=None) -> dict:
        """Create a webhook; returns the full record incl. the (only) token.

        When *signed*, also provisions an HMAC ``signing_secret`` (returned once)
        and requires a valid ``X-Signature-256`` header on every trigger. *filter*
        (H039) is a list of rules a delivery must satisfy; None or empty is none.
        """
        if target_type not in ("agent", "workflow"):
            raise ValueError(f"invalid target_type: {target_type}")
        problem = (destination_problem(deliver) or delivery_problem(deliver, deliver_only)
                   or (filter_problem(filter) if filter is not None else ""))
        if problem:
            raise ValueError(problem)
        hook_id = secrets.token_urlsafe(8).replace("-", "_")  # a CLI positional: never "-h…"
        token = secrets.token_urlsafe(24)
        record = {
            "id": hook_id,
            "token": token,
            "target": target,
            "target_type": target_type,
            "name": name or target,
            "signed": bool(signed),
            "signing_secret": secrets.token_urlsafe(32) if signed else None,
            "enabled": True,
            "events": normalize_events(events),
            "prompt": str(prompt or ""),
            "deliver": deliver,
            "deliver_only": deliver_only is True,
            "description": str(description or "")[:MAX_DESCRIPTION],
            "filter": normalize_filter(filter),
            "created_at": time.time(),
            "calls": 0,
            "skipped": 0,
            "filtered": 0,
            "last_called": None,
        }
        self._hooks[hook_id] = record
        try:
            self._save()
        except Exception:
            del self._hooks[hook_id]  # memory never runs ahead of the file
            raise
        return dict(record)

    def get(self, hook_id: str) -> Optional[dict]:
        rec = self._hooks.get(hook_id)
        return dict(rec) if rec else None

    def delete(self, hook_id: str) -> bool:
        if hook_id in self._hooks:
            rec = self._hooks.pop(hook_id)
            try:
                self._save()
            except Exception:
                self._hooks[hook_id] = rec  # memory never runs ahead of the file
                raise
            return True
        return False

    def set_enabled(self, hook_id: str, enabled: bool) -> Optional[dict]:
        """Switch a hook on or off (H153); the masked record, or None when unknown.

        A disabled hook keeps its token and secret, so switching it back on needs no
        change at the sender. The trigger refuses it after authentication.
        """
        return self.update(hook_id, enabled=enabled)

    _EDITABLE = ("enabled", "events", "prompt", "deliver", "deliver_only", "description", "filter")

    def update(self, hook_id: str, *, enabled: Optional[bool] = None, events=None,
               prompt: Optional[str] = None, deliver: Optional[str] = None,
               deliver_only: Optional[bool] = None, description: Optional[str] = None,
               filter=None) -> Optional[dict]:
        """Change a hook's switch, event list, prompt template, destination,
        description or payload filter (H153, H039): the masked record, or None when
        unknown. A save that fails undoes the change in memory. A change to where a
        delivery goes is refused when it would leave deliver-only on the log; a change
        to anything else is not (a record from before that rule can still be switched
        off)."""
        rec = self._hooks.get(hook_id)
        if rec is None:
            return None
        if deliver is not None:
            problem = destination_problem(deliver)
            if problem:
                raise ValueError(problem)
        if filter is not None:
            problem = filter_problem(filter)
            if problem:
                raise ValueError(problem)
        if deliver is not None or deliver_only is not None:
            problem = delivery_problem(deliver if deliver is not None else self.destination(rec),
                                       (deliver_only is True) if deliver_only is not None
                                       else self.delivers_only(rec))
            if problem:
                raise ValueError(problem)
        before = {key: rec[key] for key in self._EDITABLE if key in rec}
        if enabled is not None:
            rec["enabled"] = bool(enabled)
        if events is not None:
            rec["events"] = normalize_events(events)
        if prompt is not None:
            rec["prompt"] = str(prompt)
        if deliver is not None:
            rec["deliver"] = deliver
        if deliver_only is not None:
            rec["deliver_only"] = deliver_only is True
        if description is not None:
            rec["description"] = str(description)[:MAX_DESCRIPTION]
        if filter is not None:
            rec["filter"] = normalize_filter(filter)
        try:
            self._save()
        except Exception:
            for key in self._EDITABLE:  # memory never runs ahead of the file
                if key in before:
                    rec[key] = before[key]
                else:
                    rec.pop(key, None)
            raise
        return self._masked(rec)

    @staticmethod
    def is_enabled(rec: dict) -> bool:
        """A record written before the switch existed is on; otherwise only a literal
        true is (a hand-edited "false", 0 or null reads as off, never as on)."""
        return rec["enabled"] is True if "enabled" in rec else True

    @staticmethod
    def stored_events(rec: dict) -> Optional[list[str]]:
        """A hook's event list: empty (every event) for a record written before the
        field existed, and None when a hand edit left something that is not a list of
        names: null, not a list, or an item that is not text, is blank, holds a comma or
        is too long. The trigger reads None as "skip everything", never as "run
        everything". Other oddities the API would refuse (a control character, more than
        32 names) are kept: they can only narrow what the list matches."""
        if "events" not in rec:
            return []
        events = rec["events"]
        if not isinstance(events, list):
            return None
        for item in events:
            if (not isinstance(item, str) or not item.strip() or "," in item
                    or len(item.strip()) > MAX_EVENT_NAME):
                return None
        return normalize_events(events)

    @staticmethod
    def stored_filter(rec: dict) -> Optional[list[dict]]:
        """A hook's payload filter (H039): empty (no rule) for a record written before
        the field existed, and None when a hand edit left something that is not a valid
        filter. The trigger reads None as "filter everything", never as "no rule"."""
        if "filter" not in rec:
            return []
        rules = rec["filter"]
        return None if filter_problem(rules) else normalize_filter(rules)

    @staticmethod
    def destination(rec: dict) -> str:
        """Where a delivery goes: the log for a record written before the field existed,
        and for a hand edit that names anything the API would refuse."""
        value = rec.get("deliver", DELIVER_LOG)
        return value if isinstance(value, str) and not destination_problem(value) else DELIVER_LOG

    @staticmethod
    def delivers_only(rec: dict) -> bool:
        """Whether a delivery skips the agent: only a literal true does."""
        return rec.get("deliver_only") is True

    def _masked(self, rec: dict) -> dict:
        safe = {k: v for k, v in rec.items() if k not in ("token", "signing_secret")}
        safe["token_hint"] = rec["token"][:4] + "…"
        safe["signed"] = bool(rec.get("signed"))
        safe["enabled"] = self.is_enabled(rec)
        events = self.stored_events(rec)
        safe["events"] = events or []
        if events is None:
            safe["events_unreadable"] = True
        safe["prompt"] = rec["prompt"] if isinstance(rec.get("prompt"), str) else ""
        safe["skipped"] = rec["skipped"] if isinstance(rec.get("skipped"), int) else 0
        safe["deliver"] = self.destination(rec)
        safe["deliver_only"] = self.delivers_only(rec)
        description = rec.get("description")
        safe["description"] = description[:MAX_DESCRIPTION] if isinstance(description, str) else ""
        rules = self.stored_filter(rec)
        safe["filter"] = rules or []
        if rules is None:
            safe["filter_unreadable"] = True
        safe["filtered"] = rec["filtered"] if isinstance(rec.get("filtered"), int) else 0
        for key in ("last_delivery", "last_test"):
            if not isinstance(rec.get(key), dict):
                safe.pop(key, None)
        return safe

    def list(self) -> list[dict]:
        """List webhooks with the token masked (never expose it after creation)."""
        out = [self._masked(rec) for rec in self._hooks.values()]
        return sorted(out, key=lambda r: r["created_at"], reverse=True)

    # ── auth + accounting ────────────────────────────────────────────────────

    def verify(self, hook_id: str, token: str) -> bool:
        rec = self._hooks.get(hook_id)
        if not rec or not token:
            return False
        return hmac.compare_digest(rec["token"], token)

    def verify_signature(self, hook_id: str, raw_body: Union[bytes, str], signature: str) -> bool:
        """H16.4 — constant-time HMAC check of a signed source's request body."""
        rec = self._hooks.get(hook_id)
        if not rec or not rec.get("signing_secret") or not signature:
            return False
        expected = compute_signature(rec["signing_secret"], raw_body)
        provided = signature.strip()
        if "=" not in provided:                       # allow a bare hexdigest
            provided = f"sha256={provided}"
        return hmac.compare_digest(expected, provided)

    def mark_called(self, hook_id: str) -> None:
        rec = self._hooks.get(hook_id)
        if rec:
            rec["calls"] += 1
            rec["last_called"] = time.time()
            self._save()

    def mark_skipped(self, hook_id: str, event: str) -> None:
        """A delivery the event list turned away (H153): counted apart from calls,
        with the event it named, so the owner can see what a sender posts."""
        rec = self._hooks.get(hook_id)
        if rec:
            rec["skipped"] = (rec["skipped"] if isinstance(rec.get("skipped"), int) else 0) + 1
            rec["last_skipped"] = time.time()
            rec["last_skipped_event"] = _event_name(event, MAX_EVENT_NAME)
            self._save()

    def mark_delivered(self, hook_id: str, channel: str, ok: bool, reason: str = "") -> None:
        """Where the last delivery went and whether it arrived (H153 review)."""
        rec = self._hooks.get(hook_id)
        if rec:
            rec["last_delivery"] = {"at": time.time(), "channel": str(channel), "ok": bool(ok),
                                    "reason": _event_name(reason, 300)}
            self._save()

    def mark_filtered(self, hook_id: str, reason: str) -> None:
        """A delivery the payload filter turned away (H039): counted apart from calls and
        skips, with the rule that turned it away, so the owner can see what a rule does."""
        rec = self._hooks.get(hook_id)
        if rec:
            rec["filtered"] = (rec["filtered"] if isinstance(rec.get("filtered"), int) else 0) + 1
            rec["last_filtered"] = time.time()
            rec["last_filtered_rule"] = _event_name(reason, 300)
            self._save()

    def mark_tested(self, hook_id: str, outcome: str, reason: str = "") -> None:
        """What the last test delivery (H039) found: never a call, never a delivery."""
        rec = self._hooks.get(hook_id)
        if rec:
            rec["last_test"] = {"at": time.time(), "outcome": _event_name(outcome, 32),
                                "reason": _event_name(reason, 300)}
            self._save()

    # ── the test delivery ────────────────────────────────────────────────────

    def sample_delivery(self, hook_id: str, event: Optional[str] = None, payload=None) -> Optional[dict]:
        """A delivery a sender could post to the hook (H039), built and signed here: the
        event (the one given, else the hook's first subscribed one, else ``test``), the
        payload (the one given, else a small sample that names the hook and says it is a
        test), the raw body as it is signed, and the headers a sender must set: the event
        header and the hook's own credential, computed the way a sender computes it (the
        HMAC of the raw body under the signing secret, or the token). None when the hook
        is unknown. The caller verifies it with :meth:`verify_signature` or :meth:`verify`,
        the receiver's own checks, so a test proves the sender's recipe, not a shortcut."""
        rec = self._hooks.get(hook_id)
        if rec is None:
            return None
        events = self.stored_events(rec) or []
        name = _event_name(event, MAX_EVENT_NAME) if event else (events[0] if events else "test")
        if payload is None:
            label = str(rec.get("name") or rec.get("target") or hook_id)
            payload = {
                "event": name,
                "test": True,
                "text": f"Test delivery from Nerva for webhook {label}",
                "webhook": {"id": hook_id, "name": label},
                "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"content-type": "application/json", "x-webhook-event": name, "x-nerva-test": "1"}
        if rec.get("signed") and rec.get("signing_secret"):
            headers["x-signature-256"] = compute_signature(rec["signing_secret"], raw)
        else:
            headers["x-webhook-token"] = rec["token"]
        return {"event": name, "payload": payload, "raw": raw, "headers": headers}
