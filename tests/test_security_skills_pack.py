"""0.42 — Security Skills Pack: curated, honest, offline defensive-security knowledge."""

from agents.core import security_skills as sk
from agents.core.security_skills import pack


def test_tactics_are_complete_and_carry_provenance():
    out = sk.tactics()
    assert out["count"] == 14                      # ATT&CK enterprise tactics, complete
    assert out["curated"] is True and "DISCLAIMER" or out["disclaimer"]
    assert out["disclaimer"] and "attack" in out["sources"]
    ids = {t["id"] for t in out["tactics"]}
    assert {"TA0001", "TA0002", "TA0040"} <= ids


def test_techniques_filter_by_tactic_and_hide_keywords():
    out = sk.techniques("TA0002")                  # Execution
    assert out["count"] >= 1
    for t in out["techniques"]:
        assert "TA0002" in t["tactics"]
        assert "keywords" not in t                 # internal heuristic field never leaks
    # unfiltered returns everything
    assert sk.techniques()["count"] == len(pack.TECHNIQUES)


def test_technique_detail_enriches_with_countermeasures_and_csf():
    out = sk.technique("t1486")                    # case-insensitive; ransomware
    assert out is not None
    tech = out["technique"]
    assert tech["id"] == "T1486" and tech["name"] == "Data Encrypted for Impact"
    assert any(cm["id"] == "D3-FBA" for cm in tech["countermeasures"])
    assert "RC" in tech["csf_functions"]           # File Backup & Restore → Recover
    assert sk.technique("T9999") is None           # unknown → None (router → 404)


def test_map_behavior_is_an_honest_keyword_heuristic():
    out = sk.map_behavior("attacker used powershell to run a script then exfiltrate data")
    ids = {c["id"] for c in out["candidates"]}
    assert "T1059" in ids                          # Command and Scripting Interpreter
    assert "T1041" in ids                          # Exfiltration Over C2 Channel
    # every candidate carries the matched evidence (transparent, not a black-box classifier)
    assert all(c["evidence"] for c in out["candidates"])
    assert out["heuristic"] == "keyword-match"


def test_map_behavior_empty_returns_no_candidates():
    out = sk.map_behavior("   ")
    assert out["candidates"] == [] and out["count"] == 0


def test_build_playbook_reports_gaps_and_unknowns_honestly():
    out = sk.build_playbook(["T1566", "T1486", "NOPE"])
    assert out["generated"] is False
    assert out["unknown"] == ["NOPE"]              # unknown id surfaced, never silently dropped
    by_id = {p["id"]: p for p in out["playbook"]}
    assert set(by_id) == {"T1566", "T1486"}
    assert by_id["T1486"]["gap"] is False and by_id["T1486"]["countermeasures"]
    # CSF coverage is the union, and gaps are the complement (honest "what we don't cover")
    assert set(out["csf_coverage"]).isdisjoint(out["csf_gaps"])
    assert len(out["csf_coverage"]) + len(out["csf_gaps"]) == 6


def test_frameworks_overview_lists_all_three():
    out = sk.frameworks()
    assert len(out["attack_tactics"]) == 14
    assert len(out["csf_functions"]) == 6          # NIST CSF 2.0
    assert {d["id"] for d in out["d3fend_tactics"]} >= {"D3-HARDEN", "D3-DETECT", "D3-RESTORE"}


def test_no_fabricated_countermeasure_ids_outside_known_tactics():
    # every mapped countermeasure references a real D3FEND tactic bucket
    valid = {d["id"] for d in pack.D3FEND_TACTICS}
    for cms in pack.COUNTERMEASURES.values():
        for cm in cms:
            assert cm["d3fend_tactic"] in valid
