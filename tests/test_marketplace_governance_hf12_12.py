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


def _entries(mk):
    """Everything in the skills dir, staging debris included."""
    return sorted(p.name for p in mk.skills_dir.iterdir())


def _pkg(*entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


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
    assert _entries(mk) == []                          # H503: and nothing landed inside it


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


# ── H503: the install path goes through the shared archive_safe extractor ──
@pytest.mark.parametrize("evil", ["..\\evil.txt", "C:/evil.txt", "c:evil.txt",
                                  "\\\\server\\share\\evil.txt", "/abs.txt"])
def test_windows_and_absolute_member_names_are_rejected(tmp_path, evil):
    mk = _mk(tmp_path)
    with pytest.raises(ValueError):
        mk.install_from_zip(_pkg(("SKILL.md", "# Evil\n"), (evil, "pwned")))
    assert _entries(mk) == []
    assert not (tmp_path / "evil.txt").exists()


def test_symlink_entry_fails_the_install(tmp_path):
    import stat
    mk = _mk(tmp_path)
    link = zipfile.ZipInfo("main.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match="symlink"):
        mk.install_from_zip(_pkg(("SKILL.md", "# Linky\n"), (link, "/etc/passwd")))
    assert _entries(mk) == []


def test_oversized_package_is_rejected_before_anything_lands(tmp_path, monkeypatch):
    from core.skills import marketplace as mkmod

    from agents.core.archive_safe import ArchiveLimits
    monkeypatch.setattr(mkmod, "SKILL_PACKAGE_LIMITS", ArchiveLimits(max_members=10, max_bytes=1000))
    mk = _mk(tmp_path)
    with pytest.raises(ValueError, match="bytes"):
        mk.install_from_zip(_pkg(("SKILL.md", "# Big\n"), ("blob.bin", b"\0" * 5000)))
    with pytest.raises(ValueError, match="members"):
        mk.install_from_zip(_pkg(("SKILL.md", "# Many\n"),
                                 *[(f"f{i}.txt", "x") for i in range(12)]))
    assert _entries(mk) == []


def test_a_rejected_update_keeps_the_previous_install(tmp_path, monkeypatch):
    """The signature gate used to rmtree the target dir — destroying the installed skill
    when an unsigned *update* of it was refused. Staging keeps the old tree intact."""
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    mk = _mk(tmp_path)
    _, name = _publish(mk, folder="src", title="Keeper")
    monkeypatch.setenv("JARVIS_REQUIRE_SIGNED_SKILLS", "1")
    assert mk.install_skill(name) is True
    installed = mk.skills_dir / "keeper"
    assert (installed / "main.py").read_text() == "def run():\n    return 'ok'\n"
    with pytest.raises(PermissionError):
        mk.install_from_zip(_pkg(("SKILL.md", "# Keeper\n"), ("main.py", "tampered = True\n")))
    assert (installed / "main.py").read_text() == "def run():\n    return 'ok'\n"
    assert (installed / "SKILL.sig").exists()
    assert sorted(_entries(mk)) == ["keeper", "src"]   # no staging debris


def test_reinstall_places_exactly_the_package(tmp_path):
    mk = _mk(tmp_path)
    assert mk.install_from_zip(_pkg(("SKILL.md", "# Swap\n"), ("old.py", "x = 1\n"))) is True
    assert mk.install_from_zip(_pkg(("SKILL.md", "# Swap\n"), ("new.py", "y = 2\n"))) is True
    installed = mk.skills_dir / "swap"
    assert (installed / "new.py").exists()
    assert not (installed / "old.py").exists()         # no stale file outside the package
    assert (installed / "EXTERNAL_SOURCE").exists()    # provenance marker still written
    assert _entries(mk) == ["swap"]


def test_nested_package_layout_is_preserved(tmp_path):
    mk = _mk(tmp_path)
    assert mk.install_from_zip(_pkg(("pkg/SKILL.md", "# Nested\n"), ("pkg/main.py", "x\n"))) is True
    installed = mk.skills_dir / "nested"
    assert (installed / "pkg" / "SKILL.md").exists()
    assert (installed / "pkg" / "EXTERNAL_SOURCE").exists()
    assert (installed / "EXTERNAL_SOURCE").exists()
