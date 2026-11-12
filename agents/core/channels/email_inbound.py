"""email_inbound.py — what an inbound email is, before anything acts on it (H096).

Pure and offline: every function here takes an already-parsed :class:`email.message.Message`
and returns plain data. :mod:`agents.core.channels.email` owns the IMAP/SMTP transport.

Five jobs, each bounded:

- **Who sent it, as far as the receiving server could tell.** :func:`sender_auth` reads the
  ``Authentication-Results`` header (RFC 8601) the owner's mail provider stamped on the
  message: DMARC, DKIM and SPF results, and whether the domain that passed is aligned with
  the ``From`` domain. A sender can write that header too, so only one header is read: the
  one from an ``authserv-id`` the owner named (``EMAIL_TRUSTED_AUTHSERV_IDS``). Only that
  header can make a sender *verified*. When no id is named, the topmost header is read,
  but it can only report a failure, never a pass (if the receiving server adds no header,
  the topmost one is the sender's own). The header is tokenised by RFC 8601's rules
  (quoted strings, nested comments); anything malformed, or a message with several
  ``From`` headers, is *unverified*. An explicit DMARC result decides; DKIM/SPF alignment
  only decides when no DMARC result was reported. The verdict is shown on the inbox
  thread and on the reply's approval card; a message whose authentication was reported
  as *failed* is not routed, and ``EMAIL_REQUIRE_SENDER_AUTH`` admits only messages a
  configured server verified. It never grants anything; pairing still decides who is
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
import unicodedata
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

VERDICT_PASS = "pass"  # nosec B105 - DMARC verdict label, not a credential
VERDICT_FAIL = "fail"
VERDICT_NONE = "none"

_MSGID = re.compile(r"<[!-;=?-~]{1,250}>")   # printable ASCII, no '<', '>' or whitespace
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")
_RESULT_WORDS = frozenset({"pass", "fail", "softfail", "neutral", "none", "temperror",
                           "permerror", "policy", "hardfail", "quarantine", "reject"})
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
    #: ``configured`` (an authserv-id the owner named: the only basis that can verify),
    #: ``topmost`` (no id named; the topmost header, which may be the sender's own, so it
    #: can report a failure but never a pass), ``absent`` (no usable header), ``malformed``
    #: (the header did not parse) or ``ambiguous`` (several From headers or addresses).
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
        if self.basis == "topmost":
            return "unverified sender (no trusted mail server configured)"
        return "unverified sender"


SENDER_AUTH_KEYS = frozenset(SenderAuth().to_dict())
_BASES = frozenset({"configured", "topmost", "absent", "malformed", "ambiguous"})


def clean_sender_auth(value: object) -> dict | None:
    """A stored ``sender_auth`` record, re-validated; anything else is None."""
    if not isinstance(value, dict) or set(value) != SENDER_AUTH_KEYS:
        return None
    if value.get("verdict") not in {VERDICT_PASS, VERDICT_FAIL, VERDICT_NONE}:
        return None
    if value.get("basis") not in _BASES:
        return None
    if value["verdict"] == VERDICT_PASS and value["basis"] != "configured":
        return None   # only a configured server's header can verify a sender
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
    """Alignment, approximately relaxed: the same domain, or one a subdomain of the other.

    Deliberately stricter than DMARC's organizational-domain alignment (no public-suffix
    list ships with Nerva): two sibling subdomains of one organization do not align here,
    so such mail reads "unverified" in the no-DMARC fallback; it can never read "pass"
    falsely. When the server reports a DMARC result, that result decides instead."""
    if not domain or not from_domain:
        return False
    return (domain == from_domain or domain.endswith("." + from_domain)
            or from_domain.endswith("." + domain))


class _Malformed(ValueError):
    pass


def _scan(header: str) -> list[list[str]]:
    """Tokenise an Authentication-Results value (RFC 8601 / RFC 5322 lexical rules).

    Returns the ``;``-separated segments, each a list of tokens: words, ``"="``, and
    quoted-strings (unescaped, glued to any adjacent word characters, so
    ``"a;b"@example.com`` is one token). Comments are removed, nested ones included; a
    quoted string inside a comment is skipped whole (see below). An unterminated quoted
    string or comment, or a stray ``)``, raises :class:`_Malformed`."""
    segments: list[list[str]] = []
    tokens: list[str] = []
    buf: list[str] = []
    started = False
    i, n = 0, len(header)

    def flush():
        nonlocal started
        if started:
            tokens.append("".join(buf))
        buf.clear()
        started = False

    while i < n:
        c = header[i]
        if c == '"':
            started = True
            i += 1
            while True:
                if i >= n:
                    raise _Malformed("unterminated quoted-string")
                c = header[i]
                if c == "\\":
                    if i + 1 >= n:
                        raise _Malformed("dangling escape")
                    buf.append(header[i + 1])
                    i += 2
                    continue
                i += 1
                if c == '"':
                    break
                buf.append(c)
            continue
        if c == "(":
            flush()
            depth, i = 1, i + 1
            while depth:
                if i >= n:
                    raise _Malformed("unterminated comment")
                c = header[i]
                if c == "\\":
                    i += 2
                    continue
                if c == '"':
                    # A quoted local part the server echoes in its comment
                    # (``domain of "a)b"@x``) is opaque: its parentheses neither open
                    # nor close anything. Stricter than RFC 5322, where '"' is ctext.
                    end = i + 1
                    while end < n and header[end] != '"':
                        end += 2 if header[end] == "\\" else 1
                    if end >= n:
                        raise _Malformed("unterminated quoted-string in comment")
                    i = end + 1
                    continue
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                i += 1
            continue
        if c == ")":
            raise _Malformed("unbalanced comment")
        if c in " \t\r\n":
            flush()
        elif c == ";":
            flush()
            segments.append(tokens)
            tokens = []
        elif c == "=":
            flush()
            tokens.append("=")
        else:
            buf.append(c)
            started = True
        i += 1
    flush()
    segments.append(tokens)
    return segments


def _resinfo(tokens: list[str]) -> tuple[str, str, dict[str, list[str]]]:
    """``method = result (name = value)*`` → (method, result, {name: [values]})."""
    if len(tokens) < 3 or tokens[1] != "=" or "=" in (tokens[0], tokens[2]):
        raise _Malformed("bad resinfo")
    method = tokens[0].lower().split("/", 1)[0]
    result = tokens[2].lower()
    props: dict[str, list[str]] = {}
    rest = tokens[3:]
    if len(rest) % 3:
        raise _Malformed("bad property")
    for k in range(0, len(rest), 3):
        name, eq, value = rest[k:k + 3]
        if eq != "=" or "=" in (name, value):
            raise _Malformed("bad property")
        props.setdefault(name.lower(), []).append(value)
    return method, result, props


#: DMARC results that say the message failed DMARC (some servers name the action).
_DMARC_FAILED = frozenset({"fail", "quarantine", "reject"})
#: DMARC results after which only DKIM/SPF alignment may decide (no policy published).
_DMARC_FALLBACK = frozenset({"", "none"})


def _authserv_id(header: str) -> str:
    """Which server's header this is: the first word, before any comment or ``;``. A header
    whose rest is malformed is still recognised as that server's, then judged malformed."""
    first = re.split(r"[\s;(]", header.strip(), maxsplit=1)[0] if header.strip() else ""
    return first.lower() if _DOMAIN.fullmatch(first.lower()) else ""


def sender_auth(msg: Message, *, trusted_ids: frozenset[str] | None = None) -> SenderAuth:
    """Read the trusted ``Authentication-Results`` header of *msg*; see the module docstring.

    Only a header from an authserv-id the owner configured can verify a sender. Without
    one, the topmost header may still report a failure (a sender gains nothing by
    claiming one), but never a pass: when the receiving server stamps no header, the
    topmost one is the sender's own."""
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
    froms = msg.get_all("From") or []
    from_addrs = getaddresses([str(f) for f in froms])
    if len(froms) != 1 or len(from_addrs) != 1:
        return SenderAuth(basis="ambiguous")      # several From headers or addresses
    from_domain = _domain_of(from_addrs[0][1])
    if len(chosen) > _MAX_AUTH_HEADER_CHARS:
        return SenderAuth(basis="malformed")
    try:
        segments = _scan(_CTRL.sub(" ", chosen))
        if not segments[0] or segments[0][0] == "=":
            raise _Malformed("no authserv-id")
        sid = segments[0][0].lower()
        parsed = [_resinfo(seg) for seg in segments[1:] if seg and seg != ["none"]]
    except _Malformed:
        return SenderAuth(basis="malformed")
    sid = sid if _DOMAIN.fullmatch(sid) else ""
    dmarc_results: list[tuple[str, bool]] = []
    dkim_results: list[tuple[str, bool]] = []
    spf_results: list[tuple[str, bool]] = []
    for method, result, props in parsed:
        if result not in _RESULT_WORDS:
            continue
        if method == "dmarc":
            # DMARC's own header.from must be present and name the From domain.
            named = props.get("header.from", [])
            dmarc_results.append((result, len(named) == 1
                                  and _domain_of(named[0]) == from_domain != ""))
        elif method == "dkim":
            ds = props.get("header.d", []) or props.get("header.i", [])
            dkim_results.append((result, len(ds) == 1 and _aligned(_domain_of(ds[0]), from_domain)))
        elif method == "spf":
            # The MAIL FROM identity only: a HELO name says nothing about the From domain.
            mf = props.get("smtp.mailfrom", [])
            spf_results.append((result, len(mf) == 1 and _aligned(_domain_of(mf[0]), from_domain)))
    dmarc_words = {r for r, _ in dmarc_results}
    if dmarc_words & _DMARC_FAILED:
        dmarc = "fail"                      # a failure wins over any other dmarc result
    elif len(dmarc_words) == 1:
        dmarc = next(iter(dmarc_words))
    elif dmarc_words:
        dmarc = "permerror"                 # conflicting, neither a failure: undecided
    else:
        dmarc = ""
    dkim_pass_aligned = any(r == "pass" and al for r, al in dkim_results)
    spf_words = {r for r, _ in spf_results}
    spf_failed = bool(spf_words & {"fail", "hardfail"})
    spf_pass_aligned = not spf_failed and any(r == "pass" and al for r, al in spf_results)
    dkim = ("pass" if dkim_pass_aligned else
            next((r for r, _ in dkim_results if r == "fail"), dkim_results[0][0] if dkim_results else ""))
    spf = "fail" if spf_failed else (spf_results[0][0] if spf_results else "")
    if dmarc == "fail":
        verdict = VERDICT_FAIL
    elif dmarc == "pass":
        verdict = VERDICT_PASS if all(al for r, al in dmarc_results) else VERDICT_NONE
    elif dmarc in _DMARC_FALLBACK:
        if dkim_pass_aligned or spf_pass_aligned:
            verdict = VERDICT_PASS
        elif spf_failed and not any(r == "pass" for r, _ in dkim_results):
            verdict = VERDICT_FAIL
        else:
            verdict = VERDICT_NONE
    else:
        verdict = VERDICT_NONE              # temperror/permerror: nobody decided
    if verdict == VERDICT_PASS and basis != "configured":
        verdict = VERDICT_NONE              # nothing vouches for who wrote this header
    return SenderAuth(verdict=verdict, dmarc=dmarc, dkim=dkim, spf=spf,
                      aligned=verdict == VERDICT_PASS, authserv_id=sid, basis=basis)


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
    """A file name safe to show: no control or format characters (Unicode category Cc/Cf,
    which includes the bidi overrides U+202A-202E and isolates U+2066-2069 that can make
    ``invoice\u202Efdp.exe`` read as ``invoiceexe.pdf``), no path separators, bounded."""
    text = "".join(ch for ch in str(name or "")
                   if unicodedata.category(ch) not in {"Cc", "Cf", "Zl", "Zp"})
    text = text.replace("/", "_").replace("\\", "_").strip()
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
