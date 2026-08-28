# Handoff — Backlog Zero, run 016 → next session

> **Written:** 2026-08-28 · **Branch:** `claude/nerva-backlog-zero-f161fe` (pushed, tracks origin)
> **Head:** `97553800` · **Base:** `main` @ `a5916fd6` (clean fast-forward, main unmoved)
> **Green at handoff:** backend **7,084** · frontend **622** · mobile **96** (see caveats §5)

---

## 1. The prompt (paste this to start)

```
Continue the Nerva "Backlog Zero" protocol on branch claude/nerva-backlog-zero-f161fe
(pushed, head 97553800). Read in this order and treat as binding: CLAUDE.md →
AGENTS.md → MAX.md → MOONSHOT.md §5 → BACKLOG.md. The execution ledger is
docs/BACKLOG_ZERO_LEDGER.md; the run log is docs/MAX_RUNS.md (latest row: 016).
Read docs/handoff-2026-08-28-backlog-zero.md FIRST — it has the environment
gotchas that cost the last session real time, and the honest status of every
remaining item.

Phase 0 before writing any code: re-verify the ledger rows you intend to touch
against the actual code, not against BACKLOG.md prose. Last session found ~1-in-4
"open" rows were already shipped and merely undocumented, and separately caught
itself marking a row closed that wasn't. Grep for the row's own keywords before
trusting its status either way.

Then work the loop: one slice, test-first, full gates, BACKLOG.md + ledger updated
in the same commit. Owner-gated items get a packet in docs/OWNER_TASKS.md, not a
guess. Commit locally without PRs unless told otherwise.
```

---

## 2. What run 016 shipped (do not redo)

Eleven slices, 22 commits. All closed rows are marked in `docs/BACKLOG_ZERO_LEDGER.md`.

| Item | State |
|---|---|
| T-0.41 (+ digest tail) | **Closed** — signals router, HUD panel, morning-brief consumption |
| H5.16 | **Closed** — TTS synthesizes while the chat streams |
| T-0.29 | **PWA half closed**; signed installers → owner packet |
| T-0.58 | **Closed** — typed Pack Manager (skill + knowledge; `model` declared unsupported *with a reason*) |
| T-0.50 | **Surface closed** — publish readiness that provably never publishes; executor → owner |
| T-0.37 | **Provenance half closed**; ontology half deliberately untouched |
| AUD-14 | **Closed-as-ratcheted** — 145→115 reads + a count ratchet so it can only shrink |
| H18.24 / H18.25 | **Contracts closed**, proven against 80 / 500 shared vectors; renderers device-gated |
| AUD-18 / F30 | **Closed** — CORS origins validated instead of silently inert |

Earlier in the same session: A8-iv, T-0.53, T-0.20, H34.3, WV-170 (code+CI), plus three
`NEEDS-RECOUNT` rows cleared and a 26-row recount sweep.

---

## 3. What is genuinely open — with honest reads

**Reasonable next picks (AI-buildable, verified open):**

- **AUD-18 tail** — four independent sub-items, each a real slice: Qdrant-by-default at
  scale (a *runtime default flip*; wants a running Qdrant to validate, not code-only),
  lazy plugin instantiation, Vite code-split, F31 loader retry/feedback. The last two are
  the most bounded.
- **T-0.37 ontology half** — a shared entity schema + cross-agent sharing. This is a
  **design question** (what the ontology *is*; what cross-agent read authority means under
  the plugin/data-space gate), not a wiring gap. Scope it before coding.

**Needs scoping before any code:**

- **T-0.49** (approval-gated timeline) — genuinely under-specified. `canvas.py` has no
  timeline/approval element kind; `ActivityTimelinePanel` is read-only history. Do not
  improvise an interactive approval surface; write the spec first.

**Do NOT attempt in a single session:**

- **AUD-13** (orchestrator decomposition: one `PromptBuilder`+`_preprocess_turn`, extract
  context/dispatch/persist, retire `sys.modules` indirection). Note `app_state.py`
  *formalised* that indirection deliberately — retiring it fights an intentional decision.
- **AUD-15** (retire HUD v1, `@jarvis/client` extraction, 70 files still `@ts-nocheck`,
  `strict: false`). Both are explicitly post-1.0.

**Blocked on a device / hardware — packet, not code:**

- H18.24/H18.25 **renderers** + hold-to-talk: mobile has no mic-capture pipeline and no
  graphics dependency. A voice orb is purely visual; shipping one unverifiable is the exact
  "looks done, isn't proven" failure this sweep exists to catch.
- **WV-170**: test + CI job are written and committed but have **never actually run** —
  Docker Desktop would not start locally. First real execution will be on GitHub Actions.

**Owner packets awaiting signature** (`docs/OWNER_TASKS.md`): code-signing certificates
(T-0.29), continuity-identity scoping (E731), drag-drop canvas build-or-drop (BUG-2b.2),
plus the pre-existing Lane A gates (⭐B0, 72h soak, license flip, design partners).

---

## 4. Environment gotchas — these cost real time last session

1. **Python is not in the worktree.** Use the main checkout's venv:
   `C:/Users/andrei649/Documents/GitHub/jarvis-hub/.venv/Scripts/python.exe`
2. **`frontend/node_modules` and `mobile/node_modules` do not exist here.** Junction them
   from the main checkout (lockfiles matched byte-for-byte, so it is safe):
   `New-Item -ItemType Junction -Path <worktree>/frontend/node_modules -Target <main>/frontend/node_modules`
3. **Mobile jest cannot run.** The junctioned `jest`/`jest-cli` are empty shells; `npx jest`
   fetches an unrelated jest and fails on babel config. Mobile tests are CI-only here.
4. **The `typescript` package entry is a stub** (`version.cjs`) — `ts.transpileModule` is
   undefined. The **`npx tsc` binary works**; use `npx tsc <file> --ignoreConfig --outDir …`
   to compile a single file (that is how the mobile contract ports were verified locally).
5. **`status_sync.py` full mode fails** on the mobile count. Hand-edit `project-status.json`'s
   `tests.frontend` after a frontend change, then run `scripts/status_sync.py --reuse-js-counts`.

---

## 5. Verification rules learned the hard way

**Run the FULL backend suite before calling a multi-slice run green.** Per-slice targeted
runs missed two cross-cutting failures last session:
- `docs/test-manual/14-api-surface-sweep.md` goes stale on any route change →
  `python scripts/gen_api_sweep.py`
- `test_orchestrator_bindings.py` pins binding calls by **exact line/column** — *adding an
  import to `web.py` breaks it*. Verify the real call site, then re-seed
  `EXTERNAL_BINDING_WRITERS` in `agents/core/orchestrator_bindings.py`.

**Adding a route requires all of:** `python tests/test_route_parity_guard.py --update`,
`python tests/test_openapi_parity_guard.py --update`, regenerate `tests/_snapshots/route_auth.json`,
add a `RULES` entry in `tests/test_hud_v2_parity.py` (mode or `NOT_IN_HUD`), a caller or a
`MACHINE_FACING`/`UNCALLED_BACKLOG` entry, `gen_api_sweep.py`, then `status_sync.py`.

**Two import traps:**
- `core.routers.X` and `agents.core.routers.X` are **different module objects** (both on
  `sys.path`). `web.py` mounts the `agents.` one — monkeypatching the other silently tests
  unpatched code while appearing to pass. Always import via `agents.` in tests.
- Calling a FastAPI handler directly bypasses dependency resolution, so `Query(...)`
  defaults arrive as `Query` objects, not ints. Pass them explicitly, and cover the real
  path with a `TestClient` round-trip.

**Known-environmental, NOT regressions:** `tests/test_ingestion_data_lifecycle.py` has 4
failures — `WinError 1314`, Windows symlink creation needs admin/Developer Mode. They
reproduce identically on clean `main` and pass on Linux CI. Exclude with
`--ignore=tests/test_ingestion_data_lifecycle.py` when sweeping.

---

## 6. Judgement notes worth inheriting

- **A gate caught the last session overstating its own work** (claiming T-0.41 closed while
  the digest consumed none of it). When a gate contradicts your claim, fix the claim first,
  then the code — do not silence the gate with a declaration.
- **Three times the tests were wrong and the code was right.** When a test fails, check the
  real contract before changing production code. Where a wrong fixture could pass vacuously,
  add a fixture-validity guard (see `test_a_valid_asset_and_metadata_pass_their_automatic_checks`).
- **Property tests earned their keep twice** — the sentence-aggregator round-trip (arbitrary
  chunk boundaries) caught two real bugs; the AUD-14 ratchet was red-proved with planted
  reads rather than assumed.
- **Prefer declaring a thing unsupported with a reason over stubbing it** (see `model` packs
  in `routers/packs.py`). An empty type that reads as done is worse than an honest absence.

---

## 7. Review status

**Nothing on this branch has been independently reviewed.** Per `AGENTS.md` the builder does
not accept its own work, and several slices touch governance-adjacent surfaces (vault router,
CORS validation, publish-readiness gate, kernel metrics). No PR was opened — the session was
instructed to work locally. Open one with:

```bash
gh pr create --base main --head claude/nerva-backlog-zero-f161fe --draft
```

Unrelated pre-existing: Dependabot reports 35 vulnerabilities on the default branch (22 high)
— that is the A3 owner tail, not introduced by this branch.
