# H277 governed image empty retry — bounded source review

Review target: branch `codex/h277-image-empty-retry-20261002`, base `9313fe0c9b2d918579b0dda64f11fad59bedc9c2`. Review covers the image retry source, five governed native consumers, CLI/HUD disclosure, config/docs, tests, and whole-row evidence impact. Writer-frozen source hashes verified by reviewer below. Reviewer ran no tests or live calls; `git diff --check` passed on the frozen diff.

## Frozen file identities

- `agents/core/llm/vlm.py`: `f3bcbe79fa99bd6cd4802aa65f9ead88659d2af89e9572c70b6f54e1e39d5417`
- `agents/core/llm/vision_policy.py`: `f7b216249d5b0a021065b1280072631ec7ec4a1d23dd808ab3648c3049be417a`
- `agents/core/llm/vision_retry.py`: `247ba3433a4cafc7910e1d5e893a04632083b24fa983b9f0d514ced03c805407`
- `agents/core/llm/native_response.py`: `d6248f4322e5d878768f0669b8e3cd6c2723030081b7b9f1cd0b833778608c07`
- `agents/core/video_analysis.py`: `5ddd1f7acb380ee96235c6b6a264cea1851ac516f464af8f81f86c8cd91cb535`
- `tests/test_h277_image_empty_retry.py`: `45f1d055b207541eea53ff2ffdfab75d2f40795ba33bb6975de7a6422fc31b79`
- `agents/cli/nerva.py`: `aa5938dca9e070f5ef8e9f96db0307fc2baae6c14e09308ac3bee1888ae3bcf9`
- `tests/test_h277_image_retry_cli.py`: `8ed7bad2ffcd1fff11cf0263c8d07bf029847985dfdaad20f7b0b462eb7e57ef`
- `frontend/src/composer-images.tsx`: `076ca559006bd2cd773aa9afecfee8706cb685704df8d3daa47ee8ef441001d3`
- `frontend/src/gap.tsx`: `918ff92ac998852dc577a8e1369bc2f89136f6fa4d451a67d195051727a35a2e`
- Frontend tests (`composer-images`, `vlm-describe-panel`, `screen-reflex-panel`): `006d1971`, `6c5a6df0`, `edbbeb44` respectively.

## Runtime conclusion

No remaining concrete blocker found in the current source after the final request-hook repair. The prior WIP flaw was that a request hook inserted after the egress recorder could mutate the prepared image body after physical validation. The new `last_request_hook` in `agents/core/llm/vision_policy.py` checks that it is last in the hook list, rechecks policy/authorization and validates the exact body/marker immediately before transport. `tests/test_h277_image_empty_retry.py::test_late_request_hook_cannot_mutate_prepared_image_body` exercises the previously unsafe path and expects no transport send. This is present at the verified frozen writer hashes.

Enabled authority is bound to `VisionIdentity.binding` (`vision_policy.py`), so composer destination confirmation and unattended media/camera role grants stale when the budget changes. The retry context is installed only in `_native_request_scope`, binds the exact backend/model, and expires on scope exit (`vision_retry.py`). `generate_vision_checked` activates it only for image-bearing calls; ordinary text, unguarded direct backend use and fake adapters do not get a retry. Each attempt uses the prepared canonical JSON and one-send latch; the recorder check plus last hook run the existing H513 physical guard, transport, selection, destination, and authorization checks. Response streaming is capped at 512,000 bytes and both sends share one 180-second deadline; the first response context closes before the second. Only the extracted existing video predicate's structurally valid stopped empty 2xx result triggers attempt two. Malformed/error/oversized/exception/cancellation/thought-stripped blank responses cannot authorize a second send. The second blank returns to the existing consumer failure path. The original five producers each create or own a scoped backend and retain their cleanup checks: web composer, local describe, screen reflex, Telegram media, camera description.

CLI validates paired enabled metadata and prints a bounded notice before remote acknowledgment/send; HUD composer displays it before its checkbox, whose binding resets on changed budget. Local panels and role notes expose the fixed notice. Default-zero status/binding/result shapes remain unchanged. Documentation and parity text bound the claim to the implemented scope.

Limits: reviewer validation was static plus `git diff --check`; no test suite was run by reviewer. Writer reported 469 focused tests passing, including 40 new; parent reported CLI 117 and frontend 1,847 passing with typecheck, E2E TypeScript compilation and build; browser E2E execution was not run. Independent backend integration union remains parent-owned. The concurrent-scope test uses independent backend/client instances, as do governed production consumers. Overlapping scopes on the same injected client are not established as supported. The H277 partial row still needs truthful remaining-work wording for unimplemented adapters and broader normalization. No live provider acceptance is claimed.

## Assessment evidence impact at base

A base-object scan checked every evidence pin for each touched row, not merely the changed path. Across the actual 21 tracked diff paths (including seven deleted generated assets and `agents/web/v2/index.html`), 81 rows have touched evidence: 31 whole-row current at base and 50 already stale. Added untracked files, new generated asset names, and changed frontend tests add no additional row beyond these 81; no assessment row pins `agents/web/v2/` assets. The 50 inherited-stale rows must stay excluded from restamping; see `/tmp/nerva-image-empty-row-freshness-20261002.json` for IDs, hit paths and all base mismatches.

Direct claim review:
- `H277` (partial): `agents/core/video_analysis.py` only extracts its pre-existing valid-empty predicate into `agents/core/llm/native_response.py`, preserving old video behavior; the new image recovery supports one narrower H277 increment. `frontend/src/gap.tsx` adds local panel disclosure. Do not promote H277 or say full Hermes vision parity.
- `H513` (equivalent code contract): `agents/core/llm/vision_policy.py` and `vlm.py` change the active physical send and policy binding; composer/panel UI, config docs and three frontend test files also change. Update claim-specific citation/test union and verify guards, grants, cleanup and notices; preserve equivalent status only on validated code contract.
- `H586` (equivalent): `frontend/src/composer-images.tsx`, its test, `agents/core/llm/vlm.py`, and `agents/cli/nerva.py` add retry disclosure and same-body retry to existing web/terminal image composer. Existing composer source/transport/consent claims still hold.
- `H378` (equivalent, guard-adjacent): only the CLI image-turn block and local panel lines shift. `sg.evaluate` in `vision_policy.py::check` and the registry/selection-guard evidence are unchanged; relocate exact anchored citations if necessary without broad restamp.

The other 27 whole-row-current rows touch only unrelated regions of the large `agents/cli/nerva.py` or `frontend/src/gap.tsx` files. Their claim-specific symbols were not modified by this diff; retain statuses and relocate line citations only after text-anchor equality, using existing claim-specific tests as needed: `H004 H145 H156 H157 H165 H168 H227 H242 H259 H273 H329 H340 H350 H413 H441 H464 H465 H487 H515 H518 H595 H613 H660 H666 H667 H671 H687`.

Recommended focused union for substantive claims: `tests/test_h277_image_empty_retry.py`, `tests/test_h277_image_retry_cli.py`, `tests/test_h513_interactive_local_vision.py`, `tests/test_h513_unattended_media_reader.py`, `tests/test_h513_camera_policy.py`, `tests/test_composer_vision.py`, `tests/test_nerva_chat_image.py`, `tests/test_screen_reflex_route.py`, `tests/test_vlm_h13_1.py`, `tests/test_h277_video_empty_retry.py`, `tests/test_h277_video_retry.py`; frontend `composer-images`, `vlm-describe-panel`, `screen-reflex-panel`, `composer-vision-turn` tests, plus typecheck/build. Parent owns actual execution and any evidence restamp.
