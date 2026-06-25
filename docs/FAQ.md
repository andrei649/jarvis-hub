# Jarvis Hub — FAQ

> Quick answers. See the [User Guide](USER_GUIDE.md), [UPGRADE](UPGRADE.md),
> [PRIVACY](PRIVACY.md), and [SECURITY](../SECURITY.md) for depth.

### Does my data leave my machine?
**Not by default.** Jarvis is local-first and binds to loopback; your conversations,
memory, and knowledge graph stay on your disk. Data only leaves if **you** opt a specific
agent into a cloud LLM or enable a channel/plugin — and the **network monitor**
(`/api/admin/network/calls`) lets you *prove* local-only agents make zero outbound calls.
See [PRIVACY.md](PRIVACY.md).

### Is there any telemetry / phone-home?
**No.** No analytics beacon, no crash reporter, no usage tracker — there's no
Jarvis-operated server to receive it. The local "analytics" table is first-party and never
transmitted.

### Do I need a GPU?
For **cloud** LLMs, no. For **local** models, a GPU makes larger models comfortable, but
small models run on CPU. Jarvis tiers work by complexity to fit your hardware.

### Which models can I use?
Local via **LM Studio** or **Ollama**, and/or **cloud** providers (Anthropic, OpenAI,
Google) opted in **per agent**. Strict-local agents never make a cloud hop.

### Windows, macOS, or Linux?
All three. **Windows is first-class** (one-click `INSTALL.bat` / `START.bat`); Python 3.12+
is the floor (see [`COMPATIBILITY.md`](COMPATIBILITY.md)).

### Is it multi-user?
**No — single-user** for now (a deliberate 0.x scope; multi-user isolation is post-1.0).

### How do I stop proactive messages / autonomy?
Engage the **kill-switch** (Admin panel), lower the **interrupt budget**, or disable the
relevant watcher in settings. Proactive pushes are capped at **≤4/day** and reversible
actions wait in an **approval queue**.

### How do I add a channel like Telegram or Gmail?
Add its credentials in **Admin → settings** and enable the plugin. Each channel runs under
an allowlisted egress policy; disable it to stop all data flow to that provider.

### What does it cost?
Jarvis itself is **free and self-hosted**. Local models cost nothing to run. If you opt
into a cloud provider, you pay that provider directly for usage.

### How do I update?
Windows: double-click **`UPDATE.bat`**. Otherwise `git pull` + reinstall + restart. Schema
migrations apply automatically. Full steps + version notes: [UPGRADE.md](UPGRADE.md).

### How do I back up, export, or delete my data?
**Backup:** `POST /api/admin/backup` (optionally encrypted). **Export:** `POST
/api/admin/export` (portable bundle, secrets stripped). **Delete:** `POST /api/admin/forget`
(erases memory, transcripts, vectors, and the graph at rest). Retention TTLs can prune
automatically.

### What are WorldView and the Signal Layer?
**Optional** companion stacks: WorldView is the 4D OSINT globe (needs Node + Docker); the
Signal Layer is a situational-awareness API (replay mode by default). Both are opt-out
(`JARVIS_WORLDVIEW=0`, `JARVIS_SIGNAL_LAYER=0`) and Jarvis runs fine without them.

### Something's wrong — where do I look?
`GET /healthz` / `GET /readyz` for liveness/readiness, the **audit log** and **APM** in the
Admin panel, and the server console. To report a security issue, see [SECURITY.md](../SECURITY.md).
