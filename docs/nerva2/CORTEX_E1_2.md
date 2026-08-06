# Cortex E1.2a — owner-local measured primary-route contract

Program: #757 · Epic: #759 · Slice: #841 · Prerequisites: E1.0/#780 and
E1.1/#792 · E9 store/harness: #784

## State and boundary

The code contract is `contract_ready`. It is not representative evidence:
`owner_evidence_blocked` remains until the E1.2b owner gate is satisfied, and
`real_task_outcome_quality=not_measured` is fixed for this slice. E1 remains
`building`; B2 live enforcement remains partial; neither program completion nor
release readiness follows from this document.

E1.2a evaluates only whether the **current router's primary route** belongs to
the owner-declared acceptable primary routes for a retained task. The
primary-route adequacy metric is `accepted / (accepted + rejected)`. A rejected
observation is valid scored negative evidence; adequacy may remain measured
when other retained observations or measurements make the overall report
incomplete. It is not answer quality, task completion, safety, selector
superiority, a production route change, or an authority decision.

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
    build_measured_report,
    load_route_label_set,
    render_measured_report,
    run_measured_comparison,
)
from agents.core.observability.benchmark import BenchmarkStore

label_path = Path(r"D:\\Nerva-private\\e1-2\\route-labels.json")
store_root = Path(r"D:\\Nerva-private\\e9-store").resolve()
labels = load_route_label_set(label_path, allowed_routes=tuple(agents))
batch = asyncio.run(
    run_measured_comparison(
        router=router,
        agents=agents,
        label_set=labels,
        store_root=store_root,
        source_revision="<exact-lowercase-40-hex-commit>",
    )
)
report = build_measured_report(batch, BenchmarkStore(store_root), labels)
json_report_path = store_root / "e1-2-report.json"
markdown_report_path = store_root / "e1-2-report.md"
json_report_path.write_text(report.to_json(), encoding="utf-8")
markdown_report_path.write_text(render_measured_report(report), encoding="utf-8")
```

The store path must be an existing absolute, non-symlink directory. The run
performs one warm-up and then retains five retained runs. It first persists the
derived E9 suite and verifies each retained run can be read back exactly.

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

## What is and is not measured

| Dimension | State | Meaning |
|---|---|---|
| Primary-route adequacy | measured from scored evidence | `accepted / (accepted + rejected)`; rejected evidence is a valid scored negative. |
| Harness latency | measured, harness-only | It does not measure a shared production path. |
| Provider charge, compute, energy, hardware, downstream agent, tool, action | `not_measured` unless deterministic local evidence exists | No inferred resource claim. |
| Real task-outcome quality | `real_task_outcome_quality=not_measured` | No answer-quality, completion, or safety claim. |
| Authority | evaluation-only | Cannot change routing, authorize, execute, promote, or mark complete. |

`complete=false` is a separate honesty flag. It applies to error, unscored,
missing required measurement, or unavailable deterministic provider-charge
proof; it does not erase otherwise scored adequacy. A rejected observation is
valid scored negative evidence, and adequacy may remain measured even when the
report is incomplete.

## Report v1 output contract

`nerva.cortex.measured-comparison.v1` is a privacy-minimised aggregate report.
It records the label ID/fingerprint, suite name/version, exact source revision,
and fixed candidate/no baseline. It retains five ordered retained-run
fingerprints and task/repetition/sample counts.

The report carries the raw E9 environment-profile fingerprint separately from
the sanitised environment evidence fingerprint and platform/Python digests; it
does not expose raw platform or Python-version strings. It records
accepted/rejected/error/incomplete totals, scored adequacy, and sorted
per-actual-route aggregates.

Latency median and nearest-rank p95 are measured only from
`benchmark.harness`/`ms` observations. Provider charge is measured `$0` only
under the full local-deterministic/no-model/no-baseline/`candidate.runner`
USD-zero conjunction. The report leaves the following dimensions explicitly
`not_measured`: compute/energy/hardware/downstream-agent/tool/action/executed-task-outcome.

Authority is fixed `evaluation_only`, with all
routing/authorization/execution/promotion/completion booleans false. The
structural `from_json()` is not evidence acceptance: the rebinder must
match the exact batch/store/labels before a report is accepted as retained
evidence.

## Failure and completeness

The warm-up must complete every case or the run aborts before retained evidence
is produced. Each retained run is append-verified; duplicate run IDs, malformed
stores, missing/reordered evidence, unknown labels, cloud classifier use, or
mismatched decision evidence fail closed. A router exception remains a bounded
incomplete observation. Any error or unscored retained observation makes the
report incomplete; it cannot become a completion, release, or adequacy claim.

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

## Next state

After the owner supplies the five inputs and permits a local run, E1.2b may
collect representative evidence under this fixed contract. It must still report
the fixed limitations and separately earn any future E1, B2, program, or release
decision.
