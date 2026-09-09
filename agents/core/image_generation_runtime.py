"""Durably approved, single-use local image ToolRPC execution.

The backend transport is reachable only from the MediaGenManager local guard.
Neither a tool argument nor an HTTP request can supply approval authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Mapping
from pathlib import Path

from .media_backends.comfyui import (
    ComfyUIBackend,
    ComfyUIConfig,
    ImageGenerationError,
    validate_options,
)
from .paths import data_path
from .tool_rpc import ToolRPCValidationError

_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
TOOL = "image_generate"
KIND = "tool.rpc"
TITLE = "Tool 'image_generate' via RPC"
INPUT_SCHEMA = {
    "type": "object", "required": ["prompt"], "additionalProperties": False,
    "properties": {
        "prompt": {"type": "string", "minLength": 1, "maxLength": 4000},
        "seed": {"type": "integer", "minimum": 0, "maximum": 2**63 - 1},
        "width": {"type": "integer", "minimum": 64, "maximum": 1024, "multipleOf": 64},
        "height": {"type": "integer", "minimum": 64, "maximum": 1024, "multipleOf": 64},
        "steps": {"type": "integer", "minimum": 1, "maximum": 40},
    },
}


def configuration_status():
    try:
        config = ComfyUIConfig.from_env()
    except ImageGenerationError as exc:
        return {"configured": False, "backend": "comfyui", "reason": exc.reason, "reachable": None}
    return {"configured": config is not None, "backend": "comfyui" if config else "off",
            "reason": "not_probed" if config else "disabled", "reachable": None,
            "local": True, "approval_required": True}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _task_binding(task):
    """Immutable proposal tuple, independent of subsequent worker status changes."""
    return _digest({key: getattr(task, key) for key in (
        "id", "agent", "kind", "title", "payload", "origin", "risk_tier", "autonomy_level",
    )})


def is_image_task(task):
    """Only this image tuple may use the canonical ToolRPC executor."""
    payload = getattr(task, "payload", None)
    return (
        getattr(task, "kind", None) == KIND
        and isinstance(payload, Mapping)
        and payload.get("tool") == TOOL and payload.get("target") == TOOL
    )


def _write_exclusive(path, value):
    # An incomplete file remains a refusal after a crash. It is never erased to
    # create permission for another attempt. No model data selects this path.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())


class LocalImageRuntime:
    def __init__(self, *, queue, approved_task, authorizer, enqueue):
        self._queue = queue
        self._approved_task = approved_task
        self._authorizer = authorizer
        self._enqueue = enqueue

    def _config(self):
        from .kernel import kernel_enabled
        from .system_profiles import heavy_features_enabled
        config = ComfyUIConfig.from_env()
        if config is None:
            raise ImageGenerationError("local_image_disabled")
        if self._authorizer is None or not kernel_enabled():
            raise ImageGenerationError("kernel_required")
        if not heavy_features_enabled():
            raise ImageGenerationError("heavy_features_paused")
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _SOURCE_SHA:
            raise ImageGenerationError("runtime_changed_restart_required")
        return config

    def _head(self, config):
        return _digest({"backend": config.fingerprint(), "runtime": _SOURCE_SHA})

    def _record_path(self, task, suffix):
        binding = task.payload["args"]["_binding"]
        nonce = binding["nonce"]
        if type(task.id) is not int or task.id <= 0 or not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32}", nonce):
            raise ImageGenerationError("invalid_binding")
        return data_path("media", "image_approvals", f"{task.id}-{nonce}.{suffix}")

    def preflight(self, args):
        try:
            config = self._config()
            task = self._approved_task()
            allowed = set(INPUT_SCHEMA["properties"])
            if task is not None:
                allowed.add("_binding")
            if set(args) - allowed:
                raise ImageGenerationError("invalid_args")
            prompt = args.get("prompt")
            options = validate_options(prompt, {k: v for k, v in args.items() if k not in {"prompt", "_binding"}})
            normalized = {"prompt": prompt, **options}
            if task is None:
                if "seed" not in args:
                    normalized["seed"] = secrets.randbits(63)
                normalized["_binding"] = {"nonce": secrets.token_hex(16), "head": self._head(config)}
            else:
                binding = args.get("_binding")
                if not isinstance(binding, dict) or set(binding) != {"nonce", "head"} or binding.get("head") != self._head(config):
                    raise ImageGenerationError("backend_binding_changed")
                normalized["_binding"] = dict(binding)
                if normalized != args:
                    raise ImageGenerationError("approved_payload_changed")
            return normalized
        except ImageGenerationError as exc:
            raise ToolRPCValidationError(exc.reason) from None

    def intake(self, agent, args):
        """Authorize and enqueue the identical full image tuple exactly once."""
        from .action_origin import current_action_origin
        from .kernel import Action, Decision, Verdict
        from .security.taint import mark_if_untrusted

        self._config()
        if self._queue is None:
            raise ImageGenerationError("queue_required")
        origin = current_action_origin()
        payload = mark_if_untrusted({"tool": TOOL, "args": args, "target": TOOL}, origin)
        decision = self._authorizer(Action(
            kind=KIND, agent=agent, title=TITLE, payload=payload, origin=origin,
        ))
        if not isinstance(decision, Decision) or decision.verdict not in {Verdict.GRANT, Verdict.QUEUE}:
            raise ToolRPCValidationError("kernel_denied")
        task_id = self._enqueue(
            agent, KIND, TITLE, payload=payload, risk_tier=2,
            autonomy_level="ask", origin=origin,
        )
        task = self._queue.get(task_id)
        if not is_image_task(task) or task.payload.get("args") != args:
            raise ImageGenerationError("proposal_binding_failed")
        # Bind AFTER governed intake has raised risk/provenance/taint, before the
        # caller receives a task id. A failed write leaves a non-executable row.
        _write_exclusive(self._record_path(task, "proposal"), {"digest": _task_binding(task)})
        return task_id

    def _approval(self, args, config):
        task = self._approved_task()
        if task is None or self._queue is None:
            raise ImageGenerationError("trusted_execution_required")
        persisted = self._queue.get(getattr(task, "id", None))
        if persisted is None or not (
            is_image_task(persisted) and persisted.status == "running"
            and persisted.autonomy_level == "ask"
            and persisted.decision in {"accept", "edit"}
            and persisted.decided_by and str(persisted.decided_by).strip().lower() != "policy"
            and _task_binding(task) == _task_binding(persisted)
            and persisted.payload.get("args") == args
            and args["_binding"]["head"] == self._head(config)
        ):
            raise ImageGenerationError("approval_binding_invalid")
        proposal = self._record_path(persisted, "proposal")
        try:
            if proposal.stat().st_size > 1024 or json.loads(proposal.read_text(encoding="utf-8")) != {"digest": _task_binding(persisted)}:
                raise ImageGenerationError("approved_payload_changed")
        except (OSError, ValueError):
            raise ImageGenerationError("approval_binding_invalid") from None
        mode = getattr(self._queue, "mediation_mode", None)
        if mode == "enforce":
            # The worker has already consumed its private dispatch permit.
            # Recheck the presented snapshot against current authenticated
            # storage at each guard, including immediately before the attempt.
            if not self._queue.validate_mediated_execution(
                task, self._queue.execution_fingerprint(task),
            ):
                raise ImageGenerationError("mediation_execution_required")
        elif mode != "off":
            raise ImageGenerationError("mediation_execution_required")
        return persisted

    async def execute(self, args):
        from .action_origin import current_action_origin
        from .kernel import Action, Verdict
        from .media_catalog import default_catalog_if_enabled
        from .media_gen import MediaGenManager
        from .security.taint import is_untrusted_source

        reason = "local_refused"
        try:
            config = self._config()
            task = self._approval(args, config)
        except (ImageGenerationError, OSError, KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "reason": getattr(exc, "reason", "approval_binding_invalid")}
        options = {key: args[key] for key in ("seed", "width", "height", "steps")}

        def guard(kind, prompt, opts):
            nonlocal reason
            try:
                if kind != "image" or prompt != args["prompt"] or opts != options:
                    raise ImageGenerationError("approved_payload_changed")
                live_config = self._config()
                persisted = self._approval(args, live_config)
                if live_config != config:
                    raise ImageGenerationError("backend_binding_changed")
                origin = persisted.origin
                active = current_action_origin()
                if is_untrusted_source(active):
                    origin = active
                decision = self._authorizer(Action(
                    kind="tool.rpc", agent=persisted.agent, title="Generate one local image",
                    payload={**persisted.payload, "risk_tier": max(2, persisted.risk_tier),
                             "effect": "local_image", "task_id": persisted.id,
                             "approved_digest": _task_binding(persisted)},
                    origin=origin,
                ))
                verdict = getattr(decision, "verdict", None)
                if verdict is Verdict.DENY:
                    raise ImageGenerationError("kernel_denied")
                if verdict not in {Verdict.GRANT, Verdict.QUEUE}:
                    raise ImageGenerationError("kernel_error")
                # FileTools semantics: QUEUE is satisfied by this exact durable
                # human approval; it is not rewritten to GRANT. The exclusive
                # durable marker consumes that authority before the only POST.
                self._approval(args, self._config())
                try:
                    _write_exclusive(self._record_path(persisted, "attempt"), {
                        "task_id": persisted.id, "digest": _task_binding(persisted),
                        "head": args["_binding"]["head"], "verdict": verdict.value,
                        "origin": origin, "risk_tier": max(2, persisted.risk_tier),
                        "decided_by": persisted.decided_by,
                        "state": "consumed_result_may_be_unknown",
                    })
                except FileExistsError:
                    raise ImageGenerationError("approval_consumed_result_may_be_unknown") from None
                except OSError:
                    raise ImageGenerationError("durable_attempt_unavailable") from None
                return True, ""
            except Exception as exc:
                reason = getattr(exc, "reason", "local_guard_failed")
                return False, reason

        async def comfyui(prompt, opts):
            nonlocal reason
            try:
                return await ComfyUIBackend(config).generate(prompt, opts)
            except ImageGenerationError as exc:
                reason = exc.reason
                raise

        manager = MediaGenManager(backends={"image": comfyui}, agent=task.agent,
                                  local_guard=guard, catalog=default_catalog_if_enabled())
        result = await manager.generate("image", args["prompt"], opts=options)
        if not result.get("ok"):
            result["reason"] = reason
        elif isinstance(result.get("result"), dict):
            artifact = result["result"]
            artifact.pop("path", None)
            artifact["url"] = "/api/media/generated/" + artifact["artifact_id"]
        return result
