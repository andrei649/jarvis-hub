"""
ssrf.py — SSRF protection for Jarvis agents.

Port of OpenJarvis's Rust-based SSRF check to pure Python.
Blocks requests to private IPs and cloud metadata endpoints.
"""

import ipaddress
import socket
from typing import Literal, Optional

BLOCKED_HOSTS = frozenset({
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.google.com",
    "100.100.100.200",
})

BLOCKED_CIDR = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]

def _embedded_ipv4(addr: ipaddress.IPv6Address) -> Optional[ipaddress.IPv4Address]:
    mapped = addr.ipv4_mapped
    if mapped is not None:
        return mapped
    packed = addr.packed
    if packed[:12] == b"\x00" * 12 and addr != ipaddress.IPv6Address("::") and addr != ipaddress.IPv6Address("::1"):
        return ipaddress.IPv4Address(packed[12:])
    return None

def _normalized_address(ip_str: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(addr)
        if embedded is not None:
            return embedded
    return addr


def is_private_ip(ip_str: str) -> bool:
    addr = _normalized_address(ip_str)
    return addr is not None and any(addr in net for net in BLOCKED_CIDR)


def _safe_for_mode(address: str, mode: Literal["public", "lan"]) -> bool:
    addr = _normalized_address(address)
    if addr is None:
        return False
    if mode == "lan":
        return addr.is_loopback or (
            isinstance(addr, ipaddress.IPv4Address)
            and any(addr in network for network in (
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
            ))
        )
    return (
        addr.is_global
        and not addr.is_multicast
        and not addr.is_unspecified
        and not addr.is_loopback
        and not addr.is_private
        and not addr.is_link_local
        and not addr.is_reserved
    )

def resolve_and_validate(
    hostname: str,
    *,
    mode: Literal["public", "lan"] = "public",
) -> tuple[list[str], Optional[str]]:
    """Resolve *hostname* once and validate every address it maps to.

    Returns ``(ips, error)``. ``error`` is non-None — and ``ips`` empty — when the
    host is a blocked metadata name, fails to resolve, or resolves to **any**
    private/blocked address. Rejecting on *any* private hit (not just the first)
    closes a split-horizon / multi-record DNS-rebinding trick where a host hands
    out one public and one private A record.

    Callers should connect to one of the returned ``ips`` (pinning), so the IP
    that was validated is the IP that's actually dialed — otherwise httpx would
    re-resolve and a low-TTL record could rebind to a private host between our
    check and the connection (the HF-4 TOCTOU). On DNS failure ``ips`` is empty
    with a "DNS resolution failed" error so callers can fail closed.
    """
    hostname = hostname.lower().rstrip(".")
    if not hostname:
        return [], "DNS resolution failed for empty hostname"
    if mode not in {"public", "lan"}:
        return [], "invalid SSRF address mode"
    if hostname in BLOCKED_HOSTS:
        return [], f"Blocked host: {hostname} (cloud metadata endpoint)"

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        normalized = _normalized_address(hostname)
        if normalized is not None and str(normalized) in BLOCKED_HOSTS:
            return [], f"Blocked host: {normalized} (cloud metadata endpoint)"
        if not _safe_for_mode(hostname, mode):
            return [], f"URL resolves to unsafe address for {mode} mode: {hostname}"
        return [str(normalized)], None

    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError:
        return [], f"DNS resolution failed for {hostname}"

    ips: list[str] = []
    for family, stype, proto, canonname, sockaddr in resolved:
        ip = sockaddr[0].split("%")[0]
        normalized = _normalized_address(ip)
        if normalized is None or not _safe_for_mode(ip, mode):
            return [], f"URL resolves to unsafe address for {mode} mode: {ip}"
        ips.append(str(normalized))
    if not ips:
        return [], f"DNS resolution failed for {hostname}"
    return list(dict.fromkeys(ips)), None


def check_ssrf(url: str) -> Optional[str]:
    """Return a block reason if *url* is unsafe to fetch, else None.

    A pre-flight filter. Network callers must still pin the resulting address;
    failed or empty resolution is a refusal rather than a best-effort allow.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return "No hostname in URL"
    _ips, err = resolve_and_validate(hostname)
    return err
