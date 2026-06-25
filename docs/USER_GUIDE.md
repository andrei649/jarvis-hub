# Jarvis Hub — User Guide

> Get Jarvis running and learn the daily flow. Jarvis is a **local-first, self-hosted
> personal AI cabinet**: it runs on your machine, binds to loopback, and keeps your data
> on your disk. Pair with the [FAQ](FAQ.md), [UPGRADE](UPGRADE.md), and [PRIVACY](PRIVACY.md).

## 1. Requirements

- **Python 3.12+** (the supported floor — see [`COMPATIBILITY.md`](COMPATIBILITY.md)).
- **A local model server** for local-first use: **LM Studio** or **Ollama** running on your
  machine. (You can instead opt specific agents into a **cloud** LLM — see §5.)
- *Optional:* **Node 20+** and **Docker** only if you want the WorldView (4D OSINT) stack.

## 2. Install

**Windows (no terminal needed):** double-click **`INSTALL.bat`** — it checks/installs
Python + Git, fetches the code, builds the environment, installs everything, and runs the
tests.

**Any OS (manual):**
```bash
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-beta.txt                  # one install — full feature set
python -m pytest                                       # optional: confirm a green suite
```
*Linux/macOS shortcut:* `./install.sh` does the venv + install + tests in one step.

## 3. Start

- **Windows:** double-click **`START.bat`**.
- **Any OS:** `python serve.py` → **http://127.0.0.1:8080** (or `./start.sh`, which also
  launches WorldView + the Signal Layer when present).

Key surfaces:
- **HUD (cockpit):** http://127.0.0.1:8080/ — the V2 HUD (legacy at `/v1`).
- **Admin panel:** http://127.0.0.1:8080/admin
- **CLI REPL:** `python agents/run.py`
- **Health:** `GET /healthz` (live), `GET /readyz` (ready).

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

See [UPGRADE.md](UPGRADE.md) (Windows `UPDATE.bat`, or `git pull` + reinstall + restart;
schema migrations apply automatically).
