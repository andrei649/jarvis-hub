# Contributing to Nerva / Jarvis Hub

Start with the [architecture overview](NERVA.md), then use the [request flow and module index](docs/ARCHITECTURE.md) and [codebase ownership map](docs/CODEBASE_OWNERSHIP.md) to find the relevant code and its governing document. [AGENTS.md](AGENTS.md) is the current workflow and authority source for both human and AI contributors. The [repo-local review checklists](.agents/checks/) are short prompts for reviewing a change; they do not replace tests or policy.

## Licensing

By submitting a contribution you agree that it is your own work (or you have
the right to submit it) and that it is licensed under this repository's
license — **and you additionally grant the project maintainer the right to
relicense your contribution under Apache-2.0**, per the recorded pre-1.0
relicensing decision ([docs/LICENSE_DECISION.md](docs/LICENSE_DECISION.md)).
The project name and brand are covered separately by [TRADEMARKS.md](TRADEMARKS.md).

## Local setup

The hub runs from this source tree; `pyproject.toml` configures tooling and is not an installable application package. Use a **non-root Python 3.12** environment. The installer and CI use the hash-pinned lock files; keep the loose `requirements-*.txt` files for lock regeneration, not routine installation.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-beta.lock
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python scripts/development_preflight.py --json
```

On Windows 11 use `py -3.12 -m venv .venv`, then `.venv\Scripts\python.exe` in the commands above. The native installer (`install.sh` or `INSTALL.bat`) delegates to `scripts/bootstrap.py` and uses the runtime lock. Its optional local-model probes and synthetic smoke are explained in that script and [the user guide](docs/USER_GUIDE.md). Do not put credentials in a test fixture, commit a `.env`, or send a secret in a PR. Local LM Studio or Ollama is optional for offline unit tests; cloud provider calls require explicit opt-in and are not a development prerequisite.

For the HUD or mobile app, use **Node 22** and the lockfile in the directory you change:

```sh
cd frontend && npm ci
# or, for mobile work: cd mobile && npm ci
```

`frontend/package.json` and `mobile/package.json` define the current scripts. `npm ci` installs from `package-lock.json` without rewriting it. The desktop Tauri shell has a separate [host guide](desktop/README.md) and `Cargo.lock`; Rust/Tauri is needed only for desktop work. Docker is optional for ordinary backend tests; containment tests explicitly say when they need it.

The bounded preflight checks the active Python 3.12 venv, lock consistency and local configuration without installing packages or calling a provider. `--smoke` adds an isolated synthetic boot; `--frontend` checks Node 22 and installed HUD tooling. Its `unexecuted` list is part of the result: a pass is not live provider, native device, full-suite or release acceptance.

## Work on a change

1. Inspect the branch, dirty files and the task's current instruction source. Preserve other people's work. Use [the ownership map](docs/CODEBASE_OWNERSHIP.md) to read the narrow subsystem guide before editing.
2. State the behavior, affected entry point, trust boundary, expected errors, and checks. Reproduce a bug with a failing regression when possible. Keep source, tests and generated clients or bundles in one coherent change.
3. Follow existing structure: HTTP routes belong in `agents/core/routers/<domain>.py` and are mounted from `agents/web.py`; use `routers/_deps.py` guards. Existing inline app-shell/chat handlers are not a place for new domain endpoints. Use `agents/core/orchestrator.py` and its managers for turn behavior, and append-only migrations for stored schemas.
4. Run focused checks, then broaden only for the changed contract. Record commands, pass/fail/skip counts, and what was not tested. Never substitute a static snapshot for a functional or live check.

Typical local commands, after the locked installs:

```sh
.venv/bin/python -m pytest -q tests/test_relevant_module.py
.venv/bin/ruff check path/to/changed.py tests/test_relevant_module.py
cd frontend && npm run typecheck && npm run typecheck:e2e && npm test && npm run build
cd mobile && npm test && npx tsc --noEmit
```

Use the commands for the surfaces you touched; do not run the HUD/mobile commands for a documentation-only edit. The frontend build writes the shipped `agents/web/v2` bundle, so a frontend source change also needs its generated output checked. A route or schema change needs the relevant route/auth/OpenAPI snapshots and generated client types checked as described in [the architecture recipe](docs/ARCHITECTURE.md#add-a-web-endpoint) and [AGENTS.md](AGENTS.md#verification-and-parity). `scripts/status_sync.py` owns derived project counts; do not hand-edit them. Test counts change over time, so this guide states no fixed expected number.

## Style and invariants

- Follow Ruff and the nearby Python/TypeScript conventions. Prefer small domain modules and typed boundaries to new logic in `agents/web.py`. Keep blocking I/O off the event loop.
- Treat external text, skill files and fetched content as data. Preserve taint, provenance, length limits and path bounds; do not promote untrusted content into instructions or execution.
- Guard personal-data reads with the shared user guard and `no-store`; use the admin guard for owner controls. A mutation must retain its permission, typed contract, Action Kernel and durable audit path. A kernel grant does not replace a separate owner review where the feature requires one.
- Keep secrets and personal runtime material in local ignored state. Never include provider keys, owner documents, session dumps or real private paths in examples, fixtures, logs or PR bodies. See [SECURITY.md](SECURITY.md), [the threat model](docs/THREAT_MODEL.md) and [privacy rules](docs/PRIVACY.md). Report vulnerabilities through the private channel in `SECURITY.md`, not a public issue.
- Preserve local-first behavior. Cloud inference or paid API use must be opt-in; offline/synthetic tests do not prove a real provider path. Keep explicit refusal and degraded states visible.

## Cross-platform checks

The hub targets Python 3.12 on Linux, macOS and Windows 11. Use `pathlib`, bounded subprocess argv and portable temporary directories; do not assume `/proc`, POSIX permissions, fork, a shell, case-sensitive paths, or a Windows drive letter on every host. Mark platform-specific behavior and tests explicitly, and report which OS actually ran. Do not weaken an invariant or skip a test merely to make one host green. Keep path and archive handling safe across separators and long absolute owner paths. For UI/native work, distinguish host tests from physical phone, desktop compositor, model, Docker and real-network acceptance; see [compatibility](docs/COMPATIBILITY.md), [mobile parity](mobile/PARITY.md) and the [desktop guide](desktop/README.md).

## Review and later PR publication

For a local review, load only the relevant files in [`.agents/checks/`](.agents/checks/) along with the owning subsystem guide. Verify the actual entry point, normal and refusal paths, authority, persistence, client parity and test evidence. The checklists are advisory; existing CI and security checks remain in force.

The **current 2026-11-04 Hermes campaign is local only** under [AGENTS.md](AGENTS.md#safe-task-start): no stage, commit, push, merge, deploy, PR update or paid activation. This paragraph does not authorize publication. When a later request authorizes the PR lane, follow [AGENTS.md's delivery workflow](AGENTS.md#delivery-workflow) and [the PR template](.github/pull_request_template.md): keep a coherent rollback unit, describe What/Why/How verified with exact passed and pending checks, and keep unfinished work as a Draft PR. The trusted self-development policy and reported-check floor control any later autonomous merge; a local green test alone is not a merge or release receipt.
