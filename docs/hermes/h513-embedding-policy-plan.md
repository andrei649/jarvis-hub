# H513 local embedding policy and cache provenance

Status: coordinator-approved bounded plan, 2026-09-27. Documentation only until
coordinator releases the full backend checkpoint. No live model calls, publication,
new providers or vector-store migration.

## Contract

Guard the actual embedding dispatch for existing no-router callers: lazy
`MemoryManager.embed()` / recall / remember / optional background turn embeddings,
and ingestion / watcher / Howard archive search through `IngestionPipeline`.
Public embedding APIs retain vectors, aligned batches, empty-input behavior,
deterministic hash fallback and ordinary bounded transient retry/backoff.

Initial coverage is local-only LM Studio and Ollama. Require a proven loopback
actual destination and safe current provider policy; unknown, training, malformed
or unsupported targets immediately fall back to hash with zero model I/O. Neither
an inherited owner principal nor primary-provider/judge consent grants remote
embedding use. A consented remote embedding target remains an explicit follow-up.

## Client identity and physical boundary

LM Studio posts `/v1/embeddings` through an owned synchronous HTTPX client. Ollama
posts `/api/embeddings` through an owned `ollama.Client`; do not use or mutate the
SDK module-level global client. Preserve SDK `OLLAMA_HOST` parsing and effective
`OLLAMA_API_KEY` / Authorization behavior. `Embedder.from_env()` currently passes
a LM Studio default `EMBED_BASE_URL` even when selecting Ollama; that value must
not silently replace Ollama's host with port 1234. Preserve Ollama host selection
rather than introducing a new precedence rule in this slice.

Coordinator decision: owned Ollama requests have a 30-second timeout, matching
existing LM Studio requests. Disable redirects for both owned clients. Resolve
actual client base URL and effective Authorization, not an assumed provider
endpoint or the unused Ollama `Embedder.base_url`. Unsupported custom auth,
cookies and unverifiable injected clients fail closed; test fakes expose truthful
wire metadata or use actual HTTPX MockTransport.

Final transport review: owned clients also disable environment proxy discovery
(`trust_env=False`). An injected client whose selected transport can proxy a
loopback request is unsupported and must fall back without sending data. This
is local to embedding clients; generic HTTPX factories retain their defaults.

Add synchronous request checking alongside the existing context-local physical
request guard, preserving its async API and existing cleanup semantics. A narrowly
scoped embedding policy helper may compose the guard and explicit internal /
generated classification. Establish scope inside each actual worker attempt so
ThreadPoolExecutor workers do not depend on inherited ContextVars. Freeze private
wire identity for an attempt and freshly validate configuration, policy and actual
adapter/request identity before each physical send: exact POST endpoint,
Authorization, no cookies, no redirect/reused-request hop. Preserve ordinary
rebuilt retries; never wrap unrelated SDK methods or mutate a global SDK client.

Policy refusal immediately produces hash without sleep or model retry. Transient
network/model failures retain existing retry counts and backoff. Refusal/transport
fallback preserve the public vector result and existing degraded-state logging.

## Cache provenance

Existing process keys and disk namespaces identify backend/model only. Request-time
hash fallback leaves that identity unchanged, so hash vectors can persist under
semantic keys and prevent later semantic recovery. Correct this within the same
slice:

- Carry immutable source provenance per computed result; do not use a shared mutable
  last-result flag across batch workers. Public methods still return vector lists.
- Introduce versioned semantic cache identities bound to provider, model and actual
  target/account identity through a keyed opaque binding. Process and disk caches
  use the same identity. Existing mixed legacy namespaces are ignored, not deleted.
- Never put fallback under a semantic identity. For a requested semantic backend,
  do not cache fallback as semantic success; the same text may recover on a later
  call. Explicit hash-backend caching remains deterministic and separate.
- Safe local generation works when the protected scope key is unavailable. In that
  case disable shared process/disk semantic cache use; never expose an unkeyed hash
  of credentials or make local generation depend on secret-store availability.
- Review the archive loader's direct `embedder.cache.get()` seam when implementing:
  it must not silently read an old or mismatched namespace. Any necessary consumer
  change outside owned paths is reported to the coordinator before editing.

Existing memory/vector-store records may already mix hash and semantic vectors.
This slice does not migrate/re-embed those records or change vector dimensions,
retention, session deletion, provenance ledgers or recall ranking. Record an explicit
follow-up for durable producer provenance and a reviewable re-embedding/migration
strategy; cache correction alone must not be described as repairing stored vectors.

## Ownership and verification

Runtime writer owns `agents/core/ingestion/embedder.py`,
`agents/core/llm/data_handling.py`, `agents/core/llm/egress.py`, new
`tests/test_h513_embedding_policy.py`, and truthful fixture updates in
`tests/test_memory_embeddings.py` and `tests/test_embedding_pipeline.py`. One narrow
helper in ingestion/llm is allowed if composition improves the implementation.
Composer work uses separate `vision_policy.py`; do not overlap its source.
Coordinator owns integration and checkpoint evidence. No source edits until go.

RED/GREEN offline tests cover LM Studio and actual SDK Ollama loopback success;
OLLAMA_HOST/key destination resolution; timeout/redirect settings; off-loopback
zero-I/O hash despite inherited owner/provider/judge grants; malformed/unverifiable
clients; fresh endpoint/auth/policy changes between retries; actual request
mutation/redirect/cookie refusal; batch/thread isolation; fallback then recovery
for identical text; target/account cache isolation; unavailable scope-key local
success without shared/disk semantic cache; and legacy mixed-cache exclusion.

Focused regressions: memory embeddings, embedding pipeline, Howard RAG, ingestion
pipeline provenance and ingestion data lifecycle. Preserve existing assertions;
replace incomplete network fakes with truthful metadata/MockTransport. No full
suite, delegation, commits or push by this writer.

Rollback removes the dispatch guard/new client setup and versioned cache writes
without deleting caches, queued memory, archived messages or vector-store records.
The deliberate new 30-second Ollama bound is part of the accepted slice.

## Checkpoint release

Coordinator released implementation after the complete local judge milestone:
18,919 backend passes, 35 skips, zero failures; 1,804 frontend passes. Generation
date 2026-09-27; base/head `bd2bb70ead1b493043a335e77713fc42c47d4013`.
Next action: implement the owned paths above with focused RED/GREEN tests.
Composer-specific policy helpers belong in `agents/core/llm/vision_policy.py`;
embedding owns the shared data-handling and egress sync additions.

## Implementation checkpoint

The local implementation now carries per-result cache provenance, owns its Ollama
client, and enforces synchronous request guards. Howard RAG fixtures explicitly
select offline hash embeddings; their archive/search assertions are unchanged.
Full integration and the final proxy regression are tracked in the subsequent
vision/embedding evidence snapshot. Existing stored vectors are not migrated.
