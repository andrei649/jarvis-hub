"""Canonical private-data roots for Howard ingestion.

The raw Facebook/WhatsApp drop and the derived Howard archive are both private
owner data. Keeping their relative roots in one module lets export, retention,
and forget share one contract instead of maintaining three partial inventories.
It also detects the pre-G35 repo-local ``data/`` default: unresolved legacy data
stays discoverable but makes lifecycle completeness fail visibly until the owner
migrates or removes it.
"""

from __future__ import annotations

from pathlib import Path

from agents.core.paths import app_root, data_path

INGESTION_IMPORT_ROOT = "ingestion"
INGESTION_ARCHIVE_ROOT = "archive"
PRIVATE_INGESTION_ROOTS: tuple[str, ...] = (
    INGESTION_IMPORT_ROOT,
    INGESTION_ARCHIVE_ROOT,
)


def legacy_import_root() -> Path:
    """Return the pre-G35 repo-local default used by shipped installations."""
    return app_root() / "data"


def legacy_import_status() -> dict[str, object]:
    """Describe unresolved private imports at the pre-G35 default.

    The old watcher resolved ``Path("data")`` from the checkout. We never move,
    export, retain, or erase that owner data implicitly because it is outside the
    configured runtime-data authority. A non-empty legacy root instead remains
    visible to the watcher and makes lifecycle operations report incomplete
    until the owner explicitly migrates or removes it.
    """
    root = legacy_import_root()
    detected = root.is_symlink() or root.is_file()
    if root.is_dir() and not root.is_symlink():
        try:
            for source in (root / "facebook", root / "whatsapp"):
                if source.is_symlink() or source.is_file():
                    detected = True
                    break
                if source.is_dir() and any(
                    item.is_file() or item.is_symlink() for item in source.rglob("*")
                ):
                    detected = True
                    break
        except OSError:
            # An unreadable old root is unresolved private data, never absence.
            detected = True
    return {
        "detected": detected,
        "path": str(root),
        "reason": (
            "legacy_repo_local_imports_require_owner_resolution" if detected else None
        ),
    }


def default_import_root() -> Path:
    """Return the canonical raw drop, preserving unresolved legacy discovery."""
    legacy = legacy_import_status()
    legacy_root = Path(str(legacy["path"]))
    if legacy["detected"] and legacy_root.is_dir() and not legacy_root.is_symlink():
        return legacy_root
    return data_path(INGESTION_IMPORT_ROOT)


def default_archive_root() -> Path:
    """Derived Howard archive below the configured runtime data root."""
    return data_path(INGESTION_ARCHIVE_ROOT)
