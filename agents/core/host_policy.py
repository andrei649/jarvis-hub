"""
host_policy.py — the Host-header guard for the local API (Hermes absorption 5b).

The threat is DNS rebinding. A page on ``evil.example`` is opened in the owner's
browser; its name first resolves to the attacker's server (which serves the page)
and then, on the next lookup, to ``127.0.0.1`` or the box's LAN address. The
browser's same-origin rule is satisfied — the origin is still ``evil.example`` —
so the page's scripts now read and drive the hub's API from inside the victim's
network, with the victim's loopback origin. The only thing that gives the trick
away is the ``Host`` header: it carries the attacker's name, and nothing
legitimate ever does. Refusing a request whose ``Host`` is not one of the names
this box answers to closes the hole with no configuration for the common cases:
loopback names, the address the server is bound to, the address the request
arrived on, and any IP literal (an IP literal cannot be a rebound DNS name — this
is what keeps a LAN install reached by its address working out of the box).
Names beyond that (a tailnet name, a domain behind a reverse proxy) are declared
in ``JARVIS_ALLOWED_HOSTS``; a wildcard there is refused at boot because it would
turn the guard back off.

Only the header's shape is ever logged or returned in an error — the value is
attacker-chosen text and stays out of logs and response bodies.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from ipaddress import ip_address

from agents.core.env_config import env_str

logger = logging.getLogger("jarvis.host_policy")

ALLOWED_HOSTS_ENV = "JARVIS_ALLOWED_HOSTS"
MAX_HOSTS = 64
MAX_HOST_CHARS = 253
# A Host header may carry brackets and a port on top of the name; anything longer
# than that is not a host name and is dropped before any parsing happens.
_MAX_HEADER_CHARS = MAX_HOST_CHARS + len("[]:65535")
# Names a request from the same box legitimately carries. ``0.0.0.0`` and ``::``
# appear because a bind-all server reports them as its own address and answers
# a request addressed to them from the same box; they are unroutable elsewhere,
# so accepting them widens nothing.
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"})  # nosec B104 — a Host name compared against, never a socket bind
# Characters that never occur in a host name; their presence means the header
# was crafted (a path, credentials, a query) rather than typed by a client.
_FORBIDDEN_HOST_CHARS = frozenset(" \t/\\@?#")

_memo_key: str | None = None
_memo_value: tuple[str, ...] = ()


def normalize_host(header: str) -> str:
    """Canonical host name from a ``Host`` header; ``""`` on anything unreadable.

    Strips surrounding whitespace, IPv6 brackets, one trailing dot and a numeric
    port, then lower-cases. ``[::1]:8000`` becomes ``::1`` while a bare ``::1``
    is left alone — a bare IPv6 literal carries more than one colon and never a
    port, so text with several colons is accepted only when it really is an IPv6
    address (``localhost:8000:9000`` is a typo, not a host, and must not become
    an allowlist entry that never matches). Over ``MAX_HOST_CHARS`` or containing
    a character no host name has → ``""``, so the caller refuses rather than
    guesses.
    """
    text = header.strip()
    if not text or len(text) > _MAX_HEADER_CHARS:
        return ""
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            return ""
        host = text[1:end]
        rest = text[end + 1:]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return ""
    elif text.count(":") > 1:
        host = text
        if not is_ip_literal(host.split("%", 1)[0]):
            return ""
    else:
        host, separator, port = text.partition(":")
        if separator and not port.isdigit():
            return ""
    if host.endswith("."):
        host = host[:-1]
    host = host.lower()
    if not host or len(host) > MAX_HOST_CHARS:
        return ""
    if any(char in _FORBIDDEN_HOST_CHARS for char in host):
        return ""
    return host


def is_ip_literal(host: str) -> bool:
    """True when *host* is an IPv4 or IPv6 address, not a name."""
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


def parse_allowed_hosts(raw: str, *, variable: str = ALLOWED_HOSTS_ENV) -> tuple[str, ...]:
    """Parse a comma-separated list of extra host names, normalised.

    Refused with a ``ValueError`` naming the variable and the entry's position
    (never the value): a wildcard (``*`` anywhere), a leading-dot suffix
    wildcard, an entry carrying a scheme or a path, anything that does not
    normalise to a host name, and more than ``MAX_HOSTS`` entries. Any of those
    would either turn the guard off or admit a name that was not meant.
    """
    entries = [part.strip() for part in raw.split(",")]
    entries = [entry for entry in entries if entry]
    if len(entries) > MAX_HOSTS:
        raise ValueError(f"{variable}: too many entries ({len(entries)} > {MAX_HOSTS})")
    hosts: list[str] = []
    for position, entry in enumerate(entries, start=1):
        if "*" in entry:
            raise ValueError(f"{variable}: entry {position} is a wildcard, which would disable the Host guard")
        if entry.startswith("."):
            raise ValueError(f"{variable}: entry {position} is a leading-dot suffix wildcard, which is not allowed")
        if "://" in entry or "/" in entry:
            raise ValueError(f"{variable}: entry {position} carries a scheme or a path; give a bare host name")
        host = normalize_host(entry)
        if not host:
            raise ValueError(f"{variable}: entry {position} is not a host name")
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def allowed_hosts() -> tuple[str, ...]:
    """The operator's extra host names, memoised on the raw env string.

    Unset or empty → ``()``. A malformed value → ``()`` with one warning per
    distinct value; refusing is the boot guard's job
    (:func:`assert_parseable_allowed_hosts`), and at request time the closed
    answer is the safe one.
    """
    global _memo_key, _memo_value
    raw = env_str(ALLOWED_HOSTS_ENV)   # env_config is the one parse home (AUD-14)
    if raw == _memo_key:
        return _memo_value
    if not raw.strip():
        hosts: tuple[str, ...] = ()
    else:
        try:
            hosts = parse_allowed_hosts(raw)
        except ValueError as exc:
            logger.warning("%s; accepting no extra host names", exc)
            hosts = ()
    _memo_key, _memo_value = raw, hosts
    return hosts


def host_accepted(
    host_header: str, *, bind_host: str, server_host: str, allowed: tuple[str, ...],
) -> bool:
    """Decide whether a request's ``Host`` names this box.

    The threat, exactly: a page on ``evil.example`` whose name has been re-pointed
    at this box's address gets same-origin access to the API from the victim's
    browser. The ``Host`` header of those requests carries the attacker's name,
    and nothing legitimate ever does. Accepted, in order: a loopback name; any IP
    literal (an address cannot be a rebound DNS name, and this keeps a LAN
    install reached by its address working with no configuration); the address
    the server is bound to; the address the request arrived on; a name the
    operator listed. An empty or unreadable header is refused — a browser always
    sends one.
    """
    host = normalize_host(host_header)
    if not host:
        return False
    if host in LOOPBACK_NAMES:
        return True
    if is_ip_literal(host):
        return True
    if host == normalize_host(bind_host) or host == normalize_host(server_host):
        return True
    return host in allowed


def assert_parseable_allowed_hosts(environ: Mapping[str, str] | None = None) -> None:
    """Refuse boot when ``JARVIS_ALLOWED_HOSTS`` is set but cannot be parsed.

    Silently accepting no extra names would leave a proxied or tailnet install
    answering 400 to every request, and the operator's likely next move — a
    wildcard — would switch the guard off. Unset and empty are fine. The message
    names the variable and the remedies, never the value.
    """
    env = os.environ if environ is None else environ
    raw = env.get(ALLOWED_HOSTS_ENV)
    if raw is None or not raw.strip():
        return
    try:
        parse_allowed_hosts(raw)
    except ValueError as exc:
        raise SystemExit(
            f"Refusing to start: {exc}.\n"
            f"Set {ALLOWED_HOSTS_ENV} to a comma-separated list of bare host names this box "
            f"answers to (at most {MAX_HOSTS}; no wildcard, scheme, path or leading dot), "
            f"or unset it — loopback names, IP literals and the bound address are always accepted."
        ) from None
