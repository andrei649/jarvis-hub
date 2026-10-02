# H277 next slice: acquisition auxiliary models design

Source inspected at the clean integration checkout after the four-producer increment: `docs/hermes/h277-auxiliary-expansion-map-2026-10-02.md`, `agents/core/acquisition/llm_synth.py`, `agents/core/llm/auxiliary_text.py`, `agents/core/llm/router.py`, `agents/core/llm/hybrid_router.py`, `agents/core/llm/job_selection.py`, the acquisition route, and the current H32/H513 tests. Approved by the standing owner-autonomous development directive; implementation is tracked separately and is not yet complete. Base a5b74939d4632c61e007ad64e4df937c44c47bc5.

## Current behavior that must survive

`generate_capability` and `draft_plan` each capture `router.local_backend` and `router.active_model or "local"` once per operation. A malformed JSON response gets at most one retry against that *same* backend/model, at temperature 0.0 after 0.2. Every attempt opens a fresh `auxiliary_request_scope` with its own role (`acquisition_capability` or `acquisition_draft`), so H513 preflight and physical-request checks remain fresh. Capability uses 2048 tokens and requires an object; draft uses 1024 and requires an array. Provider/policy/configuration failure is not a JSON retry. The downstream code and citation validators still decide whether a parsed result is usable.

The actual `LLMRouter.local_backend` accessor only returns `_backend` or raises when no local backend exists. It does **not** consult `current_selection`. `HybridRouter` inherits that accessor; job pins are applied by `job_selection.apply_selection` inside `HybridRouter.select_backend`, which these acquisition functions never call. Thus an active job pin is currently ignored by acquisition: it neither selects the pinned model nor blocks these strict-local calls. Recommend preserving that compatibility in this bounded routing slice, with an explicit regression test. Requiring exclusion would be a separate policy change; it must not arrive accidentally by reusing the four producers' helper unchecked.

## Minimal shared contract

Extend the immutable task table in `auxiliary_text.py` with two fixed entries:

| Task | Environment model override | Unset fallback | Job pin |
| --- | --- | --- | --- |
| `acquisition_capability` | `JARVIS_AUX_ACQUISITION_CAPABILITY_MODEL` | active model, else `"local"` | ignored, matching current behavior |
| `acquisition_draft` | `JARVIS_AUX_ACQUISITION_DRAFT_MODEL` | active model, else `"local"` | ignored, matching current behavior |

Use the existing override validator: read via `env_config.env_str` when the operation begins; allow a printable Unicode string of at most 256 raw characters, trim ASCII spaces only, and reject invalid types/controls/oversize with sanitized `AuxiliaryConfigError`. No provider, endpoint, key, discovery or cloud fallback configuration. The four existing tasks retain their job-pin exclusion and other behavior.

Add `prepare_local_auxiliary(router, task: str) -> Callable[..., Awaitable[str]]` (or an equivalent opaque operation handle). It validates the fixed task, applies its fixed pin policy, reads the override once, captures the chosen model and `router.local_backend` once, and returns an awaited generate call accepting `system`, `prompt`, `max_tokens`, and `temperature`. The returned call opens `auxiliary_request_scope(router, captured_backend, captured_model, role=task)` around **each** awaited generation. It never re-reads the override, active model, or backend for a retry. There is no API argument accepting a caller-supplied backend/model or a caller-selectable pin bypass. Keep `generate_local_auxiliary` as the one-shot wrapper over the same prepared operation for the existing four consumers; compression continues to use its streamed path inside one scope. Add `/no_think` only for title/rewrite, never acquisition.

In `llm_synth.py`, prepare once at the start of each producer, before its JSON loop. Invoke that prepared callable for both attempts, keeping the current prompts, JSON extraction, output-type checks, two-attempt bound, temperature progression, logging, and `SynthesisError` behavior. The existing route's early `local_backend` probe is only a fail-closed availability check; the producer's prepared operation owns the actual frozen backend/model. A fresh separate producer invocation may see a changed override/backend, which is intended.

## Exact owned files for the later implementation

- `agents/core/llm/auxiliary_text.py` — fixed table entries and operation-bound invocation seam.
- `agents/core/acquisition/llm_synth.py` — two producer adoptions only.
- New `tests/test_h277_acquisition_auxiliary.py` — behavioral, policy, and operation-freeze coverage.

The parent can own flag documentation in `.env.example` and `docs/FLAGS.md`. Reuse existing `tests/test_h32_llm_synth.py`, `tests/test_h513_acquisition_policy.py`, and governed acquisition/drive suites as regressions without editing them unless a concrete finding demands it.

## Meaningful test plan

1. Write red-first tests through both real producers: independent configured model IDs reach the backend, active model is unchanged, printable Unicode IDs work, unset/ASCII-space-only values use the exact `"local"` fallback, invalid values are sanitized and dispatch nothing, and a second operation sees a changed flag.
2. For each producer, return malformed JSON on attempt one, then mutate the environment, active model, and router's current local backend before attempt two. Assert both attempts used the originally captured backend/model, temperature changed from 0.2 to 0.0, and each attempt got a fresh H513 preflight. Then call the producer anew and assert it sees the new route.
3. Under `selection_scope` with a distinct pinned model/provider, exercise the real `LLMRouter`/`HybridRouter` accessor and both producers: acquisition still uses its strict-local configured model and does not touch cloud or the pin. Assert the four earlier tasks still refuse pins. A cloud-only router must fail before generation.
4. Use the actual `llm_async_client` physical request hook with `httpx.MockTransport`: revocation between attempts blocks the second send; revocation before a physical retry blocks it even if an adapter swallows the inner refusal. Assert no fallback to another provider and no JSON retry on H513 or configuration errors.
5. Retain H32 shape/sanitation and grounded-plan checks, token limits, fenced-JSON parsing, and the real drive's blocked/409 outcome on failure. Run the relevant H277/H513/H32 focused selection and scoped Ruff/diff checks; leave full-suite, live provider and publication evidence to the integration milestone.
