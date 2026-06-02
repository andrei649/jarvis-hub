"""Tests for skill signature verification + sandboxing (H12.1)."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.skills import signing
from agents.core.skills.loader import SkillLoader


def _make_skill(path: Path, name="DemoSkill", body="x = 1\n"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"# {name}\n\n> demo\n\n**Version:** 0.1.0\n**Agents:** jarvis\n\n## Commands\n- `demo <q>` — do it\n",
        encoding="utf-8",
    )
    (path / "main.py").write_text(body, encoding="utf-8")
    return path


def test_unsigned_skill_flagged_untrusted(tmp_path):
    sk = _make_skill(tmp_path / "demo")
    trusted, reason = signing.verify_skill(sk)
    assert trusted is False
    assert reason == "unsigned"


def test_sign_then_verify(tmp_path):
    sk = _make_skill(tmp_path / "demo")
    line = signing.sign_skill(sk)
    assert (sk / "SKILL.sig").exists()
    assert line.startswith("sha256:")
    trusted, reason = signing.verify_skill(sk)
    assert trusted is True
    assert reason == "signed"


def test_tampered_skill_detected(tmp_path):
    sk = _make_skill(tmp_path / "demo")
    signing.sign_skill(sk)
    # Modify source after signing → signature no longer matches.
    (sk / "main.py").write_text("x = 999  # tampered\n", encoding="utf-8")
    trusted, reason = signing.verify_skill(sk)
    assert trusted is False
    assert reason == "signature-mismatch"


def test_malformed_signature(tmp_path):
    sk = _make_skill(tmp_path / "demo")
    (sk / "SKILL.sig").write_text("garbage-no-colon\n", encoding="utf-8")
    trusted, reason = signing.verify_skill(sk)
    assert trusted is False
    assert reason == "malformed-signature"


def test_hmac_signing_with_key(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    sk = _make_skill(tmp_path / "demo")
    line = signing.sign_skill(sk)
    assert line.startswith("hmac-sha256:")
    trusted, reason = signing.verify_skill(sk)
    assert trusted is True and reason == "signed"


def test_hmac_sig_algo_mismatch_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    sk = _make_skill(tmp_path / "demo")
    signing.sign_skill(sk)
    # Same machine, key now gone → recomputed algo is plain sha256, sig is hmac.
    monkeypatch.delenv("JARVIS_SKILL_SIGNING_KEY")
    trusted, reason = signing.verify_skill(sk)
    assert trusted is False and reason == "algo-mismatch"


def test_loader_flags_unsigned_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    loader = SkillLoader()
    loader.discover()
    sk = loader.get_skill("DemoSkill")
    assert sk is not None
    assert sk.trusted is False
    assert sk.signature_reason == "unsigned"
    # Advisory mode: module still loaded, not sandboxed.
    assert sk.sandboxed is False
    assert sk.module is not None


def test_loader_loads_signed_skill_trusted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    sk_dir = _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    signing.sign_skill(sk_dir)
    loader = SkillLoader()
    loader.discover()
    sk = loader.get_skill("DemoSkill")
    assert sk.trusted is True
    assert sk.module is not None


def test_require_signed_sandboxes_unsigned(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_REQUIRE_SIGNED_SKILLS", "1")
    skills_root = tmp_path / "skills"
    _make_skill(skills_root / "demo", body="raise RuntimeError('should not exec')\n")
    loader = SkillLoader()
    loader.discover()
    sk = loader.get_skill("DemoSkill")
    assert sk.sandboxed is True
    assert sk.module is None  # untrusted module NOT exec'd in strict mode


def test_loader_sign_skill_helper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    loader = SkillLoader()
    loader.discover()
    line = loader.sign_skill("DemoSkill")
    assert line.startswith("sha256:")
    assert loader.get_skill("DemoSkill").trusted is True


def test_to_dict_shape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    loader = SkillLoader()
    loader.discover()
    d = loader.get_skill("DemoSkill").to_dict()
    for key in ("name", "trusted", "signature_reason", "sandboxed", "has_module"):
        assert key in d
