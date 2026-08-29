"""Named execution-target policy and tamper-evident authorization audit.

This module is a policy plane only. It never launches a subprocess, container, or SSH
connection and deliberately accepts no command or payload content. The transport
that consumes its decisions lives beside it in ``execution.py`` (GAP-9).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ALLOW = "allow"
APPROVAL_REQUIRED = "approval_required"
DENY = "deny"
OUTCOMES = frozenset({ALLOW, APPROVAL_REQUIRED, DENY})
GENESIS_HASH = "0" * 64
MAX_AUDIT_FILE_BYTES = 10_000_000
MAX_AUDIT_LINE_BYTES = 64_000

_TARGET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_AUDIT_FIELDS = frozenset({
    "sequence",
    "timestamp",
    "target",
    "backend",
    "agent",
    "capability",
    "correlation_id",
    "outcome",
    "reason",
    "previous_hash",
    "entry_hash",
})


class TargetAuditCorrupt(RuntimeError):
    """A persisted target audit cannot be trusted or safely extended."""


@dataclass(frozen=True)
class TerminalTarget:
    name: str
    backend: str
    enabled: bool
    allowed_agents: frozenset[str]
    capabilities: frozenset[str]
    approval_required: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        from agents.core.environments import backend_profiles

        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if any(isinstance(value, (str, bytes)) for value in (
            self.allowed_agents, self.capabilities, self.approval_required
        )):
            raise ValueError("agent and capability policies must be collections")
        name = str(self.name or "").strip()
        backend = str(self.backend or "").strip()
        agents = frozenset(str(item or "").strip() for item in self.allowed_agents)
        capabilities = frozenset(str(item or "").strip() for item in self.capabilities)
        approvals = frozenset(str(item or "").strip() for item in self.approval_required)
        valid_backends = {profile.name for profile in backend_profiles()}

        if _TARGET_RE.fullmatch(name) is None:
            raise ValueError("target name must be a safe 1-64 character token")
        if backend not in valid_backends:
            raise ValueError(f"backend must be one of {sorted(valid_backends)}")
        if not agents or any(item != "*" and _TOKEN_RE.fullmatch(item) is None for item in agents):
            raise ValueError("allowed_agents must contain safe agent tokens")
        if not capabilities or any(_TOKEN_RE.fullmatch(item) is None for item in capabilities):
            raise ValueError("capabilities must contain safe capability tokens")
        if any(_TOKEN_RE.fullmatch(item) is None for item in approvals):
            raise ValueError("approval_required must contain safe capability tokens")
        if not approvals.issubset(capabilities):
            raise ValueError("approval_required must be a subset of capabilities")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "allowed_agents", agents)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "approval_required", approvals)


@dataclass(frozen=True)
class TargetDecision:
    target: str
    backend: str | None
    agent: str
    capability: str
    outcome: str
    reason: str
    correlation_id: str | None = None

    @property
    def requires_approval(self) -> bool:
        return self.outcome == APPROVAL_REQUIRED


class TargetAuditChain:
    """Thread-safe SHA-256 chain with optional durable JSONL append."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        max_file_bytes: int = MAX_AUDIT_FILE_BYTES,
        max_line_bytes: int = MAX_AUDIT_LINE_BYTES,
    ) -> None:
        if type(max_file_bytes) is not int or max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be a positive integer")
        if type(max_line_bytes) is not int or max_line_bytes <= 0:
            raise ValueError("max_line_bytes must be a positive integer")
        self.path = Path(path).expanduser().resolve() if path else None
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_file_bytes = max_file_bytes
        self._max_line_bytes = max_line_bytes
        self._lock = threading.RLock()
        self._entries: list[dict] = []
        if self.path is not None and self.path.exists():
            self._load()

    @property
    def entries(self) -> list[dict]:
        """Return a detached snapshot so callers cannot mutate the live chain."""
        with self._lock:
            return [dict(entry) for entry in self._entries]

    def append(self, decision: TargetDecision) -> dict:
        if decision.outcome not in OUTCOMES:
            raise ValueError("invalid target audit outcome")
        with self._lock:
            previous_hash = self._entries[-1]["entry_hash"] if self._entries else GENESIS_HASH
            timestamp = self._clock()
            if not isinstance(timestamp, datetime):
                raise ValueError("target audit clock must return datetime")
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            record = {
                "sequence": len(self._entries) + 1,
                "timestamp": timestamp.astimezone(UTC).isoformat(),
                "target": decision.target,
                "backend": decision.backend,
                "agent": decision.agent,
                "capability": decision.capability,
                "correlation_id": decision.correlation_id,
                "outcome": decision.outcome,
                "reason": decision.reason,
                "previous_hash": previous_hash,
            }
            record["entry_hash"] = self._hash_record(record)
            encoded = json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            encoded_bytes = len((encoded + "\n").encode("utf-8"))
            if encoded_bytes > self._max_line_bytes:
                raise ValueError("target audit record exceeds line budget")
            if self.path is not None:
                current_size = self.path.stat().st_size if self.path.exists() else 0
                if current_size + encoded_bytes > self._max_file_bytes:
                    raise ValueError("target audit file exceeds configured size budget")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(encoded + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            self._entries.append(record)
            return dict(record)

    def verify_chain(self, entries: Iterable[dict] | None = None) -> bool:
        with self._lock:
            snapshot = list(entries) if entries is not None else self._entries
            previous_hash = GENESIS_HASH
            for sequence, record in enumerate(snapshot, start=1):
                if not isinstance(record, dict) or set(record) != _AUDIT_FIELDS:
                    return False
                if record.get("sequence") != sequence:
                    return False
                if record.get("previous_hash") != previous_hash:
                    return False
                if record.get("outcome") not in OUTCOMES:
                    return False
                if record.get("entry_hash") != self._hash_record(record):
                    return False
                previous_hash = record["entry_hash"]
            return True

    def _load(self) -> None:
        try:
            if self.path is None or self.path.stat().st_size > self._max_file_bytes:
                raise TargetAuditCorrupt("target audit is missing or exceeds its size budget")
            entries = []
            with self.path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if len(line.encode("utf-8")) > self._max_line_bytes:
                        raise TargetAuditCorrupt("target audit line exceeds its size budget")
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise TargetAuditCorrupt("target audit record is not an object")
                    entries.append(record)
            self._entries = entries
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TargetAuditCorrupt("target audit cannot be parsed") from exc
        if not self.verify_chain():
            raise TargetAuditCorrupt("target audit hash chain is invalid")

    @staticmethod
    def _hash_record(record: dict) -> str:
        payload = {key: value for key, value in record.items() if key != "entry_hash"}
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(
            (str(payload.get("previous_hash", "")) + canonical).encode("utf-8")
        ).hexdigest()


class TargetRegistry:
    """Named target inventory with per-agent/capability authorization."""

    def __init__(
        self,
        targets: Iterable[TerminalTarget] = (),
        *,
        audit: TargetAuditChain | None = None,
    ) -> None:
        self.audit = audit or TargetAuditChain()
        self._targets: dict[str, TerminalTarget] = {}
        self._lock = threading.RLock()
        for target in targets:
            self.register(target)

    def register(self, target: TerminalTarget) -> None:
        if not isinstance(target, TerminalTarget):
            raise ValueError("target must be TerminalTarget")
        with self._lock:
            if target.name in self._targets:
                raise ValueError(f"duplicate target: {target.name}")
            self._targets[target.name] = target

    def authorize(
        self,
        target: str,
        agent: str,
        capability: str,
        *,
        correlation_id: str | None = None,
    ) -> TargetDecision:
        target_name = self._safe_target(target)
        agent_name = self._safe_token(agent, "agent")
        capability_name = self._safe_token(capability, "capability")
        correlation = (
            self._safe_token(correlation_id, "correlation_id")
            if correlation_id is not None else None
        )
        with self._lock:
            target_record = self._targets.get(target_name)

        if target_record is None:
            decision = TargetDecision(
                target_name, None, agent_name, capability_name, DENY, "target_missing", correlation
            )
        elif not target_record.enabled:
            decision = TargetDecision(
                target_name,
                target_record.backend,
                agent_name,
                capability_name,
                DENY,
                "target_disabled",
                correlation,
            )
        elif "*" not in target_record.allowed_agents and agent_name not in target_record.allowed_agents:
            decision = TargetDecision(
                target_name,
                target_record.backend,
                agent_name,
                capability_name,
                DENY,
                "agent_not_allowed",
                correlation,
            )
        elif capability_name not in target_record.capabilities:
            decision = TargetDecision(
                target_name,
                target_record.backend,
                agent_name,
                capability_name,
                DENY,
                "capability_not_allowed",
                correlation,
            )
        elif capability_name in target_record.approval_required:
            decision = TargetDecision(
                target_name,
                target_record.backend,
                agent_name,
                capability_name,
                APPROVAL_REQUIRED,
                "target_policy_requires_approval",
                correlation,
            )
        else:
            decision = TargetDecision(
                target_name,
                target_record.backend,
                agent_name,
                capability_name,
                ALLOW,
                "target_policy_allowed",
                correlation,
            )
        self.audit.append(decision)
        return decision

    @staticmethod
    def _safe_target(value: str) -> str:
        token = str(value or "").strip()
        if _TARGET_RE.fullmatch(token) is None:
            raise ValueError("target name must be a safe token")
        return token

    @staticmethod
    def _safe_token(value: str, label: str) -> str:
        token = str(value or "").strip()
        if _TOKEN_RE.fullmatch(token) is None:
            raise ValueError(f"{label} must be a safe token")
        return token


def default_targets() -> tuple[TerminalTarget, ...]:
    """Conservative named inventory; host/SSH transports remain disabled by default."""
    return (
        TerminalTarget(
            name="bonobo-windows",
            backend="local",
            enabled=False,
            allowed_agents=frozenset({"jarvis", "ultron"}),
            capabilities=frozenset({
                "terminal.read", "terminal.exec", "file.read", "file.write"
            }),
            approval_required=frozenset({"terminal.exec", "file.write"}),
        ),
        TerminalTarget(
            name="pi-house",
            backend="ssh",
            enabled=False,
            allowed_agents=frozenset({"jarvis", "frigga", "ultron"}),
            capabilities=frozenset({"terminal.read", "terminal.exec", "file.read"}),
            approval_required=frozenset({"terminal.exec"}),
        ),
        TerminalTarget(
            name="isolated-sandbox",
            backend="docker",
            enabled=True,
            allowed_agents=frozenset({"*"}),
            capabilities=frozenset({
                "terminal.read", "terminal.exec", "file.read", "file.write"
            }),
            approval_required=frozenset(),
        ),
    )
