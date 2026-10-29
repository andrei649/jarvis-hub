"""
anthropic.py — Anthropic Claude API backend with streaming support.
Uses Anthropic Messages API directly via httpx (no SDK dependency).
"""

import base64
import binascii
import json
from typing import Any, Callable

import httpx

from .auth_rotation import is_rotatable_status
from .base import LLMBackend, _emit, cloud_cap
from .egress import llm_async_client
from .model_config import DEFAULT_CLAUDE_MODEL
from .provider_errors import note_provider_failure
from .provider_request import (
    ProfileRequestRefused,
    apply_profile_request,
    prepare_profile_messages,
    profile_headers,
    profile_reasoning_config,
    require_profile_base,
    require_profile_kind,
)
from .providers import DEFAULT_REGISTRY
from .providers.admitted_profiles import AdmittedProviderProfile, prepare_admitted_profile
from .providers.native_transport import (
    AdmittedClientMixin,
    native_admitted_client,
    native_post,
    native_stream,
)
from .quota import ProviderRateLimited
from .reasoning_effort import apply_anthropic, parse_overrides, supported_reasoning_efforts
from .repetition_guard import RepetitionStreamGuard
from .tool_dialects import (
    ANTHROPIC_FINISH_REASONS,
    anthropic_messages,
    anthropic_text,
    anthropic_tool_calls,
    anthropic_tools,
    anthropic_usage,
    cache_marked_system,
    cache_marked_tools,
    normalize_finish_reason,
)
from .tool_protocol import PROVIDER_REJECTED_FINISH, ToolSpec, ToolTurn, parse_openai_tool_calls
from .usage_context import report_text_usage

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
#: H297 — the statuses of a request the provider refused as invalid
#: (``invalid_request_error``, ``request_too_large``): the only failures the tool loop
#: answers by resending without the images the request carried.
_REJECTED_REQUEST_STATUSES = frozenset({400, 413})
_TOOL_HISTORY_TEXT_BYTES = 256 * 1024
_BUILTIN_REQUEST_IMAGE_B64_CHARS = 20_000_000  # AgentToolRuntime's request image ceiling.
_BUILTIN_REQUEST_IMAGES = 8
_BUILTIN_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


def _builtin_tool_history_limit(messages: list[dict]) -> int:
    """Validate tool-result images and count their bytes above the text limit.

    Signed profiles still use their isolated worker/request bounds. The ordinary
    built-in image path can carry up to 20 MB of base64, and the JSON ownership
    copy must accommodate those bytes without granting extra text history.
    """
    # Loading the LLM package while tool_rpc is initializing must not import its
    # image validators before that module has defined them.
    from ..tool_rpc import MAX_IMAGE_B64_CHARS, image_signature_ok

    count = total = 0
    for row in messages:
        if type(row) is not dict or row.get("role") != "tool":
            continue
        if "images" not in row:
            continue
        images = row["images"]
        if type(images) is not list:
            raise ProfileRequestRefused("invalid tool image")
        for image in images:
            if (type(image) is not dict or set(image) != {"media_type", "data"}
                    or type(image.get("media_type")) is not str
                    or image["media_type"] not in _BUILTIN_IMAGE_TYPES
                    or type(image.get("data")) is not str):
                raise ProfileRequestRefused("invalid tool image")
            count += 1
            if count > _BUILTIN_REQUEST_IMAGES:
                raise ProfileRequestRefused("too many tool images")
            size = len(image["data"])
            if size > MAX_IMAGE_B64_CHARS:
                raise ProfileRequestRefused("tool image too large")
            try:
                raw = base64.b64decode(image["data"].encode("ascii"), validate=True)
            except (binascii.Error, UnicodeError, ValueError):
                raise ProfileRequestRefused("invalid tool image") from None
            if not image_signature_ok(raw, image["media_type"]):
                raise ProfileRequestRefused("invalid tool image")
            total += size
            if total > _BUILTIN_REQUEST_IMAGE_B64_CHARS:
                raise ProfileRequestRefused("tool images too large")
    return _TOOL_HISTORY_TEXT_BYTES + total


class ClaudeBackend(AdmittedClientMixin, LLMBackend):
    # Tool calls travel as tool_use / tool_result blocks; the translation lives in
    # tool_dialects (Hermes absorption, wave 0.1).
    supports_tools = True
    # H297: a tool_result block carries image blocks, so a multimodal tool result
    # reaches the model as images (tool_dialects.anthropic_messages).
    supports_tool_result_images = True

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_CLAUDE_MODEL,
        auth_pool=None,
        reasoning_effort: str = "",
        effort_overrides=None,
        profile=None,
    ):
        self.api_key = api_key
        self.model = model
        self.profile = profile or DEFAULT_REGISTRY.get("anthropic")
        if isinstance(self.profile, AdmittedProviderProfile):
            require_profile_kind(self.profile, "anthropic", "anthropic_messages")
            from .providers.selected_runtime import current_construction
            if current_construction() is None:
                require_profile_base(self.profile, ANTHROPIC_API_BASE)
            if auth_pool is not None:
                raise ValueError("admitted Anthropic auth pool is unavailable")
        # H364 — one ladder rung for this install, clamped per model at send time.
        # Empty means "ask for nothing", which is what every install did before.
        # The override map is the escape hatch for a family whose contract moves
        # under us: it can widen or, by naming an empty list, silence a model.
        self.reasoning_effort = str(reasoning_effort or "")
        self._signed_base = (str(self.profile.default_base_url).rstrip('/')
                             if isinstance(self.profile, AdmittedProviderProfile) else ANTHROPIC_API_BASE)
        self.effort_overrides = parse_overrides(effort_overrides)
        # H12.20 — optional multi-key auth pool. When set, the active key is drawn
        # from the pool and a rotatable error (401/403/429) fails over to the next
        # healthy key. None → single-key behavior, unchanged.
        self.auth_pool = auth_pool
        self.client = (native_admitted_client(self.profile, api_key, model)
                       if isinstance(self.profile, AdmittedProviderProfile)
                       else llm_async_client("anthropic", timeout=120.0))

    def _active_key(self) -> str:
        if self.auth_pool is not None:
            return self.auth_pool.current_key() or self.api_key
        return self.api_key


    def _headers(self, profile=None) -> dict:
        return profile_headers(profile or self.profile, {
            "x-api-key": self._active_key(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        })

    def _declared_vocabulary(self, profile, model):
        declared = profile.supported_reasoning_efforts(model)
        normalized = str(model).strip().lower().replace(".", "-").replace("_", "-")
        if any(pattern and pattern in normalized for pattern in self.effort_overrides):
            declared = supported_reasoning_efforts(
                "anthropic", model, overrides=self.effort_overrides)
        return declared, normalized

    async def _request_profile(self, model: str, messages: list[dict]):
        profile = self.profile
        if not isinstance(profile, AdmittedProviderProfile):
            return profile
        from .request_context import current_session
        declared, _ = self._declared_vocabulary(profile, model)
        reasoning = profile_reasoning_config(
            profile, model, self.reasoning_effort, vocabulary=declared)
        return await prepare_admitted_profile(
            profile, model=model, messages=messages,
            reasoning_config=reasoning, session_id=current_session() or None)

    def _fit_to_wire(self, payload: dict, model: str, *, profile=None):
        """Add what this model accepts and remove what it rejects (H364).

        Runs on every request, not only the ones that ask to think harder: the
        sampling parameters return a 400 on the 4.7 generation and later whether
        or not an effort was requested, so `temperature` has to come off there
        even on a default install that never touches the ladder.
        """

        from .request_context import reconcile_payload, selected_reasoning
        profile = profile or self.profile
        declared, normalized = self._declared_vocabulary(profile, model)
        apply_profile_request(
            profile, payload, model=model,
            context={"reasoning_config": profile_reasoning_config(
                profile, model, self.reasoning_effort, vocabulary=declared)},
        )
        # apply_anthropic matches normalized family keys; use the same key as
        # the profile declaration so dotted/underscored model IDs cannot fall
        # through to the broader vendor capability at the physical send.
        overrides = ({normalized: declared} if declared is not None
                     else dict(self.effort_overrides))

        plan = apply_anthropic(
            payload,
            model or self.model,
            selected_reasoning(self.reasoning_effort),
            overrides=overrides,
        )
        # H681: a sampling value the model family refuses is taken off here; a delegated
        # child's record then says so instead of claiming the override was applied.
        reconcile_payload(payload)
        return plan

    def _build_messages(self, prompt: str, system: str = "") -> list[dict]:

        """Preserve the historical user-message helper used by callers."""
        return prepare_profile_messages(self.profile, [{"role": "user", "content": prompt}])

    def _prepared_text(self, prompt: str, system: str, *, profile=None) -> tuple[str, list[dict]]:
        rows = ([{"role": "system", "content": system}] if system else [])
        rows.append({"role": "user", "content": prompt})
        prepared = prepare_profile_messages(profile or self.profile, rows)
        return anthropic_messages(prepared)


    async def _text_payload(self, model, prompt, system, max_tokens, temperature, *, stream=False):
        rows = ([{"role": "system", "content": system}] if system else [])
        rows.append({"role": "user", "content": prompt})
        profile = await self._request_profile(model, rows)
        prepared_system, prepared_messages = self._prepared_text(prompt, system, profile=profile)
        payload = {
            "model": model,
            "max_tokens": cloud_cap(max_tokens),
            "temperature": temperature,
            "system": cache_marked_system(prepared_system) if prepared_system else prepared_system,
            "messages": prepared_messages,
        }
        if stream:
            payload["stream"] = True
        self._fit_to_wire(payload, model, profile=profile)
        return payload, profile

    async def _tool_payload(self, model, messages, tools, max_tokens, temperature):
        profile = await self._request_profile(model, messages)
        maximum = (512 * 1024 if isinstance(self.profile, AdmittedProviderProfile)
                   else _builtin_tool_history_limit(messages))
        system, converted = anthropic_messages(
            prepare_profile_messages(profile, messages, maximum=maximum))
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": cloud_cap(max_tokens),
            "temperature": temperature,
            "messages": converted,
        }
        if system:
            payload["system"] = cache_marked_system(system)
        if tools:
            payload["tools"] = cache_marked_tools(anthropic_tools(tools))
            payload["tool_choice"] = {"type": "auto"}
        self._fit_to_wire(payload, model, profile=profile)
        return payload, profile

    def _fail_over_held(self, key: str, exc: ProviderRateLimited) -> bool:
        """Cool a key the shared 429 guard holds for its whole hold, and say whether another
        key is left to try (H373: the refusal sent nothing, so failing over is safe)."""
        if self.auth_pool is None or self.auth_pool.size < 2:
            return False
        self.auth_pool.report_failure(key, cooldown=exc.retry_in)
        return True


    async def _post_messages(self, payload: dict | None, *, model=None, prepare_attempt=None) -> tuple[dict | None, str, int | None]:
        """POST /messages once per healthy auth profile, failing over on rotatable errors (H12.20).

        Returns ``(data, "", None)`` on success or ``(None, error_text, status)``; never
        raises. ``status`` is the HTTP error status that ended the call, and ``None`` when
        no HTTP error did (a transport error, the shared 429 guard refusing before
        sending, every profile exhausted) — H297 tells a request the provider refused as
        invalid from a transient failure by it.

        """
        attempts = self.auth_pool.size if self.auth_pool else 1
        last_err = ""
        last_exc: BaseException | None = None
        model = model or (payload or {}).get("model")
        for _ in range(max(1, attempts)):
            from .request_context import ensure_reasoning_active
            ensure_reasoning_active()
            attempt_payload, attempt_profile = (
                await prepare_attempt() if prepare_attempt is not None
                else (payload, self.profile))
            key = self._active_key()
            try:
                resp = await native_post(self.profile, attempt_profile, self.client,
                    f"{self._signed_base}/messages",
                    headers=self._headers(attempt_profile),
                    json=attempt_payload,
                )
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise ValueError("response body is not an object")
            except httpx.HTTPStatusError as e:
                last_err, last_exc = str(e), e
                status = e.response.status_code
                if self.auth_pool is not None and is_rotatable_status(status) and self.auth_pool.size > 1:
                    self.auth_pool.report_failure(key)
                    continue   # fail over to the next key
                note_provider_failure("anthropic", model, e)
                return None, f"[Claude API error: {e}]", status
            except ProviderRateLimited as e:
                # H373 — held by the shared 429 guard, refused before sending: the next key.
                last_err, last_exc = str(e), e
                if self._fail_over_held(key, e):
                    continue
                note_provider_failure("anthropic", model, e, kind="rate_limited", status=429)
                return None, f"[Claude API error: {e}]", None
            except Exception as e:
                note_provider_failure("anthropic", model, e)
                return None, f"[Claude API error: {e}]", None
            if self.auth_pool is not None:
                self.auth_pool.report_success(key)
            return data, "", None
        note_provider_failure("anthropic", model, last_exc)
        return None, f"[Claude API error: all auth profiles exhausted: {last_err}]", None

    async def generate(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        model = model or self.model

        if isinstance(self.profile, AdmittedProviderProfile):
            data, error, _status = await self._post_messages(
                None, model=model,
                prepare_attempt=lambda: self._text_payload(
                    model, prompt, system, max_tokens, temperature))
        else:
            payload, _ = await self._text_payload(model, prompt, system, max_tokens, temperature)
            data, error, _status = await self._post_messages(payload)

        if data is None:
            return error
        answer = (
            self._finalize_cloud(anthropic_text(data["content"]), data.get("stop_reason"), model)
            if data.get("content") else ""
        )
        report_text_usage(anthropic_usage(data))
        return answer

    async def generate_tool_turn(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> ToolTurn:
        """One tool-enabled turn; every tool_use block crosses `parse_openai_tool_calls`."""

        model = model or self.model
        if isinstance(self.profile, AdmittedProviderProfile):
            data, error, status = await self._post_messages(
                None, model=model,
                prepare_attempt=lambda: self._tool_payload(
                    model, messages, tools, max_tokens, temperature))
        else:
            payload, _ = await self._tool_payload(
                model, messages, tools, max_tokens, temperature)
            data, error, status = await self._post_messages(payload)

        if data is None:
            # H297: only a request the provider refused as invalid (400/413) is named,
            # so the tool loop can resend without the images it carried. A transient
            # failure (429, 5xx/529, timeout, auth) ends the turn with its error as
            # before and the images stay attached for the owner's retry.
            if status in _REJECTED_REQUEST_STATUSES:
                return ToolTurn(content=error, finish_reason=PROVIDER_REJECTED_FINISH)
            return ToolTurn(content=error)
        blocks = data.get("content") or []
        return ToolTurn(
            content=self._finalize_cloud(anthropic_text(blocks), data.get("stop_reason"), model),
            tool_calls=parse_openai_tool_calls(anthropic_tool_calls(blocks)),
            finish_reason=normalize_finish_reason(ANTHROPIC_FINISH_REASONS, data.get("stop_reason")),
            usage=anthropic_usage(data),
        )

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        model = model or self.model

        payload = profile = None
        if not isinstance(self.profile, AdmittedProviderProfile):
            payload, profile = await self._text_payload(
                model, prompt, system, max_tokens, temperature, stream=True)

        # H373 — a key the shared 429 guard holds is refused before a byte is sent, so
        # nothing has streamed yet and the next key in the pool is tried in its place.
        attempts = max(1, self.auth_pool.size if self.auth_pool else 1)
        for attempt in range(attempts):
            if isinstance(self.profile, AdmittedProviderProfile):
                payload, profile = await self._text_payload(
                    model, prompt, system, max_tokens, temperature, stream=True)
            full = ""
            stop_reason = None
            rg = RepetitionStreamGuard()   # H393: never paint a loop live
            raw_usage = {}
            started = completed = usage_failed = final_output = errored = False
            stream_key = self._active_key()
            try:
                async with native_stream(self.profile, profile, self.client,
                    "POST",
                    f"{self._signed_base}/messages",
                    headers=self._headers(profile),
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            chunk = line[6:]
                            if chunk.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(chunk)
                                event_type = data.get("type", "")
                                if "error" in data or event_type == "error":
                                    usage_failed = True
                                if event_type == "message_start":
                                    started = True
                                    raw = (data.get("message") or {}).get("usage")
                                    raw_usage = dict(raw) if isinstance(raw, dict) else {}
                                    if not isinstance(raw, dict):
                                        usage_failed = True
                                elif event_type == "message_delta":
                                    stop_reason = (data.get("delta") or {}).get("stop_reason") or stop_reason
                                    raw = data.get("usage")
                                    # A start/intermediate count is not final output.
                                    final_output = (isinstance(raw, dict)
                                                    and type(raw.get("output_tokens")) is int
                                                    and raw["output_tokens"] >= 0)
                                    if not isinstance(raw, dict):
                                        usage_failed = True
                                    if isinstance(raw, dict):
                                        # Deltas are cumulative snapshots, not increments.
                                        raw_usage.update(raw)
                                elif event_type == "content_block_delta":
                                    delta = data.get("delta", {})
                                    # Only the answer's own deltas. H364 makes thinking
                                    # reachable on this stream for the first time, and a
                                    # reasoning delta must never be concatenated into the
                                    # reply — so the block type decides, not the presence
                                    # of a `text` key.
                                    text = (
                                        delta.get("text", "")
                                        if delta.get("type") == "text_delta"
                                        else ""
                                    )
                                    if text:
                                        full += text
                                        if on_token:
                                            await _emit(on_token, rg.feed(text))
                                elif event_type == "message_stop":
                                    completed = True
                                    break
                            except json.JSONDecodeError:
                                usage_failed = True
                                continue
            except ProviderRateLimited as e:
                usage_failed = True
                errored = True
                full = f"[Claude API stream error: {e}]"
                if self._fail_over_held(stream_key, e) and attempt + 1 < attempts:
                    continue
                note_provider_failure("anthropic", model, e, kind="rate_limited", status=429)
            except httpx.HTTPStatusError as e:
                usage_failed = True
                errored = True
                # Rotatable error → cool this key down so the next call fails over (H12.20).
                if self.auth_pool is not None and is_rotatable_status(e.response.status_code):
                    self.auth_pool.report_failure(stream_key)
                full = f"[Claude API stream error: {e}]"
                note_provider_failure("anthropic", model, e)
            except Exception as e:
                usage_failed = True
                errored = True
                full = f"[Claude API stream error: {e}]"
                note_provider_failure("anthropic", model, e)
            break
        answer = self._finalize_cloud(full, stop_reason, model)
        # H393: withheld text reaches the bubble iff the answer was kept. Any
        # attempt that ended without an exception counts — a clean EOF without
        # message_stop still returns ``full`` as the answer — while an error
        # attempt returns a sentinel, never the withheld text.
        if on_token and not errored:
            await _emit(on_token, rg.release(answer))
        if started and completed and final_output and not usage_failed:
            report_text_usage(anthropic_usage({"usage": raw_usage}))
        return answer

    async def aclose(self):
        """Close the pooled httpx client (BUG-7)."""
        await self.client.aclose()
