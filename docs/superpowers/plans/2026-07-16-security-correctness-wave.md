# Security Correctness Wave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every verified security/correctness defect from the 2026-07-15 fresh-eyes audit in one integration branch and one draft pull request.

**Architecture:** Keep the existing router, policy, channel, and HTTP surfaces, but move authority to their correct request-scoped boundaries: selected LLM backend, immutable Gemini request lease, server-owned autonomy metadata, validated proxy peer, and explicitly governed channel sender. Deliver ten independently testable commits in dependency order; no endpoint or response schema is added.

**Tech Stack:** Python 3.12, FastAPI/Starlette, httpx, asyncio/ContextVar, SQLite, pytest, existing Jarvis guardrails/autonomy/channel primitives, Git component locks.

## Global Constraints

- Work only on `codex/security-correctness-wave`; publish one draft PR into `main`, never push directly to `main`.
- Before edits, run `python lock.py release-stale`, `python lock.py status`, and acquire the relevant component lock as `opencode`; release each component lock after its commit.
- Run at most two non-overlapping workstreams in parallel. `agents/core/orchestrator.py`, `agents/web.py`, `agents/core/llm/gemini.py`, `agents/core/llm/gemini_cache.py`, `.env.example`, `BACKLOG.md`, and generated status artifacts have one owner at a time.
- Frigga, Ultron, and Howard make zero cloud calls in normal, tool, synthesis, and streaming paths. A missing local backend returns one stable local-unavailable reply and never falls back to cloud.
- Guardrail `WARN` remains token-streaming. `REDACT` and `BLOCK` emit no token or tool argument before output enforcement.
- Gemini credentials use `x-goog-api-key`; no API key, request URL, prompt, provider response body, or raw provider exception may enter user text, persistence, or logs.
- Gemini cache identity includes model, system digest, history-prefix boundary/digest, auth-profile fingerprint, guardrail policy, and scanner version. Legacy or mismatched entries are misses.
- The canonical Claude default is exactly `claude-sonnet-4-6`; only the exact retired default `claude-sonnet-4-20250514` migrates. Custom values remain byte-identical.
- Proposal payload fields `kind`, `risk_tier`, `agent`, `origin`, `autonomy_level`, and `attention_mode` never carry policy authority. Execution payload bytes remain available to executors.
- Forwarding headers are authoritative only when `JARVIS_TRUSTED_PROXY=1` and the socket peer matches `JARVIS_TRUSTED_PROXY_CIDRS`. Preserve HF-7 fail-closed auth behind an untrusted same-host proxy.
- The HTTP limiter keeps a 60-second window and at most 4,096 buckets, including one reserved overflow bucket. Identity churn never clears or evicts a live dedicated bucket.
- Telegram starts only with a valid positive-integer owner allowlist or governed pairing. Pairing failures and callback identity ambiguity fail closed.
- Email remains default-off, uses SMTP ports `1..65535` (default `587`), IMAP ports `1..65535` (default `993`), IMAP polling `5..3600` seconds (default `60`), and `SMTP_TLS=true` on unknown input. Only `ChannelReplyBroker.execute()` may authorize an email send.
- No new route is added, so route/OpenAPI snapshots are not reseeded. Still run route, OpenAPI, lifespan, HUD, and mobile parity gates.
- Use a temporary settings database in cache/settings tests. Never delete or mutate the repository's shared runtime settings database.
- Do not claim live Telegram, SMTP, IMAP, Gemini, or Anthropic validation without owner credentials; hermetic transport tests must be labeled as such.

---

## Scope Check

The approved design covers independent LLM, autonomy, HTTP, Telegram, and email subsystems. Separate PR plans were considered, but the user explicitly selected one integration wave to avoid repeated GitHub waits, and `agents/core/orchestrator.py` plus `agents/web.py` require ordered shared-seam integration. This master plan therefore keeps one branch/PR while making each subsystem a separately reviewable, testable commit.

---

## File and Responsibility Map

### LLM and guardrails

- Create `agents/core/llm/gemini_context.py`: immutable Gemini lease binding, task-local scope value, and typed cached-content rejection.
- Create `agents/core/llm/provider_errors.py`: stable degraded replies plus secret-safe provider failure logging.
- Modify `agents/core/security/scanner.py`: scanner ruleset version and deterministic fingerprint.
- Modify `agents/core/security/guardrails.py`: unbound policy prototype, immutable backend binding, enforcing stream buffer, tool-argument enforcement, and guarded cache material.
- Modify `agents/core/llm/base.py`: stable strict-local unavailable reply and degraded-result recognition.
- Modify `agents/core/llm/hybrid_router.py`: typed strict-local selection failure and canonical model defaults.
- Modify `agents/core/llm/auth_rotation.py`: immutable `AuthLease` snapshots.
- Modify `agents/core/llm/gemini.py`: request-local binding, header authentication, bounded invalid-cache retry, and sanitized failures.
- Rewrite internals of `agents/core/llm/gemini_cache.py`: session locks, complete cache identity, compare-and-delete invalidation, header authentication, and temporary-DB-safe persistence.
- Modify `agents/core/agent.py`: bind guardrails only after backend selection for process/tool/synthesis.
- Modify `agents/core/orchestrator.py`: always-present guardrail prototype, selected-backend streaming, history boundary integration, tracked cache tasks, degraded-result bookkeeping.
- Modify `agents/core/plugins/cloud_llm.py`, `agents/core/resilience.py`, and `agents/core/http_client.py`: header authentication and secret-safe error/log behavior.
- Modify `agents/core/llm/model_config.py`, `agents/core/llm/anthropic.py`, `agents/core/llm/providers/__init__.py`, `agents/core/llm/cost_estimator.py`, and `agents/core/settings_db.py`: Claude 4.6 truth, exact migration, and price coverage.
- Modify public model hints in `agents/_templates/SOUL.template.md`, `agents/athena/SOUL.md`, `agents/argus/SOUL.md`, `agents/veronica/SOUL.md`, and `agents/vision/SOUL.md`; never touch `SOUL.local.md`.

### Autonomy and HTTP ingress

- Modify `agents/core/autonomy/policy.py`: strict trusted tier floor and effective-tier recalculation.
- Modify `agents/core/autonomy/worker.py`: sanitized policy view and authoritative reserved fields.
- Modify `agents/core/autonomy/queue.py`: atomic payload plus policy update that preserves task identity.
- Modify `agents/core/autonomy/observer.py`, `agents/core/autonomy/watchers.py`, and `agents/core/scheduler_service.py`: move intended tiers from payload data to the trusted call argument.
- Create `agents/core/http_identity.py`: pure CIDR parser and canonical request identity resolver.
- Create `agents/core/rate_limit.py`: bounded sliding-window limiter with an in-cap overflow bucket.
- Modify `agents/web.py`: use one client identity for auth and rate limiting, then wire secure channel startup.

### Channels and delivery truth

- Modify `agents/core/channels/gateway.py`: static sender policy plus global pairing fail-closed behavior.
- Modify `agents/core/channels/telegram.py`: strict allowlist parsing, pairing-compatible message flow, owner-only callbacks, and token-safe logs.
- Modify `agents/core/autonomy_coordinator.py`: live owner-chat validation at callback time.
- Modify `agents/core/channels/email.py`: canonical env construction, header validation, SMTP result, and observable IMAP health.
- Modify `agents/core/channels/manager.py`: email-capable approved-reply dispatch while generic auto-replies remain denied.
- Modify `agents/core/channel_reply.py`: call the approved-reply manager seam and preserve explicit failure results.
- Modify `.env.example`, `docs/ARCHITECTURE.md`, `docs/MANUAL_TESTING.md`, `mobile/PARITY.md`, `BACKLOG.md`, and generated status artifacts: exact secure defaults, parity, backlog reconciliation, and test counts.

---

### Task 1: Make Guardrails an Immutable, Fully Enforcing Policy

**Files:**
- Modify: `agents/core/security/scanner.py`
- Modify: `agents/core/security/guardrails.py`
- Modify: `agents/core/security/__init__.py`
- Modify: `tests/test_guardrails_generate_kwargs.py`

**Interfaces:**
- Consumes: `LLMBackend`, frozen `ToolCall`/`ToolTurn`, `RedactionMode`, existing secret/PII scanners.
- Produces: `GuardrailBindingError`, `GuardedCacheMaterial`, `GuardrailsEngine.bind()`, `GuardrailsEngine.policy_fingerprint()`, `GuardrailsEngine.prepare_cache_material()`, and `bind_guardrails()`.

- [ ] **Step 1: Add red tests for binding and output enforcement**

Add these exact cases to `tests/test_guardrails_generate_kwargs.py` using its existing `_EchoBackend` and `_RecordingToolBackend` fixtures:

```python
async def test_unbound_policy_rejects_generation():
    policy = GuardrailsEngine(backend=None)
    with pytest.raises(GuardrailBindingError):
        await policy.generate("m", "hello")


def test_bind_returns_distinct_wrapper_with_same_policy():
    policy = GuardrailsEngine(backend=None, mode=RedactionMode.REDACT)
    first = policy.bind(_EchoBackend("one"))
    second = policy.bind(_EchoBackend("two"))
    assert first is not second
    assert first._backend is not second._backend
    assert first.policy_fingerprint() == second.policy_fingerprint()
    assert policy._backend is None


async def test_generate_stream_redact_buffers_before_callback():
    emitted = []
    engine = GuardrailsEngine(_EchoBackend(f"mail {_EMAIL}"), mode=RedactionMode.REDACT)
    result = await engine.generate_stream("m", "safe", on_token=emitted.append)
    assert _EMAIL not in result
    assert emitted == [result]


async def test_generate_stream_block_emits_nothing():
    emitted = []
    engine = GuardrailsEngine(_EchoBackend(f"mail {_EMAIL}"), mode=RedactionMode.BLOCK)
    with pytest.raises(SecurityBlockError):
        await engine.generate_stream("m", "safe", on_token=emitted.append)
    assert emitted == []
```

Also add `test_generate_tool_turn_redacts_arguments_consistently`, `test_generate_tool_turn_non_string_finding_fails_closed`, and `test_prepare_cache_material_redacts_copy_without_mutation`. Assert that redacted `arguments` parses to the same value as `raw_arguments`, call ID/name are unchanged, a numeric surviving finding raises, `BLOCK` returns before cache I/O, and the original history tuple remains unchanged.

- [ ] **Step 2: Run the new tests and verify red**

Run:

```powershell
python -m pytest tests/test_guardrails_generate_kwargs.py -k "unbound or bind_returns or buffers_before or emits_nothing or tool_turn or cache_material" -v
```

Expected: FAIL because a policy currently requires a backend, shared state has no binding method, enforcing streams forward raw tokens, and tool arguments are not scanned.

- [ ] **Step 3: Implement the immutable guardrail seam**

Import `hashlib`, then add the ruleset version and deterministic scanner identity in `scanner.py`:

```python
SCANNER_RULESET_VERSION = "2026-07-15.1"


class BaseScanner:
    scanner_id = "base"

    def fingerprint(self) -> str:
        material = {
            "id": self.scanner_id,
            "version": SCANNER_RULESET_VERSION,
            "patterns": [
                {
                    "name": name,
                    "pattern": pattern.pattern,
                    "flags": pattern.flags,
                    "threat": threat.value,
                    "description": description,
                }
                for name, pattern, threat, description in self._compiled
            ],
        }
        raw = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

Implement the public guardrail values and binding shape in `guardrails.py`:

```python
@dataclass(frozen=True, slots=True)
class GuardedCacheMaterial:
    system_instruction: str
    history: tuple[str, ...]
    policy_fingerprint: str


class GuardrailBindingError(RuntimeError):
    pass


def bind_guardrails(policy: "GuardrailsEngine | None", backend: LLMBackend) -> LLMBackend:
    return policy.bind(backend) if policy is not None else backend


class GuardrailsEngine:
    def __init__(
        self,
        backend: LLMBackend | None = None,
        mode: RedactionMode = RedactionMode.WARN,
        scan_input: bool = True,
        scan_output: bool = True,
        scanners: Sequence[BaseScanner] | None = None,
    ) -> None:
        self._backend = backend
        self._scanners = tuple(scanners) if scanners is not None else (
            SecretScanner(),
            PIIScanner(),
        )
        self._mode = mode
        self._scan_input = scan_input
        self._scan_output = scan_output

    def bind(self, backend: LLMBackend) -> "GuardrailsEngine":
        return GuardrailsEngine(
            backend=backend,
            mode=self._mode,
            scan_input=self._scan_input,
            scan_output=self._scan_output,
            scanners=self._scanners,
        )

    def _bound_backend(self) -> LLMBackend:
        if self._backend is None:
            raise GuardrailBindingError("guardrails policy is not bound to a backend")
        return self._backend
```

Make `supports_tools`, `generate`, `generate_tool_turn`, and `generate_stream` call `_bound_backend()`. For enforcing streams, suppress the provider callback, scan the complete result, and emit only the safe result:

```python
if self._scan_output and self._mode in {RedactionMode.REDACT, RedactionMode.BLOCK}:
    response = await self._bound_backend().generate_stream(
        model=model,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
        on_token=None,
    )
    safe = self._guard_output(response)
    if on_token is not None and safe:
        emitted = on_token(safe)
        if inspect.isawaitable(emitted):
            await emitted
    return safe
```

Rebuild every `ToolCall` with `dataclasses.replace()`: recursively guard string values, regenerate compact sorted JSON, scan that JSON again, and raise `SecurityBlockError` when any finding survives. Use these exact helper shapes so `arguments` and `raw_arguments` cannot diverge:

```python
def _guard_tool_value(self, value):
    if isinstance(value, str):
        return self._guard_output(value)
    if isinstance(value, list):
        return [self._guard_tool_value(item) for item in value]
    if isinstance(value, dict):
        return {key: self._guard_tool_value(item) for key, item in value.items()}
    return value


def _guard_tool_call(self, call: ToolCall) -> ToolCall:
    guarded = self._guard_tool_value(call.arguments)
    raw = json.dumps(guarded, sort_keys=True, separators=(",", ":"))
    if self._scan_output and not self._scan_text(raw).clean:
        raise SecurityBlockError("guarded tool arguments still match a security rule")
    return dataclasses.replace(call, arguments=guarded, raw_arguments=raw)
```

`prepare_cache_material()` guards copies of the system/history strings and returns a fingerprint over mode, input/output scan flags, ruleset version, and scanner fingerprints:

```python
def policy_fingerprint(self) -> str:
    material = {
        "mode": self._mode.value,
        "scan_input": self._scan_input,
        "scan_output": self._scan_output,
        "ruleset": SCANNER_RULESET_VERSION,
        "scanners": [scanner.fingerprint() for scanner in self._scanners],
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def prepare_cache_material(
    self,
    system_instruction: str,
    history: Sequence[str],
) -> GuardedCacheMaterial:
    guard = self._guard_input if self._scan_input else (lambda value: value)
    return GuardedCacheMaterial(
        system_instruction=guard(str(system_instruction)),
        history=tuple(guard(str(part)) for part in history),
        policy_fingerprint=self.policy_fingerprint(),
    )
```

- [ ] **Step 4: Run focused green**

Run:

```powershell
python -m pytest tests/test_guardrails_generate_kwargs.py -v
```

Expected: PASS, including replacement of the old unsafe assertion that allowed an email address to survive in `raw_arguments`.

- [ ] **Step 5: Commit Task 1**

```powershell
git add agents/core/security/scanner.py agents/core/security/guardrails.py agents/core/security/__init__.py tests/test_guardrails_generate_kwargs.py
git commit -m "fix(security): enforce bound guardrails"
```

### Task 2: Preserve the Selected Backend Through Every Agent Path

**Files:**
- Modify: `agents/core/llm/base.py`
- Modify: `agents/core/llm/hybrid_router.py`
- Modify: `agents/core/agent.py`
- Modify: `agents/core/orchestrator.py`
- Modify: `tests/test_hybrid_router.py`
- Modify: `tests/test_admin_knobs_wiring.py`
- Create: `tests/test_route_preserving_guardrails.py`

**Interfaces:**
- Consumes: `bind_guardrails()` from Task 1 and the existing router three-tuple `(backend, model, route)`.
- Produces: `LocalBackendUnavailableError`, `LOCAL_SELECTION_UNAVAILABLE_REPLY`, and one selected-backend binding algorithm shared by normal, tool, synthesis, and streaming paths.

- [ ] **Step 1: Add hermetic route-preservation tests**

Create `tests/test_route_preserving_guardrails.py`. Parameterize Frigga, Ultron, and Howard with separate local/Gemini/Claude recording backends:

```python
@pytest.mark.parametrize("agent_id", ["frigga", "ultron", "howard"])
async def test_local_only_agents_never_call_cloud_after_guardrail_binding(agent_id):
    local = RecordingBackend("local answer")
    gemini = RecordingBackend("gemini answer")
    claude = RecordingBackend("claude answer")
    agent = build_agent(agent_id, local=local, gemini=gemini, claude=claude)
    agent.guardrails = GuardrailsEngine(backend=claude)
    assert await agent.process("private request", {"session_id": "s"}) == "local answer"
    assert len(local.calls) == 1
    assert gemini.calls == []
    assert claude.calls == []
```

Add exact cases `test_tool_runtime_receives_wrapper_bound_to_selected_backend`, `test_synthesis_uses_selected_backend_not_boot_backend`, `test_streaming_uses_selected_backend_not_policy_prototype`, `test_boot_without_backend_then_redetect_guards_first_request`, `test_local_unavailable_paths_share_stable_reply_and_zero_cloud_calls`, and `test_unavailable_synthesis_returns_constituent_reports`.

- [ ] **Step 2: Verify the bypass tests fail**

Run:

```powershell
python -m pytest tests/test_route_preserving_guardrails.py tests/test_admin_knobs_wiring.py::test_orchestrator_guardrails_honors_settings -v
```

Expected: FAIL because `Agent.process`, `Agent.synthesize`, and streamed orchestration replace the routed backend with the boot-bound global wrapper; boot without a backend also drops guardrails.

- [ ] **Step 3: Introduce typed local-selection failure and one public reply**

In `base.py` add:

```python
LOCAL_SELECTION_UNAVAILABLE_REPLY = (
    "⚠️ No local language model is available. "
    "Start LM Studio or Ollama and try again."
)
```

In `hybrid_router.py` add `LocalBackendUnavailableError(RuntimeError)` and raise it from every strict-local no-backend branch, including Howard. Do not catch it by selecting Gemini or Claude.

- [ ] **Step 4: Bind only after selection**

In `Agent.process()` and `Agent.synthesize()` use this order:

```python
try:
    selected, routed_model, route_name = self.llm_router.select_backend(self.id, prompt)
except LocalBackendUnavailableError:
    return LOCAL_SELECTION_UNAVAILABLE_REPLY
backend = bind_guardrails(self.guardrails, selected)
```

Use the same `bind_guardrails()` call in `_handle_input_stream()`. In `Orchestrator.load_agents()`, always construct the policy prototype without reading `self.llm_router.backend`:

```python
self.security = GuardrailsEngine(
    backend=None,
    mode=_mode,
    scan_input=bool(_gv("security", "scan_input", True)),
    scan_output=bool(_gv("security", "scan_output", True)),
)
```

Keep this prototype on active and later-promoted agents. If synthesis selection raises the typed local error, return the already-produced constituent reports; do not make a replacement provider call.

- [ ] **Step 5: Run focused and adjacent green**

Run:

```powershell
python -m pytest tests/test_route_preserving_guardrails.py tests/test_guardrails_generate_kwargs.py tests/test_hybrid_router.py tests/test_admin_knobs_wiring.py tests/test_agent_runtime_v2.py -q
```

Expected: PASS with zero cloud calls for all three strict-local agents and unchanged cloud-capable routing.

- [ ] **Step 6: Commit Task 2**

```powershell
git add agents/core/llm/base.py agents/core/llm/hybrid_router.py agents/core/agent.py agents/core/orchestrator.py tests/test_hybrid_router.py tests/test_admin_knobs_wiring.py tests/test_route_preserving_guardrails.py
git commit -m "fix(llm): preserve selected routes through guardrails"
```

### Task 3: Make Gemini Authentication Request-Scoped and Secret-Safe

**Files:**
- Create: `agents/core/llm/gemini_context.py`
- Create: `agents/core/llm/provider_errors.py`
- Modify: `agents/core/llm/auth_rotation.py`
- Modify: `agents/core/llm/gemini.py`
- Modify: `agents/core/plugins/cloud_llm.py`
- Modify: `agents/core/resilience.py`
- Modify: `agents/core/http_client.py`
- Modify: `tests/test_h12_20_auth_rotation.py`
- Modify: `tests/test_hybrid_router.py`
- Modify: `tests/test_resilience.py`
- Modify: `tests/test_http_client.py`
- Create: `tests/test_gemini_request_context.py`
- Create: `tests/test_gemini_secret_safety.py`

**Interfaces:**
- Consumes: the existing `AuthProfilePool` health/rotation behavior and `GeminiBackend` public generate/stream signatures.
- Produces: frozen `AuthLease`, frozen `GeminiRequestBinding`, `CachedContentRejected`, task-local `GeminiBackend.request_scope()`, `GEMINI_DEGRADED_REPLY`, and `log_provider_failure()`.

- [ ] **Step 1: Add red request-scope and secret-sentinel tests**

Use these exact sentinels in `tests/test_gemini_secret_safety.py`:

```python
API_KEY_SENTINEL = "API_KEY_SENTINEL_7e31"
URL_SENTINEL = "MODEL_URL_SENTINEL_91ac"
PROMPT_SENTINEL = "PROMPT_SENTINEL_02bf"
BODY_SENTINEL = "BODY_SENTINEL_f433"
```

Add `test_generate_uses_header_auth_and_sanitizes_http_failure`, `test_stream_uses_header_auth_and_sanitizes_http_failure`, `test_non_http_transport_failure_is_sanitized`, `test_cloud_plugin_uses_header_and_sanitizes_retry_exhaustion`, `test_gemini_sentinels_absent_from_debug_logs`, and `test_gemini_sources_never_construct_key_query`. Assert no request URL contains `?key=`, the header contains the exact active lease key, returned text equals the stable degraded constant, and none of the four sentinels appear in captured DEBUG logs.

In `tests/test_gemini_request_context.py`, add `test_nested_scope_restores_parent`, `test_scope_resets_after_exception`, `test_scope_resets_after_cancellation`, `test_concurrent_scopes_do_not_leak_cache_names`, `test_uncached_request_inherits_no_previous_cache`, `test_cached_rejection_invalidates_and_retries_generate_once`, `test_cached_rejection_invalidates_and_retries_stream_once`, and `test_auth_rotation_drops_old_cache_binding`.

- [ ] **Step 2: Run the new tests and verify red**

Run:

```powershell
python -m pytest tests/test_gemini_request_context.py tests/test_gemini_secret_safety.py tests/test_resilience.py::test_resilient_call_final_error_log_omits_exception_message tests/test_http_client.py::test_open_post_breaker_log_omits_request_url -q
```

Expected: FAIL because the cache name is shared mutable state, keys are in URLs, and raw exceptions are logged/returned.

- [ ] **Step 3: Add immutable auth and request values**

In `auth_rotation.py` import `dataclass` and add:

```python
@dataclass(frozen=True, slots=True)
class AuthLease:
    profile_id: str
    api_key: str


def lease(self) -> AuthLease | None:
    profile = self.current()
    if profile is None:
        return None
    return AuthLease(profile_id=profile.id, api_key=profile.api_key)
```

`GeminiBackend.acquire_lease()` returns `self.auth_pool.lease()` when a pool exists; otherwise it returns `AuthLease(profile_id="gemini-single", api_key=self.api_key)` for a configured single key. If neither source has a key, it raises a provider-unavailable error before constructing a request.

In `gemini_context.py` define:

```python
InvalidateCallback = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class GeminiRequestBinding:
    lease: AuthLease
    session_id: str | None = None
    cache_name: str | None = None
    cached_prefix_count: int = 0
    invalidate_cache: InvalidateCallback | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def without_cache(self, *, lease: AuthLease | None = None) -> "GeminiRequestBinding":
        return replace(
            self,
            lease=lease or self.lease,
            cache_name=None,
            cached_prefix_count=0,
            invalidate_cache=None,
        )


class CachedContentRejected(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"cached content rejected ({status_code})")
```

- [ ] **Step 4: Add the provider-safe error contract**

Create `provider_errors.py`:

```python
GEMINI_DEGRADED_REPLY: Final[str] = "[Gemini error: provider request failed]"


def provider_http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def log_provider_failure(
    logger: logging.Logger,
    *,
    provider: str,
    operation: str,
    exc: BaseException,
    level: int = logging.WARNING,
) -> None:
    status = provider_http_status(exc)
    logger.log(
        level,
        "%s %s failed (type=%s, status=%s)",
        provider,
        operation,
        type(exc).__name__,
        status if status is not None else "none",
    )
```

Never pass `str(exc)`, traceback, URL, body, prompt, or headers to this helper.

- [ ] **Step 5: Replace mutable cache state and query authentication in Gemini**

Give `GeminiBackend` a task-local context and remove `_use_cache`:

```python
self._request_binding: ContextVar[GeminiRequestBinding | None] = ContextVar(
    f"gemini_request_binding_{id(self)}",
    default=None,
)

@contextmanager
def request_scope(self, binding: GeminiRequestBinding):
    token = self._request_binding.set(binding)
    try:
        yield binding
    finally:
        self._request_binding.reset(token)

def current_binding(self) -> GeminiRequestBinding | None:
    return self._request_binding.get()
```

`_build_payload()` reads only `current_binding().cache_name`. The common request helper captures the binding once before any await and uses that same binding for payload construction, header authentication, success/failure reporting, and the optional one-time cache rejection retry.

Build provider URLs without secrets:

```python
def _build_url(self, model: str, *, streaming: bool = False) -> str:
    action = "streamGenerateContent" if streaming else "generateContent"
    suffix = "?alt=sse" if streaming else ""
    return f"{GEMINI_API_BASE}/models/{model}:{action}{suffix}"
```

Every request uses:

```python
headers = {"x-goog-api-key": binding.lease.api_key}
```

When a bound cached request receives cache-specific `400` or `404`, raise `CachedContentRejected`. The common generate/stream helper awaits `invalidate_cache()` and retries once under `binding.without_cache()`. Auth rotation reports success/failure against `lease.profile_id`, and a new lease never inherits the old cache name. Exhaustion returns only `GEMINI_DEGRADED_REPLY`.

Update `CloudLLMPlugin._call_gemini()` to use the same header and URL rule. Sanitize the final failure logs in `resilience.py` and remove request URLs from the circuit-open log in `http_client.py`.

- [ ] **Step 6: Run focused green**

Run:

```powershell
python -m pytest tests/test_gemini_request_context.py tests/test_gemini_secret_safety.py tests/test_h12_20_auth_rotation.py tests/test_hybrid_router.py tests/test_resilience.py tests/test_http_client.py -q
```

Expected: PASS; generate/stream/plugin use header auth, request scopes isolate cache names, and sentinel values are absent from results/logs.

- [ ] **Step 7: Commit Task 3**

```powershell
git add agents/core/llm/gemini_context.py agents/core/llm/provider_errors.py agents/core/llm/auth_rotation.py agents/core/llm/gemini.py agents/core/plugins/cloud_llm.py agents/core/resilience.py agents/core/http_client.py tests/test_h12_20_auth_rotation.py tests/test_hybrid_router.py tests/test_resilience.py tests/test_http_client.py tests/test_gemini_request_context.py tests/test_gemini_secret_safety.py
git commit -m "fix(llm): isolate Gemini auth and sanitize failures"
```

### Task 4: Make Gemini Context Cache Atomic, Boundary-Aware, and Shutdown-Safe

**Files:**
- Rewrite internals: `agents/core/llm/gemini_cache.py`
- Modify: `agents/core/orchestrator.py`
- Modify: `tests/test_gemini_cache.py`
- Create: `tests/test_orchestrator_gemini_cache.py`
- Modify: `tests/test_agent_runtime_v2.py`
- Modify: `tests/test_context_compression_phase2.py`
- Modify: `tests/test_shutdown_cleanup.py`

**Interfaces:**
- Consumes: `AuthLease`, `GeminiRequestBinding`, `GeminiBackend.request_scope()`, `GuardedCacheMaterial`, and `bind_guardrails()` from Tasks 1–3.
- Produces: frozen `CacheEntry`, `ContextCache.acquire_binding()`, `ContextCache.create_or_extend()`, compare-and-delete `ContextCache.invalidate()`, tracked cache background tasks, and exact once-only history-tail prompting.

- [ ] **Step 1: Isolate existing cache tests from runtime state and add red identity tests**

Replace the current cache cleanup fixture with a temporary settings database:

```python
@pytest.fixture(autouse=True)
def isolated_settings_db(tmp_path, monkeypatch):
    from core import settings_db

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    settings_db.ensure_initialized()
```

Add to `tests/test_gemini_cache.py`: `test_acquire_binding_hit_returns_recorded_boundary`, `test_acquire_binding_miss_on_identity_change`, `test_legacy_entry_is_miss`, `test_same_session_create_is_serialized`, `test_different_sessions_can_create_concurrently`, `test_compare_and_delete_preserves_newer_mapping`, `test_policy_or_scanner_change_invalidates_mapping`, and `test_persistence_omits_raw_history_and_api_key`.

Create `tests/test_orchestrator_gemini_cache.py` with `test_cache_hit_sends_tail_exactly_once`, `test_changed_or_truncated_prefix_sends_full_history`, `test_cache_miss_keeps_full_history_and_schedules_creation`, `test_block_mode_performs_zero_cache_network_calls`, `test_redact_mode_uploads_copy_without_mutating_history`, `test_warn_cache_is_not_reused_after_enforcing_restart`, and `test_shutdown_drains_cache_tasks_before_client_close`. Count every prior/current turn occurrence in the final provider prompt; do not assert only the cache name.

- [ ] **Step 2: Verify cache identity and history boundary tests fail**

Run:

```powershell
python -m pytest tests/test_gemini_cache.py tests/test_orchestrator_gemini_cache.py tests/test_shutdown_cleanup.py -q
```

Expected: FAIL because persistence lacks full identity/boundary metadata, cache decisions are unsynchronized, streaming omits all history on any hit, and cache tasks are untracked.

- [ ] **Step 3: Implement the persisted cache value and identity functions**

In `gemini_cache.py` define:

```python
@dataclass(frozen=True, slots=True)
class CacheEntry:
    cache_name: str
    model: str
    system_digest: str
    prefix_count: int
    prefix_digest: str
    policy_fingerprint: str
    profile_fingerprint: str


def _digest_parts(parts: Sequence[str]) -> str:
    encoded = json.dumps(
        list(parts),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _profile_fingerprint(lease: AuthLease) -> str:
    return hashlib.sha256(lease.api_key.encode("utf-8")).hexdigest()
```

The class interface is:

```python
class ContextCache:
    def __init__(
        self,
        auth_pool_provider: Callable[[], AuthProfilePool | None],
    ) -> None:
        self._auth_pool_provider = auth_pool_provider
        self._cache_map = self._load_map()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._client = httpx.AsyncClient(timeout=30.0)

    async def acquire_binding(
        self,
        *,
        session_id: str,
        model: str,
        system_instruction: str,
        history: Sequence[str],
        policy_fingerprint: str,
        lease: AuthLease,
    ) -> GeminiRequestBinding | None:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            entry = self._entry_for(session_id)
            if entry is None or not self._entry_matches(
                entry,
                model=model,
                system_instruction=system_instruction,
                history=history,
                policy_fingerprint=policy_fingerprint,
                lease=lease,
            ):
                return None
            expected_name = entry.cache_name

            async def invalidate_cache() -> bool:
                return await self.invalidate(
                    session_id=session_id,
                    expected_cache_name=expected_name,
                )

            return GeminiRequestBinding(
                lease=lease,
                session_id=session_id,
                cache_name=entry.cache_name,
                cached_prefix_count=entry.prefix_count,
                invalidate_cache=invalidate_cache,
            )
```

`_entry_matches()` must require the same model, system digest, policy fingerprint, profile fingerprint, and a prefix count within current history whose digest equals the persisted prefix digest. Mapping dictionaries missing any field return `None` from `_entry_for()` and are treated as legacy misses:

```python
def _entry_for(self, session_id: str) -> CacheEntry | None:
    raw = self._cache_map.get(session_id)
    if not isinstance(raw, dict):
        return None
    try:
        return CacheEntry(**{field.name: raw[field.name] for field in fields(CacheEntry)})
    except (KeyError, TypeError, ValueError):
        return None

def _entry_matches(self, entry: CacheEntry, *, model, system_instruction, history,
                   policy_fingerprint, lease) -> bool:
    if entry.prefix_count < 0 or entry.prefix_count > len(history):
        return False
    return (
        entry.model == model
        and entry.system_digest == _digest_parts((system_instruction,))
        and entry.prefix_digest == _digest_parts(history[: entry.prefix_count])
        and entry.policy_fingerprint == policy_fingerprint
        and entry.profile_fingerprint == _profile_fingerprint(lease)
    )
```

Persistence serializes only the seven `CacheEntry` fields with `dataclasses.asdict()`; no raw history, key, or profile ID is written.

- [ ] **Step 4: Serialize cache network operations and authenticate by lease**

`create_or_extend()` acquires the per-session lock, rechecks the current entry, and sends cache POST/PATCH with:

```python
headers = {"x-goog-api-key": lease.api_key}
```

The URL contains no credential. It calls `report_success(lease.profile_id)` on success and `report_failure(lease.profile_id)` on rotatable failure. It attempts each healthy lease once, never carries a cache name across a lease change, and persists only after provider success. `invalidate(session_id, expected_cache_name)` removes the mapping only when its current name still matches; this preserves a newer concurrent mapping.

- [ ] **Step 5: Integrate history parts, guardrails, and task lifecycle once**

Add these orchestrator seams:

```python
async def _history_for_prompt_parts(self, last_n: int) -> tuple[str, tuple[str, ...]]:
    history_text = await self._history_for_prompt(last_n)
    parts = tuple(part.strip() for part in history_text.split("\n---\n") if part.strip())
    return history_text, parts


def _spawn_cache_task(self, coroutine, *, session_id: str) -> None:
    task = asyncio.create_task(coroutine, name=f"gemini-cache:{session_id}")
    self._cache_tasks.add(task)
    task.add_done_callback(self._cache_tasks.discard)
    task.add_done_callback(_log_task_result)
```

Set `self.context_cache: ContextCache | None = None` in `Orchestrator.__init__`. Construct it only after router detection, using `lambda: self.llm_router._gemini_pool`, so `GEMINI_API_KEYS`-only configurations work. In `_handle_input_stream()`, build the full prompt first and route on it; for a selected `GeminiBackend`, prepare guarded cache material, acquire one lease, acquire a cache binding, rebuild the prompt from `history_parts[binding.cached_prefix_count:]` on a valid hit, and include the current user turn separately exactly once. A miss retains all history and schedules creation. `BLOCK` schedules no cache network call. Scope the selected Gemini binding before wrapping it with guardrails.

Initialize `self._cache_tasks` to an empty set. In `aclose()`, cancel and drain those tasks before closing `ContextCache`:

```python
for task in tuple(self._cache_tasks):
    task.cancel()
await asyncio.gather(*self._cache_tasks, return_exceptions=True)
self._cache_tasks.clear()
if self.context_cache is not None:
    await self.context_cache.close()
```

- [ ] **Step 6: Run focused cache and streaming green**

Run:

```powershell
python -m pytest tests/test_gemini_cache.py tests/test_orchestrator_gemini_cache.py tests/test_gemini_request_context.py tests/test_gemini_secret_safety.py tests/test_h12_20_auth_rotation.py tests/test_agent_runtime_v2.py tests/test_context_compression_phase2.py tests/test_shutdown_cleanup.py -q
```

Expected: PASS; concurrent sessions are isolated, every tail turn occurs once, stricter guardrail policy invalidates old cache entries, and shutdown drains cache work before client close.

- [ ] **Step 7: Commit Task 4**

```powershell
git add agents/core/llm/gemini_cache.py agents/core/orchestrator.py tests/test_gemini_cache.py tests/test_orchestrator_gemini_cache.py tests/test_agent_runtime_v2.py tests/test_context_compression_phase2.py tests/test_shutdown_cleanup.py
git commit -m "fix(llm): make Gemini cache request scoped"
```

### Task 5: Align Claude Model Truth and Degraded-Result Bookkeeping

**Files:**
- Modify: `agents/core/llm/model_config.py`
- Modify: `agents/core/llm/anthropic.py`
- Modify: `agents/core/plugins/cloud_llm.py`
- Modify: `agents/core/llm/providers/__init__.py`
- Modify: `agents/core/settings_db.py`
- Modify: `agents/core/llm/cost_estimator.py`
- Modify: `agents/core/orchestrator.py`
- Modify: `agents/_templates/SOUL.template.md`
- Modify: `agents/athena/SOUL.md`
- Modify: `agents/argus/SOUL.md`
- Modify: `agents/veronica/SOUL.md`
- Modify: `agents/vision/SOUL.md`
- Modify: `tests/test_settings_db.py`
- Modify: `tests/test_orchestrator_process_record.py`
- Modify: `tests/test_hybrid_router.py`
- Modify: `tests/test_cost_estimator.py`
- Modify: `tests/test_h10_24_cost_trace.py`
- Modify: `tests/test_resilience_integration.py`
- Create: `tests/test_claude_model_truth.py`

**Interfaces:**
- Consumes: `is_degraded_reply()` and the current settings seed transaction.
- Produces: `DEFAULT_CLAUDE_MODEL`, migration-only `RETIRED_CLAUDE_DEFAULT`, exact conditional migration, non-zero canonical pricing, and `_is_failed_agent_reply()`.

- [ ] **Step 1: Add red default/migration/result tests**

Add settings cases `test_fresh_db_seeds_current_claude_default`, `test_retired_claude_default_migrates_exactly_once`, `test_custom_claude_model_value_remains_byte_identical`, `test_claude_migration_is_idempotent`, `test_force_init_reseeds_current_claude_default`, and `test_concurrent_ensure_initialized_migrates_once` using a patched temporary `DB_PATH`.

Create `tests/test_claude_model_truth.py` with `test_claude_backend_default_is_canonical`, `test_cloud_plugin_default_is_canonical`, `test_anthropic_profile_default_is_canonical`, `test_settings_default_is_canonical`, `test_public_soul_hints_are_claude_4_6`, `test_retired_default_is_not_an_operational_default`, and `test_configured_cloud_defaults_have_prices`. Assert `estimate_cost(DEFAULT_CLAUDE_MODEL, 1_000_000, 1_000_000)["total"] == 18.0` and unknown models remain zero-priced.

Extend `tests/test_orchestrator_process_record.py` with:

```python
def test_record_gemini_degraded_reply_is_failure_everywhere(orchestrator):
    response = "[Gemini error: provider request failed]"
    captured = {}
    orchestrator.learning.record = lambda **kw: captured.update(
        learning=kw["success"]
    )
    orchestrator.bench.record = lambda **kw: captured.update(
        bench=kw["success"]
    )

    class RecordingRunHistory:
        def record(self, **kwargs):
            captured["run_history"] = kwargs["ok"]

    orchestrator.run_history = RecordingRunHistory()
    orchestrator._record_interactions("prompt", {"jarvis": response}, response)
    assert captured == {
        "learning": False,
        "bench": False,
        "run_history": False,
    }


def test_degraded_reply_does_not_spawn_background_review(orchestrator):
    orchestrator._spawn_background_review(
        "prompt",
        "[Gemini error: provider request failed]",
        "web",
    )
    assert orchestrator.spawned_reviews == []
```

Use the existing test doubles' actual observation fields when integrating these assertions.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests/test_settings_db.py tests/test_claude_model_truth.py tests/test_orchestrator_process_record.py -k "claude or degraded or model_truth" -q
```

Expected: FAIL because operational defaults are retired, seed initialization does not migrate existing rows, and degraded cloud replies are recorded as successful work.

- [ ] **Step 3: Centralize Claude 4.6 and migrate only the retired value**

In `model_config.py` define:

```python
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
RETIRED_CLAUDE_DEFAULT = "claude-sonnet-4-20250514"
```

Import `DEFAULT_CLAUDE_MODEL` into the Anthropic backend, cloud plugin, provider profile, settings defaults, and cost estimator. In `settings_db.py` add:

```python
def _migrate_retired_claude_default(conn: sqlite3.Connection) -> bool:
    cursor = conn.execute(
        """
        UPDATE settings
           SET value = ?
         WHERE category = 'llm'
           AND key = 'claude_model'
           AND value = ?
        """,
        (
            json.dumps(DEFAULT_CLAUDE_MODEL),
            json.dumps(RETIRED_CLAUDE_DEFAULT),
        ),
    )
    return cursor.rowcount > 0
```

Call it after `INSERT OR IGNORE` and before the existing single commit. `force=True` deletes then seeds 4.6, making migration a no-op. Do not query and rewrite custom values.

Add `MODELS[DEFAULT_CLAUDE_MODEL] = {"input": 3.00, "output": 15.00}` and change every listed public SOUL fallback to `claude-sonnet-4-6`.

- [ ] **Step 4: Mark degraded replies as failures everywhere that learns**

In `orchestrator.py` define:

```python
def _is_failed_agent_reply(agent_id: str | None, response: object) -> bool:
    return is_degraded_reply(response) or bool(
        agent_id
        and re.match(
            rf"^\[{re.escape(agent_id)} (error|timeout)\b",
            str(response),
        )
    )
```

Use it for `learning.record(success=)`, `bench.record(success=)`, and `run_history.record(ok=)`. Return early from `_spawn_background_review()` for degraded synthesized output, and do not apply positive persona/living-memory success signals. The stable generic degraded reply may remain in conversation history; provider diagnostics may not.

- [ ] **Step 5: Run focused green**

Run:

```powershell
python -m pytest tests/test_settings_db.py tests/test_claude_model_truth.py tests/test_orchestrator_process_record.py tests/test_hybrid_router.py tests/test_cost_estimator.py tests/test_h10_24_cost_trace.py tests/test_resilience_integration.py -q
```

Expected: PASS; only the exact retired value migrates, custom bytes remain identical, current defaults are priced, and failures cannot improve learning/bench data or trigger a reviewer.

- [ ] **Step 6: Commit Task 5**

```powershell
git add agents/core/llm/model_config.py agents/core/llm/anthropic.py agents/core/plugins/cloud_llm.py agents/core/llm/providers/__init__.py agents/core/settings_db.py agents/core/llm/cost_estimator.py agents/core/orchestrator.py agents/_templates/SOUL.template.md agents/athena/SOUL.md agents/argus/SOUL.md agents/veronica/SOUL.md agents/vision/SOUL.md tests/test_settings_db.py tests/test_orchestrator_process_record.py tests/test_hybrid_router.py tests/test_cost_estimator.py tests/test_h10_24_cost_trace.py tests/test_resilience_integration.py tests/test_claude_model_truth.py
git commit -m "fix(llm): align Claude defaults and degraded results"
```

### Task 6: Make Autonomy Policy Metadata Server-Owned

**Files:**
- Modify: `agents/core/autonomy/policy.py`
- Modify: `agents/core/autonomy/worker.py`
- Modify: `agents/core/autonomy/queue.py`
- Modify: `agents/core/autonomy/observer.py`
- Modify: `agents/core/autonomy/watchers.py`
- Modify: `agents/core/scheduler_service.py`
- Modify: `tests/test_autonomy_worker.py`
- Modify: `tests/test_autonomy_queue.py`
- Modify: `tests/test_autonomy_observer.py`
- Modify: `tests/test_event_watchers.py`
- Modify: `tests/test_autonomy_endpoints.py`
- Modify: `tests/test_h30_house_actuation.py`
- Modify: `tests/test_r2_taint_propagation.py`
- Modify: `tests/test_h33_attention_integration.py`
- Create: `tests/test_autonomy_metadata_integrity.py`
- Create: `tests/test_scheduler_service_autonomy.py`

**Interfaces:**
- Consumes: existing `RiskTier`, `Decision`, `AutonomyPolicy`, `TaskQueue`, and top-level governed-producer `risk_tier` arguments.
- Produces: strict tier normalization, sanitized `_policy_view()`, a trusted keyword-only `risk_tier` tail parameter on `submit()`, and atomic `TaskQueue.update_payload_policy()`.

- [ ] **Step 1: Add malicious-payload and edit red tests**

Create `tests/test_autonomy_metadata_integrity.py` with these cases:

```python
@pytest.mark.parametrize("bad", [True, False, -1, 4, "0", object()])
async def test_invalid_trusted_tier_fails_closed_to_tier_three_and_ask(worker, bad):
    task = await worker.submit(
        agent="steve",
        kind="monitor.status",
        title="status",
        payload={},
        risk_tier=bad,
    )
    assert task.risk_tier == 3
    assert task.autonomy_level == "ask"


async def test_submit_payload_reserved_fields_cannot_shadow_identity_or_tier(worker):
    payload = {
        "kind": "monitor.status",
        "risk_tier": 0,
        "agent": "attacker",
        "origin": "generated",
        "target": "delete production data",
    }
    task = await worker.submit(
        agent="steve",
        kind="delete_database",
        title="delete",
        payload=payload,
        origin="inbound",
    )
    assert task.agent == "steve"
    assert task.kind == "delete_database"
    assert task.origin == "inbound"
    assert task.risk_tier == 3
    assert task.autonomy_level == "ask"
    assert task.payload == payload
```

Also add `test_submit_blank_kind_ignores_payload_name_and_fails_closed`, `test_submit_trusted_tier_three_recalculates_read_only_act_to_ask`, `test_submit_trusted_tier_zero_cannot_lower_delete_or_money`, `test_govern_enqueue_uses_strictest_policy_caller_taint_and_money_result`, and `test_edit_preserves_identity_and_escalates_durable_tier`.

Replace the unsafe edit expectation in `tests/test_autonomy_worker.py`; add queue atomicity, producer migration, malicious admin route, and House canonical-payload preservation cases in the listed adjacent files.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests/test_autonomy_metadata_integrity.py tests/test_autonomy_worker.py tests/test_autonomy_queue.py tests/test_autonomy_endpoints.py tests/test_h30_house_actuation.py -q
```

Expected: FAIL because payload fields currently shadow authoritative fields and edited payloads can lower the durable policy tier.

- [ ] **Step 3: Normalize the trusted floor and decide at the effective tier**

In `policy.py` add:

```python
def _normalize_tier_floor(
    value: RiskTier | int | None,
) -> tuple[RiskTier | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, bool):
        return RiskTier.IRREVERSIBLE_OR_MONEY, True
    if isinstance(value, RiskTier):
        return value, False
    if isinstance(value, int) and 0 <= value <= 3:
        return RiskTier(value), False
    return RiskTier.IRREVERSIBLE_OR_MONEY, True
```

Change `AutonomyPolicy.decide(self, action, *, tier_floor=None)`. Classify the sanitized action first, compute `effective_tier = max(classified_tier, normalized_floor)`, and then calculate mode, money cap, tier outcome, earned autonomy, and urgency from `effective_tier`. The invalid flag forces `ASK`. `_base_tier()` uses an explicitly present `kind` even when blank; it falls back to `name` only when the key is absent.

- [ ] **Step 4: Build a policy-only view and preserve the executor payload**

In `worker.py` add:

```python
RESERVED_PROPOSAL_FIELDS = frozenset(
    {"kind", "risk_tier", "agent", "origin", "autonomy_level", "attention_mode"}
)


def _policy_view(
    self,
    *,
    agent: str,
    kind: str,
    payload: dict | None,
    origin: str,
    autonomy_level: str | None,
    attention_mode: str,
) -> dict:
    view = {
        key: value
        for key, value in dict(payload or {}).items()
        if key not in RESERVED_PROPOSAL_FIELDS
    }
    view.update(
        {
            "agent": agent,
            "kind": kind,
            "origin": origin,
            "autonomy_level": autonomy_level,
            "attention_mode": attention_mode,
        }
    )
    return view
```

Keep the existing top-level `risk_tier` parameter on `govern_enqueue()` source-compatible and treat it as the trusted floor. Extend `submit()` only at the tail with `risk_tier: RiskTier | int | None = None`. Resolve origin, taint and retain the full execution payload, construct the view, call `decide(view, tier_floor=risk_tier)`, then apply the stricter caller/policy/taint result.

In `queue.py` add `update_payload_policy(task_id, payload, *, risk_tier, autonomy_level)`: perform one locked SQL update of only `payload`, `risk_tier`, `autonomy_level`, and `updated_at`; reload and return the task. Edit reclassification uses original agent/kind/origin/attention mode and original authoritative tier as a floor. If the new decision is `ASK`, keep the task blocked and re-present it.

- [ ] **Step 5: Move internal producer intent to the trusted argument**

For all three observer calls, both watcher calls, and `run_log_quick_scan`, `run_log_hourly_scan`, and `run_log_daily_scan`, remove `risk_tier` from payload and pass `RiskTier.READ_ONLY` or `RiskTier.IRREVERSIBLE_OR_MONEY` as the top-level argument. Leave `agents/core/routers/autonomy.py::autonomy_submit()` unchanged so HTTP payloads never gain the trusted seam. Preserve House's canonical payload tier for hashing/schema validation.

Update fake policy signatures in `tests/test_r2_taint_propagation.py` and `tests/test_h33_attention_integration.py` to accept keyword-only `tier_floor=None`.

- [ ] **Step 6: Run focused autonomy green**

Run:

```powershell
python -m pytest tests/test_autonomy_metadata_integrity.py tests/test_autonomy_worker.py tests/test_autonomy_queue.py tests/test_autonomy_observer.py tests/test_event_watchers.py tests/test_scheduler_service_autonomy.py tests/test_autonomy_endpoints.py tests/test_h30_house_actuation.py tests/test_r2_taint_propagation.py tests/test_h33_attention_integration.py -q
```

Expected: PASS; destructive/money actions cannot be lowered, House executor payload stays valid, and the admin route remains authenticated with no trusted tier argument.

- [ ] **Step 7: Commit Task 6**

```powershell
git add agents/core/autonomy/policy.py agents/core/autonomy/worker.py agents/core/autonomy/queue.py agents/core/autonomy/observer.py agents/core/autonomy/watchers.py agents/core/scheduler_service.py tests/test_autonomy_worker.py tests/test_autonomy_queue.py tests/test_autonomy_observer.py tests/test_event_watchers.py tests/test_autonomy_endpoints.py tests/test_h30_house_actuation.py tests/test_r2_taint_propagation.py tests/test_h33_attention_integration.py tests/test_autonomy_metadata_integrity.py tests/test_scheduler_service_autonomy.py
git commit -m "fix(autonomy): make proposal metadata server owned"
```

### Task 7: Unify Trusted-Proxy Identity and Preserve Rate-Limit State

**Files:**
- Create: `agents/core/http_identity.py`
- Create: `agents/core/rate_limit.py`
- Modify: `agents/web.py`
- Modify: `tests/test_rate_limit_hf2.py`
- Modify: `tests/test_admin_guard_hf7.py`
- Modify: `tests/test_user_guard_hf1.py`
- Modify: `tests/test_h2311_operability.py`
- Create: `tests/test_http_client_identity.py`

**Interfaces:**
- Consumes: Starlette request socket/header data, `env_flag`, `env_list`, and existing `_real_client_host`/`_client_ip` compatibility consumers.
- Produces: `ClientIdentity`, `resolve_client_identity()`, `BoundedSlidingWindowLimiter`, and one identity projection shared by auth and limiter.

- [ ] **Step 1: Add pure identity and bounded-limiter red tests**

Create `tests/test_http_client_identity.py` with `test_forwarding_ignored_without_trusted_peer_but_auth_fails_closed`, `test_trusted_peer_requires_flag_and_matching_ipv4_or_ipv6_cidr`, `test_xff_walks_right_to_left_to_first_untrusted_hop`, `test_x_real_ip_is_used_only_when_xff_is_absent`, `test_malformed_or_oversized_xff_is_rejected_as_one_unit`, `test_ipv4_mapped_ipv6_is_canonicalized_to_ipv4`, `test_forwarded_header_is_detected_but_never_parsed`, and `test_missing_socket_uses_shared_unknown_identity`.

Replace `test_client_ip_prefers_first_xff_hop` with an untrusted-XFF socket-key assertion. Add rotating-XFF 429, live-bucket retention across 4,097 identities, expired-bucket pruning, and exact 4,096-cap assertions to `tests/test_rate_limit_hf2.py`.

- [ ] **Step 2: Verify spoof/overflow tests fail**

Run:

```powershell
python -m pytest tests/test_http_client_identity.py tests/test_rate_limit_hf2.py tests/test_admin_guard_hf7.py tests/test_user_guard_hf1.py -q
```

Expected: FAIL because XFF is trusted unconditionally by the limiter, proxy trust has no peer CIDR validation, and reaching the identity cap clears all buckets.

- [ ] **Step 3: Implement the pure client identity resolver**

Create `http_identity.py` with:

```python
MAX_FORWARD_HEADER_BYTES = 8192
MAX_FORWARD_HOPS = 32
UNKNOWN_CLIENT_KEY = "<unknown>"


def canonical_ip(value: object) -> str | None:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(address)


def parse_trusted_proxy_cidrs(
    values: Sequence[str],
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    try:
        return tuple(ipaddress.ip_network(value.strip(), strict=False) for value in values)
    except ValueError:
        return ()


@dataclass(frozen=True, slots=True)
class ClientIdentity:
    socket_ip: str | None
    client_ip: str | None
    forwarding_present: bool
    forwarding_trusted: bool

    @property
    def auth_host(self) -> str | None:
        if self.forwarding_present:
            return self.client_ip if self.forwarding_trusted else None
        return self.socket_ip

    @property
    def rate_key(self) -> str:
        return self.client_ip or self.socket_ip or UNKNOWN_CLIENT_KEY

    @property
    def is_authoritative_loopback(self) -> bool:
        host = self.auth_host
        return bool(host and ipaddress.ip_address(host).is_loopback)
```

`resolve_client_identity()` canonicalizes the socket, trusts forwarding only when the flag is enabled and the socket belongs to one configured network, rejects a whole XFF over 8 KiB/32 hops/one malformed literal, walks right-to-left past trusted proxy networks, uses valid X-Real-IP only when XFF is absent, and detects but never parses RFC `Forwarded`. For untrusted forwarding, retain the socket only as `rate_key`; `auth_host` and loopback exemption remain false to preserve HF-7.

- [ ] **Step 4: Implement the bounded limiter**

Create `rate_limit.py`:

```python
class BoundedSlidingWindowLimiter:
    OVERFLOW_KEY = "<overflow>"

    def __init__(self, window_seconds: float = 60.0, max_buckets: int = 4096):
        if max_buckets < 2:
            raise ValueError("max_buckets must reserve a dedicated and overflow bucket")
        self.window_seconds = window_seconds
        self.max_buckets = max_buckets
        self._buckets: dict[str, deque[float]] = {}

    def hit(self, key: str, now: float, *, limit: int) -> bool:
        self._prune_expired(now)
        target = key or "<unknown>"
        if target not in self._buckets and len(self._buckets) >= self.max_buckets - 1:
            target = self.OVERFLOW_KEY
        bucket = self._buckets.setdefault(target, deque(maxlen=max(1, limit + 1)))
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(now)
        return limit > 0 and len(bucket) > limit

    def reset(self) -> None:
        self._buckets.clear()

    @property
    def bucket_count(self) -> int:
        return len(self._buckets)
```

`_prune_expired()` removes only empty/expired dedicated buckets and the expired overflow bucket; it never evicts a live bucket:

```python
def _prune_expired(self, now: float) -> None:
    cutoff = now - self.window_seconds
    expired = [
        key
        for key, bucket in self._buckets.items()
        if not bucket or bucket[-1] < cutoff
    ]
    for key in expired:
        self._buckets.pop(key, None)
```

- [ ] **Step 5: Wire one request identity into auth and middleware**

In `web.py`, parse `TRUSTED_PROXY_NETWORKS = parse_trusted_proxy_cidrs(env_list("JARVIS_TRUSTED_PROXY_CIDRS"))`, create one limiter, and add `_client_identity(request)`. Keep `_real_client_host`, `_client_ip`, and `_rate_limited` as wrappers so MCP/tests remain source-compatible. Local rate exemption uses `identity.is_authoritative_loopback`, not a string comparison against a spoofable key. Replace `_rate_hits.clear()` tests with `_rate_limiter.reset()`.

- [ ] **Step 6: Run focused and adjacent green**

Run:

```powershell
python -m pytest tests/test_http_client_identity.py tests/test_rate_limit_hf2.py tests/test_admin_guard_hf7.py tests/test_user_guard_hf1.py tests/test_h2311_operability.py::test_probes_exempt_from_rate_limit tests/test_mcp_route_tools.py -q
```

Expected: PASS; untrusted XFF rotation shares the socket bucket, only matching CIDR peers can forward identity, and overflow never resets an existing limit.

- [ ] **Step 7: Commit Task 7**

```powershell
git add agents/core/http_identity.py agents/core/rate_limit.py agents/web.py tests/test_rate_limit_hf2.py tests/test_admin_guard_hf7.py tests/test_user_guard_hf1.py tests/test_h2311_operability.py tests/test_http_client_identity.py
git commit -m "fix(web): harden proxy identity and rate limiting"
```

### Task 8: Fail Closed at Telegram Sender and Approval Boundaries

**Files:**
- Modify: `agents/core/channels/telegram.py`
- Modify: `agents/core/channels/gateway.py`
- Modify: `agents/core/autonomy_coordinator.py`
- Modify: `agents/web.py`
- Modify: `tests/test_autonomy_telegram_callback.py`
- Modify: `tests/test_h12_19_pairing.py`
- Modify: `tests/test_webhook_channels_h12_16.py`
- Create: `tests/test_telegram_security_posture.py`

**Interfaces:**
- Consumes: `SenderPairing`, `pairing_enabled()`, `Gateway.route()`, current live `autonomy.owner_chat_id`, and Telegram's existing callback shape.
- Produces: `parse_allowed_user_ids()`, `telegram_channel_from_env()`, `Gateway.configure_sender_policy()`, and two-factor callback authorization (`chat_id` plus static owner `user_id`).

- [ ] **Step 1: Add token-only, parser, pairing, callback, and log-sentinel red tests**

Create `tests/test_telegram_security_posture.py` with:

```python
@pytest.mark.parametrize(
    "raw",
    ["true", "false", "0", "-1", "1.5", "1,,2", str(2**63)],
)
def test_invalid_allowed_user_ids_fail_closed_without_client(monkeypatch, raw):
    constructed = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", raw)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: constructed.append(True))
    channel, reason = telegram_channel_from_env(handler=None)
    assert channel is None
    assert reason == "invalid_allowed_user_ids"
    assert constructed == []


def test_token_only_startup_is_disabled_without_network(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("JARVIS_CHANNEL_PAIRING", raising=False)
    channel, reason = telegram_channel_from_env(handler=None)
    assert channel is None
    assert reason == "missing_sender_posture"
```

Add valid trim/dedupe, allowlisted-owner bypass, pairing-only chat, combined posture, non-owner drop, global pairing-exception fail-closed for Telegram/email/webhook, callback wrong-user, callback wrong-chat, pairing-only callback denial, live owner-setting change, generic denial/no-task-leak, and bot-token log-sentinel cases.

- [ ] **Step 2: Verify Telegram posture tests fail**

Run:

```powershell
python -m pytest tests/test_telegram_security_posture.py tests/test_autonomy_telegram_callback.py tests/test_h12_19_pairing.py tests/test_webhook_channels_h12_16.py -q
```

Expected: FAIL because token-only startup constructs a client, an empty allowlist permits everyone, pairing exceptions allow routing, and callbacks lack current owner-chat enforcement.

- [ ] **Step 3: Parse startup posture before constructing any client**

In `telegram.py` add:

```python
MAX_TELEGRAM_USER_ID = 2**63 - 1


def parse_allowed_user_ids(raw: str) -> tuple[int, ...] | None:
    text = str(raw or "").strip()
    if not text:
        return ()
    values: list[int] = []
    for token in text.split(","):
        item = token.strip()
        if not item or not item.isascii() or not item.isdigit():
            return None
        value = int(item)
        if value <= 0 or value > MAX_TELEGRAM_USER_ID:
            return None
        if value not in values:
            values.append(value)
    return tuple(values)


def telegram_channel_from_env(handler=None) -> tuple["TelegramChannel | None", str]:
    token = env_str("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None, "missing_token"
    allowed = parse_allowed_user_ids(env_str("TELEGRAM_ALLOWED_USER_IDS", ""))
    if allowed is None:
        return None, "invalid_allowed_user_ids"
    if not allowed and not pairing_enabled():
        return None, "missing_sender_posture"
    return TelegramChannel(token=token, handler=handler, allowed_user_ids=list(allowed)), "enabled"
```

Use an immutable `frozenset` internally for `allowed_users`. Remove the message-loop prefilter: every sender reaches the gateway, which applies static owner/pairing policy. Callback handling remains stricter and always requires `uid in allowed_users`; otherwise answer `Not authorized` without invoking `on_callback`.

- [ ] **Step 4: Add explicit gateway sender policy and global fail-closed pairing**

In `Gateway.__init__`, add `_sender_policies`. Implement:

```python
def configure_sender_policy(
    self,
    channel: str,
    *,
    allowed_senders: Iterable[object],
    allow_pairing: bool,
) -> None:
    self._sender_policies[channel] = {
        "allowed": frozenset(str(value) for value in allowed_senders),
        "allow_pairing": bool(allow_pairing),
    }
```

At route time, a sender in the channel's static set bypasses pairing. A non-static Telegram sender is dropped when pairing is off or unavailable; when pairing is enabled, use `gate_inbound()`. For every sender-bearing channel, any `gate_inbound()` exception produces `allowed=False` and never invokes the handler. Log only channel and exception type.

- [ ] **Step 5: Validate the live owner chat and static owner user at callback time**

In `AutonomyCoordinator` add:

```python
def _owner_chat_id(self) -> str:
    return os.environ.get("AUTONOMY_OWNER_CHAT_ID", "").strip() or str(
        self._orch.get_setting("autonomy.owner_chat_id", "") or ""
    ).strip()


async def _on_callback(self, task_id: int, action: str, **kwargs):
    owner_chat = self._owner_chat_id()
    telegram = self._orch.channels.get("telegram")
    user_id = kwargs.get("user_id")
    chat_id = kwargs.get("chat_id")
    allowed_users = frozenset(getattr(telegram, "allowed_users", ()))
    if not owner_chat or str(chat_id) != owner_chat or user_id not in allowed_users:
        return None
    try:
        await self._orch.autonomy.apply_decision(
            task_id,
            action,
            decided_by="telegram",
        )
    except Exception as exc:
        logger.warning("Autonomy decision callback failed (type=%s)", type(exc).__name__)
        return None
    return f"Task #{task_id}: {action}"
```

`TelegramChannel._handle_callback()` acknowledges any `None` result as the same generic denial. It may acknowledge authorized success, but denial never includes task ID, existence, or state. Re-read the live setting on each callback.

- [ ] **Step 6: Remove token-bearing raw exception logs and wire secure startup**

Replace every Telegram log that interpolates an exception object with operation, exception class, and optional numeric status only. Do not log the exception traceback because Telegram request URLs embed the bot token.

In `web.py`, remove unconditional `gateway.register_channel("telegram")`. Call `telegram_channel_from_env()`, configure the gateway sender policy from the returned channel's static IDs and `pairing_enabled()`, then register/start the channel only on `enabled`. For invalid/token-only posture, emit one structured actionable warning and continue starting the rest of Jarvis.

- [ ] **Step 7: Run focused channel green**

Run:

```powershell
python -m pytest tests/test_telegram_security_posture.py tests/test_autonomy_telegram_callback.py tests/test_h12_19_pairing.py tests/test_webhook_channels_h12_16.py tests/test_shutdown_cleanup.py -q
```

Expected: PASS; token-only/invalid config makes zero Telegram client/network calls, allowed owners and paired chat behave as designed, and unauthorized callbacks cannot transition autonomy state.

- [ ] **Step 8: Commit Task 8**

```powershell
git add agents/core/channels/telegram.py agents/core/channels/gateway.py agents/core/autonomy_coordinator.py agents/web.py tests/test_autonomy_telegram_callback.py tests/test_h12_19_pairing.py tests/test_webhook_channels_h12_16.py tests/test_telegram_security_posture.py tests/test_shutdown_cleanup.py
git commit -m "fix(channels): fail closed for Telegram identity"
```

### Task 9: Make Approved Email Transport Constructible, Safe, and Observable

**Files:**
- Modify: `agents/core/env_config.py`
- Modify: `agents/core/channels/email.py`
- Modify: `agents/core/channels/manager.py`
- Modify: `agents/core/channel_reply.py`
- Modify: `agents/web.py`
- Modify: `tests/test_o26_p2_env_config.py`
- Modify: `tests/test_email_inbox_transport.py`
- Modify: `tests/test_safe_comms_channel_inbox.py`
- Modify: `tests/test_r3_b5_channel_send_contracts.py`
- Create: `tests/test_email_transport_correctness.py`

**Interfaces:**
- Consumes: `env_int`, `env_flag`, `ChannelReplyBroker.execute()`, `ChannelManager`, and the existing SMTP/IMAP adapter.
- Produces: bounded env parsing, `EmailChannel.from_env()`, `EmailChannel.poll_once()`, `EmailChannel.health_snapshot()`, and `ChannelManager.send_approved_reply()`.

- [ ] **Step 1: Add env, authorization, header, SMTP, and IMAP-health red tests**

Extend the env helper test with:

```python
def test_env_int_honors_minimum_and_maximum(monkeypatch):
    monkeypatch.setenv(VAR, "65536")
    assert env_int(VAR, 587, minimum=1, maximum=65535) == 587
    monkeypatch.setenv(VAR, "0")
    assert env_int(VAR, 587, minimum=1, maximum=65535) == 587
    monkeypatch.setenv(VAR, "2525")
    assert env_int(VAR, 587, minimum=1, maximum=65535) == 2525
```

Create `tests/test_email_transport_correctness.py` with `test_from_env_builds_exact_smtp_imap_dictionaries`, `test_invalid_ports_poll_interval_and_tls_fall_back_securely`, `test_missing_destination_makes_zero_smtp_calls`, `test_crlf_and_oversized_headers_make_zero_smtp_calls`, `test_invalid_destination_makes_zero_smtp_calls`, `test_smtp_refusal_returns_false_without_secret_or_body_logs`, `test_generic_channel_manager_send_cannot_send_email`, `test_approved_broker_reply_sends_through_real_manager`, `test_broker_reports_send_failed_not_deferred`, `test_poll_once_records_healthy_snapshot`, and `test_poll_once_records_secret_safe_degraded_snapshot`.

- [ ] **Step 2: Verify email startup and transport tests fail**

Run:

```powershell
python -m pytest tests/test_email_transport_correctness.py tests/test_email_inbox_transport.py tests/test_r3_b5_channel_send_contracts.py tests/test_o26_p2_env_config.py -q
```

Expected: FAIL because startup passes unsupported constructor keywords, the manager rejects all email dispatch, headers/destinations are unvalidated, and IMAP polling has no observable result.

- [ ] **Step 3: Add maximum-aware integer parsing and canonical email construction**

Change the shared helper without breaking existing callers:

```python
def env_int(
    name: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value
```

In `email.py`, add `EmailChannel.from_env(handler=None) -> EmailChannel | None`. Return `None` unless both hosts are present. Construct:

```python
smtp_config = {
    "host": env_str("SMTP_HOST", "").strip(),
    "port": env_int("SMTP_PORT", 587, minimum=1, maximum=65535),
    "user": env_str("SMTP_USER", ""),
    "password": env_str("SMTP_PASS", ""),
    "tls": env_flag("SMTP_TLS", True),
    "from": env_str("SMTP_FROM", "").strip()
    or env_str("SMTP_USER", "").strip()
    or "cabinet@localhost",
    "default_recipient": env_str("SMTP_DEFAULT_RECIPIENT", "").strip(),
}
imap_config = {
    "host": env_str("IMAP_HOST", "").strip(),
    "port": env_int("IMAP_PORT", 993, minimum=1, maximum=65535),
    "user": env_str("IMAP_USER", ""),
    "password": env_str("IMAP_PASS", ""),
    "poll_interval": env_int(
        "IMAP_POLL_SECONDS",
        60,
        minimum=5,
        maximum=3600,
    ),
}
```

Use this classmethod from `web.py`; do not rebuild dictionaries there.

- [ ] **Step 4: Validate headers and return explicit SMTP outcomes**

Add pure validation helpers using `email.utils.parseaddr`: reject CR/LF in From/To/Subject, empty/unparseable destination, addresses over 254 characters, and subject over 255 characters before MIME construction or SMTP connection. Preserve `default_recipient` fallback. Log a stable code, host, exception type, and optional SMTP numeric code only; never log password, recipient body, message body, or raw exception.

- [ ] **Step 5: Separate generic sends from approved email replies**

Add `email` to `_SUPPORTED_SEND_CHANNELS`, then centralize dispatch:

```python
async def send(self, channel: str, response, **kwargs) -> bool:
    return await self._dispatch(
        channel,
        response,
        approved_reply=False,
        kwargs=kwargs,
    )


async def send_approved_reply(self, channel: str, response, **kwargs) -> bool:
    return await self._dispatch(
        channel,
        response,
        approved_reply=True,
        kwargs=kwargs,
    )
```

`_dispatch()` evaluates the existing shape-only send contract. It returns `False` for `channel == "email"` unless `approved_reply` is true; then it calls the email adapter with `to`/`subject`. `Orchestrator.channel_handler()` continues using generic `send()` and therefore cannot auto-email.

Change `ChannelReplyBroker.execute()` to require `send_approved_reply()`. A missing manager method, exception, or false result returns exactly `{"status": "failed", "reason": "send_failed", "channel": channel}` and never records an outbound inbox message.

- [ ] **Step 6: Add observable IMAP polling health**

Initialize a secret-safe health dictionary. Implement:

```python
async def poll_once(self) -> bool:
    now = time.time()
    try:
        await self._check_imap()
    except Exception as exc:
        self._health.update(
            {
                "status": "degraded",
                "reason": "imap_poll_failed",
                "last_error_at": now,
            }
        )
        logger.warning("IMAP poll failed (type=%s)", type(exc).__name__)
        return False
    self._health.update(
        {
            "status": "healthy",
            "reason": "",
            "last_success_at": now,
        }
    )
    return True


def health_snapshot(self) -> dict:
    return dict(self._health)
```

The background loop calls `poll_once()` and continues after false. `stop()` cancels and awaits the poll task. Disabled IMAP reports `disabled`; IMAP failure is never represented as outbound `send=False`.

- [ ] **Step 7: Run focused and adjacent green**

Run:

```powershell
python -m pytest tests/test_email_transport_correctness.py tests/test_email_inbox_transport.py tests/test_safe_comms_channel_inbox.py tests/test_r3_b5_channel_send_contracts.py tests/test_o26_p2_env_config.py tests/test_cross_channel_sessions.py tests/test_h12_19_pairing.py -q
```

Expected: PASS; startup builds the real adapter, generic auto-email is denied, approved broker email sends through stubbed SMTP, failures are explicit, and IMAP health is observable without secrets.

- [ ] **Step 8: Commit Task 9**

```powershell
git add agents/core/env_config.py agents/core/channels/email.py agents/core/channels/manager.py agents/core/channel_reply.py agents/web.py tests/test_o26_p2_env_config.py tests/test_email_inbox_transport.py tests/test_safe_comms_channel_inbox.py tests/test_r3_b5_channel_send_contracts.py tests/test_email_transport_correctness.py
git commit -m "fix(channels): wire approved email transport"
```

### Task 10: Reconcile Product Truth, Run the Integrated Gate, and Publish One Draft PR

**Files:**
- Modify: `.env.example`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/MANUAL_TESTING.md`
- Modify: `mobile/PARITY.md`
- Modify: `BACKLOG.md`
- Generated: `STATUS.md`
- Generated: `project-status.json`
- Generated: `README.md`
- Generated: `JARVIS.md`
- Generated: `GO_LIVE_PLAN.md`

**Interfaces:**
- Consumes: all nine green component commits and live collected-test counts.
- Produces: exact configuration/backlog/parity truth, one full-suite evidence record, one pushed branch, and one draft PR.

- [ ] **Step 1: Update configuration and architecture truth**

Document these exact values in `.env.example` and `docs/ARCHITECTURE.md`:

```dotenv
# Forwarding headers are trusted only when both values are configured.
JARVIS_TRUSTED_PROXY=
JARVIS_TRUSTED_PROXY_CIDRS=

# Telegram requires at least one positive owner user ID or JARVIS_CHANNEL_PAIRING=1.
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
JARVIS_CHANNEL_PAIRING=

SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_TLS=true
SMTP_FROM=
SMTP_DEFAULT_RECIPIENT=
IMAP_HOST=
IMAP_PORT=993
IMAP_USER=
IMAP_PASS=
IMAP_POLL_SECONDS=60
```

Explain right-to-left XFF resolution, the HF-7 untrusted-proxy auth failure mode, token-only Telegram disablement, pairing-only users' inability to approve autonomy, approved-reply-only email send, and hermetic-versus-live validation boundaries. Add manual scenarios for rotating untrusted XFF, owner/wrong-user/wrong-chat Telegram callbacks, SMTP success/refusal, and IMAP healthy/degraded snapshots.

- [ ] **Step 2: Reconcile backlog and mobile parity without adding scope**

Add Lane B row `B8` for this single fresh-eyes security/correctness wave. Mark it complete only after the integrated gate is green. Update:

- `HF-7`: trust now requires both flag and matching CIDR; auth remains fail-closed behind untrusted forwarding.
- `H12.19`: pairing exceptions fail closed, Telegram static owners bypass chat pairing, and paired-only contacts cannot approve autonomy.
- `B5`: approved email replies are now constructible through the real manager against hermetic SMTP/IMAP doubles; owner live transport proof remains open, and WhatsApp remains parked.
- `mobile/PARITY.md`: approval/inbox endpoint parity remains green; stricter risk metadata and Telegram owner checks are server-side shared semantics, not a new native surface.

Do not add an active-sprint item, endpoint, HUD punch-list row, route snapshot change, or mobile implementation task.

- [ ] **Step 3: Run every focused component gate once more**

Run:

```powershell
python -m pytest tests/test_guardrails_generate_kwargs.py tests/test_route_preserving_guardrails.py tests/test_gemini_request_context.py tests/test_gemini_secret_safety.py tests/test_gemini_cache.py tests/test_orchestrator_gemini_cache.py tests/test_claude_model_truth.py tests/test_autonomy_metadata_integrity.py tests/test_http_client_identity.py tests/test_telegram_security_posture.py tests/test_email_transport_correctness.py -q
```

Expected: PASS. Record exact collected/passed/skipped counts.

- [ ] **Step 4: Run parity, lifecycle, and source-quality gates**

Run:

```powershell
python -m pytest tests/test_route_parity_guard.py tests/test_openapi_parity_guard.py tests/test_lifespan_smoke.py tests/test_hud_v2_parity.py tests/test_shutdown_cleanup.py -q
$pythonFiles = @(git diff --name-only origin/main...HEAD -- "*.py")
python -m ruff check @pythonFiles
python scripts/code_health.py
```

Expected: parity/lifecycle and touched-file Ruff checks PASS. `code_health.py` is advisory; record findings and fix only findings in files touched by this wave.

- [ ] **Step 5: Run the complete backend suite exactly once**

Run:

```powershell
python -m pytest tests/ -q
```

Expected: all collected backend tests PASS except repository-known skips. Record exact passed/skipped/warning counts; do not replace this with selective tests.

- [ ] **Step 6: Generate and verify status truth**

Run:

```powershell
python scripts/status_sync.py --reuse-js-counts
python scripts/status_sync.py --check --reuse-js-counts
python scripts/release_gate.py --skip-tests
git diff --check
```

Expected: status sync check and mechanical release gate PASS. Inspect generated diffs to ensure only counts/marker blocks changed, then mark `B8` complete with the exact local evidence.

- [ ] **Step 7: Commit documentation and generated status artifacts**

```powershell
git add .env.example docs/ARCHITECTURE.md docs/MANUAL_TESTING.md mobile/PARITY.md BACKLOG.md STATUS.md project-status.json README.md JARVIS.md GO_LIVE_PLAN.md
git commit -m "docs: reconcile security correctness wave"
```

- [ ] **Step 8: Refresh main once before publishing and rerun impacted checks if needed**

```powershell
git fetch origin
git rebase origin/main
```

Expected: clean rebase. If upstream changed any touched file, rerun that component's focused suite plus status sync/check before publishing.

- [ ] **Step 9: Verify final branch scope**

```powershell
git status --short --branch
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
```

Expected: clean worktree, exactly the bounded design/plan/component/docs commits, no unrelated file changes, and no whitespace errors.

- [ ] **Step 10: Push once and open one draft PR**

Use the `github:yeet` skill for the publish boundary. Push `codex/security-correctness-wave`, then open one draft PR titled `Security correctness wave: routing, policy, ingress, and channels` with:

- the verified defects and stale audit claims separated;
- component commit summary;
- exact local test counts and commands;
- explicit hermetic-only Telegram/email/cloud note;
- migration/secure-default compatibility notes;
- rollback-by-component instructions;
- the exact `Backlog: B8 ✅` status only when the backlog row is complete.

Expected: one draft PR targeting `main`; no intermediate PRs and no direct push to `main`.
