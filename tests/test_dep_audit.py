"""H022 — audit installed dependencies for known vulnerabilities.

The SBOM has been generated for months and checked against nothing. This pins
the audit that closes that gap: enumerate what is actually installed in this
interpreter plus the exact Python pins extensions declare, ask OSV.dev, and
rank what comes back. Three properties matter more than the happy path and
each has its own test:

* an advisory whose severity OSV does not state is never treated as safe —
  ``unknown`` fails every ``--fail-on`` threshold;
* a database that could not be reached is ``unavailable``, never ``clean`` —
  the report says nothing is claimed, and the exit code is distinct from both
  "clean" and "findings" so a script can tell the three apart;
* the network client is injected, so nothing here touches OSV.dev.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.core.security import dep_audit
from agents.core.security.dep_audit import (
    BATCH_LIMIT,
    Component,
    OSVUnavailable,
    audit,
    enumerate_extensions,
    enumerate_installed,
    fixed_in,
    mcp_surface,
    normalize_severity,
    render,
)

# ── fakes ─────────────────────────────────────────────────────────────────────


def _dist(name: str, version: str):
    return SimpleNamespace(metadata={"Name": name}, version=version)


def _vuln(vid, package, *, severity=None, fixed=None, aliases=(), cvss=None,
          affected_severity=None, summary="something bad"):
    affected = {"package": {"name": package, "ecosystem": "PyPI"},
                "ranges": [{"type": "ECOSYSTEM",
                            "events": [{"introduced": "0"}] + ([{"fixed": fixed}] if fixed else [])}]}
    if affected_severity:
        affected["database_specific"] = {"severity": affected_severity}
    body = {"id": vid, "aliases": list(aliases), "summary": summary, "affected": [affected]}
    if severity:
        body["database_specific"] = {"severity": severity}
    if cvss:
        body["severity"] = [{"type": "CVSS_V3", "score": cvss}]
    return body


class FakeOSV:
    def __init__(self, hits=None, vulns=None, *, fail_batch=None, fail_detail=()):
        self.hits = hits or {}
        self.vulns = vulns or {}
        self.fail_batch = fail_batch
        self.fail_detail = set(fail_detail)
        self.batches: list[list[dict]] = []
        self.detail_calls: list[str] = []

    def query_batch(self, queries):
        if self.fail_batch:
            raise OSVUnavailable(self.fail_batch)
        self.batches.append(list(queries))
        return [list(self.hits.get((q["package"]["name"], q["version"]), [])) for q in queries]

    def vulnerability(self, vuln_id):
        self.detail_calls.append(vuln_id)
        if vuln_id in self.fail_detail:
            raise OSVUnavailable("detail fetch failed")
        return self.vulns[vuln_id]


def _installed(*pairs):
    return [Component("installed", name, version, "importlib.metadata") for name, version in pairs]


# ── enumeration ───────────────────────────────────────────────────────────────


def test_installed_enumeration_normalizes_names_and_dedupes():
    comps = enumerate_installed([_dist("Foo_Bar", "1.0"), _dist("foo-bar", "1.0"), _dist("Baz", "2.1")])
    assert [(c.name, c.version) for c in comps] == [("baz", "2.1"), ("foo-bar", "1.0")]
    assert {c.surface for c in comps} == {"installed"}


def test_installed_enumeration_skips_nameless_or_versionless_distributions():
    comps = enumerate_installed([
        SimpleNamespace(metadata={}, version="1.0"),
        SimpleNamespace(metadata={"Name": "ok"}, version=None),
        _dist("keep", "3.0"),
    ])
    assert [(c.name, c.version) for c in comps] == [("keep", "3.0")]


def _manifest(tmp_path, name, python):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({
        "manifest_version": 1, "api_version": 1, "id": name, "version": "1.0.0",
        "capabilities": ["tools"], "tools": ["noop"], "commands": [], "events": [],
        "requires": {"extensions": {}, "python": python},
    }), encoding="utf-8")
    return path


def test_extension_manifests_contribute_exact_python_pins(tmp_path):
    a = _manifest(tmp_path, "alpha", {"requests": "2.19.0"})
    b = _manifest(tmp_path, "beta", {"httpx": "0.27.0", "requests": "2.19.0"})
    comps, errors = enumerate_extensions([a, b])
    assert errors == []
    assert sorted((c.name, c.version, c.origin) for c in comps) == [
        ("httpx", "0.27.0", "beta"), ("requests", "2.19.0", "alpha"), ("requests", "2.19.0", "beta"),
    ]
    assert {c.surface for c in comps} == {"extension"}


def test_an_invalid_manifest_is_reported_not_fatal(tmp_path):
    good = _manifest(tmp_path, "alpha", {"requests": "2.19.0"})
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    comps, errors = enumerate_extensions([good, bad, tmp_path / "missing.json"])
    assert [(c.name, c.version) for c in comps] == [("requests", "2.19.0")]
    assert [e["reason"] for e in errors] == ["manifest_unreadable", "manifest_not_regular_file"]
    # descriptor paths are not reflected back — only the normalized reason is
    assert all(str(tmp_path) not in json.dumps(e) for e in errors)


def test_mcp_surface_is_declared_empty_with_its_reason():
    surface = mcp_surface()
    assert surface["count"] == 0
    assert "HTTP" in surface["reason"]


# ── severity ──────────────────────────────────────────────────────────────────


def test_severity_prefers_database_specific_then_affected_then_unknown():
    assert normalize_severity(_vuln("A", "x", severity="HIGH"), "x") == ("high", "database_specific")
    assert normalize_severity(_vuln("B", "x", severity="MODERATE"), "x") == ("moderate", "database_specific")
    assert normalize_severity(_vuln("C", "x", severity="MEDIUM"), "x") == ("moderate", "database_specific")
    assert normalize_severity(_vuln("D", "x", affected_severity="CRITICAL"), "x") == ("critical", "affected")
    # a CVSS vector alone is not a level; we do not compute a score we cannot vouch for
    assert normalize_severity(_vuln("E", "x", cvss="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"), "x") == ("unknown", "none")
    assert normalize_severity(_vuln("F", "x", severity="WHATEVER"), "x") == ("unknown", "none")


def test_fixed_in_reads_the_matching_package_range_only():
    v = _vuln("A", "requests", fixed="2.32.4")
    assert fixed_in(v, "requests") == "2.32.4"
    assert fixed_in(v, "Requests") == "2.32.4"            # PyPI names are case-insensitive
    assert fixed_in(v, "other") is None
    assert fixed_in(_vuln("B", "requests"), "requests") is None


# ── the audit ─────────────────────────────────────────────────────────────────


def test_findings_are_sorted_by_severity_then_package_then_id():
    comps = _installed(("zeta", "1.0"), ("alpha", "2.0"))
    osv = FakeOSV(
        hits={("zeta", "1.0"): ["GHSA-low"], ("alpha", "2.0"): ["GHSA-crit", "GHSA-high"]},
        vulns={"GHSA-low": _vuln("GHSA-low", "zeta", severity="LOW"),
               "GHSA-crit": _vuln("GHSA-crit", "alpha", severity="CRITICAL"),
               "GHSA-high": _vuln("GHSA-high", "alpha", severity="HIGH")},
    )
    report = audit(comps, osv, fail_on="low")
    assert [(f.severity, f.name, f.id) for f in report.findings] == [
        ("critical", "alpha", "GHSA-crit"), ("high", "alpha", "GHSA-high"), ("low", "zeta", "GHSA-low"),
    ]
    assert report.status == "findings" and len(report.failing()) == 3


def test_unknown_severity_fails_every_threshold():
    comps = _installed(("pkg", "1.0"))
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-unrated"]},
                  vulns={"GHSA-unrated": _vuln("GHSA-unrated", "pkg")})
    for threshold in ("low", "moderate", "high", "critical"):
        report = audit(comps, osv, fail_on=threshold)
        assert report.status == "findings", threshold
        assert [f.id for f in report.failing()] == ["GHSA-unrated"]


def test_fail_on_threshold_filters_the_verdict_but_not_the_listing():
    comps = _installed(("pkg", "1.0"))
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-mod"]},
                  vulns={"GHSA-mod": _vuln("GHSA-mod", "pkg", severity="MODERATE")})
    report = audit(comps, osv, fail_on="high")
    assert report.status == "clean"
    assert [f.id for f in report.findings] == ["GHSA-mod"]     # still listed
    assert report.failing() == []
    assert audit(comps, osv, fail_on="moderate").status == "findings"


def test_ignore_matches_the_id_or_any_alias_case_insensitively():
    comps = _installed(("pkg", "1.0"))
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-a", "GHSA-b"]},
                  vulns={"GHSA-a": _vuln("GHSA-a", "pkg", severity="HIGH", aliases=("CVE-2024-1",)),
                         "GHSA-b": _vuln("GHSA-b", "pkg", severity="HIGH")})
    report = audit(comps, osv, fail_on="low", ignore=("cve-2024-1",))
    assert [f.id for f in report.findings] == ["GHSA-b"]
    assert [f.id for f in report.ignored] == ["GHSA-a"]
    assert report.status == "findings"
    assert audit(comps, osv, fail_on="low", ignore=("ghsa-a", "GHSA-B")).status == "clean"


def test_queries_are_chunked_at_the_osv_batch_limit():
    comps = _installed(*[(f"p{i}", "1.0") for i in range(BATCH_LIMIT + 1)])
    osv = FakeOSV()
    report = audit(comps, osv, fail_on="low")
    assert [len(b) for b in osv.batches] == [BATCH_LIMIT, 1]
    assert report.queried == BATCH_LIMIT + 1 and report.status == "clean"


def test_a_database_that_cannot_be_reached_is_unavailable_never_clean():
    comps = _installed(("pkg", "1.0"))
    report = audit(comps, FakeOSV(fail_batch="connection refused"), fail_on="low")
    assert report.status == "unavailable"
    assert report.unavailable == "connection refused"
    assert report.findings == [] and report.failing() == []
    text = render(report)
    assert "nothing is claimed" in text.lower() and "clean" not in text.lower()


def test_a_missing_advisory_detail_keeps_the_finding_as_unknown_not_dropped():
    comps = _installed(("pkg", "1.0"))
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-gone", "GHSA-ok"]},
                  vulns={"GHSA-ok": _vuln("GHSA-ok", "pkg", severity="LOW")},
                  fail_detail=("GHSA-gone",))
    report = audit(comps, osv, fail_on="critical")
    gone = next(f for f in report.findings if f.id == "GHSA-gone")
    assert gone.severity == "unknown" and gone.severity_source == "detail_unavailable"
    assert [f.id for f in report.failing()] == ["GHSA-gone"]   # unknown fails even at critical
    assert report.status == "findings"


def test_each_advisory_is_fetched_once_even_when_several_components_share_it():
    comps = _installed(("pkg", "1.0")) + [Component("extension", "pkg", "1.0", "alpha")]
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-x"]}, vulns={"GHSA-x": _vuln("GHSA-x", "pkg", severity="LOW")})
    report = audit(comps, osv, fail_on="low")
    assert osv.detail_calls == ["GHSA-x"]
    assert sorted(f.surface for f in report.findings) == ["extension", "installed"]


def test_report_round_trips_to_json_and_names_every_surface():
    comps = _installed(("pkg", "1.0"))
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-x"]},
                  vulns={"GHSA-x": _vuln("GHSA-x", "pkg", severity="HIGH", fixed="1.1", aliases=("CVE-1",))})
    report = audit(comps, osv, fail_on="low", extension_errors=[{"reason": "manifest_unreadable"}])
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["status"] == "findings" and payload["fail_on"] == "low"
    assert set(payload["surfaces"]) == {"installed", "extension", "mcp"}
    assert payload["surfaces"]["mcp"]["count"] == 0
    assert payload["errors"] == [{"reason": "manifest_unreadable"}]
    f = payload["findings"][0]
    assert f == {"surface": "installed", "name": "pkg", "version": "1.0", "origin": "importlib.metadata",
                 "id": "GHSA-x", "aliases": ["CVE-1"], "severity": "high",
                 "severity_source": "database_specific", "fixed_in": "1.1", "summary": "something bad"}


def test_render_lists_findings_with_severity_first_and_fix_when_known():
    comps = _installed(("pkg", "1.0"))
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-x"]},
                  vulns={"GHSA-x": _vuln("GHSA-x", "pkg", severity="HIGH", fixed="1.1", aliases=("CVE-1",))})
    text = render(audit(comps, osv, fail_on="low"))
    line = next(line for line in text.splitlines() if "GHSA-x" in line)
    assert line.startswith("HIGH") and "pkg 1.0" in line and "CVE-1" in line and "fixed in 1.1" in line
    assert "1 finding" in text and "osv.dev" in text.lower()


def test_offline_report_claims_nothing():
    report = dep_audit.offline_report(_installed(("pkg", "1.0")))
    assert report.status == "offline" and report.findings == [] and report.queried == 0
    assert "nothing is claimed" in render(report).lower()


@pytest.mark.parametrize("bad", ["", "http://api.osv.dev", "ftp://x", "api.osv.dev"])
def test_the_osv_endpoint_must_be_https(bad):
    with pytest.raises(ValueError):
        dep_audit.default_client(bad)


# ── alias merging (what the live data showed) ─────────────────────────────────


def _live_pair(component="requests"):
    """The shape OSV actually returns: a rated GHSA and an unrated PYSEC mirror of one CVE."""
    ghsa = _vuln("GHSA-9hjg-9r4m-mvj7", component, severity="MODERATE", fixed="2.32.4",
                 aliases=("CVE-2024-47081", "PYSEC-2026-1872"))
    pysec = _vuln("PYSEC-2026-1872", component, fixed="2.32.4",
                  aliases=("CVE-2024-47081", "GHSA-9hjg-9r4m-mvj7"),
                  cvss="CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:H/I:N/A:N")
    return {ghsa["id"]: ghsa, pysec["id"]: pysec}


def test_a_pysec_mirror_merges_into_its_rated_ghsa_advisory():
    comps = _installed(("requests", "2.19.0"))
    osv = FakeOSV(hits={("requests", "2.19.0"): ["GHSA-9hjg-9r4m-mvj7", "PYSEC-2026-1872"]}, vulns=_live_pair())
    report = audit(comps, osv, fail_on="low")
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f.id == "GHSA-9hjg-9r4m-mvj7" and f.severity == "moderate" and f.severity_source == "database_specific"
    assert f.aliases == ("CVE-2024-47081", "PYSEC-2026-1872") and f.fixed_in == "2.32.4"
    # the whole point: a moderate issue must not fail a high bar because of its unrated mirror
    assert audit(comps, osv, fail_on="high").status == "clean"
    assert audit(comps, osv, fail_on="moderate").status == "findings"


def test_merge_keeps_the_best_stated_severity_and_every_id():
    comps = _installed(("pkg", "1.0"))
    vulns = {
        "GHSA-a": _vuln("GHSA-a", "pkg", severity="LOW", aliases=("CVE-1",)),
        "OTHER-b": _vuln("OTHER-b", "pkg", severity="CRITICAL", aliases=("CVE-1",), fixed="1.9"),
    }
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-a", "OTHER-b"]}, vulns=vulns)
    report = audit(comps, osv, fail_on="low")
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f.id == "OTHER-b" and f.severity == "critical" and f.fixed_in == "1.9"
    assert f.aliases == ("CVE-1", "GHSA-a")


def test_merge_does_not_join_unrelated_advisories():
    comps = _installed(("pkg", "1.0"))
    vulns = {"GHSA-a": _vuln("GHSA-a", "pkg", severity="LOW", aliases=("CVE-1",)),
             "GHSA-b": _vuln("GHSA-b", "pkg", severity="LOW", aliases=("CVE-2",))}
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-a", "GHSA-b"]}, vulns=vulns)
    assert [f.id for f in audit(comps, osv, fail_on="low").findings] == ["GHSA-a", "GHSA-b"]


def test_ignoring_a_merged_mirror_id_ignores_the_whole_issue():
    comps = _installed(("requests", "2.19.0"))
    osv = FakeOSV(hits={("requests", "2.19.0"): ["GHSA-9hjg-9r4m-mvj7", "PYSEC-2026-1872"]}, vulns=_live_pair())
    report = audit(comps, osv, fail_on="low", ignore=("pysec-2026-1872",))
    assert report.findings == [] and [f.id for f in report.ignored] == ["GHSA-9hjg-9r4m-mvj7"]
    assert report.status == "clean"


def test_an_unfetchable_mirror_merges_through_its_siblings_alias_list():
    comps = _installed(("requests", "2.19.0"))
    osv = FakeOSV(hits={("requests", "2.19.0"): ["GHSA-9hjg-9r4m-mvj7", "PYSEC-2026-1872"]},
                  vulns=_live_pair(), fail_detail=("PYSEC-2026-1872",))
    report = audit(comps, osv, fail_on="critical")
    assert [f.id for f in report.findings] == ["GHSA-9hjg-9r4m-mvj7"]
    assert report.findings[0].severity == "moderate"       # the sibling rates it; not unknown
    assert report.status == "clean"


def test_an_unfetchable_advisory_with_no_rated_sibling_still_fails():
    comps = _installed(("pkg", "1.0"))
    osv = FakeOSV(hits={("pkg", "1.0"): ["GHSA-lonely"]}, vulns={}, fail_detail=("GHSA-lonely",))
    report = audit(comps, osv, fail_on="critical")
    assert report.findings[0].severity == "unknown" and report.status == "findings"
