# ComfyUI reported execution-error evidence

- Generated: 2026-10-09 UTC.
- Goal: distinguish one documented ComfyUI history error report from incomplete,
  malformed or otherwise unknown image outcomes.
- Base / HEAD before edits: `c486cb245a279022155146b26e10673b259cecfd`.
- Branch/worktree: `codex/comfyui-response-evidence-20261009`,
  `/workspace/jarvis-hub-comfyui-response`.
- Scope: autonomous local development; no publication, live generator or device.
- Next action: failing producer/worker and strict projection tests, then the
  bounded implementation in separately owned files.

## Source-backed contract and limits

Official ComfyUI at commit
`1d2ea2948d33dfda4d7cfe58c6d234968aa62cf8` (2026-10-09 07:39:49 UTC) records
`status_str: "error", completed: false, messages: [...]` when its executor reports
failure. The worker passes this to task_done; the queue removes the running entry
and stores history under the prompt ID; GET /history/{id} returns that entry.
Source: [worker](https://github.com/Comfy-Org/ComfyUI/blob/1d2ea2948d33dfda4d7cfe58c6d234968aa62cf8/main.py#L380),
[queue](https://github.com/Comfy-Org/ComfyUI/blob/1d2ea2948d33dfda4d7cfe58c6d234968aa62cf8/execution.py#L1334),
[route](https://github.com/Comfy-Org/ComfyUI/blob/1d2ea2948d33dfda4d7cfe58c6d234968aa62cf8/server.py#L1125).
Root read the pinned queue/route and the research report. No upstream code was
executed. Deployed versions are not pinned by this app; changed shapes fall back
to uncertainty. Some upstream staged-node error paths do not set success false,
so this is a one-way recognition, not a complete classifier of all failures.

The accepted meaning is only a provider-reported execution error with no usable
image verified. It does not prove no work/partial output/charge or safe retry.
The existing web/native failed copy states this limited meaning and asks the
owner to check the task; it needs no new state, controls, preview or resubmission.

Do not classify bare generation_failed or invalid_output. Do not use arbitrary
error messages, current configured backend or a caller-controlled flag. Require
one accepted /prompt ID followed by a bounded history response whose plain top
dict has exactly that ID, plain entry, and plain status dict with exactly
status_str/completed/messages, literal error, completed is False, messages a list.
Do not require empty outputs: partial work/output may exist and is never fetched
by this error branch. Message contents stay unread and never cross the result.

The existing JSON parser accepts duplicate keys. To avoid minting evidence from
ambiguous/malformed JSON, the same bounded ComfyUI JSON decoder must reject
duplicate object keys and non-finite constants as invalid_response; valid wire
objects and binary responses retain their existing behavior. Use a local decoder
hook in comfyui.py, without new module/cyclic dependency or message inspection.
This affects invalid /prompt, /upload and /history JSON only; no retry is added.

## Fixed producer and projection interface

comfyui.py owns `_HISTORY_ERROR_REASON = "generation_failed"`,
`_HISTORY_ERROR_MARKER = "comfyui_history_error_v1"` and private
`_ComfyHistoryError(ImageGenerationError)` with a no-argument constructor fixing
its reason. Mint it only at the exact history branch above, before the existing
broad generation_failed check. Everything else keeps its prior generic reason.

LocalImageRuntime preserves the existing OpenAI response type/marker and adds a
second exact-type/fixed-reason case for this new type. Store the selected marker
in the existing nested `provider_response_failed` field only on failure; do not
infer it from strings/configuration. Manager, ToolRPC, queue and worker stay
unchanged. The fixed result is:

```json
{"status":"failed","reason":"generation_failed","tool":"image_generate",
 "result":{"ok":false,"reason":"generation_failed",
           "provider_response_failed":"comfyui_history_error_v1"}}
```

The local projector retains queue DONE, canonical tool.rpc payload identity,
exact plain outer/nested shapes, false ok and matching string reasons. It accepts
only either the prior OpenAI marker with its five reasons OR this ComfyUI marker
with generation_failed. Wrong protocol/reason pairs remain uncertain. Public
result remains task_id/failed/null only; admin/no-store/row-ID guards stay intact.
Cloud recovered ready and valid local ready retain precedence/behavior.

All malformed/duplicate/unknown histories, success/false, error/true or non-bool,
missing/wrong ID/status/messages, transport loss, timeout, /prompt ambiguity,
download/output/PNG defects, guard/withheld/machinery/publication failures remain
unmarked/uncertain. Existing source fingerprints invalidate prior pending
approvals; no authority, workflow, attempt or artifact mechanism changes.

## Ownership, verification and rollback

- auth_audit (gpt-6-sol/high): comfyui.py, image_generation_runtime.py and new
  tests/test_comfyui_history_outcome.py. Reuse existing direct backend and signed
  off/enforce composition fixtures without editing their shared files. Test RED
  before source changes, then typed history/strict JSON and real worker/public
  readback, one /prompt POST, no /view/PNG/catalog, replay refusal and exclusions.
- mobile_session_transport (gpt-6-sol/high): image_generation_view.py and
  tests/test_image_generation_view.py. RED/GREEN exact protocol-marker pairing,
  malformed/legacy exclusions and retained OpenAI/cloud/ready behavior. No client
  edits unless an actual copy incompatibility is demonstrated and scope coordinated.
- Root: integration/review, source citations, named evidence freshness, generated
  counts, BACKLOG/parity/HUD notes, proof and git. Optional luna/medium read-only
  pin inventory; max four active including root, no nested delegation.
- Reuse the just-completed green base backend milestone. After focused producer/
  projection checks, run provider/runtime/ComfyUI/edit/mediation/cloud/artifact/
  route union, Ruff and one full backend milestone. Compare skipped IDs, verify
  count, refresh only formerly current pins after bounded claim review. Preserve
  all already-stale pins, assessment verdicts and device/live acceptance limits.
  Clients/schema/bundle are unchanged and their prior evidence is retained.
- Rollback this typed history recognition, strict JSON decode, runtime marker,
  projector/tests and documentation as one local unit. No migration or authority
  change; stored marker-bearing rows return to uncertainty after rollback.
- H18.27 stays partial for physical-device/live-generator proof. Other ambiguous
  results intentionally stay uncertain; this does not promise universal failure
  classification or every ComfyUI version.

## Implementation and focused evidence

The fixed producer, exact-type runtime propagation and paired protocol projection
are implemented. Strict JSON also rejects float overflow (1e10000), which Python
otherwise parses to infinity; its added regression was separately RED. Root read
the pinned worker source directly in addition to queue/route evidence.

Producer RED had seven expected failures; projection RED had one in 96 cases.
Focused producer union 389/389 and independent projection 96/96 pass. Root's
broader 16-file union passes 574/574, zero errors/failures/skips. After review,
the 44 new history cases were strengthened to require the exact negative reason
and request path; short timeouts apply only to deliberate polling-timeout cases.
The corrected module passes 44/44; no production change followed the broad union.

Canonical collection finds 21,252 backend cases (+53), routes stay 555, and the
unchanged frontend/native/mobile inventories retain their preceding evidence.
Ruff passes all five changed Python files. Cross-review found no Critical/Important
issue. Named claim review supports 13 formerly current evidence-pin refreshes;
three already-stale pins and all claims/verdicts/remaining text stay unchanged.
Root AST review verifies unchanged shared artifact/workflow helpers, the seven
other runtime methods and public model declarations. The complete backend
milestone will follow the source checkpoint; results belong in the
[integration evidence](../project-comfyui-response-20261009.md).
