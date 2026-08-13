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

The candidate introduces one canonical inventory, moves the shipped raw-import default below the
runtime root, and binds all three lifecycle operations to that same tuple:

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
15 passed

Lifecycle + export + retention + forget + Howard/provenance adjacency
90 passed; one existing Starlette/httpx deprecation warning

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

## Boundary

This is hermetic lifecycle proof, not a run against Andrei's real Facebook/WhatsApp archive. An
explicitly injected external source directory remains caller-owned; the shipped runtime default is
the central `ingestion/` root. Existing repo-local `data/` is gitignored to prevent accidental
commits and is no longer the shipped default; this slice does not silently move a user's files.
