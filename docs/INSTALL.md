# Install — one step per OS, ending inside the Command Center

> The activation funnel in one line. Every path below ends the same way: a `.venv`
> with the **hash-pinned** dependency set, a passed **install smoke** (real boot +
> `/readyz` + one deterministic chat turn), and the **Command Center** open at
> `http://127.0.0.1:8080/v2` — bound to **loopback only**. Nothing here asks for a
> cloud key; nothing here writes a bind other than `127.0.0.1`.

## Requirements

- **Python 3.12+** — the supported floor ([`COMPATIBILITY.md`](COMPATIBILITY.md)). The
  bootstrap refuses anything older with a named reason (`python_too_old:3.11<3.12`)
  instead of failing halfway through `pip`.
- **A local model runtime** for local-first replies: [Ollama](https://ollama.com)
  (`:11434`) or [LM Studio](https://lmstudio.ai) (`:1234`). The installer *detects*
  them on loopback and tells you; it never installs or starts one. Nerva boots
  without a runtime — cloud providers stay opt-in per agent.
- `git` only for the hosted one-liner (it clones the checkout for you).
- *Optional, opt-in:* Node 20+ and Docker only for the WorldView companion.

## Linux / macOS

Hosted one-liner (clones into `~/nerva`, or `$NERVA_DIR`):

```bash
curl -fsSL https://raw.githubusercontent.com/andrei649/jarvis-hub/main/install.sh | bash
```

From a checkout:

```bash
./install.sh              # venv + locked deps + smoke, then starts Nerva and opens /v2
./install.sh --no-start   # install only
./install.sh --dev        # also run the full offline pytest suite afterwards
```

`install.sh` is a thin wrapper: it finds an interpreter that meets the floor (or the
newest one it can, so the refusal is readable), optionally sets up WorldView
(`JARVIS_WORLDVIEW=1`), and hands over to `scripts/bootstrap.py`. When stdout is a
terminal it ends by running `./start.sh`, which opens the Command Center once
`/readyz` answers (`--no-browser` / `NERVA_NO_BROWSER=1` to skip).

## Windows 11

Double-click **`INSTALL.bat`** (inside the checkout, or anywhere — it clones for you
when `git` is present). It checks for Python 3.12 (offers `winget` when missing),
runs `scripts\bootstrap.py`, and after **[DONE]** asks *Start Nerva now?* — the
default after 15 s is yes, and `START.bat` opens `http://127.0.0.1:8080/v2` once the
server is ready.

No Node, no Docker, no 7,000-test run: WorldView is opt-in (`set JARVIS_WORLDVIEW=1`
before running `INSTALL.bat`).

For the packaged executable (built with `scripts\build_exe.py`), use
`packaging\windows\install.ps1 -Launch` — see [`PACKAGING.md`](PACKAGING.md).

## Docker (quickstart)

```bash
docker compose -f docker-compose.quickstart.yml up --build
```

One container, host networking, `JARVIS_HOST=127.0.0.1` — the same loopback posture as
the native install, so a runtime on the host is reachable at `127.0.0.1:11434` and
nothing is published on a LAN interface. Data lives in the `nerva_data` volume
(`JARVIS_HOME=/data`). Docker Desktop on macOS/Windows needs *Enable host
networking* (4.34+). The full stack (qdrant/neo4j/n8n + the headless coordinator) is
the separate `docker-compose.yml`.

## What `scripts/bootstrap.py` does

Stdlib-only, so it runs before any dependency exists, and tested with fakes
(`tests/test_bootstrap_script.py`):

| step | what | named failure |
|---|---|---|
| `python` | floor check `>= 3.12` | `python_too_old:<have><<want>` |
| `venv` | `python -m venv .venv` once; re-runs reuse it | `venv_create_failed` |
| `deps` | `pip install --require-hashes -r requirements-beta.lock` (`--unlocked` → `requirements-beta.txt`) | `pip_install_failed`, `requirements_missing` |
| `runtimes` | loopback probes for Ollama / LM Studio + an accelerator hint; report only | never fails (`no_local_runtime` is a note) |
| `smoke` | `scripts/install_smoke.py --json` in the venv, with `JARVIS_HOST=127.0.0.1` pinned and cloud keys scrubbed from the child environment | `smoke_failed`, `smoke_output_unparseable` |

`python scripts/bootstrap.py --json` prints the whole report; exit status is 1 on the
first failed step. Flags: `--skip-smoke`, `--unlocked`, `--root <checkout>`.

## Check-up: `doctor`

```bash
python scripts/doctor.py            # or: ./start.sh --doctor   /   START.bat doctor
python scripts/doctor.py --json     # machine-readable
python scripts/doctor.py --smoke    # also run the install smoke (~30 s)
```

Changes nothing; one named reason per row. Required rows (`FAIL` → exit 1): `python`,
`venv`, `locks_in_sync` (same rule as `scripts/lock_deps.sh --check`),
`bind_is_loopback` (what `boot_guards.assert_safe_bind` would refuse),
`data_root_writable`. Advisory rows (`warn`, never exit 1): `runtimes`
(`no_local_runtime`), `readyz` (`server_not_running` / `readyz_status:503`), `smoke`
(`skipped` unless `--smoke`). Paste the `--json` output into a bug report.

## After the install

- Start: `./start.sh` / `START.bat` → `http://127.0.0.1:8080/v2`.
- A phone or a second device is a separate, token-gated decision:
  [`PHONE_ACCESS.md`](PHONE_ACCESS.md). The installer never makes it for you.
- Update: `git pull` + `./install.sh --no-start` (or `UPDATE.bat`) — the venv is
  reused, only changed dependencies are installed ([`UPGRADE.md`](UPGRADE.md)).
- Uninstall: `./uninstall.sh --confirm` / `UNINSTALL.bat` removes `.venv` and the
  WorldView residue and **never** touches your data root
  (`agents/core/uninstall.py`, cross-checked against the installers by
  `tests/test_uninstall.py`).

## Troubleshooting by reason

| reason | fix |
|---|---|
| `python_too_old:3.11<3.12` | install Python 3.12+ and re-run; on Linux `python3.12` is picked automatically when present |
| `pip_install_failed` on an exotic platform | `./install.sh --unlocked` (installs from the loose `.txt`; hashes are not verified — say so in any bug report) |
| `smoke_failed` | run `python scripts/doctor.py --smoke` and read the last stderr line it quotes |
| `non_loopback_without_token` | you set `JARVIS_HOST` to a LAN address without `JARVIS_USER_TOKEN`; see [`PHONE_ACCESS.md`](PHONE_ACCESS.md) |
| `lock_stale:requirements-beta.lock` | a checkout mid-edit: `./scripts/lock_deps.sh` (needs `uv`) or `git checkout -- requirements-beta.lock` |
| `data_root_not_writable` | the folder in `JARVIS_HOME` (or `memory_logs/`) is not writable by your user |
