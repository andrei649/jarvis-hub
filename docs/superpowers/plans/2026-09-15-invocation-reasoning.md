# Invocation reasoning override

Goal: canonical `--reasoning` for one CLI/chat invocation without configuration writes.
Base: 16f229ceba3a9a6c2c0226942d0767a9967a79c4. Generated: 2026-09-15.
Head: this source unit. Next action: independent exact-source review.

## Contract and implementation

Frozen inventory `27-providers.md:1389` requires the eight canonical levels:
none, minimal, low, medium, high, xhigh, max, ultra. This increment covers reasoning
only, not model/provider override flags or H364's broader vendor coverage.

`nerva chat 'message' --reasoning low` sends optional `ChatRequest.reasoning`.
The HTTP field accepts the canonical eight strings or null. Missing/null uses the
existing backend's configured default; explicit `none` remains a requested ceiling.
The CLI keeps a local tuple with a runtime-ladder parity test so help/completion
remain stdlib-only. Neither the command nor the HTTP implementation writes settings.

`request_context.reasoning_scope` binds immutable effort plus a shared revocable
lifetime. Scope cleanup restores its parent and revokes explicit inherited overrides.
Top-level missing/null creates no revocable frame, preserving existing background behavior.
Nested null scopes retain any explicit ancestor lifetime while using the configured default.
An expired explicit ancestor cannot be discarded by entering a null scope.
`selected_reasoning(default)` resolves the value; `ensure_reasoning_active()` is
public for adapters that need an expiry check without introducing reasoning fields.
SSE binds inside its actual runner alongside the existing principal lifetime.

Compatible parameters, Gemini effort shaping, and Claude wire shaping consume the
scope without mutating shared backends. Claude auth retries and Gemini tool retries
check lifetime immediately before dispatch because those paths reuse a built payload.
Other paths shape immediately before dispatch and rebuild on retry. An already-issued
network request cannot be recalled by closing a scope; cancellation retains the existing
transport/runner behavior. Expiry prevents subsequent dispatch, not retroactive egress.

H679 is unchanged: declared empty suppresses controls, unknown models do not gain a
wire schema, and supported vocabularies clamp downward or refuse. Current compatible
vocabulary normalization excludes a disable rung: explicit `none` refuses those
nonempty profiles rather than silently using configured high. A supported Anthropic
model receives its existing disabled-thinking mapping. No provider/model selection,
authorization, credential, cache header, TTL, or dependency changes.

## Executed plan and evidence

- [x] Scope RED: 10 failures; lifetime, canonical validation, absent/default, nesting,
  and concurrent cases pass after implementation.
- [x] Actual provider RED: 12 failures; extended matrix now verifies 36 actual
  text/stream/tool paths across compatible/OpenRouter/Gemini/Anthropic and declared,
  empty, unknown vocabularies, with unchanged shared backend defaults.
- [x] CLI/HTTP RED: 12 failures; actual CLI→HTTP→provider and HTTP/SSE tests pass.
  Test assumptions about compatible `none` were corrected to the existing H679 refusal.
- [x] Auth retry expiry RED: two failures; neither adapter dispatches its second
  request after the explicit scope closes. SSE completion/disconnect and inherited
  children, concurrent HTTP requests, supported Anthropic disabling all pass.
- [x] Root review caught a CLI cold-start dependency regression. Actual Python `-S`
  help/chat-help/completion produced three RED failures; the local tuple/parity repair
  restores dependency-free startup.
- [x] Generated API types differ only by optional `ChatRequest.reasoning`; route and
  operation snapshots remain unchanged. Frontend, e2e, and dispatch-e2e TypeScript
  configurations pass using existing installed dependencies. No bundle change.
- [x] Final guarded focused run: **453 passed**, one pre-existing Starlette warning,
  in 14.36 seconds; **89 new tests** in the two invocation test modules.
- [x] Whole `ruff check .` and Bandit1.9.4 baseline over relative `agents scripts`
  pass. Scoped eight-file Graft wiring build/check is fresh, outside the repository;
  no secrets, dependencies, generated artifacts, deep/provider indexing or hooks.

Logs: `/tmp/nerva-invocation-{scope-red,wire-red,http-red,retry-red,stdlib-red}.log`,
`/tmp/nerva-invocation-final.xml`/`.log`, `/tmp/nerva-invocation-{ruff,bandit}.log`,
`/tmp/nerva-invocation-graft-{build,check}.log`. Tests used the isolated product
Python3.12 launcher, TMPDIR=/private/tmp, NERVA_PUBLIC_PROFILE=0, original pytest.ini
socket/timeout guards and fish PATH; no guard overrides or full backend run.

Scope: CLI/web, four LLM context/shaping modules, two focused test modules,
`frontend/src/api/schema.gen.ts`, this plan. No global assessment/status, assets,
protected paths or publication. Rollback is a source revert; no persisted state.

## Independent review repair

Reviewer found that a null scope entered while an explicit parent was still active
could drop ancestry, await parent completion, then send configured high through the
actual compatible adapter. One actual-adapter RED reproduced this. A null frame now
retains its parent's revocable lifetime; selected_reasoning still uses the default
for its null effort. Top-level null/absent remains unmanaged. Existing explicit
closed-after-entry and unmanaged default compatibility tests remain unchanged.

Repaired final verification: **454 guarded focused tests passed**, one pre-existing
Starlette warning, in13.99seconds; **90 new tests** total. Evidence:
`/tmp/nerva-invocation-null-red.log`, `/tmp/nerva-invocation-repaired.xml`/`.log`.
Whole Ruff/Bandit baseline pass again. Scoped Graft explicitly checked stale,
rebuilt, then passed freshness. Generated schema is unchanged from the earlier
three successful TypeScript checks.

## Independent review and integration

Independent review cleared repaired source332d0f1b984810c6510ff3fd63526a39586e33fb:
194 guarded cases pass, including the original actual-provider null-scope escape
counterexample. Evidence /tmp/nerva-invocation-review-final.log and .xml. Top-level
null remains frameless/default-compatible; nested null retains its explicit ancestor
lifetime and cannot dispatch after revocation. No live provider calls were used.

The two source commits were rebased onto actual clock main
86e5084f95e351145a19a832e2251e7103997964, producing source base
2c504203ef297c06d8f3d47adf31e17511f7e4b4. Assessment base and UTC timestamp identify
that source. Evidence hashes are refreshed only for rows whose ENTIRE prior evidence
matched that base; already-stale rows are retained verbatim. The manifest is
/tmp/nerva-invocation-evidence-refresh.json. H364 remains partial for named Grok and
Codex/Responses paths; neither lineage nor arbitrary vendor support is inferred.
Full-suite verification is owned by the integrator and will be recorded only from
its completed /tmp/nerva-invocation-full.log and .xml artifacts.

Final integrator full backend completed: **11,750 collected, 11,726 passed,
23 skipped, one expected failure, zero errors/failures**, 267.442 seconds. Evidence
/tmp/nerva-invocation-full.log and /tmp/nerva-invocation-full.xml. Product Python3.12,
existing pytest.ini/socket/timeout guards, TMPDIR=/private/tmp and
NERVA_PUBLIC_PROFILE=0 were retained through /tmp/nerva-run-isolated.py. PATH:
/tmp/nerva-fish-runtime/fish/4.9.3/bin:/Users/andrei649/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin.
Whole Ruff and Bandit1.9.4 baseline passed on the integrated source:
/tmp/nerva-invocation-integrated-ruff.log and /tmp/nerva-invocation-integrated-bandit.log.
Root independently reviewed the runtime delta and verified all 25 previously-stale
rows stayed identical to base.

Final metadata verification: 81 cases from test_hermes_sprint_status,
test_status_sync and test_release_gate, /tmp/nerva-invocation-metadata.log and .xml.
status_sync --verify-test-count backend --test-result /tmp/nerva-invocation-full.xml
confirms11750; generated status retains frontend1326/mobile140/routes501. Frontend
and native suites were not rerun for this source integration. Hermes totals remain
121 equivalent/327 partial/94 missing/107 excluded/48 needing review, with frozen
accepted scope590/excluded107. The concrete invocation gap is closed; H364 remains
partial and no real provider acceptance or billing verification is claimed.
