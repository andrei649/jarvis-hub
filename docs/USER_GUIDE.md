# Nerva — User Guide

> Get Jarvis running and learn the daily flow. Jarvis is a **local-first, self-hosted
> personal AI cabinet**: it runs on your machine, binds to loopback, and keeps your data
> on your disk. Pair with the [FAQ](FAQ.md), [UPGRADE](UPGRADE.md), and [PRIVACY](PRIVACY.md).

## 1. Requirements

- **Python 3.12+** (the supported floor — see [`COMPATIBILITY.md`](COMPATIBILITY.md)).
- **A local model server** for local-first use: **LM Studio** or **Ollama** running on your
  machine. (You can instead opt specific agents into a **cloud** LLM — see §5.)
- *Optional:* **Node 20+** and **Docker** only if you want the WorldView (4D OSINT) stack.

## 2. Install

One step per OS; every path ends with a passed install smoke and the **Command
Center** open at `http://127.0.0.1:8080/v2`, bound to loopback only. Full detail,
flags and troubleshooting-by-reason: [`INSTALL.md`](INSTALL.md).

**Linux/macOS — one line:**
```bash
curl -fsSL https://raw.githubusercontent.com/andrei649/jarvis-hub/main/install.sh | bash
```
(or `./install.sh` inside a checkout; `--no-start` installs without launching).

**Windows (no terminal needed):** double-click **`INSTALL.bat`** — it checks Python
3.12+, runs `scripts\bootstrap.py` (venv + hash-pinned deps + install smoke) and
offers to start Nerva right away.

**Docker:** `docker compose -f docker-compose.quickstart.yml up --build`.

**Manual (any OS):**
```bash
python3 scripts/bootstrap.py        # refuses Python < 3.12 with a named reason
python3 scripts/doctor.py           # check-up: one named reason per row, changes nothing
```
WorldView (4D OSINT) is an opt-in companion: `JARVIS_WORLDVIEW=1 ./install.sh`.

## 3. Start

- **Windows:** double-click **`START.bat`** (`START.bat doctor` runs the check-up).
- **Any OS:** `./start.sh` (or `python serve.py`) → the Command Center opens at
  **http://127.0.0.1:8080/v2** once `/readyz` answers (`--no-browser` to skip;
  `--doctor` runs the check-up). WorldView / the Signal Layer start only with
  `JARVIS_WORLDVIEW=1` / `JARVIS_SIGNAL_LAYER=1`.

Key surfaces:
- **Command Center (V2 HUD):** http://127.0.0.1:8080/v2 (also at `/`; legacy at `/v1`).
- **Admin panel:** http://127.0.0.1:8080/admin
- **CLI REPL:** `python agents/run.py`
- **Health:** `GET /healthz` (live), `GET /readyz` (ready).
- **From a phone / second device:** not reachable by default, by design — the
  token-gated LAN path is [`PHONE_ACCESS.md`](PHONE_ACCESS.md).

## 4. The cabinet

Jarvis is an **orchestrator (Jarvis)** routing a cabinet of specialist agents — e.g.
**Stark** (engineering), **Ultron** (security), **Frigga** (family/home, strictly local),
**Gecko** (finance), **Argus** (WorldView/geoint), **Howard** (your emerging digital
twin), and more — each with its own role, model tier, and capability/network scope. You
talk to Jarvis; it delegates.

## 5. Configure a model

Point Jarvis at your local server (LM Studio's OpenAI-compatible endpoint or Ollama) in
the **Admin panel → settings**, or opt a specific agent into a cloud provider by adding its
API key there. **Strict-local agents are never forced to make a cloud hop.** If the local
server is down, Jarvis degrades gracefully with a clear message rather than hanging.

### Integrations: keys for search and cloud models, in the HUD

**Console → Start → Integrations** is the one place for what needs your setup: the search
services (Tavily, Exa, Brave Search, Parallel), the cloud model providers that take a key
(native and the ones adopted from Hermes Agent) and a link to the Hermes skills catalog.

- **Key.** Open a line, type the key, save. It is stored encrypted in Nerva's secret store
  (`<data>/security/secrets.enc`) and works at once, without a restart. It is never shown
  again: only "set" and its last four characters. "remove key" takes it out at once.
- **`.env` still works and wins.** A key or search choice set in `.env` (or the hub's
  environment) is shown as "set in .env" and cannot be changed or removed from the panel.
  At start, a key stored from the panel is used only when `.env` does not set that name.
- **Shared key names.** A name several providers read (`DASHSCOPE_API_KEY`) is one key: the
  panel asks whether it is the same key for all of them, shows it as "shared key" on the
  others, does not test it there, and removing it from one provider keeps it for the rest.
- **Gemini** answers as soon as its key is set, so its key asks for your consent when saved.
- **Search services from Hermes** (Exa, Brave Search, Parallel) answer only when chosen
  ("Use", or `NERVA_WEB_BACKEND` in `.env`); automatic search never picks or falls back to them.
- **Test** asks that one provider or search service whether the key works, in plain words.
- **Use** picks the search service or the cloud model provider (with its model). If the
  choice needs your acknowledgement (data handling not verified, no known price), one card
  shows the facts and "I understand, use it" records your consent in the audit log.
- Only an admin token opens the panel.

## 6. Daily use

- **Chat** in the HUD (or the CLI). Replies stream; conversation memory + real-embeddings
  recall give continuity across sessions.
- **Voice** (optional): push-to-talk dictation + spoken replies.
- **Autonomy:** Jarvis can work proactively (watchers → proposals → an **approval queue**
  for anything reversible/irreversible). Proactive pushes are capped (**≤4/day** interrupt
  budget), and a runaway is halted by the kernel's budget/loop breaker.
- **Plugins & channels** (weather, news, Telegram, Gmail, …) are **opt-in** and run under a
  declared network/data policy; nothing reaches the cloud unless you enable it.

## 7. Admin panel (`/admin`)

Settings & secrets (encrypted at rest), the **security audit log** (verifiable), the
**network monitor** (`/api/admin/network/calls` — prove local-only agents make zero
outbound calls), **capability readiness** (`/api/metrics/capabilities`), **north-star +
guardrail** metrics (`/api/metrics/north-star`), APM, and the **kill-switch**.

## 8. Your data & controls

Everything lives under a gitignored data root on your disk. You can **export** (`POST
/api/admin/export`), **forget/delete** (`POST /api/admin/forget`), set **retention** TTLs,
and **back up** (`POST /api/admin/backup`, optionally encrypted). See [PRIVACY.md](PRIVACY.md)
for what (optionally) leaves the machine, and [SECURITY.md](../SECURITY.md) /
[THREAT_MODEL.md](THREAT_MODEL.md) for the defenses.

## 9. Upgrading

See [UPGRADE.md](UPGRADE.md) (Windows `UPDATE.bat`, or `git pull` + `./install.sh
--no-start` + restart; the venv is reused and schema migrations apply automatically).
Uninstall: `./uninstall.sh --confirm` / `UNINSTALL.bat` — your data root is never touched.
