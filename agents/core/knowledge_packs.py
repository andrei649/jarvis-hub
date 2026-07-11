"""knowledge_packs.py — 0.21 Offline Knowledge Packs (manifest / verify / install-plan).

Kiwix-style *packs* over the H12.2 drop-folder indexer (`local_docs.py`): a knowledge pack is a
folder of supported documents plus a **manifest** with per-file SHA-256 checksums, so a pack can
be shared/moved and verified before it touches memory.

* ``build_manifest`` — fingerprint a pack folder (supported files only, bounded).
* ``verify_pack`` — tamper/completeness check: ``missing`` / ``modified`` / ``unexpected`` are
  each surfaced (never silently passed).
* ``install_pack`` — verify **first**, then index through the injected ``LocalDocsIndexer``;
  a pack that fails verification is refused (nothing partial enters memory).

Honest by construction: no downloads (fetching a pack is an owner-gated step — this manages
packs already on disk), verification failures name every file, and installs report exactly what
the indexer did. Offline; hashing is content-addressed like the 0.37/0.47 provenance ledgers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agents.core.local_docs import SUPPORTED_EXTS

MANIFEST_NAME = "pack.json"
_MAX_FILES = 5000


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _pack_files(root: Path) -> list[Path]:
    files = [p for p in sorted(root.rglob("*"))
             if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]
    return files[:_MAX_FILES]


def build_manifest(folder: str | Path, *, name: str = "", version: str = "0.1.0") -> dict:
    """Fingerprint the pack folder into a manifest (supported files only, bounded).

    Each entry: ``{path, sha256, bytes}`` (paths relative to the pack root, POSIX-style so a
    manifest travels across OSes). Deterministic for identical content.
    """
    root = Path(folder).expanduser()
    if not root.is_dir():
        return {"error": f"not a folder: {folder}"}
    entries = [{
        "path": p.relative_to(root).as_posix(),
        "sha256": _sha256(p),
        "bytes": p.stat().st_size,
    } for p in _pack_files(root)]
    return {
        "name": str(name or root.name),
        "version": str(version),
        "files": entries,
        "count": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
    }


def write_manifest(folder: str | Path, manifest: dict) -> Path:
    """Persist *manifest* as ``pack.json`` inside the pack folder. Returns the path."""
    root = Path(folder).expanduser()
    out = root / MANIFEST_NAME
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def load_manifest(folder: str | Path) -> dict | None:
    """Read ``pack.json`` from the pack folder; None if absent/corrupt (caller decides)."""
    p = Path(folder).expanduser() / MANIFEST_NAME
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (ValueError, OSError):
        return None


def verify_pack(folder: str | Path, manifest: dict) -> dict:
    """Check the pack folder against *manifest*.

    Returns ``{ok, missing, modified, unexpected, checked}`` — every discrepancy is named:
    ``missing`` (in manifest, not on disk), ``modified`` (hash mismatch), ``unexpected``
    (supported file on disk that the manifest doesn't know). ``ok`` only when all three are empty.
    """
    root = Path(folder).expanduser()
    m = manifest if isinstance(manifest, dict) else {}
    wanted = {e.get("path"): e.get("sha256") for e in (m.get("files") or [])
              if isinstance(e, dict) and e.get("path")}
    missing: list[str] = []
    modified: list[str] = []
    for rel, digest in wanted.items():
        p = root / rel
        if not p.is_file():
            missing.append(rel)
        elif _sha256(p) != digest:
            modified.append(rel)
    on_disk = {p.relative_to(root).as_posix() for p in _pack_files(root)}
    unexpected = sorted(on_disk - set(wanted))
    return {"ok": not (missing or modified or unexpected),
            "missing": missing, "modified": modified,
            "unexpected": unexpected, "checked": len(wanted)}


async def install_pack(folder: str | Path, indexer, *, manifest: dict | None = None) -> dict:
    """Verify the pack, then index it into memory through *indexer* (a ``LocalDocsIndexer``).

    Refuses to index anything when verification fails (``installed: False`` + the named
    discrepancies) — a tampered or incomplete pack never partially enters memory. With no
    manifest on disk or passed in, refuses too (a pack without a manifest is just a folder —
    use the plain drop-folder indexer for that, deliberately).
    """
    m = manifest or load_manifest(folder)
    if not m:
        return {"installed": False, "reason": "no_manifest",
                "hint": "build_manifest()+write_manifest() first, or use the drop-folder indexer"}
    check = verify_pack(folder, m)
    if not check["ok"]:
        return {"installed": False, "reason": "verification_failed", "verify": check}
    result = await indexer.index(folder)
    return {"installed": "error" not in result, "pack": m.get("name"),
            "version": m.get("version"), "verify": check, "index": result}
