# Session Reference — Cognition (Living Memory & Personality), Tools & Hardware

> **Date:** 2026-06-07 · **Branch:** `claude/open-source-tools-overview-Hx4hM` · **Owner:** Andrei
> **Status:** design + validated plan (no implementation yet) · **No PR opened this session.**
>
> Complete record of a single working session so nothing is lost. Companion artifacts:
> **`docs/COGNITION.md`** (the schematic & diagnostic map) and **`BACKLOG.md` → ORIZONT 21**
> (the tracked work). This doc is the *narrative + decisions + raw findings*; COGNITION.md is
> the *operational map*; the backlog is the *task list*. Read this to understand **why**.

---

## 0. Table of contents

1. Open-source tools evaluation (10 tools)
2. Hardware — image & video generation
3. Hermes Agent — five pillars & integration
4. Human-like memory & personality — first synthesis (4 expert lenses)
5. The ultracode version — multi-agent panel (frontier mechanisms)
6. Code verification — the real seams (file:line)
7. The refined plan v2 (phases, architecture, guardrails)
8. Unbounded & neuroplastic memory + brain analogies
9. Decisions, open questions, sources

---

## 1. Open-source tools evaluation

User asked about 10 tools as potential local-LLM "skills" for Jarvis, with the rule: **don't
overlap with what's already built if it adds no real gain.** Lens = the MOONSHOT principles
(local-first, opt-in cloud, inspectable). Verdict:

| Verdict | Tools | Why |
|---|---|---|
| ❌ **Already built — skip** | **ollama** (`OllamaBackend`, Howard), **whisper** (`voice/stt.py` faster-whisper + `/api/voice/stt`), **n8n** (`plugins/n8n.py` + docker-compose) | Re-adding = nothing |
| ⚠️ **Overlap — marginal** | **plausible** (vs GA4 `analytics.py`; only for privacy-first *product-site* analytics), **cal.com** (vs read-only Google Calendar; only if public booking pages needed), **appflowy** (vs Notion CRM; a local-first *replacement*, not new capability), **penpot** (design tool — **no fit, drop**) | Sidegrades, not gains |
| ✅ **Genuine gain — on-mission** | **bitwarden/vaultwarden** (secrets out of plaintext `.env` → self-hosted vault; aligns with HF-5 key hygiene + local-first), **yt-dlp** (composes with existing Whisper: download→transcribe→summarize a video/podcast) | Real new capability, low cost |
| 🟡 **New but off-mission** | **fooocus** (local image-gen — competes for VRAM, not in north-star; see §2 for the idle-time answer) | Parked |

**Recommendation:** do **vaultwarden** (best principle-alignment) and a **yt-dlp media skill**;
everything else is already built, a sidegrade, or off-mission. → BACKLOG H21.A / H21.B.

---

## 2. Hardware — image & video generation

**Machine:** laptop **RTX 5090 (mobile GB203, 24GB GDDR7, power-capped ~175W)** in a System76
Bonobo (Linux). *Note:* `NERVA.md` describes a Windows desktop w/ 192GB DDR5 + `TdrDelay=8`
(Windows-only) — **doc/hardware mismatch to reconcile** if the laptop is now the main box.

- **A laptop GPU can't be upgraded** (soldered, power-capped, thermally throttled, no PCIe slots).
- **Image generation = $0, runs on idle.** Key insight (user's): run it **when the LLM is
  unloaded**, so the diffusion model gets the full 24GB — no VRAM contention. Timings on the
  mobile 5090 with full VRAM: SDXL-Lightning ~1–3s; SDXL ~6–15s; Flux-schnell ~5–15s;
  **Flux-dev FP8 ~30–60s (best quality)**. Blackwell **FP4** can accelerate Flux further.
  Since it's an idle batch, **pick Flux-dev for quality — you never wait.** One-time ~1min
  LLM↔diffusion VRAM swap per batch, hidden during night-shift.
  → This is exactly the autonomy/night-shift pattern (queue request → idle dispatch →
  `LMStudioController` unload LLM → ComfyUI/diffusers generate → reload → deliver via brief/Telegram).
  → BACKLOG H21.C.
- **Video generation:** local serious video is a $5–10k upgrade for output worse than cloud,
  and a laptop is the wrong host. **Decision: manual via the user's Gemini/Veo account** ($0 API
  tokens — user pastes the prompt). Jarvis's role = a **prompt-builder** (local LLM drafts/refines
  the prompt for paste). → BACKLOG H21.D. *(If local video is ever required: a ~$2.8k LAN desktop
  node with a desktop 5090 32GB, or an eGPU — both parked.)*

---

## 3. Hermes Agent — five pillars & integration

Hermes ("the agent that grows with you", Nous Research) is already a skill *source* in
`SkillImporter.import_from_hermes`. Its five pillars:

| Pillar | Hermes | Jarvis status |
|---|---|---|
| **Memory** | Bounded always-injected `USER.md`/`MEMORY.md` + FTS5 session search + self-nudge to persist | ✅ deeper retrieval (vector+graph+RRF, H8 profile) — missing the *guaranteed bounded core* + self-nudge |
| **Skills** | `~/.hermes/skills/SKILL.md` (YAML), on-demand progressive disclosure | ✅ runtime exists (`SkillLoader`, marketplace, importer) |
| **Soul** | Personality/system-prompt | ✅ deeper — 16 `SOUL.md` |
| **Crons** | Scheduled self-tasks | ✅ deeper — heartbeat + autonomy + night-shift |
| **Self-improvement** | `skill_manage`: agent **writes its own skills** on success, **patches** on failure | 🔴 **THE GAP** — only a primitive `generate_skill`/`[learn:]` |

**Finding:** Jarvis already out-architects Hermes on 4/5 pillars. The one thing worth stealing is
exactly what the user liked — **autonomous, self-improving procedural skill-building** + the
**always-on curated memory core**. → curated core lands in Cognition **H21.3**; the self-writing
skill loop is now tracked separately in **ORIZONT 20 — Hermes Mining** (H20.5 skill self-improvement,
H20.4 self-evolution), which Cognition **H21.4** *feeds + governs* (KC/calibration/correction signals)
rather than duplicates.

> **Update (post-session, on `main`):** another session shipped **PR #166** — it **fixed BUG-13**
> (the broken `import_from_hermes` against the real `hermes-agent` SKILL.md / agentskills.io layout)
> and added **`ORIZONT 20 — Hermes Mining`** (net Hermes capabilities: tool-RPC `execute_code`,
> OpenRouter hot-swap, ContextCompressor, DSPy/GEPA self-evolution, skill self-improvement, sub-agent
> delegation) + `docs/research/2026-06-07-hermes-agent.md`. So the importer is no longer broken and the
> skill-self-writing "gap" is now a tracked horizon — Cognition (ORIZONT 21) is the complementary
> memory/personality/governance deepening, reusing the YAML-frontmatter parser BUG-13 introduced.

---

## 4. Human-like memory & personality — first synthesis (4 expert lenses)

The "writers' room" framing: psychology + education + personality + acting, each translated to
Jarvis mechanisms.

- **🧠 Cognitive science (memory):** typed stores (episodic/semantic/procedural/prospective/
  autobiographical); event segmentation; salience gating (emotion×self-reference×goal×surprise);
  elaborative encoding; gist/verbatim dual-trace; NREM/REM consolidation; adaptive forgetting
  (retrieval vs storage strength); reconsolidation; metamemory/provenance/calibration; replay;
  associative graph; working-memory executive + bounded always-on core.
- **🎓 Learning science (gets better over time):** spaced reinforcement; testing effect as
  verification; deliberate practice on weaknesses; knowledge tracing (user + self); ZPD
  scaffolding; interleaving/desirable difficulty; elaboration/self-explanation; progressive autonomy.
- **🎭 Personality psychology (consistent yet alive):** Big Five/**HEXACO** core (+facets);
  trait×state + **Fleeson density distributions**; **CAPS if-then signatures**; OCC appraisal→
  affect→mood→expression + regulation; values/super-objective; McAdams 3-layer narrative identity;
  attachment/secure-base; theory-of-mind user model; **slow maturation with identity anchor**;
  **anchor on Honesty-Humility, not Agreeableness**.
- **🎬 Acting craft (believable, continuous, audible):** super-objective/spine; Uta Hagen
  backstory bible; Meisner active-listening/subtext/"moment before"; **status transactions**;
  "yes-and"; **rehearsal (draft→self-critique→deliver)**; voice/prosody on XTTS; continuity =
  memory+personality persistence; "never break character" reconciled with honesty.

**Cross-cutting non-negotiable:** human-like ≠ deceptive. Believability is built **on** honesty.

---

## 5. The ultracode version — multi-agent panel (frontier mechanisms)

A real 4-agent panel (one per discipline) pushed each layer to the research frontier. The
**meta-finding:** four independently-prompted experts converged on the **same six seams** in the
codebase → this is *one cohesive subsystem*, not 35 bolt-ons.

**🧠 Memory (beyond the first pass):** predictive-coding **encoding gate** (store the surprise/
residual, not the event); formalized **Complementary Learning Systems** + interleaved generative
replay (no overwrite); **hippocampal-index → reconstruction** (regenerate from schemas; auto-update);
**pattern separation on write / completion on read**; **neuromodulator (DA/NE/ACh) tagging**;
**synaptic tag-and-capture**; **Temporal-Context-Model** recall ordering; **feeling-of-knowing**
metamemory (reliable "I don't know").

**🎓 Learning:** **dual Knowledge-Component tracing** (user + agent competence) → metacognitive
routing; **contrastive correction ledger** (the corrected→correct delta); **deliberate practice**
on weakest KCs (idle); **calibration-gated autonomy** (risk = f(mastery, calibration, blast-radius));
**preference-function meta-learning** (forbidden from moving correctness/honesty); **anti-skill-rot**
regression gating (monotone-by-construction).

**🎭 Personality:** **whole-trait density sampling** ({μ,σ,skew}, seeded/reproducible — mean is the
anchor, variance is the life); **mood attractor dynamics** (τ relaxation → continuity); **striving
engine** (living goals → agency); **dyadic relational self** (per-user adaptation on shared core);
**ensemble casting matrix** (ε-diversity assert); **anti-sycophancy judge** (the load-bearing loop
inversion); **identity-anchored drift + psychometric tripwire** (bounded, git-versioned, revertible).

**🎬 Acting:** typed **character-bible**; **Objective·Obstacle·Tactic** per reply; **status dial**;
**subtext + "moment-before" residue**; **idiolect** micro-consistency; **rehearsal stage** (reuses
`judge_fn`); **trait+affect → prosody**; **director-style synthesis** (preserve voices, not mush).

**The six convergence seams:** `QualityMonitor.judge_fn` (anti-sycophancy/honesty critic — 3 experts);
`DailyReflector` (consolidation + SRL + self-test — 3 experts); a new **affect module** (salience ⊕
personality ⊕ voice — 3 experts); the **autonomy risk gate** (calibration-driven); **`SOUL.md` → typed
schema**; **memory → generative/reconstructive** with provenance.

**Honesty keystone:** sycophancy is gradient descent on warmth → a prompt isn't enough. Wire an
anti-sycophancy critic into `QualityMonitor` that *lowers* score for agreement-without-grounds; make
Honesty-Humility a **frozen non-trait**; when persona conflicts with truth, persona yields.

**One conjunctive metric (can't be gamed — all must move together):** per-KC mastery↑ while
calibration-error↓; first-pass acceptance↑ **while gold-correctness holds** (else sycophancy alarm);
trait mean tracks μ with live variance **and** pushback-reversal ≤0.05 while warmth high; blind
ensemble-ID ≥80% **gated by** a truth-audit.

---

## 6. Code verification — the real seams (file:line)

Four verification agents read the actual code. Load-bearing findings (these reshaped the plan):

**Personality / agent / quality / voice**
- 🔴 **`SOUL.md` is read 100% verbatim** (`agent.py:44-52`) — **no front-matter parser**. The
  `personality:`/`bible:` block needs net-new parsing (split body from meta in `_load_soul`).
- 🟡 **Two prompt builders** — `Agent.process` (`agent.py:108`) **and** a streaming path in
  `orchestrator.py:1115` (already injects a `_runtime_state_block` at `:1114` — the precedent).
  Personality injection must patch **both**.
- 🔴 **`Agent` instances are shared across concurrent turns** → stateful affect/mood/relational
  **must not** be instance attributes (would race like `self._failures`). Persist keyed by session.
- 🟢 **`QualityMonitor` judge slot is real** (`quality.py:61`) but **unwired** (`orchestrator.py:252`
  passes no judge) **and runs inline on the hot path** (`:1306`) → judge must be deferred.
- 🟢 `synthesize()` says *"Do not mention internal agent IDs"* (`agent.py:193-197`) → discards
  specialist voice; attribution = one-string edit.
- 🟡 `tts.py` VOICE_MAP static, no prosody; edge/XTTS params unwired; **TTS caches by `hash(text)`**
  → prosody must fold into the cache key.
- settings split-brain: `get_value()` live vs `orchestrator.get_setting()` ≤30s stale.

**Memory** — *major: much is already shipped (H14.x)*
- ✅ **Reuse, don't reinvent:** `decay.py` (ACT-R retrieval strength, H14.4), `bitemporal.py`
  (provenance/valid-time, H14.1), `consolidation.py` (Mem0 ADD/UPDATE/DELETE/NOOP, H14.3),
  `entity.py` (freq/recency). Greenfield = salience/predictive gate, neuromodulator 3-vector,
  pattern-sep/completion, TCM re-rank.
- 🟢 `VectorRecord.metadata` is a free-form dict (`store.py:35`) → salience/provenance/temporal_context
  drop in with no migration (Qdrant flattens to payload but **drops `timestamp`** — store time in metadata).
- 🟡 **RRF is deliberately rank-only** (`fusion.py:38-71`) — TCM term can't go inside it; add a
  pre-ranked source or a post-fusion re-rank pass.
- 🟡 **`DailyReflector` is fragile:** idempotency is **in-memory only** (`reflection.py:46`, re-runs
  on restart); reads **only the current session** (`:85`); writes **graph-only**, `lessons` dropped.
  NREM/REM split must fix both + persist `_last_run`.
- 🔴 **H8 profile store is flat/global/single-tenant** (`store.py:201` `UNIQUE(category,key)`), no
  agent/user/mood dimension → per-(agent,user) core+delta+mood is a schema redesign touching 4
  consumers. **Resolution:** don't migrate it — put affect/relational/mastery in new locked keyed
  `JsonStore`s under `cognition/`.
- ⚠️ no DB-migration framework; mixed asyncio/threading locks; `MemoryManager._lock` serializes
  reads/writes → do scoring **before** the lock; hash-embedding fallback corrupts residuals → gate
  must detect fallback.

**Learning / autonomy / skills / eval**
- 🟢 Task `kind` is free-form + longest-prefix executor → new kinds (`skill_draft`, `consolidate_*`,
  `reinforce`, `practice`) slot in; **pass explicit `risk_tier`**. Night-shift already wired
  (`is_night_window` + `tick(max_tier=1)`).
- 🟢 **Regression-gating exists:** `DatasetStore.compare()` returns a `regression` bool; versioned datasets.
- 🟡 Risk gate already factor-driven (`policy._apply_scoring`) → tier=f(mastery, calibration) is a
  clean extension once those are computed (measured nowhere today).
- 🔴 **`generate_skill` is a template stub** (no codegen, no sandbox, no gate, no versioning; execs
  **inline, bypassing the gate**). Hermes loop's middle is greenfield; auto-revert is Red (no versioning).
- ⚠️ Learning store is per-agent **JSONL** (no KC, no calibration) → new `memory_logs/learning/kc.db`.
  HF-6 host-exec confirmed (skill tester must force Docker). **BUG-11 partial** (money-edits re-gate;
  tier-escalating non-money edits don't → call `policy.decide()` on edited payload). **BUG-10**
  appears **fixed in source** (`orchestrator.py:563`) but stale in backlog.

**Architecture & long-term quality**
- One `Orchestrator` singleton; per-request state lives as mutable instance attrs → **BUG-5**
  (`session_id` save/restore on shared instance, `orchestrator.py:871-876`). The new subsystem's
  `TurnContext` **fixes BUG-5** as a side effect.
- CLN-2 (orchestrator god-object, 1826 LOC) + CLN-3 (web.py ~3981 LOC) → **don't grow them**.
  Use the existing `ComponentRegistry` to register **one** `cognition` facade; new routes as an
  `APIRouter`, never appended to `web.py`.
- Settings live-reload + per-behavior kill-switches confirmed; idle jobs hang off `_autonomy_loop`
  (night-windowed, tier-capped) or APScheduler; offline test conventions (asyncio_mode=auto,
  sys.path pattern, fake backends, `Orchestrator.__new__`/`_bare_orchestrator`, `make_app`).

---

## 7. The refined plan v2

**Architectural spine (the long-term-quality decision):** one `agents/core/cognition/` package
(`facade.py` + `affect/ personality/ relational/ mastery/ residue/ judge/ jobs/`), registered as a
single component; **per-request `TurnContext`** for transient state (fixes BUG-5); **locked keyed
`JsonStore`s** for durable signals; **master-off = true no-op**; heavy work deferred to idle;
deterministic-default + optional injected LLM; HTTP via a dedicated `APIRouter`.

**Phases (= BACKLOG H21.0–H21.5):**
0. **Scaffold + BUG-5 fix** (ships no behavior change).
1. **Honesty keystone** — anti-sycophancy/persona judge (deferred) + synthesize attribution. *(start here)*
2. **Affect + personality expression** — SOUL front-matter parser; mood attractor + whole-trait
   sampler; inject into both prompt builders; O·O·T + status; prosody (fold affect into cache key).
3. **Living, unbounded memory** — reuse H14 + greenfield gate/3-vector/pattern-sep/TCM; NREM/REM
   split (durable, multi-session); replay/tag-capture/SHY/maintenance/re-projection; tiers; bounded core.
4. **Learning & governed self-improvement** — kc.db (dual KC + calibration); correction ledger;
   calibration-gated autonomy; practice/reinforce kinds; self-writing skill loop (codegen→Docker
   sandbox→regression gate→policy→versioned discover→auto-revert; fix BUG-11, force Docker/HF-6).
5. **Ensemble & maturation** — casting matrix + ε-assert; director synthesis; identity-anchored drift
   + psychometric tripwire (human-gated, reversible); relational delta.

**Start-here slice:** Phase 0 + 1 (lowest risk, no new state, fixes BUG-5, lands the honesty keystone).

**10 quality guardrails:** (1) no per-turn state as instance attrs; (2) orchestrator touches only the
facade; (3) no new `web.py` routes; (4) every behavior gated default-OFF under one `cognition`
category, master-resolved; (5) hot path cheap, all heavy/LLM work deferred; (6) durable state via
locked `JsonStore`, one store per concept, avoid SQLite sprawl; (7) idle jobs gated-inside +
try/except→warn + `to_thread` + honor `JARVIS_TESTING`; (8) deterministic-default + optional LLM;
(9) drift/self-mod reversible + human-gated; (10) one offline `tests/test_cognition_*.py` per module.

---

## 8. Unbounded & neuroplastic memory + brain analogies

User's emphasis (the most important feature): **memory/files are NOT limited; valuable over time;
think like a human brain with as many analogies as possible; don't limit it.** Reconciliation:

- **Unbounded & append-only** — the brain doesn't *delete*; forgetting = reduced **accessibility**
  (retrieval strength) + **tier demotion** (hot→warm→cold), **reversible** (a cue reactivates a cold
  memory). The **only** true erase is the user's explicit *forget*.
- **Forever-valuable** — value compounds via consolidation (episodes→schemas) + **synaptic-homeostasis
  renormalization** (nightly downscaling keeps signal-to-noise high at any size).
- **Future-proof = neuroplasticity** — each trace records its **embedding-model version**; a nightly
  **re-projection** job upgrades old memories to newer models (cortical remapping); working memory is
  **context-window-elastic**; backends are pluggable. No hard caps — limits are generous settings.

**Full schematic with ~35 brain analogies, tier/data-flow diagrams, component reference, and a
symptom→cause→remedy troubleshooting playbook → `docs/COGNITION.md`** (the diagnostic source of truth).

---

## 9. Decisions, open questions, sources

**Decisions made this session**
- Do **vaultwarden** + **yt-dlp media skill**; skip the already-built/sidegrade/off-mission tools.
- Image-gen = local, $0, **idle-batched** (Flux-dev); video = **manual Gemini/Veo**, Jarvis builds the prompt.
- Steal from Hermes: **self-writing skills** + **always-on curated core**.
- Build the cognition subsystem as **one `cognition/` facade** reusing H14 memory + autonomy/eval; honesty load-bearing.
- **Memory is unbounded/append-only** (forgetting = accessibility, not deletion) and **neuroplastic** (re-embed on better models).
- **ORIZONT 21** is the cognition horizon — ORIZONT 19 = **WorldView (4D OSINT)** and ORIZONT 20 = **Hermes Mining**, both claimed by other sessions (18 = native apps). Cognition was renumbered 19→20→21 and placed next to Hermes, de-duplicated against it.

**Open questions / to reconcile**
- `NERVA.md` hardware section (Windows desktop / 192GB) vs the actual Bonobo laptop — doc-truth pass needed.
- Confirm BUG-10's cron is actually called at startup; BUG-11 tier-escalation re-gate; HF-6 force-Docker — prerequisites for H21.4 / the Hermes skill loop it governs (H20.5).
- Resolved: ORIZONT 19 = WorldView, ORIZONT 20 = Hermes Mining; Cognition merged in as ORIZONT 21, de-duplicated against Hermes (H21.4 feeds/governs H20.5/H20.4 instead of re-implementing the skill loop).

**Sources (AI-implementation grounding; human-science = established theory)**
- Generative Agents (Park et al., Stanford) · MemGPT/Letta · A-MEM (Zettelkasten) · TiMem ·
  "Hindsight 20/20" · CLS / pattern separation · predictive-coding & memory · Temporal Context Model
  (Howard & Kahana) · TRAIT / PersonaLLM / psychometrics-for-LLMs · Hermes Agent (Nous Research).
