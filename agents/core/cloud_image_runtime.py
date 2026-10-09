"""One signed cloud image POST, with durable no-replay and local completion."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import estop
from .autonomy.executor import ExecutionGuardDeclined
from .autonomy.queue import MediationStateUnavailable, TaskQueue
from .env_config import env_flag, env_str
from .http_client import PluginHTTPClient, PluginTimeouts
from .image_generation_runtime import _task_binding
from .kernel import Action, Verdict, kernel_enabled
from .media_backends.comfyui import implementation_fingerprint, save_artifact
from .media_backends.openai_image import ENDPOINT, MAX_RESPONSE, decode_result, normalize_request
from .media_catalog import MediaCatalog
from .paths import data_root
from .vault import _file_lock

PLUGIN = "cloud-image"
VERSION = "openai-image-v1"
_CODE_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes()
    + (Path(__file__).parent / "media_backends" / "openai_image.py").read_bytes()
    + implementation_fingerprint().encode("ascii")
).hexdigest()


class _Declined(ValueError):
    """A gate that declined — governance or configuration (the feature switched off, the
    kernel denying, the approval or the configuration changed, the emergency stop) —
    rather than machinery that broke. ``reason`` names it; the message stays the
    runtime's own (review round 5, item 8)."""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


class _ProviderFailed(ValueError):
    """The provider answered, but not with an image this runtime accepts."""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


class _StateUnavailable(ValueError):
    """The queue could not read the mediated-execution state (review round 6, item 2):
    the machinery failing, reported as ``mediation_state_unavailable``, a failure —
    never the governance hold ``mediation_execution_required``."""

    reason = "mediation_state_unavailable"


def matches(task):
    return (
        getattr(task, "kind", None) == "plugin.egress"
        and isinstance(getattr(task, "payload", None), dict)
        and task.payload.get("plugin") == PLUGIN
    )


def _safe(root):
    root = Path(root).absolute()
    if root.resolve() != root or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("unsafe cloud image storage")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write(path, data, *, replace=False):
    _safe(path.parent)
    if path.is_symlink():
        raise ValueError("unsafe cloud image record")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".image-", delete=False) as f:
            temporary = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json(path):
    if path.is_symlink() or path.stat().st_size > 8192:
        raise ValueError("invalid cloud image record")
    return json.loads(path.read_text(encoding="utf-8"))


class _Claim:
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint
        self.active = True
        self.lock = threading.Lock()

    def consume(self, fingerprint):
        with self.lock:
            active, self.active = self.active, False
            return active and fingerprint == self.fingerprint


class _Client(PluginHTTPClient):
    def __init__(self, check, **kwargs):
        super().__init__(PLUGIN, timeouts=PluginTimeouts(connect=5, read=180, total=180), **kwargs)
        self.check = check

    def _enforce_kernel(self, method, url, host):
        # This adapter never inherits the base hook's intentional fail-open behavior.
        self.check(method, url)


class CloudImageRuntime:
    def __init__(
        self, worker, *, kernel, redact, root=None, key=None, resolver=None, transport_factory=None,
        gate=None,
    ):
        self.worker, self.kernel, self.redact = worker, kernel, redact
        # H285: the live PermissionGate holds its own manifests (a toggle and the load set
        # switch those); without one, the module table is asked.
        self.gate = gate
        self.root = Path(root) if root is not None else data_root()
        self.key = key or (lambda: env_str("OPENAI_API_KEY"))
        self.resolver, self.transport_factory = resolver, transport_factory
        self._claim = contextvars.ContextVar("cloud_image_claim", default=None)

    @property
    def records(self):
        return _safe(self.root / "media" / "cloud-image")

    def _configuration(self):
        key = self.key()
        if not isinstance(key, str) or not key.strip():
            raise _Declined("credential_not_configured", "OpenAI image credential unavailable")
        # The generation binds the helper that actually publishes PNGs. A disk
        # edit after import cannot silently approve different loaded behavior.
        implementation_fingerprint()
        # Only a random generation is public. The credential hash stays in a
        # private local record, so task/status metadata is not a secret oracle.
        digest = hashlib.sha256((VERSION + _CODE_DIGEST + "\0" + key).encode()).hexdigest()
        path = self.records / "configuration.json"
        with _file_lock(self.records / "configuration.lock"):
            old = _json(path) if path.exists() else {}
            if old.get("digest") != digest:
                old = {"digest": digest, "generation": uuid.uuid4().hex}
                _write(path, json.dumps(old).encode(), replace=True)
        return key, old["generation"]

    def status(self):
        from .media_backends.openai_image import MODEL, SIZES

        configured = False
        try:
            self._available(probe_signing=False)
            key = self.key()
            configured = isinstance(key, str) and bool(key.strip())
        except Exception:
            configured = False
        return {
            "configured": configured,
            "provider": "openai",
            "model": MODEL,
            "local": False,
            "approval_required": True,
            "reachable": None,
            "reason": "not_probed" if configured else "unavailable",
            "sizes": sorted(SIZES),
            "qualities": ["low", "medium", "high"],
        }

    def _available(self, *, probe_signing=True):
        from .plugin_gate import BUILTIN_PLUGINS
        from .system_profiles import heavy_features_enabled

        manifest = (self.gate.plugins if self.gate is not None else BUILTIN_PLUGINS).get(PLUGIN)
        if manifest is None or not manifest.enabled or not heavy_features_enabled():
            raise _Declined("cloud_image_unavailable", "cloud image feature unavailable")
        if self.worker.queue.mediation_mode != "enforce" or not kernel_enabled():
            raise _Declined("enforced_mediation_unavailable",
                            "cloud image enforced mediation unavailable")
        if not callable(self.kernel) or not callable(self.redact):
            # A kernel or a screen that is not wired is a component that failed to
            # start — machinery, not configuration (review round 6, item 6: the guard
            # now reports its declines, so only a governance one may be a refusal).
            raise ValueError("cloud image enforced mediation unavailable")
        signer = getattr(self.worker, "_mediation_signer", None)
        if not callable(getattr(signer, "sign", None)) or (
            probe_signing and signer.sign(b"cloud-image availability") is None
        ):
            raise ValueError("cloud image signing unavailable")

    def validate(self, payload):
        self._available()
        if (
            not isinstance(payload, dict)
            or set(payload) - {"plugin", "method", "url", "image", "tainted"}
            or payload.get("plugin") != PLUGIN
            or payload.get("method") != "POST"
            or payload.get("url") != ENDPOINT
        ):
            raise ValueError("invalid cloud image identity")
        value = payload.get("image")
        if not isinstance(value, dict) or set(value) != {"body", "generation", "nonce", "version"}:
            raise ValueError("invalid cloud image request")
        body = value["body"]
        if (
            not isinstance(body, dict)
            or body
            != normalize_request(
                body.get("prompt"), {k: body[k] for k in ("model", "size", "quality") if k in body}
            )
            or value["version"] != VERSION
            or not isinstance(value["nonce"], str)
            or not re.fullmatch("[a-f0-9]{32}", value["nonce"])
        ):
            raise ValueError("invalid cloud image request")
        # Screening refuses; it never rewrites the body bound to owner approval.
        # Repeat validation immediately before dial for newly known secrets.
        try:
            screened = self.redact(body["prompt"])
        except Exception:
            raise ValueError("cloud image prompt screening unavailable") from None
        if not isinstance(screened, str) or screened != body["prompt"]:
            raise _Declined("prompt_screening_refused", "cloud image prompt screening refused")
        key, generation = self._configuration()
        if value["generation"] != generation:
            raise _Declined("configuration_changed", "cloud image configuration changed")
        return key

    def submit(self, prompt, options, origin, *, actor="jarvis"):
        body = normalize_request(prompt, options)
        self._available()
        _, generation = self._configuration()
        payload = {
            "plugin": PLUGIN,
            "method": "POST",
            "url": ENDPOINT,
            "image": {
                "body": body,
                "generation": generation,
                "nonce": uuid.uuid4().hex,
                "version": VERSION,
            },
        }
        self.validate(payload)
        task_id = self.worker.govern_enqueue(
            agent=actor,
            kind="plugin.egress",
            title="Paid OpenAI image generation: one image and local artifact",
            payload=payload,
            risk_tier=3,
            autonomy_level="ask",
            origin=origin,
        )
        task = self.worker.queue.get(task_id)
        if not matches(task) or task.payload.get("image") != payload["image"]:
            raise ValueError("cloud image proposal unavailable")
        _write(self._path(task, "proposal"), json.dumps({"binding": _task_binding(task)}).encode())
        return task_id

    def _path(self, task, suffix):
        nonce = task.payload["image"]["nonce"]
        if not isinstance(nonce, str) or not re.fullmatch("[a-f0-9]{32}", nonce):
            raise ValueError("invalid cloud image nonce")
        return self.records / f"{nonce}.{suffix}"

    def _bound(self, task):
        # A record that cannot be read raises its own error (machinery); only a record
        # that no longer binds this exact task is the approval that changed.
        if not matches(task) or _json(self._path(task, "proposal")) != {
            "binding": _task_binding(task)
        }:
            raise _Declined("approved_payload_changed", "cloud image approval changed")

    def guard(self, task):
        self._claim.set(None)
        if not matches(task):
            return False
        try:
            self.validate(task.payload)
            self._bound(task)
            if (
                task.autonomy_level != "ask"
                or task.decision not in {"accept", "edit"}
                or not task.decided_by
                or str(task.decided_by).strip().lower() == "policy"
            ):
                return False
            if not self.worker.execution_allowed(task):
                return False
            self._claim.set(_Claim(TaskQueue.execution_fingerprint(task)))
            return True
        except _Declined as exc:
            # A gate that declined before any attempt — governance or configuration:
            # the guard says which (review round 6, item 6), so the worker records it as
            # the refusal it is instead of a failure. Anything else is a bare False.
            raise ExecutionGuardDeclined(exc.reason) from None
        except Exception:
            return False

    def recover(self, task):
        """Only local finalization of already durable validated bytes; never HTTP."""
        with _file_lock(self._path(task, "finalize.lock")):
            return self._recover(task)

    def _recover(self, task):
        self._bound(task)
        done = _json(self._path(task, "complete"))
        if done["binding"] != _task_binding(task):
            raise ValueError("cloud image completion changed")
        artifact = done["artifact"]
        from .media_backends.comfyui import artifact_bytes

        data = artifact_bytes(artifact["artifact_id"], self.root / "media" / "generated")
        if hashlib.sha256(data).hexdigest() != done["sha256"]:
            raise ValueError("cloud image artifact changed")
        result = {"ok": True, "kind": "image", "result": artifact}
        warning = None
        if done.get("catalog_id"):
            result["catalog_id"] = done["catalog_id"]
        elif done.get("catalog_requested") and env_flag("JARVIS_MEDIA_CATALOG"):
            # The image is saved and its completion record durable, so the image WAS
            # delivered: a catalog (index) step that fails here is a warning on a
            # success, as on the local image path — never ``unknown`` (review round 6,
            # item 3). The completion keeps no catalog id, so a later ``recover`` adds
            # the row (idempotently: the record id derives from the task binding).
            try:
                catalog = MediaCatalog(self.root / "media" / "catalog.json")
                row = catalog.add(
                    kind="image",
                    prompt=task.payload["image"]["body"]["prompt"],
                    path=str(self.root / "media" / "generated" / (artifact["artifact_id"] + ".png")),
                    now=done["created_at"],
                    backend="openai:gpt-image-1.5",
                    cloud=True,
                    record_id="md-" + hashlib.sha256(_task_binding(task).encode()).hexdigest()[:12],
                    sha256=done["sha256"],
                    meta={"task_id": task.id, "sha256": done["sha256"]},
                )
                done["catalog_id"] = row["id"]
                _write(self._path(task, "complete"), json.dumps(done).encode(), replace=True)
                result["catalog_id"] = row["id"]
            except Exception:
                warning = "catalog_record_failed"
        completed = {"status": "ok", "tool": "cloud_image_generate", "result": result}
        if warning is not None:
            completed["warning"] = warning
        return completed

    def project(self, task):
        from .image_generation_view import ImageArtifactView, project_image_task

        view = project_image_task(task)
        try:
            result = self.recover(task)
            artifact = result["result"]["result"]
            view.artifact = ImageArtifactView(
                id=artifact["artifact_id"],
                bytes=artifact["bytes"],
                width=artifact["width"],
                height=artifact["height"],
            )
            view.state = "ready"
        except Exception:
            return view
        return view

    async def execute(self, task):
        claim = self._claim.get()
        self._claim.set(None)
        fingerprint = TaskQueue.execution_fingerprint(task)
        if not matches(task) or not isinstance(claim, _Claim) or not claim.consume(fingerprint):
            return {"status": "refused", "reason": "cloud image execution claim required"}
        # How far this attempt got decides what an error means (review round 5, item 8):
        # "preflight" — nothing sent; "dialled" — the durable attempt marker is written
        # and the POST may be on the wire; "generated" — the provider answered with an
        # image; "published" — the recheck after the answer passed.
        phase = "preflight"
        try:
            self.validate(task.payload)
            self._bound(task)
            if self._path(task, "complete").exists():
                phase = "published"
                return self.recover(task)
            attempted = self._path(task, "attempt")
            if attempted.exists():
                # A submission an earlier attempt may have made: never replayed, its
                # result not known — the worker records ``unknown`` as a failure.
                return {
                    "status": "unknown",
                    "reason": "cloud image submission may have occurred; not replayed",
                }
            key = self.validate(task.payload)

            def live_check(method, url):
                self.validate(task.payload)
                self._bound(task)
                if estop.is_engaged():
                    raise _Declined("estop_engaged", "cloud image dispatch refused")
                if method != "POST" or url != ENDPOINT:
                    raise _Declined("dispatch_changed", "cloud image dispatch refused")
                try:
                    mediated = self.worker.queue.validate_mediated_execution(task, fingerprint)
                except MediationStateUnavailable:
                    raise _StateUnavailable("cloud image mediation state unavailable") from None
                if not mediated:
                    raise _Declined("mediation_execution_required",
                                    "cloud image execution receipt invalid")
                decision = self.kernel(
                    Action(
                        kind="plugin.egress",
                        agent=task.agent,
                        title=task.title,
                        payload=task.payload,
                        origin=task.origin,
                    )
                )
                if decision.verdict is Verdict.DENY:
                    raise _Declined("kernel_denied", "cloud image kernel refused")
                if decision.verdict not in {Verdict.GRANT, Verdict.QUEUE}:
                    raise ValueError("cloud image kernel refused")

            def check(method, url):
                nonlocal phase
                live_check(method, url)
                # A durable exclusive marker immediately before dial. A second
                # callback/request can never reuse this logical approval.
                _write(attempted, json.dumps({"binding": _task_binding(task)}).encode())
                phase = "dialled"

            client = _Client(
                check, resolver=self.resolver, transport_factory=self.transport_factory
            )
            try:
                async with asyncio.timeout(180):
                    async with client.stream(
                        "POST",
                        ENDPOINT,
                        follow_redirects=False,
                        json=task.payload["image"]["body"],
                        headers={
                            "Authorization": "Bearer " + key,
                            "Accept-Encoding": "identity",
                            "Accept": "application/json",
                        },
                    ) as response:
                        if (
                            response.status_code != 200
                            or response.headers.get("content-encoding", "identity") != "identity"
                        ):
                            raise _ProviderFailed("cloud_image_provider_error",
                                                  "cloud image provider refused")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_RESPONSE:
                                raise _ProviderFailed("cloud_image_response_too_large",
                                                      "cloud image response too large")
                            body.extend(chunk)
                        try:
                            data = decode_result(
                                json.loads(body), task.payload["image"]["body"]["size"]
                            )
                        except (ValueError, TypeError, KeyError, RecursionError):
                            raise _ProviderFailed("cloud_image_invalid_response",
                                                  "cloud image response invalid") from None
            finally:
                await client.close()
            phase = "generated"
            live_check("POST", ENDPOINT)
            phase = "published"
            generated_root = _safe(self.root / "media" / "generated")
            width, height = map(int, task.payload["image"]["body"]["size"].split("x"))

            def final_publication_guard():
                nonlocal phase
                # Root safety is storage, not a governance refusal. Keep its
                # failure in the publication/unknown phase.
                _safe(generated_root)
                try:
                    live_check("POST", ENDPOINT)
                except Exception:
                    # The provider answered, but the last live governance or
                    # machinery recheck refused before the PNG link.
                    phase = "generated"
                    raise

            published = save_artifact(
                generated_root, data, width, height, guard=final_publication_guard,
            )
            done = {
                "binding": _task_binding(task),
                "created_at": time.time(),
                "catalog_requested": env_flag("JARVIS_MEDIA_CATALOG"),
                "sha256": published["sha256"],
                "artifact": {
                    "artifact_id": published["artifact_id"],
                    "bytes": published["bytes"],
                    "width": published["width"],
                    "height": published["height"],
                },
            }
            _write(self._path(task, "complete"), json.dumps(done).encode())
            return self.recover(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Provider exceptions/body can contain credentials or prompt content: only a
            # fixed reason code ever leaves here.
            return _attempt_result(phase, exc)


def _attempt_result(phase, exc):
    """The executor's result for an attempt that stopped at *phase* with *exc* (review
    round 5, item 8). It was ``{"status": "unknown"}`` on every path, which the worker
    recorded as a SUCCESS."""
    declined = isinstance(exc, _Declined)
    if isinstance(exc, _StateUnavailable) and phase in {"preflight", "generated"}:
        # The queue's mediation state could not be read at a check (round 6, item 2):
        # the machinery failing, before the dial or after the answer — a failure under
        # its own reason, never the governance hold (refused / withheld).
        return {"status": "failed", "reason": exc.reason}
    if phase == "preflight":
        # Nothing was sent: a gate that declined is a refusal; anything else (a
        # malformed request, a record or a screening that failed, the signer, the
        # kernel raising) is the machinery failing before the dial.
        if declined:
            return {"status": "refused", "reason": exc.reason}
        return {"status": "failed", "reason": "cloud_image_preflight_failed"}
    if phase == "dialled":
        if isinstance(exc, _ProviderFailed):
            return {"status": "failed", "reason": exc.reason}
        # A transport error after the dial: the POST may have been processed (and
        # paid). Never replayed; its result is not known.
        return {
            "status": "unknown",
            "reason": "cloud image completion unavailable; submission not replayed",
        }
    if phase == "generated":
        # The recheck after the provider answered: a governance cause withholds the
        # generated image (records nothing, like tool.rpc's: round 5, item 1); a
        # recheck that broke is a failure.
        if declined:
            return {"status": "failed", "reason": "withheld_after_generation",
                    "detail": exc.reason}
        return {"status": "failed", "reason": "cloud_image_recheck_failed"}
    # Generated and allowed, but the image or its completion record was not durably
    # kept here (a write failed): the image may exist remotely and is not kept locally
    # — ``unknown``. A failure only of the catalog step after the completion was
    # written is a success with a warning (``_recover``, round 6, item 3).
    return {
        "status": "unknown",
        "reason": "cloud image completion unavailable; submission not replayed",
    }
