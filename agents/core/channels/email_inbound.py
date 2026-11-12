"""email_inbound.py — what an inbound email is, before anything acts on it (H096).

Pure and offline: every function here takes an already-parsed :class:`email.message.Message`
and returns plain data. :mod:`agents.core.channels.email` owns the IMAP/SMTP transport.

Five jobs, each bounded:

- **Who sent it, as far as the receiving server could tell.** :func:`sender_auth` reads the
  ``Authentication-Results`` header (RFC 8601) the owner's mail provider stamped on the
  message: DMARC, DKIM and SPF results, and whether the domain that passed is aligned with
  the ``From`` domain. A sender can write that header too, so only one header is read: the
  one from an ``authserv-id`` the owner named (``EMAIL_TRUSTED_AUTHSERV_IDS``), or, when
  none is named, the topmost one — the header the receiving server adds last, above
  anything the sender wrote. The verdict is information for the owner (it is shown on the
  inbox thread and on the reply's approval card) and one refusal: a message whose
  authentication *failed* is not routed at all, so a forged ``From`` of a paired address
  cannot speak as that address. It never grants anything; pairing still decides who is
  heard.
- **Whether a person wrote it.** :func:`automated_reason` names auto-replies, bounces,
  mailing lists, no-reply senders and our own address, so a vacation responder cannot
  start a reply loop.
- **What it says.** :func:`extract_body` takes the first text/plain part, or strips the
  HTML part to text when there is no plain one (scripts, styles and markup dropped).
- **What came with it.** :func:`attachments` lists the attached files (bounded in count and
  size); the channel decides which are read.
- **What a reply must quote to stay in the thread.** :func:`threading_headers` gives the
  ``Message-ID`` and a bounded ``References`` chain, each id checked against a strict shape
  so nothing a sender wrote can inject a header line into the reply.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from email.message import Message
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser

MAX_BODY_CHARS = 20_000
MAX_DECODE_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_TEXT_ATTACHMENT_CHARS = 8_000
MAX_REFERENCES = 10
MAX_SUBJECT_CHARS = 200
_MAX_AUTH_HEADER_CHARS = 4_000
_MAX_NAME_CHARS = 120

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_NONE = "none"

_MSGID = re.compile(r"<[!-;=?-~]{1,250}>")   # printable ASCII, no '<', '>' or whitespace
_COMMENT = re.compile(r"\([^()]*\)")
_METHOD = re.compile(r"\s*(dmarc|dkim|spf)\s*=\s*([a-z]+)", re.IGNORECASE)
_PROP = re.compile(r"(header\.from|header\.d|header\.i|smtp\.mailfrom|smtp\.helo)\s*=\s*([^\s;]+)",
                   re.IGNORECASE)
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")
_RESULT_WORDS = frozenset({"pass", "fail", "softfail", "neutral", "none", "temperror",
                           "permerror", "policy", "hardfail"})
_NO_REPLY_LOCAL = re.compile(
    r"^(?:no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer[-_.]?daemon|postmaster|bounces?|"
    r"notifications?|auto[-_.]?reply)(?:[+-].*)?$", re.IGNORECASE)
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class SenderAuth:
    """What the receiving server said about who sent a message."""

    verdict: str = VERDICT_NONE
    dmarc: str = ""
    dkim: str = ""
    spf: str = ""
    aligned: bool = False
    authserv_id: str = ""
    #: ``configured`` (an authserv-id the owner named), ``topmost`` (no id named; the
    #: header nearest the receiving server) or ``absent`` (no usable header).
    basis: str = "absent"

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "dmarc": self.dmarc, "dkim": self.dkim,
                "spf": self.spf, "aligned": self.aligned,
                "authserv_id": self.authserv_id, "basis": self.basis}

    @property
    def label(self) -> str:
        """One short phrase for a card: ``verified sender``, ``sender authentication
        FAILED`` or ``unverified sender``."""
        if self.verdict == VERDICT_PASS:
            return "verified sender"
        if self.verdict == VERDICT_FAIL:
            return "sender authentication FAILED"
        return "unverified sender"


SENDER_AUTH_KEYS = frozenset(SenderAuth().to_dict())


def clean_sender_auth(value: object) -> dict | None:
    """A stored ``sender_auth`` record, re-validated; anything else is None."""
    if not isinstance(value, dict) or set(value) != SENDER_AUTH_KEYS:
        return None
    if value.get("verdict") not in {VERDICT_PASS, VERDICT_FAIL, VERDICT_NONE}:
        return None
    if value.get("basis") not in {"configured", "topmost", "absent"}:
        return None
    if type(value.get("aligned")) is not bool:
        return None
    out = {"verdict": value["verdict"], "basis": value["basis"], "aligned": value["aligned"]}
    for key in ("dmarc", "dkim", "spf"):
        result = value.get(key)
        if not isinstance(result, str) or (result and result not in _RESULT_WORDS):
            return None
        out[key] = result
    sid = value.get("authserv_id")
    if not isinstance(sid, str) or (sid and _DOMAIN.fullmatch(sid) is None):
        return None
    out["authserv_id"] = sid
    return out


def _domain_of(value: str) -> str:
    value = str(value or "").strip().strip("<>").lower()
    if "@" in value:
        value = value.rsplit("@", 1)[1]
    value = value.rstrip(".")
    return value if _DOMAIN.fullmatch(value) and "." in value else ""


def _aligned(domain: str, from_domain: str) -> bool:
    """Relaxed alignment: the same domain, or one a subdomain of the other."""
    if not domain or not from_domain:
        return False
    return (domain == from_domain or domain.endswith("." + from_domain)
            or from_domain.endswith("." + domain))


def _authserv_id(header: str) -> str:
    first = header.split(";", 1)[0].strip().split()
    return first[0].lower() if first else ""


def sender_auth(msg: Message, *, trusted_ids: frozenset[str] | None = None) -> SenderAuth:
    """Read the trusted ``Authentication-Results`` header of *msg*; see the module docstring."""
    headers = [str(h) for h in (msg.get_all("Authentication-Results") or [])]
    chosen = ""
    basis = "absent"
    trusted = frozenset(i.strip().lower() for i in (trusted_ids or ()) if i and i.strip())
    if trusted:
        for header in headers:   # topmost first
            if _authserv_id(header) in trusted:
                chosen, basis = header, "configured"
                break
    elif headers:
        chosen, basis = headers[0], "topmost"
    if not chosen:
        return SenderAuth()
    chosen = _CTRL.sub(" ", chosen[:_MAX_AUTH_HEADER_CHARS])
    sid = _authserv_id(chosen)
    sid = sid if _DOMAIN.fullmatch(sid or "") else ""
    from_domain = _domain_of(parseaddr(str(msg.get("From", "")))[1])
    results: dict[str, tuple[str, bool]] = {}
    for resinfo in _COMMENT.sub(" ", chosen).split(";")[1:]:
        found = _METHOD.match(resinfo)
        if not found:
            continue
        method, result = found.group(1).lower(), found.group(2).lower()
        if result not in _RESULT_WORDS or method in results:
            continue   # the first result per method counts
        props = {k.lower(): v for k, v in _PROP.findall(resinfo)}
        if method == "dmarc":
            dom = _domain_of(props.get("header.from", "")) or from_domain
        elif method == "dkim":
            dom = _domain_of(props.get("header.d", "") or props.get("header.i", ""))
        else:
            dom = _domain_of(props.get("smtp.mailfrom", "") or props.get("smtp.helo", ""))
        results[method] = (result, _aligned(dom, from_domain))
    dmarc, dmarc_al = results.get("dmarc", ("", False))
    dkim, dkim_al = results.get("dkim", ("", False))
    spf, spf_al = results.get("spf", ("", False))
    if (dmarc == "pass" and dmarc_al) or (dkim == "pass" and dkim_al) or (spf == "pass" and spf_al):
        verdict, aligned = VERDICT_PASS, True
    elif dmarc == "fail" or (dmarc in {"", "none"} and dkim in {"", "fail", "none", "permerror"}
                             and spf in {"fail", "hardfail"}):
        verdict, aligned = VERDICT_FAIL, False
    else:
        verdict, aligned = VERDICT_NONE, False
    return SenderAuth(verdict=verdict, dmarc=dmarc, dkim=dkim, spf=spf, aligned=aligned,
                      authserv_id=sid, basis=basis)


def automated_reason(msg: Message, *, own_addresses: frozenset[str] = frozenset()) -> str | None:
    """Why *msg* was not written by a person (``None`` when nothing says so)."""
    sender = parseaddr(str(msg.get("From", "")))[1].strip().lower()
    if sender and sender in own_addresses:
        return "own_address"
    auto = str(msg.get("Auto-Submitted", "") or "").strip().lower()
    if auto and auto != "no":
        return "auto_submitted"
    if str(msg.get("Precedence", "") or "").strip().lower() in {"bulk", "junk", "list", "auto_reply"}:
        return "precedence"
    if msg.get("List-Id") or msg.get("List-Unsubscribe"):
        return "mailing_list"
    for name in ("X-Autoreply", "X-Autorespond", "X-Auto-Reply"):
        if msg.get(name):
            return "auto_reply"
    return_path = msg.get("Return-Path")
    if return_path is not None and str(return_path).strip() in {"<>", ""}:
        return "bounce"
    if msg.get_content_type() == "multipart/report":
        return "bounce"
    local = sender.split("@", 1)[0] if "@" in sender else ""
    if local and _NO_REPLY_LOCAL.match(local):
        return "no_reply_sender"
    return None


class _HTMLText(HTMLParser):
    _SKIP = frozenset({"script", "style", "head", "title", "noscript", "template"})
    _BLOCK = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
                        "blockquote", "pre", "table", "ul", "ol", "hr", "section", "article"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self.size = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip and self.size < MAX_BODY_CHARS * 2:
            self.parts.append(data)
            self.size += len(data)


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    try:
        parser.feed(str(html or "")[:MAX_DECODE_BYTES])
        parser.close()
    except Exception:
        return ""
    text = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out[:MAX_BODY_CHARS]


def _decode(part: Message) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        return ""
    if not isinstance(payload, bytes | bytearray):
        return ""
    payload = bytes(payload[:MAX_DECODE_BYTES])
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _is_attachment(part: Message) -> bool:
    disposition = str(part.get("Content-Disposition", "") or "").split(";", 1)[0].strip().lower()
    return disposition == "attachment" or (disposition == "inline" and bool(part.get_filename()))


def extract_body(msg: Message) -> str:
    """The first text/plain body part, else the first text/html part as plain text."""
    plain = html = None
    parts = msg.walk() if msg.is_multipart() else [msg]
    for count, part in enumerate(parts):
        if count > 200:
            break
        if part.is_multipart() or _is_attachment(part):
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and plain is None:
            plain = _decode(part)
            break
        if ctype == "text/html" and html is None:
            html = _decode(part)
    if plain is not None:
        return plain[:MAX_BODY_CHARS]
    if html is not None:
        return html_to_text(html)
    return ""


@dataclass(frozen=True)
class InboundAttachment:
    name: str
    mime: str
    size: int
    data: bytes | None   # None when it was too large to hold

    @property
    def kind(self) -> str:
        if self.mime.startswith("image/"):
            return "image"
        if self.mime.startswith("text/") or self.mime in {"application/json", "application/csv"}:
            return "text"
        return "file"


def clean_name(name: object) -> str:
    text = _CTRL.sub("", str(name or "")).replace("/", "_").replace("\\", "_").strip()
    return text[:_MAX_NAME_CHARS] or "attachment"


def attachments(msg: Message, *, max_count: int = MAX_ATTACHMENTS,
                max_bytes: int = MAX_ATTACHMENT_BYTES) -> tuple[list[InboundAttachment], int]:
    """The attached files (at most *max_count*), and how many more were left out."""
    found: list[InboundAttachment] = []
    skipped = 0
    if not msg.is_multipart():
        return found, 0
    for count, part in enumerate(msg.walk()):
        if count > 200:
            break
        if part.is_multipart() or not _is_attachment(part):
            continue
        if len(found) >= max_count:
            skipped += 1
            continue
        try:
            data = part.get_payload(decode=True)
        except Exception:
            data = None
        data = bytes(data) if isinstance(data, bytes | bytearray) else b""
        size = len(data)
        found.append(InboundAttachment(
            name=clean_name(part.get_filename()),
            mime=part.get_content_type().lower()[:100],
            size=size,
            data=data if 0 < size <= max_bytes else None,
        ))
    return found, skipped


def text_attachment(att: InboundAttachment, *, source: str = "email.attachment") -> str:
    """A text attachment as fenced, JSON-encoded data (a raw newline could close the fence)."""
    from agents.core.security.quarantine import fence_tool_result

    if att.data is None:
        return ""
    text = att.data.decode("utf-8", errors="replace")[:MAX_TEXT_ATTACHMENT_CHARS]
    fenced, _flags = fence_tool_result(json.dumps(text, ensure_ascii=False), source=source)
    return fenced


def message_id(value: object) -> str:
    """One message id in ``<…>`` form, or ``""`` when it is not one."""
    found = _MSGID.search(str(value or ""))
    return found.group(0) if found else ""


def threading_headers(msg: Message) -> dict:
    """``message_id`` and ``references`` for a reply that stays in this thread."""
    own = message_id(msg.get("Message-ID", ""))
    chain = [m.group(0) for m in _MSGID.finditer(str(msg.get("References", "") or "")[:20_000])]
    if not chain:
        parent = message_id(msg.get("In-Reply-To", ""))
        chain = [parent] if parent else []
    if own:
        chain.append(own)
    seen: list[str] = []
    for item in chain:
        if item not in seen:
            seen.append(item)
    return {"message_id": own, "references": " ".join(seen[-MAX_REFERENCES:]) if own else ""}


def valid_references(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 2_600:
        return False
    items = value.split(" ")
    return 0 < len(items) <= MAX_REFERENCES and all(_MSGID.fullmatch(i) for i in items)


def clean_subject(value: object) -> str:
    return " ".join(_CTRL.sub(" ", str(value or "")).split())[:MAX_SUBJECT_CHARS]


def reply_subject(value: object) -> str:
    subject = clean_subject(value)
    return subject if subject.lower().startswith("re:") else f"Re: {subject}".strip()


def own_addresses(*values: object) -> frozenset[str]:
    return frozenset(addr.strip().lower() for _n, addr in getaddresses([str(v or "") for v in values])
                     if "@" in addr)


__all__ = [
    "InboundAttachment", "MAX_ATTACHMENTS", "SENDER_AUTH_KEYS", "SenderAuth", "VERDICT_FAIL",
    "VERDICT_NONE", "VERDICT_PASS", "attachments", "automated_reason", "clean_sender_auth",
    "clean_name", "clean_subject", "extract_body", "html_to_text", "message_id", "own_addresses",
    "reply_subject", "sender_auth", "text_attachment", "threading_headers", "valid_references",
]
