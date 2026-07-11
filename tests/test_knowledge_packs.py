"""0.21 Offline Knowledge Packs — manifest / verify / install-plan over local_docs.

A pack = folder + checksummed manifest. Verification names every discrepancy; install refuses
tampered or manifest-less packs (nothing partial enters memory). Offline.
"""
import sys
from pathlib import Path

from agents.core import knowledge_packs as kp
from agents.core.local_docs import LocalDocsIndexer

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _mk_pack(tmp_path) -> Path:
    root = tmp_path / "pack"
    (root / "sub").mkdir(parents=True)
    (root / "a.md").write_text("# alpha doc\ncontent alpha", encoding="utf-8")
    (root / "sub" / "b.txt").write_text("bravo content", encoding="utf-8")
    (root / "ignore.bin").write_bytes(b"\x00\x01")     # unsupported ext → not in the pack
    return root


def test_manifest_fingerprints_supported_files_only():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = _mk_pack(Path(td))
        m = kp.build_manifest(root, name="demo", version="1.2.3")
        paths = [e["path"] for e in m["files"]]
        assert paths == ["a.md", "sub/b.txt"]           # posix-relative, sorted, no .bin
        assert m["count"] == 2 and m["total_bytes"] > 0
        assert all(len(e["sha256"]) == 64 for e in m["files"])
        # deterministic
        assert kp.build_manifest(root, name="demo", version="1.2.3") == m


def test_verify_names_every_discrepancy():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = _mk_pack(Path(td))
        m = kp.build_manifest(root)
        assert kp.verify_pack(root, m)["ok"] is True
        # modify one, delete one, add one
        (root / "a.md").write_text("tampered", encoding="utf-8")
        (root / "sub" / "b.txt").unlink()
        (root / "new.md").write_text("smuggled", encoding="utf-8")
        check = kp.verify_pack(root, m)
        assert check["ok"] is False
        assert check["modified"] == ["a.md"]
        assert check["missing"] == ["sub/b.txt"]
        assert check["unexpected"] == ["new.md"]


async def test_install_indexes_only_a_verified_pack():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = _mk_pack(Path(td))
        kp.write_manifest(root, kp.build_manifest(root, name="demo"))
        remembered = []

        async def remember(text, meta):
            remembered.append((text, meta))
            return "id"

        out = await kp.install_pack(root, LocalDocsIndexer(remember))
        assert out["installed"] is True and out["pack"] == "demo"
        assert out["index"]["files_indexed"] == 2
        assert remembered and remembered[0][1]["source"] == "local_docs"


async def test_install_refuses_tampered_pack_nothing_enters_memory():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = _mk_pack(Path(td))
        kp.write_manifest(root, kp.build_manifest(root))
        (root / "a.md").write_text("evil", encoding="utf-8")       # tamper after manifest
        remembered = []

        async def remember(text, meta):
            remembered.append(text)
            return "id"

        out = await kp.install_pack(root, LocalDocsIndexer(remember))
        assert out["installed"] is False and out["reason"] == "verification_failed"
        assert out["verify"]["modified"] == ["a.md"]
        assert remembered == []                                     # nothing partial indexed


async def test_install_refuses_manifestless_folder():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = _mk_pack(Path(td))

        async def remember(text, meta):
            return "id"

        out = await kp.install_pack(root, LocalDocsIndexer(remember))
        assert out["installed"] is False and out["reason"] == "no_manifest"


def test_manifest_on_missing_folder_is_honest():
    assert "error" in kp.build_manifest("/nope/definitely-missing-xyz")
