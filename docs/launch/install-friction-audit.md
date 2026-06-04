# Install-friction audit — Jarvis Hub (2026-06-04)

> Why this exists: the GTM research found local AI's #1 adoption killer is **friction, not quality**
> ("it just works" is the top messaging lever). This audits the cold-start install/run path and fixes
> what it found — verified by actually booting the server, not by reading.

## Verdict

**Running it already "just works" — the friction was in the install path (now reduced to one command).**

**Cold-start test** (this box, a venv with only `requirements-beta` + dev installed — deliberately *no* "extras"):
`python serve.py` → **HTTP 200 at `/status` in 0.12s**, log shows `Components: 19/19 components ok`,
web + voice channels up, and a graceful `backend: none` with no LM Studio running. It boots fine
**without** `tiktoken`/`beautifulsoup4` (both have graceful fallbacks) — proof the second "extras" pip
step was never required to run.

## Findings & fixes (this PR)

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | **Two pip commands.** README + INSTALL.bat + UPDATE.bat run a 2nd `pip install tiktoken beautifulsoup4 psutil pytest-asyncio`, but **`psutil` and `pytest-asyncio` are already in `requirements-beta.txt`**, and tiktoken/bs4 are graceful-optional. | Friction (high — the #1 killer) | Folded `tiktoken` + `beautifulsoup4` into `requirements-beta.txt`; **deleted the redundant 2nd pip line** in README/INSTALL/UPDATE → **one install command**. |
| 2 | **INSTALL.bat update path is broken.** `git pull --rebase origin master` (×2), but the default branch is **`main`** → fails on any re-run over an existing checkout. | Bug | `master` → `main` (UPDATE.bat already used `main`). |
| 3 | **No venv guidance for Linux/macOS.** The "Manual (any OS)" path runs `pip install` against system Python → on modern Debian/Ubuntu/Homebrew it hits PEP-668 "externally-managed-environment" / "Cannot uninstall PyYAML" (**reproduced on this box**). | Friction | Added `python3 -m venv .venv && source ...` to the Quickstart. |
| 4 | **Stale boot banner.** `serve.py` printed `v0.9.2` (project is 9.9.9). | Doc-truth | Dropped the hard-coded version from the banner. |

## Noted, not changed
- `requirements-beta.txt` still carries dev deps (`pytest*`) because INSTALL/UPDATE run the suite as a verify step. Splitting runtime vs dev requirements is a possible follow-up.
- On boot the HUD polls `api.github.com` for the latest commit (returned 403 here). Harmless, but for a privacy-first product, consider making the outbound "latest commit" check opt-in / clearly disclosed.

## Recommended before public launch (not code — tracked in the launch plan)
- A real **demo GIF** above the README fold (already flagged with a `TODO` in the hero, PR #135).
- Optional: an `install.sh` mirror of `INSTALL.bat` so Linux/macOS gets the same one-double-click parity.
