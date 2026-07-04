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


def _signing_key() -> Optional[bytes]:
    key = os.environ.get("JARVIS_SKILL_SIGNING_KEY", "").strip()
    return key.encode("utf-8") if key else None


def compute_digest(skill_dir: Path) -> tuple[str, str]:
    """Return ``(algo, hexdigest)`` for the skill's source files.

    ``algo`` is ``hmac-sha256`` when a signing key is configured, else ``sha256``.
    """
    h = hashlib.sha256()
    for name in _SIGNED_FILES:
        fpath = skill_dir / name
        if fpath.exists():
            # Include the filename so reordering/renaming changes the digest.
            h.update(name.encode("utf-8"))
            h.update(b"\0")
            h.update(fpath.read_bytes())
            h.update(b"\0")
    content_digest = h.digest()

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
    if hmac.compare_digest(sig_value.strip(), digest):
        return (True, "signed")
    return (False, "signature-mismatch")


def require_signed() -> bool:
    from agents.core.env_config import env_flag
    return env_flag("JARVIS_REQUIRE_SIGNED_SKILLS")
