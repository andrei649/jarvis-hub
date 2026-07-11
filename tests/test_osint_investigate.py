"""0.40 OSINT Investigator Pack — offline investigation planner.

Prioritized leads + pivot suggestions over the correlate drawer; never performs a live lookup
(`live_lookups_performed: False`), taint stays visible, deterministic.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.osint import investigate as inv  # noqa: E402


def _evidence():
    # two corroborating sightings of one domain + one email, mixed sources
    return [
        {"kind": "domain", "value": "acme.example", "source": "report-a"},
        {"kind": "domain", "value": "acme.example", "source": "report-b"},
        {"kind": "email", "value": "j@acme.example", "source": "report-a"},
    ]




def test_investigation_prioritizes_leads_and_suggests_pivots():
    plan = inv.build_investigation(_evidence())
    assert plan["live_lookups_performed"] is False        # never enriches
    kinds = {ld["kind"] for ld in plan["leads"]}
    assert {"domain", "email"} <= kinds
    # domain → ip/url/email pivots; email → domain/username pivots (deterministic)
    to_kinds = {(p["from_kind"], p["to_kind"]) for p in plan["pivots"]}
    assert ("domain", "ip") in to_kinds
    assert ("email", "username") in to_kinds
    assert "No live lookup" in plan["caveats"][0]




def test_pivots_are_deduped_and_bounded():
    # many repeats of the same domain → pivots dedupe by (from,value,to)
    ev = [{"kind": "domain", "value": "x.example", "source": f"s{i}"} for i in range(30)]
    plan = inv.build_investigation(ev)
    pv = plan["pivots"]
    assert len(pv) == len({(p["from_kind"], p["from_value"], p["to_kind"]) for p in pv})
    assert len(pv) <= inv._MAX_PIVOTS




def test_tainted_source_flags_leads_pivots_and_caveats():
    ev = [{"kind": "domain", "value": "bad.example", "source": "rss"}]   # rss = untrusted
    plan = inv.build_investigation(ev)
    assert plan["untrusted_ingestion"] is True
    assert all(p["tainted"] for p in plan["pivots"])
    assert any("untrusted" in cav for cav in plan["caveats"])




def test_empty_evidence_is_honest():
    plan = inv.build_investigation([])
    assert plan["leads"] == [] and plan["pivots"] == []
    assert plan["headline"] == "no leads correlated"
    assert plan["live_lookups_performed"] is False




def test_deterministic():
    a = inv.build_investigation(_evidence())
    b = inv.build_investigation(_evidence())
    assert a == b



def test_missing_or_unknown_source_fails_closed_as_tainted():
    for evidence in (
        {"kind": "domain", "value": "unknown.example"},
        {"kind": "domain", "value": "unknown.example", "source": "mystery-feed"},
    ):
        plan = inv.build_investigation([evidence])
        assert plan["untrusted_ingestion"] is True
        assert plan["leads"][0]["tainted"] is True
        assert all(pivot["tainted"] for pivot in plan["pivots"])
        assert any("untrusted" in caveat for caveat in plan["caveats"])




def test_explicit_manual_source_remains_trusted():
    plan = inv.build_investigation([
        {"kind": "domain", "value": "operator.example", "source": "manual"}
    ])
    assert plan["untrusted_ingestion"] is False
    assert plan["leads"][0]["tainted"] is False




def test_bad_top_value_degrades_to_default_instead_of_crashing():
    plan = inv.build_investigation(_evidence(), top="not-a-number")
    assert plan["leads"]



def test_non_finite_top_value_degrades_safely():
    plan = inv.build_investigation(_evidence(), top=float("inf"))
    assert plan["leads"]




def test_source_labels_are_canonical_for_corroboration():
    plan = inv.build_investigation([
        {"kind": "domain", "value": "same.example", "source": " Manual "},
        {"kind": "domain", "value": "same.example", "source": "manual"},
    ])
    lead = plan["leads"][0]
    assert lead["sources"] == ["manual"]
    assert plan["counts"]["corroborated"] == 0




def test_base_brief_also_degrades_bad_top_values():
    from core.osint.correlate import build_brief

    brief = build_brief(_evidence(), top="bad")
    assert brief["top"]


def test_mixed_source_writeback_records_the_untrusted_origin():
    from core.osint.correlate import correlate, writeback_payload

    drawer = correlate([
        {"kind": "domain", "value": "mixed.example", "source": "manual"},
        {"kind": "domain", "value": "mixed.example", "source": "rss"},
    ])
    payload = writeback_payload(drawer["findings"][0])

    assert payload["tainted"] is True
    assert payload["taint_source"] == "rss"

