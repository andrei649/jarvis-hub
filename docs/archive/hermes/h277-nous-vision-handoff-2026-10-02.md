# H277 Nous vision: verified local checkpoint

Generated 2026-10-02T07:53:13.236186+00:00. Goal: full local Nerva/Hermes parity across
all 697 accepted capabilities; H277 remains partial. Base `54e5bf1b`, runtime
`43c669b0`, frozen full-suite head `cfd81423565846bca166fbc918bcb54b0f24eb00` on
`codex/h277-provider-discovery-20261002`. Pinned Hermes:
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. No push, merge, deployment, credential
copying or live/paid provider request. This handoff is a later documentation-only change.

## Delivered behavior

Explicit `JARVIS_ROLE_VISION_PROVIDER=nous` now connects an owned account to the
actual image composer. A pinned model bypasses metadata; otherwise the Portal's
tier-aware public catalog prepares the model. Welcome endpoints use `nous/welcome`.
Public catalog requests carry no account token; forced account-tier checks bind
their bearer to the account issuer. Public cache data is bounded and persistent;
private selection stays encrypted and binds account, endpoint, configuration and
credentials. Superseded preparations cannot replace the current selection.

GET status prepares usable credentials off-loop. Refresh catalog refreshes
metadata without forcing usable OAuth credentials to rotate. POST and role/policy
reads perform no credential refresh or replacement discovery. Logout, expiry,
credential and configuration changes invalidate prior approval. Loopback overrides
report actual locality while data policy remains unknown. Remote endpoints never
enable local-only describe, screen or Telegram consumers; Nous video stays unavailable.

Chat Completions is the default. Explicit native mode uses Messages for Anthropic
models, with bearer auth and the version header; auto stays on chat as pinned
Hermes does. Both modes bind the actual body/model/endpoint/auth/wire, bound response
bytes and total duration, and preserve the optional one-call empty recovery budget.
Typed text is preferred; typed thinking fallback matches Hermes' primary vision
consumer. Opaque redacted blocks are not answer text. Account management UI remains open.

## Verification and review

- Full backend: **21,049 passed, 34 skipped,
  1 expected failure**, 21,084 collected. All
  4,371 tracked regular files and HEAD stayed unchanged;
  clean before and after. The receipt records the exact command and file fingerprint.
- Focused H277/vision/composer: **1,705 passed**; 66 new backend cases
  across this increment. Combined status/docs/OpenAPI/route/HUD gates:
  **119 passed**. TypeScript, full Ruff and diff checks passed.
- Red-first integration reproduced incorrect role-branch placement, refresh forcing
  OAuth rotation, and loopback locality refusal. The initial broad focused run had
  1,694 passes and ten composer failures caused by passing a new kwarg to legacy
  test adapters; scoped constructor arguments restore legacy behavior, and the
  final union is green. No initial failed run is represented as successful.
- Two Sol High implementers supplied disjoint recommendation/resolver work, then
  documentation and a bounded read-only review. Root owned wire/consumer integration
  and fixes. A reasoning-fallback review finding was withdrawn after tracing the
  actual pinned vision consumer, not just the Anthropic transport.
- Strict scan: 77 cumulative indexed paths, zero findings before the full run.
  Graft source graph refreshed; semantic context remains unbuilt.
- Frontend runtime/schema did not change. Prior 1,859 frontend and six browser
  results are historical, not new live/UI acceptance. Provider transport was mocked;
  no live OAuth registration, inference acceptance or new mutation campaign is claimed.

Six previously current evidence rows were reviewed, including three identical
anchored citation moves. No promotions: **172 equivalent, 254 partial, 64 missing,
207 requiring review, zero excluded / 697**. H277's completed dependencies do not
establish full capability parity. [Verification receipt](evidence/h277-nous-vision-verification-2026-10-02.json).

## Next action

Implement the actual runtime-aware main → OpenRouter → Nous → DeepInfra vision
selection chain, preserving explicit role precedence and binding the selected route
before image dispatch. Composer currently has no selected conversation-agent/main
runtime: represent it as absent rather than deriving one from unrelated global keys.
Actual main selection comes from `HybridRouter.select_backend(agent_id, prompt)`.
The pinned vision path skips known text-only main models but permits unknown
capability; its aggregator fallback differs from the text main-unavailable refusal.
OpenRouter fallback must retain free-only configuration and dedicated vision model;
DeepInfra requires its served vision catalog; Nous uses its recommendation tier.
Use available adapter implementations, not generic compatible relabeling.

Remaining full-goal work includes runtime context, automatic routing, SDK recovery,
credential pools/anonymous lifecycle, signed video breadth, account UI and all
unfinished/review-required Hermes rows. Existing mutation receipts remain attached
to their original source revisions. Keep all work local.

Rollback this increment's runtime and generated records together, preserving the
independent Nous account lifecycle. No deployed process or external account changed.

## Changed paths

- `.env.example`
- `BACKLOG.md`
- `GO_LIVE_PLAN.md`
- `HERMES_STATUS.md`
- `NERVA.md`
- `README.md`
- `STATUS.md`
- `agents/core/llm/model_roles.py`
- `agents/core/llm/nous_auth.py`
- `agents/core/llm/nous_models.py`
- `agents/core/llm/providers/__init__.py`
- `agents/core/llm/vision_nous.py`
- `agents/core/llm/vision_nous_wire.py`
- `agents/core/llm/vision_policy.py`
- `agents/core/llm/vision_retry.py`
- `agents/core/llm/vlm.py`
- `agents/core/routers/composer_vision.py`
- `docs/FLAGS.md`
- `docs/HERMES_CAPABILITIES.md`
- `docs/design/HUD_V2_REMAINING.md`
- `docs/hermes/assessment.json`
- `docs/hermes/h277-nous-vision-plan-2026-10-02.md`
- `docs/nous-auth.md`
- `mobile/PARITY.md`
- `project-status.json`
- `tests/test_h277_nous_auth.py`
- `tests/test_h277_nous_models.py`
- `tests/test_h277_nous_vision_config.py`
- `tests/test_h277_nous_vision_consumer.py`
- `tests/test_h277_nous_vision_wire.py`
