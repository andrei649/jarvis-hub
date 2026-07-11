"""vault.py — 0.20 Jarvis Vault (encrypted personal blob vault + retention controls).

The missing data-management flagship: a **local, encrypted-at-rest vault** for the user's
private blobs (documents, exports, credentials backups — whatever must outlive a session but
never sit on disk in plaintext). The adjacent pieces already shipped (backup #302, at-rest
encryption AUD-1, export #303, forget AUD-2); this is the store itself.

Built on ``agents.core.secrets.SecretStore``'s cipher (Fernet when ``cryptography`` is
present, the authenticated pure-Python fallback otherwise; same ``JARVIS_SECRET_KEY`` /
keyfile discipline, 0600). Design rules:

* **Encrypted at rest, always** — blobs land on disk only as ciphertext; there is no
  plaintext mode to misconfigure.
* **Bounded** — byte + item quotas; a put that would exceed them is refused (never a silent
  eviction of the user's vault — a vault is not a cache).
* **Retention controls** — per-item optional ``expires_at``; ``sweep(now)`` removes expired
  items and reports exactly what it removed (H23.10-style, injectable clock — deterministic).
* **Forget-me ready** — ``clear_memory()`` (in-memory only, backup-first friendly) and
  ``purge()`` (at-rest erase) mirror the canvas/purge discipline.
* **Honest** — reads verify integrity (a tampered blob raises, never returns garbage);
  the index never stores plaintext content, only metadata.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from pathlib import Path

# one import style for both `secrets` modules (stdlib + agents.core) — the mixed
# import/import-from pair trips CodeQL's module-shadowing check
from secrets import token_urlsafe as _token_urlsafe

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError

DEFAULT_DIR = data_path("vault")

_MAX_ITEMS = 10_000
_MAX_TOTAL_BYTES = 1 << 40          # 1 TB — the roadmap's stated ceiling
_MAX_ITEM_BYTES = 1 << 30           # 1 GB per item


class VaultError(Exception):
    """Refused vault operation (quota, integrity, missing item)."""


class Vault:
    """Encrypted personal blob vault with quotas and retention."""

    def __init__(self, root: str | Path | None = None, *, key: str | None = None,
                 max_items: int = _MAX_ITEMS, max_total_bytes: int = _MAX_TOTAL_BYTES,
                 max_item_bytes: int = _MAX_ITEM_BYTES) -> None:
        self.root = Path(root) if root else DEFAULT_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        # Reuse the SecretStore key discipline; the store file anchors key/salt paths.
        self._cipher = SecretStore(self.root / "vault.keys", key=key)
        self._index_path = self.root / "index.json"
        self._lock = threading.Lock()
        self.max_items = int(max_items)
        self.max_total_bytes = int(max_total_bytes)
        self.max_item_bytes = int(max_item_bytes)
        self._index: dict[str, dict] = self._load_index()

    # ── index persistence (metadata only — never plaintext content) ─────────
    def _load_index(self) -> dict:
        if not self._index_path.exists():
            return {}
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (ValueError, OSError):
            return {}

    def _save_index(self) -> None:
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._index, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self._index_path)

    def _blob_path(self, vid: str) -> Path:
        return self.root / f"{vid}.blob"

    # ── core API ─────────────────────────────────────────────────────────────
    def put(self, data: bytes, *, name: str = "", kind: str = "blob",
            now: float = 0.0, expires_at: float | None = None) -> dict:
        """Encrypt + store *data*. Refuses (VaultError) on quota breach — never evicts.

        ``now`` is the injectable clock (epoch seconds) recorded as ``created_at``;
        ``expires_at`` opts the item into the retention sweep.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise VaultError("vault stores bytes")
        size = len(data)
        if size > self.max_item_bytes:
            raise VaultError(f"item exceeds per-item cap ({size} > {self.max_item_bytes})")
        with self._lock:
            if len(self._index) >= self.max_items:
                raise VaultError(f"vault item cap reached ({self.max_items})")
            used = sum(e.get("bytes", 0) for e in self._index.values())
            if used + size > self.max_total_bytes:
                raise VaultError("vault byte quota reached")
            vid = _token_urlsafe(12)
            token = self._cipher._encrypt(base64.b64encode(bytes(data)).decode("ascii"))
            self._blob_path(vid).write_text(token, encoding="ascii")
            entry = {
                "id": vid,
                "name": str(name or "")[:200],
                "kind": str(kind or "blob")[:40],
                "bytes": size,
                "sha256": hashlib.sha256(bytes(data)).hexdigest(),
                "created_at": float(now),
                "expires_at": float(expires_at) if expires_at is not None else None,
            }
            self._index[vid] = entry
            self._save_index()
            return dict(entry)

    def get(self, vid: str) -> bytes:
        """Decrypt + return a blob; integrity is verified (tampered → VaultError)."""
        entry = self._index.get(vid)
        if entry is None:
            raise VaultError(f"no such vault item: {vid}")
        p = self._blob_path(vid)
        if not p.exists():
            raise VaultError(f"vault blob missing on disk: {vid}")
        try:
            plain_b64 = self._cipher._decrypt(p.read_text(encoding="ascii"))
        except SecretStoreError as e:
            raise VaultError(f"cannot decrypt vault item {vid}: {e}") from e
        data = base64.b64decode(plain_b64.encode("ascii"))
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            raise VaultError(f"vault item {vid} failed integrity check")
        return data

    def list(self) -> list[dict]:
        """Metadata for every item (never content), newest first."""
        return sorted((dict(e) for e in self._index.values()),
                      key=lambda e: -float(e.get("created_at") or 0))

    def remove(self, vid: str) -> bool:
        with self._lock:
            entry = self._index.pop(vid, None)
            if entry is None:
                return False
            self._blob_path(vid).unlink(missing_ok=True)
            self._save_index()
            return True

    def stats(self) -> dict:
        used = sum(e.get("bytes", 0) for e in self._index.values())
        return {"items": len(self._index), "bytes": used,
                "max_items": self.max_items, "max_bytes": self.max_total_bytes}

    # ── retention (H23.10 discipline: sweep is explicit + reported) ─────────
    def sweep(self, now: float) -> dict:
        """Remove every item whose ``expires_at`` <= *now*. Reports exactly what went."""
        with self._lock:
            expired = [vid for vid, e in self._index.items()
                       if e.get("expires_at") is not None and e["expires_at"] <= now]
            for vid in expired:
                self._index.pop(vid, None)
                self._blob_path(vid).unlink(missing_ok=True)
            if expired:
                self._save_index()
        return {"removed": expired, "count": len(expired)}

    # ── forget-me integration (mirrors the canvas/purge discipline) ─────────
    def clear_memory(self) -> None:
        """Drop the in-memory index WITHOUT touching disk (pre-backup live-clear)."""
        self._index = {}

    def purge(self) -> int:
        """Erase the vault at rest: every blob + the index. Returns items removed."""
        with self._lock:
            n = len(self._index)
            for vid in list(self._index):
                self._blob_path(vid).unlink(missing_ok=True)
            self._index = {}
            self._save_index()
            return n
