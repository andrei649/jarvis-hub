"""Permanent-approval promotion broker with a restart-reconcilable journal."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError

from .models import RequestStatus
from .package_store import PackageStoreError
from .quarantine import QuarantineError
from .receipt import VerificationReceipt, receipt_is_current, receipt_matches_package


class PromotionError(RuntimeError):
    pass


def make_skill_install_kernel_gate(action_kernel):
    """Bind the ``skill.install`` kernel gate used by :meth:`PromotionBroker.propose`.

    One factory serves both the production wiring (``autonomy_coordinator``) and the
    action-auth matrix, so the gate the matrix proves is the gate that ships. The
    kernel hook is skipped entirely unless ``JARVIS_ACTION_KERNEL`` is set (the same
    call-time ``kernel_enabled()`` discipline every other broker follows) — and even
    a kernel GRANT cannot bypass the permanent owner-approval floor in ``propose``.
    """

    def _gate(payload):
        from agents.core.kernel import Action, kernel_enabled

        if action_kernel is None or not kernel_enabled():
            return "queue"
        decision = action_kernel(
            Action(
                kind="skill.install",
                agent="jarvis",
                title="Install acquired capability",
                payload=dict(payload),
                origin="generated",
            )
        )
        return decision.verdict.value

    return _gate


@dataclass(frozen=True, slots=True)
class PromotionProposal:
    proposal_id: str
    artifact_id: str
    request_id: str
    name: str
    package_hash: str
    receipt_hash: str
    contract_hash: str
    action_kind: str
    risk_tier: int
    approval_mode: str
    status: str
    created_at: float
    decided_at: float | None = None
    decided_by: str | None = None


@dataclass(frozen=True, slots=True)
class JournalEntry:
    proposal_id: str
    artifact_id: str
    name: str
    package_hash: str
    stage: str
    updated_at: float
    reason: str = ""


class _EncryptedRows:
    schema = 1

    def __init__(self, root: str | Path, filename: str, *, clock=time.time, max_bytes=4 * 1024 * 1024):
        self.root = Path(root)
        if self.root.is_symlink():
            raise PromotionError("promotion store root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.path = self.root / filename
        self._cipher = SecretStore(self.root / f"{filename}.cipher.json")
        self.clock = clock
        self.max_bytes = max(1024, int(max_bytes))
        self._lock = threading.RLock()
        self._rows: list | None = None

    def _read_payload(self) -> list[dict]:
        if not self.path.exists():
            return []
        if self.path.is_symlink():
            raise PromotionError("promotion store cannot be a symlink")
        try:
            payload = json.loads(self._cipher.decrypt_bytes(self.path.read_bytes()).decode("utf-8"))
            if payload.get("schema") != self.schema or not isinstance(payload.get("rows"), list):
                raise ValueError("invalid promotion store schema")
            return payload["rows"]
        except (OSError, UnicodeError, json.JSONDecodeError, SecretStoreError, ValueError) as exc:
            raise PromotionError("cannot decrypt or validate promotion store") from exc

    def _commit(self, rows: list) -> None:
        raw = json.dumps(
            {"schema": self.schema, "rows": [asdict(row) for row in rows]},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(raw) > self.max_bytes:
            raise PromotionError("promotion store capacity reached")
        token = self._cipher.encrypt_bytes(raw)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".promotion-", delete=False) as handle:
                temporary = handle.name
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise PromotionError("cannot atomically commit promotion store") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)
        self._rows = rows


class PromotionStore(_EncryptedRows):
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        clock=time.time,
        max_proposals=512,
        event_sink=None,
    ):
        super().__init__(
            root or data_path("acquisition", "proposals"),
            "proposals.enc",
            clock=clock,
        )
        self.max_proposals = max(1, min(10_000, int(max_proposals)))
        self._event_sink = event_sink

    def _load(self) -> list[PromotionProposal]:
        if self._rows is None:
            try:
                self._rows = [PromotionProposal(**row) for row in self._read_payload()]
            except (TypeError, ValueError, KeyError) as exc:
                raise PromotionError("invalid promotion proposal record") from exc
            if len(self._rows) > self.max_proposals:
                raise PromotionError("promotion proposal capacity reached")
        return self._rows

    def create(self, *, package, receipt: VerificationReceipt) -> PromotionProposal:
        with self._lock:
            rows = self._load()
            existing = next(
                (
                    row
                    for row in rows
                    if row.artifact_id == package.artifact_id
                    and row.status in {"pending", "approved"}
                ),
                None,
            )
            if existing is not None:
                return existing
            if len(rows) >= self.max_proposals:
                raise PromotionError("promotion proposal capacity reached")
            proposal = PromotionProposal(
                proposal_id=uuid.uuid4().hex,
                artifact_id=package.artifact_id,
                request_id=package.request_id,
                name=package.name,
                package_hash=package.package_hash,
                receipt_hash=receipt.receipt_hash,
                contract_hash=package.contract_hash,
                action_kind="skill.install",
                risk_tier=3,
                approval_mode="permanent",
                status="pending",
                created_at=float(self.clock()),
            )
            self._commit([*rows, proposal])
            self._emit(
                "approval.proposed",
                proposal,
                actor="promotion-broker",
                status="pending",
            )
            return proposal

    def get(self, proposal_id: str) -> PromotionProposal | None:
        with self._lock:
            return next((row for row in self._load() if row.proposal_id == proposal_id), None)

    def decide(self, proposal_id: str, *, approved: bool, actor: str) -> PromotionProposal:
        with self._lock:
            rows = self._load()
            current = next((row for row in rows if row.proposal_id == proposal_id), None)
            if current is None:
                raise KeyError(proposal_id)
            if current.status != "pending":
                return current
            updated = replace(
                current,
                status="approved" if approved else "rejected",
                decided_at=float(self.clock()),
                decided_by=actor,
            )
            self._commit([updated if row is current else row for row in rows])
            self._emit(
                "approval.approved" if approved else "approval.rejected",
                updated,
                actor=actor,
                status=updated.status,
            )
            return updated

    def _emit(self, event_type: str, proposal: PromotionProposal, *, actor: str, status: str) -> None:
        if self._event_sink is not None:
            self._event_sink(
                event_type,
                actor=actor,
                request_id=proposal.request_id,
                artifact_id=proposal.artifact_id,
                task_id=proposal.proposal_id,
                status=status,
                details={
                    "package_hash": proposal.package_hash,
                    "receipt_hash": proposal.receipt_hash,
                    "risk_tier": proposal.risk_tier,
                    "approval_mode": proposal.approval_mode,
                },
            )

    def mark_installed(self, proposal_id: str) -> PromotionProposal:
        return self._mark(proposal_id, "installed")

    def mark_failed(self, proposal_id: str) -> PromotionProposal:
        return self._mark(proposal_id, "failed")

    def _mark(self, proposal_id: str, status: str) -> PromotionProposal:
        with self._lock:
            rows = self._load()
            current = next((row for row in rows if row.proposal_id == proposal_id), None)
            if current is None:
                raise KeyError(proposal_id)
            updated = replace(current, status=status)
            self._commit([updated if row is current else row for row in rows])
            return updated


class PromotionJournal(_EncryptedRows):
    _ORDER = ("prepared", "verified", "installed", "registered", "committed", "rolled_back")

    def __init__(self, root: str | Path | None = None, *, clock=time.time):
        super().__init__(
            root or data_path("acquisition", "journal"),
            "journal.enc",
            clock=clock,
        )

    def _load(self) -> list[JournalEntry]:
        if self._rows is None:
            try:
                self._rows = [JournalEntry(**row) for row in self._read_payload()]
            except (TypeError, ValueError, KeyError) as exc:
                raise PromotionError("invalid promotion journal record") from exc
        return self._rows

    def begin(self, proposal: PromotionProposal) -> JournalEntry:
        with self._lock:
            rows = self._load()
            existing = next((row for row in rows if row.proposal_id == proposal.proposal_id), None)
            if existing is not None:
                return existing
            entry = JournalEntry(
                proposal_id=proposal.proposal_id,
                artifact_id=proposal.artifact_id,
                name=proposal.name,
                package_hash=proposal.package_hash,
                stage="prepared",
                updated_at=float(self.clock()),
            )
            self._commit([*rows, entry])
            return entry

    def advance(self, proposal_id: str, stage: str, *, reason: str = "") -> JournalEntry:
        if stage not in self._ORDER:
            raise PromotionError("invalid promotion journal stage")
        with self._lock:
            rows = self._load()
            current = next((row for row in rows if row.proposal_id == proposal_id), None)
            if current is None:
                raise KeyError(proposal_id)
            if current.stage in {"committed", "rolled_back"}:
                return current
            if stage not in {"rolled_back"} and self._ORDER.index(stage) < self._ORDER.index(current.stage):
                raise PromotionError("promotion journal cannot move backwards")
            updated = replace(
                current,
                stage=stage,
                reason=str(reason or "")[:256],
                updated_at=float(self.clock()),
            )
            self._commit([updated if row is current else row for row in rows])
            return updated

    def get(self, proposal_id: str) -> JournalEntry | None:
        with self._lock:
            return next((row for row in self._load() if row.proposal_id == proposal_id), None)

    def open_entries(self) -> list[JournalEntry]:
        with self._lock:
            return [row for row in self._load() if row.stage not in {"committed", "rolled_back"}]


class PromotionBroker:
    def __init__(
        self,
        *,
        enabled,
        quarantine,
        requests,
        proposals: PromotionStore,
        packages,
        journal: PromotionJournal,
        tool_rpc,
        runtime,
        marketplace,
        profile,
        kernel_gate=None,
        failpoint=None,
        event_sink=None,
    ) -> None:
        self.enabled = enabled
        self.quarantine = quarantine
        self.requests = requests
        self.proposals = proposals
        self.packages = packages
        self.journal = journal
        self.tool_rpc = tool_rpc
        self.runtime = runtime
        self.marketplace = marketplace
        self.profile = profile
        self.kernel_gate = kernel_gate or (lambda _payload: "queue")
        self.failpoint = failpoint
        self._event_sink = event_sink

    def propose(self, artifact_id: str, *, contract) -> PromotionProposal:
        self._require_enabled()
        try:
            record = self.quarantine.get_record(artifact_id)
        except QuarantineError as exc:
            raise PromotionError("quarantine integrity is tampered") from exc
        if record is None or record.status != "verified" or record.receipt is None:
            raise PromotionError("verified quarantine receipt required")
        try:
            receipt = VerificationReceipt(**record.receipt)
        except (TypeError, ValueError) as exc:
            raise PromotionError("verification receipt is invalid") from exc
        if not receipt_is_current(receipt, record.package, contract, self.profile):
            raise PromotionError("verification receipt or package integrity is tampered")
        payload = {
            "kind": "skill.install",
            "name": record.package.name,
            "risk_tier": 3,
            "reversible": False,
            "approval_mode": "permanent",
            "package_hash": record.package.package_hash,
            "receipt_hash": receipt.receipt_hash,
        }
        try:
            decision = str(self.kernel_gate(payload)).lower()
        except Exception as exc:
            raise PromotionError("skill.install kernel gate failed") from exc
        if decision == "deny":
            raise PromotionError("skill.install denied by action kernel")
        # Even an accidental kernel GRANT cannot bypass this permanent approval floor.
        proposal = self.proposals.create(package=record.package, receipt=receipt)
        request = self.requests.get(record.package.request_id)
        if request is not None and request.status == RequestStatus.QUARANTINED:
            self.requests.transition(
                request.request_id,
                RequestStatus.APPROVAL_PENDING,
                actor="promotion-broker",
            )
        return proposal

    def decide(
        self,
        proposal_id: str,
        *,
        approved: bool,
        actor: str,
        permanent: bool,
    ) -> PromotionProposal:
        if str(actor or "").strip().lower() != "owner":
            raise PromotionError("owner decision required")
        if approved and permanent is not True:
            raise PromotionError("permanent owner approval required")
        return self.proposals.decide(proposal_id, approved=approved, actor="owner")

    async def promote(self, proposal_id: str) -> dict:
        self._require_enabled()
        proposal = self.proposals.get(proposal_id)
        if proposal is None or proposal.status != "approved":
            raise PromotionError("approved permanent proposal required")
        try:
            record = self.quarantine.get_record(proposal.artifact_id)
        except QuarantineError as exc:
            raise PromotionError("quarantine integrity is tampered") from exc
        if record is None or record.status != "verified" or record.receipt is None:
            raise PromotionError("verified quarantine artifact required")
        try:
            receipt = VerificationReceipt(**record.receipt)
        except (TypeError, ValueError) as exc:
            raise PromotionError("verification receipt is invalid") from exc
        if (
            proposal.package_hash != record.package.package_hash
            or proposal.receipt_hash != receipt.receipt_hash
            or not receipt_matches_package(receipt, record.package)
            or receipt.runtime_image != self.profile.image
            or receipt.runtime_config_hash != self.profile.config_hash
        ):
            raise PromotionError("approval receipt recheck detected tamper")

        entry = self.journal.begin(proposal)
        if entry.stage == "prepared":
            self.journal.advance(proposal_id, "verified")
            self._fail("verified")
        try:
            installed = self.packages.install(
                package=record.package,
                receipt=receipt,
                version="0.1.0",
            )
        except PackageStoreError as exc:
            raise PromotionError(str(exc)) from exc
        self.journal.advance(proposal_id, "installed")
        self.marketplace.index_acquired_package(installed.catalog_metadata())
        self._fail("installed")
        self._register(installed.name)
        self.journal.advance(proposal_id, "registered")
        self._fail("registered")
        self._finalize(proposal, record.package.request_id)
        return {
            "status": "installed",
            "name": installed.name,
            "package_hash": installed.package_hash,
        }

    async def execute_task(self, task) -> dict:
        payload = getattr(task, "payload", None)
        proposal_id = payload.get("proposal_id") if isinstance(payload, dict) else None
        if not isinstance(proposal_id, str):
            return {"status": "failed", "reason": "proposal_id_required"}
        try:
            return await self.promote(proposal_id)
        except PromotionError:
            return {"status": "failed", "reason": "promotion_refused"}

    def register_executor(self, executor):
        executor.register("skill.install", self.execute_task)
        return executor

    def restore_registrations(self) -> int:
        restored = 0
        for record in self.packages.list_records():
            if record.status == "active" and self.packages.verify(record.name):
                self._register(record.name)
                restored += 1
        return restored

    async def reconcile(self) -> dict[str, int]:
        result = {"committed": 0, "rolled_back": 0}
        for entry in self.journal.open_entries():
            proposal = self.proposals.get(entry.proposal_id)
            record = self.packages.get(entry.name)
            if (
                proposal is not None
                and proposal.status == "approved"
                and record is not None
                and self.packages.verify(entry.name)
                and record.package_hash == entry.package_hash
            ):
                self.marketplace.index_acquired_package(record.catalog_metadata())
                self._register(entry.name)
                quarantine = self.quarantine.get_record(entry.artifact_id)
                request_id = quarantine.package.request_id if quarantine is not None else proposal.request_id
                self._finalize(proposal, request_id)
                result["committed"] += 1
                continue
            if record is not None:
                await self.tool_rpc.unregister_tool(entry.name, cancel_inflight=True)
                self.packages.uninstall(entry.name)
            self._rollback_state(entry, proposal)
            self.journal.advance(entry.proposal_id, "rolled_back", reason="restart reconciliation")
            result["rolled_back"] += 1
        return result

    async def revoke(self, name: str) -> dict:
        """Deny new calls immediately and leave a durable revoked package record."""
        record = self.packages.get(name)
        if record is None:
            raise PromotionError("acquired package not found")
        await self.tool_rpc.unregister_tool(name, cancel_inflight=True)
        self._emit_package("registry.unregistered", record, status="revoking")
        self.packages.revoke(name)
        self.marketplace.remove_acquired_package(name)
        request = self.requests.get(record.manifest["request_id"])
        if request is not None and request.status == RequestStatus.INSTALLED:
            self.requests.transition(request.request_id, RequestStatus.REVOKED, actor="owner")
        quarantine = self.quarantine.get_record(record.manifest["artifact_id"])
        if quarantine is not None and quarantine.status == "promoted":
            self.quarantine.transition(quarantine.package.artifact_id, "revoked")
        self._emit_package("revocation.completed", record, status="revoked")
        return {"status": "revoked", "name": name}

    async def rollback(self, name: str) -> dict:
        """Restore a retained prior version, or remove a net-new acquired package."""
        current = self.packages.get(name)
        if current is None:
            raise PromotionError("acquired package not found")
        await self.tool_rpc.unregister_tool(name, cancel_inflight=True)
        self._emit_package("registry.unregistered", current, status="rolling_back")
        prior = self.packages.rollback(name)
        if prior is None:
            self.packages.revoke(name)
            self.packages.uninstall(name)
            self.marketplace.remove_acquired_package(name)
            request = self.requests.get(current.manifest["request_id"])
            if request is not None and request.status == RequestStatus.INSTALLED:
                self.requests.transition(request.request_id, RequestStatus.REVOKED, actor="rollback")
            self._emit_package("rollback.completed", current, status="uninstalled")
            return {"status": "uninstalled", "name": name}
        self.marketplace.index_acquired_package(prior.catalog_metadata())
        self._register(name)
        self._emit_package("rollback.completed", prior, status="restored")
        return {"status": "restored", "name": name, "version": prior.version}

    def _register(self, name: str) -> None:
        if self.tool_rpc.allows(name):
            return

        async def handler(args):
            return await self.runtime.run(name, args)

        self.tool_rpc.register_tool(
            name,
            handler,
            gated=False,
            description=f"Sandbox-only acquired capability {name}.",
            input_schema={"type": "object", "additionalProperties": True},
            capability_id=f"tool:acquired.{name}",
        )
        record = self.packages.get(name)
        if record is not None:
            self._emit_package("registry.registered", record, status="registered")

    def _emit_package(self, event_type: str, record, *, status: str) -> None:
        if self._event_sink is not None:
            self._event_sink(
                event_type,
                actor="promotion-broker",
                request_id=record.manifest.get("request_id", ""),
                artifact_id=record.manifest.get("artifact_id", ""),
                status=status,
                details={
                    "name": record.name,
                    "version": record.version,
                    "package_hash": record.package_hash,
                },
            )

    def _finalize(self, proposal: PromotionProposal, request_id: str) -> None:
        request = self.requests.get(request_id)
        if request is not None and request.status == RequestStatus.APPROVAL_PENDING:
            self.requests.transition(request_id, RequestStatus.INSTALLED, actor="promotion-broker")
        quarantine = self.quarantine.get_record(proposal.artifact_id)
        if quarantine is not None and quarantine.status == "verified":
            self.quarantine.transition(proposal.artifact_id, "promoted")
        self.proposals.mark_installed(proposal.proposal_id)
        self.journal.advance(proposal.proposal_id, "committed")

    def _rollback_state(
        self,
        entry: JournalEntry,
        proposal: PromotionProposal | None,
    ) -> None:
        if proposal is not None:
            self.proposals.mark_failed(entry.proposal_id)
            request = self.requests.get(proposal.request_id)
            if request is not None and request.status == RequestStatus.APPROVAL_PENDING:
                self.requests.transition(request.request_id, RequestStatus.BLOCKED, actor="reconciler")
        try:
            quarantine = self.quarantine.get_record(entry.artifact_id)
        except QuarantineError:
            quarantine = None
        if quarantine is not None and quarantine.status == "verified":
            self.quarantine.transition(entry.artifact_id, "rejected")

    def _require_enabled(self) -> None:
        try:
            active = self.enabled() is True
        except Exception:
            active = False
        if not active:
            raise PromotionError("acquisition is disabled")

    def _fail(self, stage: str) -> None:
        if self.failpoint is not None:
            self.failpoint(stage)


__all__ = [
    "JournalEntry",
    "PromotionBroker",
    "PromotionError",
    "PromotionJournal",
    "PromotionProposal",
    "PromotionStore",
]
