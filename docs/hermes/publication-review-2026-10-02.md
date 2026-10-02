# Nerva publication integration review — 2026-10-02

Compared `aa4865b5d061b52f3cee7e044dab2d922e4a4617` with `origin/main` at `9d5b3add85bd8c172bfe38ed1506a2852e2d6e5a`. This was a read-only, bounded source review of aggregate runtime changes, prioritizing permission-grant replay, signed video candidates and primary retry, and the four local auxiliary consumers. I did not edit the worktree or run tests as part of this review.

**No concrete integration blocker found in the reviewed paths.**

- Permission grants: `PermissionLedger.apply_grant` serializes receipt lookup and effect creation with `BEGIN IMMEDIATE`, binds a replay to both the governed payload and persisted authority, adopts only one matching legacy grant, and leaves revoked/consumed/expired grants inactive (`agents/core/permission_ledger.py:821-884`). OS-input restore tokens are stored before the SQL commit and are not reminted on replay (`:878-902`). The focused tests cover restart, concurrent ledger instances, uncertain commit, mismatched payload, inactive grants, legacy duplicates and token recovery (`tests/test_permission_ledger.py:339-601`).
- Video approval and candidates: intake requires enforced signed mediation and persists the classed payload (`agents/core/video_analysis.py:312-330`); the class HMAC includes every ordered route, credential binding, payload and scoped roots (`agents/core/llm/video_policy.py:190-209`). Runtime rechecks the persisted task, kernel, complete current route set and source binding before source access, each attempt and disclosure (`agents/core/video_analysis.py:404-490`). Remote candidates receive separate role consent checks (`agents/core/llm/video_policy.py:155-187`).
- Physical video requests and retry: the request scope validates direct transport, destination, method, authorization header and body after request hooks and before transport, then checks authority again during cleanup (`agents/core/llm/video_policy.py:212-295`). Primary transient retry is limited to the signed zero-or-one setting, creates a fresh body/client, and rechecks authority before another send; fallback candidates get one attempt (`agents/core/video_analysis.py:336-402`, `:453-490`; `agents/core/llm/video_retry.py:12-28`). Guard, source, hook, cancellation and unclassified failures do not become fallback authority. The focused suites include revocation, body mutation, second-send, cancellation and candidate isolation cases.
- Auxiliary interaction: the shared helper rejects job pins before model/backend lookup, selects only `router.local_backend`, captures one per-task model and holds the existing H513 scope around generation or streamed compression (`agents/core/llm/auxiliary_text.py:39-61`). These calls use separate context-local physical request guards and do not alter the video route or retry configuration.

Limits: this was not an exhaustive audit of all 28 commits or generated/historical evidence. I relied on source inspection and the existing focused test evidence; the concurrent full-suite result and GitHub CI remain separate verification. No live video provider, installed auxiliary model, paid route or production consent state was exercised. The known missing-blob fixture failure is assigned to `repair_media_deadline` and was excluded from this runtime assessment.

## Final local verification

Frozen commit `0307142d37bac7ad812f1738ca12cb75617b6e2e`:20505 backend
tests passed,34 skipped,one expected failure and64 warnings. All 4,290 tracked
regular files remained unchanged. The missing-blob fixture was reproduced red
with forced packing and repaired with a separate object store:136 module cases
passed. It no longer assumes loose Git storage or deletes pack files.

The original failed full run on aa4865b5 is retained in the
[auxiliary integration receipt](evidence/h277-local-auxiliary-integration-2026-10-02.json).
The four-producer focused selection passed 513; the isolated legacy-console tools
selection passed 40. Frontend 1,838 tests, typecheck and build are earlier proof on
unchanged frontend source/schema, not a fresh frontend rerun.

Publication lint found four errors in historical mutation runners: import order,
one unused import and a dict-constructor style issue. Localized formatting fixes
passed full Ruff and compilation; historical outcome receipts retain their original
hashes. [Normalization provenance](evidence/publication-runner-normalization-2026-10-02.json)
records original commit/hash and current hash. This is not a new mutation run.

Exactly 21 previously-current Hermes evidence rows were re-read and refreshed, with
no status promotions. The original 207 stale rows were not touched. H277 remains
partial. The next slice is operation-bound acquisition auxiliary model selection;
presence explanation still lacks a real product caller.

[PR1226](https://github.com/andrei649/jarvis-hub/pull/1226) merged on 2026-10-02
as `a5b74939d4632c61e007ad64e4df937c44c47bc5` after both CI rounds passed, including
all seven required checks. The branch rules require linear history and rejected
the planned merge commit, so integration used squash. The remote branch
`archive/hermes-integration-source-20261002` preserves original source/evidence
commits at `64e99339302ccf8ddbc0c8f866cad8563d0c140b`. The canonical local main
checkout was fast-forwarded to the merged commit. No deployment or live-provider
acceptance is included; post-merge CI is a separate run.
