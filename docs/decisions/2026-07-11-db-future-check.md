# Decision — database future check: SQLite/WAL vs Turso/libSQL (0.61)

> **Status: RECOMMENDED — stay on SQLite + WAL; re-evaluate on named triggers.** This is the
> written eval the 0.61 row asks for. Owner ratifies or overrides.

## Current state (what we actually run)

Every persistent store is **SQLite in WAL mode** (settings, checkpoints, autonomy queue,
audit chain, missions, analytics, marketplace) or a small **atomic-write JSON store**
(`JsonStore` family). Schema evolution is solved: `persistence/migrations.py` (H23.7, #305)
versions each store with `PRAGMA user_version` and append-only migration lists. Backup/restore
(#302), export (#303), and forget-me purge (#306/AUD-2) all operate on these files directly.

## The candidates

| | SQLite + WAL (today) | Turso / libSQL |
|---|---|---|
| Locality | 100% local files — the product's core promise | libSQL local works, but the value proposition is the **hosted/replicated** tier |
| Ops | zero — a file | an account, auth token, sync daemon, network egress |
| Single-user fit | exact | over-provisioned (multi-region replicas solve a problem we don't have) |
| Backup/export/purge | already built on files | would need re-plumbing for embedded-replica mode |
| Concurrency | WAL is enough for one user + agents | better multi-writer — matters only post-1.0 multi-user |
| Risk | none (boring tech) | young ecosystem; hosted tier conflicts with local-first + "keys stay local" |

## Recommendation

**Stay on SQLite + WAL through 1.0 and the design-partner phase.** Every argument for
Turso/libSQL (replication, multi-writer, edge sync) belongs to a **multi-user / multi-device**
future the H23.23 decision explicitly deferred post-1.0. Migrating storage now would touch the
backup/export/purge/migration quartet for zero user-visible gain and would strain the
local-first trust story (SECURITY.md: no third-party relay).

**Re-evaluate when any trigger fires (post-1.0):**
1. Per-user isolation gets scoped (H23.23 option B) — multi-writer becomes real;
2. A second device needs *live* state sync (not the export/backup path);
3. A design partner hits verified SQLite write-contention in the 72h soak (AUD-0 data);
4. The Pi-5 satellite services need shared read access to hub stores.

If a trigger fires, the natural path is **libSQL embedded replicas** (file-compatible,
keeps local-first) — not the hosted tier. The H23.7 migration framework and the
file-oriented backup/export/purge design make that a contained change later.

## Consequence

0.61 closes as *evaluated, deliberately deferred* — not "delayed for no reason": the
remaining work item is only "re-check on triggers." No code change.
