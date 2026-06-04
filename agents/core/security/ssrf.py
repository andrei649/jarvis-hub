"""
ssrf.py — SSRF protection for Jarvis agents.

Port of OpenJarvis's Rust-based SSRF check to pure Python.
Blocks requests to private IPs and cloud metadata endpoints.
"""

import ipaddress
import socket
from typing import Optional

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

def is_private_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(addr)
        if embedded is not None:
            addr = embedded
    return any(addr in net for net in BLOCKED_CIDR)

def resolve_and_validate(hostname: str) -> tuple[list[str], Optional[str]]:
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
    if hostname in BLOCKED_HOSTS:
        return [], f"Blocked host: {hostname} (cloud metadata endpoint)"

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        if isinstance(literal, ipaddress.IPv6Address):
            embedded = _embedded_ipv4(literal)
            if embedded is not None and str(embedded) in BLOCKED_HOSTS:
                return [], f"Blocked host: {embedded} (cloud metadata endpoint)"
        if is_private_ip(hostname):
            return [], f"URL resolves to private IP: {hostname}"
        return [hostname], None

    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return [], f"DNS resolution failed for {hostname}"

    ips: list[str] = []
    for family, stype, proto, canonname, sockaddr in resolved:
        ip = sockaddr[0].split("%")[0]  # drop any IPv6 scope id (fe80::1%eth0)
        if is_private_ip(ip):
            return [], f"URL resolves to private IP: {ip}"
        ips.append(ip)
    if not ips:
        return [], f"DNS resolution failed for {hostname}"
    return ips, None


def check_ssrf(url: str) -> Optional[str]:
    """Return a block reason if *url* is unsafe to fetch, else None.

    A pre-flight filter. Note this resolves DNS itself, so it must be paired with
    IP pinning at connect time (see resolve_and_validate) to be rebinding-proof;
    used alone it only catches the obvious cases. A DNS-resolution failure is not
    treated as a block here (the fetch would fail on its own).
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return "No hostname in URL"
    _ips, err = resolve_and_validate(hostname)
    if err and err.startswith("DNS resolution failed"):
        return None
    return err
