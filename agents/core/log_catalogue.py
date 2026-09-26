"""log_catalogue.py — H410: mask the credentials no vendor shape names, and the
Romanian identifiers, on every log handler the H495 redactor covers.

``security/log_redaction`` masks what ``SecretScanner`` recognises by its *shape*:
a vendor prefix (``sk-ant-``, ``ghp_``, ``AIza``), a quoted ``api_key="…"``, a long
high-entropy run. An opaque token matches none of those, so it went into the log
whenever it was carried by something that *names* it as a credential:

- a query parameter — ``GET /cb?access_token=<opaque>``;
- a body or form key, unquoted or quoted — ``client_secret=Zx81…``,
  ``{"refresh_token": "…"}``;
- a header — ``X-Api-Key: 9f8e…``, ``Authorization: Token …``, ``Cookie: …``.

This module masks by that name instead (the ``CATALOGUE`` below: the parameter,
key and header names that carry credentials in the protocols this hub speaks).
It also runs the two checksum-confirmed Romanian identifiers from ``PIIScanner``
— a CNP (control digit) and an IBAN (ISO 7064 mod-97, compact or spaced in groups
of four) — which the H495 filter never ran. The other PII patterns stay out: an
e-mail address or a phone number in a log is often the point of the line, and
card and SSN shapes carry no checksum here.

It is ADDITIVE and lives outside ``security/``: the H495 filter is reused
unchanged, with this module's scanner in place of ``SecretScanner`` —
``SecretRedactionFilter`` already masks in place while keeping ``record.args``
(uvicorn's ``AccessFormatter`` unpacks exactly five), masks tracebacks and stack
info, fails closed to ``[redaction-unavailable]`` and obeys the one
``JARVIS_LOG_REDACTION`` switch, snapshotted at import. ``CatalogueRedactionFilter``
wraps it rather than subclassing it, so the H495 installer — which skips a handler
already carrying a ``SecretRedactionFilter`` — never mistakes this filter for its
own. ``core.log`` installs both, the H495 filter first.

A name, not a shape, is what makes a value a credential here, so the catalogue
masks any value behind a credential-bearing *query parameter* however short
(``?token=abc``), but a free-standing ``key=value`` only when the value looks like
one (six characters or more), and a scheme-less ``Authorization:`` only when it is
at least twelve characters and carries a digit — ``Authorization: denied`` stays.
A bare ``key`` parameter is not in the catalogue: settings routes use it for a
setting's name, and the key formats that ride on it (``AIza…``) are masked by shape.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from agents.core.security.log_redaction import SecretRedactionFilter
from agents.core.security.scanner import PIIScanner, is_valid_cnp, is_valid_iban
from agents.core.security.types import ScanFinding, ScanResult, ThreatLevel

logger = logging.getLogger("jarvis.log_catalogue")

#: Query parameters whose value is a credential, whatever it looks like.
QUERY_PARAMS = (
    "access_token", "refresh_token", "id_token", "token", "auth_token", "auth",
    "api_key", "api-key", "apikey", "client_secret", "secret", "password", "passwd", "pwd",
    "signature", "sig", "x-amz-signature", "x-amz-security-token", "x-amz-credential",
    "session", "sessionid", "session_id", "jwt",
)
#: Body, form and structured-log keys whose value is a credential (hyphenated header
#: names are the header rule's: ``\b`` would find ``api-key`` inside ``X-Api-Key``).
SECRET_KEYS = (
    "access_token", "refresh_token", "id_token", "client_secret", "api_key", "apikey",
    "secret_key", "private_key", "auth_token", "session_token", "app_secret", "webhook_secret",
    "signing_secret", "access_key",
)
#: Headers whose whole value is a credential.
SECRET_HEADERS = (
    "x-api-key", "x-api-token", "x-auth-token", "x-access-token", "x-goog-api-key",
    "x-user-token", "x-admin-token", "api-key", "x-webhook-token",
)
#: ``Authorization`` schemes; the credential is the word after the scheme.
AUTH_SCHEMES = ("bearer", "basic", "token", "digest", "apikey", "api-key", "key", "hmac", "negotiate")

_NOT_MASKED = r"(?!\[REDACTED)"


def _alternation(names: Iterable[str]) -> str:
    return "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))


@dataclass(frozen=True)
class _Rule:
    name: str
    pattern: re.Pattern
    keep: int                                   # the group kept before the mask
    validator: Callable[[str], bool] | None = None
    value: int = 0                              # the group a validator checks (0: whole match)


def _rules() -> tuple[_Rule, ...]:
    q, k, h = _alternation(QUERY_PARAMS), _alternation(SECRET_KEYS), _alternation(SECRET_HEADERS)
    s = _alternation(AUTH_SCHEMES)
    i = re.IGNORECASE
    return (
        # ?access_token=… / &sig=…: any value, up to the next separator.
        _Rule("query_secret", re.compile(rf"([?&;](?:{q})=){_NOT_MASKED}[^&#\s\"'<>]+", i), 1),
        # "client_secret": "…"  /  'refresh_token': '…'  /  client_secret="…"
        # (one rule per quote, so no backreference keeps the prefilter from building)
        *(_Rule("secret_field", re.compile(
            rf"((?:{qt}(?:{k}){qt}|\b(?:{k}))\s*[=:]\s*{qt}){_NOT_MASKED}[^{qt}\r\n]+(?={qt})", i), 1)
          for qt in ('"', "'")),
        # client_secret=Zx81…  (unquoted: a credential-looking value, 6 chars or more)
        _Rule("secret_field", re.compile(rf"(\b(?:{k})\s*[=:]\s*){_NOT_MASKED}[^\s&,;\"'<>(){{}}\[\]]{{6,}}", i), 1),
        # Authorization: Token abc…   /   'Authorization': 'Basic …'  (Proxy-Authorization too:
        # \b holds after its hyphen)
        _Rule("auth_header", re.compile(
            rf"(\bauthorization[\"']?\s*[:=]\s*[\"']?(?:{s})\s+){_NOT_MASKED}[^\s,;\"']+", i), 1),
        # Authorization: abc123…  (no scheme: 12 chars or more, with a digit)
        _Rule("auth_header", re.compile(
            rf"(\bauthorization[\"']?\s*[:=]\s*[\"']?)(?!(?:{s})\s){_NOT_MASKED}"
            rf"(?=[^\s,;\"']*\d)[^\s,;\"']{{12,}}", i), 1),
        # X-Api-Key: 9f8e…   /   'x-api-key': '…'
        _Rule("api_key_header", re.compile(
            rf"(\b(?:{h})[\"']?\s*:\s*[\"']?){_NOT_MASKED}[^\s,;\"']+", i), 1),
        # Cookie: a=b; c=d   /   Set-Cookie: sid=…; HttpOnly — the whole value.
        _Rule("cookie_header", re.compile(
            rf"(\b(?:set-)?cookie[\"']?\s*:\s*[\"']?){_NOT_MASKED}[^\r\n\"']+", i), 1),
        # Romanian identifiers, only when their checksum holds (PIIScanner's patterns).
        _Rule("ro_cnp", re.compile(PIIScanner.PATTERNS["ro_cnp"][0]), 0, is_valid_cnp),
        _Rule("ro_iban", re.compile(PIIScanner.PATTERNS["ro_iban"][0]), 0, is_valid_iban),
        _Rule("ro_iban", re.compile(r"\b[Rr][Oo]\d{2}(?: [A-Za-z0-9]{4}){5}\b"), 0, is_valid_iban),
    )


class CatalogueScanner:
    """The scanner ``SecretRedactionFilter`` runs: ``redact`` and ``scan``, plus the
    ``_compiled`` rows its prefilter is built from (so a line that names nothing in
    the catalogue skips the per-rule work)."""

    scanner_id = "log_catalogue"

    def __init__(self) -> None:
        self._rules = _rules()
        self._compiled = [(r.name, r.pattern, ThreatLevel.HIGH, f"log catalogue: {r.name}") for r in self._rules]

    @staticmethod
    def _masked(rule: _Rule, match: re.Match) -> str:
        if rule.validator is not None and not rule.validator(match.group(rule.value)):
            return match.group(0)
        kept = match.group(rule.keep) if rule.keep else ""
        return f"{kept}[REDACTED:{rule.name}]"

    def redact(self, text: str) -> str:
        for rule in self._rules:
            text = rule.pattern.sub(lambda m, _r=rule: self._masked(_r, m), text)
        return text

    def scan(self, text: str) -> ScanResult:
        result = ScanResult()
        for rule in self._rules:
            for match in rule.pattern.finditer(text):
                if rule.validator is not None and not rule.validator(match.group(rule.value)):
                    continue
                result.findings.append(ScanFinding(
                    pattern_name=rule.name, matched_text=match.group(), threat_level=ThreatLevel.HIGH,
                    start=match.start(), end=match.end(), description=f"log catalogue: {rule.name}"))
        return result


class CatalogueRedactionFilter(logging.Filter):
    """The H495 filter's machinery over the catalogue scanner. Attach to a handler."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._inner = SecretRedactionFilter(scanner=CatalogueScanner())

    def redact_text(self, text: str) -> str:
        return self._inner.redact_text(text)

    def filter(self, record: logging.LogRecord) -> bool:
        return self._inner.filter(record)


_UNCOVERED_HANDLERS = 0


def uncovered_handler_count() -> int:
    """Handlers the most recent install could not cover (0 when clean)."""
    return _UNCOVERED_HANDLERS


def _is_catalogue(obj: object) -> bool:
    # By name, like the H495 cleanup: the tree is importable as agents.core.* and
    # core.*, so one file can be two classes.
    return type(obj).__name__ == "CatalogueRedactionFilter"


def _cover(loggers: Iterable[logging.Logger], shared: list) -> tuple[int, int]:
    added = refused = 0
    for lg in loggers:
        for handler in list(getattr(lg, "handlers", ()) or ()):
            try:
                if any(_is_catalogue(f) for f in (getattr(handler, "filters", ()) or ())):
                    continue
                if not shared:
                    shared.append(CatalogueRedactionFilter())
                handler.addFilter(shared[0])
                added += 1
            except Exception:
                refused += 1
    return added, refused


def _report(refused: int) -> None:
    global _UNCOVERED_HANDLERS
    _UNCOVERED_HANDLERS = refused
    if refused:
        logger.warning("Log catalogue redaction could not be attached to %d handler(s); records "
                       "written through them are NOT masked for named credentials or CNP/IBAN", refused)


def install_catalogue_redaction(target: logging.Logger | None = None) -> int:
    """Cover the handlers one logger owns (root by default); the number newly covered."""
    added, refused = _cover([logging.getLogger() if target is None else target], [])
    _report(refused)
    return added


def install_catalogue_redaction_everywhere() -> int:
    """Cover the root handlers and every other logger's own, as the H495 installer does
    (a logger with ``propagate = False`` never reaches root). Idempotent."""
    loggers = [logging.getLogger()]
    try:
        loggers += [obj for obj in list(logging.Logger.manager.loggerDict.values())
                    if isinstance(obj, logging.Logger)]
    except Exception:
        logger.warning("Could not enumerate the logger registry; only the root handlers get the "
                       "log catalogue", exc_info=True)
    added, refused = _cover(loggers, [])
    _report(refused)
    return added
