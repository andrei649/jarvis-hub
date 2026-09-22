"""
proxy_trust.py — reverse-proxy trust as a bounded CIDR allowlist (Hermes absorption 5b).

Why a list of networks and not a switch. The hub used to carry one boolean,
``JARVIS_TRUSTED_PROXY``, and once it was on the first ``X-Forwarded-For`` hop was
believed from *any* socket peer. Two gates key on the resolved client address: the
localhost auth bypass (no token configured → only a loopback origin may reach the
user/admin routes) and the HF-2 per-IP throttle. With the switch on, a LAN host
could send ``X-Forwarded-For: 127.0.0.1`` and become "localhost" — walking straight
through the auth bypass and out of the throttle. Forwarding headers are only
evidence when the peer that wrote them is a proxy we run, so trust is now a
question about the peer's address: it must sit inside ``JARVIS_TRUSTED_PROXIES``.

Why the legacy flag maps to loopback only. Existing installs that set the old flag
almost always run the proxy on the same box; keeping them working without letting
the old spelling widen trust to the whole network means "flag on" now equals
"trust a proxy that connects from loopback" and nothing more. A wider deployment
has to name its proxy addresses explicitly, and the deprecation warning says so.

Why the chain is walked right-to-left. Every proxy appends the peer it saw to the
end of ``X-Forwarded-For``, so the rightmost hops are the ones our own proxies
wrote and the leftmost is whatever the client chose to send. Walking from the
right past every trusted hop and stopping at the first untrusted one yields the
address that actually connected to our edge; reading the leftmost hop yields
whatever the attacker typed. When every hop is trusted the answer is the
*rightmost* hop — the address the proxy that connected to us actually saw —
never the leftmost: a client that happens to live inside a listed range would
otherwise type ``127.0.0.1`` in front of its own address and walk into the
loopback bypass. Every hop must also *be* an address; a trusted proxy that
passes a client-typed ``localhost`` through is not vouching for anything, so a
chain with a non-address hop resolves to nothing.

Why an entry should be the proxy's own address. A listed peer may name any
client address, and a range that contains clients as well as the proxy makes
every host in it a trusted spoofer when it connects directly. The list is
therefore a list of proxies (a single proxy is its own /32), not of networks the
proxies happen to live in.

Boundaries are explicit module constants: at most ``MAX_ENTRIES`` networks, at
most ``MAX_FORWARDED_HOPS`` hops of at most ``MAX_HOP_CHARS`` each. A value that
cannot be parsed never degrades to "trust nobody" silently at boot — the boot
guard refuses to start and names the variable (never the value); at request time
the caller treats the same error as "no trusted proxies", which is the closed
posture.

Why the resolved set is said out loud (H691). An operator who wrote a list
should be able to read back what the box ended up trusting — after
``strict=False`` folded a host address onto its network, after duplicates
collapsed, or after the legacy flag quietly meant loopback. The default is
"trust nothing", so every non-empty resolution is logged once at INFO, naming
the source and the canonical networks. Those are ``ipaddress``'s spelling of the
operator's own proxy addresses, not secrets and never the raw text; refusals and
the wide-entry warnings keep naming positions only. The web app reads the list at
import without saying anything (:func:`resolve_trusted_proxies`; logging is not
configured yet, so a line then would reach bare stderr or nobody), and the lifespan
calls :func:`announce_trusted_proxies` once logging and ``.env`` are both in place.

Why uvicorn's own proxy-header layer is switched off (H691 review). uvicorn ships a
second forwarding-header allowlist — ``proxy_headers`` with ``forwarded_allow_ips``,
defaulting to loopback and widened by ``FORWARDED_ALLOW_IPS`` or
``--forwarded-allow-ips`` — that rewrites the ASGI client address and scheme from
``X-Forwarded-For`` / ``X-Forwarded-Proto`` *before* the app sees the request. Left
on, it is a trust set nobody validates or logs: ``*`` there turned a LAN peer into
``127.0.0.1`` for both gates. So there is one trust set: ``serve.py`` builds uvicorn
with ``proxy_headers=False`` (and says so through :func:`note_server_proxy_layer`),
the compose file passes ``--no-proxy-headers``, the app reads ``X-Forwarded-Proto``
itself from a listed peer only (:func:`forwarded_proto`), and a uvicorn allowlist
that names any peer outside ``JARVIS_TRUSTED_PROXIES`` (plus uvicorn's own loopback
default) refuses boot (:func:`assert_server_proxy_layer_within_trust`). What cannot be
switched off from inside the app — a raw ``uvicorn`` start without
``--no-proxy-headers`` still believes loopback — is said at boot by the announce.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping, Sequence
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from typing import NamedTuple

from agents.core.env_config import env_str, truthy

logger = logging.getLogger("jarvis.proxy_trust")

TRUSTED_PROXIES_ENV = "JARVIS_TRUSTED_PROXIES"
LEGACY_FLAG_ENV = "JARVIS_TRUSTED_PROXY"
LOOPBACK_NETWORKS: tuple[IPv4Network | IPv6Network, ...] = (
    ip_network("127.0.0.0/8"),
    ip_network("::1/128"),
)
# Bounds. A proxy fleet larger than this is not a single-box assistant's edge;
# a forwarding chain longer than this is a header someone typed, not a route.
MAX_ENTRIES = 64
MAX_FORWARDED_HOPS = 16
MAX_HOP_CHARS = 64
# An entry wider than this is almost certainly a network the proxy lives in, not
# the proxy: every host inside it may then name any client address (including
# loopback) when it connects directly. Not refused — a /8 is a legitimate if
# unusual proxy fleet — but said once per value, naming the entry's position.
WIDE_ENTRY_PREFIXLEN_V4 = 24
WIDE_ENTRY_PREFIXLEN_V6 = 64

# Spellings that would trust the whole internet. Refused by name so the boot
# message can say what was wrong without echoing the value.
_WILDCARD_SPELLINGS = frozenset({"*", "0.0.0.0/0", "::/0"})

LEGACY_FLAG_WARNING = (
    f"{LEGACY_FLAG_ENV} is deprecated; trusting loopback only — set "
    f"{TRUSTED_PROXIES_ENV}=<cidr>; until then every client behind a non-loopback "
    "proxy shares one rate-limit bucket and the localhost bypass stays closed"
)

# uvicorn's own forwarding-header allowlist (H691 review): the env knob its Config
# reads, the CLI's auto-envvar spellings, the CLI flag, and its built-in default.
FORWARDED_ALLOW_IPS_ENV = "FORWARDED_ALLOW_IPS"
UVICORN_FORWARDED_ALLOW_IPS_ENV = "UVICORN_FORWARDED_ALLOW_IPS"
UVICORN_PROXY_HEADERS_ENV = "UVICORN_PROXY_HEADERS"
FORWARDED_ALLOW_IPS_FLAG = "--forwarded-allow-ips"
UVICORN_DEFAULT_ALLOW_IPS = "127.0.0.1,::1"
# The X-Forwarded-Proto values a listed proxy may state, folded onto an HTTP scheme;
# a WebSocket scope maps them onto ws/wss (uvicorn's own vocabulary).
_FORWARDED_PROTOS = {"http": "http", "https": "https", "ws": "http", "wss": "https"}

# Tiny memo keyed on the raw env strings so the environment is re-read on every
# call (monkeypatch.setenv in tests, a rotated .env) without re-parsing a list
# that has not changed.
_memo_key: tuple[str | None, str | None] | None = None
_memo_value: tuple[IPv4Network | IPv6Network, ...] = ()
_legacy_warned = False


def parse_trusted_proxies(
    raw: str, *, variable: str = TRUSTED_PROXIES_ENV,
) -> tuple[IPv4Network | IPv6Network, ...]:
    """Parse a comma-separated list of addresses / CIDR ranges into networks.

    Whitespace around entries is tolerated and empty entries are skipped; a bare
    address becomes its own /32 or /128. Refused with a ``ValueError`` that names
    the variable and the entry's position — never the value, because the message
    reaches logs and terminals: a wildcard (``*``, ``0.0.0.0/0``, ``::/0`` or any
    prefix length of 0, all of which would trust every peer), anything
    ``ipaddress`` cannot read, and more than ``MAX_ENTRIES`` entries. Duplicates
    collapse; the first occurrence keeps its place.
    """
    entries = [part.strip() for part in raw.split(",")]
    entries = [entry for entry in entries if entry]
    if len(entries) > MAX_ENTRIES:
        raise ValueError(
            f"{variable}: too many entries ({len(entries)} > {MAX_ENTRIES})"
        )
    networks: list[IPv4Network | IPv6Network] = []
    for position, entry in enumerate(entries, start=1):
        if entry in _WILDCARD_SPELLINGS:
            raise ValueError(
                f"{variable}: entry {position} is a wildcard that would trust every peer"
            )
        try:
            network = ip_network(entry, strict=False)
        except ValueError:
            raise ValueError(
                f"{variable}: entry {position} is not an IP address or CIDR range"
            ) from None
        if network.prefixlen == 0:
            raise ValueError(
                f"{variable}: entry {position} has prefix length 0 and would trust every peer"
            )
        if network not in networks:
            networks.append(network)
    return tuple(networks)


def trusted_proxies() -> tuple[IPv4Network | IPv6Network, ...]:
    """The networks whose peers may set forwarding headers, read from the environment.

    ``JARVIS_TRUSTED_PROXIES`` set → parsed (a malformed value raises ``ValueError``
    so the boot guard can refuse; request-time callers catch it and treat the
    result as "no trusted proxies"). Unset or blank (the shipped template carries
    ``JARVIS_TRUSTED_PROXIES=`` and a dotenv file exports that as the empty
    string, so blank must mean the same as unset — otherwise an install that
    still carries the legacy flag would lose its loopback proxy with no log line
    at all), with the legacy ``JARVIS_TRUSTED_PROXY`` truthy → loopback only, with
    one deprecation warning per process; the old flag never widens past the box
    itself. Both unset → nothing is trusted. When both are set, the list wins and
    the flag is ignored.
    """
    global _memo_key, _memo_value
    # env_config is the one parse home (AUD-14): unset and blank both read as "".
    raw = env_str(TRUSTED_PROXIES_ENV)
    legacy = env_str(LEGACY_FLAG_ENV)
    key = (raw, legacy)
    if key == _memo_key:
        return _memo_value
    networks = _resolve(raw, legacy)
    _memo_key, _memo_value = key, networks
    _say_trust_set(key, networks)
    return networks


def _resolve(raw: str, legacy: str) -> tuple[IPv4Network | IPv6Network, ...]:
    """The trust set for these two raw values; says nothing, raises ``ValueError``."""
    if raw.strip():
        return parse_trusted_proxies(raw)
    if truthy(legacy):
        return LOOPBACK_NETWORKS
    return ()


def resolve_trusted_proxies(
    environ: Mapping[str, str] | None = None,
) -> tuple[IPv4Network | IPv6Network, ...]:
    """The trust set for *environ* (default: the process environment), said to nobody.

    Same rules as :func:`trusted_proxies` — the list wins, a blank list is unset,
    the legacy flag means loopback — without the memo and without a log line, so a
    caller that runs before logging exists (web.py's informational import-time
    read, the boot guards) does not spend the once-per-value warnings on a process
    that cannot hear them yet. A malformed list raises ``ValueError``.
    """
    env = os.environ if environ is None else environ
    return _resolve(env.get(TRUSTED_PROXIES_ENV) or "", env.get(LEGACY_FLAG_ENV) or "")


def _say_trust_set(
    key: tuple[str | None, str | None], networks: tuple[IPv4Network | IPv6Network, ...],
    *, again: bool = False,
) -> None:
    """Everything a resolution says: the warnings that belong to it, then the set.

    The wide-entry warnings (by position) when the list is the source; the legacy
    deprecation — once per process, or *again* when the announce repeats a
    resolution that happened before anyone could hear it; then the INFO line.
    """
    global _legacy_warned
    raw, _legacy = key
    if raw and raw.strip():
        _warn_wide_entries(networks)
    elif networks and (again or not _legacy_warned):
        _legacy_warned = True
        logger.warning(LEGACY_FLAG_WARNING)
    _log_trust_set(key, networks)


def _trust_source(key: tuple[str | None, str | None]) -> str:
    """Which variable a resolution came from: the list wins over the legacy flag."""
    raw, _legacy = key
    if raw and raw.strip():
        return TRUSTED_PROXIES_ENV
    return f"{LEGACY_FLAG_ENV} (deprecated, loopback only)"


def _log_trust_set(
    key: tuple[str | None, str | None], networks: tuple[IPv4Network | IPv6Network, ...],
) -> None:
    """Say, at INFO, which proxy networks ended up trusted — when any did.

    Nothing is said for the default (an empty set): only a resolution that
    differs from "trust nothing" is news. The networks are the canonical
    ``ipaddress`` spelling, bounded by ``MAX_ENTRIES``; the raw value never
    reaches the log.
    """
    if not networks:
        return
    logger.info(
        "%s: trusting %d proxy network(s): %s",
        _trust_source(key), len(networks), ", ".join(str(network) for network in networks),
    )


def announce_trusted_proxies() -> tuple[IPv4Network | IPv6Network, ...]:
    """Say the trust set once the process can be heard; return it.

    Called by the web lifespan after logging is configured and ``.env`` is
    loaded. If the environment changed since the last resolution (the usual case:
    web.py's import-time read is silent and never fills the memo) this *is* the
    resolution and :func:`trusted_proxies` says it; otherwise the set was resolved
    before any handler existed and is said again here — the INFO line together with
    the warnings that belong to it (a wide entry, the legacy flag), so none of them
    is left on bare stderr or out of the log file. One INFO line either way, none
    when nothing is trusted. Then the server's own proxy-header layer is described
    when it trusts anything (:func:`server_proxy_layer`). A malformed list returns
    ``()`` without raising: the boot guard (:func:`assert_parseable_trusted_proxies`)
    owns that refusal, and request-time callers already fail closed on it.
    """
    key = (env_str(TRUSTED_PROXIES_ENV), env_str(LEGACY_FLAG_ENV))
    if key != _memo_key:
        try:
            networks = trusted_proxies()
        except ValueError:
            networks = ()
    else:
        networks = _memo_value
        _say_trust_set(key, networks, again=True)
    _say_server_layer()
    return networks


def _warn_wide_entries(networks: tuple[IPv4Network | IPv6Network, ...]) -> None:
    """Say once, by position, that an entry is wider than a proxy's own address.

    Called only when the memo misses, so a value is warned about once per
    process rather than once per request. The log carries the variable and the
    position, never the range.
    """
    for position, network in enumerate(networks, start=1):
        limit = WIDE_ENTRY_PREFIXLEN_V4 if network.version == 4 else WIDE_ENTRY_PREFIXLEN_V6
        if network.prefixlen < limit:
            logger.warning(
                "%s: entry %d is wider than /%d — every host in it may name any client "
                "address; list the proxy's own address instead",
                TRUSTED_PROXIES_ENV, position, limit,
            )


def _parse_peer(host: str) -> IPv4Address | IPv6Address | None:
    """Read a socket peer as an address; ``None`` on anything that is not one.

    Brackets (``[::1]``) and a zone id (``fe80::1%eth0``) are stripped, and an
    IPv4-mapped IPv6 address (``::ffff:10.0.0.1`` — what a dual-stack listener
    reports for an IPv4 client) is folded onto its IPv4 form so a v4 allowlist
    entry matches it.
    """
    text = host.strip()
    if not text or len(text) > MAX_HOP_CHARS:
        return None
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    text = text.split("%", 1)[0]
    try:
        address = ip_address(text)
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_trusted_peer(host: str) -> bool:
    """True when *host* is an address inside one of the trusted proxy networks.

    Garbage (a hostname, an empty string, an over-long token) is never trusted.
    A malformed ``JARVIS_TRUSTED_PROXIES`` propagates as ``ValueError`` — see
    :func:`trusted_proxies`.
    """
    address = _parse_peer(host)
    if address is None:
        return False
    return any(address in network for network in trusted_proxies())


def forwarded_client(peer: str, *, xff: str, x_real_ip: str) -> str:
    """The client address a trusted proxy is vouching for, or ``""``.

    ``""`` when *peer* is not a trusted proxy: forwarding headers from anyone
    else are attacker-controlled, so the caller must fail closed rather than
    fall back to reading them. Otherwise the ``X-Forwarded-For`` chain is walked
    right-to-left past every trusted hop and the first untrusted hop is the
    answer; a chain made only of trusted hops yields its *rightmost* entry (the
    address the connecting proxy saw — the leftmost is whatever the client
    typed); an empty chain falls back to ``X-Real-IP``. The answer is always the
    canonical spelling of an address: a hop that is not an address (``localhost``,
    a name, a typo) means the proxy passed client text through, so the whole chain
    resolves to ``""`` rather than handing a gate that compares names something
    the client wrote. More than ``MAX_FORWARDED_HOPS`` hops or a hop over
    ``MAX_HOP_CHARS`` is refused the same way — a header that shape was typed,
    not routed.
    """
    if not is_trusted_peer(peer):
        return ""
    hops = [hop.strip() for hop in xff.split(",")] if xff.strip() else []
    hops = [hop for hop in hops if hop]
    if len(hops) > MAX_FORWARDED_HOPS:
        return ""
    if any(len(hop) > MAX_HOP_CHARS for hop in hops):
        return ""
    if not hops:
        real = _parse_peer(x_real_ip)
        return str(real) if real is not None else ""
    addresses = [_parse_peer(hop) for hop in hops]
    if any(address is None for address in addresses):
        return ""
    for address in reversed(addresses):
        if not any(address in network for network in trusted_proxies()):
            return str(address)
    return str(addresses[-1])


def forwarded_proto(peer: str, values: Sequence[str], *, websocket: bool = False) -> str:
    """The scheme a trusted proxy states in ``X-Forwarded-Proto``, or ``""``.

    The same allowlist as ``X-Forwarded-For``: from a peer outside
    ``JARVIS_TRUSTED_PROXIES`` the header is the client's own claim and the socket
    scheme stands. Exactly one header whose whole value is ``http``, ``https``, ``ws``
    or ``wss`` (case and surrounding space ignored) is believed; a repeated header or
    a chained value (``https, http``) is ambiguous and ignored. The answer is folded
    onto the scope type — ``http``/``https`` for HTTP, ``ws``/``wss`` for a
    WebSocket. A malformed ``JARVIS_TRUSTED_PROXIES`` propagates as ``ValueError``
    (the caller fails closed), as in :func:`is_trusted_peer`.
    """
    if len(values) != 1:
        return ""
    scheme = _FORWARDED_PROTOS.get(values[0].strip().lower())
    if scheme is None or not is_trusted_peer(peer):
        return ""
    if websocket:
        return "wss" if scheme == "https" else "ws"
    return scheme


def assert_parseable_trusted_proxies(environ: Mapping[str, str] | None = None) -> None:
    """Refuse boot when ``JARVIS_TRUSTED_PROXIES`` is set but cannot be parsed.

    A trust-widening variable that silently degraded would leave the operator
    believing their proxy is trusted while every forwarded request fails closed
    (or, worse, a later "fix" widens it past what they meant). Unset and empty
    are fine: they mean "trust no proxy". The message carries the variable and
    the remedies, never the value. When both this list and the legacy flag are
    set, the list wins — the flag's spelling is not checked here.
    """
    env = os.environ if environ is None else environ
    raw = env.get(TRUSTED_PROXIES_ENV)
    if raw is None or not raw.strip():
        return
    try:
        parse_trusted_proxies(raw)
    except ValueError as exc:
        raise SystemExit(
            f"Refusing to start: {exc}.\n"
            f"Set {TRUSTED_PROXIES_ENV} to a comma-separated list of the reverse proxy's "
            f"own addresses or CIDR ranges (at most {MAX_ENTRIES}, no wildcard — a single "
            f"proxy is its own /32; never a range that also contains clients, every host "
            f"in a listed range may name any client address), or unset it to trust no proxy."
        ) from None


# ── the ASGI server's own proxy-header layer (H691 review) ───────────────────


class ServerProxyLayer(NamedTuple):
    """What the server in front of the app does with forwarding headers.

    ``proxy_headers`` — whether uvicorn rewrites the client address and scheme from
    ``X-Forwarded-For`` / ``X-Forwarded-Proto`` before the app runs;
    ``forwarded_allow_ips`` — the peers it believes them from, as uvicorn reads the
    value ("" when the layer is off); ``source`` — how that is known.
    """

    proxy_headers: bool
    forwarded_allow_ips: str
    source: str


#: Set by a launcher that built the server config itself (``serve.server_config``).
_server_layer_note: ServerProxyLayer | None = None


def note_server_proxy_layer(*, proxy_headers: bool, forwarded_allow_ips: str | Sequence[str] = "") -> None:
    """Record what the launcher built, so the announce states it instead of guessing."""
    global _server_layer_note
    if not isinstance(forwarded_allow_ips, str):
        forwarded_allow_ips = ",".join(forwarded_allow_ips)
    _server_layer_note = ServerProxyLayer(
        bool(proxy_headers), forwarded_allow_ips if proxy_headers else "", "serve.py",
    )


def _uvicorn_command_line(argv: Sequence[str]) -> dict[str, object] | None:
    """uvicorn's own proxy flags when this process *is* ``uvicorn …`` / ``python -m uvicorn …``.

    ``None`` for any other program (serve.py, a packaged build, a test runner), so a
    flag-shaped argument meant for something else is never read as uvicorn's.
    """
    if not argv:
        return None
    program = str(argv[0]).replace("\\", "/")
    name = program.rsplit("/", 1)[-1].lower()
    if name not in {"uvicorn", "uvicorn.exe"} and not program.endswith("uvicorn/__main__.py"):
        return None
    flags: dict[str, object] = {}
    args = [str(arg) for arg in argv[1:]]
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--proxy-headers", "--no-proxy-headers"):
            flags["proxy_headers"] = arg == "--proxy-headers"
        elif arg == FORWARDED_ALLOW_IPS_FLAG:
            flags["forwarded_allow_ips"] = args[index + 1] if index + 1 < len(args) else ""
            index += 1
        elif arg.startswith(FORWARDED_ALLOW_IPS_FLAG + "="):
            flags["forwarded_allow_ips"] = arg[len(FORWARDED_ALLOW_IPS_FLAG) + 1:]
        index += 1
    return flags


def server_proxy_layer(
    environ: Mapping[str, str] | None = None, argv: Sequence[str] | None = None,
) -> ServerProxyLayer:
    """Describe uvicorn's proxy-header layer for this process, as far as it can be known.

    A launcher that noted what it built (``serve.py``: off) is taken at its word.
    uvicorn's CLI is read the way uvicorn reads it: the flag, else its
    ``UVICORN_*`` auto-envvar, else ``FORWARDED_ALLOW_IPS``, else uvicorn's loopback
    default. Anything else (an embedding that calls ``uvicorn.run(app)``, a test
    client) is described with ``uvicorn.run``'s defaults — on, from
    ``FORWARDED_ALLOW_IPS`` or loopback — because that is the wider possibility.
    """
    if _server_layer_note is not None:
        return _server_layer_note
    env = os.environ if environ is None else environ
    cli = _uvicorn_command_line(sys.argv if argv is None else argv)
    if cli is None:
        return ServerProxyLayer(
            True, env.get(FORWARDED_ALLOW_IPS_ENV, UVICORN_DEFAULT_ALLOW_IPS), "launcher not known",
        )
    proxy_headers = cli.get("proxy_headers")
    if proxy_headers is None:
        proxy_headers = truthy(env.get(UVICORN_PROXY_HEADERS_ENV), default=True)
    if "forwarded_allow_ips" in cli:
        allow = str(cli["forwarded_allow_ips"])
    elif env.get(UVICORN_FORWARDED_ALLOW_IPS_ENV):  # click ignores an empty auto-envvar
        allow = env[UVICORN_FORWARDED_ALLOW_IPS_ENV]
    else:
        allow = env.get(FORWARDED_ALLOW_IPS_ENV, UVICORN_DEFAULT_ALLOW_IPS)
    return ServerProxyLayer(bool(proxy_headers), allow if proxy_headers else "", "uvicorn CLI")


def _say_server_layer() -> None:
    """INFO the server's own trust set when it believes anybody; nothing when it is off.

    The value has passed :func:`assert_server_proxy_layer_within_trust` by the time the
    lifespan announces, so it is named in canonical form, like the Nerva set.
    """
    layer = server_proxy_layer()
    if not layer.proxy_headers or not layer.forwarded_allow_ips.strip():
        return
    try:
        networks = parse_trusted_proxies(layer.forwarded_allow_ips, variable="forwarded_allow_ips")
    except ValueError:
        logger.warning(
            "uvicorn proxy headers (%s): the allow list is not a list of addresses — the boot "
            "guard refuses it; start through serve.py", layer.source,
        )
        return
    if not networks:
        return
    logger.info(
        "uvicorn proxy headers (%s): X-Forwarded-For and X-Forwarded-Proto are believed from %s "
        "before %s is consulted — start through serve.py, or pass --no-proxy-headers, to leave "
        "%s the only trust set",
        layer.source, ", ".join(str(network) for network in networks),
        TRUSTED_PROXIES_ENV, TRUSTED_PROXIES_ENV,
    )


def _first_entry_outside(
    raw: str, allowed: tuple[IPv4Network | IPv6Network, ...], *, variable: str,
) -> str:
    """The refusal for the first entry of *raw* that no network in *allowed* contains."""
    entries = [entry for entry in (part.strip() for part in raw.split(",")) if entry]
    for position, entry in enumerate(entries, start=1):
        network = ip_network(entry, strict=False)
        if not any(network.version == outer.version and network.subnet_of(outer) for outer in allowed):
            return (
                f"{variable}: entry {position} names a peer that {TRUSTED_PROXIES_ENV} does not list"
            )
    return ""


def assert_server_proxy_layer_within_trust(
    environ: Mapping[str, str] | None = None, argv: Sequence[str] | None = None,
) -> None:
    """Refuse boot when uvicorn's own allowlist would trust more than Nerva's.

    ``FORWARDED_ALLOW_IPS``, ``UVICORN_FORWARDED_ALLOW_IPS`` and — when this process
    is uvicorn's CLI — ``--forwarded-allow-ips`` are each a list of peers whose
    ``X-Forwarded-For`` / ``X-Forwarded-Proto`` uvicorn believes before the app
    consults ``JARVIS_TRUSTED_PROXIES``. Every entry must be an address or bounded
    range that sits inside ``JARVIS_TRUSTED_PROXIES`` or uvicorn's own loopback
    default; a wildcard, a ``/0``, something that is not an address, or a peer the
    Nerva list does not name refuses boot, naming the source and the position —
    never the value. Checked whatever the launcher: under ``serve.py`` the layer is
    off and the knob would be inert, and a knob that reads as trust but does nothing
    is refused rather than left to mislead. A malformed ``JARVIS_TRUSTED_PROXIES``
    is its own guard's refusal; here it leaves loopback as the only allowed range.
    """
    env = os.environ if environ is None else environ
    sources: list[tuple[str, str]] = []
    for variable in (FORWARDED_ALLOW_IPS_ENV, UVICORN_FORWARDED_ALLOW_IPS_ENV):
        value = env.get(variable)
        if value and value.strip():
            sources.append((variable, value))
    cli = _uvicorn_command_line(sys.argv if argv is None else argv)
    if cli is not None and str(cli.get("forwarded_allow_ips", "")).strip():
        sources.append((FORWARDED_ALLOW_IPS_FLAG, str(cli["forwarded_allow_ips"])))
    if not sources:
        return
    try:
        allowed = resolve_trusted_proxies(env) + LOOPBACK_NETWORKS
    except ValueError:
        allowed = LOOPBACK_NETWORKS
    for variable, value in sources:
        try:
            parse_trusted_proxies(value, variable=variable)
            problem = _first_entry_outside(value, allowed, variable=variable)
        except ValueError as exc:
            problem = str(exc)
        if problem:
            raise SystemExit(
                f"Refusing to start: {problem}.\n"
                f"uvicorn believes X-Forwarded-For and X-Forwarded-Proto from the peers {variable} "
                f"lists and rewrites the client address and scheme before Nerva consults "
                f"{TRUSTED_PROXIES_ENV} — a second, wider trust set in front of the localhost gate "
                f"and the rate limiter. Remove {variable} and list the reverse proxy's own address "
                f"in {TRUSTED_PROXIES_ENV} instead: Nerva reads the forwarding headers itself "
                f"(serve.py switches uvicorn's layer off; a raw uvicorn start takes --no-proxy-headers)."
            )
