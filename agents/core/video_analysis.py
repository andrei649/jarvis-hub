"""Owner-approved video understanding from scoped files or public HTTP(S) URLs.

This is a ToolRPC consumer, not the inbound-media or video-generation pipeline.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx

from .file_tools import FileScope, FileScopeError
from .http_client import PluginHTTPClient, PluginTimeouts
from .llm.data_handling import authorize_role_target
from .llm.egress import llm_async_client
from .llm.native_response import compatible_empty_success
from .llm.video_failures import provider_failure_category, transport_failure_category
from .llm.video_native import (
    VIDEO_MIME,
    VideoNativeEmpty,
    VideoNativeRefused,
    gemini_video_answer,
    gemini_video_body,
    gemini_video_mime,
)
from .llm.video_policy import (
    VideoPolicyRefused,
    authorization_check,
    chain_class_binding,
    describe_video_route_set,
    native_video_request_scope,
)
from .llm.video_retry import (
    native_retryable_status,
    resolve_video_empty_retry_count,
    resolve_video_retry_count,
)
from .tool_rpc import ToolRPCValidationError

# A 37.5 MiB binary becomes at most 50 MiB in the native base64 payload.
MAX_VIDEO_BYTES = 37_500_000
MAX_URL_CHARS = 2048
MAX_QUESTION_CHARS = 4000
MAX_ANSWER_CHARS = 16_000
MAX_MODEL_RESPONSE_BYTES = 512_000
VIDEO_EXECUTION_TIMEOUT = 180
VIDEO_MODEL_ATTEMPT_TIMEOUT = 65
VIDEO_NATIVE_CLIENT_TIMEOUT = 60
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


class _EligibleModelFailure(Exception):
    """A fixed category established by one native model request."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


class _TransientModelFailure(_EligibleModelFailure):
    """An owned primary retry candidate; fallback remains a separate decision."""


class _EmptyModelResponse(Exception):
    """A successful native response had no usable visible answer."""


def _short_notice_value(value: str, limit: int) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]", "?", value)
    if len(value) <= limit:
        return value
    digest = hashlib.sha256(value.encode()).hexdigest()[:6]
    return value[:limit - 7] + "~" + digest


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

    def _binding(self, args, *, source_data=None, actor="", retry_policy=None):
        retry_count, empty_count = (retry_policy if retry_policy is not None else
                                    (resolve_video_retry_count(), resolve_video_empty_retry_count()))
        scope = FileScope.from_env()
        kind, source, mime = _source(args["video_url"], scope)
        identities = describe_video_route_set()
        if not identities:
            raise VideoPolicyRefused("video role model is not configured")
        if any(identity.provider == "gemini" for identity in identities):
            try:
                gemini_video_mime(mime)
            except VideoNativeRefused as exc:
                raise VideoPolicyRefused("video format is unavailable for this route") from exc
        for identity in identities:
            authorization_check(identity, allow_remote=args["allow_remote"],
                                confirm_expensive=args["confirm_expensive"], router=self.router,
                                actor=actor)
        source_key = args["video_url"]
        if kind == "file":
            data = _read_scoped(source, scope) if source_data is None else source_data
            source_key = [str(source), hashlib.sha256(data).hexdigest()]
        material = {**args, "video_url": source_key}
        if retry_count:
            material = {**material, "_internal_video_retry_policy": "primary-once:v1"}
        if empty_count:
            material = {**material, "_internal_video_empty_policy": "consumer-once:v1"}
        cls = chain_class_binding(identities, material, tuple(map(str, scope.roots)))
        return cls, identities, (retry_count, empty_count)

    def classifier(self, args):
        cls, identities, (retry_count, empty_count) = self._binding(args)
        if retry_count or empty_count:
            legend = ("lm=LM Studio,oc=OpenAI-compatible,g=Gemini" if any(
                identity.provider == "gemini" for identity in identities)
                else "lm=LM Studio,oc=OpenAI-compatible")
            if retry_count and empty_count:
                prefix = "Video full-chain empty restart once; primary transient retry once: "
            elif empty_count:
                prefix = "Video full-chain empty restart once: "
            else:
                prefix = f"Video primary retry once ({legend}): "
            per_lane = (200 - len(prefix) - 2 * (len(identities) - 1)) // len(identities)
            lanes = []
            for index, identity in enumerate(identities, 1):
                origin = urlsplit(identity.request_url)
                code = {"lm-studio": "lm", "openai-compatible": "oc", "gemini": "g"}[identity.provider]
                label = f"{index}{'L' if identity.local else 'R'}:{code}/"
                available = per_lane - len(label) - 1
                model_budget = max(7, available // 2)
                lanes.append(f"{label}{_short_notice_value(identity.model, model_budget)}@"
                             f"{_short_notice_value(f'{origin.scheme}://{origin.netloc}', available - model_budget)}")
            return {"class": cls, "notice": prefix + "; ".join(lanes)}
        if len(identities) == 1:
            identity = identities[0]
            destination = "local" if identity.local else "remote"
            notice = f"Analyze video on {destination} {identity.provider}/{identity.model}"
        else:
            lanes = []
            for identity in identities:
                origin = urlsplit(identity.request_url)
                provider = re.sub(r"[\x00-\x1f\x7f]", "?", identity.provider)[:64]
                model = re.sub(r"[\x00-\x1f\x7f]", "?", identity.model)[:256]
                lanes.append(f"{len(lanes) + 1}. {'local' if identity.local else 'remote'} "
                             f"{provider}/{model} at {origin.scheme}://{origin.netloc}")
            notice = "Analyze video with approved routes: " + "; ".join(lanes)
            if len(notice) > 200:
                prefix = ("Video routes (lm=LM Studio,oc=OpenAI-compatible,g=Gemini): "
                          if any(item.provider == "gemini" for item in identities) else
                          "Video routes (lm=LM Studio,oc=OpenAI-compatible): ")
                per_lane = (200 - len(prefix) - 2 * (len(identities) - 1)) // len(identities)
                compact = []
                for index, identity in enumerate(identities, 1):
                    origin = urlsplit(identity.request_url)
                    origin_text = f"{origin.scheme}://{origin.netloc}"
                    code = {"lm-studio": "lm", "openai-compatible": "oc", "gemini": "g"}[identity.provider]
                    label = f"{index}{'L' if identity.local else 'R'}:{code}/"
                    available = per_lane - len(label) - 1  # one separator before origin
                    model_budget = max(7, available // 3)
                    compact.append(f"{label}{_short_notice_value(identity.model, model_budget)}@"
                                   f"{_short_notice_value(origin_text, available - model_budget)}")
                notice = prefix + "; ".join(compact)
        return {"class": cls, "notice": notice}

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

    async def _attempt(self, identity, prompt, data_url, check):
        """Send once on one frozen lane; close before returning or selecting another."""
        body = gemini_video_body(prompt, data_url) if identity.provider == "gemini" else {"model": identity.model, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt}, {"type": "video_url", "video_url": {"url": data_url}},
        ]}], "stream": False}
        physical_send = False

        def record_use():
            authorize_role_target(self.router, identity, actual_use=True)

        def mark_dispatch():
            nonlocal physical_send
            if physical_send:
                raise VideoPolicyRefused("video lane already sent")
            physical_send = True

        # Factory failures have no transport-origin proof and must not switch lanes.
        client = self.model_client_factory(
            identity.provider, trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(VIDEO_NATIVE_CLIENT_TIMEOUT))
        attempt_timeout = asyncio.timeout(VIDEO_MODEL_ATTEMPT_TIMEOUT)
        request_timeout = False
        try:
            async with attempt_timeout:
                try:
                    async with client:
                        with native_video_request_scope(identity, client, expected_body=body,
                                                        check=check, record_use=record_use,
                                                        mark_dispatch=mark_dispatch):
                            try:
                                async with client.stream(
                                        "POST", identity.request_url, json=body,
                                        headers=identity.request_headers) as response:
                                    result = bytearray()
                                    async for chunk in response.aiter_bytes():
                                        check()
                                        result.extend(chunk)
                                        if len(result) > MAX_MODEL_RESPONSE_BYTES:
                                            raise VideoPolicyRefused("video model response too large")
                                    check()
                                    if not 200 <= response.status_code < 300:
                                        category = provider_failure_category(response.status_code, bytes(result))
                                        if category is not None:
                                            raise _EligibleModelFailure(category)
                                        if native_retryable_status(response.status_code):
                                            raise _TransientModelFailure("transient_http")
                                        raise VideoPolicyRefused("video model status refused")
                                    parsed = json.loads(result)
                                    if identity.provider == "gemini":
                                        try:
                                            answer = gemini_video_answer(parsed)
                                        except VideoNativeEmpty:
                                            raise _EmptyModelResponse from None
                                    else:
                                        answer = parsed["choices"][0]["message"]["content"]
                                        if ((isinstance(answer, str) and not answer.strip()
                                             or answer is None) and compatible_empty_success(parsed)):
                                            raise _EmptyModelResponse
                            except asyncio.CancelledError:
                                request_timeout = attempt_timeout.expired()
                                raise
                            except httpx.HTTPError as exc:
                                category = transport_failure_category(exc) if physical_send else None
                                if category is not None:
                                    failure_type = _TransientModelFailure if category == "connection" else _EligibleModelFailure
                                    raise failure_type(category) from None
                                raise
                finally:
                    check()  # Includes cleanup, revocation, and complete chain freshness.
        except TimeoutError:
            if attempt_timeout.expired() and request_timeout and physical_send:
                raise _EligibleModelFailure("timeout") from None
            raise
        if not isinstance(answer, str) or not answer.strip():
            raise VideoPolicyRefused("video model returned no text")
        return answer

    async def execute(self, args):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + VIDEO_EXECUTION_TIMEOUT
        try:
            task = self.approved_task()
            if not is_video_task(task) or not self.execution_check(task):
                return {"ok": False, "reason": "trusted_execution_required"}
        except Exception:
            return {"ok": False, "reason": "video_analysis_refused"}

        def check():
            try:
                if loop.time() >= deadline:
                    raise VideoPolicyRefused("video execution deadline expired")
                if (self.queue is None or self.queue.mediation_mode != "enforce"
                        or self.queue.classify_mediation("tool.rpc") is not True):
                    raise VideoPolicyRefused("signed video mediation is unavailable")
                if not self.execution_check(task):
                    raise VideoPolicyRefused("video approval was revoked")
                if self.kernel_check(args, task):
                    raise VideoPolicyRefused("video kernel denied the action")
                cls, current, retry_policy = self._binding(args, actor=task.agent)
                if cls != task.payload.get("class"):
                    raise VideoPolicyRefused("video source or role changed after approval")
                if loop.time() >= deadline:
                    raise VideoPolicyRefused("video execution deadline expired")
                return current, retry_policy
            except VideoPolicyRefused:
                raise
            except Exception as exc:
                raise VideoPolicyRefused("video authority check refused") from exc

        try:
            async with asyncio.timeout_at(deadline):
                identities, (retry_count, empty_count) = check()
                scope = FileScope.from_env()
                kind, source, mime = _source(args["video_url"], scope)
                if kind == "file":
                    data = _read_scoped(source, scope)
                    actual_class, _, _ = self._binding(args, source_data=data, actor=task.agent)
                    if actual_class != task.payload.get("class"):
                        raise VideoPolicyRefused("video bytes changed after approval")
                else:
                    data = await _read_url(source, check, client_factory=self.source_client_factory)
                check()
                data_url = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
                prompt = ("Fully describe and explain everything happening in this video, including visual "
                          "content, motion, audio cues, text overlays, and scene transitions. "
                          "Then answer the following question:\n\n" + args["question"])
                if any(identity.provider == "gemini" for identity in identities):
                    gemini_video_body(prompt, data_url)
                failures = []
                for consumer_call in range(1, 2 + empty_count):
                    restart = False
                    for route_index, identity in enumerate(identities):
                        max_attempts = 1 + retry_count if route_index == 0 else 1
                        for attempt in range(1, max_attempts + 1):
                            check()
                            try:
                                answer = await self._attempt(identity, prompt, data_url, check)
                            except _EmptyModelResponse:
                                if not empty_count:
                                    raise
                                failures.append({"target_id": identity.target_id,
                                                 "category": "empty_output",
                                                 "consumer_call": consumer_call, "attempt": attempt})
                                if consumer_call > empty_count:
                                    check()
                                    return {"ok": False, "reason": "video_analysis_refused",
                                            "attempts": failures}
                                restart = True
                                break
                            except _EligibleModelFailure as exc:
                                failure = {"target_id": identity.target_id, "category": exc.category}
                                if empty_count:
                                    failure.update({"consumer_call": consumer_call, "attempt": attempt})
                                elif retry_count:
                                    failure["attempt"] = attempt
                                failures.append(failure)
                                transient = isinstance(exc, _TransientModelFailure)
                                if transient and route_index == 0 and attempt < max_attempts:
                                    continue
                                if exc.category == "transient_http":
                                    check()
                                    result = {"ok": False, "reason": "video_analysis_refused"}
                                    if retry_count or empty_count:
                                        result["attempts"] = failures
                                    return result
                                break
                            check()
                            result = {"ok": True, "analysis": answer[:MAX_ANSWER_CHARS]}
                            if retry_count or empty_count or len(identities) > 1:
                                result.update({"attempts": failures, "chosen_route": identity.target_id,
                                               "chosen_provider": identity.provider, "chosen_model": identity.model})
                                if retry_count or empty_count:
                                    result["chosen_attempt"] = attempt
                                if empty_count:
                                    result["chosen_call"] = consumer_call
                            return result
                        if restart:
                            break
                    if not restart:
                        break
                    check()
                check()
                result = {"ok": False, "reason": "video_analysis_refused"}
                if retry_count or empty_count or len(identities) > 1:
                    result["attempts"] = failures
                return result
        except Exception:
            # Never disclose provider bodies, credentials, guard text, or traceback.
            return {"ok": False, "reason": "video_analysis_refused"}
