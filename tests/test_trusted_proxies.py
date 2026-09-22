"""Hermes absorption 5b — reverse-proxy trust is a bounded CIDR allowlist.

The old JARVIS_TRUSTED_PROXY switch trusted the FIRST X-Forwarded-For hop from ANY
peer once it was on, so a LAN host could spoof 127.0.0.1 straight into the
localhost auth bypass and out of the HF-2 throttle. Trust is now a question about
the socket peer's address (JARVIS_TRUSTED_PROXIES), the chain is walked
right-to-left, the legacy flag maps to loopback only, and a malformed list
refuses boot naming the variable — never the value.
"""
import logging
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402
from agents.core import proxy_trust  # noqa: E402
from tests.test_admin_guard_hf7 import _FakeReq  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_proxy_env(monkeypatch):
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("JARVIS_TRUSTED_PROXY", raising=False)
    monkeypatch.setattr(proxy_trust, "_legacy_warned", False)
    monkeypatch.setattr(proxy_trust, "_memo_key", None)
    monkeypatch.setattr(web, "_malformed_proxy_list_warned", False, raising=False)


class _RateReq:
    def __init__(self, headers=None, host="1.2.3.4"):
        self.headers = Headers(headers or {})
        self.client = type("C", (), {"host": host})()


# ── parsing ──────────────────────────────────────────────────────────────────

def test_single_cidr_and_bare_ip_parse():
    nets = proxy_trust.parse_trusted_proxies(" 10.0.0.0/8 , 192.168.1.9,, fd00::/64 ,10.0.0.0/8")
    assert [str(n) for n in nets] == ["10.0.0.0/8", "192.168.1.9/32", "fd00::/64"]
    assert proxy_trust.parse_trusted_proxies("") == ()
    assert proxy_trust.parse_trusted_proxies(" , ") == ()
    # strict=False: a host address with a prefix is accepted as its network.
    assert str(proxy_trust.parse_trusted_proxies("10.1.2.3/24")[0]) == "10.1.2.0/24"


@pytest.mark.parametrize("raw", ["*", "0.0.0.0/0", "::/0", "10.0.0.1, 1.2.3.4/0", "not-an-ip"])
def test_wildcard_and_prefixlen_zero_and_too_many_are_refused_naming_the_variable_not_the_value(raw):
    with pytest.raises(ValueError) as ei:
        proxy_trust.parse_trusted_proxies(raw)
    message = str(ei.value)
    assert message.startswith("JARVIS_TRUSTED_PROXIES:")
    for entry in raw.split(","):
        assert entry.strip() not in message
    # A custom variable name is carried through (the boot guard names its own).
    with pytest.raises(ValueError, match="^OTHER_VAR:"):
        proxy_trust.parse_trusted_proxies(raw, variable="OTHER_VAR")
    too_many = ",".join(f"10.0.{i}.1" for i in range(proxy_trust.MAX_ENTRIES + 1))
    with pytest.raises(ValueError, match="JARVIS_TRUSTED_PROXIES: too many entries"):
        proxy_trust.parse_trusted_proxies(too_many)
    assert len(proxy_trust.parse_trusted_proxies(",".join(f"10.0.{i}.1" for i in range(proxy_trust.MAX_ENTRIES)))) == proxy_trust.MAX_ENTRIES


def test_malformed_list_refuses_boot(monkeypatch):
    with pytest.raises(SystemExit) as ei:
        proxy_trust.assert_parseable_trusted_proxies({"JARVIS_TRUSTED_PROXIES": "0.0.0.0/0"})
    message = str(ei.value)
    assert "JARVIS_TRUSTED_PROXIES" in message
    assert "0.0.0.0/0" not in message
    assert "unset it" in message  # a remedy line
    # Unset / empty / a good list boot fine; the real environment is the default source.
    proxy_trust.assert_parseable_trusted_proxies({})
    proxy_trust.assert_parseable_trusted_proxies({"JARVIS_TRUSTED_PROXIES": "  "})
    proxy_trust.assert_parseable_trusted_proxies({"JARVIS_TRUSTED_PROXIES": "10.0.0.1"})
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "garbage")
    with pytest.raises(SystemExit) as ei:
        proxy_trust.assert_parseable_trusted_proxies()
    assert "garbage" not in str(ei.value)
    # At request time the same value never 500s: the resolver reads it as "no trust".
    req = _FakeReq({"x-forwarded-for": "127.0.0.1"}, host="127.0.0.1")
    assert web._real_client_host(req) == ""
    assert web._client_ip(req) == "127.0.0.1"


def test_legacy_flag_means_loopback_only_with_one_warning(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXY", "1")
    with caplog.at_level(logging.WARNING, logger="jarvis.proxy_trust"):
        assert proxy_trust.trusted_proxies() == proxy_trust.LOOPBACK_NETWORKS
        assert proxy_trust.trusted_proxies() == proxy_trust.LOOPBACK_NETWORKS
    warnings = [r for r in caplog.records if "JARVIS_TRUSTED_PROXY is deprecated" in r.getMessage()]
    assert len(warnings) == 1
    assert "JARVIS_TRUSTED_PROXIES" in warnings[0].getMessage()
    # A blank list (the shipped template's ``JARVIS_TRUSTED_PROXIES=``) is the same
    # as unset: the flag still means loopback, and the deprecation is still said —
    # never a silent loss of the loopback proxy.
    monkeypatch.setattr(proxy_trust, "_legacy_warned", False)
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "   ")
    with caplog.at_level(logging.WARNING, logger="jarvis.proxy_trust"):
        assert proxy_trust.trusted_proxies() == proxy_trust.LOOPBACK_NETWORKS
    assert sum("JARVIS_TRUSTED_PROXY is deprecated" in r.getMessage() for r in caplog.records) == 2
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES")
    # Loopback only: the LAN proxy that used to be trusted under the flag is not.
    assert proxy_trust.is_trusted_peer("127.0.0.1") is True
    assert proxy_trust.is_trusted_peer("::1") is True
    assert proxy_trust.is_trusted_peer("10.0.0.1") is False
    # The list wins over the flag when both are set.
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1")
    assert proxy_trust.is_trusted_peer("10.0.0.1") is True
    assert proxy_trust.is_trusted_peer("127.0.0.1") is False
    # Both unset → nothing is trusted.
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES")
    monkeypatch.delenv("JARVIS_TRUSTED_PROXY")
    assert proxy_trust.trusted_proxies() == ()
    assert proxy_trust.is_trusted_peer("127.0.0.1") is False


# ── the resolvers ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_untrusted_peer_ignores_forwarded_headers_and_fails_closed(monkeypatch):
    assert proxy_trust.forwarded_client("192.168.1.9", xff="127.0.0.1", x_real_ip="") == ""
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1/32")
    assert proxy_trust.forwarded_client("192.168.1.9", xff="127.0.0.1", x_real_ip="127.0.0.1") == ""
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    req = _FakeReq({"x-forwarded-for": "127.0.0.1"}, host="192.168.1.9")
    assert web._real_client_host(req) == ""
    with pytest.raises(HTTPException) as ei:
        await web._admin_guard(req)
    assert ei.value.status_code == 403
    # X-Real-IP alone from a stranger is no better.
    assert web._real_client_host(_FakeReq({"x-real-ip": "127.0.0.1"}, host="192.168.1.9")) == ""


def test_trusted_peer_walks_xff_right_to_left_past_trusted_hops(monkeypatch):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8")
    assert proxy_trust.forwarded_client(
        "10.0.0.1", xff="198.51.100.7, 10.0.0.5, 10.0.0.1", x_real_ip="") == "198.51.100.7"
    # The leftmost hop is attacker-typed; the first untrusted hop from the right wins.
    assert proxy_trust.forwarded_client(
        "10.0.0.1", xff="127.0.0.1, 203.0.113.9, 10.0.0.5", x_real_ip="") == "203.0.113.9"
    # An all-trusted chain yields its RIGHTMOST entry — the address the connecting
    # proxy saw — never the leftmost, which a client inside the listed range typed.
    assert proxy_trust.forwarded_client("10.0.0.1", xff="10.0.0.7, 10.0.0.5", x_real_ip="") == "10.0.0.5"
    # (Loopback is outside the /8, so a typed 127.0.0.1 behind a client in the
    # range IS the first untrusted hop — the range-contains-clients case the
    # wide-entry warning is about, not the all-trusted rule.)
    assert proxy_trust.forwarded_client("10.0.0.1", xff="127.0.0.1, 10.0.0.50", x_real_ip="") == "127.0.0.1"
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8, 127.0.0.0/8")
    assert proxy_trust.forwarded_client("10.0.0.1", xff="127.0.0.1, 10.0.0.50", x_real_ip="") == "10.0.0.50"
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8")
    # An empty chain falls back to X-Real-IP, stripped.
    assert proxy_trust.forwarded_client("10.0.0.1", xff="", x_real_ip=" 203.0.113.4 ") == "203.0.113.4"
    assert proxy_trust.forwarded_client("10.0.0.1", xff="", x_real_ip="") == ""
    # A hop that is not an address is client text the proxy passed through: the
    # chain resolves to nothing rather than to a name a gate might compare.
    assert proxy_trust.forwarded_client("10.0.0.1", xff="localhost", x_real_ip="") == ""
    assert proxy_trust.forwarded_client("10.0.0.1", xff="localhost, 10.0.0.5", x_real_ip="") == ""
    assert proxy_trust.forwarded_client("10.0.0.1", xff="203.0.113.9, nope", x_real_ip="") == ""
    assert proxy_trust.forwarded_client("10.0.0.1", xff="", x_real_ip="localhost") == ""
    assert proxy_trust.forwarded_client("10.0.0.1", xff="", x_real_ip="foo bar") == ""
    # The answer is the canonical spelling of the address, so the bucket key and the
    # localhost comparison never see an alternate form.
    assert proxy_trust.forwarded_client("10.0.0.1", xff="0:0:0:0:0:0:0:1", x_real_ip="") == "::1"
    assert proxy_trust.forwarded_client("10.0.0.1", xff="", x_real_ip="[203.0.113.4]") == "203.0.113.4"
    # Bounds: too many hops or an over-long hop → "" (fail closed).
    long_chain = ", ".join("10.0.0.5" for _ in range(proxy_trust.MAX_FORWARDED_HOPS + 1))
    assert proxy_trust.forwarded_client("10.0.0.1", xff=long_chain, x_real_ip="") == ""
    assert proxy_trust.forwarded_client("10.0.0.1", xff="a" * (proxy_trust.MAX_HOP_CHARS + 1), x_real_ip="") == ""
    assert proxy_trust.forwarded_client("10.0.0.1", xff="", x_real_ip="a" * (proxy_trust.MAX_HOP_CHARS + 1)) == ""


@pytest.mark.asyncio
async def test_lan_peer_cannot_spoof_loopback_into_the_auth_bypass(monkeypatch):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1/32")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    with pytest.raises(HTTPException) as ei:
        await web._admin_guard(_FakeReq({"x-forwarded-for": "127.0.0.1"}, host="192.168.1.9"))
    assert ei.value.status_code == 403
    await web._admin_guard(_FakeReq({"x-forwarded-for": "127.0.0.1"}, host="10.0.0.1"))
    # A trusted proxy that passes a client-typed "localhost" through (a non-appending
    # proxy, or X-Real-IP copied from the client) vouches for nothing: 403.
    for headers in ({"x-forwarded-for": "localhost"}, {"x-real-ip": "localhost"},
                    {"x-forwarded-for": "localhost, 10.0.0.1"}):
        assert web._real_client_host(_FakeReq(headers, host="10.0.0.1")) == ""
        with pytest.raises(HTTPException) as ei:
            await web._admin_guard(_FakeReq(headers, host="10.0.0.1"))
        assert ei.value.status_code == 403
    # The same holds for the user gate.
    monkeypatch.setattr(web, "USER_TOKEN", "")
    with pytest.raises(HTTPException) as ei:
        await web._user_guard(_FakeReq({"x-forwarded-for": "127.0.0.1"}, host="192.168.1.9"))
    assert ei.value.status_code == 403
    await web._user_guard(_FakeReq({"x-forwarded-for": "127.0.0.1"}, host="10.0.0.1"))


@pytest.mark.asyncio
async def test_client_inside_a_listed_range_cannot_spoof_loopback_through_the_proxy(monkeypatch):
    # The operator lists the LAN the proxy lives in AND loopback. The client at
    # 10.0.0.50 types "127.0.0.1", the proxy at 10.0.0.1 appends the client's
    # address. Every hop is inside a listed range, so the walk finds no untrusted
    # hop — the answer must be the address the proxy saw (rightmost), never what
    # the client typed.
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8, 127.0.0.0/8")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    monkeypatch.setattr(web, "USER_TOKEN", "")
    req = _FakeReq({"x-forwarded-for": "127.0.0.1, 10.0.0.50"}, host="10.0.0.1")
    assert web._real_client_host(req) == "10.0.0.50"
    with pytest.raises(HTTPException) as ei:
        await web._admin_guard(req)
    assert ei.value.status_code == 403
    with pytest.raises(HTTPException) as ei:
        await web._user_guard(req)
    assert ei.value.status_code == 403
    # The rate bucket is keyed on the same honest address, not the typed one.
    assert web._client_ip(_RateReq({"x-forwarded-for": "127.0.0.1, 10.0.0.50"}, host="10.0.0.1")) == "10.0.0.50"
    # A same-box client through a loopback proxy under the legacy flag still works:
    # the proxy appended 127.0.0.1 because the client really is local.
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES")
    monkeypatch.setenv("JARVIS_TRUSTED_PROXY", "1")
    await web._admin_guard(_FakeReq({"x-forwarded-for": "127.0.0.1"}, host="127.0.0.1"))
    with pytest.raises(HTTPException):
        await web._admin_guard(_FakeReq({"x-forwarded-for": "127.0.0.1, 192.168.1.9"}, host="127.0.0.1"))


def test_rate_limit_bucket_uses_the_resolved_client(monkeypatch):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8")
    # Untrusted peer with a header → its own socket address.
    assert web._client_ip(_RateReq({"x-forwarded-for": "127.0.0.1"}, host="192.168.1.9")) == "192.168.1.9"
    # Trusted peer → the first untrusted hop from the right.
    assert web._client_ip(_RateReq({"x-forwarded-for": "127.0.0.1, 203.0.113.9, 10.0.0.5"}, host="10.0.0.1")) == "203.0.113.9"
    # Trusted peer whose chain is refused (over-long) → the peer, never "".
    long_chain = ", ".join("10.0.0.5" for _ in range(proxy_trust.MAX_FORWARDED_HOPS + 1))
    assert web._client_ip(_RateReq({"x-forwarded-for": long_chain}, host="10.0.0.1")) == "10.0.0.1"
    # No headers → the peer.
    assert web._client_ip(_RateReq(host="10.0.0.1")) == "10.0.0.1"


def test_wide_entries_are_said_once_by_position_never_by_value(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1, 10.0.0.0/8, fd00::/48")
    with caplog.at_level(logging.WARNING, logger="jarvis.proxy_trust"):
        assert len(proxy_trust.trusted_proxies()) == 3
        assert len(proxy_trust.trusted_proxies()) == 3  # memo hit: no second warning
    wide = [r.getMessage() for r in caplog.records if "wider than" in r.getMessage()]
    assert len(wide) == 2
    assert "JARVIS_TRUSTED_PROXIES: entry 2" in wide[0] and f"/{proxy_trust.WIDE_ENTRY_PREFIXLEN_V4}" in wide[0]
    assert "JARVIS_TRUSTED_PROXIES: entry 3" in wide[1] and f"/{proxy_trust.WIDE_ENTRY_PREFIXLEN_V6}" in wide[1]
    assert "10.0.0.0/8" not in caplog.text and "fd00::" not in caplog.text
    # A warning, not a refusal: the wide entries still trust their peers.
    assert proxy_trust.is_trusted_peer("10.200.1.1") is True
    # The proxy's own address is never warned about.
    caplog.clear()
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1/32, fd00::1")
    with caplog.at_level(logging.WARNING, logger="jarvis.proxy_trust"):
        proxy_trust.trusted_proxies()
    assert not any("wider than" in r.getMessage() for r in caplog.records)


def test_ipv6_mapped_and_bracketed_peers_are_recognised(monkeypatch):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1, fe80::1/128")
    assert proxy_trust.is_trusted_peer("::ffff:10.0.0.1") is True
    assert proxy_trust.is_trusted_peer("[::ffff:10.0.0.1]") is True
    assert proxy_trust.is_trusted_peer("[fe80::1]") is True
    assert proxy_trust.is_trusted_peer("fe80::1%eth0") is True
    assert proxy_trust.is_trusted_peer("::ffff:10.0.0.2") is False
    # Surrounding whitespace is tolerated (a header value, not garbage).
    assert proxy_trust.is_trusted_peer("10.0.0.1 ") is True
    for garbage in ("", "testclient", "localhost", "[10.0.0.1", "a" * 200):
        assert proxy_trust.is_trusted_peer(garbage) is False


# ── the resolved trust set is said (H691) ────────────────────────────────────
#
# Hermes logs, at info, the trust set the operator ended up with whenever it
# differs from the default. Nerva's default is "trust nothing", so any non-empty
# resolution is said: once, naming the source and the canonical networks. The
# canonical spelling is what ipaddress produced, never the raw text the operator
# typed (refusals and the wide-entry warnings still never echo the value).

def _trust_set_lines(caplog):
    return [r for r in caplog.records
            if r.name == "jarvis.proxy_trust" and r.levelno == logging.INFO
            and "trusting" in r.getMessage()]


def test_resolved_trust_set_is_logged_once_at_info_naming_source_and_networks(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "127.0.0.1, 10.0.0.5/32")
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        assert len(proxy_trust.trusted_proxies()) == 2
        assert len(proxy_trust.trusted_proxies()) == 2  # memo hit: nothing more said
    lines = _trust_set_lines(caplog)
    assert len(lines) == 1
    message = lines[0].getMessage()
    assert message.startswith("JARVIS_TRUSTED_PROXIES:")
    assert "2 proxy network(s)" in message
    assert "127.0.0.1/32, 10.0.0.5/32" in message  # canonical, in list order
    # A changed value (a rotated .env) is a new resolution and is said again.
    caplog.clear()
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "fd00::1, 10.1.2.3/24")
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        proxy_trust.trusted_proxies()
    lines = _trust_set_lines(caplog)
    assert len(lines) == 1
    assert "fd00::1/128, 10.1.2.0/24" in lines[0].getMessage()
    assert "10.1.2.3/24" not in caplog.text  # never the operator's raw spelling


def test_default_and_malformed_resolutions_say_no_trust_set(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        assert proxy_trust.trusted_proxies() == ()  # both unset: the default, nothing to say
        monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "   ")
        assert proxy_trust.trusted_proxies() == ()  # blank is the same as unset
        monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1, nonsense")
        with pytest.raises(ValueError):
            proxy_trust.trusted_proxies()  # refused, so nothing ended up trusted
    assert _trust_set_lines(caplog) == []
    assert "nonsense" not in caplog.text


def test_legacy_flag_trust_set_names_loopback(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXY", "1")
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        proxy_trust.trusted_proxies()
        proxy_trust.trusted_proxies()
    lines = _trust_set_lines(caplog)
    assert len(lines) == 1
    message = lines[0].getMessage()
    assert message.startswith("JARVIS_TRUSTED_PROXY ")
    assert "loopback only" in message
    assert "127.0.0.0/8, ::1/128" in message
    # The deprecation warning is still said alongside it, once.
    assert sum("JARVIS_TRUSTED_PROXY is deprecated" in r.getMessage() for r in caplog.records) == 1


def test_announce_says_the_set_resolved_before_logging_was_configured(monkeypatch, caplog):
    # web.py resolves the list at import, before the lifespan configures logging,
    # so that first INFO line goes nowhere. The lifespan announces the set once
    # logging and .env are both in place — exactly one line either way.
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.5")
    proxy_trust.trusted_proxies()  # the import-time resolution
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        assert proxy_trust.announce_trusted_proxies() == (proxy_trust.ip_network("10.0.0.5/32"),)
    lines = _trust_set_lines(caplog)
    assert len(lines) == 1 and "10.0.0.5/32" in lines[0].getMessage()
    # .env changed the value after import: the announce is the resolution, said once.
    caplog.clear()
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.5, 10.0.0.6")
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        proxy_trust.announce_trusted_proxies()
    lines = _trust_set_lines(caplog)
    assert len(lines) == 1 and "10.0.0.5/32, 10.0.0.6/32" in lines[0].getMessage()
    # Nothing trusted → nothing announced.
    caplog.clear()
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES")
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        assert proxy_trust.announce_trusted_proxies() == ()
    assert _trust_set_lines(caplog) == []
    # A malformed list is the boot guard's to refuse; the announce never raises and
    # says nothing was trusted by it.
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "*")
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        assert proxy_trust.announce_trusted_proxies() == ()
    assert _trust_set_lines(caplog) == []


def test_web_lifespan_announces_the_trust_set_after_logging_and_env_load():
    import inspect

    src = inspect.getsource(web.lifespan)
    logging_up = src.index("setup_logging()")
    late_guard = src.index("assert_front_door()")
    announced = src.index("announce_trusted_proxies()")
    assert logging_up < late_guard < announced
