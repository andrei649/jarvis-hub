"""Outgoing email of Nerva Workspace: SMTP settings, the password store and sending (spec §6, §7).

Where things live. The connection settings (host, port, security, username, sender,
allowed recipient domains) are plain JSON under ``org.settings_json["smtp"]``. The
password is the one secret, so it lives encrypted in
``SecretStore(data_path("workspace", "secrets.enc"))`` and is never returned by any API
(``has_password`` says whether one is stored). Building a store costs ~230 ms with a
passphrase key, so one instance per path is cached and every function that touches it
runs off the event loop (sync routes or worker threads).

Sending. ``smtplib`` runs in a worker thread with a 15 s socket timeout, TLS through
``agents.core.tls_trust.trust_context()`` — implicit TLS for ``ssl``, ``STARTTLS`` for
``starttls``, nothing for ``none``. ``none`` with credentials is refused unless the
server is on loopback: a password must never cross a network in clear text.

Guards before any byte leaves: at most 20 valid, de-duplicated recipients; every
recipient's domain in ``allowed_domains`` when that list is set (``422
recipient_not_allowed``); no CR/LF or other control character in any header value, so a
subject or name can never inject a header. The callers audit their own sends
(``email.sent`` / ``email.failed``); this module only reports what happened.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import smtplib
import sqlite3
import ssl
import threading
from collections.abc import Mapping, Sequence
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from agents.core import tls_trust
from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError
from agents.core.workspace import config, db, identity
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.http import (
    MAX_EMAILS,
    invalid,
    normalize_email,
    optional_int,
    optional_str,
    require_choice,
    require_email,
    require_list,
    require_str,
)

logger = logging.getLogger("nerva.workspace.mailer")

SETTINGS_KEY = "smtp"
#: Name of the SMTP credential inside the workspace secret store.
CREDENTIAL_NAME = "smtp.password"
STORE_FILE = "secrets.enc"
SECURITIES = ("starttls", "ssl", "none")
DEFAULT_PORTS = {"starttls": 587, "ssl": 465, "none": 25}
SMTP_TIMEOUT_SECONDS = 15.0
MAX_HOST = 253
MAX_SUBJECT = 400
MAX_NAME = 200
MAX_USERNAME = 254
MAX_CREDENTIAL = 512
MAX_DOMAINS = 50

_HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                       r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
# C0/C1 controls and the Unicode line separators: any of them could split a header.
_HEADER_UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")

_DEFAULTS: dict[str, Any] = {
    "host": "", "port": DEFAULT_PORTS["starttls"], "security": "starttls", "username": "",
    "from_address": "", "from_name": "", "allowed_domains": [],
}

_stores: dict[str, SecretStore] = {}
_stores_lock = threading.Lock()


# ── errors ───────────────────────────────────────────────────────────────────────────

def not_configured() -> WorkspaceError:
    """``409 smtp_not_configured`` — outgoing email has no server or sender yet."""
    return WorkspaceError("smtp_not_configured", "outgoing email is not configured", 409)


def _failed(reason: str) -> WorkspaceError:
    return WorkspaceError("smtp_failed", "the mail server refused or could not be reached", 502,
                          reason=reason)


# ── the secret store ─────────────────────────────────────────────────────────────────

def secret_store() -> SecretStore:
    """The cached workspace secret store (built on first use: call it off the event loop)."""
    path = data_path("workspace", STORE_FILE)
    key = str(path)
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            config.workspace_dir()
            store = SecretStore(path)
            _stores[key] = store
        return store


def has_password() -> bool:
    """Whether an SMTP password is stored (reads the store's index, never decrypts)."""
    return CREDENTIAL_NAME in secret_store()


def set_password(value: str | None) -> None:
    """Store *value* as the SMTP password, or delete it when ``None``."""
    store = secret_store()
    if value is None:
        store.delete(CREDENTIAL_NAME)
    else:
        store.set(CREDENTIAL_NAME, value)


def _read_password() -> str | None:
    try:
        return secret_store().get(CREDENTIAL_NAME)
    except SecretStoreError as exc:
        raise WorkspaceError("smtp_password_unreadable",
                             "the stored SMTP password cannot be read; enter it again",
                             409) from exc


# ── settings ─────────────────────────────────────────────────────────────────────────

def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _normalized(raw: Any) -> dict[str, Any]:
    """Stored settings with every field present and of the right type.

    ``settings_json`` is free-form JSON shared with other features, so whatever is
    found is coerced field by field rather than trusted.
    """
    data = raw if isinstance(raw, Mapping) else {}
    security = data.get("security") if data.get("security") in SECURITIES else "starttls"
    port = data.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        port = DEFAULT_PORTS[security]
    domains = data.get("allowed_domains")
    return {
        "host": _as_str(data.get("host")), "port": port, "security": security,
        "username": _as_str(data.get("username")), "from_address": _as_str(data.get("from_address")),
        "from_name": _as_str(data.get("from_name")),
        "allowed_domains": [d for d in domains if isinstance(d, str)] if isinstance(domains, list) else [],
    }


def _org_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    org = identity.ensure_org(conn)
    if org is None:
        return {}
    try:
        settings = json.loads(org["settings_json"] or "{}")
    except ValueError:
        logger.warning("org.settings_json is not valid JSON; treating it as empty")
        return {}
    return settings if isinstance(settings, dict) else {}


def stored_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    """The SMTP settings without the password (defaults when nothing is stored)."""
    return _normalized(_org_settings(conn).get(SETTINGS_KEY))


def _is_configured(settings: Mapping[str, Any]) -> bool:
    return bool(settings["host"] and settings["from_address"])


def smtp_configured(conn: sqlite3.Connection) -> bool:
    """Whether a server and a sender are set (cheap: no secret store access)."""
    return _is_configured(stored_settings(conn))


def smtp_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    """Settings as the admin console shows them: no password, ``has_password`` instead.

    Touches the secret store, so call it from a sync route or a worker thread.
    """
    settings = stored_settings(conn)
    return {**settings, "has_password": has_password(), "configured": _is_configured(settings)}


def is_loopback(host: str) -> bool:
    """``localhost`` or a loopback IP literal (the only place clear-text auth is allowed)."""
    if host.lower().rstrip(".") == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _check_host(host: str) -> str:
    if not host:
        return host
    literal = host.strip("[]")
    try:
        ipaddress.ip_address(literal)
    except ValueError:
        if not _HOSTNAME.match(host):
            raise invalid("host", "malformed", "host must be a host name or an IP address") from None
        return host.lower()
    return literal


def _clean_domains(body: Mapping[str, Any]) -> list[str]:
    domains: list[str] = []
    for item in require_list(body, "allowed_domains", max_items=MAX_DOMAINS, required=False):
        domain = item.strip().lower().lstrip("@").rstrip(".") if isinstance(item, str) else ""
        if not _DOMAIN.match(domain):
            raise invalid("allowed_domains", "malformed",
                          "allowed_domains must hold domain names such as firma.ro")
        if domain not in domains:
            domains.append(domain)
    return domains


def _ascii_login(value: str, field: str) -> str:
    """*value* when it is ASCII, else ``422 not_ascii`` naming *field*.

    ``smtplib`` encodes login details as ASCII only: anything else could be saved but
    never used to sign in, so it is refused when the admin types it.
    """
    if not value.isascii():
        raise invalid(field, "not_ascii", f"{field} must use ASCII characters only")
    return value


def parse_update(body: Mapping[str, Any], *, password_stored: bool) -> tuple[dict, str | None, bool]:
    """Validate a ``PUT /admin/smtp`` body → ``(settings, new_password, password_given)``.

    ``password`` absent or ``null`` keeps the stored one (``password_given`` False);
    ``""`` clears it; any other string replaces it. An empty ``host`` turns outgoing
    email off. ``none`` security with credentials is refused off loopback.
    """
    security = require_choice(body, "security", SECURITIES, default="starttls")
    host = _check_host(require_str(body, "host", max_len=MAX_HOST, required=False))
    port = optional_int(body, "port", minimum=1, maximum=65535) or DEFAULT_PORTS[security]
    username = _ascii_login(require_str(body, "username", max_len=MAX_USERNAME, required=False),
                            "username")
    from_address = require_email(body, "from_address", required=bool(host))
    from_name = optional_str(body, "from_name", max_len=MAX_NAME) or ""
    password_given = body.get("password") is not None
    password = (_ascii_login(require_str(body, "password", max_len=MAX_CREDENTIAL, strip=False),
                             "password") if password_given else None)
    settings = {"host": host, "port": port, "security": security, "username": username,
                "from_address": from_address, "from_name": from_name,
                "allowed_domains": _clean_domains(body)}
    will_have_password = bool(password) if password_given else password_stored
    if security == "none" and host and username and will_have_password and not is_loopback(host):
        raise invalid("security", "insecure_credentials",
                      "a password may only be sent without TLS to a server on this machine")
    return settings, password, password_given


def save_settings(conn: sqlite3.Connection, settings: Mapping[str, Any]) -> None:
    """Write *settings* under ``settings_json["smtp"]`` (joins the caller's transaction)."""
    with db.tx(conn):
        current = _org_settings(conn)
        current[SETTINGS_KEY] = dict(settings)
        conn.execute("UPDATE org SET settings_json = ? WHERE id = 1",
                     (json.dumps(current, ensure_ascii=False),))


# ── guards ───────────────────────────────────────────────────────────────────────────

def clean_recipients(to: object) -> list[str]:
    """1..20 distinct lower-cased addresses, or ``422 invalid_request`` (field ``to``)."""
    if isinstance(to, str) or not isinstance(to, Sequence):
        raise invalid("to", "type", "to must be a list of addresses")
    recipients: list[str] = []
    for item in to:
        email = normalize_email(item)
        if email is None:
            raise invalid("to", "invalid_email", "to holds an invalid email address")
        if email not in recipients:
            recipients.append(email)
    if not recipients:
        raise invalid("to", "too_few", "at least one recipient is required")
    if len(recipients) > MAX_EMAILS:
        raise invalid("to", "too_many", f"at most {MAX_EMAILS} recipients")
    return recipients


def check_recipients_allowed(settings: Mapping[str, Any], recipients: Sequence[str]) -> None:
    """``422 recipient_not_allowed`` naming every address outside ``allowed_domains``."""
    allowed = set(settings.get("allowed_domains") or ())
    if not allowed:
        return
    refused = [email for email in recipients if email.rsplit("@", 1)[-1] not in allowed]
    if refused:
        raise WorkspaceError("recipient_not_allowed",
                             "email may only go to the organisation's allowed domains", 422,
                             recipients=refused, allowed_domains=sorted(allowed))


def check_deliverable(conn: sqlite3.Connection, recipients: Sequence[str]) -> None:
    """Before a request is accepted: SMTP is configured and the recipients are allowed."""
    settings = stored_settings(conn)
    if not _is_configured(settings):
        raise not_configured()
    check_recipients_allowed(settings, recipients)


def _header(value: object, field: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise invalid(field, "type", f"{field} must be text")
    text = value.strip()
    if _HEADER_UNSAFE.search(text):
        raise invalid(field, "control_characters", f"{field} must be a single line")
    if not text:
        raise invalid(field, "required")
    if len(text) > max_len:
        raise invalid(field, "too_long")
    return text


def _body(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise invalid(field, "type", f"{field} must be text")
    # Lone surrogates (possible in model output) cannot be encoded; replace them.
    return value.encode("utf-8", "replace").decode("utf-8")


# ── sending ──────────────────────────────────────────────────────────────────────────

def _message(settings: Mapping[str, Any], recipients: Sequence[str], subject: str, text: str,
             html: str | None, reply_to: str | None) -> EmailMessage:
    message = EmailMessage()
    sender = settings["from_address"]
    message["Subject"] = subject
    message["From"] = Address(display_name=_HEADER_UNSAFE.sub(" ", settings["from_name"]).strip(),
                              addr_spec=sender)
    message["To"] = ", ".join(recipients)
    if reply_to:
        message["Reply-To"] = reply_to
    message["Date"] = formatdate(db.now(), usegmt=True)
    message["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
    # Scheduled reports are machine-sent: ask auto-responders not to answer them.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _open(settings: Mapping[str, Any]) -> smtplib.SMTP:
    """A connected (and, per ``security``, encrypted) client; closed again on failure."""
    host, port, security = settings["host"], settings["port"], settings["security"]
    if security == "ssl":
        return smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS,
                                context=tls_trust.trust_context())
    client = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
    if security == "starttls":
        try:
            client.ehlo()
            client.starttls(context=tls_trust.trust_context())
            client.ehlo()
        except BaseException:
            client.close()
            raise
    return client


def _causes(exc: BaseException) -> list[BaseException]:
    """*exc* and the exceptions it was raised from (smtplib wraps socket errors)."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain and len(chain) < 8:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _failure_reason(exc: BaseException) -> str:
    """A stable reason word for an SMTP failure (the most specific cause wins).

    ``smtplib`` reports a read timeout as ``SMTPServerDisconnected`` raised while
    handling the socket's ``TimeoutError``, so the whole chain is inspected.
    """
    answers: list[tuple[type[BaseException], str]] = [
        (smtplib.SMTPAuthenticationError, "auth_failed"),
        (smtplib.SMTPNotSupportedError, "not_supported"),
        (smtplib.SMTPRecipientsRefused, "recipients_refused"),
        (smtplib.SMTPSenderRefused, "sender_refused"),
        (smtplib.SMTPDataError, "data_refused"),
        (ssl.SSLError, "tls_failed"),
    ]
    for cls, reason in answers:
        if isinstance(exc, cls):
            return reason
    if any(isinstance(cause, TimeoutError) for cause in _causes(exc)):
        return "timeout"
    if isinstance(exc, smtplib.SMTPException) and not isinstance(exc,
                                                                 smtplib.SMTPServerDisconnected):
        return "smtp_error"
    return "connection_failed"


def _login(client: smtplib.SMTP, username: str, password: str) -> None:
    """Sign in to the server; a login it cannot encode fails as ``auth_failed``.

    ``smtplib`` sends the AUTH exchange as ASCII and raises ``UnicodeEncodeError`` for
    anything else — a login saved before :func:`parse_update` refused such values must
    still end as an honest ``smtp_failed``, never as an unhandled exception.
    """
    try:
        client.login(username, password)
    except UnicodeError as exc:
        logger.warning("the stored SMTP login is not ASCII, so signing in is impossible")
        raise _failed("auth_failed") from exc


def _deliver(recipients: list[str], subject: str, text: str, html: str | None,
             reply_to: str | None) -> list[str]:
    """Worker-thread half of :func:`send_mail`: settings, password, SMTP conversation."""
    conn = db.connect()
    try:
        settings = stored_settings(conn)
    finally:
        conn.close()
    if not _is_configured(settings):
        raise not_configured()
    check_recipients_allowed(settings, recipients)
    password = _read_password() if settings["username"] else None
    credentials = bool(settings["username"] and password)
    if settings["security"] == "none" and credentials and not is_loopback(settings["host"]):
        raise _failed("insecure_transport")
    message = _message(settings, recipients, subject, text, html, reply_to)
    try:
        with _open(settings) as client:
            if credentials:
                _login(client, settings["username"], password or "")
            refused = client.send_message(message, from_addr=settings["from_address"],
                                          to_addrs=recipients)
    except OSError as exc:  # smtplib.SMTPException, ssl.SSLError and timeouts included
        reason = _failure_reason(exc)
        logger.warning("sending email via %s:%s failed (%s, %s)", settings["host"],
                       settings["port"], reason, type(exc).__name__)
        raise _failed(reason) from exc
    accepted = [email for email in recipients if email not in refused]
    if refused:
        logger.warning("the mail server refused %d of %d recipients", len(refused), len(recipients))
    return accepted


async def send_mail(*, to: Sequence[str], subject: str, text: str, html: str | None = None,
                    reply_to: str | None = None) -> list[str]:
    """Send one message; returns the recipients the server accepted.

    Raises ``smtp_not_configured`` (409), ``recipient_not_allowed`` (422),
    ``invalid_request`` (422, a bad recipient or header), ``smtp_password_unreadable``
    (409) or ``smtp_failed`` (502, with ``reason``). Reads the settings through its own
    connection in a worker thread.
    """
    recipients = clean_recipients(to)
    clean_subject = _header(subject, "subject", MAX_SUBJECT)
    clean_reply_to = None
    if reply_to is not None:
        clean_reply_to = normalize_email(reply_to)
        if clean_reply_to is None:
            raise invalid("reply_to", "invalid_email")
    return await asyncio.to_thread(_deliver, recipients, clean_subject, _body(text, "text"),
                                   None if html is None else _body(html, "html"), clean_reply_to)


_TEST_MESSAGES = {
    "ro": ("Nerva Workspace — test de email",
           "Acesta este un mesaj de test trimis din consola de administrare Nerva Workspace.\n"
           "Dacă l-ați primit, trimiterea emailurilor funcționează.\n"),
    "en": ("Nerva Workspace — test email",
           "This is a test message sent from the Nerva Workspace admin console.\n"
           "If you received it, outgoing email works.\n"),
}


async def send_test(to: str, *, locale: str) -> dict[str, Any]:
    """Send the admin console's test message → ``{ok}`` or ``{ok: false, error, reason?}``."""
    subject, text = _TEST_MESSAGES.get(locale, _TEST_MESSAGES["ro"])
    try:
        await send_mail(to=[to], subject=subject, text=text)
    except WorkspaceError as exc:
        outcome: dict[str, Any] = {"ok": False, "error": exc.code}
        if "reason" in exc.extra:
            outcome["reason"] = exc.extra["reason"]
        return outcome
    return {"ok": True}
