# Privacy Policy — Jarvis Hub

> How Jarvis handles your data. The short version: **it's your machine, your data, and
> nothing leaves it unless you opt a specific agent or channel into the cloud.** Grounded
> in the code; pair with [`THREAT_MODEL.md`](THREAT_MODEL.md). Last reviewed: 2026-06.

## The principle: local-first

Jarvis Hub is **self-hosted and single-user**. It runs on your own machine and binds to
**loopback (`127.0.0.1`) by default** — there is no Jarvis-operated server, account, or
cloud backend. Your conversations, memory, and knowledge graph live on **your disk**.

## No telemetry, no phone-home

Jarvis ships with **zero outbound telemetry**. There is no analytics beacon, crash
reporter, or usage tracker calling out to us or a third party — we have no servers to
receive it. Two things people sometimes mistake for telemetry:

- **First-party analytics** (`analytics_store.py`) — a *local* event table (Plausible
  lineage), aggregated on-read with SQL. **No cookies, no cross-site IDs, no third-party
  (GA4)**, never transmitted off-box.
- **The neural-mesh "telemetry feed"** (`routers/brain.py`) — an *in-process* feed that
  drives the HUD's live visualization. It never leaves the machine.

If outbound telemetry is ever added, it will be **opt-in and disclosed here** — never on
by default.

**This promise is tested, and here is exactly what the test measures** (0.22):
`tests/test_no_telemetry_proof.py` boots the real app through its real lifespan, holds a
real `/chat` turn, and shuts it down, while *counting* every non-loopback socket egress
attempt — TCP connect, connected **and unconnected UDP**, and raw sends. It counts rather
than raises, because a best-effort caller would swallow a blocked connect and hide the
beacon. It also instruments `subprocess.Popen`, `os.system` and `os.popen` and **refuses a
recognised network tool before it runs** (including via `sh -c`, `env`, `shell=True`,
`cmd /c`, and PowerShell web cmdlets). Measured result: **zero** egress attempts.

What it does **not** prove, stated plainly rather than implied:

- it observes *this process*. A fully general guarantee needs an OS-level egress deny
  (network namespace / firewall) — a host control, not a test;
- the accompanying static scan is a **known-vendor ratchet** (sentry, GA, segment, …), not
  a general guarantee: an IP literal, a novel hostname, a runtime-composed URL, or a beacon
  inside a third-party dependency is invisible to it. It exists so a *recognisable* beacon
  cannot be pasted in unnoticed;
- **child processes are bounded, not proven silent**: a child uses its own sockets, which
  the in-process hooks cannot observe. A recognised network tool is blocked pre-exec, but a
  renamed binary, a bespoke client, or an uninstrumented spawn API (`os.posix_spawn`,
  `os.execv`, `multiprocessing`) would not be caught. Nerva does spawn `docker info`,
  `wasmtime --version` and `uname -p` at boot — the claim is "no recognised network tool
  ran", not "no child ran";
- owner-configured cloud agents and plugins are opt-in by design, disclosed above, and
  governed by the egress monitor — they are out of scope for this gate.

## What's stored, and where

All runtime data lives under the **gitignored data root** (`agents/data/`, `memory_logs/`):
conversation transcripts, `memory.db` + the knowledge graph, the embedding cache, Howard's
raw `ingestion/` drop and derived `archive/`, the local analytics table, and the audit log.
Legacy repo-local `data/` is also gitignored. If it contains imports from an existing install,
Howard keeps watching it rather than orphaning it, but it is outside the configured data-root
authority: Nerva does not silently move or erase it and marks export/forget incomplete until the
owner resolves it. A clean install uses the central data root. Credentials in `settings.db` are
**Fernet-encrypted at rest**; backups can be written **encrypted** (`.tar.gz.enc`).

## What can leave the machine — and only when you opt in

Nothing leaves unless you enable an agent/plugin that talks to the cloud. Each plugin
declares a **data scope** and **network policy** enforced at the egress choke point, and
the **network monitor** (`GET /api/admin/network/calls`) lets you *prove* that local-only
agents make zero outbound calls:

| What leaves | When | Where |
| --- | --- | --- |
| Your prompt + context | Only if you route a turn to a **cloud LLM** | The provider you configured (Anthropic/OpenAI/Google) |
| Message contents | Only via a **channel** you enable | Telegram / Gmail / Discord / Slack APIs |
| OSINT queries | Only in **WorldView** flows | The providers you configure |
| LAN-only data (family/home) | Stays on your **local network** | Pi / homebridge / WhatsApp bridge (`LAN`-scoped, never cloud) |

Strict-local agents (`frigga`, `ultron`, `howard`) are **never** forced to make a cloud
hop. Local-first is enforced, not just promised.

## Your controls

- **Export** everything you hold — `POST /api/admin/export` (portable bundle, secrets stripped),
  including raw Howard imports and every derived archive artifact. Symlinks are never followed and
  make the export report `private_ingestion_complete: false` instead of silently leaking a target.
  An unresolved pre-G35 repo-local import root does the same and is named in
  `legacy_private_ingestion`; its content is not silently copied across the authority boundary.
- **Forget / delete** — `POST /api/admin/forget` erases everything under the data root except
  your settings/credentials, the installed-skill catalogue and the append-only audit chain:
  memory, transcripts, notes, run history, channel threads, vectors and the knowledge graph.
  It reports what it could **not** erase rather than claiming success over surviving data, and
  a store we don't reach (an unreachable Qdrant or Neo4j) is named in `not_erased`.
  A detected legacy Howard root is likewise named in `not_erased`, sets `ok: false`, and remains
  untouched for explicit owner resolution.
  A pre-forget archive is taken by default so an accidental forget is recoverable — it is
  **encrypted** and kept **outside** the data root, only the newest is retained, and you can
  decline it with `{"backup_first": false}`.
- **Retention** — TTLs prune old transcripts/audit rows automatically; Howard imports/archive have
  their own `retention.ingestion_ttl_days` and default to `0` (keep forever). Retention is globally
  off by default.
- **Kill-switch** — one engage halts new privileged actions (and, as the kernel syscall lands, quarantines credentials).
- **Encryption** — secret columns + opt-in encrypted backups.

## Third parties

The only third parties involved are the **cloud LLM providers and messaging platforms you
choose to configure**. Once enabled, data you send through them is handled under *their*
privacy policies — Jarvis does not add any intermediary. Disable the plugin/agent to stop
all data flow to that provider.

## Questions / disclosure

Security and privacy concerns: see [`SECURITY.md`](../SECURITY.md).
