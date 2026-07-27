"""H12.12: signed + moderated skills marketplace (anti-ClawHub supply chain).

Publishing signs the package; installing is gated by a moderation review and a
signature check; and path-traversal (zip-slip) entries are refused before
extraction. The two enforcement gates are opt-in (env) so default behaviour is
unchanged, but the metadata is always surfaced and zip-slip is always blocked.
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.skills.marketplace import SkillMarketplace  # noqa: E402


def _mk(tmp_path):
    return SkillMarketplace(skills_dir=str(tmp_path / "skills"), db_path=str(tmp_path / "mk.db"))


def _publish(mk, folder="myskill", title="My Skill"):
    sd = mk.skills_dir / folder
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "SKILL.md").write_text(f"# {title}\nversion: 1.0\n", encoding="utf-8")
    (sd / "main.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    mk.publish_skill(folder)
    return sd, mk.list_skills()[0]["name"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for v in ("JARVIS_REQUIRE_REVIEWED_SKILLS", "JARVIS_REQUIRE_SIGNED_SKILLS", "JARVIS_SKILL_SIGNING_KEY"):
        monkeypatch.delenv(v, raising=False)


def test_publish_signs_and_marks_pending(tmp_path):
    mk = _mk(tmp_path)
    sd, name = _publish(mk)
    assert (sd / "SKILL.sig").exists()                 # package is signed on publish
    entry = mk.list_skills()[0]
    assert entry["review_status"] == "pending"
    assert entry["signed"] is True


def test_review_gate_off_by_default(tmp_path):
    mk = _mk(tmp_path)
    _, name = _publish(mk)
    assert mk.install_skill(name) is True              # pending installs when gate is off


def test_review_gate_blocks_until_approved(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_REQUIRE_REVIEWED_SKILLS", "1")
    mk = _mk(tmp_path)
    _, name = _publish(mk)
    with pytest.raises(PermissionError):
        mk.install_skill(name)                         # pending → blocked
    mk.approve_skill(name)
    assert mk.install_skill(name) is True              # approved → installs
    mk.reject_skill(name)
    with pytest.raises(PermissionError):
        mk.install_skill(name)                         # rejected → blocked again


def test_zip_slip_is_blocked(tmp_path):
    mk = _mk(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", "# Evil\n")
        z.writestr("../../evil.txt", "pwned")
    with pytest.raises(ValueError):
        mk.install_from_zip(buf.getvalue())
    assert not (tmp_path / "evil.txt").exists()        # nothing escaped the skills dir


def test_signature_gate_rejects_unsigned(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_REQUIRE_SIGNED_SKILLS", "1")
    # SEC-B2: enforcement requires a key, or the gate accepts any signature an attacker
    # computes for themselves. require_signed() refuses to pretend otherwise.
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    mk = _mk(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", "# Unsigned\n")
        z.writestr("main.py", "x = 1\n")               # no SKILL.sig
    with pytest.raises(PermissionError):
        mk.install_from_zip(buf.getvalue())
    assert not (mk.skills_dir / "unsigned").exists()   # rejected package is removed


def test_signature_gate_accepts_signed_publish(tmp_path, monkeypatch):
    # Publish (which signs), then require signatures on install → still installs.
    # Sign at publish time under the same key enforcement will verify against (SEC-B2).
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    mk = _mk(tmp_path)
    _, name = _publish(mk)
    monkeypatch.setenv("JARVIS_REQUIRE_SIGNED_SKILLS", "1")
    assert mk.install_skill(name) is True
