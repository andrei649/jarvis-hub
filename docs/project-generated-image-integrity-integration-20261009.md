# Generated image integrity integration — 2026-10-09

- Goal: bind newly published local and cloud generated PNGs to their expected bytes
  at both raw download and edit-reference reads, preserving approvals and no replay.
- Verified source/head: `5c0985cf86ac7177a0d2276301557ceacb4c6d98` on
  `codex/cloud-generated-digest-20261009`.
- Base: the earlier full-backend milestone at `c75e031`, recorded by `e145aaa`.
- Integrated units: `7fe1f27` (local shared publisher/reader), then `5c0985c`
  (cloud adoption, storage/authority phase mapping and publisher source binding).
- Runtime paths changed since the earlier milestone:
  `agents/core/media_backends/comfyui.py` and `agents/core/cloud_image_runtime.py`.
- Generated: 2026-10-09 UTC. Next action: continue the remaining local backlog;
  these units are verified but do not complete H477 or the project.

## Result

Full backend: **21,069 passed, 37 skipped, zero failures/errors**, 21,106 cases,
266.284 seconds. The command used the isolated Python environment and existing
subreaper wrapper around `python -m pytest tests/ -n 4 --dist loadfile --timeout=90
-q --tb=short --junitxml=...`. Evidence:

- JUnit: `/workspace/scratch/generated-image-integrity-backend-final.xml`
- Log: `/workspace/scratch/generated-image-integrity-backend-final.log`
- Exact backend test-count gate: 21,106 matches the tracked inventory.
- Project-status and Hermes freshness gates, Ruff on the changed Python files,
  and `git diff --check`: pass.

The local unit had 538 distinct focused/integration/status passes and an
independent 26-case repeat. The cloud unit had 334 focused/integration passes
and an independent 11-case repeat. Both independent reviews found no
Critical/Important issue. Builders/reviewers used gpt-6-sol/high; narrowly scoped
read-only inventories used gpt-6-luna/medium. All new regressions were developed
red then green; no existing test assertions were weakened for these units.

Frontend/mobile runtime is unchanged from `c424e9a`; only `mobile/PARITY.md`
changed under those trees. This milestone does not rerun their suites. Their
recorded inventories remain frontend 1,962 and mobile 284; API routes remain 554.

## Delivered behavior and limits

The shared publisher reserves an ID and refuses existing PNG or metadata names,
fsyncs private files, links the strict digest sidecar first, rechecks authority,
and exclusively links the PNG. It cleans only its own prepublication binding;
a confirmed or uncertain successful PNG link retains the binding. All built-in
local and cloud publishers now cooperate through that same reservation. The
reader validates bounded regular metadata and compares its expected digest with
the exact PNG bytes it returns. Malformed metadata or a mismatch is an opaque
refusal for both downloads and edit references.

Cloud task completion retains its own SHA check on recovery, independently of
the sidecar. No provider request is replayed. Storage failures, post-generation
governance refusals and machinery failures retain their distinct existing
outcomes. The cloud configuration binds the imported shared implementation and
refuses disk drift; old pending proposals can fail closed after a source change.

Sidecar-free legacy IDs remain structurally validated but unbound on raw reads;
no migration hashes current bytes and labels them verified. Deleting metadata is
indistinguishable from legacy, so this is not tamper-proof storage against an
actor controlling the data directory. Existing path-race limits remain, and
directory-entry sync is best effort across platforms. Live/paid providers,
physical devices, broader artifact types and the remaining H477 contracts are
not certified by these offline tests.

No push, PR update, merge or deployment was performed. PR #1247 remains the
separate draft at `da7c8a2`, reconfirmed OPEN/CLEAN during this milestone. Revert
each implementation commit with its evidence as its own rollback unit; existing
sidecars require no provider replay or data migration.
