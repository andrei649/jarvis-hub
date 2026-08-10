"""Dependency-free DNS guard installed by the global pytest harness."""

from __future__ import annotations

import ipaddress
import socket

REAL_GETADDRINFO = socket.getaddrinfo
# These must classify as globally routable so SSRF/egress policy takes its
# public-host path. pytest-socket still blocks connect() before any packet exits.
HERMETIC_IPV4 = "93.184.216.34"
HERMETIC_IPV6 = "2606:4700:4700::1111"


def hermetic_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    rendered = host.decode(errors="replace") if isinstance(host, bytes) else host
    if rendered is None:
        return REAL_GETADDRINFO(host, port, family, type, proto, flags)
    normalized = str(rendered).rstrip(".").lower()
    try:
        ipaddress.ip_address(normalized)
        literal = True
    except ValueError:
        literal = False
    if literal or normalized == "localhost" or normalized.endswith(".localhost"):
        return REAL_GETADDRINFO(host, port, family, type, proto, flags)

    resolved_port = {"http": 80, "https": 443}.get(str(port).lower(), port or 0)
    addresses = []
    families = [family] if family in {socket.AF_INET, socket.AF_INET6} else [socket.AF_INET]
    socket_types = [type] if type else [socket.SOCK_STREAM, socket.SOCK_DGRAM]
    for selected_family in families:
        address = HERMETIC_IPV6 if selected_family == socket.AF_INET6 else HERMETIC_IPV4
        for selected_type in socket_types:
            selected_proto = proto or (
                socket.IPPROTO_UDP if selected_type == socket.SOCK_DGRAM else socket.IPPROTO_TCP
            )
            addresses.append(
                (selected_family, selected_type, selected_proto, "", (address, resolved_port))
            )
    return addresses


def install_hermetic_dns() -> None:
    socket.getaddrinfo = hermetic_getaddrinfo
