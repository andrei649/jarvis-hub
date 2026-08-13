"""Canonical private-data roots for Howard ingestion.

The raw Facebook/WhatsApp drop and the derived Howard archive are both private
owner data.  Keeping their relative roots in one module lets export, retention,
and forget share one contract instead of maintaining three partial inventories.
"""

from __future__ import annotations

from pathlib import Path

from agents.core.paths import data_path

INGESTION_IMPORT_ROOT = "ingestion"
INGESTION_ARCHIVE_ROOT = "archive"
PRIVATE_INGESTION_ROOTS: tuple[str, ...] = (
    INGESTION_IMPORT_ROOT,
    INGESTION_ARCHIVE_ROOT,
)


def default_import_root() -> Path:
    """Owner-visible raw import drop below the configured runtime data root."""
    return data_path(INGESTION_IMPORT_ROOT)


def default_archive_root() -> Path:
    """Derived Howard archive below the configured runtime data root."""
    return data_path(INGESTION_ARCHIVE_ROOT)
