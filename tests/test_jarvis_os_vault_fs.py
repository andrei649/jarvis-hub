"""Containment of the ANDREI OS vault: nothing is read from, or written to, outside it.

`apps/jarvis-os/vault_fs.py` opens every path component relative to its verified parent's
handle and follows no link. These tests run natively on the platform they execute on
(POSIX `openat` or Windows `NtCreateFile`): symlinks, directory links (a junction on
Windows), hard links, an ancestor swapped under a held handle, and a malicious inbox.
Every secret here is synthetic.
"""
import json
import os
import subprocess
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
vault_fs = engine.vault_fs

SECRET = "SYNTHETIC-SECRET-do-not-leak"


def link_dir(link: Path, target: Path) -> None:
    """A directory link: a symlink on POSIX, a junction on Windows (needs no privilege)."""
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


def link_file(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except OSError as exc:  # Windows without the symlink privilege (CI runners have it)
        pytest.skip(f"cannot create a file symlink here: {exc}")


@pytest.fixture
def tree(tmp_path):
    """A vault, and a folder beside it holding what must never be reached."""
    vault = tmp_path / "Vault"
    (vault / "02 Proiecte").mkdir(parents=True)
    (vault / "02 Proiecte" / "Plan.md").write_text("# Plan\n\nIn the vault.\n", encoding="utf-8")
    (vault / "00 Acasa").mkdir()
    (vault / "00 Acasa" / "Acasa.md").write_text("# Acasa\n", encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text(f"# Secret\n\n{SECRET}\n", encoding="utf-8")
    return vault, outside


def walked(vault, **kwargs):
    with vault_fs.VaultFs(vault, **kwargs) as fs:
        found = {"/".join(parts): data for parts, _entry, data in fs.walk(cap=lambda name: 4096)}
        return found, dict(fs.skipped)


def cfg_for(vault, nerva=None, **extra):
    engine.invalidate_brain_cache()
    return {"vaultMode": "andrei_plus_nerva" if nerva else "andrei_os", "vaultPath": str(vault),
            "nervaPath": str(nerva or vault.parent / "no-repo"), **extra}


def graph_text(cfg) -> str:
    graph = engine.build_real_brain_graph(cfg)
    return "\n".join(f"{n.get('title')}\n{n.get('relPath')}\n{n.get('body')}" for n in graph["nodes"])


# ── the filesystem layer ─────────────────────────────────────────

def test_walk_yields_plain_files_and_skips_dot_folders(tree):
    vault, _outside = tree
    found, skipped = walked(vault)
    assert sorted(found) == ["00 Acasa/Acasa.md", "02 Proiecte/Plan.md"]
    assert b"In the vault." in found["02 Proiecte/Plan.md"] and skipped == {}


def test_a_file_symlink_is_never_followed(tree):
    vault, outside = tree
    link_file(vault / "02 Proiecte" / "Leak.md", outside / "secret.md")
    found, skipped = walked(vault)
    assert "02 Proiecte/Leak.md" not in found and "02 Proiecte/Leak.md" in skipped
    assert SECRET.encode() not in b"".join(found.values())
    with vault_fs.VaultFs(vault) as fs, pytest.raises(vault_fs.UnsafePath):
        fs.read_file(("02 Proiecte", "Leak.md"), 4096)


def test_a_directory_link_is_never_followed(tree):
    vault, outside = tree
    link_dir(vault / "Linked", outside)
    found, skipped = walked(vault)
    assert not [name for name in found if name.startswith("Linked")] and "Linked" in skipped
    assert SECRET.encode() not in b"".join(found.values())
    with vault_fs.VaultFs(vault) as fs:
        with pytest.raises(vault_fs.UnsafePath):
            fs.read_file(("Linked", "secret.md"), 4096)
        with pytest.raises(vault_fs.UnsafePath):
            fs.list_names(("Linked",))


def test_a_hard_link_is_refused_unless_the_caller_allows_it(tree):
    vault, outside = tree
    os.link(outside / "secret.md", vault / "02 Proiecte" / "Hard.md")
    found, skipped = walked(vault)
    assert "02 Proiecte/Hard.md" not in found and skipped == {"02 Proiecte/Hard.md": "hard link"}
    with vault_fs.VaultFs(vault) as fs, pytest.raises(vault_fs.UnsafePath):
        fs.read_file(("02 Proiecte", "Hard.md"), 4096)
    allowed, skipped = walked(vault, allow_hardlinks=True)
    assert SECRET.encode() in allowed["02 Proiecte/Hard.md"] and skipped == {}


@pytest.mark.parametrize("parts", [
    ("..", "outside", "secret.md"), ("02 Proiecte", "..", "..", "outside", "secret.md"),
    ("02 Proiecte/Plan.md",), ("02 Proiecte\\Plan.md",), ("",), (".",), (), ("a\x00b",),
])
def test_only_single_path_components_are_accepted(tree, parts):
    vault, _outside = tree
    with vault_fs.VaultFs(vault) as fs, pytest.raises(vault_fs.UnsafePath):
        fs.read_file(parts, 4096)


def test_a_swapped_ancestor_cannot_redirect_a_read(tree):
    """The walk holds the folder's handle; replacing the folder's name changes nothing."""
    vault, outside = tree
    (outside / "Plan.md").write_text(SECRET, encoding="utf-8")
    with vault_fs.VaultFs(vault) as fs:
        held = fs.open_dir(("02 Proiecte",))
        try:
            os.rename(vault / "02 Proiecte", vault / "moved")
            link_dir(vault / "02 Proiecte", outside)
            _entry, data = fs.read_in(held, "Plan.md", 4096)
            assert b"In the vault." in data and SECRET.encode() not in data
        finally:
            fs.close_dir(held)
        # A fresh walk from the root meets the link and refuses it.
        with pytest.raises(vault_fs.UnsafePath):
            fs.read_file(("02 Proiecte", "Plan.md"), 4096)


def test_create_is_exclusive_and_makes_the_folder_inside_the_vault(tree):
    vault, outside = tree
    with vault_fs.VaultFs(vault) as fs:
        fs.create_exclusive(("08 Inbox",), "Idee.md", b"prima")
        with pytest.raises(FileExistsError):
            fs.create_exclusive(("08 Inbox",), "Idee.md", b"a doua")
    assert (vault / "08 Inbox" / "Idee.md").read_bytes() == b"prima"
    assert sorted(p.name for p in outside.iterdir()) == ["secret.md"]


def test_create_refuses_an_inbox_that_links_out_of_the_vault(tree):
    vault, outside = tree
    link_dir(vault / "08 Inbox", outside)
    with vault_fs.VaultFs(vault) as fs, pytest.raises(vault_fs.UnsafePath):
        fs.create_exclusive(("08 Inbox",), "Escaped.md", b"x")
    assert sorted(p.name for p in outside.iterdir()) == ["secret.md"]


def test_create_cannot_be_redirected_by_swapping_the_inbox(tree):
    """The file is created relative to the verified inbox handle, not its name."""
    vault, outside = tree
    with vault_fs.VaultFs(vault) as fs:
        inbox = fs.open_dir(("08 Inbox",), create=True)
        try:
            os.rename(vault / "08 Inbox", vault / "inbox-moved")
            link_dir(vault / "08 Inbox", outside)
            handle = fs._api.create_file(inbox, "Nota.md")
            fs._api.write(handle, b"stays inside")
            fs._api.close(handle)
        finally:
            fs.close_dir(inbox)
    assert (vault / "inbox-moved" / "Nota.md").read_bytes() == b"stays inside"
    assert sorted(p.name for p in outside.iterdir()) == ["secret.md"]


def test_a_missing_vault_is_an_error_not_a_fallback(tmp_path):
    with pytest.raises(FileNotFoundError):
        vault_fs.VaultFs(tmp_path / "nope")


# ── the graph (and so the model's grounding) ─────────────────────

def test_graph_never_contains_content_reached_through_a_link(tree):
    vault, outside = tree
    link_dir(vault / "Linked", outside)
    os.link(outside / "secret.md", vault / "02 Proiecte" / "Hard.md")
    cfg = cfg_for(vault)
    graph = engine.build_real_brain_graph(cfg)
    text = graph_text(cfg)
    assert SECRET not in text and "Linked" not in text and "Hard" not in text
    assert "In the vault." in text
    assert graph["skipped"] == {"count": 2, "reasons": {"hard link": 1, "reparse point" if sys.platform == "win32" else "symlink": 1}}
    _context, nodes = engine.retrieve_vault_context("secret synthetic", cfg, 6)
    assert SECRET not in "\n".join(str(n.get("body")) for n in nodes)


def test_graph_file_symlink_is_left_out(tree):
    vault, outside = tree
    link_file(vault / "02 Proiecte" / "Leak.md", outside / "secret.md")
    cfg = cfg_for(vault)
    assert SECRET not in graph_text(cfg)
    assert engine.build_real_brain_graph(cfg)["skipped"]["count"] == 1


def test_hard_linked_notes_are_indexed_only_when_switched_on(tree, monkeypatch):
    vault, outside = tree
    os.link(outside / "secret.md", vault / "02 Proiecte" / "Hard.md")
    assert SECRET not in graph_text(cfg_for(vault))
    assert SECRET in graph_text(cfg_for(vault, allowHardLinks=True))
    monkeypatch.setenv("JARVIS_OS_ALLOW_HARDLINKS", "1")
    assert SECRET in graph_text(cfg_for(vault))


# ── the note route: an allowlist of indexed Markdown ─────────────

@pytest.fixture
def repo_like(tmp_path):
    """A synthetic checkout with the files a path check would have served."""
    repo = tmp_path / "repo"
    (repo / "apps" / "jarvis-os").mkdir(parents=True)
    (repo / "agents" / "jarvis").mkdir(parents=True)
    (repo / "README.md").write_text("# Readme\n\nPublic doc.\n", encoding="utf-8")
    (repo / "apps" / "jarvis-os" / "config.json").write_text(json.dumps({"anthropicKey": SECRET}), encoding="utf-8")
    (repo / ".env").write_text(f"API_KEY={SECRET}\n", encoding="utf-8")
    (repo / "notes.txt").write_text(SECRET, encoding="utf-8")
    (repo / "agents" / "jarvis" / "SOUL.md").write_text("# Soul\n\nTemplate.\n", encoding="utf-8")
    (repo / "agents" / "jarvis" / "SOUL.local.md").write_text(f"# Mine\n\n{SECRET}\n", encoding="utf-8")
    return repo


def test_note_serves_indexed_markdown(tree, repo_like):
    vault, _outside = tree
    cfg = cfg_for(vault, repo_like)
    assert "In the vault." in engine.read_indexed_note(cfg, "02 Proiecte/Plan.md")[2]
    assert "Public doc." in engine.read_indexed_note(cfg, "Nerva/jarvis-hub/README.md")[2]
    assert "Template." in engine.read_indexed_note(cfg, "Nerva/jarvis-hub/agents/jarvis/SOUL.md")[2]


@pytest.mark.parametrize("rel", [
    "Nerva/jarvis-hub/apps/jarvis-os/config.json", "Nerva/jarvis-hub/.env", "Nerva/jarvis-hub/notes.txt",
    "Nerva/jarvis-hub/agents/jarvis/SOUL.local.md", "Nerva/jarvis-hub/../outside/secret.md",
    "../outside/secret.md", "02 Proiecte/../../outside/secret.md", "data.json", "02 Proiecte", "",
])
def test_note_refuses_everything_the_graph_did_not_index(tree, repo_like, rel):
    vault, _outside = tree
    (vault / "data.json").write_text(json.dumps({"token": SECRET}), encoding="utf-8")
    cfg = cfg_for(vault, repo_like)
    assert SECRET not in graph_text(cfg)            # *.local.md, config, .env never indexed
    with pytest.raises(ValueError):
        engine.read_indexed_note(cfg, rel)


def test_note_rereads_through_the_safe_layer(tree, repo_like):
    """Indexed first, replaced by a link afterwards: the read still does not follow it."""
    vault, outside = tree
    cfg = cfg_for(vault, repo_like)
    engine.build_real_brain_graph(cfg)
    (vault / "02 Proiecte" / "Plan.md").unlink()
    os.link(outside / "secret.md", vault / "02 Proiecte" / "Plan.md")
    with pytest.raises(OSError):
        engine.read_indexed_note(cfg, "02 Proiecte/Plan.md")


# ── capture ──────────────────────────────────────────────────────

def test_capture_refuses_a_linked_inbox_and_writes_nothing_outside(tree):
    vault, outside = tree
    link_dir(vault / "08 Inbox", outside)
    with pytest.raises(vault_fs.UnsafePath):
        engine.capture_inbox_note(cfg_for(vault), "Escaped", "content")
    assert sorted(p.name for p in outside.iterdir()) == ["secret.md"]


def test_hub_capture_route_reports_the_refusal(tree, monkeypatch):
    vault, outside = tree
    link_dir(vault / "08 Inbox", outside)
    monkeypatch.setenv(jarvis_os.VAULT_ENV, str(vault))
    engine.invalidate_brain_cache()
    response = TestClient(web.app).post("/api/os/brain/capture", json={"title": "Escaped", "content": "x"})
    assert response.status_code == 409 and response.json()["ok"] is False
    assert sorted(p.name for p in outside.iterdir()) == ["secret.md"]


def test_hub_note_route_refuses_repo_configuration(tree, monkeypatch):
    vault, _outside = tree
    monkeypatch.setenv(jarvis_os.VAULT_ENV, str(vault))
    engine.invalidate_brain_cache()
    client = TestClient(web.app)
    for rel in ("Nerva/jarvis-hub/apps/jarvis-os/config.example.json", "Nerva/jarvis-hub/.env.example",
                "Nerva/jarvis-hub/apps/jarvis-os/config.json", "Nerva/jarvis-hub/pyproject.toml"):
        response = client.get("/api/os/brain/note", params={"relPath": rel})
        assert response.status_code == 404 and response.json() == {"ok": False, "error": "note not found"}, rel
    assert client.get("/api/os/brain/note", params={"relPath": "Nerva/jarvis-hub/NERVA.md"}).status_code == 200


def test_capture_title_cannot_name_a_path(tree):
    vault, outside = tree
    result = engine.capture_inbox_note(cfg_for(vault), "..\\..\\outside\\x", "content")
    written = Path(result["path"])
    assert written.parent == vault / "08 Inbox" and written.is_file()
    assert sorted(p.name for p in outside.iterdir()) == ["secret.md"]
