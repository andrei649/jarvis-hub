"""Owner-approved video understanding from scoped files or public HTTP(S) URLs.

This is a ToolRPC consumer, not the inbound-media or video-generation pipeline.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import stat
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx

from .file_tools import FileScope, FileScopeError
from .http_client import PluginHTTPClient, PluginTimeouts
from .llm.egress import llm_async_client
from .llm.video_policy import (
    VideoPolicyRefused,
    authorization_check,
    class_binding,
    describe_video_data_target,
    native_video_request_scope,
)
from .tool_rpc import ToolRPCValidationError

VIDEO_MIME = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/mov",
              ".avi": "video/mp4", ".mkv": "video/mp4", ".mpeg": "video/mpeg",
              ".mpg": "video/mpeg"}
# A 37.5 MiB binary becomes at most 50 MiB in the native base64 payload.
MAX_VIDEO_BYTES = 37_500_000
MAX_URL_CHARS = 2048
MAX_QUESTION_CHARS = 4000
MAX_ANSWER_CHARS = 16_000
MAX_MODEL_RESPONSE_BYTES = 512_000
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "video_url": {"type": "string", "description": "Public HTTP(S) URL or file path inside the configured workspace roots."},
        "question": {"type": "string", "description": "Question about the video."},
        "allow_remote": {"type": "boolean", "description": "Approve sending the video to the configured remote video model."},
        "confirm_expensive": {"type": "boolean", "description": "Confirm a known expensive video model for this call."},
    },
    "required": ["video_url", "question"],
    "additionalProperties": False,
}


def is_video_task(task) -> bool:
    payload = getattr(task, "payload", None)
    return (getattr(task, "kind", None) == "tool.rpc" and isinstance(payload, dict)
            and payload.get("tool") == payload.get("target") == "video_analyze"
            and isinstance(payload.get("args"), dict)
            and isinstance(payload.get("class"), str)
            and payload["class"].startswith("video."))


def _source(source: str, scope: FileScope):
    if not isinstance(source, str) or not source or len(source) > MAX_URL_CHARS or source != source.strip():
        raise ToolRPCValidationError("bad_video_source")
    parts = urlsplit(source)
    if parts.scheme in {"http", "https"}:
        if (not parts.hostname or parts.username or parts.password or parts.fragment
                or any(key.lower() in {"token", "key", "api_key", "access_token", "authorization", "password", "secret"}
                       for key, _ in parse_qsl(parts.query, keep_blank_values=True))):
            raise ToolRPCValidationError("bad_video_url")
        from .security.ssrf import is_private_ip
        if parts.hostname.lower().rstrip(".") in {"localhost", "localhost.localdomain"} or is_private_ip(parts.hostname):
            raise ToolRPCValidationError("private_video_url")
        suffix = Path(parts.path).suffix.lower()
        if suffix not in VIDEO_MIME:
            raise ToolRPCValidationError("unsupported_video_format")
        return "url", source, VIDEO_MIME[suffix]
    if parts.scheme:
        raise ToolRPCValidationError("bad_video_url")
    try:
        path = scope.resolve(source)
    except FileScopeError as exc:
        raise ToolRPCValidationError(str(exc)) from exc
    suffix = path.suffix.lower()
    if suffix not in VIDEO_MIME:
        raise ToolRPCValidationError("unsupported_video_format")
    return "file", path, VIDEO_MIME[suffix]


def _read_scoped(path: Path, scope: FileScope) -> bytes:
    """Walk the owner root through O_NOFOLLOW descriptors, then bound the read."""
    if os.name != "posix":
        raise VideoPolicyRefused("scoped video reads require POSIX descriptors")
    root = scope.root_for(path)
    if root is None:
        raise VideoPolicyRefused("video source left the workspace")
    relative = path.relative_to(root)
    if not relative.parts:
        raise VideoPolicyRefused("video source must be a regular file")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(child, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_VIDEO_BYTES:
                raise VideoPolicyRefused("video source must be a bounded regular file")
            data = stream.read(MAX_VIDEO_BYTES + 1)
    finally:
        os.close(fd)
    if not data or len(data) > MAX_VIDEO_BYTES:
        raise VideoPolicyRefused("video source is empty or too large")
    return data


class VideoHTTPClient(PluginHTTPClient):
    """Plugin egress/DNS guard plus current approval at the physical GET hook."""

    def __init__(self, *args, check, **kwargs):
        super().__init__(*args, **kwargs)
        self._video_check = check
        self._checked_clients = set()

    def _pinned_client(self, target):
        client = super()._pinned_client(target)
        if client not in self._checked_clients:
            async def request_check(request):
                self._video_check()
                if request.headers.get("Authorization") or request.headers.get("Cookie"):
                    raise VideoPolicyRefused("video source request gained credentials")

            client.event_hooks["request"].append(request_check)
            self._checked_clients.add(client)
        return client


async def _read_url(source: str, check, *, client_factory=VideoHTTPClient) -> bytes:
    current = source
    client = client_factory("video_analysis", check=check,
                            timeouts=PluginTimeouts(connect=5, read=10, total=30))
    try:
        async with asyncio.timeout(35):
            for _ in range(5):
                check()
                # One hop per call: validate the next URL and current authority before
                # every new DNS resolution and physical GET, including redirects.
                async with client.stream("GET", current, follow_redirects=False,
                                         headers={"Accept": "video/*"}) as response:
                    check()
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise VideoPolicyRefused("video redirect has no location")
                        current = urljoin(current, location)
                        _source(current, FileScope.from_env())
                        continue
                    response.raise_for_status()
                    size = response.headers.get("content-length", "")
                    if size.isdecimal() and int(size) > MAX_VIDEO_BYTES:
                        raise VideoPolicyRefused("video source too large")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        check()
                        data.extend(chunk)
                        if len(data) > MAX_VIDEO_BYTES:
                            raise VideoPolicyRefused("video source too large")
                    check()
                    if not data:
                        raise VideoPolicyRefused("video source is empty")
                    return bytes(data)
        raise VideoPolicyRefused("video redirect limit exceeded")
    finally:
        await client.close()


class VideoAnalysisTool:
    """Registered gated ToolRPC handler with its own persisted-task proof."""

    def __init__(self, *, approved_task, execution_check, kernel_check, enqueue, queue, router=None,
                 source_client_factory=VideoHTTPClient, model_client_factory=llm_async_client):
        self.approved_task = approved_task
        self.execution_check = execution_check
        self.kernel_check = kernel_check
        self.enqueue = enqueue
        self.queue = queue
        self.router = router
        self.source_client_factory = source_client_factory
        self.model_client_factory = model_client_factory

    def preflight(self, args):
        if (set(args) - {"video_url", "question", "allow_remote", "confirm_expensive"}
                or not isinstance(args.get("question"), str)
                or not 0 < len(args["question"].strip()) <= MAX_QUESTION_CHARS
                or type(args.get("allow_remote", False)) is not bool
                or type(args.get("confirm_expensive", False)) is not bool):
            raise ToolRPCValidationError("bad_video_args")
        scope = FileScope.from_env()
        _source(args.get("video_url"), scope)
        return {"video_url": args["video_url"], "question": args["question"].strip(),
                "allow_remote": args.get("allow_remote", False),
                "confirm_expensive": args.get("confirm_expensive", False)}

    def _binding(self, args, *, source_data=None, actor=""):
        scope = FileScope.from_env()
        kind, source, _ = _source(args["video_url"], scope)
        identity = describe_video_data_target()
        if identity is None:
            raise VideoPolicyRefused("video role model is not configured")
        authorization_check(identity, allow_remote=args["allow_remote"],
                            confirm_expensive=args["confirm_expensive"], router=self.router,
                            actor=actor)
        source_key = args["video_url"]
        if kind == "file":
            data = _read_scoped(source, scope) if source_data is None else source_data
            source_key = [str(source), hashlib.sha256(data).hexdigest()]
        material = {**args, "video_url": source_key}
        cls = class_binding(identity, material, tuple(map(str, scope.roots)))
        return cls, identity

    def classifier(self, args):
        cls, identity = self._binding(args)
        destination = "local" if identity.local else "remote"
        return {"class": cls, "notice": f"Analyze video on {destination} {identity.provider}/{identity.model}"}

    def intake(self, actor, args):
        """Submit the exact classed payload under the canonical signed tool.rpc kind."""
        from .action_origin import current_action_origin

        if (self.queue is None or self.queue.mediation_mode != "enforce"
                or self.queue.classify_mediation("tool.rpc") is not True):
            raise ToolRPCValidationError("signed_video_mediation_required")
        labels = self.classifier(args)
        self._binding(args, actor=actor)
        payload = {"tool": "video_analyze", "target": "video_analyze", "args": args,
                   "class": labels["class"], "notice": labels["notice"]}
        title = "Tool 'video_analyze' via RPC — " + labels["notice"]
        try:
            task_id = self.enqueue(actor, "tool.rpc", title, payload=payload, risk_tier=3,
                                   autonomy_level="ask", origin=current_action_origin())
            task = self.queue.get(task_id)
            if not is_video_task(task) or task.payload.get("args") != args or task.payload.get("class") != labels["class"]:
                raise ToolRPCValidationError("video_proposal_binding_failed")
            return task_id
        except ToolRPCValidationError:
            raise
        except Exception as exc:
            raise ToolRPCValidationError("video_proposal_refused") from exc

    async def execute(self, args):
        task = self.approved_task()
        if task is None or not self.execution_check(task):
            return {"ok": False, "reason": "trusted_execution_required"}

        def check():
            if (self.queue is None or self.queue.mediation_mode != "enforce"
                    or self.queue.classify_mediation("tool.rpc") is not True):
                raise VideoPolicyRefused("signed video mediation is unavailable")
            if not self.execution_check(task):
                raise VideoPolicyRefused("video approval was revoked")
            if self.kernel_check(args, task):
                raise VideoPolicyRefused("video kernel denied the action")
            cls, current = self._binding(args, actor=task.agent)
            if cls != task.payload.get("class"):
                raise VideoPolicyRefused("video source or role changed after approval")
            return current

        try:
            identity = check()
            scope = FileScope.from_env()
            kind, source, mime = _source(args["video_url"], scope)
            if kind == "file":
                data = _read_scoped(source, scope)
                actual_class, _ = self._binding(args, source_data=data, actor=task.agent)
                if actual_class != task.payload.get("class"):
                    raise VideoPolicyRefused("video bytes changed after approval")
            else:
                data = await _read_url(source, check, client_factory=self.source_client_factory)
            check()
            data_url = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
            prompt = ("Fully describe and explain everything happening in this video, including visual "
                      "content, motion, audio cues, text overlays, and scene transitions. "
                      "Then answer the following question:\n\n" + args["question"])
            body = {"model": identity.model, "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt}, {"type": "video_url", "video_url": {"url": data_url}},
            ]}], "stream": False}
            async with self.model_client_factory(identity.provider, trust_env=False, follow_redirects=False,
                                                 timeout=httpx.Timeout(60)) as client:
                from .llm.data_handling import authorize_role_target

                with native_video_request_scope(
                        identity, client, expected_body=body, check=check,
                        record_use=lambda: authorize_role_target(self.router, identity, actual_use=True)):
                    async with asyncio.timeout(65):
                        async with client.stream(
                                "POST", identity.request_url, json=body,
                                headers={"Authorization": identity.authorization}
                                if identity.authorization else {}) as response:
                            response.raise_for_status()
                            result = bytearray()
                            async for chunk in response.aiter_bytes():
                                check()
                                result.extend(chunk)
                                if len(result) > MAX_MODEL_RESPONSE_BYTES:
                                    raise VideoPolicyRefused("video model response too large")
                            check()
                            answer = json.loads(result)["choices"][0]["message"]["content"]
                check()
            check()  # A close hook or transport cleanup can revoke authority.
            if not isinstance(answer, str) or not answer.strip():
                raise VideoPolicyRefused("video model returned no text")
            return {"ok": True, "analysis": answer[:MAX_ANSWER_CHARS]}
        except (VideoPolicyRefused, ToolRPCValidationError, FileScopeError, OSError,
                httpx.HTTPError, TimeoutError, KeyError, IndexError, TypeError, ValueError):
            return {"ok": False, "reason": "video_analysis_refused"}
