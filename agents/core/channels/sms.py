"""sms.py — SMS as a channel: a Twilio-signed webhook in, approved Twilio REST replies out (H098, G16).

SMS is the channel that still works when nothing else does: no app, no data plan, no
account. It is also the one where every outbound message costs money and reaches a phone
number, so this adapter is stricter than the others on both sides.

**Off by default.** Nothing listens or sends unless ``JARVIS_SMS_ENABLED`` is on and the
Twilio account (``JARVIS_SMS_ACCOUNT_SID``, ``JARVIS_SMS_FROM_NUMBER``) and auth token
(``JARVIS_SMS_AUTH_TOKEN`` — set it in the HUD's Integrations panel, which keeps it in the
encrypted secret store; ``.env`` also works) are configured. Every value is read through
``env_config`` at call time. The webhook answers 404 while SMS is off.

**Inbound** (``POST /api/channels/sms/webhook``, ``routers/channels_sms.py``):

1. the body is capped at 65,536 bytes before it is parsed (``Content-Length`` and the
   bytes actually read are both checked);
2. ``X-Twilio-Signature`` must be present and equal, in constant time, to
   base64(HMAC-SHA1(auth token, URL + every POST parameter name and value, sorted by
   name)) — Twilio's documented algorithm, tried with and without the URL's default port
   (Twilio signs whichever form it was configured with). The URL is
   ``JARVIS_SMS_WEBHOOK_URL`` when set (the public URL behind a proxy), else the request
   URL. Unsigned or mis-signed requests get 403 and nothing else happens;
3. ``AccountSid`` must be this hub's account;
4. a message from this hub's own number is an echo and is dropped;
5. the sender must be the owner's: listed in ``JARVIS_SMS_ALLOWED_NUMBERS`` or explicitly
   paired (``pairing`` status *allowed*). SMS never opens to strangers, even with
   ``JARVIS_CHANNEL_PAIRING=0``. An unknown number is recorded as a pairing request (the
   owner can approve it from the HUD) and is **never answered** — an answer would cost
   money and confirm the number reaches someone;
6. **replay**: Twilio signs no timestamp, so the replay window is the ``MessageSid``. An
   admitted sender's SID is one row of the reliability store's ``seen_ids`` table for 24
   hours (up to 20,000 rows; it survives a restart), and a repeat is answered and dropped.
   Strangers never reach this step, so they cannot evict the owner's ids, and a store that
   cannot be read or written drops the message (fail closed).

The webhook replies with empty TwiML at once; the turn runs in the background. The
sender's number appears in logs only redacted (``+1…4567``).

**Outbound**: there is no direct send. A reply to an inbound SMS is queued by the
orchestrator as a governed ``channel.reply`` task (the same path as Slack, Discord and
ntfy replies) at the **irreversible/money tier (3)**, so it waits in the approval queue
even when the Action Kernel is on; the kernel still applies the kill switch, plan mode
and budgets first. Only the approved task reaches :meth:`SmsChannel.send`, through
``ChannelManager.send_channel_reply`` and G15's delivery ledger, with a ``delivery_key``
of the task id so a retried task never sends twice. At execution the reply must still go
to the exact number that wrote the inbound message, and a per-number hourly cap
(``JARVIS_SMS_REPLY_MAX_PER_HOUR``, 10) applies. A reply is rendered to plain text and
cut to at most :data:`MAX_SEGMENTS` billed segments (GSM-7 153 characters a segment,
UCS-2 67 — the carrier's count, not characters), sent in parts of 1,600 characters.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from ..env_config import env_flag, env_list, env_str
from .base import ChannelAdapter
from .descriptor import ChannelDescriptor

logger = logging.getLogger("jarvis.channels.sms")

CHANNEL_ID = "sms"
ENABLED_ENV = "JARVIS_SMS_ENABLED"
ACCOUNT_SID_ENV = "JARVIS_SMS_ACCOUNT_SID"
AUTH_TOKEN_ENV = "JARVIS_SMS_AUTH_TOKEN"  # nosec B105 — the variable name, not a value
FROM_NUMBER_ENV = "JARVIS_SMS_FROM_NUMBER"
ALLOWED_NUMBERS_ENV = "JARVIS_SMS_ALLOWED_NUMBERS"
WEBHOOK_URL_ENV = "JARVIS_SMS_WEBHOOK_URL"

MAX_BODY_BYTES = 65_536
MAX_MESSAGE_LENGTH = 1_600
MAX_PARTS = 3
#: The most billed SMS segments one reply may cost (GSM-7: 153 characters a segment,
#: UCS-2 — any character outside GSM-7, such as most emoji or diacritics: 67 UTF-16 units).
MAX_SEGMENTS = 10
_GSM7 = frozenset("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  "ÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
_GSM7_EXT = frozenset("^{}\\[~]|€\f")
#: How long a MessageSid is remembered against replay.
REPLAY_WINDOW_S = 24 * 3600
REPLAY_MAX_SIDS = 20_000
_REPLAY_SCOPE = "sms.message_sid"

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
TWILIO_HOST = "api.twilio.com"

_E164 = re.compile(r"\+[1-9][0-9]{6,14}")
_SID = re.compile(r"(SM|MM|SMS)[0-9a-fA-F]{32}")
_ACCOUNT = re.compile(r"AC[0-9a-fA-F]{32}")


def e164(value: object) -> str | None:
    text = str(value or "").strip()
    return text if _E164.fullmatch(text) else None


def sender_id(number: str) -> str:
    """The pairing identity of a number: its digits (what ``parse_sender_allowlist`` keeps)."""
    return number.lstrip("+")


def redact_phone(number: object) -> str:
    digits = re.sub(r"\D", "", str(number or ""))
    if len(digits) < 6:
        return "+…"
    return f"+{digits[:1]}…{digits[-4:]}"


def segments(text: str) -> int:
    """How many billed SMS segments *text* costs as one concatenated message."""
    if all(ch in _GSM7 or ch in _GSM7_EXT for ch in text):
        units = sum(2 if ch in _GSM7_EXT else 1 for ch in text)
        return 1 if units <= 160 else -(-units // 153)
    units = len(text.encode("utf-16-le")) // 2
    return 1 if units <= 70 else -(-units // 67)


def fit_segments(text: str, limit: int = MAX_SEGMENTS) -> str:
    """*text* cut (with a note) so that it costs at most *limit* segments."""
    if segments(text) <= limit:
        return text
    tail = "... (cut: the full reply is in the HUD)"
    lo, hi = 0, len(text)
    while lo < hi:          # the longest prefix that fits with the tail
        mid = (lo + hi + 1) // 2
        if segments(text[:mid] + tail) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + tail


def target_ref(number: object) -> str:
    """What the delivery ledger keeps for a number: a digest, never the number."""
    return "sms-" + hashlib.sha256(str(number or "").encode()).hexdigest()[:16]


# ── configuration ────────────────────────────────────────────────────────────────


def enabled() -> bool:
    return env_flag(ENABLED_ENV)


def account_sid() -> str:
    sid = env_str(ACCOUNT_SID_ENV).strip()
    return sid if _ACCOUNT.fullmatch(sid) else ""


def auth_token() -> str:
    return env_str(AUTH_TOKEN_ENV).strip()


def from_number() -> str | None:
    return e164(env_str(FROM_NUMBER_ENV))


def allowed_numbers() -> frozenset[str]:
    return frozenset(n for n in (e164(v) for v in env_list(ALLOWED_NUMBERS_ENV)) if n)


def missing_config() -> list[str]:
    """The settings SMS cannot run without (names only)."""
    need = []
    if not enabled():
        need.append(ENABLED_ENV)
    if not account_sid():
        need.append(ACCOUNT_SID_ENV)
    if not auth_token():
        need.append(AUTH_TOKEN_ENV)
    if not from_number():
        need.append(FROM_NUMBER_ENV)
    return need


def configured() -> bool:
    return not missing_config()


# ── Twilio's request signature ───────────────────────────────────────────────────


def compute_signature(token: str, url: str, params: dict[str, list[str]]) -> str:
    """base64(HMAC-SHA1(token, url + name1 + value1 + name2 + value2 …)), names sorted,
    repeated values of one name sorted (the twilio-python validator's order)."""
    payload = url
    for name in sorted(params):
        for value in sorted(params[name]):
            payload += name + value
    digest = hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _url_variants(url: str) -> list[str]:
    """The URL as given, with its default port added and without it (Twilio signs the
    form it was configured with; a proxy may add or drop the port)."""
    parts = urlsplit(url)
    default = {"https": 443, "http": 80}.get(parts.scheme)
    variants = [url]
    if default is None or not parts.hostname:
        return variants
    host = parts.hostname
    if ":" in host:   # IPv6 literal
        host = f"[{host}]"
    userinfo = parts.netloc.rsplit("@", 1)[0] + "@" if "@" in parts.netloc else ""
    without = urlunsplit((parts.scheme, userinfo + host, parts.path, parts.query, parts.fragment))
    with_port = urlunsplit((parts.scheme, f"{userinfo}{host}:{parts.port or default}", parts.path,
                            parts.query, parts.fragment))
    for candidate in (without, with_port):
        if candidate not in variants:
            variants.append(candidate)
    return variants


def valid_signature(token: str, url: str, params: dict[str, list[str]], signature: str | None) -> bool:
    """Constant-time check of ``X-Twilio-Signature``; a missing header or token is False."""
    if not token or not isinstance(signature, str) or not signature.strip() or len(signature) > 512:
        return False
    given = signature.strip().encode("ascii", "replace")
    ok = False
    for candidate in _url_variants(url):
        expected = compute_signature(token, candidate, params).encode("ascii")
        # Evaluate every variant: the time taken does not depend on which matched.
        ok = hmac.compare_digest(expected, given) or ok
    return ok


# ── replay window (MessageSid) ───────────────────────────────────────────────────


class ReplayStoreUnavailable(RuntimeError):
    """The replay record cannot be read or written: the message is dropped (fail closed)."""


def remember_sid(sid: str, *, now: float | None = None) -> bool:
    """True when *sid* is new (and is now remembered); False for a replay.

    One row per MessageSid in the G15 reliability store (``seen_ids``), 24-hour TTL,
    at most :data:`REPLAY_MAX_SIDS` rows. Only admitted senders' messages are recorded
    (``accept`` checks the sender first), so strangers cannot evict the owner's ids. A
    store that cannot be opened, read or written raises :class:`ReplayStoreUnavailable`:
    the message is dropped, never let through unchecked."""
    from . import delivery_ledger

    store = delivery_ledger.store()
    if store is None:
        raise ReplayStoreUnavailable("reliability store unavailable")
    try:
        return store.remember_once(_REPLAY_SCOPE, sid, ttl_s=REPLAY_WINDOW_S,
                                   max_rows=REPLAY_MAX_SIDS, now=now)
    except Exception as exc:
        raise ReplayStoreUnavailable(type(exc).__name__) from exc


# ── the adapter ──────────────────────────────────────────────────────────────────


class SmsChannel(ChannelAdapter):
    """Inbound from the signed webhook; outbound only for an approved ``channel.reply``."""

    descriptor = ChannelDescriptor(max_message_length=MAX_MESSAGE_LENGTH)

    def __init__(self, handler: Callable | None = None, *, pairing=None, transport=None) -> None:
        super().__init__(CHANNEL_ID, handler)
        self.pairing = pairing
        self._transport = transport   # async request(method, url, data=, auth=)
        self.counts = {"routed": 0, "unknown_sender": 0, "echo": 0, "replay": 0, "empty": 0}
        self._tasks: set = set()

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False
        for task in list(self._tasks):
            task.cancel()
        transport = self._transport
        if transport is not None and hasattr(transport, "aclose"):
            try:
                await transport.aclose()
            except Exception:
                logger.debug("SMS transport close failed", exc_info=True)

    # ── inbound ──

    def sender_admitted(self, number: str) -> bool:
        """Allowlisted, or paired *explicitly* — never "pairing is off, so everyone"."""
        if number in allowed_numbers():
            return True
        pairing = self.pairing
        if pairing is None:
            return False
        try:
            from .pairing import ALLOWED

            return pairing.status(CHANNEL_ID, sender_id(number)) == ALLOWED
        except Exception:
            return False

    def _knock(self, number: str) -> None:
        """Record an unknown sender as a pairing request; nothing is sent back."""
        pairing = self.pairing
        if pairing is None:
            return
        try:
            pairing.request(CHANNEL_ID, sender_id(number))
        except Exception:
            logger.debug("SMS pairing request not recorded", exc_info=True)

    async def accept(self, params: dict[str, list[str]]) -> str:
        """An already signature-checked webhook: decide, and route the turn. Returns what
        happened (``routed``, ``unknown_sender``, ``echo``, ``replay``, ``empty``)."""
        def one(name: str) -> str:
            values = params.get(name) or [""]
            return str(values[0] or "")

        # Order: identity first (echo, sender), then the replay window, so a stranger's
        # message never touches the replay record and cannot evict the owner's ids.
        sid = one("MessageSid") or one("SmsMessageSid")
        if not _SID.fullmatch(sid):
            self.counts["empty"] += 1
            return "empty"
        number = e164(one("From"))
        own = from_number()
        if number is None:
            self.counts["empty"] += 1
            return "empty"
        if own is not None and number == own:
            self.counts["echo"] += 1
            return "echo"
        if not self.sender_admitted(number):
            self.counts["unknown_sender"] += 1
            logger.info("SMS from an unknown number %s ignored (pairing request recorded)",
                        redact_phone(number))
            self._knock(number)
            return "unknown_sender"
        try:
            fresh = remember_sid(sid)
        except ReplayStoreUnavailable:
            logger.warning("SMS dropped: the replay record is unavailable (fail closed)")
            self.counts["replay"] += 1
            return "replay"
        if not fresh:
            self.counts["replay"] += 1
            return "replay"
        text = one("Body")[:MAX_BODY_BYTES].strip()
        media = int(one("NumMedia") or 0) if one("NumMedia").isdigit() else 0
        if media:
            note = f"[The sender attached {media} picture(s) by MMS; Nerva does not read MMS media.]"
            text = f"{text}\n{note}".strip()
        if not text:
            self.counts["empty"] += 1
            return "empty"
        self.counts["routed"] += 1
        await self.receive(text, sender=sender_id(number), sms_to=number, chat_type="private",
                           provider_id=sid)
        # The return value is never sent from here: a reply leaves only as an approved
        # channel.reply task (the orchestrator queues it).
        return "routed"

    def accept_in_background(self, params: dict[str, list[str]]) -> None:
        import asyncio

        task = asyncio.get_running_loop().create_task(self._accept_logged(params))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _accept_logged(self, params) -> None:
        try:
            await self.accept(params)
        except Exception:
            logger.warning("SMS inbound turn failed", exc_info=True)

    # ── outbound (approved channel.reply only) ──

    async def _get_transport(self):
        if self._transport is None:  # pragma: no cover - real network path
            from ..http_client import PluginHTTPClient

            self._transport = PluginHTTPClient.for_plugin("channel_sms")
        return self._transport

    async def send(self, message: str, sms_to: str | None = None, **kwargs) -> bool:
        """Send an approved reply with Twilio's Messages API. Reached only through
        ``ChannelManager.send_channel_reply`` (``channel.reply`` executor)."""
        from . import delivery_ledger
        from .render import chunk, to_plain

        to = e164(sms_to)
        sid, token, own = account_sid(), auth_token(), from_number()
        if not enabled() or not to or not sid or not token or not own:
            delivery_ledger.note_send_failure(status=None)
            logger.warning("SMS send refused: SMS is off or not configured")
            return False
        text = to_plain(str(message or "")).strip()
        if not text:
            return False
        # The cost cap is in billed segments, not characters (UCS-2 text costs more).
        parts = chunk(fit_segments(text), MAX_MESSAGE_LENGTH)[:MAX_PARTS]
        transport = await self._get_transport()
        url = f"https://{TWILIO_HOST}/2010-04-01/Accounts/{sid}/Messages.json"
        for index, part in enumerate(parts):
            try:
                resp = await transport.request("POST", url, data={"To": to, "From": own, "Body": part},
                                               auth=(sid, token))
                status = getattr(resp, "status_code", 200)
                if not 200 <= int(status) < 300:
                    delivery_ledger.note_send_failure(status=int(status), partial=bool(index))
                    if index:
                        delivery_ledger.note_partial()
                    logger.warning("SMS to %s refused by Twilio (HTTP %s)", redact_phone(to), status)
                    return False
            except Exception as exc:
                delivery_ledger.note_send_failure(exc=exc)
                if index:
                    delivery_ledger.note_partial()
                logger.warning("SMS to %s failed: %s", redact_phone(to), type(exc).__name__)
                return False
        logger.info("SMS reply sent to %s (%d part(s))", redact_phone(to), len(parts))
        return True

    def status(self) -> dict:
        return {"enabled": enabled(), "configured": configured(), "missing": missing_config(),
                "allowed_numbers": len(allowed_numbers()), "counts": dict(self.counts)}


__all__ = [
    "ACCOUNT_SID_ENV", "ALLOWED_NUMBERS_ENV", "AUTH_TOKEN_ENV", "CHANNEL_ID", "EMPTY_TWIML",
    "ENABLED_ENV", "FROM_NUMBER_ENV", "MAX_BODY_BYTES", "SmsChannel", "WEBHOOK_URL_ENV",
    "account_sid", "allowed_numbers", "auth_token", "compute_signature", "configured", "e164",
    "enabled", "from_number", "missing_config", "redact_phone", "remember_sid", "segments", "sender_id",
    "target_ref", "valid_signature",
]
