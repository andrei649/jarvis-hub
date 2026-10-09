# Standalone generated image digest binding

- Generated: 2026-10-09 UTC. Base/head before implementation: `e145aaa` on `codex/generated-artifact-digest-20261009`.
- Goal: newly published local ComfyUI and local OpenAI PNGs carry a strict optional expected digest sidecar; the shared generated-ID reader verifies the expected hash for both HTTP delivery and edit references.
- Scope: only `agents/core/media_backends/comfyui.py`, dedicated `tests/test_generated_artifact_digest.py`, and this plan. Shared `save_artifact` is used by both local providers. The sidecar is bound to the same already validated immutable bytes, with no destination reread.
- Design: exclusive per-ID reservation; refuse when either final path already exists, including dangling symlinks. Fsync each temporary file; exclusively publish the digest sidecar first, then run the existing authority guard immediately before exclusively linking the PNG. Best-effort directory sync uses the existing cross-platform helper. Before PNG publication, remove only this invocation's sidecar on failure; after PNG publication, retain the binding. The reader validates a bounded regular sidecar through a nonblocking, no-follow descriptor, exact JSON schema/version/canonical hash, and hashes its already bounded PNG bytes. Missing sidecar means legacy-unbound availability; malformed or mismatched sidecar refuses generically.
- Non-goals: no cloud publisher, catalog, route, auth, task queue, or approval-marker changes; no backfill of legacy IDs and no tamper-proof filesystem claim. Missing sidecars cannot distinguish legacy images from sidecar deletion.
- Tests: red/green matching HTTP/edit reads, same-size valid PNG tamper, malformed/oversized/FIFO/symlink sidecars, missing legacy sidecar, sidecar orphan, collision for either final path, and guard/failure cleanup. Focused image runtime and provider regression suites, Ruff, and diff check.
- Dependencies/limits: publication changes the shared local backend implementation fingerprint, so old uncompleted approvals can fail closed after reload. Directory entry sync is best effort on supported platforms, unlike authority-critical approval markers.
- Cross-publisher limit: the separate cloud publisher uses the same generated directory but does not participate in this local reservation. A forced same-ID collision can leave a mixed sidecar/cloud PNG if local cleanup is interrupted; its mismatched bytes refuse in the shared reader. Normal cleanup removes only the local sidecar and leaves the cloud PNG legacy-unbound. Only a sidecar with no PNG is inert; do not treat the reservation as universal across producers.
- Rollback: revert this source, test, and plan as one unit. Published sidecars may remain but legacy reader behavior returns if source is reverted; no provider replay is needed.
- Proof: red-first dedicated tests failed in 15 expected cases before implementation (missing sidecar, unchecked malformed/tampered sidecars, and local ID collisions). The final seven-file focused run in `/workspace/scratch/generated-artifact-digest-focused.xml` passed 295 tests with zero failures/errors/skips, including cloud generated-ID delivery, local provider/runtime, edit, and API flow regressions. The new tests also prove an authenticated tampered GET returns opaque 404 and edit refuses before transport, and that a failure after the PNG link (including an ambiguous link acknowledgment or failed identity inspection) retains both bound files. Ruff on the changed Python files and `git diff --check` passed. No full backend suite or live provider call was run in this worktree.
- Delivered details: new binding is validated again on every generated-ID read. The sidecar reader checks file identity before/open/after-open, bounds bytes, rejects symlinks, special files, duplicate JSON keys, bool version, unknown fields, noncanonical hashes, and hash mismatch. An absent sidecar remains legacy-unbound. A forced noncooperating publisher collision preserves its PNG; if local sidecar cleanup cannot complete, the mixed pair refuses by digest mismatch.

Coordinator verification (2026-10-09): the final source SHA-256 is
`ba9ccae42a0b88f9ff51f5caa2da64cbbd823e636ca350eecd16e32b3b83b654`.
The seven-file focused union passed 295 cases in 5.460 seconds; four disjoint
catalog/view/archive suites passed 157 in 6.235 seconds; the status/Hermes suites
passed 86. These are **538 distinct passing cases**, with zero failures/errors/skips.
Reports are `/workspace/scratch/generated-artifact-digest-{focused,integration,status}.xml`.
The independent gpt-6-sol/high reviewer also ran the new 26-case module and found no
Critical/Important issue; the builder used the same model/effort. A read-only
inventory used gpt-6-luna/medium. No physical device, live provider, full backend,
or frontend execution was added for this unit. The preceding combined full-backend
milestone remains recorded separately at source `c75e031`.

Full backend collection confirms 21,095 cases (+26); frontend 1,962, mobile 284,
and 554 routes are unchanged. Project-status and Hermes freshness gates, Ruff,
and diff checks pass. Only previously current ComfyUI evidence pins H477, H515,
H517, H518 and H598 were refreshed after scoped review. H312/H523 were already
stale and remain untouched; all assessment verdicts are preserved. H477 and the
mobile parity note describe the new local standalone binding and its remaining
legacy/cloud limits. Local commit is the delivery checkpoint; this unit was not
pushed into PR #1247 or deployed.

Combined milestone (2026-10-09), verified source `5c0985c`: full backend **21,069 passed, 37 skipped, zero failures/errors** out of 21,106 cases in 266.284 seconds. Exact-count and generated freshness gates pass. This later run covers both local and cloud standalone digest units; earlier notes keep their checkpoint scope. [Integrated proof](../project-generated-image-integrity-integration-20261009.md).
