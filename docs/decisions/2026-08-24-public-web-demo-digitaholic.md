# Decision + spec — public web demo instance for digitaholic.ro (H23.23-adjacent)

> **Status: DRAFT — produced outside the normal dev session, for owner review before any branch is
> opened.** Written by a Claude (Cowork) session working on digitaholic.ro, at Andrei's request,
> after reading [`docs/decisions/2026-07-11-single-user-1.0.md`](2026-07-11-single-user-1.0.md),
> `agents/core/security/hardened.py`, `agents/core/memory/{manager,graph,seed_graph}.py`,
> `agents/core/llm/hybrid_router.py`, and `agents/_system/agents.yaml` against the `main` branch as
> of 2026-08-24. Not an implementation — no branch, no PR, no code changed. Meant to be the
> "record goal, non-goals, likely paths, risk, tests, rollback, and dependencies" step `AGENTS.md`
> asks for before non-trivial implementation.
>
> **Implementation note (2026-08-26, appended — the spec body below is left as written):** the one
> core code change this spec asks for is now delivered. `seed_graph()` self-gates on
> `NERVA_PUBLIC_PROFILE` and returns 0 without touching the graph. It was placed **inside
> `seed_graph()`** rather than at the `MemoryManager.__init__` call site named below, so no present
> or future caller can re-open the exposure; the default (flag unset) is unchanged. Evidence:
> `tests/test_public_profile_seed_gate.py` (+8). Nothing else in this spec is built: no roster
> overlay, no container, no deployment, and the four owner calls are still open.

## The question

Andrei wants a real, functional Nerva instance embedded in a digitaholic.ro page — not the scripted
`/nerva-ai-os/` Action Kernel demo — connected to a free online model, auto-updated from `main`. His
framing: strip personal data out, and have Nerva "learn to use a folder or archive" so each visitor
gets something like a save-game slot for their own personalization.

## This is not a new question — H23.23 already answered the hard part

[`docs/decisions/2026-07-11-single-user-1.0.md`](2026-07-11-single-user-1.0.md) (status:
RECOMMENDED, still awaiting owner ratification) already chose, for the exact same underlying
tension: ship single-user per install; treat per-user isolation inside one running instance (shared
memory/session/canvas/approval partitioned by identity) as a large, security-sensitive, explicitly
post-1.0 horizon. Nothing about wanting a public demo changes that reasoning — if anything it raises
the stakes, since the "users" would now be anonymous strangers instead of 1–3 vetted design
partners.

**Consequence for the save-game idea:** don't build per-user partitioning into the shared memory
subsystem (that's still option B, still deferred, still large). Instead, map "save" onto the unit
the architecture already endorses — **one install per user**. A visitor's "save" is a disposable,
isolated Nerva install; the folder Andrei is picturing is literally that install's `$JARVIS_HOME`
data root. This is smaller, matches what's already decided, and doesn't touch the deferred work at
all.

## What already exists and can be reused as-is

- **CDX-12 hardened profile** (`agents/core/security/hardened.py`, `JARVIS_HARDENED=1`) — off by
  default, built for exactly this: design-partner / multi-tenant box. One flag tightens guardrails
  to `REDACT`, forces HMAC-keyed audit log, forces strict egress, blocks mutating MCP tools, and
  turns on CDX-11 plugin least-privilege. [`docs/OWNER_TASKS.md`](../OWNER_TASKS.md) already lists
  turning it on as Andrei's call — this is that call, scoped to one box.
- **CDX-11 plugin least-privilege** — under hardening, external-transmit plugins (`social_x`,
  `writeback_*`, `call_*`, `channel_*`, `telegram`) are deny-by-default; `JARVIS_PLUGIN_GRANTS` must
  explicitly name `plugin_id:agent_id` pairs. For the public box: grant nothing, or nothing that
  writes anywhere real.
- **In-memory fallbacks for both stores** — `create_graph()` falls back to `InMemoryGraph()` when
  Neo4j isn't configured/reachable; vector store falls back to `InMemoryVectorStore` unless
  `VECTOR_BACKEND=qdrant`. A disposable public instance needs neither Qdrant nor Neo4j — it can run
  fully in-process, which keeps hosting cheap and removes two stateful dependencies from a box that
  gets thrown away anyway.
- **Cloud LLM routing already exists** — `hybrid_router.py` supports any OpenAI-compatible endpoint,
  `agents.yaml` already has a `cloud_llm_agents` allowlist (`jarvis, athena, stark, vision,
  veronica`) and `LOCAL_ONLY_AGENTS = {frigga, ultron, howard, hestia}` hardcoded with no cloud
  fallback. Plugging in a free-tier provider (OpenRouter/Groq/Gemini — verify current limits at
  implementation time, they move) is a config change, not new engineering. The four local-only
  agents simply won't run without a local model — which is correct here, since a
  family/security/home/digital-twin agent means nothing for an anonymous visitor anyway.

## What's a real gap — small, but must not ship silently

- **`agents/core/memory/seed_graph.py` is the exposure.** `SEED_FACTS` hardcodes
  Andrei/Alexandra/Max/Raiffeisen/Cosmina de Sus/BMW E93 and seeds them into the graph on first boot
  whenever it's empty. This is almost certainly the source (or a source) of what
  `claude/nerva-jarvis-hub.md` already flagged as public-repo exposure. A public box must not call
  `seed_graph()` as-is. **Smallest fix:** gate the call in `MemoryManager.__init__` behind a new flag
  (e.g. `NERVA_PUBLIC_PROFILE=1` skips seeding, or seeds a generic/empty fixture instead). This is
  the one core-code change this spec actually requires; everything else above is configuration.
- **Agent roster for the public box needs an explicit allowlist**, not just "whatever's in
  `agents.yaml`." Practical shape: a `agents.public.yaml` overlay (or a `status: disabled` flip)
  limited to the cloud-capable, non-local-only agents relevant to a demo (jarvis / athena / vision /
  veronica are plausible; stark is internal-KPI-flavored and probably not visitor-facing). Pick the
  smallest roster that still demonstrates the loop, not all 18.
- **No identity model exists today** (`X-User-Token` gates by presence, not identity — H23.23 says
  this plainly). A visitor's session ties to their disposable container via a bearer token/cookie for
  that session's lifetime. Durable "come back tomorrow, same save" is **out of scope for v1** — that
  requires storing whatever the visitor told Nerva about themselves past the session, which makes
  Digitaholic a data controller for a stranger's personal data (GDPR, since Digitaholic is a Romanian
  company — this is the same compliance lens as the ComplyDesk roadmap item). If durable saves are
  wanted later, that's a deliberate v2 decision with a retention/deletion policy, not a default.

## Proposed shape (v1)

1. Build a container image from `main` with: `JARVIS_HARDENED=1` + `JARVIS_AUDIT_KEY` set,
   `JARVIS_PLUGIN_GRANTS` empty, `NERVA_PUBLIC_PROFILE=1` (new flag, skips `seed_graph()`),
   `VECTOR_BACKEND` unset / `KNOWLEDGE_GRAPH_BACKEND` unset (in-memory), a free-tier
   OpenAI-compatible endpoint configured as the LLM backend, agent roster limited via
   `agents.public.yaml`.
2. One container per visitor session (or per N-minute-idle-timeout), destroyed after. The
   container's data root is the "save" for that session only.
3. digitaholic.ro page embeds a small chat widget (same `wp:html` block pattern as the rest of the
   site) that talks to whichever box is currently live.
4. GitHub Actions on push to `main`: build the image, push to a registry, redeploy the public-box
   host. Because v1 only needs a config/env overlay plus the one seed-skip flag, most `main` changes
   flow through without touching this spec again; a core-breaking change still needs the same
   forward-only migration discipline [`docs/UPGRADE.md`](../UPGRADE.md)/H23.18 already describes for
   normal upgrades.
5. Hosting: no GPU/heavy RAM requirement (cloud LLM + in-memory stores) — any small container host
   works; check current free-tier compute limits when actually building this, they change.

## Non-goals (v1)

- Per-user isolation inside one shared running instance (still H23.23 option B, still deferred).
- Durable cross-visit "save" / any real identity system.
- Any of the four `LOCAL_ONLY_AGENTS`, or any external-transmit plugin, reachable from the public
  box.
- Indexing the full repo (including `docs/VALUATION_AND_PRICING.md`, test fixtures, or anything else
  already flagged in the public-repo exposure note) into whatever the public agents can retrieve.

## Suggested risk tier

Reads as **R2** under the canonical policy — a new deployment surface plus one small env-gated code
path (`seed_graph()` skip), no auth-identity model change, no kernel change. Whoever picks this up
should classify it properly against [`.github/ai-development-policy.json`](../../.github/ai-development-policy.json)
rather than trusting this read.

## Dependencies / open calls (Andrei's, not this session's)

- Ratify H23.23 (A) — or note explicitly that this spec uses the install-per-user shape it already
  recommends, so it doesn't block on ratification either way.
- Turn on CDX-12 hardened + decide `JARVIS_PLUGIN_GRANTS` for this box specifically (already an open
  [`docs/OWNER_TASKS.md`](../OWNER_TASKS.md) item — this is that decision, scoped).
- Pick the free LLM provider/key.
- Pick the container host.

## Rollback

New, separate deployment surface — doesn't touch the primary personal install, its data, or its
`JARVIS_HOME`. Rollback is stop-routing-the-page-to-it / redeploy the previous image. Blast radius to
the real Nerva install is zero by construction, as long as the public box never gets pointed at the
real data root or the real plugin grants.

---

## Verification of this draft's references (added on filing, 2026-08-24)

Checked against `main` at `75e9281` when this draft was filed into the backlog — every load-bearing
claim holds:

| Claim | Verified |
|---|---|
| `hardened.py` exists, `JARVIS_HARDENED` opt-in, forces strict egress + audit key | ✅ `agents/core/security/hardened.py:30-87` |
| `SEED_FACTS` hardcodes personal data, seeded unconditionally on empty graph | ✅ `seed_graph.py:10`, called at `memory/manager.py:45` — was **unconditional** when written; gated by `NERVA_PUBLIC_PROFILE` since 2026-08-26 |
| `LOCAL_ONLY_AGENTS = {frigga, ultron, howard, hestia}` | ✅ `llm/hybrid_router.py:93` |
| `cloud_llm_agents: [jarvis, athena, stark, vision, veronica]` | ✅ `agents/_system/agents.yaml:21` |
| `NERVA_PUBLIC_PROFILE` is a *new* flag | ✅ zero occurrences in tree when this spec was written; **implemented 2026-08-26** in `seed_graph.py` |
| CDX-12 / CDX-11 already listed as owner calls | ✅ `docs/OWNER_TASKS.md:253`, `:274` |

One reference is **external to this repo**: `claude/nerva-jarvis-hub.md` (the public-repo exposure
note) is not in `jarvis-hub` — it lives in the digitaholic.ro workspace. Don't hunt for it here.
