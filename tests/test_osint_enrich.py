"""0.40 OSINT enrichment scaffold (DRA-05/DRA-10) — injectable-client pivot follow-through.

`osint/investigate.py` suggests pivots and never follows one. This covers the layer that
*does* follow them, under the rails that already exist:

* default-off — with no client injected, network pivots are refused by name, never faked;
* offline-derivable pivots (url→domain, email→domain) still resolve locally, so the
  scaffold is not merely a refusal stub;
* every enriched record is emitted with an untrusted source label, so `correlate()` keeps
  the finding tainted and `writeback_payload` still escalates GRANT→QUEUE;
* the live client (`plugins/osint_enrich.py`) is behind its own egress flag and carries the
  indicator as a *query parameter against a fixed host* — an indicator value can never
  become the request host.
"""
import sys
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.osint import enrich as en  # noqa: E402
from agents.core.osint import investigate as inv  # noqa: E402
from agents.core.osint.correlate import correlate, writeback_payload  # noqa: E402


def _evidence():
    # mirrors tests/test_osint_investigate.py::_evidence
    return [
        {"kind": "domain", "value": "acme.example", "source": "report-a"},
        {"kind": "domain", "value": "acme.example", "source": "report-b"},
        {"kind": "email", "value": "j@acme.example", "source": "report-a"},
    ]


class _FakeClient:
    """Records every call; answers only the pairs it was told to answer."""

    def __init__(self, answers=None, raises=False, supported=None):
        self.answers = answers or {}
        self.raises = raises
        self.supported = supported
        self.calls = []

    def supports(self, from_kind, to_kind):
        if self.supported is not None:
            return (from_kind, to_kind) in self.supported
        return True

    async def lookup(self, *, from_kind, from_value, to_kind):
        self.calls.append((from_kind, from_value, to_kind))
        if self.raises:
            raise RuntimeError("upstream exploded")
        return list(self.answers.get((from_kind, from_value, to_kind), []))


# ── 1. no client → refuse by name, but offline derivations still resolve ──────
@pytest.mark.asyncio
async def test_without_a_client_network_pivots_are_refused_and_never_fabricated():
    plan = inv.build_investigation(_evidence())
    result = await en.enrich_pivots(plan["pivots"], client=None)

    assert result["live_lookups_performed"] is False
    assert result["performed"] == 0
    reasons = {(r["from_kind"], r["to_kind"]): r["reason"] for r in result["refused"]}
    assert reasons[("domain", "ip")] == "enrichment_client_not_configured"
    assert reasons[("email", "username")] == "enrichment_client_not_configured"
    # ...yet the offline email→domain derivation still yields real evidence.
    derived = {(e["kind"], e["value"]) for e in result["evidence"]}
    assert ("domain", "acme.example") in derived
    assert all(e["source"] == "osint:enrich" for e in result["evidence"])


@pytest.mark.asyncio
async def test_offline_url_to_domain_derivation_needs_no_provider():
    pivots = [{"from_kind": "url", "from_value": "https://Shop.Acme.example/a?b=1",
               "to_kind": "domain", "tainted": False}]
    result = await en.enrich_pivots(pivots, client=None)
    assert [(e["kind"], e["value"]) for e in result["evidence"]] == [("domain", "shop.acme.example")]
    assert result["refused"] == []
    assert result["live_lookups_performed"] is False


@pytest.mark.asyncio
async def test_undecodable_offline_pivot_refuses_rather_than_inventing_a_value():
    pivots = [{"from_kind": "url", "from_value": "not a url at all", "to_kind": "domain"}]
    result = await en.enrich_pivots(pivots, client=None)
    assert result["evidence"] == []
    assert result["refused"][0]["reason"] == "offline_derivation_failed"


# ── 2. the governance leg: enriched evidence stays tainted end-to-end ─────────
@pytest.mark.asyncio
async def test_enriched_result_stays_tainted_through_correlate_and_writeback():
    client = _FakeClient({("domain", "acme.example", "ip"): [{"kind": "ip", "value": "203.0.113.7"}]},
                         supported={("domain", "ip")})
    plan = inv.build_investigation(_evidence())
    result = await en.enrich_pivots(plan["pivots"], client=client)

    assert result["live_lookups_performed"] is True
    assert any(e["kind"] == "ip" and e["value"] == "203.0.113.7"
               and e["source"] == "osint:enrich" for e in result["evidence"])

    drawer = correlate(_evidence() + result["evidence"])
    ip_finding = next(f for f in drawer["findings"] if f["kind"] == "ip")
    assert ip_finding["tainted"] is True
    payload = writeback_payload(ip_finding)
    assert payload["tainted"] is True
    assert "osint:enrich" in payload["taint_source"]


@pytest.mark.asyncio
async def test_taint_of_the_originating_pivot_is_carried_even_for_untagged_records():
    client = _FakeClient({("domain", "bad.example", "ip"): [{"kind": "ip", "value": "198.51.100.9"}]},
                         supported={("domain", "ip")})
    pivots = [{"from_kind": "domain", "from_value": "bad.example", "to_kind": "ip", "tainted": True}]
    result = await en.enrich_pivots(pivots, client=client)
    record = result["evidence"][0]
    assert record["tainted"] is True
    assert record["pivot_tainted"] is True


# ── 3. bounds and robustness ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_lookup_budget_caps_client_calls_and_refuses_the_rest():
    client = _FakeClient(supported={("domain", "ip"), ("domain", "url"), ("domain", "email"),
                                    ("email", "username")})
    plan = inv.build_investigation(_evidence())
    result = await en.enrich_pivots(plan["pivots"], client=client, max_lookups=2)

    assert len(client.calls) == 2
    assert result["performed"] == 2
    assert any(r["reason"] == "lookup_budget_exhausted" for r in result["refused"])


@pytest.mark.asyncio
async def test_a_junk_budget_degrades_instead_of_crashing():
    client = _FakeClient(supported={("domain", "ip")})
    pivots = [{"from_kind": "domain", "from_value": "acme.example", "to_kind": "ip"}]
    result = await en.enrich_pivots(pivots, client=client, max_lookups="banana")
    assert result["performed"] == 1  # coerced to the documented default, not a crash


@pytest.mark.asyncio
async def test_a_raising_client_becomes_a_refusal_not_an_exception():
    client = _FakeClient(raises=True, supported={("domain", "ip")})
    pivots = [{"from_kind": "domain", "from_value": "acme.example", "to_kind": "ip"}]
    result = await en.enrich_pivots(pivots, client=client)
    assert result["evidence"] == []
    assert result["refused"][0]["reason"] == "lookup_failed"


@pytest.mark.asyncio
async def test_unsupported_pair_says_provider_not_configured():
    client = _FakeClient(supported=set())
    pivots = [{"from_kind": "domain", "from_value": "acme.example", "to_kind": "ip"}]
    result = await en.enrich_pivots(pivots, client=client)
    assert result["refused"][0]["reason"] == "provider_not_configured"


@pytest.mark.asyncio
async def test_identical_records_are_deduped_on_kind_and_value():
    client = _FakeClient({
        ("domain", "acme.example", "ip"): [
            {"kind": "ip", "value": "203.0.113.7"},
            {"kind": "ip", "value": "203.0.113.7"},
            {"kind": "ip", "value": "203.0.113.8"},
        ]
    }, supported={("domain", "ip")})
    pivots = [{"from_kind": "domain", "from_value": "acme.example", "to_kind": "ip"}]
    result = await en.enrich_pivots(pivots, client=client)
    assert [e["value"] for e in result["evidence"]] == ["203.0.113.7", "203.0.113.8"]


# ── 4. investigate_and_enrich composes without changing the offline contract ──
@pytest.mark.asyncio
async def test_investigate_and_enrich_offline_matches_the_plan_and_stays_honest():
    plan = inv.build_investigation(_evidence())
    out = await en.investigate_and_enrich(_evidence(), client=None)
    assert out["leads"] == plan["leads"]
    assert out["pivots"] == plan["pivots"]
    assert out["live_lookups_performed"] is False
    assert "No live lookup" in out["caveats"][0]
    assert any("not followed" in c for c in out["caveats"])
    assert out["drawer"]["counts"]["findings"] >= plan["counts"]["findings"]


@pytest.mark.asyncio
async def test_investigate_and_enrich_reports_live_lookups_without_touching_the_planner():
    client = _FakeClient({("domain", "acme.example", "ip"): [{"kind": "ip", "value": "203.0.113.7"}]},
                         supported={("domain", "ip")})
    out = await en.investigate_and_enrich(_evidence(), client=client)
    assert out["live_lookups_performed"] is True
    assert "No live lookup" not in out["caveats"][0]
    assert any(f["value"] == "203.0.113.7" for f in out["drawer"]["findings"])
    # the offline planner's own contract is untouched
    assert inv.build_investigation(_evidence())["live_lookups_performed"] is False


# ── 5. the live plugin: default-off, fixed host, indicator never the host ─────
class _RecordingHTTP:
    def __init__(self, payload=None):
        self.payload = payload or {}
        self.requests = []

    async def get(self, url, params=None, **kwargs):
        self.requests.append((url, dict(params or {})))
        return _Resp(self.payload)

    async def close(self):
        pass


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_plugin_is_default_off_and_makes_zero_requests(monkeypatch):
    from agents.core.plugins.osint_enrich import OsintEnrichPlugin

    monkeypatch.delenv("JARVIS_OSINT_ENRICH", raising=False)
    http = _RecordingHTTP()
    plugin = OsintEnrichPlugin(http_client=http)
    assert plugin.enabled() is False
    assert plugin.supports("domain", "ip") is False
    assert await plugin.lookup(from_kind="domain", from_value="acme.example", to_kind="ip") == []
    assert http.requests == []


@pytest.mark.asyncio
async def test_plugin_resolves_an_a_record_with_the_indicator_as_a_query_param(monkeypatch):
    from agents.core.plugins.osint_enrich import OsintEnrichPlugin

    monkeypatch.setenv("JARVIS_OSINT_ENRICH", "1")
    http = _RecordingHTTP({"Status": 0, "Answer": [{"type": 1, "data": "203.0.113.7"},
                                                   {"type": 5, "data": "cname.example."}]})
    plugin = OsintEnrichPlugin(http_client=http)
    assert plugin.supports("domain", "ip") is True
    records = await plugin.lookup(from_kind="domain", from_value="acme.example", to_kind="ip")
    assert [(r["kind"], r["value"]) for r in records] == [("ip", "203.0.113.7")]

    url, params = http.requests[0]
    assert url == "https://dns.google/resolve"          # fixed host, always
    assert params["name"] == "acme.example"             # indicator rides as a parameter
    assert params["type"] == "A"


@pytest.mark.asyncio
async def test_plugin_never_lets_an_indicator_become_the_request_host(monkeypatch):
    """The whole reason the resolvers are keyless-fixed-host: a hostile indicator
    must not be able to steer egress at an internal address."""
    from urllib.parse import urlparse

    from agents.core.plugins.osint_enrich import OsintEnrichPlugin

    monkeypatch.setenv("JARVIS_OSINT_ENRICH", "1")
    http = _RecordingHTTP({"Status": 0, "Answer": []})
    plugin = OsintEnrichPlugin(http_client=http)
    for value in ("169.254.169.254", "127.0.0.1"):
        await plugin.lookup(from_kind="ip", from_value=value, to_kind="domain")
        await plugin.lookup(from_kind="ip", from_value=value, to_kind="asn")
    hosts = {urlparse(url).hostname for url, _ in http.requests}
    assert hosts == {"dns.google"}


@pytest.mark.asyncio
async def test_plugin_refuses_a_malformed_indicator_without_dialing(monkeypatch):
    from agents.core.plugins.osint_enrich import OsintEnrichPlugin

    monkeypatch.setenv("JARVIS_OSINT_ENRICH", "1")
    http = _RecordingHTTP({"Status": 0, "Answer": []})
    plugin = OsintEnrichPlugin(http_client=http)
    assert await plugin.lookup(from_kind="domain", from_value="../../etc/passwd",
                               to_kind="ip") == []
    assert await plugin.lookup(from_kind="ip", from_value="not-an-ip", to_kind="asn") == []
    assert http.requests == []


@pytest.mark.asyncio
async def test_plugin_declines_pairs_no_keyless_resolver_covers(monkeypatch):
    from agents.core.plugins.osint_enrich import OsintEnrichPlugin

    monkeypatch.setenv("JARVIS_OSINT_ENRICH", "1")
    plugin = OsintEnrichPlugin(http_client=_RecordingHTTP())
    assert plugin.supports("username", "email") is False
    assert await plugin.lookup(from_kind="username", from_value="jdoe", to_kind="email") == []


@pytest.mark.asyncio
async def test_disabled_plugin_drives_the_scaffold_to_provider_not_configured(monkeypatch):
    from agents.core.plugins.osint_enrich import OsintEnrichPlugin

    monkeypatch.delenv("JARVIS_OSINT_ENRICH", raising=False)
    plugin = OsintEnrichPlugin(http_client=_RecordingHTTP())
    pivots = [{"from_kind": "domain", "from_value": "acme.example", "to_kind": "ip"}]
    result = await en.enrich_pivots(pivots, client=plugin)
    assert result["live_lookups_performed"] is False
    assert result["refused"][0]["reason"] == "provider_not_configured"


# ── 6. the static egress guard ───────────────────────────────────────────────
def test_manifest_pins_only_the_host_the_plugin_actually_dials():
    from agents.core.plugin_gate import BUILTIN_PLUGINS, DataScope, NetworkAccess

    manifest = BUILTIN_PLUGINS["osint_enrich"]
    # rdap.org was allowlisted for an ip->asn resolver that could never work; an egress
    # host no resolver dials is permission surface with nothing behind it.
    assert manifest.allowed_domains == ["dns.google"]
    assert manifest.network_access is NetworkAccess.RESTRICTED
    # indicator values genuinely leave the machine — the manifest must say so
    assert manifest.data_scope is DataScope.TRANSMITTED


def test_the_egress_boundary_blocks_a_host_the_manifest_does_not_name(monkeypatch):
    """Under strict egress, the indicator's own domain is not a place we may dial."""
    from agents.core.http_client import PluginEgressError, PluginHTTPClient

    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    client = PluginHTTPClient.for_plugin("osint_enrich")
    client._enforce_egress("https://dns.google/resolve?name=acme.example")
    with pytest.raises(PluginEgressError):
        client._enforce_egress("https://acme.example/resolve")


# ── 7. resolver isolation, and the ip→asn claim the code could never keep ─────
class _Resp302:
    """What ``rdap.org`` really answers: a 302 to the registry that holds the record.

    ``PluginHTTPClient`` pins DNS and runs ``follow_redirects=False``, and httpx's
    ``raise_for_status`` rejects every non-2xx — 3xx included. So a redirecting host is
    not a slow resolver, it is a resolver that raises on the first byte, every time.
    """

    status_code = 302

    def raise_for_status(self):
        request = httpx.Request("GET", "https://dns.google/resolve")
        httpx.Response(
            302, headers={"location": "https://elsewhere.example/"}, request=request
        ).raise_for_status()

    def json(self):  # pragma: no cover - raise_for_status fires first
        return {}


class _PartlyDeadHTTP:
    """One resolver that always redirects, next to one that answers."""

    def __init__(self):
        self.requests = []

    async def get(self, url, params=None, **kwargs):
        params = dict(params or {})
        self.requests.append((url, params))
        if params.get("type") == "PTR":
            return _Resp302()
        return _Resp({"Status": 0, "Answer": [{"type": 1, "data": "203.0.113.7"}]})

    async def close(self):
        pass


async def _no_sleep(*_args, **_kwargs):
    return None


def _clear_osint_breakers():
    from agents.core.resilience import _circuit_breakers

    for key in [k for k in _circuit_breakers if k.startswith("plugin:osint_enrich")]:
        _circuit_breakers.pop(key)


@pytest.mark.asyncio
async def test_a_redirecting_resolver_cannot_open_the_breaker_of_a_working_one(monkeypatch):
    """A dead pivot burns its own retry budget — never the live resolvers' availability."""
    from agents.core.plugins.osint_enrich import OsintEnrichPlugin

    monkeypatch.setenv("JARVIS_OSINT_ENRICH", "1")
    monkeypatch.setattr("agents.core.resilience.asyncio.sleep", _no_sleep)
    _clear_osint_breakers()
    http = _PartlyDeadHTTP()
    plugin = OsintEnrichPlugin(http_client=http)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await plugin.lookup(from_kind="ip", from_value="8.8.8.8", to_kind="domain")
        # three attempts, three failures — enough to trip a threshold-3 breaker
        assert len([p for _, p in http.requests if p.get("type") == "PTR"]) == 3
        from agents.core.resilience import _circuit_breakers
        assert _circuit_breakers["plugin:osint_enrich:dns_ptr"].state == "open"
        assert "plugin:osint_enrich:dns_a" not in _circuit_breakers

        records = await plugin.lookup(from_kind="domain", from_value="acme.example",
                                      to_kind="ip")
        assert [(r["kind"], r["value"]) for r in records] == [("ip", "203.0.113.7")]
    finally:
        _clear_osint_breakers()


@pytest.mark.asyncio
async def test_ip_to_asn_is_not_advertised_because_no_keyless_resolver_reaches_it(monkeypatch):
    """An absent capability beats one advertised in a docstring the code cannot honour."""
    from agents.core.plugins import osint_enrich as oe

    assert ("ip", "asn") not in oe.RESOLVERS
    assert set(oe.RESOLVERS) == {("domain", "ip"), ("ip", "domain")}
    # the dead RDAP resolver and its URL are gone, not merely unreferenced
    assert not hasattr(oe, "RDAP_IP_URL")
    assert not hasattr(oe.OsintEnrichPlugin, "_resolve_origin_asn")

    monkeypatch.setenv("JARVIS_OSINT_ENRICH", "1")
    http = _RecordingHTTP()
    plugin = oe.OsintEnrichPlugin(http_client=http)
    assert plugin.supports("ip", "asn") is False
    assert await plugin.lookup(from_kind="ip", from_value="8.8.8.8", to_kind="asn") == []
    assert http.requests == []
