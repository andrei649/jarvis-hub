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
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    monkeypatch.delenv("UVICORN_FORWARDED_ALLOW_IPS", raising=False)
    monkeypatch.delenv("UVICORN_PROXY_HEADERS", raising=False)
    monkeypatch.setattr(proxy_trust, "_legacy_warned", False)
    monkeypatch.setattr(proxy_trust, "_memo_key", None)
    monkeypatch.setattr(proxy_trust, "_server_layer_note", None, raising=False)
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
    # The import-time resolution, unheard: an earlier test's lifespan may already
    # have configured INFO logging in this process, so hold the logger above INFO.
    with caplog.at_level(logging.WARNING, logger="jarvis.proxy_trust"):
        proxy_trust.trusted_proxies()
    caplog.clear()
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


def test_announce_re_says_the_warnings_that_belong_with_the_trust_set(monkeypatch, caplog):
    # The wide-entry and legacy-deprecation warnings are part of the trust set's
    # story: when the set was resolved before logging could be heard, the announce
    # says them again next to the INFO line instead of leaving them on bare stderr.
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8")
    proxy_trust.trusted_proxies()  # an early resolution nobody heard
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        proxy_trust.announce_trusted_proxies()
    assert sum("entry 1 is wider than" in r.getMessage() for r in caplog.records) == 1
    assert len(_trust_set_lines(caplog)) == 1
    warned = "".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert "10.0.0.0/8" not in warned
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES")
    monkeypatch.setenv("JARVIS_TRUSTED_PROXY", "1")
    proxy_trust.trusted_proxies()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        proxy_trust.announce_trusted_proxies()
    assert sum("JARVIS_TRUSTED_PROXY is deprecated" in r.getMessage() for r in caplog.records) == 1
    assert len(_trust_set_lines(caplog)) == 1


def test_resolving_without_the_memo_says_nothing(monkeypatch, caplog):
    # web.py's informational import-time read uses the silent resolver, so the first
    # *said* resolution is the lifespan's announce — after logging is configured.
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.0/8")
    with caplog.at_level(logging.DEBUG, logger="jarvis.proxy_trust"):
        assert proxy_trust.resolve_trusted_proxies() == (proxy_trust.ip_network("10.0.0.0/8"),)
        assert proxy_trust.resolve_trusted_proxies({"JARVIS_TRUSTED_PROXY": "1"}) == proxy_trust.LOOPBACK_NETWORKS
        assert proxy_trust.resolve_trusted_proxies({}) == ()
        with pytest.raises(ValueError):
            proxy_trust.resolve_trusted_proxies({"JARVIS_TRUSTED_PROXIES": "*"})
    assert caplog.records == []
    assert proxy_trust._memo_key is None


def test_importing_the_web_app_says_nothing_on_bare_stderr(tmp_path):
    # Before logging exists a WARNING goes to logging.lastResort: bare stderr, no
    # timestamp, no redaction filter, never the log file. The import must not
    # resolve (and so warn about) the trust set; the lifespan's announce does.
    import os
    import subprocess

    env = {**os.environ, "JARVIS_TESTING": "1", "JARVIS_HOME": str(tmp_path),
           "JARVIS_TRUSTED_PROXIES": "10.0.0.0/8"}
    env.pop("JARVIS_TRUSTED_PROXY", None)
    proc = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'agents'); import agents.web"],
        cwd=str(repo_root), env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "wider than" not in proc.stderr


def test_web_lifespan_says_the_trust_set_once_after_logging_is_configured(monkeypatch):
    # Behavioural, not a source-text match: run the real lifespan and watch what the
    # proxy_trust logger says, and when, relative to setup_logging().
    from fastapi.testclient import TestClient

    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.5")
    events = []
    real_setup_logging = web.setup_logging

    def _setup_logging(*args, **kwargs):
        events.append("setup_logging")
        return real_setup_logging(*args, **kwargs)

    monkeypatch.setattr(web, "setup_logging", _setup_logging)

    class _Recorder(logging.Handler):
        def emit(self, record):
            if record.levelno == logging.INFO and "trusting" in record.getMessage():
                events.append(record.getMessage())

    trust_logger = logging.getLogger("jarvis.proxy_trust")
    recorder = _Recorder(level=logging.INFO)
    previous_level = trust_logger.level
    trust_logger.addHandler(recorder)
    trust_logger.setLevel(logging.INFO)
    try:
        with TestClient(web.app):
            pass
    finally:
        trust_logger.removeHandler(recorder)
        trust_logger.setLevel(previous_level)
    said = [event for event in events if event != "setup_logging"]
    assert said == ["JARVIS_TRUSTED_PROXIES: trusting 1 proxy network(s): 10.0.0.5/32"]
    assert events.index("setup_logging") < events.index(said[0])


# ── one trust set: uvicorn's proxy-header layer (H691 review) ────────────────
#
# uvicorn has its own forwarding-header allowlist (proxy_headers +
# forwarded_allow_ips, default loopback) that rewrites scope["client"] and
# scope["scheme"] BEFORE the app consults JARVIS_TRUSTED_PROXIES. Left on, it is a
# second, unvalidated, unlogged trust set: '*' there let a LAN peer become
# 127.0.0.1 for both gates. The served config turns it off, the app reads
# X-Forwarded-Proto itself from the same allowlist, and a uvicorn list that would
# trust more than JARVIS_TRUSTED_PROXIES (plus uvicorn's own loopback default)
# refuses boot.

def _scope_behind_served_config(cfg, peer, headers):
    """The scope the app receives behind *cfg* — mirrors uvicorn.Config.load()."""
    import asyncio

    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    captured = {}

    async def _app(scope, receive, send):
        captured["scope"] = scope

    served = _app
    if cfg.proxy_headers:
        served = ProxyHeadersMiddleware(served, trusted_hosts=cfg.forwarded_allow_ips)
    scope = {
        "type": "http", "method": "GET", "path": "/", "raw_path": b"/", "query_string": b"",
        "scheme": "http", "server": ("127.0.0.1", 8080), "client": (peer, 5555),
        "http_version": "1.1", "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        + [(b"host", b"127.0.0.1:8080")],
    }
    asyncio.run(served(scope, None, None))
    return captured["scope"]


def test_served_config_leaves_jarvis_trusted_proxies_the_only_trust_set(monkeypatch):
    from starlette.requests import Request

    import serve

    # Nothing configured: a same-box peer's forwarding headers change nothing —
    # not the client, not the scheme — and are not believed by either gate.
    cfg = serve.server_config()
    assert cfg.proxy_headers is False
    scope = _scope_behind_served_config(
        cfg, "127.0.0.1", {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"})
    assert scope["client"][0] == "127.0.0.1" and scope["scheme"] == "http"
    request = Request(scope)
    assert web._real_client_host(request) == ""
    assert web._client_ip(request) == "127.0.0.1"
    # uvicorn's own knob set to '*' next to the FLAGS.md same-box config: a LAN peer
    # typing X-Forwarded-For: 127.0.0.1 reads as loopback to neither gate.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "127.0.0.1")
    cfg = serve.server_config()
    assert cfg.proxy_headers is False
    scope = _scope_behind_served_config(cfg, "192.168.1.50", {"X-Forwarded-For": "127.0.0.1"})
    assert scope["client"][0] == "192.168.1.50"
    request = Request(scope)
    assert web._real_client_host(request) not in web._LOCALHOSTS
    assert web._client_ip(request) not in web._LOCALHOSTS


def test_unlisted_proxy_forwarding_is_not_localhost_exempt_from_the_throttle(monkeypatch):
    # With uvicorn's layer off, a same-box proxy that is NOT listed connects from
    # 127.0.0.1 for every client it forwards. The HF-2 exemption follows the same
    # origin as the localhost gate, so those requests are throttled, not waved on.
    from fastapi.testclient import TestClient

    path = "/no-such-route-h691"
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(web, "USER_TOKEN", "")
    monkeypatch.setattr(web, "_rate_hits", {})
    client = TestClient(web.app, client=("127.0.0.1", 50000))
    for _ in range(4):  # a direct loopback client is exempt
        assert client.get(path).status_code != 429
    forwarded = {"X-Forwarded-For": "192.168.1.50"}
    codes = [client.get(path, headers=forwarded).status_code for _ in range(3)]
    assert codes[-1] == 429
    # A listed proxy with a chain that vouches for nothing: throttled on the proxy's key.
    monkeypatch.setattr(web, "_rate_hits", {})
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "127.0.0.1")
    garbage = {"X-Forwarded-For": "localhost, 192.168.1.50"}
    codes = [client.get(path, headers=garbage).status_code for _ in range(3)]
    assert codes[-1] == 429
    # A listed proxy forwarding a client that really is local: exempt, as before.
    monkeypatch.setattr(web, "_rate_hits", {})
    for _ in range(4):
        assert client.get(path, headers={"X-Forwarded-For": "127.0.0.1"}).status_code != 429


def test_forwarded_proto_is_believed_only_from_a_listed_peer(monkeypatch):
    from fastapi.testclient import TestClient

    path = "/.well-known/oauth-protected-resource"
    https = {"X-Forwarded-Proto": "https"}
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.5")
    listed = TestClient(web.app, client=("10.0.0.5", 4321))
    assert listed.get(path, headers=https).json()["resource"].startswith("https://")
    assert listed.get(path).json()["resource"].startswith("http://")
    # A chained or unknown value is not a scheme a proxy vouched for.
    for value in ("https, http", "ftp", ""):
        assert listed.get(path, headers={"X-Forwarded-Proto": value}).json()["resource"].startswith("http://")
    stranger = TestClient(web.app, client=("192.168.1.50", 4321))
    assert stranger.get(path, headers=https).json()["resource"].startswith("http://")
    # The default trusts nothing — not even loopback, which uvicorn used to believe.
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES")
    local = TestClient(web.app, client=("127.0.0.1", 4321))
    assert local.get(path, headers=https).json()["resource"].startswith("http://")


def test_forwarded_proto_helper_maps_to_the_scope_type(monkeypatch):
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.5")
    fp = proxy_trust.forwarded_proto
    assert fp("10.0.0.5", ["https"]) == "https"
    assert fp("10.0.0.5", [" HTTPS "]) == "https"
    assert fp("10.0.0.5", ["http"]) == "http"
    assert fp("10.0.0.5", ["wss"]) == "https"
    assert fp("10.0.0.5", ["https"], websocket=True) == "wss"
    assert fp("10.0.0.5", ["http"], websocket=True) == "ws"
    assert fp("192.168.1.50", ["https"]) == ""
    assert fp("10.0.0.5", []) == ""
    assert fp("10.0.0.5", ["https", "http"]) == ""  # two headers: ambiguous
    assert fp("10.0.0.5", ["https,http"]) == ""
    assert fp("10.0.0.5", ["ftp"]) == ""
    assert fp("10.0.0.5", ["x" * 100]) == ""


_UVICORN_MAIN = "/venv/lib/python3.12/site-packages/uvicorn/__main__.py"


@pytest.mark.parametrize("variable", ["FORWARDED_ALLOW_IPS", "UVICORN_FORWARDED_ALLOW_IPS"])
@pytest.mark.parametrize("value", ["*", "0.0.0.0/0", "::/0", "not-an-ip", "192.168.1.0/24",
                                   "10.0.0.5, 192.168.1.50"])
def test_a_uvicorn_allow_list_wider_than_the_nerva_set_refuses_boot(variable, value):
    env = {"JARVIS_TRUSTED_PROXIES": "10.0.0.5", variable: value}
    with pytest.raises(SystemExit) as ei:
        proxy_trust.assert_server_proxy_layer_within_trust(env, argv=["pytest"])
    message = str(ei.value)
    assert message.startswith("Refusing to start:")
    assert variable in message and "JARVIS_TRUSTED_PROXIES" in message
    for entry in value.split(","):
        assert entry.strip() not in message


def test_a_uvicorn_allow_list_inside_the_nerva_set_boots():
    guard = proxy_trust.assert_server_proxy_layer_within_trust
    guard({}, argv=["pytest"])
    guard({"FORWARDED_ALLOW_IPS": "  "}, argv=["pytest"])
    guard({"FORWARDED_ALLOW_IPS": "127.0.0.1,::1"}, argv=["pytest"])  # uvicorn's own default
    guard({"JARVIS_TRUSTED_PROXIES": "10.0.0.0/24", "FORWARDED_ALLOW_IPS": "10.0.0.5, 127.0.0.1"},
          argv=["pytest"])
    guard({"JARVIS_TRUSTED_PROXY": "1", "UVICORN_FORWARDED_ALLOW_IPS": "127.0.0.1"}, argv=["pytest"])
    # A malformed JARVIS_TRUSTED_PROXIES is its own guard's refusal; this one then
    # measures against loopback alone rather than skipping the check.
    with pytest.raises(SystemExit):
        guard({"JARVIS_TRUSTED_PROXIES": "junk", "FORWARDED_ALLOW_IPS": "10.0.0.5"}, argv=["pytest"])


def test_the_uvicorn_cli_flag_is_read_only_from_a_uvicorn_command_line():
    guard = proxy_trust.assert_server_proxy_layer_within_trust
    for argv in ([_UVICORN_MAIN, "agents.web:app", "--forwarded-allow-ips", "*"],
                 ["/usr/local/bin/uvicorn", "agents.web:app", "--forwarded-allow-ips=192.168.1.0/24"]):
        with pytest.raises(SystemExit) as ei:
            guard({}, argv=argv)
        assert "--forwarded-allow-ips" in str(ei.value)
        assert "192.168.1.0/24" not in str(ei.value)
    guard({}, argv=[_UVICORN_MAIN, "agents.web:app", "--forwarded-allow-ips", "127.0.0.1"])
    guard({}, argv=["pytest", "--forwarded-allow-ips", "*"])  # not uvicorn's command line


def test_the_server_layer_is_described_from_the_launcher():
    layer = proxy_trust.server_proxy_layer
    # Unknown launcher (an embedding, a test client): uvicorn.run's defaults assumed.
    assert layer({}, argv=["pytest"]) == (True, "127.0.0.1,::1", "launcher not known")
    assert layer({"FORWARDED_ALLOW_IPS": "10.0.0.5"}, argv=["pytest"]).forwarded_allow_ips == "10.0.0.5"
    # uvicorn's CLI: the flag beats UVICORN_FORWARDED_ALLOW_IPS beats FORWARDED_ALLOW_IPS.
    env = {"FORWARDED_ALLOW_IPS": "10.0.0.7", "UVICORN_FORWARDED_ALLOW_IPS": "10.0.0.6"}
    assert layer(env, argv=[_UVICORN_MAIN, "agents.web:app"]) == (True, "10.0.0.6", "uvicorn CLI")
    flagged = [_UVICORN_MAIN, "a:b", "--forwarded-allow-ips", "10.0.0.5"]
    assert layer(env, argv=flagged).forwarded_allow_ips == "10.0.0.5"
    assert layer({"FORWARDED_ALLOW_IPS": "10.0.0.7"}, argv=[_UVICORN_MAIN, "a:b"]).forwarded_allow_ips == "10.0.0.7"
    assert layer({}, argv=[_UVICORN_MAIN, "a:b", "--no-proxy-headers"]).proxy_headers is False
    assert layer({"UVICORN_PROXY_HEADERS": "false"}, argv=[_UVICORN_MAIN, "a:b"]).proxy_headers is False
    assert layer({"UVICORN_PROXY_HEADERS": "false"},
                 argv=[_UVICORN_MAIN, "a:b", "--proxy-headers"]).proxy_headers is True
    # serve.py says what it built, and that wins over any guess.
    import serve

    serve.server_config()
    assert layer(env, argv=[_UVICORN_MAIN, "a:b"]) == (False, "", "serve.py")


def test_announce_names_the_server_proxy_layer_when_it_trusts_anything(monkeypatch, caplog):
    def _layer_lines():
        return [r.getMessage() for r in caplog.records
                if r.name == "jarvis.proxy_trust" and r.getMessage().startswith("uvicorn proxy headers")]

    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.5")
    # A raw uvicorn start with its defaults: the layer believes loopback — said.
    monkeypatch.setattr(sys, "argv", [_UVICORN_MAIN, "agents.web:app"])
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        proxy_trust.announce_trusted_proxies()
    lines = _layer_lines()
    assert len(lines) == 1
    assert "uvicorn CLI" in lines[0] and "127.0.0.1/32, ::1/128" in lines[0]
    assert "--no-proxy-headers" in lines[0]
    # The flag's value is named in canonical form.
    caplog.clear()
    monkeypatch.setattr(sys, "argv", [_UVICORN_MAIN, "agents.web:app", "--forwarded-allow-ips", "10.0.0.5"])
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        proxy_trust.announce_trusted_proxies()
    assert len(_layer_lines()) == 1 and "10.0.0.5/32" in _layer_lines()[0]
    # Switched off (the compose file's --no-proxy-headers, or serve.py): nothing to say.
    caplog.clear()
    monkeypatch.setattr(sys, "argv", [_UVICORN_MAIN, "agents.web:app", "--no-proxy-headers"])
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        proxy_trust.announce_trusted_proxies()
    assert _layer_lines() == []
    import serve

    serve.server_config()
    caplog.clear()
    monkeypatch.setattr(sys, "argv", [_UVICORN_MAIN, "agents.web:app"])
    with caplog.at_level(logging.INFO, logger="jarvis.proxy_trust"):
        proxy_trust.announce_trusted_proxies()
    assert _layer_lines() == []


def test_the_compose_entry_turns_uvicorns_layer_off():
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    line = next(ln for ln in compose.splitlines() if '"agents.web:app"' in ln)
    assert '"--no-proxy-headers"' in line
