"""Relevance for notes that may become model attachments."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def rank():
    path = Path(__file__).resolve().parents[1] / "apps/jarvis-os/vault_search.py"
    spec = importlib.util.spec_from_file_location("vault_search", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rank


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
