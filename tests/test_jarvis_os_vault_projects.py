"""Synthetic project index fixtures; a personal vault is never read here."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def projects():
    path = Path(__file__).resolve().parents[1] / "apps/jarvis-os/vault_projects.py"
    spec = importlib.util.spec_from_file_location("vault_projects", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def index(items, **extra):
    return json.dumps({"schema": "project-index/v1", "items": items, **extra},
                      ensure_ascii=False).encode("utf-8")


def test_searchable_metadata_without_following_paths(projects):
    rows = projects.project_records(index([{
        "id": "PRJ-123", "n": "Garden Plan.md", "st": 2, "pas": "Check seedlings",
        "bl": None, "sc": 84, "privateLink": "https://invalid.example/private",
    }], extraNotes="ignored root prose"))
    assert rows == [{
        "projectId": "PRJ-123", "title": "Garden Plan",
        "noteFile": "Garden Plan.md",
        "relPath": "Projects/index.json#PRJ-123",
        "body": ("Garden Plan · PRJ-123\nStadiu (0–5): 2\n"
                 "Scor de finalizare (0–100): 84\nPas următor: Check seedlings"),
        "tags": ["proiect", "PRJ-123"],
    }]
    assert "private" not in rows[0]["body"]


def test_optional_fields_can_be_missing_or_null(projects):
    rows = projects.project_records(index([{"id": "PRJ-001", "n": "Simple Plan.md"},
                                          {"id": "WS-workshop-demo", "n": "Another Plan.md", "st": None}]))
    assert len(rows) == 2
    assert "Stadiu" not in rows[0]["body"] + rows[1]["body"]


@pytest.mark.parametrize("items", [
    [{"id": "PRJ-001", "n": "One.md"}, {"id": "PRJ-001", "n": "Two.md"}],
    [{"id": "prj-001", "n": "One.md"}],
    [{"id": "PRJ-001", "n": "../One.md"}],
    [{"id": "PRJ-001", "n": "One\\Two.md"}],
    [{"id": "PRJ-001", "n": "CON.md"}],
    [{"id": "PRJ-001", "n": "One.txt"}],
    [{"id": "PRJ-001", "n": "One.md", "st": True}],
    [{"id": "PRJ-001", "n": "One.md", "st": 6}],
    [{"id": "PRJ-001", "n": "One.md", "sc": -1}],
    [{"id": "PRJ-001", "n": "One.md", "pas": 4}],
    ["not a row"],
])
def test_rejects_malformed_rows(projects, items):
    with pytest.raises(ValueError):
        projects.project_records(index(items))


def test_rejects_ambiguous_json_and_bounds(projects):
    for data in (b'{"schema":"project-index/v1","items":[],"items":[]}',
                 b'{"schema":"other","items":[]}', index([{"id": "PRJ-001", "n": "One.md"}] * 1001),
                 b" " * (projects.MAX_BYTES + 1)):
        with pytest.raises(ValueError):
            projects.project_records(data)


@pytest.mark.parametrize("path", ["../index.json", "/index.json", "C:/index.json",
                                         "Projects//index.json", "Projects/.hidden.json", "Projects/CON.json"])
def test_rejects_unsafe_private_index_path(projects, path):
    with pytest.raises(ValueError):
        projects.settings({"projectIndexPath": path})


def test_private_settings_keep_existing_layout_compatible(projects):
    path, register, schema = projects.settings({
        "projectIndexPath": "Archive/summary.json",
        "projectRegisterDir": "Archive/Notes",
        "projectIndexSchema": "custom-projects/v1",
    })
    data = json.dumps({"schema": schema, "items": [{"id": "PRJ-123", "n": "Garden.md"}]}).encode()
    assert register == "Archive/Notes"
    assert projects.project_records(data, index_path=path, schema=schema)[0]["relPath"] == "Archive/summary.json#PRJ-123"
