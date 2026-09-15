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
from .autonomy.queue import TaskQueue
from .env_config import env_flag, env_str
from .http_client import PluginHTTPClient, PluginTimeouts
from .image_generation_runtime import _task_binding
from .kernel import Action, Verdict, kernel_enabled
from .media_backends.openai_image import ENDPOINT, MAX_RESPONSE, decode_result, normalize_request
from .media_catalog import MediaCatalog
from .paths import data_root
from .vault import _file_lock

PLUGIN = "cloud-image"
VERSION = "openai-image-v1"
_CODE_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes()
    + (Path(__file__).parent / "media_backends" / "openai_image.py").read_bytes()
).hexdigest()


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
        self, worker, *, kernel, redact, root=None, key=None, resolver=None, transport_factory=None
    ):
        self.worker, self.kernel, self.redact = worker, kernel, redact
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
            raise ValueError("OpenAI image credential unavailable")
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

        manifest = BUILTIN_PLUGINS.get(PLUGIN)
        if manifest is None or not manifest.enabled or not heavy_features_enabled():
            raise ValueError("cloud image feature unavailable")
        if (
            self.worker.queue.mediation_mode != "enforce"
            or not kernel_enabled()
            or not callable(self.kernel)
            or not callable(self.redact)
        ):
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
            raise ValueError("cloud image prompt screening refused")
        key, generation = self._configuration()
        if value["generation"] != generation:
            raise ValueError("cloud image configuration changed")
        return key

    def submit(self, prompt, options, origin):
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
            agent="jarvis",
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
        if not matches(task) or _json(self._path(task, "proposal")) != {
            "binding": _task_binding(task)
        }:
            raise ValueError("cloud image approval changed")

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
        if done.get("catalog_id"):
            result["catalog_id"] = done["catalog_id"]
        elif done.get("catalog_requested") and env_flag("JARVIS_MEDIA_CATALOG"):
            catalog = MediaCatalog(self.root / "media" / "catalog.json")
            row = catalog.add(
                kind="image",
                prompt=task.payload["image"]["body"]["prompt"],
                path=str(self.root / "media" / "generated" / (artifact["artifact_id"] + ".png")),
                now=done["created_at"],
                backend="openai:gpt-image-1.5",
                cloud=True,
                record_id="md-" + hashlib.sha256(_task_binding(task).encode()).hexdigest()[:12],
                meta={"task_id": task.id, "sha256": done["sha256"]},
            )
            result["catalog_id"] = row["id"]
            done["catalog_id"] = row["id"]
            _write(self._path(task, "complete"), json.dumps(done).encode(), replace=True)
        return {"status": "ok", "tool": "cloud_image_generate", "result": result}

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
        try:
            self.validate(task.payload)
            self._bound(task)
            if self._path(task, "complete").exists():
                return self.recover(task)
            attempted = self._path(task, "attempt")
            if attempted.exists():
                return {
                    "status": "unknown",
                    "reason": "cloud image submission may have occurred; not replayed",
                }
            key = self.validate(task.payload)

            def live_check(method, url):
                self.validate(task.payload)
                self._bound(task)
                if method != "POST" or url != ENDPOINT or estop.is_engaged():
                    raise ValueError("cloud image dispatch refused")
                if not self.worker.queue.validate_mediated_execution(task, fingerprint):
                    raise ValueError("cloud image execution receipt invalid")
                decision = self.kernel(
                    Action(
                        kind="plugin.egress",
                        agent=task.agent,
                        title=task.title,
                        payload=task.payload,
                        origin=task.origin,
                    )
                )
                if decision.verdict not in {Verdict.GRANT, Verdict.QUEUE}:
                    raise ValueError("cloud image kernel refused")

            def check(method, url):
                live_check(method, url)
                # A durable exclusive marker immediately before dial. A second
                # callback/request can never reuse this logical approval.
                _write(attempted, json.dumps({"binding": _task_binding(task)}).encode())

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
                            raise ValueError("cloud image provider refused")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_RESPONSE:
                                raise ValueError("cloud image response too large")
                            body.extend(chunk)
                        data = decode_result(
                            json.loads(body), task.payload["image"]["body"]["size"]
                        )
            finally:
                await client.close()
            live_check("POST", ENDPOINT)
            artifact_id = uuid.uuid4().hex
            destination = self.root / "media" / "generated" / (artifact_id + ".png")
            _write(destination, data)
            width, height = map(int, task.payload["image"]["body"]["size"].split("x"))
            done = {
                "binding": _task_binding(task),
                "created_at": time.time(),
                "catalog_requested": env_flag("JARVIS_MEDIA_CATALOG"),
                "sha256": hashlib.sha256(data).hexdigest(),
                "artifact": {
                    "artifact_id": artifact_id,
                    "bytes": len(data),
                    "width": width,
                    "height": height,
                },
            }
            _write(self._path(task, "complete"), json.dumps(done).encode())
            return self.recover(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Provider exceptions/body can contain credentials or prompt content.
            return {
                "status": "unknown",
                "reason": "cloud image completion unavailable; submission not replayed",
            }
