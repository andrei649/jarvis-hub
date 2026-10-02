# H277 Nous accounts: verified local checkpoint

Generated 2026-10-02T07:16:22.238894+00:00. Goal: full local Nerva parity with pinned
Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`; H277 remains partial.
Base: `7a73bf03`. Runtime: `a5b0bdb3`. Frozen full-suite head: `18d031d561d2a41a186cf6c06d4a3d389e775c35`.
Branch: `codex/h277-provider-discovery-20261002`. Local only: no push, merge,
deployment, credential migration or live/paid provider calls. This handoff and
receipt are subsequent documentation-only changes.

## Delivered behavior

Nerva owns its Nous device-login and refresh lifecycle. CLI `auth nous login`,
`status` and `logout` use four owner-only API routes. Login prints the public code
and Portal link; private device codes, access and refresh tokens stay on the hub.
Status is local and does not create an absent store. Logout clears only the chosen
profile and pending flow. Actual CLI/API/service/encrypted-store integration is tested.

Dedicated encrypted SQLite state reuses SecretStore and serializes transactions;
refresh reads the newest state and adopts an already rotated usable peer token.
Tests prove cross-instance/thread serialization; a dedicated multi-process refresh
campaign was not run. Terminal OAuth rejection commits quarantine; transport/rate/edge
errors retain state. Successful refresh commits the replacement grant even if the JWT
is unusable. Missing replacement refresh token retains the old grant, matching pinned
Hermes; that remains a live provider-contract assumption.

Native HTTP checks the final request after client hooks, binds issuer/client/current
configuration, refuses redirects/proxies and bounds responses/deadline. Review fixes
cover encoded private device-code links, oversized JWT expiry, list-valued scopes,
unhashable OAuth error metadata and non-object JWT claims. Public responses sanitize
errors and never expose prepared inference credentials.

A registered public `JARVIS_NOUS_CLIENT_ID` is required. No working registration is
invented and Hermes's client identity/credential files are not reused. Live registration
and acceptance remain unverified. Signing in does not enable cloud or select a model.

## Verification

- Final full backend: **20,983 passed, 34 skipped,
  1 expected failure**, with 64 warnings; 21,018 collected. All 4,361
  tracked regular files and HEAD stayed unchanged; clean before and after.
- Focused integration: **266 passed, 3 skipped**, including **80 new auth tests**.
  Red-first root integration previously had 17 failures before API/CLI wiring;
  this review reproduced 8 malformed-error failures and 2 malformed-JWT failures
  before corrections. Provider transport is synthetic; no live inference proof.
- Initial full run had 20,981 passes and two failures: the OpenAPI snapshot omitted
  the four new routes and the HUD parity list omitted their unfinished UI. Fixed in
  `1267e809`; 51 targeted route/surface tests then passed before the final full run.
  The second full run passed 20,982 tests but caught the roadmap count still at 10
  instead of 14. Commit `18d031d5` corrects that count; all 143 combined documentation,
  route and surface gates passed before the final full run. The HUD gap is explicitly
  recorded, not classified as implemented.
- Documentation/status: 92 passed. TypeScript passed against regenerated OpenAPI.
  Frontend runtime is unchanged; previous 1,859 frontend/6 browser results were not
  rerun or counted as fresh acceptance for this CLI/API increment.
- Full Ruff, diff check and strict index secret scan passed; 66 cumulative paths,
  zero findings before final full run. Graft source graph fresh, no semantic index.
- Two Sol High implementers delivered disjoint credential-store/auth-service paths;
  root integrated API/CLI, reviewed, corrected defects and ran combined verification.

Twenty previously current Hermes rows were reviewed against the additive CLI/OAuth
changes, with 26 identical anchored citation moves. Inherited/stale rows were not
blindly restamped. Ledger remains **172 equivalent, 254 partial, 64 missing,
207 requiring review, 0 excluded out of 697**. No capability promotion is claimed.
The [receipt](evidence/h277-nous-auth-verification-2026-10-02.json) records all three full
runs and hashes of local artifacts. This is regression evidence, not a new mutation
campaign or proof of live provider acceptance.

## Next action and corrected upstream contract

Connect real Nous credentials to tier-aware recommendations and native inference,
then actual per-request main context and the main → OpenRouter → Nous → DeepInfra
selection order. Preserve explicit roles, local-only consumers and reviewed destination
consent. HUD/native account management, auth-pool/anonymous lifecycle, SDK recovery,
video breadth and the remaining 697-row scope are still open.

Inspection during the frozen run corrected an earlier planning shorthand: Anthropic
models do **not** always require Messages. In pinned `hermes_cli/providers.py`,
`nous_api_mode` uses `nous.anthropic_wire`: default `chat`, explicit `native` selects
Messages, and `auto` starts with chat. `agent/nous_wire.py` has
`GMI_NATIVE_WIRE_CLEARED = False`, so auto does not promote in this reference.
The comment on `_resolve_nous_branch` is older than the function it calls. Implement
the actual three-mode contract rather than forcing native for every Anthropic model.

`hermes_cli/models.py:301` detects known free tier with a 180-second profile cache;
`get_nous_recommended_aux_model` uses free-only or paid-then-free picks from the public
`/api/nous/recommended-models`, with a 600-second profile/Portal cache and stale disk
fallback. Welcome-host routes choose `nous/welcome`; normal fallback is
`google/gemini-3.6-flash`. `hermes_cli/nous_account.py` takes a usable JWT entitlement
snapshot first; forced freshness uses issuer-bound Bearer GET `/api/oauth/account`.
Do not replace these behaviors with a generic OpenAI-compatible alias and claim parity.

Rollback: revert this batch's runtime, parity-gate and records commits together.
No deployed process, existing credentials or external account was modified.

## Changed paths

- `.env.example`
- `BACKLOG.md`
- `GO_LIVE_PLAN.md`
- `HERMES_STATUS.md`
- `NERVA.md`
- `README.md`
- `STATUS.md`
- `agents/cli/nerva.py`
- `agents/cli/nous_auth.py`
- `agents/core/llm/nous_auth.py`
- `agents/core/llm/nous_credentials.py`
- `agents/core/routers/oauth.py`
- `docs/DEVELOPMENT_ROADMAP.md`
- `docs/FLAGS.md`
- `docs/HERMES_CAPABILITIES.md`
- `docs/design/HUD_V2_REMAINING.md`
- `docs/hermes/assessment.json`
- `docs/hermes/h277-nous-auth-plan-2026-10-02.md`
- `docs/nous-auth.md`
- `docs/test-manual/14-api-surface-sweep.md`
- `frontend/src/api/schema.gen.ts`
- `mobile/PARITY.md`
- `project-status.json`
- `tests/_snapshots/openapi_surface.json`
- `tests/_snapshots/route_auth.json`
- `tests/_snapshots/route_surface.json`
- `tests/test_h277_nous_auth.py`
- `tests/test_h277_nous_auth_surface.py`
- `tests/test_h277_nous_credentials.py`
- `tests/test_hud_v2_parity.py`
- `tests/test_nerva_cli.py`
