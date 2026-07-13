"""Privacy-safe, decay-linked situation memory for H33."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .contracts import AmbientDecision, AmbientEvent, MonitorDefinition

_CAMERA_LABELS = frozenset({"animal", "car", "motion", "package", "person"})
_DIGITAL_SEVERITIES = frozenset({"critical", "info", "warning"})
_RETENTION_SECONDS = 30 * 24 * 60 * 60


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AmbientSituationMemory:
    """Durable anonymous aggregates with linked KG/decay deletion."""

    def __init__(
        self,
        path: str | Path,
        *,
        decay: object,
        kg: object,
        clock: Callable[[], float] = time.time,
        private_house_sink: Callable[[AmbientEvent], object] | None = None,
    ) -> None:
        if not callable(clock):
            raise ValueError("ambient memory clock must be callable")
        if not callable(getattr(decay, "add", None)) or not callable(
            getattr(decay, "forget", None)
        ):
            raise ValueError("ambient decay memory is required")
        if not callable(getattr(kg, "add_fact", None)) or not callable(
            getattr(kg, "invalidate", None)
        ):
            raise ValueError("ambient bi-temporal KG is required")
        if private_house_sink is not None and not callable(private_house_sink):
            raise ValueError("private house owner-store sink must be callable")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._decay = decay
        self._kg = kg
        self._clock = clock
        self._private_house = private_house_sink
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), timeout=5, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS situations (
                situation_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                scope_hash TEXT NOT NULL,
                kind TEXT NOT NULL,
                first_valid_at REAL NOT NULL,
                first_observed_at REAL NOT NULL,
                last_observed_at REAL NOT NULL,
                count INTEGER NOT NULL,
                consent_generation INTEGER NOT NULL,
                provenance_adapter TEXT NOT NULL,
                provenance_version INTEGER NOT NULL,
                contradicted INTEGER NOT NULL DEFAULT 0,
                kg_subject TEXT NOT NULL,
                kg_predicate TEXT NOT NULL,
                kg_object TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_situations_scope
                ON situations(scope_hash, first_valid_at);
            CREATE TABLE IF NOT EXISTS situation_observations (
                event_fingerprint TEXT PRIMARY KEY,
                situation_id TEXT NOT NULL REFERENCES situations(situation_id) ON DELETE CASCADE,
                occurred_at REAL NOT NULL,
                observed_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS situation_tombstones (
                event_fingerprint TEXT PRIMARY KEY,
                purged_at REAL NOT NULL
            );
            """
        )
        self._db.commit()

    def _now(self) -> float:
        value = self._clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError("ambient memory clock returned an invalid timestamp")
        return float(value)

    @staticmethod
    def _projection(event: AmbientEvent) -> tuple[str, str] | None:
        scope = _hash(
            f"{event.source}:{event.schema}:{event.subject_id}:{event.consent_generation}"
        )
        if event.source == "camera":
            label = str(event.attribute("label", "")).strip().lower()
            if event.attribute("anonymous") is not True or label not in _CAMERA_LABELS:
                return None
            return scope, f"anonymous_{label}_observation"
        if event.source == "digital" and event.privacy == "public":
            severity = str(event.attribute("severity", "info")).strip().lower()
            if severity not in _DIGITAL_SEVERITIES:
                severity = "info"
            return scope, f"digital_signal_{severity}"
        return None

    @staticmethod
    def _validate(
        decision: AmbientDecision,
        event: AmbientEvent,
        definition: MonitorDefinition,
    ) -> None:
        if not all(
            (
                isinstance(decision, AmbientDecision),
                isinstance(event, AmbientEvent),
                isinstance(definition, MonitorDefinition),
            )
        ):
            raise ValueError("ambient memory inputs are invalid")
        if (
            decision.rung != "remember"
            or decision.event_fingerprint != event.fingerprint
            or decision.monitor_id != definition.monitor_id
            or decision.monitor_hash != definition.definition_hash
            or definition.source != event.source
        ):
            raise ValueError("ambient memory provenance is invalid")

    def remember(
        self,
        decision: AmbientDecision,
        event: AmbientEvent,
        definition: MonitorDefinition,
    ) -> dict[str, Any]:
        self._validate(decision, event, definition)
        if event.source == "house":
            if self._private_house is not None:
                self._private_house(event)
            return {"status": "delegated", "reason": "private_house_owner_store"}
        projection = self._projection(event)
        if projection is None:
            return {"status": "ignored", "reason": "situation_not_allowlisted"}
        scope_hash, kind = projection
        situation_id = _hash(f"{scope_hash}:{kind}")
        kg_subject = f"ambient:{scope_hash[:24]}"
        consent_root = f"ambient-consent-{event.source}-{event.consent_generation}"
        new_situation = False
        with self._lock:
            db = self._db
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM situation_tombstones WHERE event_fingerprint=?",
                (event.fingerprint,),
            ).fetchone():
                db.commit()
                return {"status": "duplicate", "reason": "consent_replay_tombstone"}
            if db.execute(
                "SELECT 1 FROM situation_observations WHERE event_fingerprint=?",
                (event.fingerprint,),
            ).fetchone():
                db.commit()
                return {"status": "duplicate", "reason": "observation_duplicate"}
            row = db.execute(
                "SELECT count FROM situations WHERE situation_id=?", (situation_id,)
            ).fetchone()
            if row is None:
                db.execute(
                    "UPDATE situations SET contradicted=1 WHERE scope_hash=? AND contradicted=0",
                    (scope_hash,),
                )
                db.execute(
                    """INSERT INTO situations(
                           situation_id, source, scope_hash, kind, first_valid_at,
                           first_observed_at, last_observed_at, count, consent_generation,
                           provenance_adapter, provenance_version, contradicted,
                           kg_subject, kg_predicate, kg_object, expires_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 0, ?, 'situation', ?, ?)""",
                    (
                        situation_id,
                        event.source,
                        scope_hash,
                        kind,
                        event.occurred_at,
                        event.observed_at,
                        event.observed_at,
                        event.consent_generation,
                        event.provenance.adapter,
                        event.provenance.version,
                        kg_subject,
                        kind,
                        event.observed_at + _RETENTION_SECONDS,
                    ),
                )
                new_situation = True
                count = 1
            else:
                count = int(row["count"]) + 1
                db.execute(
                    """UPDATE situations SET count=?, last_observed_at=?, expires_at=?
                       WHERE situation_id=?""",
                    (
                        count,
                        event.observed_at,
                        event.observed_at + _RETENTION_SECONDS,
                        situation_id,
                    ),
                )
            db.execute(
                """INSERT INTO situation_observations(
                       event_fingerprint, situation_id, occurred_at, observed_at
                   ) VALUES(?, ?, ?, ?)""",
                (
                    event.fingerprint,
                    situation_id,
                    event.occurred_at,
                    event.observed_at,
                ),
            )
            db.commit()

        self._decay.add(consent_root, ts=event.observed_at, label="ambient consent root")
        self._decay.add(
            situation_id,
            ts=event.observed_at,
            depends_on=[consent_root],
            label=kind,
        )
        if new_situation:
            self._kg.add_fact(
                kg_subject,
                "situation",
                kind,
                valid_from=event.occurred_at,
                ingested_at=event.observed_at,
            )
        return {
            "status": "remembered",
            "situation_id": situation_id,
            "kind": kind,
            "count": count,
        }

    def list_situations(
        self, *, include_contradicted: bool = False, limit: int = 1_000
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1_000))
        where = "" if include_contradicted else "WHERE contradicted=0"
        with self._lock:
            rows = self._db.execute(
                f"""SELECT situation_id, source, kind, first_valid_at,
                           first_observed_at, last_observed_at, count,
                           consent_generation, provenance_adapter, provenance_version,
                           contradicted
                    FROM situations {where}
                    ORDER BY first_valid_at, situation_id LIMIT ?""",  # nosec B608
                (bounded,),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["contradicted"] = bool(item["contradicted"])
            item["provenance"] = {
                "adapter": item.pop("provenance_adapter"),
                "version": item.pop("provenance_version"),
            }
            output.append(item)
        return output

    def repeated_observations(self, event: AmbientEvent) -> dict[str, Any]:
        projection = self._projection(event)
        if projection is None or event.source != "camera":
            return {
                "kind": "",
                "count": 0,
                "same_individual": False,
                "interpretation": "no anonymous observation aggregate",
            }
        scope_hash, kind = projection
        with self._lock:
            row = self._db.execute(
                """SELECT kind, count, first_observed_at, last_observed_at
                   FROM situations WHERE scope_hash=? AND kind=?""",
                (scope_hash, kind),
            ).fetchone()
        if row is None:
            return {
                "kind": kind,
                "count": 0,
                "same_individual": False,
                "interpretation": "no anonymous observation aggregate",
            }
        return {
            "kind": row["kind"],
            "count": int(row["count"]),
            "first_observed_at": float(row["first_observed_at"]),
            "last_observed_at": float(row["last_observed_at"]),
            "same_individual": False,
            "interpretation": "repeated anonymous observations in one privacy-safe scope",
        }

    def purge(
        self,
        *,
        source: str,
        consent_generation: int,
        purged_at: float | None = None,
    ) -> dict[str, int]:
        timestamp = self._now() if purged_at is None else float(purged_at)
        with self._lock:
            rows = self._db.execute(
                """SELECT situation_id, kg_subject, kg_predicate, kg_object
                   FROM situations WHERE source=? AND consent_generation=?""",
                (source, consent_generation),
            ).fetchall()
            situation_ids = [str(row["situation_id"]) for row in rows]
            fingerprints: list[str] = []
            if situation_ids:
                placeholders = ",".join("?" for _ in situation_ids)
                fingerprints = [
                    str(row["event_fingerprint"])
                    for row in self._db.execute(
                        f"""SELECT event_fingerprint FROM situation_observations
                            WHERE situation_id IN ({placeholders})""",  # nosec B608
                        situation_ids,
                    ).fetchall()
                ]
            self._db.execute("BEGIN IMMEDIATE")
            for fingerprint in fingerprints:
                self._db.execute(
                    """INSERT OR REPLACE INTO situation_tombstones(
                           event_fingerprint, purged_at
                       ) VALUES(?, ?)""",
                    (fingerprint, timestamp),
                )
            self._db.execute(
                "DELETE FROM situations WHERE source=? AND consent_generation=?",
                (source, consent_generation),
            )
            self._db.commit()
        consent_root = f"ambient-consent-{source}-{consent_generation}"
        self._decay.forget(consent_root)
        for row in rows:
            self._kg.invalidate(
                row["kg_subject"], row["kg_predicate"], row["kg_object"], at=timestamp
            )
        return {
            "situations": len(rows),
            "observations": len(fingerprints),
            "tombstones": len(fingerprints),
        }

    def close(self) -> None:
        with self._lock:
            self._db.close()


__all__ = ["AmbientSituationMemory"]
