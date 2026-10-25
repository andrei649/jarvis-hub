# Handoff — Hermes absorption, session of 2026-10-21 … 2026-10-25

Ledger: **130/697** rows documented as equivalent (was 99 at the start of the last handoff, 119 when #1249 merged).
Source of truth is `docs/hermes/assessment.json`; query it with `scripts/hermes_status.py summary|list|show|check|write`
and `scripts/hermes_restamp.py cite|stamp`. BACKLOG entries for every batch are in `BACKLOG.md` (search "Hermes batch").

## What is finished (merged to `main`)

- **#1249 / #1251** Hermes absorption to 119/697 (H009, batches 1–2, H283/H310/H537).
- **#1254** local-pilot check in `nerva doctor` + shared-memory MCP read hints; **#1268, #1274, #1273, #1276, #1278, #1280, #1281** dependency / Bolt / flaky-test PRs.
- **#1279 (batch 3)** H164 H288 H331 H557 H574 H592 H652 equivalent; H444 partial.
- Closed as superseded or not worth merging: #1277 #1269 #1257 #1258 (each has a comment).
- Decision recorded: REA (`morluto/rea`) is not adopted — `docs/decisions/2026-10-20-rea-reverse-engineering-not-adopted.md`.

## What batch 4 delivers (PR from `claude/cto-session-recovery-qinvkg`)

Equivalent now: **H006** (`nerva config edit|path|env-path|migrate`), **H039** (webhook signed test, linear-time payload filter, `nerva webhook` verbs),
**H221** (HUD language menu + synced `lang` preference), **H354** (skill use/view/patch counters, in-process reality verify).
Partial, limits recorded in the ledger (`remaining`): **H303**, **H403**, **H414**, **H486** — see "Not finished" below.

## Not finished (next session starts here)

### Rows closed only partially (all have code on `main` once the batch-4 PR is merged)
| Row | What is missing |
|---|---|
| H303 file read/search | xlsx/pptx extractors; ripgrep is deliberately NOT used (Unicode class semantics differ, output could not be bounded) so a catastrophic-backtracking regex stops at the 10 s deadline with partial rows; `.gitignore` support is only plain directory names |
| H403 background review | summary is process memory and shown on the owner's NEXT admin turn (HUD / telegram / slack / discord / ntfy), not pushed on completion; not persisted; non-admin turns' reviews still spend the shared daily budget; cache-parity fork / review routing / split prompts not built |
| H414 `/btw`, run_oneshot, plugin LLM | main-chat-stream observer hooks (`on_stream_start/delta/end` with turn_id/session_id/model/surface) NOT built; no shipped plugin uses the LLM facade (`llm_access`/`attach_llm`); on ntfy `/btw` waits for the running turn; Discord/Slack batch pieces not in the snapshot |
| H486 denial breaker / ceilings | the sub-agent-spawn ceiling is a dormant guard (Nerva has no model-facing spawn tool); breaker counts chat `terminal_run` cards only; ceiling trip ends the turn with the cap notice; approval expiry is not counted |
| H444 | other document formats (only .pdf/.docx extracted) |

### Remaining Hermes work
- The 429-row backlog of `partial` rows: `docs/research/` triage says 78 closable with S/M work, 122 with L/XL work, 229 blocked (hardware, live accounts, protected paths, owner decisions). The ranking used for batches is `scratchpad`-only (not in the repo); regenerate with the same method: per-row plan + files from `hermes_status.py show`, skip rows whose files are protected.
- Candidate next rows already triaged as closable (S/M): H019 (`nerva status` service block), H046 (timeline node routes), H047 (insights module), H058 (per-user allowed commands, `/whoami`), H120 (gateway message dedup), H137 (tool-call SSE events), H258 (settings migration ladder), H322 (house tools), H336 (skill catalog route/CLI), H349 (origin recording, pin/unpin route), H367 (custom endpoints), H379 (auxiliary model pins), H381 (egress ledger), H382 (local API key), H411 (wire hygiene), H422 (core block budget/off routes), H434 (context engine protocol), H470 (kanban swarm), H491 (sub-agent approval cards), H510 (readyz for unaccepted Host), H519 (`vision_analyze` tool), H534 (room-aware Wyoming), H577 (session heartbeat), H632 (config docs), H646 (prompt tiers, `/compress`), H655 (CONTRIBUTING/OWNERSHIP docs), H697 (session recovery lever).
- Security-path rows (H481 H495 H502 H512, anything under `agents/core/security/**`, `kernel/**`, `secrets/**`) are the owner's — leave them.

### Process notes that cost time this session (read before the next batch)
1. **Worktree isolation bases on `origin/main`, not on the PR branch.** Agents must `git checkout -b X <base sha>` first.
2. **Every code change makes every ledger row that pins the changed file stale.** Order of work: implement → review → cherry-pick onto one integration branch → rebuild HUD bundle (`cd frontend && npm run build`, commit `agents/web/v2`) → `scripts/gen_api_sweep.py` → `scripts/status_sync.py --reuse-js-counts` → re-read rows (`reread.py`-style auto remap, hand re-read of flagged rows, a grep of ledger text for claims the batch made false) → `hermes_status.py write && check`.
3. **The citation checker uses `str.splitlines()` numbering** (form feeds, U+0085, U+2028 shift it against editors) and rejects a cited range whose FIRST line is blank or past EOF. `tests/test_file_search.py` contains such characters.
4. Guard tests that fail after touching these files: `tests/test_orchestrator_bindings.py` (line inventory of `autonomy_coordinator.py`/`plugin_manager.py`/`web.py` writers — update from the observed values), `tests/test_route_auth_matrix.py` + snapshots (new routes), `tests/test_hud_v2_parity.py` (new route needs a client caller), `tests/test_o26_p2_env_config.py` (env flags only through `env_config`), `tests/test_troubleshooting_docs.py`, `tests/test_cost_measurement_and_cap.py` (binds `_record_interactions` to a stand-in: use `Orchestrator._review_key`, not `self._review_key`).
5. Reviewers (2 per row, completeness + correctness, up to 3 rounds) found a real defect in every one of 8 rows — never skip them. Recurring defect classes: ReDoS / unbounded work on the event loop, cross-user leaks through process-wide state, claims in docs/labels for code paths no production caller reaches, redact-after-truncate, double counting.
6. `tests/test_socket_guard.py::test_external_connect_is_blocked_fast` fails locally when run with `-o addopts=""` (needs the repo's addopts); it is green in CI. Heavy parallel runs also make a few timing tests flaky (`test_recall_gate` handoff TTL, `test_h277_video_provider_chain`, session-kernel tests) — rerun them alone before treating as real.
7. Commit trailer / attribution follows the session reminder; commits must be signed (never `-c commit.gpgsign=false`). No force-push on shared branches; use merge commits. Do not edit `AGENTS.md`, `.github/**`, `.claude/**`, security/kernel/secrets paths.

## Owner follow-ups (not code)
- Canva MCP needs OAuth in claude.ai → Settings → Connectors.
- Codex security review on #1254 never finished (non-blocking); rerun with `@codex security review` if wanted.
- Business/Workspace work beyond the pilot spec waits for owner answers D1–D3 (`docs/decisions/2026-10-14-nerva-business-suite-kickoff-questions.md`).
