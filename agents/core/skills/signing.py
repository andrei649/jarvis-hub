"""
signing.py — Skill signature verification (H12.1, anti-ClawHub).

A skill pack is "signed" by shipping a ``SKILL.sig`` file next to ``SKILL.md``.
The signature is a deterministic content hash over every relevant source/artifact
file in the skill tree, optionally HMAC-keyed when a project signing key is set.

This is **opt-in / advisory by default**: unsigned skills still load, but they
are flagged ``trusted=False`` so the loader can sandbox them and the HUD can
surface the distinction. When ``JARVIS_REQUIRE_SIGNED_SKILLS=1`` the loader
refuses to run the Python module of an unsigned/invalid skill.

Sig file format (one line)::

    sha256:<hex>          # plain content hash (anyone can recompute)
    hmac-sha256:<hex>     # keyed hash, requires JARVIS_SKILL_SIGNING_KEY
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.skills.signing")

SIG_FILENAME = "SKILL.sig"
# Host-managed control files are not executable skill artifacts and may change
# as part of approval/install lifecycle. Everything else below the skill root is
# byte-bound, including nested Python, manifests, prompts, templates and assets.
_CONTROL_METADATA = frozenset(
    {
        SIG_FILENAME,
        "PENDING_REVIEW",
        "OWNER_APPROVED_IN_PROCESS",
        "EXTERNAL_SOURCE",
    }
)


class SkillSourceSnapshotError(OSError):
    """The source tree could not be captured as stable regular-file bytes."""


@dataclass(frozen=True)
class SkillSourceFile:
    relative_path: str
    kind: str
    content: bytes


@dataclass(frozen=True)
class SkillSourceSnapshot:
    """Immutable bytes used for both trust validation and external execution."""

    files: tuple[SkillSourceFile, ...]
    fingerprint: str

    @property
    def digest_bytes(self) -> bytes:
        return bytes.fromhex(self.fingerprint.removeprefix("sha256:"))

    def read_bytes(self, relative_path: str) -> bytes | None:
        relative_path = Path(relative_path).as_posix()
        return next(
            (
                item.content
                for item in self.files
                if item.relative_path == relative_path and item.kind == "file"
            ),
            None,
        )


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(reparse and attributes & reparse)
    except OSError:
        return True


def _excluded_source_path(relative_path: Path) -> bool:
    return len(relative_path.parts) == 1 and relative_path.name in _CONTROL_METADATA


def source_snapshot(skill_dir: Path) -> SkillSourceSnapshot:
    """Capture every relevant regular file by relative path, type and bytes.

    Link-like and non-regular artifacts fail closed. Per-file metadata is checked
    before and after reading so the returned bytes are the exact validated input,
    rather than a path that will be reopened later.
    """
    root = Path(skill_dir)
    if _is_link_like(root):
        raise SkillSourceSnapshotError(f"linked skill root refused: {root}")
    try:
        candidates = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    except OSError as exc:
        raise SkillSourceSnapshotError(f"cannot enumerate skill source: {root}") from exc

    files: list[SkillSourceFile] = []
    digest = hashlib.sha256()
    for path in candidates:
        relative = path.relative_to(root)
        if _excluded_source_path(relative):
            if _is_link_like(path):
                raise SkillSourceSnapshotError(
                    f"linked control artifact refused: {relative.as_posix()}"
                )
            try:
                control_stat = path.stat(follow_symlinks=False)
            except OSError as exc:
                raise SkillSourceSnapshotError(
                    f"cannot stat control artifact: {relative.as_posix()}"
                ) from exc
            if not stat.S_ISREG(control_stat.st_mode):
                raise SkillSourceSnapshotError(
                    f"non-regular control artifact refused: {relative.as_posix()}"
                )
            if control_stat.st_nlink != 1:
                raise SkillSourceSnapshotError(
                    f"hardlinked control artifact refused: {relative.as_posix()}"
                )
            continue
        if _is_link_like(path):
            raise SkillSourceSnapshotError(
                f"linked skill artifact refused: {relative.as_posix()}"
            )
        try:
            before = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise SkillSourceSnapshotError(
                f"cannot stat skill artifact: {relative.as_posix()}"
            ) from exc
        if stat.S_ISDIR(before.st_mode):
            continue
        if not stat.S_ISREG(before.st_mode):
            raise SkillSourceSnapshotError(
                f"non-regular skill artifact refused: {relative.as_posix()}"
            )
        try:
            content = path.read_bytes()
            after = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise SkillSourceSnapshotError(
                f"cannot read skill artifact: {relative.as_posix()}"
            ) from exc
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if identity_before != identity_after or len(content) != after.st_size:
            raise SkillSourceSnapshotError(
                f"skill artifact changed while reading: {relative.as_posix()}"
            )

        relative_name = relative.as_posix()
        kind = "file"
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(kind.encode("ascii"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        files.append(SkillSourceFile(relative_name, kind, content))

    fingerprint = f"sha256:{digest.hexdigest()}"
    return SkillSourceSnapshot(tuple(files), fingerprint)


def _source_digest_bytes(skill_dir: Path) -> bytes:
    return source_snapshot(Path(skill_dir)).digest_bytes


def source_fingerprint(skill_dir: Path) -> str:
    """Return a stable byte-binding fingerprint, not an authorship claim."""
    return source_snapshot(Path(skill_dir)).fingerprint


class SkillSigningMisconfigured(RuntimeError):
    """Enforcement is on but no signing key exists — the gate cannot do its job."""


def _signing_key() -> Optional[bytes]:
    key = os.environ.get("JARVIS_SKILL_SIGNING_KEY", "").strip()
    return key.encode("utf-8") if key else None


def compute_digest(
    skill_dir: Path,
    *,
    snapshot: SkillSourceSnapshot | None = None,
) -> tuple[str, str]:
    """Return ``(algo, hexdigest)`` for the skill's source files.

    ``algo`` is ``hmac-sha256`` when a signing key is configured, else ``sha256``.
    """
    content_digest = (
        snapshot.digest_bytes
        if snapshot is not None
        else _source_digest_bytes(Path(skill_dir))
    )

    key = _signing_key()
    if key:
        tag = hmac.new(key, content_digest, hashlib.sha256).hexdigest()
        return ("hmac-sha256", tag)
    return ("sha256", content_digest.hex())


def sign_skill(skill_dir: Path) -> str:
    """Write a ``SKILL.sig`` for the skill and return the signature line."""
    skill_dir = Path(skill_dir)
    snapshot = source_snapshot(skill_dir)
    algo, digest = compute_digest(skill_dir, snapshot=snapshot)
    line = f"{algo}:{digest}"
    sig_file = skill_dir / SIG_FILENAME
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=skill_dir,
            prefix=f".{SIG_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, sig_file)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return line


def verify_skill(
    skill_dir: Path,
    *,
    snapshot: SkillSourceSnapshot | None = None,
) -> tuple[bool, str]:
    """Verify a skill's signature.

    Returns ``(trusted, reason)``. ``trusted`` is True only when a ``SKILL.sig``
    exists and matches the recomputed digest. ``reason`` is a short human label
    suitable for the HUD ("signed", "unsigned", "signature-mismatch",
    "algo-mismatch").
    """
    skill_dir = Path(skill_dir)
    sig_file = skill_dir / SIG_FILENAME
    if not sig_file.exists():
        return (False, "unsigned")

    raw = sig_file.read_text(encoding="utf-8").strip()
    if ":" not in raw:
        return (False, "malformed-signature")
    sig_algo, _, sig_value = raw.partition(":")

    algo, digest = compute_digest(skill_dir, snapshot=snapshot)
    if sig_algo != algo:
        # e.g. sig is hmac but no key configured locally (or vice-versa).
        return (False, "algo-mismatch")
    if not hmac.compare_digest(sig_value.strip(), digest):
        return (False, "signature-mismatch")

    # SEC-B2 / adversarial audit 2026-07-25. An unkeyed digest is not a signature. With
    # no key configured, `compute_digest` returns a plain sha256 of the source files —
    # which an attacker can compute exactly as easily as we can, so they simply ship
    # their own SKILL.sig and the package loads as `trusted`. It detects accidental
    # corruption; it proves nothing about authorship.
    #
    # It stays TRUE-but-labelled rather than becoming False, because at the shipped
    # default (enforcement off) that digest is the only integrity signal there is and
    # turning every bundled skill into "unverified" helps nobody. `require_signed()`
    # below is where an unkeyed digest stops being sufficient.
    if algo != "hmac-sha256":
        return (True, "integrity-only")
    return (True, "signed")


def signing_key_configured() -> bool:
    """Whether a signing key exists — the difference between integrity and authorship.

    Surfaced through ``GET /api/security/posture`` so the distinction is visible rather
    than implicit in the algorithm label.
    """
    return _signing_key() is not None


def signing_posture() -> dict:
    """Read-only view of the signing gate, for status surfaces. Never raises.

    ``require_signed()`` deliberately raises on a misconfiguration, which is right for the
    enforcement path and wrong for an endpoint whose job is to *report* posture — a 500
    tells the owner nothing about why. This says it in words instead, and surfaces the
    distinction the audit's root-cause cluster is named for: whether the digests being
    verified are keyed at all.
    """
    from agents.core.env_config import env_flag
    enforced = env_flag("JARVIS_REQUIRE_SIGNED_SKILLS")
    keyed = signing_key_configured()
    return {
        "require_signed": enforced,
        "signing_key_configured": keyed,
        # The honest headline: enforcement without a key stops honest unsigned content
        # and not an attacker, who simply ships their own SKILL.sig.
        "effective": bool(enforced and keyed),
        "integrity_only": not keyed,
        "misconfigured": bool(enforced and not keyed),
    }


def require_signed() -> bool:
    """Whether unsigned skills must be refused.

    Fails CLOSED: with enforcement on and no key configured, this raises rather than
    returning True. Returning True there was the SEC-B2 finding — the flag would refuse
    honest unsigned content while accepting any signature an attacker chose to compute,
    so an owner who deliberately hardened got a gate that stopped only the people who
    were not attacking them. Refusing to start is the honest response to a security
    control that cannot do its job: it is a misconfiguration, exactly as
    ``hardened.enforce()`` treats a missing audit key.

    Note the audit's own correction, which decides what to fix FIRST: the signature is
    not what grants code execution. At the shipped default a package with no signature at
    all installs and runs identically, because ``loader._load_skill`` executes module
    top-level code. That is the primitive; this is the label on it.
    """
    from agents.core.env_config import env_flag
    enforced = env_flag("JARVIS_REQUIRE_SIGNED_SKILLS")
    if enforced and not signing_key_configured():
        raise SkillSigningMisconfigured(
            "JARVIS_REQUIRE_SIGNED_SKILLS=1 requires JARVIS_SKILL_SIGNING_KEY. Without a "
            "key the 'signature' is a plain sha256 that an attacker can recompute and "
            "ship in their own SKILL.sig, so enforcement blocks honest unsigned skills "
            "and not a deliberate one. Set JARVIS_SKILL_SIGNING_KEY (and re-sign your "
            "skills with sign_skill), or unset JARVIS_REQUIRE_SIGNED_SKILLS."
        )
    return enforced
