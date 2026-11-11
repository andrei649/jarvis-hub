# What is left after the 2026-11-11 merge to main

State when this was written: `main` contains PR #1347 (Nerva rebrand + Hermes integrated by feature) and
every other PR that was open on 2026-11-11 (#1341, #1342, #1343, #1348 and the five dependency updates
#1349–#1353). Hermes ledger: **161 equivalent · 489 partial · 11 missing · 36 excluded** of 697
(`scripts/hermes_status.py summary`).

## 1. Built but not reviewed — patches, not on `main`

Three rows were built after the last review round. They are **not merged** because each touches a
security-sensitive path and has not had the independent adversarial review every other group got.
Each patch applies on top of commit `f1d54ad` (generated files left out — regenerate after applying):

| Patch | Row | What it does | Review focus |
|---|---|---|---|
| `docs/hermes/pending/H624-update-apply.patch` | H624 | Apply an update only to a commit/tag signed by an owner-pinned key, behind a fresh verified backup and an irreversible-tier card; post-restart health check; automatic and manual rollback | signature verification, git argument/env hardening, dependency install, rollback correctness |
| `docs/hermes/pending/H224-terminal-interaction.patch` | H224 | Keyboard model for the terminal chat (Ctrl+C semantics, $EDITOR, history, completion, queue, session switcher, model picker) and a turn-interrupt route | the interrupt route may only cancel the caller's own turn; history file permissions |
| `docs/hermes/pending/H658-remote-room-members.patch` | H658 | A remote machine joins a shared session under a capability the target machine issues, scopes, ties to a policy digest and can revoke | capability forgery/replay, revocation on every call, remote actions run as the member principal under the target's kernel |

Process for each: apply → regenerate (`scripts/hermes_status.py write`, `tests/test_openapi_parity_guard.py --update`,
`scripts/gen_api_sweep.py`, `tests/test_capability_readiness_matrix.py --update`, `tests/test_tool_surface.py --update`,
`frontend/src/api/schema.gen.ts`, `cd frontend && npm run build`, `scripts/status_sync.py`) → adversarial review with
runnable repros → fix → rerun the repros → merge.

## 2. Hermes rows still `missing` (11)

| Rows | Why open | Next step |
|---|---|---|
| H624, H224, H658 | Built, unreviewed (section 1) | Review and merge |
| H032, H214, H238, H590, H657 | Hermes offers them only through its own sidecar (model committee, mascot "pet", room failover); the original audit marked them skip | **Owner decision:** exclude, expose through the governed sidecar, or build natively |
| H040, H086 | `hermes sync` and the browser-control broker no longer exist at the pinned Hermes commit | **Owner decision:** build natively from the ledger text, or exclude |
| H690 | macOS TCC permission anchoring | Needs a macOS host |

## 3. Hermes rows `partial` (489)

Every partial row names its remaining work in `docs/hermes/assessment.json` (`scripts/hermes_status.py show Hxxx`).
The recurring themes:

- **Live verification**: providers, Twilio SMS, Matrix, real editors over ACP, language servers beyond pyright and
  typescript, a real Hermes sidecar install on pin 9c0560f8, desktop shell on macOS/Windows.
- **Breadth gaps against Hermes**: 9 of 37 hook events; 23 of 27 language servers; ACP `session/load`/fork/list;
  MMS and proactive SMS; media delivery outside Telegram; channel enable switches and Test probes.
- **Hardening still open**: hook runs and language servers have no OS sandbox outside Linux/bwrap; with the Action
  Kernel off (default) hook runs are checked directly rather than through the kernel; dependency sub-pins for
  language-server installs; install egress enforcement.
- **Matrix E2EE (H127)**: Olm/Megolm needs a new pinned dependency (owner decision).
- **Credential isolation (H496)**: per-guest credentials and per-guest shares; plugins that read keys from the
  process environment are guarded at the turn seams only.

## 4. BACKLOG items outside Hermes

`scripts/backlog.py open` lists 39 open rows. Owner-gated: RB-3 (code identifiers and repo rename), NWS-21 (pilot
tag), GAP-4 / DRA-45 (run the Hermes head-to-head), DRA-62 (VRAM benchmark numbers), the hardware/credential
wiring rows (Google OAuth, Spotify, Home Assistant, Frigate, Telegram token). Engineering: NWS-8 (native OIDC),
NWS-9 (MCP business connectors), SEC-B5 (dataflow taint), the kernel default flip (criteria-gated), HA-4i, DRA-08,
DRA-58/59/60.

## 5. Known test environment caveats

In a container running as root, `tests/test_h361_*` and three `tests/test_action_auth_matrix.py` cases fail
("sandbox uid must be a non-root identity"); run the suite as a non-root user. A few tests are load-sensitive under
`-n 8` (route-auth AST scan, workspace OCR process tests) and pass alone.
