"""Synthetic vault privacy boundary across graph, note, and retrieval routes."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web  # noqa: E402
from agents.core.routers import jarvis_os  # noqa: E402

engine = jarvis_os._engine()


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    (root / "Projects").mkdir(parents=True)
    (root / "Projects" / "Public.md").write_text("# Public\n\namberword public fact", encoding="utf-8")
    (root / "Projects" / "Private.md").write_text(
        '---\nprivacy: "restricted"\ntitle: Hidden\n---\n\namberword private fact', encoding="utf-8")
    (root / "Journal" / "Family").mkdir(parents=True)
    (root / "Journal" / "Family" / "Secret.md").write_text(
        "# Secret\n\namberword excluded fact", encoding="utf-8")
    monkeypatch.setenv(jarvis_os.VAULT_ENV, str(root))
    monkeypatch.setenv("JARVIS_OS_VAULT_EXCLUDE", "Journal/Family")
    engine.invalidate_brain_cache()
    yield root
    engine.invalidate_brain_cache()


def cfg(vault):
    return {"vaultMode": "andrei_os", "vaultPath": str(vault), "nervaPath": str(vault.parent / "absent")}


def test_malformed_saved_scope_never_expands_to_whole_vault(vault, monkeypatch):
    disk = vault.parent / "config.json"
    disk.write_text(json.dumps({**cfg(vault), "vaultInclude": ["Projects"]}), encoding="utf-8")
    monkeypatch.setattr(engine, "CONFIG_PATH", disk)
    assert engine.build_real_brain_graph(engine.load_config())["nodes"] == []


def test_unavailable_scoped_vault_never_switches_to_another_vault(vault, monkeypatch):
    missing = str(vault.parent / "offline")
    disk = vault.parent / "config.json"
    disk.write_text(json.dumps({**cfg(vault), "vaultPath": missing, "vaultInclude": "Projects"}), encoding="utf-8")
    monkeypatch.setattr(engine, "CONFIG_PATH", disk)
    monkeypatch.setattr(engine, "DEFAULT_VAULT_PATH", str(vault))
    assert engine.load_config()["vaultPath"] == missing


def test_private_and_excluded_notes_are_absent_everywhere(vault):
    config = cfg(vault)
    graph = engine.build_real_brain_graph(config)
    text = str(graph)
    assert "Public.md" in text
    assert "Private.md" not in text and "private fact" not in text
    assert "Secret.md" not in text and "excluded fact" not in text
    context, nodes = engine.retrieve_vault_context("amberword", config, top_k=4)
    assert [node["title"] for node in nodes] == ["Public"]
    assert "private fact" not in context and "excluded fact" not in context
    for rel in ("Projects/Private.md", "Journal/Family/Secret.md"):
        with pytest.raises(ValueError):
            engine.read_indexed_note(config, rel)
    client = TestClient(web.app)
    graph_response = client.get("/api/os/brain").json()
    assert "Private.md" not in str(graph_response) and "Secret.md" not in str(graph_response)
    retrieved = client.get("/api/os/brain/retrieve", params={"q": "amberword"}).json()
    assert "private fact" not in str(retrieved) and "excluded fact" not in str(retrieved)
    for rel in ("Projects/Private.md", "Journal/Family/Secret.md"):
        assert client.get("/api/os/brain/note", params={"relPath": rel}).status_code == 404


def test_normalized_vault_path_collision_fails_closed(vault):
    folder = vault / "Projects"
    nfc_name, nfd_name = "Café.md", "Cafe\u0301.md"
    first, second = folder / nfc_name, folder / nfd_name
    first.write_text("# First\n\ncollisionword first body", encoding="utf-8")
    second.write_text("# Second\n\ncollisionword second body", encoding="utf-8")
    if first.samefile(second):
        pytest.skip("filesystem normalizes Unicode filenames")
    config = cfg(vault)
    graph = engine.build_real_brain_graph(config)
    nodes = [node for node in graph["nodes"] if node.get("relPath") == "Projects/Café.md"]
    assert len(nodes) == 2
    assert all("obsidianSource" not in node for node in nodes)
    with pytest.raises(ValueError):
        engine.read_indexed_note(config, "Projects/Café.md")
    context, found = engine.retrieve_vault_context("collisionword", config)
    assert not found and "collisionword" not in context


def test_unique_nfd_vault_note_keeps_exact_native_filename(vault):
    name = "Cafe\u0301.md"
    (vault / "Projects" / name).write_text("# Unique\n\nuniqueword", encoding="utf-8")
    config = cfg(vault)
    graph = engine.build_real_brain_graph(config)
    node = next(node for node in graph["nodes"] if node.get("relPath") == "Projects/Café.md")
    assert node["obsidianSource"] == {
        "vault": vault.name, "file": "Projects/" + name, "readable": True,
    }
    assert "uniqueword" in engine.read_indexed_note(config, "Projects/Café.md")[2]


def test_normalized_directory_collision_fails_closed(vault):
    first = vault / "Projects" / "Café"
    second = vault / "Projects" / "Cafe\u0301"
    first.mkdir()
    second.mkdir(exist_ok=True)
    if first.samefile(second):
        pytest.skip("filesystem normalizes Unicode directory names")
    (first / "Note.md").write_text("# First\n\nsharedword first", encoding="utf-8")
    (second / "Note.md").write_text("# Second\n\nsharedword second", encoding="utf-8")
    config = cfg(vault)
    graph = engine.build_real_brain_graph(config)
    nodes = [node for node in graph["nodes"] if node.get("relPath") == "Projects/Café/Note.md"]
    assert len(nodes) == 2
    assert all("obsidianSource" not in node for node in nodes)
    with pytest.raises(ValueError):
        engine.read_indexed_note(config, "Projects/Café/Note.md")


@pytest.mark.parametrize("frontmatter", [
    "\ufeff---\r\n'privacy': 'personal-private'\r\n---\r\n",
    '---\n{"privacy": "restricted", "title": "Hidden"}\n---\n',
    "---\nprivacy: PRIVaTE\n---\n",
    "---\nprivacy: personal\u2011private\n---\n",
    "---\nprivacy: [restricted]\n---\n",
    "---\nprivacy: [unterminated\n---\n",
    "---\nprivacy: public\nprivacy: restricted\n---\n",
    "---\nprivacy: restricted\n",  # incomplete header
])
def test_conservative_frontmatter_forms_are_hidden(vault, frontmatter):
    target = vault / "Projects" / "Private.md"
    target.write_text(frontmatter + "\namberword private fact", encoding="utf-8")
    config = cfg(vault)
    assert "Private.md" not in str(engine.build_real_brain_graph(config))
    assert "private fact" not in engine.retrieve_vault_context("amberword", config)[0]
    with pytest.raises(ValueError):
        engine.read_indexed_note(config, "Projects/Private.md")


def test_warm_graph_and_direct_note_follow_new_privacy(vault):
    config = cfg(vault)
    target = vault / "Projects" / "Public.md"
    assert "public fact" in engine.read_indexed_note(config, "Projects/Public.md")[2]
    target.write_text("---\nprivacy: restricted\n---\n\namberword now private", encoding="utf-8")
    assert "Public.md" not in str(engine.build_real_brain_graph(config))
    assert "now private" not in engine.retrieve_vault_context("amberword", config)[0]
    with pytest.raises(ValueError):
        engine.read_indexed_note(config, "Projects/Public.md")


def test_exclusion_changes_are_not_reused_from_cache(vault, monkeypatch):
    config = cfg(vault)
    assert "Secret.md" not in str(engine.build_real_brain_graph(config))
    monkeypatch.delenv("JARVIS_OS_VAULT_EXCLUDE")
    assert "Secret.md" in str(engine.build_real_brain_graph(config))
    monkeypatch.setenv("JARVIS_OS_VAULT_EXCLUDE", "Journal/Family")
    assert "Secret.md" not in str(engine.build_real_brain_graph(config))


def test_invalid_exclusion_fails_closed(vault, monkeypatch):
    monkeypatch.setenv("JARVIS_OS_VAULT_EXCLUDE", "../outside")
    graph = engine.build_real_brain_graph(cfg(vault))
    assert not graph.get("nodes")


def test_include_is_casefolded_and_prunes_other_subtrees(vault, monkeypatch):
    monkeypatch.setenv("NERVA_OS_VAULT_INCLUDE", "projects")
    graph = engine.build_real_brain_graph(cfg(vault))
    assert "Public.md" in str(graph)
    assert "Secret.md" not in str(graph)
    monkeypatch.setenv("JARVIS_OS_VAULT_EXCLUDE", "Projects")
    assert "Public.md" not in str(engine.build_real_brain_graph(cfg(vault)))


def test_folder_filter_prevents_descendant_reads(vault):
    includes, excludes = engine._folder_policy()
    read_names = []
    with engine.vault_fs.VaultFs(vault) as files:
        found = list(files.walk(
            cap=lambda name: read_names.append(name) or 4096,
            allow_dir=lambda p: engine._vault_path_allowed(p, includes, excludes, directory=True),
            allow_file=lambda p: engine._vault_path_allowed(p, includes, excludes, directory=False),
        ))
    assert "Secret.md" not in read_names
    assert all(parts[-1] != "Secret.md" for parts, _entry, _data in found)


def test_zero_match_has_no_owner_note_fallback(vault):
    context, nodes = engine.retrieve_vault_context("zzzxqv", cfg(vault), 4)
    assert (context, nodes) == ("", [])
