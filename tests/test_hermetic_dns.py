"""The global test harness must not leak external hostnames to real DNS."""

import socket


def test_external_dns_is_deterministic_and_never_calls_system_resolver(monkeypatch):
    from support import hermetic_dns

    def forbidden(*args, **kwargs):
        raise AssertionError("system resolver was called for an external hostname")

    monkeypatch.setattr(hermetic_dns, "REAL_GETADDRINFO", forbidden)
    result = hermetic_dns.hermetic_getaddrinfo("api.tavily.com", 443, type=socket.SOCK_STREAM)
    assert {item[4][0] for item in result} == {hermetic_dns.HERMETIC_IPV4}


def test_loopback_and_ip_literals_keep_normal_socket_semantics(monkeypatch):
    from support import hermetic_dns

    seen = []

    def recorder(*args):
        seen.append(args[0])
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 80))]

    monkeypatch.setattr(hermetic_dns, "REAL_GETADDRINFO", recorder)
    hermetic_dns.hermetic_getaddrinfo("localhost", 80)
    hermetic_dns.hermetic_getaddrinfo("127.0.0.1", 80)
    assert seen == ["localhost", "127.0.0.1"]


def test_external_ipv6_requests_receive_a_stable_ipv6_address(monkeypatch):
    from support import hermetic_dns

    monkeypatch.setattr(
        hermetic_dns,
        "REAL_GETADDRINFO",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected resolver call")),
    )
    result = hermetic_dns.hermetic_getaddrinfo("example.com", "https", family=socket.AF_INET6)
    assert result[0][4] == (hermetic_dns.HERMETIC_IPV6, 443)
