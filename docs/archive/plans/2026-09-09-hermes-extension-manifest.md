# S1: declarative extensions and read-only inspection

Freshness: 2026-09-09; base/head before changes
`a5b8b496f319447f0233b1baf4a0f54cb8551c06`;
branch `codex/hermes-extension-manifest`; lease none. Main was clean; the only
open PR changed requirements-dev.txt. Next action: regression-first implementation,
focused/adjacent tests, then independent review; no push, install or service start.

Goal: a strict JSON authoring contract (manifest version 1, API version 1), bounded
descriptor doctor, and honest inspection of already-composed acquisition state.
Capabilities explicitly declare tools, commands and observation-only events.
Local tool names are exposed only as qualified `extension_id.tool` declarations.
Commands cannot replace the current core registry. Duplicate ids/names, unknown
capabilities/events, dependency cycles and registration mismatches are errors.
Dependencies use exact versions; Python distribution metadata is read without
importing candidate modules or installing anything. JSON is bounded and rejects
duplicate keys, unknown fields, paths/hooks and unsupported versions.

`nerva extensions doctor <descriptor...>` reads named local JSON descriptors;
`nerva extensions list` uses a new user-guarded plugin inspection GET. The GET
accepts no local paths and never initializes acquisition/promotion stores. Existing
signed acquired packages are projected from their existing manifest and verified
with their existing package store. No descriptor grants trust, registers a handler,
changes quarantine/approval state or proves isolated runtime availability. S1
reports callable tools/commands as empty and explicitly names missing SDK dispatch.

Paths: new `agents/core/extensions/{manifest,doctor}.py`, `agents/cli/nerva.py`,
`agents/core/routers/plugins.py`, tests and route snapshots, scoped BACKLOG/Hermes
and mobile/HUD parity notes. No coordinator/tool-profile or protected paths.

Non-goals: external execution/SDK context (S2), event delivery (S3), UI injection,
Git installation, raw-shell lifecycle hooks, package installation or live Docker
proof. Existing acquisition signing, receipts, promotion and revocation stay the
authority; this change does not modify those controls.

Tests: malformed manifests, namespace/core collisions, cycles/missing dependencies,
metadata-only checks, exact registration comparison, side-effect-free CLI,
disabled/tampered/revoked acquisition inspection, real route auth; existing CLI,
command catalogs, acquisition promotion/receipt/API and route/OpenAPI guards.
Rollback: remove descriptor/inspection surfaces as one PR; acquisition records and
the existing acquired runtime are unaffected.

## Stable implementation handoff

Generated 2026-09-09 12:56 UTC. Base and current pre-commit head remain
`a5b8b496f319447f0233b1baf4a0f54cb8551c06`; all S1 edits are uncommitted in this
worktree. Root owns the next action: generated global status, integration against
current main, commit and authorized PR delivery. Lease remains none.

Final changed surfaces: extension manifest/doctor, CLI, plugin inspection route;
`tests/test_extension_{manifest,doctor}.py`, CLI catalog/HUD parity expectations;
route/auth/OpenAPI snapshots, generated TypeScript schema and API sweep;
BACKLOG, architecture, Hermes, setup, plan and mobile/HUD parity notes.
No protected path, runtime activation, installation, service startup or remote
mutation was performed. No environment flags were added. The route uses the
canonical `require_component` helper and returns 503 when acquisition is absent.

Validation (main checkout Python 3.11.15):

- 48 focused manifest/doctor cases passed, independently repeated by `scope_review`.
- Final 202-test packet passed: `test_extension_manifest`, `test_extension_doctor`,
  `test_nerva_cli`, `test_nerva_send`, `test_commands_catalog`, `test_slash_commands`,
  `test_h32_promotion`, `test_h32_acquisition_api`, `test_plugin_runtime_honesty`,
  `test_require_component_sweep`, `test_route_parity_guard`, `test_route_auth_matrix`,
  `test_openapi_parity_guard`, `test_openapi_ts_typegen_gate`, `test_hud_v2_parity`.
- App lifespan smoke passed separately (1 test). Both runs reported one warning.
- Ruff, `git diff --check`, `scripts/gen_api_sweep.py --check` passed.
- OpenAPI TypeScript regenerated with cached pinned `openapi-typescript` 7.13.0;
  no frontend behavior changed and no browser/manual hub check was performed.

Regression evidence during recovery: unreadable descriptor was loaded twice and
could raise an unbound reason error; malformed list responses were accepted as
success; missing route composition returned a successful empty result. Seven new
cases reproduced those failures before fixes. Independent review identified an
additional CLI failure-status issue: unreadable/capacity inspector reports exited
0; two real-inspector regressions failed before the corrected failure exit. Review
rechecked the fix and found no further actionable issue. All callable sets remain
empty; approval, quarantine inspection, S2/S3 runtime and dedicated UI are not
claimed complete. Signature verification alone never sets approval verified.

Root integration: rebased the clean unit onto image-backend main
`8db71a9dbc257b0997c9b2d46d29ce2dc8f7593c`, preserving both delivery notes and
regenerating the combined API sweep. The roadmap caller-gap count now includes
the extension inspection view. On the combined tree, 116 focused CLI/extension,
route/auth/OpenAPI/typegen/HUD/document-reference checks passed; Ruff and diff
checks passed. Backend collection is 9,589, with 1,041 frontend and 137 mobile
counts retained; 478 routes. These inventory numbers are not suite pass counts.
Next action: publish this eligible unit and wait for all hosted checks before
merge; no deployment or external extension execution is part of this delivery.
