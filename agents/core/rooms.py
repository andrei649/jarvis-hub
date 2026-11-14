"""
rooms.py — H10.20 Chat Channels / Rooms + H657 Surviving-Host Failover & Fencing.

Themed chat rooms (per project/context). Each room carries its own context
(injected into every turn) and a roster of agents; inside a room you can
``@mention`` a specific agent to route the turn to it. Routing goes through the
full orchestrator pipeline (tools, RAG, filters) — same as the main chat.

H657 adds monotonic authority epochs, hash-chained verbatim room log pages,
idempotent replica ingestion (refusing sequence gaps, epoch regressions, and
log divergence), explicit-confirm replica promotion at ``epoch + 1`` with an
``authority_claimed`` lineage event, and cryptographic fencing demotion when a
dead owner host comes back after a newer epoch has been claimed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from agents.core.paths import data_path

from .config import ROOM_HISTORY_CAP as _HISTORY_CAP  # Q4: centralized limit
from .persistence import JsonStore

DEFAULT_PATH = data_path("rooms.json")
_MENTION = re.compile(r"@([A-Za-z0-9_\-]+)")
_EVENT_LOG_CAP = max(int(_HISTORY_CAP) * 4, 500)
_GENESIS_DIGEST = "genesis"


class RoomAuthorityError(Exception):
    """Raised when a room write, replication, promotion, or demotion violates authority."""

    def __init__(self, reason: str, status: int = 409, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.status = status
        self.detail = detail or reason


def _default_host_id() -> str:
    for env_name in ("JARVIS_HOST_ID", "JARVIS_DEVICE_ID"):
        val = os.environ.get(env_name, "").strip()
        if val:
            return val[:80]
    try:
        host = socket.gethostname().strip()
        if host:
            return host[:80]
    except OSError:
        pass
    return "local-hub"


def _compute_event_digest(room_id: str, entry: dict[str, Any]) -> str:
    canonical = {
        "room_id": room_id,
        "seq": int(entry["seq"]),
        "epoch": int(entry["epoch"]),
        "host": str(entry.get("host", "")),
        "kind": str(entry.get("kind", "")),
        "role": str(entry.get("role", "")),
        "agent": str(entry.get("agent", "")),
        "text": str(entry.get("text", "")),
        "prev_digest": str(entry.get("prev_digest", _GENESIS_DIGEST)),
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sign_fencing_payload(secret: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


class RoomStore(JsonStore):
    def __init__(
        self,
        path: str | Path = DEFAULT_PATH,
        *,
        host_id: str = "",
        signing_secret: Optional[str] = None,
    ) -> None:
        self.host_id = (host_id or _default_host_id()).strip() or "local-hub"
        env_secret = os.environ.get("JARVIS_ROOM_FENCING_SECRET", "")
        self._signing_secret = signing_secret if signing_secret is not None else env_secret
        super().__init__(path)

    def _serialize(self):
        return self._rooms

    def _deserialize(self, raw) -> None:
        self._rooms = raw if isinstance(raw, dict) else {}
        for room_id, room in list(self._rooms.items()):
            if isinstance(room, dict):
                self._ensure_authority_fields(room_id, room)

    def _ensure_authority_fields(self, room_id: str, room: dict[str, Any]) -> None:
        room.setdefault("id", room_id)
        room.setdefault("name", "room")
        room.setdefault("description", "")
        room.setdefault("agents", [])
        room.setdefault("default_agent", "jarvis")
        room.setdefault("history", [])
        room.setdefault("created_at", time.time())
        room.setdefault("authority_epoch", 1)
        room.setdefault("authority_role", "owner")
        room.setdefault("authority_host", self.host_id)
        room.setdefault("fenced_by", None)
        room.setdefault("base_seq", 0)
        room.setdefault("base_digest", _GENESIS_DIGEST)
        if "event_log" not in room or not isinstance(room["event_log"], list):
            # Backfill hash-chained log from legacy history if present.
            log: list[dict[str, Any]] = []
            prev = _GENESIS_DIGEST
            epoch = int(room.get("authority_epoch", 1))
            host = str(room.get("authority_host") or self.host_id)
            for idx, msg in enumerate(room.get("history", []), start=1):
                entry = {
                    "seq": idx,
                    "epoch": epoch,
                    "host": host,
                    "kind": "message",
                    "role": str(msg.get("role", "user")),
                    "agent": str(msg.get("agent", "")),
                    "text": str(msg.get("text", "")),
                    "ts": float(msg.get("ts", room["created_at"])),
                    "prev_digest": prev,
                }
                entry["digest"] = _compute_event_digest(room_id, entry)
                prev = entry["digest"]
                log.append(entry)
            room["event_log"] = log
        if "lineage" not in room or not isinstance(room["lineage"], list):
            room["lineage"] = [
                {
                    "event": "room_created",
                    "epoch": int(room.get("authority_epoch", 1)),
                    "host": str(room.get("authority_host") or self.host_id),
                    "seq": 0,
                    "ts": float(room["created_at"]),
                }
            ]

    @staticmethod
    def _tail_cursor(room: dict[str, Any]) -> tuple[int, str]:
        log = room.get("event_log") or []
        if log:
            last = log[-1]
            return int(last["seq"]), str(last["digest"])
        return int(room.get("base_seq", 0)), str(room.get("base_digest", _GENESIS_DIGEST))

    def _append_log_entry(
        self,
        room: dict[str, Any],
        *,
        kind: str,
        role: str = "system",
        agent: str = "",
        text: str = "",
        epoch: Optional[int] = None,
        host: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> dict[str, Any]:
        last_seq, last_digest = self._tail_cursor(room)
        now = float(ts if ts is not None else time.time())
        entry: dict[str, Any] = {
            "seq": last_seq + 1,
            "epoch": int(epoch if epoch is not None else room["authority_epoch"]),
            "host": str(host if host is not None else room["authority_host"]),
            "kind": kind,
            "role": role,
            "agent": agent,
            "text": text,
            "ts": now,
            "prev_digest": last_digest,
        }
        entry["digest"] = _compute_event_digest(str(room["id"]), entry)
        room["event_log"].append(entry)
        if len(room["event_log"]) > _EVENT_LOG_CAP:
            overflow = len(room["event_log"]) - _EVENT_LOG_CAP
            dropped = room["event_log"][overflow - 1]
            room["base_seq"] = int(dropped["seq"])
            room["base_digest"] = str(dropped["digest"])
            room["event_log"] = room["event_log"][overflow:]
        return dict(entry)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        description: str = "",
        agents: Optional[list] = None,
        default_agent: str = "jarvis",
        *,
        room_id: Optional[str] = None,
    ) -> dict:
        rid = (room_id or uuid.uuid4().hex[:12]).strip()
        now = time.time()
        room: dict[str, Any] = {
            "id": rid,
            "name": name or "room",
            "description": description or "",
            "agents": list(agents or []),
            "default_agent": default_agent or "jarvis",
            "history": [],
            "created_at": now,
            "authority_epoch": 1,
            "authority_role": "owner",
            "authority_host": self.host_id,
            "fenced_by": None,
            "base_seq": 0,
            "base_digest": _GENESIS_DIGEST,
            "event_log": [],
            "lineage": [
                {
                    "event": "room_created",
                    "epoch": 1,
                    "host": self.host_id,
                    "seq": 0,
                    "ts": now,
                }
            ],
        }
        with self._lock:
            self._rooms[rid] = room
            self._save()
            return self._public(room)

    def get(self, room_id: str) -> Optional[dict]:
        with self._lock:
            room = self._rooms.get(room_id)
            return self._public(room) if room else None

    def list(self) -> list[dict]:
        with self._lock:
            rooms = [self._public(r) for r in self._rooms.values()]
        rooms.sort(key=lambda r: r["created_at"], reverse=True)
        return rooms

    def delete(self, room_id: str) -> bool:
        with self._lock:
            if room_id in self._rooms:
                del self._rooms[room_id]
                self._save()
                return True
            return False

    @classmethod
    def _public(cls, room: dict[str, Any]) -> dict[str, Any]:
        last_seq, _ = cls._tail_cursor(room)
        out = {
            k: v
            for k, v in room.items()
            if k not in {"history", "event_log", "base_seq", "base_digest"}
        }
        out["last_seq"] = last_seq
        return out

    # ── messages ─────────────────────────────────────────────────────────────

    def add_message(self, room_id: str, role: str, text: str, agent: str = "") -> Optional[dict]:
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            self._ensure_authority_fields(room_id, room)
            auth_role = room.get("authority_role", "owner")
            if auth_role == "fenced":
                fenced = room.get("fenced_by") or {}
                raise RoomAuthorityError(
                    "room_fenced",
                    status=409,
                    detail=(
                        f"room {room_id} is fenced by epoch {fenced.get('epoch')} "
                        f"({fenced.get('host', 'remote-host')})"
                    ),
                )
            if auth_role != "owner":
                raise RoomAuthorityError(
                    "room_not_authority",
                    status=409,
                    detail=f"room {room_id} has role={auth_role}; promote replica before writing",
                )
            now = time.time()
            entry = self._append_log_entry(
                room,
                kind="message",
                role=role,
                agent=agent,
                text=text,
                ts=now,
            )
            msg = {
                "role": role,
                "agent": agent,
                "text": text,
                "ts": now,
                "seq": entry["seq"],
                "epoch": entry["epoch"],
            }
            room["history"].append(msg)
            room["history"] = room["history"][-_HISTORY_CAP:]
            self._save()
            return dict(msg)

    def history(self, room_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return []
            return list(room["history"])[-max(1, limit):]

    # ── H657 replication, promotion & fencing ────────────────────────────────

    def export_log_page(
        self,
        room_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> Optional[dict[str, Any]]:
        """Export a bounded verbatim page of hash-chained room log entries."""
        bounded_after = max(0, int(after_seq))
        bounded_limit = max(1, min(int(limit), 500))
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            self._ensure_authority_fields(room_id, room)
            entries = [
                dict(e)
                for e in room["event_log"]
                if int(e["seq"]) > bounded_after
            ][:bounded_limit]
            last_seq, last_digest = self._tail_cursor(room)
            return {
                "room_id": room_id,
                "room_meta": {
                    "name": room["name"],
                    "description": room["description"],
                    "agents": list(room["agents"]),
                    "default_agent": room["default_agent"],
                    "created_at": room["created_at"],
                },
                "authority_epoch": int(room["authority_epoch"]),
                "authority_host": str(room["authority_host"]),
                "authority_role": str(room["authority_role"]),
                "after_seq": bounded_after,
                "entries": entries,
                "last_seq": last_seq,
                "last_digest": last_digest,
            }

    def replica_state(self, room_id: str) -> Optional[dict[str, Any]]:
        """Inspect authority epoch, role, cursor, fencing state, and lineage for a room."""
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            self._ensure_authority_fields(room_id, room)
            last_seq, last_digest = self._tail_cursor(room)
            return {
                "room_id": room_id,
                "name": room["name"],
                "local_host": self.host_id,
                "authority_role": str(room["authority_role"]),
                "authority_epoch": int(room["authority_epoch"]),
                "authority_host": str(room["authority_host"]),
                "last_seq": last_seq,
                "last_digest": last_digest,
                "history_count": len(room["history"]),
                "event_count": len(room["event_log"]),
                "fenced_by": dict(room["fenced_by"]) if isinstance(room.get("fenced_by"), dict) else None,
                "lineage": [dict(item) for item in room.get("lineage", [])],
            }

    def replicate(self, room_id: str, page: dict[str, Any]) -> dict[str, Any]:
        """Ingest a verbatim room log page onto a standby replica (idempotent, gap/epoch-safe)."""
        if not isinstance(page, dict):
            raise RoomAuthorityError("invalid_page", status=400, detail="page must be an object")
        page_room = str(page.get("room_id") or room_id).strip()
        if page_room != room_id:
            raise RoomAuthorityError(
                "room_mismatch",
                status=400,
                detail=f"page room_id {page_room!r} does not match target {room_id!r}",
            )
        raw_entries = page.get("entries")
        if raw_entries is None:
            raw_entries = []
        if not isinstance(raw_entries, list):
            raise RoomAuthorityError("invalid_page", status=400, detail="entries must be a list")

        page_epoch = int(page.get("authority_epoch") or 0)
        page_host = str(page.get("authority_host") or "").strip() or "remote-hub"
        meta = page.get("room_meta") if isinstance(page.get("room_meta"), dict) else {}

        with self._lock:
            room = self._rooms.get(room_id)
            created_replica = False
            if room is None:
                if page_epoch < 1 and not raw_entries:
                    raise RoomAuthorityError(
                        "epoch_regression",
                        status=409,
                        detail="initial replica page must declare authority_epoch >= 1",
                    )
                init_epoch = max(1, page_epoch or int(raw_entries[0].get("epoch", 1)))
                now = float(meta.get("created_at") or time.time())
                room = {
                    "id": room_id,
                    "name": str(meta.get("name") or room_id)[:120],
                    "description": str(meta.get("description") or ""),
                    "agents": list(meta.get("agents") or []),
                    "default_agent": str(meta.get("default_agent") or "jarvis"),
                    "history": [],
                    "created_at": now,
                    "authority_epoch": init_epoch,
                    "authority_role": "replica",
                    "authority_host": page_host,
                    "fenced_by": None,
                    "base_seq": 0,
                    "base_digest": _GENESIS_DIGEST,
                    "event_log": [],
                    "lineage": [
                        {
                            "event": "replica_initialized",
                            "epoch": init_epoch,
                            "host": page_host,
                            "seq": 0,
                            "ts": time.time(),
                        }
                    ],
                }
                created_replica = True
            else:
                self._ensure_authority_fields(room_id, room)

            current_epoch = int(room["authority_epoch"])
            if page_epoch and page_epoch < current_epoch:
                raise RoomAuthorityError(
                    "epoch_regression",
                    status=409,
                    detail=f"page epoch {page_epoch} regresses below local epoch {current_epoch}",
                )
            if room["authority_role"] == "owner" and page_epoch <= current_epoch and raw_entries:
                raise RoomAuthorityError(
                    "room_is_owner",
                    status=409,
                    detail=(
                        f"room {room_id} is owned locally at epoch {current_epoch}; "
                        "cannot overwrite owner log without a higher epoch"
                    ),
                )

            by_seq: dict[int, dict[str, Any]] = {int(e["seq"]): e for e in room["event_log"]}
            last_seq, last_digest = self._tail_cursor(room)
            highest_seen_epoch = current_epoch
            staged: list[dict[str, Any]] = []
            skipped = 0

            for raw in raw_entries:
                if not isinstance(raw, dict):
                    raise RoomAuthorityError("invalid_page", status=400, detail="entry must be an object")
                try:
                    seq = int(raw["seq"])
                    entry_epoch = int(raw["epoch"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise RoomAuthorityError(
                        "invalid_page", status=400, detail="entry missing integer seq/epoch"
                    ) from exc
                if seq < 1:
                    raise RoomAuthorityError("sequence_gap", status=409, detail="seq must be >= 1")
                if entry_epoch < highest_seen_epoch:
                    raise RoomAuthorityError(
                        "epoch_regression",
                        status=409,
                        detail=f"entry seq={seq} epoch={entry_epoch} < current epoch={highest_seen_epoch}",
                    )
                expected_digest = _compute_event_digest(room_id, raw)
                provided_digest = str(raw.get("digest") or "")
                if not provided_digest or not hmac.compare_digest(expected_digest, provided_digest):
                    raise RoomAuthorityError(
                        "log_divergence",
                        status=409,
                        detail=f"entry seq={seq} failed digest verification",
                    )

                if seq <= last_seq:
                    existing = by_seq.get(seq)
                    if existing is not None and not hmac.compare_digest(
                        str(existing["digest"]), provided_digest
                    ):
                        raise RoomAuthorityError(
                            "log_divergence",
                            status=409,
                            detail=f"digest mismatch at already-replicated seq={seq}",
                        )
                    skipped += 1
                    continue

                if seq != last_seq + 1:
                    raise RoomAuthorityError(
                        "sequence_gap",
                        status=409,
                        detail=f"expected seq={last_seq + 1}, received seq={seq}",
                    )
                if str(raw.get("prev_digest") or "") != last_digest:
                    raise RoomAuthorityError(
                        "log_divergence",
                        status=409,
                        detail=f"prev_digest mismatch at seq={seq}",
                    )

                clean_entry = {
                    "seq": seq,
                    "epoch": entry_epoch,
                    "host": str(raw.get("host") or page_host),
                    "kind": str(raw.get("kind") or "message"),
                    "role": str(raw.get("role") or "user"),
                    "agent": str(raw.get("agent") or ""),
                    "text": str(raw.get("text") or ""),
                    "ts": float(raw.get("ts") or time.time()),
                    "prev_digest": last_digest,
                    "digest": provided_digest,
                }
                staged.append(clean_entry)
                by_seq[seq] = clean_entry
                last_seq = seq
                last_digest = provided_digest
                highest_seen_epoch = max(highest_seen_epoch, entry_epoch)

            # Commit atomically now that the entire page validated cleanly.
            if created_replica:
                self._rooms[room_id] = room
            for entry in staged:
                room["event_log"].append(entry)
                if entry["kind"] == "message":
                    room["history"].append(
                        {
                            "role": entry["role"],
                            "agent": entry["agent"],
                            "text": entry["text"],
                            "ts": entry["ts"],
                            "seq": entry["seq"],
                            "epoch": entry["epoch"],
                        }
                    )
                elif entry["kind"] == "authority_claimed":
                    room["lineage"].append(
                        {
                            "event": "authority_claimed",
                            "epoch": entry["epoch"],
                            "host": entry["host"],
                            "seq": entry["seq"],
                            "digest": entry["digest"],
                            "reason": entry["text"],
                            "ts": entry["ts"],
                        }
                    )
            if len(room["history"]) > _HISTORY_CAP:
                room["history"] = room["history"][-_HISTORY_CAP:]
            if len(room["event_log"]) > _EVENT_LOG_CAP:
                overflow = len(room["event_log"]) - _EVENT_LOG_CAP
                dropped = room["event_log"][overflow - 1]
                room["base_seq"] = int(dropped["seq"])
                room["base_digest"] = str(dropped["digest"])
                room["event_log"] = room["event_log"][overflow:]

            target_epoch = max(highest_seen_epoch, page_epoch or highest_seen_epoch)
            if target_epoch > current_epoch and room["authority_role"] == "owner":
                # A returning host ingesting a newer-epoch page transitions out of owner.
                room["authority_role"] = "fenced"
                room["fenced_by"] = {
                    "host": page_host,
                    "epoch": target_epoch,
                    "at": time.time(),
                    "proof_digest": last_digest,
                }
            elif room["authority_role"] != "fenced":
                room["authority_role"] = "replica"
            room["authority_epoch"] = target_epoch
            room["authority_host"] = page_host
            self._save()
            return {
                "ok": True,
                "room_id": room_id,
                "created_replica": created_replica,
                "applied": len(staged),
                "skipped_duplicates": skipped,
                "authority_role": room["authority_role"],
                "authority_epoch": room["authority_epoch"],
                "authority_host": room["authority_host"],
                "last_seq": last_seq,
                "last_digest": last_digest,
            }

    def promote(
        self,
        room_id: str,
        *,
        confirm: bool = False,
        new_host: Optional[str] = None,
        reason: str = "",
    ) -> Optional[dict[str, Any]]:
        """Promote this surviving host to room authority at ``epoch + 1`` (explicit confirm)."""
        if not confirm:
            raise RoomAuthorityError(
                "confirm_required",
                status=409,
                detail="explicit confirm=True is required to promote a room replica",
            )
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            self._ensure_authority_fields(room_id, room)
            prev_epoch = int(room["authority_epoch"])
            prev_host = str(room["authority_host"])
            new_epoch = prev_epoch + 1
            claimed_by = (new_host or self.host_id).strip() or self.host_id
            now = time.time()
            claim_reason = (reason or f"promoted from epoch {prev_epoch} ({prev_host})").strip()[:300]

            room["authority_epoch"] = new_epoch
            room["authority_role"] = "owner"
            room["authority_host"] = claimed_by
            room["fenced_by"] = None

            lineage_entry = self._append_log_entry(
                room,
                kind="authority_claimed",
                role="system",
                agent="",
                text=claim_reason,
                epoch=new_epoch,
                host=claimed_by,
                ts=now,
            )
            lineage_record = {
                "event": "authority_claimed",
                "epoch": new_epoch,
                "prev_epoch": prev_epoch,
                "host": claimed_by,
                "prev_host": prev_host,
                "seq": lineage_entry["seq"],
                "digest": lineage_entry["digest"],
                "reason": claim_reason,
                "ts": now,
            }
            room["lineage"].append(lineage_record)

            proof_payload = {
                "room_id": room_id,
                "epoch": new_epoch,
                "prev_epoch": prev_epoch,
                "claimed_by": claimed_by,
                "seq": lineage_entry["seq"],
                "digest": lineage_entry["digest"],
                "ts": now,
            }
            fencing_proof: dict[str, Any] = {
                **proof_payload,
                "lineage_event": lineage_entry,
            }
            if self._signing_secret:
                fencing_proof["signature"] = _sign_fencing_payload(
                    self._signing_secret, proof_payload
                )

            self._save()
            return {
                "ok": True,
                "room_id": room_id,
                "authority_role": "owner",
                "authority_epoch": new_epoch,
                "prev_epoch": prev_epoch,
                "authority_host": claimed_by,
                "lineage_event": lineage_record,
                "fencing_proof": fencing_proof,
            }

    def demote(self, room_id: str, *, proof: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Fence and demote this host upon cryptographic/lineage proof of a newer epoch."""
        if not isinstance(proof, dict):
            raise RoomAuthorityError("invalid_proof", status=400, detail="proof must be an object")
        if str(proof.get("room_id") or "") != room_id:
            raise RoomAuthorityError(
                "invalid_proof",
                status=400,
                detail="proof room_id does not match target room",
            )
        lineage_event = proof.get("lineage_event")
        if not isinstance(lineage_event, dict) or lineage_event.get("kind") != "authority_claimed":
            raise RoomAuthorityError(
                "invalid_proof",
                status=400,
                detail="proof must carry an authority_claimed lineage_event",
            )
        try:
            proof_epoch = int(proof["epoch"])
            event_epoch = int(lineage_event["epoch"])
            event_seq = int(lineage_event["seq"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RoomAuthorityError(
                "invalid_proof", status=400, detail="proof missing integer epoch/seq"
            ) from exc

        claimed_by = str(proof.get("claimed_by") or lineage_event.get("host") or "").strip()
        if not claimed_by or proof_epoch != event_epoch or str(lineage_event.get("host") or "") != claimed_by:
            raise RoomAuthorityError(
                "invalid_proof",
                status=400,
                detail="proof epoch/claimed_by does not match lineage_event",
            )

        expected_digest = _compute_event_digest(room_id, lineage_event)
        provided_digest = str(lineage_event.get("digest") or "")
        if (
            not provided_digest
            or not hmac.compare_digest(expected_digest, provided_digest)
            or not hmac.compare_digest(str(proof.get("digest") or ""), provided_digest)
        ):
            raise RoomAuthorityError(
                "invalid_proof",
                status=400,
                detail="lineage_event digest verification failed",
            )

        if self._signing_secret:
            sig = str(proof.get("signature") or "")
            proof_payload = {
                "room_id": room_id,
                "epoch": proof_epoch,
                "prev_epoch": int(proof.get("prev_epoch", 0)),
                "claimed_by": claimed_by,
                "seq": event_seq,
                "digest": provided_digest,
                "ts": float(proof.get("ts", lineage_event.get("ts", 0.0))),
            }
            expected_sig = _sign_fencing_payload(self._signing_secret, proof_payload)
            if not sig or not hmac.compare_digest(expected_sig, sig):
                raise RoomAuthorityError(
                    "invalid_proof",
                    status=403,
                    detail="fencing proof HMAC signature invalid",
                )

        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            self._ensure_authority_fields(room_id, room)
            current_epoch = int(room["authority_epoch"])
            if proof_epoch <= current_epoch:
                raise RoomAuthorityError(
                    "not_newer_epoch",
                    status=409,
                    detail=f"proof epoch {proof_epoch} is not newer than local epoch {current_epoch}",
                )
            now = time.time()
            prev_role = str(room["authority_role"])
            room["authority_role"] = "fenced"
            room["authority_epoch"] = proof_epoch
            room["authority_host"] = claimed_by
            room["fenced_by"] = {
                "host": claimed_by,
                "epoch": proof_epoch,
                "seq": event_seq,
                "proof_digest": provided_digest,
                "at": now,
            }
            room["lineage"].append(
                {
                    "event": "fenced_demoted",
                    "epoch": proof_epoch,
                    "prev_epoch": current_epoch,
                    "prev_role": prev_role,
                    "fenced_by_host": claimed_by,
                    "proof_digest": provided_digest,
                    "ts": now,
                }
            )
            self._save()
            return {
                "ok": True,
                "room_id": room_id,
                "authority_role": "fenced",
                "authority_epoch": proof_epoch,
                "prev_epoch": current_epoch,
                "authority_host": claimed_by,
                "fenced_by": dict(room["fenced_by"]),
            }

    # ── routing helpers ──────────────────────────────────────────────────────

    @staticmethod
    def parse_mentions(text: str) -> list[str]:
        """Extract @mentioned agent names in order, de-duplicated."""
        seen, out = set(), []
        for m in _MENTION.findall(text or ""):
            low = m.lower()
            if low not in seen:
                seen.add(low)
                out.append(low)
        return out

    def route(self, room_id: str, text: str) -> Optional[str]:
        """Pick the target agent for a turn: first @mention in the room roster,
        else the room's default agent."""
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            roster = {a.lower() for a in room["agents"]}
            for name in self.parse_mentions(text):
                if not roster or name in roster:
                    return name
            return room["default_agent"]

    def context_for(self, room_id: str) -> str:
        room = self.get(room_id)
        if not room or not room["description"].strip():
            return ""
        return f"[Room: {room['name']}]\n{room['description']}\n\n"
