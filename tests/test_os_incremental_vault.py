"""Synthetic persistent index and structured vault privacy checks."""

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    source = Path(__file__).resolve().parents[1] / "apps/jarvis-os/server.py"
    spec = importlib.util.spec_from_file_location("incremental_vault_engine", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fixture_vault(tmp_path):
    root = tmp_path / "Vault"
    (root / "Home").mkdir(parents=True)
    (root / "Projects").mkdir()
    (root / "Home" / "map.json").write_text(json.dumps({
        "schema": "test-map/v1", "zone": [{"dir": "Projects", "hub": None}],
        "intrari": [{"p": "Home/Today.md", "rol": "Azi"},
                   {"p": "Home/Decisions.md", "rol": "Decizii"}]}), encoding="utf-8")
    (root / "Home" / "Today.md").write_text("# Today\n\npublic today", encoding="utf-8")
    (root / "Home" / "Decisions.md").write_text("# Decisions\n\npublic decision", encoding="utf-8")
    (root / "Projects" / "Alpha.md").write_text("# Alpha\n\ncurrentword", encoding="utf-8")
    (root / "Projects" / "Private.md").write_text(
        "---\nprivacy: restricted\n---\n\nsecretword", encoding="utf-8")
    (root / "Projects" / "Excluded.md").write_text("# Excluded\n\nexcludedword", encoding="utf-8")
    (root / "Projects" / "summary.json").write_text(json.dumps({
        "schema": "test-index-scurt/v1", "items": [
            {"id": "PRJ-001", "n": "Alpha.md", "st": 3, "pas": "Finish report", "bl": "public extra"},
            {"id": "PRJ-002", "n": "Private.md", "st": 4, "pas": "Private step", "bl": "hidden extra"}],
        "cozi": {"termina_acum": ["PRJ-001", "PRJ-002"]},
        "termene_14_zile": [{"id": "PRJ-001", "data": "2026-12-01", "text": "Review report"},
                             {"id": "PRJ-002", "data": "2026-12-02", "text": "Private deadline"}]}),
        encoding="utf-8")
    cfg = {"vaultMode": "andrei_os", "vaultPath": str(root), "nervaPath": str(tmp_path / "absent"),
           "vaultInclude": "Home;Projects", "vaultExclude": "Projects/Excluded.md",
           "vaultMapPath": "Home/map.json", "vaultMapSchema": "test-map/v1",
           "projectIndex": True, "projectIndexPath": "Projects/summary.json",
           "projectRegisterDir": "Projects", "projectIndexSchema": "test-index-scurt/v1",
           "indexDb": str(tmp_path / "private" / "index.sqlite"), "buildSourceDirs": ("Projects",)}
    return root, cfg


def test_incremental_update_delete_rename_and_policy_purge(engine, fixture_vault):
    root, cfg = fixture_vault
    first = engine.sync_vault_index(cfg)
    assert first["ok"] and first["indexedNotes"] == 3 and first["excludedZones"] == 1
    assert first["sourceMtimeNs"] > 0
    assert engine.sync_vault_index(cfg)["lastIndexedAt"] == first["lastIndexedAt"]
    assert engine.sync_vault_index(cfg)["sourceSignature"] == first["sourceSignature"]
    with sqlite3.connect(cfg["indexDb"]) as db:
        assert db.execute("SELECT COUNT(*) FROM hidden").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 3
    note = root / "Projects" / "Alpha.md"
    note.write_text("# Alpha\n\nchangedword", encoding="utf-8")
    os.utime(note, None)
    assert engine.sync_vault_index(cfg)["lastIndexedAt"] != first["lastIndexedAt"]
    context, _ = engine.retrieve_vault_context("changedword", cfg)
    assert "changedword" in context
    note.rename(root / "Projects" / "Renamed.md")
    renamed = engine.sync_vault_index(cfg)
    assert renamed["sourceSignature"] != first["sourceSignature"]
    with sqlite3.connect(cfg["indexDb"]) as db:
        assert db.execute("SELECT path FROM notes ORDER BY path").fetchall() == [
            ("Home/Decisions.md",), ("Home/Today.md",), ("Projects/Renamed.md",)]
    (root / "Projects" / "Renamed.md").unlink()
    assert engine.sync_vault_index(cfg)["indexedNotes"] == 2
    assert not engine.retrieve_vault_context("changedword", cfg)[1]
    cfg["vaultExclude"] = "Projects"
    assert engine.sync_vault_index(cfg)["indexedNotes"] == 2
    with sqlite3.connect(cfg["indexDb"]) as db:
        assert db.execute("SELECT COUNT(*) FROM hidden").fetchone()[0] == 0


def test_structured_graph_local_reader_and_excluded_open_gate(engine, fixture_vault, monkeypatch):
    _root, cfg = fixture_vault
    original = engine.vault_fs.VaultFs.read_file

    def guard(files, parts, cap):
        assert "Excluded.md" not in parts
        return original(files, parts, cap)

    monkeypatch.setattr(engine.vault_fs.VaultFs, "read_file", guard)
    graph = engine.build_real_brain_graph({**cfg, "localProjectMetadata": True, "maskVaultPath": True})
    assert graph["ok"] and "Excluded.md" not in str(graph)
    assert graph["vaultPath"] == "" and graph["discoveredSources"][0]["path"] == ""
    assert any(node.get("isHub") and node.get("title") == "Projects" for node in graph["nodes"])
    projects = [node for node in graph["nodes"] if node.get("projectId")]
    assert len(projects) == 2
    restricted = next(node for node in projects if node["projectId"] == "PRJ-002")
    assert restricted["localOnly"] and "hidden extra" not in str(restricted)
    assert [row["id"] for row in engine.project_priorities(cfg, "finish projects", 4)] == ["PRJ-001"]
    owner_rows = engine.project_priorities({**cfg, "localProjectMetadata": True}, "finish projects", 4)
    assert [row["id"] for row in owner_rows] == ["PRJ-001", "PRJ-002"]
    assert all(set(row) == {"id", "title", "stage", "nextStep"} for row in owner_rows)
    assert [row["id"] for row in engine.structured_brief(cfg, "deadlines")] == ["PRJ-001"]
    owner_deadlines = engine.structured_brief({**cfg, "localProjectMetadata": True}, "deadlines")
    assert [row["id"] for row in owner_deadlines] == ["PRJ-001", "PRJ-002"]
    assert set(owner_deadlines[1]) == {"id", "title", "stage", "nextStep"}
    assert engine.structured_brief(cfg, "azi")[0]["title"] == "Today"
    assert engine.structured_brief(cfg, "decisions")[0]["title"] == "Decisions"
    assert "secretword" not in engine.retrieve_vault_context("secretword", cfg)[0]
    with pytest.raises(ValueError):
        engine.read_indexed_note(cfg, "Projects/Private.md")
    assert "secretword" in engine.read_indexed_note(cfg, "Projects/Private.md", local_only=True)[2]
    with pytest.raises(ValueError):
        engine.read_indexed_note(cfg, "Projects/Excluded.md", local_only=True)


def test_structured_vault_without_scope_fails_closed(engine, fixture_vault):
    _root, cfg = fixture_vault
    cfg.pop("vaultInclude")
    assert not engine.sync_vault_index(cfg)["ok"]
    assert engine.build_real_brain_graph(cfg)["nodes"] == []


@pytest.mark.parametrize("exclude", ("", "Private/Unrelated.md", "00 Acasa", "00 Acasa/index-vault.json"))
def test_detected_structured_vault_needs_scope_even_without_map_config(engine, tmp_path, monkeypatch, exclude):
    root = tmp_path / "Vault"
    (root / "00 Acasa").mkdir(parents=True)
    (root / "00 Acasa" / "index-vault.json").write_text("{}", encoding="utf-8")
    (root / "Private").mkdir()
    (root / "Private" / "Secret.md").write_text("secretword", encoding="utf-8")
    cfg = {"vaultMode": "andrei_os", "vaultPath": str(root), "indexDb": str(tmp_path / "index.sqlite"),
           "vaultExclude": exclude}
    original_open = engine.vault_fs.VaultFs.open_dir
    original_read = engine.vault_fs.VaultFs.read_file

    def checked_open(files, parts, *args, **kwargs):
        if exclude == "00 Acasa":
            assert tuple(parts) != ("00 Acasa",)
        return original_open(files, parts, *args, **kwargs)

    def checked_read(files, parts, cap):
        assert tuple(parts) != ("00 Acasa", "index-vault.json")
        assert tuple(parts) != ("Private", "Secret.md")
        return original_read(files, parts, cap)

    monkeypatch.setattr(engine.vault_fs.VaultFs, "open_dir", checked_open)
    monkeypatch.setattr(engine.vault_fs.VaultFs, "read_file", checked_read)
    assert not engine.sync_vault_index(cfg)["ok"]
    assert engine.build_real_brain_graph(cfg)["nodes"] == []
    assert engine.retrieve_vault_context("secretword", cfg) == ("", [])
    with pytest.raises(ValueError):
        engine.read_indexed_note(cfg, "Private/Secret.md", local_only=True)


def test_warm_note_cache_does_not_bypass_new_structured_marker(engine, tmp_path):
    root = tmp_path / "Vault"
    root.mkdir()
    (root / "Public.md").write_text("# Public\n\nmarkerword", encoding="utf-8")
    cfg = {"vaultMode": "andrei_os", "vaultPath": str(root),
           "vaultExclude": "Unrelated.md", "indexDb": str(tmp_path / "index.sqlite")}
    assert engine.build_real_brain_graph(cfg)["ok"]
    assert "markerword" in engine.read_indexed_note(cfg, "Public.md")[2]
    (root / "00 Acasa").mkdir()
    (root / "00 Acasa" / "index-vault.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        engine.read_indexed_note(cfg, "Public.md")
    assert engine.retrieve_vault_context("markerword", cfg) == ("", [])


def test_block_tags_are_visible_and_native_queue_updates_stamp(engine, fixture_vault):
    root, cfg = fixture_vault
    tagged = root / "Projects" / "Tagged.md"
    tagged.write_text("---\ntags:\n  - action\n  - review\n---\n\n# Tagged\n\npathword", encoding="utf-8")
    first = engine.sync_vault_index(cfg)
    graph = engine.build_real_brain_graph(cfg)
    node = next(node for node in graph["nodes"] if node.get("relPath") == "Projects/Tagged.md")
    assert node["tags"] == ["action", "review"]
    summary = root / "Projects" / "summary.json"
    index = json.loads(summary.read_text(encoding="utf-8"))
    index["cozi"]["termina_acum"] = []
    summary.write_text(json.dumps(index), encoding="utf-8")
    assert engine.sync_vault_index(cfg)["lastIndexedAt"] != first["lastIndexedAt"]
    assert engine.project_priorities(cfg, "finish projects") == []


def test_warm_index_from_another_process(engine, tmp_path):
    vault = tmp_path / "Vault"
    vault.mkdir()
    for index in range(120):
        (vault / f"note-{index:03}.md").write_text(f"# Note {index}\n\nunique{index}", encoding="utf-8")
    cfg = {"vaultMode": "andrei_os", "vaultPath": str(vault), "allowHardLinks": True,
           "indexDb": str(tmp_path / "index.sqlite")}
    assert engine.sync_vault_index(cfg)["indexedNotes"] == 120
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    source = Path(engine.__file__).resolve()
    script = (
        "import importlib.util,json,sys,time;"
        "from pathlib import Path;"
        "s=importlib.util.spec_from_file_location('warm',sys.argv[1]);"
        "e=importlib.util.module_from_spec(s);s.loader.exec_module(e);"
        "c=json.loads(Path(sys.argv[2]).read_text());"
        "t=time.perf_counter();x=e.sync_vault_index(c);"
        "assert x['ok'] and x['indexedNotes']==120;"
        "print((time.perf_counter()-t)*1000)"
    )
    result = subprocess.run([sys.executable, "-c", script, str(source), str(config_path)],
                            check=True, capture_output=True, text=True)
    assert float(result.stdout.strip()) < 200


def test_all_restricted_registry_local_projection_and_configured_inbox(engine, fixture_vault):
    root, cfg = fixture_vault
    (root / "Projects" / "Alpha.md").write_text(
        "---\nprivacy: restricted\n---\n\nprivate alpha body", encoding="utf-8")
    assert engine.project_priorities(cfg, "finish projects") == []
    owner = engine.project_priorities({**cfg, "localProjectMetadata": True}, "finish projects")
    assert [row["id"] for row in owner] == ["PRJ-001", "PRJ-002"]
    assert all(set(row) == {"id", "title", "stage", "nextStep"} for row in owner)
    assert "private alpha body" not in str(owner)
    capture_cfg = {**cfg, "vaultInclude": "Home;Projects;08 Inbox",
                   "vaultInbox": "08 Inbox", "vaultInboxConfigured": True}
    with pytest.raises(engine.vault_fs.UnsafePath):
        engine.capture_inbox_note(capture_cfg, "New", "content", reindex=False)
    assert not (root / "08 Inbox").exists()
