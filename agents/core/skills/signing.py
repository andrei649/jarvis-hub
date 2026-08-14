"""
signing.py — Skill signature verification (H12.1, anti-ClawHub).

A skill pack is "signed" by shipping a ``SKILL.sig`` file next to ``SKILL.md``.
The signature is a deterministic content hash over the skill's source files
(SKILL.md + main.py), optionally HMAC-keyed when a project signing key is set.

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
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.skills.signing")

# Files that contribute to a skill's signature, in a stable order.
_SIGNED_FILES = ("SKILL.md", "main.py")
SIG_FILENAME = "SKILL.sig"


def _source_digest_bytes(skill_dir: Path) -> bytes:
    digest = hashlib.sha256()
    for name in _SIGNED_FILES:
        path = Path(skill_dir) / name
        if path.exists():
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.digest()


def source_fingerprint(skill_dir: Path) -> str:
    """Return a stable byte-binding fingerprint, not an authorship claim."""
    return f"sha256:{_source_digest_bytes(Path(skill_dir)).hex()}"


class SkillSigningMisconfigured(RuntimeError):
    """Enforcement is on but no signing key exists — the gate cannot do its job."""


def _signing_key() -> Optional[bytes]:
    key = os.environ.get("JARVIS_SKILL_SIGNING_KEY", "").strip()
    return key.encode("utf-8") if key else None


def compute_digest(skill_dir: Path) -> tuple[str, str]:
    """Return ``(algo, hexdigest)`` for the skill's source files.

    ``algo`` is ``hmac-sha256`` when a signing key is configured, else ``sha256``.
    """
    content_digest = _source_digest_bytes(Path(skill_dir))

    key = _signing_key()
    if key:
        tag = hmac.new(key, content_digest, hashlib.sha256).hexdigest()
        return ("hmac-sha256", tag)
    return ("sha256", content_digest.hex())


def sign_skill(skill_dir: Path) -> str:
    """Write a ``SKILL.sig`` for the skill and return the signature line."""
    algo, digest = compute_digest(Path(skill_dir))
    line = f"{algo}:{digest}"
    (Path(skill_dir) / SIG_FILENAME).write_text(line + "\n", encoding="utf-8")
    return line


def verify_skill(skill_dir: Path) -> tuple[bool, str]:
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

    algo, digest = compute_digest(skill_dir)
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
