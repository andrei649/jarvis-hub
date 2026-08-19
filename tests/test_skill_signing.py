"""Tests for skill signature verification + sandboxing (H12.1)."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.skills import signing
from agents.core.skills.approval import SkillApprovalStore
from agents.core.skills.loader import SkillLoader


def _make_skill(path: Path, name="DemoSkill", body="x = 1\n"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"# {name}\n\n> demo\n\n**Version:** 0.1.0\n**Agents:** jarvis\n\n## Commands\n- `demo <q>` — do it\n",
        encoding="utf-8",
    )
    (path / "main.py").write_text(body, encoding="utf-8")
    return path


def _directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")


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


def test_host_provenance_marker_does_not_break_keyed_signature(tmp_path, monkeypatch):
    """Marketplace provenance is trusted control metadata, not package source."""
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    sk = _make_skill(tmp_path / "demo")
    signing.sign_skill(sk)
    (sk / "EXTERNAL_SOURCE").write_text("source=marketplace\n", encoding="utf-8")

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
    bundled = _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    monkeypatch.setattr(
        loader_mod,
        "_matches_bundled_source",
        lambda path, root: path.resolve() == bundled.resolve(),
    )
    monkeypatch.setattr(
        loader_mod,
        "_snapshot_matches_bundled",
        lambda snapshot, name: name == "demo",
    )
    loader = SkillLoader()
    loader.discover()
    sk = loader.get_skill("DemoSkill")
    assert sk is not None
    assert sk.trusted is False
    assert sk.signature_reason == "unsigned"
    # Advisory mode: module still loaded, not sandboxed.
    assert sk.sandboxed is False
    assert sk.module is not None


def test_unsigned_user_home_skill_is_visible_but_never_imported(tmp_path, monkeypatch):
    """Owner/imported code must not execute merely because discovery found it."""
    from agents.core.skills import loader as loader_mod

    bundled_root = tmp_path / "bundled"
    user_root = tmp_path / "owner" / "skills"
    _make_skill(
        bundled_root / "bundled",
        name="Bundled",
        body="MARKER = 'bundled-loaded'\n",
    )
    _make_skill(
        user_root / "personal",
        name="Personal",
        body="raise RuntimeError('unsigned owner code executed')\n",
    )
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: user_root)
    monkeypatch.setattr(
        loader_mod,
        "_matches_bundled_source",
        lambda path, root: path.resolve() == (bundled_root / "bundled").resolve(),
    )
    monkeypatch.setattr(
        loader_mod,
        "_snapshot_matches_bundled",
        lambda snapshot, name: name == "bundled",
    )

    skills = SkillLoader().discover()

    assert skills["Bundled"].module is not None
    assert skills["Personal"].module is None
    assert skills["Personal"].sandboxed is True
    assert skills["Personal"].signature_reason == "unsigned"


@pytest.mark.parametrize("linked_root", [True, False], ids=["root", "entry"])
def test_linked_bundled_discovery_provenance_fails_closed(
    tmp_path,
    monkeypatch,
    linked_root,
):
    """A link or junction cannot turn outside bytes into bundled code."""
    from agents.core.skills import loader as loader_mod

    outside_root = tmp_path / "outside"
    _make_skill(
        outside_root / "linked",
        name="Linked",
        body="MARKER = 'outside-code-executed'\n",
    )
    bundled_root = tmp_path / "bundled"
    if linked_root:
        _directory_link(bundled_root, outside_root)
    else:
        bundled_root.mkdir()
        _directory_link(bundled_root / "linked", outside_root / "linked")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)

    skill = SkillLoader(
        approval_store=SkillApprovalStore(tmp_path / "private" / "approvals.json")
    ).discover()["Linked"]

    assert skill.module is None
    assert skill.sandboxed is True


def test_forged_user_home_approval_marker_does_not_execute(tmp_path, monkeypatch):
    """Candidate-controlled integrity bytes cannot attest owner approval."""
    from agents.core.skills import loader as loader_mod

    bundled_root = tmp_path / "bundled"
    bundled_root.mkdir()
    user_root = tmp_path / "owner" / "skills"
    skill_dir = _make_skill(
        user_root / "personal",
        name="Personal",
        body="MARKER = 'forged-loaded'\n",
    )
    signing.sign_skill(skill_dir)
    (skill_dir / "OWNER_APPROVED_IN_PROCESS").write_text("forged\n", encoding="utf-8")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: user_root)

    skill = SkillLoader().discover()["Personal"]

    assert skill.signature_reason == "integrity-only"
    assert skill.module is None
    assert skill.sandboxed is True


def test_keyed_user_home_skill_may_load_in_process(tmp_path, monkeypatch):
    """A real HMAC signature remains the non-interactive external-code trust path."""
    from agents.core.skills import loader as loader_mod

    bundled_root = tmp_path / "bundled"
    bundled_root.mkdir()
    user_root = tmp_path / "owner" / "skills"
    skill_dir = _make_skill(
        user_root / "personal",
        name="Personal",
        body="MARKER = 'keyed-loaded'\n",
    )
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    signing.sign_skill(skill_dir)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: user_root)

    skill = SkillLoader().discover()["Personal"]

    assert skill.signature_reason == "signed"
    assert skill.sandboxed is False
    assert skill.module is not None


@pytest.mark.parametrize("trust_path", ["approval", "keyed-signature"])
def test_external_execution_uses_validated_source_snapshot(
    tmp_path,
    monkeypatch,
    trust_path,
):
    """Changing disk after the trust decision cannot change executed bytes."""
    from agents.core.skills import loader as loader_mod

    bundled_root = tmp_path / "bundled"
    bundled_root.mkdir()
    user_root = tmp_path / "owner" / "skills"
    marker = tmp_path / "executed.txt"
    approved_body = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('approved', encoding='utf-8')\n"
    )
    attacker_body = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('attacker', encoding='utf-8')\n"
    )
    skill_dir = _make_skill(
        user_root / "personal",
        name="Personal",
        body=approved_body,
    )
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    if trust_path == "approval":
        store.approve(skill_dir)
    else:
        monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
        signing.sign_skill(skill_dir)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: user_root)
    original_spec = loader_mod.importlib.util.spec_from_file_location

    def swap_before_disk_loader(*args, **kwargs):
        (skill_dir / "main.py").write_text(attacker_body, encoding="utf-8")
        return original_spec(*args, **kwargs)

    monkeypatch.setattr(
        loader_mod.importlib.util,
        "spec_from_file_location",
        swap_before_disk_loader,
    )

    skill = SkillLoader(approval_store=store).discover()["Personal"]

    assert skill.module is not None
    assert marker.read_text(encoding="utf-8") == "approved"


@pytest.mark.parametrize("trust_path", ["approval", "keyed-signature"])
def test_external_execution_reads_artifacts_from_validated_snapshot(
    tmp_path,
    monkeypatch,
    trust_path,
):
    """Relative artifact reads cannot reopen swapped candidate-controlled bytes."""
    from agents.core.skills import loader as loader_mod

    bundled_root = tmp_path / "bundled"
    bundled_root.mkdir()
    user_root = tmp_path / "owner" / "skills"
    marker = tmp_path / "artifact-result.txt"
    body = (
        "from pathlib import Path\n"
        "payload = Path(__file__).with_name('payload.txt').read_text(encoding='utf-8')\n"
        f"Path({str(marker)!r}).write_text(payload, encoding='utf-8')\n"
    )
    skill_dir = _make_skill(user_root / "personal", name="Personal", body=body)
    payload = skill_dir / "payload.txt"
    payload.write_text("approved", encoding="utf-8")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")

    def mutate_source() -> None:
        payload.write_text("attacker", encoding="utf-8")

    if trust_path == "approval":
        store.approve(skill_dir)
        approved_snapshot = store.approved_snapshot

        def approve_then_mutate(*args, **kwargs):
            result = approved_snapshot(*args, **kwargs)
            mutate_source()
            return result

        monkeypatch.setattr(store, "approved_snapshot", approve_then_mutate)
    else:
        monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
        signing.sign_skill(skill_dir)
        verify_skill = signing.verify_skill

        def verify_then_mutate(*args, **kwargs):
            result = verify_skill(*args, **kwargs)
            mutate_source()
            return result

        monkeypatch.setattr(signing, "verify_skill", verify_then_mutate)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", bundled_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: user_root)

    skill = SkillLoader(approval_store=store).discover()["Personal"]

    assert skill.module is not None
    assert marker.read_text(encoding="utf-8") == "approved"


def test_signing_refuses_hardlinked_control_file_without_overwriting_target(
    tmp_path,
):
    victim = tmp_path / "victim.txt"
    victim.write_text("DO-NOT-TOUCH", encoding="utf-8")
    skill_dir = _make_skill(tmp_path / "skill", name="Demo")
    os.link(victim, skill_dir / "SKILL.sig")

    with pytest.raises(signing.SkillSourceSnapshotError, match="hardlinked control"):
        signing.sign_skill(skill_dir)

    assert victim.read_text(encoding="utf-8") == "DO-NOT-TOUCH"
    assert (skill_dir / "SKILL.sig").samefile(victim)


def test_imported_skill_sidecar_blocks_unsigned_in_process_import(tmp_path, monkeypatch):
    """Imported provenance is external even when the skill lives under the app root."""
    from agents.core.skills import loader as loader_mod

    skills_root = tmp_path / "skills"
    skill_dir = _make_skill(
        skills_root / "imported",
        name="Imported",
        body='raise RuntimeError("unsigned imported module executed")\n',
    )
    (skill_dir / "manifest.json").write_text(
        '{"imported": true, "source": "external"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: tmp_path / "user-skills")
    monkeypatch.setenv("JARVIS_REQUIRE_SIGNED_SKILLS", "0")

    skill = SkillLoader().discover()["Imported"]

    assert skill.module is None
    assert skill.sandboxed is True
    assert skill.signature_reason == "unsigned"


@pytest.mark.parametrize("external_marker", ["manifest.json", "EXTERNAL_SOURCE"])
@pytest.mark.parametrize("registry_state", ["intact", "missing", "corrupt", "unknown-schema"])
def test_removing_external_sidecar_cannot_shed_private_provenance(
    tmp_path,
    monkeypatch,
    external_marker,
    registry_state,
):
    """A changed approved import remains external after deleting its sidecar."""
    from agents.core.skills import loader as loader_mod

    skills_root = tmp_path / "skills"
    marker = tmp_path / "executed.txt"
    skill_dir = _make_skill(
        skills_root / "imported",
        name="Imported",
        body="VALUE = 'approved'\n",
    )
    provenance = skill_dir / external_marker
    provenance.write_text(
        '{"imported": true, "source": "external"}'
        if external_marker == "manifest.json"
        else "marketplace\n",
        encoding="utf-8",
    )
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill_dir)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: tmp_path / "user-skills")

    first = SkillLoader(approval_store=store).discover()["Imported"]
    assert first.module is not None

    provenance.unlink()
    (skill_dir / "main.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('attacker', encoding='utf-8')\n",
        encoding="utf-8",
    )
    if registry_state == "missing":
        store.path.unlink()
    elif registry_state == "corrupt":
        store.path.write_text("not-json", encoding="utf-8")
    elif registry_state == "unknown-schema":
        store.path.write_text('{"version": 999, "approvals": {}}', encoding="utf-8")

    second = SkillLoader(approval_store=store).discover()["Imported"]

    assert second.module is None
    assert second.sandboxed is True
    assert store.tracks_path(skill_dir) is (registry_state == "intact")
    assert not store.is_approved(skill_dir)
    assert not marker.exists()


def test_relocated_external_skill_cannot_inherit_bundled_provenance(
    tmp_path,
    monkeypatch,
):
    from agents.core.skills import loader as loader_mod

    skills_root = tmp_path / "skills"
    marker = tmp_path / "executed.txt"
    original = _make_skill(skills_root / "original", name="Imported", body="VALUE = 'approved'\n")
    (original / "manifest.json").write_text('{"imported": true}', encoding="utf-8")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(original)
    moved = original.rename(skills_root / "moved")
    (moved / "manifest.json").unlink()
    (moved / "main.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('attacker', encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: tmp_path / "user-skills")

    skill = SkillLoader(approval_store=store).discover()["Imported"]

    assert skill.module is None
    assert skill.sandboxed is True
    assert not marker.exists()


def test_product_bundled_manifest_matches_exact_shipped_sources():
    from agents.core.skills import loader as loader_mod

    shipped = {path.name for path in loader_mod.SKILLS_DIR.iterdir() if path.is_dir()}

    assert shipped == set(loader_mod._BUNDLED_SKILL_MANIFEST)
    assert all(
        loader_mod._matches_bundled_source(loader_mod.SKILLS_DIR / name, loader_mod.SKILLS_DIR)
        for name in shipped
    )


def test_exact_bundled_source_executes_same_validated_snapshot(
    tmp_path,
    monkeypatch,
):
    from agents.core.skills import loader as loader_mod

    skills_root = tmp_path / "skills"
    marker = tmp_path / "executed.txt"
    approved_body = (
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('shipped', encoding='utf-8')\n"
    )
    attacker_body = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('attacker', encoding='utf-8')\n"
    )
    skill_dir = _make_skill(skills_root / "demo", name="Demo", body=approved_body)
    expected = {
        relative: hashlib.sha256(
            (skill_dir / relative).read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for relative in ("SKILL.md", "main.py")
    }
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: tmp_path / "user-skills")
    monkeypatch.setattr(loader_mod, "_BUNDLED_SKILL_MANIFEST", {"demo": expected})
    original_spec = loader_mod.importlib.util.spec_from_file_location

    def mutate_after_snapshot(*args, **kwargs):
        (skill_dir / "main.py").write_text(attacker_body, encoding="utf-8")
        return original_spec(*args, **kwargs)

    monkeypatch.setattr(
        loader_mod.importlib.util,
        "spec_from_file_location",
        mutate_after_snapshot,
    )

    skill = SkillLoader().discover()["Demo"]

    assert skill.module is not None
    assert skill.sandboxed is False
    assert marker.read_text(encoding="utf-8") == "shipped"


@pytest.mark.parametrize("external_marker", ["manifest.json", "EXTERNAL_SOURCE"])
def test_imported_or_marketplace_skill_cannot_self_approve(
    tmp_path,
    monkeypatch,
    external_marker,
):
    from agents.core.skills import loader as loader_mod

    skills_root = tmp_path / "skills"
    skill_dir = _make_skill(
        skills_root / "external",
        name="External",
        body="MARKER = 'forged-loaded'\n",
    )
    if external_marker == "manifest.json":
        (skill_dir / external_marker).write_text(
            '{"imported": true, "source": "external"}', encoding="utf-8"
        )
    else:
        (skill_dir / external_marker).write_text("marketplace\n", encoding="utf-8")
    signing.sign_skill(skill_dir)
    (skill_dir / "OWNER_APPROVED_IN_PROCESS").write_text("forged\n", encoding="utf-8")
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: tmp_path / "user-skills")

    skill = SkillLoader().discover()["External"]

    assert skill.signature_reason == "integrity-only"
    assert skill.module is None
    assert skill.sandboxed is True


def test_loader_loads_signed_skill_trusted(tmp_path, monkeypatch):
    from agents.core.skills import loader as loader_mod

    skills_root = tmp_path / "skills"
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    sk_dir = _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    monkeypatch.setattr(
        loader_mod,
        "_matches_bundled_source",
        lambda path, root: path.resolve() == sk_dir.resolve(),
    )
    monkeypatch.setattr(
        loader_mod,
        "_snapshot_matches_bundled",
        lambda snapshot, name: name == "demo",
    )
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
    posture = signing.signing_posture()  # must not raise, unlike require_signed()
    assert posture["require_signed"] is True
    assert posture["signing_key_configured"] is False
    assert posture["effective"] is False
    assert posture["misconfigured"] is True

    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "project-key")
    posture = signing.signing_posture()
    assert posture["effective"] is True and posture["misconfigured"] is False
    assert posture["integrity_only"] is False
