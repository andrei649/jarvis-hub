"""0.20 Jarvis Vault — encrypted personal blob vault + retention."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.vault import Vault, VaultError  # noqa: E402


def _vault(tmp_path, **kw):
    return Vault(tmp_path / "v", key="test-passphrase", **kw)


def test_roundtrip_and_ciphertext_on_disk(tmp_path):
    v = _vault(tmp_path)
    entry = v.put(b"family document contents", name="doc.txt", kind="document", now=100.0)
    assert v.get(entry["id"]) == b"family document contents"
    for p in (tmp_path / "v").rglob("*"):
        if p.is_file():
            assert b"family document contents" not in p.read_bytes()
    meta = v.list()[0]
    assert meta["name"] == "doc.txt" and meta["bytes"] == len(b"family document contents")
    assert "content" not in meta


def test_tampered_blob_raises_never_returns_garbage(tmp_path):
    v = _vault(tmp_path)
    e = v.put(b"secret", now=1.0)
    blob = tmp_path / "v" / f"{e['id']}.blob"
    blob.write_text(blob.read_text(encoding="ascii")[:-4] + "AAAA", encoding="ascii")
    with pytest.raises(VaultError):
        v.get(e["id"])


def test_quota_refuses_never_evicts(tmp_path):
    v = _vault(tmp_path, max_items=2, max_total_bytes=100)
    v.put(b"a" * 40, now=1.0)
    v.put(b"b" * 40, now=2.0)
    with pytest.raises(VaultError):
        v.put(b"c", now=3.0)
    v2 = _vault(tmp_path / "w", max_total_bytes=50)
    v2.put(b"x" * 40, now=1.0)
    with pytest.raises(VaultError):
        v2.put(b"y" * 20, now=2.0)
    assert v2.stats()["items"] == 1


def test_retention_sweep_is_deterministic_and_reported(tmp_path):
    v = _vault(tmp_path)
    keep = v.put(b"keep", now=10.0)
    gone = v.put(b"gone", now=10.0, expires_at=20.0)
    later = v.put(b"later", now=10.0, expires_at=99.0)
    out = v.sweep(now=20.0)
    assert out == {"removed": [gone["id"]], "count": 1}
    assert {e["id"] for e in v.list()} == {keep["id"], later["id"]}
    assert not (tmp_path / "v" / f"{gone['id']}.blob").exists()


def test_persistence_across_instances(tmp_path):
    v = _vault(tmp_path)
    e = v.put(b"survives restart", name="n", now=5.0)
    assert Vault(tmp_path / "v", key="test-passphrase").get(e["id"]) == b"survives restart"
    with pytest.raises(VaultError):
        Vault(tmp_path / "v", key="wrong-passphrase").get(e["id"])


def test_forget_me_hooks(tmp_path):
    v = _vault(tmp_path)
    e = v.put(b"private", now=1.0)
    v.clear_memory()
    assert v.list() == []
    assert (tmp_path / "v" / f"{e['id']}.blob").exists()
    v2 = Vault(tmp_path / "v", key="test-passphrase")
    assert v2.purge() == 1
    assert v2.list() == [] and not (tmp_path / "v" / f"{e['id']}.blob").exists()


def test_remove_and_missing_are_honest(tmp_path):
    v = _vault(tmp_path)
    e = v.put(b"x", now=1.0)
    assert v.remove(e["id"]) is True
    assert v.remove(e["id"]) is False
    with pytest.raises(VaultError):
        v.get(e["id"])
