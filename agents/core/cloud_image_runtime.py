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
from contextlib import ExitStack
from pathlib import Path

from . import estop
from .autonomy.executor import ExecutionGuardDeclined
from .autonomy.queue import MediationStateUnavailable, TaskQueue
from .env_config import env_flag, env_str
from .http_client import PluginHTTPClient, PluginTimeouts
from .image_generation_runtime import _task_binding
from .kernel import Action, Verdict, kernel_enabled
from .media_backends import (
    codex_image,
    deepinfra_image,
    fal_image,
    krea_enhance,
    krea_image,
    krea_jobs,
    openrouter_image,
    xai_image,
)
from .media_backends.openai_image import (
    ENDPOINT,
    IMAGE2_TIERS,
    MAX_RESPONSE,
    decode_result,
    normalize_request,
)
from .media_catalog import MediaCatalog
from .paths import data_root
from .security.taint import is_untrusted_source
from .vault import VaultError, _file_lock

PLUGIN = "cloud-image"
FAL_PLUGIN = "cloud-image-fal"
CODEX_PLUGIN = "cloud-image-codex"
OPENROUTER_PLUGIN = "cloud-image-openrouter"
KREA_PLUGIN = "cloud-image-krea"
XAI_PLUGIN = "cloud-image-xai"
DEEPINFRA_PLUGIN = "cloud-image-deepinfra"
VERSION = "openai-image-v1"
FAL_VERSION = "fal-image-v1"
CODEX_VERSION = "codex-image-v1"
OPENROUTER_VERSION = "openrouter-image-v1"
KREA_VERSION = "krea-image-v1"
XAI_VERSION = "xai-image-v1"
DEEPINFRA_VERSION = "deepinfra-image-v1"
_CODE_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes()
    + (Path(__file__).parent / "media_backends" / "openai_image.py").read_bytes()
).hexdigest()
_FAL_CODE_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes()
    + (Path(__file__).parent / "media_backends" / "fal_image.py").read_bytes()
    + (Path(__file__).parent / "media_backends" / "fal_catalog.py").read_bytes()
).hexdigest()
_CODEX_CODE_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes()
    + (Path(__file__).parent / "media_backends" / "codex_image.py").read_bytes()
    + (Path(__file__).parent / "media_backends" / "openai_image.py").read_bytes()
).hexdigest()
_OPENROUTER_CODE_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes() + Path(openrouter_image.__file__).read_bytes()
    + Path(fal_image.__file__).read_bytes()
).hexdigest()
_KREA_CODE_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes() + Path(krea_image.__file__).read_bytes()
    + Path(krea_jobs.__file__).read_bytes() + Path(fal_image.__file__).read_bytes()
    + Path(krea_enhance.__file__).read_bytes()
).hexdigest()
_VERSIONS = {PLUGIN: VERSION, FAL_PLUGIN: FAL_VERSION, CODEX_PLUGIN: CODEX_VERSION,
             OPENROUTER_PLUGIN: OPENROUTER_VERSION, KREA_PLUGIN: KREA_VERSION,
             XAI_PLUGIN: XAI_VERSION, DEEPINFRA_PLUGIN: DEEPINFRA_VERSION}
_CODE_DIGESTS = {PLUGIN: _CODE_DIGEST, FAL_PLUGIN: _FAL_CODE_DIGEST,
                 CODEX_PLUGIN: _CODEX_CODE_DIGEST, OPENROUTER_PLUGIN: _OPENROUTER_CODE_DIGEST,
                 KREA_PLUGIN: _KREA_CODE_DIGEST,
                 XAI_PLUGIN: hashlib.sha256(Path(__file__).read_bytes()
                     + Path(xai_image.__file__).read_bytes() + Path(fal_image.__file__).read_bytes()).hexdigest(),
                 DEEPINFRA_PLUGIN: hashlib.sha256(Path(__file__).read_bytes()
                     + Path(deepinfra_image.__file__).read_bytes() + Path(fal_image.__file__).read_bytes()).hexdigest()}
_OPENROUTER_OPTIONS = {"backend", "model", "size", "references", "aspect_ratio_exact",
                      "resolution", "quality", "background", "output_compression", "seed", "n"}
_KREA_OPTIONS = {"backend", "model", "size", "aspect_ratio", "creativity", "seed", "image_style_references"}
_XAI_OPTIONS = {"backend", "model", "size", "references", "resolution", "quality", "n"}
_DEEPINFRA_OPTIONS = {"backend", "model", "size", "aspect_ratio", "references", "n"}


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
        and task.payload.get("plugin") in _VERSIONS
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


def _json(path, *, limit=8192):
    if path.is_symlink() or path.stat().st_size > limit:
        raise ValueError("invalid cloud image record")
    return json.loads(path.read_text(encoding="utf-8"))


def _reference_bytes(root, references):
    """Resolve only owner-admitted generated artifacts; bound the aggregate upload."""
    from .media_backends.comfyui import artifact_bytes

    if (not isinstance(references, list) or len(references) > 16 or
            len(set(references)) != len(references)):
        raise ValueError("invalid cloud image references")
    result = []
    total = 0
    for artifact_id in references:
        data = artifact_bytes(artifact_id, Path(root) / "media" / "generated")
        total += len(data)
        if total > 64 * 1024 * 1024:
            raise ValueError("cloud image references too large")
        result.append(data)
    return result


def _references_with_digests(root, refs):
    return [hashlib.sha256(data).hexdigest() for data in _reference_bytes(root, refs)]


def _normalize_body(plugin, prompt, options, root, *, catalog=None):
    if plugin == DEEPINFRA_PLUGIN:
        return deepinfra_image.normalize_request(prompt, options, catalog=catalog)
    if plugin == XAI_PLUGIN:
        body = xai_image.normalize_request(prompt, options)
        if body["references"]:
            body["reference_digests"] = _references_with_digests(root, body["references"])
        return body
    if plugin == OPENROUTER_PLUGIN:
        body = openrouter_image.normalize_request(prompt, options)
        if body.get("resolution") == "4K":
            raise ValueError("cloud image artifact resolution unsupported")
        if body["references"]:
            body["reference_digests"] = _references_with_digests(root, body["references"])
        return body
    if plugin == KREA_PLUGIN:
        body = krea_image.normalize_request(prompt, options)
        if "image_style_references" in body:
            # The queue bounds nesting; serialize exact owner-visible style objects.
            body["style_references_json"] = json.dumps(body.pop("image_style_references"),
                                                       sort_keys=True, separators=(",", ":"))
        return body
    if plugin == FAL_PLUGIN:
        body = fal_image.normalize_request(prompt, options)
        body.pop("body")
        return body
    if plugin == CODEX_PLUGIN:
        clean = {k: v for k, v in options.items() if k != "backend"}
        if set(options) - {"backend", "model", "size", "references"}:
            raise ValueError("unsupported Codex image option")
        body = codex_image.normalize_request(prompt, clean)
        if body["references"]:
            body["reference_digests"] = _references_with_digests(root, body["references"])
        return body
    if set(options) - {"backend", "model", "size", "quality", "references"} or \
            options.get("backend", "openai") != "openai":
        raise ValueError("unsupported cloud image option")
    selected = options.get("model", "gpt-image-1.5")
    refs = options.get("references", [])
    if refs and selected not in IMAGE2_TIERS:
        raise ValueError("cloud image model cannot edit")
    body = normalize_request(prompt, {k: v for k, v in options.items()
                                      if k in {"model", "size", "quality"}})
    if selected in IMAGE2_TIERS:
        body["selected_model"] = selected
    if refs:
        body["references"] = refs
        body["reference_digests"] = _references_with_digests(root, refs)
    return body


def _endpoint(plugin, body):
    if plugin == XAI_PLUGIN:
        return xai_image.endpoint_for(_provider_body(plugin, body))
    if plugin == DEEPINFRA_PLUGIN:
        return deepinfra_image.endpoint_for(body)
    if plugin == OPENROUTER_PLUGIN:
        return openrouter_image.endpoint_for(_provider_body(plugin, body))
    if plugin == KREA_PLUGIN:
        if body.get("operation") == "enhance":
            return krea_enhance.endpoint_for(body)
        return krea_image.endpoint_for(_provider_body(plugin, body))
    if plugin == FAL_PLUGIN:
        return "https://fal.run/" + body["endpoint"]
    if plugin == CODEX_PLUGIN:
        return codex_image.endpoint_for(body)
    if body.get("references"):
        return "https://api.openai.com/v1/images/edits"
    return ENDPOINT


def _provider_body(plugin, body):
    result = {key: value for key, value in body.items() if key != "reference_digests"}
    if plugin == KREA_PLUGIN and "style_references_json" in result:
        value = result.pop("style_references_json")
        if not isinstance(value, str) or len(value) > 24000:
            raise ValueError("invalid cloud style references")
        result["image_style_references"] = json.loads(value)
    return result


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
    def __init__(self, check, *, plugin=PLUGIN, gate=None, **kwargs):
        deadline = 300 if plugin in {CODEX_PLUGIN, OPENROUTER_PLUGIN} else 180
        super().__init__(plugin, timeouts=PluginTimeouts(connect=5, read=deadline, total=deadline), **kwargs)
        self.check = check
        self.gate = gate

    def _manifest_mode(self, url):
        from urllib.parse import urlsplit

        from .plugin_gate import BUILTIN_PLUGINS, NetworkAccess, dynamic_domains, host_in_allowlist

        manifest = (self.gate.plugins if self.gate is not None else BUILTIN_PLUGINS).get(self.plugin_name)
        host = urlsplit(url).hostname or ""
        if (manifest is None or not manifest.enabled or manifest.network_access is not NetworkAccess.RESTRICTED
                or not host_in_allowlist(host, manifest.allowed_domains + dynamic_domains(self.plugin_name))):
            raise _Declined("download_host_not_admitted", "cloud image egress host refused")
        return "public"

    def _enforce_kernel(self, method, url, host):
        # This adapter never inherits the base hook's intentional fail-open behavior.
        self._manifest_mode(url)
        self.check(method, url)


class CloudImageRuntime:
    def __init__(
        self, worker, *, kernel, redact, root=None, key=None, fal_key=None, resolver=None, transport_factory=None,
        gate=None, codex_source=None, openrouter_key=None, krea_key=None, poll_sleep=None,
        xai_key=None, deepinfra_key=None,
    ):
        self.worker, self.kernel, self.redact = worker, kernel, redact
        # H285: the live PermissionGate holds its own manifests (a toggle and the load set
        # switch those); without one, the module table is asked.
        self.gate = gate
        self.root = Path(root) if root is not None else data_root()
        self.key = key or (lambda: env_str("OPENAI_API_KEY"))
        self.fal_key = fal_key or (lambda: env_str("FAL_KEY"))
        self.codex_source = codex_source or codex_image.configured_source
        self.openrouter_key = openrouter_key or (lambda: env_str("OPENROUTER_API_KEY"))
        self.krea_key = krea_key or (lambda: env_str("KREA_API_KEY"))
        self.xai_key = xai_key or (lambda: env_str("XAI_API_KEY"))
        self.deepinfra_key = deepinfra_key or (lambda: env_str("DEEPINFRA_API_KEY"))
        self.poll_sleep = poll_sleep
        self.resolver, self.transport_factory = resolver, transport_factory
        self._claim = contextvars.ContextVar("cloud_image_claim", default=None)

    @property
    def records(self):
        return _safe(self.root / "media" / "cloud-image")

    def _configuration(self, plugin=PLUGIN):
        key = (codex_image.resolve_credential(self.codex_source) if plugin == CODEX_PLUGIN
               else {FAL_PLUGIN: self.fal_key, OPENROUTER_PLUGIN: self.openrouter_key,
                     KREA_PLUGIN: self.krea_key, XAI_PLUGIN: self.xai_key,
                     DEEPINFRA_PLUGIN: self.deepinfra_key}.get(plugin, self.key)())
        if plugin != CODEX_PLUGIN and (not isinstance(key, str) or not key.strip()):
            raise _Declined("credential_not_configured", "cloud image credential unavailable")
        # Only a random generation is public. The credential hash stays in a
        # private local record, so task/status metadata is not a secret oracle.
        version = _VERSIONS[plugin]
        code_digest = _CODE_DIGESTS[plugin]
        material = (key.access_token + "\0" + key.base_url + "\0" + key.account_id
                    if plugin == CODEX_PLUGIN else key)
        digest = hashlib.sha256((version + code_digest + "\0" + material).encode()).hexdigest()
        name = {FAL_PLUGIN: "fal-configuration", CODEX_PLUGIN: "codex-configuration",
                OPENROUTER_PLUGIN: "openrouter-configuration", KREA_PLUGIN: "krea-configuration",
                XAI_PLUGIN: "xai-configuration", DEEPINFRA_PLUGIN: "deepinfra-configuration"}.get(plugin, "configuration")
        path = self.records / (name + ".json")
        with _file_lock(self.records / (name + ".lock")):
            old = _json(path) if path.exists() else {}
            if old.get("digest") != digest:
                old = {"digest": digest, "generation": uuid.uuid4().hex}
                _write(path, json.dumps(old).encode(), replace=True)
        return key, old["generation"]

    @staticmethod
    def _catalog_digest(catalog):
        return hashlib.sha256(json.dumps(list(catalog.items()), sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode()).hexdigest()

    def catalog(self):
        """Read the result of an owned catalog GET; discovery never dials here."""
        self._available(plugin=DEEPINFRA_PLUGIN, probe_signing=False)
        try:
            record = _json(self.records / "deepinfra-models.json", limit=deepinfra_image.MAX_CATALOG_BYTES)
        except OSError:
            raise ValueError("DeepInfra catalog unavailable") from None
        source = self.worker.queue.get(record["task_id"])
        self._bound(source)
        if (source.payload.get("plugin") != DEEPINFRA_PLUGIN or source.payload.get("method") != "GET"
                or source.payload.get("url") != deepinfra_image.CATALOG_ENDPOINT
                or source.payload["image"]["body"] != {"operation": "catalog_refresh", "prompt": ""}
                or source.status != "done" or source.decision not in {"accept", "edit"}
                or not source.decided_by or str(source.decided_by).strip().lower() == "policy"
                or record.get("binding") != _task_binding(source)
                or record.get("execution_fingerprint") != TaskQueue.execution_fingerprint(source)):
            raise ValueError("DeepInfra catalog approval unavailable")
        catalog = record["catalog"]
        deepinfra_image.model_capabilities(catalog)
        digest = self._catalog_digest(catalog)
        if (not isinstance(source.result, dict) or source.result.get("status") != "ok"
                or source.result.get("catalog_digest") != digest):
            raise ValueError("DeepInfra catalog changed")
        _, generation = self._configuration(DEEPINFRA_PLUGIN)
        if source.payload["image"]["generation"] != generation:
            raise _Declined("configuration_changed", "DeepInfra catalog configuration changed")
        return catalog

    def refresh_catalog(self, provider, origin, *, actor="jarvis"):
        if provider != "deepinfra":
            raise ValueError("unsupported image catalog")
        self._available(plugin=DEEPINFRA_PLUGIN)
        _, generation = self._configuration(DEEPINFRA_PLUGIN)
        payload = {"plugin": DEEPINFRA_PLUGIN, "method": "GET", "url": deepinfra_image.CATALOG_ENDPOINT,
                   "image": {"body": {"operation": "catalog_refresh", "prompt": ""},
                             "generation": generation, "nonce": uuid.uuid4().hex,
                             "version": DEEPINFRA_VERSION}}
        self.validate(payload)
        task_id = self.worker.govern_enqueue(agent=actor, kind="plugin.egress",
            title="Read DeepInfra image model catalog; no image generation POST",
            payload=payload, risk_tier=3, autonomy_level="ask", origin=origin)
        task = self.worker.queue.get(task_id)
        if not matches(task) or task.payload["image"] != payload["image"]:
            raise ValueError("image catalog proposal unavailable")
        _write(self._path(task, "proposal"), json.dumps({"binding": _task_binding(task)}).encode())
        return task_id

    def status(self):
        from .media_backends.fal_catalog import DEFAULT_MODEL, FAL_MODELS
        from .media_backends.openai_image import MODEL, SIZES
        from .plugin_gate import BUILTIN_PLUGINS

        configured = False
        try:
            self._available(probe_signing=False)
            key = self.key()
            configured = isinstance(key, str) and bool(key.strip())
        except Exception:
            configured = False
        manifests = self.gate.plugins if self.gate is not None else BUILTIN_PLUGINS
        openai_manifest = manifests.get(PLUGIN)
        openai_enabled = bool(openai_manifest and openai_manifest.enabled)
        fal_manifest = manifests.get(FAL_PLUGIN)
        fal_enabled = bool(fal_manifest and fal_manifest.enabled)
        codex_manifest = manifests.get(CODEX_PLUGIN)
        codex_enabled = bool(codex_manifest and codex_manifest.enabled)
        try:
            self._available(plugin=FAL_PLUGIN, probe_signing=False)
            fal_credential = self.fal_key()
            fal_configured = isinstance(fal_credential, str) and bool(fal_credential.strip())
        except Exception:
            fal_configured = False
        codex_configured = False
        codex_reason = "disabled" if not codex_enabled else "unavailable"
        try:
            self._available(plugin=CODEX_PLUGIN, probe_signing=False)
        except _Declined as exc:
            if codex_enabled:
                codex_reason = exc.reason
        except Exception:
            codex_configured = False
        else:
            try:
                codex_image.resolve_credential(self.codex_source)
                codex_configured = True
                codex_reason = "not_probed"
            except Exception:
                codex_reason = "credential_not_configured"
        models = [MODEL, *IMAGE2_TIERS]
        capabilities = {MODEL: {"edit": False, "max_reference_images": 0,
                                "reference_kind": "artifact_id"}}
        capabilities.update({model: {"edit": True, "max_reference_images": 16,
                                     "reference_kind": "artifact_id"} for model in IMAGE2_TIERS})
        fal_capabilities = {
            model: {"edit": bool(meta.get("edit_endpoint")),
                    "max_reference_images": meta.get("max_reference_images") or 0,
                    "reference_kind": "fal_media_url"}
            for model, meta in FAL_MODELS.items()
        }
        extra_providers = {}
        for provider, plugin, credential, default, offered, caps in (
            ("openrouter", OPENROUTER_PLUGIN, self.openrouter_key, openrouter_image.DEFAULT_MODEL,
             list(openrouter_image.MODELS), openrouter_image.model_capabilities()),
            ("krea", KREA_PLUGIN, self.krea_key, krea_image.DEFAULT_MODEL,
             list(krea_image.MODEL_CATALOG), {model: {
                 "edit": False, "max_reference_images": 0, "reference_kind": "style_url",
                 "style_guided": True, "max_style_references": 10,
             } for model in krea_image.MODEL_CATALOG}),
            ("xai", XAI_PLUGIN, self.xai_key, xai_image.DEFAULT_MODEL,
             list(xai_image.MODEL_CATALOG), xai_image.model_capabilities()),
        ):
            manifest = manifests.get(plugin)
            enabled = bool(manifest and manifest.enabled)
            ready = False
            try:
                self._available(plugin=plugin, probe_signing=False)
                secret = credential()
                ready = isinstance(secret, str) and bool(secret.strip())
            except Exception:
                ready = False
            extra_providers[provider] = {
                "enabled": enabled, "configured": ready, "default_model": default,
                "models": offered, "model_capabilities": caps, "reachable": None,
                "reason": "not_probed" if ready else "unavailable",
            }
        manifest = manifests.get(DEEPINFRA_PLUGIN)
        refresh_available = False
        deepinfra_models = {}
        try:
            self._available(plugin=DEEPINFRA_PLUGIN, probe_signing=False)
            secret = self.deepinfra_key()
            refresh_available = isinstance(secret, str) and bool(secret.strip())
            if refresh_available:
                deepinfra_models = self.catalog()
        except Exception:
            deepinfra_models = {}
        extra_providers["deepinfra"] = {
            "enabled": bool(manifest and manifest.enabled), "configured": bool(deepinfra_models),
            "catalog_refresh_available": refresh_available,
            "default_model": next(iter(deepinfra_models), ""), "models": list(deepinfra_models),
            "model_capabilities": deepinfra_image.model_capabilities(deepinfra_models),
            "reachable": None, "reason": "not_probed" if deepinfra_models else "catalog_required",
        }
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
            "providers": {"openai": {
                "enabled": openai_enabled, "configured": configured,
                "default_model": MODEL, "models": models,
                "model_capabilities": capabilities,
                "reachable": None, "reason": "not_probed" if configured else "unavailable",
            }, "openai-codex": {
                "enabled": codex_enabled, "configured": codex_configured,
                "default_model": codex_image.DEFAULT_MODEL, "models": list(IMAGE2_TIERS),
                "model_capabilities": {k: capabilities[k] for k in IMAGE2_TIERS},
                "reachable": None,
                "reason": codex_reason,
            }, "fal": {
                "enabled": fal_enabled, "configured": fal_configured,
                "default_model": DEFAULT_MODEL, "models": sorted(FAL_MODELS),
                "model_capabilities": fal_capabilities,
                "reachable": None, "reason": "not_probed" if fal_configured else "unavailable",
            }, **extra_providers},
        }

    def _available(self, *, plugin=PLUGIN, probe_signing=True):
        from .plugin_gate import BUILTIN_PLUGINS
        from .system_profiles import heavy_features_enabled

        manifest = (self.gate.plugins if self.gate is not None else BUILTIN_PLUGINS).get(plugin)
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
        plugin = payload.get("plugin") if isinstance(payload, dict) else None
        if plugin not in _VERSIONS:
            raise ValueError("invalid cloud image identity")
        self._available(plugin=plugin)
        if (
            not isinstance(payload, dict)
            or set(payload) - {"plugin", "method", "url", "image", "tainted", "taint_source"}
            or payload.get("method") not in {"POST", "GET"}
        ):
            raise ValueError("invalid cloud image identity")
        if "taint_source" in payload and (
            payload.get("tainted") is not True
            or not isinstance(payload["taint_source"], str)
            or not is_untrusted_source(payload["taint_source"])
        ):
            raise ValueError("invalid cloud image provenance")
        value = payload.get("image")
        continuation = plugin == KREA_PLUGIN and isinstance(value, dict) and "resume" in value
        enhancement = plugin == KREA_PLUGIN and isinstance(value, dict) and "enhance" in value
        refresh = (plugin == DEEPINFRA_PLUGIN and isinstance(value, dict)
                   and value.get("body") == {"operation": "catalog_refresh", "prompt": ""})
        fields = {"body", "generation", "nonce", "version"}
        if continuation:
            fields.add("resume")
        if enhancement:
            fields.add("enhance")
        if plugin == DEEPINFRA_PLUGIN and not refresh:
            fields.add("catalog_digest")
        if (not isinstance(value, dict) or set(value) != fields
                or payload["method"] != ("GET" if continuation or refresh else "POST")):
            raise ValueError("invalid cloud image request")
        body = value["body"]
        if not isinstance(body, dict):
            raise ValueError("invalid cloud image request")
        try:
            catalog = None
            if refresh:
                normalized = body
                valid_version = value["version"] == DEEPINFRA_VERSION
            elif plugin == DEEPINFRA_PLUGIN:
                catalog = self.catalog()
                if value["catalog_digest"] != self._catalog_digest(catalog):
                    raise _Declined("catalog_changed", "DeepInfra image catalog changed")
                options = {"backend": "deepinfra", **{key: body[key] for key in
                           _DEEPINFRA_OPTIONS - {"backend", "aspect_ratio"} if key in body}}
                valid_version = value["version"] == DEEPINFRA_VERSION
            elif plugin == XAI_PLUGIN:
                clean = _provider_body(plugin, body)
                options = {"backend": "xai", **{key: clean[key] for key in
                           _XAI_OPTIONS - {"backend"} if key in clean}}
                valid_version = value["version"] == XAI_VERSION
            elif plugin == OPENROUTER_PLUGIN:
                clean = _provider_body(plugin, body)
                options = {"backend": "openrouter", **{key: clean[key] for key in
                           _OPENROUTER_OPTIONS - {"backend", "aspect_ratio_exact"} if key in clean}}
                if clean.get("surface") == "images":
                    options["aspect_ratio_exact"] = clean.get("aspect_ratio")
                valid_version = value["version"] == OPENROUTER_VERSION
            elif enhancement:
                normalized = krea_enhance._checked_body(body)
                valid_version = value["version"] == KREA_VERSION
            elif plugin == KREA_PLUGIN:
                clean = _provider_body(plugin, body)
                options = {"backend": "krea", **{key: clean[key] for key in
                           _KREA_OPTIONS - {"backend", "aspect_ratio"} if key in clean}}
                valid_version = value["version"] == KREA_VERSION
            elif plugin == FAL_PLUGIN:
                options = {"backend": "fal", **{k: body[k] for k in
                           ("model", "size", "references", "seed", "steps") if k in body}}
                valid_version = value["version"] == FAL_VERSION
            elif plugin == CODEX_PLUGIN:
                options = {"backend": "openai-codex", **{k: body[k] for k in
                           ("model", "size", "references") if k in body}}
                valid_version = value["version"] == CODEX_VERSION
            else:
                selected = body.get("selected_model", body.get("model"))
                options = {"model": selected, **{k: body[k] for k in ("size", "references") if k in body}}
                if selected == "gpt-image-1.5" and "quality" in body:
                    options["quality"] = body["quality"]
                valid_version = value["version"] == VERSION
            if not refresh and not enhancement:
                normalized = _normalize_body(plugin, body.get("prompt"), options, self.root, catalog=catalog)
            expected_url = (deepinfra_image.CATALOG_ENDPOINT if refresh else
                            krea_image.poll_endpoint(value["resume"]["job_id"]) if continuation
                            else _endpoint(plugin, normalized))
            valid_body = body == normalized and payload["url"] == expected_url
        except _Declined:
            raise
        except (ValueError, TypeError, KeyError):
            raise ValueError("invalid cloud image request") from None
        if (
            not valid_body or not valid_version
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
        key, generation = self._configuration(plugin)
        if value["generation"] != generation:
            raise _Declined("configuration_changed", "cloud image configuration changed")
        if continuation:
            self._resume_source(payload, key=key)
        if enhancement:
            self._enhance_source(payload, key=key)
        return key

    def _enhance_source(self, payload, *, key=None):
        image = payload["image"]
        descriptor = image.get("enhance")
        if (not isinstance(descriptor, dict)
                or set(descriptor) != {"task_id", "nonce", "binding", "artifact_id", "sha256"}
                or type(descriptor["task_id"]) is not int or not 1 <= descriptor["task_id"] < 2**63):
            raise ValueError("invalid Krea Enhance source")
        source = self.worker.queue.get(descriptor["task_id"])
        if (not matches(source) or source.payload["plugin"] != KREA_PLUGIN
                or source.payload.get("method") != "POST"
                or set(source.payload["image"]) != {"body", "generation", "nonce", "version"}):
            raise ValueError("invalid Krea Enhance source")
        self._bound(source)
        job = _json(self._path(source, "job"))
        self._resume_source({"image": {"body": source.payload["image"]["body"], "resume": {
            "task_id": source.id, "nonce": source.payload["image"]["nonce"],
            "job_id": job["job_id"], "binding": _task_binding(source)}}}, key=key)
        done = _json(self._path(source, "complete"))
        artifact = done["artifact"]
        if (descriptor != {"task_id": source.id, "nonce": source.payload["image"]["nonce"],
                           "binding": _task_binding(source), "artifact_id": artifact["artifact_id"],
                           "sha256": done["sha256"]}
                or done["binding"] != _task_binding(source)
                or done.get("job_id") != job["job_id"]
                or done.get("provider_result_url") != job.get("provider_result_url")
                or done["sha256"] != job.get("result_sha256")):
            raise ValueError("Krea Enhance source changed")
        self._recover(source)
        body = source.payload["image"]["body"]
        expected = krea_enhance.normalize_request(body["prompt"], {
            "backend": "krea", "model": body["model"], "size": body["size"],
            "enhance_image_url": done["provider_result_url"],
        })
        if image["body"] != expected or self.redact(expected["image_url"]) != expected["image_url"]:
            raise ValueError("Krea Enhance source changed")
        from urllib.parse import urlsplit

        from .plugin_gate import BUILTIN_PLUGINS, NetworkAccess, dynamic_domains, host_in_allowlist

        manifest = (self.gate.plugins if self.gate is not None else BUILTIN_PLUGINS).get(KREA_PLUGIN)
        if (manifest is None or not manifest.enabled or manifest.network_access is not NetworkAccess.RESTRICTED
                or not host_in_allowlist(urlsplit(expected["image_url"]).hostname,
                                         manifest.allowed_domains + dynamic_domains(KREA_PLUGIN))):
            raise _Declined("source_host_not_admitted", "Krea Enhance source host refused")
        return source

    def enhance(self, task_id, origin, *, actor="jarvis"):
        """Propose one fresh Enhance payment for a completed, approved Krea image."""
        if type(task_id) is not int or not 1 <= task_id < 2**63:
            raise ValueError("invalid Krea Enhance source id")
        source = self.worker.queue.get(task_id)
        if not matches(source) or source.payload["plugin"] != KREA_PLUGIN:
            raise ValueError("invalid Krea Enhance source")
        if "resume" in source.payload["image"]:
            # A continuation must itself have executed before selecting its result.
            self.recover(source)
            source = self._resume_source(source.payload)
        if set(source.payload["image"]) != {"body", "generation", "nonce", "version"}:
            raise ValueError("Krea Enhance requires an original generation")
        try:
            done = _json(self._path(source, "complete"))
        except (OSError, ValueError):
            raise ValueError("Krea Enhance requires a completed generation") from None
        body = source.payload["image"]["body"]
        self._available(plugin=KREA_PLUGIN)
        _, generation = self._configuration(KREA_PLUGIN)
        payload = {"plugin": KREA_PLUGIN, "method": "POST", "url": krea_image.ENHANCE_ENDPOINT,
                   "image": {"body": krea_enhance.normalize_request(body["prompt"], {
                       "backend": "krea", "model": body["model"], "size": body["size"],
                       "enhance_image_url": done["provider_result_url"]}),
                       "generation": generation, "nonce": uuid.uuid4().hex, "version": KREA_VERSION,
                       "enhance": {"task_id": source.id, "nonce": source.payload["image"]["nonce"],
                                   "binding": _task_binding(source), "artifact_id": done["artifact"]["artifact_id"],
                                   "sha256": done["sha256"]}}}
        self.validate(payload)
        task_id = self.worker.govern_enqueue(agent=actor, kind="plugin.egress",
            title="Paid Krea Enhance: one 2x pass; preserve the original image",
            payload=payload, risk_tier=3, autonomy_level="ask", origin=origin)
        task = self.worker.queue.get(task_id)
        if not matches(task) or task.payload["image"] != payload["image"]:
            raise ValueError("Krea Enhance proposal unavailable")
        _write(self._path(task, "proposal"), json.dumps({"binding": _task_binding(task)}).encode())
        return task_id

    def _resume_source(self, payload, *, key=None, authority=True):
        image = payload["image"]
        descriptor = image.get("resume")
        if (not isinstance(descriptor, dict) or set(descriptor) != {"task_id", "nonce", "job_id", "binding"}
                or type(descriptor["task_id"]) is not int or descriptor["task_id"] < 1):
            raise ValueError("invalid Krea continuation")
        source = self.worker.queue.get(descriptor["task_id"])
        if (not matches(source) or source.payload["plugin"] != KREA_PLUGIN
                or source.payload.get("method") != "POST" or "resume" in source.payload["image"]):
            raise ValueError("invalid Krea source")
        self._bound(source)
        original = source.payload["image"]
        binding = _task_binding(source)
        job = _json(self._path(source, "job"))
        if (descriptor["nonce"] != original["nonce"] or descriptor["binding"] != binding
                or job.get("binding") != binding or job.get("job_id") != descriptor["job_id"]
                or job.get("generation") != original["generation"] or image["body"] != original["body"]
                or _json(self._path(source, "attempt")) != {"binding": binding}):
            raise ValueError("Krea source changed")
        krea_image.poll_endpoint(descriptor["job_id"])
        if authority:
            if (source.status not in {"running", "done", "failed"} or source.decision not in {"accept", "edit"}
                    or not source.decided_by or str(source.decided_by).strip().lower() == "policy"
                    or not job.get("execution_fingerprint")
                    or job["execution_fingerprint"] != TaskQueue.execution_fingerprint(source)):
                raise _Declined("source_approval_changed", "Krea source approval changed")
            if key is None:
                self._available(plugin=KREA_PLUGIN)
                key, generation = self._configuration(KREA_PLUGIN)
            else:
                _, generation = self._configuration(KREA_PLUGIN)
            if "principal" in job:
                if job["principal"] != hashlib.sha256(key.encode()).hexdigest():
                    raise _Declined("source_principal_changed", "Krea source credential changed")
            elif original["generation"] != generation:
                raise _Declined("legacy_job_principal_unavailable", "Krea legacy job identity unavailable")
        return source

    def resume(self, task_id, origin, *, actor="jarvis"):
        if type(task_id) is not int or not 1 <= task_id < 2**63:
            raise ValueError("invalid Krea source id")
        source = self.worker.queue.get(task_id)
        if not matches(source) or source.payload["plugin"] != KREA_PLUGIN:
            raise ValueError("invalid Krea source")
        if "resume" in source.payload["image"]:
            source = self._resume_source(source.payload)
        self._available(plugin=KREA_PLUGIN)
        self._bound(source)
        if self._path(source, "complete").exists():
            raise ValueError("Krea source already completed")
        job = _json(self._path(source, "job"))
        _, generation = self._configuration(KREA_PLUGIN)
        payload = {"plugin": KREA_PLUGIN, "method": "GET", "url": krea_image.poll_endpoint(job["job_id"]),
                   "image": {"body": source.payload["image"]["body"], "generation": generation,
                             "nonce": uuid.uuid4().hex, "version": KREA_VERSION,
                             "resume": {"task_id": source.id, "nonce": source.payload["image"]["nonce"],
                                        "job_id": job["job_id"], "binding": _task_binding(source)}}}
        if "enhance" in source.payload["image"]:
            payload["image"]["enhance"] = source.payload["image"]["enhance"]
        self.validate(payload)
        try:
            with _file_lock(self._path(source, "activity.lock"), timeout=0):
                task_id = self.worker.govern_enqueue(agent=actor, kind="plugin.egress",
                    title="Continue saved Krea job: polling and local artifact; no generation POST",
                    payload=payload, risk_tier=3, autonomy_level="ask", origin=origin)
                task = self.worker.queue.get(task_id)
                if not matches(task) or task.payload["image"] != payload["image"]:
                    raise ValueError("Krea continuation unavailable")
                _write(self._path(task, "proposal"), json.dumps({"binding": _task_binding(task)}).encode())
        except VaultError:
            raise _Declined("krea_job_busy", "Krea job is active or unavailable") from None
        return task_id

    def submit(self, prompt, options, origin, *, actor="jarvis"):
        selector = options.get("backend") if isinstance(options, dict) else None
        plugin = {"fal": FAL_PLUGIN, "openai-codex": CODEX_PLUGIN,
                  "openrouter": OPENROUTER_PLUGIN, "krea": KREA_PLUGIN,
                  "xai": XAI_PLUGIN, "deepinfra": DEEPINFRA_PLUGIN,
                  None: PLUGIN, "openai": PLUGIN}.get(selector)
        if plugin is None:
            raise ValueError("unsupported cloud image backend")
        catalog = self.catalog() if plugin == DEEPINFRA_PLUGIN else None
        body = _normalize_body(plugin, prompt, options, self.root, catalog=catalog)
        endpoint = _endpoint(plugin, body)
        self._available(plugin=plugin)
        _, generation = self._configuration(plugin)
        payload = {
            "plugin": plugin,
            "method": "POST",
            "url": endpoint,
            "image": {
                "body": body,
                "generation": generation,
                "nonce": uuid.uuid4().hex,
                "version": _VERSIONS[plugin],
            },
        }
        if plugin == DEEPINFRA_PLUGIN:
            payload["image"]["catalog_digest"] = self._catalog_digest(catalog)
        self.validate(payload)
        task_id = self.worker.govern_enqueue(
            agent=actor,
            kind="plugin.egress",
            title=("Paid FAL image generation: one image and local artifact" if plugin == FAL_PLUGIN
                   else "Codex OAuth image generation: one image and local artifact" if plugin == CODEX_PLUGIN
                   else "Paid OpenRouter image generation: one selected model and local artifact" if plugin == OPENROUTER_PLUGIN
                   else "Paid Krea image generation: one submit, job polling and local artifact" if plugin == KREA_PLUGIN
                   else "Paid xAI image generation or edit: one image and local artifact" if plugin == XAI_PLUGIN
                   else "Paid DeepInfra image generation: one catalog-selected model and local artifact" if plugin == DEEPINFRA_PLUGIN
                   else "Paid OpenAI image generation: one image and local artifact"),
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
        if "resume" in task.payload["image"]:
            self._bound(task)
            if (task.status not in {"running", "done", "failed"} or task.decision not in {"accept", "edit"}
                    or not task.decided_by or str(task.decided_by).strip().lower() == "policy"
                    or not task.mediation_execution_id
                    or _json(self._path(task, "continuation-authority")) != {
                        "fingerprint": TaskQueue.execution_fingerprint(task)}):
                raise ValueError("Krea continuation execution unavailable")
            task = self._resume_source(task.payload, authority=False)
        with _file_lock(self._path(task, "finalize.lock")):
            return self._recover(task)

    def _recover(self, task):
        self._bound(task)
        done = _json(self._path(task, "complete"))
        if done["binding"] != _task_binding(task):
            raise ValueError("cloud image completion changed")
        artifact = done["artifact"]
        from .media_backends.comfyui import artifact_bytes

        data = artifact_bytes(artifact["artifact_id"], self.root / "media" / "generated",
                              max_dimension=self._artifact_limit(task))
        if hashlib.sha256(data).hexdigest() != done["sha256"]:
            raise ValueError("cloud image artifact changed")
        if self._artifact_limit(task) == 4096:
            self._artifact_proof(task, done, data)
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
                    backend=("fal:" + task.payload["image"]["body"]["model"]
                             if task.payload["plugin"] == FAL_PLUGIN else
                             "openai-codex:" + task.payload["image"]["body"]["model"]
                             if task.payload["plugin"] == CODEX_PLUGIN else
                             "openrouter:" + task.payload["image"]["body"]["model"]
                             if task.payload["plugin"] == OPENROUTER_PLUGIN else
                             {KREA_PLUGIN: "krea", XAI_PLUGIN: "xai", DEEPINFRA_PLUGIN: "deepinfra"}[
                                 task.payload["plugin"]] + ":" + task.payload["image"]["body"]["model"]
                             if task.payload["plugin"] in {KREA_PLUGIN, XAI_PLUGIN, DEEPINFRA_PLUGIN} else
                             "openai:" + task.payload["image"]["body"].get(
                                 "selected_model", "gpt-image-1.5")),
                    cloud=True,
                    record_id="md-" + hashlib.sha256(_task_binding(task).encode()).hexdigest()[:12],
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

    @staticmethod
    def _artifact_limit(task):
        return (4096 if task.payload["plugin"] == KREA_PLUGIN
                and task.payload["image"]["body"].get("operation") == "enhance" else 2048)

    def _artifact_proof(self, task, done, data):
        """A private completed execution binds the wider download to exact pixels."""
        from .media_backends.comfyui import validate_png

        artifact = done["artifact"]
        job = _json(self._path(task, "job"))
        fingerprint = TaskQueue.execution_fingerprint(task)
        if (task.status not in {"running", "done", "failed"} or task.decision not in {"accept", "edit"}
                or not task.decided_by or str(task.decided_by).strip().lower() == "policy"
                or not task.mediation_execution_id or job.get("execution_fingerprint") != fingerprint
                or (artifact["width"], artifact["height"]) != validate_png(data, max_dimension=4096)
                or artifact["bytes"] != len(data)):
            raise ValueError("Krea Enhance artifact execution unavailable")
        proof = {"task_id": task.id, "nonce": task.payload["image"]["nonce"],
                 "binding": _task_binding(task), "sha256": done["sha256"],
                 "max_dimension": 4096, "execution_fingerprint": fingerprint}
        path = self.records / (artifact["artifact_id"] + ".artifact")
        if path.exists() or path.is_symlink():
            if _json(path) != proof:
                raise ValueError("Krea Enhance artifact proof changed")
        else:
            _write(path, json.dumps(proof).encode())

    def read_artifact(self, artifact_id):
        """Read proof-bound Enhance output; None leaves normal IDs to the 2K reader."""
        from .media_backends.comfyui import ImageGenerationError, artifact_bytes

        if not isinstance(artifact_id, str) or not re.fullmatch("[a-f0-9]{32}", artifact_id):
            raise ImageGenerationError("reference_not_found")
        path = self.records / (artifact_id + ".artifact")
        if not path.exists() and not path.is_symlink():
            return None
        try:
            proof = _json(path)
            if type(proof.get("task_id")) is not int or not 1 <= proof["task_id"] < 2**63:
                raise ValueError
            source = self.worker.queue.get(proof["task_id"])
            if not matches(source) or self._artifact_limit(source) != 4096:
                raise ValueError
            self._bound(source)
            done = _json(self._path(source, "complete"))
            if (done["binding"] != _task_binding(source)
                    or done["artifact"]["artifact_id"] != artifact_id
                    or done["sha256"] != proof["sha256"]):
                raise ValueError
            data = artifact_bytes(artifact_id, self.root / "media" / "generated", max_dimension=4096)
            if hashlib.sha256(data).hexdigest() != done["sha256"]:
                raise ValueError
            self._artifact_proof(source, done, data)
            return data
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise ImageGenerationError("reference_not_found") from None

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
            try:
                if task.payload["plugin"] == KREA_PLUGIN:
                    source = (self._resume_source(task.payload) if "resume" in task.payload["image"] else task)
                    if not self._path(source, "complete").exists():
                        job = _json(self._path(source, "job"))
                        descriptor = {"task_id": source.id, "nonce": source.payload["image"]["nonce"],
                                      "job_id": job["job_id"], "binding": _task_binding(source)}
                        self._resume_source({"image": {"body": source.payload["image"]["body"], "resume": descriptor}})
                        with _file_lock(self._path(source, "activity.lock"), timeout=0):
                            view.resume_available = True
            except Exception:
                view.resume_available = False
            return view
        try:
            if task.payload["plugin"] == KREA_PLUGIN:
                source = self._resume_source(task.payload) if "resume" in task.payload["image"] else task
                done = _json(self._path(source, "complete"))
                body = source.payload["image"]["body"]
                self._enhance_source({"image": {"body": krea_enhance.normalize_request(body["prompt"], {
                    "backend": "krea", "model": body["model"], "size": body["size"],
                    "enhance_image_url": done["provider_result_url"]}),
                    "enhance": {"task_id": source.id, "nonce": source.payload["image"]["nonce"],
                                "binding": _task_binding(source), "artifact_id": done["artifact"]["artifact_id"],
                                "sha256": done["sha256"]}}})
                view.enhance_available = True
        except Exception:
            view.enhance_available = False
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
        job_id = None
        catalog_refresh = False
        resources = ExitStack()
        try:
            plugin = task.payload["plugin"]
            endpoint = task.payload["url"]
            download_url = None
            poll_url = None
            self.validate(task.payload)
            self._bound(task)
            continuation = plugin == KREA_PLUGIN and "resume" in task.payload["image"]
            catalog_refresh = (plugin == DEEPINFRA_PLUGIN and task.payload["method"] == "GET")
            source = self._resume_source(task.payload) if continuation else task
            if plugin == KREA_PLUGIN:
                try:
                    resources.enter_context(_file_lock(self._path(source, "activity.lock"), timeout=0))
                except VaultError:
                    raise _Declined("krea_job_busy", "Krea job is active or unavailable") from None
            if continuation:
                _write(self._path(task, "continuation-authority"),
                       json.dumps({"fingerprint": fingerprint}).encode())
            if self._path(source, "complete").exists():
                phase = "published"
                return self.recover(task)
            attempted = self._path(source, "attempt")
            if attempted.exists() and not continuation:
                # A submission an earlier attempt may have made: never replayed, its
                # result not known — the worker records ``unknown`` as a failure.
                return {
                    "status": "unknown",
                    "reason": "cloud image submission may have occurred; not replayed",
                }
            key = self.validate(task.payload)
            if continuation:
                job_id = task.payload["image"]["resume"]["job_id"]
                poll_url = krea_image.poll_endpoint(job_id)
                phase = "dialled"
            approved_body = task.payload["image"]["body"]
            references = approved_body.get("references", []) if plugin not in {FAL_PLUGIN, KREA_PLUGIN} else []
            image_inputs = _reference_bytes(self.root, references) if references else []
            if image_inputs and [hashlib.sha256(data).hexdigest() for data in image_inputs] != \
                    approved_body.get("reference_digests"):
                raise _Declined("reference_changed", "cloud image reference changed")
            if plugin == XAI_PLUGIN:
                request = {"json": xai_image.wire_body(_provider_body(plugin, approved_body), image_inputs)}
                headers = xai_image.auth_headers(key)
            elif plugin == DEEPINFRA_PLUGIN:
                request = {} if catalog_refresh else {"json": deepinfra_image.wire_body(approved_body)}
                headers = deepinfra_image.auth_headers(key)
            elif plugin == OPENROUTER_PLUGIN:
                request = {"json": openrouter_image.wire_body(_provider_body(plugin, approved_body), image_inputs)}
                headers = openrouter_image.auth_headers(key)
            elif plugin == KREA_PLUGIN:
                request = {"json": (krea_enhance.wire_body(approved_body) if "enhance" in task.payload["image"]
                                    else krea_image.wire_body(_provider_body(plugin, approved_body)))}
                headers = {"Authorization": "Bearer " + key}
            elif plugin == FAL_PLUGIN:
                request = {"json": fal_image.normalize_request(
                    approved_body["prompt"],
                    {"backend": "fal", **{k: approved_body[k] for k in
                     ("model", "size", "references", "seed", "steps") if k in approved_body}},
                )["body"]}
                headers = {"Authorization": "Key " + key, "X-Fal-No-Retry": "1"}
            elif plugin == CODEX_PLUGIN:
                request = {"json": codex_image.wire_body(approved_body, image_inputs)}
                headers = key.headers
            else:
                wire = {k: v for k, v in approved_body.items() if k not in {
                    "selected_model", "references", "reference_digests"}}
                if image_inputs:
                    request = {"data": {k: str(v) for k, v in wire.items()},
                               "files": [("image", (f"reference-{i}.png", data, "image/png"))
                                         for i, data in enumerate(image_inputs)]}
                else:
                    request = {"json": wire}
                headers = {"Authorization": "Bearer " + key}

            def live_check(method, url):
                self.validate(task.payload)
                self._bound(task)
                if estop.is_engaged():
                    raise _Declined("estop_engaged", "cloud image dispatch refused")
                if not ((method == task.payload["method"] and url == endpoint) or
                        (plugin in {FAL_PLUGIN, OPENROUTER_PLUGIN, KREA_PLUGIN, XAI_PLUGIN, DEEPINFRA_PLUGIN} and method == "GET" and
                         download_url is not None and url == download_url) or
                        (plugin == KREA_PLUGIN and method == "GET" and poll_url is not None and url == poll_url)):
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
                if method == "POST" or catalog_refresh:
                    _write(attempted, json.dumps({"binding": _task_binding(task)}).encode())
                    phase = "dialled"

            client = _Client(
                check, plugin=plugin, gate=self.gate, resolver=self.resolver,
                transport_factory=self.transport_factory
            )
            try:
                async with asyncio.timeout(300 if plugin in {CODEX_PLUGIN, OPENROUTER_PLUGIN} else 180):
                    if catalog_refresh:
                        async with client.stream("GET", endpoint, follow_redirects=False, headers={
                            **headers, "Accept-Encoding": "identity", "Accept": "application/json",
                        }) as response:
                            if (response.status_code != 200 or
                                    response.headers.get("content-encoding", "identity") != "identity"):
                                raise _ProviderFailed("cloud_image_catalog_error", "image catalog refused")
                            raw = bytearray()
                            async for chunk in response.aiter_bytes():
                                if len(raw) + len(chunk) > deepinfra_image.MAX_CATALOG_BYTES:
                                    raise _ProviderFailed("cloud_image_catalog_too_large", "image catalog too large")
                                raw.extend(chunk)
                            catalog = deepinfra_image.catalog_from_response(json.loads(raw))
                        live_check("GET", endpoint)
                        digest = self._catalog_digest(catalog)
                        record = {"catalog": catalog, "task_id": task.id, "binding": _task_binding(task),
                                  "execution_fingerprint": fingerprint}
                        _write(self.records / "deepinfra-models.json", json.dumps(record).encode(), replace=True)
                        return {"status": "ok", "tool": "cloud_image_catalog_refresh",
                                "models_count": len(catalog), "catalog_digest": digest}
                    if not continuation:
                        async with client.stream(
                            "POST",
                            endpoint,
                            follow_redirects=False,
                            **request,
                            headers={
                                **headers,
                                "Accept-Encoding": "identity",
                                "Accept": "application/json",
                            },
                        ) as response:
                            if (
                                response.status_code not in ({200, 202} if plugin == KREA_PLUGIN else {200})
                                or response.headers.get("content-encoding", "identity") != "identity"
                            ):
                                raise _ProviderFailed("cloud_image_provider_error",
                                                      "cloud image provider refused")
                            body = bytearray()
                            response_limit = (32768 if plugin == KREA_PLUGIN else
                                              fal_image.MAX_RESPONSE if plugin == FAL_PLUGIN else MAX_RESPONSE)
                            async for chunk in response.aiter_bytes():
                                if len(body) + len(chunk) > response_limit:
                                    raise _ProviderFailed("cloud_image_response_too_large",
                                                          "cloud image response too large")
                                body.extend(chunk)
                            try:
                                if plugin in {OPENROUTER_PLUGIN, XAI_PLUGIN, DEEPINFRA_PLUGIN}:
                                    parser = {OPENROUTER_PLUGIN: openrouter_image, XAI_PLUGIN: xai_image,
                                              DEEPINFRA_PLUGIN: deepinfra_image}[plugin]
                                    kind, content = parser.parse_response(json.loads(body))
                                    if kind == "url":
                                        download_url = content
                                    elif plugin == DEEPINFRA_PLUGIN:
                                        data, dimensions = fal_image.decode_image(content)
                                    else:
                                        from .media_backends.comfyui import validate_png

                                        data, dimensions = content, validate_png(content)
                                elif plugin == KREA_PLUGIN:
                                    job_id = krea_image.parse_job_id(json.loads(body))
                                    poll_url = krea_image.poll_endpoint(job_id)
                                    _write(self._path(task, "job"), json.dumps({
                                        "binding": _task_binding(task), "job_id": job_id,
                                        "generation": task.payload["image"]["generation"],
                                        "principal": hashlib.sha256(key.encode()).hexdigest(),
                                        "execution_fingerprint": fingerprint,
                                    }).encode())
                                elif plugin == FAL_PLUGIN:
                                    download_url = fal_image.result_url(json.loads(body))
                                else:
                                    data = decode_result(
                                        json.loads(body), task.payload["image"]["body"]["size"]
                                    )
                            except (ValueError, TypeError, KeyError, RecursionError):
                                raise _ProviderFailed("cloud_image_invalid_response",
                                                      "cloud image response invalid") from None
                    if plugin == KREA_PLUGIN:
                        async def get_status(url):
                            async with client.stream("GET", url, follow_redirects=False, headers={
                                **headers, "Accept-Encoding": "identity", "Accept": "application/json",
                            }) as response:
                                if response.headers.get("content-encoding", "identity") != "identity":
                                    raise krea_jobs.KreaPollResponseError()
                                raw = bytearray()
                                async for chunk in response.aiter_bytes():
                                    if len(raw) + len(chunk) > 32768:
                                        raise krea_jobs.KreaPollResponseError()
                                    raw.extend(chunk)
                                if not 200 <= response.status_code < 300:
                                    return response.status_code, None
                                return response.status_code, json.loads(raw)

                        try:
                            download_url = await krea_jobs.poll_job(
                                job_id, get_status, check=lambda: live_check("GET", poll_url),
                                sleep=self.poll_sleep or asyncio.sleep,
                            )
                        except krea_jobs.KreaJobFailed:
                            raise _ProviderFailed("krea_job_failed", "Krea job failed") from None
                        except krea_jobs.KreaPollResponseError:
                            raise _ProviderFailed("krea_job_invalid_response", "Krea job response invalid") from None
                    if download_url is not None:
                        async with client.stream(
                            "GET", download_url, follow_redirects=False,
                            headers={"Accept-Encoding": "identity", "Accept": "image/*"},
                        ) as response:
                            if (response.status_code != 200 or
                                    response.headers.get("content-encoding", "identity") != "identity"):
                                raise _ProviderFailed("cloud_image_provider_error",
                                                      "cloud image download refused")
                            raw = bytearray()
                            async for chunk in response.aiter_bytes():
                                if len(raw) + len(chunk) > fal_image.MAX_IMAGE:
                                    raise _ProviderFailed("cloud_image_response_too_large",
                                                          "cloud image download too large")
                                raw.extend(chunk)
                            try:
                                data, dimensions = fal_image.decode_image(bytes(raw),
                                    max_dimension=self._artifact_limit(source))
                            except ValueError:
                                raise _ProviderFailed("cloud_image_invalid_response",
                                                      "cloud image download invalid") from None
            finally:
                await client.close()
            phase = "generated"
            live_check(task.payload["method"], endpoint)
            phase = "published"
            artifact_id = uuid.uuid4().hex
            destination = self.root / "media" / "generated" / (artifact_id + ".png")
            _write(destination, data)
            width, height = (dimensions if plugin in {FAL_PLUGIN, OPENROUTER_PLUGIN, KREA_PLUGIN, XAI_PLUGIN, DEEPINFRA_PLUGIN} else
                             tuple(map(int, task.payload["image"]["body"]["size"].split("x"))))
            done = {
                "binding": _task_binding(source),
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
            if plugin == KREA_PLUGIN:
                done["provider_result_url"] = download_url
                done["job_id"] = job_id
                job = _json(self._path(source, "job"))
                job.update(provider_result_url=download_url, result_sha256=done["sha256"])
                _write(self._path(source, "job"), json.dumps(job).encode(), replace=True)
            _write(self._path(source, "complete"), json.dumps(done).encode())
            return self.recover(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Provider exceptions/body can contain credentials or prompt content: only a
            # fixed reason code ever leaves here.
            result = ({"status": "refused" if isinstance(exc, _Declined) else "failed",
                       "reason": exc.reason if isinstance(exc, _Declined) else "cloud_image_catalog_refresh_failed"}
                      if catalog_refresh else _attempt_result(phase, exc))
            if job_id is not None:
                result["job_id"] = job_id
                result["submission_replayed"] = False
                if isinstance(exc, _Declined):
                    result["detail"] = exc.reason
            return result
        finally:
            resources.close()


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
