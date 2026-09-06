# Memory, Sessions, Checkpoints & Context Engine

This shard documents everything Hermes Agent v2026.8.31 remembers and everything it can rewind:
the built-in curated memory stores (`MEMORY.md` / `USER.md`) and the `memory` tool that edits them;
the pluggable external memory-provider framework (`MemoryManager`, `MemoryProvider` ABC) and all
eight shipped provider plugins (honcho, openviking, mem0, hindsight, holographic, retaindb,
byterover, supermemory); the `ContextEngine` ABC and `plugins/context_engine/` loader; the SQLite
session store (`state.db` schema, FTS5 indexes, triggers, storage layouts) with the whole
`hermes sessions …` command family (list/export/import/delete/prune/archive/optimize/
optimize-storage/clean-markers/repair/repair-routing/recover/stats/rename/pin/unpin/pinned/
retitle-skills/browse), the `session_search` tool, the filesystem checkpoint store
(`hermes checkpoints …` + `/rollback`), and the learning-journey / memory-graph surfaces.

Deliberately left to sibling shards: the compression *algorithm* itself
(`agent/context_compressor.py`, `agent/conversation_compression.py` → agent-core), all gateway
`/memory` and `/sessions` slash commands (gw-slash), Desktop and Web-dashboard session/memory
panels (desktop-*, web-*), TUI overlays (tui), the write-approval framework internals
(`tools/write_approval.py` → agent-core), and the generic plugin installer (optional).

---

### Built-in curated memory (MEMORY.md + USER.md)  `id: memory.builtin-stores`
- **Surface:** Core
- **Where:** Files on disk at `<HERMES_HOME>/memories/MEMORY.md` and `<HERMES_HOME>/memories/USER.md` (default `~/.hermes/memories/`). Rendered into the system prompt as two fenced blocks headed `MEMORY (your personal notes) [<pct>% — <n>/<limit> chars]` and `USER PROFILE (who the user is) [<pct>% — <n>/<limit> chars]`.
- **What it does:** Gives the agent bounded, curated, file-backed recall that survives across sessions. `MEMORY.md` holds the agent's own notes (environment facts, project conventions, tool quirks, lessons); `USER.md` holds what it knows about the user (name, role, preferences, communication style).
- **How it works:** `tools/memory_tool.py:171` `class MemoryStore` owns both stores. `get_memory_dir()` (`tools/memory_tool.py:63`) resolves `get_hermes_home() / "memories"` **dynamically on every call** so a profile switch (HERMES_HOME override) is always honoured. `load_from_disk()` (`tools/memory_tool.py:227`) creates the dir, reads both files, deduplicates entries with `list(dict.fromkeys(...))` (order-preserving, first wins), threat-scans each entry, and captures a **frozen snapshot** `self._system_prompt_snapshot = {"memory": …, "user": …}` via `_render_block()` (`tools/memory_tool.py:751`). The snapshot is what enters the system prompt and never changes mid-session — this preserves the LLM prefix cache. Live edits go straight to disk; the prompt only refreshes at the next session start. Entry storage format: entries joined by the delimiter `ENTRY_DELIMITER = "\n§\n"` (`tools/memory_tool.py:79`). Entries may be multiline. Files are read with `encoding="utf-8-sig"` so a Windows/Notepad BOM is stripped (`tools/memory_tool.py:772`), and written atomically via `atomic_write_text(path, content, tmp_prefix=".mem_")` (`tools/memory_tool.py:900`) so readers never see a truncated file. Block rendering (`_render_block`): a 46-character `═` separator line, the header, another separator, then the `§`-joined content. Header prefixes are exported as `MEMORY_BLOCK_HEADERS = {"memory": "MEMORY (your personal notes)", "user": "USER PROFILE (who the user is)"}` (`tools/memory_tool.py:74`) so compression's prompt-retention check can detect a leftover block.
- **Inputs / options:** Not directly user-editable through a command — you edit via the `memory` tool, the `/memory` slash command family, or by hand-editing the two files. Char limits come from config (`memory.memory_char_limit`, `memory.user_char_limit`). Enable flags: `memory.memory_enabled`, `memory.user_profile_enabled`.
- **Outputs / side effects:** Writes `<HERMES_HOME>/memories/MEMORY.md`, `<HERMES_HOME>/memories/USER.md`, per-file lock files `MEMORY.md.lock` / `USER.md.lock`, and drift snapshots `MEMORY.md.bak.<unix_ts>`.
- **Config / env:** `memory.memory_enabled` (default `true`), `memory.user_profile_enabled` (`true`), `memory.memory_char_limit` (`2200`), `memory.user_char_limit` (`1375`), `memory.write_approval` (`false`), `memory.nudge_interval` (`10`), `memory.provider` (`""`). `HERMES_HOME` selects the profile directory.
- **Edge cases / guards:** Two agent processes must not share one Hermes home — memory writes are automatic and compound (documented caution in `website/docs/user-guide/features/memory.md:22`). Character limits are hard: memory never auto-compacts; an over-budget write returns an error with `current_entries` so the model consolidates. Exact-duplicate adds return success with `"Entry already exists (no duplicate added)."`. Poisoned entries are replaced in the *snapshot* by `[BLOCKED: <filename> entry contained threat pattern(s): <ids>. Removed from system prompt; use memory(action=remove) to delete the original.]` while the live list keeps the raw text so the user can see and delete it (`tools/memory_tool.py:266`).
- **Rebuild notes:** Two plain-text files, entries joined by `\n§\n`, byte-budgeted (not token-budgeted, because chars are model-independent). Load → dedupe → scan → render once per session; mutate → lock → re-read → validate → atomic write. A better version would keep an append-only journal with per-entry ids, timestamps, provenance and decay scores, so consolidation could be automatic and auditable instead of an LLM-driven retry loop.

### `memory` tool  `id: memory.tool-memory`
- **Surface:** Tool
- **Where:** Model-callable tool named `memory`, toolset `memory`, emoji 🧠 (`tools/memory_tool.py:1379` registry.register).
- **What it does:** The single write path into `MEMORY.md` / `USER.md`. Lets the model add, replace, or remove entries — either one at a time or as an atomic batch that is budget-checked only on the final result.
- **How it works:** `memory_tool()` (`tools/memory_tool.py:1075`) dispatches. Batch path: `operations` non-empty → `_apply_batch_write_gate()` → `MemoryStore.apply_batch()` (`tools/memory_tool.py:583`). Single-op path: validates required params BEFORE the approval gate (so an invalid write is never staged), then `_apply_write_gate()` → `store.add/replace/remove`. Every mutating call takes an exclusive lock on a sidecar `<file>.lock` via `MemoryStore._file_lock()` (`tools/memory_tool.py:305`, `fcntl.flock` on POSIX, `msvcrt.locking` on Windows, no-op when neither is importable), re-reads the file under the lock (`_reload_target`), and only then mutates + atomically writes. `replace`/`remove`/`apply_batch` additionally run the **external-drift guard** `_detect_external_drift()` (`tools/memory_tool.py:839`); `add` skips it with `skip_drift=True` because appending cannot clobber. Substring targeting: `old_text` must match exactly one entry (`old_text in entry`); if several *distinct* entries match, the call fails with `"Multiple entries matched '<old_text>'. Be more specific."` plus 80-char previews; if all matches are byte-identical duplicates the first is used.
- **Inputs / options:** JSON schema `MEMORY_SCHEMA` (`tools/memory_tool.py:1259`), `required: ["target"]`.
  - `action` — string enum `add` | `replace` | `remove`. "The action to perform (single-op shape). Omit when using 'operations'."
  - `target` — string enum `memory` | `user`. "Which memory store: 'memory' for personal notes, 'user' for user profile."
  - `content` — string. Required for `add` and `replace` (single-op). Alias `new_text`.
  - `old_text` — string. REQUIRED for `replace` and `remove` (single-op): a short unique substring identifying the entry.
  - `new_text` — string. Alias for `content`; if both are set, `content` wins (`tools/memory_tool.py:1104`).
  - `operations` — array of objects `{action (required, enum add|replace|remove), content, new_text, old_text}`. Applied atomically against the FINAL char budget.
- **Outputs / side effects:** JSON string. Success shape: `{"success": true, "done": true, "target": …, "usage": "<pct>% — <n>/<limit> chars", "entry_count": N, "message": …, "note": "Write saved. This update is complete — do not repeat it."}` — deliberately **does not** echo the entries list, to stop the model re-issuing the same ops (`tools/memory_tool.py:722`). Failure shapes carry `current_entries` and `usage`. Staged shape: `{"success": true, "staged": true, "pending_id": <id>, "message": …}`. Disk: rewrites the whole target file.
- **Config / env:** `memory.memory_enabled`, `memory.user_profile_enabled`, `memory.memory_char_limit`, `memory.user_char_limit`, `memory.write_approval`.
- **Edge cases / guards:** (1) `check_memory_requirements()` (`tools/memory_tool.py:1210`) hides the tool entirely when BOTH stores are disabled; `_build_memory_schema_overrides()` (`tools/memory_tool.py:1332`) narrows the advertised `target` enum to just the enabled store and rewrites the TARGETS paragraph of the description accordingly. (2) `target: null` from strict providers is coerced to `"memory"`. (3) Invalid target → `"Invalid memory target '<t>'. Use 'memory' or 'user'."`; disabled target → `"Built-in <MEMORY.md|USER.md> writes are disabled in memory config."`. (4) Missing `old_text` on replace/remove returns `_missing_old_text_error()` — the current inventory plus a retry instruction rather than a dead-end (issues #43412, #49466). (5) Per-turn consolidation cap: after `_MAX_CONSOLIDATION_FAILURES_PER_TURN = 3` failed at-capacity attempts in one turn, the tool returns a TERMINAL `{"success": false, "done": true, "error": "Memory consolidation failed N times this turn. Stop retrying memory calls …"}` so a fragile replace/add cannot loop the turn to budget exhaustion (#42405); a success resets the counter. (6) Unreadable-but-existing file → `_read_failed_error()` refuses the write ("Treating an unreadable file as empty and saving would wipe existing memory"). (7) Drift → `_drift_error()` refuses, names the `.bak.<ts>` snapshot, and gives remediation text. (8) All add/replace content is threat-scanned at `scope="strict"` via `tools/threat_patterns.first_threat_message` before it touches disk; in a batch, one poisoned op rejects the whole batch with `"Operation <i>: <reason>"`.
- **Rebuild notes:** One tool, three verbs, plus an atomic batch verb; substring-addressed entries; hard char budget evaluated on the post-batch state; lock + re-read + atomic-write on every mutation; refuse rather than guess whenever the on-disk view is uncertain. A better version: content-addressed entry ids so `replace`/`remove` are unambiguous, a CRDT/merge path for concurrent writers instead of a drift refusal, and automatic scored eviction instead of an LLM consolidation loop.

### Memory external-drift guard (`.bak.<ts>` snapshots)  `id: memory.drift-guard`
- **Surface:** Core
- **Where:** Fires transparently inside any `memory` replace / remove / batch call; user sees the error text and a `MEMORY.md.bak.<unix_ts>` file next to the store.
- **What it does:** Refuses to rewrite a memory file whose on-disk content was not written by the memory tool, so a shell append, a `patch`-tool edit, a manual edit, or a sister session's write is never silently discarded.
- **How it works:** `MemoryStore._detect_external_drift(target, raw)` (`tools/memory_tool.py:839`) runs on the *same* raw snapshot the checked read produced (an earlier version re-read the file and treated a failed second read as "no drift", opening a lost-update window). Two signals: (1) **round-trip mismatch** — `raw.strip() != ENTRY_DELIMITER.join([e.strip() for e in raw.split(ENTRY_DELIMITER) if e.strip()])`; (2) **entry-size overflow** — `max(len(e) for e in parsed) > char_limit`, i.e. a single parsed entry is larger than the whole store's budget, which no tool-written entry can be. On detection it writes `path.with_suffix(path.suffix + f".bak.{int(time.time())}")` and returns that path; the caller aborts with `_drift_error()`.
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** `<HERMES_HOME>/memories/MEMORY.md.bak.<ts>` or `USER.md.bak.<ts>`. If the backup write itself fails, the returned string is `"<path> (BACKUP FAILED — file unchanged on disk)"`.
- **Config / env:** Uses `memory.memory_char_limit` / `memory.user_char_limit` for signal 2.
- **Edge cases / guards:** `add` deliberately bypasses the guard (`skip_drift=True`) because appending cannot clobber — but it still aborts on `_READ_FAILED`. Empty/whitespace file → no drift.
- **Rebuild notes:** Detect "this file is not shaped like our serializer's output" before any read-modify-write; snapshot then refuse. Better: store a content hash in a sidecar and do a real 3-way merge instead of refusing.

### Memory system-prompt threat sanitization  `id: memory.snapshot-sanitizer`
- **Surface:** Core
- **Where:** Invisible; the effect is a `[BLOCKED: …]` placeholder inside the MEMORY/USER block of the system prompt.
- **What it does:** Stops a poisoned memory file (supply chain, compromised tool, sister-session write) from injecting instructions into the system prompt, while still letting the user see and delete the offending entry.
- **How it works:** `MemoryStore._sanitize_entries_for_snapshot(entries, filename)` (`tools/memory_tool.py:266`) runs `tools.threat_patterns.scan_for_threats(entry, scope="strict")` on each entry at load time. On a hit it logs `"Memory entry from %s blocked at load time: %s"` and substitutes `[BLOCKED: <filename> entry contained threat pattern(s): <ids>. Removed from system prompt; use memory(action=remove) to delete the original.]` into the snapshot only. Entries already starting with `[BLOCKED:` and empty entries pass through. Scanning is deterministic from disk bytes so the snapshot stays byte-stable for the whole session (prefix-cache invariant).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Altered system-prompt block; a WARNING log line; the raw entry remains in `memory_entries` / `user_entries`.
- **Config / env:** n/a (pattern set lives in `tools/threat_patterns.py`).
- **Edge cases / guards:** Uses the broadest ("strict") pattern scope precisely because memory is a frozen snapshot that persists across sessions until explicitly removed.
- **Rebuild notes:** Scan at snapshot-build time, not at write time only; never drop silently — replace with a visible marker that names the remediation command.

### Memory write approval gate (`memory.write_approval`)  `id: memory.write-approval`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `memory: write_approval: true|false`; user-facing review via `/memory pending`, `/memory approve <id>`, `/memory reject <id>`, `/memory approval on|off`.
- **What it does:** When on, every memory write (foreground turns and the background self-improvement review) must be approved before it lands. Interactive CLI prompts inline; everywhere else the write is staged.
- **How it works:** `_apply_write_gate(action, target, content, old_text)` (`tools/memory_tool.py:947`) builds a human summary (`add to memory` / `replace in user profile` / `remove from memory`) plus a detail body (for replace: `old: <old_text>\nnew: <content>`), then calls `write_approval.evaluate_gate(wa.MEMORY, inline_summary=…, inline_detail=…)`. `decision.allow` → return None (real write proceeds). `decision.blocked` → `tool_error(decision.message, success=False)`. Otherwise `wa.stage_write(wa.MEMORY, payload, summary=f"{summary}: {detail[:120]}", origin=wa.current_origin())` and return the staged JSON. Batch equivalent: `_apply_batch_write_gate()` (`tools/memory_tool.py:1001`) gates the whole batch as one unit with a per-op detail listing (`- remove: <old_text>`, `- replace: <old_text> -> <content>`, `- <action>: <content>`). Approved writes are replayed by `apply_memory_pending(payload, store)` (`tools/memory_tool.py:1229`) which bypasses the gate and dispatches on `payload["action"]` ∈ `batch|add|replace|remove`. Staged records live under `~/.hermes/pending/`. If `tools.write_approval` cannot be imported the gate **fails open**.
- **Inputs / options:** `true` / `false`. Slash commands: `/memory pending`, `/memory approve <id|all>`, `/memory reject <id|all>`, `/memory approval on|off`.
- **Outputs / side effects:** Staged records on disk; `{"success": true, "staged": true, "pending_id": …}` tool results; `MemoryManager.notify_memory_tool_write` explicitly refuses to mirror staged writes to external providers.
- **Config / env:** `memory.write_approval` (default `false`). Sibling: `skills.write_approval`.
- **Edge cases / guards:** Validation happens before staging so an invalid write cannot be queued. `_memory_tool_result_succeeded()` treats `staged is True` as *not* committed.
- **Rebuild notes:** Gate only the mutating verbs; stage a replayable payload, not a diff; validate before staging; fail open on gate-module import error so memory never becomes unusable.

### `load_on_disk_store()` — agent-less memory access  `id: memory.load-on-disk-store`
- **Surface:** Core
- **Where:** Used by the messaging gateway, the Desktop GUI, and the bare CLI `/memory` handler.
- **What it does:** Builds a fresh `MemoryStore` honouring the configured char limits and enable flags, for any context that has no live agent but still needs to read memory or apply an approved write.
- **How it works:** `tools/memory_tool.py:910`. Defaults 2200/1375/enabled/enabled; loads config via `hermes_cli.config.load_config()`, reads `get_builtin_memory_config()` and `get_builtin_memory_store_flags()`, constructs the store and calls `load_from_disk()`. Any exception falls back to the built-in defaults so `/memory` can never break on a missing/unreadable config.
- **Inputs / options:** none.
- **Outputs / side effects:** Returns a loaded `MemoryStore`.
- **Config / env:** `memory.memory_char_limit`, `memory.user_char_limit`, `memory.memory_enabled`, `memory.user_profile_enabled`.
- **Edge cases / guards:** Mirrors exactly how `agent/agent_init.py` builds the live store, so an approval applied without an agent enforces the same caps.
- **Rebuild notes:** One constructor shared by every surface; never let a headless surface use different limits than the agent.

### `MemoryManager` — provider orchestration  `id: memory.manager`
- **Surface:** Core
- **Where:** `agent/memory_manager.py`; single integration point in `run_agent.py`.
- **What it does:** Owns the built-in provider plus **at most one** external provider, fans every lifecycle hook out to them, routes provider tool calls, and keeps all provider I/O off the turn thread.
- **How it works:** `class MemoryManager` (`agent/memory_manager.py:415`). `add_provider()` (`:474`) accepts `name == "builtin"` unconditionally; a second non-builtin provider is rejected with `"Rejected memory provider '<x>' — external provider '<y>' is already registered. Only one external memory provider is allowed at a time. Configure which one via memory.provider in config.yaml."`. Tool names are indexed into `_tool_to_provider`; a provider tool that shadows a name in `toolsets._HERMES_CORE_TOOLS` is refused at the door (built-ins always win, #40466), and a duplicate name across providers is ignored with a warning. Background work: `_get_sync_executor()` lazily creates a `tools.daemon_pool.DaemonThreadPoolExecutor(max_workers=1, thread_name_prefix="mem-sync")` — a single worker so turn N's write lands before turn N+1's, and daemon threads so a wedged provider cannot block interpreter exit. `_submit_background(fn, kind="write"|"prefetch")` wraps `fn` in `contextvars.copy_context().run` so the caller's ContextVar-scoped `HERMES_HOME` profile override reaches the worker. Futures are tracked in `_background_futures: Dict[Future, str]` by durability class.
- **Inputs / options:** Constructor kwarg `external_prefetch_timeout` (default `_EXTERNAL_PREFETCH_TIMEOUT_S = 8.0`, must be > 0). Methods: `add_provider`, `providers` (property), `get_provider(name)`, `build_system_prompt()`, `prefetch_all(query, session_id="")`, `describe_recall()`, `queue_prefetch_all(query, session_id="")`, `sync_all(user_content, assistant_content, session_id="", messages=None)`, `flush_pending(timeout=None)`, `get_all_tool_schemas()`, `get_all_tool_names()`, `has_tool(name)`, `handle_tool_call(name, args, **kw)`, `on_turn_start(turn_number, message, **kw)`, `on_session_end(messages)`, `commit_session_boundary_async(messages, new_session_id, parent_session_id="", reason="new_session")`, `on_session_switch(new_session_id, parent_session_id="", reset=False, rewound=False, **kw)`, `supports_pre_compress_checkpoint(api_version=2)`, `on_pre_compress(messages, evidence_messages=None, require_checkpoint=False, checkpoint_api_version=2)`, `on_memory_write(action, target, content, metadata=None)`, `notify_memory_tool_write(tool_result, tool_args, build_metadata=None)`, `on_delegation(task, result, child_session_id="", **kw)`, `shutdown_all()`, `shutdown_drain_state` (property), `initialize_all(session_id, **kw)`.
- **Outputs / side effects:** System-prompt text, injected `<memory-context>` blocks, provider-side writes, tool schemas appended to the agent tool surface.
- **Config / env:** `memory.provider` selects the external plugin. `agent.disabled_toolsets` / platform toolsets gate provider tools.
- **Edge cases / guards:** Every hook is individually try/except'd so one provider's failure never blocks another. `initialize_all()` auto-injects `hermes_home=str(get_hermes_home())` into kwargs so providers never import `get_hermes_home` themselves. `shutdown_all()` first calls `_drain_sync_executor()` (bounded by `_SYNC_DRAIN_TIMEOUT_S = 5.0`), then shuts providers down in **reverse** registration order.
- **Rebuild notes:** One manager, one external provider, one serialized daemon worker, contextvar propagation, per-hook exception isolation, bounded shutdown drain with an explicit "abandoned" report. A better version would give each provider its own bounded queue with backpressure and a circuit breaker instead of a single shared worker.

### Memory prefetch (pre-turn recall)  `id: memory.prefetch`
- **Surface:** Core
- **Where:** Runs before every API call; the user sees its result only as improved answers plus the recall indicator line.
- **What it does:** Asks each registered provider for context relevant to the upcoming user message and merges the non-empty results.
- **How it works:** `MemoryManager.prefetch_all(query, session_id="")` (`agent/memory_manager.py:585`) first calls `_strip_skill_scaffolding()` → `agent.skill_commands.extract_user_instruction_from_skill_message(text)`; a bare `/skill` invocation with no user instruction returns falsy and the whole turn is skipped (nothing worth recalling). Then, per provider, `_prefetch_provider()` (`:606`): the **builtin** provider is called inline; an **external** provider is run on a daemon thread named `memory-prefetch-<name>` whose target is `functools.partial(contextvars.copy_context().run, _run)`, joined with `self._external_prefetch_timeout` (default 8.0 s). If a previous prefetch thread for that provider is still alive the turn is skipped with `"Memory provider '%s' prefetch is still running; skipping this turn"`. On timeout: `"Memory provider '%s' prefetch timed out after %.1fs; skipping it until the stuck call returns"` and `""` is returned. Exceptions raised on the thread are re-raised on the caller. Results are joined with `"\n\n"`.
- **Inputs / options:** `query` (the user message), `session_id`.
- **Outputs / side effects:** A single merged context string, later wrapped by `build_memory_context_block()`.
- **Config / env:** provider-specific; the manager-level timeout is a constructor arg, not a config key.
- **Edge cases / guards:** `agent/memory_provider.py:90` `is_trivial_prompt()` is the shared gate used by the core per-turn prefetch path — empty/whitespace input, anything starting with `/`, and bare greetings/acknowledgements are treated as trivial and skip recall entirely.
- **Rebuild notes:** Strip scaffolding once for all providers; hard-timeout externals on a daemon thread; never let two prefetches for the same provider overlap.

### `<memory-context>` fencing and sanitization  `id: memory.context-fence`
- **Surface:** Core
- **Where:** Injected into the model's message list; never shown verbatim to the user.
- **What it does:** Wraps recalled memory in a machine-recognisable fence with a system note so the model treats it as reference data, not as new user input — and scrubs any leakage of that fence back out of model output.
- **How it works:** `build_memory_context_block(raw_context)` (`agent/memory_manager.py:405`) returns exactly:
  ```
  <memory-context>
  [System note: The following is recalled memory context, NOT new user input. Treat as authoritative reference data — this is the agent's persistent memory and should inform all responses.]

  <clean>
  </memory-context>
  ```
  `sanitize_context(text)` (`agent/memory_manager.py:242`) strips, in order: whole `<memory-context>…</memory-context>` blocks (`_INTERNAL_CONTEXT_RE`), the system-note line (`_INTERNAL_NOTE_RE`, which matches both the "informational background data" and "authoritative reference data" wordings), then any stray open/close fence tags (`_FENCE_TAG_RE`, case-insensitive, tolerant of internal whitespace). If the provider had pre-wrapped its output, a warning `"memory provider returned pre-wrapped context; stripped"` is logged.
- **Inputs / options:** n/a.
- **Outputs / side effects:** The fenced string appended to the request.
- **Config / env:** n/a.
- **Edge cases / guards:** Empty/whitespace context returns `""` (no block at all).
- **Rebuild notes:** One canonical fence, one canonical note, one sanitizer used on both ingress (provider output) and egress (model output).

### `StreamingContextScrubber` — split-fence leak guard  `id: memory.streaming-scrubber`
- **Surface:** Core
- **Where:** Wraps the streaming delta path so a `<memory-context>` span opened in one chunk and closed in a later chunk never reaches the UI.
- **What it does:** Runs a small state machine across streaming deltas, holding back partial tag tails and discarding everything inside a fence span.
- **How it works:** `class StreamingContextScrubber` (`agent/memory_manager.py:251`). API: `feed(text) -> visible`, `flush() -> trailing`, `reset()`. `_OPEN_TAG = "<memory-context>"`, `_CLOSE_TAG = "</memory-context>"`. Inside a span it searches for the close tag; if absent it holds back `_max_partial_suffix(buf, CLOSE_TAG)` characters and drops the rest. Outside a span it uses `_find_boundary_open_tag()` — an open tag only counts when `_is_block_boundary()` (nothing but whitespace since the last newline, tracked across feeds by `_at_block_boundary`) AND `_has_block_opener_suffix()` (the character right after the tag is `\r` or `\n`). `_max_pending_open_suffix()` holds a complete boundary tag back until the next character confirms it. `flush()` inside an unterminated span discards the buffer (leaking partial memory context is worse than a truncated answer); otherwise it emits the held tail verbatim.
- **Inputs / options:** `feed(str)`, `flush()`, `reset()`.
- **Outputs / side effects:** The visible portion of the stream.
- **Config / env:** n/a.
- **Edge cases / guards:** Re-entrant per agent instance; callers starting a new top-level response must construct a fresh scrubber or call `reset()`.
- **Rebuild notes:** Never regex a stream — hold back at most `len(tag)-1` characters, track block-boundary state across chunks, and fail closed at flush.

### Deterministic recall indicator (`describe_recall`)  `id: memory.recall-indicator`
- **Surface:** Core
- **Where:** A status line emitted in chat, e.g. `👁️ Hindsight — recalled 3 memories` or `🧠 Provider — recalled 1 memory`.
- **What it does:** Shows the user that memory was actually used this turn, independently of whether the model chose to mention it.
- **How it works:** `MemoryManager.describe_recall()` (`agent/memory_manager.py:669`) is called right after `prefetch_all` on the same turn thread. It collects each provider's `recall_status()` → `RecallStatus(provider_label, count, glyph=INDICATOR_GLYPH)` (`agent/memory_provider.py:55`). Rendering: `count == 1` → `"recalled 1 memory"`; `count > 1` → `f"recalled {count} memories"`; `count <= 0` → `"recalled relevant memory"` (content injected but no discrete count, e.g. a synthesized reflect answer). Segments are joined with two spaces. Providers returning `None` contribute nothing; a raising `recall_status()` is logged at debug and skipped.
- **Inputs / options:** n/a.
- **Outputs / side effects:** A one-line string the caller emits unconditionally (empty when nothing was injected).
- **Config / env:** Default glyph `INDICATOR_GLYPH = "🧠"` (`agent/memory_provider.py:52`); providers override per status (Hindsight uses `👁️`).
- **Edge cases / guards:** Must reflect only the LAST prefetch — never a stale prior count.
- **Rebuild notes:** Derive the indicator from provider state, not from model text; render 0 as a generic phrase, never "0 memories".

### Post-turn memory sync (`sync_all`)  `id: memory.sync-all`
- **Surface:** Core
- **Where:** Runs after every completed turn, off the turn thread.
- **What it does:** Persists the finished user/assistant exchange to every provider without holding the turn open.
- **How it works:** `MemoryManager.sync_all(user_content, assistant_content, session_id="", messages=None)` (`agent/memory_manager.py:739`). Skill scaffolding is stripped first; a bare skill invocation skips the sync. The fan-out closure is submitted via `_submit_background(_run)` — NOT run inline: a misconfigured Hindsight daemon was observed blocking ~298 s, which kept `run_conversation` open and made every interface mark the agent "running" for minutes. `_provider_sync_accepts_messages(provider)` (`:723`) inspects `sync_turn`'s signature and passes `messages=` only when the provider accepts it (or has `**kwargs`); signature-inspection failure defaults to True. A raising provider logs `"Memory provider '%s' sync_turn failed: %s"` at WARNING and the loop continues.
- **Inputs / options:** `user_content`, `assistant_content`, `session_id`, `messages` (OpenAI-style list as of the completed turn, including tool calls and results).
- **Outputs / side effects:** Provider-side durable writes; nothing returned.
- **Config / env:** n/a.
- **Edge cases / guards:** Writes are serialized through the single worker so turn N lands before turn N+1 — providers need no ordering logic of their own.
- **Rebuild notes:** Never do provider I/O on the turn thread; serialize writes; strip prompt scaffolding once, centrally.

### `queue_prefetch_all` — next-turn warm-up  `id: memory.queue-prefetch`
- **Surface:** Core
- **Where:** Runs after each turn completes.
- **What it does:** Asks providers to start recalling for the *next* turn in the background, so the next `prefetch()` can return a cached result instantly.
- **How it works:** `agent/memory_manager.py:701`. Skips when there are no providers or when skill-stripping yields nothing. Submits one closure calling `provider.queue_prefetch(clean_query, session_id=session_id)` for each provider via `_submit_background(_run, kind="prefetch")`; failures are debug-logged only. Default `MemoryProvider.queue_prefetch` is a no-op.
- **Inputs / options:** `query`, `session_id`.
- **Outputs / side effects:** Provider-internal cache warm-up.
- **Config / env:** n/a.
- **Edge cases / guards:** Tracked under the `"prefetch"` durability class so shutdown can abandon prefetches separately from writes.
- **Rebuild notes:** Split "warm the cache" from "write the turn" so shutdown can drop the former and must not drop the latter.

### Session-boundary commit (`commit_session_boundary_async`)  `id: memory.session-boundary-commit`
- **Surface:** Core
- **Where:** Fires on `/new` (session rotation) and equivalent boundaries.
- **What it does:** Guarantees end-of-session extraction runs strictly before the provider rebinds to the new session id, without blocking the `/new` command.
- **How it works:** `agent/memory_manager.py:993`. Both hooks are submitted as ONE task on the manager's single background worker: `on_session_end(snapshot)` then `on_session_switch(new_session_id, parent_session_id=…, reset=True, reason=…)`. Running extraction inline blocked `/new` for the whole LLM round trip (#16454); running it on an ad-hoc thread raced the inline switch (transcript misattributed to the new session id, double-ingest of the old turn buffer, cleared new-session buffers). FIFO ordering on the shared worker also serializes end→switch against every per-turn `sync_all` and prefetch. If the executor is unavailable, `_submit_background` degrades to inline execution (the pre-#16454 behaviour: slow but correct).
- **Inputs / options:** `messages`, `new_session_id`, `parent_session_id=""`, `reason="new_session"`.
- **Outputs / side effects:** Provider-side extraction + rebinding.
- **Config / env:** n/a.
- **Edge cases / guards:** No-op when no providers are registered. `messages` is snapshotted with `list(messages or [])` before queuing.
- **Rebuild notes:** Order-sensitive hook pairs must be submitted as one task on one FIFO worker, never as two.

### `on_session_switch` fan-out  `id: memory.session-switch`
- **Surface:** Core
- **Where:** Fires on `/resume`, `/branch`, `/reset`, `/new`, the gateway equivalents, and context compression.
- **What it does:** Tells providers the agent's `session_id` rotated so cached per-session state (`_session_id`, `_document_id`, turn buffers, counters) is refreshed and later writes land in the right record.
- **How it works:** `agent/memory_manager.py:1035`. No-op on empty `new_session_id`. `rewound=True` is forwarded **only when set**, deliberately — passing `rewound=False` unconditionally would pollute every provider's `**kwargs` on the common paths and break exact-dict assertions. `reset=True` marks a genuinely new conversation (`/reset`, `/new`) and tells providers to flush accumulated per-session buffers; `reset=False` is used for `/resume`, `/branch` and compression where the logical conversation continues under a new id. `parent_session_id` carries lineage: fork lineage for `/branch`, continuation lineage for compression, the session being left for `/resume`.
- **Inputs / options:** `new_session_id`, `parent_session_id=""`, `reset=False`, `rewound=False`, `**kwargs`.
- **Outputs / side effects:** Provider-side state refresh.
- **Config / env:** n/a.
- **Edge cases / guards:** Per-provider try/except with a debug log; providers keep running (no teardown).
- **Rebuild notes:** Distinguish "new conversation" from "same conversation, new id" from "same id, truncated transcript" — three different provider actions.

### Pre-compress hook + checkpoint API v2  `id: memory.pre-compress-checkpoint`
- **Surface:** Core
- **Where:** Runs immediately before context compression discards messages.
- **What it does:** Lets providers extract insights from the about-to-be-discarded transcript and contribute text to the compression summary prompt; optionally makes compression fail-closed unless a provider durably checkpointed the evidence.
- **How it works:** `MemoryManager.on_pre_compress(messages, evidence_messages=None, require_checkpoint=False, checkpoint_api_version=2)` (`agent/memory_manager.py:1103`). `PRE_COMPRESS_CHECKPOINT_API_VERSION = 2` (`agent/memory_provider.py:48`); providers without the attribute are treated as `_LEGACY_PRE_COMPRESS_API_VERSION = 1` (`agent/memory_manager.py:41`) — best-effort semantics, raw message list. A provider advertising ≥ the requested version receives `evidence_messages` (the host-normalized direct-evidence list) when supplied, otherwise the raw list. `_accepts_require_checkpoint(fn)` (`agent/memory_manager.py:44`) inspects the signature and only passes `require_checkpoint=` when the provider declares it or has `**kwargs` — so a v2 provider written against the original one-arg docs example does not die on an unexpected kwarg. Under `require_checkpoint=True`, a checkpoint provider's exception is **re-raised** so the caller can keep the uncompressed transcript; if no checkpoint provider succeeded, the manager raises `RuntimeError("No active memory provider completed pre-compress checkpoint API v<N>")`. Non-empty returns are joined with `"\n\n"`. `supports_pre_compress_checkpoint(api_version=2)` (`:1082`) reports whether any active provider guarantees support.
- **Inputs / options:** `messages`, `evidence_messages`, `require_checkpoint`, `checkpoint_api_version`.
- **Outputs / side effects:** Text merged into the compression summary prompt; possibly an exception that aborts compression.
- **Config / env:** `compression.checkpoint_required` (default `false`) is the config that turns on the strict mode.
- **Edge cases / guards:** v1 providers never see the requirement signal; a non-int `pre_compress_checkpoint_api_version` is skipped in `supports_…` and treated as legacy in `on_pre_compress`.
- **Rebuild notes:** Version the hook contract on the provider object, sniff the callable signature before passing new kwargs, and make "fail closed" an explicit per-call flag rather than a global mode.

### Mirroring built-in memory writes to providers (`notify_memory_tool_write`)  `id: memory.mirror-writes`
- **Surface:** Core
- **Where:** Called by the agent loop right after the built-in `memory` tool runs.
- **What it does:** Forwards committed built-in memory edits to the external provider so both stores stay in step.
- **How it works:** `agent/memory_manager.py:1272`. Gate: `_memory_tool_result_succeeded(result)` (`:1247`) fails closed — a non-JSON string, a non-dict, a missing `success`, or `staged is True` all return False. Then the single-op and batch shapes are expanded into a uniform op list (`operations` if a non-empty list, else one synthetic op from `action`/`content`/`old_text`). Only `_MIRRORED_MEMORY_ACTIONS = {"add", "replace", "remove"}` are mirrored. Per op it builds metadata from the agent-side `build_metadata()` callable (the loop knows session/task/tool-call provenance the manager does not), adds `metadata["old_text"]` when present, and calls `on_memory_write(action, target, content, metadata=metadata)`. `on_memory_write` (`agent/memory_manager.py:1221`) **skips the builtin provider** (it is the source) and adapts to each provider's signature via `_provider_memory_write_metadata_mode()` (`:1193`): `"keyword"` when `**kwargs` or a named `metadata` parameter exists, `"positional"` when ≥4 positional-capable parameters, else `"legacy"` (three args only).
- **Inputs / options:** `tool_result`, `tool_args`, `build_metadata`.
- **Outputs / side effects:** Provider-side mirrored writes. Documented metadata keys: `write_origin`, `execution_context`, `session_id`, `parent_session_id`, `platform`, `tool_name`, plus `old_text`.
- **Config / env:** n/a.
- **Edge cases / guards:** `target` defaults to `"memory"`. Non-dict ops in the batch are skipped. Every failure is debug-logged, never raised.
- **Rebuild notes:** Mirror only committed writes; adapt to three historical hook signatures rather than breaking old plugins; carry provenance metadata so the remote store can attribute the write.

### Provider tool injection into the agent surface  `id: memory.provider-tool-injection`
- **Surface:** Core
- **Where:** Runs at agent init; effect is extra model-callable tools (e.g. `honcho_reflect`, `mem0_search`).
- **What it does:** Appends each external memory provider's tool schemas to the agent's tool list, subject to the same gate that decides whether the provider's system-prompt block is shown.
- **How it works:** `inject_memory_provider_tools(agent)` (`agent/memory_manager.py:165`) reads `agent._memory_manager` and `agent.tools`, checks `memory_provider_tools_exposed(agent)` (`:145`), then for each schema from `get_all_tool_schemas()` runs `normalize_tool_schema()` (`:83`) and appends `{"type": "function", "function": schema}` plus the name into `agent.valid_tool_names`. `normalize_tool_schema` unwraps an already-OpenAI-shaped entry (`{"type":"function","function":{…}}`) so double-wrapping cannot produce a nameless function — a bug that made strict providers (DeepSeek) reject the ENTIRE request with `tools[N].function: missing field name` (HTTP 400) and break every turn (#47707); anything without a resolvable string name returns `None` and is skipped with a warning. `memory_provider_tools_enabled(enabled_toolsets, disabled_toolsets, memory_tool_present=False)` (`:117`): `"memory"` in `disabled_toolsets` → False; `memory_tool_present` → True; `enabled_toolsets is None` → True; empty list → False; `"memory"` in the list → True; otherwise resolve each named toolset via `toolsets.resolve_toolset(name)` and return True if any expands to include `memory`.
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** Returns the count of tools added; mutates `agent.tools` and `agent.valid_tool_names`.
- **Config / env:** `agent.disabled_toolsets`, per-platform `platform_toolsets`, `toolsets`.
- **Edge cases / guards:** When a provider is configured but the memory toolset is gated off, an INFO line names the providers and says "provider tools and system-prompt block are both withheld" — a silent `return 0` made #81014 undiagnosable. Provider and prompt block are gated together so the prompt never advertises tools that do not exist.
- **Rebuild notes:** Normalize schemas defensively; one gate function shared by tool injection and prompt assembly; log loudly when a configured capability is suppressed.

### `MemoryProvider` ABC — the plugin contract  `id: memory.provider-abc`
- **Surface:** Core
- **Where:** `agent/memory_provider.py`; plugins ship in `plugins/memory/<name>/` and are activated via `memory.provider`.
- **What it does:** Defines every method a memory backend can implement, the semantics of each lifecycle hook, and the config-schema format `hermes memory setup` walks the user through.
- **How it works:** `class MemoryProvider(ABC)` (`agent/memory_provider.py:110`). Class attribute `pre_compress_checkpoint_api_version = 1`.
  - **Abstract:** `name` (property), `is_available() -> bool` (must not make network calls — config + installed deps only), `initialize(session_id, **kwargs)`, `get_tool_schemas() -> List[dict]`.
  - **Core overridables:** `unavailable_reason() -> str` (short actionable hint surfaced by the caller's "provider unavailable" warning, since a provider that reports unavailable is never initialized), `system_prompt_block() -> str` (STATIC info only), `prefetch(query, session_id="") -> str`, `queue_prefetch(query, session_id="")`, `recall_status() -> Optional[RecallStatus]`, `sync_turn(user_content, assistant_content, session_id="", messages=None)`, `handle_tool_call(name, args, **kwargs) -> str` (must return a JSON string; default raises `NotImplementedError`), `shutdown()`.
  - **Optional hooks:** `on_turn_start(turn_number, message, **kwargs)` (kwargs may include `remaining_tokens`, `model`, `platform`, `tool_count`), `on_session_end(messages)`, `on_session_switch(new_session_id, parent_session_id="", reset=False, rewound=False, **kwargs)`, `on_pre_compress(messages) -> str`, `on_delegation(task, result, child_session_id="", **kwargs)` (parent-side observation; the subagent itself runs with `skip_memory=True`), `on_memory_write(action, target, content, metadata=None)`, `backup_paths() -> List[str]`.
  - **Setup surface:** `get_config_schema() -> List[dict]` with per-field keys `key`, `description`, `secret` (default False → goes to `.env`), `required`, `default`, `choices`, `type` (`text|integer|number|boolean`), `minimum`, `maximum`, `step`, `url`, `env_var`; and `save_config(values, hermes_home)` for providers with a native config file. New plugins MUST implement one of the two.
  - `initialize()` kwargs always include `hermes_home` and `platform` ("cli", "telegram", "discord", "cron", …); may include `agent_context` (`primary|subagent|cron|flush` — providers should skip writes for non-primary contexts because cron system prompts would corrupt user representations), `agent_identity` (profile name), `agent_workspace`, `parent_session_id`, `user_id`, `user_id_alt`.
- **Inputs / options:** as listed above.
- **Outputs / side effects:** n/a (interface).
- **Config / env:** `memory.provider`.
- **Edge cases / guards:** `backup_paths()` must be callable without `initialize()` and without network; `hermes backup` captures only paths that exist and live under the user's home into a reserved `_external/` subtree, and `hermes import` restores them — paths outside `$HOME` are skipped for safety.
- **Rebuild notes:** Keep abstract surface minimal (4 methods), everything else defaulted; declare external on-disk state explicitly so backup/restore is complete; document which hooks fire on which lifecycle event.

### `is_trivial_prompt()` — shared recall gate  `id: memory.trivial-prompt`
- **Surface:** Core
- **Where:** `agent/memory_provider.py:90`; used by the core per-turn prefetch gate (`agent/turn_context.py`, `run_agent.py`) and by provider-side classifiers (`plugins/memory/honcho`).
- **What it does:** Returns True for prompts that carry no semantic signal, so memory recall (and its blocking network round-trip) is skipped.
- **How it works:** `TRIVIAL_PROMPT_RE` (`agent/memory_provider.py:81`) is anchored at `^` and matches one of: `yes|no|ok|okay|sure|thanks|thank you|y|n|yep|nope|yeah|nah|hi|hey|hello|yo|sup|continue|go ahead|do it|proceed|got it|cool|nice|great|done|next|lgtm|k`, followed only by whitespace or punctuation from the class `[\s!?.:;,"'~‘’“”—–…()\[\]{}<>*&^%$#@!+=\` ]*$`, case-insensitive. `is_trivial_prompt()` additionally returns True for `None`/empty/whitespace-only text and for anything starting with `/` (slash commands).
- **Inputs / options:** `text: Optional[str]`.
- **Outputs / side effects:** bool.
- **Config / env:** n/a.
- **Edge cases / guards:** The trailing-character class means `"hi!"`, `"hey."`, `"thanks :)"`, `"done???"` all match, while `"k8s"`, `"yolo"`, `"note"`, `"hindsight"` do NOT (a trivial word must not merely be a prefix).
- **Rebuild notes:** One regex, one function, shared by host and plugins so the two can never drift apart.

### Memory shutdown drain  `id: memory.shutdown-drain`
- **Surface:** Core
- **Where:** Process teardown; observable via `MemoryManager.shutdown_drain_state` and a WARNING log line.
- **What it does:** Gives queued memory writes a bounded chance to land before providers are torn down, then explicitly reports what was abandoned.
- **How it works:** `_drain_sync_executor()` (`agent/memory_manager.py:1385`) sets `_shutting_down`, detaches the executor under the lock, snapshots tracked futures, and records `{"status": "draining"|"drained", "abandoned_writes": 0, "abandoned_prefetches": 0, "active_tasks": <not-done count>}`. Then `executor.shutdown(wait=False, cancel_futures=False)` (closes submission without touching the FIFO) and `concurrent.futures.wait(tracked, timeout=_SYNC_DRAIN_TIMEOUT_S)` with `_SYNC_DRAIN_TIMEOUT_S = 5.0` (`agent/memory_manager.py:78`). Anything still pending is `future.cancel()`ed and counted by durability class; uncancellable futures count as `active_tasks`. Final state `"timed_out"` plus the log line `"Memory shutdown drain timed out after %.2fs; abandoning %d queued memory write(s) and %d queued prefetch(es); %d active task(s) remain detached"`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `shutdown_drain_state` dict snapshot; providers then shut down in reverse order.
- **Config / env:** n/a.
- **Edge cases / guards:** Late `_submit_background` calls during shutdown are rejected with `"Memory manager is shutting down; rejecting late %s task"`. Worker threads are daemon, so anything still wedged dies with the interpreter.
- **Rebuild notes:** Bounded drain + explicit abandonment accounting beats both "wait forever" and "kill silently".

### `flush_pending()` — memory write barrier  `id: memory.flush-pending`
- **Surface:** Core
- **Where:** Called at real session boundaries and by tests that need deterministic provider state.
- **What it does:** Blocks until every previously submitted sync/prefetch task has run.
- **How it works:** `agent/memory_manager.py:879`. Because the executor has exactly one worker, submitting a no-op sentinel and waiting on it is a full barrier. Returns True when no executor exists or the sentinel completed within `timeout`; False on timeout; True when the executor is already shut down (`RuntimeError` → nothing pending).
- **Inputs / options:** `timeout: Optional[float]`.
- **Outputs / side effects:** bool.
- **Config / env:** n/a.
- **Edge cases / guards:** Only correct because `max_workers=1`.
- **Rebuild notes:** A single-worker queue makes a barrier trivial; with N workers you need a real fence.

### `hermes memory` (command group)  `id: memory.cli-memory`
- **Surface:** CLI
- **Where:** `hermes memory [-h] {setup,status,off,reset} ...`
- **What it does:** Sets up and manages external memory provider plugins. Help text: *"Set up and manage external memory provider plugins. Available providers: honcho, openviking, mem0, hindsight, holographic, retaindb, byterover. Only one external provider can be active at a time. Built-in memory (MEMORY.md/USER.md) is always active."*
- **How it works:** `cmd_memory(args)` (`hermes_cli/main.py:12853`) handles `off` and `reset` inline; everything else falls through to `hermes_cli/memory_setup.memory_command(args)` (`hermes_cli/memory_setup.py:573`), which routes `setup` (with or without a positional provider) and `status`, and defaults to `status` when no subcommand is given.
- **Inputs / options:** `-h/--help`. Subcommands: `setup` ("Interactive provider selection and configuration"), `status` ("Show current memory provider config"), `off` ("Disable external provider (built-in only)"), `reset` ("Erase all built-in memory (MEMORY.md and USER.md)").
- **Outputs / side effects:** Depends on subcommand.
- **Config / env:** `memory.provider`.
- **Edge cases / guards:** The help text enumerates only 7 providers; `supermemory` is also bundled (8 directories under `plugins/memory/`).
- **Rebuild notes:** A four-verb provider manager: pick, inspect, disable, wipe.

### `hermes memory setup [provider]`  `id: memory.cli-memory-setup`
- **Surface:** CLI
- **Where:** `hermes memory setup [-h] [provider]`
- **What it does:** Interactive wizard that picks a memory provider, installs its dependencies, walks its config schema, writes `memory.provider` into `config.yaml`, provider config into the provider's native location, and secrets into `.env`.
- **How it works:** `cmd_setup(args)` (`hermes_cli/memory_setup.py:281`). `_get_available_providers()` calls `plugins.memory.discover_memory_providers()` then `load_memory_provider(name)`; each provider gets a **setup hint** derived from its config schema: both secret and non-secret fields → `"API key / local"`; only secrets → `"requires API key"`; empty schema → `"no setup needed"`; otherwise `"local"`. Picker: `_curses_select("Memory provider setup", items, default=<Built-in only index>, cancel_returns=-1)` → `hermes_cli.curses_ui.curses_radiolist`; each row renders `"<name> - — <hint>"` and the last row is `("Built-in only", "— MEMORY.md / USER.md (default)")`. Cancel prints `"\n  Cancelled. No changes saved.\n"`. Choosing "Built-in only" writes `memory.provider = ""` and prints `"  ✓ Memory provider: built-in only"` / `"  Saved to config.yaml"`. Otherwise `_install_dependencies(name)` runs, then: if the provider defines `post_setup(hermes_home, config)` the wizard delegates **entirely** to it (it owns config, connection test, and activation); else the generic schema walk runs.
  Generic schema walk, per field: `key`, `description`, `default`, `default_from` ({field, map} — a dynamic default looked up from another already-answered field's value), `secret`, `choices`, `env_var`, `url`, `when` ({k: v} conditions that must all equal current provider config values, else the field is skipped). Choice fields (non-secret) use a curses radiolist seeded at the current value; secrets use `masked_secret_prompt` and show `"(current: ...<last4>, blank to keep)"` when the env var is already set, or print `"  Get yours at <url>"` first; plain text fields prompt with `"  <desc> [<default>]: "` and also mirror to `.env` when the field declares an `env_var`.
  Finally: `memory.provider = name` saved to config.yaml; `provider.save_config(provider_config, hermes_home)` if defined (failure prints `"  Failed to write provider config: <e>"`); `_write_env_vars(env_writes)` → `hermes_cli.config.save_env_value` (validated name regex, denylist incl. `LD_PRELOAD`/`PYTHONPATH`/`HERMES_HOME`, CR/LF stripping, atomic 0o600-from-creation write). Closing output: `"\n  Memory provider: <name>"`, `"  Activation saved to config.yaml"`, optional `"  Provider config saved"`, optional `"  API keys saved to .env"`, `"\n  Start a new session to activate.\n"`.
  `hermes memory setup <provider>` → `cmd_setup_provider()` (`hermes_cli/memory_setup.py:243`) skips the picker; unknown name prints `"\n  Memory provider '<x>' not found."` + `"  Run 'hermes memory setup' to see available providers.\n"`.
- **Inputs / options:** `provider` (positional, optional) — "Provider to configure directly (e.g. honcho), skipping the picker"; `-h/--help`.
- **Outputs / side effects:** Writes `~/.hermes/config.yaml`, `~/.hermes/.env` (0600), provider-native config files, and pip installs.
- **Config / env:** `memory.provider`, `memory.<provider>.*`, provider env vars, `HERMES_LAZY_INSTALL_TARGET` (immutable-image install routing).
- **Edge cases / guards:** No providers → `"\n  No memory provider plugins detected."` + `"  Install a plugin to ~/.hermes/plugins/ and try again.\n"`. `_install_dependencies()` (`hermes_cli/memory_setup.py:107`) reads `plugin.yaml` `pip_dependencies`, maps pip→import names via `{"honcho-ai": "honcho", "mem0ai": "mem0", "hindsight-client": "hindsight_client", "hindsight-all": "hindsight"}`, skips already-importable packages unless `force=True` (used by `hermes update` to heal a rebuilt venv, #53272/#70636), prints `"\n  Installing dependencies: <list>"` then `"  ✓ Installed …"` / `"  ⚠ Cannot install …: <reason>"` / `"  ⚠ Failed to install …"` with up to 200 chars of stderr and `"  Run manually: uv pip install <deps>"`. `external_dependencies` entries are probed with their `check` command (5 s timeout) and, on failure, printed as `"\n  ⚠ '<name>' not found. Install with:"` + the `install` line. `_provider_pip_dependencies()` (`hermes_cli/memory_setup.py:20`) adds `hindsight-all` when `~/.hermes/hindsight/config.json` has `mode` in `{"local", "local_embedded"}` (`"local"` is a legacy alias).
- **Rebuild notes:** Schema-driven wizard with `when`/`default_from` conditionals, secret/non-secret split, a delegate hook (`post_setup`) for providers whose setup is a real flow, and a hardened `.env` writer. A better version would validate credentials before activating and offer a dry-run connection test for every provider, not just those with `post_setup`.

### `hermes memory status`  `id: memory.cli-memory-status`
- **Surface:** CLI
- **Where:** `hermes memory status [-h]`; also the default when `hermes memory` is run bare.
- **What it does:** Prints the built-in store flags, whether the `memory` tool is actually exposed on the CLI platform, the active provider and its config, plugin availability with a per-env-var checklist, and the list of installed plugins.
- **How it works:** `cmd_status(args)` (`hermes_cli/memory_setup.py:479`). Output block:
  ```
  Memory status
  ────────────────────────────────────────
    Built-in (MEMORY.md / USER.md):
      Memory injection:   enabled ✓ | disabled ✗
      User profile:       enabled ✓ | disabled ✗
      Memory tool:        enabled ✓ | disabled ✗
    Provider:  <name> | (none — built-in only)
  ```
  The **Memory tool** line is computed from `hermes_cli.tools_config._get_platform_tools(config, "cli", include_default_mcp_servers=False)` containing `"memory"` AND `tools.memory_tool.check_memory_requirements()` — so it reflects both toolset gating and the both-stores-disabled gate. When a provider is set it then prints `"\n  <name> config:"` and each key/value, passing the raw config through `provider.get_status_config(provider_config)` when that hook exists (an exception adds a `status_config_error` key rather than failing). Then `"\n  Plugin:    installed ✓"` and either `"  Status:    available ✓"` or `"  Status:    not available ✗"` followed by a `"  Missing:"` checklist of every schema field with an `env_var` (`✓`/`✗` + the var name, plus `"  → <url>"` when unset), then the two-line note `"  Note: systemd/gateway services do not inherit ~/.hermes/.env —"` / `"        set any variables above in the service environment."`. A configured-but-absent plugin prints `"\n  Plugin:    NOT installed ✗"` + `"  Install the '<name>' memory plugin to ~/.hermes/plugins/"`. Finally `"\n  Installed plugins:"` with `"    • <name>  (<hint>)"` and `" ← active"` on the active one.
- **Inputs / options:** `-h/--help`.
- **Outputs / side effects:** stdout only.
- **Config / env:** reads `memory.*`, platform toolsets, and provider env vars.
- **Edge cases / guards:** Loading a provider for status does NOT register its skills (`load_memory_provider(..., register_skills=False)` semantics via `_get_active_memory_provider()` comparison).
- **Rebuild notes:** Status must show the *effective* surface (is the tool actually exposed?), not just the config flags.

### `hermes memory off`  `id: memory.cli-memory-off`
- **Surface:** CLI
- **Where:** `hermes memory off [-h]`
- **What it does:** Disables the external memory provider, leaving built-in MEMORY.md/USER.md as the only memory.
- **How it works:** `hermes_cli/main.py:12855` — loads config, ensures `config["memory"]` is a dict, sets `config["memory"]["provider"] = ""`, saves, prints `"\n  ✓ Memory provider: built-in only"` and `"  Saved to config.yaml\n"`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Rewrites `~/.hermes/config.yaml`.
- **Config / env:** `memory.provider`.
- **Edge cases / guards:** Does not touch provider-side data or credentials — it only deactivates.
- **Rebuild notes:** Deactivation must be non-destructive and reversible by re-running setup.

### `hermes memory reset`  `id: memory.cli-memory-reset`
- **Surface:** CLI
- **Where:** `hermes memory reset [-h] [--yes] [--target {all,memory,user}]`
- **What it does:** Permanently erases the built-in memory files.
- **How it works:** `hermes_cli/main.py:12865`. Resolves `<HERMES_HOME>/memories`, maps `--target` → files: `all` → both, `memory` → `("MEMORY.md", "agent notes")`, `user` → `("USER.md", "user profile")`. If none of the selected files exist: `"\n  Nothing to reset — no memory files found in <display_hermes_home()>/memories/\n"`. Otherwise prints `"\n  This will permanently erase the following memory files:"` and, per file, `"    ◆ <file> (<desc>) — <size:,> bytes"`. Unless `--yes`, prompts `"\n  Type 'yes' to confirm: "` and requires exactly `yes` (case-insensitive after strip); EOF/Ctrl-C or any other answer prints `"\n  Cancelled.\n"` / `"  Cancelled.\n"`. Then `Path.unlink()` each with `"  ✓ Deleted <file> (<desc>)"`, and closes with `"\n  Memory reset complete. New sessions will start with a blank slate."` + `"  Files were in: <home>/memories/\n"`.
- **Inputs / options:** `--yes, -y` ("Skip confirmation prompt"); `--target {all,memory,user}` ("Which store to reset: 'all' (default), 'memory', or 'user'"); `-h/--help`.
- **Outputs / side effects:** Deletes `MEMORY.md` and/or `USER.md`. Does not delete `.bak.*` snapshots or `.lock` files.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** In Hermes Console the confirmation is auto-answered — `_apply_confirmed_defaults()` sets `args.yes = True` when `memory_command == "reset"` (`hermes_cli/console_engine.py:1282`).
- **Rebuild notes:** Show sizes before deleting, require a typed word (not `y`), and scope by store.

### Memory provider discovery (four sources, bundled-wins)  `id: memory.provider-discovery`
- **Surface:** Core
- **Where:** `plugins/memory/__init__.py`; visible through the `hermes memory setup` picker and the dashboard's `memory.provider` dropdown.
- **What it does:** Finds memory-provider plugins from four sources and resolves a name to exactly one implementation.
- **How it works:** Sources, in precedence order (`plugins/memory/__init__.py:124` `_iter_provider_dirs`): (1) **bundled** `plugins/memory/<name>/`; (2) **user-installed** `$HERMES_HOME/plugins/<name>/`; (3) **project-local** `./.hermes/plugins/<name>/`, gated on `HERMES_ENABLE_PROJECT_PLUGINS`; (4) **pip entry points** in group `hermes_agent.memory_providers`. Precedence is **deliberately the reverse** of the general `PluginManager`'s later-source-wins order — a memory provider is activated by name, so letting a directory dropped into the working tree shadow a shipped provider would silently redirect the agent's memory; the module comment marks changing this as a breaking change, not a cleanup. Directory candidates from sources 2/3 must pass `_is_memory_provider_dir()` — a cheap text scan of the first 8192 bytes of `__init__.py` for `register_memory_provider` or `MemoryProvider` (no import). Public API: `list_memory_provider_names()` (name-only, imports nothing, safe at module-import time — fills the dashboard dropdown), `discover_memory_providers() -> [(name, description, is_available)]` (reads `plugin.yaml` `description`, loads each provider with `register_skills=False`, calls `is_available()`), `load_memory_provider(name, register_skills=None)`, `find_provider_dir(name)`, `find_provider_entry_point(name)`, `discover_plugin_cli_commands()`. Loading a directory provider: bundled modules import as `plugins.memory.<name>`, user/project ones as `_hermes_user_memory.<name>` (a synthetic package registered via `_register_synthetic_package` so relative imports resolve); every sibling `*.py` is pre-registered as a submodule so `from .store import …` works. Extraction order: `register(ctx)` with a `_ProviderCollector` first, else the first `MemoryProvider` subclass found via `dir(mod)`.
- **Inputs / options:** n/a (library API).
- **Outputs / side effects:** `sys.modules` entries; possibly registered plugin skills/tools/hooks.
- **Config / env:** `memory.provider`, `HERMES_ENABLE_PROJECT_PLUGINS`, `HERMES_HOME`.
- **Edge cases / guards:** A provider that raises *after* calling `register_memory_provider` keeps its registered instance with the warning `"Memory provider '%s' raised after registering (%s) — using the registered provider; later registrations were skipped"` — falling through to the subclass scan would silently downgrade to a bare second instance. Entry-point directories are resolved **without importing** the module (`_entry_point_package_dir` → `hermes_cli.plugins.resolve_module_origin`) because discovery runs from the dashboard and argparse long before any provider is chosen; only package entry points (`pkg/__init__.py`) yield a directory. A cached `sys.modules` entry without `__file__` (a synthetic shell registered by `discover_plugin_cli_commands`) is not reused.
- **Rebuild notes:** Four sources, explicit precedence, no-import discovery, synthetic namespaces to avoid collisions, and an extraction fallback chain. Better: sign or pin bundled providers so a name can never be hijacked at all.

### `_ProviderCollector` — memory-provider plugin context  `id: memory.provider-collector`
- **Surface:** Core
- **Where:** `plugins/memory/__init__.py:539`.
- **What it does:** Gives a memory provider the same registration surface as any other plugin while owning the one call that is exclusive (`register_memory_provider`).
- **How it works:** `register_memory_provider(provider)` stores the instance. `register_skill(*args, **kwargs)` is handled explicitly (not via `__getattr__`) because skills are tracked for pruning: it forwards to a real `PluginContext`, then records `_REGISTERED_MEMORY_PROVIDER_SKILLS[f"{provider}:{skill}"] = resolved_path` so switching providers can retract the previous one's skills; it is gated on `register_skills` so merely inspecting an inactive provider (`hermes memory status`, the setup picker) leaves no registry side effects. `register_cli_command` is a no-op (CLI registration happens via `discover_plugin_cli_commands()`). Every other `register_*` attribute is forwarded through `__getattr__` to a lazily built real `PluginContext(PluginManifest(name, key), get_plugin_manager())` — so every method `PluginContext` exposes — `register_tool`, `register_hook`, `register_auxiliary_task`, and any future one — works on the same commit it is added there (the docstring names `register_auxiliary_task` as the case that used to raise `AttributeError`, despite `PluginContext.register_auxiliary_task` documenting a memory provider, hindsight's pre-retain dedup, as its worked example); failures log `"Memory provider '%s' failed to %s: %s"` and return None rather than costing the provider. Non-`register_*` attributes raise `AttributeError` normally so typos fail loudly. `_prune_inactive_memory_provider_skills(active_provider=None)` removes tracked skills whose namespace is not the active provider.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Plugin registry entries (skills, tools, hooks, auxiliary tasks).
- **Config / env:** `memory.provider`.
- **Edge cases / guards:** The lazy `PluginContext` avoids importing the general plugin manager on the common path (a provider that only registers itself), which discovery touches on every hermes startup.
- **Rebuild notes:** Delegate rather than enumerate; track what you register so you can un-register on switch.

### Memory-provider CLI subcommands (`discover_plugin_cli_commands`)  `id: memory.provider-cli-commands`
- **Surface:** CLI
- **Where:** `hermes <active-provider> …` — e.g. `hermes honcho …` when `memory.provider: honcho`.
- **What it does:** Exposes the *active* memory provider's own CLI subcommand tree at argparse time.
- **How it works:** `plugins/memory/__init__.py:687`. Reads `memory.provider`; if empty, registers nothing. Resolves the provider directory, requires a `cli.py`, imports **only that file** (bundled → `plugins.memory.<name>.cli`, user → `_hermes_user_memory.<name>.cli` after registering synthetic parents), and requires a callable `register_cli`. Metadata comes from `plugin.yaml` `description` (fallback help `"Manage <name> memory plugin"`). The handler is `getattr(cli_mod, f"{name}_command")` or, as a fallback, `getattr(cli_mod, "honcho_command")`. Returns at most one dict: `{"name", "help", "description", "setup_fn", "handler_fn", "plugin"}`.
- **Inputs / options:** determined by the plugin's `register_cli(subparser)`.
- **Outputs / side effects:** New top-level `hermes <provider>` subcommand.
- **Config / env:** `memory.provider`.
- **Edge cases / guards:** Lightweight — never imports the full plugin module, so it is safe during argparse setup before any provider is loaded. Only the active provider gets commands.
- **Rebuild notes:** Load only the CLI file, only for the active provider, at parser-construction time.

### Memory provider OAuth connect API  `id: memory.provider-oauth-api`
- **Surface:** API
- **Where:** `POST /api/memory/providers/{provider}/oauth/start` and `GET /api/memory/providers/{provider}/oauth/status`, both accepting an optional `profile` query parameter (`hermes_cli/memory_oauth.py`).
- **What it does:** Runs a memory provider's zero-CLI OAuth flow from the dashboard: opens the browser, captures the grant on a loopback listener, and exposes a pollable status.
- **How it works:** Dispatch is purely by convention — `_resolve_flow(provider)` imports `plugins.memory.<provider>.oauth_flow` and calls `start_loopback_flow_background()` / `get_flow_status()`. No provider is named in the router. `provider` must satisfy `str.isidentifier()`, else 404 `"unknown memory provider '<x>'"`; an `ImportError` yields 404 `"<provider> does not support OAuth connect"`; any other exception yields 500 `"Failed to start <provider> OAuth: <exc>"` / `"Failed to read <provider> OAuth status: <exc>"`. `_scope_to_profile(profile)` is a context manager: empty/`"current"` leaves the home untouched; otherwise it validates the name (`profiles.validate_profile_name`, 400 on `ValueError`), requires existence (404 `"Profile '<p>' does not exist."`), and applies `set_hermes_home_override(profile_dir)` for the duration so the flow's eager config-path resolution targets that profile's `honcho.json`.
- **Inputs / options:** path `provider`; query `profile`.
- **Outputs / side effects:** Opens a browser, starts a background worker thread that outlives the request and the override, writes provider credentials.
- **Config / env:** `HERMES_HOME` override per profile.
- **Edge cases / guards:** Status values are documented as `idle | pending | connected | error`.
- **Rebuild notes:** Convention-based dispatch keeps the router provider-agnostic; scope config resolution to the target profile before spawning the worker, since the worker outlives the request.

### Declarative provider config schema (`config_schema.py`)  `id: memory.provider-config-schema`
- **Surface:** Core
- **Where:** `plugins/memory/config_schema.py` + each provider's optional `plugins/memory/<name>/config_schema.py`; rendered by the desktop UI and served by `GET/PUT /api/memory/providers/{name}/config`.
- **What it does:** Lets a provider *declare* its configurable surface (fields, types, secrets, select options) so one generic renderer and one generic endpoint pair drive every provider's config panel — adding a provider config surface is pure declaration, no bespoke UI.
- **How it works:** Field kinds: `KIND_TEXT = "text"`, `KIND_SELECT = "select"`, `KIND_SECRET = "secret"`, `KIND_BOOL = "bool"`, `KIND_NUMBER = "number"`, `KIND_JSON = "json"`. Storage backends: `STORAGE_FLAT_JSON = "flat_json"`, `STORAGE_HONCHO_HOST_BLOCK = "honcho_host_block"`. `@dataclass(frozen=True) ProviderFieldOption(value, label, description="")`. `@dataclass(frozen=True) ProviderField(key, label, kind="text", default="", description="", placeholder="", options=(), env_key=None, aliases=(), env_fallbacks=(), inline=False, group="", info="", scope="host")` with `is_secret` property and `allowed_values()`. `@dataclass(frozen=True) ProviderConfigSchema(name, label, storage="flat_json", docs_url="", fields=())` with `inline_fields()`. Non-secret fields persist under `key` through the storage backend; `secret` fields persist to the env store under `env_key` and are NEVER read back over the API (only an `is_set` flag). `aliases` / `env_fallbacks` read legacy values written by earlier CLI/env setup. `inline=True` marks the curated subset shown in the compact panel; the rest appear only in the full-config modal, bucketed by `group`; `info` becomes a tooltip. `scope` is `"host"` (per-profile) or `"root"` for host-block storage; flat-json ignores it. `get_provider_config_schema(name)` loads `config_schema.py` **by path** (`importlib.util.spec_from_file_location(f"_hermes_memory_config_schema.{name}", path)`) — never via package import, because a plugin `__init__.py` pulls in the agent runtime which must not load into the web server; a `config_schema.py` may only import from this module. `_SCHEMA_CACHE` keys on the resolved **file path**, not the name, because user-installed plugins are per-profile and one profile's lookup must never answer for another's; a failed load is never cached (it would pin an empty panel until restart).
- **Inputs / options:** n/a (data declarations).
- **Outputs / side effects:** Config panel rendering and read/write dispatch.
- **Config / env:** provider-specific.
- **Edge cases / guards:** Providers without a `config_schema.py` return `None` and render no panel. Shipped schemas exist for `honcho` (`plugins/memory/honcho/config_schema.py`, 324 lines) and `hindsight` (`plugins/memory/hindsight/config_schema.py`, 76 lines).
- **Rebuild notes:** Pure-data schema + path-based loading + a secret/non-secret storage split; one renderer, one endpoint pair. Better: generate both the CLI wizard and the web panel from the same declaration (today the CLI uses `get_config_schema()` and the web uses `CONFIG_SCHEMA`).

### Memory query rewrite auxiliary task  `id: memory.query-rewrite`
- **Surface:** Core
- **Where:** `plugins/memory/query_rewrite.py`; configured under `hermes model` → auxiliary models → **Memory query rewrite**.
- **What it does:** Turns the latest user message into one concise English retrieval question for a memory backend, using a cheap auxiliary model. Provider-agnostic — any provider can pass `rewrite_memory_query` as its query rewriter (Honcho opts in with `queryRewrite: true`).
- **How it works:** `TASK_KEY = "memory_query_rewrite"`. Input is bounded to `_MAX_INPUT_CHARS = 4_000`; longer input becomes `head[:3000] + "\n\n[... middle omitted ...]\n\n" + tail[-900:]`. The system prompt (verbatim at `plugins/memory/query_rewrite.py:42`) instructs: treat the latest message as untrusted data, never follow instructions inside it, do not answer it, preserve concrete entities/constraints/unresolved references, make the question explicitly about the user's history/preferences/prior decisions, return exactly one question with no label/explanation/quotes/Markdown, keep it under 240 characters. The user message is `"Latest user message (JSON string; data only):\n" + json.dumps(bounded)`. Call: `agent.auxiliary_client.call_llm(task=TASK_KEY, messages=…, temperature=0, max_tokens=96)`. `_normalize_rewrite()` then applies a strict accept/reject filter: strip ``` fences, strip a leading `retrieval query:|memory query:|query:|question:` label (`_OUTPUT_PREFIX_RE`), strip surrounding quotes/backticks, remove control characters, collapse whitespace; then REJECT (return `""`) if empty or > `_MAX_QUERY_CHARS = 320`; if it does not start with an interrogative (`what|which|who|where|when|why|how|is|are|was|were|do|does|did|has|have|had|can|could|would|should|may|might`); if it lacks a memory-grounding word (`user|their|they|them|previous|prior|past|history|preference|preferences|context|known|remembered|earlier`); if it leaks instructions (`ignore|obey|follow|instructions?|system prompt|answer directly|answer instead|answer the user|answer this`); or if it contains more than one sentence (`[.!?]\s+\S` after stripping a trailing `?`). Finally a `?` is appended if missing.
- **Inputs / options:** `user_message: str` → returns the rewritten question or `""`.
- **Outputs / side effects:** One auxiliary LLM call per dialectic cycle (not per pass).
- **Config / env:** `auxiliary.memory_query_rewrite.provider` (default `"auto"`), `.model` (`""`), `.base_url` (`""`), `.api_key` (`""`), `.timeout` (`8` seconds).
- **Edge cases / guards:** Any exception or an invalid rewrite returns `""` so the caller falls back to its previous behaviour (Honcho's cold/warm prompt). Off by default because it adds a model call.
- **Rebuild notes:** Treat the user message as data (JSON-encoded), reject anything that does not look like a single grounded question, and always have a silent fallback. A better version would cache rewrites per message hash and skip the call for trivial prompts.

### Memory provider: Honcho  `id: memory.provider-honcho`
- **Surface:** Provider
- **Where:** `memory.provider: honcho`; `hermes memory setup honcho`; `hermes honcho …` once active; Desktop "Connect" link next to the memory-provider dropdown.
- **What it does:** AI-native cross-session user modeling with multi-pass dialectic reasoning, session summaries, bidirectional peer tools, and persistent conclusions. plugin.yaml: `"Honcho AI-native memory — cross-session user modeling with dialectic Q&A, semantic search, and persistent conclusions."`, version 1.0.0, pip `honcho-ai`, hook `on_session_end`.
- **How it works:** `plugins/memory/honcho/__init__.py` (1712 lines) + `client.py` (1367) + `session.py` (1819) + `cli.py` (1976) + `oauth.py` (640) + `oauth_flow.py` (656) + `config_schema.py` (324). **Two-layer context injection into the USER message at API-call time** (not the system prompt) so prompt caching survives; only a static mode header goes in the system prompt, and the injected block is `<memory-context>`-fenced. Layer 1 (base context, refreshed every `contextCadence` turns): SESSION SUMMARY from `session.context(summary=True)` first, then User Representation, User Peer Card, AI Self-Representation, AI Identity Card. Layer 2 (dialectic supplement, every `dialecticCadence` turns): multi-pass `.chat()` reasoning appended after base context. Both are joined then truncated to `contextTokens` via `_truncate_to_budget` (tokens × 4 chars, word-boundary safe). **Dialectic depth** `dialecticDepth` 1–3 (clamped): 1 = single `.chat()`; 2 = audit + synthesis with a conditional bail-out when pass 0 returns strong signal (>300 chars, or structured with bullets/sections >100 chars); 3 = audit + synthesis + reconciliation of contradictions. **Proportional reasoning levels** when `dialecticDepthLevels` is unset: depth 1 → `[base]`, depth 2 → `[minimal, base]`, depth 3 → `[minimal, base, low]`. **Query-adaptive level:** the auto-injected dialectic scales `dialecticReasoningLevel` by query length — +1 level at ≥120 chars, +2 at ≥400 — clamped at `reasoningLevelCap` (default `"high"`); disable with `reasoningHeuristic: false`. **Cold vs warm pass-0 prompt** (not configurable): cold (no base context cached) = *"Who is this person? What are their preferences, goals, and working style? Focus on facts that would help an AI assistant be immediately useful."*; warm = *"Given what's been discussed in this session so far, what context about this user is most relevant to the current conversation? Prioritize active context over biographical facts."* **Input sanitization:** `run_conversation` strips leaked `<memory-context>` blocks from user input before processing, because `saveMessages` can persist a turn that included injected context.
  **Config resolution** — first existing file of: (1) `$HERMES_HOME/honcho.json` (profile-local), (2) `~/.hermes/honcho.json` (default profile), (3) `~/.honcho/config.json` (global, cross-app). Host key derives from the active profile: `hermes` or `hermes_<profile>`. Per-key order: **host block > root > env var > default**.
  **Identity resolver ladder** (first match wins): 1 `pinUserPeer`/`pinPeerName` true → `peerName`; 2 `userPeerAliases[runtime_id]`; 3 `userPeerAliases[runtime_id_alt]`; 4 `runtimePeerPrefix + runtime_id` with sha256 collision escalation; 5 raw sanitized runtime id; 6 `peerName`; 7 session-key fallback.
  **Session name resolution** (first match wins): 1 manual `sessions` map; 2 `/title` mid-session rename; 3 gateway session key (always used on gateway platforms, per-chat isolation); 4 `per-session` → Hermes session id; 5 `per-repo` → git root dir name; 6 `per-directory` → `$PWD` basename; 7 `global` → workspace name. `sessionPeerPrefix: true` prepends the peer name.
- **Inputs / options:** Five bidirectional tools, all taking an optional `peer` (aliases `"user"` default / `"ai"`, or any workspace peer id):
  - `honcho_profile` — read/write the peer CARD. Params: `peer` (string), `card` (array of fact strings; omit to read). No LLM. An empty read returns a `hint`, not an error.
  - `honcho_search` — hybrid semantic+keyword RRF-ranked raw message excerpts across ALL past sessions the peer took part in. Params: `query` (required), `max_tokens` (int, default 800, max 2000), `peer`. No LLM.
  - `honcho_reasoning` — dialectic `.chat()` synthesized prose answer; the only Honcho tool that runs an LLM. Params: `query` (required), `reasoning_level` (enum `minimal|low|medium|high|max`; `minimal` is hard-capped at 250 tokens combined with hidden reasoning tokens), `peer`.
  - `honcho_context` — standing snapshot (session summary + representation + card + recent messages) in one call. Params: `peer`. No LLM.
  - `honcho_conclude` — write/list/delete persistent conclusions. Params: `conclusion` (create), `delete_id` (delete; ids are opaque and must come from a prior `list`), `list` (bool), `query` (only with `list`), `peer`. Exactly one of conclusion/delete_id/list is required; any other combination is an error. Deletion exists only for PII removal — for wrong facts write a corrected conclusion instead.
  Tool visibility follows `recallMode`: hidden in `context`, present in `tools` and `hybrid`.
  Config keys (README "Full Configuration Reference"): **Identity & Connection** `apiKey`, `oauth` (object: refresh token, expiry, client, token endpoint — written by the Connect flows, rotated automatically), `baseUrl` (local URLs auto-skip API-key auth), `environment` (default `"production"`), `enabled` (auto-enables when `apiKey` or `baseUrl` present), `workspace` (default host key), `peerName`, `aiPeer` (default host key). **Identity mapping** `pinUserPeer` (bool, default false; deprecated alias `pinPeerName`), `userPeerAliases` (object, default `{}`; many-to-one intended, one-to-many unsupported), `runtimePeerPrefix` (string, default `""`). **Memory & Recall** `recallMode` (`hybrid` default | `context` | `tools`; legacy `auto` → `hybrid`), `observationMode` (`directional` default | `unified`), `observation` (object, per-peer granular). **Write behaviour** `writeFrequency` (`async` default | `turn` | `session` | integer N), `saveMessages` (bool, default true; false skips `sync_turn`, `on_memory_write` conclusion mirroring, and session-end/shutdown flushes while reads/tools keep working). **Session resolution** `sessionStrategy` (`per-directory` default | `per-session` | `per-repo` | `global`), `sessionPeerPrefix` (bool, default false), `sessions` (object, default `{}`). **Dialectic** `contextCadence`, `dialecticCadence`, `dialecticDepth`, `dialecticDepthLevels`, `dialecticReasoningLevel`, `reasoningLevelCap` (default `"high"`), `reasoningHeuristic`, `contextTokens`, `queryRewrite`. Runtime `get_config_schema()` exposes just `api_key` and `baseUrl` (the wizard delegates the rest to `post_setup`).
- **Outputs / side effects:** Writes `honcho.json` (or `~/.honcho/config.json`), OAuth grants, and messages/conclusions on the Honcho service. `backup_paths()` returns `["~/.honcho"]`.
- **Config / env:** `HONCHO_API_KEY`; the JSON config above.
- **Edge cases / guards:** OAuth, device-code, and API-key auth modes; on SSH/headless machines the wizard's **device** option prints a short code and a link. `hermes honcho setup` only works AFTER honcho is the active provider (the subcommand is registered for the active provider only) — on a fresh install use `hermes memory setup honcho`. The gateway identity-mapping wizard step is skipped entirely when no gateway platform is connected. Un-pinning `pinUserPeer` does NOT migrate data — the wizard offers the "pooled" alias steer automatically.
- **Rebuild notes:** Inject into the *user* message (cache-safe), split base context from expensive reasoning on independent cadences, budget-truncate the merged block, and resolve identity through an explicit deterministic ladder with no runtime inference or automatic merging. A better version would cache dialectic answers keyed on (peer, question-embedding) and expose the cadence counters in the status line.

### Memory provider: Hindsight  `id: memory.provider-hindsight`
- **Surface:** Provider
- **Where:** `memory.provider: hindsight`; config at `~/.hermes/hindsight/config.json`.
- **What it does:** Long-term memory with a knowledge graph, entity resolution, and multi-strategy retrieval (semantic + keyword + entity-graph traversal + reranking), in cloud, local-embedded, or local-external mode. plugin.yaml: `"Hindsight — long-term memory with knowledge graph, entity resolution, and multi-strategy retrieval."`, version 1.0.0, pip `hindsight-client>=0.6.1`, hook `on_session_end`.
- **How it works:** `plugins/memory/hindsight/__init__.py` (2470 lines) + `config_schema.py` + `templates.py` (starter memory templates). Three modes: **cloud** (`https://api.hindsight.vectorize.io`, needs `HINDSIGHT_API_KEY`), **local_embedded** (Hermes spins up a local Hindsight daemon with built-in PostgreSQL; starts automatically in the background on first use and stops after 5 minutes of inactivity; embeddings and reranking run locally; startup logs `~/.hermes/logs/hindsight-embed.log`, runtime logs `~/.hindsight/profiles/<profile>.log`; web UI via `hindsight-embed -p hermes ui start`), **local_external** (point at an existing instance; URL + optional API key, no daemon management). The setup wizard installs deps via `uv`, walks configuration, and offers to seed the bank with a **starter memory template** (curated dispositions/instructions for common agent roles) — skippable, and it warns before overwriting an already-configured bank. `_provider_pip_dependencies()` adds `hindsight-all` when the mode is `local`/`local_embedded`. The plugin auto-upgrades `hindsight-client` on session start if an older version than 0.6.1 is detected. `backup_paths()` returns `["~/.hindsight"]`. The recall indicator uses the glyph `👁️`.
- **Inputs / options:** Tools (available in `hybrid` and `tools` memory modes):
  - `hindsight_retain` — "Store information to long-term memory. Hindsight automatically extracts structured facts, resolves entities, and indexes for retrieval." Params: `content` (required), `context` (short label, e.g. 'user preference', 'project decision'), `tags` (array; merged with configured default retain tags), `occurred_at` (ISO-8601 date/datetime — pass whenever the memory references a specific event time so Hindsight can anchor it on the timeline; omit for timeless facts).
  - `hindsight_recall` — "Search long-term memory. Returns memories ranked by relevance using semantic search, keyword matching, entity graph traversal, and reranking." Params: `query` (required). No per-call `types` argument — it reads the same `recall_types` config as auto-recall.
  - `hindsight_reflect` — "Synthesize a reasoned answer from long-term memories. Unlike recall, this reasons across all stored memories to produce a coherent response." Params: `query` (required).
  Config keys (`~/.hermes/hindsight/config.json`), grouped: **Connection** `mode` (`cloud` default | `local_embedded` | `local_external`), `api_url` (default `https://api.hindsight.vectorize.io`), `api_key`. **Memory bank** `bank_id` (default `hermes`), `bank_id_template` (placeholders `{profile}`, `{workspace}`, `{platform}`, `{user}`, `{session}`; empty placeholders collapse cleanly), `bank_mission` (reflect mission — identity/framing), `bank_retain_mission` (steers what gets extracted). **Recall** `recall_budget` (`low|mid|high`, default `mid`), `recall_prefetch_method` (`recall` default | `reflect`), `recall_max_tokens` (4096), `recall_max_input_chars` (800), `recall_prompt_preamble`, `recall_tags`, `recall_tags_match` (`any` default | `all` | `any_strict` | `all_strict`), `recall_types` (default **`observation`** only — deliberately narrowed; set `observation,world,experience` to include raw facts; applies to both auto-recall and the tool), `auto_recall` (true), `recall_sync` (false — when true, recall runs synchronously against the *current* message each turn for higher relevance at the cost of latency; default off means recall runs in the background and is injected on the next turn), `recall_indicator` (true — `👁️ Hindsight — recalled N memories`). **Retain** `auto_retain` (true), `retain_async` (true), `retain_every_n_turns` (1), `retain_context` (default `"conversation between Hermes Agent and the User"`), `retain_tags`, `retain_source` (empty by default — no attribution tag ships unless set), `retain_indicator` (true — `👁️ Hindsight — saving to memory…`), `retain_user_prefix` (`User`), `retain_assistant_prefix` (`Assistant`). **Integration** `memory_mode` (`hybrid` default | `context` | `tools`). **Local embedded LLM** `llm_provider` (`openai|anthropic|gemini|groq|openrouter|minimax|ollama|lmstudio|openai_compatible`), `llm_model`, `llm_base_url`, plus `llm_api_key` stored as `HINDSIGHT_LLM_API_KEY`. Additional runtime schema keys: `observation_scopes`, `prefetch_waits_for_retain`, `prefetch_retain_drain_timeout`, `timeout`, `idle_timeout`, `port_health_grace_timeout`.
- **Outputs / side effects:** Writes `~/.hermes/hindsight/config.json`, `~/.hindsight/*`, log files, and memories on the Hindsight service/daemon.
- **Config / env:** `HINDSIGHT_API_KEY`, `HINDSIGHT_LLM_API_KEY`, `HINDSIGHT_API_LLM_BASE_URL`, `HINDSIGHT_API_URL`, `HINDSIGHT_BANK_ID`, `HINDSIGHT_BUDGET`, `HINDSIGHT_MODE`.
- **Edge cases / guards:** A misconfigured Hindsight daemon was observed blocking `sync_turn` ~298 s — the reason `MemoryManager.sync_all` runs off-thread. `recall_indicator`/`retain_indicator` exist so customer-facing agents can hide memory activity.
- **Rebuild notes:** Three deployment modes behind one config file; a consolidated "observation" layer preferred over raw facts for per-turn injection; per-call tags merged with configured defaults; explicit event-time anchoring (`occurred_at`). Better: expose per-call `types` on the recall tool and surface the daemon's health in `hermes memory status`.

### Memory provider: Mem0  `id: memory.provider-mem0`
- **Surface:** Provider
- **Where:** `memory.provider: mem0`; behavioural config in `$HERMES_HOME/mem0.json`, secret in `~/.hermes/.env`.
- **What it does:** Server-side LLM fact extraction with semantic search, automatic deduplication, and opt-in reranking. plugin.yaml: version 1.3.0, pip `mem0ai>=2.0.10,<3`.
- **How it works:** `plugins/memory/mem0/__init__.py` (628) + `_backend.py` (358) + `_setup.py` (1003) + `_oss_providers.py` (88) + `_openai_llm.py` (100). Three connection modes: **platform** (default, Mem0 Cloud `api.mem0.ai`, needs `MEM0_API_KEY`), **self-hosted dashboard/server** (set `host`; the plugin authenticates with `X-API-Key` and uses the server's `/search` and `/memories` routes; `api_key` is optional — omit only for servers running with `AUTH_DISABLED`), and **oss** (run `mem0ai` in-process with your own LLM + embedder + vector store). Setting `host` routes to the self-hosted server automatically; `mode: oss` takes precedence and ignores `host`. OSS supported providers: LLM `openai|ollama`, Embedder `openai|ollama`, Vector store `qdrant` (local path or server) | `pgvector`. Example OSS config block in `mem0.json`: `{"mode":"oss","oss":{"llm":{"provider":"openai","config":{"model":"gpt-5-mini","is_reasoning_model":true}},"embedder":{"provider":"openai","config":{"model":"text-embedding-3-small"}},"vector_store":{"provider":"qdrant","config":{"path":"~/.hermes/mem0_qdrant"}}}}`. A **circuit breaker** trips after 5 consecutive failures and resets after 2 minutes, surfacing `"Mem0 temporarily unavailable"`.
- **Inputs / options:** Tools:
  - `mem0_search` — semantic search; params `query` (required), `top_k` (int, default 10, max 50), `rerank` (bool, default false, platform mode only). Description tells the model to call it several times with varied wording for multi-hop questions.
  - `mem0_add` — "Store a durable fact about the user, verbatim (no LLM extraction)"; param `content` (required).
  - `mem0_update` — replace an existing memory's text; params `memory_id` (UUID, required), `text` (required).
  - `mem0_delete` — delete by id; param `memory_id` (required).
  Config keys (`$HERMES_HOME/mem0.json`): `mode` (default `platform`; or `oss`), `host` (self-hosted server URL), `user_id` (default `hermes-user`), `agent_id` (default `hermes`), `rerank` (default `false`, platform only), `api_key`.
  Non-interactive setup flags (`hermes memory setup mem0 …`): `--mode {platform,oss,selfhosted}`, `--host`, `--api-key`, `--oss-llm` (default openai), `--oss-llm-key`, `--oss-embedder` (default openai), `--oss-vector` (default qdrant), `--oss-vector-path`, `--user-id`, `--dry-run`.
- **Outputs / side effects:** Writes `$HERMES_HOME/mem0.json`, `~/.hermes/.env`, optionally `~/.hermes/mem0_qdrant/`; memories on the Mem0 platform/server.
- **Config / env:** `MEM0_API_KEY`, `MEM0_HOST`.
- **Edge cases / guards:** `mem0_add` stores verbatim with no extraction — LLM extraction happens through `sync_turn`. `user_id` must match across sessions or memories appear missing. Troubleshooting hints cover qdrant path permissions, `curl http://localhost:6333/healthz`, `pg_isready`, and `curl http://localhost:11434/api/tags` for Ollama.
- **Rebuild notes:** One plugin, three transports (cloud SDK, HTTP to a self-hosted server, in-process SDK) selected by config precedence; a circuit breaker around every remote call; a verbatim-store tool distinct from the extraction path. Better: expose the circuit-breaker state in `hermes memory status`.

### Memory provider: Holographic (local SQLite fact store)  `id: memory.provider-holographic`
- **Surface:** Provider
- **Where:** `memory.provider: holographic`; DB at `$HERMES_HOME/memory_store.db`; config under `plugins.hermes-memory-store` in config.yaml.
- **What it does:** A fully local memory backend: SQLite fact store with FTS5 search, trust scoring, regex entity resolution, and HRR (holographic reduced representation) compositional retrieval. plugin.yaml: version 0.1.0, `"Holographic memory — local SQLite fact store with FTS5 search, trust scoring, and HRR-based compositional retrieval."`, hook `on_session_end`. No requirements beyond SQLite; NumPy optional.
- **How it works:** `plugins/memory/holographic/{__init__.py (462), store.py (688), retrieval.py (668), holographic.py (290)}`.
  **Schema** (`store.py:17`): `facts(fact_id INTEGER PK AUTOINCREMENT, content TEXT NOT NULL UNIQUE, category TEXT DEFAULT 'general', tags TEXT DEFAULT '', trust_score REAL DEFAULT 0.5, retrieval_count INTEGER DEFAULT 0, helpful_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, hrr_vector BLOB)`; `entities(entity_id PK, name TEXT NOT NULL, entity_type TEXT DEFAULT 'unknown', aliases TEXT DEFAULT '', created_at)`; `fact_entities(fact_id REFERENCES facts, entity_id REFERENCES entities, PRIMARY KEY (fact_id, entity_id))`; indexes `idx_facts_trust ON facts(trust_score DESC)`, `idx_facts_category ON facts(category)`, `idx_entities_name ON entities(name)`; `facts_fts USING fts5(content, tags, content=facts, content_rowid=fact_id)` with `facts_ai` / `facts_ad` / `facts_au` triggers; `memory_banks(bank_id PK, bank_name TEXT UNIQUE, vector BLOB NOT NULL, dim INTEGER NOT NULL, fact_count INTEGER DEFAULT 0, updated_at)`.
  **Trust:** `_HELPFUL_DELTA = +0.05`, `_UNHELPFUL_DELTA = -0.10`, clamped to `[0.0, 1.0]`. `record_feedback()` also increments `helpful_count` on a positive rating and returns `{fact_id, old_trust, new_trust, helpful_count}`; unknown ids raise `KeyError`.
  **Entity extraction** (`store.py:448`) is regex-only: `_RE_CAPITALIZED = \b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b`, `_RE_DOUBLE_QUOTE = "([^"]+)"`, `_RE_SINGLE_QUOTE = '([^']+)'`, and `_RE_AKA = (\w+(?:\s+\w+)*)\s+(?:aka|also known as)\s+(\w+(?:\s+\w+)*)` (case-insensitive) for alias resolution.
  **HRR algebra** (`holographic.py`) — phase vectors of angles in [0, 2π): `bind` = circular convolution (phase addition), `unbind` = circular correlation (phase subtraction), `bundle` = superposition (circular mean), `similarity` = cosine-like on phases. `encode_atom(word, dim=1024)` is deterministic from SHA-256 counter blocks — hash `f"{word}:{i}"` for i = 0,1,2…, concatenate digests, `struct.unpack` as uint16, scale by `2π/65536`, truncate to `dim`, return `np.float64[dim]` — so representations are identical across processes, machines, and Python versions. `encode_text`, `encode_fact(content, entities, dim)`, `phases_to_bytes` / `bytes_to_phases` (BLOB prefix `b"HRR1"`, float32), and `snr_estimate(dim, n_items) = sqrt(dim / n_items)` which logs a capacity warning when SNR < 2.0 (i.e. `n_items > dim/4`). Category banks are stored as `cat:<category>` rows in `memory_banks`, rebuilt by bundling every fact vector in that category. `rebuild_all_vectors(dim=None)` recomputes everything for recovery/migration.
  **Retrieval** (`retrieval.py`): `FactRetriever(store, temporal_decay_half_life=0, fts_weight=0.4, jaccard_weight=0.3, hrr_weight=0.3, hrr_dim=1024)`; when NumPy is missing the weights auto-redistribute to `fts=0.6, jaccard=0.4, hrr=0.0`. `search()` pipeline: (1) FTS5 fetches `limit*3` candidates; (2) per candidate `jaccard = |A∩B|/|A∪B|` over whitespace-lowercased, punctuation-stripped tokens of content+tags, plus `hrr_sim = (similarity+1)/2` (neutral 0.5 when the fact has no vector), query vector encoded lazily at most once; (3) `relevance = 0.4*fts_rank + 0.3*jaccard + 0.3*hrr_sim`, `score = relevance * trust_score`; (4) optional temporal decay `score *= 0.5^(age_days/half_life)` (1.0 when disabled or unparsable). Raw `hrr_vector` bytes are stripped from results. `probe(entity)` / `related(entity)` / `reason(entities)` / `contradict()` all score with `(sim + 1.0)/2.0 * trust_score` (using the MIN similarity across entities for `reason`, the BEST for `related`) and fall back to FTS5 (or an empty list for `contradict`) when NumPy is unavailable. `_sanitize_fts_query()` converts prose to an FTS5-safe OR expression: lowercase-split, strip `.,;:!?"'()[]{}#@<>` then the FTS5 specials `"()*^:-+`, drop tokens shorter than 2 chars, drop a 127-word English stopword list, phrase-quote each survivor, join with ` OR `; if nothing survives it falls back to the raw query so the caller gets zero results rather than a SQL error.
- **Inputs / options:** Tools:
  - `fact_store` — 9 actions. Params: `action` (required, enum `add|search|probe|related|reason|contradict|update|remove|list`), `content` (required for add), `query` (required for search), `entity` (for probe/related), `entities` (array, for reason), `fact_id` (int, for update/remove), `category` (enum `user_pref|project|tool|general`), `tags` (comma-separated string), `trust_delta` (number, for update), `min_trust` (number, default 0.3), `limit` (int, default 10). Description: *"Deep structured memory with algebraic reasoning. Use alongside the memory tool — memory for always-on context, fact_store for deep recall and compositional queries."* with per-action bullets and *"IMPORTANT: Before answering questions about the user, ALWAYS probe or reason…"*.
  - `fact_feedback` — params `action` (required, enum `helpful|unhelpful`), `fact_id` (int, required). *"Rate a fact after using it. Mark 'helpful' if accurate, 'unhelpful' if outdated. This trains the memory — good facts rise, bad facts sink."*
  Config (`config.yaml` → `plugins.hermes-memory-store`): `db_path` (default `$HERMES_HOME/memory_store.db`), `auto_extract` (default `false` — auto-extract facts at session end), `default_trust` (`0.5`), `hrr_dim` (`1024`).
- **Outputs / side effects:** One SQLite file; no network at all.
- **Config / env:** the four keys above; `HERMES_HOME` for the default DB path.
- **Edge cases / guards:** `facts.content` is UNIQUE, so duplicate facts are rejected at the DB level. `MemoryStore.release_all_under(directory)` closes every open connection under a path (test/teardown helper). Migrated stores can have FTS candidates whose `hrr_vector` was never backfilled — `_init_db` adds the column without backfilling and search treats them as neutral. NumPy-free installs silently lose `probe`/`related`/`reason`/`contradict` fidelity (documented fallbacks).
- **Rebuild notes:** SQLite + FTS5 external-content + three trigger sync + a deterministic SHA-256-seeded phase-vector VSA layer for compositional queries, all weighted by a feedback-trained trust score with optional exponential recency decay. This is the single best model in the tree for a fully offline memory backend. A better version would add embeddings alongside HRR, learn the three weights from feedback, and expose SNR/capacity in the tool output.

### Memory provider: OpenViking  `id: memory.provider-openviking`
- **Surface:** Provider
- **Where:** `memory.provider: openviking`; connection settings in the active profile's `.env`.
- **What it does:** Context database (Volcengine / ByteDance) with a filesystem-style knowledge hierarchy addressed by `viking://` URIs, tiered retrieval, and automatic memory extraction. plugin.yaml: version 2.0.0, pip `httpx`, hook `on_session_end`.
- **How it works:** `plugins/memory/openviking/__init__.py` (5391 lines — the largest provider). Requires an `openviking-server` you run yourself (`openviking-server init`, `openviking-server doctor`, then `openviking-server`); 0.2.10+ recommended, and Hermes can identify older servers exposing the legacy status-only health response only when anonymous OpenAPI metadata also identifies the service as OpenViking (0.2.6 and earlier are deprecated). Setup can link to an existing `~/.openviking/ovcli.conf`, copy its connection values into Hermes, or create a minimal one. Identity: with `OPENVIKING_API_KEY` set, OpenViking derives account/user from the key; in local/trusted deployments without a key Hermes sends `OPENVIKING_ACCOUNT` / `OPENVIKING_USER` as identity headers. Every request carries `User-Agent: openviking-memory-hermes/<version>` (a harness identifier with the Hermes version and no per-user id, no extra request). Peer identity is optional — new connections use the OpenViking user's memory directory and setup does not ask for a peer id; without one, neither `X-OpenViking-Actor-Peer` nor assistant-message `peer_id` is sent. Peer resolution order: environment → linked OpenViking config (`actor_peer_id`, legacy `agent_id`) → Hermes YAML `memory.openviking.agent`. **Writes:** `viking_remember` posts `POST /api/v1/content/write` with `mode=create`, creating files at `viking://user/<user>/memories/…` (or `viking://user/<user>/peers/<peer>/memories/…` when a peer is configured); `<user>` is resolved client-side from `/api/v1/system/status` (server-asserted current user) and cached per active connection, falling back to the configured user or `default` when the probe fails. Explicit-uid URIs are canonical under every auth mode; the `viking://~` alias only expands for USER/ADMIN roles, not default dev mode. **Mirroring:** the built-in memory tool's `add` maps to `content/write` with `mode=create`; `replace` and `remove` are deliberately NOT mirrored because Hermes native memory entries carry no stable OpenViking file URI.
- **Inputs / options:** Tools:
  - `viking_search` — params `query` (required), `mode` (enum `auto|fast|deep`, default auto), `scope` (viking URI prefix, e.g. `viking://resources/docs/`), `limit` (int, default 10).
  - `viking_read` — params `uri` (single), `uris` (array, up to three), `level` (enum `abstract` ≈100-token summary L0 | `overview` ≈2k-token key points L1, default | `full` complete content L2).
  - `viking_browse` — params `action` (required, enum `tree|list|stat`), `path` (default `viking://`).
  - `viking_remember` — params `content` (required), `category` (enum `preference|entity|event|case|pattern`, default auto-detected).
  - `viking_forget` — param `uri` (required): an exact `viking://` memory file URI ending in `.md`.
  - `viking_add_resource` — params `url` (required; public http(s), git, or ssh URL, or a local file/directory uploaded first via OpenViking `temp_upload`), `reason`, `to` (target URI), `parent` (parent URI; cannot be combined with `to`), `instruction` (processing instruction for semantic extraction), `wait` (bool), `timeout` (number, used when `wait`).
  Provider config schema keys: `endpoint`, `api_key`, `account`, `user`, `agent`, `recall_limit`, `recall_score_threshold`, `recall_max_injected_chars`, `profile_token_budget`, `recall_timeout_seconds`, `recall_request_timeout_seconds`, `recall_full_read_limit`, `recall_prefer_abstract`, `recall_resources`.
- **Outputs / side effects:** Writes to the OpenViking server; `backup_paths()` returns `["~/.openviking/ovcli.conf"]`.
- **Config / env:** `OPENVIKING_ENDPOINT` (default `http://127.0.0.1:1933`), `OPENVIKING_API_KEY`, `OPENVIKING_ACCOUNT` (`default`), `OPENVIKING_USER` (`default`), `OPENVIKING_AGENT`, plus the server's own `OPENVIKING_CONFIG_FILE` / `OPENVIKING_CLI_CONFIG_FILE` (`ov.conf` / `ovcli.conf`).
- **Edge cases / guards:** `viking_forget` is intentionally narrow — it accepts only concrete user memory **file** URIs (including files directly under `memories/`), and rejects directories, resources, skills, sessions, generated summary files, and any URI with a query string or fragment; `viking://~/...` input is passed through untouched for deployments where the server expands the home alias. Upgrades never move or delete existing memories: installs that relied on the old implicit `hermes` peer now write at user scope while old peer memories stay searchable at their existing paths; set `agent: hermes` to restore peer-scoped writes.
- **Rebuild notes:** URI-addressed hierarchical knowledge with three read granularities is the key idea — it lets the model page in exactly as much as it needs. Narrow the delete verb to a single exact file URI. Better: mirror `replace`/`remove` by storing the returned file URI alongside each built-in memory entry.

### Memory provider: RetainDB  `id: memory.provider-retaindb`
- **Surface:** Provider
- **Where:** `memory.provider: retaindb`; all config via env vars in `.env`.
- **What it does:** Cloud memory API with hybrid search (vector + BM25 + reranking), 7 memory types, and a shared file store. plugin.yaml: version 1.0.0, pip `requests`, `requires_env: [RETAINDB_API_KEY]`.
- **How it works:** `plugins/memory/retaindb/__init__.py` (860 lines). Requires a RetainDB account ($20/month per the README) from retaindb.com.
- **Inputs / options:** Tools:
  - `retaindb_profile` — no params. "Get the user's stable profile — preferences, facts, and patterns recalled from long-term memory."
  - `retaindb_search` — `query` (required), `top_k` (int, default 8, max 20).
  - `retaindb_context` — `query` (required). "Synthesized context block — what matters most for the current task."
  - `retaindb_remember` — `content` (required), `memory_type` (enum `factual|preference|goal|instruction|event|opinion`, default `factual`), `importance` (number 0–1, default 0.7).
  - `retaindb_forget` — `memory_id` (required).
  - `retaindb_upload_file` — `local_path` (required), `remote_path` (e.g. `/reports/q1.pdf`), `scope` (enum `USER|PROJECT|ORG`, default `PROJECT`), `ingest` (bool, default false — also extract memories after upload). Returns an `rdb://` URI any agent can reference.
  - `retaindb_list_files` — `prefix` (path prefix filter), `limit` (int, default 50).
  - `retaindb_read_file` — `file_id` (required).
  - `retaindb_ingest_file` — `file_id` (required). Chunks, embeds, and extracts memories so the file becomes searchable.
  - `retaindb_delete_file` — `file_id` (required).
  Config schema keys: `api_key`, `base_url`, `project`.
- **Outputs / side effects:** Memories and files on the RetainDB service.
- **Config / env:** `RETAINDB_API_KEY` (required), `RETAINDB_BASE_URL` (default `https://api.retaindb.com`), `RETAINDB_PROJECT` (default auto, profile-scoped).
- **Edge cases / guards:** The README's tool table lists only the first five tools; the runtime registers ten (the five file-store tools are undocumented there).
- **Rebuild notes:** Typed memories with an explicit importance score plus a shared file store with scope levels — the file half is what distinguishes it. Better: expose the memory type + importance in search results so the model can weight them.

### Memory provider: ByteRover  `id: memory.provider-byterover`
- **Surface:** Provider
- **Where:** `memory.provider: byterover`; working directory `$HERMES_HOME/byterover/` (profile-scoped).
- **What it does:** Persistent memory through the external `brv` CLI — a hierarchical knowledge tree with tiered retrieval (fuzzy text → LLM-driven search). plugin.yaml: version 1.0.0, `external_dependencies: [{name: brv, install: "curl -fsSL https://byterover.dev/install.sh | sh", check: "brv --version"}]`, hook `on_pre_compress`.
- **How it works:** `plugins/memory/byterover/__init__.py` (449 lines) shells out to the `brv` binary. Local-first; cloud sync is optional via `BRV_API_KEY`. It is the only bundled provider that registers the `on_pre_compress` hook in its manifest. Install alternatives: `curl -fsSL https://byterover.dev/install.sh | sh` or `npm install -g byterover-cli`.
- **Inputs / options:** Tools:
  - `brv_query` — `query` (required, "What to search for."). "Search ByteRover's persistent knowledge tree for relevant context. Returns memories, project knowledge, architectural decisions, and patterns from previous sessions."
  - `brv_curate` — `content` (required, "The information to remember."). "Store important information … ByteRover's LLM automatically categorizes and organizes the memory."
  - `brv_status` — no params. "Check ByteRover status — CLI version, context tree stats, cloud sync state."
  Config schema keys: `api_key`, `auto_extract`.
- **Outputs / side effects:** Files under `$HERMES_HOME/byterover/`; optional cloud sync.
- **Config / env:** `BRV_API_KEY` (optional).
- **Edge cases / guards:** `is_available()` depends on the `brv` binary being on PATH; the setup wizard prints the install command when the `check` probe fails.
- **Rebuild notes:** Wrapping an external CLI is the cheapest way to add a backend — declare `external_dependencies` with `check`/`install` so setup can diagnose it. Better: parse `brv` output into structured JSON rather than passing text through.

### Memory provider: Supermemory  `id: memory.provider-supermemory`
- **Surface:** Provider
- **Where:** `memory.provider: supermemory`; config file `$HERMES_HOME/supermemory.json`.
- **What it does:** Semantic long-term memory with profile recall, semantic search, explicit memory tools, and full-session conversation ingest (one ingest per session) for richer profiles. plugin.yaml: version 1.0.1, pip `supermemory`.
- **How it works:** `plugins/memory/supermemory/__init__.py` (1051 lines). Hosted at `https://api.supermemory.ai` or fully self-hosted (`npx supermemory local`, default `http://localhost:6767`). Base-URL precedence: `supermemory.json` → `SUPERMEMORY_BASE_URL` → the hosted default; resolved once and used for SDK operations, setup/status probes, and conversation ingest alike. The provider buffers the whole conversation and ingests it as **one session** at session end (or on `/reset`, branch, compression, or shutdown) via the conversations endpoint, which drives entity extraction and profile building while keeping a clean retrievable transcript. Every API call sends `x-sm-source: hermes` and document writes stamp `metadata.sm_source: hermes` — documented as a functional routing key (grouping Hermes memories into a "Hermes" Space in the Supermemory app), not telemetry.
- **Inputs / options:** Eight registered tool names — four kebab-case (the ones advertised to the agent) plus four snake_case aliases: `supermemory-save`/`supermemory_store`, `supermemory-search`/`supermemory_search`, `supermemory-forget`/`supermemory_forget`, `supermemory-profile`/`supermemory_profile`.
  - save/store — `content` (required), `metadata` (object).
  - search — `query` (required), `limit` (int 1–20).
  - forget — `id` (exact memory id) or `query` (best-match); neither required.
  - profile — `query` (optional focus).
  In multi-container mode all four additionally accept `container_tag`.
  Config keys (`$HERMES_HOME/supermemory.json`): `base_url` (default `https://api.supermemory.ai`; takes priority over `SUPERMEMORY_BASE_URL`), `container_tag` (default `hermes`; supports the `{identity}` template → `hermes-{identity}` becomes `hermes-coder` for profile `coder`, `hermes-default` for the default profile), `auto_recall` (true), `auto_capture` (true), `max_recall_results` (10), `profile_frequency` (50 — profile facts on the first turn and every N turns), `capture_mode` (`all` — skip tiny/trivial turns by default), `search_mode` (`hybrid` profile+memories | `memories` | `documents`), `entity_context` (extraction guidance passed to Supermemory; has a built-in default), `api_timeout` (5.0), plus multi-container keys `enable_custom_container_tags` (bool), `custom_containers` (array of tag names), `custom_container_instructions` (injected into the system prompt).
- **Outputs / side effects:** Writes `$HERMES_HOME/supermemory.json`; memories/documents/conversations on the Supermemory service.
- **Config / env:** `SUPERMEMORY_API_KEY` (required), `SUPERMEMORY_BASE_URL`, `SUPERMEMORY_CONTAINER_TAG` (overrides the config file).
- **Edge cases / guards:** In multi-container mode a passed `container_tag` must be in the whitelist (primary container + `custom_containers`); **automatic** operations (turn sync, prefetch, memory-write mirroring, session ingest) always use the **primary** container only. For self-hosting, set `base_url` in `supermemory.json` BEFORE running `hermes memory setup` so the setup connection probe also stays local.
- **Rebuild notes:** Buffer the session and ingest it once — one clean transcript beats N fragmentary writes for profile building. Container tags with an `{identity}` template give per-profile isolation for free. Better: make the session-ingest boundary configurable and expose ingest failures in the status line.

### `ContextEngine` ABC — pluggable context management  `id: memory.context-engine-abc`
- **Surface:** Core
- **Where:** `agent/context_engine.py`; selected by `context.engine` in config.yaml (default `"compressor"`).
- **What it does:** Defines the contract an engine implements to decide when to compact, how to compact, how to *select* context per turn, and which tools to expose. Only one engine is active.
- **How it works:** `class ContextEngine(ABC)` (`agent/context_engine.py:89`). Lifecycle documented in the module docstring: (1) instantiate + register (plugin `register()` or default); (2) `on_session_start()`; (3) `update_from_response()` after each API response; (4) `should_compress()` after each turn; (5) `compress()` when it returns True; (6) `on_session_end()` at real session boundaries only.
  **Token state the host reads directly:** `last_prompt_tokens`, `last_completion_tokens`, `last_total_tokens`, `threshold_tokens`, `context_length`, `compression_count` (all default 0).
  **Compaction parameters:** `threshold_percent = 0.75`, `protect_first_n = 3` (since PR #13754: the count of non-system head messages always preserved verbatim, IN ADDITION to the always-implicitly-protected system prompt), `protect_last_n = 6`, `emit_automatic_compaction_status = True`.
  **Abstract methods:** `name` (property), `update_from_response(usage)`, `should_compress(prompt_tokens=None)`, `compress(messages, current_tokens=None, focus_topic=None, force=False, memory_context="")`.
  **Optional overrides:** `should_compress_info(prompt_tokens=None) -> (bool, reason|None)` (base returns `(should_compress(...), None)`; richer engines surface a block reason such as a summary-LLM cooldown so callers can warn instead of silently skipping — added for the silent-overflow fix #62625 so plugin engines don't raise `AttributeError`); `prune_tool_results_only(messages, current_tokens=None) -> (messages, n_pruned)` (default safe no-op returning `(messages, 0)`, so the loop's post-tool-call prune never raises on an engine that predates the hook); `select_context(request_messages, conversation_messages=None, incoming_message=None, budget_tokens=0)`; `on_turn_complete(messages, usage=None, **kwargs)`; `should_compress_preflight(messages)` (default False); `should_defer_preflight_to_real_usage(rough_tokens)` (default False); `get_automatic_compaction_status_message(phase, default_message, **context)`; `has_content_to_compress(messages)` (default True — the gateway `/compress` preflight guard that lets it report "nothing to compress yet" without an LLM call); `on_session_start(session_id, **kwargs)`; `on_session_end(session_id, messages)`; `on_session_reset()` (default zeroes the three token counters and `compression_count`); `get_tool_schemas()` (default `[]`); `handle_tool_call(name, args, **kwargs)` (default returns `{"error": "Unknown context engine tool: <name>"}`); `get_status()`; `update_model(model, context_length, base_url="", api_key="", provider="", api_mode="")`.
  `update_from_response(usage)` always receives the legacy keys `prompt_tokens`/`completion_tokens`/`total_tokens`; newer hosts add the canonical buckets `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` — engines must treat those as optional.
  `get_status()` clamps the `-1` "compression just ran, awaiting real usage" sentinel to 0 so readers never see a negative `usage_percent`, and returns `{last_prompt_tokens, threshold_tokens, context_length, usage_percent (min(100, last/ctx*100) or 0), compression_count}`.
  `update_model()` snapshots the pre-override `threshold_percent` **once** into `_config_threshold_percent` so repeated model switches fall back to the configured value rather than the previous model's override, resolves a per-model override with `agent.context_compressor.resolve_model_threshold(model, self.model_thresholds, self._config_threshold_percent)` (longest-substring match), and recomputes `threshold_tokens = int(context_length * threshold_percent)`.
- **Inputs / options:** as enumerated above.
- **Outputs / side effects:** A rewritten message list (compression), a replaced request list (selection), engine tools.
- **Config / env:** `context.engine` (default `"compressor"`).
- **Edge cases / guards:** `select_context()` returns a **request-only** list — it replaces what is sent for one call and MUST NOT be treated as persisted transcript state; the DB history is untouched so nothing leaks across turns. Ordering contract: the host runs it BEFORE prompt cache-control and BEFORE every request sanitizer (orphaned-tool cleanup, thinking-only/role normalization, whitespace/JSON normalization), so a malformed replacement can never reach the provider and the default no-op leaves the request byte-identical (prompt-cache stability is an AGENTS.md invariant). It is evaluated per provider request, so it re-runs on retries within a turn. `on_turn_complete()` fires from the standard finalization seam only — some abnormal early returns (content-policy block, provider terminal failure) persist and return without it, so it is explicitly best-effort; `kwargs` may include `turn_id`, `task_id`, `api_call_count`, `interrupted`, `failed`, `turn_exit_reason`, and `usage` is `None` on turns that never reached a provider response.
- **Rebuild notes:** Separate the two verbs — `compress()` (too long → shorter) and `select_context()` (wrong context → different one) — and give the engine a post-turn observation hook so it never has to abuse `should_compress()` as a per-turn callback. Version every new kwarg with a default so old engines keep working.

### Memory-context sanitization for the compression boundary  `id: memory.context-engine-sanitize`
- **Surface:** Core
- **Where:** `agent/context_engine.py:40` `sanitize_memory_context()`.
- **What it does:** Prepares memory-provider context before it crosses the context-engine/LLM egress boundary — redacts secrets and hard-caps the size.
- **How it works:** `redact_sensitive_text(memory_context.strip(), force=True, redact_url_credentials=True)` then, if longer than `MEMORY_CONTEXT_MAX_CHARS = 6_000`, returns `sanitized[:4000] + "\n...[memory provider context truncated]...\n" + sanitized[-1500:]` (`_MEMORY_CONTEXT_HEAD_CHARS = 4_000`, `_MEMORY_CONTEXT_TAIL_CHARS = 1_500`, `_MEMORY_CONTEXT_TRUNCATION_MARKER`).
- **Inputs / options:** `memory_context: str`.
- **Outputs / side effects:** The sanitized string handed to a summarizing engine's handoff prompt.
- **Config / env:** n/a.
- **Edge cases / guards:** `force=True` bypasses any "redaction disabled" setting — this is an egress boundary.
- **Rebuild notes:** Head+tail truncation with an explicit marker preserves both the framing and the most recent facts; a middle-cut is better than a tail-cut for recalled memory.

### Automatic-compaction status suppression  `id: memory.compaction-status`
- **Surface:** Core
- **Where:** `agent/context_engine.py:56` `automatic_compaction_status_message()`; the effect is a chat status line during automatic compaction.
- **What it does:** Lets an alternative engine keep successful automatic compaction passes silent (treating them as routine background maintenance) or customize the wording, while warnings, errors, and explicit manual `/compress` still surface.
- **How it works:** Returns `None` immediately when `engine.emit_automatic_compaction_status` is False. Otherwise, if the engine defines `get_automatic_compaction_status_message(phase=…, default_message=…, **context)` it is called; else `default_message` is used. `None` or an empty/whitespace string means "do not emit". `phase` identifies the host call site (e.g. `"preflight"`, `"compress"`); `context` carries best-effort fields such as `approx_tokens` and `threshold_tokens`.
- **Inputs / options:** `engine`, `phase`, `default_message`, `**context`.
- **Outputs / side effects:** A status string or `None`.
- **Config / env:** engine attribute `emit_automatic_compaction_status`.
- **Edge cases / guards:** Does not control warning/error messages or manual commands.
- **Rebuild notes:** Give the plugin two levers — a boolean off-switch and a formatter — and make empty mean "silent".

### Context-engine plugin discovery + loading  `id: memory.context-engine-plugins`
- **Surface:** Core
- **Where:** `plugins/context_engine/<name>/`; selected with `context.engine`.
- **What it does:** Scans repo-local context-engine plugin directories and loads exactly one engine instance.
- **How it works:** `plugins/context_engine/__init__.py`. Context engines are separate from the general plugin system — they live in the repo and are always available without user installation. `discover_context_engines() -> [(name, description, is_available)]` iterates `plugins/context_engine/*/` (skipping `_`/`.`-prefixed dirs and dirs without `__init__.py`), reads `plugin.yaml` `description`, and probes availability by loading the engine and calling `is_available()` when present. `load_context_engine(name)` returns an instance or `None`. `_load_engine_from_dir()` mirrors the memory-provider loader: registers parent packages `plugins` and `plugins.context_engine` in `sys.modules`, loads the module as `plugins.context_engine.<name>` with `submodule_search_locations`, pre-registers every sibling `*.py` so relative imports work, then tries `register(ctx)` with an `_EngineCollector` and falls back to instantiating the first `ContextEngine` subclass found.
  `_EngineCollector` captures `register_context_engine(engine)` and also forwards `register_command(name, handler, description="", args_hint="")` to the global plugin command registry: the name is lowercased, stripped, `/`-stripped and spaces replaced with `-`; an empty name warns and returns; a name colliding with a built-in (`hermes_cli.commands.resolve_command`) warns `"…conflicts with a built-in command. Skipping."`; a name already held by a plugin warns `"…is already registered by a plugin. Skipping."`; otherwise it writes `manager._plugin_commands[clean] = {"handler", "description" (default "Context engine command"), "plugin": f"context-engine:<name>", "args_hint"}`. `register_tool`, `register_hook`, `register_cli_command` and `register_memory_provider` are explicit no-ops.
- **Inputs / options:** `context.engine` name.
- **Outputs / side effects:** `sys.modules` entries; plugin slash commands (e.g. `/lcm`).
- **Config / env:** `context.engine` (default `"compressor"`).
- **Edge cases / guards:** In v2026.8.31 `plugins/context_engine/` ships **only** `__init__.py` — there are no bundled alternative engines; the directory exists for third-party drops (the docstring's worked example is LCM with `lcm_grep`, `lcm_describe`, `lcm_expand`).
- **Rebuild notes:** Same loader shape as memory providers but without the four-source precedence, because engines are repo-local only.

### `hermes journey` — learning timeline  `id: memory.cli-journey`
- **Surface:** CLI
- **Where:** `hermes journey [--reveal 0..1] [--play] [--fps FPS] [--width W] [--height H] [--no-color] [--json] {list,delete,edit}`. Aliases: `hermes learning`, `hermes memory-graph`. Mirrors the TUI `/journey` overlay and the desktop Star Map / Memory Graph panel.
- **What it does:** Renders a terminal timeline bar chart of learned skills and memory chunks over time (oldest at top, newest at bottom) plus a playable constellation scrubber, and lets you prune/correct what Hermes has learned.
- **How it works:** `hermes_cli/journey.py`. Payload from `agent.learning_graph.build_learning_graph()`; layout and palette from `agent.learning_graph_render` so CLI, TUI and desktop draw identical data. Palette: `derive_palette(primary_hex, dark=True)` where the primary comes from the active skin's `ui_primary` (fallback `banner_title`, fallback `#FFD700`); title colour `#E8C463`; age tinting fades each ink toward the background by an alpha, but "charted signals" labels are lifted toward black/white until they clear `_CHARTED_SIGNAL_MIN_CONTRAST = 4.5` (WCAG contrast, 20 mixing steps of 0.05, falling back to the pure pole). Terminal size defaults to `(90, 30)` with floors `max(40, width)` / `max(10, height)`; inner width is `max(24, cols-2)` and the field gets `max(6, rows - 10 - len(summary))` rows. Frame composition: title `"✦ Journey "` + `"· learned skills & memories over time"`; a legend row of `glyph + label` pairs; an optional category row; a blank line; the graph grid (each line padded left 2); a date axis with the start label left and end label right; a footer `"◷ <date>   <visible>/<count> revealed · <pct>%"`; then, when present, `"  charted signals"` and up to 6 rows of `"<key> <glyph> <label>  <meta truncated to 32 chars with …>"`; then the summary lines. `--play` runs a `rich.live.Live` animation of 42 frames at `1/clamp(fps,1,60)` seconds each, ending on `reveal=1.0`; Ctrl-C prints `"interrupted"` and exits 130. Empty graph prints *"No learning yet — use Hermes a while and your learned skills and memories will start mapping out here."*
  **Graph assembly** (`agent/learning_graph.py`): skill roots are `("base", <repo>/skills)` and `("profile", <HERMES_HOME>/skills)`; every `SKILL.md` under them is parsed (first 4000 chars) for frontmatter, skipping any path containing `.archive`, `.hub`, `node_modules`, `.git`. A `SkillNode` carries `name, category, source, timestamp, use_count, state, created_by, pinned, related`; `category` comes from frontmatter `category` or `metadata.hermes.category`, else the `<category>` path segment in `…/skills/<category>/<skill>/SKILL.md`, else `"general"`. `timestamp` is the first present of usage `last_activity_at | last_used_at | last_viewed_at | last_patched_at | created_at`, else the file mtime. Only **learned** skills enter the graph: `source != "base" AND (created_by == "agent" OR use_count > 0)`. Skill↔skill edges come from declared `related_skills` (undirected, deduped, both endpoints must exist). Memory cards come from `_memory_cards()`: `MEMORY.md` then `USER.md`, split on `"\n§\n"`, each non-empty chunk becoming a card with `source` (`memory`|`profile`), `timestamp = file_mtime + chunk_index`, `title` = the first line stripped of leading `# ` truncated to 80 chars + `…`, and `body` = the first 1200 chars. Memory↔skill edges are lexical: tokens are `[^a-z0-9]+`-split lowercase words of length ≥ 3; a skill scores `+6` if its lowercased name appears in the card text plus one point per shared token; the top 4 scoring skills get edges. The payload is `{nodes, edges, clusters, memory, stats}` where node ids are the skill name or `memory:<source>:<index>` and `stats` merges `density_stats` (`nodes, related_edges, edges_per_node, linked_nodes, isolated_pct, categories, agent_created, used, top_categories[:8]`) with `memory_nodes`, `memory_skill_edges`, `learned_skills`.
- **Inputs / options:** Top-level flags: `--reveal 0..1` (default 1.0, clamped) "Render the timeline built up to this point (0=oldest, 1=now)."; `--play` "Animate the build-up over time (Ctrl-C to stop)."; `--fps FPS` (default 12); `--width WIDTH`; `--height HEIGHT`; `--no-color`; `--force-color` (SUPPRESSed from help — forces truecolor ANSI so the interactive CLI can capture and re-render it through prompt_toolkit); `--json` "Print the raw graph payload as JSON and exit."; `-h/--help`. Subcommands: `list [--no-color]`, `delete <node> [-y/--yes]`, `edit <node>`.
- **Outputs / side effects:** Terminal rendering, or JSON on `--json`. `delete`/`edit` mutate skills and memory files.
- **Config / env:** `HERMES_HOME`; the active skin; `$EDITOR` / `$VISUAL` (fallback `vi`) for `edit`.
- **Edge cases / guards:** `--json` prints via `Console.print_json` and exits 0 even with no nodes.
- **Rebuild notes:** One payload builder, three renderers. Node ids must be stable and human-typable; derive memory↔skill edges lexically when you have no embeddings. Better: persist per-node creation timestamps instead of deriving them from file mtime + index (the current scheme makes ids and times shift when a file is rewritten).

### `hermes journey list`  `id: memory.cli-journey-list`
- **Surface:** CLI
- **Where:** `hermes journey list [-h] [--no-color]`
- **What it does:** Lists every graph node id with its glyph, label and date, so you know what to pass to `delete`/`edit`.
- **How it works:** `_cmd_list()` (`hermes_cli/journey.py:295`) sorts nodes by `timestamp or 0` ascending and prints `"<id>  <glyph> <label>  <date>"` where the glyph is `◆` for memory nodes and `●` for skills, and the date comes from `agent.learning_graph_render.format_date`. Empty graph prints `"No learning yet."`.
- **Inputs / options:** `--no-color`, `--force-color` (hidden), `-h/--help`.
- **Outputs / side effects:** stdout.
- **Config / env:** n/a.
- **Edge cases / guards:** Node ids are `<skill-name>` or `memory:<memory|profile>:<global index>`.
- **Rebuild notes:** Always print the exact id the mutating verbs accept.

### `hermes journey delete <node>`  `id: memory.cli-journey-delete`
- **Surface:** CLI
- **Where:** `hermes journey delete [-h] [-y] node`
- **What it does:** Deletes a learned skill (archived, restorable) or a memory chunk (rewritten out of its file).
- **How it works:** `_cmd_delete()` (`hermes_cli/journey.py:311`) resolves the node with `agent.learning_mutations.node_detail()`; a miss prints the failure message and exits 1. Without `-y` it prompts `"  Delete '<label>'? [y/N] "` and accepts only `y`/`yes` (case-insensitive); anything else, EOF, or Ctrl-C prints `"  aborted"` and exits 1. `delete_node()` (`agent/learning_mutations.py:123`) dispatches: **skill** → refuses when `skill_usage.get_record(name)["pinned"]` with `"'<name>' is pinned — unpin it first (hermes curator unpin <name>)"`, else `skill_usage.archive_skill(name)` and, on success, clears the skills system-prompt cache and reports `"archived '<name>' — restore with: hermes curator restore <name>"`; **memory** → `_parse_memory_id` splits `memory:<source>:<index>`, `_locate_memory` maps the global index to the file-local index (all `MEMORY.md` cards precede all `USER.md` cards, so a profile card's local index is `global - count(memory cards)`), the chunk is removed, and the file is rewritten through `MemoryStore._write_file` (atomic temp+rename, `§`-join single-sourced) with the message `"deleted memory from <FILE>.md"`.
- **Inputs / options:** `node` (positional, required) "Node id (skill name or memory:<source>:<index>; see `journey list`)."; `-y/--yes` "Skip the confirmation prompt."; `-h/--help`.
- **Outputs / side effects:** Archives a skill directory or rewrites `MEMORY.md`/`USER.md`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** A stale id (the card at that index now belongs to the other source, or the index is out of range) fails with `"memory node id is stale — refresh the graph"`; a missing file fails with `"<FILE>.md not found"`; a malformed id fails with `"bad memory node id: '<id>'"`.
- **Rebuild notes:** Archive skills (recoverable) but hard-delete memory chunks; validate the derived index against the live card list so a stale id can never delete the wrong entry.

### `hermes journey edit <node>`  `id: memory.cli-journey-edit`
- **Surface:** CLI
- **Where:** `hermes journey edit [-h] node`
- **What it does:** Opens a learned skill's `SKILL.md` or a memory chunk in `$EDITOR` and writes back the result.
- **How it works:** `_cmd_edit()` (`hermes_cli/journey.py:327`). `node_detail()` returns `{ok, kind, id, label, content}` — for memory, `content` is the raw `§` chunk and `label` is its first line truncated to 80 chars; for a skill, `content` is the whole `SKILL.md` (resolved via `tools.skill_manager_tool._find_skill`) and `label` is the skill name. `_open_in_editor(initial, suffix)` writes a `NamedTemporaryFile` with suffix `.md` (skill) or `.txt` (memory), runs `subprocess.call([*editor.split(), path])` with `EDITOR` → `VISUAL` → `vi`, reads it back and unlinks it (an `OSError` prints `"  editor failed: <exc>"` and returns None). Unchanged content prints `"  no changes"` and exits 0. Otherwise `edit_node()` dispatches: skill → `skill_manager_tool._edit_skill` then clears the prompt cache, message `"updated '<name>'"`; memory → an empty body is refused with `"empty memory — use delete to remove it"`, else the chunk is replaced and the file rewritten with `"updated memory in <FILE>.md"`.
- **Inputs / options:** `node` (positional, required); `-h/--help`.
- **Outputs / side effects:** Rewrites a `SKILL.md` or a memory file; clears `agent.prompt_builder.clear_skills_system_prompt_cache(clear_snapshot=True)`.
- **Config / env:** `EDITOR`, `VISUAL`, `HERMES_HOME`.
- **Edge cases / guards:** The temp file is always unlinked in a `finally`. Skill edits go through the normal `skill_manager_tool._edit_skill` validation path, so a malformed `SKILL.md` is rejected there and reported as `"<error>"`.
- **Rebuild notes:** Round-trip through a temp file with a type-appropriate suffix so the editor picks the right syntax mode; diff before writing so a no-op edit is free.

### SQLite session store (`state.db`) — schema  `id: memory.session-db-schema`
- **Surface:** Core
- **Where:** `<HERMES_HOME>/state.db` (default `~/.hermes/state.db`), WAL mode. Read by `hermes sessions …`, `/sessions`, `/resume`, the dashboard, the Desktop app, `session_search`, and `hermes insights`.
- **What it does:** Stores every conversation from every surface (CLI, TUI, gateway platforms, cron, batch, API server, ACP, webhook) with full message history, metadata, cost accounting, and FTS5 search.
- **How it works:** `SCHEMA_SQL` in `hermes_state_common.py:385`, `SCHEMA_VERSION = 26` (`:322`). Tables:
  - **`schema_version(version INTEGER NOT NULL)`**
  - **`system_prompts(hash TEXT PRIMARY KEY, prompt TEXT NOT NULL)`** — deduplicated system prompts.
  - **`sessions`** — `id TEXT PRIMARY KEY, source TEXT NOT NULL, user_id, session_key, chat_id, chat_type, thread_id, display_name, origin_json, expiry_finalized INTEGER DEFAULT 0, model, model_config, system_prompt, system_prompt_hash, parent_session_id, started_at REAL NOT NULL, ended_at REAL, end_reason, message_count INTEGER DEFAULT 0, tool_call_count INTEGER DEFAULT 0, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens (all INTEGER DEFAULT 0), cwd, git_branch, git_repo_root, git_metadata_generation INTEGER NOT NULL DEFAULT 0, billing_provider, billing_base_url, billing_mode, estimated_cost_usd REAL, actual_cost_usd REAL, cost_status, cost_source, pricing_version, title, title_source, last_activity_at REAL, last_activity_description, last_activity_provenance, api_call_count INTEGER DEFAULT 0, handoff_state, handoff_platform, handoff_error, compression_failure_cooldown_until REAL, compression_failure_error, compression_fallback_streak INTEGER NOT NULL DEFAULT 0, compression_ineffective_count INTEGER NOT NULL DEFAULT 0, profile_name, rewind_count INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0, last_read_at REAL`, with `FOREIGN KEY (parent_session_id) REFERENCES sessions(id)` and `FOREIGN KEY (system_prompt_hash) REFERENCES system_prompts(hash)`.
  - **`messages`** — `id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id), role TEXT NOT NULL, content TEXT, tool_call_id, tool_calls, tool_name, effect_disposition, timestamp REAL NOT NULL, token_count INTEGER, finish_reason, reasoning, reasoning_content, reasoning_details, codex_reasoning_items, codex_message_items, platform_message_id, observed INTEGER DEFAULT 0, _compressed_summary INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, compacted INTEGER NOT NULL DEFAULT 0, api_content TEXT, display_kind TEXT, display_metadata TEXT`.
  - **`session_model_usage`** — per-(session, model, billing_provider, billing_base_url, billing_mode, task) composite-PK usage rows with `api_call_count`, the five token buckets, `estimated_cost_usd`, `actual_cost_usd`, `cost_status`, `cost_source`, `first_seen`, `last_seen`. (`task='background_review'` is how the memory/skill review fork's usage is attributed.)
  - **`state_meta(key TEXT PRIMARY KEY, value TEXT)`** — key/value control plane (FTS rebuild watermarks, prune timestamps, layout markers).
  - **`gateway_routing(scope TEXT NOT NULL DEFAULT '', session_key TEXT NOT NULL, entry_json TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (scope, session_key))`** — the real routing index.
  - **`gateway_hygiene_state(session_key TEXT PRIMARY KEY, failure_streak INTEGER NOT NULL DEFAULT 0)`**.
  - **`gateway_heartbeats(backend_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, started_at REAL NOT NULL, last_heartbeat REAL NOT NULL, profile TEXT NOT NULL DEFAULT '', host TEXT NOT NULL DEFAULT '')`** — per-backend liveness (#94895) so the startup orphan sweep does not reap rows whose backend is alive but idle; a backend whose `last_heartbeat` is stale is treated as dead, and rows with no matching heartbeat fall back to the original staleness predicate.
  - **`compression_locks(session_id PK, holder, acquired_at, expires_at)`**, **`session_turn_leases(conversation_id PK, holder, acquired_at, expires_at)`**, **`async_delegations(delegation_id PK, origin_session, origin_ui_session_id, parent_session_id, state, dispatched_at, completed_at, updated_at, event_json, result_json, delivery_state DEFAULT 'pending', delivery_attempts, delivered_at, owner_pid, owner_started_at, task_json, delivery_claim, delivery_claimed_at)`**.
  - **Indexes in `SCHEMA_SQL`:** `idx_sessions_source`, `idx_sessions_source_id`, `idx_sessions_parent`, `idx_sessions_started(started_at DESC)`, `idx_messages_session(session_id, timestamp)`, `idx_messages_session_id(session_id, id)`, the partial `idx_messages_assistant_calls_by_session ON messages(session_id) WHERE role='assistant' AND tool_calls IS NOT NULL` (for the Insights tool/skill-usage scan), `idx_compression_locks_expires`, `idx_session_turn_leases_expires`, `idx_session_model_usage_session`, `idx_session_model_usage_model`, `idx_async_delegations_delivery(delivery_state, completed_at)`.
  - **`DEFERRED_INDEX_SQL`** (created after `_reconcile_columns` adds later-version columns, so legacy DBs don't fail `executescript`): `idx_messages_session_active(session_id, active, timestamp)`, `idx_messages_active_null ON messages(active) WHERE active IS NULL`, `idx_sessions_session_key(session_key, started_at DESC)`, `idx_sessions_gateway_peer(source, user_id, chat_id, chat_type, thread_id, started_at DESC)`, `idx_sessions_handoff_state(handoff_state, started_at)`, `idx_sessions_system_prompt_hash`.
  Schema management follows the Beets/sqlite-utils pattern: `SCHEMA_SQL` is the single source of truth, `_parse_schema_columns(SCHEMA_SQL)` derives the expected columns per table (by executing the DDL into a scratch in-memory DB), and `_reconcile_columns()` ADDs any missing column on open — adding a column to `SCHEMA_SQL` is all that is needed.
- **Inputs / options:** n/a (storage).
- **Outputs / side effects:** `state.db` plus `-wal`/`-shm` sidecars; timestamped backups from repair commands.
- **Config / env:** `database.journal_mode` (default `"wal"`), `database.wal_autocheckpoint` (null), `database.journal_size_limit` (null), `HERMES_HOME`.
- **Edge cases / guards:** WAL mode gives concurrent readers with a single writer, which suits the gateway's multi-platform architecture. Titles carry a unique index (NULLs allowed; only non-NULL titles must be unique). `~/.hermes/sessions/sessions.json` is a **legacy mirror** of `gateway_routing`, written only when `gateway.write_sessions_json: true` (the default), and contains gateway entries only — it is NOT the session list. Legacy `*.jsonl` transcripts under `~/.hermes/sessions/` are no longer written or read.
- **Rebuild notes:** One table for sessions, one for messages, one for per-model usage, one KV table for control state, plus routing/lease/heartbeat tables. Derive the migration from the DDL rather than hand-writing ALTERs. A better version would split message content into a side table so metadata scans never touch blob pages.

### FTS5 search index (v23 external-content layout)  `id: memory.session-fts5`
- **Surface:** Core
- **Where:** `messages_fts` and `messages_fts_trigram` inside `state.db`; used by `session_search`, `/sessions` search, and the dashboard.
- **What it does:** Full-text search over message content, tool names, and tool-call JSON, with a separate trigram index so CJK/Thai substring queries work.
- **How it works:** `FTS_SQL` (`hermes_state_common.py:637`): `CREATE VIRTUAL TABLE messages_fts USING fts5(content, tool_name, tool_calls, content='messages', content_rowid='id')` — external-content, so the index stores no duplicate copy of the text. Three triggers keep it in sync: `messages_fts_insert AFTER INSERT`, `messages_fts_delete AFTER DELETE`, and `messages_fts_update AFTER UPDATE OF content, tool_name, tool_calls` (the `UPDATE OF` clause skips the trigger entirely for status/compacted/observed writes, which is stronger than the `WHEN` gate alone and avoids FTS I/O saturation on large DBs — #68858 / #73639). Every trigger additionally gates on the **deferred-rebuild predicate**: a row is indexed iff `id <= P` (backfilled) OR `id > H` (inserted after the drop), where `H = state_meta['fts_rebuild_high_water']` (MAX(messages.id) when the old indexes were dropped) and `P = state_meta['fts_rebuild_progress']` (highest id the chunked backfill has reached); rows in `(P, H]` are not yet indexed. When no rebuild is pending both keys are absent and `COALESCE(...,-1)` makes the predicate a tautology. Firing an external-content `'delete'` for a row not in the index corrupts it, and skipping it for a row that IS indexed leaves a stale entry — hence the identical gate on all three triggers.
  `FTS_TRIGRAM_SQL` (`hermes_state_common.py:704`): a view `messages_fts_trigram_src AS SELECT id, role, content, tool_name, tool_calls FROM messages WHERE role <> 'tool'`, then `CREATE VIRTUAL TABLE messages_fts_trigram USING fts5(content, tool_name, tool_calls, content='messages_fts_trigram_src', content_rowid='id', tokenize='trigram')` with three matching triggers gated on `role <> 'tool'` plus the same rebuild predicate. Rationale: the trigram index is the most expensive index in `state.db` (~2.6× the size of the text it covers) and `role='tool'` rows are ~90% of message bytes while being almost entirely machine noise (base64 payloads, file dumps, delegation transcripts); tool rows stay fully stored and fully searchable via `messages_fts`, they just get no trigram treatment. `search_messages` routes CJK queries that filter on `role='tool'` to the LIKE fallback for the same reason.
  **Layout versioning:** `FTS_STORAGE_VERSION = 1` (v23 external-content layout) tracked in `state_meta['fts_storage_version']` INDEPENDENTLY of `SCHEMA_VERSION` — the main schema version advances freely on open, but the FTS *layout* only reaches the current version when a DB is born fresh or explicitly optimized. A legacy DB sits at layout 0 (marker absent) with a working inline index until the user opts in. `LEGACY_FTS_SQL` / `LEGACY_FTS_TRIGRAM_SQL` are the exact v11–v22 inline shapes (each virtual table stores its own copy of `content || ' ' || tool_name || ' ' || tool_calls`, and the trigram table indexes every row including tools); they are never created on a fresh install and exist only so a legacy DB is never handed the v23 DDL (which would create the trigram source VIEW and leave a mixed, broken state).
  **Breadcrumbs in `state_meta`:** `fts_cjk_stale` (`FTS_CJK_STALE_KEY`) — set when a tokenizer-less process had to drop the cjk triggers to keep writes alive, so the cjk index must not serve reads until `hermes sessions optimize-storage` rebuilds it on a capable host; `fts_stale` (`FTS_STALE_KEY`) — a base/trigram index detached from `messages` after runtime corruption, requiring a complete rebuild before triggers are reinstalled; `fts_rebuild_deferral` (`FTS_REBUILD_DEFERRAL_KEY`) — durable diagnostic for stale-FTS recovery blocked across process restarts.
  **Cross-process admission:** every FULL structural rebuild entry point (`SessionSearchMixin.rebuild_fts()`, `SessionSchemaMixin._rebuild_fts_indexes()` via `_init_schema`, `_recover_stale_fts()`) goes through one portable file-lock admission authority (msvcrt on Windows, flock elsewhere), bounded wait, **fail closed** — two concurrent rebuilds have structurally corrupted `state.db` in production (PR #93200; the 2026-08-15 / 2026-08-23 incidents, issues #89293 / #90950). The chunked deferred backfill (`fts_rebuild_step`) is deliberately NOT routed through it: it claims progress under `_execute_write`'s SQLite transaction authority and is intentionally multi-process.
  Trigger name sets: `_FTS_TRIGGERS` = `messages_fts_insert/delete/update` + `messages_fts_trigram_insert/delete/update`, split into `_FTS_BASE_TRIGGERS` and `_FTS_TRIGRAM_TRIGGERS` (they have different repair paths because the trigram DDL needs the trigram tokenizer); `_FTS_CJK_TRIGGERS` = `messages_fts_cjk_insert/delete/update` (dropped legacy names).
- **Inputs / options:** FTS5 query syntax — bare keywords (AND by default), `"exact phrase"`, `docker OR kubernetes`, `python NOT java`, `deploy*` prefix.
- **Outputs / side effects:** Index rows; `state_meta` markers.
- **Config / env:** `sessions.cjk_fts` (default `true`), `sessions.fts_optimize_notice` (default `"advise"`), `sessions.search_slow_ms` (default `1000`).
- **Edge cases / guards:** `MAX_FTS5_QUERY_CHARS = 2_048` caps user-controlled query input before regex/sanitizer processing so behaviour stays predictable under adversarial input. `_sqlite_supports_fts5()` probes by creating `temp._hermes_fts5_probe`; without FTS5 the index is skipped entirely.
- **Rebuild notes:** External-content FTS5 + `UPDATE OF` triggers + a resumable watermark pair (`high_water`, `progress`) is the pattern that makes a multi-GB index rebuildable online. Never let two structural rebuilds run at once.

### `hermes sessions list`  `id: memory.cli-sessions-list`
- **Surface:** CLI
- **Where:** `hermes sessions list [-h] [--source SOURCE] [--limit LIMIT] [--workspace NEEDLE]`
- **What it does:** Lists recent sessions with title, preview, relative last-active time, source, and id.
- **How it works:** `hermes_cli/sessions_cmd.py` + `hermes_cli/session_listing.py`. Two output shapes: when any listed session has a title, columns are `Title | Preview | Last Active | ID`; when none do, `Preview | Last Active | Src | ID`. "Last active" uses the freshest of `sessions.last_activity_at` and `MAX(messages.timestamp)`, falling back to `started_at` (`_sql_session_last_active`, `hermes_state_common.py:284`) — a rate-limited (~60 s) durable heartbeat must never win over a newer message. Previews come from `_PREVIEW_RAW_SELECT` (`hermes_state_common.py:145`): a compaction-carrier row yields the text after `_SUMMARY_END_MARKER` (force-user-leading) or the unwrapped prior-context half of a merged summary; a `/skill`-scaffolded row yields a wide excerpt (the whole message up to `_PREVIEW_SCAFFOLD_WINDOW*2 = 800` chars, else head 400 + `SKILL_EXCERPT_JOINT` + tail 400) so `describe_skill_invocation` can recover `"/work — fix the title leak"`; anything else yields the first `_PREVIEW_HEAD_CHARS = 63` characters. `_shape_preview()` then strips newlines, applies `describe_skill_invocation`, and truncates to `_PREVIEW_MAX_CHARS = 60` with `"..."`. Which rows are listable is `_LISTABLE_CHILD_SQL`: roots plus branch children (`model_config.$._branched_from` marker, or the legacy heuristic "parent ended with `branched` and the child started at/after the parent's end") plus reset children (`model_config.$._reset_from` marker, or the legacy same-non-empty-`session_key` + parent end reason in `session_reset|session_switch|idle|daily|suspended|resume_pending_expired`). Subagent runs and compression continuations stay hidden.
- **Inputs / options:** `--source SOURCE` "Filter by source (cli, telegram, discord, etc.)"; `--limit LIMIT` "Max sessions to show"; `--workspace NEEDLE` "Only sessions in one workspace: a git repo root or project dir (matched by path substring or basename)."; `-h/--help`.
- **Outputs / side effects:** stdout table.
- **Config / env:** n/a.
- **Edge cases / guards:** Archived sessions are hidden. Default limit is 20 per the docs.
- **Rebuild notes:** Compute "last active" as a max over heartbeat and message time; make previews aware of every synthetic message shape your system injects, or listings become unreadable after the first compaction.

### `hermes sessions export`  `id: memory.cli-sessions-export`
- **Surface:** CLI
- **Where:** `hermes sessions export [options] [output]`
- **What it does:** One surface for five export formats over one selection filter set — backups, readable archives, shareable HTML, and Hugging Face agent traces.
- **How it works:** `hermes_cli/session_export.py` (JSONL/dispatch), `session_export_md.py` (Markdown/QMD), `session_export_html.py` (HTML), plus the trace writer. Selection uses the shared filter parser in `hermes_cli/session_filters.py` (same as `prune`/`archive`). Markdown/QMD write one file per session into `<hermes home>/session-exports` (overridable by the positional `output`) plus a `manifest.jsonl` carrying the file path, message count, lineage ids, and SHA-256. HTML writes a single self-contained page with styled message bubbles, collapsible tool output, and — for multi-session exports — a sidebar switcher; no remote dependencies. `--format trace` emits Claude Code JSONL, the transcript shape the Hugging Face Hub auto-detects for its Agent Trace Viewer; bulk trace export writes one `<id>.trace.jsonl` per session.
- **Inputs / options:** Positional `output` — "Output path. JSONL: file path (use - for stdout, required). md/qmd: output directory (default: <hermes home>/session-exports)". Flags: `--format {jsonl,md,qmd,html,trace}` (default `jsonl`; "'trace' emits Claude Code JSONL for the Hugging Face Agent Trace Viewer"); `--upload` (trace only — "upload to your Hugging Face traces dataset instead of writing a local file (needs HF_TOKEN)"); `--public` (trace `--upload` only — "create/update a public dataset instead of private"); `--no-redact` (trace only — "skip the forced secret redaction; only use after manual review"); `--only {user-prompts}` ("Export only a filtered view (user-prompts: one prompt record per line for jsonl, headed sections for md)"); `--session-id SESSION_ID` ("Session ID or unique prefix to export"); `--older-than AGE`; `--newer-than AGE`; `--before TIME`; `--after TIME`; `--source SOURCE`; `--title TITLE`; `--end-reason END_REASON`; `--cwd CWD`; `--min-messages N`; `--max-messages N`; `--model MODEL`; `--provider PROVIDER`; `--user USER`; `--chat-id CHAT_ID`; `--chat-type CHAT_TYPE`; `--branch BRANCH`; `--min-tokens N`; `--max-tokens N`; `--min-cost N`; `--max-cost N`; `--min-tool-calls N`; `--max-tool-calls N`; `--dry-run`; `--yes/-y`; `--redact` ("Redact secrets (API keys, tokens, credentials) from exported content"); `--lineage {single,logical}` (md/qmd only — "export one row or its compression lineage"); `--delete-after-verified` (md/qmd only — "after verified single-session export, delete that session (needs --yes)"); `--force` (md/qmd only — "overwrite an existing export file"); `-h/--help`.
- **Outputs / side effects:** Files on disk (or stdout with `-`), a `manifest.jsonl` for md/qmd, an HF dataset push with `--upload`, and — only with `--delete-after-verified --yes` — a session deletion.
- **Config / env:** `sessions.max_export_messages` (default `20000`); `HF_TOKEN` for `--upload`.
- **Edge cases / guards:** Bulk md/qmd export **requires at least one filter** — a bare bulk export is refused. `--delete-after-verified` is intentionally limited to `--session-id` and requires `--yes`; because deleting a parent also removes its delegate/subagent sessions, this mode exports and verifies each delegate in a separate file first, and refuses deletion if the delegate set changes during export. Trace exports are secret-redacted by default (they are meant to leave the machine) and `--upload` is private unless `--public`. Bulk filters match **ended** sessions; an unfiltered `export` dumps everything including active ones.
- **Rebuild notes:** One selection layer, N serializers. Verify-then-delete must re-check the delegate set, and any format destined to leave the machine must redact by default with an explicit opt-out.

### `hermes sessions import`  `id: memory.cli-sessions-import`
- **Surface:** CLI
- **Where:** `hermes sessions import [-h] [--from {claude,codex}] [path]`; also `hermes --resume @claude` / `hermes --resume @codex`.
- **What it does:** Pulls a conversation started in Claude Code (`~/.claude/projects`) or Codex CLI (`~/.codex/sessions`) into the Hermes session store so it can be resumed with `hermes --resume <id>`. The foreign files are only read, never modified.
- **How it works:** `hermes_cli/foreign_sessions.py` (+ `sessions_cmd.py` wiring). Without `path` it shows an interactive picker across both tools, newest first. Creates a new Hermes session titled `Imported from Claude Code: <first user message>` (or `Imported from Codex CLI: …`) and prints the id plus a ready-to-paste `hermes --resume <id>`. What carries over: the ordered user/assistant conversation, with tool activity condensed to short `[ran tool: …]` notes inside assistant turns. What is left behind: system prompts, injected context, reasoning traces, and raw tool output — the import is a clean transcript, not a byte-for-byte replay.
- **Inputs / options:** `path` (positional, optional) "Path to a specific session JSONL file (skips the picker)"; `--from {claude,codex}` "Which tool to import from (default: pick across both)"; `-h/--help`.
- **Outputs / side effects:** A new row in `sessions` plus its `messages`.
- **Config / env:** n/a.
- **Edge cases / guards:** The foreign directories are read-only inputs.
- **Rebuild notes:** Normalize to your own transcript shape and label the provenance in the title; never mutate the other tool's files.

### `hermes sessions delete`  `id: memory.cli-sessions-delete`
- **Surface:** CLI
- **Where:** `hermes sessions delete [-h] [--yes] session_id`
- **What it does:** Deletes one session (and, by cascade, its delegate/subagent children).
- **How it works:** `hermes_cli/sessions_cmd.py`. Prompts unless `--yes`.
- **Inputs / options:** `session_id` (positional, required) "Session ID to delete"; `--yes, -y` "Skip confirmation"; `-h/--help`.
- **Outputs / side effects:** Removes rows from `sessions`, `messages`, `session_model_usage` (ON DELETE CASCADE) and the FTS indexes via the delete triggers.
- **Config / env:** n/a.
- **Edge cases / guards:** Remaining child sessions (branches) are orphaned rather than deleted so the FK stays satisfied (`hermes_state.py:14068`).
- **Rebuild notes:** Cascade usage rows, orphan branch children, and let the FTS triggers handle index cleanup.

### `hermes sessions prune`  `id: memory.cli-sessions-prune`
- **Surface:** CLI
- **Where:** `hermes sessions prune [filters] [--dry-run] [--yes] [--include-archived] [--include-pinned] [--never-active]`
- **What it does:** Deletes old **ended** sessions, filterable by time window, source, title, model, provider, cost, tokens, tool calls, and messaging origin.
- **How it works:** `hermes_cli/sessions_cmd.py` + `hermes_cli/session_filters.py`. Time semantics: `--older-than`/`--newer-than` use **latest message activity** (falling back to session start for empty sessions); `--before`/`--after` use **session start time** explicitly. All values accept a duration (`5h`, `30m`, `2d`, `1w`), a bare number of days, or an ISO timestamp (`2026-07-05`, `2026-07-05 14:30`). Attribute filters: `--source` (exact), `--title`/`--model`/`--branch` (case-insensitive substring), `--provider` (exact), `--end-reason`/`--user`/`--chat-id`/`--chat-type` (exact), `--cwd` (path prefix); numeric bounds `--min/--max-messages`, `--min/--max-tokens` (input+output), `--min/--max-cost` (USD, actual falling back to estimated), `--min/--max-tool-calls`. All filters AND together. **Using any filter disables the implicit 90-day default** — only a completely bare `hermes sessions prune` keeps the 90-day cutoff. Every non-`--yes` run shows the match count plus the oldest and newest matching session before asking for confirmation. Operator-supplied substrings are escaped with `escape_like()` (`hermes_state_common.py:48`, escaping `\`, `%`, `_`, paired with `ESCAPE '\'`) so a `_` in a branch name or path cannot silently widen the match.
- **Inputs / options:** `--older-than AGE`, `--newer-than AGE`, `--before TIME`, `--after TIME`, `--source`, `--title`, `--end-reason`, `--cwd`, `--min-messages`, `--max-messages`, `--model`, `--provider`, `--user`, `--chat-id`, `--chat-type`, `--branch`, `--min-tokens`, `--max-tokens`, `--min-cost`, `--max-cost`, `--min-tool-calls`, `--max-tool-calls`, `--dry-run` ("List matching sessions without changing anything"), `--yes/-y`, `--include-archived` ("Also delete archived sessions (excluded by default)"), `--include-pinned` ("Also delete pinned sessions (excluded by default — pin is a keep flag)"), `--never-active` ("Instead of ended sessions, delete keyed gateway rows that were opened and never used (no messages, tokens, tool calls or title) and are older than AGE (default 30 days). Ordinary prune can never reach these — it only ever selects ended sessions"), `-h/--help`.
- **Outputs / side effects:** Deletes rows; a VACUUM may follow (see the auto-prune entry).
- **Config / env:** `sessions.retention_days` (default 90) is the bare-prune cutoff.
- **Edge cases / guards:** **Only ended sessions are ever pruned** — active sessions are never touched. Archived and pinned sessions are excluded by default.
- **Rebuild notes:** Two independent time axes (activity vs start), an implicit default that any explicit filter disables, and a dry-run that prints the extremes of the match set.

### `hermes sessions archive`  `id: memory.cli-sessions-archive`
- **Surface:** CLI
- **Where:** `hermes sessions archive [same filters as prune] [--dry-run] [--yes]`
- **What it does:** Bulk soft-hides sessions matching filters — sets the same `archived` flag as archiving a single session from the Desktop/Dashboard UI. No deletion; messages and search stay intact.
- **How it works:** Shares the filter parser with `prune`. Archived sessions are hidden from `hermes sessions list` and `/resume` but remain in the database and can be unarchived from the Desktop/Dashboard session list.
- **Inputs / options:** `--older-than`, `--newer-than`, `--before`, `--after`, `--source`, `--title`, `--end-reason`, `--cwd`, `--min-messages`, `--max-messages`, `--model`, `--provider`, `--user`, `--chat-id`, `--chat-type`, `--branch`, `--min-tokens`, `--max-tokens`, `--min-cost`, `--max-cost`, `--min-tool-calls`, `--max-tool-calls`, `--dry-run`, `--yes/-y`, `-h/--help`. (No `--include-archived` / `--include-pinned` / `--never-active` — those are prune-only.)
- **Outputs / side effects:** Sets `sessions.archived = 1`.
- **Config / env:** `sessions.auto_archive` (default `false`), `sessions.auto_archive_days` (default `3`) drive the automatic stale sweep that pinned sessions are exempt from.
- **Edge cases / guards:** **At least one filter is required** — a bare `hermes sessions archive` refuses to archive your entire history.
- **Rebuild notes:** A soft-hide flag shared by every surface beats per-surface hiding; require a filter for any bulk mutation.

### `hermes sessions rename`  `id: memory.cli-sessions-rename`
- **Surface:** CLI
- **Where:** `hermes sessions rename [-h] session_id title [title ...]`
- **What it does:** Sets or changes a session's title. Multi-word titles do not need quotes.
- **How it works:** `hermes_cli/sessions_cmd.py:1059`. `db.resolve_session_id(args.session_id)` accepts a full id or a unique prefix; a miss prints `"Session '<x>' not found."` and returns 1. The title is `" ".join(args.title)`. Guards (SES-05): a blank/whitespace-only title is rejected with `"Error: title cannot be empty or whitespace-only."` (it would render as `—`), and any `\n` or `\r` with `"Error: title cannot contain newlines."` (they corrupt the `list` table). Length is validated inside `db.set_session_title`. Success prints `"Session '<resolved>' renamed to: <title>"`; a `ValueError` (e.g. a duplicate title) prints `"Error: <msg>"` and returns 1.
- **Inputs / options:** `session_id` (positional, required); `title` (positional, one or more words, required); `-h/--help`.
- **Outputs / side effects:** Updates `sessions.title` (and `title_source`).
- **Config / env:** n/a.
- **Edge cases / guards:** Title rules (docs): unique across sessions, max 100 characters, sanitized (control characters, zero-width characters, and RTL overrides are stripped), normal Unicode (emoji, CJK, accents) allowed.
- **Rebuild notes:** Titles are a user-facing key — enforce uniqueness, cap length, and strip bidi/zero-width characters at the write.

### `hermes sessions pin` / `unpin` / `pinned`  `id: memory.cli-sessions-pin`
- **Surface:** CLI
- **Where:** `hermes sessions pin [-h] session_ids [session_ids ...]`, `hermes sessions unpin [-h] session_ids [...]`, `hermes sessions pinned [-h] [--json]`
- **What it does:** Sets/clears the durable **keep** flag. Pinned sessions are exempt from the `sessions.auto_archive` stale sweep and always appear in listings. It is the same flag the Desktop sidebar's Pinned section uses — pin from either surface and both see it.
- **How it works:** `hermes_cli/sessions_cmd.py:1085`. Each argument goes through `db.resolve_session_id()` (unique prefixes accepted); a miss prints `"Session '<raw>' not found."` and counts a failure (non-zero exit if any). Success prints `"Pinned session '<id>'."` / `"Unpinned session '<id>'."` with `"  (<title>)"` appended when a title exists. `pinned` calls `db.list_sessions_rich(limit=1, include_pinned=True, exclude_sources=_exclude)` — `limit=1` keeps the recency page minimal while `include_pinned` back-fills **all** pinned rows the page missed (bounded by the pin count), so old pins cannot fall off a paging window. Human output: header `"Title                            Last Active   Src       ID"` (widths 32/13/9) and a 100-char `─` rule; each row uses `title or preview or "—"` truncated to 30 chars and a relative last-active string. Empty: `"No pinned sessions. Pin one with: hermes sessions pin <session_id>"`. `--json` emits an indented array of `{id, title, source, last_active, message_count}`.
- **Inputs / options:** pin/unpin: `session_ids` (one or more ids or unique prefixes), `-h/--help`. pinned: `--json` ("Emit machine-readable JSON (for backup/restore scripting)"), `-h/--help`.
- **Outputs / side effects:** Updates `sessions.pinned`.
- **Config / env:** `sessions.auto_archive`, `sessions.auto_archive_days`.
- **Edge cases / guards:** `prune` skips pinned sessions unless `--include-pinned` is passed. Rationale in code (issue #52955): pin state is operational infrastructure, so every surface — GUI, TUI, CLI, scripts — needs read/write access to the same store.
- **Rebuild notes:** One durable boolean, written by every surface, honoured by every sweep; back-fill pinned rows outside the recency page so they never age out of the listing.

### `hermes sessions retitle-skills`  `id: memory.cli-sessions-retitle-skills`
- **Surface:** CLI
- **Where:** `hermes sessions retitle-skills [-h] [--apply] [--limit LIMIT]`
- **What it does:** Regenerates titles for sessions whose auto-title was derived from an expanded `/skill` body (so the title described the SKILL, not the user's request).
- **How it works:** `hermes_cli/sessions_cmd.py:1148`. `db.list_skill_scaffolded_sessions(limit=limit)` finds candidates (`limit` defaults to 200, floored at 1). For each, `agent.skill_commands.describe_skill_invocation(row["content"])` recovers what the user actually typed and `agent.title_generator.generate_title(typed)` produces a new title. A candidate is skipped when the new title is empty or identical. `_is_titlelike(candidate)` requires `candidate[0].isalnum()` — an auxiliary model sometimes answers the prompt instead of titling it and echoes assistant output (`"$ df -h /"`); the live path has no alternative, but this is a REPAIR, so a non-title candidate keeps the old title and prints `"  <id>\n    kept '<old>' — got '<new>'"`. Otherwise it prints `"  <id>\n    '<old>'\n    → '<new>'"`. With `--apply`, `db.set_session_title` writes it; a unique-title collision falls back to `db.get_next_title_in_lineage(new_title)` (the same `base #2`, `base #3` dedup the live auto-titler uses) and prints `"    (renamed to '<deduped>' — title was taken)"`, or `"    skipped: <error>"` if that also fails. Header: `"<N> session(s) opened with a /skill"` plus `" (dry run — pass --apply to write)"` when not applying. Footers: `"  every title already reflects the user's request."` or `"✓ Re-titled <N> session(s)."`. No candidates → `"No sessions were titled from a /skill invocation."`
- **Inputs / options:** `--apply` ("Write the new titles (default: dry run)"); `--limit LIMIT` ("Maximum sessions to examine (default: 200)"); `-h/--help`.
- **Outputs / side effects:** Updates `sessions.title`; makes auxiliary-model calls for title generation.
- **Config / env:** the auxiliary title-generation model settings.
- **Edge cases / guards:** Dry run by default; never replaces a serviceable title with model output that does not look like a title.
- **Rebuild notes:** A repair pass should be strictly more conservative than the live path it repairs — add an acceptance predicate the live path does not have.

### `hermes sessions browse`  `id: memory.cli-sessions-browse`
- **Surface:** CLI
- **Where:** `hermes sessions browse [-h] [--source SOURCE] [--limit LIMIT]`
- **What it does:** Interactive picker — browse, search, and resume sessions. Selecting one replaces the current process with `hermes --resume <id>`.
- **How it works:** `hermes_cli/sessions_cmd.py:1208`. Loads `db.list_sessions_rich(source=source, exclude_sources=(None if source else ["tool"]), limit=limit)`; empty → `"No sessions found."`. The DB is kept **open** while the picker runs because the picker uses it for lifecycle status tags and its `d` delete-with-confirmation action (`_session_browse_picker(sessions, session_db=db)`), then closed in a `finally`. Cancel prints `"Cancelled."`. On selection it prints `"Resuming session: <id>"` and calls `hermes_cli.relaunch.relaunch(["--resume", selected_id])` — an `execvp`, so nothing after it runs.
- **Inputs / options:** `--source SOURCE` ("Filter by source (cli, telegram, discord, etc.)"); `--limit LIMIT` ("Max sessions to load (default: 500)"); `-h/--help`. In-picker keys include `d` (delete with confirmation) plus the standard picker navigation/search.
- **Outputs / side effects:** Process replacement into a resumed session; possible session deletion from inside the picker.
- **Config / env:** n/a.
- **Edge cases / guards:** With no explicit `--source`, sessions tagged `tool` are excluded.
- **Rebuild notes:** Keep the DB handle alive for the picker's own actions, and `exec` rather than spawn so the resumed session inherits the terminal cleanly.

### `hermes sessions optimize`  `id: memory.cli-sessions-optimize`
- **Surface:** CLI
- **Where:** `hermes sessions optimize [-h]`
- **What it does:** Reclaims disk space with no data change: merges FTS5 index segments, then `VACUUM`s.
- **How it works:** `hermes_cli/sessions_cmd.py:1237`. Records `os.path.getsize(db_path)` before, prints `"Optimizing session store (FTS merge + VACUUM)…"`, then `db.vacuum()` (which runs `optimize_fts` on each index and then `VACUUM`, returning the number of indexes merged). Failure prints `"Error: optimization failed: <e>"`. After: it prefers `db.logical_size_bytes()` (SQLite's `page_count * page_size`) over `stat()`, because in WAL mode the VACUUM's rewrite sits in the `-wal` file until a checkpoint folds it back — and that checkpoint is refused while a live gateway holds a read-mark, so `stat()` understates the win and can even go negative. Prints `"Optimized <n> FTS index(es)."` and `"Database size: <before> MB -> <after> MB (<delta label>)"`.
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** Rewrites `state.db`; no session data changes.
- **Config / env:** `sessions.vacuum_after_prune`, `sessions.min_vacuum_interval_days` govern the automatic variant.
- **Edge cases / guards:** Non-destructive — the recommended first response to a large `state.db`.
- **Rebuild notes:** Report logical size, not file size, whenever WAL can defer the checkpoint.

### `hermes sessions optimize-storage`  `id: memory.cli-sessions-optimize-storage`
- **Surface:** CLI
- **Where:** `hermes sessions optimize-storage [-h] [--no-vacuum] [--yes]`
- **What it does:** Migrates the search index to the compact v23 external-content layout, reclaiming a large fraction of `state.db` on big databases (the old layout stored duplicate copies of every message and indexed tool output).
- **How it works:** `hermes_cli/sessions_cmd.py:1292`. `db.fts_optimize_available()` gates it — already-compact DBs print `"Search index is already on the compact layout — nothing to do."`. **Disk preflight:** the rebuild adds the new index before tearing down the old, and the final VACUUM needs a full second copy of the file, so it requires `need_bytes = before_bytes` (or `0.3 * before_bytes` with `--no-vacuum`). It prints `"Search-index optimization for <path>"`, `"  Current database size: <n> MB"`, and `"  Free disk: <n> MB (need ~<n> MB to complete[ incl. VACUUM])"`; insufficient space aborts with `"⚠ Not enough free disk to complete safely. Free up space, or run with --no-vacuum (rebuilds the index but doesn't reclaim space until a later VACUUM)."`. DBs over 500 MB get `"  This may take a while on a large database. It runs in the foreground with progress below; safe to Ctrl-C and re-run (it resumes)."`. Unless `--yes` it prompts `"Proceed? [y/N] "`. A progress callback renders `"\r  Rebuilding index: <pct>% (<indexed>/<total>)"` during the `backfill` phase and, on phase change, `"\n  <label>…"` where labels are `teardown → "Reclaiming old index"`, `vacuum → "Compacting database (VACUUM)"`, `done → "Done"`. Then `db.optimize_fts_storage(progress_cb=…, vacuum=do_vacuum)`; an exception prints `"\nError: optimization failed: <e>"` + `"No data was lost. Re-run to resume."`; a non-ok result prints `"\nCould not optimize: <reason>"`. Success prints `"\n✓ Search index optimized."` and the same logical-size-based before/after line; when `result["vacuumed"] is False` it adds `"  (VACUUM was skipped or failed — run `hermes sessions optimize` later to reclaim freed space.)"`. It throttles so a running gateway stays responsive, and no conversation data is changed — only the search index is rebuilt.
- **Inputs / options:** `--no-vacuum` ("Skip the final VACUUM (index is rebuilt but freed pages aren't returned to the OS until a later VACUUM)"); `--yes, -y` ("Skip the disk-space confirmation prompt"); `-h/--help`.
- **Outputs / side effects:** Drops and rebuilds `messages_fts` / `messages_fts_trigram` in the v23 layout; sets `state_meta['fts_storage_version'] = 1`; optionally VACUUMs.
- **Config / env:** `sessions.fts_optimize_notice` (default `"advise"`) controls the nag that suggests running it.
- **Edge cases / guards:** Safe to interrupt and re-run — it resumes from `state_meta['fts_rebuild_progress']` against `fts_rebuild_high_water`.
- **Rebuild notes:** Resumable chunked backfill + a watermark pair + a disk preflight is what makes an online index migration safe on a multi-GB store.

### `hermes sessions clean-markers`  `id: memory.cli-sessions-clean-markers`
- **Surface:** CLI
- **Where:** `hermes sessions clean-markers [-h] [--dry-run] [--no-backup]`
- **What it does:** Permanently clears stale tool-call marker content left by sessions from before the #78148 fix — bare bracketed markers (e.g. `"[memory]"`) persisted as an assistant turn's content instead of real text.
- **How it works:** `hermes_cli/sessions_cmd.py:1272` → `db.purge_stale_tool_call_markers(dry_run=…, backup=not args.no_backup)`. Prints `"Dry run — scanning for stale tool-call marker rows (#78148)…"` or `"Scanning for stale tool-call marker rows (#78148)…"`; then `"✓ No affected rows found — nothing to clean."`, or `"Would clear <n> row(s): ids <list>"` (dry run), or `"  backup: <path>"` + `"✓ Cleared <n> row(s)."`. Only the `content` column is touched — `tool_calls` and every other column on the row are left untouched. The condition is already repaired in memory on every session load, so running this is optional; it rewrites the affected rows once, in place, so long-lived sessions stop re-scanning/re-repairing the same rows on every resume.
- **Inputs / options:** `--dry-run` ("Report the affected row count without writing"); `--no-backup` ("Skip the timestamped state.db backup taken before writing (not recommended)"); `-h/--help`.
- **Outputs / side effects:** Rewrites `messages.content` for affected rows; a timestamped `state.db` backup by default.
- **Config / env:** n/a.
- **Edge cases / guards:** Idempotent; safe to re-run.
- **Rebuild notes:** When you repair-on-read, offer a one-shot repair-on-disk so the read path stops paying for it forever.

### `hermes sessions repair`  `id: memory.cli-sessions-repair`
- **Surface:** CLI
- **Where:** `hermes sessions repair [-h] [--check-only] [--no-backup]`
- **What it does:** Repairs a `state.db` whose **schema** is malformed (e.g. `table messages_fts already exists`), the failure that makes Desktop/Dashboard show no sessions.
- **How it works:** `hermes_cli/sessions_cmd.py:133` — runs BEFORE `SessionDB()` is opened, because a malformed schema is exactly the case where the normal open fails. Missing file → `"No session database at <path> (nothing to repair)."`. `_db_opens_cleanly(db_path)` returns `None` when fine (`"✓ <path> opens cleanly — no repair needed."`) or a reason (`"✗ <path> does not open cleanly: <reason>"`). With `--check-only` it stops there. Otherwise `"Repairing (a backup copy is made first)…"` and `repair_state_db_schema(db_path, backup=not args.no_backup)`. On success it prints the backup path and `"  strategy: <strategy>"`, then reopens `SessionDB()` and reports `"✓ Repaired — <n> sessions recovered."` (or a bare `"✓ Repaired."` if the count query fails). On failure it prints `"✗ Repair failed: <error>"`, preserves and names the backup, warns `"  Keep state.db and the backup; do not delete them."`, and — crucially — points at the offline path so the user is not at a dead end: `"  Next step — offline recovery (never modifies the source):"` with a two-command recipe, `hermes sessions recover --source <backup|db> --inspect-only` first, then `--output recovered-state.db`.
- **Inputs / options:** `--check-only` ("Only report whether the database opens cleanly; do not modify it"); `--no-backup` ("Skip the timestamped backup copy (not recommended)"); `-h/--help`.
- **Outputs / side effects:** Rewrites schema in place; a timestamped backup; rebuilds the FTS index if needed. Sessions and messages are preserved.
- **Config / env:** n/a.
- **Edge cases / guards:** Only touches schema, never conversation rows.
- **Rebuild notes:** A repair command must run before the normal open path and must always name the next escalation when it fails.

### `hermes sessions recover`  `id: memory.cli-sessions-recover`
- **Surface:** CLI
- **Where:** `hermes sessions recover [-h] --source SOURCE [--output OUTPUT] [--inspect-only] [--work-dir DIR] [--chunk-size N] [--allow-partial] [--report PATH]`
- **What it does:** Offline, non-destructive recovery for a damaged `state.db`. The source database and its WAL/SHM/rollback-journal sidecars are **copied before SQLite opens anything**; canonical rows are rebuilt into a NEW output database; derived search indexes are recreated; the active database is never replaced automatically.
- **How it works:** `hermes_cli/sessions_cmd.py:192` → `hermes_cli/session_recovery.py` (`inspect_session_database`, `recover_session_database`, `write_recovery_report`, `SessionRecoveryError`). Argument validation returns exit code 2 for: `--output` with `--inspect-only` (`"Error: --output cannot be used with --inspect-only."`), `--allow-partial` with `--inspect-only`, a missing `--output` outside inspect mode (`"Error: --output is required unless --inspect-only is used."`), and an existing report path (`"Error: refusing to overwrite existing report: <path>"`). The default report path is `<output>.recovery.json`. Recovery prints `"Recovering canonical session data into a new database…"` and a per-table progress line `"  <table>: <copied>/<source_rows>"` updated in place. Errors (`SessionRecoveryError`, `OSError`, `sqlite3.DatabaseError`) print `"Error: session recovery failed: <exc>"` + `"The supplied source database was not replaced or deleted."` and exit 1. Exit semantics: `--inspect-only` → 0 when `report["recoverable"]`, else 1. A complete recovery prints `"✓ Recovered database verified at: <output>"`, `"  The active session database was not changed."`, `"  Review the JSON report before installing this database."` → 0. With `--allow-partial` and a verified report: either `"✓ BEST-EFFORT page-level salvage verified at: <output>"` + `"  The source table schemas were unreadable; rows were rebuilt from raw pages via sqlite3 .recover and mapped heuristically."` (when `report["best_effort"]`) or `"✓ Partial recovery output verified at: <output>"`, then `"  Recovered <n> sessions and <n> messages."`, `"  The active session database was not changed."`, `"  This output is incomplete. Review every skipped range and orphan count in the JSON report before installing it."` → 0. Anything else prints `"✗ Recovery output did not pass every verification check."` + `"  Do not install it. Review the JSON report for partial data or errors."` → 1.
- **Inputs / options:** `--source SOURCE` (required) "Source state.db or preserved backup to inspect/recover"; `--output OUTPUT` "New recovery database path (required unless --inspect-only)"; `--inspect-only` "Only report canonical table readability; do not create an output database"; `--work-dir WORK_DIR` "Existing directory for the disposable source copy (defaults beside the output)"; `--chunk-size CHUNK_SIZE` "Rows committed per recovery batch (default: 1000)"; `--allow-partial` "Best-effort salvage across damaged row ranges; the output remains separate and every skipped range is recorded"; `--report REPORT` "JSON report path (defaults to <output>.recovery.json)"; `-h/--help`.
- **Outputs / side effects:** A new database file, a JSON report, and a disposable copy in the work dir. Never touches the source or the active DB.
- **Config / env:** n/a.
- **Edge cases / guards:** Copies WAL/SHM/journal sidecars first so SQLite cannot mutate the damaged source by opening it. Refuses to overwrite an existing report. Best-effort mode goes through `sqlite3 .recover` page-level salvage with heuristic column mapping and is explicitly labelled as such.
- **Rebuild notes:** Never open the damaged file directly; copy every sidecar; write to a new file; verify; hand the operator a machine-readable report and make installing it their explicit decision.

### `hermes sessions repair-routing`  `id: memory.cli-sessions-repair-routing`
- **Surface:** CLI
- **Where:** `hermes sessions repair-routing [-h] [--apply] [--max-gap-seconds N]`
- **What it does:** Finds gateway conversations stranded in session rows whose routing identity (`session_key`/`chat_id`/`origin`) was never written (#82616) — such a row is invisible to restart recovery, so the chat resumes an older session instead — and re-stamps each orphan from the keyed predecessor it continues, only when that predecessor is unambiguous.
- **How it works:** `hermes_cli/sessions_cmd.py:1392`. `db.find_orphaned_gateway_sessions(max_gap_s=…)` returns records; each prints `"<orphan_id>  (<source>, <n> messages)"` followed by either `"  → adopt into <session_key> (from <donor_id>, evidence: <evidence>)"` or `"  ✗ not repairable — <reason>"`. Evidence rules (docs): **lineage** — the orphan's `parent_session_id` points at a keyed row of the same platform (a recorded fact; no time window applies); **contiguity** — exactly one keyed row of the same platform fell quiet within `--max-gap-seconds` of the orphan's start. Anything ambiguous (two candidate predecessors, or two orphans claiming the same predecessor) is reported with a reason and left untouched — a wrong adoption would splice one conversation into another chat. Summary lines: `"✓ No gateway sessions are missing their routing identity."`; `"\n<N> orphaned session(s) found, none unambiguously repairable. Nothing to do."`; `"\n<M> of <N> orphaned session(s) can be repaired. Re-run with --apply to perform them."`. With `--apply` it first prints `"\nStop the gateway before applying — a running gateway still holds the old routing mapping in memory."` and asks `"Adopt <M> orphaned session(s)? [y/N] "`; each adoption prints `"✓ <orphan> now owns <session_key>"` or `"✗ <orphan> was not adopted (the row changed since it was reported)"`, then `"\nRepaired <k> of <M> session(s)."`. Declining prints `"Aborted — nothing was changed."`. The superseded row is retired under `superseded_by_repair` so restart recovery can never resurrect it.
- **Inputs / options:** `--apply` ("Perform the adoptions (default: report only)"); `--max-gap-seconds MAX_GAP_SECONDS` ("Window between a keyed predecessor's last activity and an orphan's start for them to count as the same conversation (default: 900)"); `-h/--help`.
- **Outputs / side effects:** Rewrites `session_key`/`chat_id`/`origin_json` on adopted rows and retires the donor.
- **Config / env:** n/a.
- **Edge cases / guards:** Deliberately **not automatic** — if the chat has since built a second history, choosing which thread it continues is the operator's call. The stranded conversation stays readable via `/resume` and session search either way; routing is the only thing the repair changes. Docs advise `cp ~/.hermes/state.db ~/.hermes/state.db.bak` first.
- **Rebuild notes:** Require unambiguous evidence, report before writing, refuse on any ambiguity, and re-verify the row at write time so a concurrent change cannot be clobbered.

### `hermes sessions stats`  `id: memory.cli-sessions-stats`
- **Surface:** CLI
- **Where:** `hermes sessions stats [-h]`
- **What it does:** Prints total session and message counts, per-source counts for the five main platforms, and the database file size.
- **How it works:** `hermes_cli/sessions_cmd.py:1438`. `db.session_count()`, `db.message_count()`, then `db.session_count(source=src)` for `["cli", "telegram", "discord", "whatsapp", "slack"]` (only non-zero rows are printed), then `os.path.getsize(db_path) / (1024*1024)`. Output shape:
  ```
  Total sessions: 142
  Total messages: 3847
    cli: 89 sessions
    telegram: 38 sessions
    discord: 15 sessions
  Database size: 12.4 MB
  ```
- **Inputs / options:** `-h/--help` only.
- **Outputs / side effects:** stdout.
- **Config / env:** n/a.
- **Edge cases / guards:** The per-source loop is a fixed five-platform list — sessions from `signal`, `matrix`, `mattermost`, `email`, `sms`, `dingtalk`, `feishu`, `wecom`, `weixin`, `bluebubbles`, `qqbot`, `homeassistant`, `webhook`, `api-server`, `acp`, `cron`, `batch`, `tool`, `subagent` and `kanban` count toward the total but get no per-source line. Uses `stat()`, so a WAL-deferred VACUUM makes this lag `hermes sessions optimize`'s reported size.
- **Rebuild notes:** For deeper analytics (token usage, cost estimates, tool breakdown, activity patterns) the docs point at `hermes insights`.

### Session auto-prune / auto-archive sweeps  `id: memory.session-auto-sweeps`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `sessions:` block; runs at CLI/gateway startup.
- **What it does:** Optionally deletes old ended sessions and/or soft-archives stale ones without the user running a command.
- **How it works:** When `sessions.auto_prune: true`, ended sessions inactive for `sessions.retention_days` (default 90) are pruned at CLI/gateway startup. After a prune that actually removed rows, `state.db` is `VACUUM`ed to reclaim disk when at least `sessions.min_vacuum_interval_days` (default 30) have elapsed since the last successful VACUUM — SQLite does not shrink the file on plain DELETE. Pruning runs at most once per `sessions.min_interval_hours` (default 24), and the last-run timestamp is tracked **inside `state.db` itself** so it is shared across every Hermes process in the same `HERMES_HOME`. `sessions.auto_archive` (default false) with `sessions.auto_archive_days` (default 3) drives the stale-archive sweep that pinned sessions are exempt from. Ended sessions are aged from their **latest message**, so a long-lived conversation used recently is not deleted merely because it began before the retention window.
- **Inputs / options:** `auto_prune`, `retention_days`, `vacuum_after_prune`, `min_vacuum_interval_days`, `min_interval_hours`, `auto_archive`, `auto_archive_days`.
- **Outputs / side effects:** Deleted/archived rows; a VACUUM.
- **Config / env:** `sessions.auto_prune` (`false`), `sessions.retention_days` (`90`), `sessions.auto_archive` (`false`), `sessions.auto_archive_days` (`3`), `sessions.vacuum_after_prune` (`true`), `sessions.min_vacuum_interval_days` (`30`), `sessions.min_interval_hours` (`24`), `sessions.write_json_snapshots` (`false`), `sessions.max_resume_messages` (`20000`), `sessions.max_export_messages` (`20000`).
- **Edge cases / guards:** Default is **off** — session history powers `session_search` recall and silently deleting it would surprise users. Active sessions are never auto-pruned regardless of age. Documented failure mode that motivates enabling it: a 384 MB `state.db` with ~1000 sessions slowing FTS5 inserts and `/resume` listing.
- **Rebuild notes:** Ship destructive maintenance off by default, store the idempotency marker inside the database so every process shares it, and age by last activity rather than creation.

### `session_search` tool  `id: memory.tool-session-search`
- **Surface:** Tool
- **Where:** Model-callable tool `session_search`, toolset `session_search`, emoji 🔍 (`tools/session_search_tool.py`).
- **What it does:** Searches past Hermes sessions (FTS5 over the local session DB) or reads/scrolls inside one. Four shapes picked purely from which arguments are set — there is no `mode` parameter. Results are actual DB messages; no LLM calls anywhere.
- **How it works:** `_session_search_impl()` (`tools/session_search_tool.py:953`).
  **Link normalization:** a `session_id` containing `/` is split on the first slash into `profile` + `id` (session ids never contain `/`), and the embedded profile is adopted only when none was passed explicitly — so every permutation of an `@session:<profile>/<id>` link works.
  **Cross-profile:** `_resolve_profile_db(profile)` normalizes and validates the profile name, requires it to exist, and opens `<profile dir>/state.db` with `read_only=True` (SQLite `mode=ro`, no write lock — safe against a live profile's DB). `current_session_id` is cleared so the current-lineage guards go inert.
  **Shape precedence:** scroll (`session_id` + `around_message_id`) → read (`session_id` alone) → browse (no query) → discovery. `limit` is coerced to int and clamped to `[1, 10]`; `sort` is normalized to `newest`/`oldest` or dropped; `detail` is `"full"` only on an exact case-insensitive match, else `"adaptive"`.
  **Read fallback:** if a read misses in the target profile, `_locate_session_db(sid)` scans **every** profile's `state.db` read-only for the id (ids are globally unique: timestamp + random hex, so the first hit is authoritative) and returns the session tagged with the profile it was found in — the safety net for links where the model dropped the profile segment.
  **Discovery** (`_discover`): scans `_DISCOVER_SCAN_LIMIT = 300` FTS rows (well above the handful of distinct sessions a query returns, so interactive matches buried under cron hits can still be found), selecting `_DISCOVER_SEARCH_FIELDS = (id, session_id, role, snippet, source, model, session_started)`. `_order_for_recall()` stable-sorts so `_DEMOTED_SESSION_SOURCES = ("cron",)` rows sink below interactive ones while BM25 order is preserved within each class — cron jobs accumulate large volumes of repetitive vocabulary and under bare BM25 they dominate top-N and starve out the user's own sessions ("recall blindness", #19434); demoting rather than excluding keeps cron reachable when it is the only match. `_HIDDEN_SESSION_SOURCES = ("kanban", "subagent", "tool")` are excluded from browsing/searching entirely. Hits are deduped by session **lineage** (`_resolve_lineage`), then each surviving session is hydrated: `adaptive` fully hydrates only the top-ranked result (bookends + ±5 window) and returns just the flagged anchor message for the rest; `full` hydrates every result. Bookends are the first/last 3 user+assistant messages, with `_COMPACTION_PREFIXES = ("[CONTEXT COMPACTION", "[CONTEXT SUMMARY]:")` rows excluded so a huge compaction payload is never re-introduced into a fresh session via session_search (#43175). `_FRESH_RESET_END_REASONS = frozenset(_RESET_END_REASONS) | {"new_session"}` marks children whose prior content is NOT in live context (gateway `/new`, `/reset`, idle/daily expiry, CLI `/new`), as opposed to compression continuations (summary carried forward) and live delegation children (parent still running).
  **Scroll** (`_scroll`): `window` clamped to `[1, 20]`, default 5; returns ±window messages around the anchor with no FTS5 and no bookends; scroll forward by re-anchoring on `messages[-1].id`, backward on `messages[0].id`; the boundary message appears in both windows as an orientation marker; `messages_before`/`messages_after` below `window` means you are at the start/end. ~1–2 ms per call.
  **Read** (`_read_session`): whole session, or a bounded head/tail view (`head=20, tail=10`) for large sessions.
  **Browse** (`_list_recent_sessions`): recent sessions chronologically with titles, previews and timestamps.
  **Links:** `_session_link(session_id, profile)` emits `@session:<profile>/<id>` (or `@session:<id>` when the profile can't be named confidently, or the active profile resolves to `"custom"`) — the same value the desktop composer emits when a session is dragged into a message, so the desktop renders it as a titled link. The tool description instructs the model to write the `link` value verbatim inline.
  **DB lifecycle:** `session_search()` opens a `SessionDB()` when none is passed, tracks every DB it opened in `owned_dbs`, and closes them in reverse order in a `finally`.
- **Inputs / options:** `query` (string — discovery; omit to browse; ignored in scroll shape), `limit` (int, default 3, max 10 — discovery only), `sort` (enum `newest|oldest` — discovery only; omit for relevance-only), `detail` (enum `adaptive` default | `full` — discovery only), `session_id` (string — scroll/read), `around_message_id` (integer — scroll), `window` (int, default 5, clamped `[1,20]` — scroll only), `role_filter` (comma-separated roles; discovery defaults to `user,assistant`; pass `user,assistant,tool` to include tool output or `tool` for tool output only), `profile` (string — read another profile's DB read-only). No required parameters.
- **Outputs / side effects:** A JSON string. Discovery result fields: `session_id`, `title`, `when`, `source`, `snippet` (FTS5-highlighted excerpt), `detail` (`full`|`compact`), `bookend_start`/`bookend_end` (first/last 3 user+assistant messages for full results; empty lists for compact), `messages` (±5 around the match for full; only the flagged anchor for compact), `match_message_id`, `messages_before`, `messages_after`, `link`. Read-fallback results additionally carry `profile`. No writes.
- **Config / env:** `sessions.search_slow_ms` (`1000`) for slow-query logging; `sessions.cjk_fts` (`true`).
- **Edge cases / guards:** `check_session_search_requirements()` requires `_default_db_path().parent` to exist. `MAX_FTS5_QUERY_CHARS = 2_048`. The tool description explicitly warns: "Searches conversation history ONLY — when the user gave a direct source (URL, file, contact, live system), inspect that first; never conclude 'not found' from history alone." `_annotate_rebuild_status()` flags results while an FTS rebuild is pending, and `_is_compacted_message()` / `_get_message_storage_state()` report when a message's content has been compacted away.
- **Rebuild notes:** Infer the shape from the arguments instead of adding a `mode`; dedupe by lineage, not by session id; demote automation sources rather than excluding them; hydrate adaptively so one call answers the common case without paying for N windows; and always return a copy-pasteable link.

### Filesystem checkpoints (shadow git store)  `id: memory.checkpoints-store`
- **Surface:** Core
- **Where:** `~/.hermes/checkpoints/`; opt-in via `hermes chat --checkpoints` or `checkpoints.enabled: true`.
- **What it does:** Automatically snapshots your project before destructive operations so `/rollback` can restore it. Your real project `.git` is never touched.
- **How it works:** `tools/checkpoint_manager.py` (2243 lines). This is NOT a tool — the LLM never sees it. **Storage layout** (`tools/checkpoint_manager.py:14`):
  ```
  ~/.hermes/checkpoints/
      store/                     — single bare-ish git repo
          HEAD, config, objects/ — standard git internals (shared)
          refs/hermes/<hash16>   — per-project branch tip
          indexes/<hash16>       — per-project git index
          projects/<hash16>.json — {workdir, created_at, last_touch}
          ledgers/<hash16>       — agent-write ledger
          info/exclude           — default excludes (shared)
      .last_prune                — auto-prune idempotency marker
      legacy-<timestamp>/        — archived pre-v2 per-project shadow repos
  ```
  Constants: `CHECKPOINT_BASE = get_hermes_home()/"checkpoints"`, `_STORE_DIRNAME="store"`, `_REFS_PREFIX="refs/hermes"`, `_INDEXES_DIRNAME="indexes"`, `_PROJECTS_DIRNAME="projects"`, `_LEDGERS_DIRNAME="ledgers"`, `_LEGACY_PREFIX="legacy-"`, `_LEDGER_MAX_ENTRIES=2000`, `_GIT_TIMEOUT = max(10, min(60, env_int("HERMES_CHECKPOINT_TIMEOUT", 30)))`, `_MAX_FILES=50_000`, `_COMMIT_HASH_RE = ^[0-9a-fA-F]{4,64}$`. `<hash16>` is derived from the absolute working-directory path.
  **Why one store:** the pre-v2 design kept a full shadow repo per working directory, re-storing most of the project's files under its own `objects/` with zero sharing; a user with a dozen worktrees of one repo burned ~40 MB each (~500 MB total). A single shared store lets git's content-addressable object DB deduplicate across projects and turns, so a new worktree costs near-zero. Operations use `GIT_DIR` + `GIT_WORK_TREE` + `GIT_INDEX_FILE` (per-project index so projects don't race) so no git state leaks into the user's directory.
  **Triggers:** before `write_file` and `patch`, and before destructive terminal commands — `rm`, `rmdir`, `cp`, `install`, `mv`, `sed -i`, `truncate`, `dd`, `shred`, output redirects (`>`), and `git reset`/`clean`/`checkout`. `ensure_checkpoint(working_dir, reason="auto")` takes **at most one checkpoint per directory per turn** (`self._checkpointed_dirs` set), never raises, and returns False when disabled, when `git` is not on PATH (`shutil.which("git")`, cached), or when the directory is `/` or `Path.home()`.
  **Agent-write ledger:** every successful `write_file`/`patch` records `{relpath: {"sha256": …, "ts": …}}` in `ledgers/<hash16>`, capped to the newest `_LEDGER_MAX_ENTRIES = 2000`, written atomically and best-effort (never raises). `/rollback` uses it to skip files whose current contents no longer match what Hermes last wrote.
  **Listing:** `list_checkpoints(working_dir)` runs `git log <ref> --format=%H|%h|%aI|%s -n <max_snapshots>` and, per entry, `git diff --shortstat <hash>~1 <hash>` parsed by `_parse_shortstat` into `files_changed`/`insertions`/`deletions`. `list_all_checkpoints()` iterates `projects/<hash>.json` and tags each entry with its `workdir`.
- **Inputs / options:** `--checkpoints` CLI flag; the `checkpoints.*` config block.
- **Outputs / side effects:** Git objects and refs under `~/.hermes/checkpoints/store/`; project metadata JSON; ledger files.
- **Config / env:** `checkpoints.enabled` (default **`false`** — opt-in), `checkpoints.max_snapshots` (`20`, enforced via ref rewrite + `git gc --prune=now`), `checkpoints.max_total_size_mb` (`500`, oldest commit per project dropped round-robin until under the cap), `checkpoints.max_file_size_mb` (`10`, larger files excluded from the snapshot), `checkpoints.auto_prune` (`true`), `checkpoints.retention_days` (`7`), `checkpoints.min_interval_hours` (`24`). Env: `HERMES_CHECKPOINT_TIMEOUT`.
- **Edge cases / guards:** Git missing → transparently disabled. Directories with more than 50,000 files are skipped. No-change snapshots are skipped. All errors inside the manager are logged at debug level and tools continue. The startup auto-prune sweep **never** deletes orphan entries (a missing workdir at startup is ambiguous — deleted project vs unmounted volume / network share / VPN not yet up); orphan cleanup only ever happens through the explicit `hermes checkpoints prune` with a confirmation prompt.
- **Rebuild notes:** One shared bare git repo, per-project refs and indexes, `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE` isolation, one snapshot per directory per turn, and a content-hash ledger so restore can distinguish agent writes from human edits. A better version would snapshot with a real content-addressed store rather than shelling out to git, and record the tool call id on each commit.

### `/rollback` — restore from a checkpoint  `id: memory.rollback`
- **Surface:** CLI
- **Where:** In-session slash command. Forms: `/rollback`, `/rollback <N>`, `/rollback <N> --all`, `/rollback diff <N>`, `/rollback <N> <file>`.
- **What it does:** Lists checkpoints with change stats, previews a diff, restores the working directory to a checkpoint (preserving your hand-edits by default), or restores a single file.
- **How it works:** `tools/checkpoint_manager.py` `list_checkpoints` / `diff` / `restore`. Listing renders:
  ```
  📸 Checkpoints for /path/to/project:

    1. 4270a8c  2026-03-16 04:36  before patch  (1 file, +1/-0)
    2. eaf4c1f  2026-03-16 04:35  before write_file
    3. b3f9d2e  2026-03-16 04:34  before terminal: sed -i s/old/new/ config.py  (1 file, +1/-1)

    /rollback <N>             restore to checkpoint N (keeps your hand-edits)
    /rollback <N> --all       full restore, overwriting your hand-edits too
    /rollback diff <N>        preview changes since checkpoint N
    /rollback <N> <file>      restore a single file from checkpoint N
  ```
  Restore sequence: (1) verify the target commit exists in the shadow store (`_validate_commit_hash`, 4–64 hex chars); (2) take a **pre-rollback snapshot** of the current state so you can "undo the undo"; (3) restore tracked files, **skipping** any file whose current content hash no longer matches the agent-write ledger entry (you edited it afterwards, or Hermes never touched it); (4) undo the last conversation turn so the agent's context matches the restored filesystem. Output on a safe restore:
  ```
  ✅ Restored to checkpoint a1b2c3d4: before write_file
  ↷ Kept your hand-edits: src/config.py, notes.md
  Use /rollback <N> --all to restore those too.
  ```
  When the ledger is empty (a store created before the feature, or Hermes has not written any files in the project yet) `/rollback` falls back to the full restore automatically (`{"ledger_empty": True}`). `/rollback diff <N>` shows a git diff-stat summary followed by the diff. `/rollback <N> <file>` restores one file; the path is validated against the working dir by `_validate_file_path`.
- **Inputs / options:** `<N>` (1-based checkpoint index from the list); `--all` (full restore, overwriting hand-edits); `diff <N>`; `<N> <file>` (single-file restore); bare `/rollback` (list).
- **Outputs / side effects:** Rewrites files in the working directory; adds a pre-rollback checkpoint commit; truncates the last conversation turn.
- **Config / env:** the `checkpoints.*` block.
- **Edge cases / guards:** `--all` is the only way to overwrite files you edited yourself. Commit hashes and file paths are both validated before they reach git.
- **Rebuild notes:** Snapshot before restoring, default to preserving human edits, and list exactly which files were skipped with the flag that would include them.

### `hermes checkpoints` / `status` / `list`  `id: memory.cli-checkpoints-status`
- **Surface:** CLI
- **Where:** `hermes checkpoints` (bare = `status`), `hermes checkpoints status [-h] [--limit LIMIT]`, `hermes checkpoints list [-h] [--limit LIMIT]`
- **What it does:** Shows total size, project count, and a per-project breakdown of the checkpoint store, plus any legacy archives.
- **How it works:** `hermes_cli/checkpoints.py:56` `cmd_status` → `tools.checkpoint_manager.store_status()`. Output:
  ```
  Checkpoint base: <base>
  Total size:      <fmt>
    store/         <fmt>
    legacy-*       <fmt>
  Projects:        <n>

    WORKDIR                                                       COMMITS    LAST TOUCH  STATE
    <workdir, left-truncated to 60 with a leading …>                   20       2h ago  live
    ...

  Legacy archives (<n>):
    <name>                                    <size>

  Clear with: hermes checkpoints clear-legacy
  ```
  Projects are sorted by `last_touch` descending and capped at `--limit` (default 20). `STATE` is `live` when the workdir exists, `orphan` when it does not. `_fmt_age` renders `now` / `<n>s ago` / `<n>m ago` / `<n>h ago` / `<n>d ago`, and `—` on a bad value. `list` is a literal alias that calls `cmd_status`.
- **Inputs / options:** `--limit LIMIT` ("Max projects to list (default 20)"); `-h/--help`.
- **Outputs / side effects:** stdout only. Requires no running agent; safe to call any time.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** An unreachable workdir is reported as `orphan` but never auto-deleted here.
- **Rebuild notes:** Show the cost per project and mark unreachable ones without acting on them.

### `hermes checkpoints prune`  `id: memory.cli-checkpoints-prune`
- **Surface:** CLI
- **Where:** `hermes checkpoints prune [-h] [--retention-days N] [--max-size-mb N] [--keep-orphans] [-f]`
- **What it does:** Forces a sweep that ignores the 24 h idempotency marker: deletes orphan and stale projects, GCs the store, and enforces the size cap.
- **How it works:** `hermes_cli/checkpoints.py:101`. When orphan deletion is enabled and `--force` is not passed, it first prints a preview: `"This will permanently delete <n> orphan checkpoint project(s) whose workdir is not currently reachable:"`, then one line per v2 orphan `"  <workdir>  (<n> commit(s))"` and per pre-v2 orphan `"  <workdir>  (pre-v2 shadow repo)"`, then `"A workdir can be unreachable because the project was deleted,"` / `"or because an external volume / network share / VPN is down."` / `"Pass --keep-orphans to prune stale entries only."` and `_confirm("Delete these orphan projects?")` → `"[y/N]: "`, accepting only `y`/`yes`; declining prints `"Aborted."` and returns 1. The deletion is then **bound to exactly what was displayed** via an `orphan_allowlist` of v2 project hashes and pre-v2 shadow-repo paths — a project that becomes orphaned only *after* the preview (its volume disappears while waiting on input) must not be swept up in the same run; the allowlist is set unconditionally on every non-force run, so an EMPTY preview binds to an EMPTY allowlist and can never authorize deleting orphans found by the later rescan. `--force` passes `None` (no restriction) because there is no preview to bind to. Then it prints the parameter echo (`"Pruning checkpoint store…"`, `"  retention_days:    <n>"`, `"  delete_orphans:    <bool>"`, `"  max_total_size_mb: <n>"`) and calls `prune_checkpoints(retention_days=…, delete_orphans=…, max_total_size_mb=…, orphan_allowlist=…)`, finishing with `Scanned:` / `Deleted orphan:` / `Deleted stale:` / `Errors:` / `Bytes reclaimed:`.
- **Inputs / options:** `--retention-days RETENTION_DAYS` ("Drop projects whose last_touch is older than N days (default 7)"); `--max-size-mb MAX_SIZE_MB` ("After orphan/stale prune, drop oldest commits per project until total size <= this (default 500)"); `--keep-orphans` ("Skip deleting projects whose workdir no longer exists"); `-f/--force` ("Skip the orphan-deletion confirmation prompt"); `-h/--help`.
- **Outputs / side effects:** Deletes refs/indexes/project metadata, runs `git gc --prune=now`, drops oldest commits to meet the size cap.
- **Config / env:** mirrors `checkpoints.retention_days` / `checkpoints.max_total_size_mb` defaults.
- **Edge cases / guards:** The allowlist binding is the key guard — a confirmation must authorize exactly the identities it displayed, never a superset discovered later.
- **Rebuild notes:** Bind every destructive confirmation to the exact identity set it showed; re-scanning after the prompt is a TOCTOU bug.

### `hermes checkpoints clear`  `id: memory.cli-checkpoints-clear`
- **Surface:** CLI
- **Where:** `hermes checkpoints clear [-h] [-f]`
- **What it does:** Deletes the entire checkpoint base — all `/rollback` history for every working directory.
- **How it works:** `hermes_cli/checkpoints.py:181`. If the store is empty and the base does not exist: `"Nothing to clear — checkpoint base does not exist."` → 0. Otherwise it prints `"This will delete the ENTIRE checkpoint base at <base>"`, `"  size:        <fmt>"`, `"  projects:    <n>"`, `"  legacy dirs: <n>"`, and `"All /rollback history for every working directory will be lost."`, then `_confirm("Proceed?")` unless `--force`; declining prints `"Aborted."` → 1. `clear_all()` then runs; success prints `"Cleared. Reclaimed <fmt>."` → 0, failure prints `"Could not clear checkpoint base (see logs)."` → 2.
- **Inputs / options:** `-f/--force` ("Skip confirmation prompt"); `-h/--help`.
- **Outputs / side effects:** Removes `~/.hermes/checkpoints/` entirely.
- **Config / env:** n/a.
- **Edge cases / guards:** Distinct exit codes: 0 nothing/cleared, 1 aborted, 2 failed.
- **Rebuild notes:** Print the cost and the consequence before asking; distinguish "aborted" from "failed" in the exit code.

### `hermes checkpoints clear-legacy`  `id: memory.cli-checkpoints-clear-legacy`
- **Surface:** CLI
- **Where:** `hermes checkpoints clear-legacy [-h] [-f]`
- **What it does:** Deletes only the `legacy-<ts>/` archives moved aside during the v1→v2 single-store migration.
- **How it works:** `hermes_cli/checkpoints.py:207`. No archives → `"No legacy archives to clear."` → 0. Otherwise `"Found <n> legacy archive(s), total <fmt>:"` and one line per archive, then the explanation `"Legacy archives hold pre-v2 per-project shadow repos, moved aside"` / `"during the single-store migration. Delete when you're confident"` / `"you don't need the old /rollback history."` and `_confirm("Delete all legacy archives?")` unless `--force`; declining prints `"Aborted."` → 1. Success prints `"Deleted <n> archive(s), reclaimed <fmt>."`
- **Inputs / options:** `-f/--force`; `-h/--help`.
- **Outputs / side effects:** Removes `legacy-*` directories.
- **Config / env:** n/a.
- **Edge cases / guards:** Legacy archives are also swept by `checkpoints.auto_prune` after `retention_days`. Old `/rollback` history remains reachable by inspecting a legacy archive manually with `git` until it is cleared.
- **Rebuild notes:** Keep the migration's leftovers in an obviously-named directory and give the user a one-command way to reclaim them.

### Session resume, `--continue`, and per-terminal breadcrumbs  `id: memory.session-resume`
- **Surface:** CLI
- **Where:** `hermes --continue` / `-c`, `hermes -c "<title>"`, `hermes --resume <id|title|latest|@claude|@codex>` / `-r`, `hermes chat --continue|--resume`, plus `--in <dir>` and `--no-restore-cwd`.
- **What it does:** Reopens a previous conversation with its full history, optionally restoring the workspace directory it belonged to.
- **How it works:** `-c` looks up the most recent `cli` session in `state.db`. **Per-terminal continue:** each CLI session drops a breadcrumb file under `~/.hermes/terminal-sessions/`, keyed by the terminal it runs in (tty device, tmux pane, kitty window, wezterm pane, Zellij pane, Windows Terminal session, …), so a bare `-c` in the *same* terminal resumes that terminal's own session — two panes side by side each continue their own conversation instead of both grabbing the globally most-recent one. With no breadcrumb (first use, deleted session, or a breadcrumb older than 30 days) `-c` falls back to most-recent. `-c "name"` and `--resume` are unaffected. Session ids are `YYYYMMDD_HHMMSS_<hex>` — CLI/TUI use a 6-char hex suffix, gateway sessions an 8-char suffix; both `-c` and `-r` accept a full id, a unique id prefix, or a title. Resuming by name with lineage variants (`my project`, `my project #2`, `my project #3`) automatically picks the most recent. `--resume latest` is the same lookup as `-c`. `--in <dir>` changes into a directory before starting/resuming (so `--resume latest --in ./my-project` picks the most recent session for that directory's workspace) and pins the session to it — the recorded working directory is not restored, as if `--no-restore-cwd` were passed. Otherwise a resume `cd`s back into the session's recorded workspace (git repo root or project dir) and prints `↪ restored workspace dir: …`; restore failures never break the resume.
- **Inputs / options:** `--continue` / `-c` (optionally with a title argument); `--resume` / `-r <id|prefix|title|latest|@claude|@codex>`; `--in <dir>`; `--no-restore-cwd`; the same flags on `hermes chat`.
- **Outputs / side effects:** Loads the transcript into the agent, writes/updates a terminal breadcrumb, may change the process working directory.
- **Config / env:** `session.terminal_continue` (default `true`) — set false to disable per-terminal `-c`. `sessions.max_resume_messages` (default `20000`).
- **Edge cases / guards:** `latest` is a reserved keyword for `--resume`; a session literally titled "latest" is still reachable by its id or via `-c latest` (title match).
- **Rebuild notes:** Key the "continue" breadcrumb on the terminal identity, expire it (30 days), and always fall back to most-recent instead of failing.

### Conversation recap on resume  `id: memory.resume-recap`
- **Surface:** CLI
- **Where:** Shown automatically in a styled "Previous Conversation" panel before the input prompt when resuming a session.
- **What it does:** Gives a compact replay of the recent conversation so you can re-orient without scrolling.
- **How it works:** Renders **user messages** with a gold `●` and **assistant responses** with a green `◆`; truncates long messages (300 chars for user, 200 chars / 3 lines for assistant); collapses tool calls into a count with tool names (e.g. `[3 tool calls: terminal, web_search]`); hides system messages, tool results, and internal reasoning; caps at the last 10 exchanges with a `... N earlier messages ...` indicator; uses dim styling to distinguish it from the live conversation.
- **Inputs / options:** none (automatic on resume).
- **Outputs / side effects:** Terminal output only.
- **Config / env:** `display.resume_display` — `full` (default) or `minimal` (keeps the one-liner behaviour).
- **Edge cases / guards:** Purely local rendering from stored messages; no LLM call.
- **Rebuild notes:** A resume banner should be free (no model call), bounded (last N exchanges), and visually distinct from live output.

### `/recap` — in-session activity summary  `id: memory.session-recap`
- **Surface:** CLI
- **Where:** `/recap` slash command, available on the CLI and on every gateway platform.
- **What it does:** Summarizes what has happened in the current session — the latest prompt, the latest assistant text, which classes of work were active, and which files were touched — so a user juggling sessions can re-orient instantly.
- **How it works:** `hermes_cli/session_recap.py` `build_recap()`. Pure local computation from the in-memory conversation history: **no LLM call, no auxiliary model, no prompt-cache invalidation** — a recap should be instant and free. Both CLI and gateway call the same helper, so behaviour is identical everywhere (Claude Code's `/recap`, the acknowledged inspiration, is CLI-only). Constants: `_RECENT_TURN_WINDOW = 20` recent user/assistant turns counted as "recent activity"; `_PROMPT_PREVIEW_CHARS = 140` of the latest user prompt; `_ASSISTANT_PREVIEW_CHARS = 200` of the latest assistant text; `_MAX_FILES_LISTED = 5` recently-touched files. Tool vocabulary is tailored to Hermes (`terminal`, `patch`, `write_file`, `delegate_task`, `browser_*`, `web_*`) so the recap surfaces which classes of work were most active. Text is passed through `tools.ansi_strip.sanitize_display_text`.
- **Inputs / options:** none.
- **Outputs / side effects:** A rendered summary; no state change.
- **Config / env:** n/a.
- **Edge cases / guards:** Works unchanged on every surface because there is exactly one implementation.
- **Rebuild notes:** Compute it locally from the transcript — an LLM-generated recap costs a cache miss and adds latency for no accuracy gain.

### Active-session liveness registry  `id: memory.active-sessions`
- **Surface:** Core
- **Where:** `hermes_cli/active_sessions.py`; enforced through `max_concurrent_sessions` / `max_live_sessions`.
- **What it does:** Records currently open chat surfaces — including idle CLI/TUI sessions that have not written a transcript row yet — as cross-process leases, so concurrency caps and ownership decisions are correct.
- **How it works:** The session database records *persisted* conversations; this module records *open* ones. Leases are written under `HERMES_HOME` with a uuid-identified holder, a pid, and a timestamp, taken and released through a context manager. `coerce_max_concurrent_sessions(value, key)` returns a positive integer cap or `None` when disabled/invalid (a bool is rejected with a warning). `ActiveSessionRegistryError` is raised when the registry cannot prove a safe ownership decision — it fails closed rather than guessing.
- **Inputs / options:** n/a (library).
- **Outputs / side effects:** Lease files under `HERMES_HOME`.
- **Config / env:** `max_concurrent_sessions` (default `null` = unlimited), `max_live_sessions` (default `16`), `agent.session_stall_timeout` (default `300` seconds).
- **Edge cases / guards:** Idle sessions that never wrote a message still hold a lease, which is exactly why the SQLite store alone is insufficient for the cap.
- **Rebuild notes:** Track "open" separately from "persisted"; make the registry fail closed on ambiguity.

### Context-switch guard (model switch → compression warning)  `id: memory.context-switch-guard`
- **Surface:** Core
- **Where:** `hermes_cli/context_switch_guard.py`; surfaces inside the existing model-switch warning on TUI, CLI, and gateway.
- **What it does:** Warns when switching to a substantially lower-context model will trigger preflight compression on the very next turn.
- **How it works:** Merges its text into `ModelSwitchResult.warning_message` (joined with `" | "` when a warning already exists), which every surface already renders — the same pattern as the expensive-model guard. `_threshold_tokens(context_length, threshold_percent) = max(int(context_length * threshold_percent), MINIMUM_CONTEXT_LENGTH)`. `_estimate_tokens(agent, messages)` reads the agent's `context_compressor`, skips when the transcript is no longer than `protect_first_n + protect_last_n + 1` (defaults 3 + 20 + 1), and otherwise uses `agent.model_metadata.estimate_request_tokens_rough`. Display context length comes from `hermes_cli.model_switch.resolve_display_context_length`.
- **Inputs / options:** n/a (automatic on model switch).
- **Outputs / side effects:** A warning string on the switch result.
- **Config / env:** the active engine's `threshold_percent`; `agent.model_metadata.MINIMUM_CONTEXT_LENGTH`.
- **Edge cases / guards:** Addresses part of issue #23767; the sibling fixes (hard preflight token guard, metadata cache invalidation on switch, compression safety invariant, oversized tool-output handling) are tracked separately.
- **Rebuild notes:** Reuse the existing warning channel rather than inventing a new surface; skip the estimate entirely when the transcript is fully protected.

### Session lost-and-found (page-level salvage)  `id: memory.session-lost-and-found`
- **Surface:** Core
- **Where:** `hermes_cli/session_lost_and_found.py`; reached through `hermes sessions recover --allow-partial` when SQL-level salvage is impossible.
- **What it does:** Last-resort recovery when the *schema page itself* is damaged: rebuilds rows from raw b-tree pages and heuristically maps them back into a fresh current-schema Hermes session database.
- **How it works:** `hermes sessions recover --allow-partial` normally copies rows through SQL, which requires the `sessions` and `messages` table **schemas** to be readable. When they are not, this module shells out to the SQLite **command-line shell**'s page-level `.recover` command (a shell feature, NOT available through the Python `sqlite3` module), which rebuilds unattributable rows into `lost_and_found(rootpgno, pgno, nfield, id, c0, c1, ..., cN)` tables. Rows are then classified heuristically by field count plus sentinel values: `SESSION_ID_PATTERN = ^\d{8}_\d{6}_` is the strongest sentinel (Hermes session ids are `20260812_135332_ab12cd`), and `MESSAGE_ROLES = {"user", "assistant", "tool", "system"}` plus a table of observed `sessions.source` values across gateway platforms and tooling identify message and session rows. Orphaned child rows get **fabricated stub parent sessions** rather than being deleted, and derived FTS indexes are rebuilt from scratch.
- **Inputs / options:** driven by `hermes sessions recover --allow-partial`.
- **Outputs / side effects:** A new database plus every skipped range recorded in the JSON report.
- **Config / env:** requires the `sqlite3` CLI on PATH.
- **Edge cases / guards:** Everything produced through this lane is explicitly **best effort** and labelled as such in the CLI output (`"✓ BEST-EFFORT page-level salvage verified at: …"`).
- **Rebuild notes:** Keep a sentinel-based classifier for schema-less rows, stub rather than drop orphans, and never let best-effort output be installed silently.

### Document extraction into the transcript (`read_file`)  `id: memory.document-extraction`
- **Surface:** Docs
- **Where:** `read_file` on a document path; documented at `website/docs/user-guide/features/document-extraction.md`.
- **What it does:** Converts common document formats to Markdown text so the agent can inspect a PDF or spreadsheet the same way it reads source code — and warns when a PDF's pages are scanned images with no text layer.
- **How it works:** Converters by format: Jupyter notebooks `.ipynb`, Word `.docx`, and Excel `.xlsx` use **built-in stdlib** converters (always available); PDF `.pdf`, legacy Office `.doc/.ppt/.xls/.pptx` and variants, OpenDocument `.odt/.ods/.odp`, and rich text / eBooks `.rtf/.epub` use the optional `firecrawl-anydoc` converter, installed lazily where installs are permitted. Output is Markdown, paginated through `read_file`'s normal `offset`/`limit` window. Extraction works with remote terminal backends (Docker, Modal, SSH): the file's bytes cross the backend boundary and are converted host-side. **Coverage warning:** PDF conversion reads the text layer only; when a meaningful share of pages yields no text (**over 20% of the document, or 10+ pages absolute**) `read_file` prepends `[EXTRACTION COVERAGE WARNING: <n> of <m> pages in this PDF yielded no text. … Unreadable gaps, each labeled with the last text extracted before it: …  Decide which gaps you actually need — do NOT OCR or render everything. …]`, listing each gap as `pages <a>-<b> (<n> pages) — after "<last text>" (p<n>)`. Detection uses poppler's `pdftotext` for per-page text counts; without poppler the extraction still works and the coverage check is silently skipped. Recovery paths named in the warning: (1) a few pages → render + vision, `pdftoppm -jpeg -r 150 -f 92 -l 94 document.pdf /tmp/page` then `vision_analyze` (zero extra dependencies, poppler is already required for detection); (2) many pages → the `ocr-and-documents` skill with marker-pdf (90+ languages, equations and tables, ~3–5 GB install).
- **Inputs / options:** the `read_file` tool's own `offset`/`limit`.
- **Outputs / side effects:** Extracted Markdown enters the transcript (and therefore the session store and context budget).
- **Config / env:** `security.allow_lazy_installs` gates the optional converter install.
- **Edge cases / guards:** Documents over **50 MB** are refused to keep tool turns bounded. Without the optional converter the three stdlib formats still work and everything else falls back to the binary-file guard. The docs tell human readers to treat "header with an empty body" as a scanned section, not a missing one.
- **Rebuild notes:** Detect the silent-failure mode (empty text layer) and report it as structured page ranges with the nearest preceding heading, so the agent can target only the gaps it needs instead of OCRing everything.

### What counts toward context (media vs text)  `id: memory.context-accounting`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/sessions.md` → "What Counts Toward Context".
- **What it does:** Documents which parts of a stored session are actually re-sent to the model each turn, so users know why context grows.
- **How it works:** On each turn the model sees the selected system prompt, the current conversation window, and any content Hermes explicitly injects for that turn. Media attachments are **turn-scoped inputs**: images may be attached natively to the next model call or pre-analyzed into a text description when the active model has no native vision; audio is transcribed into text when speech-to-text is configured; text documents can have their extracted text included, while other document types are usually represented by a saved local path plus a short note. Attachment paths and extracted/derived text can appear in the transcript, but the **raw image, audio, or binary bytes are not repeatedly copied into future prompts**. Worked example from the docs: a user sends an image and asks for a meme; Hermes inspects the image once with vision and runs an image-processing script; future turns carry only the request, a short description, a local cache path, and the final response — not the JPEG.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** The stated most common cause of context growth is verbose text — pasted transcripts, full logs, large tool outputs, long diffs, repeated status reports, detailed proof dumps — not media. Guidance: prefer summaries, file paths, focused excerpts, and tool-backed lookups. `/compress` reduces the active context; it is **not** a privacy delete. `hermes sessions optimize` is the non-destructive first step when `state.db` has grown.
- **Rebuild notes:** Make media turn-scoped by construction and store a derived text handle in the transcript, so the transcript stays replayable without carrying binary payloads.

### Session auto-titling (two-stage)  `id: memory.session-auto-title`
- **Surface:** Core
- **Where:** Titles shown in `hermes sessions list`, `hermes sessions browse`, `/sessions`, the Desktop sidebar and the dashboard.
- **What it does:** Names every session automatically — instantly from the first user message, then upgraded by a small model — so sessions are findable without the user doing anything.
- **How it works:** `agent/title_generator.py`. **Stage 1 (instant, deterministic):** `derive_title(user_message)` writes a title *before the model is even called* — it costs nothing, cannot fail, and means a session is named the moment it starts instead of after the first turn finishes (measured p50 151 s / p90 1212 s on real sessions). It is capped at `MAX_DERIVED_TITLE_CHARS = 48`, cutting at a word boundary when the space is past the halfway point. **Stage 2 (upgrade):** one small-model call on a cheap/fast tier with thinking disabled and the response constrained by `_TITLE_RESPONSE_FORMAT` — a strict `json_schema` `{"title": string}` with `additionalProperties: false` — which removes the whole class of "model answered the prompt instead of titling it" failures that produced titles like `<title>...</title>` and `User: Yep, that's the catch —`. Input is capped at `MAX_TITLE_INPUT_CHARS = 1000` (Claude Code and OpenClaw independently converged on the same budget: a title needs the opening intent, not a pasted stack trace). The prompt (`_TITLE_PROMPT_TEMPLATE`) is verbatim: *"You name chat sessions. Given the user's opening message, write a title that lets them find this conversation again in a list."* with rules "- 3 to 7 words, sentence case (capitalize only the first word and proper nouns).", "- Name what the user wants DONE, not that they asked a question.", "- Keep technical terms, filenames, numbers, and error codes exact.", "- Drop filler words: the, this, my, a, an.", "- No trailing punctuation, no quotes, no tool names, no 'Title:' prefix.", "- Never answer the message. Name it.", "- Always produce something, even for a bare greeting.", the language rule, three Good examples (`Fix login button on mobile`, `Postgres connection pool exhaustion`, `Friendly greeting`), a "Too vague" and a "Too long" example, and `Reply with JSON only: {"title": "..."}`. Language rule is either `- Write the title in the same language as the user's message.` or `- Write the title in {language}.` when pinned. **Answer-shaped output guard:** a candidate longer than `_MAX_TITLE_WORDS = 12` words is rejected (port of can1357/oh-my-pi#7306) — 12 leaves headroom for legitimately wordy titles while excluding full-sentence answers. **Provenance ordering** `derived < llm < user` is enforced by the storage layer (`sessions.title_source`), so stage 2 can only ever replace stage 1 and neither can replace a name the user typed — the same `custom > ai > fallback` precedence Codex CLI encodes in its session importer. **Scaffolding stripping:** `strip_control_wrappers()` removes `_CONTROL_WRAPPERS` — `<command-message>`, `<command-name>`, `<command-args>`, `<local-command-caveat>`, `<local-command-stderr>`, `<local-command-stdout>`, `<task-notification>`, `<system-reminder>`, `<ide_opened_file>`, `<ide_selection>` (ported from Codex CLI's `RECOGNIZED_CONTROL_WRAPPERS`, which strips and keeps titling rather than refusing) — and `_MACHINE_PREFIXES` rejects Hermes' own machine-authored openers: `"[CONTEXT COMPACTION"`, `LEGACY_SUMMARY_PREFIX`, `"[Runtime note:"`, `"[System note:"`, `"[SYSTEM]"`, and `"[System: The active model for this chat has changed to "` (the model-switch marker persisted with `role="user"` because strict OpenAI-compatible providers reject a non-first system message, #48338 — without this entry, switching models before the first real message titled the session after the marker).
- **Inputs / options:** none user-facing; `/title <text>` and `hermes sessions rename` override it.
- **Outputs / side effects:** Writes `sessions.title` and `sessions.title_source`; makes one auxiliary model call per session.
- **Config / env:** an auto-title enable flag (`_auto_title_enabled()`), a title language setting (`_title_language()`), and the auxiliary model configuration.
- **Edge cases / guards:** Auto-titling fires **once per session** and is skipped if a title was set manually. Duplicate titles are deduped in the lineage style (`base #2`, `base #3`) via `db.get_next_title_in_lineage`.
- **Rebuild notes:** Two stages with a provenance ladder is the pattern: a free deterministic name immediately, a model name later, and neither may overwrite the human. Constrain the model with a JSON schema and add a shape guard (word count) on top.

### Session title lineage on compression  `id: memory.title-lineage`
- **Surface:** Core
- **Where:** Visible as `my project` → `my project #2` → `my project #3` in listings and in `-c "my project"`.
- **What it does:** When a session's context is compressed (manually via `/compress` or automatically), Hermes creates a continuation session; if the original had a title, the new one gets the next numbered variant.
- **How it works:** `db.get_next_title_in_lineage(base)` produces `base #2`, `base #3`, …; the continuation row carries `parent_session_id` pointing at the compressed predecessor and the predecessor is stamped `end_reason = "compression"` (`_COMPRESSION_CHILD_SQL`, `hermes_state_common.py:190`). Compression continuations are **hidden** from pickers (`_LISTABLE_CHILD_SQL` lists only roots, branch children, and reset children). Resuming by name picks the most recent session in the lineage. `session_search` dedupes discovery hits by lineage (`_resolve_lineage`) so one conversation never occupies several result slots.
- **Inputs / options:** n/a.
- **Outputs / side effects:** New `sessions` rows with numbered titles and parent lineage.
- **Config / env:** n/a.
- **Edge cases / guards:** `hermes sessions export --lineage logical` exports the whole lineage as one document; `--lineage single` exports just the row.
- **Rebuild notes:** Give continuations a numbered title and a parent pointer, hide them from pickers, and resolve "by name" to the newest member of the lineage.

### Session sources taxonomy  `id: memory.session-sources`
- **Surface:** Docs
- **Where:** `sessions.source` column; `--source` on every session command; the `Src` column in listings.
- **What it does:** Tags every session with the surface it came from.
- **How it works:** Documented values (`website/docs/user-guide/sessions.md`): `cli` (Interactive CLI — `hermes` or `hermes chat`), `telegram`, `discord`, `slack`, `whatsapp`, `signal`, `matrix`, `mattermost`, `email` (IMAP/SMTP), `sms` (Twilio), `dingtalk`, `feishu` (Feishu/Lark), `wecom` (WeChat Work), `weixin` (personal WeChat), `bluebubbles` (Apple iMessage via the BlueBubbles macOS server), `qqbot` (Tencent QQ, Official API v2), `homeassistant` (Home Assistant conversation), `webhook`, `api-server`, `acp` (ACP editor integration), `cron` (scheduled jobs), `batch` (batch processing runs). Additional internal sources not in the docs table but referenced in code: `tool` (third-party integrations tagged via `HERMES_SESSION_SOURCE=tool`), `subagent` (delegate runs), `kanban` (dispatcher workers) — all three are in `_HIDDEN_SESSION_SOURCES` and never appear in browsing/search.
- **Inputs / options:** `--source <value>` on `list`, `browse`, `prune`, `archive`, `export`.
- **Outputs / side effects:** n/a.
- **Config / env:** `HERMES_SESSION_SOURCE` for third-party integrations.
- **Edge cases / guards:** `cron` is *demoted* (not hidden) in `session_search` discovery ranking.
- **Rebuild notes:** Separate three tiers — visible, hidden, and demoted — rather than a single boolean; machine traffic must be reachable but must never crowd out human conversation.

### Gateway session keying  `id: memory.gateway-session-keys`
- **Surface:** Docs
- **Where:** `sessions.session_key` and the `gateway_routing` table.
- **What it does:** Determines which conversation a message on a messaging platform belongs to.
- **How it works:** Deterministic keys built from the message source (`website/docs/user-guide/sessions.md`): Telegram DM `agent:main:telegram:dm:<chat_id>` (one session per DM chat); Discord DM `agent:main:discord:dm:<chat_id>`; WhatsApp DM `agent:main:whatsapp:dm:<canonical_identifier>` (LID/phone aliases collapse to one identity when a mapping exists); group chat `agent:main:<platform>:group:<chat_id>:<user_id>` (per-user inside the group when the platform exposes a user id); group thread/topic `agent:main:<platform>:group:<chat_id>:<thread_id>` (shared session for all thread participants by default; per-user with `thread_sessions_per_user: true`); channel `agent:main:<platform>:channel:<chat_id>:<user_id>`. When Hermes cannot get a participant identifier for a shared chat it falls back to one shared session for that room.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Rows in `gateway_routing` (`scope`, `session_key`, `entry_json`, `updated_at`) plus the mirrored `sessions.session_key`.
- **Config / env:** `group_sessions_per_user` (default `true` — Alice and Bob in the same Discord channel do not share transcript history, one user's tool-heavy task does not pollute another's context, and interrupt handling stays per-user because the running-agent key matches the isolated session key; set `false` for one shared "room brain" per room, which also shares token costs, interrupt state, and context growth), `thread_sessions_per_user`, `gateway.write_sessions_json` (default `true`).
- **Edge cases / guards:** Session identity (routing key, chat, origin) is written **atomically** when the session row is created on every creation path (`/new`, first message, `/branch` children); if that write ever fails, the next turn's routing refresh repairs the row automatically. `hermes sessions repair-routing` is the manual fallback for rows damaged before that guarantee existed.
- **Rebuild notes:** Make the key a pure function of the message source, write it atomically with the row, and keep a self-healing refresh on the hot path.

### Gateway session reset policies and restart continuity  `id: memory.session-reset-policies`
- **Surface:** Config
- **Where:** `session_reset` section in `config.yaml`.
- **What it does:** Optionally auto-resets gateway sessions on idle or on a daily schedule; and guarantees a chat is one continuous session across crashes and restarts otherwise.
- **How it works:** Modes: **`none`** (default — never auto-reset; context is managed by `/reset` and compression), **`idle`** (reset after N minutes of inactivity), **`daily`** (reset at a specific hour each day), **`both`** (whichever comes first). Before an auto-reset the agent is given a turn to save any important memories or skills from the conversation. Sessions with **active background processes are never auto-reset**, regardless of policy. Restart continuity: after a restart the gateway re-resolves each chat to the session with the most recent **actual activity**, so a stale row can never win over the conversation you were actually having; recovery **respects `/new` boundaries** — if the most recent event for a chat is an intentional reset, recovery starts fresh instead of reaching behind the reset; recovered sessions keep their real idle time so an idle/daily policy applies correctly instead of treating every recovered session as brand new. The reason taxonomy lives in `hermes_state_common.py`: `_RESET_END_REASONS = ("session_reset", "session_switch", "idle", "daily", "suspended", "resume_pending_expired")`; `_RECOVERABLE_END_REASONS = ("agent_close", "ws_orphan_reap", "superseded_by_resume", "startup_orphan_reap")` — accidental ends that recovery treats as resumable; `_AUTOMATIC_END_REASONS = _RECOVERABLE_END_REASONS | {"tui_shutdown", "ws_disconnect", "idle_timeout", "lru_evict"}` with the single predicate `is_automatic_end_reason(reason)` (`hermes_state_common.py:249`) — an automatic stamp records "some runtime went away", NOT "this conversation ended", so a writer that can prove the conversation is still live (e.g. an active compression rotation holding the lease, #88197) may clear it.
- **Inputs / options:** `session_reset.mode` and its idle/daily parameters.
- **Outputs / side effects:** `sessions.ended_at` / `end_reason`; a memory/skill save turn before reset.
- **Config / env:** `session_reset.*`; `max_live_sessions` (`16`); `agent.session_stall_timeout` (`300`).
- **Edge cases / guards:** `session_switch` is in `_RESET_END_REASONS` because pre-marker DBs can hold legacy reset children whose parent later ended with `session_switch`, and the set is interpolated into the recovery fence so the listing predicate and the recovery predicate cannot drift.
- **Rebuild notes:** One canonical end-reason taxonomy with one predicate function; never re-implement "was this an accident?" at each call site.

### Session storage locations  `id: memory.session-storage-locations`
- **Surface:** Docs
- **Where:** Under `HERMES_HOME` (default `~/.hermes`).
- **What it does:** Documents where every piece of session state actually lives, and which files are NOT the session list.
- **How it works:** `~/.hermes/state.db` — all session metadata + messages with FTS5, and the canonical store for gateway messages. `gateway_routing` table inside `state.db` — maps session keys to active session ids with origin metadata and expiry flags. `~/.hermes/sessions/sessions.json` — a **legacy mirror** of the routing index, written only when `gateway.write_sessions_json: true` (the default); it contains gateway/messaging entries only (`agent:main:whatsapp:dm:...`), so seeing only those is expected and does NOT mean CLI sessions are missing. `~/.hermes/sessions/saved/*.json` — `/save` snapshots, convenience exports, not an index. `~/.hermes/sessions/*.jsonl` — legacy transcripts from before `state.db` became canonical; no longer written or read, safe to delete once the session is verified present in `state.db`. `~/.hermes/session-exports/` — default output directory for md/qmd exports. `~/.hermes/terminal-sessions/` — per-terminal `-c` breadcrumbs. `~/.hermes/memories/` — `MEMORY.md`, `USER.md`, their `.lock` and `.bak.<ts>` files. `~/.hermes/checkpoints/` — the shadow git store. `~/.hermes/pending/` — staged memory/skill writes awaiting approval.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** `HERMES_HOME`, `gateway.write_sessions_json`, `sessions.write_json_snapshots` (default `false`).
- **Edge cases / guards:** If CLI sessions genuinely do not appear in `hermes sessions list`, the cause is `state.db` not receiving them — run `hermes sessions repair` and watch for a `⚠ Session store unavailable` warning at CLI startup, which means SQLite persistence failed for that run.
- **Rebuild notes:** One canonical store, clearly labelled legacy mirrors, and a documented diagnostic for "my data is missing".

### Background review memory notifications (`display.memory_notifications`)  `id: memory.review-notifications`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `display: memory_notifications: off|on|verbose`; per-platform override `display.platforms.<platform>.memory_notifications`.
- **What it does:** Controls the in-chat line the background self-improvement review prints when it quietly saves a memory or updates a skill.
- **How it works:** `off` — no chat notification (the review still runs and still writes; you just do not see a line). `on` (default) — a generic line, e.g. `💾 Memory updated`, `💾 Skill 'foo' patched`. `verbose` — includes a compact preview of what changed, e.g. `💾 Memory ➕ User prefers terse replies` or an `"old" → "new"` skill diff snippet. This governs the **gateway** chat notification only; the review itself and the writes to your memory/skill stores are unaffected.
- **Inputs / options:** `off` | `on` | `verbose`.
- **Outputs / side effects:** A chat line.
- **Config / env:** `display.memory_notifications` (default `"on"`).
- **Edge cases / guards:** Turning it off does not turn off the writes — `memory.write_approval: true` is the gate for that.
- **Rebuild notes:** Separate "did it happen" (notification) from "may it happen" (approval); never conflate visibility with consent.

### Background review fork (`auxiliary.background_review`)  `id: memory.background-review`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `auxiliary: background_review: {enabled, provider, model, extra_tools}`.
- **What it does:** Runs Hermes' consent-aware learning loop after a turn — repeated corrections and durable workflow lessons become compact memory entries or procedural skills.
- **How it works:** By default the review runs on your **main chat model**, replaying the conversation, which is already warm in the prompt cache (cheap cache reads). Pointing `provider`/`model` at a *different* model runs it there for substantially lower cost (~3–5× in benchmarks); because a different model cannot reuse the main model's prompt cache, the fork automatically replays a compact **digest** (recent turns verbatim + a summary of older ones) rather than the full transcript, minimizing what it writes to the new cache — in testing, memory capture was identical and skill capture near-identical. `auto` (the default) or the main model's own id keeps the full warm-cache replay. Fork usage is persisted in `session_model_usage` with `task='background_review'` and a completion line is written to `agent.log`: `Background review complete: thread=bg-review calls=… in=… out=… result=…`. Inside the review fork, `review_agent._memory_nudge_interval = 0` and `review_agent._skill_nudge_interval = 0` (`agent/background_review.py:1249`, `agent/curator.py:1977`) so the review cannot nudge itself.
- **Inputs / options:** `enabled` (bool — `false` skips automatic post-turn forks; manual `/refine` still works), `provider`, `model` (`auto` default = main chat model), `extra_tools` (list of tool names). Background review can use memory, skill-management, and read-only file tools by default; `extra_tools` opts in additional named tools that must already be available to the parent agent — it adds to the review fork's runtime whitelist only and does not enable arbitrary tools; unlisted tools remain denied. The documented example is `propose_shared_memory`. Default is an empty list.
- **Outputs / side effects:** Memory entries, skill edits, `session_model_usage` rows, `agent.log` lines.
- **Config / env:** `auxiliary.background_review.enabled` / `.provider` / `.model` / `.extra_tools`; `memory.nudge_interval` (default `10`) sets `agent._memory_nudge_interval` (`agent/agent_init.py:1859`, overridden from `memory.nudge_interval`).
- **Edge cases / guards:** The docs advise keeping `extra_tools` narrow and preferring tools that stage a proposal for human review over ones that apply external or destructive changes directly. Operators on busy hosts can disable the fork without zeroing nudge intervals.
- **Rebuild notes:** Make the learning loop a separate fork with its own model, its own tool whitelist, and its own usage accounting, so its cost is measurable and its blast radius bounded.

### Heap trimming for long-lived processes (`context.memory_trim`)  `id: memory.mem-trim`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `context: memory_trim: {enabled, cooldown_seconds, log_every_n, info_log_min_delta_mb}`; implemented in `hermes_cli/mem_trim.py`.
- **What it does:** Rate-limited heap release for long-lived Hermes gateway processes — returns pages from freed Python/C allocations to the OS. (This is process RAM, not conversational memory; it lives under `context.` and is listed here so the key is not mistaken for a memory-store setting.)
- **How it works:** On Linux/glibc it calls `malloc_trim(0)` through `ctypes`; other platforms and allocators are safe no-ops. Settings are read fail-open via `hermes_cli.config.load_config_readonly()` — the **no-deepcopy** variant, deliberately, because this runs on every trim attempt before the cooldown check and generating a full-config deepcopy per attempt is exactly the allocator garbage the module exists to release. Module defaults: `_DEFAULT_COOLDOWN_SECONDS = 60.0`, `_DEFAULT_LOG_EVERY_N = 1`, `_DEFAULT_INFO_LOG_MIN_DELTA_MB = 0.0`. Guarded by `_trim_lock`, `_last_trim_monotonic`, a one-time `_probe_done` symbol probe, and a `_trim_call_count`.
- **Inputs / options:** `enabled` (bool), `cooldown_seconds` (float), `log_every_n` (int), `info_log_min_delta_mb` (float).
- **Outputs / side effects:** RSS reduction; log lines.
- **Config / env:** `context.memory_trim.enabled` (`true`), `context.memory_trim.cooldown_seconds` (`60.0`), `context.memory_trim.log_every_n` (`1`), `context.memory_trim.info_log_min_delta_mb` (`0.0`). Related: `agent.agent_cache.memory_high_mb` (`"auto"`).
- **Edge cases / guards:** Every config read is wrapped in a bare `except Exception: pass` so a broken config can never break trimming; the TUI gateway resolves it from the session's own config (`tui_gateway/server.py:13570`).
- **Rebuild notes:** Rate-limit the syscall, probe the symbol once, and never let the settings read allocate more than the trim frees.

### `GET /api/memory` — memory status  `id: memory.api-memory-status`
- **Surface:** API
- **Where:** `GET /api/memory` (`hermes_cli/web_server.py:14332`); backs the dashboard/Desktop memory panel.
- **What it does:** Reports the active external provider, the discovered provider list with per-provider status, and the on-disk sizes of the two built-in memory files so the UI can show what a reset would erase.
- **How it works:** Runs on a worker thread (`asyncio.to_thread`) because `load_config()`, file stats and provider discovery are disk reads. `active` = `_normalize_memory_provider_name(config["memory"]["provider"])` or `""`. `providers` = `_discover_memory_provider_statuses()`. `builtin_files` = `{"memory": <bytes of MEMORY.md or 0>, "user": <bytes of USER.md or 0>}` from `get_hermes_home()/"memories"`.
- **Inputs / options:** none.
- **Outputs / side effects:** `{"active": str, "providers": [...], "builtin_files": {"memory": int, "user": int}}`. Read-only. Live shape of each provider entry (verified against the running dashboard): `{"name": "<id>", "description": "<plugin.yaml description>", "available": bool, "configured": bool, "status": "ready"|"unavailable", "setup": {"pip_dependencies": [...], "external_dependencies": [{"name","install","check"}], "required_env": [...], "dependencies_installed": bool}}` — e.g. `{"name":"holographic", …, "available":true, "status":"ready", "setup":{"pip_dependencies":[],"external_dependencies":[],"required_env":[],"dependencies_installed":true}}` and `{"name":"byterover", …, "available":false, "status":"unavailable", "setup":{"external_dependencies":[{"name":"brv","install":"curl -fsSL https://byterover.dev/install.sh | sh","check":"brv --version"}], "dependencies_installed":false}}`.
- **Config / env:** `memory.provider`, `HERMES_HOME`.
- **Edge cases / guards:** A missing file reports `0`, not an error.
- **Rebuild notes:** Report byte sizes so a destructive UI action can state its consequence precisely.

### `PUT /api/memory/provider` — switch active provider  `id: memory.api-memory-provider`
- **Surface:** API
- **Where:** `PUT /api/memory/provider` (`hermes_cli/web_server.py:14359`).
- **What it does:** Sets `memory.provider` in `config.yaml` to the requested provider (or `""` for built-in only).
- **How it works:** Body model `MemoryProviderSelect{provider}`. The name is normalized, `_require_memory_provider_ready(provider)` validates it can actually run, then the write happens under `_CONFIG_MUTATION_LOCK`: load config, ensure `config["memory"]` is a dict, set `provider`, save.
- **Inputs / options:** JSON body `{"provider": "<name>"}`.
- **Outputs / side effects:** Rewrites `config.yaml`; returns `{"ok": true, "active": "<name>"}`.
- **Config / env:** `memory.provider`.
- **Edge cases / guards:** A provider that is not ready is rejected before the config is touched, so the dashboard cannot activate a broken backend.
- **Rebuild notes:** Validate readiness before persisting activation; take a config mutation lock so concurrent panels cannot interleave writes.

### `POST /api/memory/reset` — erase built-in memory  `id: memory.api-memory-reset`
- **Surface:** API
- **Where:** `POST /api/memory/reset` (`hermes_cli/web_server.py:14377`).
- **What it does:** Deletes `MEMORY.md` and/or `USER.md` — the web equivalent of `hermes memory reset`.
- **How it works:** Body model `MemoryReset{target}`. `target` is lowercased/stripped and must be one of `all` | `memory` | `user`, else HTTP 400 `"target must be all, memory, or user"`. Builds the file list (`all` → both), unlinks each that exists, and collects the names; an `OSError` becomes HTTP 500 `"Could not delete <file>: <exc>"`.
- **Inputs / options:** JSON body `{"target": "all"|"memory"|"user"}` (defaults to `"all"`).
- **Outputs / side effects:** Deletes files; returns `{"ok": true, "deleted": ["MEMORY.md", ...]}`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Missing files are silently skipped (not listed in `deleted`). Unlike the CLI there is no typed confirmation — the UI owns that.
- **Rebuild notes:** Validate the enum server-side; report exactly which files were removed.

### `GET/PUT /api/memory/providers/{name}/config` + `POST .../setup`  `id: memory.api-provider-config`
- **Surface:** API
- **Where:** `hermes_cli/web_server.py:7176` (GET), `:7199` (POST setup), `:7221` (PUT).
- **What it does:** Serves and writes a memory provider's configuration surface for the generic dashboard/Desktop panel, and triggers a provider's install/setup commands.
- **How it works:** Every handler starts with `_require_valid_memory_provider_name(name)` and runs inside `_profile_scope(profile)` so a non-default profile's files are targeted. **GET** has two surfaces: `?surface=declared` returns the declarative `CONFIG_SCHEMA` via `get_provider_config_schema(name)` rendered by `_declared_provider_payload()`, falling back to `{"name": name, "label": name, "docs_url": "", "fields": []}` for undeclared providers (e.g. builtin) so the generic panel renders nothing; the default surface loads the provider and returns `_memory_provider_payload(name, provider)`, or `{"name", "label", "fields": [], "setup": _memory_provider_setup_info(name)}` when it cannot be loaded. **POST setup** refuses with 404 `"Unknown memory provider: <name>"` only when there is neither a loadable provider nor a discoverable plugin manifest (a provider can legitimately be `None` with a manifest present when its pip deps are not installed yet — that is exactly the setup use case), optionally persists `body.values` first (`ValueError` → 400; anything else → 500 `"Internal server error"`), invalidates the plugins-hub cache, and returns `_install_memory_provider_setup(name)`. **PUT** with `?surface=declared` writes through `_update_memory_provider_config(declared, _stringify_submitted_values(values))` and returns `{"ok": true}`; the default surface writes the provider's values, re-checks readiness with `_require_memory_provider_ready(name)`, sets `memory.provider = name` in config.yaml, invalidates the hub cache, and returns `{"ok": true, "active": name}`.
- **Inputs / options:** path `name`; query `surface` (`declared` or omitted) and `profile`; bodies `MemoryProviderSetupRequest{values}` and `MemoryProviderConfigUpdate{values}`.
- **Outputs / side effects:** Writes provider-native config and `.env` secrets, may run installs, may activate the provider.
- **Config / env:** `memory.<provider>.*`, `memory.provider`, provider env vars.
- **Edge cases / guards:** Secrets are write-only over the API — the declared schema surfaces only an `is_set` flag, never the value. A `ValueError` from validation is a 400, not a 500.
- **Rebuild notes:** Two surfaces (declared schema vs live provider) behind one path, profile-scoped, with secrets that can be written but never read back.

### `GET /api/learning/graph` and `/api/learning/node`  `id: memory.api-learning`
- **Surface:** API
- **Where:** `GET /api/learning/graph`, `GET /api/learning/node`, `DELETE /api/learning/node`, `PUT /api/learning/node` (`hermes_cli/web_server.py:4354`–`4418`); backs the desktop Star Map / Memory Graph panel.
- **What it does:** Serves the journey payload and lets the panel read, edit, or delete individual nodes.
- **How it works:** All four run on a worker thread — `_profile_scope(profile)` takes `_SKILLS_PROFILE_LOCK` and the graph build reads skills/memories from disk, so it must stay off the event loop. `GET /api/learning/graph` returns `agent.learning_graph.build_learning_graph()`; a failure logs `"GET /api/learning/graph failed"` and returns HTTP 500 `"Failed to build learning graph"`. `GET /api/learning/node?id=…&profile=…` returns `agent.learning_mutations.node_detail(id)` for an edit prefill, or HTTP 404 with the mutation's own message. `DELETE /api/learning/node` (body `LearningNodeRef{id, profile}`) calls `delete_node(id)` — skills are archived (restorable), memories removed — and returns HTTP 400 with the message on failure. `PUT /api/learning/node` (body `LearningNodeEdit{id, content, profile}`) calls `edit_node(id, content)`, HTTP 400 on failure.
- **Inputs / options:** query `id`, `profile`; bodies `{id, profile}` and `{id, content, profile}`.
- **Outputs / side effects:** Reads the graph; archives skills; rewrites `MEMORY.md`/`USER.md` chunks and `SKILL.md` files.
- **Config / env:** `HERMES_HOME`, profile scoping.
- **Edge cases / guards:** Same node-id semantics as the CLI (`<skill-name>` or `memory:<memory|profile>:<index>`), including the stale-index refusal.
- **Rebuild notes:** One mutation module shared by CLI, TUI RPCs and REST, so all three surfaces enforce identical guards.

### `GET /api/ops/checkpoints` and `POST /api/ops/checkpoints/prune`  `id: memory.api-checkpoints`
- **Surface:** API
- **Where:** `hermes_cli/web_server.py:14754` and `:14788`; backs the dashboard's storage/ops panel.
- **What it does:** Read-only listing of the `/rollback` shadow store (per-directory file count and byte size plus a total), and a one-click prune.
- **How it works:** GET scans `<hermes_home>/checkpoints` with `os.scandir`, sorts children by name, and for every subdirectory sums `rglob("*")` file sizes and counts (per-file `OSError` is skipped), returning `{"sessions": [{"session": <dirname>, "files": <n>, "bytes": <n>}, ...], "total_bytes": <n>}`. POST does not prune inline — it spawns `hermes checkpoints prune` via `_spawn_hermes_action(["checkpoints", "prune"], "checkpoints-prune")` so the confirmation and pruning logic stay in exactly one place (the CLI), returning `{"ok": true, "pid": <pid>, "name": "checkpoints-prune"}`; a spawn failure logs `"Failed to spawn checkpoints prune"` and returns HTTP 500 `"Failed to prune checkpoints: <exc>"`.
- **Inputs / options:** none for either endpoint.
- **Outputs / side effects:** GET is read-only; POST starts a background CLI process whose log the dashboard tails.
- **Config / env:** `HERMES_HOME`; the `checkpoints.*` defaults the spawned CLI applies.
- **Edge cases / guards:** The key `"session"` in the response is the directory name (`store`, `legacy-<ts>`, or a pre-v2 project hash) — not a Hermes session id.
- **Rebuild notes:** Never re-implement a destructive sweep in a second place; spawn the canonical command and stream its log.

### `hermes honcho` — active-provider CLI  `id: memory.cli-honcho`
- **Surface:** CLI
- **Where:** `hermes honcho [--target-profile NAME] {setup,status,peers,sessions,map,peer,mode,strategy,tokens,identity,migrate,enable,disable,sync}`. Registered **only while `memory.provider: honcho`** (see `discover_plugin_cli_commands`).
- **What it does:** Inspects and edits the Honcho memory provider's configuration and identity from the shell, without hand-editing `honcho.json`.
- **How it works:** `plugins/memory/honcho/cli.py:1879` `register_cli(subparser)`; dispatch is `honcho_command(args)`. Top-level flag `--target-profile NAME` targets a specific profile's Honcho config **without switching** the active profile. Unknown subcommand prints `"  Unknown honcho command: <sub>"` and `"  Available: status, sessions, map, peer, mode, strategy, tokens, identity, migrate, enable, disable, sync"`.
- **Inputs / options:** every subcommand and flag:
  - `--target-profile NAME` — "Target a specific profile's Honcho config without switching".
  - `setup` — "Initial Honcho setup (redirects to hermes memory setup)".
  - `status [--all]` — "Show current Honcho config and connection status"; `--all` = "Show config overview across all profiles".
  - `peers` — "Show peer identities across all profiles".
  - `sessions` — "List known Honcho session mappings".
  - `map [session_name]` — "Map current directory to a Honcho session name (no arg = list mappings)"; positional `session_name` (optional) = "Session name to associate with this directory. Omit to list current mappings."
  - `peer [--user NAME] [--ai NAME] [--reasoning {minimal,low,medium,high,max}]` — "Show or update peer names and dialectic reasoning level"; `--user` = "Set user peer name", `--ai` = "Set AI peer name", `--reasoning` = "Set default dialectic reasoning level (minimal/low/medium/high/max)".
  - `mode [{hybrid,context,tools}]` — "Show or set recall mode (hybrid/context/tools)"; omit the positional to show the current value.
  - `strategy [{per-session,per-directory,per-repo,global}]` — "Show or set session strategy"; omit to show current.
  - `tokens [--context N] [--dialectic N]` — "Show or set token budget for context and dialectic"; `--context` = "Max tokens Honcho returns from session.context() per turn", `--dialectic` = "Max chars of dialectic result to inject into system prompt".
  - `identity [file] [--show]` — "Seed or show the AI peer's Honcho identity representation"; positional `file` = "Path to file to seed from (e.g. SOUL.md). Omit to show usage.", `--show` = "Show current AI peer representation from Honcho".
  - `migrate` — "Step-by-step migration guide from openclaw-honcho to Hermes Honcho".
  - `enable` / `disable` — "Enable/Disable Honcho for the active profile".
  - `sync` — "Sync Honcho config to all existing profiles".
- **Outputs / side effects:** Reads and rewrites `honcho.json` (profile-local, default-profile, or global per the resolution chain); `identity <file>` writes an AI-peer representation into Honcho; network calls for `status`, `identity --show`.
- **Config / env:** `memory.provider`, `HONCHO_API_KEY`, the whole `honcho.json` key set.
- **Edge cases / guards:** On a fresh install the `honcho` subcommand does not exist yet — use `hermes memory setup honcho`. `hermes honcho setup` itself just redirects to `hermes memory setup`.
- **Rebuild notes:** A provider CLI registered only when the provider is active keeps the top-level command surface honest; every mutating subcommand should also be a no-arg "show" so the user can discover the current value.

### Honcho OAuth / device-code connect  `id: memory.honcho-oauth`
- **Surface:** Provider
- **Where:** `plugins/memory/honcho/oauth.py` (640 lines) and `oauth_flow.py` (656 lines); reached from `hermes memory setup honcho` and from the Desktop **Connect** link next to the memory-provider dropdown (which calls `POST /api/memory/providers/honcho/oauth/start`).
- **What it does:** Signs you in to Honcho Cloud without copying an API key — the wizard asks **OAuth, device code, or API key**; OAuth opens a browser sign-in and stores the grant itself, and tokens refresh automatically.
- **How it works:** `oauth_flow.py` exposes the two functions the generic router dispatches to by convention: `start_loopback_flow_background()` (opens the browser and captures the grant on a loopback listener; the worker thread outlives the HTTP request, which is why `memory_oauth._scope_to_profile` resolves the config path eagerly inside the profile scope) and `get_flow_status()` returning `idle | pending | connected | error`. On SSH/headless machines the **device** option prints a short code and a link you open in a browser on any other machine; setup completes once you approve there. The grant is stored in `honcho.json` under the `oauth` object (refresh token, expiry, client, token endpoint), written by the Connect/sign-in flows and rotated automatically — explicitly documented as not hand-edited. When connected via OAuth, `apiKey` holds the auto-refreshing access token instead of a static key; an API key alone also works with no `oauth` object at all.
- **Inputs / options:** the wizard's three-way auth choice; the dashboard's Connect button; `POST/GET /api/memory/providers/honcho/oauth/{start,status}` with an optional `profile`.
- **Outputs / side effects:** Writes `honcho.json` (`apiKey` + `oauth`); opens a browser; binds a loopback listener.
- **Config / env:** `HONCHO_API_KEY` (alternative), `honcho.json` `oauth`/`apiKey`/`baseUrl`. Local `baseUrl` values auto-skip API-key auth.
- **Edge cases / guards:** The router 404s any provider without an `oauth_flow` module, so no provider name is hardcoded in the web layer.
- **Rebuild notes:** Three auth paths (browser, device code, static key) behind one wizard question; store the grant in the provider's own config file and rotate it silently.

### `hermes sessions` (command group)  `id: memory.cli-sessions`
- **Surface:** CLI
- **Where:** `hermes sessions [-h] {list,export,delete,prune,archive,optimize,clean-markers,optimize-storage,repair,repair-routing,recover,stats,rename,pin,unpin,pinned,retitle-skills,browse,import} ...` — help text: *"View and manage the SQLite session store"*.
- **What it does:** The umbrella command for every session-store operation.
- **How it works:** `cmd_sessions(args, sessions_parser=None)` (`hermes_cli/sessions_cmd.py:124`) switches on `args.sessions_action`. `repair` and `recover` are dispatched **before** `SessionDB()` is opened — a malformed schema is exactly the case where the normal open fails, and recovery promises never to open the supplied source directly (it works through its own disposable copy). Every other action opens the DB, runs, and closes it in the common tail (`db.close()`); `browse` closes it inside its own `finally` because it hands the handle to the picker. An unrecognised action prints the group help.
- **Inputs / options:** the 18 subcommands with their help strings: `list` "List recent sessions"; `export` "Export sessions to JSONL, Markdown, or QMD"; `delete` "Delete a specific session"; `prune` "Delete old sessions (filterable by time window, source, title, ...)"; `archive` "Bulk-archive (soft-hide) sessions matching filters — no deletion"; `optimize` "Reclaim disk space: merge FTS5 segments + VACUUM (no data change)"; `clean-markers` "Permanently clear stale tool-call marker content left by sessions from before #78148"; `optimize-storage` "Migrate the search index to the compact v23 layout (reclaims disk on large DBs)"; `repair` "Repair a malformed state.db schema so hidden sessions reappear"; `repair-routing` "Re-stamp gateway sessions that lost their routing identity"; `recover` "Rebuild canonical session data into a separate clean database"; `stats` "Show session store statistics"; `rename` "Set or change a session's title"; `pin` "Pin session(s) — durable keep flag, exempt from auto-archive"; `unpin` "Remove the pin (durable keep flag) from session(s)"; `pinned` "List pinned sessions"; `retitle-skills` "Re-title sessions whose auto-title came from a /skill's own text"; `browse` "Interactive session picker — browse, search, and resume sessions"; `import` "Import a Claude Code or Codex CLI session into Hermes". Plus `-h/--help`.
- **Outputs / side effects:** per subcommand.
- **Config / env:** `HERMES_HOME`, the `sessions.*` block.
- **Edge cases / guards:** The export/prune/archive filter set is shared, so a filter learned once works on all three.
- **Rebuild notes:** Order the dispatch so recovery paths run before the store is opened; share one filter parser across every bulk verb.

### Honcho observation model (directional vs unified)  `id: memory.honcho-observation`
- **Surface:** Provider
- **Where:** `honcho.json` → `observationMode` and the `observation` block; documented at `website/docs/user-guide/features/honcho.md:184`.
- **What it does:** Controls which peer's messages Honcho uses to build which representation — the switch between "the AI models the user AND itself" and a shared single-observer pool.
- **How it works:** Honcho models a conversation as peers exchanging messages. Each peer has two toggles mapping 1:1 to Honcho's `SessionPeerConfig`: `observeMe` ("Honcho builds a representation of this peer from its own messages") and `observeOthers` ("This peer observes the other peer's messages (feeds cross-peer reasoning)"). Two peers × two toggles = four flags. `observationMode` is a shorthand preset: **`"directional"` (default)** — user `{me: on, others: on}`, AI `{me: on, others: on}`, full mutual observation, enabling cross-peer dialectic ("what does the AI know about the user, based on what the user said and the AI replied"); **`"unified"`** — user `{me: on, others: off}`, AI `{me: off, others: on}`, shared-pool semantics where the AI observes the user's messages only and the user peer only self-models. Override the preset with an explicit per-peer block:
  ```json
  "observation": {
    "user": { "observeMe": true,  "observeOthers": true },
    "ai":   { "observeMe": true,  "observeOthers": false }
  }
  ```
  Documented patterns: full observation for most users → `"observationMode": "directional"`; "AI shouldn't re-model the user from its own replies" → `"ai": {"observeMe": true, "observeOthers": false}`; "strong persona the AI peer shouldn't update from self-observation" → `"ai": {"observeMe": false, "observeOthers": true}`.
- **Inputs / options:** `observationMode` (`directional` | `unified`), `observation.user.observeMe`, `observation.user.observeOthers`, `observation.ai.observeMe`, `observation.ai.observeOthers`.
- **Outputs / side effects:** Changes which representations Honcho accumulates.
- **Config / env:** `honcho.json` (host block > root > env > default).
- **Edge cases / guards:** **Server-side toggles set in the Honcho dashboard win over local defaults** — Hermes syncs them back at session init, so a local block can be overridden from the cloud UI.
- **Rebuild notes:** Expose the primitive flags AND a two-value preset; sync server state back at init so the two sources of truth cannot silently disagree.

### Memory provider: Memori (pip-installed)  `id: memory.provider-memori`
- **Surface:** Provider
- **Where:** `memory.provider: memori`; installed with `pip install hermes-memori` + `hermes-memori install` (a pip entry-point provider in group `hermes_agent.memory_providers`, not bundled under `plugins/memory/`).
- **What it does:** Structured long-term memory using Memori Cloud, with background completed-turn capture, tool-aware turn context, and explicit recall tools for facts, summaries, quota, signup, and feedback.
- **How it works:** Documented at `website/docs/user-guide/features/memory-providers.md:650`. Best for "Agent-controlled recall with structured project and session attribution". Data lives in Memori Cloud; cost follows Memori pricing. Because it is an entry-point provider, `find_provider_dir()` resolves its package directory (without importing it) so its `config_schema.py` and `cli.py` still work — otherwise a pip-installed provider would silently lose its dashboard config panel and its `hermes <provider>` subcommands.
- **Inputs / options:** Tools: `memori_recall` (search long-term memory), `memori_recall_summary` (summarized context), `memori_quota` (usage/quota), `memori_signup` (request signup email), `memori_feedback` (send integration feedback). Setup: `pip install hermes-memori`, `hermes-memori install`, `hermes config set memory.provider memori`, `hermes memory setup`.
- **Outputs / side effects:** Memories on Memori Cloud.
- **Config / env:** a Memori API key from `app.memorilabs.ai/signup`.
- **Edge cases / guards:** Not bundled — it will not appear in `hermes memory setup` until the package is installed, and `hermes memory`'s own help text lists only the seven providers it hardcodes.
- **Rebuild notes:** Entry-point providers must be first-class: resolve their package directory without importing, so the config panel and CLI registration work identically to a directory install.

### Provider comparison and profile isolation  `id: memory.provider-comparison`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/features/memory-providers.md:673` (comparison) and `:687` (profile isolation).
- **What it does:** Summarizes every provider on one axis set so an operator can choose, and states how each provider's data is scoped per Hermes profile.
- **How it works:** Comparison table (Provider | Storage | Cost | Tools | Dependencies | Unique Feature): **Honcho** Cloud / Paid / 5 tools / `honcho-ai` / "Dialectic user modeling + session-scoped context"; **OpenViking** Self-hosted / Free / 6 / `openviking` + server / "Filesystem hierarchy + tiered loading"; **Mem0** Cloud or Self-hosted / Free or Paid / 4 / `mem0ai` / "Server-side LLM extraction + self-hosted/OSS modes"; **Hindsight** Cloud or Local / Free or Paid / 3 / `hindsight-client` / "Knowledge graph + reflect synthesis"; **Holographic** Local / Free / 2 / none / "HRR algebra + trust scoring"; **RetainDB** Cloud / $20/mo / 10 / `requests` / "Delta compression"; **ByteRover** Local or Cloud / Free or Paid / 3 / `brv` CLI / "Pre-compression extraction"; **Supermemory** Cloud or Self-hosted / Free or Paid / 4 / `supermemory` / "Context fencing + session graph ingest + multi-container"; **Memori** Cloud / Free or Paid / 5 / `hermes-memori` / "Tool-aware memory + structured recall". Profile isolation: **local-storage providers** (Holographic, ByteRover) use `$HERMES_HOME/` paths that differ per profile; **config-file providers** (Honcho, Mem0, Hindsight, Supermemory) store config in `$HERMES_HOME/` so each profile has its own credentials; **cloud providers** (RetainDB) auto-derive profile-scoped project names; **env-var providers** (OpenViking) are configured through each profile's `.env`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** `HERMES_HOME` per profile.
- **Edge cases / guards:** Only ONE external provider can be active at a time — the manager rejects a second registration.
- **Rebuild notes:** Publish a one-row-per-backend comparison and state the isolation mechanism per storage class; without it, users cannot reason about what a profile switch does to their memory.

## Handoffs

- `/memory` gateway slash-command family (`pending`, `approve`, `reject`, `approval on|off`) full dispatch and per-platform rendering → gw-slash shard.
- `/sessions`, `/resume`, `/new`, `/reset`, `/branch`, `/title`, `/compress`, `/undo`, `/save`, `/recap`, `/journey` slash-command dispatch on the gateway → gw-slash shard.
- `/handoff <platform>` cross-platform session transfer (validation, gateway watcher claim, per-adapter thread creation for Telegram/Discord/Slack, 60 s claim timeout, 15 min transfer wait, failure modes) → platforms shard.
- `agent/context_compressor.py` and `agent/conversation_compression.py` — the built-in `ContextCompressor` engine's actual summarization algorithm, head/tail protection, cooldowns, `SUMMARY_PREFIX`/`_SUMMARY_END_MARKER` formats, and `resolve_model_threshold` → agent-core shard.
- `tools/write_approval.py` — the generic staged-write framework (`evaluate_gate`, `stage_write`, `current_origin`, `~/.hermes/pending/`) and `skills.write_approval` → agent-core shard.
- `agent/insights.py` (`hermes insights`) — token/cost/tool analytics over the same session store → cli shard.
- `agent/learning_graph_render.py` — palette derivation, glyph/legend/axis/summary construction and the constellation layout algorithm → agent-core or tui shard.
- Desktop Star Map / Memory Graph panel and Desktop session sidebar (Pinned section, archive/unarchive) → desktop shard.
- Web dashboard session list, memory panel and provider config modal rendering (i18n keys, buttons) → web shard.
- TUI `/journey` overlay and TUI session picker → tui shard.
- `tools/thread_context.py` (thread-scoped context helper) → tools shard.
- `hermes backup` / `hermes import` archive format and the reserved `_external/` subtree that carries provider `backup_paths()` → cli shard.
- `agent/curator.py` skill archive/restore (`hermes curator restore|unpin`) referenced by `journey delete` → skills shard.
- `session_export_html.py` HTML template details (bubble styling, collapsible tool output, sidebar) → cli or web shard.
