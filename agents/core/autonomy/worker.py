"""
worker.py — Autonomy Worker (H6.1 glue + H6.2/H6.3 integration).

Ties the queue, policy and decision inbox together:

  submit()  → enqueue (proposed) → policy.decide → auto-approve (act/notify)
              or block + push a decision card to the inbox (ask), within the
              daily interruption budget.
  tick()    → run approved tasks via the injected executor, with a retry cap.
  apply_decision() → resolve a blocked task from a human's inbox tap.

Executor and notifier are injected (set by web.py at startup) so this module
stays free of orchestrator/Telegram imports and is unit-testable offline.
"""

from __future__ import annotations

if __name__ != "agents.core.autonomy.worker":
    raise ImportError("AutonomyWorker authority must be imported as agents.core.autonomy.worker")

import inspect
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, date
from typing import Awaitable, Callable, Optional

from ..action_origin import current_action_origin
from ..ambient.policy import AttentionDeliveryBroker, AttentionLedger
from ..security import taint
from .mediation import (
    DetachedHMACSigner,
    ReceiptExpectation,
    issue_intake_evidence,
    issue_receipt,
)
from .policy import ACT, ASK, NOTIFY, AutonomyPolicy, RiskTier
from .queue import (
    MAX_ATTEMPTS,
    MediationStateUnavailable,
    Task,
    TaskQueue,
    TaskQueueError,
    TaskStatus,
)

logger = logging.getLogger("jarvis.autonomy.worker")

INTERRUPT_BUDGET_PER_DAY = 4

# ── the refusal vocabulary (review round 2, MINOR 2) ─────────────────────────
#
# A refusal ran nothing, so it says nothing about how well a capability works and
# records no capability outcome (``_record_capability_outcome``). A handler that
# says so in its status (``refused``; ``blocked`` for a contract denial) is taken at
# its word whatever the reason. But many handlers return a refusal as
# ``{"status": "failed", "reason": ...}``, the same shape as an attempt that broke,
# so for ``failed`` the REASON decides: a reason listed for the task's kind is a
# refusal; any other reason — including one nobody listed yet — is a failure, the
# conservative direction (it lowers confidence, it can never earn autonomy).
#
# The principle (review round 3): a reason is a refusal only when it can ONLY mean
# "nothing was attempted" — a gate declined BEFORE any attempt. An ambiguous reason,
# one that can also follow an attempt that began, is a failure until its handler
# splits it into two reasons.
#
# Per kind (review round 4, item 4): the vocabulary maps each ACTION_CAPABILITY_MANIFESTS
# kind to the refusal reasons ITS handler returns (and the parameterised prefixes, the
# same way). A reason one handler uses as a refusal is not a refusal when another
# kind's handler returns it: ``kernel_denied`` from house or tool.rpc ran nothing, from a
# call handler (which never says it) it is an unknown reason, a failure. A kind resolves
# like the manifests do: its exact key, else a ``prefix.*`` pattern.
#
# Over ALL of a task's attempts (review round 4, item 1): the worker retries a task
# whose handler raised, and a gate can refuse the retry — the kill switch engaged, the
# kernel now denies, a budget was spent in between — after the first attempt broke (a
# database that was locked, a store it could not read). That refusal is true of the
# retry, not of the task: the capability WAS attempted and broke. So a task whose
# final attempt would record nothing (a refusal, a withheld result, a no-op or a mock)
# records ONE failure when an earlier attempt of it failed (its handler raised an
# error whose reason is not a refusal of its kind; the retry records that durably on
# the task). A first-attempt refusal, or a refusal on every attempt, still records
# nothing; a later success records the one success.
#
# Only the HANDLER's error is an attempt of the capability (review round 5, item 3).
# The worker's own bookkeeping after the handler returned — ``queue.transition(DONE)``
# raising — is not: that attempt's own outcome is recorded then and there (a success
# once, marked durably on the task so no later attempt records again; a returned
# failure counts as an attempt that broke; a refusal counts as nothing), and the task
# is retried or failed as before.
#
# The one class that is neither (review round 4, item 3; round 5, items 1 and 8):
# ATTEMPTED BUT WITHHELD BY GOVERNANCE. tool.rpc's local image runtime and the cloud
# image runtime (plugin.egress) re-check their gates after the backend request has
# completed; when a GOVERNANCE cause (a refusal of the kind: a kernel denial, a
# mediation hold, a changed approval, a gate switched off, the emergency stop) withholds
# an image that was already generated, they report ``withheld_after_generation`` (the
# cause in ``detail``). The capability ran and worked — governance withheld the result
# — so it is not a refusal (something was attempted) and not a failure (nothing broke):
# it records NOTHING (WITHHELD_REASONS_BY_KIND). A post-request check that BROKE (the
# kernel raising, a verdict that is not one, a record it cannot read, the backend's own
# source changing) is the machinery failing: a failure under its own reason, the same
# as before the request. Before the request the same gates stay refusals.
#
# A success is EXPLICIT (review round 5, item 8): a returned result records a success
# only when its status is one a handler uses for a success (SUCCESS_STATUSES), or when
# it carries no status but ``ok: True``. Any other status — the cloud image runtime's
# ``unknown`` (the submission may have happened, the result is not known), a status
# nobody listed — is a failure, the conservative direction.
#
# A capability that was never exercised records nothing (review round 5, item 9): a
# task whose kind has no registered handler runs through the executor's generic LLM
# fallback (``TaskExecutor.handles`` is False) — the capability its manifest names did
# not run, whatever the fallback returned or raised.
#
# Review round 6 — the three-way rule, path by path:
#   * A DEFERRAL is not work done (item 4). The default (offline) rails — call.outbound,
#     social.*, writeback.* with no credential and no live flag, node.dispatch with no
#     node transport — return their client's ``degraded({"status": "deferred"})``; each
#     broker lifts that marker and its reason to the top level (keeping ``status`` and
#     the nested key for its readers), and ``_attempt_outcome`` never counts a success
#     status wrapped around a degraded value (defence in depth). The record follows the
#     rule for a deferral: a credential or a transport this hub has not configured is
#     "nothing attempted", a configuration refusal of its kind
#     (``call_credential_not_configured``, ``social_credential_not_configured``,
#     ``writeback_credential_not_configured``, ``node_transport_not_built`` are listed
#     below): nothing is recorded. A nested degraded reason nobody listed is a failure.
#     A top-level mock (ADV-094) still records nothing: the handler itself says it did
#     nothing.
#   * The EXECUTION GUARD (item 6) runs before any attempt. A guard that declined for a
#     gate it can name raises ``ExecutionGuardDeclined(reason)``; the task still fails
#     (``mediation_execution_context_required``, a TaskQueueError, the reason kept as
#     ``guard_reason``), and the capability records NOTHING when the reason is a refusal
#     of the kind (the cloud image and URL monitor guards: the plugin or heavy features
#     off, mediation or the kernel switched off, the credential missing, the key, the
#     job or the approval record changed, a secret in the prompt). A guard that returned
#     a bare False, raised anything else, or named an unlisted reason is a failure.
#   * A MEDIATION STORE that cannot be read (item 2) is machinery:
#     ``TaskQueue.validate_mediated_execution`` raises ``MediationStateUnavailable``
#     instead of answering False, and every caller reports it as a failure
#     (``mediation_state_unavailable`` in the image, cloud image and URL monitor
#     runtimes; the worker's own pre-dispatch check fails the task before the handler,
#     recording nothing — no handler ran). False stays the governance hold
#     ``mediation_execution_required``.
#   * A PROVIDER the owner reconfigured during a local image request (item 1) reaches
#     the guard as ``backend_binding_changed`` — governance, the image withheld (0,0);
#     ``approval_binding_invalid`` is only an approval record that is missing,
#     unreadable or does not match the running row (a failure).
#   * A cloud image whose bytes and completion record are durable but whose CATALOG row
#     failed (item 3) is a success with ``warning: catalog_record_failed``; ``unknown``
#     is only an image that may exist remotely and is not durably kept here.
#   * The URL monitor (item 7) splits like the cloud image runtime: a gate declining
#     at the dial is ``refused`` (0,0); a gate declining on a check after the response
#     arrived withholds it (``withheld_after_fetch``, 0,0); a fetch or kernel that broke
#     is a failure.
#   * House (item 5): a driver that did not succeed — it returned an error or a refusal
#     after it ran, or raised — is a failure (``driver_failed``) even when the device
#     state verifies (it may have matched already); the row finishes, nothing is rolled
#     back, the result names both (``state_verified``, ``driver_reason``).
#
# What counts as a refusal: a governance decision (kernel, capability token, kill
# switch, allowlist, approval binding, a human decision the handler needs), a spent
# budget, a guard against a concurrent or changed request, or a capability this hub
# has not configured. What does not: a malformed request the handler could not carry
# out (``invalid_call``, ``bad_args``, ``unknown_target_action``), an error of the
# capability's own machinery — even one before the attempt, such as a classifier that
# crashed or a store that could not be read (``client_error``, ``send_failed``,
# ``tool_error``, ``apply_failed``, ``verification_failed``, ``classify_failed``,
# ``provider_store_unavailable``, ``install_failed``, ``promotion_store_unavailable``,
# ``attention_ledger_unavailable``, ``work_run_ledger_unavailable``,
# ``wall_time_budget_exceeded``, ``capability_broker_unavailable``,
# ``mediation_state_unavailable``, ``driver_failed``, a kernel that raised or answered
# with no Decision — ``kernel_error``, ``local_guard_failed`` — or is not there —
# ``kernel_unavailable``) — and a world the handler found unfit to act in (a stale or
# degraded house state).
#
# Known gap (review round 4, closure C; not fixed here): ``credential_not_configured``
# (call.outbound, social.*, writeback.*) also covers a secret that is configured but
# cannot be decrypted — ``SecretBroker._safe_get`` swallows ``SecretStoreError`` and
# the lookup reads as not found. That is a store failure reported as a refusal; the
# broker lives in a protected module (agents/core/security/secret_broker.py), so the
# split is the owner's change to make.
#
# Known gaps (review round 5, item 5; not fixed here): duplicate EFFECTS the net above
# cannot prevent. It records one outcome per task; it cannot undo what a broken attempt
# left behind when the handler's own write is not idempotent and the retry repeats it:
#   * goal.approve — CLOSED by H464c: ``open_run`` checks and inserts in one write
#     transaction that rolls back on any failure (a commit that raised leaves no row for
#     the next commit to write), and a ``task:<id>:…`` approval opens ONE run, ever — the
#     retry gets the run the first attempt opened (same pinned fingerprint), with that
#     run's goal id, or ``approval_already_used``.
#   * permission.grant — ``apply_grant`` runs ``_insert`` then ``_audit``/``commit`` with
#     no rollback; one of those raising lets the retry insert a SECOND grant.
#   * channel.reply — ``record_outbound`` raising after the send escapes the broker; the
#     retry SENDS the reply again.
# Each needs its handler to key the write to the task (or roll back before raising).
#
# Known gaps (review round 6; documented, not fixed here):
#   * The ComfyUI local image provider drops the post-request ``guard``
#     (``media_backends/registry.py:134``, ``ComfyImageProvider.generate``): a
#     governance change during a ComfyUI generation is not rechecked after the request,
#     so the image is published and a success recorded.
#   * skill.install: a task reaped mid-install and reconciled reads as
#     ``promotion_refused`` (``acquisition/runtime.py``), whichever way the reconcile
#     went.
#   * A task whose DONE transition failed is retried, so its handler runs again (only
#     the record is kept right: round 5, item 3); with the three duplicate-effect gaps
#     above, that retry can repeat the effect.
#
# Collected by reading the executor of every ACTION_CAPABILITY_MANIFESTS kind the
# worker runs. The kinds with an empty entry (kg.write, media.*, model.pull,
# report.export, terminal.exec, file.write, browser.step, desktop.step, host.control,
# repo.sync, admin.*, payment, mcp.mutating, house.recovery) have no worker executor
# of their own that returns a refusal as ``failed``; their implementations run at a
# route or the unified action API.
# house (round 5, item 6): ``kernel_denied`` is only a real kernel Decision that refused
# or queued the actuation, and the two switches — the unified action API or the kernel
# turned off — are decided before any driver call; a kernel that broke is a failure.
_HOUSE_REFUSALS = ("kernel_denied", "execution_in_progress", "task_payload_changed",
                   "unified_action_api_disabled", "action_kernel_disabled")
_REFUSALS_BY_KIND: dict[str, tuple[str, ...]] = {
    # node.dispatch — NodeMesh.execute re-authorises at action time: NodeMesh._authorize
    # and security.capability.authorize (``kill-switch engaged for scope '<scope>'``
    # matches by prefix, below). ``capability_broker_unavailable`` is not one: the
    # broker (``orch.capabilities``) is None only when its component failed to start —
    # machinery, a failure (round 5, item 7).
    # ``node_transport_not_built`` is the deferral every dispatch returns while no node
    # transport exists (round 6, item 4): nothing was attempted.
    "node.dispatch": ("unknown_node", "no_valid_capability",
                      "no valid capability token for this action", "denied",
                      "node_transport_not_built"),
    # call.outbound — CallBroker.execute (budget ledger, credential, live-rail config,
    # interrupt budget; ``call_config_missing:<keys>`` matches by prefix, below).
    # ``interrupt_budget_exhausted`` is only an attention ledger that declined to admit
    # the call (a spent budget, or a delivery it already settled before dispatch); a
    # ledger that cannot be read is ``attention_ledger_unavailable``, a failure
    # (round 4, item 5).
    # ``call_credential_not_configured`` is the default (offline) rail's deferral with no
    # credential (round 6, item 4), like ``social_…`` and ``writeback_…`` below.
    "call.outbound": ("budget_exceeded", "credential_not_configured", "call_config_missing",
                      "interrupt_budget_exhausted", "call_credential_not_configured"),
    # social.* — SocialBroker.execute / _execute_postiz.
    "social.*": ("credential_not_configured", "postiz_not_configured",
                 "social_credential_not_configured"),
    # writeback.* — WriteBackBroker.execute.
    "writeback.*": ("credential_not_configured", "writeback_credential_not_configured"),
    "payment": (),
    # plugin.egress — the coordinator's URL monitor routing, the URL monitor and cloud
    # image executors, all ``refused``; and the gates their EXECUTION GUARDS report
    # before any attempt (round 6, item 6: ``ExecutionGuardDeclined`` — the plugin or a
    # heavy feature switched off, mediation not enforced or the kernel switched off, the
    # credential missing, the key or the monitored job changed since the approval, the
    # approval record no longer binding the task, a secret in the prompt). The same gates
    # in ``execute`` return ``refused``; after the request they withhold (below).
    "plugin.egress": ("URL monitor unavailable", "unsupported egress operation",
                      "URL monitor execution claim required",
                      "cloud image execution claim required",
                      "cloud_image_unavailable", "enforced_mediation_unavailable",
                      "credential_not_configured", "configuration_changed",
                      "approved_payload_changed", "prompt_screening_refused"),
    "mcp.mutating": (),
    "host.control": (),
    # tool.rpc — the coordinator's image-only gate, ToolRPCServer.execute (allowlist,
    # H506 class binding, trusted execution, kernel), the image dispatcher's cloud
    # routing guard and the local image runtime's own guard BEFORE the backend request
    # (after it, each of these gates is ``withheld_after_generation``: round 4, item 3;
    # this list is also what decides that — ``media_backends.comfyui.governance_withholds``,
    # round 5, item 1). The runtime gates ``local_image_disabled``, ``kernel_required``
    # and ``heavy_features_paused`` are refusals since that split. Failures, not listed
    # (before OR after the request): ``classify_failed`` (the classifier crashed:
    # machinery), ``approval_binding_invalid`` (an approval record missing, unreadable
    # or not matching the running row — a provider changed since the approval is
    # ``backend_binding_changed``, round 6, item 1), ``mediation_state_unavailable`` (the
    # queue's mediation state could not be read, round 6, item 2),
    # ``validation_failed`` (also a preflight that raised),
    # ``runtime_changed_restart_required`` / ``backend_source_changed`` (the code itself
    # changed), ``local_guard_failed`` / ``kernel_error`` (the kernel raised or gave no
    # verdict).
    "tool.rpc": ("image_task_required", "tool_not_allowed",
                 "approval_class_mismatch", "trusted_execution_required", "kernel_denied",
                 "cloud_worker_required", "approved_payload_changed", "backend_binding_changed",
                 "mediation_execution_required", "local_image_disabled", "kernel_required",
                 "heavy_features_paused"),
    "repo.sync": (),
    "admin.kill_switch": (),
    "admin.capability_issue": (),
    "kg.write": (),
    # channel.reply — ChannelReplyBroker.execute (its contract denial is ``blocked``).
    "channel.reply": ("channel_manager_unavailable", "reply_transport_unavailable"),
    # skill.install — AcquisitionRuntime.execute_install_task and
    # PromotionBroker.execute_task. ``promotion_refused`` is only a check that declined
    # before any install work (disabled, no approved proposal, the quarantine's package
    # hash check, receipt tamper); once the journal began — whatever raised — it is
    # ``install_failed``, and a store unreadable before any write (proposals, quarantine,
    # the journal inside ``begin``) is ``promotion_store_unavailable``: both failures
    # (round 3, item 1; round 4, item 2).
    "skill.install": ("acquisition_unavailable", "promotion_refused"),
    "media.present": (),
    "media.restore": (),
    "desktop.step": (),
    "browser.step": (),
    # house.control / house.security_control — HouseActuator.execute_task; the
    # registered handler raises HouseActuationError(reason) instead of returning.
    # ``execution_in_progress`` is only another execution of this task in flight right
    # now; a row an earlier attempt left ``running`` (it raised after ``begin``, or the
    # process died) is ``execution_stranded``, a failure (round 3, item 2). Only a
    # security task needs a strong confirmation.
    "house.control": _HOUSE_REFUSALS,
    "house.security_control": (*_HOUSE_REFUSALS, "strong_confirmation_required"),
    "house.recovery": (),
    # permission.grant — PermissionLedger.apply_grant, all ``refused`` (a contract
    # denial carries the contract's own reason).
    "permission.grant": ("kind_mismatch", "human_decision_required", "decision_not_approval",
                         "payload_required", "contract_denied", "never_entry"),
    "terminal.exec": (),
    "file.write": (),
    "model.pull": (),
    "report.export": (),
    # settings.voice_command — irreversible.execute and command_settings.apply_approved,
    # returned as ``refused``; a store that fails while applying is returned as
    # ``failed`` / ``provider_store_unavailable``, a failure (round 3, item 5).
    "settings.voice_command": (
        "unknown_kind", "human_decision_required", "decision_not_approval", "payload_required",
        "edit_not_supported", "decision_not_accept", "not_requested", "payload_changed",
        "invalid_provider_id", "payload_invalid", "invalid_command", "not_armed", "safe_mode",
        "changed_since_request", "provider_revision_conflict", "provider_capacity_full"),
    # goal.approve — the coordinator's _open_approved_goal: its refusals are all
    # ``refused`` (the GoalContractError / WorkRunError reason). A work-run ledger that
    # failed to construct is ``failed`` / ``work_run_ledger_unavailable``, a failure
    # (round 4, item 5).
    "goal.approve": (),
}
REFUSAL_REASONS_BY_KIND: dict[str, frozenset[str]] = {
    kind: frozenset(reasons) for kind, reasons in _REFUSALS_BY_KIND.items()}
# The refusal reasons that carry a parameter, per kind.
REFUSAL_REASON_PREFIXES_BY_KIND: dict[str, tuple[str, ...]] = {
    "call.outbound": ("call_config_missing:",),
    "node.dispatch": ("kill-switch engaged for scope ",),
}
# Attempted, then withheld by governance: records nothing (see above). plugin.egress:
# the cloud image runtime's recheck after the provider answered (round 5, item 8), and
# the URL monitor's check after the response arrived (round 6, item 7).
WITHHELD_REASONS_BY_KIND: dict[str, frozenset[str]] = {
    "tool.rpc": frozenset({"withheld_after_generation"}),
    "plugin.egress": frozenset({"withheld_after_generation", "withheld_after_fetch"}),
}
# Statuses by which a handler itself says it declined.
REFUSAL_STATUSES = frozenset({"refused", "blocked"})
# Statuses by which a handler says its capability did the work (round 5, item 8),
# collected from the executor of every manifest kind: ``ok`` (node, call, social,
# writeback, channel.reply, permission.grant, goal.approve, settings.voice_command,
# tool.rpc, plugin.egress — the URL monitor and the cloud image completion; the
# executor's own wrapping of a non-dict result), ``redirect`` (the URL monitor's hop
# answered with a redirect for the job to follow), ``verified`` (house) and
# ``installed`` (skill.install). Every other status is a failure.
SUCCESS_STATUSES = frozenset({"ok", "redirect", "verified", "installed"})


def _vocabulary_kind(kind: object) -> str | None:
    """The vocabulary entry for a task kind: its exact key, else a ``prefix.*`` pattern
    (the resolution ``capability_manifests.manifest_for_action`` uses)."""
    if not isinstance(kind, str) or not kind:
        return None
    if kind in REFUSAL_REASONS_BY_KIND:
        return kind
    return next((pattern for pattern in REFUSAL_REASONS_BY_KIND
                 if pattern.endswith(".*") and kind.startswith(pattern[:-1])), None)


def is_refusal_reason(kind: object, reason: object) -> bool:
    """Whether a ``failed`` result's (or a raised error's) reason names a refusal of the
    handler of *kind*."""
    entry = _vocabulary_kind(kind)
    if entry is None or not isinstance(reason, str) or not reason:
        return False
    return (reason in REFUSAL_REASONS_BY_KIND[entry]
            or reason.startswith(REFUSAL_REASON_PREFIXES_BY_KIND.get(entry, ())))


def is_refusal(kind: object, result: object) -> bool:
    """Whether a handler's returned result is a refusal: nothing ran, nothing to record."""
    if not isinstance(result, dict):
        return False
    status = result.get("status")
    if status in REFUSAL_STATUSES:
        return True
    return status == "failed" and is_refusal_reason(kind, result.get("reason"))


def is_withheld(kind: object, result: object) -> bool:
    """Whether a returned ``failed`` result is an attempt governance withheld the result
    of (the capability ran and worked): nothing to record."""
    entry = _vocabulary_kind(kind)
    return (entry is not None and isinstance(result, dict) and result.get("status") == "failed"
            and result.get("reason") in WITHHELD_REASONS_BY_KIND.get(entry, ()))


# A retry marks the task with the failed attempts before it (round 4, item 1), and
# with the outcome an earlier attempt already recorded (round 5, item 3: a success
# whose DONE transition raised), in the task's ``result`` (outside every execution
# fingerprint; DONE/FAILED overwrite it).
_FAILED_ATTEMPTS_KEY = "failed_attempts"
_OUTCOME_RECORDED_KEY = "outcome_recorded"


def _earlier_failed_attempts(task: Task) -> int:
    result = task.result if isinstance(task.result, dict) else {}
    count = result.get(_FAILED_ATTEMPTS_KEY)
    return count if type(count) is int and count > 0 else 0


def _outcome_already_recorded(task: Task) -> bool:
    return isinstance(task.result, dict) and task.result.get(_OUTCOME_RECORDED_KEY) is True


def _retry_record(error: BaseException, *, failures: int, recorded: bool) -> dict | None:
    """The task's ``result`` while it waits for its retry: the error, with the marks the
    next attempt reads. None (the result is left as it is) when there is nothing to mark."""
    if not failures and not recorded:
        return None
    record = _failure_record(error)
    if failures:
        record[_FAILED_ATTEMPTS_KEY] = failures
    if recorded:
        record[_OUTCOME_RECORDED_KEY] = True
    return record


def _guard_refusal(result: dict) -> TaskQueueError:
    """The error that fails a task whose execution guard declined (the executor's
    ``mediation_execution_context_required``). When the guard named its reason
    (``ExecutionGuardDeclined``, review round 6, item 6) the error carries it as
    ``reason`` — so a governance decline in the kind's refusal vocabulary records
    nothing, like any refusal raised before an attempt — and the FAILED task keeps it
    (``guard_reason``). A guard that declined without a reason, or broke, stays a
    failure."""
    error = TaskQueueError("mediation execution context refused")
    reason = result.get("guard_reason")
    if isinstance(reason, str) and reason:
        error.reason = reason
        error.task_record = {"guard_reason": reason}
    return error


def _failure_record(error: BaseException) -> dict:
    """The FAILED task's result: the error, plus the flags a handler's error carries for
    the record (``task_record``, e.g. house's ``manual_recovery_required``)."""
    record: dict = {"error": str(error)}
    extra = getattr(error, "task_record", None)
    if isinstance(extra, dict):
        for key, value in extra.items():
            if isinstance(key, str) and key != "error" and isinstance(value, (bool, int, str)):
                record[key] = value
    return record


# executor(task) -> dict result ; notifier(task) -> bool (pushed ok)
Executor = Callable[[Task], Awaitable[dict]]
Notifier = Callable[[Task], Awaitable[bool]]


class _ExecutionPermit:
    """Shared one-use permit that cannot be replayed by a copied ContextVar."""

    def __init__(self, task: Task) -> None:
        self._fingerprint = TaskQueue.execution_fingerprint(task)
        self._active = True
        self._lock = threading.Lock()

    def consume(self, task: Task, *, validate: Callable[[Task, str], bool]) -> bool:
        with self._lock:
            if not self._active:
                return False
            self._active = False
            fingerprint = TaskQueue.execution_fingerprint(task)
            if (
                not self._fingerprint
                or fingerprint != self._fingerprint
                or task.status != TaskStatus.RUNNING.value
            ):
                return False
        return validate(task, self._fingerprint)

    def revoke(self) -> None:
        with self._lock:
            self._active = False


def is_night_window(hour: int, start: int = 23, end: int = 6) -> bool:
    """True if `hour` falls in the night window (handles wrap past midnight)."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps midnight, e.g. 23→6


class InterruptBudget:
    """Compatibility view over H33's durable global attention ledger."""

    def __init__(
        self,
        per_day: int = INTERRUPT_BUDGET_PER_DAY,
        *,
        ledger=None,
        dimension: str = "interrupts/day",
        attention_ledger: AttentionLedger | None = None,
        timezone_name: str = "UTC",
    ):
        self._k3 = ledger
        self._dimension = dimension
        self._timezone_name = timezone_name
        self._owns_attention_ledger = attention_ledger is None
        self.attention_ledger = attention_ledger or AttentionLedger(
            ":memory:",
            timezone_name=timezone_name,
            per_day=per_day,
            k3=ledger,
        )
        self.attention_ledger.per_day = per_day
        self.delivery_broker = AttentionDeliveryBroker(self.attention_ledger)
        self._day = date.today()
        self._counter = 0

    @property
    def per_day(self) -> int:
        return self.attention_ledger.per_day

    @per_day.setter
    def per_day(self, value: int) -> None:
        self.attention_ledger.per_day = value

    def _roll(self) -> None:
        # Kept solely for the old public test/API that mutates ``_day``. Real
        # rollover is owner-timezone aware and persistent inside AttentionLedger.
        today = date.today()
        if today != self._day and self._owns_attention_ledger:
            self.attention_ledger.close()
            self.attention_ledger = AttentionLedger(
                ":memory:",
                timezone_name=self._timezone_name,
                per_day=self.per_day,
                k3=self._k3,
            )
            self.delivery_broker = AttentionDeliveryBroker(self.attention_ledger)
            self._day = today
            self._counter = 0

    def remaining(self) -> int:
        self._roll()
        return self.attention_ledger.remaining()

    def consume(
        self,
        *,
        delivery_id: str | None = None,
        channel_class: str = "legacy",
    ) -> bool:
        self._roll()
        self._counter += 1
        delivery_id = delivery_id or f"legacy-{self._day.isoformat()}-{self._counter}"
        reservation = self.attention_ledger.reserve(delivery_id, channel_class)
        if reservation.admitted and reservation.state == "reserved":
            self.attention_ledger.start_dispatch(delivery_id)
            self.attention_ledger.delivered(delivery_id)
        return reservation.admitted


class AutonomyWorker:
    def __init__(
        self,
        queue: TaskQueue,
        policy: Optional[AutonomyPolicy] = None,
        executor: Optional[Executor] = None,
        notifier: Optional[Notifier] = None,
        budget: Optional[InterruptBudget] = None,
        audit=None,
        prefs=None,
        kill_switch=None,
        delivery_broker: AttentionDeliveryBroker | None = None,
        clock: Optional[Callable[[], float]] = None,
        running_ttl_seconds: float = 3600.0,
        kernel=None,
        mediation_signer: DetachedHMACSigner | None = None,
        mediation_clock_ms: Optional[Callable[[], int]] = None,
        mediation_receipt_ttl_ms: int = 86_400_000,
    ):
        self.queue = queue
        self.policy = policy or AutonomyPolicy()
        if hasattr(self.policy, "outcome_provider"):
            self.policy.outcome_provider = self._capability_outcome_stats
        self.executor = executor
        self.notifier = notifier
        self.budget = budget or InterruptBudget()
        self.delivery_broker = delivery_broker or getattr(self.budget, "delivery_broker", None)
        self.audit = audit
        self.prefs = prefs
        # O26-P0.7 (F3): the executor seam honors the global kill-switch
        # KERNEL-INDEPENDENTLY — before this, engaging the halt did not stop an
        # already-approved broker task from executing on a default install.
        self._kill_switch = kill_switch
        import time as _time

        self._clock = clock or _time.time
        # Q6: TTL for the stuck-RUNNING reaper; <=0 disables it.
        self.running_ttl_seconds = float(running_ttl_seconds)
        # Strong refs to fire-and-forget push tasks so they aren't GC'd mid-flight.
        self._bg_tasks: set = set()
        # E5.0 — the work-run ledger, when company mode has one. A seam rather
        # than a constructor argument: the worker predates company mode and must
        # keep working with no ledger at all, which is also the default.
        self.work_run_ledger = None
        self.approval_judge = None
        self._mediation_kernel = kernel
        self._mediation_signer = mediation_signer or DetachedHMACSigner(None)
        self._mediation_clock_ms = mediation_clock_ms or (lambda: int(time.time() * 1000))
        self._mediation_receipt_ttl_ms = int(mediation_receipt_ttl_ms)
        self._execution_context = ContextVar(
            f"autonomy_mediated_execution_{id(self)}", default=None
        )

    def attach_approval_judge(self, judge, *, loop=None, capacity=None, audit=None) -> None:
        """Bind an optional advisory adapter, independent of all task authority."""
        from .task_approval_judge import TaskApprovalJudge

        adapter = TaskApprovalJudge(self.queue)
        adapter.attach_judge(judge, loop=loop, capacity=capacity)
        adapter.attach_audit(audit)
        self.approval_judge = adapter

    def _schedule_approval_judge(self, task: Task) -> None:
        adapter = self.approval_judge
        if adapter is not None:
            adapter.schedule(task.id)

    def bind_mediation(self, kernel, signer: DetachedHMACSigner | None) -> None:
        """Bind the existing Action Kernel and detached owner signer to this worker."""

        from ..kernel.binding import MediationKernelBridge

        if kernel is not None and not isinstance(kernel, MediationKernelBridge):
            kernel = MediationKernelBridge(kernel)
        self._mediation_kernel = kernel
        self._mediation_signer = signer or DetachedHMACSigner(None)

    def kernel_gate(self, action, capability=None, budget=None):
        """Broker-facing kernel hook that preserves the exact decision for enqueue."""

        kernel = self._mediation_kernel
        if not callable(kernel):
            raise RuntimeError("action kernel is unavailable")
        from ..kernel import Action

        origin = self._effective_origin(getattr(action, "origin", "generated"))
        payload, _tainted = self._mark_payload_for_origin(getattr(action, "payload", None), origin)
        finalized_action = Action(
            kind=action.kind,
            agent=action.agent,
            title=action.title,
            payload=payload,
            scope=action.scope,
            origin=origin,
        )
        decision = kernel(finalized_action, capability=capability, budget=budget)
        try:
            from ..kernel import Verdict

            if (
                decision.verdict is Verdict.DENY
                and self.queue.mediation_mode in {"enforce", "hold"}
                and self.queue.classify_mediation(finalized_action.kind) is not False
            ):
                self.queue.record_mediation_refusal(finalized_action.kind)
        except Exception:
            logger.warning("could not persist kernel refusal evidence", exc_info=True)
        return decision

    def execution_allowed(self, task: Task) -> bool:
        """Guard a TaskExecutor call with the worker's private validated-claim context."""

        if self.queue.mediation_mode == "off":
            return True
        persisted, mediated = self.queue.execution_snapshot(
            getattr(task, "id", 0), presented_kind=getattr(task, "kind", "")
        )
        persisted_fingerprint = (
            TaskQueue.execution_fingerprint(persisted) if persisted is not None else None
        )
        presented_fingerprint = TaskQueue.execution_fingerprint(task)
        if (
            persisted is None
            or not persisted_fingerprint
            or persisted_fingerprint != presented_fingerprint
        ):
            return False
        if not mediated:
            return True
        if self.queue.mediation_mode != "enforce":
            return False
        permit = self._execution_context.get()
        return isinstance(permit, _ExecutionPermit) and permit.consume(
            task, validate=self.queue.validate_mediated_execution
        )

    def _kernel_action(self, agent: str, kind: str, title: str, payload: dict, origin: str):
        from ..kernel import Action

        return Action(
            kind=kind,
            agent=agent,
            title=title,
            payload=payload,
            scope="global",
            origin=origin,
        )

    def _kernel_decision(self, action):
        from ..kernel import Decision, Verdict, kernel_enabled

        if not kernel_enabled() or not callable(self._mediation_kernel):
            return None
        try:
            consume = getattr(self._mediation_kernel, "consume", None)
            decision = consume(action) if callable(consume) else None
            if decision is None:
                decision = self._mediation_kernel(action)
                decision = consume(action) if callable(consume) else decision
            return self._validated_kernel_decision(decision, Decision, Verdict)
        except Exception:
            logger.warning("Action Kernel mediation failed closed", exc_info=True)
            return None

    @staticmethod
    def _validated_kernel_decision(decision, decision_type=None, verdict_type=None):
        if decision_type is None or verdict_type is None:
            from ..kernel import Decision as decision_type
            from ..kernel import Verdict as verdict_type

        if not isinstance(decision, decision_type) or decision.verdict not in {
            verdict_type.DENY,
            verdict_type.QUEUE,
            verdict_type.GRANT,
        }:
            return None
        if decision.verdict is not verdict_type.DENY and (
            isinstance(decision.tier, bool)
            or not isinstance(decision.tier, int)
            or not 0 <= decision.tier <= int(RiskTier.IRREVERSIBLE_OR_MONEY)
        ):
            return None
        return decision

    def _action_and_decision_for_enqueue(
        self, *, agent: str, kind: str, title: str, payload: dict, origin: str
    ):
        from ..kernel import kernel_enabled
        from ..kernel.binding import MediationDecisionMismatch

        kernel = self._mediation_kernel
        consume = getattr(kernel, "take_intake_evidence", None)
        try:
            if not kernel_enabled():
                if callable(consume):
                    consume(agent=agent, kind=kind, title=title, payload=payload, origin=origin)
                action = self._kernel_action(agent, kind, title, payload, origin)
                return action, None
            if callable(consume):
                pending = consume(
                    agent=agent,
                    kind=kind,
                    title=title,
                    payload=payload,
                    origin=origin,
                )
                if pending is not None:
                    action, decision = pending
                    return action, self._validated_kernel_decision(decision)
        except MediationDecisionMismatch as exc:
            self.queue.record_mediation_refusal(kind)
            raise TaskQueueError("pending kernel decision does not match finalized task") from exc
        action = self._kernel_action(agent, kind, title, payload, origin)
        try:
            if not callable(kernel):
                return action, None
            decision = kernel(action)
            if callable(consume):
                pending = consume(
                    agent=agent, kind=kind, title=title, payload=payload, origin=origin
                )
                if pending is not None:
                    taken_action, taken_decision = pending
                    return taken_action, self._validated_kernel_decision(taken_decision)
            return action, self._validated_kernel_decision(decision)
        except MediationDecisionMismatch as exc:
            self.queue.record_mediation_refusal(kind)
            raise TaskQueueError("pending kernel decision does not match finalized task") from exc
        except Exception:
            logger.warning("Action Kernel mediation failed closed", exc_info=True)
            return action, None

    @staticmethod
    def _apply_kernel_floor(kernel_decision, tier: int, effective: str) -> tuple[int, str]:
        if kernel_decision is None:
            return tier, effective
        from ..kernel import Verdict

        tier = max(tier, int(kernel_decision.tier or 0))
        if kernel_decision.verdict is Verdict.QUEUE:
            effective = ASK
        return tier, effective

    def _classified_mediated_enqueue(
        self,
        *,
        action,
        decision,
        payload: dict,
        risk_tier: int,
        autonomy_level: str,
        attention_mode: str,
        approval_deadline_at: str | None = None,
    ) -> int:
        from ..kernel import Verdict

        if decision is None:
            self.queue.record_mediation_refusal(action.kind)
            raise TaskQueueError("classified task mediation authority is unavailable")
        if decision.verdict is Verdict.DENY:
            self.queue.record_mediation_refusal(action.kind)
            raise TaskQueueError(f"kernel denied classified task: {decision.reason or 'denied'}")
        now_ms = self._mediation_clock_ms()
        enqueue_id = str(uuid.uuid4())
        expectation = ReceiptExpectation(
            enqueue_id=enqueue_id,
            agent=action.agent,
            kind=action.kind,
            title=action.title,
            origin=action.origin,
            scope=action.scope,
            payload=payload,
            effective_tier=risk_tier,
            policy_revision=self.queue.mediation_policy_revision,
            enqueue_revision=1,
        )
        receipt = issue_receipt(
            self._mediation_signer,
            receipt_id=str(uuid.uuid4()),
            expectation=expectation,
            verdict=decision.verdict.value,
            tier=int(decision.tier),
            reason=str(decision.reason or ""),
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + self._mediation_receipt_ttl_ms,
        )
        if receipt is None:
            self.queue.record_mediation_refusal(action.kind)
            raise TaskQueueError("classified task mediation receipt is unavailable")
        return self.queue.enqueue_mediated(
            action.agent,
            action.kind,
            action.title,
            payload,
            receipt=receipt,
            approval_deadline_at=approval_deadline_at,
            scope=action.scope,
            autonomy_level=autonomy_level,
            origin=action.origin,
            attention_mode=attention_mode,
        )

    def _persist_intake_evidence(
        self, task_id: int, action, decision, payload: dict, task_tier: int
    ) -> None:
        if action is None or decision is None:
            return
        try:
            from ..kernel import Verdict

            if decision.verdict not in {Verdict.GRANT, Verdict.QUEUE}:
                return
            evidence = issue_intake_evidence(
                self._mediation_signer,
                intake_id=str(uuid.uuid4()),
                agent=action.agent,
                kind=action.kind,
                title=action.title,
                origin=action.origin,
                payload=payload,
                verdict=decision.verdict.value,
                tier=int(decision.tier),
                task_tier=task_tier,
                issued_at_ms=self._mediation_clock_ms(),
                task_id=task_id,
            )
            if evidence is not None and self.queue.attach_kernel_intake_evidence(task_id, evidence):
                return
        except Exception:
            logger.warning("could not seal QA4 intake evidence", exc_info=True)
            return
        logger.warning("could not persist QA4 intake evidence")

    def _halted(self, scope: Optional[str] = None) -> bool:
        if self._kill_switch is None:
            try:
                from ..security.capability import KillSwitch

                self._kill_switch = KillSwitch()
            except Exception:
                return False
        try:
            if scope is None:
                return bool(self._kill_switch.is_halted())
            return bool(self._kill_switch.is_halted(scope))
        except Exception:
            return False

    def _reap_stuck(self) -> int:
        """Fail tasks stranded in RUNNING by a crash, past the TTL (Q6)."""
        ttl = float(getattr(self, "running_ttl_seconds", 0.0) or 0.0)
        if ttl <= 0:
            return 0
        try:
            reaped = self.queue.reap_stuck_running(ttl, now=self._clock())
        except Exception:
            logger.warning("stuck-running reaper failed", exc_info=True)
            return 0
        for task in reaped:
            self._audit(
                "autonomy.reaped", task, f"stuck in running > {int(ttl)}s — failed by the reaper"
            )
        return len(reaped)

    # O26-P0.7 (F3): the governed intake brokers use as their enqueue sink.
    # Before this, social/writeback/call/node/tool-rpc proposals went straight
    # to TaskQueue.enqueue as status='proposed' — bypassing the risk policy
    # (AUTO/ASK/OFF dial + money caps) AND invisible to the decision inbox
    # (pending_decisions filtered status='blocked' only).
    _LEVEL_RANK = {ACT: 0, NOTIFY: 1, ASK: 2}

    def _effective_origin(self, origin: str | None) -> str:
        explicit = str(origin or "generated")
        try:
            active = current_action_origin()
        except Exception:
            active = explicit
        if taint.is_untrusted_source(active):
            return active
        if taint.is_untrusted_source(explicit):
            return explicit
        return explicit or "generated"

    def _mark_payload_for_origin(self, payload: dict | None, origin: str) -> tuple[dict, bool]:
        # This legacy caller-controlled marker has no authority and must never
        # enter a signed QA4 payload digest or a persisted task payload.
        clean_payload = dict(payload or {})
        clean_payload.pop("kernel_mediation", None)
        marked = taint.mark_if_untrusted(clean_payload, origin)
        return marked, taint.is_tainted(marked)

    def _has_valid_b7_receipt(self, task: Task) -> bool:
        """Exempt only a receipt the B7 execution boundary reauthenticates."""

        fingerprint = TaskQueue.execution_fingerprint(task)
        try:
            return bool(fingerprint) and self.queue.validate_mediated_execution(task, fingerprint)
        except MediationStateUnavailable:
            # Not exempt (round 6, item 2): an unreadable store proves no receipt, and
            # this observation never changes the task's execution.
            return False

    def _observe_qa4_intake(self, task: Task) -> None:
        """Record missing QA4 evidence, while leaving task execution unchanged."""

        if self._has_valid_b7_receipt(task):
            return
        if self.queue.validate_kernel_intake_evidence(
            task, self._mediation_signer, now_ms=self._mediation_clock_ms()
        ):
            return
        try:
            from ..kernel.metrics import KERNEL_METRICS

            KERNEL_METRICS.record_ungoverned(task.kind)
        except Exception:
            logger.warning("QA4 intake observation failed", exc_info=True)

    def _policy_action(
        self,
        agent: str,
        kind: str,
        payload: dict | None,
        origin: str,
    ) -> dict:
        """Build a policy view with server-owned identity fields authoritative."""
        action = dict(payload or {})
        action.pop("risk_tier", None)
        action["agent"] = agent
        action["kind"] = kind
        action["origin"] = origin
        return action

    @staticmethod
    def _normalize_trusted_tier(tier_floor: int | RiskTier | None) -> tuple[int | None, bool]:
        """Normalize a server-owned tier floor; invalid values fail closed."""
        if tier_floor is None:
            return None, False
        if isinstance(tier_floor, bool):
            return int(RiskTier.IRREVERSIBLE_OR_MONEY), True
        if isinstance(tier_floor, RiskTier):
            return int(tier_floor), False
        if isinstance(tier_floor, int) and 0 <= tier_floor <= int(RiskTier.IRREVERSIBLE_OR_MONEY):
            return tier_floor, False
        return int(RiskTier.IRREVERSIBLE_OR_MONEY), True

    def _policy_accepts_tier_floor(self) -> bool:
        """Detect legacy policy doubles without swallowing policy failures."""
        try:
            parameters = inspect.signature(self.policy.decide).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD or parameter.name == "tier_floor"
            for parameter in parameters
        )

    def _policy_decision(
        self,
        action: dict,
        tier_floor: int | RiskTier | None,
    ) -> tuple[object, int, bool]:
        """Call new and legacy policy interfaces without weakening a tier floor."""
        trusted_tier, invalid_tier = self._normalize_trusted_tier(tier_floor)
        if self._policy_accepts_tier_floor():
            decision = self.policy.decide(action, tier_floor=tier_floor)
        else:
            decision = self.policy.decide(action)

        try:
            decided_tier = int(decision.tier)
        except (AttributeError, TypeError, ValueError):
            return decision, int(RiskTier.IRREVERSIBLE_OR_MONEY), True
        if not 0 <= decided_tier <= int(RiskTier.IRREVERSIBLE_OR_MONEY):
            return decision, int(RiskTier.IRREVERSIBLE_OR_MONEY), True

        effective_tier = max(decided_tier, trusted_tier or 0)
        must_ask = invalid_tier or (trusted_tier is not None and decided_tier < trusted_tier)
        return decision, effective_tier, must_ask

    def _strictest_level(self, requested: str, decided: str) -> str:
        rank = self._LEVEL_RANK
        return requested if rank.get(requested, 2) >= rank.get(decided, 2) else decided

    def _force_ask_for_taint(self, level: str, tainted: bool) -> str:
        return ASK if tainted and level in (ACT, NOTIFY) else level

    def _capability_outcome_stats(self, kind: str) -> dict | None:
        """Resolve a non-spoofable policy confidence input from the durable ledger."""
        try:
            from agents.core.capability_manifests import manifest_for_action

            manifest = manifest_for_action(str(kind or ""))
            stats = getattr(self.queue, "capability_outcome_stats", None)
            if manifest is not None and callable(stats):
                return stats(manifest.id)
        except Exception:
            logger.warning("capability outcome lookup failed closed", exc_info=True)
        return None

    def govern_enqueue(
        self,
        agent: str,
        kind: str,
        title: str,
        payload: dict = None,
        risk_tier: int = 2,
        autonomy_level: str = ASK,
        origin: str = "generated",
        attention_mode: str = "interrupt",
    ) -> int:
        """Sync governed intake (drop-in for ``TaskQueue.enqueue``).

        Runs ``policy.decide`` and applies the STRICTER of the caller's
        requested level and the policy outcome (a broker's always-ask can
        never be weakened; a kernel-granted ``act`` can still be tightened
        by the policy's money caps). ``ask`` tasks land BLOCKED so they enter
        the decision inbox; the Telegram push is best-effort (scheduled when
        an event loop is running, else the card waits in the inbox).
        """
        origin = self._effective_origin(origin)
        proposed_payload = payload or {}
        payload, tainted = self._mark_payload_for_origin(proposed_payload, origin)
        classification = self.queue.classify_mediation(kind)
        mediated = self.queue.mediation_mode in {"enforce", "hold"} and classification is not False
        action = kernel_decision = None
        if mediated and (self.queue.mediation_mode != "enforce" or classification is not True):
            return self.queue.enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=proposed_payload,
                risk_tier=risk_tier,
                autonomy_level=autonomy_level,
                origin=origin,
                attention_mode=attention_mode,
            )
        if mediated or self._mediation_kernel is not None:
            action, kernel_decision = self._action_and_decision_for_enqueue(
                agent=agent, kind=kind, title=title, payload=payload, origin=origin
            )
        try:
            decision, tier, must_ask = self._policy_decision(
                self._policy_action(agent, kind, payload, origin),
                risk_tier,
            )
        except Exception as exc:
            if mediated:
                self.queue.record_mediation_refusal(kind)
                raise TaskQueueError("classified task policy is unavailable") from exc
            raise
        effective = self._strictest_level(autonomy_level, decision.outcome)
        if must_ask:
            effective = ASK
        effective = self._force_ask_for_taint(effective, tainted)
        if mediated:
            tier, effective = self._apply_kernel_floor(kernel_decision, tier, effective)
        elif kernel_decision is not None:
            from ..kernel import Verdict

            if kernel_decision.verdict is Verdict.QUEUE:
                effective = ASK
        if mediated:
            task_id = self._classified_mediated_enqueue(
                action=action,
                decision=kernel_decision,
                payload=payload,
                risk_tier=tier,
                autonomy_level=effective,
                attention_mode=attention_mode,
            )
        else:
            task_id = self.queue.enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=payload,
                risk_tier=tier,
                autonomy_level=effective,
                origin=origin,
                attention_mode=attention_mode,
            )
            self._persist_intake_evidence(task_id, action, kernel_decision, payload, tier)
        if effective in (ACT, NOTIFY):
            task = self.queue.transition(
                task_id,
                TaskStatus.APPROVED,
                decided_by="policy",
                decision=f"auto-{effective}",
            )
            self._audit("autonomy.auto_approve", task, decision.reason)
            return task_id
        task = self.queue.transition(
            task_id,
            TaskStatus.BLOCKED,
            decided_by="policy",
            decision="needs-approval",
            expected_status=TaskStatus.PROPOSED,
        )
        # Metadata cannot turn a successfully persisted ask into enqueue_failed.
        try:
            from .approval_grouping import current_model_producer
            context = current_model_producer()
            if context is not None and type(self.policy) is AutonomyPolicy:
                policy = {key: getattr(self.policy, key) for key in (
                    'mode', 'agent_modes', 'cap_per_action', 'daily_ceiling',
                    'earned_autonomy_enabled', 'tier_outcomes', '_spent_today',
                )}
                policy['decision'] = decision.to_dict()
                self.queue.register_pending_group(task.id, context=context, policy=policy)
        except Exception:
            logger.warning('model approval grouping unavailable; independent task retained')
        self._schedule_approval_judge(task)
        try:
            import asyncio

            if attention_mode == "interrupt":
                # Keep a reference (else the task can be GC'd mid-flight) and log
                # any failure — otherwise the push exception vanishes silently.
                t = asyncio.get_running_loop().create_task(self._maybe_push(task))
                self._bg_tasks.add(t)
                t.add_done_callback(self._bg_tasks.discard)
                t.add_done_callback(
                    lambda d: (
                        logger.error(
                            "decision push failed: %s", d.exception(), exc_info=d.exception()
                        )
                        if not d.cancelled() and d.exception()
                        else None
                    )
                )
        except RuntimeError:
            logger.debug("no running loop — decision card waits in the inbox")
        return task_id

    # ── intake ────────────────────────────────────────────────────
    async def submit(
        self,
        agent: str,
        kind: str,
        title: str,
        payload: dict = None,
        origin: str = "generated",
        attention_mode: str = "interrupt",
        risk_tier: int | None = None,
        *, grouping_context=None, approval_deadline_at: str | None = None,
    ) -> Task:
        """Propose a task, gate it through the policy, and route it."""
        origin = self._effective_origin(origin)
        proposed_payload = payload or {}
        payload, tainted = self._mark_payload_for_origin(proposed_payload, origin)
        classification = self.queue.classify_mediation(kind)
        mediated = self.queue.mediation_mode in {"enforce", "hold"} and classification is not False
        action = kernel_decision = None
        if mediated and (self.queue.mediation_mode != "enforce" or classification is not True):
            self.queue.enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=proposed_payload,
                risk_tier=risk_tier if risk_tier is not None else 3,
                autonomy_level=ASK,
                origin=origin,
                attention_mode=attention_mode,
            )
            raise TaskQueueError("classified task mediation is unavailable")
        if mediated or self._mediation_kernel is not None:
            action, kernel_decision = self._action_and_decision_for_enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=payload,
                origin=origin,
            )
        try:
            decision, tier, must_ask = self._policy_decision(
                self._policy_action(agent, kind, payload, origin),
                risk_tier,
            )
        except Exception as exc:
            if mediated:
                self.queue.record_mediation_refusal(kind)
                raise TaskQueueError("classified task policy is unavailable") from exc
            raise
        effective = self._force_ask_for_taint(decision.outcome, tainted)
        if must_ask:
            effective = ASK
        if mediated:
            tier, effective = self._apply_kernel_floor(kernel_decision, tier, effective)
        elif kernel_decision is not None:
            from ..kernel import Verdict

            if kernel_decision.verdict is Verdict.QUEUE:
                effective = ASK
        if mediated:
            task_id = self._classified_mediated_enqueue(
                action=action,
                decision=kernel_decision,
                payload=payload,
                risk_tier=tier,
                autonomy_level=effective,
                attention_mode=attention_mode,
                approval_deadline_at=approval_deadline_at if effective == ASK else None,
            )
        else:
            task_id = self.queue.enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=payload,
                risk_tier=tier,
                autonomy_level=effective,
                origin=origin,
                attention_mode=attention_mode,
                approval_deadline_at=approval_deadline_at if effective == ASK else None,
            )
            self._persist_intake_evidence(task_id, action, kernel_decision, payload, tier)

        if effective in (ACT, NOTIFY):
            task = self.queue.transition(
                task_id,
                TaskStatus.APPROVED,
                decided_by="policy",
                decision=f"auto-{effective}",
            )
            self._audit("autonomy.auto_approve", task, decision.reason)
            return task

        # ASK → block, then push a decision card if budget allows.
        task = self.queue.transition(
            task_id,
            TaskStatus.BLOCKED,
            decided_by="policy",
            decision="needs-approval",
        )
        if grouping_context is not None and type(self.policy) is AutonomyPolicy:
            policy = {key: getattr(self.policy, key) for key in (
                'mode', 'agent_modes', 'cap_per_action', 'daily_ceiling',
                'earned_autonomy_enabled', 'tier_outcomes', '_spent_today',
            )}
            policy['decision'] = decision.to_dict()
            self.queue.register_pending_group(task.id, context=grouping_context, policy=policy)
        self._schedule_approval_judge(task)
        if attention_mode == "interrupt":
            await self._maybe_push(task)
        return task

    async def _maybe_push(self, task: Task, *, delivery_id: str | None = None) -> bool:
        if not self.notifier:
            return False
        from .inbox import is_decision_notification_leader

        if not is_decision_notification_leader(self.queue, task):
            return False
        if self.delivery_broker is None:
            logger.warning(
                "Decision push held for #%s: durable delivery broker unavailable",
                task.id,
            )
            return False
        result = await self.delivery_broker.dispatch(
            delivery_id or f"task-{task.id}",
            "decision_push",
            lambda: self.notifier(task),
        )
        ok = result.get("status") == "delivered"
        if ok:
            self.queue.mark_pushed(task.id)
            self._audit("autonomy.push_decision", task, "pushed to inbox")
        elif result.get("status") == "downgraded":
            logger.info("Interrupt budget exhausted — task #%s held for daily review", task.id)
        else:
            logger.warning("Decision push failed for #%s: %s", task.id, result.get("reason"))
        return ok

    # ── execution ─────────────────────────────────────────────────
    def _current_expiry_task(self, effect):
        task = self.queue.get(effect.task_id)
        return task if (task is not None and task.status == TaskStatus.EXPIRED.value
                        and task.expired_at == effect.expired_at) else None

    def _clear_expiry_judges(self, batch) -> set[int]:
        cleared = set()
        if self.approval_judge is not None:
            for effect in batch.effects:
                try:
                    if self._current_expiry_task(effect) is not None:
                        self.approval_judge.clear_pending(effect.task_id)
                        cleared.add(effect.task_id)
                except Exception:
                    logger.warning("Expired judge pending cleanup held for #%s", effect.task_id, exc_info=True)
        return cleared

    async def _drain_approval_expiry(self, batch, *, limit=100, notify_promotions=True,
                                    already_cleared=frozenset()) -> int:
        from agents.core.env_config import env_flag

        from .pending_requests import FLAG, PendingRequests
        from .queue import ApprovalExpiryBatch, approval_is_pending

        def ack(effect, task=None):
            one = ApprovalExpiryBatch((task,) if task is not None else (),
                                      (effect.group_id,) if effect.group_id else (), effects=(effect,))
            return self.queue.ack_approval_expiry_effects(one)

        acknowledged = 0
        for effect in batch.effects:
            if self._halted():
                break
            try:
                # Batch rows are detached evidence, never fresh authorization.
                task = self._current_expiry_task(effect)
                if task is None:
                    acknowledged += ack(effect)
                    continue
                if self.approval_judge is not None and task.id not in already_cleared:
                    self.approval_judge.clear_pending(task.id)
                if self.audit is not None:
                    self.audit.log("autonomy.approval.expired", {
                        "task_id": task.id, "agent": task.agent, "kind": task.kind,
                        "expired_at": effect.expired_at, "resolution": "expired_unanswered",
                    })
                if self._current_expiry_task(effect) is None:
                    acknowledged += ack(effect)
                    continue
                ledger = self.work_run_ledger
                if ledger is not None:
                    # This ledger can be attached for read-only past-run access
                    # even while company mode is disabled. Keep relevant effects.
                    sources = ledger.pending_asks_for_task(task.id, limit=limit)
                    if sources and not env_flag(FLAG):
                        continue
                    reconciler = PendingRequests(ledger, read_task=self.queue.get)
                    for source in sources:
                        if not env_flag(FLAG):
                            break
                        reconciler.reconcile(source.run_id)
                    if ledger.pending_asks_for_task(task.id, limit=1):
                        continue
                if self._current_expiry_task(effect) is None:
                    acknowledged += ack(effect)
                    continue
                if notify_promotions and effect.group_id is not None:
                    candidate = self.queue.pending_group_leader(effect.group_id)
                    if (self.notifier is not None and candidate
                            and candidate.attention_mode == "interrupt" and not candidate.pushed
                            and (not approval_is_pending(candidate) or not await self._maybe_push(candidate))):
                        continue
                acknowledged += ack(effect, task)
            except Exception:
                logger.warning("Approval expiry effects held for #%s", effect.task_id, exc_info=True)
        return acknowledged

    async def approval_housekeeping(self, *, limit: int = 100, now=None,
                                    reconcile: bool = True, notify_promotions: bool = True) -> dict:
        """Sweep metadata and clear judges; other effects stay held under e-stop."""
        from datetime import datetime

        now = now or datetime.fromtimestamp(self._clock(), UTC)
        changed = self.queue.expire_pending_approvals(now=now, limit=limit)
        cleared = self._clear_expiry_judges(changed)
        result = {"expired": len(changed.tasks), "expiry_effects_acked": 0}
        if not reconcile or self._halted():
            return result
        batch = self.queue.pending_approval_expiry_effects(limit=limit)
        result["expiry_effects_acked"] = await self._drain_approval_expiry(
            batch, limit=limit, notify_promotions=notify_promotions, already_cleared=cleared,
        )
        return result

    async def _consume_committed_expiry(self, batch) -> None:
        cleared = self._clear_expiry_judges(batch)
        if not self._halted():
            await self._drain_approval_expiry(batch, already_cleared=cleared)

    async def tick(self, limit: int = 10, max_tier: Optional[int] = None) -> dict:
        """Run approved tasks. Returns a small summary dict.

        `max_tier` caps which risk tiers run this pass — used by the night shift
        to batch only reversible/read-only work (max_tier=1).
        """
        ran = done = failed = held = 0
        await self.approval_housekeeping(limit=limit, reconcile=not self._halted())
        # Q6: reap crash-stranded RUNNING tasks first — bookkeeping, not an
        # action, so it runs even under a halt (the stuck state is honest).
        reaped = 0 if self.queue.mediation_mode == "hold" else self._reap_stuck()
        # O26-P0.7 (F3): an engaged kill-switch stops execution at THIS seam,
        # kernel-independently — approved tasks stay approved (nothing is lost)
        # and run on the first tick after release.
        if self._halted():
            logger.warning("kill-switch engaged — autonomy tick skipped (tasks held)")
            return {"ran": 0, "done": 0, "failed": 0, "halted": True, "held": 0, "reaped": reaped}
        for task in self.queue.runnable(limit=limit, max_tier=max_tier):
            # Q6: a per-agent halt (scope = the agent's name, ch07 GOV-178)
            # holds that agent's tasks at this same kernel-independent seam —
            # they stay APPROVED and run on the first tick after release.
            if self._halted(task.agent):
                held += 1
                continue
            if self.queue.mediation_mode == "off":
                mediated = False
            else:
                persisted, mediated = self.queue.execution_snapshot(
                    task.id, presented_kind=task.kind
                )
                if persisted is None:
                    held += 1
                    continue
                task = persisted
            if mediated and self.queue.mediation_mode == "hold":
                held += 1
                continue
            if mediated and task.mediation_scope and self._halted(task.mediation_scope):
                held += 1
                continue
            if mediated:
                claimed = self.queue.claim_mediated(task.id, execution_id=str(uuid.uuid4()))
                if claimed is None:
                    continue
                task = claimed
            else:
                self.queue.transition(task.id, TaskStatus.RUNNING)
                task = self.queue.get(task.id)
            ran += 1
            attempts = self.queue.increment_attempts(task.id)
            # Bind the permit to the exact durable snapshot after the attempt
            # counter/update timestamp mutation and before handler dispatch.
            task = self.queue.get(task.id)
            if self.queue.mediation_mode != "off":
                persisted, still_mediated = self.queue.execution_snapshot(
                    task.id, presented_kind=task.kind
                )
                fingerprint = TaskQueue.execution_fingerprint(task)
                valid = (
                    persisted is not None
                    and still_mediated == mediated
                    and fingerprint is not None
                    and TaskQueue.execution_fingerprint(persisted) == fingerprint
                    and persisted.status == TaskStatus.RUNNING.value
                )
                unreadable = False
                if valid and mediated:
                    try:
                        valid = self.queue.validate_mediated_execution(task, fingerprint)
                    except MediationStateUnavailable:
                        # The store could not be read (round 6, item 2): the task fails
                        # before any handler, as a refused validation does, and says why.
                        valid, unreadable = False, True
                if not valid:
                    if mediated:
                        self.queue.transition(
                            task.id,
                            TaskStatus.FAILED,
                            result={"error": "mediation state unavailable" if unreadable
                                    else "mediation execution validation failed"},
                        )
                        failed += 1
                    else:
                        self.queue.transition(task.id, TaskStatus.APPROVED)
                        held += 1
                    continue
                task = persisted
            self._observe_qa4_intake(task)
            # Round 4, item 1: the failed attempts before this one, as the retry that
            # followed each recorded them on the task (durable across workers). Round 5:
            # whether an earlier attempt already recorded the task's outcome (item 3),
            # and whether this attempt exercises the kind's capability at all (item 9).
            earlier_failures = _earlier_failed_attempts(task)
            recorded_before = _outcome_already_recorded(task)
            records = not recorded_before and self._exercises_capability(task)
            final = mediated or attempts >= MAX_ATTEMPTS
            execution_permit = _ExecutionPermit(task) if mediated else None
            execution_token = self._execution_context.set(execution_permit)
            try:
                try:
                    result = await self._execute(task)
                    if result.get("status") == "refused" and result.get("reason") == (
                        "mediation_execution_context_required"
                    ):
                        raise _guard_refusal(result)
                except Exception as e:
                    # The capability's handler raised: a failed attempt, unless its
                    # reason is a refusal of this kind.
                    if final:
                        self.queue.transition(task.id, TaskStatus.FAILED, result=_failure_record(e))
                        if records:
                            self._record_capability_outcome(task, success=False, error=e,
                                                            earlier_failures=earlier_failures)
                        self._audit("autonomy.failed", task, f"giving up after {attempts}: {e}")
                        failed += 1
                    else:
                        # Back to approved for another attempt. An attempt that broke is
                        # counted on the task, so a retry that then refuses still records
                        # the failure (round 4, item 1).
                        failures = earlier_failures + (
                            0 if is_refusal_reason(task.kind, getattr(e, "reason", None)) else 1)
                        self.queue.transition(
                            task.id, TaskStatus.APPROVED,
                            result=_retry_record(e, failures=failures, recorded=recorded_before),
                        )
                        logger.info(f"Task #{task.id} failed (attempt {attempts}), will retry: {e}")
                    continue
                try:
                    self.queue.transition(task.id, TaskStatus.DONE, result=result)
                except Exception as e:
                    # The handler returned; the WORKER's own bookkeeping raised (round 5,
                    # item 3). Not an attempt of the capability that broke: this
                    # attempt's own outcome is recorded now — a success once, marked on
                    # the task so no later attempt records again — and the task is
                    # retried or failed as any attempt whose DONE could not be written.
                    if final:
                        self.queue.transition(task.id, TaskStatus.FAILED, result=_failure_record(e))
                        if records:
                            self._record_capability_outcome(task, success=True, result=result,
                                                            earlier_failures=earlier_failures)
                        self._audit("autonomy.failed", task, f"giving up after {attempts}: {e}")
                        failed += 1
                    else:
                        outcome = (self._attempt_outcome(task, success=True, result=result,
                                                         error=None) if records else None)
                        if outcome is True:
                            self._record_capability_outcome(task, success=True, result=result)
                        self.queue.transition(
                            task.id, TaskStatus.APPROVED,
                            result=_retry_record(
                                e, failures=earlier_failures + (outcome is False),
                                recorded=recorded_before or outcome is True),
                        )
                        logger.info(f"Task #{task.id} ran (attempt {attempts}) but could not "
                                    f"be marked done, will retry: {e}")
                    continue
                if records:
                    self._record_capability_outcome(task, success=True, result=result,
                                                    earlier_failures=earlier_failures)
                self._settle_spend(task)
                self._audit("autonomy.done", task, "executed")
                done += 1
            finally:
                if execution_permit is not None:
                    execution_permit.revoke()
                self._execution_context.reset(execution_token)
        return {"ran": ran, "done": done, "failed": failed, "held": held, "reaped": reaped}

    def _exercises_capability(self, task: Task) -> bool:
        """False when the injected executor says no handler of its own is registered for
        the task's kind (``TaskExecutor.handles``): it would run the task through its
        generic fallback — the LLM pipeline — so the capability the kind's manifest names
        is not exercised and nothing is recorded for it (review round 5, item 9). An
        executor that cannot say is taken at its word: its result is the capability's."""
        handles = getattr(getattr(self.executor, "__self__", None), "handles", None)
        return not callable(handles) or handles(task.kind) is not False

    async def _execute(self, task: Task) -> dict:
        if self.executor is None:
            # No executor wired → no-op success so the loop is observable.
            return {"status": "noop", "note": "no executor configured"}
        if self.queue.mediation_mode == "off":
            return await self.executor(task)
        dispatch_task = TaskQueue.detach_execution_task(task)
        if dispatch_task is None:
            raise TaskQueueError("could not snapshot execution task")
        return await self.executor(dispatch_task)

    def _settle_spend(self, task: Task) -> None:
        amount = task.payload.get("amount") if task.payload else None
        if amount:
            try:
                self.policy.record_spend(float(amount))
            except (TypeError, ValueError):
                pass

    def _record_capability_outcome(
        self,
        task: Task,
        *,
        success: bool,
        result: dict | None = None,
        error: BaseException | None = None,
        earlier_failures: int = 0,
    ) -> None:
        """Record one terminal REAL execution; ignore no-ops, mocks, refusals and unknown actions.

        ADV-094 (adversarial audit 2026-07-25): this skipped only a literal
        ``status == "noop"``, while ``is_degraded()`` — which recognises the ``_mock`` /
        ``_degraded`` markers every mock-falling-back plugin stamps on its return — had
        zero production callers. So a capability that returned a MOCK recorded a success,
        and ``GET /api/capabilities`` showed ``success_rate: 1.0`` and rising confidence
        for capabilities that had never delivered anything.

        Grade it as the audit did, and the correction matters: this is a misleading
        dashboard, NOT a live loosening of governance. The claimed autonomy escalation
        does not occur — every degraded seam hardcodes ``autonomy_level = "ask"`` and
        ``govern_enqueue`` takes the stricter of the two — so a rising score could not
        widen what an agent may do. It could only mislead the human reading the board.

        Review F2 (Codex sprint): handlers report a refusal or an apply error as a
        returned dict, not an exception, and the worker moves any returned dict to DONE.
        A ``refused`` result executed nothing (a machine decider, a card changed since
        the request, a gate that was off), so it records nothing; a ``failed`` result
        is a failure, never a success.

        Review round 2 (MINOR 2): many handlers return a refusal as ``failed`` too (a
        spent interrupt budget, a kernel denial, a missing credential), and the house
        handler raises one. :func:`is_refusal` / :data:`REFUSAL_REASONS_BY_KIND` name
        those, per kind (round 4), so a refusal records nothing whichever shape it
        takes; every other ``failed`` result, and every other raised error, is a
        failure. A result governance withheld after the capability ran
        (:func:`is_withheld`) records nothing either.

        Review round 4 (item 1): the outcome is the TASK's, over all its attempts. When
        this final attempt would record nothing but *earlier_failures* attempts of the
        task broke, it records one failure.

        Review round 5: the caller records at most one outcome per task (item 3 — an
        attempt whose DONE transition raised records its own outcome then and marks the
        task), and none for a task the executor ran through its generic fallback (item
        9); a success needs an explicit success status (item 8, :meth:`_attempt_outcome`).
        """
        outcome = self._attempt_outcome(task, success=success, result=result, error=error)
        if outcome is None and earlier_failures > 0:
            outcome = False
        if outcome is None:
            return
        try:
            from agents.core.capability_manifests import manifest_for_action

            manifest = manifest_for_action(task.kind)
            record = getattr(self.queue, "record_capability_outcome", None)
            if manifest is not None and callable(record):
                record(manifest.id, success=outcome)
        except Exception:
            logger.warning("capability outcome record failed", exc_info=True)

    @staticmethod
    def _attempt_outcome(
        task: Task,
        *,
        success: bool,
        result: dict | None,
        error: BaseException | None,
    ) -> bool | None:
        """What this attempt alone says: True a success, False a failure, None nothing
        to record (a no-op, a refusal, a result governance withheld, a mock).

        A success is explicit (review round 5, item 8): a status a handler uses for one
        (:data:`SUCCESS_STATUSES`), or no status and ``ok: True``. Any other returned
        status — ``unknown``, one nobody listed — is a failure."""
        if success:
            if not isinstance(result, dict):
                return False
            status = result.get("status")
            if status == "noop" or is_refusal(task.kind, result) or is_withheld(task.kind, result):
                return None
            from agents.core.plugins.degradation import is_degraded, nested_degraded

            if is_degraded(result):
                logger.debug("capability outcome skipped: degraded/mock result for %s", task.kind)
                return None
            if not (status in SUCCESS_STATUSES or (status is None and result.get("ok") is True)):
                return False
            nested = nested_degraded(result)
            if nested is not None:
                # A success status wrapped around a degraded client result (round 6, item
                # 4 — defence in depth; the brokers lift the marker themselves): the work
                # was not done, so it is not a success. Nothing when its reason is a
                # refusal of the kind (a credential or transport this hub has not
                # configured: nothing was attempted), a failure otherwise.
                reason = nested["_degraded"].get("reason") if isinstance(
                    nested.get("_degraded"), dict) else None
                return None if is_refusal_reason(task.kind, reason) else False
            return True
        if error is not None and is_refusal_reason(task.kind, getattr(error, "reason", None)):
            return None
        return False

    # ── human decisions ───────────────────────────────────────────
    async def _push_promoted_group(self, group_id: str | None) -> None:
        if group_id is None:
            return
        try:
            candidate = self.queue.pending_group_leader(group_id)
            if candidate and candidate.attention_mode == 'interrupt' and not candidate.pushed:
                await self._maybe_push(candidate)
        except Exception:
            logger.warning('Promoted decision notification failed for group %s',
                           group_id, exc_info=True)

    async def reject_group(self, group_id: str, *, snapshot: str, member_ids: list[int],
                           decided_by: str = 'admin', reason: str | None = None) -> list[Task] | None:
        from .queue import TaskApprovalExpired

        try:
            return await self._reject_group(group_id, snapshot=snapshot, member_ids=member_ids,
                                            decided_by=decided_by, reason=reason)
        except TaskApprovalExpired as exc:
            await self._consume_committed_expiry(exc.batch)
            return None

    async def _reject_group(self, group_id: str, *, snapshot: str, member_ids: list[int],
                           decided_by: str = 'admin', reason: str | None = None) -> list[Task] | None:
        """Commit an exact group rejection before any per-task observations."""
        rejected = self.queue.reject_pending_group(group_id, snapshot=snapshot, member_ids=member_ids,
                                                   decided_by=decided_by, reason=reason)
        if rejected is None:
            return None
        for task in rejected:
            if self.approval_judge is not None:
                self.approval_judge.clear_pending(task.id)
            self._audit('autonomy.decision.reject', task, f'by {decided_by} (group {group_id})')
            if self.prefs:
                try:
                    self.prefs.record(task, 'reject', decided_by=decided_by)
                except Exception:
                    logger.warning('Preference record failed for #%s', task.id, exc_info=True)
            self._reconcile_waiting_run(task)
        return rejected

    async def apply_decision(
        self, task_id: int, action: str, decided_by: str = "user", payload: dict = None,
        *, reason: str | None = None,
    ) -> Task:
        from .queue import TaskApprovalExpired, approval_is_pending

        try:
            current = self.queue.get(task_id)
            if (action in {"accept", "edit", "reject", "defer"} and current is not None
                    and current.status in {"proposed", "blocked"}
                    and getattr(current, "approval_deadline_at", None) is not None and not approval_is_pending(current)):
                # Also fence paths which refuse mediated edits before reaching
                # their ordinary queue mutation. The queue fresh due CAS wins.
                self.queue.transition_with_group(task_id, TaskStatus(current.status),
                                                 expected_status=TaskStatus(current.status))
            return await self._apply_decision(task_id, action, decided_by, payload, reason=reason)
        except TaskApprovalExpired as exc:
            await self._consume_committed_expiry(exc.batch)
            raise

    async def _apply_decision(
        self, task_id: int, action: str, decided_by: str = "user", payload: dict = None,
        *, reason: str | None = None,
    ) -> Task:
        """Resolve a task; an optional human explanation is separate metadata."""
        from .decision_reasons import normalize_reason

        reason = normalize_reason(reason)
        current = self.queue.get(task_id)
        promotion_group_id = None
        if (
            action == "edit"
            and payload is not None
            and current is not None
            and self.queue.mediation_mode in {"enforce", "hold"}
            and self.queue.classify_mediation(current.kind) is not False
        ):
            raise TaskQueueError("mediated edit requires a new enqueue revision")
        if action == "accept":
            task, promotion_group_id = self.queue.transition_with_group(
                task_id, TaskStatus.APPROVED, decided_by=decided_by, decision="accept",
                human_reason=reason
            )
        elif action == "edit":
            if payload is not None:
                edited = self.queue.get(task_id)
                edited_origin = self._effective_origin(edited.origin)
                marked_payload, tainted = self._mark_payload_for_origin(
                    payload,
                    edited_origin,
                )
                # BUG-11: an edit must not be auto-approved under the *original*
                # (lower-risk) decision. Re-gate the FULL edited payload — not
                # just the amount — so changing kind/target/reversible/risk_tier
                # (e.g. READ_ONLY → an irreversible kind), or an amount under the
                # per-action cap but over the remaining daily ceiling, is caught.
                action_payload = self._policy_action(
                    edited.agent,
                    edited.kind,
                    marked_payload,
                    edited_origin,
                )
                decision, tier, must_ask = self._policy_decision(
                    action_payload,
                    edited.risk_tier,
                )
                effective = self._force_ask_for_taint(decision.outcome, tainted)
                effective = self._strictest_level(edited.autonomy_level, effective)
                if must_ask:
                    effective = ASK
                edited, promotion_group_id = self.queue.update_payload_policy_with_group(
                    task_id,
                    marked_payload,
                    risk_tier=tier,
                    autonomy_level=effective,
                    decided_by=decided_by,
                    human_reason=reason,
                    approve=effective != ASK,
                )
                if effective == ASK:
                    if self.approval_judge is not None:
                        self.approval_judge.clear_pending(task_id)
                    self._schedule_approval_judge(edited)
                    # Edited payload still needs explicit approval — keep the task
                    # in its current BLOCKED state (no transition: BLOCKED→BLOCKED
                    # is illegal) and re-push a fresh decision card to the inbox.
                    logger.warning(
                        "apply_decision: edited payload on task %s still requires "
                        "approval (%s) — kept blocked, re-pushed for re-approval",
                        task_id,
                        decision.reason,
                    )
                    await self._maybe_push(
                        edited,
                        delivery_id=f"task-{edited.id}-edit-{edited.updated_at}",
                    )
                    self._audit(
                        "autonomy.decision.edit", edited, f"by {decided_by} (re-gated, blocked)"
                    )
                    if self.prefs:
                        try:
                            self.prefs.record(edited, action, decided_by=decided_by)
                        except Exception as e:
                            logger.warning(f"Preference record failed for #{task_id}: {e}")
                    await self._push_promoted_group(promotion_group_id)
                    return edited
                task = edited
            else:
                task, promotion_group_id = self.queue.transition_with_group(
                    task_id, TaskStatus.APPROVED, decided_by=decided_by, decision="edit",
                    human_reason=reason,
                )
        elif action == "reject":
            task, promotion_group_id = self.queue.transition_with_group(
                task_id, TaskStatus.REJECTED, decided_by=decided_by, decision="reject",
                human_reason=reason
            )
        elif action == "defer":
            task, promotion_group_id = self.queue.transition_with_group(
                task_id, TaskStatus.DEFERRED, decided_by=decided_by, decision="defer",
                human_reason=reason
            )
        else:
            raise TaskQueueError(f"unknown decision action: {action}")
        if self.approval_judge is not None:
            self.approval_judge.clear_pending(task_id)
        self._audit(f"autonomy.decision.{action}", task, f"by {decided_by}")
        if self.prefs:
            try:
                self.prefs.record(task, action, decided_by=decided_by)
            except Exception as e:
                logger.warning(f"Preference record failed for #{task_id}: {e}")
        # S8 / GAP-0 — time to first governed action. Called on every decision;
        # first_action owns the rules (owner-decided, accepted, once only), so
        # there is one place to read them and no chance of two callers disagreeing.
        # A metric write must never be able to fail a decision that already landed.
        try:
            from agents.core.first_action import record_first_action

            record_first_action(task)
        except Exception:
            logger.debug("activation record skipped", exc_info=True)
        # E5.0 — a company-mode run blocked on this task learns the answer now,
        # rather than on the scheduler's next sweep. Reconciling reads the task's
        # own record, so this hook cannot smuggle in a decision the queue did not
        # make; and like the metric above, it can never fail a decision that has
        # already landed.
        self._reconcile_waiting_run(task)
        await self._push_promoted_group(promotion_group_id)
        return task

    def _reconcile_waiting_run(self, task: Task) -> None:
        """Tell a blocked work run that its ask has been answered. Best effort."""
        ledger = self.work_run_ledger
        if ledger is None:
            return
        try:
            from agents.core.env_config import env_flag

            from .pending_requests import FLAG, PendingRequests

            if not env_flag(FLAG):
                return
            run_id = ledger.run_waiting_on(getattr(task, "id", 0))
            if not run_id:
                return
            PendingRequests(ledger, read_task=self.queue.get).reconcile(run_id)
        except Exception:
            logger.debug("work-run reconcile skipped", exc_info=True)

    # ── audit ─────────────────────────────────────────────────────
    def _audit(self, event: str, task: Task, detail: str) -> None:
        if not self.audit:
            return
        try:
            self.audit.log(
                event,
                {"task_id": task.id, "agent": task.agent, "kind": task.kind, "detail": detail,
                 **({"human_decision": dict(task.human_decision)}
                    if event.startswith("autonomy.decision.") and task.human_decision
                    and task.human_decision.get("reason") else {})},
            )
        except Exception:
            logger.warning(
                "Autonomy audit log failed for event '%s' task #%s", event, task.id, exc_info=True
            )
