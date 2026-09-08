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
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network

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
    global _memo_key, _memo_value, _legacy_warned
    # env_config is the one parse home (AUD-14): unset and blank both read as "".
    raw = env_str(TRUSTED_PROXIES_ENV)
    legacy = env_str(LEGACY_FLAG_ENV)
    key = (raw, legacy)
    if key == _memo_key:
        return _memo_value
    if raw.strip():
        networks = parse_trusted_proxies(raw)
        _warn_wide_entries(networks)
    elif truthy(legacy):
        if not _legacy_warned:
            _legacy_warned = True
            logger.warning(LEGACY_FLAG_WARNING)
        networks = LOOPBACK_NETWORKS
    else:
        networks = ()
    _memo_key, _memo_value = key, networks
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
