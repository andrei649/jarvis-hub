"""
email.py — Email channel adapter (SMTP send + IMAP receive).

Port of OpenJarvis's email channel to pure Python. H096 (2026-11-12) adds what makes
inbound email safe to act on and replies that stay in the thread: the receiving server's
SPF/DKIM/DMARC verdict on every message (a failed one is not routed), automated-sender
suppression, a seen-UID watermark instead of the server's UNSEEN flag, HTML-only bodies
reduced to text, attachments (read only for paired senders), In-Reply-To/References on
replies, outbound attachments and an IPv4 retry when the SMTP host cannot be reached.
The parsing lives in :mod:`agents.core.channels.email_inbound`.
"""

import asyncio
import contextlib
import email
import hashlib
import imaplib
import json
import logging
import re
import smtplib
import socket
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Optional

from ..env_config import env_flag, env_list
from ..paths import data_path
from ..persistence import JsonStore
from . import email_inbound
from .base import ChannelAdapter
from .connect_deadline import DEFAULT_CONNECT_TIMEOUT, channel_connect_timeout
from .reconnect import FATAL_REPROBE_S, Backoff, PollingCircuit, classify_exception

#: H100 — the IMAP poll's own rungs on the shared ladder (it polls once a minute when well).
IMAP_LADDER = (30.0, 60.0, 120.0, 300.0, 600.0)
IMAP_SOCKET_TIMEOUT = 15
_AUTH_WORDS = ("authenticationfailed", "authentication failed", "invalid credentials",
               "login failed", "logon failure", "auth")
#: RFC 5530 codes (and plain wording) that say an auth failure is temporary: retry.
_TRANSIENT_WORDS = ("[unavailable]", "temporary", "temporarily", "try again", "[inuse]",
                    "[serverbug]", "[limit]")

#: Messages taken from the mailbox in one poll, and the largest one read at all.
MAX_PER_POLL = 20
MAX_MESSAGE_BYTES = 25 * 1024 * 1024
#: A document attachment gets this long to turn into text, and one poll this long in all;
#: a message whose documents would run past it waits for the next poll.
DOCUMENT_TIMEOUT_S = 20.0
POLL_DOCUMENT_BUDGET_S = 60.0
#: How many times a message whose routing raised is tried again before it is given up.
ROUTE_ATTEMPTS = 3


class _Budget:
    """Seconds of document extraction one poll may still spend."""

    def __init__(self, seconds: float) -> None:
        self._left = float(seconds)

    def left(self) -> float:
        return self._left

    def spent(self) -> bool:
        return self._left <= 0

    def charge(self, seconds: float) -> None:
        self._left -= max(0.0, float(seconds))
_UID_LIST = re.compile(rb"\d+")
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")


def _tls_context(host: str):
    """G21 review M1: a VERIFIED TLS context for the mail servers (the stdlib default for
    ``IMAP4_SSL`` and ``starttls`` checks no certificate, so a password went to whoever
    answered). The owner's CA anchor (``JARVIS_CA_BUNDLE``) is honoured; a self-signed
    local server is reachable only when the owner names ``email`` or its host in
    ``JARVIS_TLS_INSECURE_TARGETS`` (never in the hardened profile, logged as a WARNING)."""
    import ssl

    from agents.core.tls_trust import verify_for

    verdict = verify_for("email", f"imaps://{host}")
    if verdict is False:
        # Owner's explicit, logged opt-in (JARVIS_TLS_INSECURE_TARGETS); refused in the hardened profile.
        # nosemgrep: python.lang.security.unverified-ssl-context.unverified-ssl-context
        return ssl._create_unverified_context()  # nosec B323 - the owner's explicit, logged opt-in
    return verdict


def _login_refused(exc: BaseException) -> bool:
    """A refused login for good (bad password, revoked app password); not a server that
    says the failure is temporary."""
    if not isinstance(exc, imaplib.IMAP4.error):
        return False
    text = str(exc).lower()
    return (any(word in text for word in _AUTH_WORDS)
            and not any(word in text for word in _TRANSIENT_WORDS))

logger = logging.getLogger("jarvis.channels.email")


def _sender_address(raw_from: object) -> str:
    """The bare, lower-cased address in a ``From`` header — the identity pairing keys on.

    A display name or a comment must never become the sender: ``"Owner" <x@y>`` and
    ``x@y`` are the same person. The header itself is forgeable; H096 reads the receiving
    server's SPF/DKIM/DMARC verdict beside it (``email_inbound.sender_auth``) and refuses a
    message whose authentication failed, but an *unverified* sender is still only what the
    header says (Hermes absorption 5b).
    """
    address = parseaddr(str(raw_from or ""))[1].strip().lower()
    return address if "@" in address else ""


class EmailSeenStore(JsonStore):
    """H096 — the newest IMAP UID already handled, per mailbox, instead of the server's
    UNSEEN flag (which any other mail client clears by opening the message).

    Keyed by a digest of host and user, never the address itself; a changed UIDVALIDITY
    (the server renumbered the mailbox) starts over from the newest message."""

    def __init__(self, path=None) -> None:
        super().__init__(path if path is not None else data_path("email_seen.json"))

    def _serialize(self):
        return self._data

    def _deserialize(self, raw) -> None:
        self._data = {}
        if isinstance(raw, dict):
            for key, row in list(raw.items())[:64]:
                if (isinstance(key, str) and isinstance(row, dict)
                        and isinstance(row.get("uidvalidity"), str)
                        and type(row.get("last_uid")) is int and row["last_uid"] >= 0):
                    self._data[key] = {"uidvalidity": row["uidvalidity"][:32],
                                       "last_uid": row["last_uid"]}

    @staticmethod
    def key(host: str, user: str) -> str:
        return hashlib.sha256(f"{host}\x00{user}".lower().encode()).hexdigest()[:24]

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._data.get(key)
            return dict(row) if row else None

    def set(self, key: str, uidvalidity: str, last_uid: int) -> None:
        with self._lock:
            prior = self._data.get(key)
            self._data[key] = {"uidvalidity": str(uidvalidity)[:32], "last_uid": max(0, int(last_uid))}
            try:
                self._save()
            except BaseException:
                if prior is None:
                    self._data.pop(key, None)
                else:
                    self._data[key] = prior
                raise


@dataclass(frozen=True)
class FetchBatch:
    """One read-only worker result; only the async routing loop checkpoints it."""

    messages: list[dict]
    key: str | None
    validity: str | None
    previous_uid: int | None
    last_uid: int | None
    baseline: bool = False
    previous_validity: str | None = None


class _IMAPConnectTimeout(RuntimeError):
    """Fixed local opening outcome; never includes a host, user or provider body."""


class _IMAPOpening:
    """One loop decision and one worker permit for the blocking IMAP handshake."""

    def __init__(self, loop: asyncio.AbstractEventLoop, deadline: float):
        self.loop = loop
        self.deadline = deadline
        self.ready = loop.create_future()
        self.permit = threading.Event()
        self.abandoned = threading.Event()
        self.reported_timeout = False

    def announce_ready(self) -> None:
        def settle() -> None:
            if not self.ready.done():
                self.ready.set_result(True)

        try:
            self.loop.call_soon_threadsafe(settle)
        except RuntimeError:
            # A closed loop cannot grant a fresh fetch. The worker's bounded
            # permit wait will expire and close its IMAP connection.
            self.abandon()

    def abandon(self) -> None:
        self.abandoned.set()
        self.permit.set()


def _resp_int(mail, name: str) -> int | None:
    try:
        _typ, data = mail.response(name)
    except Exception:
        return None
    for item in data or ():
        if isinstance(item, bytes | bytearray) and bytes(item).strip().isdigit():
            return int(bytes(item).strip())
    return None


def _uids(data) -> list[int]:
    out: list[int] = []
    for item in data or ():
        if isinstance(item, bytes | bytearray):
            out.extend(int(x) for x in _UID_LIST.findall(bytes(item)[:200_000]))
    return out


def _fetched_bytes(data) -> bytes | None:
    for item in data or ():
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes | bytearray):
            return bytes(item[1])
    return None


def _fetched_size(data) -> int | None:
    for item in data or ():
        head = item[0] if isinstance(item, tuple) and item else item
        if isinstance(head, bytes | bytearray):
            found = _SIZE.search(bytes(head)[:1000])
            if found:
                return int(found.group(1))
    return None


def _decoded_subject(value: object) -> str:
    try:
        text = str(make_header(decode_header(str(value or ""))))
    except Exception:
        text = str(value or "")
    return email_inbound.clean_subject(text)


def _msgid_domain(from_header: object) -> str | None:
    address = parseaddr(str(from_header or ""))[1]
    domain = address.rsplit("@", 1)[1] if "@" in address else ""
    return domain if re.fullmatch(r"[A-Za-z0-9.-]{1,200}", domain or "") else None


class _IPv4SMTP(smtplib.SMTP):
    """H096 — an SMTP client that connects over IPv4 only, for a host whose IPv6 address
    is unreachable. The host name is kept, so STARTTLS still verifies the certificate
    against it."""

    def _get_socket(self, host, port, timeout):
        last: Exception | None = None
        for family, kind, proto, _canon, addr in socket.getaddrinfo(
                host, port, socket.AF_INET, socket.SOCK_STREAM)[:4]:
            sock = socket.socket(family, kind, proto)
            try:
                if timeout is not None:
                    sock.settimeout(timeout)
                sock.connect(addr)
                return sock
            except OSError as exc:
                last = exc
                sock.close()
        raise last or OSError("no IPv4 address for the SMTP host")


def _open_smtp(host: str, port: int) -> smtplib.SMTP:
    return smtplib.SMTP(host, port, timeout=10)


def _open_smtp_ipv4(host: str, port: int) -> smtplib.SMTP:
    return _IPv4SMTP(host, port, timeout=10)


class EmailChannel(ChannelAdapter):
    def __init__(self, handler=None, smtp_config: dict = None, imap_config: dict = None, *,
                 pairing=None, image_reader=None, seen_store: EmailSeenStore | None = None,
                 trusted_authserv_ids=None, require_sender_auth: bool | None = None,
                 connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT):
        super().__init__("email", handler)
        self.smtp = smtp_config or {}
        self.imap = imap_config or {}
        self._connect_timeout_seconds = channel_connect_timeout(connect_timeout_seconds)
        self._poll_task: Optional[asyncio.Task] = None
        self._fetch_task: asyncio.Task | None = None
        self._opening_attempt: _IMAPOpening | None = None
        self._fetch_lease = None
        self._poll_lifecycle_lock = asyncio.Lock()
        self._circuit = PollingCircuit()
        # H096: whose attachments may be opened (the gateway's pairing store).
        self.pairing = pairing
        self._image_reader = image_reader
        self._seen = seen_store
        ids = (env_list("EMAIL_TRUSTED_AUTHSERV_IDS") if trusted_authserv_ids is None
               else list(trusted_authserv_ids))
        self.trusted_authserv_ids = frozenset(str(i).strip().lower() for i in ids if str(i).strip())
        self.require_sender_auth = (env_flag("EMAIL_REQUIRE_SENDER_AUTH")
                                    if require_sender_auth is None else bool(require_sender_auth))
        #: Inbound messages not routed, by reason (a count only; no address is kept).
        self.suppressed: dict[str, int] = {}
        #: (UIDVALIDITY, UID) already routed, and routing failures per message (bounded).
        self._routed: OrderedDict[tuple, None] = OrderedDict()
        self._route_failures: dict[tuple, int] = {}

    def _own_addresses(self) -> frozenset[str]:
        return email_inbound.own_addresses(self.smtp.get("from", ""), self.smtp.get("user", ""),
                                           self.imap.get("user", ""))

    async def start(self):
        async with self._poll_lifecycle_lock:
            if self._running:
                return
            if (self._poll_task is not None or self._fetch_task is not None
                    or self._fetch_lease is not None or not self._circuit.reset()):
                raise RuntimeError("Email polling cleanup unconfirmed")
            if not self.smtp.get("host"):
                logger.info("Email channel: no SMTP configured, send disabled")
            if not self.imap.get("host"):
                logger.info("Email channel: no IMAP configured, receive disabled")
                return
            self.health.starting()
            self._running = True
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        async with self._poll_lifecycle_lock:
            self._running = False
            self.health.stopped()
            poll = self._poll_task
            if poll is not None:
                poll.cancel()
                await asyncio.gather(poll, return_exceptions=True)
                self._poll_task = None
            worker = self._fetch_task
            if worker is not None:
                # Cancelling the asyncio waiter cannot stop a running IMAP thread.
                # Keep its handle and lease until it really settles. Cancellation of
                # this stop still propagates to ChannelManager's bounded cleanup.
                with contextlib.suppress(Exception):
                    await asyncio.shield(worker)
                self._fetch_task = None
            self._opening_attempt = None
            lease, self._fetch_lease = self._fetch_lease, None
            if lease is not None:
                self._circuit.release(lease)
            if not self._circuit.reset():
                raise RuntimeError("Email polling cleanup unconfirmed")

    def health_snapshot(self) -> dict:
        return {**super().health_snapshot(), "circuit": self._circuit.snapshot()}

    # ── outbound ─────────────────────────────────────────────────────────────

    def build_message(self, message: str, **kwargs) -> EmailMessage:
        """The MIME message :meth:`send` hands to SMTP (H096): reply threading headers,
        attachments, and header values that cannot carry a line break."""
        to_addr = kwargs.get("to") or self.smtp.get("default_recipient", "")
        in_reply_to = email_inbound.message_id(kwargs.get("in_reply_to"))
        references = kwargs.get("references")
        from .outbound_safety import sanitize_text

        # H069 review m4: the subject leaves with the message; one line, through the gate.
        subject = " ".join(sanitize_text(str(kwargs.get("subject", "Jarvis Message"))).split())
        subject = (email_inbound.reply_subject(subject) if in_reply_to
                   else email_inbound.clean_subject(subject) or "Jarvis Message")
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp.get("from", "cabinet@localhost")
        msg["To"] = to_addr
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=_msgid_domain(msg["From"]))
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = (references if email_inbound.valid_references(references)
                                 and references.split(" ")[-1] == in_reply_to else in_reply_to)
        msg.set_content(str(message))
        for item in kwargs.get("attachments") or ():
            mime = str(getattr(item, "mime", "") or "application/octet-stream")
            major, _, minor = mime.partition("/")
            msg.add_attachment(bytes(item.data), maintype=major or "application",
                               subtype=minor or "octet-stream",
                               filename=email_inbound.clean_name(getattr(item, "name", "")))
        return msg

    async def send(self, message: str, **kwargs) -> bool:
        if not self.smtp.get("host"):
            logger.warning("SMTP not configured for email channel")
            return False
        try:
            msg = self.build_message(message, **kwargs)
            to_addr = str(msg["To"] or "")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._smtp_send, msg, to_addr)
            logger.info("Email sent (%d attachment(s))", len(kwargs.get("attachments") or ()))
            return True
        except Exception as e:
            logger.error("Email send failed: %s", type(e).__name__)
            return False

    def _smtp_connect(self) -> smtplib.SMTP:
        """Connect to the SMTP host; when the connection itself fails (not an SMTP
        answer), try once more over IPv4 only (H096). Nothing has been sent at this
        point, so the retry can never send a message twice."""
        host, port = self.smtp["host"], self.smtp.get("port", 587)
        try:
            return _open_smtp(host, port)
        except smtplib.SMTPException:
            raise
        except OSError as first:
            logger.warning("SMTP connection failed (%s); retrying over IPv4", type(first).__name__)
            return _open_smtp_ipv4(host, port)

    def _smtp_send(self, msg, to_addr: str):
        with self._smtp_connect() as server:
            if self.smtp.get("tls", True):
                server.starttls(context=_tls_context(self.smtp["host"]))
            if self.smtp.get("user"):
                server.login(self.smtp["user"], self.smtp.get("password", ""))
            server.send_message(msg)

    # ── inbound ──────────────────────────────────────────────────────────────

    async def _poll_loop(self):
        backoff = Backoff(IMAP_LADDER)
        while self._running:
            lease, wait = self._circuit.admit()
            if lease is None:
                await asyncio.sleep(wait)
                continue
            self._fetch_lease = lease
            try:
                await self._check_imap()
            except asyncio.CancelledError:
                if self._fetch_task is None or self._fetch_task.done():
                    self._circuit.release(lease)
                    self._fetch_lease = None
                raise
            except Exception as e:
                if _login_refused(e):
                    self._circuit.release(lease)
                    self._fetch_lease = None
                    # H100: a refused login does not heal by asking again every minute:
                    # say so on the status surface and try the login again only every
                    # FATAL_REPROBE_S, so fixed credentials heal by themselves.
                    self.health.failed_fatally("unauthorized", reprobe_in=FATAL_REPROBE_S)
                    logger.error("Email channel: the IMAP server refused the login. Fix the "
                                 "IMAP credentials; Nerva tries again every %.0f min.",
                                 FATAL_REPROBE_S / 60)
                    await asyncio.sleep(FATAL_REPROBE_S)
                    continue
                timed_out = isinstance(e, _IMAPConnectTimeout)
                kind = "connect_timeout" if timed_out else classify_exception(e).kind
                gate_wait = self._circuit.failure(lease)
                self._fetch_lease = None
                delay = max(backoff.failure(), gate_wait)
                if timed_out:
                    # Already recorded when the deadline expired, while the
                    # real worker and lease were still held for cleanup.
                    self.health.next_retry_at = time.time() + delay
                else:
                    self.health.retrying(kind, delay)
                logger.warning("IMAP poll failed (%s); retrying in %.0f s", kind, delay)
                await asyncio.sleep(delay)
                continue
            if self._fetch_lease is lease:
                self._circuit.success(lease)
                self._fetch_lease = None
            backoff.success()
            self.health.ok()
            await asyncio.sleep(self.imap.get("poll_interval", 60))

    def _suppress(self, reason: str) -> None:
        self.suppressed[reason] = self.suppressed.get(reason, 0) + 1
        # The address is never logged: the reason is enough to diagnose.
        logger.info("Email: inbound message not routed (%s)", reason)

    async def _check_imap(self):
        """Fetch, then route each message on its own: one that raises does not cost the
        rest of the batch. The worker proposes a UID watermark; this loop commits
        only a prefix whose routing/skip decisions it accepted. An interrupted
        worker cannot checkpoint a message the loop never saw."""
        if self._fetch_task is not None:
            raise RuntimeError("Email polling cleanup unconfirmed")
        loop = asyncio.get_running_loop()
        opening = _IMAPOpening(loop, time.monotonic() + self._connect_timeout_seconds)
        self._opening_attempt = opening
        worker = asyncio.create_task(asyncio.to_thread(self._imap_fetch))
        self._fetch_task = worker
        # A cancelled poll retains the thread; retrieve a late error even if the
        # poller no longer awaits its result.
        worker.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            done, _ = await asyncio.wait({opening.ready, worker},
                                         timeout=max(0.0, opening.deadline - time.monotonic()),
                                         return_when=asyncio.FIRST_COMPLETED)
            if worker in done:
                # A pre-login error is accepted only inside the recognition
                # window. A late auth-shaped failure cannot become a fatal
                # credential verdict after the opening deadline.
                if not opening.permit.is_set() and time.monotonic() >= opening.deadline:
                    opening.abandon()
                    self.health.retrying("connect_timeout", 0)
                    opening.reported_timeout = True
                    logger.warning("Email IMAP opening timed out")
                    with contextlib.suppress(Exception):
                        await asyncio.shield(worker)
                    raise _IMAPConnectTimeout()
                fetched = await asyncio.shield(worker)
            elif opening.ready in done and time.monotonic() < opening.deadline:
                opening.permit.set()
                # Fetch duration is separate from the opening deadline.
                fetched = await asyncio.shield(worker)
            else:
                opening.abandon()
                self.health.retrying("connect_timeout", 0)
                opening.reported_timeout = True
                logger.warning("Email IMAP opening timed out")
                with contextlib.suppress(Exception):
                    await asyncio.shield(worker)
                raise _IMAPConnectTimeout()
        except _IMAPConnectTimeout:
            if not opening.reported_timeout:
                self.health.retrying("connect_timeout", 0)
                opening.reported_timeout = True
                logger.warning("Email IMAP opening timed out")
            raise
        except asyncio.CancelledError:
            opening.abandon()
            raise
        finally:
            if worker.done() and self._fetch_task is worker:
                self._fetch_task = None
                if self._opening_attempt is opening:
                    self._opening_attempt = None
        # Some existing offline worker seams return plain lists. They have no
        # checkpoint proposal; production _imap_fetch always returns FetchBatch.
        batch = fetched if isinstance(fetched, FetchBatch) else None
        messages = batch.messages if batch is not None else fetched
        lease = self._fetch_lease
        if lease is not None:
            self._circuit.success(lease)
            self._fetch_lease = None
        budget = _Budget(POLL_DOCUMENT_BUDGET_S)
        rewind: int | None = None
        current_uid: int | None = None
        try:
            for item in messages:
                current_uid = item.get("uid")
                ident = (item.get("_validity"), current_uid)
                if ident in self._routed:
                    continue
                if budget.spent() and self._needs_documents(item):
                    # Over this poll's time for documents: deferred, not dropped.
                    self._suppress("deferred_document_budget")
                    rewind = item["uid"] - 1 if rewind is None else min(rewind, item["uid"] - 1)
                    break
                try:
                    await self._route(item, budget)
                except Exception:
                    failures = self._route_failures.get(ident, 0) + 1
                    self._route_failures[ident] = failures
                    logger.warning("Email: routing a message failed (attempt %d)", failures,
                                   exc_info=True)
                    if failures < ROUTE_ATTEMPTS:
                        rewind = item["uid"] - 1 if rewind is None else min(rewind, item["uid"] - 1)
                        continue
                    self._suppress("route_failed")
                self._route_failures.pop(ident, None)
                self._routed[ident] = None
                while len(self._routed) > 2048:
                    self._routed.popitem(last=False)
        except asyncio.CancelledError:
            if batch is not None and current_uid is not None:
                through = current_uid - 1 if rewind is None else min(rewind, current_uid - 1)
                try:
                    self._commit_fetch_batch(batch, through)
                except Exception:
                    # Keep the original cancellation. A missed checkpoint may
                    # replay, but a failed store write cannot prove delivery.
                    logger.warning("Email watermark commit failed during cancellation")
            raise
        if batch is not None and batch.last_uid is not None:
            self._commit_fetch_batch(batch, batch.last_uid if rewind is None else rewind)

    def _commit_fetch_batch(self, batch: FetchBatch, through_uid: int) -> None:
        """Commit an accepted prefix, never the worker's unreviewed proposal."""
        if batch.key is None or batch.validity is None or batch.last_uid is None:
            return
        store = self._seen_store()
        state = store.get(batch.key)
        if batch.baseline:
            if (state is None) != (batch.previous_validity is None):
                raise RuntimeError("Email watermark changed during fetch")
            if state is not None and (state["uidvalidity"] != batch.previous_validity
                                      or state["last_uid"] != batch.previous_uid):
                raise RuntimeError("Email watermark changed during fetch")
            store.set(batch.key, batch.validity, batch.last_uid)
            logger.info("Email: mailbox watermark set; earlier messages are left as they are")
            return
        if (state is None or state["uidvalidity"] != batch.validity
                or state["last_uid"] != batch.previous_uid):
            raise RuntimeError("Email watermark changed during fetch")
        through = max(batch.previous_uid, min(through_uid, batch.last_uid))
        if through > batch.previous_uid:
            store.set(batch.key, batch.validity, through)

    def _needs_documents(self, item: dict) -> bool:
        return (any(getattr(a, "kind", "") == "file" for a in item.get("attachments") or ())
                and self._sender_may_be_read(item.get("sender") or ""))

    async def _route(self, item: dict, budget: "_Budget | None" = None) -> None:
        """One parsed inbound message → the gateway, unless it must not be answered."""
        if not self.handler:
            return
        if item.get("automated"):
            self._suppress(f"automated:{item['automated']}")
            return
        auth: email_inbound.SenderAuth = item["auth"]
        if auth.verdict == email_inbound.VERDICT_FAIL:
            # The receiving server reported this message as failing authentication.
            self._suppress("sender_auth_failed")
            return
        if self.require_sender_auth and not (auth.verdict == email_inbound.VERDICT_PASS
                                             and auth.basis == "configured"):
            self._suppress("sender_unverified")
            return
        sender = item["sender"]
        if not sender:
            self._suppress("no_sender")
            return
        text = item["body"] or item["subject"]
        notes = await self._attachment_notes(sender, item["attachments"], item["skipped"],
                                             budget=budget)
        if notes:
            text = f"{text}\n\n{notes}" if text else notes
        extra = {}
        if item["message_id"]:
            # H120: the provider's id for this message, bound to its sender, for the
            # gateway's duplicate window and the reply queue's idempotency.
            extra["provider_id"] = f"{sender}:{item['message_id']}"
        await self.handler(text, channel="email", sender=sender, from_addr=sender,
                           subject=item["subject"], email_message_id=item["message_id"],
                           email_references=item["references"], sender_auth=auth.to_dict(),
                           **extra)

    def _sender_may_be_read(self, sender: str) -> bool:
        pairing = self.pairing
        if pairing is None:
            return False
        try:
            return pairing.is_allowed("email", sender) is True
        except Exception:
            return False

    async def _attachment_notes(self, sender: str, atts: list, skipped: int, *,
                                budget: "_Budget | None" = None) -> str:
        """H096 — what came attached, for the turn. Contents are read only for a sender the
        pairing gate already admits (a stranger's files are named, never opened); images go
        to the proven-local vision model only, text files arrive fenced as data."""
        if not atts and not skipped:
            return ""
        readable = self._sender_may_be_read(sender)
        lines: list[str] = []
        for index, att in enumerate(atts, start=1):
            label = f"Attachment {index}: {att.name} ({att.mime}, {max(1, att.size // 1024)} KB)"
            if not readable:
                lines.append(f"{label} — not opened (the sender is not paired).")
                continue
            if att.data is None:
                lines.append(f"{label} — not read (too large or empty).")
                continue
            if att.kind == "text":
                lines.append(f"{label}, its contents as data:\n" + email_inbound.text_attachment(att))
                continue
            if att.kind == "image":
                description = await self._describe_image(att.data)
                if description is not None and description.ok:
                    lines.append(f"{label}. A local vision model described it (a machine "
                                 f"description, not something you observed):\n{description.text}")
                else:
                    from . import media_reader

                    why = media_reader.note(description) if description is not None else ""
                    lines.append(f"{label} — not read" + (f": {why}" if why else "") + ".")
                continue
            document = await self._document_text(att, budget=budget)
            if document:
                lines.append(f"{label}, its text as data:\n" + document)
            else:
                lines.append(f"{label} — reading this kind of file is not wired up yet.")
        if skipped:
            lines.append(f"{skipped} more attachment(s) were not listed.")
        return "\n".join(lines)

    @staticmethod
    async def _document_text(att, *, budget: "_Budget | None" = None) -> str:
        """A PDF, Word, Excel, CSV or Markdown attachment's text, through the bounded
        document extractor the Workspace uploads use (kind from the file name, confirmed
        by the file's own magic bytes), fenced as data. ``""`` when it cannot be read."""
        from agents.core.security.quarantine import fence_tool_result
        from agents.core.workspace import extract

        kind = extract.kind_for_filename(att.name)
        if kind is None or not extract.content_matches(kind, att.data):
            return ""
        timeout = DOCUMENT_TIMEOUT_S if budget is None else min(DOCUMENT_TIMEOUT_S, budget.left())
        if timeout <= 0:
            return ""
        started = time.monotonic()
        try:
            found = await extract.extract_document(att.data, kind, timeout=timeout)
        except Exception:
            return ""
        finally:
            if budget is not None:
                budget.charge(time.monotonic() - started)
        text = "\n".join(segment.text for segment in found.segments)
        text = text[:email_inbound.MAX_TEXT_ATTACHMENT_CHARS]
        if not text.strip():
            return ""
        return fence_tool_result(json.dumps(text, ensure_ascii=False),
                                 source="email.attachment")[0]

    async def _describe_image(self, data: bytes):
        reader = self._image_reader
        if reader is None:
            from .media_reader import InboundImageReader

            try:
                reader = self._image_reader = InboundImageReader.from_env()
            except Exception:
                return None
        try:
            return await reader(data)
        except Exception:
            return None

    def _parse(self, raw: bytes) -> dict:
        from .media_limits import current_max_bytes

        msg = email.message_from_bytes(raw)
        atts, skipped = email_inbound.attachments(msg, max_bytes=current_max_bytes())
        threading = email_inbound.threading_headers(msg)
        return {
            "sender": _sender_address(msg.get("From", "")),
            "subject": _decoded_subject(msg.get("Subject", "")),
            "body": email_inbound.extract_body(msg),
            "automated": email_inbound.automated_reason(msg, own_addresses=self._own_addresses()),
            "auth": email_inbound.sender_auth(msg, trusted_ids=self.trusted_authserv_ids),
            "attachments": atts,
            "skipped": skipped,
            "message_id": threading["message_id"],
            "references": threading["references"],
        }

    def _seen_store(self) -> EmailSeenStore:
        if self._seen is None:
            self._seen = EmailSeenStore()
        return self._seen

    def _imap_fetch(self) -> FetchBatch:
        opening = self._opening_attempt
        mail = imaplib.IMAP4_SSL(self.imap["host"], self.imap.get("port", 993),
                                 ssl_context=_tls_context(self.imap["host"]),
                                 timeout=IMAP_SOCKET_TIMEOUT)
        # Always log out (closing the SSL socket) even if login/select/fetch
        # raises — otherwise a bad login or server error leaks one socket per
        # poll interval.
        try:
            if opening is not None and (opening.abandoned.is_set()
                                        or time.monotonic() >= opening.deadline):
                raise _IMAPConnectTimeout()
            mail.login(self.imap["user"], self.imap.get("password", ""))
            if opening is not None:
                if opening.abandoned.is_set() or time.monotonic() >= opening.deadline:
                    raise _IMAPConnectTimeout()
                opening.announce_ready()
                opening.permit.wait(max(0.0, opening.deadline - time.monotonic()))
                if (opening.abandoned.is_set() or not opening.permit.is_set()
                        or time.monotonic() >= opening.deadline):
                    raise _IMAPConnectTimeout()
            return self._fetch_new(mail)
        finally:
            with contextlib.suppress(Exception):
                mail.logout()

    def _fetch_new(self, mail) -> FetchBatch:
        """H096 — the messages after the newest UID already handled. Read-only: the
        mailbox is opened with EXAMINE and bodies are fetched with BODY.PEEK, so Nerva
        never marks anything read for the owner's other mail clients."""
        status, _ = mail.select("INBOX", readonly=True)
        if status != "OK":
            return FetchBatch([], None, None, None, None)
        validity = str(_resp_int(mail, "UIDVALIDITY") or 0)
        store = self._seen_store()
        key = EmailSeenStore.key(self.imap.get("host", ""), self.imap.get("user", ""))
        state = store.get(key)
        if state is None or state["uidvalidity"] != validity:
            # First contact with this mailbox (or it was renumbered): start after the
            # newest message instead of answering the whole inbox history.
            uidnext = _resp_int(mail, "UIDNEXT")
            if uidnext is not None:
                newest = max(0, uidnext - 1)
            else:
                status, data = mail.uid("SEARCH", None, "ALL")
                if status != "OK":
                    # No UIDNEXT and no successful search: zero is not evidence
                    # that this is an empty mailbox. Retry baseline discovery.
                    return FetchBatch([], None, None, None, None)
                newest = max(_uids(data), default=0)
            return FetchBatch([], key, validity, state["last_uid"] if state else None,
                              newest, baseline=True,
                              previous_validity=state["uidvalidity"] if state else None)
        last = state["last_uid"]
        status, data = mail.uid("SEARCH", None, f"UID {last + 1}:*")
        if status != "OK":
            return FetchBatch([], key, validity, last, last)
        # "N:*" always answers the newest UID, even when it is below N.
        uids = sorted({u for u in _uids(data) if u > last})[:MAX_PER_POLL]
        messages: list[dict] = []
        for uid in uids:
            # An IMAP error raises out of this loop before the watermark moves, so a
            # message already read in this poll is read again next time, never lost.
            status, data = mail.uid("FETCH", str(uid), "(RFC822.SIZE)")
            size = _fetched_size(data) if status == "OK" else None
            if size is None or size > MAX_MESSAGE_BYTES:
                self._suppress("too_large" if size else "unreadable")
                last = max(last, uid)
                continue
            status, data = mail.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = _fetched_bytes(data) if status == "OK" else None
            last = max(last, uid)
            if not raw or len(raw) > MAX_MESSAGE_BYTES:
                self._suppress("unreadable")
                continue
            try:
                item = self._parse(raw)
            except Exception:
                self._suppress("unparseable")
                continue
            item["uid"], item["_validity"] = uid, validity
            messages.append(item)
        return FetchBatch(messages, key, validity, state["last_uid"], last)
