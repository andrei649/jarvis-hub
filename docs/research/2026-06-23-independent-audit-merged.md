# Jarvis Hub — Independent Audit (Merged)

> Fresh-eyes review, code-first (docs ignored). Two independent passes merged into one
> de-duplicated report:
> - **[Opus]** — 6 parallel deep dives (security, backend architecture, data/persistence,
>   frontend/clients, WorldView, test/CI/supply-chain), headline findings verified first-hand.
> - **[Sonnet]** — 3 specialist agents (backend/architecture, frontend/API, devops/SRE).
> - **[Both]** — found independently by both passes (higher confidence).
>
> Every finding below was re-validated against the source in this session. Severity is by
> *gate* (what must be true before networked / multi-user deployment), not effort.
> Date: 2026-06-23.

---

## 0. Verdict

This is an unusually disciplined, security-conscious codebase for a solo-maintained project
(~92k LOC Python + ~42k LOC client + a separate TypeScript WorldView subsystem + Rust + mobile +
Tauri). Real Docker sandboxing, genuine SSRF defense with IP-pinning, AEAD crypto (Fernet/PBKDF2),
fail-closed auth guards with constant-time compares, a **meaningful** test suite (~2,550 tests,
~85–90% verifying real behavior — not mock theater), and clean async hygiene (one bare `except` in
the whole tree).

So the findings are **not** "this is broken" — they are a short list of real bugs, a few features
that don't do what they claim, and one strategic problem (breadth-over-depth) that outranks any
single bug. The single most important *technical* finding is that the "forget me" / privacy story
is partly cosmetic; the single most important *project* finding is scope vs. one maintainer.

---

## 1. Strengths to protect (do not regress)

1. **Fail-closed auth** — token guards with `secrets.compare_digest`, localhost-only dev posture,
   admin⊇user, fail-closed behind untrusted proxy, token-guess rate-limiting. `web.py:83-205`. [Both]
2. **Real SSRF defense** — metadata/private-CIDR blocking, IPv4-mapped IPv6, anti-rebinding, and a
   TOCTOU-safe `fetch_page` that validates every redirect hop and pins the validated IP.
   `security/ssrf.py`, `plugins/websearch.py:94-162`. [Opus]
3. **Genuine sandbox isolation** (not theater) — Docker `--network none --read-only --memory
   --pids-limit --cpus`; host-exec off by default and surfaced in `security_status()`.
   `sandbox.py:226-238`. [Opus]
4. **Sound crypto** — Fernet AEAD + PBKDF2-HMAC-SHA256 (390k iters); OAuth tokens encrypted at rest
   in `tokens/`; key files `chmod 600`. `secrets.py`, `e2e_sync.py`. [Opus]
5. **Per-request session isolation** — `session_id` is backed by a `contextvars.ContextVar`
   (`_active_session`), so concurrent turns don't bleed (BUG-5). `orchestrator.py:113,294-336`.
   **Verified correct.** [Sonnet]
6. **Honest data semantics** — HUD renders empty over fake; `live:false` enforced. [Sonnet]
7. **Meaningful, fast, offline test suite** — ~2,550 tests; LLM faked at the HTTP transport layer so
   real parsing/sanitization runs; route-auth matrix snapshot fails CI on any new unguarded mutating
   route (`tests/test_route_auth_matrix.py`). [Both]
8. **Forward-only versioned migrations** with `user_version` gating + per-step transactions.
   `persistence/migrations.py`. [Both]
9. **~60 extracted routers (CLN-3)** — `web.py` god-object largely dismantled; zip-slip guards on
   restore/marketplace; Dependabot + third-party drift detection. [Both]

---

## 2. Findings (merged, de-duplicated)

Provenance: **[Opus]**, **[Sonnet]**, **[Both]**. Status: ✅ verified this session.

### 🔴 Critical / High — address before any networked or multi-user deployment

**F1 — "Forget me" doesn't forget, and mints an unencrypted full-PII backup.** [Opus] ✅
`data_purge.py:43-45,96-103`. Purges only `missions.db`, `autonomy.db`, `analytics.db`, `notes.json`.
**Excludes** `memory.db` (facts/preferences), every conversation transcript (`<sid>.json`/`.jsonl`),
the embedding cache, the Qdrant vector store, and the Neo4j KG — i.e. the user's actual semantic
memory survives deletion. Worse, it is "backup-first": `create_backup()` writes a full **unencrypted**
`.tar.gz` of the entire data root (incl. secrets) *before* deleting four DBs and never cleans it up.
Net effect: "forget me" can **increase** PII at rest.
*Fix:* purge the full content set (incl. vector/KG hooks); reconcile purge/export allow-lists;
don't leave an unencrypted snapshot behind.

**F2 — Secrets at rest in plaintext.** [Both] ✅ — Sonnet C1 + Opus H2.
`settings_db.py:96-113` stores `twilio_auth_token`, `notion_integration_token`, `tuya_secret`,
`gecko_*_secret`, `stark_ga4_service_account` (full GA4 service-account JSON) as `kind="text"`;
`put_category:262` writes them via `json.dumps` with **no encryption**. `backup.py:107-135` then tars
`settings.db` + `tokens/` + `security/secrets.enc` into an **unencrypted** archive.
*(Nuance: OAuth tokens in `tokens/` ARE Fernet-encrypted — only admin-entered keys in `settings.db`
are plaintext.)*
*Fix:* envelope-encrypt credential-category columns via the existing Fernet/SecretBroker at write
time; encrypt backups or exclude secret-bearing files.

**F3 — DOM XSS in the shipped HUD; can exfiltrate the admin token.** [Opus] ✅
`agents/web/index.html:369` — `nl.innerHTML = (d.news||[]).map(h => \`<div class="hl">${h}</div>\`)`.
`d.news` is **external RSS** (BBC/Google News, `plugins/news.py`) rendered unescaped; siblings at
`:365` (weather), `:372` (system), `:382` (conversation) too. Auth tokens live in `localStorage`
(`auth.js`, `console.js`), so a poisoned headline → token theft. An `esc()` helper already exists
(`components.js:15`, `brain.html:273`) but isn't used here. Compounded by **no CSP anywhere** and the
Tauri shell setting `"csp": null` (`tauri.conf.json:21`) while loading this exact page.
*Fix:* route HUD dynamic data through `esc()`/`textContent`; add a CSP + security-header middleware;
set Tauri `csp`.

**F4 — WorldView backend-api is open-by-default.** [Opus] ✅
`worldview/backend-api/src/config.ts:19` — `authSecret` defaults to `""`, which **disables auth**
(every request gets an admin/`*` principal), while `host` defaults to `0.0.0.0` and compose publishes
`4000:4000`. One missing env var → a wide-open admin OSINT API on all interfaces. (MCP + signal-layer
fail *closed* — backend-api should match.)
*Fix:* refuse to start unauthenticated on a non-loopback bind; default `HOST=127.0.0.1`.

**F5 — Sandbox containment is never tested.** [Opus] ✅ (and corrects Sonnet's "tests = positive")
`sandbox.py` is security-critical, but every test that would prove real Docker/WASM isolation
`pytest.skip`s when Docker/wasmtime is absent — i.e. always, in CI (`tests/test_sandbox_gating.py:21,43`).
The config gating is verified; the **containment guarantee is not** (no assertion that sandboxed code
can't escape, reach the network, or exhaust resources).
*Fix:* a Docker-enabled CI lane asserting no-escape / no-network / resource caps.

**F6 — Audit hash-chain is plain SHA-256, not keyed.** [Sonnet C2] ✅
`security/audit.py:91,159` — `row_hash = sha256(prev|ts|type|findings|preview|action)`. Anyone who
can write `audit.db` can recompute the whole chain, so it's tamper-*evident* only against actors
without DB access.
*Fix:* `HMAC-SHA256` with a key stored **outside** the data root (else the key is exfiltrable
alongside the DB). Severity is real but threat-model-limited — treat as High hardening, not Critical.

---

### 🟠 Medium

**F7 — Path traversal via `session_id`.** [Opus] ✅ `routers/sessions.py:33` → `memory/persistence.py:17,27`.
Unvalidated `sid` → `MEMORY_DIR / f"{sid}.json"` for read and write; `../../x` escapes the data root.
Owner-only (behind `user_guard`), but a real arbitrary-`.json`-path primitive. *Fix:* `^[A-Za-z0-9_-]+$`
at the persistence boundary.

**F8 — Blocking file I/O on the async hot path.** [Opus] ✅ `memory/conversation.py:89-108`.
`add_turn` is `async` + holds an `asyncio.Lock`, yet calls sync `_append_log` **and** `_save_snapshot`
(rewrites the entire session JSON, O(turns)) with no `to_thread`. Called 2×/turn → stalls the whole
event loop. *Fix:* `to_thread`/debounce the snapshot (the pattern is already used for checkpoints/audit).

**F9 — SSE stream leaks the orchestrator turn.** [Opus] ✅ `web.py:606-647`. The producer `task` is
`cancel()`ed only if the loop `break`s; on client disconnect `yield` raises and cancel never runs → the
LLM keeps generating/writing memory for a gone client; the task is never awaited so its errors vanish.
*Fix:* `try/finally: task.cancel(); with suppress(CancelledError): await task`.

**F10 — Settings writes have no validation and no audit.** [Sonnet C3 + H1] ✅ `routers/admin.py:85-87`,
`settings_db.py:254-267`. `put_category` checks only that a key exists, then `json.dumps`es any value
(`llm.temperature="bad"` persists); no `audit.log` records who changed what. *Fix:* a `SETTINGS_SCHEMA`
(type/range/enum) → 422 on violation; `audit.log("SETTINGS_CHANGE", …)` before each write.

**F11 — Cypher injection in the knowledge graph.** [Opus] ✅ `memory/graph.py:197,208,294`. Entity
labels, relation types, and property *keys* are f-string-interpolated into Cypher (values are correctly
parameterized). Reachable if memory-extraction/ingestion derives type strings from content.
*Fix:* allow-list / validate labels & rel-types.

**F12 — WorldView WKT built from untrusted coordinates without coercion.** [Opus] ✅
`worldview/ingestion-workers/.../wkt.py:8-21` — Polygon/MultiPolygon paths interpolate feed coordinates
as raw strings (only the Point branch coerces to `float`). Malformed-geometry / parse-failure vector
from untrusted OSINT feeds. *Fix:* coerce + bounds-check lat/lon before WKT.

**F13 — Scanner stores raw secrets in `matched_text`.** [Opus] ✅ `security/scanner.py:198,261` →
`admin.py:131`. No live path populates it today, but the first caller that logs findings-with-secrets
persists plaintext keys and serves them via `GET /api/admin/audit`. *Fix:* mask at the scanner boundary.

**F14 — Containers run as root; secrets in manifests.** [Opus] ✅ Zero `USER`/`HEALTHCHECK` across all
four WorldView/signal Dockerfiles; plaintext default DB creds baked into k8s manifests; no `sslmode` on
the Postgres pool; no `securityContext`. *Fix:* non-root `USER` + `HEALTHCHECK` + `securityContext`;
creds → Secrets; enable TLS.

**F15 — `settings.db` writer/writer contention + connection leak.** [Opus] ✅ `settings_db.py:162-175,
202,226-235`. Fresh connection per call, no write serialization (only init is locked) → intermittent
`database is locked`; conn leaks on the exception path (no context manager). *Fix:* serialize writes;
use `with` for connection lifecycle.

**F16 — No Prometheus golden-signal metrics in the hub.** [Sonnet M1] ✅ There is `/api/metrics/north-star`
(business metric, `analytics.py:142`) but **no** `http_requests_total` / latency / error metrics; the
WorldView Prometheus scrape config marks the hub as a TODO. *Fix:* add a Prometheus ASGI middleware →
`GET /metrics`.

**F17 — Frontend (HUD v2) fetch calls have no timeout.** [Sonnet M3] ✅ `frontend/src/api/client.ts` has
no `AbortController` (browser default ~300s → hung UI). **Mobile already does it right**
(`mobile/src/api/client.ts:60-67` — AbortController + timeout + retries). *Fix:* mirror the mobile client.

**F18 — TypeScript types hand-maintained, drift from backend.** [Sonnet M8] ✅ `frontend/src/api/types.ts`
is hand-written; backed by routes that lack `response_model=`. *Fix:* add `response_model` →
`openapi-typescript` generated types + CI diff gate.

**F19 — Token lifecycle: static, no expiry/rotation/hash-at-rest.** [Both] ✅ — Sonnet H5 + Opus.
A single static `JARVIS_*_TOKEN`; a leak = full compromise with no revocation but an env change; tokens
live in `localStorage`. *Fix:* TTL + rotation + hashed-at-rest; `POST /admin/rotate-tokens`; consider
read/write split; prefer httpOnly cookie over `localStorage`.

---

### 🟡 Low / hardening / quick wins

- **F20 — No LLM-call retry/backoff.** [Opus] ✅ `resilience.py`'s `@resilient_call` (breaker+backoff)
  is wired for plugins but not the LLM backends; a transient 503 just returns `"[… error]"`. Reuse it.
- **F21 — Plugins eagerly instantiated at boot.** [Sonnet H3] ✅ `plugin_manager.build()` constructs all
  plugins regardless of `enabled`. *Fix:* lazy-instantiate enabled plugins; isolate init failures.
- **F22 — Vector recall is brute-force by default.** [Sonnet H4, corrected] ✅ `memory/store.py:69`
  `InMemoryVectorStore` does O(n·d) numpy cosine — but an **indexed Qdrant/HNSW backend already exists**
  (`qdrant_store.py`, selectable via `VECTOR_BACKEND=qdrant`, `manager.py:24-48`). *Fix:* make Qdrant the
  documented default at scale; no new dep needed.
- **F23 — Load tests are mock-level only.** [Sonnet M2, corrected] ✅ `tests/test_load.py` exists (15/50
  parallel against a `_FakeBackend`), but asserts coarse wall-clock bounds — no real HTTP path, no memory
  contention, no p95. *Fix:* add a real-path concurrency test with percentile budgets.
- **F24 — Configurable scanner patterns.** [Sonnet M5] PII/secret regexes are Python constants → restart
  to update. *Fix:* load custom patterns from `settings.db` with built-in fallback.
- **F25 — Frontend bundle not code-split.** [Sonnet M4] `frontend/vite.config.ts` — add manual chunks.
- **F26 — `@ts-nocheck` everywhere + `strict:false`.** [Both] ✅ 26/27 frontend files carry `@ts-nocheck`;
  mobile is `strict:true` (proof it's doable). *Fix:* remove incrementally; flip toward strict.
- **F27 — Unclosed `httpx.Client`s.** [Opus] ✅ `memory/qdrant_store.py:21`, `ingestion/embedder.py:186`
  — no `close()`/lifecycle.
- **F28 — Skill importer path sanitization.** [Opus] ✅ `skills/importer.py:170` writes an unsanitized
  slug into a path (the marketplace path guards this; the importer doesn't).
- **F29 — Duplicated env-flag helpers.** [Sonnet L2] consolidate `_as_bool`/`_env_flag` (3 different
  truthy conventions across the tree). Folds into F-config below.
- **F30 — CORS values unvalidated.** [Sonnet L5] `web.py` — validate `JARVIS_CORS_ORIGINS`; tighten
  `allow_methods/headers=["*"]` to the verbs actually used.
- **F31 — Frontend loaders lack backoff/feedback.** [Sonnet L6] show a "server starting…" badge with
  exponential backoff instead of silent empty state.

---

### Supply-chain & CI (cluster)

- **F32 — GitHub Actions pinned to floating tags** (incl. release + auto-update with write/publish perms).
  [Opus] ✅ Pin every `uses:` to a commit SHA (Dependabot keeps them fresh).
- **F33 — No Python lockfile** — every dep is an open `>=` range, no hashes; npm *is* locked. [Opus] ✅
  Add `uv`/`pip-tools` lock with hashes.
- **F34 — No `pip-audit`/`safety` in CI.** [Sonnet M6] ✅ Add (warn → block).
- **F35 — Lint is non-blocking; no Python type gate; CodeQL `continue-on-error`.** [Both] ✅
  `ci.yml:40` `--exit-zero`; no mypy/pyright; `codeql.yml:40`. Drop `--exit-zero`; add mypy; add a blocking
  OSS SAST (semgrep/bandit) until CodeQL SARIF is available; un-gate CodeQL when public.
- **F36 — No secret-scanning pre-commit / no `.pre-commit-config.yaml` at all.** [Sonnet L4] ✅ Introduce
  pre-commit with gitleaks/detect-secrets.
- **F37 — No socket-level network block in tests.** [Opus] ✅ conftest relies on `JARVIS_TESTING=1` +
  timeout; a stray real call hangs to the timeout. Add a loopback-only socket guard.
- **F38 — `thirdparty-autoupdate` review discipline.** [Opus] ✅ It opens a PR (does **not** auto-merge —
  Sonnet/Opus both confirmed), but auto-vendored diffs are easy to rubber-stamp; label + require explicit
  human approval of the vendored diff.

---

## 3. Architecture / structural (the expensive stuff)

- **A1 — Orchestrator coupling relocated, not reduced; turn pipeline triplicated.** [Both] ✅ — Opus S2/S3 +
  Sonnet H2/M7. `orchestrator.py` (1,462 LOC) still holds a reference to ~40 subsystems and is passed as
  `self` back into each, with collaborators back-assigning onto it (`orch.writeback = …`). Prompt assembly
  is written 3× (`handle_input`, `handle_input_stream`, `_call_agents_parallel`, `agent.process`);
  `select_backend` runs twice/turn. The `sys.modules` router↔web indirection is a symptom of the same
  import-cycle/coupling root. *Fix:* one `PromptBuilder` + `_preprocess_turn`; extract context/dispatch/
  persist; a service container so collaborators get narrow interfaces (not the god object).
- **A2 — Four UI codebases + a second backend in a second language.** [Opus] ✅ HUD v1 (vanilla + vendored
  global React), HUD v2 (Vite/React/TS), WorldView app, mobile (RN), plus WorldView's Fastify/TS backend
  paralleling the Python hub. Auth/SSE/fetch logic is forked 3–4× (the XSS-vs-`esc()` divergence is proof
  drift is happening). *Fix:* retire HUD v1, make v2 the Tauri target, extract a shared `@jarvis/client`.
- **A3 — Config sprawl.** [Opus] ✅ 121 `os.getenv` across 38 files, 3 truthy-string conventions, host spec
  + default model names (`google/gemma-4-31b-a4b`) hardcoded in ~5 places. *Fix:* one `Config` read once at
  boot; derive agent-policy sets from `agents.yaml` (already loaded). (Absorbs F29.)

---

## 4. Strategic (above the code)

- **The breadth-over-depth pattern is the #1 strategic signal.** [Opus] ✅ ~36 modules carry roadmap
  "H-numbers"; **44 are "offline-testable" with `Null`/injected live rails** (`payments.py`: *"nothing here
  can actually move money"*; `social.py`: `NullSocialClient`). The governance/approval/capability scaffolding
  is real and tested, but the *integration* — the hard, valuable 80% — is deliberately deferred. This produces
  the **illusion of a 48-feature 1.0** when most features are "the safe seam exists, the rail doesn't."
- **Single-maintainer sustainability is the top project risk.** [Opus] ✅ 45 of 50 recent commits are one
  person. The surface area (Python hub + TS WorldView + 4 clients + Rust + mobile + desktop + 44 governed
  features) already exceeds what one person can deepen, secure, and keep current.
- **Recommendation:** pick the 5–6 features that *are* the product, drive them live end-to-end, and park the
  rest behind flags. This decision gates how much of the Phase-2 work below is even worth doing.

---

## 5. Consolidated improvement plan (backlog-ready, phased by gate)

> Drop-in roadmap cluster. Per `AGENTS.md`, pair the merge with a test-count refresh in `BACKLOG.md`.

**Phase 0 — Pre-1.0 blockers (exposed surfaces + data-at-rest)**
- P0-0 **Scope decision** (breadth→depth): name the 5–6 product-defining features; flag-park the rest. *(strategic; gates Phase 2)*
- P0-1 **Secrets at rest** — encrypt credential columns in `settings.db`; encrypt/exclude secrets from backups. (F2)
- P0-2 **"Forget me" correctness** — purge memory.db/transcripts/embeddings/vector/KG; drop the backup-first PII copy. (F1)
- P0-3 **HUD XSS + CSP** — `esc()` the sinks; CSP + security headers; Tauri `csp`. (F3)
- P0-4 **WorldView fail-closed** — no unauthenticated `0.0.0.0`; default loopback; creds→secrets; `sslmode`. (F4, F14)
- P0-5 **Session path-traversal** — validate `session_id`. (F7)

**Phase 1 — Next sprint (correctness + auth lifecycle + CI gates)**
- P1-1 **Token lifecycle** — TTL + rotation + hash-at-rest; rotate endpoint. (F19)
- P1-2 **SSE + async hot path** — cancellation-safe SSE; `add_turn` off the loop. (F8, F9)
- P1-3 **Settings integrity** — schema-validate + audit-log mutations. (F10)
- P1-4 **Audit chain HMAC** — keyed, key outside the DB. (F6)
- P1-5 **Supply-chain/CI** — SHA-pin Actions; Python lockfile; pip-audit; ruff blocking; blocking SAST; conftest socket-block; pre-commit+gitleaks. (F32–F37)
- P1-6 **Sandbox containment tests** — Docker-enabled CI lane. (F5)
- P1-7 **Cypher/WKT/scanner-redact** — allow-list labels; coerce coords; mask `matched_text`. (F11, F12, F13)

**Phase 2 — Post-1.0 (structure, observability, scale, DX)**
- P2-1 **Turn-pipeline de-dup + service container** — `PromptBuilder`/`_preprocess_turn`; retire `orch` back-refs + `sys.modules`. (A1)
- P2-2 **Config consolidation.** (A3, F29)
- P2-3 **Client consolidation** — retire v1; shared `@jarvis/client`; fetch timeouts; remove `@ts-nocheck`. (A2, F17, F26)
- P2-4 **Type-safety codegen** — `response_model` + openapi-typescript + CI diff. (F18)
- P2-5 **Observability + real load tests** — Prometheus `/metrics`; p95 on the real path. (F16, F23)
- P2-6 **Scale + DX** — Qdrant-by-default; lazy plugins; Vite code-split; configurable scanner; retry/backoff on LLM; close httpx clients; CORS/loaders polish. (F20–F25, F27, F28, F30, F31)

---

## Appendix A — Corrected / down-graded claims (kept for honesty)

| Source claim | Reality | Disposition |
|---|---|---|
| Sonnet **M2**: "0 sustained-load tests" | `tests/test_load.py` exists (15/50 parallel) but mock-level, no percentiles | Reframed → F23 |
| Sonnet **H4**: "no vector index" / `memory/vector_store.py` | Wrong file (`memory/store.py`); indexed Qdrant backend already exists & is selectable | Reframed → F22 |
| Sonnet **C1**: `agents/core/secrets/secret_store.py` | Path doesn't exist (`secrets.py`); OAuth tokens *are* encrypted — only `settings.db` keys are plaintext | Core claim kept → F2 |
| Sonnet **M7** fix: "make a singleton" | `app_state` is *already* a module global; `sys.modules` exists to break the web↔routers import cycle | Folded into A1 |
| Sonnet **L4**: "add a step to `.pre-commit-config.yaml`" | No pre-commit config exists at all | Reframed → F36 |
| Sonnet **C2** severity "Critical" | Real, but requires `audit.db` write access; HMAC only helps if key is off-box | Kept as High → F6 |
| Sonnet "test suite is an unqualified positive" | True overall, **except** sandbox containment is untested | Caveat → F5 |
| Sonnet positive #4: ContextVar session isolation | **Verified correct** | Kept as strength #5 |
