# OSS adoption research — what to borrow to speed up the hub (2026-06-20)

> Brief: "research these repos, what can we adopt to speed jarvis hub up." Two senses of
> *speed* are covered: **(A) runtime perf** (the 4–5s/query, the per-turn overhead, voice
> latency, concurrency) and **(B) build velocity** (indexing the codebase for agents,
> making the hub agent-native, dev-skill pipelines).
>
> Method: each repo was read on the web (README/docs/source), then every code-level claim
> about *our* repo was verified against the actual files. Verified findings are marked ✅.

---

## 0. TL;DR — the three things to do first

These came out of *reading jarvis while researching*, not from the external repos alone.
All three are **verified against the code** and are small.

| # | Win | File | Effort | Why it matters |
|---|-----|------|--------|----------------|
| 1 | **Parallelize the plugin fan-out** | `agents/core/plugin_gatherer.py` | **S** | ✅ It runs each plugin `await` **sequentially**. A query that triggers weather+news+calendar pays N serial network round-trips. `asyncio.gather` (bounded + per-plugin `wait_for`) collapses them to ~1. `ARCHITECTURE.md:33` even mislabels this path "(parallel)" — it isn't. |
| 2 | **Preload + keep-warm the fast model** | `agents/core/llm/router.py` | **S** | We poll `/v1/models` to *detect* the model but never *warm* it. An empty-prompt request at startup + a keep-alive ping (Ollama `keep_alive:-1`) removes cold-load latency from the first voice turn — a big chunk of the "4–5s". |
| 3 | **`beam_size=1` + `int8_float16` for the live STT loop** | `agents/core/voice/stt.py` | **S** | ✅ STT calls `transcribe(..., beam_size=5)` on a raw `WhisperModel`, fp16, no batching. Greedy decode is much faster on short clear utterances at negligible accuracy loss; `int8_float16` frees ~1.5GB VRAM the LLM slots want. |

Everything below is the per-repo backing for these and the larger bets.

---

## A. Runtime / inference performance

### Ollama — local model serving
Go server over llama.cpp with real lifecycle + concurrency knobs.

- **`OLLAMA_KEEP_ALIVE` / preload**: model stays resident `5m` by default; `-1` = never unload. **Preload** by POSTing an empty prompt to `/api/generate` — forces load without generating, so the first real turn doesn't eat the load. → **Win #2.**
- **`OLLAMA_NUM_PARALLEL`** (default **1**): concurrent requests served by *one* loaded model over a shared KV cache. Set **2–4** so the HUD voice turn and a background summary/plugin call interleave instead of head-of-line blocking. RAM scales by `NUM_PARALLEL × context`.
- **`OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0`**: flash-attn is off by default; on, it enables KV-cache quant (`q8_0` ≈ half KV memory vs f16, negligible quality). Gate per-model — there are crash reports on some architectures (ollama #11682, #13337). Good fit for the slot-2 deep model on the 24GB card.
- **Adopt:** Wins #2 directly; `NUM_PARALLEL` in the Ollama backend config; flash-attn/q8 behind a per-model allowlist. LM Studio exposes JIT-load + TTL but not these by name — **route concurrency-sensitive traffic to the Ollama backend** when we want real parallelism.
- Sources: ollama/envconfig/config.go, docs.ollama.com/faq.

### faster-whisper — STT
CTranslate2 reimplementation, ~4× faster than openai-whisper at equal accuracy.

- **`beam_size`**: the costliest single knob; **1 (greedy)** for the live loop. → **Win #3.**
- **`compute_type="int8_float16"`** on GPU: ~4525MB → ~2926MB VRAM, ~same speed.
- **`BatchedInferencePipeline(model, batch_size=8/16)`**: drop-in for `model.transcribe`; 13min audio 1m03s → 17s on GPU. Helps multi-segment clips more than 1-shot HUD utterances.
- **`distil-large-v3` / `turbo`** models: large-v3 quality at a fraction of decode time.
- **Adopt:** `stt.py:_init_model` hardcodes `compute_type` and `beam_size=5` — make both config, default greedy + `int8_float16` for the HUD, optional batched pipeline for long clips. Effort S.
- Source: github.com/SYSTRAN/faster-whisper.

### Fooocus → ComfyUI memory pattern
Fooocus's own flags are SDXL-specific; the reusable IP is the **ComfyUI `model_management`** pattern it inherits.

- A `VRAMState` machine + **`load_models_gpu()`** that calls **`free_memory()`** to **LRU-evict** other resident models to CPU RAM until the new one fits, keeping a `minimum_inference_memory` reserve.
- **Adopt (M, medium):** a small "model manager" for the **fast↔deep swap on the single 24GB GPU**. Track resident models with last-used timestamps; explicitly unload the LRU (Ollama `keep_alive:0` / LM Studio unload) before loading the deep model, keeping headroom. Prevents the silent OOM-thrash that adds latency to slot-2 escalations in `hybrid_router.py`. Cleanest architectural borrow of the perf set.
- Sources: Fooocus readme; ComfyUI memory-and-device-management docs.

### yt-dlp — bounded concurrent fan-out
The one transferable pattern: **`--concurrent-fragments N`** = *bounded* parallelism (a `Semaphore`, not unbounded fan-out) + layered retry with backoff and per-unit timeouts.

- **Adopt:** this *is* Win #1 — `gather_plugin_data` should build eligible coroutines and run them with `asyncio.gather`/`TaskGroup` under a `Semaphore`, each wrapped in `asyncio.wait_for` so one slow API can't stall the turn. Our embedding/disk cache already covers yt-dlp's `--cache-dir` idea.
- Source: github.com/yt-dlp/yt-dlp.

### OpenMontage — agent-orchestrated video editor
Honest verdict: **nothing for perf.** Early project, *synchronous* agent-as-orchestrator state machine reading a YAML manifest; no async, no queue, no worker pool, no batching (explicitly absent). Its one adjacent idea — a 7-dimension scoring engine for provider/tool selection per step — is conceptually near our `hybrid_router` model selection, but it's per-call and serial, the opposite of a throughput win. Skip.
- Source: github.com/calesthio/OpenMontage.

---

## B. Architecture / infra patterns

### Plausible Analytics — own your event table
Privacy-first analytics; Elixir + ClickHouse at scale. **At single-user scale, ClickHouse / salted-hash privacy / materialized rollups are all moot** — don't port them. The transferable core:

- Own a flat, append-only **event table**; **aggregate-on-read** with SQL `GROUP BY`; flat schema with a `props` JSON column; cookieless **`sendBeacon`** fire-and-forget client (<1 KB).
- **Adopt (S–M, high):** replace the mock GA4 plugin (`plugins/analytics.py`, `_fetch_ga4_kpis`) with a first-party SQLite `events(id, ts, name, path, referrer, props_json, session_id)` + `POST /api/analytics/event` (single INSERT) + a ~10-line beacon helper. Keep the existing `get_kpis()/get_summary()` interface so the HUD is untouched. Kills mock data + GA4 OAuth/service-account config; fully local/offline.
- Sources: plausible/analytics, plausible.io/docs/events-api.

### AppFlowy — local-first data model
Notion alternative; Rust core + `yrs` (Rust Yjs CRDTs) + RocksDB.

- **Block-tree document model + Delta text**: docs are trees of typed blocks (`id, type, attrs, parent, ordering`); inline text is a Delta op-list. **Take this wholesale** for notes/memory (M, high) — stable block IDs become memory references, partial edits are structured, rendering is clean. CRDT-independent.
- **View-over-data**: store memory once, define filtered views (tag/recency/agent) as saved query specs (S).
- **State-vector diff sync** (SyncStep1 state vectors → SyncStep2 missing updates): adopt only as a *pattern* layered on our existing audit Merkle chain + checkpoints, and **only if multi-device offline editing becomes real**. Full `yrs` CRDTs are overkill for single-user — defer.
- Sources: AppFlowy, AppFlowy-Collab.

### n8n — workflow execution model
We already ship a `plugins/n8n.py` bridge **and** our own engine (`workflows/engine.py`, `flow_api.py`, `hierarchical.py`) + an autonomy queue (`autonomy/queue.py` SQLite `TaskQueue` + `worker.py`). n8n's perf model is the reference to grade ours against:

- **Queue mode** (`EXECUTIONS_MODE=queue`): main process enqueues; **separate worker processes** pull jobs from a broker (Bull/Redis) and run them — execution is off the request path and scales horizontally; **per-worker bounded concurrency** (`--concurrency`).
- **Item-batched node execution**: a node runs once over *all* items (vectorized), not once per item — fewer call/await boundaries.
- **Execution-data pruning** + **binary-data offload** (filesystem/S3, not in-DB) so history doesn't bloat the store.
- **Adopt:** our autonomy worker *is* a queue+worker already; the borrow is (1) push heavy/multi-step workflow runs onto that worker instead of the request coroutine, (2) add **bounded concurrency** + **per-step timeouts** in `engine.py`, (3) **prune** execution history in `workflows/storage.py`. Effort M; payoff = request latency stops absorbing workflow cost. Skip Redis/Bull — SQLite queue is fine at our scale.
- Source: n8n docs (scaling/queue mode).

### cal.com — calendar provider abstraction
Scheduling app; multi-tenant by design (most of which we don't need). The clearly useful bit:

- **`Calendar.getAvailability` → normalized `EventBusyDate[]`**; a manager fans out across connected calendars and merges busy intervals. **Availability by subtraction**: working hours − busy − bookings − buffers, clamped by notice, stepped at `slotInterval`; timezone-safe via explicit zones (we have native `zoneinfo` in 3.12).
- **Adopt (S, high for the calendar plugins):** normalize our calendar plugins behind one `busy_intervals(start, end, tz) -> [(start,end)]` contract so an agent can ask "am I free?" provider-agnostically; optionally a small free-slots helper (M). Skip the Prisma `Booking/EventType/Schedule` model, multi-attendee intersection, and Redis slot cache.
- Source: cal.com (CalendarService.ts, slots/util.ts).

### Bitwarden — local secret vault
E2E secrets manager. Most of it (zero-knowledge server, org RSA key hierarchy) assumes a server + sharing we don't have. The transferable crypto:

- **Wrapped-data-key hierarchy**: derive a wrapping key from a master passphrase (**Argon2id**), generate a random data key, store it **wrapped**; password change re-wraps, never re-encrypts data. **Self-describing AEAD envelope** with an `alg_version` tag for painless migration.
- **Adopt (M, high):** replace plain `.env` + the *decorative* encryption in `plugins/oauth.py` — today `_get_fernet()` writes the Fernet key **in plaintext next to** the ciphertext (`TOKEN_DIR/.encryption_key`). Build one local vault: Argon2id-derived wrapping key (`argon2-cffi`) → random 32-byte data key wrapped with **AES-256-GCM** → all secrets (OAuth tokens, `*_CLIENT_SECRET`, API keys) as consumers. Unlock once at startup, hold the data key in memory only. Use **AES-GCM** (don't hand-roll Bitwarden's CBC+HMAC); 600k+ PBKDF2 or prefer Argon2id.
- Sources: bitwarden.com security white paper, kdf-algorithms, secrets-manager docs.

### Penpot — low value here
Design tool. Its real-time stack (per-file WebSockets, Redis pub/sub, mutation broadcast) and Rust/WASM/Skia renderer solve *concurrent multi-user editing of a shared canvas* and 60fps vector rendering — neither exists for a single-user `createElement` dashboard. **One mild nugget:** their rule that *changes **set** values (never increment), idempotently, scoped to one entity* is a clean idempotent-mutation principle — worth keeping in mind **only if** multiple agents ever write shared SQLite state concurrently. Not a reason to port anything.
- Sources: penpot/penpot, penpot-docs data-guide.

---

## C. Developer / agent velocity

### obra/superpowers — dev-skill + methodology pipeline
Markdown **SKILL.md** skills + an opinionated TDD/planning/review pipeline; works across Claude Code, opencode, Gemini, Cursor. Very mature, in the official Anthropic marketplace. **Note:** our `docs/superpowers/` is **only plans/ + specs/** that *reference* its skills — we consume the plan format but have **no actual dev-skill library and no dispatcher**. (Separately, our top-level `skills/*/SKILL.md` are *runtime agent capabilities* — a different concept; don't conflate.)

- Techniques: SKILL.md frontmatter where `description` starts with "Use when…" and lists *triggers* (agents act on the description, not the body); **progressive disclosure** bodies (<200 words for hot skills); a **dispatcher hook** that makes relevant skills mandatory; "no skill without a failing test first."
- **Adopt (S, highest velocity ROI):** install the plugin so all three coding assistants get the pipeline for free; then author **3–5 jarvis-specific dev SKILL.md** under `.claude/skills/` (none exist) encoding our conventions — *vanilla React no-JSX*, the `sys.path.insert` test bootstrap, the per-domain-router registration ritual + route-parity re-seed, and a dispatcher skill for *"which `AI_CONTEXT` bundle to load per task."* ~1 day.
- Sources: github.com/obra/superpowers, superpowers-skills.

### DeusData/codebase-memory-mcp — index the codebase for agents
High-perf MCP server (~88% C, single binary) that indexes a repo into a **persistent knowledge graph** for agents. ~7.3k stars, active, SLSA L3.

- **Structural indexing, not chunk-and-embed**: vendored **tree-sitter** extracts entities (functions/classes/routes) as graph **nodes**; a lightweight type-resolver adds `IMPORTS`/`CALLS`/inheritance **edges**. Unit of retrieval is a semantic node, not a text window.
- **Storage = SQLite** + **FTS5 BM25** + bundled int8 vectors; **5 retrieval modes** (semantic, BM25, structural/regex, openCypher, `trace_path` BFS) over 14 MCP tools. Shareable `.zst` index snapshot — no re-index per dev. Claims ~99% token reduction vs file-by-file.
- **Adopt — two paths:**
  - **(A) Just run it (S, high):** add to devs' `.mcp.json`, `index_repository`. Directly attacks our **~2M-token** problem and *automates* what `docs/AI_CONTEXT.md` does by hand. Trial first — its bundled embeddings are weaker than ours, and it's a `curl | bash` binary (mitigated by SLSA L3 + checksums).
  - **(B) Adopt the approach (L):** we already have vector + KG + RRF + embedding cache. Borrow **tree-sitter entity extraction → KG nodes/edges over our own source**, then reuse our RRF to fuse BM25+vector+graph. Makes the *product* codebase-aware, but partly reinvents (A). Only if codebase-awareness must live in the product, not the dev loop.
- Sources: github.com/DeusData/codebase-memory-mcp.

### BuilderIO/agent-native — make the hub agent-native
TS framework where one `defineAction()` (Zod schema + `run()`) auto-exposes as MCP tool + HTTP + UI + A2A + CLI. Younger/smaller (~1.1k stars), fast-moving. **We won't adopt the library (it's TS); we adopt the *pattern*.**

- We have **~298 route decorators** and already an **MCP *server*** (`agents/core/mcp/server.py`) that exposes *agents* as governed `ask_<agent>` tools — ✅ verified — but **not the routes**.
- **Adopt (M, medium):** generate a machine-readable **action manifest from the FastAPI app** (OpenAPI is already free via Pydantic) and have `JarvisMCPServer` expose **governed, allow-listed routes** as MCP tools alongside agents, reusing the existing permission gate. Wiring route→tool, not new infra. Payoff is product surface (any MCP client can drive the hub) more than dev velocity.
- Source: github.com/BuilderIO/agent-native.

---

## Priority shortlist (effort → impact)

| # | Action | Repo lineage | File(s) | Effort | Impact |
|---|--------|--------------|---------|--------|--------|
| 1 | `asyncio.gather` the plugin fan-out (+ per-plugin timeout) | yt-dlp | `plugin_gatherer.py` | S | **High** ✅ verified serial |
| 2 | Preload + keep-warm the fast model | ollama | `llm/router.py` | S | **High** (cold-load latency) |
| 3 | STT greedy `beam_size=1` + `int8_float16` | faster-whisper | `voice/stt.py` | S | **High** (voice path) ✅ |
| 4 | `OLLAMA_NUM_PARALLEL=2–4` for the Ollama backend | ollama | backend config | S | Medium (concurrency) |
| 5 | First-party SQLite analytics + beacon (drop GA4) | plausible | `plugins/analytics.py` | S–M | Medium (kills mock/OAuth) |
| 6 | Calendar `busy_intervals` provider contract | cal.com | calendar plugins | S | Medium |
| 7 | LRU `free_memory` model manager for fast↔deep swap | fooocus/comfyui | `llm/hybrid_router.py` | M | Medium (anti-OOM-thrash) |
| 8 | Local encrypted secret vault (Argon2id + AES-GCM) | bitwarden | `plugins/oauth.py` | M | High (security) ✅ plaintext key today |
| 9 | Workflow runs → autonomy worker, bounded concurrency + pruning | n8n | `workflows/engine.py`, `storage.py` | M | Medium |
| 10 | Block-tree + Delta data model for notes/memory | appflowy | memory subsystem | M | High (structure) |
| 11 | Install superpowers + write 3–5 dev SKILL.md | obra/superpowers | `.claude/skills/` | S | **High** (dev velocity) |
| 12 | Trial codebase-memory-mcp on the repo | codebase-memory-mcp | `.mcp.json` | S | **High** (agent comprehension) |
| 13 | Expose governed routes via the existing MCP server | agent-native | `mcp/server.py` | M | Medium (agent-native) |

**Low / no value for us:** Penpot (multi-user real-time + canvas rendering — wrong problem), OpenMontage (synchronous, no concurrency machinery). cal.com and AppFlowy's *sync* layers are over-scoped for single-user — take only the noted patterns.

---

## Verified-against-code findings (so the quick wins aren't speculative)

- ✅ `plugin_gatherer.py:gather_plugin_data` awaits each plugin sequentially; `ARCHITECTURE.md:33` mislabels it "(parallel)".
- ✅ `voice/stt.py` calls `transcribe(..., beam_size=5)` on a raw `WhisperModel`, hardcoded `compute_type`, no `BatchedInferencePipeline`.
- ✅ `mcp/server.py` exposes agents as governed `ask_<agent>` tools — not the ~298 routes.
- ✅ `plugins/oauth.py` `_get_fernet()` stores the encryption key in plaintext (`TOKEN_DIR/.encryption_key`) next to the ciphertext.
- ✅ `workflows/` engine + `autonomy/queue.py` worker + `plugins/n8n.py` all exist (the n8n borrow is reshaping, not greenfield).
