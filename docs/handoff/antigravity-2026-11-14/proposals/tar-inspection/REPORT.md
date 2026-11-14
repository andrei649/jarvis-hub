# Recovered tar inspection — independent V51 review

Date: 2026-11-13. Scope: isolated candidate only; no native edits or caller adoption. Native `agents/core/archive_safe.py` equals HEAD 686fcbf4f25ebfbb416b3a35dff29045163cffbd and has SHA256 b503bbf9df1dcdf0894ba8113b1d51a1f6ad31cda261c723f42bd7c4f60d36ac. It was not modified by V49/V50. HTML-escaped comparisons from the inline handoff were decoded into ordinary Python. The recovered implementation is preserved under `agents/core/archive_safe.py`; no archive member code was executed.

## Result

The supplied 22 tests pass. With 90 existing archive tests plus 6 independent adversarial cases, the recovered candidate passes 118 test cases. However, independent memory review found **another metadata amplification**, so the recovered patch should not be treated as fully reviewed for bounded memory without the additional fix below.

`tarfile` retains every `TarInfo` in `tar.members`; each normal member inherits a separate copy of the global PAX dictionary. The supplied name/depth/component limits do not count those copies. A small offline probe with 2,000 global PAX keys and zero-byte files measured:

| Files | Tar size | Original peak allocations | Cache-clearing variant |
|---|---:|---:|---:|
| 50 | 71,680 bytes | 4,002,620 bytes | 1,437,156 bytes |
| 500 | 296,960 bytes | 27,694,349 bytes | 1,602,501 bytes |

These are `tracemalloc` peak Python allocations for the specific fixture, not RSS or estimates of service consumption. Archive/member payload limits and supplied name limits all accept these fixtures. The probe avoids large-memory tests.

## Isolated proposed correction

After storing each member's result, clear `tar.members`. Inspection reads direct `TarInfo` objects, refuses links and never seeks previous members by name; retaining previous header objects is unnecessary. The shared guarded parser, payload hashing, trailer drain and metadata result remain unchanged. This prevents multiplication of inherited global PAX dictionaries across prior members. Existing header-payload caps (1 MiB each /256 MiB aggregate) still apply and are not tightened here.

`tests/test_archive_inspection_pax_cache.py` fails against the supplied candidate: retained-header count reaches50. It passes against the cache-clearing variant. The final combined suite passes **119 actual test cases, 0 failures/errors/skips**, 10.088s; XML `/tmp/nerva-v51-archive-pax-final.xml`. Candidate source Ruff passes. `git apply --no-index --check` of `bounded-inspection-combined.patch` against an isolated native-file copy passes.

Files:
- `archive-inspection.patch`: recovered implementation only against current native source.
- `pax-cache-fix.patch`: the additional three-line correction against the recovered implementation.
- `bounded-inspection-combined.patch`: both changes against native source.
- `bounded-cache/agents/core/archive_safe.py`: reviewed proposed variant, SHA25616691f0bc7791674df7de527b5f0f7c17c8782428cf5879d818ebb0b09ff76af.
- `tests/test_archive_inspection_recovery.py`: supplied22 tests, materialized from inline handoff.
- `tests/test_archive_inspection_adversarial.py`:6 independent cases (PAX name cap, PAX sparse refusal, negative declared size, padding cap, normalized selection names, missing source).
- `tests/test_archive_inspection_pax_cache.py`: red/green memory-retention regression.
- `pax_memory_probe.py`, `pax-memory-original.json`, `pax-memory-bounded.json`: reproducible allocation probe.
- `final-receipt.json`: hashes, results and apply-check evidence.

## Boundary and limitations

Inspection hashes regular file members and returns bytes only for selected **normalized** names. Paths, conflicts, member count, payload sizes and per-name/cumulative metadata are bounded; special members including directory entries are refused. Returned modes are metadata, not authorization to execute or apply permissions. Missing selections are absent from the returned dict. OSError for a missing/unreadable source remains OSError, consistent with the supplied implementation.

No TOCTOU protection is added between inspection and a later extraction/use; caller adoption must bind the bytes or reopen and revalidate. No caller has been switched to this API. The archive pathname itself is trusted by the caller: it is not pinned with O_NOFOLLOW or restricted to a regular source inode. Resource limit parameters are typed caller configuration; a future untrusted API must validate their integer types/ranges before calling. No live recovery flow, platform/device run or production integration is claimed.

Suggested continuation: review the three-line cache fix, then consider integrating the reusable helper/tests separately from caller adoption. Do not bulk-apply unrelated Mac deltas.

V52 receipt audit clarification: the final suite has119 ordinary testcases and12 successful unittest subtests (131 passed reports in JUnit aggregate). Instrumenting pytest9.2 report hooks for the supplied22cases confirms22 TestReport:passed +12 SubtestReport:passed; evidence /tmp/nerva-v52-archive-subreport-counts.json. The earlier inference that the aggregate was inconsistent was incorrect. Immutable V51 archive is unchanged.
