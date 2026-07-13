"""Deterministic, side-effect-free reuse resolver and durable outcome metric."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError

from .models import CapabilityRequest, RequestStatus
from .store import CapabilityRequestStore, CapabilityStoreError

_SOURCES = ("registry", "installed", "marketplace")
_EXECUTION_MODES = {"toolrpc", "kernel", "sandbox", "acquired_sandbox"}
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)
_STOP = {
    "need",
    "tool",
    "tools",
    "use",
    "create",
    "build",
    "please",
    "capability",
    "skill",
    "the",
    "this",
    "that",
    "for",
    "with",
    "into",
}


@dataclass(frozen=True, slots=True)
class ReuseCandidate:
    candidate_id: str
    name: str
    source: str
    description: str
    version: str
    enabled: bool = True
    trusted: bool = True
    quarantined: bool = False
    compatible: bool = True
    reviewed: bool = True
    governed: bool = True
    execution_mode: str = "toolrpc"
    requires_install: bool = False

    def __post_init__(self) -> None:
        if self.source not in _SOURCES:
            raise ValueError("unknown reuse source")
        if not self.candidate_id or len(self.candidate_id) > 256:
            raise ValueError("candidate identity must be bounded")
        if not self.name or len(self.name) > 128 or len(self.description) > 2048:
            raise ValueError("candidate metadata must be bounded")
        if len(self.version) > 64 or len(self.execution_mode) > 64:
            raise ValueError("candidate runtime metadata must be bounded")


@dataclass(frozen=True, slots=True)
class ReuseDecision:
    decision_id: str
    request_id: str
    outcome: str
    candidate_id: str | None
    score: float
    provenance: list[str]
    refused_reasons: list[str]
    requires_approval: bool
    at: float


class ReuseDecisionStore:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        clock: Callable[[], float] = time.time,
        max_records: int = 10_000,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.root = Path(root) if root is not None else data_path("acquisition")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "reuse-decisions.enc"
        self._cipher = SecretStore(self.root / "reuse-cipher.json")
        self._clock = clock
        self._max_records = max(1, int(max_records))
        self._max_bytes = max(1024, int(max_bytes))
        self._lock = threading.RLock()
        self._records: list[ReuseDecision] | None = None

    def record(self, decision: ReuseDecision) -> ReuseDecision:
        with self._lock:
            records = self._load()
            if len(records) >= self._max_records:
                raise CapabilityStoreError("reuse decision capacity reached")
            self._commit([*records, decision])
        return decision

    def record_outcome(
        self,
        request_id: str,
        outcome: str,
        *,
        candidate_id: str | None = None,
    ) -> ReuseDecision:
        if outcome not in {"reused", "generated", "blocked", "abandoned"}:
            raise ValueError("unknown terminal acquisition outcome")
        return self.record(
            ReuseDecision(
                decision_id=uuid.uuid4().hex,
                request_id=str(request_id)[:64],
                outcome=outcome,
                candidate_id=str(candidate_id)[:256] if candidate_id else None,
                score=0.0,
                provenance=list(_SOURCES),
                refused_reasons=[],
                requires_approval=False,
                at=float(self._clock()),
            )
        )

    def list(self) -> list[ReuseDecision]:
        with self._lock:
            return list(reversed(self._load()))

    def metrics(self) -> dict[str, int | float]:
        counts: dict[str, int] = dict.fromkeys(
            ("reused", "generated", "blocked", "abandoned"), 0
        )
        seen_requests: set[str] = set()
        for record in self.list():
            if record.request_id in seen_requests:
                continue
            if record.outcome in counts:
                counts[record.outcome] += 1
                seen_requests.add(record.request_id)
        denominator = counts["reused"] + counts["generated"]
        return {
            **counts,
            "reuse_rate": round(counts["reused"] / denominator, 6) if denominator else 0.0,
        }

    def _load(self) -> list[ReuseDecision]:
        if self._records is not None:
            return self._records
        if not self.path.exists():
            self._records = []
            return self._records
        if self.path.is_symlink():
            raise CapabilityStoreError("reuse decision store cannot be a symlink")
        try:
            payload = json.loads(self._cipher.decrypt_bytes(self.path.read_bytes()).decode("utf-8"))
            if payload.get("schema") != 1 or not isinstance(payload.get("decisions"), list):
                raise ValueError("invalid reuse decision schema")
            records = []
            for row in payload["decisions"]:
                records.append(
                    ReuseDecision(
                        decision_id=str(row["decision_id"]),
                        request_id=str(row["request_id"]),
                        outcome=str(row["outcome"]),
                        candidate_id=(str(row["candidate_id"]) if row.get("candidate_id") else None),
                        score=float(row["score"]),
                        provenance=[str(value) for value in row["provenance"]],
                        refused_reasons=[str(value) for value in row["refused_reasons"]],
                        requires_approval=bool(row["requires_approval"]),
                        at=float(row["at"]),
                    )
                )
            if len(records) > self._max_records:
                raise ValueError("reuse decision count exceeds capacity")
        except (OSError, UnicodeError, json.JSONDecodeError, SecretStoreError, ValueError, KeyError) as exc:
            raise CapabilityStoreError("cannot decrypt or validate reuse decisions") from exc
        self._records = records
        return records

    def _commit(self, records: list[ReuseDecision]) -> None:
        raw = json.dumps(
            {"schema": 1, "decisions": [asdict(record) for record in records]},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(raw) > self._max_bytes:
            raise CapabilityStoreError("reuse decision byte capacity reached")
        token = self._cipher.encrypt_bytes(raw)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".reuse-", delete=False) as handle:
                temporary = handle.name
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise CapabilityStoreError("cannot atomically commit reuse decisions") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)
        self._records = records


class ReuseResolver:
    """Search bounded candidates only; research and generation are deliberately absent."""

    def __init__(
        self,
        *,
        decision_store: ReuseDecisionStore | None = None,
        min_score: float = 0.15,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._decisions = decision_store
        self._min_score = max(0.0, min(1.0, float(min_score)))
        self._clock = clock

    def resolve(
        self,
        request: CapabilityRequest,
        candidates: list[ReuseCandidate],
        *,
        request_store: CapabilityRequestStore | None = None,
    ) -> ReuseDecision:
        if len(candidates) > 10_000:
            raise ValueError("reuse candidate set is too large")
        refused: list[str] = []
        selected: tuple[ReuseCandidate, float] | None = None
        for source in _SOURCES:
            ranked: list[tuple[float, str, ReuseCandidate]] = []
            for candidate in candidates:
                if candidate.source != source:
                    continue
                refusal = self._refusal(candidate)
                if refusal:
                    refused.append(refusal)
                    continue
                score = self._score(request.goal, candidate)
                if score >= self._min_score:
                    ranked.append((score, candidate.candidate_id, candidate))
            if ranked:
                score, _candidate_id, candidate = sorted(
                    ranked, key=lambda value: (-value[0], value[1])
                )[0]
                selected = (candidate, score)
                break

        if selected is None:
            outcome = "no_reuse"
            candidate_id = None
            score = 0.0
            approval = False
        else:
            candidate, score = selected
            candidate_id = candidate.candidate_id
            approval = candidate.source == "marketplace" and candidate.requires_install
            outcome = "install_approval_required" if approval else "reused"

        decision = ReuseDecision(
            decision_id=uuid.uuid4().hex,
            request_id=request.request_id,
            outcome=outcome,
            candidate_id=candidate_id,
            score=round(score, 6),
            provenance=list(_SOURCES),
            refused_reasons=sorted(set(refused)),
            requires_approval=approval,
            at=float(self._clock()),
        )
        if self._decisions is not None:
            self._decisions.record(decision)
        if outcome == "reused" and request_store is not None:
            request_store.transition(request.request_id, RequestStatus.REUSED, actor="reuse-resolver")
        return decision

    @staticmethod
    def _refusal(candidate: ReuseCandidate) -> str:
        if not candidate.enabled:
            return "disabled"
        if not candidate.trusted:
            return "untrusted"
        if candidate.quarantined:
            return "quarantined"
        if not candidate.compatible:
            return "incompatible"
        if candidate.source == "marketplace" and not candidate.reviewed:
            return "review_required"
        if not candidate.governed or candidate.execution_mode not in _EXECUTION_MODES:
            return "ungoverned_execution"
        return ""

    @staticmethod
    def _score(goal: str, candidate: ReuseCandidate) -> float:
        goal_normalized = " ".join(goal.casefold().split())
        name_normalized = " ".join(candidate.name.casefold().replace("_", " ").split())
        goal_tokens = {token for token in _TOKEN_RE.findall(goal_normalized) if token not in _STOP}
        candidate_tokens = {
            token
            for token in _TOKEN_RE.findall(f"{name_normalized} {candidate.description.casefold()}")
            if token not in _STOP
        }
        matches = sum(
            1
            for goal_token in goal_tokens
            if any(_tokens_match(goal_token, candidate_token) for candidate_token in candidate_tokens)
        )
        scale = max(len(goal_tokens), len(candidate_tokens))
        semantic = matches / scale if scale else 0.0
        exact = 1.0 if name_normalized and name_normalized in goal_normalized else 0.0
        return min(1.0, exact * 0.7 + semantic * 0.6)


def _tokens_match(left: str, right: str) -> bool:
    if left == right:
        return True
    return len(left) >= 4 and len(right) >= 4 and left[:4] == right[:4]


def collect_reuse_candidates(orch, *, registry_snapshot: dict | None = None) -> list[ReuseCandidate]:
    """Adapt the three existing local inventories without performing any install or I/O hop."""
    candidates: list[ReuseCandidate] = []
    if registry_snapshot is None:
        try:
            from agents.core.observability.capability_registry import snapshot

            registry_snapshot = snapshot(orch)
        except Exception:
            registry_snapshot = {"capabilities": []}
    for row in registry_snapshot.get("capabilities", []):
        if not isinstance(row, dict) or row.get("state") == "missing":
            continue
        capability_id = str(row.get("id", ""))
        if not capability_id:
            continue
        kind = str(row.get("kind", ""))
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        mode = "toolrpc" if kind == "tool" else "kernel" if kind == "action" else str(
            detail.get("execution_mode", "in_process")
        )
        candidates.append(
            ReuseCandidate(
                candidate_id=f"registry:{capability_id}",
                name=capability_id.rsplit(":", 1)[-1],
                source="registry",
                description=str(row.get("description", ""))[:2048],
                version=str(detail.get("version", ""))[:64],
                enabled=row.get("state") in {"wired", "verified", "ga"},
                trusted=detail.get("trusted", True) is True,
                quarantined=detail.get("quarantined", False) is True,
                compatible=detail.get("compatible", True) is True,
                reviewed=True,
                governed=mode in _EXECUTION_MODES,
                execution_mode=mode,
            )
        )

    loader = getattr(orch, "skills", None)
    skills = getattr(loader, "skills", {}) if loader is not None else {}
    for name, skill in sorted(skills.items() if isinstance(skills, dict) else ()):
        manifest = getattr(skill, "manifest", {})
        manifest = manifest if isinstance(manifest, dict) else {}
        mode = str(manifest.get("execution_mode", "in_process"))
        candidates.append(
            ReuseCandidate(
                candidate_id=f"installed:{name}",
                name=str(name),
                source="installed",
                description=str(manifest.get("description", f"Installed skill {name}"))[:2048],
                version=str(manifest.get("version", ""))[:64],
                enabled=getattr(skill, "module", None) is not None,
                trusted=getattr(skill, "trusted", False) is True,
                quarantined=manifest.get("quarantined", False) is True,
                compatible=manifest.get("compatible", True) is True,
                reviewed=True,
                governed=mode in _EXECUTION_MODES,
                execution_mode=mode,
            )
        )

    marketplace = getattr(orch, "marketplace", None)
    list_skills = getattr(marketplace, "list_skills", None) if marketplace is not None else None
    if callable(list_skills):
        try:
            market_rows = list_skills()
        except Exception:
            market_rows = []
        for row in market_rows[:10_000]:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            requires = row.get("requires") if isinstance(row.get("requires"), list) else []
            mode = "sandbox" if "sandbox" in requires else "in_process"
            candidates.append(
                ReuseCandidate(
                    candidate_id=f"marketplace:{name}",
                    name=name,
                    source="marketplace",
                    description=str(row.get("description", ""))[:2048],
                    version=str(row.get("version", ""))[:64],
                    enabled=True,
                    trusted=row.get("signed", False) is True,
                    quarantined=False,
                    compatible=True,
                    reviewed=row.get("review_status") == "approved",
                    governed=mode in _EXECUTION_MODES,
                    execution_mode=mode,
                    requires_install=True,
                )
            )
    return candidates
