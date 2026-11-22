"""Relevance for notes that may become model attachments."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def search():
    path = Path(__file__).resolve().parents[1] / "apps/jarvis-os/vault_search.py"
    spec = importlib.util.spec_from_file_location("vault_search", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rank(search):
    return search.rank


def note(title, body="", category="Unfiled"):
    return {"title": title, "body": body, "category": category, "relPath": f"Inbox/{title}.md"}


def test_no_unsolicited_profile_or_partial_word_matches(rank):
    notes = [note("Acasa"), note("Facebook briefing"), note("Gaming hardware")]
    for query in ("ce poate face", "ing", "upcoming", "si pe la noi"):
        assert rank(query, notes, {"pc": ["hardware"]}) == []


def test_literal_and_diacritic_matches_beat_synonyms(rank):
    direct, related = note("PC"), note("Stație", "Bonobo hardware")
    assert rank("PC", [related, direct], {"pc": ["hardware", "bonobo"]}) == [direct, related]
    assert rank("statie", [related], {}) == [related]


def test_phrase_expansion_only_at_word_boundaries(rank):
    item = note("Stație")
    assert rank("what about me?", [item], {"about me": ["stație"]}) == [item]
    assert rank("about memory", [item], {"about me": ["stație"]}) == []


def test_stable_ties_and_no_placeholder_results(rank):
    a, b = note("Assembly A"), note("Assembly B")
    synthetic = [dict(a, isHub=True), dict(a, cloudEvicted=True), dict(a, relPath="a.csv")]
    assert rank("assembly", [b, *synthetic, a], {}) == [a, b]


def test_project_identifiers_match_as_a_unit_in_register_and_notes(rank):
    project = {"projectId": "PRJ-123", "title": "Workshop", "relPath": "index.json#PRJ-123"}
    related = note("Daily", "Follow PRJ-123 and WS-workshop-tools")
    other = note("Tomorrow", "Follow PRJ-124 and WS-workshop-delivery")
    items = [other, related, project]
    assert rank("prj-123", items, {}) == [project, related]
    assert rank("status for WS-workshop-tools", items, {}) == [related]
    assert rank("PRJ-999", items, {}) == []


def test_score_matches_rank_and_accepts_fresh_body(search):
    terms, related = search.query_terms("PC", {"pc": ["hardware"]})
    node = note("Daily", "old text")
    assert search.score(node, terms, related) == (0, 0)
    assert search.score(node, terms, related, body="PC hardware") == (1, 1)
    assert search.score(dict(node, isHub=True), terms, related, body="PC") == (0, 0)
    assert search.score(node, set(), set(), body="PC") == (0, 0)


def test_passage_favors_richer_late_answer_over_title_and_private_neighbor(search):
    body = "# PC\n\n" + "General introduction. " * 90 + "\n\n## Private\nSecret unrelated notes.\n\n## Hardware\nPC has 5090 and Bonobo details.\n\n## Other private\nUnrelated account details."
    for limit in (700, 1500):
        result = search.passage(body, "PC 5090 Bonobo", {}, limit)
        assert result in body and len(result) <= limit
        assert "PC has 5090 and Bonobo details." in result
        assert "Secret unrelated" not in result
        assert "Unrelated account" not in result


def test_passage_keeps_short_note_and_falls_back_without_body_match(search):
    body = "# Relevant title\r\n\r\nA short note with no matching body words."
    assert search.passage(body, "relevant", {}, 1500) == body
    assert search.passage(body * 50, "unfindable", {}, 700) == (body * 50)[:700]


def test_passage_uses_whole_identifier_diacritic_and_synonym_matches(search):
    body = "# Intro\r\n\r\n" + "Filler. " * 110 + "\r\n\r\n## Răspuns\r\nPRJ-123 este pe stație și pe Bonobo.\r\n\r\n## Private\r\nDo not reveal this."
    result = search.passage(body, "PRJ-123 statie PC", {"pc": ["bonobo"]}, 700)
    assert "PRJ-123 este pe stație și pe Bonobo." in result
    assert "Do not reveal" not in result
    assert result in body
    assert "PRJ-123" not in search.passage(body.replace("PRJ-123", "PRJ-1234"), "PRJ-123", {}, 700)


def test_passage_finds_late_match_in_single_long_paragraph(search):
    body = "Unrelated sentence. " * 120 + "The 5090 PC answer is here. " + "Unrelated tail. " * 80
    for limit in (700, 1500):
        result = search.passage(body, "5090 PC", {}, limit)
        assert "The 5090 PC answer is here." in result
        assert result in body and len(result) <= limit


def test_passage_prefers_real_answer_over_equal_bare_heading(search):
    body = "# Spectroscope calibration\n\n" + "General introduction. " * 90 + "\n\nFor spectroscope calibration, align the reference lamp first."
    result = search.passage(body, "spectroscope calibration", {}, 700)
    assert result.startswith("For spectroscope calibration, align")


def test_multiword_expansion_does_not_match_across_paragraphs(search):
    body = "# Intro\n\n" + "Filler. " * 200 + "\n\nMac\n\nMini is an unrelated private heading.\n\nThe actual answer is here."
    result = search.passage(body, "server", {"server": ["mac mini"]}, 700)
    assert result == body[:700]
    matching = body + "\n\nThe Mac mini hosts the vault."
    assert search.passage(matching, "server", {"server": ["mac mini"]}, 700) == "The Mac mini hosts the vault."


def test_heading_boundary_and_unicode_long_paragraph(search):
    body = ("# Intro\n" + "Filler. " * 200 + "\n## Private\nSecret notes.\n"
            + "## Răspuns\n" + "Alt text. " * 100 + "Stația PRJ-123 răspunde aici. " + "Tail. " * 100)
    result = search.passage(body, "statie PRJ-123", {}, 700)
    assert "Stația PRJ-123 răspunde aici." in result
    assert "Secret notes" not in result
    assert result in body and len(result) <= 700
