# CLI receipt session attribution

- Generated: 2026-10-09 UTC.
- Base: 17712e196ec540c0ba8c75114e11b7692e61078d.
- Branch/worktree: codex/cli-receipt-session-attribution-20261009,
  /workspace/jarvis-hub-cli-receipt-session.
- Goal: distinguish requested session intent from the ID returned by the hub.
- Delivery: local; PR #1247 is the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-cli-receipt-session-attribution.md).
- [Public receipt contract and compatibility](cli-chat-receipts.md).

## Behavior and compatibility

POST /chat already returns the session the hub selected, including after /new.
The CLI used to ignore that field and echo --session in its receipt instead.
The receipt-local observed value now starts null and is populated only after a
decoded normal /chat response returns a string fully matching the intended ID
alphabet and length: ASCII letters, digits, underscore or hyphen, 1–128 chars.
The original value is preserved exactly; malformed, missing, nonstring or
whitespace-padded values are not trimmed, coerced or replaced by request intent.
A final newline is rejected by fullmatch. The shared core validator is unchanged.

New nerva.chat.usage.v1 receipts always contain requested_session_id with the
previous caller echo, including null when absent. Existing session_id now holds
only the valid observed value. This preserves request correlation while making
its distinction from response metadata explicit. Historical v1 receipts without
the additive key are not migrated or retrospectively treated as hub confirmation.
The public guide documents how consumers should read old and new files.

Valid session attribution is retained for answered, empty, refused and queued
chat responses independently of the existing completion verdict. No decoded
response means no observed ID: usage/authentication/HTTP/no-hub errors and
interruption keep null. Vision still uses its separate endpoint, cannot claim a
chat session even if its response carries a plausible field, and still refuses
--session before making a request. Interactive output/JSON, one-shot exits,
approval handling, request bodies and number of requests retain their behavior.
Nothing creates or resumes another session. All cost/usage values stay unavailable.

Only _usage_report and cmd_chat change. Root AST comparison verifies the other
77 top-level functions/classes and the rest of the CLI module are unchanged.
No HTTP model/schema, backend route, client UI, pricing, credentials or authority
change. H002 remains partial for independent outcome/usage and other CLI gaps.

## Verification

The writer's selected receipt regressions were **RED 21/21** before the production
change. Separately, the vision writer's two affected cases were **RED 2/2**.
The final six-file union passes **297 tests with one skipped**, 298 total, zero
failures/errors (5.420 seconds). This includes all **76 one-shot** and **31 vision**
cases, CLI commands, send/import and chat HTTP behavior. The existing HTTP case
checks the selected session returned after /new. The omitted live GitHub Hermes
import smoke remains gated by NERVA_HERMES_LIVE; no live test was enabled.

Root's disjoint three-file integration union passes **38/38**, zero skips/failures/
errors (2.157 seconds): image-retry CLI, pending-approval transport and the
thinking-exhaustion producer. Across the two unions there are **336 distinct
cases: 335 passed, one skipped**. The vision writer independently ran its 31 cases
successfully; that overlapping run is not added to the distinct count.

Ruff passes all three changed Python files. A site-packages-disabled Python -S
-m agents.cli.nerva --help exits 0; runpy emits the existing package/module-loaded
warning. Canonical collection records **21,300 backend cases** (+22), unchanged
frontend/native 2,009 and mobile 306 inventories, and 555 routes. Final Hermes,
generated-status and whitespace checks pass.
The prior full backend result at efac393a1219c8b87478fd694af7cd01334c9ae7 (21,237
passed, 37 skipped) remains earlier evidence, not a new full run for these CLI
changes. The focused suites cover the changed receipt paths and adjacent wire
contracts; unchanged backend/client suites are not repeated. No model, provider,
GPU or device was called.

## Review and freshness

Two gpt-6-sol/high agents owned separate source/test files; the vision writer
independently reviewed the frozen CLI and receipt contract. A gpt-6-luna/medium
inventory compared exact base pins. Root owns integration, documentation and git.
No nested delegation; no Critical/Important issue remains.

Named review supports **20 formerly current pin refreshes**: 18 CLI pins and the
H002/H586 test pins. The new public receipt guide is added as H002 evidence.
All **35 preexisting stale pins remain stale**, including the whole-file H002
CLI pin. H586's eight changed source coordinates point to identical lines after
insertion; root corrected the reviewer-suggested 2046 to the actual return line
2047. The other cited CLI coordinates precede the first insertion and do not move.

Only H002's receipt claim/remaining wording and test count, plus H586's test count
and coordinates, change. Every status and all other semantic claims remain
unchanged. The dated HERMES_SPRINT follow-up clarifies the earlier session-ID
limitation without rewriting historical test or mutation counts.

Tested SHA-256 values:
- agents/cli/nerva.py: 738919e6779d3d0fde4bbdd90447da1f27121f22a86a88e95f6e29b575ff1ef5
- tests/test_nerva_oneshot.py: 10bc16c0e5130c46f0427068ec217145a124e3adcfbed636b992f2d5b1b3cba6
- tests/test_nerva_chat_image.py: 454ea88eab29b39c562d06aa2a9045d517f405f554a7f4c9ab441038b75916f9

Scratch evidence: cli-receipt-session-{red,green,integration}.{xml,log},
cli-receipt-vision-{red,green}.log, cli-receipt-session-stdlib-help.log,
cli-receipt-session-status-sync.log, cli-receipt-session-pin-inventory.{json,md},
cli-receipt-session-{review,collateral-review}.md and
cli-receipt-session-ast-review.json.
