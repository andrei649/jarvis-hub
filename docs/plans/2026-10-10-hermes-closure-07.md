# Hermes full-contract closure — batch 07

Generated 2026-10-10 UTC. Base/initial head:
`fbb0db40a25669ff03cee5bf8024e983d954f8f8` (148/697 complete).
Branch: `codex/hermes-closure-07-20261010`. Current action: implement the
settled contracts below. No additional count credit until complete review.
Goal: complete frozen H453 and H454 together through the scheduled-output path.
No publication/deployment/provider calls/personal state. No H620 broader scheduler,
new standing grants, dependency triggering, or workflow engine.

## Settled public interfaces

`options.context_from` accepts one string or a list of at most eight distinct
canonical lowercase 12-hex IDs, with case-insensitive `self` as a special entry.
Normalize case and shape into an ordered list. Reject malformed, duplicate,
over-count, nontext or path-like IDs before lookup. No filesystem output lookup.
At runtime, `self` and the destination's own ID use its own continuity block;
explicit continuity=false suppresses only that block, leaving external IDs.
Do not reject a valid external list merely because self-continuity is disabled.

The new additive PATCH field `context_from` is StrictStr/list[StrictStr]/None.
Absent or null means unchanged; [] clears only external references. The store's
edit merges context_from and optional continuity with the latest options in its
existing single immediate transaction, validating once. Replacement options plus
either non-null additive field is refused. CLI create/edit offer repeatable
`--context-from ID`; edit also offers mutually exclusive `--clear-context-from`.
Standalone flags emit additive PATCH without GET. Explicit --options remains a
replacement object and supplied flags are folded into that explicit object.
Doctor advertises the supported option; its behavior stays read-only.

## Complete output and publication

H453 currently clips raw stdout to MAX_TEXT=2000 before no-agent delivery and
before deciding whether script context is empty. Remove this silent loss. Require
trusted complete successful UTF-8 capture for literal no-agent output. Use the
native capture metadata and explicit 50,000-byte bound rather than guessing that
absence of a truncation notice proves completeness. Incomplete/malformed/invalid
capture must fail or explicitly remain incomplete, never silently succeed as a
complete delivery. Determine emptiness and the last-line wake gate from the full
approved observation. Preserve upstream redaction and all existing approvals.
An output with 2,000 whitespace characters followed by content is not empty.
Model context may be bounded with a visible host-authored truncation notice; it
must not claim an abbreviated observation is the complete stdout. Preserve byte
digest monitor baselines, persisted at detection before the model call.

Preserve the established composition: ordinary script jobs, including no-agent,
honor the final JSON wake gate. Script/URL monitors treat all observed content as
literal data and use their change/no-change gate; a JSON marker on a monitored
page does not suppress a detected change. `[SILENT]` remains a model-response
convention, so a no-agent script may deliver that literal string.

Add a small helper owning one latest substantive output per live job in jobs.db:
job_id, producer run ID, immutable job created_at, bounded content, recorded_at
and whether bounded. Write in the same transaction that terminalizes success;
delete with configuration, while H015 historical run metadata remains retained.
Never populate it from job_runs.summary (script summaries are intentionally
non-payload), incident errors, task receipts, unknown/failed/skipped/suppressed
attempts or approval-required control replies. Publication eligibility is distinct
from H015 run success. Use an explicit per-execution result/capture signal, never
shared runner mutable state or fragile heuristic prose matching. H002's scoped
source-assigned stop collector can distinguish an approval/control turn while
leaving its H015 successful-queued status intact. Keep the existing _ask return
interface compatible where practical. Both direct model and script model calls
share eligibility and formatting. Complete no-agent stdout can publish a bounded
latest copy independently of full delivery. Brief/reminder content may publish;
task-enqueued text is not substantive output.

Maximum stored content is 8,000 Unicode characters and 32 KiB UTF-8 per job.
External references are at most eight and share a 64 KiB injected-content budget.
No unbounded concatenation. Existing own Job.notepad behavior stays compatible;
do not fabricate cross-job output from legacy control summaries. A source with
no eligible latest-output row is missing and silently skipped.

## Prompt and delayed attempts

Resolve only live same-profile sources whose created_at matches the output row.
Missing/deleted/empty sources silently skip. Preserve order; host source labels
use the validated IDs. Source content is JSON-escaped and fenced untrusted data,
with no scanner relaxation or authority promotion. Own output gets host-authored
do-not-repeat/continue guidance outside its fence. External content gets a
separate preceding-job context heading/instruction. Existing KV bounds/fencing
remain. Distinguish limits/truncation with host text outside the content fence.

Script reservation snapshots bounded source content, IDs and source created_at
in the same transaction as its existing options/KV. The eventual model call uses
that snapshot, not newer output, but rechecks that source identity still exists;
deletion/replacement revokes injection. Missing at reservation stays missing for
that attempt. Direct asks resolve once just before generation. No automatic
execution of a source or dependency cycle scheduling is introduced.

## Ownership and evidence

Core implementer: repair_1247, jobs.py, new jobs_outputs.py helper, jobs_scripts.py,
jobs_health.py and new focused core tests. Existing script/monitor fixture updates
only when needed to model the real complete-capture contract and coordinated.
Surface implementer: review_1233, routers/jobs.py, cli/nerva.py and new focused API/CLI tests.
Root: plan, docs/parity, generated schema, critical integration/authority review,
whole-contract evidence and collateral reviews. One writer per file; max two
gpt-6-sol/high implementers, optional gpt-6-luna/medium read-only reviewer.

Red-first cases: complete stdout >2000 and leading whitespace, incomplete capture
never delivered as complete, wake/empty/no-agent zero-model rules, unchanged and
failed monitor baselines, real governed collecting script -> analysing model,
separate own/external context and false continuity, invalid IDs before lookup,
Unicode bounds, delimiter injection, delayed immutable snapshot plus deletion,
exactly-once publication and no publication on approval/silent/error/unknown,
profile isolation, atomic additive edits and CLI no GET replacement race.
Run focused tests, an offline actual-lifespan smoke, type/route checks, then one
serial frozen backend milestone before whole H453/H454 credit. Preserve stale
unrelated evidence and all remaining H451/H452/H620 gaps.

## Capture and publication interface refinement

Keep existing execution return tuples. Use an optional per-attempt candidate
callback through _execute/_ask; the callback never persists. A detailed model
result with error=None, a substantive non-SILENT reply and no source-assigned
stop can be a candidate after successful delivery/hold. A process-only adapter
keeps its old execution behavior but supplies no new publication proof. Preserve
H015 successful queued-approval status while withholding that control reply
from latest outputs. Direct/script terminal-success transactions alone publish.
Cancellation, failed finish, unknown, deletion and suppressed output never publish.

Own continuity prefers an eligible latest-output record. A distinct existing
`Job.notepad` remains a separately labelled unverified legacy note, preserving
owner edits after a result exists; without a result it is a truthful legacy
fallback. Neither its wording nor an empty stop list alone proves publication.
Do not filter fixed refusal prose heuristically. Freeze own output as well as
external sources for delayed attempts, including explicit absence. Internal
publication requires a matching successful run and the producer's originally
observed `created_at`; a replacement job cannot inherit an old attempt's output.
There is no production test-only publication shortcut.

OutputCapture hashes raw bytes before secret and Unicode projection. The safe
stdout may therefore differ from the digest without corruption. Validate the
complete/UTF-8/snapshot metadata and finite bounds, never manufacture capture
metadata in production or require a redacted projection to hash like raw bytes.
The shared validator permits at most 50,000 bytes, but the current local
transport's effective snapshot cap is 16,000 bytes. This batch preserves that
transport boundary: larger incomplete stdout must fail explicitly. SSH without
equivalent metadata is likewise incomplete. No new transport authority/options
or changed approved payload. Documentation must state both caps accurately.
A trusted explicitly complete larger fixture can exercise the shared bound,
but does not prove the local transport currently delivers that size.

Core owns necessary test_job_scripts.py capture-fixture repairs; coordinate any
additional existing test changes before editing. Read-only reviewer owns no
source. Root owns generated schema, docs/backlog, assessments and final gates.
Rollback is one local job-output feature unit with additive DB tables; retained
historical run metadata and existing owner data must remain readable.

## Focused verification before the milestone

Broad core coverage before the final budget correction passes 645 cases across
24 affected job modules. After that correction, the affected ten-module selection
passes 174 cases. Surface
coverage passes 131 API/CLI cases. Five real local subprocess pipeline tests
prove complete output beyond 2,000 characters, script-context invocation,
both ordinary wake-gate modes and explicit failure beyond the effective local
capture cap. Their terminal runner uses a test authorization shim; separate
existing queue/kernel tests cover signed mediation. Red runs against the unchanged
batch06 base reproduce silent output loss and false success on incomplete output.
These selections overlap and are not summed. Root route/auth/typegen checks pass
25 cases. Generated TypeScript adds only the strict nullable context field;
frontend typecheck passes, with no UI behavior or route addition.

The actual disposable CLI/FastAPI lifespan and real orchestrator smoke uses an
offline HTTP MockTransport backend. Two synthetic generation requests verify
producer output plus destination KV, own-continuity omission, source deletion,
atomic clear, admin gates and strict IDs. Both startup network probes are blocked;
temporary state is removed and source hashes are unchanged during the run.
No provider or personal state is used. Artifacts: `live-context-smoke.json`,
`core/final-focused.xml`, `surface/regressions.xml`, `surface/transport-final.xml`,
`root-routes.xml`, `frontend-typecheck.log`, under
`/workspace/scratch/hermes-697/batch07/`.

Critical review repairs are red-first: preserve legacy owner notes that happen
to be a proper prefix of a latest result; reject publication into a replacement
producer identity; and resume old saved attempts with explicitly absent new
snapshots. Capture fixtures distinguish actual incomplete stdout from a top-level
truncation flag caused by stderr alone. Existing execution fixtures accept the
new optional callback while retaining their original gate/cancellation assertions.
Final independent review also reproduced a rendered external-context block of
65,576 bytes against its 65,536-byte limit. Budget calculation and prompt assembly
now use the same exact renderer, covering host headings, bounded notices, JSON
escaping and fences. The regression measures the actual prompt bytes; red/green
proof and the post-correction selection are in `core/render-budget-red.xml`,
`core/render-budget-green.xml` and `core/render-final.xml`. Independent final delta
review is clean. The actual lifespan smoke was rerun against these final hashes.
Full frozen-backend evidence and whole-contract count updates remain pending.
