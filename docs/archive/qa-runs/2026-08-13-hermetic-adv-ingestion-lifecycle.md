# ADV-131 private-ingestion lifecycle evidence

**Date:** 2026-08-13
**Environment:** Linux, Python 3.12, repository virtual environment
**Scope:** Hermetic filesystem/SQLite proof; no owner archive or external service

## Verdict

**CONFIRMED → CLOSED in this candidate.** Howard had two private write roots: the raw
Facebook/WhatsApp drop used by the watcher and the derived archive used by the pipeline,
stylometry, knowledge extraction, embedding cache, watcher state and optional provenance ledger.
The derived archive was erased only implicitly by the KEEP-inverted forget sweep; neither root had
an explicit retention or portable-export contract. The raw default was also repo-relative
`data/`, outside the central runtime-data root.

The candidate introduces one canonical inventory, makes the clean-install raw-import default the
runtime root, and binds all three lifecycle operations to that same tuple. Upgrade compatibility is
explicit: a non-empty pre-G35 repo-local `data/` remains the active watcher input, but export and
forget identify it as outside configured authority and refuse to claim completeness until the owner
resolves it.

| Private root | Writers / contents | Portable export | Retention | Forget |
|---|---|---|---|---|
| `ingestion/` | watcher-created Facebook/WhatsApp drop; owner-supplied raw exports | recursive, exact text/binary representation | `retention.ingestion_ttl_days`; coherent-root newest-mtime sweep; default `0` | KEEP-inverted recursive sweep; runtime conflict preflight |
| `archive/` | `archive.db`, `messages.jsonl`, voice profile, knowledge, summary, watcher state, provenance, embedding cache | SQLite tables + JSON/JSONL/text/base64, including future files by default | same explicit TTL, whole root only | same recursive sweep and preflight |

SQLite sidecars are represented as covered by their database snapshot. Symlinks are never
followed: they are named in `skipped` and set `private_ingestion_complete=false`.

## Red reproduction

The lifecycle test failed at collection because `agents.core.ingestion.lifecycle` and a shared root
inventory did not exist. Inspection then confirmed export v1 had no archive/raw section and
retention had settings only for conversations and audit rows.

## Green evidence

```text
ADV-131 lifecycle contract
18 passed

Lifecycle + export + retention + forget + Howard/provenance adjacency
93 passed; one existing Starlette/httpx deprecation warning

Ruff on changed Python paths
clean

git diff --check
clean
```

The repository-wide suite was attempted but stopped during collection because this sandbox's SOCKS
proxy dependency was absent. After adding that dependency to the disposable virtual environment,
the runner attempted a live connection to `api.ing.com`; that external banking request was refused
and the full suite was not retried or described as passing. Hosted exact-head CI remains required.

The cross-check seeds markers in raw WhatsApp text, archive SQLite, JSONL, voice-profile JSON and a
nested embedding-cache file; all appear in export, stale roots prune, and a full forget leaves no
marker bytes. It also proves forget drops the live Howard RAG pipeline and the process-wide
embedding LRU, whose keys contain raw private text and therefore sit outside the filesystem sweep.

## Independent-review remediation and rollback proof

The first independent R3 review held exact head `8d7e93e` on three findings. This candidate adds
hostile coverage for each:

1. The scheduled production path now passes the orchestrator's long-lived watcher pipeline into
   retention. A regression uses distinct watcher-writer and shared-RAG reader objects and proves
   both lose messages, owner-message lists, stylometry, knowledge and raw-text embedding keys.
2. A non-empty pre-G35 `<checkout>/data/` is detected without following or moving it. The watcher
   keeps it discoverable; export sets `private_ingestion_complete=false`; forget returns `ok=false`
   with the exact external root in `not_erased`; the marker remains owner-controlled.
3. Code-only revert is explicitly unsafe after the new root receives imports. The hermetic rollback
   rehearsal stages a copy from `<runtime-root>/ingestion/` to the old `<checkout>/data/` default
   while this candidate is still running, verifies the marker, and proves the compatibility resolver
   selects the old root. Operational rollback therefore means: stop Nerva, take and verify an
   encrypted backup, stage and verify that copy without overwriting an existing legacy root, then
   revert. Otherwise use a forward fix.

## Boundary

This is hermetic lifecycle proof, not a run against Andrei's real Facebook/WhatsApp archive. An
explicitly injected external source directory remains caller-owned. Existing repo-local `data/` is
gitignored and compatibility-detected; this slice does not silently move or erase a user's files.
