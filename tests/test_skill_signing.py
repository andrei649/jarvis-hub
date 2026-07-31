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
    # SEC-B2: an unkeyed digest verifies, but it is NOT a signature — anyone can
    # recompute it, so it proves the files are intact and nothing about who wrote them.
    # It stays trusted (at the shipped default it is the only integrity signal there is)
    # and the reason now says which of the two claims is being made. `signed` is reserved
    # for the keyed case — see test_hmac_signing_with_key.
    assert reason == "integrity-only"


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
    from agents.core.skills import loader as loader_mod
    skills_root = tmp_path / "skills"
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
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
    from agents.core.skills import loader as loader_mod
    skills_root = tmp_path / "skills"
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    sk_dir = _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    signing.sign_skill(sk_dir)
    loader = SkillLoader()
    loader.discover()
    sk = loader.get_skill("DemoSkill")
    assert sk.trusted is True
    assert sk.module is not None


def test_require_signed_sandboxes_unsigned(tmp_path, monkeypatch):
    from agents.core.skills import loader as loader_mod
    monkeypatch.setenv("JARVIS_REQUIRE_SIGNED_SKILLS", "1")
    # SEC-B2: enforcement now requires a key. Without one the "signature" is a plain
    # sha256 an attacker can recompute and ship themselves, so the gate would block
    # honest unsigned skills and not a deliberate one — a misconfiguration, and
    # require_signed() refuses rather than pretending to enforce.
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    skills_root = tmp_path / "skills"
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    _make_skill(skills_root / "demo", body="raise RuntimeError('should not exec')\n")
    loader = SkillLoader()
    loader.discover()
    sk = loader.get_skill("DemoSkill")
    assert sk.sandboxed is True
    assert sk.module is None  # untrusted module NOT exec'd in strict mode


def test_loader_sign_skill_helper(tmp_path, monkeypatch):
    from agents.core.skills import loader as loader_mod
    skills_root = tmp_path / "skills"
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    loader = SkillLoader()
    loader.discover()
    line = loader.sign_skill("DemoSkill")
    assert line.startswith("sha256:")
    assert loader.get_skill("DemoSkill").trusted is True


def test_to_dict_shape(tmp_path, monkeypatch):
    from agents.core.skills import loader as loader_mod
    skills_root = tmp_path / "skills"
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    loader = SkillLoader()
    loader.discover()
    d = loader.get_skill("DemoSkill").to_dict()
    for key in ("name", "trusted", "signature_reason", "sandboxed", "has_module"):
        assert key in d


# ── SEC-B2: an unkeyed digest is not a signature ──────────────────
def test_enforcement_without_a_key_fails_closed(monkeypatch):
    """The finding: hardening the flag bought nothing against a deliberate adversary.

    With JARVIS_REQUIRE_SIGNED_SKILLS=1 and no key, `compute_digest` returns a plain
    sha256 — so a forged package ships its own matching SKILL.sig and loads as trusted.
    The flag refused honest unsigned content and accepted anything an attacker signed,
    which is the worst of both. Enforcement without a key is a misconfiguration, and
    refusing to proceed is the same stance hardened.enforce() takes on a missing audit key.
    """
    monkeypatch.setenv("JARVIS_REQUIRE_SIGNED_SKILLS", "1")
    monkeypatch.delenv("JARVIS_SKILL_SIGNING_KEY", raising=False)
    with pytest.raises(signing.SkillSigningMisconfigured) as exc:
        signing.require_signed()
    assert "JARVIS_SKILL_SIGNING_KEY" in str(exc.value)


def test_enforcement_with_a_key_is_allowed(monkeypatch):
    monkeypatch.setenv("JARVIS_REQUIRE_SIGNED_SKILLS", "1")
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    assert signing.require_signed() is True


def test_default_is_unchanged(monkeypatch):
    """The shipped default must keep working — this fix is for the owner who hardened."""
    monkeypatch.delenv("JARVIS_REQUIRE_SIGNED_SKILLS", raising=False)
    monkeypatch.delenv("JARVIS_SKILL_SIGNING_KEY", raising=False)
    assert signing.require_signed() is False


def test_a_forged_unkeyed_signature_is_labelled_not_authenticated(tmp_path, monkeypatch):
    """An attacker computes the same digest we do, so `trusted` cannot mean authorship."""
    monkeypatch.delenv("JARVIS_SKILL_SIGNING_KEY", raising=False)
    sk = _make_skill(tmp_path / "forged", body="x = 1\n")
    # the "attacker" signs their own package with the public algorithm
    signing.sign_skill(sk)
    trusted, reason = signing.verify_skill(sk)
    assert trusted is True
    assert reason == "integrity-only", (
        "an unkeyed digest reported as `signed` claims authorship it cannot prove"
    )


def test_posture_reports_effectiveness_not_just_the_flag(monkeypatch):
    """A status surface must not let 'the flag is on' read as 'signatures are enforced'."""
    monkeypatch.setenv("JARVIS_REQUIRE_SIGNED_SKILLS", "1")
    monkeypatch.delenv("JARVIS_SKILL_SIGNING_KEY", raising=False)
    posture = signing.signing_posture()          # must not raise, unlike require_signed()
    assert posture["require_signed"] is True
    assert posture["signing_key_configured"] is False
    assert posture["effective"] is False
    assert posture["misconfigured"] is True

    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    posture = signing.signing_posture()
    assert posture["effective"] is True and posture["misconfigured"] is False
    assert posture["integrity_only"] is False
