"""0.41 World Signal Packs — per-domain signal routing (pure, offline).

Deterministic keyword classification into domains, per-agent routing, unclassifiable signals
surfaced as unrouted (never guessed), severity-ranked per-domain briefs.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core import signal_routing as sr  # noqa: E402


def _signals():
    return [
        {"title": "Ransomware breach at utility", "summary": "grid operator hit", "severity": 3},
        {"title": "Missile strike near border", "severity": 5},
        {"title": "Central bank hikes rates", "summary": "inflation pressure", "severity": 2},
        {"title": "Quiet day in the garden"},                       # unclassifiable
    ]


def test_classification_reports_matched_terms():
    c = sr.classify_signal({"title": "Ransomware breach", "summary": "grid down"})
    assert "cyber" in c["domains"] and "energy" in c["domains"]     # grid → energy
    assert "ransomware" in c["matched"]["cyber"]


def test_route_surfaces_unrouted_never_guesses():
    routed = sr.route_signals(_signals())
    assert routed["counts"] == {"signals": 4, "routed": 3, "unrouted": 1}
    assert routed["unrouted"] == [3]                                # the garden signal
    assert routed["classifications"][3]["domains"] == []            # honest: no forced label


def test_agents_get_exactly_their_domains():
    routed = sr.route_signals(_signals())
    # ultron (cyber only) gets the ransomware signal, not the missile one
    assert routed["by_agent"]["ultron"] == [0]
    # gecko (economy+energy): ransomware hit a grid (energy) + rates (economy)
    assert routed["by_agent"]["gecko"] == [0, 2]
    # argus subscribes to everything routed
    assert routed["by_agent"]["argus"] == [0, 1, 2]


def test_domain_brief_ranks_by_severity_and_is_bounded():
    sigs = [{"title": f"missile strike {i}", "severity": i} for i in range(6)]
    brief = sr.build_domain_brief(sigs, "conflict", top=3)
    assert brief["count"] == 6 and len(brief["top"]) == 3
    assert [s["severity"] for s in brief["top"]] == [5, 4, 3]       # highest first


def test_unknown_domain_is_honest():
    brief = sr.build_domain_brief(_signals(), "astrology")
    assert brief["known_domain"] is False and brief["headline"] == "unknown domain"
    assert brief["top"] == []


def test_bounded_and_deterministic():
    many = [{"title": "cyber breach"}] * (sr._MAX_SIGNALS + 50)
    routed = sr.route_signals(many)
    assert routed["counts"]["signals"] == sr._MAX_SIGNALS
    assert sr.route_signals(_signals()) == sr.route_signals(_signals())
