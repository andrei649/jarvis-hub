"""
anchor.py — H17.4 Externally-anchored audit + intent attribution.

Extends the existing Merkle audit chain (H4.10, `audit.py`) along three axes:

* **Signed identity per action** — every action record is HMAC-signed with the
  system identity key, so an entry can't be forged or silently edited.
* **Causal intent attribution** — each record carries *why* the agent did it
  (the triggering cause), not just *what* it did.
* **External anchoring** — the audit chain's head hash is periodically anchored
  into an append-only, hash-linked transparency log, so tampering with history is
  detectable against an independent record.

Offline + deterministic: keys/paths are injectable; the "external" transparency
log is a local append-only file standing in for a public log.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from ..persistence import JsonStore

logger = logging.getLogger(__name__)

INTENT_PATH = data_path("security/intent_log.json")
ANCHOR_PATH = data_path("security/transparency_log.json")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class IntentLog(JsonStore):
    """Hash-chained, HMAC-signed action records with causal intent attribution."""

    def __init__(self, path: str | Path = INTENT_PATH, secret_key: Optional[str] = None) -> None:
        super().__init__(path)
        # The signing key must be STABLE across restarts, else past entries can't
        # verify. Priority: explicit arg → env → a persisted per-install key file.
        self._key = self._resolve_key(secret_key)

    def _serialize(self):
        return self._entries

    def _deserialize(self, raw) -> None:
        self._entries = raw if isinstance(raw, list) else []

    def _resolve_key(self, secret_key: Optional[str]) -> bytes:
        if secret_key:
            return secret_key.encode("utf-8")
        env = os.environ.get("JARVIS_AUDIT_KEY")
        if env:
            return env.encode("utf-8")
        # Prefer a key stored OUTSIDE the audit-log directory: write access to the
        # log tree alone must not also hand over the signing key (HF-5). Order:
        #   1. an existing key in the secure dir (JARVIS_KEY_DIR, else ~/.config/jarvis)
        #   2. a legacy co-located key (<log>.key) — honoured for existing installs,
        #      with a warning to migrate
        #   3. a fresh key in the secure dir; only if that dir is unwritable do we
        #      fall back to co-locating it (so the chain always stays verifiable)
        name = self.path.stem  # e.g. 'intent_log'
        secure_dir = Path(os.environ.get("JARVIS_KEY_DIR") or (Path.home() / ".config" / "jarvis"))
        secure_path = secure_dir / f"{name}.key"
        legacy_path = self.path.with_suffix(".key")
        try:
            if secure_path.exists():
                return secure_path.read_text(encoding="utf-8").strip().encode("utf-8")
            if legacy_path.exists():
                logger.warning(
                    "Audit signing key is co-located with the log (%s). Set "
                    "JARVIS_AUDIT_KEY, or move it under %s, so write access to the "
                    "log dir alone can't forge the chain (HF-5).", legacy_path, secure_dir,
                )
                return legacy_path.read_text(encoding="utf-8").strip().encode("utf-8")
            key = secrets.token_hex(32)
            try:
                secure_dir.mkdir(parents=True, exist_ok=True)
                secure_path.write_text(key, encoding="utf-8")
                try:
                    secure_path.chmod(0o600)
                except Exception:
                    # chmod is best-effort (no-op on non-POSIX FS); the key is
                    # already written and usable regardless.
                    pass
                return key.encode("utf-8")
            except Exception:
                # Secure dir unwritable → keep the old behaviour (key next to the
                # log) so auditing still works, but make the weaker posture explicit.
                legacy_path.parent.mkdir(parents=True, exist_ok=True)
                legacy_path.write_text(key, encoding="utf-8")
                try:
                    legacy_path.chmod(0o600)
                except Exception:
                    # chmod is best-effort (no-op on non-POSIX FS); the key is
                    # already written and usable regardless.
                    pass
                logger.warning(
                    "Could not write the audit key to the secure dir (%s); stored it "
                    "next to the log (%s). Set JARVIS_AUDIT_KEY to harden (HF-5).",
                    secure_dir, legacy_path,
                )
                return key.encode("utf-8")
        except Exception:
            return secrets.token_hex(32).encode("utf-8")

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._save()


    def _sign(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def record(self, actor: str, action: str, why: str,
               cause: str = "", metadata: Optional[dict] = None,
               ts: Optional[float] = None) -> dict:
        """Append a signed action record. `why`/`cause` = intent attribution."""
        ts = time.time() if ts is None else float(ts)
        with self._lock:
            prev_hash = self._entries[-1]["entry_hash"] if self._entries else ""
            seq = len(self._entries) + 1
            body = f"{prev_hash}|{ts}|{actor}|{action}|{why}|{cause}"
            entry_hash = _sha(body)
            entry = {
                "seq": seq, "ts": ts, "actor": actor, "action": action,
                "why": why, "cause": cause, "metadata": metadata or {},
                "prev_hash": prev_hash, "entry_hash": entry_hash,
                "signature": self._sign(entry_hash),
            }
            self._entries.append(entry)
            self._save()
            return dict(entry)

    def head(self) -> str:
        with self._lock:
            return self._entries[-1]["entry_hash"] if self._entries else ""

    def verify(self) -> dict:
        """Verify the hash chain AND every signature. Returns {ok, bad_seq, n}."""
        with self._lock:
            entries = list(self._entries)
        prev = ""
        for e in entries:
            body = f"{prev}|{e['ts']}|{e['actor']}|{e['action']}|{e['why']}|{e['cause']}"
            if _sha(body) != e["entry_hash"]:
                return {"ok": False, "bad_seq": e["seq"], "reason": "hash", "n": len(entries)}
            if not hmac.compare_digest(self._sign(e["entry_hash"]), e["signature"]):
                return {"ok": False, "bad_seq": e["seq"], "reason": "signature", "n": len(entries)}
            prev = e["entry_hash"]
        return {"ok": True, "bad_seq": None, "n": len(entries)}

    def list(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._entries[-max(1, limit):]][::-1]


class TransparencyAnchor(JsonStore):
    """Append-only, hash-linked external anchor log (stands in for a public log)."""

    def __init__(self, path: str | Path = ANCHOR_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return self._anchors

    def _deserialize(self, raw) -> None:
        self._anchors = raw if isinstance(raw, list) else []


    def anchor(self, root_hash: str, source: str = "audit", ts: Optional[float] = None) -> dict:
        """Anchor a chain head/root hash; returns the (hash-linked) receipt."""
        ts = time.time() if ts is None else float(ts)
        with self._lock:
            prev = self._anchors[-1]["anchor_hash"] if self._anchors else ""
            seq = len(self._anchors) + 1
            anchor_hash = _sha(f"{prev}|{ts}|{source}|{root_hash}")
            receipt = {"seq": seq, "ts": ts, "source": source, "root": root_hash,
                       "prev_anchor_hash": prev, "anchor_hash": anchor_hash}
            self._anchors.append(receipt)
            self._save()
            return dict(receipt)

    def latest(self) -> Optional[dict]:
        with self._lock:
            return dict(self._anchors[-1]) if self._anchors else None

    def verify(self) -> dict:
        """Verify the anchor log is an unbroken hash chain."""
        with self._lock:
            anchors = list(self._anchors)
        prev = ""
        for a in anchors:
            if _sha(f"{prev}|{a['ts']}|{a['source']}|{a['root']}") != a["anchor_hash"]:
                return {"ok": False, "bad_seq": a["seq"], "n": len(anchors)}
            prev = a["anchor_hash"]
        return {"ok": True, "bad_seq": None, "n": len(anchors)}

    def list(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return [dict(a) for a in self._anchors[-max(1, limit):]][::-1]

    def clear(self) -> None:
        with self._lock:
            self._anchors.clear()
            self._save()
