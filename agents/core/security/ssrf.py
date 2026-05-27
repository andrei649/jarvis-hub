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

def check_ssrf(url: str) -> Optional[str]:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return "No hostname in URL"

    if hostname in BLOCKED_HOSTS:
        return f"Blocked host: {hostname} (cloud metadata endpoint)"

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        if isinstance(literal, ipaddress.IPv6Address):
            embedded = _embedded_ipv4(literal)
            if embedded is not None and str(embedded) in BLOCKED_HOSTS:
                return f"Blocked host: {embedded} (cloud metadata endpoint)"
        if is_private_ip(hostname):
            return f"URL resolves to private IP: {hostname}"
        return None

    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, stype, proto, canonname, sockaddr in resolved:
            ip = sockaddr[0]
            if is_private_ip(ip):
                return f"URL resolves to private IP: {ip}"
    except socket.gaierror:
        pass

    return None
