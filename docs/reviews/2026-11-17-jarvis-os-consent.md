# ANDREI OS post-merge repair evidence

Goal: address #1370 review findings r4595577240, r4595577246, r4595577250 and
r4595577257. Base: `3a482575ec9d3f59d6baa47d70cf4455d5f84572`.
Branch: `fix/jarvis-os-cloud-consent`. Generated 2026-11-17 UTC.

## Result

- Fresh standalone chat defaults to Ollama/offline vault synthesis. Legacy `auto`
  remains supported but becomes local-first. Cloud dispatch requires both the
  request's explicit boolean consent and current saved consent. Missing,
  malformed, unknown-provider and incomplete migrated settings fail locally.
- Every fallback is gated. Remote Ollama and custom OpenAI endpoints require
  consent. Local Ollama models need positive artifact metadata, refreshed per
  prompt; cloud aliases/unknown metadata cannot silently win the model fallback.
  Fully tagged `:local` requests prevent a local model becoming a cloud alias
  between inspection and dispatch. Older Ollama may reject the selector and fall
  back offline. Local transport bypasses inherited proxies and refuses redirects.
- Revocation is rechecked after blocking Ollama metadata/Claude auth probes,
  immediately before payload transport or the CLI prompt subprocess. Requests
  already dispatched cannot be recalled.
- Settings show the effective permitted engine, explain consent, fix the
  OpenRouter input ID, and preserve blank/masked saved keys. A failed save does
  not display success or refresh away the attempted revocation.
- `allowHardLinks` now loads/saves its documented JSON boolean. Default remains
  false; no live vault setting changed. Provenance-based vault/repo read policy
  and containment are unchanged.
- HUD V2/mobile have genuine gaps, recorded in their ledgers and BACKLOG H18.38.
  A separate `/os/` caller does not prove native parity. Hub `/os` uses `/chat`;
  this repair concerns standalone `/api/chat` and establishes no hub bypass.

## Verification

All provider tests intercept dispatch/transport or use temporary loopback doubles,
synthetic keys and synthetic notes. No real account or vault was used.

- PASS: baseline ANDREI OS router/vault/templates suite (94 tests).
- PASS: failing regressions observed before each behavioral repair, including
  default/migrated settings, revocation, cloud aliases, key masking/save failure.
- PASS: final focused integration, 300 tests (consent, actual Ollama transport,
  router, provenance/containment, templates, HUD parity, route/auth/OpenAPI,
  lifespan, documentation guards). Existing dependency deprecation warning.
- PASS: shipped settings JavaScript, 4 tests using actual HTML/methods in JSDOM.
- PASS: repository-wide Ruff, diff whitespace checks, self-development policy
  validation, Hermes 697 report consistency, generated status consistency.
- PASS: final privacy plus generated-status/release guard run on the corrected
  private temp root,210 tests. Existing network guard warning blocked an ambient
  non-loopback connection attempt; no provider transport was permitted by it.
- PASS: isolated Python 3.12 locked environment and synthetic install preflight,
  all ten checks including CLI, dependency versions and install smoke. Initial
  temporary-venv location/pip setup was corrected locally; no lockfile changed.
- PASS: full root HUD JavaScript suite (`npm test`), 250 tests, including the four
  shipped-settings tests. This is distinct from the untouched HUD V2 SPA suite.
- FAILED, BASELINED: initial full backend (`pytest tests/ -n 4 --dist loadfile
  --timeout=90`): 36,557 passed, 163 skipped, 208 failed, 141 errors. This broad
  snapshot preceded the final two late-revocation regressions/gates; focused300
  ran after those repairs. Do not describe the final branch's full suite as green.
- BASELINE CONFIRMED: reran all349 failing/error cases on unchanged base SHA:
  207 failed,141 errors,1 passed. The passing case was the browser orphan reaper;
  its initial failure is intermittent in this environment.
- ENVIRONMENT TRIAGED: sandbox `/tmp` is sticky but owned by UID65534; provider
  package/runtime guards correctly reject it (they permit UID0/current owner).
  Rerunning the349 cases on the repair with `TMPDIR` pointing to a private700
  directory under `/workspace` yields **347 passed,2 failed,0 errors**. No
  containment or owner checks were weakened, and global `/tmp` was untouched.
- REMAINING BASELINE FAILURES: `tests/test_g17_hooks.py::test_a_switch_off_mid_run_kills_the_hooks_process_group`
  and `tests/test_g17_hooks.py::test_the_timeout_kills_what_the_hook_started`
  both assert a child process remains alive. Both also failed on unchanged base;
  process supervision is outside this repair. Full backend was not rerun end to
  end with the corrected temp root; the failed-case rerun is a separate result.
- UNEXECUTED: real providers, Windows/macOS runtime, physical mobile devices,
  native HUD/mobile client acceptance, deployment and release gates.

Independent read-only reviewer found stale request consent, loopback Ollama cloud
aliases, failed-save success, and late probe revocation gaps. All received
synthetic regression coverage and repairs. Final narrow review confirmed both
late gates resolved and no remaining must-fix finding within the reviewed scope.

Focused command (JUnit recorded locally):

```sh
python -m pytest tests/test_jarvis_os_{consent,ollama_privacy,router,vault_fs,templates}.py tests/test_hud_v2_parity.py tests/test_route_auth_matrix.py tests/test_route_parity_guard.py tests/test_openapi_parity_guard.py tests/test_lifespan_smoke.py tests/test_doc_reference_integrity.py
npx vitest run tests/frontend/jarvis-os-settings.test.js
ruff check .
python scripts/development_preflight.py --smoke --json
```

## Changed paths

- Runtime/settings: `apps/jarvis-os/server.py`, `config.example.json`,
  `public/index.html`, `public/js/main.js`, `README.md`, `GEMINI.md` (all under
  `apps/jarvis-os/`).
- Regressions: `tests/test_jarvis_os_consent.py`,
  `tests/test_jarvis_os_ollama_privacy.py`, `tests/test_hud_v2_parity.py`,
  `tests/frontend/jarvis-os-settings.test.js`.
- Gap/delivery evidence: `BACKLOG.md`, `mobile/PARITY.md`,
  `docs/design/HUD_V2_REMAINING.md`, this report,
  `docs/superpowers/plans/2026-11-17-jarvis-os-consent.md`,
  `docs/handoff/antigravity-2026-11-14/CONTINUATION_LEDGER.md`.
- Generated counts/backlog mirrors: `project-status.json`, root `README.md`,
  `NERVA.md`, `STATUS.md`, `GO_LIVE_PLAN.md`. Frontend/mobile tracked counts are
  reused, not asserted as newly measured native/client acceptance.

## Publication and rollback

Publication: commit, push and draft PR only after focused checks and baseline triage. Keep draft;
no ready promotion, merge, deployment, workflow changes or service activation.
Rollback is a revert of the repair commit; no persistent data migration exists.
