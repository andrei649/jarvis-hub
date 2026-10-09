# ComfyUI reported execution-error evidence

- Generated: 2026-10-09 UTC.
- Base: `c486cb245a279022155146b26e10673b259cecfd`.
- Branch/worktree: `codex/comfyui-response-evidence-20261009`,
  `/workspace/jarvis-hub-comfyui-response`.
- Goal: recognize one documented ComfyUI error report while keeping ambiguous
  history and unrelated failures uncertain.
- Delivery: local; draft PR #1247 is a separate previously published unit.
- [Fixed contract, ownership, tests and rollback](plans/2026-10-09-comfyui-response-evidence.md).

## Protocol evidence and behavior

Official ComfyUI commit `1d2ea2948d33dfda4d7cfe58c6d234968aa62cf8`, dated
2026-10-09 07:39:49 UTC, supplies the narrow contract. Its
[worker](https://github.com/Comfy-Org/ComfyUI/blob/1d2ea2948d33dfda4d7cfe58c6d234968aa62cf8/main.py#L385)
writes status `error` with literal `completed: false` when executor success is
false. The [queue](https://github.com/Comfy-Org/ComfyUI/blob/1d2ea2948d33dfda4d7cfe58c6d234968aa62cf8/execution.py#L1334)
stores the entry under its prompt ID after removing it from running work; the
[history route](https://github.com/Comfy-Org/ComfyUI/blob/1d2ea2948d33dfda4d7cfe58c6d234968aa62cf8/server.py#L1125)
returns that entry. Root read those pinned sources; none was executed. This is
a one-way inference: not every upstream error-message path sets success false.
Arbitrary message text cannot establish failure.

After an accepted prompt ID, the adapter now mints a private fixed-reason typed
error only for a bounded history body with exactly that top-level ID, plain
entry/status objects, exactly status_str/completed/messages, `error`, `False`
and a list of messages. Partial outputs are allowed in the history but are never
fetched by this branch. Message contents are not interpreted, logged or copied
into the task result. The existing broad `generation_failed` reason is preserved.

The runtime retains the exact type as fixed `comfyui_history_error_v1` evidence
in the existing failed result. Only canonical queue DONE image tasks with exact
plain result shapes, matching reasons and the correct protocol marker project
`failed`/null. The prior local OpenAI marker still accepts only its five reasons;
crossed marker/reason pairs are rejected. Cloud verified recovery and valid local
ready behavior stay unchanged. The public response and existing web/native copy
say only that no usable image was verified and the task should be checked before
another proposal. No new client, model/schema, route or bundle change is needed.

ComfyUI JSON decoding now rejects duplicate object keys, NaN/Infinity and float
overflow as generic `invalid_response`. It does not mint history evidence from
ambiguous wire objects. Finite valid JSON and binary responses retain their
behavior. Wrong/mixed IDs, malformed/incomplete/unknown status, wrong completed
type/value, invalid messages, output/PNG/download defects, timeout, transport,
withholding, guard and publication failures stay uncertain. A guard returning
`generation_failed` alone cannot create the marker.

The observed error report proves neither no work/partial output/charge nor safe
retry. Deployed ComfyUI versions are not pinned by this app; unrecognized shapes
fall back to uncertainty. Authority, approval fingerprints, attempts, workflows,
reference/edit/upscale, artifact publication and gallery behavior are unchanged.
Existing source fingerprints invalidate old pending approvals. No data migration
or retroactive classification of unmarked stored rows occurs. H18.27 remains
partial for device/live-generator acceptance; intentionally uncertain outcomes
are not promises of universal failure classification.

## Verification

Producer RED exposed seven missing typed/strict-JSON failures; a separate
overflow-number regression was also RED. Projection RED had one expected failure
in 96 cases. The producer focused union passed **389/389**, including 44 new
history cases; the projection independently passed **96/96**. Root's broader
16-file backend union passed **574/574**, no skips/failures/errors (12.137 seconds).

Root then tightened test fidelity: only deliberate polling-timeout cases use a
short timeout, and every signed negative case must reach its exact expected
reason and request path. This prevents an incidental timeout from satisfying a
guard or publication exclusion. All **44/44** corrected cases pass (1.826 seconds);
production code did not change after the broader union.

Real queue/worker fixtures exercise both off and enforce mediation, with mocked
ComfyUI HTTP. Exact error/interruption reports produce one prompt POST, no view
download/PNG/catalog, retained attempt, admin-only no-store/redacted failed
readback, direct replay refusal and no request on a later worker tick. Wrong or
mixed IDs, malformed/duplicate JSON, polling timeout, transport loss, an actual
post-view guard using the same reason, and publication failure remain unmarked
and publicly uncertain. Existing successful ComfyUI, edit/reference/upscale,
local OpenAI, cloud, artifact integrity and route/OpenAPI tests pass in the union.

Canonical collection succeeds at **21,252 backend cases** (+53), 555 routes.
Frontend/native 2,009 and mobile 306 inventories are unchanged; their preceding
complete passing evidence is retained, not relabeled as newly executed. Ruff
passes on all five changed Python files. The full backend milestone is pending.
No physical device, real model/GPU or live provider was used.

## Bounded review and freshness

Two gpt-6-sol/high writers owned separate files and cross-reviewed the frozen
delta; no Critical/Important issue remains. A gpt-6-luna/medium inventory compared
pins against the exact base. Named H312/H477/H515/H517/H518/H523/H598 reviews
support **13 previously current pin replacements**. Three already-stale pins
stay stale: H312 runtime/ComfyUI and H523 ComfyUI. All assessment summaries,
statuses and remaining-work strings are identical. An old September 27 handoff
line citation is historical evidence and is not rewritten as a current claim.

Root's AST comparison finds all 11 existing top-level ComfyUI helper functions
unchanged, including workflow, validation, digest/reader and publication. Only
ComfyUIBackend._request/generate and LocalImageRuntime.execute change; seven
other runtime methods and the public model ASTs are unchanged. The decoded
response branch adds evidence only after the request and does not authorize any
new action or publish partial output.

Reports in `/workspace/scratch/`: `comfyui-upstream-error-contract.md`,
`comfyui-upstream-{main,execution,server}.py` (pinned reads only),
`comfyui-history-producer-red.log`, `comfyui-history-nonfinite-red.log`,
`comfyui-response-projection-{red,green}.{xml,log}`,
`comfyui-history-producer-focused.xml`, `comfyui-history-producer-corrected.xml`,
`comfyui-response-backend-focused.{xml,log}`, `comfyui-response-status-sync.log`,
`comfyui-response-pin-inventory.{json,md}`, `comfyui-response-cross-review.md`,
and `comfyui-response-producer-review.md`.
