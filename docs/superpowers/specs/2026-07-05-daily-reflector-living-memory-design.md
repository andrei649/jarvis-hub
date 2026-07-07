# DailyReflector LivingMemory Design

**Goal:** Finish the H21.3 sleep-time integration seam by letting nightly reflection results feed LivingMemory while keeping reflection idempotent across process restarts.

**Non-goals:** No new endpoints, no hot-path prompt injection, no raw transcript duplication in LivingMemory records, and no changes to the existing graph-promotion contract.

**Design:**

- Add `ReflectionRunStore`, a small JSON-backed daily ledger keyed by ISO date.
- `DailyReflector.run()` remains idempotent by default, but now checks the durable ledger as well as in-memory `_last_run`.
- Manual `/api/reflection/run` uses `force=True`, preserving the operator/HUD rerun button after durable idempotency lands.
- `DailyReflector` accepts an optional LivingMemory object/provider. The production provider returns `None` unless `cognition.memory_enabled` is active, preserving default-off behavior.
- Extracted `lessons` are encoded into LivingMemory as metadata-only records:
  - id: `reflection:<date>:lesson:<idx>:<sha>`
  - content: kind/date/source/lesson digest/length
  - no conversation text and no full lesson text inside the tier record.
- The bounded `living.core` receives the distilled lesson text, capped per lesson, so the reflection can become an always-available core fact without copying the whole transcript.

**Risks:**

- Reflection lessons are LLM-derived summaries. They are less sensitive than raw turns, but still user memory; the cognition-memory flag remains the production gate.
- The current LivingMemory module is process-local. This PR persists run idempotency, not the entire LivingMemory tier store.

**Rollback:**

- Remove the optional `run_store`/`living_memory` constructor args and return `/api/reflection/run` to clearing `_last_run`.
- The durable ledger lives under `memory_logs/reflection/daily_reflector.json`; deleting it only allows that day's reflection to run again.
