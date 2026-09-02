# Cortex E1.2a — owner-local measured primary-route contract

Program: #757 · Epic: #759 · Slice: #841 · Prerequisites: E1.0/#780 and
E1.1/#792 · E9 store/harness: #784

## State and boundary

**IMPLEMENTED CONTRACT · MERGED — CONTRACT READY.** E1.2a (issue #841) is
merged onto `main` as PR #842, squash commit `769b633` (2026-08-07); the
durable E1.2a state is `contract_ready`. It is not representative evidence:
`owner_evidence_blocked` remains until the E1.2b owner gate is satisfied, and
`real_task_outcome_quality=not_measured` is fixed for this slice. E1 remains
`building`; B2 live enforcement remains partial; neither program completion nor
release readiness follows from this document.

E1.2a evaluates only whether the **current router's primary route** belongs to
the owner-declared acceptable primary routes for a retained task. The
primary-route adequacy metric is `accepted / (accepted + rejected)` over unique
tasks, after one consensus classification across the five retained observations
for each task. A rejected task is valid scored negative evidence. Route or
outcome disagreement is retained as nondeterministic, incomplete task evidence;
the five observations are never blended into an adequacy score. Stable scored
route evidence may remain measured when a latency, cost, or reliability
measurement makes the overall report incomplete. It is not answer quality, task
completion, safety, selector superiority, a production route change, or an
authority decision.

## External owner label schema

The external document is exactly `nerva.cortex.route-label-set.v1`. It must be
an owner-private, regular local JSON file with exactly these root, window, and
case fields; a valid document has at least 20 unique ordered cases. This
schema-shaped fragment uses synthetic values only:

```json
{
  "schema": "nerva.cortex.route-label-set.v1",
  "label_set_id": "synthetic-owner-history-2026-08",
  "sampling_rule": "synthetic-consecutive-distinct-eligible-tasks",
  "source_window": {
    "start": "2026-07-01T00:00:00.000Z",
    "end": "2026-07-31T23:59:59.000Z"
  },
  "owner_attested": true,
  "retention_policy_id": "owner-local-e1-2-v1",
  "cases": [
    {
      "case_id": "synthetic-task-001",
      "text": "synthetic weather request 001",
      "privacy_class": "owner_private_local",
      "acceptable_primary_routes": ["friday"],
      "task_category": "weather",
      "source_record_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
```

## Owner-attestation boundary

`owner_attested=true` is a typed declaration, not proof of consent or label
correctness. It does not satisfy the owner gate, authorize retention, or permit
an execution. The operator must separately supply the owner decisions listed in
`docs/OWNER_TASKS.md`; until then the evidence state remains
`owner_evidence_blocked`.

## Local invocation, with explicit paths

There is no committed E1.2a CLI. An owner-local operator who has deliberately
constructed the existing router and registered local agents can invoke the
existing Python API with explicit label and store paths, for example:

```python
import asyncio
from pathlib import Path

from agents.core.cortex_measured_compare import (
    bind_route_registry,
    build_measured_report,
    load_route_label_set,
    render_measured_report,
    run_measured_comparison,
)
from agents.core.observability.benchmark import BenchmarkStore

label_path = Path(r"D:\\Nerva-private\\e1-2\\route-labels.json")
store_root = Path(r"D:\\Nerva-private\\e9-store")
registry = bind_route_registry(agents)
labels = load_route_label_set(label_path, registry=registry)
batch = asyncio.run(
    run_measured_comparison(
        router=router,
        registry=registry,
        label_set=labels,
        store_root=store_root,
        source_revision="<exact-lowercase-40-hex-commit>",
    )
)
report = build_measured_report(
    batch,
    BenchmarkStore(store_root),
    labels,
    registry=registry,
)
json_report_path = store_root / "e1-2-report.json"
markdown_report_path = store_root / "e1-2-report.md"
json_report_path.write_text(report.to_json(), encoding="utf-8")
markdown_report_path.write_text(render_measured_report(report), encoding="utf-8")
```

The binding snapshots the exact sorted registered route IDs and route objects,
and the measured runner captures the deterministic router capability once,
before any owner-private prompt is evaluated. It then checks the source mapping
for key drift before and throughout labeling, execution, persistence, report
construction, and evidence validation. Its identity is in-memory only; the
route-registry fingerprint is persisted through the label, suite, run, batch,
and report evidence.

Pass the original store path to the API; do not pre-resolve it with
`Path.resolve()`, because doing so would erase the junction/symlink boundary the
validator must inspect. The store path must be an existing absolute,
non-symlink directory. Suite and run containers must be real directories;
suite-version and `runs.jsonl` paths must be regular files when present.
Link/reparse changes, type swaps, registry drift, and bounded filesystem errors
fail closed without exposing local paths in the exception or its traceback.
The run performs one warm-up and then retains five retained runs. It first
persists the derived E9 suite and verifies each retained run can be read back
exactly.

## Stored data and owner policy

The named `retention_policy_id` covers all five artifact classes below. The
label file and the E9 suite `vN.jsonl` contain raw prompts; they must not be
copied into a report or shared outside the owner-approved local boundary.

| Artifact class | Location/form | Data handling |
|---|---|---|
| Label file | explicit owner label path | Raw prompts and source digests; owner-private local only. |
| E9 suite | `suites/<suite>/vN.jsonl` | Raw prompts; same retention/access/deletion policy. |
| Retained runs | `suites/<suite>/runs.jsonl` | Per-run evidence; same retention/access/deletion policy. |
| JSON report | operator-chosen report path | Privacy-minimised aggregate; same retention/access/deletion policy. |
| Markdown report | operator-chosen report path | Privacy-minimised aggregate; same retention/access/deletion policy. |

Digests and fingerprints remain pseudonymous and linkable: repeated values can
correlate records, and guessable source inputs may be subject to dictionary
comparison. They are therefore not safe for unrestricted publication. The
policy must name who can access every artifact, how long it is retained, and
how each copy is deleted.

The fixed limitation `filesystem_confidentiality_caller_managed` is explicit:
`retention_policy_id is declarative`, and this slice does not enforce the named
policy. The operator remains responsible for configuring and verifying windows
dacl, posix owner/mode, encryption at rest, exclusive local-volume placement,
backup/sync/index exclusion, other-local-user exclusion, and secure deletion.

## What is and is not measured

| Dimension | State | Meaning |
|---|---|---|
| Primary-route adequacy | measured from scored task evidence | `accepted / (accepted + rejected)` after one all-five-observation consensus per unique task; rejected evidence is a valid scored negative. |
| Harness latency | measured, harness-only | It does not measure a shared production path. |
| Provider charge | conditionally measured `$0` | Only when every retained result has: baseline is `none`; candidate exists; model `none`; provider `local-deterministic`; cost is measured `0.0 usd`; source `candidate.runner`. |
| Compute, energy, hardware, downstream agent, tool, action, executed-task outcome | unconditionally `not_measured` | No resource or executed-outcome claim. |
| Real task-outcome quality | `real_task_outcome_quality=not_measured` | No answer-quality, completion, or safety claim. |
| Authority | evaluation-only | Cannot change routing, authorize, execute, promote, or mark complete. |

`complete=false` is a separate honesty flag. It applies when there is any
incomplete task, incomplete observation, missing required measurement, or
unavailable deterministic provider-charge proof; it does not erase otherwise
scored adequacy. A rejected task is valid scored negative evidence, and stable
task adequacy may remain measured even when the report is incomplete.

## Report v1 output contract

`nerva.cortex.measured-comparison.v1` is a privacy-minimised aggregate report.
It records the label ID/fingerprint, suite name/version, exact source revision,
fixed candidate/no baseline, and route-registry fingerprint. It retains five
ordered retained-run fingerprints and the explicit `unique_task_count`,
`observation_count`, `accepted_task_count`, `rejected_task_count`,
`incomplete_task_count`, `nondeterministic_task_count`,
`incomplete_observation_count`, and `error_observation_count` fields.

The report carries the raw E9 environment-profile fingerprint separately from
the sanitised environment evidence fingerprint and platform/Python digests; it
does not expose raw platform or Python-version strings. It records scored
adequacy and sorted per-actual-route aggregates whose counts are task counts,
not observation counts.

Latency median and nearest-rank p95 are measured only from
`benchmark.harness`/`ms` observations. Provider charge is measured `$0` only
under the full local-deterministic/no-model/no-baseline/`candidate.runner`
USD-zero conjunction. The report leaves the following dimensions explicitly
`not_measured`: compute/energy/hardware/downstream-agent/tool/action/executed-task-outcome.

Authority is fixed `evaluation_only`, with all
routing/authorization/execution/promotion/completion booleans false. The
structural `from_json()` is not evidence acceptance: the rebinder must
match the exact batch/store/labels and the same in-memory registry binding before
a report is accepted as retained evidence.

## Failure and completeness

The warm-up must complete every case or the run aborts before retained evidence
is produced. Each retained run is append-verified; duplicate run IDs, malformed
stores, missing/reordered evidence, unknown labels, cloud classifier use, or
mismatched decision evidence fail closed. Route-registry drift latches the
binding invalid for the remainder of the run, even if the source mapping is
later restored. A router exception remains a bounded incomplete observation.
Any error or unscored retained observation makes its task incomplete. Honest
route/outcome disagreement makes the task nondeterministic and incomplete;
scored task counts require all-five consensus. Scored adequacy remains visible
in an incomplete report, but it cannot establish completion, release, or
representativeness.

The accepted E9 store is owner-local and single-writer. Collision detection and
append verification do not establish concurrent-writer safety.

## Owner gate, authority, migration, and rollback

E1.2b is owner-blocked until all five inputs are explicitly provided: historical
task dataset, acceptable routes/categories, sampling/exclusion rule,
retention/access/deletion policy, and permission for the local run. Until then,
no representative real-task evidence exists.

This slice is migration-free: it adds no database migration, production route
selection, endpoint, scheduler, automatic run, retention executor, or authority
transfer. Ultron / `nerva.action.v1` remains the sole privileged-action
authority.

Rollback is migration-free rollback: revert the E1.2a code and tests together,
remove this operator contract and its manifest/workflow/ledger references, and
delete only owner-approved local artifacts under the named policy. No production
data migration or route-state reversal is required. Existing owner-local data
must not be deleted merely because the repository code is reverted.

## Owner decisions for E1.2b (2026-09-01)

Recorded 2026-09-01 (owner). Inputs 3, 4 and 5 of the five-input E1.2b gate are
decided below, exactly as approved; **inputs 1 (the owner-private historical task
dataset) and 2 (acceptable primary routes and task categories per case) remain
pending** and are written at the desk. The gate stays open, no run has executed,
and none of this earns E1, B2, program or release evidence.

- **Input 3 — sampling / exclusion rule and source window.** `sampling_rule` =
  `consecutive-distinct-eligible-tasks` over `source_window`
  `2026-08-01T00:00:00.000Z` .. `2026-08-31T23:59:59.000Z`, taken in timestamp
  order from the persisted conversation transcripts (role=user turns only);
  predeclared exclusions: non-task turns (greetings/acks/meta), duplicates of an
  already-selected task, and any turn the label-set loader cannot hold verbatim
  (containing `/` or `\`, control or line-separator characters) — excluded, not
  normalised. The label file's `sampling_rule` and `source_window` fields carry
  this at run time.
- **Input 4 — retention / access / deletion policy.** Policy id
  `owner-local-e1-2-v1` for all five artifact classes: access = the owner's own
  OS account on the owner box only (Windows owner-only DACL / POSIX 0700);
  storage = one git-ignored directory on a single local disk, excluded from
  backups; retention = until the owner deletes them, reviewed at the
  `audit_ttl_days` horizon; deletion = the operator securely deletes every copy;
  the "never copied, quoted or published" restriction applies to the raw-prompt
  artifacts (label file, E9 suite vN.jsonl) and to digests/fingerprints only —
  aggregate counts, adequacy ratios and privacy-minimised report text may be
  shared; the code records only the policy id and enforcement is the operator's.
- **Input 5 — permission for the owner-local measured run.** Exactly one
  owner-local E1.2b measured run is permitted — one warm-up plus five retained
  runs via the documented Python API against the current router on a pinned
  `main` commit, results persisted to the owner-local E9 store under policy
  `owner-local-e1-2-v1` — to be executed only after inputs 1–4 are present in
  the label file and the policy's filesystem controls are in place, on the
  understanding that the run is evaluation-only and its report earns no E1, B2,
  program or release decision by itself.

## Next state

After the owner supplies the five inputs and permits a local run, E1.2b may
collect representative evidence under this fixed contract. It must still report
the fixed limitations and separately earn any future E1, B2, program, or release
decision.
