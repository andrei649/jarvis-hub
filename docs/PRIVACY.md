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

## What's stored, and where

All runtime data lives under the **gitignored data root** (`agents/data/`, `memory_logs/`):
conversation transcripts, `memory.db` + the knowledge graph, the embedding cache, Howard's
raw `ingestion/` drop and derived `archive/`, the local analytics table, and the audit log.
Legacy repo-local `data/` is also gitignored, but the shipped Howard default now uses the
central data root so export, retention and forget can cover it. Credentials in `settings.db` are
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
- **Forget / delete** — `POST /api/admin/forget` erases everything under the data root except
  your settings/credentials, the installed-skill catalogue and the append-only audit chain:
  memory, transcripts, notes, run history, channel threads, vectors and the knowledge graph.
  It reports what it could **not** erase rather than claiming success over surviving data, and
  a store we don't reach (an unreachable Qdrant or Neo4j) is named in `not_erased`.
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
