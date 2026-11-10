"""video_generation.py — paid video generation through the adopted Hermes providers (G19, H516).

The owner asks for a video (the ``video_generate`` tool, gated). Nothing is sent until the
owner approves one card: the card names the provider, the model, the duration and an
upper-bound cost (``video_providers.estimate``), and the task carries that cost as its
``amount`` (the autonomy policy's money accounting). The approved task then runs once on the
autonomy worker, under the same governance as the reviewed cloud image path
(``cloud_image_runtime``), whose helpers this module reuses:

* **Availability** — heavy features on, enforced mediation, the Action Kernel on, a signer,
  the provider chosen by the owner with consent (``JARVIS_VIDEO_PROVIDER``, the HUD's
  Integrations panel) and its key set. Refused while the e-stop is engaged; a plan-mode
  conversation never reaches it (the tool front door and the kernel refuse a non-read).
* **One attempt** — a durable attempt marker is written before the first POST: a task that
  stopped after it is never replayed (``unknown``: the provider may have billed it).
* **Every request** goes through the task's own ``PluginHTTPClient`` (one RESTRICTED
  manifest per provider: its own hosts only, SSRF pinning, ledger) and a live check before
  each dial: the approval still binds, the e-stop is off, the mediation receipt is valid,
  the kernel does not deny, and a POST goes only to the provider's API host.
* **Vendored code runs off the loop** on a small executor of its own (2 threads, 2 jobs at a
  time), with the egress client, the provider scope (its one key) and a staging folder bound
  in its context. The job has :data:`VIDEO_DEADLINE_SECONDS`; when the worker cancels it or
  the deadline passes, the poll's sleep wakes and its next request is refused, so no thread
  outlives its task.
* **The file** is untrusted: at most :data:`MAX_VIDEO_BYTES` (the media store's own limit),
  streamed and capped, and kept only if it is an MP4 or WebM the media store recognizes. It
  is published under a Nerva-minted name in ``media/generated`` and recorded in the media
  catalog (kind ``video``), so the owner opens it from the media gallery
  (``/api/artifacts/md-…/blob``). Provider text (errors, model names) never reaches the
  owner or a model except as a fixed reason code.
"""

from __future__ import annotations

import asyncio
import base64
import contextvars
import hashlib
import json
import logging
import re
import shutil
import time
import uuid
import weakref
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

from .. import estop
from ..autonomy.executor import ExecutionGuardDeclined
from ..autonomy.queue import MediationStateUnavailable, TaskQueue
from ..cloud_image_runtime import (
    _Claim,
    _Declined,
    _json,
    _ProviderFailed,
    _safe,
    _StateUnavailable,
    _write,
)
from ..env_config import env_str
from ..http_client import PluginEgressError, PluginHTTPClient, PluginTimeouts
from ..image_generation_runtime import _task_binding
from ..kernel import Action, Verdict, kernel_enabled
from ..media_catalog import MediaCatalog
from ..paths import data_root
from ..security.taint import is_untrusted_source
from ..vault import _file_lock
from . import video_providers as vp

logger = logging.getLogger("jarvis.creative.video_generation")

VERSION = "hermes-video-v1"
TOOL = "video_generate"
#: The whole job: submit, polls, download (the worker's own task budget is longer).
VIDEO_DEADLINE_SECONDS = 900.0
#: The largest video kept (the media store serves files up to this size).
MAX_VIDEO_BYTES = 16 * 1024 * 1024
#: Image inputs sent as data URIs, in all.
MAX_IMAGE_INPUT_BYTES = 12 * 1024 * 1024
EXECUTOR_WORKERS = 2
MAX_CONCURRENT = 2
QUEUE_WAIT_SECONDS = 30.0
PLUGINS = frozenset(row.plugin for row in vp.PROVIDERS.values())
_BY_PLUGIN = {row.plugin: row for row in vp.PROVIDERS.values()}
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,39}")

_EXECUTOR = ThreadPoolExecutor(max_workers=EXECUTOR_WORKERS, thread_name_prefix="hermes-video")
_SLOTS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _slots(loop: asyncio.AbstractEventLoop) -> asyncio.Semaphore:
    sem = _SLOTS.get(loop)
    if sem is None:
        sem = _SLOTS[loop] = asyncio.Semaphore(MAX_CONCURRENT)
    return sem


def matches(task) -> bool:
    return (getattr(task, "kind", None) == "plugin.egress"
            and isinstance(getattr(task, "payload", None), dict)
            and task.payload.get("plugin") in PLUGINS)


def endpoint(body: dict) -> str:
    """The provider URL the approval names (the submit request)."""
    name, operation = body["provider"], body.get("operation", "generate")
    if name == "fal":
        family = vp.plugin_module("fal").FAL_FAMILIES[body["model"]]
        modality = "image" if any(i.startswith("image:") for i in body.get("images", [])) else "text"
        return "https://queue.fal.run/" + family[f"{modality}_endpoint"]
    if name == "xai":
        path = {"generate": "generations", "edit": "edits", "extend": "extensions"}[operation]
        return f"https://api.x.ai/v1/videos/{path}"
    return "https://api.deepinfra.com/v1/openai/videos"


def _args_of(body: dict) -> dict:
    """The tool arguments a stored body was normalized from (re-checked at every use)."""
    args = {key: body[key] for key in ("provider", "prompt", "model", "aspect_ratio", "resolution",
                                       "negative_prompt", "seed", "audio", "source_task_id")
            if key in body}
    if body.get("duration") is not None:
        args["duration"] = body["duration"]
    if body.get("operation", "generate") != "generate":
        args["operation"] = body["operation"]
        args.pop("aspect_ratio", None)
        args.pop("resolution", None)
    refs = []
    for image in body.get("images", []):
        role, ref = image.split(":", 1)
        if role == "image":
            args["image"] = ref
        else:
            refs.append(ref)
    if refs:
        args["reference_images"] = refs
    return args


class _VideoClient(PluginHTTPClient):
    """The task's egress client: its provider's manifest, then the live check per dial.

    A refusal is raised as ``PluginEgressError`` (the compat ``httpx`` latches it as a
    policy refusal, so vendored code cannot retry past it) and its reason is kept in
    :attr:`refusal` for the runtime to report."""

    def __init__(self, check, *, plugin, gate=None, **kwargs):
        super().__init__(plugin, timeouts=PluginTimeouts(connect=10, read=90, total=95), **kwargs)
        self.check = check
        self.gate = gate
        self.refusal: Exception | None = None

    def _refuse(self, exc: Exception) -> None:
        if self.refusal is None:
            self.refusal = exc
        raise PluginEgressError("egress blocked: video request refused") from None

    def _manifest_mode(self, url):
        from urllib.parse import urlsplit

        from ..plugin_gate import BUILTIN_PLUGINS, NetworkAccess, host_in_allowlist

        manifest = (self.gate.plugins if self.gate is not None else BUILTIN_PLUGINS).get(self.plugin_name)
        host = urlsplit(url).hostname or ""
        row = _BY_PLUGIN.get(self.plugin_name)
        # Shipped disabled like the cloud-image manifests; on only while the owner has this
        # provider chosen (an explicit enable through the plugin gate also counts).
        enabled = manifest is not None and (manifest.enabled or (row is not None and vp.chosen() == row.name))
        if (manifest is None or not enabled
                or manifest.network_access is not NetworkAccess.RESTRICTED
                or urlsplit(url).scheme != "https"
                or not host_in_allowlist(host, manifest.allowed_domains)):
            self._refuse(_Declined("video_host_not_admitted", "video egress host refused"))
        return "public"

    def _enforce_kernel(self, method, url, host):
        try:
            self._manifest_mode(url)
            self.check(method, url)
        except PluginEgressError:
            raise
        except Exception as exc:
            self._refuse(exc)


class CloudVideoRuntime:
    def __init__(self, worker, *, kernel, redact, root=None, gate=None, resolver=None,
                 transport_factory=None, deadline=VIDEO_DEADLINE_SECONDS, max_bytes=MAX_VIDEO_BYTES):
        self.worker, self.kernel, self.redact = worker, kernel, redact
        self.gate = gate
        self.root = Path(root) if root is not None else data_root()
        self.resolver, self.transport_factory = resolver, transport_factory
        self.deadline = float(deadline)
        self.max_bytes = int(max_bytes)
        self._claim = contextvars.ContextVar("cloud_video_claim", default=None)

    @property
    def records(self):
        return _safe(self.root / "media" / "cloud-video")

    # ── availability and configuration ─────────────────────────────────────────

    def _available(self, provider, *, probe_signing=True):
        from ..system_profiles import heavy_features_enabled

        row = vp.PROVIDERS.get(provider)
        if row is None:
            raise _Declined("no_video_provider", "video provider unknown")
        if estop.is_engaged():
            raise _Declined("estop_engaged", "video generation refused while the e-stop is engaged")
        if not heavy_features_enabled():
            raise _Declined("video_generation_unavailable", "video generation paused")
        if vp.chosen() != provider:
            raise _Declined("video_provider_not_chosen", "the owner has not chosen this video provider")
        if not vp.key_set(provider):
            raise _Declined("credential_not_configured", "video provider key not set")
        if self.worker.queue.mediation_mode != "enforce" or not kernel_enabled():
            raise _Declined("enforced_mediation_unavailable", "video enforced mediation unavailable")
        if not callable(self.kernel) or not callable(self.redact):
            raise ValueError("video enforced mediation unavailable")
        signer = getattr(self.worker, "_mediation_signer", None)
        if not callable(getattr(signer, "sign", None)) or (
                probe_signing and signer.sign(b"cloud-video availability") is None):
            raise ValueError("video signing unavailable")
        return row

    def _configuration(self, provider):
        """A random generation bound to (version, key digest): a key change voids approvals."""
        row = vp.PROVIDERS[provider]
        key = str(env_str(row.key, "") or "").strip()
        if not key:
            raise _Declined("credential_not_configured", "video provider key not set")
        digest = hashlib.sha256((VERSION + "\0" + provider + "\0" + key).encode()).hexdigest()
        path = self.records / f"{provider}-configuration.json"
        with _file_lock(self.records / f"{provider}-configuration.lock"):
            old = _json(path) if path.exists() else {}
            if old.get("digest") != digest:
                old = {"digest": digest, "generation": uuid.uuid4().hex}
                _write(path, json.dumps(old).encode(), replace=True)
        return key, old["generation"]

    def status(self) -> dict:
        """What the media panel shows (no key value, no request)."""
        providers = {}
        choice = vp.chosen()
        for name, row in vp.PROVIDERS.items():
            providers[name] = {"display_name": row.display, "configured": vp.key_set(name),
                               "chosen": choice == name, "host": row.host,
                               "operations": list(row.operations)}
        return {"provider": choice or None, "approval_required": True, "providers": providers,
                "max_bytes": self.max_bytes, "deadline_seconds": int(self.deadline)}

    # ── inputs ─────────────────────────────────────────────────────────────────

    def _hosts(self, plugin):
        from ..plugin_gate import BUILTIN_PLUGINS

        manifest = (self.gate.plugins if self.gate is not None else BUILTIN_PLUGINS).get(plugin)
        return tuple(manifest.allowed_domains) if manifest is not None else ()

    def _image_bytes(self, artifact_id):
        from ..media_backends.comfyui import artifact_bytes

        return artifact_bytes(artifact_id, self.root / "media" / "generated")

    def _bind_images(self, body):
        """Digest each generated-image input into the body the approval binds."""
        total, digests = 0, []
        for image in body["images"]:
            ref = image.split(":", 1)[1]
            if vp.ARTIFACT_ID.fullmatch(ref):
                data = self._image_bytes(ref)
                total += len(data)
                if total > MAX_IMAGE_INPUT_BYTES:
                    raise ValueError("video image inputs too large")
                digests.append(hashlib.sha256(data).hexdigest())
            else:
                digests.append("")
        if digests:
            body["image_sha256"] = digests

    def _image_inputs(self, body):
        """Data URIs for Nerva artifacts (re-read, digest re-checked) or provider URLs."""
        image_url, refs = None, []
        for image, digest in zip(body["images"], body.get("image_sha256", []), strict=True):
            role, ref = image.split(":", 1)
            if vp.ARTIFACT_ID.fullmatch(ref):
                data = self._image_bytes(ref)
                if hashlib.sha256(data).hexdigest() != digest:
                    raise _Declined("reference_changed", "video image input changed")
                value = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
            else:
                value = ref
            if role == "image":
                image_url = value
            else:
                refs.append(value)
        return image_url, refs

    def _source(self, source_task_id):
        """A completed, owner-approved xAI video this hub generated (edit / extend input)."""
        source = self.worker.queue.get(source_task_id)
        if (not matches(source) or source.payload["plugin"] != vp.PROVIDERS["xai"].plugin
                or source.status != "done" or source.decision not in {"accept", "edit"}
                or not source.decided_by or str(source.decided_by).strip().lower() == "policy"):
            raise ValueError("video source unavailable")
        self._bound(source)
        done = _json(self._path(source, "complete"))
        url = done.get("provider_url")
        from urllib.parse import urlsplit

        parts = urlsplit(url or "")
        if (done.get("binding") != _task_binding(source) or parts.scheme != "https"
                or (parts.hostname or "") != "vidgen.x.ai"):
            raise ValueError("video source unavailable")
        reported = done.get("artifact", {}).get("duration")
        billed = source.payload["video"]["body"].get("billed_seconds")
        # The provider's reported length, else what the source was billed for (an upper bound).
        seconds = reported if type(reported) is int and 1 <= reported <= 60 else billed
        if type(seconds) is not int or not 1 <= seconds <= 60:
            raise ValueError("video source unavailable")
        return url, seconds

    def _finish_body(self, body):
        """Edit / extend: bind the source video's URL and real length (the edit's output
        length and the input-video charge both follow it)."""
        if body["operation"] == "generate":
            return body
        body["source_url"], body["source_seconds"] = self._source(body["source_task_id"])
        if body["operation"] == "edit":
            body["billed_seconds"] = body["source_seconds"]
        return body

    # ── proposal ───────────────────────────────────────────────────────────────

    def submit(self, args, origin, *, actor="jarvis"):
        if estop.is_engaged():
            raise _Declined("estop_engaged", "video generation refused while the e-stop is engaged")
        body = vp.normalize_request(dict(args))
        row = self._available(body["provider"])
        self._bind_images(body)
        self._finish_body(body)
        _, generation = self._configuration(body["provider"])
        cost = vp.estimate(body)
        payload = {
            "plugin": row.plugin, "method": "POST", "url": endpoint(body), "amount": cost["usd"],
            "video": {"body": body, "cost": cost, "generation": generation,
                      "nonce": uuid.uuid4().hex, "version": VERSION},
        }
        self.validate(payload)
        verb = {"generate": "video", "edit": "video edit", "extend": "video extension"}[body["operation"]]
        title = (f"Paid {row.display} {verb}: {body['model']}, {cost['seconds']} s, "
                 f"up to ${cost['usd']:.2f} (approval required)")
        task_id = self.worker.govern_enqueue(
            agent=actor, kind="plugin.egress", title=title, payload=payload,
            risk_tier=3, autonomy_level="ask", origin=origin)
        task = self.worker.queue.get(task_id)
        if not matches(task) or task.payload.get("video") != payload["video"]:
            raise ValueError("video proposal unavailable")
        _write(self._path(task, "proposal"), json.dumps({"binding": _task_binding(task)}).encode())
        return task_id

    def validate(self, payload):
        """Re-derive everything an approval binds; returns the provider key."""
        plugin = payload.get("plugin") if isinstance(payload, dict) else None
        row = _BY_PLUGIN.get(plugin)
        if row is None:
            raise ValueError("invalid video identity")
        if set(payload) - {"plugin", "method", "url", "amount", "video", "tainted", "taint_source"} \
                or payload.get("method") != "POST":
            raise ValueError("invalid video identity")
        if "taint_source" in payload and (
                payload.get("tainted") is not True or not isinstance(payload["taint_source"], str)
                or not is_untrusted_source(payload["taint_source"])):
            raise ValueError("invalid video provenance")
        value = payload.get("video")
        if not isinstance(value, dict) or set(value) != {"body", "cost", "generation", "nonce", "version"}:
            raise ValueError("invalid video request")
        body = value["body"]
        try:
            if not isinstance(body, dict) or body.get("provider") != row.name:
                raise ValueError
            self._available(row.name)
            expected = self._finish_body(vp.normalize_request(_args_of(body)))
            digests = body.get("image_sha256")
            if expected["images"]:
                expected["image_sha256"] = digests
                if (not isinstance(digests, list) or len(digests) != len(expected["images"])
                        or any(bool(vp.ARTIFACT_ID.fullmatch(image.split(":", 1)[1]))
                               != bool(isinstance(d, str) and re.fullmatch("[a-f0-9]{64}", d))
                               for image, d in zip(expected["images"], digests, strict=True))):
                    raise ValueError
            valid = (body == expected and value["cost"] == vp.estimate(body)
                     and payload["amount"] == value["cost"]["usd"]
                     and payload["url"] == endpoint(body) and value["version"] == VERSION
                     and isinstance(value["nonce"], str) and re.fullmatch("[a-f0-9]{32}", value["nonce"]))
        except _Declined:
            raise
        except (ValueError, TypeError, KeyError):
            raise ValueError("invalid video request") from None
        if not valid:
            raise ValueError("invalid video request")
        try:
            screened = self.redact(body["prompt"] + "\n" + body.get("negative_prompt", ""))
        except Exception:
            raise ValueError("video prompt screening unavailable") from None
        if screened != body["prompt"] + "\n" + body.get("negative_prompt", ""):
            raise _Declined("prompt_screening_refused", "video prompt screening refused")
        key, generation = self._configuration(row.name)
        if value["generation"] != generation:
            raise _Declined("configuration_changed", "video provider configuration changed")
        return key

    def _path(self, task, suffix):
        nonce = task.payload["video"]["nonce"]
        if not isinstance(nonce, str) or not re.fullmatch("[a-f0-9]{32}", nonce):
            raise ValueError("invalid video nonce")
        return self.records / f"{nonce}.{suffix}"

    def _bound(self, task):
        if not matches(task) or _json(self._path(task, "proposal")) != {"binding": _task_binding(task)}:
            raise _Declined("approved_payload_changed", "video approval changed")

    def guard(self, task):
        self._claim.set(None)
        if not matches(task):
            return False
        try:
            self.validate(task.payload)
            self._bound(task)
            if (task.autonomy_level != "ask" or task.decision not in {"accept", "edit"}
                    or not task.decided_by or str(task.decided_by).strip().lower() == "policy"):
                return False
            if not self.worker.execution_allowed(task):
                return False
            self._claim.set(_Claim(TaskQueue.execution_fingerprint(task)))
            return True
        except _Declined as exc:
            raise ExecutionGuardDeclined(exc.reason) from None
        except Exception:
            return False

    # ── completion ─────────────────────────────────────────────────────────────

    def recover(self, task):
        """Local finalization of an already published video; never HTTP."""
        with _file_lock(self._path(task, "finalize.lock")):
            self._bound(task)
            done = _json(self._path(task, "complete"))
            if done["binding"] != _task_binding(task):
                raise ValueError("video completion changed")
            artifact = done["artifact"]
            from ..media_library import read_catalog_blob

            meta, _data = read_catalog_blob(artifact["catalog_id"], self.root)
            if meta["sha256"] != done["sha256"] or meta["mime"] != artifact["mime"]:
                raise ValueError("video artifact changed")
            return {"status": "ok", "tool": TOOL,
                    "result": {"ok": True, "kind": "video", "result": artifact,
                               "catalog_id": artifact["catalog_id"]},
                    "cost": done["cost"]}

    def _publish(self, task, data, mime, *, provider_url, reported_usd, duration):
        generated = _safe(self.root / "media" / "generated")
        artifact_id = uuid.uuid4().hex
        suffix = {"video/webm": "webm", "video/quicktime": "mov"}.get(mime, "mp4")
        target = generated / f"{artifact_id}.{suffix}"
        with open(target, "xb") as handle:
            handle.write(data)
        digest = hashlib.sha256(data).hexdigest()
        body = task.payload["video"]["body"]
        row = MediaCatalog(self.root / "media" / "catalog.json").add(
            kind="video", prompt=body["prompt"], path=str(target), now=time.time(),
            backend=f"{body['provider']}:{body['model']}", cloud=True,
            record_id="md-" + hashlib.sha256(_task_binding(task).encode()).hexdigest()[:12],
            sha256=digest, meta={"task_id": task.id, "sha256": digest})
        cost = dict(task.payload["video"]["cost"])
        if reported_usd is not None:
            cost["reported_usd"] = reported_usd
        done = {
            "binding": _task_binding(task), "created_at": time.time(), "sha256": digest,
            "artifact": {"artifact_id": artifact_id, "catalog_id": row["id"], "bytes": len(data),
                         "mime": mime, "duration": duration},
            "cost": cost,
        }
        if provider_url:
            done["provider_url"] = provider_url
        _write(self._path(task, "complete"), json.dumps(done).encode())

    # ── execution ──────────────────────────────────────────────────────────────

    def _run_vendored(self, name, body, image_url, refs, staging):
        """On the video executor, inside the bound context: generate, then fetch the file."""
        from agents.vendor.hermes_compat import video_media

        prov = vp.provider(name)
        if prov is None:
            raise _ProviderFailed("video_provider_unavailable", "video provider not loaded")
        operation = body.get("operation", "generate")
        if operation == "edit":
            result = vp.plugin_module("xai").run_xai_video_edit(
                prompt=body["prompt"], video_url=body["source_url"], model=body["model"])
        elif operation == "extend":
            result = vp.plugin_module("xai").run_xai_video_extend(
                prompt=body["prompt"], video_url=body["source_url"], duration=body["duration"],
                model=body["model"])
        else:
            kwargs = {"model": body["model"], "duration": body.get("duration"),
                      "aspect_ratio": body["aspect_ratio"], "resolution": body["resolution"]}
            if image_url:
                kwargs["image_url"] = image_url
            if refs:
                kwargs["reference_image_urls"] = refs
            for key in ("negative_prompt", "seed", "audio"):
                if key in body:
                    kwargs[key] = body[key]
            result = prov.generate(body["prompt"], **kwargs)
        if not isinstance(result, dict) or result.get("success") is not True:
            code = str((result or {}).get("error_type") or "") if isinstance(result, dict) else ""
            raise _ProviderFailed("video_provider_error:" + (code if _ERROR_CODE.fullmatch(code) else "other"),
                                  "video provider failed")
        video = result.get("video")
        sink = video_media.current_sink()
        provider_url = None
        if isinstance(video, str) and video.startswith("data:"):
            path = Path(video_media.save_data_uri(video, prefix=name))
        elif isinstance(video, str) and video.startswith("https://"):
            if video_media.host_admitted(video, sink):
                provider_url = video
                path = Path(video_media.save_url("videos", video, prefix=name, max_bytes=sink.max_bytes))
            elif name == "deepinfra" and sink.job_ids:
                # A delivery URL off api.deepinfra.com (a CDN): the same file through the
                # OpenAI videos content endpoint on the API host, so a paid video is not lost.
                from agents.vendor.hermes_compat import video_openai

                client = video_openai.OpenAI(api_key=prov._api_key(), base_url=prov._base_url())
                raw = client.videos.download_content(sink.job_ids[-1]).read()
                path = Path(video_media.save_bytes("videos", raw, prefix=name))
            else:
                raise _Declined("video_host_not_admitted", "video host refused")
        else:
            path = Path(str(video or ""))
        if path not in sink.files:
            raise _ProviderFailed("video_missing", "video provider returned no file")
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        ticks = usage.get("cost_in_usd_ticks")
        reported = (round(ticks / 1e10, 4) if type(ticks) is int and 0 <= ticks < 10**14 else None)
        duration = result.get("duration") if type(result.get("duration")) is int else None
        return path, provider_url, reported, duration

    async def execute(self, task):
        claim = self._claim.get()
        self._claim.set(None)
        fingerprint = TaskQueue.execution_fingerprint(task)
        if not matches(task) or not isinstance(claim, _Claim) or not claim.consume(fingerprint):
            return {"status": "refused", "reason": "video execution claim required"}
        phase = "preflight"
        resources = ExitStack()
        staging = None
        try:
            self.validate(task.payload)
            self._bound(task)
            row = _BY_PLUGIN[task.payload["plugin"]]
            body = task.payload["video"]["body"]
            if self._path(task, "complete").exists():
                phase = "published"
                return self.recover(task)
            attempted = self._path(task, "attempt")
            if attempted.exists():
                return {"status": "unknown",
                        "reason": "video submission may have occurred; not replayed"}
            image_url, refs = self._image_inputs(body)

            def live_check(method, url):
                self.validate(task.payload)
                self._bound(task)
                if estop.is_engaged():
                    raise _Declined("estop_engaged", "video dispatch refused")
                if method not in {"GET", "POST"} or (method == "POST" and url != task.payload["url"]):
                    raise _Declined("dispatch_changed", "video dispatch refused")
                try:
                    mediated = self.worker.queue.validate_mediated_execution(task, fingerprint)
                except MediationStateUnavailable:
                    raise _StateUnavailable("video mediation state unavailable") from None
                if not mediated:
                    raise _Declined("mediation_execution_required", "video execution receipt invalid")
                decision = self.kernel(Action(kind="plugin.egress", agent=task.agent, title=task.title,
                                              payload=task.payload, origin=task.origin))
                if decision.verdict is Verdict.DENY:
                    raise _Declined("kernel_denied", "video kernel refused")
                if decision.verdict not in {Verdict.GRANT, Verdict.QUEUE}:
                    raise ValueError("video kernel refused")

            def check(method, url):
                nonlocal phase
                live_check(method, url)
                if method == "POST":
                    # One approved submit: a second POST (a retry, an upstream add-on pass
                    # such as FAL's upscale) is refused, never billed.
                    if attempted.exists():
                        raise _Declined("second_submit_refused", "video dispatch refused")
                    _write(attempted, json.dumps({"binding": _task_binding(task)}).encode())
                    phase = "dialled"

            client = _VideoClient(check, plugin=row.plugin, gate=self.gate, resolver=self.resolver,
                                  transport_factory=self.transport_factory)
            staging = self.records / f"{task.payload['video']['nonce']}.staging"
            staging.mkdir(mode=0o700, exist_ok=True)
            loop = asyncio.get_running_loop()
            deadline = time.monotonic() + self.deadline
            sem = _slots(loop)
            try:
                await asyncio.wait_for(sem.acquire(), timeout=QUEUE_WAIT_SECONDS)
            except TimeoutError:
                raise _ProviderFailed("video_busy", "video workers busy") from None
            resources.callback(sem.release)
            from agents.vendor.hermes_compat import httpx as compat_httpx
            from agents.vendor.hermes_compat import video_media
            from agents.vendor.hermes_compat.web_search_provider import provider_scope

            try:
                with compat_httpx.bound_egress(client, loop, deadline=deadline) as call, \
                        provider_scope(row.name), video_media.bound_sink(
                            staging, self.max_bytes, hosts=self._hosts(row.plugin)):
                    ctx = contextvars.copy_context()
                    work = loop.run_in_executor(_EXECUTOR, ctx.run, self._run_vendored,
                                                row.name, body, image_url, refs, staging)
                    try:
                        path, provider_url, reported, duration = await asyncio.wait_for(
                            work, timeout=max(0.0, deadline - time.monotonic()))
                    except TimeoutError:
                        call.abandon()
                        raise _ProviderFailed("video_timeout", "video job timed out") from None
                    except asyncio.CancelledError:
                        call.abandon()
                        raise
                    except Exception:
                        if isinstance(client.refusal, (_Declined, _StateUnavailable)):
                            raise client.refusal from None
                        if call.policy_block:
                            raise _Declined("egress_refused", "video egress refused") from None
                        if call.failure == "too_large":
                            raise _ProviderFailed("video_too_large", "video over the size cap") from None
                        raise
            finally:
                await client.close()
            if isinstance(client.refusal, (_Declined, _StateUnavailable)):
                raise client.refusal
            if call.policy_block:
                raise _Declined("egress_refused", "video egress refused")
            phase = "generated"
            data = path.read_bytes()
            if len(data) > self.max_bytes:
                raise _ProviderFailed("video_too_large", "video over the size cap")
            from ..artifact_store import sniff

            try:
                mime = sniff(data)
            except ValueError:
                mime = ""
            if mime not in {"video/mp4", "video/webm", "video/quicktime"}:
                raise _ProviderFailed("video_unrecognized", "not an MP4, QuickTime or WebM video")
            live_check("POST", task.payload["url"])
            phase = "published"
            self._publish(task, data, mime, provider_url=provider_url, reported_usd=reported,
                          duration=duration)
            result = self.recover(task)
            amount = float(task.payload["amount"])
            if reported is not None and reported > amount:
                # The provider billed more than the card said: the owner is told, and the
                # spend accounting carries the real amount (the worker settles ``amount``
                # on success; the difference is added here).
                result["warning"] = "reported_cost_above_estimate"
                logger.warning("video task %s: provider reported $%.4f, above the $%.2f estimate",
                               task.id, reported, amount)
                policy = getattr(self.worker, "policy", None)
                if policy is not None and callable(getattr(policy, "record_spend", None)):
                    policy.record_spend(round(reported - amount, 4))
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return _video_result(phase, exc)
        finally:
            resources.close()
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)


def _video_result(phase, exc):
    declined = isinstance(exc, _Declined)
    if isinstance(exc, _StateUnavailable) and phase in {"preflight", "generated"}:
        return {"status": "failed", "reason": exc.reason}
    if phase == "preflight":
        if declined:
            return {"status": "refused", "reason": exc.reason}
        if isinstance(exc, _ProviderFailed):
            return {"status": "failed", "reason": exc.reason}
        return {"status": "failed", "reason": "video_preflight_failed"}
    if phase == "dialled":
        if declined:
            # Refused at a later request (e-stop, kernel, a changed approval): the submit
            # may have been billed; never replayed.
            return {"status": "refused", "reason": exc.reason, "submission_replayed": False}
        if isinstance(exc, _ProviderFailed):
            return {"status": "failed", "reason": exc.reason, "submission_replayed": False}
        return {"status": "unknown", "reason": "video completion unavailable; submission not replayed"}
    if phase == "generated":
        if declined:
            return {"status": "failed", "reason": "withheld_after_generation", "detail": exc.reason}
        if isinstance(exc, _ProviderFailed):
            return {"status": "failed", "reason": exc.reason}
        return {"status": "failed", "reason": "video_recheck_failed"}
    return {"status": "unknown", "reason": "video completion unavailable; submission not replayed"}


# ── the tool ─────────────────────────────────────────────────────────────────────

INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["prompt"],
    "properties": {
        "prompt": {"type": "string", "minLength": 1, "maxLength": vp.MAX_PROMPT,
                   "description": "What the video shows: subject, motion, camera, style."},
        "provider": {"type": "string", "enum": sorted(vp.PROVIDERS),
                     "description": "Default: the provider the owner chose in Integrations."},
        "model": {"type": "string", "maxLength": 128,
                  "description": "FAL family id, xAI model, or DeepInfra model id (required for DeepInfra)."},
        "duration": {"type": "integer", "minimum": 1, "maximum": 30,
                     "description": "Seconds; the provider clamps it. Omit for its default."},
        "aspect_ratio": {"type": "string", "enum": list(vp.ASPECT_RATIOS)},
        "resolution": {"type": "string", "enum": list(vp.RESOLUTIONS)},
        "image": {"type": "string", "maxLength": 2048,
                  "description": "Animate this still: a generated image id, or the provider's own media URL."},
        "reference_images": {"type": "array", "minItems": 1, "maxItems": 7,
                             "items": {"type": "string", "maxLength": 2048},
                             "description": "xAI only: reference-guided generation (image ids or xAI media URLs)."},
        "negative_prompt": {"type": "string", "maxLength": vp.MAX_NEGATIVE},
        "seed": {"type": "integer", "minimum": 0, "maximum": 2**31 - 1},
        "audio": {"type": "boolean", "description": "FAL families with an audio toggle."},
        "operation": {"type": "string", "enum": ["generate", "edit", "extend"],
                      "description": "xAI only: edit or extend a video Nerva generated with xAI."},
        "source_task_id": {"type": "integer", "minimum": 1, "maximum": 2**63 - 1,
                           "description": "The task of the xAI video to edit or extend."},
    },
}


class VideoToolDispatcher:
    """``video_generate``: validates, then proposes one approval card; never runs here."""

    def __init__(self, runtime, *, approved_task):
        self.runtime = runtime
        self.approved_task = approved_task

    def preflight(self, args):
        from ..tool_rpc import ToolRPCValidationError

        if self.approved_task() is not None:
            raise ToolRPCValidationError("cloud_worker_required")
        try:
            vp.normalize_request(dict(args))
        except vp.VideoRequestError as exc:
            raise ToolRPCValidationError(str(exc)) from None
        return dict(args)

    def intake(self, actor, args):
        from ..action_origin import current_action_origin
        from ..tool_rpc import ToolRPCValidationError

        runtime = self.runtime()
        if runtime is None:
            raise ToolRPCValidationError("video_generation_unavailable")
        try:
            return runtime.submit(args, current_action_origin(), actor=actor)
        except _Declined as exc:
            raise ToolRPCValidationError(exc.reason) from None
        except vp.VideoRequestError as exc:
            raise ToolRPCValidationError(str(exc)) from None
        except Exception:
            raise ToolRPCValidationError("video_proposal_refused") from None

    async def execute(self, args):
        return {"status": "failed", "reason": "cloud_worker_required"}


DESCRIPTION = ("Propose one paid video (text-to-video, image-to-video, reference-guided; "
               "xAI edit/extend) on the provider the owner chose; owner approval with a cost estimate required.")


def register_video_tool(server, runtime, approved_task):
    dispatcher = VideoToolDispatcher(runtime, approved_task=approved_task)
    server.register_tool(
        TOOL, dispatcher.execute, gated=True,
        description=DESCRIPTION,
        input_schema=INPUT_SCHEMA, capability_id=f"tool:{TOOL}",
        preflight=dispatcher.preflight, trusted_execution=True, gated_intake=dispatcher.intake,
    )
    return dispatcher


def wire_cloud_video(orch, executor):
    """Compose the video runtime into the worker's ``plugin.egress`` guard and handler."""
    from ..orchestrator_bindings import bind_external_orchestrator_attribute

    worker = getattr(orch, "autonomy", None)
    redact = getattr(getattr(orch, "secret_broker", None), "redact", None)
    if worker is None or not callable(redact):
        return None
    runtime = CloudVideoRuntime(worker, kernel=getattr(worker, "kernel_gate", None), redact=redact,
                                gate=getattr(orch, "permission_gate", None))
    previous_guard, previous_execute = executor.execution_guard, executor.resolve("plugin.egress")

    def guard(task):
        if matches(task):
            return runtime.guard(task)
        return callable(previous_guard) and previous_guard(task)

    async def execute(task):
        if matches(task):
            return await runtime.execute(task)
        if callable(previous_execute):
            return await previous_execute(task)
        return {"status": "refused", "reason": "unsupported egress operation"}

    executor.execution_guard = guard
    executor.register("plugin.egress", execute)
    bind_external_orchestrator_attribute(orch, "cloud_videos", runtime)
    return runtime


__all__ = ["CloudVideoRuntime", "INPUT_SCHEMA", "MAX_VIDEO_BYTES", "PLUGINS", "TOOL",
           "VIDEO_DEADLINE_SECONDS", "VideoToolDispatcher", "endpoint", "matches",
           "register_video_tool", "wire_cloud_video"]
