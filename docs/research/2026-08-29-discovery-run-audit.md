# Discovery-run completeness audit (run `wf_dcf964a6`, audited against `main` @ 5e6e184)

> Status: **research note** · date 2026-08-29 · branch `claude/hermes-jarvis-integration-2wkqph`
> Purpose: establish what the 144-agent open-work discovery sweep actually covered, what it got
> wrong, and what still needs a further agent swarm. **Read-only pass** over run journals and the
> worktree; the only files written are this note and the `DRA-*` ledger in `BACKLOG.md`.

## Why this exists

The discovery run was interrupted mid-flight by a session usage limit and resumed from cache. A
resumed run can report success while silently replaying *failed* results, so its output could not be
trusted on its own summary. This note records the forensic check of the run, and a second 88-agent
audit of the run's conclusions.

## Method

Two independent passes:

1. **Mechanical forensics** — parsed `journal.jsonl` and all 215 agent transcripts for the run:
   per-agent status, tool-call counts, stop reasons, synthetic error messages, result payload sizes.
   Nothing here relies on an agent's self-report.
2. **Adversarial audit** (88 agents, four lanes) — re-checked the run's own conclusions: the
   candidates it killed, each of the eight sources it swept, the plan's coverage of the surviving
   items, and whether any planned cluster was already done. Every claim then faced a confirmation
   agent instructed to **default to rejecting** it. 67 claims raised → **53 confirmed**, 14 rejected.

---

## Part A — what is fully covered (verified, no further work needed)

| Question | Verdict | Evidence |
|---|---|---|
| Did every planned agent run? | ✅ **Yes — 144/144** | 8 sweep + 134 verify + 1 rank + 1 critic; journal has 144 `result` rows, 0 empty payloads |
| Did the interruption lose work? | ✅ **No** | 208 starts / 146 unique keys → 62 keys started twice; all 62 usage-limit failures re-ran under the *same* cache key and succeeded |
| Were the 2 orphaned keys lost work? | ✅ **No — correctly superseded** | First-attempt rank + critic died mid-work with degraded inputs (the critic's prompt contains a literal `plan: null`); on resume both re-ran under new keys with correct inputs |
| Did the final synthesis see everything? | ✅ **Yes** | Final ranker's prompt embeds all 120 items; final critic's prompt embeds the full 26-cluster plan |
| Did verifiers actually read code? | ✅ **Yes** | Read/Grep/Bash calls per verify agent: min 2, median 10, max 31. The single 2-read agent was checking one stale doc line. The only 0-read agent is the ranker, correct by design (pure synthesis) |
| Were any results truncated? | ✅ **No** | No `max_tokens` stop reason anywhere; stop reasons are `tool_use` / `stop_sequence` only |
| Were sweep finders lazy? | ✅ **No** | 16–65 file reads each (median 42). The failure was *judgement about when a source was exhausted*, not effort |
| Do the 14 kills hold up? | ⚠️ **10 of 14** | 4 confirmed wrongly killed → `DRA-01`…`DRA-04` |
| Does the plan cover the 120 items? | ⚠️ **114 of 120** | 6 verified-open items land in no cluster and no owner lane → `DRA-05`…`DRA-10` |

**Bottom line for Part A:** agent *execution* was complete and honest. Agent *coverage* was not.
The run's real failure mode is under-mining sources it had already been pointed at — most starkly,
it pulled roughly 3 items from the parity gate's own list of 71 uncalled routes.

---

## Part B — what is NOT confirmed and needs another swarm

Each item below is work the audit could not close, with the swarm shape that would close it.

### B1 — The 9 completeness-critic additions ✅ CLOSED 2026-08-30

The discovery script ends after the critic, so its 9 extra items skipped the adversarial verify
phase entirely: each of the 120 `open_items` carries a `verdict` field, none of the 9 do. They are
single-source claims at materially lower confidence than everything else in the plan.

**Closed by a verification pass on 2026-08-30**: all 9 were checked against the code with a
default-to-closed instruction, and **all 9 are genuinely still open** at high confidence. They are
now recorded as `DRA-54`…`DRA-62` in `BACKLOG.md` with their remaining scope, so they carry the
same evidentiary weight as the other 120 rather than sitting as unverified single-source claims.

### B2 — Convergence was never demonstrated *(unfinished)*

Both the discovery sweep and this audit ran **exactly one round**. The loop-until-dry pattern —
keep sweeping until K consecutive rounds surface nothing new — was not used. Round 1 of the audit
found 39 missed items, which is strong evidence that round 2 would find more. Nothing here proves
the source list is exhausted.

**Swarm:** repeat the 8-source sweep with the 120 + 53 known items supplied as the exclusion set,
looping until two consecutive rounds return zero new confirmed items. Medium-to-large; this is the
single highest-value follow-up.

### B3 — `UNCALLED_BACKLOG` was never actually mined *(unfinished, `DRA-15` + `DRA-36`)*

`tests/test_hud_v2_parity.py` declares **71 shipped user-facing routes with no client caller** — a
pre-written inventory of open UI work. The run surfaced about three of them. Additionally the gate's
`_has_caller` matches only the stem before the first path parameter, so sub-routes under an
already-called prefix can never be flagged (`DRA-35`) — the true number is higher than 71.

**Swarm:** batch the 71 routes ~6 per agent (12 agents); each decides render-worthiness, the honest
surface, and the tier. Then one ranking pass. Also fix `_has_caller` and re-derive the list first,
or the input is itself incomplete.

### B4 — `mobile/PARITY.md` is materially incomplete *(unfinished, `DRA-18`)*

Roughly 40 user-guarded HUD surfaces have no row at all, so the parity document cannot be used as a
coverage source until it is re-derived.

**Swarm:** 1 agent to re-derive the full surface list from the route table + HUD callers, 3–4 to
classify each missing row (ported / intentionally-web-only / open), 1 to write the file.

### B5 — The 39 newly found items have no implementation scope *(unfinished)*

They were confirmed *open*, not scoped. None carries a corrected scope, size estimate, gated-path
determination, or test plan — so none is ready to hand to a builder.

**Swarm:** one scoping agent per item in batches (~8 agents), producing the same shape the original
120 carry (`corrected_scope`, size, `gated_paths`, acceptance tests).

### B6 — The 120 "still open" verdicts were never independently re-checked *(unconfirmed)*

This is the largest remaining blind spot. The audit re-checked the run's **negative** verdicts (the
14 kills) and found 4 wrong — a 29% error rate in that direction. The **positive** verdicts were
never given a second opinion: each of the 120 rests on exactly one agent's single-vote judgement.
The phantom lane found item-level false positives incidentally (items 80, 94, 99, 114, 115, 117),
which is corroboration that the positive side carries error too.

**Swarm:** a second-opinion pass over the 120, ideally perspective-diverse (2–3 lenses per item,
majority rules) rather than a single re-verify. Large — but it is the difference between "120 items
an agent believed" and "120 items that survived a vote."

### B7 — The 26-cluster plan is stale and must be re-ranked *(unfinished)*

Clusters 2, 3 and 4 shipped in PR #982. Clusters 6 and 11 survived as genuine residuals but their
BACKLOG rows are factually wrong (below). 53 new findings sit in no cluster. Re-ranking against the
current corpus is a prerequisite for any "what's next" answer.

**Swarm:** 1 ranking agent over the merged corpus (120 − shipped + 53 + whatever B1/B2 add), plus a
completeness critic — but only *after* B1/B2/B5 land, or it re-ranks a stale set.

---

## The three corrections that matter most

1. **SEC-B5 is a partial, not a tick.** The kill recommended flipping `BACKLOG.md` SEC-B5 to
   "FIXED in #941". PR #941 closed the proactive, ambient and WorldView-*storage* legs. The
   recall→action leg is provably unbuilt: `agents/core/security/rag_guard.py:59` defines
   `WrappedMemory.tainted`, `agents/core/orchestrator.py:1799-1801` discards it, and no consumer of
   that field exists anywhere in the tree. Recording the row as closed would write a false claim onto
   a movement-gated document. (`DRA-02`)
2. **SEC-B4's row is factually false in the other direction.** #956 closed the vulnerability by making
   browser navigation fail-closed; the row still describes the old TOCTOU hole, and the *open* work is
   now building the pinned transport so governed browser automation can run at all. (`DRA-09`)
3. **Three honesty regressions are live in the HUD** — the exact failure class this product exists to
   refuse: the ADMIN plugin registry renders 8 fabricated integrations in live mode (`DRA-03`), OBSERVE
   shows a seeded 4.2s p50 under a green LIVE badge when `/bench/stats` 503s (`DRA-04`), and the
   WV-170 Neo4j lane trusted by a kill is red on main and has never validated its Cypher (`DRA-01`).

## What shipped from this audit (2026-08-30)

Nine of the 53 confirmed findings were built and validated in the same PR that records them, so the
ledger below is not a wish list — `DRA-01`…`DRA-04`, `DRA-18`, `DRA-32`…`DRA-35` are ticked, plus
WFL-113 (the identical regex sink in `transforms.py`, found by the WFL-112 lane and closed with it)
and the frigate event-loop block.

Two findings from the build itself are worth recording, because both are the same class of defect
this audit exists to catch:

- **The parity gate's own hole was structural, and so was the WV-170 one.** The Neo4j probe bug
  survived because the *entire* test file sat behind a schedule-only gate, so nothing on the
  pull-request path ever tested the probe. Moving the skip onto the fixture put six offline
  regressions on the PR path. A check that only runs where nobody looks is not a check.
- **SEC-B5 leaked across tests before it was caught.** Making `WrappedMemory.tainted` finally do
  something meant a tainted-recall mark could cross a test-file boundary in a shared pytest worker;
  CI's `-n auto --dist loadfile` ordering caught it where a serial run did not. The autouse fixture
  in `tests/conftest.py` scopes the binding per test. Worth remembering: for a change to a
  process-wide ContextVar, the serial suite is not the check that matters.

## Ledger

All 53 confirmed findings are recorded as `DRA-01`…`DRA-53` in `BACKLOG.md`, grouped by class and
ordered by severity (9 high · 34 medium · 10 low), followed by the 9 critic additions that B1
verified (`DRA-54`…`DRA-62`) — 62 rows in total.

| Class | Count | BACKLOG range | Shipped in this PR |
|---|---:|---|---|
| Wrongly killed — functionality actually missing | 4 | `DRA-01`…`DRA-04` | 4 of 4 |
| Verified open but in no cluster | 6 | `DRA-05`…`DRA-10` | — |
| Planned work already done (record only) | 4 | `DRA-11`…`DRA-14` | n/a |
| Missed by the sweep entirely | 39 | `DRA-15`…`DRA-53` | 5 (`DRA-18`, `DRA-32`…`DRA-35`) |
| Critic additions, verified open by B1 | 9 | `DRA-54`…`DRA-62` | — |

> Two of the four "already done" entries are not defects of the discovery run: clusters 2 and 4 were
> shipped by PR #982 hours after the run produced the plan, and the audit was told about #982.
