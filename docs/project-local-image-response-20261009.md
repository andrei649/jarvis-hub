# Local image provider-response evidence

- Generated: 2026-10-09 UTC.
- Goal: distinguish observed invalid local image responses from unknown outcomes.
- Base: `662cd4c3d522f6e508a5300aeee56fdf85d508e5`.
- Verified source: `b5fc19c55553923a2c463c84d5d5d916fcfa17a4`.
- Branch/worktree: `codex/local-image-response-evidence-20261009`,
  `/workspace/jarvis-hub-local-image-response`.
- Delivery: local; previously published draft PR #1247 is a separate unit.
- Plan: [contract, ownership, checks and rollback](plans/2026-10-09-local-image-response-evidence.md).

## Behavior and limits

The local OpenAI-compatible image adapter now raises a private typed error only
at reviewed negative response branches after its one fixed loopback POST yields
a response: nonredirect non-200 HTTP, invalid JSON headers/length/schema/base64,
oversize response, invalid decoded PNG or mismatched dimensions. It preserves
the five existing reason codes. The runtime retains the exact type through the
manager's generic failure wrapper and adds a fixed `local_openai_images_v1`
marker to that failed result. No response body, URL, prompt, path, exception
message or variable provider metadata is added to the marker.

Only a normally completed canonical `tool.rpc` image task with the exact plain
outer/nested result shapes, matching allowlisted reasons, false `ok` and the
fixed marker projects `failed` with null artifact. The admin response still
contains only task ID, state and artifact. The existing web/native finite reader
and cautious provider-response copy already handle this state without a preview,
automatic proposal or active-task polling. No client, public model/schema, route
or production bundle changes are needed.

Legacy/unmarked results and current ComfyUI failure reasons remain uncertain.
Redirect/encoding policy refusal, HTTPError/timeout, unknown submission, changed
authority/configuration, withheld generation, broken guards and publication
failures never acquire the producer marker. A guard using an allowlisted reason
string alone is insufficient. The existing validated local success and verified
cloud recovery paths retain their meaning. This is evidence within the queue's
trust domain, not proof against total database forgery, proof that no work or
charge occurred, or permission to retry.

Authority, durable attempts, source/configuration binding, physical transport,
catalog opt-in and artifact publication are unchanged. Source changes are already
part of the existing approval fingerprints: old approvals cannot authorize the
new implementation. Old results without this marker are not retroactively
reclassified. ComfyUI, video, other protocols and live-provider acceptance are
outside this unit; H18.27 stays partial.

## Regression and integration checks

Producer RED showed 15 failures on missing typed/durable response evidence;
projection RED showed five exact allowed responses still appearing uncertain.
The producer's final focused union passed **233/233** (four files), and the
projection module independently passed **87/87**. Root's broader provider,
runtime, ComfyUI, image/API/mediation, cloud, artifact-integrity and route/OpenAPI
union passed **474/474**, zero skips/failures/errors in 10.730 seconds.

Real signed intake, human acceptance, worker and durable queue fixtures with
mocked HTTP exercise six invalid response cases. They assert exact queue DONE
envelopes, admin `failed`/null/no-store/redaction, exactly one POST, no PNG or
catalog entry, direct replay refusal and no later dispatch. Timeout, redirect,
encoding, publication and an otherwise matching guard error stay unmarked and
publicly uncertain. Literal-envelope tests reject mismatched or unsupported
reasons, wrong markers, numeric `ok`, subclass dicts, extra fields, legacy task
kinds and queue FAILED. Existing source drift and approval/no-replay checks run
in the focused union.

Ruff passes on all six changed Python files. Canonical collection succeeds at
**21,199 backend cases** (+45), with 555 routes. Generated status retains the
unchanged client inventories: 2,009 frontend/native and 306 mobile cases. Their
complete suites, types, build and browser proofs passed in the immediately
preceding [image failure milestone](project-image-provider-failure-20261009.md);
this Python-only change does not rerun or relabel them as new executions.

The complete backend milestone at `b5fc19c` passes: **21,162 passed, 37 skipped,
zero failures/errors**, 21,199 total in 264.508 seconds, process exit zero. All 37
skipped test IDs match the preceding image failure milestone; no skip was added.
The executed JUnit count matches the canonical collection and tracked inventory.
The complete run also covers the metadata gates and earlier audit-order repair.
Command:

```sh
python /workspace/scratch/pytest-subreaper.py \
  /workspace/scratch/backend-copy-venv/bin/python -m pytest tests/ \
  -n 4 --dist loadfile --timeout=90 -q --tb=short \
  --junitxml=/workspace/scratch/local-image-response-backend-final.xml
```

No live provider or physical device was used. No push, merge, deployment or
activation occurred.

## Review and evidence freshness

Two gpt-6-sol/high writers owned disjoint files and cross-reviewed the frozen
six-file delta. No Critical/Important finding remains. A gpt-6-luna/medium
read-only inventory compared evidence hashes to the exact base. Named bounded
claim reviews cover H312/H515/H517/H518/H523/H598. Root refreshes only **11
previously current pins**; H312's already-stale runtime pin stays stale. Every
assessment summary, status and remaining-work string stays unchanged. No
affected literal file/line citation needs repair.

Root's AST comparison confirms only LocalImageRuntime.execute changes; its
seven other methods and nested authority guard are structurally identical to the
base. Public ImageTaskView/ImageArtifactView models are structurally identical.
The adapter subtype changes error classification only at response validation;
approval intake, attempts, physical guards and successful artifact flow retain
their existing checks. Gallery/readback/export and scheduled media are untouched.

Scratch reports: `local-image-response-producer-red.log`,
`local-image-response-producer-focused.xml`,
`local-image-response-projection-red.log`,
`local-image-response-projection-final.xml`,
`local-image-response-backend-focused.{xml,log}`,
`local-image-response-backend-final.{xml,log}`,
`local-image-response-status-sync.log`,
`local-image-response-pin-inventory.{json,md}`,
`local-image-response-view-collateral-review.md`,
`local-image-response-cross-review.md`, and
`local-image-response-producer-review.md` in `/workspace/scratch/`.
