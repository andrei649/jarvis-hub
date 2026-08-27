# Jarvis Hub — Backlog Multi-Agent

> Owner: Andrei · Planificat: 2026-05-30 · Echipă: agenți Claude + opencode
> HUD: http://127.0.0.1:8080/ · Admin: /admin

> **North Star (vision, principles, phase gates):** [MOONSHOT.md](MOONSHOT.md) — re-rank this backlog against it
> **Go-Live Plan (features, roadmap, marketing brief):** [GO_LIVE_PLAN.md](GO_LIVE_PLAN.md)
> **Delivery History (H1–H8 completed sprints):** [docs/HISTORY.md](docs/HISTORY.md)
> **Hermes migration v3 plan (reviewed by Fable 2026-07-07 — APPROVED with notes):** [docs/research/2026-07-06-hermes-agent-migration-plan.md](docs/research/2026-07-06-hermes-agent-migration-plan.md) · review verdict + remaining-phase order in [docs/handoff-fable-2026-07-07.md](docs/handoff-fable-2026-07-07.md) §5
> **Last-day Fable handoff (2026-07-07 — ordered owner/AI task lanes, risk register):** [docs/handoff-fable-2026-07-07.md](docs/handoff-fable-2026-07-07.md)
> **Pre-go-live stakeholder sync (2026-07-07 — 5-seat agent panel, conditional GO, Gate-2 checklist):** [docs/meetings/2026-07-07-pre-go-live-sync.md](docs/meetings/2026-07-07-pre-go-live-sync.md)
> **Nerva product & capability vision (the 1.0 gate expanded 2026-07-11; visions merged 2026-07-12):** [NERVA_VISION.md](NERVA_VISION.md) — brand architecture (Cortex/Atlas/Synapse/Vision/Ultron), six pillars, capability registry, the Hermes superiority bar; horizons ORIZONT 27–33 (= Nerva Programs A–G) below · provenance: [docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md](docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md)


<!-- P0:PUBLIC-DEMO-DIGITAHOLIC:START -->
## 🔴 P0 — Owner decision + spec: public web demo instance for digitaholic.ro (H23.23-adjacent)

> **Priority: HIGH · Status: spec awaiting owner review; the one core code gap is CLOSED.**
> The `NERVA_PUBLIC_PROFILE` seed gate is delivered (see below). Deployment, roster overlay and the
> four owner calls remain open — nothing is deployed and no public box exists.
> Full spec: [`docs/decisions/2026-08-24-public-web-demo-digitaholic.md`](docs/decisions/2026-08-24-public-web-demo-digitaholic.md)
> Authored 2026-08-24 by a Claude (Cowork) session working on digitaholic.ro, against `main` @ `75e9281`.

**Goal.** A real, functional Nerva instance embedded in a digitaholic.ro page (not the scripted
`/nerva-ai-os/` Action Kernel demo), on a free cloud model, auto-updated from `main`, with personal
data stripped and each visitor getting their own "save-game slot" of personalization.

**The key call it already makes:** don't build per-user partitioning into the shared memory
subsystem — that is still H23.23 **option B**, still deferred, still large. Map "save" onto the unit
the architecture already endorses: **one disposable install per visitor session**, whose
`$JARVIS_HOME` data root *is* the folder Andrei is picturing. Smaller, consistent with the recorded
H23.23 decision, and it touches none of the deferred work.

**Reuse as-is (config, not engineering):** CDX-12 hardened profile (`JARVIS_HARDENED=1`) · CDX-11
plugin least-privilege (grant nothing) · in-memory graph + vector fallbacks (no Neo4j, no Qdrant) ·
existing OpenAI-compatible cloud routing in `hybrid_router.py` + the `cloud_llm_agents` allowlist.

**The one real code gap — ✅ CLOSED:** `agents/core/memory/seed_graph.py` `SEED_FACTS` hardcodes
Andrei/Alexandra/Max/Raiffeisen/Cosmina de Sus/BMW E93 and `MemoryManager.__init__` seeded them
**unconditionally** into an empty graph. `seed_graph()` now self-gates on `NERVA_PUBLIC_PROFILE`
and returns 0 without touching the graph when it is on. The gate sits **inside `seed_graph()`**,
not at the single `MemoryManager.__init__` call site the spec named, so no present or future caller
can re-open the exposure. Default (flag unset) is byte-identical to before — the owner's private
install still seeds. Evidence: `tests/test_public_profile_seed_gate.py` (+8, red-proven first).
**Residual, pinned not fixed:** the flag reads through the shared AUD-14 `env_flag()` parse, whose
declared rule resolves unrecognized spellings to the flag's default — so a *typo*
(`NERVA_PUBLIC_PROFILE=pubic`) deploys a public box that seeds the owner's family. A test pins this
so it is visible rather than silent; closing it needs a boot guard that refuses to start on a
set-but-unparseable value, which is a separate change with its own owner call.

Everything else in v1 is configuration. Secondary gaps: an explicit `agents.public.yaml` roster overlay (smallest roster
that demos the loop, not all 18), and session-scoped tokens only — **no durable cross-visit save**
(that would make Digitaholic a GDPR data controller for a stranger's personal data; a deliberate v2
call with a retention/deletion policy, never a default).

**Suggested risk tier:** R2 (new deployment surface + one env-gated code path; no auth-identity model
change, no kernel change) — classify properly against `.github/ai-development-policy.json` before
opening a branch, don't trust the draft's read.

**Blocked on four owner calls** (see [`docs/OWNER_TASKS.md`](docs/OWNER_TASKS.md)): ratify H23.23 (A)
— or note that this spec uses the install-per-user shape it already recommends and so doesn't block
either way · turn on CDX-12 hardened + fix `JARVIS_PLUGIN_GRANTS` for this box (`OWNER_TASKS.md:253`,
`:274`) · pick the free LLM provider/key · pick the container host.

**Rollback:** separate deployment surface; stop routing the page at it / redeploy the previous image.
Blast radius to the real personal install is zero by construction — as long as the public box is
never pointed at the real data root or the real plugin grants.
<!-- P0:PUBLIC-DEMO-DIGITAHOLIC:END -->

<!-- NERVA2:E0-REPOSITORY-LEDGER:START -->
## Nerva 2.0 program control — E0 DONE

> Canonical program: [#757](https://github.com/andrei649/jarvis-hub/issues/757) · E0 epic:
> [#758](https://github.com/andrei649/jarvis-hub/issues/758) · blocker plan:
> [#778](https://github.com/andrei649/jarvis-hub/issues/778) · machine-readable completion ledger:
> [`docs/nerva2/E0_COMPLETION.json`](docs/nerva2/E0_COMPLETION.json).

- Accepted E0 evidence is complete through #789: baseline, ownership, dependencies, authority,
  risks, ORIZONT mapping, issue ledgers and repository ledgers were independently reviewed.
- E0 is **DONE** with `close_e0=true`. This closes the baseline/control gate only; it does not claim
  that Cortex, Atlas, Episodes, Synapse SDK or Research Lab runtime capabilities are implemented.
- #780 (Cortex), #781 (Atlas), #783 (Synapse) and #784 (Research Lab) are no longer blocked by E0 and
  may proceed as separate bounded slices. #782 (Episodes) still waits for the minimum Atlas slice #781.
- Ultron / `nerva.action.v1` remains the sole privileged-action authority. Cortex is shadow/no-action,
  Atlas is read-only to consumers, Episodes is memory-record-only, Synapse is description-only and
  Research Lab is evaluation-only in the first wave.
- Historical ORIZONT delivery remains intact. Broader program-manifest work, Continuity Core mapping,
  live task-level mediation, real adapters, Night Shift prerequisites and release proof remain open.
<!-- NERVA2:E0-REPOSITORY-LEDGER:END -->

**Accepted M1 slices and bounded program controls since E0** (each independently reviewed and
squash-merged once present on `main`; no item by itself completes a runtime epic or release gate):

- ✅ E1.0 / #780 / PR #791 — typed shadow `nerva.decision.v1` and `ShadowDecisionRouter`.
- ✅ E1.1 / #792 — bounded current-router comparison over `nerva.cortex.comparison.v1`.
- ✅ E1.2a / #841 / PR #842 — merged onto `main` as commit `769b633`
  (2026-08-07); the owner-local measured primary-route contract is
  `contract_ready`, but remains `owner_evidence_blocked` pending the five
  E1.2b owner inputs, with `real_task_outcome_quality=not_measured`. This
  does not complete E1, B2 live enforcement, the program, or release
  readiness.
- ✅ E2.0 / #781 — Atlas identity/provenance and read-only snapshot.
- ✅ E3.0 / #782 / PR #796 — `nerva.episode.v1` schema, lifecycle and manual boundary.
- ✅ E3.1 / #798 / PR #799 — longitudinal Episode retrieval comparison, evaluation-only.
- ✅ E8.0 / #783 / PR #797 — Synapse manifest conformance, description-only.
- ✅ E8.1a / #804 / PR #819 — read-only Hermes upstream discovery and compatibility map,
  pinned to source tag `v2026.8.3` / commit `3c27eb6`. No dependency, provider contract,
  adapter, execution or authority change. Merged as `a6e85854`; E8.1 remains `BUILDING`.
- ✅ E8.1a exact-fetch integrity / #830 / PR #834 — Hermes imports pin the signed
  annotated `v2026.8.3` tag, unsigned commit `3c27eb6`, exact tree and all 71
  allowlisted `SKILL.md` byte digests; exact-commit fetches verify URL, digest
  and frontmatter before mutation. No manifest enrolment, provider contract,
  adapter, execution or authority change; E8.1 remains `BUILDING`.
- ✅ E8.1b / #835 / PR #838 — strict, versioned `nerva.execution-provider.v1`
  descriptor/request/result/health value types bind exact provider revision and
  fingerprints, deep-freeze bounded JSON, and fail closed across sandbox,
  filesystem, network, secret-reference, budget and lifecycle policy. Provider-local
  results remain `unverified`; all authority fields are immutable false and external
  verification is mandatory. The protocol is inert: no Hermes dependency, manifest
  enrolment, adapter, registry, route, execution or kernel integration is added.
  E8.1 remains `BUILDING`; E8.1c and provider-specific E9 evidence remain separate.
- ✅ E8.1c / #844 / PR #845 — static Hermes invocation and supply-chain preflight,
  pinned to tag `v2026.8.3`, commit `3c27eb6`, tree `b217767` and OCI index digest
  `sha256:16788311e2fa3035456bdc1bafb8ec2b1777db64ebf020af9bb7eb73c3712c9e`.
  The accepted scope is `preflight_evidence_only`: no image or package artifact was
  pulled, installed, imported or executed; the OCI/one-shot candidate remains
  unexecuted; compatibility and provider-specific E9 remain unmeasured; license
  closure, SBOM/provenance and observed CVEs remain later gates.
  No dependency, third-party-manifest enrolment, adapter, provider, route, credential,
  runtime or authority change is added. E8.1 and E8 remain `BUILDING`; #804, B7/#818
  and provider evidence #767 remain open, and release readiness remains false.
- ✅ E8.1d / #824 / PR #827 — fail-closed manual-only third-party updater policy;
  `auto_update: false` stays drift-visible and is denied by scheduler and direct updater.
  No Hermes enrolment, provider or authority change; E8.1 remains `BUILDING`.
- ✅ E9.0 / #784 / PR #803 — versioned `nerva.benchmark.v1` contract and task suite.
- ✅ E9.1 / #807 / PR #809 — scheduled current-router shadow comparison and
  `nerva.benchmark.report.v1` regression report, `evaluation_only`. Runs through the existing
  Eval Nightly lane on synthetic-public fixtures; reports, never routes. Merged as `f59191c`;
  docs in [`docs/nerva2/RESEARCH_LAB_E9_1.md`](docs/nerva2/RESEARCH_LAB_E9_1.md).
- ✅ E6.0 / #806 / PR #808 — evidence-bound `OutcomeObservation` / `nerva.lesson.v1`
  proposal contract, `proposal_only`. Reflection may propose a lesson; destinations own
  promotion. Merged as `df0d529`; docs in [`docs/nerva2/REFLECTION_E6_0.md`](docs/nerva2/REFLECTION_E6_0.md).
- ✅ E6.0 integrity correction / #820 / PR #823 — every lesson lifecycle sink revalidates
  canonical observations before producing audit or advanced state; a correctly re-hashed forged
  proposal is rejected at `accepted_by_destination`. E6 remains `BUILDING`.
- ✅ E6.1 / #817 / PR #832 — synthetic-public held-out lesson-proposal evaluation reuses the
  accepted E9.0 store/harness with immutable fixture splits, equal candidate/baseline budgets,
  explicit false/hallucinated-recall metrics and strict retained-evidence preflight. Reports remain
  `evaluation_only`; no lesson promotion, memory write, routing, execution or completion authority
  is added. E6 remains `BUILDING`, and owner-live benefit is still unproven.
- 🟡 E1/E6/E9 authority-ceiling successors from closed #854 — the E1 measured report (#859), E6
  observation/proposal/evaluation payloads (#860), and E9 regression report (#861) landed before
  their required #856 Step-2 predecessor was accepted. That predecessor is now satisfied by #913,
  but its later acceptance does not retroactively validate those merge procedures. The original
  #859 merge remains historically invalid; its missing E1 hostile-proof evidence was separately
  accepted in #865 and that E1 side gate is closed. The retained E6 (#860), E9 (#861), and separate
  E9 totals-validation (#864) bytes still await their own fresh post-B2 acceptance decisions. The
  #866 coordination-only history cleanup was separately accepted and grants no functional
  acceptance. Serialization still
  hard-codes `evaluation_only`/`proposal_only` and `can_* = false`; no authority, routing, execution
  or promotion changed, B2 remains `PARTIAL` beyond Step 2, and the epics stay `BUILDING`.
- 🟡 Landed-not-yet-accepted governance wave (2026-08-14…16) — SEC-B8 external-skill approval
  hardening (#911, merged `790a725`) and the external exact-head acceptance-state core (#916,
  merged `519dca0`) are on `main` with terminal-green exact-head CI, but **each carries a recorded
  post-merge integration HOLD**: #911 merged with zero independent review submissions ("must not
  be treated as governance-complete or as satisfying #905/#906"), and #916's reviewer verdict was
  only "GO — no content blockers", not the required R3 PASS. Both await a durable post-merge
  attestation plus an owner retain/revert decision. The B7 candidate/corrective pair #912/#918 is
  tracked in the B7 paragraph below. No authority was added; release readiness remains false.
- ✅ Innovation Lab control v1 / #805 / PRs #831 and #837 — versioned RFC and Knowledge Garden
  contracts, fail-closed lifecycle/lineage validation, immutable retained evidence and the
  documented no-delivery-authority boundary. The governed synthetic-public examples complete
  acceptance items 7–9: Alpha reaches `ACCEPTED_FOR_EPIC` only through the separate, proposed and
  unscheduled #836, while Beta retains an evidence-backed `REJECTED` decision. Together the two
  control-only packages satisfy all ten #805 acceptance items. No runtime, provider, routing,
  deployment, privileged action, automatic promotion, prototype outcome or owner-live capability
  is added; #836 remains open and grants no implementation authority.
- ✅ B2 repository-manifest control / #839 / PR #840 — effective only when this PR is
  squash-merged after exact-head hosted gates, versioned JSON becomes the sole current
  dependency/status/gate/blocker/runtime truth for E0–E12; its Markdown view is deterministic and
  byte-checked, and the offline checker fails closed on hostile structure, mutable-only evidence,
  unsafe repository paths, Git/index/worktree drift and candidate-HEAD movement. This closes only
  the repository-manifest portion of B2: parent #778 and program #757 remain open/partial; live
  issue-ledger reconciliation, B7, E8.1c, provider-specific E9 proof, Night Shift, owner-live and
  release gates remain separate. No runtime, route, provider, execution, action or completion
  authority is added; Ultron remains the sole privileged-action authority and release readiness
  remains false.

**Innovation Lab precursor documents** (merged, but **not** epic slices — neither satisfies a
#805 checkbox and neither promotes, adopts or adds an integration/dependency pin):

- ✅ Integration catalogue RFC / #805-adjacent / PR #821 — survey of external open-source
  candidates Nerva could wire in, in
  [`docs/nerva2/INTEGRATION_CATALOGUE_RFC.md`](docs/nerva2/INTEGRATION_CATALOGUE_RFC.md).
  Merged as `ccc36e8`. Explicitly a *precursor catalogue*: it does not implement the #805 control
  slice (RFC template, status transitions, Knowledge Garden links, integrity check), and its
  acceptance satisfies no #805 checkbox. Every row carries a #805-canonical status — all `PARKED`
  except one durable `REJECTED` (external agent framework as Nerva's brain) resting on in-repo
  primary evidence. The accepted catalogue already distinguishes Playwright as an in-repository
  fact, queues official-but-unread artifacts as primary follow-up, makes its six adoption gates
  additive to the #805 minimum contract, and records #819 as accepted at `a6e8585`. #805 itself
  therefore stays open.
- ✅ MCP Registry evidence correction / #825 / PR #826 — merged as `72dca7e`. Replaces the
  catalogue's categorical "not designed for self-hosting" claim with a recorded primary read of
  the upstream README blob `33ce337` at commit `0b5cc0f`, which documents a local PostgreSQL dev
  path, offline seeding and pre-built GHCR images. Local runnability is **not** adoption
  readiness; the row stays `PARKED`. PR #826 changed only this MCP Registry evidence path. No
  dependency, manifest, updater, provider, routing or authority change entered either PR.

The catalogue's own §5 recommendation stands and is not yet scheduled: take **one** Tier A
candidate through a complete adoption-grade primary-source pass plus the additive §4 gates before
touching a second. E8.1d / #824 / PR #827 resolved the no-opt-out part of the auto-update hazard:
every source declares a literal boolean `auto_update`, while `false` remains drift-visible and is
denied by both the scheduler and direct updater before mutation. Broad version-token replacement
remains a reviewed risk for explicitly auto-enabled non-vendored entries with an `update_doc`.
A short pin record, dual GitHub/PyPI drift, exact revision/content integrity, adapter compatibility,
supply-chain and E9 gates still precede Hermes enrolment or promotion.

E1, E6 and E9 remain `BUILDING` — E9.1 proves scheduled reporting only, not routing
superiority or Research Lab completion. Its residual limits are recorded in the slice doc:
four synthetic cases may overfit, shared-runner latency is deliberately unmeasured, and the
module-private construction guards are boundaries, not cryptographic capabilities.

E1 and E6 remain `BUILDING`. E5 Night Shift stays blocked: it needs sufficient E1/E2/E3/E6
behavior **plus** the B7 task-level Ultron mediation evidence. B7 status per the #757/#778
work-claim ledger: discovery child [#818](https://github.com/andrei649/jarvis-hub/issues/818)
is open and reserved to the Ultron Security Architect on `nerva2/b7-task-mediation-evidence`.
The six owner decisions are resolved. PR #912 landed the bounded default-off candidate, but it
was merged after its final exact-head R3 verdict remained **BLOCK**: intentionally-direct work
could bypass a degraded global mediation head, and the dispatch permit did not revalidate the
complete persisted execution tuple. Corrective PR #918 closed those authority seams plus the
adjacent raw-executor, refusal-accounting, post-guard mutation and hostile-copy paths, and its
technical R3 gates completed on exact head `6eed5a7`: terminal-green hosted Linux/Windows CI and
a fresh distinct R3 **PASS / approved-for-integration** attestation
([comment 5313004564](https://github.com/andrei649/jarvis-hub/pull/918#issuecomment-5313004564)).
It was then merged as `b5e52c6` (2026-08-17) while the integrator's owner/policy-gate **HOLD**
still stood: #818 remains `owner_hold`, live #906 integration authority remains open, and
#757/#778/#818 were not reconciled to #918 before merge. The recorded post-merge verdict is
**merged but not program-accepted** — the owner must either record a bounded retain/exception
decision and reconcile the ledgers, or authorize a corrective revert/successor. B7 therefore
remains not accepted and E5/E8 stay blocked.

B3 / Continuity Core (#731) mapping — all six #778 unblock items now have an explicit
destination, prior-art citation where accepted evidence exists (including `RISKS.md`'s
prior `MEM-03`/`SEC-05` ownership of the memory-taint check), and an honestly recorded
gap where it doesn't, in
[`docs/nerva2/CONTINUITY_CORE_RECONCILIATION.md`](docs/nerva2/CONTINUITY_CORE_RECONCILIATION.md).
No epic gained a typed contract or acceptance test from this document; #731 stays open
per its own bar ("close it only after every requirement has a destination and
acceptance test") not yet being met. The clearest open gap is Jarvis's own Identity
Manifest, which has no destination issue — #762/E4 is scoped to Howard's preference
prediction only, not Jarvis's continuity identity.

**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**

## Run

```bash
pip install -r requirements-beta.txt
python serve.py   # canonical entry (boot guards + graceful shutdown; O26-P0.6: the raw
#   uvicorn entry `python -m uvicorn agents.web:app` now runs the same guards via the lifespan)
python scripts/install_smoke.py --json  # fast install smoke: boot + /readyz + fake local turn
python -m pytest tests/ -v          # ~6,849 backend collected (+521 frontend vitest, +96 mobile jest;
#   counters generated into project-status.json via scripts/status_sync.py)
```

> Singurul skip rămas e heartbeat-ul opțional. (Vechiul `tests/test_spotify.py` cu 8 skip-uri a
> fost eliminat în CLN-1; Spotify (H2.5) **funcționează** via `skills/spotify/main.py`, acoperit
> de `tests/test_spotify_skill.py`.)

**Rulare autonomă (10h):** coada aprobată + protocolul complet + promptul de shift sunt în
[`docs/superpowers/plans/2026-08-01-finish-line-plan.md`](docs/superpowers/plans/2026-08-01-finish-line-plan.md)
— A8-unblockers întâi (trigger achiziție · seam MediaDriver · presence→media · Q1 stream-synthesis);
statusul per item se ține în tabelul §3 al planului, nu aici.

**După modificări JS/CSS:** Ctrl+F5 în browser (cache bust).
**După modificări Python:** repornire server (Ctrl+C, re-execută comanda uvicorn).
**Server curent** (dacă e pornit): PID vezi `netstat -ano | findstr ":8080 "`.
**Stack:** Python 3.12 + FastAPI + vanilla React (createElement, no JSX).

> **Recent hardening (2026-07-05):** #549 closes the H17.1a inbound-origin
> bypass noted in the frontier audit: `handle_input` and `handle_input_stream`
> now bind turn origin by construction, internal orchestrator channels stay
> trusted, an upstream inbound context cannot be downgraded, and plugin-egress
> actions carry the current origin instead of hard-coding `generated`.
> #550 continued 0.45 Batch B1: skill marketplace/generation and
> host-control seams now evaluate live reusable contracts before package,
> promotion, restart, or LM Studio subprocess control. #551 moves
> Safe Comms from preview to transport v0: telegram/web inbound threads persist,
> governed replies enter the approval funnel, and approved replies send through
> the live channel manager. #552 fixes the eval-nightly workflow parser by
> moving cache hash expressions out of job-level `env`. #553 wires H21.3
> metadata into live recall ordering and adds
> `/api/memory/eval/run?mode=recall` as a real-path eval smoke. #554 persists
> DailyReflector run idempotency and hands distilled lessons to LivingMemory
> when cognition memory is enabled. #555 injects bounded LivingMemory core
> facts into the shared prompt path. #556 makes `LivingMemory.core` survive
> process restarts. #557 makes LivingMemory tier metadata durable too. #558
> closes the matching AUD-2 privacy gap: explicit user-forget now clears those
> cognition stores live and at rest. #559 wires the default-off re-projection
> maintenance hook. #560 passes the existing local memory embedder into
> that hook so old tier records can be upgraded during maintenance. #561
> reactivates matched LivingMemory recall hits, refreshing both tier activation
> and the H14 decay access ledger. #562 rejects exact duplicate LivingMemory
> turn digests before they create another tier/decay record. #578 gates
> Oracle's external commit pull/test loop behind a live
> repo-sync contract plus the Action Kernel, default-refuses when the kernel is
> off, and removes shell execution from MCP stdio startup while gating outbound
> MCP tool calls through a live contract. R2 is merged in #580: inbound taint
> now has kernel-independent teeth at the autonomy queue, edited inbound tasks
> are re-marked before policy re-evaluation, and inbound memory embeddings stay
> visibly tainted through recall provenance. R3-B2 is merged in #582: live
> contract gates to external KG writes and destructive forget purge before state
> mutation. R3-B3 is merged in #584: inbound A2A task intake and autonomy
> escalation fan-out now have contract-denial teeth before inbox writes or
> channel sends. R3-B4 is merged in #586: mutating MCP route tools now have a
> reusable contract gate after identity and before kernel mediation or adapter
> writes; full PR CI was green before merge. R3-B5 is merged in #588: the
> generic ChannelManager send boundary has a shape-only contract gate before
> adapter I/O; full PR CI was green before merge. TASK-3 channel-ingress
> taint is merged in #590: the gateway marks untrusted inbound channel messages
> with private taint metadata, persists only public taint fields in the Safe
> Comms inbox, and strips private metadata before outbound adapter sends; full
> PR CI was green before merge. AUD-14 channel send-rate env-int is merged in
> #592: the global `JARVIS_CHANNEL_SEND_RATE` cap now uses shared `env_int()`
> parsing with malformed/negative values pinned as unlimited; full PR CI was
> green before merge. M3.5/#169 WorldView MCP write transport is merged in
> #594: Argus can reach `watch_aoi` and `reconstruct_event` only through
> plugin-gate + Action Kernel + scoped HMAC MCP token; full PR CI was green
> before merge. AUD-14 LLM model-name config is merged in #596: LLM
> model-name defaults and the `JARVIS_DEEP_MODEL` override now live in one
> shared config module. AUD-14 task-budget env-float is merged in #598:
> `JARVIS_TASK_MAX_SECONDS` now uses shared `env_float(..., minimum=0.0)`
> instead of local try/except parsing. AUD-14 analytics max-events env-int is
> merged in #600: malformed `JARVIS_ANALYTICS_MAX_EVENTS` no longer crashes
> analytics import. AUD-14 STT beam-size env-int is merged in #602:
> `JARVIS_STT_BEAM_SIZE` now uses shared `env_int(..., minimum=1)` parsing.
> AUD-14 log rotation env-int is merged in #604: `JARVIS_LOG_MAX_MB` and
> `JARVIS_LOG_BACKUPS` now use shared `env_int()` parsing while keeping
> settings-DB fallback intact. AUD-14 call-config env-json is merged in #606:
> `JARVIS_CALL_CONFIG` now uses shared `env_json_object()` parsing. AUD-14
> channel-rates env-map is merged in #608: `JARVIS_CHANNEL_SEND_RATES` now
> uses shared `env_int_map()` parsing. AUD-14 email-port env-int is merged in
> #610: `SMTP_PORT` and `IMAP_PORT` now use shared `env_int()` parsing.
> AUD-14 vector-dimension env-int is merged in #612: `VECTOR_DIMENSION` now
> uses shared `env_int(..., minimum=1)` parsing. AUD-14 skill-history env-flag
> is merged in #614: `JARVIS_SKILL_HISTORY` now uses shared `env_flag()`
> parsing. AUD-14 webhook-channels env-json is merged in #616:
> `JARVIS_WEBHOOK_CHANNELS` now uses shared `env_json_object()` parsing.
> AUD-14 CORS-origins env-list is merged in #618: `JARVIS_CORS_ORIGINS` now
> uses shared `env_list()` parsing. AUD-14 plugin-grants env-list is merged in
> #620: `JARVIS_PLUGIN_GRANTS` now uses shared `env_list()` parsing. AUD-14
> trust env-flags is merged in #622: trust-status mic/strict-local env reads
> now use shared `env_flag()` parsing. Visual-artifact lane wave 1 is merged in
> #652: the cockpit gains an Artifacts tab over the unchanged `/api/canvas*`
> surface (safe typed rendering, consent-gated remote images, pin/unpin/delete)
> plus an explicit save-response control (markdown contract, visible 4,000-char
> truncation, never auto); `_safe_url` now rejects protocol-relative and
> control-char URLs, `_s()` drops lone UTF-16 surrogates (store-poisoning fix),
> and forget-me resets `canvas.json` + clears the live canvas store without
> emptying the file before the pre-forget backup. Mobile parity is tracked as
> H18.20 (ORIZONT 18). Self-Improvement (ad-hoc, owner request 2026-07-18) adds
> the missing *proactive* half next to the reactive H32 Capability Acquisition
> loop: `agents/core/autonomy/tech_scout.py` is a default-off, weekly, read-only
> websearch scan that dedupes findings and files them as `RiskTier.READ_ONLY`
> informational autonomy tasks (no executor — same "observations inform,
> decisions interrupt" posture as `observer.py`). `GET /api/self-improvement/status`
> aggregates error diagnostics + Observer + Acquisition + Ambient status in one
> read; `POST /api/self-improvement/enable` flips the documented bundle of
> already-existing default-off settings in one call (no new capability, no
> changed shipped default). New HUD `SelfImprovementPanel` (Console → Observe).
> `cognition.review_enabled` also gained its missing `settings_db` row (was
> read via `get_setting` with no DEFAULTS entry — invisible/unsettable from the
> admin API; now visible, default unchanged). +17 new backend tests, +3
> frontend; full backend (5,101) and frontend (361) suites green, route/OpenAPI/
> route-auth snapshots and the HUD-v2 parity map re-seeded for the 2 new routes.
> Packaged-app groundwork (ad-hoc, owner request 2026-07-18): Jarvis now builds
> as a PyInstaller onedir executable (`packaging/jarvis.spec` +
> `scripts/build_exe.py` with a real boot smoke test, `packaging/windows/install.ps1`,
> `docs/PACKAGING.md`), and a packaged install keeps ALL personal state in one
> owner-visible **user data home** (`~/Documents/Jarvis`: README, `.env`,
> `memory/`, `skills/`, `souls/` overlays — `agents/core/paths.py:user_home()/
> ensure_user_home()`). Formerly CWD-relative reads (skills, souls, heartbeats,
> `agents.yaml`, `.env`) are anchored on `app_root()`; generated/marketplace
> skills write to the user home when active; `$JARVIS_HOME` keeps winning for
> the data root, and a plain dev checkout is byte-identical (user home inert).
> Linux-verified end-to-end (built exe boots, `/readyz` green, scaffold
> created); the Windows exe build is an owner task (`docs/OWNER_TASKS.md`).
> +14 backend tests (`tests/test_user_home_packaging.py` + soul-overlay case).
> The **Nerva in-product rename** (owner decision 2026-07-19, per NERVA_VISION §2)
> shipped in the same wave: every user-facing surface says Nerva (HUD chrome/titles,
> `nerva[.exe]` + `Documents/Nerva`, landing, README hero, new neural-N logo
> `docs/brand/nerva-mark.svg`, wake word `nerva` added, `JARVIS.md` → `NERVA.md` with
> all 28 cross-references updated). Kept: agent personas (Jarvis = the orchestrator
> agent), `jarvis-hub` repo/engine codename + `JARVIS_*` env prefix. Owner-only rest:
> the GitHub repo rename (OWNER_TASKS). Decision log: `docs/HISTORY.md`.
>
> **Voice orb — the reactive particle sphere** (ad-hoc, owner request 2026-08-06, from the
> "J.A.R.V.I.S. in the room" build guide): `frontend/src/orb.tsx` adds `VoiceOrb`, a Canvas-2D
> particle sphere (Fibonacci distribution + yaw/tilt projection + depth-shaded filaments + reactor
> rings) bound to the live `useVoice()` state machine — off / standing-by / listening / transcribing
> / speaking / error. Cinema mode gains a stage picker (`o` = orb, `n` = mesh; mesh stays the
> default so existing demos open unchanged) and the cockpit voice pill gets the same orb inline in
> place of the flat status dot. **Honesty contract:** only the LISTENING state may be driven by a
> measured signal (the real mic RMS from `voice.ts`); every other state runs a fixed breathing
> animation, is labelled `state animation`, and no numeric level is ever rendered — an animation is
> a state indicator, never a metric. No new dependency (no three.js/WebGL/CDN), no new endpoint, no
> backend change; degrades to a non-throwing empty shell on a null 2D context and honours
> `prefers-reduced-motion` + the HUD's calm-motion setting. +14 frontend tests (frontend Vitest
> 408 → **422**); `tsc --noEmit`, production HUD build, `tests/test_hud_v2_parity.py` and
> `tests/test_route_parity_guard.py` green. Mobile parity tracked as H18.24; the guide's remaining
> gap (ambient LED sync) is filed as H30.8. Guide-vs-repo map:
> [`docs/design/JARVIS_PRESENCE_GAP.md`](docs/design/JARVIS_PRESENCE_GAP.md).
>
> **Briefing wall — the reference layout** (same owner request, after five frames of the actual
> video arrived and materially changed the visual brief): `frontend/src/burst.tsx` adds
> `NeuralBurst`, a Canvas-2D neural firing field — per-tier dendrite trees grown from a
> deterministic seed, synapse nodes, long white axon sweeps and a blown-out core — and
> `frontend/src/wall.tsx` adds `BriefingWall`, the full wall-screen board (letterspaced wordmark,
> live pill, running clock, four stat cards, subsystem status rail, spoken line, corner brackets)
> with the field full-bleed behind it. It is the `brain` stage of cinema mode (`m` then `b`; `n`
> mesh, `o` orb). **Honesty:** regions are real cabinet tiers, node density follows the real agent
> count, only tiers that are actually executing fire, and `burstEnergy()` reports whether the light
> comes from a measured mic level, live work, or idle. The reference's agency KPIs are NOT
> reproduced — the same slots carry provable Nerva figures, and anything unmeasured renders `—`
> with the reason attached. +15 frontend tests (Vitest 422 → **437**). No new dependency, no
> endpoint, no backend change.
>
> **Wall pass 2 — from the two owner videos** (the still frames were a partial read; the videos
> showed the mobile build too): region chips are now bordered plates with a thick coloured edge bar
> and a `N agents · firing X% · N tasks` sub-line (the firing share is real: executing/roster); the
> wall gains a **HOLD TO TALK** control wired to the live `useVoice()` loop (press starts, release
> stops, refusing honestly when the mic is muted or the browser cannot capture audio); collapsed
> **AGENT OPS / CABINET** edge tabs carry live counts and drop the badge instead of showing `0`
> when the task feed is unavailable; and under 820px the wall takes the reference's portrait
> layout — cards give way to the edge tabs, chrome centres, and the talk button leads. +5 frontend
> tests (Vitest 437 → **442**).
>
> **Wall pass 3 — integration-review fixes** (owner review on #843, head `9974f81`): two evidence
> boundaries failed open and are now closed. (a) `sources.tasks` is the proof the task feed answered
> *this* load; a retained array from an earlier poll no longer reaches `wallState`, `burstEnergy` or
> `NeuralBurst`, so the wall can never claim WORKING / firing regions / task chips while its own rail
> reports `task feed · no data`. (b) `trust` is deliberately RETAINED across polls in `app.tsx`
> (`if (d.trust) setTrust(d.trust)`), so a stale `mic:'on'` could outlive its evidence — the
> HOLD TO TALK control, and the rail's mic/strict-local rows, now key off `sources.trust` and fail
> closed with `trust status unavailable` rather than opening a microphone on unproven state. The
> room-facing spoken line gained a persisted redaction control (`hud.wall.transcript`,
> `TRANSCRIPT_DEFAULT_VISIBLE` flips the installation default). +9 hostile frontend tests, all
> red-proved against the pre-fix code (Vitest 442 → **451**).
>
> **Wall pass 4 — second integration review** (head `5e8825b`): the microphone now fails closed over
> its whole *lifecycle*, not just at first render — capture needs current `sources.trust` evidence
> **and** an exact `mic === 'on'` (missing/unknown/malformed authorizes nothing), and it stops on
> permission loss, trust expiry and unmount/stage-switch; the control is keyboard-operable
> (space/enter, repeat-safe). The room-facing spoken line now defaults to **hidden** — the owner
> reaffirmed default-hide over the reference's always-on line, so showing it is an explicit,
> persisted per-installation opt-in. Two unevidenced zeros are gone: `EXECUTING` gates on
> `sources.agents` and `DECISIONS PENDING` on the absence of any live decision feed (there is no
> endpoint yet — it renders `—` with that reason outside demo). The HUD motion preference is wired
> end-to-end (app → cinema → orb/mesh/burst and the cockpit's inline orb), so the calm-motion claim
> in `docs/VOICE.md` is now true instead of aspirational; unknown trust reads `MIC · UNKNOWN`.
> Docs: the presence doc pointed ambient work at H23.x instead of H30.8; the phone claims are
> narrowed to the browser HUD with native tracked as new **H18.25** (`mobile/PARITY.md` flips the
> wall from ➖ to ⬜); and the wall-screen room validation the doc *claimed* was in
> `docs/OWNER_TASKS.md` is now actually there (legibility, mic pickup, echo, per-room privacy).
> +13 hostile frontend tests (Vitest 451 → **464**).
>
> **Wall pass 5 — third review round** (head `fc9e94e`): a **capture-after-cancellation race** in
> `frontend/src/voice.ts` is closed. `getUserMedia()` can sit on a permission prompt for seconds;
> `stop()`/unmount released a stream that did not exist yet, so a late-resolving permission then
> published the stream, went active and entered the hands-free loop — capture starting *after*
> authorization was withdrawn. A monotonic `startGenRef` now invalidates pending starts: a stale
> resolution stops every returned track and publishes nothing. Second: `useVoice()` returns a fresh
> wrapper each render and the wall's parent rerenders every clock tick, so the wall's unmount
> cleanup (keyed on that identity) was stopping a valid capture about once a second — release and
> cleanup now key on a stable `stopRef`, never the wrapper. Third: the roster evidence rule was only
> half-applied — `evidenceAgents` now gates every roster-derived consumer (`wallState`,
> `burstEnergy`, `NeuralBurst`, the firing count and the CABINET badge), not just the two cells.
> Fourth: the footer rendered a malformed `mic` value as OPEN/IDLE; only an exact `on`/`off` maps to
> OPEN/IDLE/MUTED and everything else reads `UNKNOWN`. +14 tests, all four red-proved against the
> pre-fix code (Vitest 464 → **478**).
>
> **Wall pass 6 — fourth review round** (head `e07b311`): two regressions from the previous pass.
> (a) The roster evidence gate emptied **demo mode**: `loadJarvisData(true)` seeds the roster while
> leaving `sources.agents` false on purpose — that flag means *real live* evidence and demo is a
> separate, watermarked provenance — so the demo wall lost its field, counts and badge.
> `agentEvidence` now accepts `demo || sources.agents === true`, with a regression shaped like the
> real loader's demo output (not the convenient `sources.agents:true` the earlier positive control
> used) plus the non-demo negative control. (b) In `voice.ts`, a **stale permission rejection** from
> a superseded start still published `error`, overwriting the OFF state a `stop()` had just set; the
> catch now compares generations first. Noted honestly: the reviewer's second interleaving (stale
> rejection while a newer capture is live) is covered by the same guard but is **not red-provable**
> through the hook's public state — the running loop clears status/error every iteration — so no
> test is claimed for it. Vitest 478 → **482**.
>
> **Wall pass 7 — fifth review round** (head `af372eb`): (a) the DEMO corpus was labelled as live
> at the point it was read — `CABINET · NOW · live`, `THIS SESSION · measured` (over app.tsx's demo
> `localPct = 87`) and the subsystem rail — even though the page chrome said DEMO. Provenance is now
> per-card: every stamp reads `demo · seeded` in demo, and the regression is driven by the REAL
> `loadJarvisData(true)` output instead of a hand-built props shape, asserting each card's stamp.
> (b) The two stale-rejection interleavings the previous pass called unprovable ARE provable: with a
> `MediaRecorder` mock that never completes an utterance, the newer session parks in `listening` and
> a stale write is plainly visible. Older-reject-after-newer-success now red-proves the catch guard;
> the unmount-then-reject case is kept as an invariant with its weaker status labelled in the test.
> Vitest 482 → **484**.
>
> **Wall pass 8 — sixth review round** (head `6b57faf`): the per-card demo stamp added in pass 7 was
> the mirror of the bug it fixed. A **connected** demo keeps polling and replaces seeded values with
> real ones as each source answers (`sources.agents`, `.calendar`, `.heartbeat`, `.tasks`, `.trust`
> are set independently), so stamping every card `demo · seeded` from `demo === true` relabelled
> live data as seeded — and one card can legitimately hold both at once, which no single card label
> can describe. Provenance is now **per cell** (`data-prov`, plus a visible `seeded` tag on seeded
> values), and the card stamp is *derived* from the cells it actually shows: `live`/`measured`,
> `demo · seeded`, or `mixed · live + seeded`. `localPct` provenance is passed from `app.tsx`
> (`measured` / `strict-local` / `seeded`) instead of inferred from `demo`. Vitest 484 → **488**,
> with connected, partially-connected and mixed-card regressions alongside the offline-demo and
> non-demo controls.
>
> **Wall pass 9 — seventh review round** (head `8d05aab`): a **fail-closed trust parse**. The wall's
> "exact `mic === 'on'`" rule was defeated upstream by the adapter in `api/loaders.ts`:
> `mic: d.mic || 'on'` turned a missing/empty/`0`/`false` value into an affirmative permission, and
> `strict_local: !!d.strict_local` turned the STRING `"false"` into a true governance claim (which
> also feeds a derived 100% locality figure). Only the literal strings/boolean now count; anything
> else is `unknown` and refuses capture. Also: `cardStamp()` returned the live label when a card had
> nothing to show, so an all-`—` card announced evidence it lacked (now `no evidence`); the demo
> page caption was unconditional, so a fully connected demo described live data as seeded (now
> derived from the real source mix); a `Cell` with no declared provenance defaulted to `live` (now
> `unknown`); and an empty seeded decision list rendered `0` rather than `—`. +13 tests, all
> red-proved (Vitest 488 → **501**).
>
> **Wall pass 10 — eighth review round** (head `c4055a2`): provenance labels must name the ACTUAL
> source. A strict-local 100% is *derived* from a governance flag, not measured, but the wall folded
> every non-seeded locality source into `live` and `THIS SESSION` then stamped it `measured`. The
> three-way source is now preserved end to end (`measured` / `strict-local` / `seeded`), a derived
> value carries its own visible tag, and `cardStamp()` gained `derived` / `mixed · live + derived`.
> The derivation moved into `frontend/src/locality.ts` so the reachable App path is testable — in
> demo the app skips locality loading and the loader clears it, so that branch cannot be reached by
> a props fixture at all. Also: the ATTENTION card passed `queue` (not a provenance) as its all-live
> label, so a card with live calendar/heartbeat evidence stamped `queue`; it now stamps `live`.
> +12 tests, red-proved (Vitest 501 → **513**).
>
> **Wall pass 11 — ninth review round** (head `13012cf`): `THIS SESSION` stamped `measured` whenever
> its cells were live, so a card whose only evidence was a trust read (CLOUD LANE) — or a resident
> model — claimed to have measured something. The live label is now conditional on a genuinely
> *measured* locality split being among the values shown; otherwise the card reads `live`. One of
> the previous pass's tests had pinned that contradiction (live cell + `measured` card) and is
> replaced, with a loader-shaped trust-only regression added. Vitest 513 → **515**.

---

## 📋 Docs-vs-code accuracy pass (2026-07-24 — feature-sheet audit)

Fixed since: ✅ **integration-closure and SEC-B4 delivery plans recorded** (#957) — the approved
planning/spec documents for this sprint are in `docs/superpowers/plans/`; no product code.


> 47 claims from `README.md`/`docs/FEATURES.md` verified against source (6 parallel research
> passes): **36 live · 11 partial/default-off · 0 fabricated**. Complements the 2026-07-18
> live-vs-plumbing audit below — that epic fixes *code* honesty (MOCK badges, degraded stamps);
> this pass fixed the *docs*, which narrated opt-in rails as generally on. BACKLOG was already
> accurate (H27.3 says default-off) — per the house rule, the stale docs were fixed to match it.

- [x] `docs/FEATURES.md` — Action Kernel bullet now names the always-on risk-tier gate and marks
  the kernel opt-in (`JARVIS_ACTION_KERNEL`); ORIZONT 27 "delivered" → code-complete with the
  `perform()` facade + earned autonomy explicitly default-off; earned-autonomy sentence carries
  its flag; voice reworded (browser-mic loop ships; server wake word = optional native deps);
  Discord/Slack marked SDK-install; plugin bullet advertises the MOCK/degraded honesty layer;
  stale counts refreshed (369→400 routes; 4,300+/209/55 → 5,300+/370/96 tests; date 2026-07-24).
- [x] `README.md` — thesis line "every autonomous action crosses one Action Kernel" → honest
  "risk-gated …, converging on one Action Kernel mediation point (opt-in while it hardens)".
- [ ] Owner decision (parked in `docs/OWNER_TASKS.md`, not sprint scope): define the flip-on
  criteria for `JARVIS_ACTION_KERNEL` + `JARVIS_UNIFIED_ACTION_API` — when does the kernel
  become the default rail instead of the opt-in one?

---

## 🥊 Nerva vs Hermes Agent — honest gap analysis (2026-07-25)

Fixed since: ✅ **NERVA_VISION capability claims reconciled with the code** (#952) — the
verified/partial/aspirational split in `NERVA_VISION.md` now matches what actually ships, so the
vision doc stops reading as a status report for capabilities that are still seeds.


> Full analysis + evidence: [`docs/research/2026-07-25-nerva-vs-hermes-honest-gap-analysis.md`](docs/research/2026-07-25-nerva-vs-hermes-honest-gap-analysis.md).
> Hermes side re-grounded live (repo + releases + docs, 2026-07-25): **v0.19.0** (07-20), 220.1k★,
> releases every ~2–3 weeks; it now ships **real desktop computer-use** (`cua-driver`, mac/win/linux,
> a11y + screenshots, per-action approval), real browser automation (local CDP + Browserbase +
> Browser Use), **Home Assistant device control** (`ha_list_entities`/`ha_get_state`/`ha_list_services`/
> `ha_call_service`), smart approvals **by default**, Bitwarden/1Password secret sources, `/goal`
> completion contracts verified against evidence, and Skills-Hub security scanning.
> **Verification:** the analysis was itself put through an 11-agent adversarial pass (6 refuters +
> 5 deepening passes) — **103 claims audited, 46 confirmed, 56 refuted-or-partial, 16
> story-changing**. The items below are the *corrected* ones; the draft's own errors are recorded in
> §9 of the doc.
> **Headline:** architecturally ahead, operationally behind — and three of our "gated" behaviours are
> **broken rather than gated** (§3.2 of the doc). Corrected S-bar count: **4 of 8 bars have a CI-green
> artifact (S1/S2/S3/S5), 4 have none (S4/S6/S7/S8), and 8 of 8 have no artifact produced on real
> hardware or scored against Hermes** — the earlier "7 of 8 have no artifact" was wrong. S7 is
> *unreachable by construction* (every P4–P6 reality pack is `promotable: False` while the harness is
> the only path to VERIFIED). Strongest fact for our moat: Hermes issue #487 (SHA-256 hash-chained
> action log) was closed **"not planned"** — they have declined to build the thing we built and left
> disconnected in production.

- [ ] 🔴 **GAP-0 — distribution is the binding constraint, and we have the data.** The repo is
  **public** (4★, 979 commits) and `marketing/alpha-testing/2026-07-10-fb-response-triage.md` records
  a campaign that reached **24,182 unique visitors / 165 interactions / ~16 warm leads** and converted
  **0** design partners (A7 still ⬜ fifteen days later). Demand exists; time-to-first-value is what
  fails. This outranks every capability item below.
- [ ] 🔴 **GAP-1 — A8 first, everything else after.** Note the pillar taxonomy: house + cameras are
  *configuration* work (real clients ship, only the LAN device is missing); **media is driver-missing**
  (no `MediaDriver` implementation exists and `routers/media_director.py` has no injection point — the
  owner must write driver code); **acquisition is caller-missing** (needs a contract factory + a
  trigger, not just a caller). A8's `present()` line is not a config task.
- [x] 🔴 **GAP-2a/b/c — three of the four one-line fixes: DONE.** Shipped together as
  "defaults that are broken, not off":
  - [x] **(a) the learning loop was unreachable** — `cognition.review_enabled` added to `WAVE1_FLAGS`
    (`product_posture.py`). Both wave-1 postures (Companion / Design Partner) enabled the master flag,
    memory, learning and personality but omitted `review_enabled`, and `sub_enabled()` needs both — so
    the ORIZONT 20 per-turn review had never run for anyone. Provenance is automatic (`_SNAPSHOT_FLAGS`
    derives from `WAVE1_FLAGS`, so all three trust surfaces show `source=product.posture:<name>`,
    satisfying O26-P2.4/D1). Cost was already bounded: daily budget 20 + cadence knob + strict-local
    `local_backend` that fails closed.
  - [x] **(b) default-install memory lost history on restart** — `list_sessions()` globbed every
    `*.json` in the data root and ranked `entities.json` (rewritten by the KG on any turn with a proper
    noun) as the newest session, so restore picked a session with no turns. NEW
    `agents/core/session_files.py` holds one rule — denylist + valid-id + *payload-shape confirmation*
    — and `persistence`, `retention` and `data_purge` now share it instead of carrying two partial
    copies. Also closed the restore half: `_boot` now resumes the checkpoint-restored session, which
    `ConversationMemory` never loaded (it only auto-loads the newest at construction).
  - [x] **(c) no action was ever audited in production** — `AutonomyWorker` got no `audit` sink, and
    the one place a sink *was* passed (`RemediationRunner` ← `orch.audit`) could not work because
    `log(event_str, dict)` ≠ `AuditLogger.log(SecurityEvent)`. NEW
    `agents/core/autonomy/audit_sink.py` (`ActionAuditSink`) adapts that shape onto **`IntentLog`** —
    always HMAC-signed with an out-of-tree key, and it already models intent — so auto-approve, human
    decision, execution and failure now leave signed records with causal attribution. Both call sites
    share `orch.action_audit`. Best-effort contract preserved: a failed audit write never aborts an
    authorized action. (+9 tests across a/b/c; backend counter 5430 → 5439 after rebase onto #729.)
- [x] ✅ **GAP-2d — SEC-B3 Telegram owner binding.** **Owner-binding half done** — the approval sink
  now checks owner chat id **and** user id and fails closed with neither configured, and
  `TELEGRAM_ALLOWED_USER_IDS` is parsed so the channel guards are reachable at all (they were
  unreachable no-ops). *Still open:* channel pairing ON by default, which is the defaults lane.
- [x] ✅ **GAP-3 — register the escaping action kinds.** **DONE** — `channel.reply` and `skill.install`
  are registered KERNEL in `ACTION_REGISTRY` + `tests/_snapshots/action_auth.json`, enumerated in
  `known_broker_action_kinds()` (from their own KIND constants, so the matrix discovers them), carry
  full H27 capability manifests, and both have real matrix exercisers (kernel-on invokes / kernel-off
  doesn't). The acquisition gate now goes through the shared `make_skill_install_kernel_gate` factory,
  which also closes its kernel-off gap: it used to call `authorize` even with `JARVIS_ACTION_KERNEL`
  unset, unlike every sibling broker. Original: both kinds called `kernel.authorize` but were absent
  from the registry, and the matrix's broker enumeration was a hand-maintained import list.
- [ ] 🟠 **GAP-4 — run the head-to-head once.** Install Hermes on the same box; **10** tasks
  (browser · desktop · house · one acquisition); publish the table including the losses. Aim at where
  Hermes documents *limits* — Windows admin-integrity windows (UIPI), Wayland without XWayland,
  password entry. ~1 day. Feeds S1/S2.
- [x] ✅ **GAP-5 — SEC-B1 with its preconditions stated.** **FIXED**, and the preconditions were right
  to insist on: cloud configured AND (`cloud_fallback=always` OR local down OR a prompt over the local
  window) — not a default-install leak. The adversarial audit independently reached the same
  correction after its first pass overstated it. Overstating a real finding is how it gets dismissed.
- [ ] 🟠 **GAP-6 — flags: know what flipping costs.** `JARVIS_ACTION_KERNEL` is **not pure hardening**
  — with it on, a broker GRANT sets `autonomy_level="act"`, removing the wave-1 unconditional `ask`
  floor; and the O27–O30 facades need **two** flags (`JARVIS_UNIFIED_ACTION_API` too), so the kernel
  flag alone does not light up house/media/desktop. Cheapest real win instead: the five governed
  webhook channels (WhatsApp/Signal/Matrix/Teams/Google Chat) need **no extra pip dependency**, only
  `JARVIS_WEBHOOK_CHANNELS`.
- [ ] 🟡 **GAP-7 — restate the Hermes verdict** in `NERVA_VISION.md` §8. Drop "Hermes can't touch a
  light" and "no household story" (it has an HA `area` filter and per-family-member profile
  isolation) — both refute in one link. Defensible: **"Hermes has HA as a tool; Nerva has a house
  model"** and **"Hermes declined to build an action-level audit chain; we built one and have not
  turned it on."** Also credit what Hermes *doesn't* gate: `ha_call_service` has no approval,
  container isolation *replaces* command checks, smart approvals auto-approve low risk, memory writes
  default to no approval.
- [ ] 🟡 **GAP-8 — re-baseline `NERVA_VISION.md`** §3's prose *and* §4's percentages (P1 ~35%, P4 ~20%,
  P5 ~15% — no pillar is stated as 0%), plus §98's "11 privileged action kinds" (the snapshot now
  covers 18).
- [ ] 🟡 **GAP-9 — honesty debt found by the pass** (each traced to file:line in the doc):
  `/api/house/state.presence` is structurally always `[]` in every production configuration (the only
  writer of those predicates has no prod caller); ONVIF discovery needs the undeclared `wsdiscovery`
  package; the camera VLM leg needs a self-hosted VLM server; `environments/` is a policy plane that
  never executes and **no SSH transport exists in the repo**; the reality harness persists nothing
  (in-process registry, no uploaded artifact); README's voice stack lists engines no install path
  ships.

---

## 🛡️ Governance-rails security audit (2026-07-24 — 8-reviewer adversarial pass)

Fixed since: ✅ **SEC-B4 egress boundary** (#956) — every plugin HTTP call now dials a
resolver-validated, pinned target (Host/SNI preserved, redirects re-validated per hop) instead of
letting httpx re-resolve. Two defects found while integrating and fixed there: RESTRICTED plugins
whose base URL is a self-hosted loopback/RFC1918 literal were validated in `public` mode and so
became unreachable (local-first regression, MOONSHOT §5.1), and the twelve tests still mocking the
retired `_client` seam were doing real DNS/TCP. **Still an owner gate:** this is R3 and the
independent review named in the draft has not happened.


> Full findings + severities + evidence: [`docs/research/2026-07-24-governance-rails-security-audit.md`](docs/research/2026-07-24-governance-rails-security-audit.md).
> One reviewer per invariant (kernel bypass · taint · approval queue · strict-local · secret/audit
> crypto · SSRF · skill signing · router auth), each required to trace enforcement code and build a
> concrete bypass. **Headline: the core "can't act ungoverned by default" invariant HOLDS**
> (kernel-off path verified across all six action families; classifier fails closed). The holes are
> data-exposure, one strict-local leak, and integrity labels that over-promise. Feeds the
> 2026-07-16 security-correctness wave (`docs/superpowers/plans/2026-07-16-security-correctness-wave.md`).

**Delivered (PR #711, merged):**
- [x] **SEC-A1 — unguarded personal-data reads.** Added `user_guard` to 10 read routes whose sibling
  writes were already guarded (KG entities/facts, `/memory/{agent_id}`, `/api/actions[/pending]`,
  `/api/traces[/{id}]`, `/api/cost`). Re-seeded `tests/_snapshots/route_auth.json` (open→user).
- [x] **SEC-A2 — audit empty-hash bypass.** `verify_chain` now fails closed on a blank `row_hash`
  after the chain starts (previously `continue`'d past it, so a forged row passed even in HMAC
  mode), while still tolerating a legitimate legacy pre-Merkle prefix. +3 regression tests.

**Deferred — needs design/posture work (ranked):**
- [x] ✅ **SEC-B1 — Frigga family data → cloud via synthesis.** **FIXED** — `Agent.synthesize` now computes a policy floor over CONTRIBUTORS and pins the merge to `llm_router.local_backend` (the fail-closed accessor `_compression_summarizer` already used), falling back to the deterministic join when no local backend exists. Tested at the synthesize boundary, per the audit. Original: `Agent.synthesize` runs
  under jarvis's cloud-eligible policy and embeds a strict-local agent's raw output; a direct-to-Frigga
  turn triggers synthesis. Fix: synthesis inherits the strictest contributor policy (pin local if any
  responder ∈ `LOCAL_ONLY_AGENTS`) + a test that frigga-containing responses never select cloud.
  Precondition: cloud configured + (`cloud_fallback=always` or large prompt). Breaks the hardest promise.
- [x] ✅ **SEC-B2 — unkeyed-hash-as-signature (audit #3 + skill signing #9).** **FIXED both halves** — `require_signed()` fails closed when enforcement is on with no key; `verify_skill` returns `integrity-only` rather than `signed` for an unkeyed digest; `signing_posture()` surfaces `effective`/`integrity_only` on `/api/security/posture`; and the audit-chain half is AUDIT-1 above. Original: `REQUIRE_SIGNED_SKILLS`
  and the "tamper-evident" audit claim only hold when an optional key env var is set. Fail closed /
  label unkeyed digests as integrity-only; surface the distinction in `/api/security/posture`.
- [x] ✅ **SEC-B3 — Telegram approval owner-binding.** **FIXED** — `TELEGRAM_ALLOWED_USER_IDS` is parsed and passed (the guards were unreachable no-ops before), the decision callback checks owner chat **and** user id and fails closed with neither, and the pairing gate no longer defaults to allow on a store error. Original: Callback handler has no owner check when
  constructed without `allowed_user_ids` (the production wiring). Implement the 2-factor callback
  check (owner `chat_id` + `user_id`, fail closed on empty allowlist) the wave plan already specifies.
- [ ] 🟡 **SEC-B4 — SSRF IP-pinning coverage.** *(still open — needs a live network/browser host to demonstrate; chapter 15 ADV-142.)* The checker is sound but the Playwright path and the
  central `PluginHTTPClient` don't route through `resolve_and_validate` with pinning (rebinding TOCTOU).
- [ ] 🟡 **SEC-B5 — taint by dataflow, not just declared origin.** Proactive/recall/ambient payloads
  rebuilt outside an inbound turn drop ingress taint (worst confirmed case is READ_ONLY-bounded).
**Adversarial audit, 2026-07-25 (26 agents · 18 findings tested · 2 confirmed · 10 corrected down ·
6 refuted · 3 new from the completeness critic).** Its headline is a compliment: independent agents
trying hard to embarrass this codebase mostly re-discovered SEC-B1…B6 above. Two need owner triage
because they are **not** on that list:

- [x] ✅ **AUDIT-1 (High, confirmed) — the audit chain is forgeable in hardened mode.** **FIXED** — `verify_chain`
  recomputes each row with *the row's own* `hash_algo`, and `_digest` demands the key only when that
  column says `hmac-sha256`. Downgrade every row to `sha256` and the chain re-links cleanly with
  `JARVIS_AUDIT_KEY` set and `hardened.enforce()` returning clean — reproduced independently while
  writing chapter 15 (`sqlite3` + `hashlib` only; the key is never read). The shipped regression
  passes because it downgrades **one** row, so the break surfaces at the next row whose `prev_hash`
  is still an HMAC. Fix: pin the algorithm per install and treat a post-legacy `sha256` row as
  tampering when a key is configured — the fail-closed shape the blank-row guard (SEC-A2) already
  uses. Extend the regression to a full-table rewrite in the same commit. Same root cause as SEC-B2.
- [x] ✅ **AUDIT-2 (High, confirmed) — `POST /api/admin/forget` did not erase, it copied.** **FIXED** — Three
  independent failures: twelve user-content stores sit outside the `PURGE_*` allowlists (including
  per-agent run previews and full inbound message bodies, two of them on a denylist that also stops
  the session path deleting them, so nothing removes them ever); the vector/KG wipe is dead code —
  no `VectorStore`/`KnowledgeGraph` implementation defines `clear()` and the call is `hasattr`-guarded,
  so under the documented qdrant/neo4j backends every embedding and triple survives permanently while
  the purge reports `ok`; and the forced pre-forget archive lands **inside** the data root it just
  purged, unencrypted unless a backup key is set, with no API equivalent of the CLI's `--no-backup`
  and nothing pruning it. `docs/PRIVACY.md` promises erasure and AUD-2 is ticked done. Contradicts
  the A7 design-partner gate directly: a partner asked to delete their data before returning the box
  currently cannot. Fix: invert to a KEEP allowlist, make `clear()` abstract, move and encrypt the
  archive. The purge's *engineering* is sound (verified snapshot before any delete, SQLite
  online-backup API, Zip-Slip guard) — the bug is the allowlist.

The systemic finding is not a bug at all: five of six lenses independently found **a gate that checks
the shape of a claim rather than its substance** — a parity test matching a URL prefix, a capability
probe registering its own lambda, a safety pack whose `ungoverned_actions` counter is the literal
`0`, a signature verifier accepting an unkeyed hash. Verification protocol for all 18 findings, the
six refuted ones (so nobody chases them), the never-measured surfaces, and a **38-row
missing-code/missing-feature gap ledger**: [`docs/test-manual/15-audit-gap-verification.md`](docs/test-manual/15-audit-gap-verification.md)
(160 cases, `ADV` prefix) + `scripts/qa_audit_probes.py`, which reproduces nine of the claims on the
owner's machine in 30 seconds, read-only.
  *Update 2026-08-11 (successor of split #894):* the last probe still OPEN on `main` — **ADV-087**,
  "capability probe registering its own lambda" — is **FIXED**: `_make_action_kernel_probe` now
  resolves `manifest.implementation` to the real actuator before the refusal rail and fails closed
  when the declared implementation does not resolve; the green case's evidence names the certified
  implementation (+2 tests in `test_h27_capability_verification.py`). `qa_audit_probes.py` reports all
  nine claims CLOSED.

- [ ] 🟡 **SEC-B6 — gate hardening.** *Bytes landed on `main` via #896 (`d57d87f`, 2026-08-09) with
  green CI, but GitHub records no independent review submission for it, so per the #894 integrator
  directive below this stays 🟡 until an evidence-backed acceptance is recorded.*
  `test_route_auth_matrix.py` gains a *read* half: `test_no_unclassified_open_read` forces every OPEN
  GET to be classified by the **substance of its handler** (`INTENTIONALLY_OPEN_READS`, each with a
  reason) or carry `user_guard`; `test_read_classifications_are_honest` keeps both sets shrink-only so
  the allowlist can't mask a later guard. The classification pass found 13 personal-content reads
  shipping open (per-agent run history + SOUL, quality scores, review queue, missions, workflows,
  learning, arena match, oracle conflicts, reflection status, worldview overview) — all flipped to
  `user_guard`, snapshot re-seeded, generated chapter-14 sweep regenerated. Per-handler substance
  evidence: [`docs/security/SEC-B6-open-reads-evidence.md`](docs/security/SEC-B6-open-reads-evidence.md).
  **Mark ✅ DONE only when the successor PR passes fresh exact-head CI + independent review** (owner
  integrator directive, #894). *Follow-up delivered:* the export/purge-drift gap is closed — #900
  (`2f81029`, Max «copper-nectar») added `tests/test_forget_export_purge_parity.py` asserting
  nothing an export names may sit on the forget KEEP list.

**Parallel bug hunt, 2026-07-28 (8 finder lenses · 164 agents · 52 findings · 41 confirmed after
3-lens adversarial verification · 11 refuted).** Every confirmed finding was re-derived from source
and, where the defect was reproducible, reproduced before being fixed. The verification stage
required 2 of 3 independent skeptics to fail to refute a claim, each with a different lens
(does-it-reproduce / already-handled-elsewhere / is-the-severity-honest).

The theme is the same one the 2026-07-25 audit named — a claim whose shape is checked but whose
substance is not — and it turned out to be much wider than the gates. It runs through the *display*
layer end to end: **twelve surfaces asserted something they had never measured.**

Fixed, all with regression tests that fail when the defect is reintroduced:

- [x] ✅ **Privacy: a forget kept a plaintext copy of everything it erased.** `backups` sat on
  `KEEP_DIRS`, justified as holding the pre-forget archive — but AUDIT-2c had already moved that
  archive *outside* the data root. What the entry actually retained was ordinary owner snapshots,
  and `POST /api/admin/backup` passes no key, so those are unencrypted tarballs of the whole root.
  Back up Monday, forget Friday, and `purge_data` returned `ok:true` while a cleartext copy sat in
  the folder it had just cleaned.
- [x] ✅ **Data loss: every forget destroyed `settings.db`.** The sweep unlinked SQLite `-wal`/`-shm`
  sidecars, including those of the KEPT databases (`Path("settings.db-wal").suffix` is `.db-wal`, so
  it matched no branch and fell through to `unlink()`). Deleting the `-wal` of a live WAL database
  leaves it unopenable — reproduced as `disk I/O error`.
- [x] ✅ **Money: the runway figure was computed from mock bank balances.** With ING configured and
  failing, `_total_balance()` summed the hardcoded `MOCK_BALANCES` to 16000.32 and divided real
  monthly spend by it, returning `"mock": false`.
- [x] ✅ **Two lost-write races on the secret store.** Key/salt creation was check-then-act, reachable
  from the two backup routes that each build a `SecretStore` in a worker thread — the loser's archive
  becomes permanently undecryptable. Writing the tests surfaced a second race the finders missed: a
  shared `.tmp` filename plus a read-modify-write over a per-instance cache, which silently dropped
  credentials.
- [x] ✅ **Privacy assurance from missing data.** The legacy HUD computed strict-local as
  `!trust || trust.strict_local`, so a HUD that could not reach `/api/trust/status` displayed a
  padlock reading "nothing leaves this machine".
- [x] ✅ **The HUD synthesized its own telemetry.** `useLiveSys` layered sine waves and
  `Math.random()` onto RAM/VRAM/GPU/latency every 1.4s and rendered the result as live host state,
  seeded from a hardcoded 42/192 GB machine. Numbers that drift are more convincing than static ones.
- [x] ✅ **`/security/status` was entirely static** — mode always `WARN`, every counter `0`, pattern
  counts hand-written and wrong. Guardrails now actually count; what is still unmeasured says so.
- [x] ✅ **`/readyz` published a configured backend NAME inside a dict called `checks`.**
- [x] ✅ **`/api/cognition` fabricated a routing decision** (confidence 1.0, zeroed timings) when
  nothing had been routed. Its test asserted the fabrication.
- [x] ✅ **`/learning/stats` had never once worked** — `list()` over an int count, TypeError on every
  call, swallowed into a body of zeros. Its test asserted only "ints and lists", which zeros satisfy.
- [x] ✅ **`/ticker` read a key the observer has never emitted**, so every unhealthy probe was
  silently dropped. Its test stubbed the same fictional key, so test and code agreed while both
  disagreed with the class.
- [x] ✅ **OBSERVE rendered the demo seed under a LIVE badge** — `/api/quality` nests under `stats`
  and `/api/resilience` emits none of uptime/errors/redactions, so four fabricated numbers showed
  with a green chip.
- [x] ✅ **XSS in the public widget snippet** (`color`/`position` unescaped into `innerHTML`) and
  **path traversal in skill import** (`replace(" ", "-")` left `..` and `/` intact).
- [x] ✅ **The four hanging routes, root-caused.** A blocking Qdrant read inside an async handler
  under a lock froze the whole event loop, so handlers with no I/O of their own hung too; plus a
  heavy ML import on the loop and an unbounded memory await.
- [x] ✅ **Shutdown released nothing** — autonomy worker and learning loop never cancelled, two
  sqlite handles never closed (which is what makes a data directory undeletable on Windows).
- [x] ✅ **Cypher property names could hijack node identity** — a relation property called `source`
  rewired the relation to a different node.

Still open from that run (verified real, not yet fixed): the seeded ADMIN/OBSERVE
corpora in `modes3.tsx`/`modes2.tsx`. Fixed since (2026-08-01): ✅ the dead `arr() || fallback` in
the two `gap.tsx` panels — CLOUD AUTH PROFILES and OAUTH now render their APIs' real object-map
shapes (`{pools:{provider:…}}` / bare `{service:…}`), with vitest regressions.
Fixed since (2026-08-22): ✅ **blocking DNS/HTTP on the request path** — `browser.py`
(`/api/browser/check` + plan preview: SSRF `getaddrinfo` per URL, up to 200/preview),
`house` (`snapshot()` + actuation re-resolved the HA origin inline on every call),
ONVIF discovery (`_normalize` resolved each candidate xaddr on the loop), and
`memory_kg.py` (all graph-editor + search-tool routes ran sync neo4j httpx inline;
default in-memory backend unaffected) — all now pay their blocking calls to worker
threads via `asyncio.to_thread`, gated by loop-responsiveness regression tests
(`tests/test_request_path_blocking_io.py`). Audit correction: `codeintel.py` was a false
positive *for network I/O* (pure local AST/FS) — but ✅ **its filesystem walk was a real
loop-blocker in the same family** (#949): a cold `project_index()`/`reindex()` parses the whole
repo synchronously, so `/api/codeintel/{search,stats,reindex}` froze every other route for the
build; now offloaded via `asyncio.to_thread`, gated by
`tests/test_codeintel_router_async.py`. The real ONVIF surface is `cameras/onvif.py`,
not an `onvif.py` router; adjacent same-family `cameras/frigate.py:138` getaddrinfo noted,
still open.
Fixed since: ✅ the unauthenticated full-chain re-verify in `security.py` — `audit/verify` plus its
`audit/intent` and `audit/anchors` siblings (and `GET /api/workflows/traces`, WFL-132) are now
user-guarded, route-auth snapshot re-seeded; ✅ `north_star.py` all-time-as-7-day — `local_pct` is
computed via `RunHistory.locality(since=cutoff)` over the same trailing window as every other
counter metric (all-time stays available to `/api/analytics/locality`).

- [x] ✅ **Follow-up: the secret-store race fix corrupted key material on Windows.** The new
  `_read_or_create_atomically` opened its descriptor without `O_BINARY`, so the CRT ran it in TEXT
  mode and expanded every `0x0A` to `0x0D 0x0A`: the creator returned the 16 salt bytes it minted
  while every later reader read 17 different ones, deriving a different key for the same store. ~6%
  per salt (`1 - (255/256)**16`), silent, and reported only as "cannot decrypt secret (wrong key or
  corrupted)" against data written correctly. It surfaced as three unrelated Windows failures on a
  docs-only PR (`test_secrets`, `test_h30_presence`, `test_oauth_token_key`), which is the honest
  version of "the Windows run was green last time" — it was, by luck. `vault.py` has always ORed the
  flag in; `secrets.py` was the one `os.open` in the repo that did not. +3 tests, one of which pins
  the flag by giving POSIX an `O_BINARY`, so a Linux-only run can still catch its removal.

**The phone surface — open question, owner call (2026-07-29).** The scheduled e2e run fails 9
`mobile-chrome` cases (`.inputbar .transmit` and the push-to-talk button "intercept pointer events" at
the 393×851 Pixel 5 viewport). Nothing regressed: `E2E_BROWSER_MATRIX` is set only on `schedule`
events, and **all 26 scheduled runs since 2026-07-04 have failed — none has ever passed.** The matrix
was switched on over a layout that was never made responsive. Two facts frame the decision:

- [ ] 🟡 **The web HUD is not reachable from a phone today, by design.** `serve.py:66` defaults
  `JARVIS_HOST` to `127.0.0.1`, and `assert_safe_bind()` (`boot_guards.py:25`) **exits** on a
  non-loopback bind unless `JARVIS_USER_TOKEN`/`JARVIS_ADMIN_TOKEN` is set (or
  `JARVIS_ALLOW_INSECURE_BIND=1`); even then `_user_guard` (`web.py:192`) 403s every non-localhost
  client without a `USER_TOKEN`. The guards are right — but **the supported LAN path is documented
  nowhere**: a `docs/` grep for LAN/remote-access guidance returns nothing. Write it down regardless
  of the decision below.
- [ ] 🟡 **`mobile/` already assumes this topology** — a React Native app whose client takes a
  configured `baseUrl` (`mobile/src/api/client.ts`). If the app is the phone story, the web HUD is a
  desktop surface and `mobile-chrome` should come **out** of the matrix rather than stay permanently
  red. If the web HUD is also meant to work on phones, the fix is a real stacked-layout breakpoint
  (single column, chat pane full-height, rails collapsed/drawered) — not a pointer-events tweak.

---

## 🔌 Live-vs-Plumbing Remediation — mock → real (owner request 2026-07-18)

> **Full audit:** [`docs/research/2026-07-18-live-vs-plumbing-capability-audit.md`](docs/research/2026-07-18-live-vs-plumbing-capability-audit.md)
> · six-domain LIVE/PLUMBING/STUB code audit. The running product does far less than
> the merged PRs imply: of ~77 capabilities, **~11 LIVE** (only ~3 user-facing —
> weather, news, local analytics), **~52 PLUMBING** (real, but gated off / waiting on
> a key/OAuth/LAN-hub/engine), **~14 STUB** (mock / placeholder / absent). Dominant
> pattern: *"integration-ready, mock-fallback + host seam"* — a capability degrades
> quietly to a mock or `deferred` instead of erroring, so scaffold reads as product.
> **This epic tracks closing the gap** — turning PLUMBING into LIVE and building STUBs
> for real. Cross-cuts ORIZONT 27–33 (the pillars are code-complete but actuator-gated).

**Tranche 1 — shipped (mock → real, first cut):**
- [x] Capability audit persisted to `docs/research/2026-07-18-live-vs-plumbing-capability-audit.md`
- [x] `agents/core/plugins/degradation.py` — honesty helper: mock fallbacks now self-report a `_degraded` `{reason, needs}` + `_mock` so a degraded feature is distinguishable from a real one
- [x] **Real Tuya Cloud OpenAPI signing** (`iot_control.py`) — replaces the hardcoded `sign="MOCK_SIGNATURE"` (which Tuya always 401s) with the documented HMAC-SHA256 token-grant + signed-command flow; unconfigured → honest degraded result (no device touched)
- [x] **Real balance burn-rate** (`balance.py`) — was `MOCK_BURN_RATE` *even when configured*; now computed from a transactions CSV (`plugins.gecko_tx_csv_path`): monthly spend/income, top categories, runway from real balances
- [x] +14 tests (`tests/test_live_remediation.py`, pinned Tuya signature vectors); existing iot test updated to the honest `not_configured` contract; test counter synced (5,115)

**Config-wins — flip to LIVE with no new code (owner action, see `docs/OWNER_TASKS.md`):**
- [ ] Google OAuth → email + calendar
- [ ] Spotify OAuth → real playback control
- [ ] Install engines: `faster-whisper` (STT), `edge-tts`/`kokoro` (TTS), `playwright` (browser operator), `beautifulsoup4` (DDG search), `discord.py`/`slack_sdk` (Discord/Slack channels — adapters exist, SDKs not in base requirements)
- [ ] LAN Home Assistant + `JARVIS_HOUSE_BRAIN`/`JARVIS_HOME_ASSISTANT` → house read + control
- [ ] Frigate NVR + household consent → the camera + ambient stack
- [ ] Flip cognition master posture + a local LLM → the reflect-and-rewrite learn loop
- [ ] Telegram bot token → `channel.reply` (the one real autonomy side-effect)

**Genuinely unbuilt — needs real code:**
- [x] Tuya real signer (done, Tranche 1)
- [x] Balance burn-rate from CSV transactions (done, Tranche 1) — [ ] extend to ING/Libra transaction fetch (API path still pending)
- [x] Stock quotes feed — keyless `StockQuotesPlugin` (Stooq CSV), the third LIVE keyless plugin next to weather/news; egress-restricted, wired into the plugin gatherer (`$AAPL`/ticker detection), honest degrade when the feed is down. `market` router can consume it next.
- [x] Social: the live rail activates behind approval — the default Null client lazily
  upgrades to `HttpSocialClient` the moment an approved task resolves a real owner
  credential (`secret:x_api_token`), no restart needed; unconfigured stays honestly
  deferred and now carries the `_degraded {reason, needs}` stamp; injected clients
  are never replaced (`tests/test_social_live_client.py`)
- [x] Autonomy executors: live rails at the writeback / call host seams — same
  lazy-upgrade-behind-approval pattern as social (`Null* → HttpWriteBackClient` /
  `HttpCallClient` when the approved task resolves a real credential); deferred
  results now stamped `_degraded {reason, needs}`. Node mesh has **no transport
  at all** (not just an unwired client) — its deferred dispatch is stamped
  `node_transport_not_built`; building a real node transport stays open below
  under "Media / desktop / node actuators" (`tests/test_writeback_live_client.py`,
  `tests/test_call_live_client.py`)
- [x] Capability acquisition: the missing production glue —
  `AcquisitionRuntime.synthesize_and_propose()` composes reuse-resolution's `no_reuse`
  outcome → research → strict-local generation → sandbox verification →
  `PromotionBroker.propose()` into one callable path that creates a real `PromotionProposal`
  (previously only test/reality-harness fixtures ever reached `propose()`). Real skill
  code-synthesis: `agents/core/acquisition/llm_synth.py` implements the `generate`/`draft`
  seams `StrictLocalGenerator`/`GovernedResearch` take by injection with actual
  `LLMRouter.local_backend` calls (JSON-only, bounded retry) instead of hand-written
  fixtures — every downstream guardrail (AST/stdlib allowlist, placeholder-body rejection,
  `ground_plan()` citation gate, sandbox verification, permanent owner approval) is
  unchanged and still gates whatever the model returns. Deliberately **not** auto-triggered
  from chat/gap-capture — a caller (future admin action or scheduled worker) must invoke it
  explicitly, same as `resolve_gap` itself already is. The separate `SkillLoader.generate_skill()`
  `[learn:…]` stub (`"implement logic in handle()"`) is a distinct, smaller subsystem and is
  untouched here (`tests/test_h32_llm_synth.py`, `tests/test_h32_synthesis_pipeline.py`)
- [ ] Real payment rail adapter (AP2/ACP/x402) at `payments.settle()` — **owner decision required (moves money)**
- [ ] Media / desktop / node actuators (owner-wired host seams)
- [ ] `agents/vision`, `agents/argus` — real implementation (currently persona markdown, zero code).
  Argus's SOUL was completed 2026-08-18 (Scope/Rules/Dependencies/Memory/Channels — it had 4 of the
  roster's 9 sections); the code gap below it is unchanged.
- [ ] `agents/hestia` — the House Brain agent added 2026-08-18 owns `agents/core/house/**` (graph,
  presence, actuation, home_assistant) in *persona* only. ORIZONT 30 shipped the modules and the
  router; wiring Hestia's reads/proposals onto them is the remaining slice.
- [x] **HUD seed roster is 3 agents behind the backend.** `frontend/src/data.ts` hardcodes 15 agents
  (`AGENTS`, `GLYPHS`, `COLLAB`, `DOSSIER`, routing keywords) — it never gained **howard** or **argus**,
  and now not **hestia** either, while the registry is at 18. Found 2026-08-18 during the roster pass and
  deliberately *not* half-fixed: adding only Hestia would leave a roster that is stale in a less obvious
  way. Fixing it means a glyph, an `AGENTS` row, `COLLAB` edges, a `DOSSIER` entry and keyword weights
  per missing agent. The backend is the source of truth (`GET /api/status`, `agents.yaml`); the honest
  end state is deriving this panel from the API rather than re-hardcoding 18.
  **Delivered 2026-08-22 via the derive-from-API end state:** `/api/agents` now derives `tier`/`role`
  for registry-only agents from their SOUL.md front-matter (curated `_AGENT_META` rows keep priority),
  so howard/hestia describe themselves server-side; the loaders' degraded path unions `/status` agent
  ids with the seed meta instead of silently dropping unknown ids; unknown glyph ids render a neutral
  mark instead of an empty path. The watermarked demo corpus intentionally stays at 15 — it is fiction
  by contract, not a stale live view (`tests/test_agent_roster_meta.py`, `glyph-fallback.test.tsx`,
  `loaders.test.ts`). Remaining (non-blocking): dossier/collab *enrichment* for new agents in demo mode.
  **Correction 2026-08-22:** the neutral-mark claim above held only in the `Glyph` primitive.
  `network.tsx` (Neural-Mesh nodes) kept a raw `V2.GLYPHS[a.id] || ''` lookup, so howard/argus/hestia
  rendered an empty `<path>` — a hex outline with no glyph, the exact "looks absent" failure the
  primitive's fallback exists to prevent. The fallback now lives in one place (`V2.glyphFor`, used by
  the primitive, the mesh renderer and `loaders.ts`), so it can no longer be fixed in one renderer and
  missed in another; `glyph-fallback.test.tsx` covers both call sites and fails on the pre-fix code.

**Honesty layer (cross-cutting, highest-leverage):**
- [x] `degradation.py` helper + applied to `iot_control` + `balance`
- [x] Apply `degraded()` to the remaining mock fallbacks — sms-alerts, crm-sync, and the
  `MOCK_BALANCES` dict now carry `_degraded {reason, needs}`; whatsapp/apple-health/n8n audited
  clean (they already fail honestly via `configured` flags instead of returning fake data)
- [x] Surface degradation in the HUD — plugins expose a `degradation_info()` contract, the
  `/plugins` listing carries `degraded`/`degraded_reason`/`degraded_needs`, and the Admin
  plugin registry badges mock-backed plugins **MOCK** (amber, tooltip = reason + needed config).
- [x] **Mirror the badge onto capability-registry state (tranche 4)** — `_plugin_records(orch=)`
  now resolves the exact same live honesty verdict (`configured`/`honesty`/`degraded*`) into each
  plugin's `detail`, so `/api/capabilities` (the canonical board) can no longer imply a mock
  plugin is live either. Resolution logic (`runtime_configuration`/`degradation_info`/
  `live_plugin_for`) extracted from `routers/plugins.py` into `plugins/honesty.py` so both
  surfaces share one source of truth instead of re-deriving it. Backward-compatible: `orch=None`
  (the static-derivation path used by most tests) carries no honesty keys, unchanged from before.
- [x] **The agent-generated skill loop actually executes (tranche 5)** — the `main.py` template
  in `SkillLoader.generate_skill()` registered a 3-parameter `handle(cmd, args, context)` as the
  command function, while `Skill.execute()` dispatches `cmd_fn(args, context)` / `cmd_fn(args)`
  (`loader.py:177-179`): **every** generated command raised `TypeError` and surfaced as
  `[skill:X] error: …`. The same template made `get_commands()` name a function it never defined,
  so `getattr(mod, cmd)` (`loader.py:284-286`) raised `AttributeError` and logged a misleading
  "Failed to load skill module" on every `discover()`. The template now emits a per-command
  `$cmd(args, context=None)` with `handle()` kept as the 3-arg module fallback — the same shape
  every hand-written skill uses. `tests/test_generated_skill_contract.py` (+19) executes the
  generated command instead of only asserting the quarantine lifecycle, which is what let this
  ship past `tests/test_cdx8_skill_quarantine.py`.
- [x] **Generated command names are sanitized before they become code** — `command_name` arrives
  as untrusted LLM output (field 3 of a `[learn:…]` block, `orchestrator.py`) and was string-
  substituted into generated Python source, so a quote + newline escaped the `register_command`
  string literal. New `_safe_command_name()` coerces it to a bare identifier *after*
  `quarantine.detect_injection` has seen the raw value (sanitizing first would blind the scanner).
  Ratcheted for hostile inputs: generated `main.py` must always compile.
- [x] **Catalog ratchet: a documented command must resolve, or be a declared seam** — every
  `## Commands` entry in `skills/*/SKILL.md` must map to something callable. `skills/weather`
  stays manifest-only *on purpose* (`INTENTIONALLY_SEAM`, live weather comes from the plugin
  path) and is exempt through that one existing escape set — implementing it was tried and
  reverted, because a live `main.py` makes `parse_command("weather X")` short-circuit the agent
  path with a raw wttr.in string and removes the repo's only intentional-seam exemplar
  (`tests/test_h27_capability_verification.py::test_intentional_skill_seam_cannot_be_promoted`).
  A *new* manifest-only skill now has to be a conscious `INTENTIONALLY_SEAM` entry, not a silent
  addition.
- [x] **Removed the stale committed `skills/user_greeting_055711/`** — a pre-CDX-8 artifact with
  no `PENDING_REVIEW` marker, so `loader.py:247` never quarantined it: it was `exec_module`'d
  in-process in every install and warned on every boot. It was also cited as the reference
  pattern in `.opencode/plans/skill-api-corrected.md` and `docs/internal/gemini_architecture_prompt.md`,
  propagating the broken shape; both now point at `skills/pm/`.

---

## 🤝 Handoff — Fable last-day review (2026-07-07)

> Full review, verdict, and rationale: **[docs/handoff-fable-2026-07-07.md](docs/handoff-fable-2026-07-07.md)**
> (ground truth verified: CI green on main, 0 open PRs, 3,820-test suite green; Hermes v3 plan
> **APPROVED with notes** — §5 of the handoff). The two lanes below are the same items, tracked
> here so they surface in any "what's next" conversation. Tick them here AND in the handoff doc.
>
> **2026-07-14 update:** A9 "tag 1.0.0" now sits behind the **expanded** 1.0 gate — the proof
> track (A1–A7, unchanged) **plus** the AI-OS capability program (ORIZONT 27–33 below /
> [NERVA_VISION.md](NERVA_VISION.md)). Code/harness completion does not satisfy the real-host
> v1 bars by itself: A8 names the owner-only hardware proof explicitly. A1–A8 are blocking and
> remain the critical path.

**Lane A — owner critical path (ordered; delivered via PR #634):**

| # | Item | Status |
|---|------|--------|
| A1 | ⭐B0 governed-autonomy demo + full `docs/MANUAL_TESTING.md` pass on the RTX box. **Instrument ready (#728):** `docs/TEST_MANUAL.md` — 15 chapters giving the step-by-step depth behind every checklist row, plus `docs/COWORK_QA_RUNBOOK.md` §3b (the R1–R9 pass from the 2026-07-24 run) and **§3c (S1–S6, the 2026-07-27 run-2 findings)**. **Run 2 executed (2026-07-27, RTX box)** — findings fixed, re-proof pending on the box. **Chapter 15 (`ADV`) is new and unexecuted:** adversarial-audit verification + a missing-code/missing-feature ledger; §8a of the runbook is its launch prompt. | ⬜ **the gate** |
| A2 | 72h soak (0.63) + record AUD-0 / H23.23 | ⬜ |
| A3 | Dependabot re-triage — 19 open alerts on main (4 high, 2026-07-07) | 🟢 agent half done in #634 — local re-audit enumerated everything without the UI: fixed frontend `undici` (high, dev-chain) and worldview/mcp `hono`+`esbuild` (high+moderate), both trees now 0 vulns with suites green; mobile attempt reverted after it broke `tsc` (expo-audio type surface — the device gate is real). Owner tail: worldview 2 moderates (in-next postcss, wait for next 16.3), mobile Expo SDK upgrade on a device, dismiss stale alerts in UI |
| A4 | GitHub settings batch (SEC-4 required checks · CQ-2 dismissals · CQ-3 paste · repo metadata) | ⬜ |
| A5 | License flip MIT→Apache-2.0 + TRADEMARKS.md | 🟢 prep done in #634 — `TRADEMARKS.md` live, CONTRIBUTING relicense grant added, canonical Apache-2.0 staged in `docs/legal/`; the flip itself is 3 owner commands (steps in OWNER_TASKS), timing per LICENSE_DECISION = just before v1.0 |
| A6 | Demo video (60s) + publish landing (dev half ✅ #512) | ⬜ |
| A7 | Recruit 1–3 design partners; north-star on a non-owner install ≥2 weeks | ⬜ |
| A8 | **AI-OS v1 owner-host proof** — complete `docs/MANUAL_TESTING.md` §N on real hardware: installed Playwright Chromium + Windows UIA browser/desktop actuation; real Home Assistant state + device/room/occupant/presence graph + governed device actuation; consented Frigate event → house/memory/ambient flow; presence-aware Media Director delivery on ≥2 non-chat output surfaces/device classes; one approved acquisition→reuse loop. Record redacted audit/task/device evidence; hermetic reality packs alone do not clear this gate. **⚠️ Parts of §N are not runnable as written (#728), being unblocked by the finish-line run:** ✅ **A8-i done 2026-08-02** — the H32 acquisition loop now has a product trigger, `POST /api/acquisition/{request_id}/drive` (admin; reuse-first, honest `_degraded` refusals; AIO-038 rewritten to use it, no Python shell). ✅ **A8-iii done 2026-08-02** — `JARVIS_MEDIA_DRIVERS=local_file` binds the shipped `LocalFileMediaDriver` (real durable state through the present/verify/restore/duration rails; kind `local`; whole-list fail-closed registry in `_get_director()`; the audible/visible half still needs owner hardware). ✅ **A8-ii done 2026-08-02** — `target:"presence:auto"` resolves the owner room's default device, gated on a FRESH `present` signal from the H34.2 owner-presence store (temporal) + `JARVIS_MEDIA_PRESENCE_ROOM` (spatial, default-off); idle/away/stale/unset → honest `presence_unknown`; a registered device id can never shadow the sentinel. Still open: **A8-iv** — `ungoverned_actions == 0` is measurable only inside the hermetic reality packs. A first live-counter attempt (QA4) was written and **withdrawn 2026-08-02 for a design flaw its own full-suite run exposed** (a mediation ContextVar that never resets masks a later task's bypass within one tick, and cannot bridge enqueue→execute at all, so it under-reports breaches); the correct design — persist the kernel decision on the task at `govern_enqueue` and read that stamp at the worker seam — plus what was sound and reusable is written up in [`docs/superpowers/plans/2026-08-02-qa4-ungoverned-counter-park.md`](docs/superpowers/plans/2026-08-02-qa4-ungoverned-counter-park.md). Full list with `file:line` in that chapter's **Open gaps**; media-hardware purchase can be scheduled once C3/C4 merge. | ⬜ **blocking owner/live gate** |
| A9 | Tag 1.0.0 (only after A1 + A7 + A8 and every other open owner gate) | ⬜ |

**Lane B — engineering tail (any AI session; one item = one PR, default-off):**

| # | Item | Status |
|---|------|--------|
| B1 | Hermes v3 Phase 2 — context compression maturity | ✅ done in #634 (2026-07-07) — `keep_first` leading-turn protection, hermes structured summary template, iterative summary-merge (`prior`/`covered`), and an opt-in **strict-local** LLM summarizer (`memory.compression_summarizer`, uses `LLMRouter.local_backend` only, degrades to the deterministic digest). Defaults byte-identical; `tests/test_context_compression_phase2.py` (+12) |
| B2 | 0.19 First-Run Command Center (activation for design partners; seams in H23.20) | ✅ done in #634 (2026-07-07) — `GET /api/onboarding/command-center` (user-guarded, one fetch: `/readyz` snapshot + version, model backend truth, H23.20 wizard state, honest `first_actions` with backend-derived `ready`/`reason`) + HUD `CommandCenterPanel` (new **Start** Console cluster; "say hello" drives a real `/chat` turn and records the `test_chat` funnel step). Red/green: `tests/test_first_run_command_center.py` (+4) + `command-center-panel.test.tsx` (+4); parity/openapi/auth snapshots reseeded; typegen schema regenerated |
| B3 | AUD-14 tail — remaining raw env-read slices (template: #592–#622) | 🟢 re-audited 2026-07-07 (in #634): **zero** unsafe parses remain — no `int()`/`float()`/`json.loads()` on raw env, no ad-hoc boolean truthiness (ratchet `test_o26_p2_env_config.py` green); ~104 plain `env_str`-equivalent string reads left = cosmetic, migrate opportunistically in files you already touch |
| B4 | M2.4 live-eval lane | 🟢 **ci-small-model lane shipped in #634 (2026-07-07, owner-approved)** — `companion_eval --live-model` runs the golden suite through any OpenAI-compatible endpoint (live generation, deterministic rubric scoring, preflight probe so infra failure ≠ score 0, results recorded to the DatasetStore) + an opt-in `live-small-model` job in `eval-nightly.yml` gated on repo var `JARVIS_EVAL_CI_SMALL_MODEL=1` (Ollama + qwen2.5:0.5b on the runner; advisory, honestly labeled). `tests/test_companion_eval_live_lane.py` (+3, in-process endpoint double). Owner: flip the repo variable to activate; the owner-box fidelity lane (`JARVIS_EVAL_LIVE`) stays separate |
| B5 | Non-v0 inbox channels (email/WhatsApp) | 🟢 **email half done in #634 (2026-07-07)** — `email` joins `SUPPORTED_INBOX_CHANNELS`: inbound IMAP messages become inbox threads whose reply metadata carries the SMTP kwargs (`to` aliased from `from_addr`, `subject`), the `CHANNEL_REPLY_CONTRACT` gains the email reply-target branch, and `EmailChannel` now passes `sender=` so the H12.19 pairing gate applies to inbound email. All against test doubles (`tests/test_email_inbox_transport.py`, +6); owner live SMTP/IMAP validation remains. **WhatsApp stays parked** (bridge hardware) |
| B6 | Maintenance runbook ("if the owner disappears a month", REVIEW_YEAR_ONE §9.7) | ✅ drafted in #634 — [docs/MAINTENANCE_RUNBOOK.md](docs/MAINTENANCE_RUNBOOK.md), owner to verify the `[owner: verify]` marks |
| B7 | Hermes v3 Phases 3/5/6 live wiring (file-RPC exec · gateway sessions · cron) | ⬜ on-demand only — primitives merged, wire behind real pull |

---

## 📣 Alpha signals — FB tester call (2026-07-10)

> Prima postare personală de recrutare a explodat: **39.6k afișări, 67 comentarii, 17 salvări,
> 0 reacții negative** (ținta era „2–3 prieteni"). Triaj lead-uri + kit de răspuns:
> [`marketing/alpha-testing/2026-07-10-fb-response-triage.md`](marketing/alpha-testing/2026-07-10-fb-response-triage.md);
> FAQ onest reutilizabil: [`marketing/alpha-testing/FAQ.md`](marketing/alpha-testing/FAQ.md).
> Alimentează direct **Lane A / A7** („Recruit 1–3 design partners"). Docs de marketing ✅ livrate;
> itemii de produs de mai jos rămân de decis. **Consumer first-run follow-up (2026-07-20):**
> Command Center now projects three outcome-oriented starter packs from live model/folder/plugin
> honesty (`READY NOW` / `NEEDS SETUP`) and explains qualified privacy + read-only effects without exposing
> credentials; this is the first product slice of the consumer-grade Nerva direction.

| # | Semnal din comentarii | Item | P | S |
|---|---|---|---|---|
| FB1 | „Merge pe M4?" (Tudor ML) — `install.sh` acoperă deja macOS, dar nu e în matricea de suport | **Apple Silicon în matricea de suport alpha** — smoke pe M-series (LM Studio/Ollama, memorie unificată) + un rând în README/FAQ. Cerere reală de la Mac-uri. | P2 | 3 |
| FB2 | „cheia rămâne locală sau trece prin serverele voastre?" (×2) — cea mai repetată obiecție | **Trust one-pager: API-key locality** — o pagină scurtă (sau secțiune README/`SECURITY.md`) care arată drumul cheii (`.env` → direct la furnizor, fără relay) + cum se verifică. Pre-întâmpinat deja în FAQ + copy. | P2 | 2 |
| FB3 | „folosește subscripția în loc de API" (Cristi Simion) + confuzia Plus≠API (recurentă) | ✅ **Done 2026-07-20** — Command Center now explains that ChatGPT Plus / Claude Pro subscriptions do not include API access whenever a starter outcome is held by missing model/API setup; the FAQ remains the long-form source. | P3 | 2 |
| FB4 | „local-only pe 8GB — chiar e utilizabil?" (Robert Olah) | **Benchmark onest 8GB VRAM** — un tabel „ce merge decent pe 8/12/16/24GB local vs. hybrid", publicat, ca să calibrăm așteptările testerilor. Leagă de M2.4 live-eval. | P2 | 5 |
| FB5 | „fă-l TUI-only, waste of memory pe 8GB" (Bogdan G. Fuerea) | **Mod headless / TUI** — rulare fără UI-ul greu (deja e posibil local/cloud/hybrid; de expus explicit un profil headless). Feedback de early-adopter, nu blocker. | P3 | 5 |
| FB6 | OpenRouter + OpenAI-compatible + local (Stefan Vintila) — **deja livrat** (`agents/core/llm/openrouter.py`, `/model`) | doar **discoverability**: pune-l în README/FAQ ca feature vizibil (userii nu știu că există). | P3 | 1 |

> **Surfaced în docs canonice 2026-07-11 (PR follow-up):** **FB2** cheie-API locală → `SECURITY.md` §„API keys & cloud calls"; **FB1** Apple Silicon + **FB6** OpenRouter/OpenAI-compatible + **FB5** profil `headless` → `docs/COMPATIBILITY.md` matrice + README Hardware; **FB4** schelet benchmark VRAM onest (owner umple numerele măsurate) → `docs/HARDWARE_BENCHMARKS.md`; **FB3** subscription≠API este în FAQ + SECURITY + Command Center. **FB5** e și cod: profil `headless` real în `system_profiles.PROFILES` (+test). Rămâne owner/cod: FB4 numerele măsurate (hardware).

**Non-produs (owner/GTM):** capacitatea de suport 1:1 e depășită de volum → ține ținta la **1–3
instalați** (restul pe listă de așteptare). Candidați contributor din fir (Iulian Tu, Stefan Vintila)
→ `CONTRIBUTING.md`. Detalii + kit de răspuns în doc-ul de triaj.

---

## Version Roadmap

| Version | Target | Milestone | Items |
|---------|--------|-----------|-------|
| **0.5-beta** | 🟢 Live | Foundation complete. All H1–H4, cross-cutting, security, bugs done. | H1–H4, Sprint 0, Cross-cutting, Sec, Bugs |
| **0.6-beta** | 🟢 Live | Howard fine-tuning + voice clone + continuous ingestion | H5.1 |
| **0.7-beta** | 🟢 Live | Mobile PWA + i18n + UI Overhaul | H5.2, H5.3, H5.4 |
| **0.8-beta** | 🟢 Live | Performance & robustness + multi-agent workflows | H5.5, H5.6 |
| **0.9-beta** | 🟢 Live | New integrations + agent marketplace | H5.7, H5.8 |
| **0.9.1-beta** | 🟢 Live | Recall cu embeddings reale + perf cale fierbinte | H7.1–H7.5 (perf) |
| **0.9.2-beta** | 🟢 Live | Hardening complet, CI/CD, memorie personală, cost analytics, onboarding | H7 (11 iteme) + H8 (7 iteme) + BUG-1 |

> The `0.5-beta…0.9.2-beta` rows above are **provenance** (when each capability first landed).
> The line below is the **forward plan** — there is no separate "audit gate" version; the version
> number *is* the roadmap. **1.0 is a real destination**, not the current near-done state.
> **Gate expanded 2026-07-11 (owner decision):** 1.0 ships only when **both** halves are done —
> **(a) the proof track** (the 0.13–0.20 themes + ⭐B0 + 72h soak + design partners) **and (b) the
> AI-OS capability program** (v0.21–v0.27 / ORIZONT 27–33, six pillars at their v1 bar —
> [NERVA_VISION.md](NERVA_VISION.md) §10). Manual testing/audit is the *release step that tags a
> version*, not a roadmap item; owner-only items (license, naming, GitHub settings) live in
> [docs/OWNER_TASKS.md](docs/OWNER_TASKS.md).

### Forward roadmap — the version is the plan (theme-per-minor)

> **Version labels vs theme IDs:** rows in this table are **release versions**, always written
> three-part (`0.16.0`, `v0.21.0`). The Competitive-Gap section below uses bare two-part
> **theme-IDs** (`0.21`, `0.46`) which are NOT versions — when citing a theme in new text, write
> **`T-0.21`** to disambiguate. Existing text is not mass-renamed.

`⚠️` = surfaced by the 2026-06-21 productionization research (was not previously tracked); now in **H23** below.

| Version | Theme | Scope highlights |
|---------|-------|------------------|
| **0.10.0** | Baseline | Everything delivered to date: H1–H21 + ORIZONT 22 + WorldView O19 + CLN-3 batch 2; north-star instrumented; **single-user** |
| **0.11.0** | 🟢 **Finish the refactor (done, #296)** | CLN-3 **complete** — `web.py` 4,636→1,282 LOC, 233→9 inline routes across 45 per-domain routers (304-route surface byte-identical, parity-guarded). CLN-2 substantially done — `PluginManager`+`llm_control`+`cognition_trace` extracted; orchestrator 1,620→1,456 LOC (remaining inline = the BUG-5 request pipeline, not safely extractable). |
| **0.12.0** | **Harden what shipped (here now)** | ORIZONT-22 review fixes (#294, merged); #292 argus governed-facade wiring; #279 MCP route-tools harden/remove; TASK-3 cross-channel taint-tracking |
| **0.13.0 ⚠️** | Agentic safety completeness | step/recursion + token/time **budgets + loop detection**; **model-version pinning & reproducibility**; **kill-switch in the HUD** + credential quarantine; eval/regression harness as a **release gate**; audit-log verify UI + secret redaction |
| **0.14.0 ⚠️** | Upgrade & data durability | **backup/restore** + restore drill ✅ (#302); **data export** ✅ (#303, CLI); **DB schema-migration framework** ✅ (#305, H23.7); **delete/forget** ✅ (#306 + #315, `/api/admin/forget` — purge completeness done **AUD-2**: erases the memory subsystem at rest, endpoint **and** CLI; backup-first snapshot encrypted once a key is set, **AUD-1** #309); retention defaults ✅ (#317, H23.10); export HTTP surface ✅ (#315, H23.9) |
| **0.15.0 ✅** | Operability & distribution | health/readiness endpoint ✅ (H23.11, `/healthz`+`/readyz`) + signal handlers/graceful shutdown ✅ + log rotation ✅ (H23.11); graceful **local-LLM-down** everywhere ✅ (H23.12, split-timeout + clean degraded reply); systemd/service templates ✅ (H23.15, `deploy/`); **release artifacts** ✅ (H23.13 — tag→source bundle + SBOM + checksums + optional GPG sign, `docs/RELEASE.md`); **semver compatibility contract** ✅ + supported-versions matrix ✅ + deprecation policy ✅ + platform matrix ✅ (H23.14, `docs/COMPATIBILITY.md`) |
| **0.16.0** | HUD depth + observability UI | TASK-2 ~37 surfaces incl. **north-star panel** + **network monitor** ✅ (watch LOCAL_ONLY make zero calls — egress data layer + `GET /api/admin/network/calls` + Console panel, H23.16); LIVE/SEED indicators ✅; OpenAPI typegen/diff gate ✅; plugin-gated mode base wiring ✅ (#505); P3.2 reconciliation guard ✅ (#507); remaining tail = owner live-data/plugin setup; channel inbox transport v0 ✅ (#551) |
| **0.17.0** | Local ceiling + velocity | H22.4 concurrency, H22.5 model-manager LRU, H22.9 agent-native routes, constrained-decoding tail |
| **0.18.0 🖥️** | Digital twin & fine-tune (**GPU-gated**) | H12.14 fine-tuned model, H13.3 speculative decoding, TASK-1 Howard first real run |
| **0.19.0 ⚠️** | Reach, quality & user docs | mobile parity tail (H18); **quality gates** (E2E, load/soak, a11y, i18n, browser+mobile matrix); **user docs ✅** (USER_GUIDE/FAQ/UPGRADE — H23.18; trust docs THREAT_MODEL/PRIVACY/SECURITY/NOTICE/SBOM — H23.19); **onboarding wizard** + activation funnel + cold-start error guidance |
| **0.20.0 ⚠️** | Product-proof | design-partner program (recruit 1–3) — *in-app **feedback/NPS** + program doc ✅ H23.21*; support channel + SLA; north-star **measured on real usage**; landing page + demo |
| **v0.21.0** 🧠 | **Capability plane** (AI-OS Phase 1) | ORIZONT 27 (Nerva Program A) — Capability Registry v1 + unified Action API (`perform()`) + verification hooks + earned autonomy; extends O24 K/V, no parallel system |
| **v0.22.0** 🖱️ | **Operator** (AI-OS Phase 2a) | ORIZONT 28 (Nerva Program B) — real browser driver (Playwright behind GovernedBrowser) + desktop actuation + terminal-target abstraction + the API→CLI→UI→visual router; **unpark wave 1** |
| **v0.23.0** 📺 | **Media Director** (AI-OS Phase 2b) | ORIZONT 29 (Nerva Program C) — `media_player` abstraction + Chromecast + the `present()` fabric + session etiquette; **unpark wave 2** |
| **v0.24.0** 🏠 | **House Brain** (AI-OS Phase 3) | ORIZONT 30 (Nerva Program D) — Home Assistant state adapter + device/room/occupant graph + presence + governed actuation; **unpark wave 3** |
| **v0.25.0** 📷 | **Camera Intelligence** (AI-OS Phase 4) | ORIZONT 31 (Nerva Program E) — privacy contract first, then RTSP/ONVIF ingest + local detection + event index + NL clip retrieval |
| **v0.26.0** 🌱 | **Capability Acquisition** (AI-OS Phase 5) | ORIZONT 32 (Nerva Program F) — the gap→search→research→generate→sandbox→approve→register→reuse loop |
| **v0.27.0** 👁️ | **Ambient Intelligence** (AI-OS Phase 6) | ORIZONT 33 (Nerva Program G) — monitor framework + the ignore/remember/monitor/act-silently/ask/interrupt ladder |
| **1.0.0** | 🎯 **The governed Personal AI OS — owned & proven** | **proof track done** (H23 spine + ⭐B0 + 72h soak + 1–3 partners ≥2 weeks) **+ six pillars at their v1 bar** ([NERVA_VISION.md](NERVA_VISION.md) §10) **+** owner legal/brand; manual-test/audit pass → tag |

> **The active execution ORDER for what remains is ORIZONT 25 — M1→1.0** (2026-07-02, section below):
> milestone tables + a model-agnostic execution protocol + the companion-quality charter, backed by the
> [execution blueprint](docs/superpowers/specs/2026-07-02-orizont25-execution-blueprint.md). It sequences
> the remaining slices of the versions above (0.12–0.20) — it does not renumber them. The capability
> minors **v0.21+** may interleave with the proof-track tail — order can adapt, **gates cannot be
> skipped** (MOONSHOT §4).
>
> **The program that organizes 0.11→1.0 is ORIZONT 24 — "AI-OS"** (decided 2026-06-23, section below): an
> **Action Kernel** (every agent action mediated, budgeted, revocable) + a **Verification Fabric** (each
> capability proven against reality before it may claim "done") + the four live capability packs, all on the
> H23 spine. Phase A of it = the AUD-\* hardening cluster.

---

## 🧭 Competitive-Gap Roadmap (product depth) — folded in from the uploaded plan

> The owner's 2026-06-21 **Competitive Gap Plan** (themes `0.19`–`0.63` + gates, derived from 24 OSS
> "Jarvis"/agent repos) is captured here so this file stays the **single source of truth**. These ~48
> themes are **product-depth slices, NOT a release sequence** — the version line above (the H23 spine)
> is the real path to 1.0; the numbers below are **theme-IDs**, and many are already DONE, so they
> can't be a monotonic version order. Each theme maps onto an existing version/H-item. Status is grounded
> in the code audit, re-verified against HEAD on 2026-06-25:
> [`docs/research/2026-06-25-roadmap-vs-codebase-reaudit.md`](docs/research/2026-06-25-roadmap-vs-codebase-reaudit.md)
> (supersedes the [2026-06-21 baseline](docs/research/2026-06-21-roadmap-vs-codebase-audit.md)).
> **Headline: ~85% already seeded; only 6 are truly greenfield.** Status keys: ✅ done · 🟢 in open PR ·
> 🟡 partial · 🌱 seed (module exists, feature mostly unbuilt) · ⬜ missing.
> **Citation convention (2026-07-11):** these are **theme-IDs, not versions** — in new text cite
> them as `T-0.21`, `T-0.46` etc.; release versions in the roadmap table above are always three-part.

| Theme | Status | What exists / the bounded gap | Maps to |
|-------|--------|-------------------------------|---------|
| 0.19 First-Run Command Center | ✅ done (#634, 2026-07-07) | `GET /api/onboarding/command-center` + HUD `CommandCenterPanel` (Start cluster): install health (`/readyz` snapshot + version) + model truth + wizard state + honest first actions in one read; "say hello" drives a real `/chat` turn and records the funnel step | H23.20 |
| 0.20 Jarvis Vault | 🟡 partial → **encrypted vault core ✅ (store + quotas + retention + forget hooks)** | **NEW `agents/core/vault.py`** — the missing data-mgmt flagship: a local **encrypted-at-rest blob vault** on the AUD-1 `SecretStore` cipher (Fernet-or-fallback, same `JARVIS_SECRET_KEY`/keyfile 0600 discipline). **Always ciphertext on disk** (no plaintext mode to misconfigure); index carries metadata only; reads are **integrity-verified** (tampered blob raises, never returns garbage); **quotas refuse, never evict** (a vault is not a cache — 1 TB ceiling, per-item 1 GB, 10k items, all injectable); **retention** via per-item `expires_at` + deterministic `sweep(now)` that reports exactly what it removed (H23.10 discipline); **forget-me hooks** `clear_memory()` (live, pre-backup) + `purge()` (at-rest) mirroring the canvas/purge pattern. `tests/test_vault.py` (+7: roundtrip/no-plaintext-on-disk, tamper→raise, quota-refusal, sweep, cross-instance + wrong-key, forget hooks, honest missing). **Persistence boundary hardened ✅ (#660, 2026-07-12)** — the plaintext, unauthenticated catalog is replaced by a root-bound **authenticated encrypted `index.enc`** (public `SecretStore.encrypt_bytes`/`decrypt_bytes`); full catalog-schema validation (safe generated IDs, hashes, byte counts, finite timestamps); all catalog/quota mutations serialized via an in-process lock **plus portable OS file locking** (fcntl/msvcrt) with authoritative-catalog reload before mutation (no live-instance lost updates — proven by a real two-process max-items race test, exactly one writer wins); blob/catalog writes atomic + restrictive-permission + **symlink-safe** (lock/index/blob/temp paths rejected if symlinked) with crash-residue reconciliation; corrupt/swapped/injected/missing-blob/tampered catalogs **fail closed** (no silent empty-catalog fallback); `clear_memory()→purge()`/`put()` safe in-instance; purge enumerates every contained blob independently of the in-memory/index catalog. `tests/test_vault_hardening.py` (+~23) + `test_vault.py` adjusted. *(Remaining 0.20: router/HUD surface + wiring into export #303 and the forget flow — same governed pattern as canvas.)* | H23.10 |
| 0.21 Offline Knowledge Packs | 🟡 partial → **pack manifest · verify · governed installer ✅** | **NEW `agents/core/knowledge_packs.py`** over the H12.2 drop-folder indexer: a pack = folder + `pack.json` manifest with per-file SHA-256 (`build_manifest`/`write_manifest`/`load_manifest`, posix-relative, bounded, deterministic); `verify_pack` names EVERY discrepancy (`missing`/`modified`/`unexpected` — never a silent pass); `install_pack` verifies FIRST and **refuses tampered or manifest-less packs** (nothing partial enters memory), then indexes through the injected `LocalDocsIndexer`. No downloads — fetching a pack stays owner-gated; this manages packs already on disk. `tests/test_knowledge_packs.py` (+6). *(Remaining 0.21: curated pack catalog + owner-gated fetcher.)* | 0.21 |
| 0.22 Appliance Install/Update | 🟡 partial → **no-telemetry gate ✅ (scoped)** | `install.sh`,`start.sh`,`docker-compose.yml`, **release bundles + SBOM + checksums + optional sign** ✅ (H23.13). **No-telemetry gate ✅ (Max «quiet-quill», round-2)** — `PRIVACY.md`'s claim ("zero outbound telemetry, no analytics beacon/crash reporter") had **no gate**; pytest-socket is test hygiene (AUD-10), not a product proof, and every egress call site here is best-effort so a blocked connect is swallowed and stays invisible. **NEW `tests/test_no_telemetry_proof.py`** records non-loopback egress across **TCP connect, connected AND unconnected UDP (`sendto`/`sendmsg`), and raw sends**, plus **pre-exec refusal of recognised network-tool child processes** (`subprocess.Popen`/`os.system`/`os.popen`, incl. `sh -c`/`env`/`shell=True`/`cmd /c`/PowerShell cmdlets), while booting the real lifespan, holding an **authenticated** `/chat` turn (asserted past `_user_guard`, since a 403 would mean the handler was never entered), and shutting down. Measured: **zero** attempts. **Round-1 review (#939) found a false negative** in the first version (connect-only spy + boot-only exercise): unconnected UDP and request-path beacons were invisible. Both are now regressions that fail against the old approach, and the gate was red-proofed end-to-end against a UDP beacon planted on `/api/status` (caught, removed). **Scope is stated, not implied** — in-process only (a general guarantee needs OS-level egress deny), and the static half is an explicit *known-vendor ratchet*, not protection against arbitrary/dependency telemetry; **child-process egress is bounded by a denylist, not proven absent** (a renamed binary or an uninstrumented spawn API would evade it). *(Remaining 0.22: **uninstall**.)* | H23.13/15 |
| 0.23 Hardware Benchmark & Profiles | 🟡 partial | `bench.py`,`llm/model_manager.py` (VRAM) / RTX scoring + mode profiles (GPU-gated) | 0.18 |
| 0.24 Voice Hotkey & Dictation | 🟡 partial → **dictation cleanup core ✅** | `voice/{wake_word,stt,pipeline}.py` transcribe raw text; nothing cleaned it. **NEW `agents/core/voice/dictation.py`** — a pure, offline, **bilingual RO/EN** post-processor: strips whole-token fillers (`um`/`uh`/`ăă`/`deci`…) + phrase hedges (`you know`/`i mean`), collapses stutter repetitions, applies the spoken-punctuation convention (`period`→`.`, `new line`→break, `virgulă`→`,`), and capitalizes sentences. **Conservative** (matches only whole tokens — drops `um`, keeps `umbrella`; punctuation commands opt-in) + **honest** (returns `removed` counts so the edit is inspectable) + bounded. `tests/test_dictation.py` (+11). **Wired into the live STT path ✅ (2026-07-18):** `voice.dictation_cleanup` (default-off) applies `clean_dictation` inside `POST /api/voice/stt` with inspectable removed-counts in the response; sentinel transcripts (`[silence]`…) pass through untouched. / remaining (owner/host-gated): the hold-to-talk **hotkey** (OS-level, like 0.64) | — |
| 0.25 Desktop Control Pack | 🟡 partial → **app-launch + OS-action allowlist core ✅** | `GovernedDesktop` (H15.3) already gates *how* a step runs (read-only inline / mutating approval-held / injection abort) but not *what* may be launched or controlled. **NEW `agents/core/desktop_control.py`** is that front door: a strict, pure **allowlist** turning a high-level request into a governed desktop step, refusing anything off-list with a reason. **Not passthrough** — apps are named by a **canonical key** (`browser`/`terminal`/`editor`…), never a binary path or shell string, so the pack can't be an arbitrary-exec vector (a path/`rm -rf`/`$(…)`/`C:\…` isn't a key → refused; keys are also regex-guarded against separators/metachars). **Validated OS actions** (`volume_set`/`brightness_set` clamp 0–100, `volume_mute` wants a bool, `media_*`/`lock_screen`/`sleep_display`, `screenshot` read-only) — unknown action or out-of-range value refused, never coerced. **Recording consent-flagged** (always mutating + approval + explicit privacy note, never auto-started). **Plans, never actions** — `DesktopControl.run` forwards admitted plans to `GovernedDesktop` (approval + injection guard) and reports the allowlist-refused ones (never silently dropped). `tests/test_desktop_control.py` (+14). / remaining (owner/host-gated): the real injectable VM/desktop driver + the host key→launcher map, **Action-Kernel recheck + audit-log entry at execution time**, **model ToolRPC registration** (so an agent can call it), a user-facing control surface + HUD parity tracking, and `browser_agent.py` recording wiring | — |
| 0.26 Capture Inbox | 🟡 partial → **inbox view ✅ · export ✅** | `passive_capture.py`+`routers/capture.py` + **HUD `CapturePanel`** (HUD-v3: the captured stream, each item's redacted preview shown + individually deletable + clear-all — the privacy promise made visible) + **`PassiveCapture.export()`/`write_export()`** (the data half of "phone export"): a portable, JSON-safe snapshot `{version, exported_at, surface, count, surfaces, records}` of the capture inbox, optionally filtered by surface. Records carry **only already-redacted previews + metadata** (secrets are scrubbed at `ingest` and raw content is never stored) so the export can't leak a secret — it's the same data the inbox exposes via `list`, packaged for off-device transfer; `write_export(dest)` dumps it to a file. `tests/test_h12_7_capture.py` (+4: packages redacted records, surface filter, empty, write-to-file + secret-never-present). / remaining: the host-side phone transfer + transcript sync | — |
| 0.27 Local VLM Eyes | ✅ done | `llm/vlm.py` + `/api/vlm/describe` | — |
| 0.28 Voice Persona Studio | 🟡 partial | `cognition/persona.py`,`voice/tts.py`,`ttsStream.ts` / consent, barge-in→HUD (BUG-2b.3) | TASK-4 |
| 0.29 Native Launcher | 🟡 partial | `desktop/src-tauri/tauri.conf.json` (Tauri shell) / PWA, signed installers | 0.15 |
| 0.30 Context Compression | ✅ done | `context_compressor.py` wired in `routers/tools.py` | — |
| 0.31 Code Intelligence MCP | 🟢 **done (indexing backend)** | new `agents/core/codeintel/` — a pure, offline **AST symbol index** over the project's own Python source: `build_index(root)` walks `*.py` (skipping vendored/cache dirs) and extracts module functions / classes / methods with kind + relative path + line + **first docstring line** (structure, **not file contents**); a syntax-error file is recorded under `errors`, never fatal. `search_symbols(index, q, kind=, limit=)` does a transparent substring match ranked exact-name-first. Lazily-built **cached** project index (772 files / 7.8k symbols / 0 errors on HEAD). Served at `GET /api/codeintel/{stats,search}` (user) + `POST /api/codeintel/reindex` (admin). **Now also an MCP route tool** (the "Code Intelligence **MCP**" part): `codeintel_search` joins the read-only `ROUTE_TOOL_ALLOWLIST` (guard pinned to `route_auth.json` by the 0.36 gate), so an agent can call `route_codeintel_search` to locate code — under the existing default-off `JARVIS_MCP_ROUTE_TOOLS` kill-switch. A module-level `routers/codeintel.search_payload` is shared by the HTTP route + the tool (plain signature → reflectable in-process dispatch). `tests/test_codeintel.py` (+6) + `tests/test_codeintel_mcp_tool.py` (+2). | — |
| 0.32 Mission Workspaces | ✅ done | `autonomy/missions.py` + `routers/missions.py` (#301) | — |
| 0.33 Subagent Gateway | ✅ done | `subagents.py` + `a2a.py` + `autonomy_coordinator.py` | — |
| 0.34 Workflow Runtime Upgrade | 🟡 partial → **run-persistence + pruning done** | `workflows/engine.py` (timeouts, bounded concurrency, recursion cap) + **NEW `workflows/run_store.py`**: an **opt-in, default-off** persistent store for workflow **run history** (it lived only in an in-memory `deque`, lost on restart). `WorkflowRunStore` is a **bounded** (`max_keep`, oldest pruned) atomically-written JSON array; the engine **seeds** its ring from it on init and **records** each run — but only when a store is attached (`JARVIS_WORKFLOW_PERSIST=1`, else `None` → behavior byte-identical). Corrupt/missing files degrade to empty, never crash. `tests/test_workflow_run_store.py` (+11). **Durable pending-run queue + retry ✅** — NEW `workflows/pending_queue.py`: `WorkflowPendingQueue` is the other direction (enqueue runs that survive a restart), a bounded, atomically-written JSON queue mirroring `run_store`'s safety. A failed run **retries with exponential backoff** (`next_at` pushed out, capped) until its `max_attempts` cap, then parks as `dead` (never silently dropped); `due(now)`/`complete`/`fail`/`list`/`stats`. The engine gains an **opt-in** `drain_pending(queue, resolve, now=)` that claims due items → runs → completes or retries (a crashing run or unknown pipeline is retried/dead, not lost); `resolve(pipeline_id)→Pipeline|None` keeps the engine decoupled from the registry. **Default path byte-identical** — nothing enqueues or drains unless a caller wires it; binding the drain into the autonomy-coordinator tick is **now done ✅** — `AutonomyCoordinator._drain_workflow_pending()` runs once per tick, **opt-in** behind `JARVIS_WORKFLOW_PERSIST` (unset → the tick is byte-identical, no queue even constructed), resolving pipeline ids through the live `workflow_registry.get` and draining due items via `WorkflowEngine.drain_pending` (a drain hiccup is swallowed so it can't break the tick; the queue is cached across ticks). `tests/test_autonomy_coordinator_pending_drain.py` (+4: noop-when-unset, drains+caches-when-set, noop-when-engine-absent, hiccup-swallowed; the run/retry/dead mechanics stay covered by the pending-queue tests). `tests/test_workflow_pending_queue.py` (+12: persistence, due-by-next_at, retry→dead at cap, capped backoff, terminal-first pruning, corrupt-safe, drain complete/retry/dead/crash/unknown-pipeline).* | 0.17 |
| 0.35 Prompt Registry | ✅ done | `soul_versioning.py` (commit/diff/rollback + A/B) | — |
| 0.36 Agent-Native Action Manifest | ✅ **done** | `mcp/route_tools.py` + web wiring works, **now unseamed**: each allow-list spec (read `RouteToolSpec` + mutating `MutatingRouteSpec`) declares its `guard`, and a new parity gate `tests/test_route_tools_auth_parity.py` pins those declarations to `tests/_snapshots/route_auth.json` (the SEC-2 source of truth) — CI now fails if the manifest drifts from a route's real guard, exposes a non-existent path, surfaces an **admin** route as an agent **read** tool, or lists an **open** (unauthenticated) **write** tool. `route_auth.json` is the single source of truth the agent manifest is checked against (+3 tests). | 0.12 (#279) |
| 0.37 Memory Ingestion Lab | 🟡 partial → **provenance ledger ✅ · wired into the pipeline ✅ · surfaced end-to-end ✅** | `ingestion/pipeline.py` (7-phase) + `data_spaces.py` + **NEW `ingestion/provenance.py`**: an **opt-in, default-off** auditable provenance ledger for ingested memory. Today a `NormalizedMessage` carries only `source` + free-form `metadata` — no structured record of *where a memory came from and how it was produced*. `ProvenanceLedger` (a bounded, atomically-written, corrupt/missing-file-safe JSON array mirroring the 0.34 stores) records one entry per ingested artifact — `{id, run_id, source, origin, phase, content_hash, produced_at, parent_id, meta}` — where `content_hash` is a SHA-256 fingerprint giving **tamper-evidence** (`verify(id, content)` → False if a persisted memory was altered) + dedup *without storing the content*, and `parent_id` links a derived artifact to its source so a chain (embedding ← message ← file) is walkable via `lineage(id)` (cycle-guarded). Plus `by_run`/`by_source`/`stats`. **Default ingestion path byte-identical** — nothing writes provenance unless a caller wires a ledger; attaching it across the 7 phases is the next wave. `tests/test_ingestion_provenance.py` (+12: fingerprint stability/str-bytes-equivalence, record shape + required fields, by_run/by_source, lineage chain/unknown-id/cycle-safe, verify tamper-detection, cross-instance persistence, corrupt-file-safe, oldest-first pruning, stats). **Now wired into `IngestionPipeline`**: `IngestionPipeline(ledger=…, clock=…)` stamps a per-run `run_id` (surfaced in the summary) and records one provenance entry per parsed message after each parse phase (source/origin=conversation/content-hash/sender·is-me); **opt-in + best-effort** — a no-op with no ledger and a ledger hiccup never breaks ingestion (the per-message granularity is bounded by the ledger's oldest-first pruning). `tests/test_ingestion_pipeline_provenance.py` (+4: per-message records carry right source/origin/hash, no-ledger no-op, message-source-overrides-batch, ledger-hiccup-never-breaks). **Surfaced end-to-end ✅** — `provenance.default_ledger_if_enabled()` (opt-in via **`JARVIS_PROVENANCE`**, default-off → ingestion byte-identical, no conversation ids at rest) wired into `IngestionWatcher` so each watcher-triggered run records provenance when enabled; **`GET /api/ingestion/provenance`** (admin-guarded — a forensic/lineage view of personal-memory ingestion; `run`/`source` filters; `enabled:false` when off); and a HUD **`ProvenancePanel`** (Memory cluster) rendering recent records + by-source stats with the honest "empty until JARVIS_PROVENANCE is on" banner. Ledger gained `recent(limit)` (newest-first). 3 route snapshots reseeded (auth=admin); `tests/test_ingestion_provenance.py` (+2: `recent`, opt-in helper) + `frontend/src/test/provenance-panel.test.tsx` (+2). *(Remaining 0.37: ontology + cross-agent sharing; provenance for the derived knowledge/embedding phases.)* | — |
| 0.38 Today In Jarvis | ✅ done | `memory/timeline.py` `build_unified_digest` fuses *did* (autonomy done-tasks) + *learned* (memory facts) → `GET /api/dashboard/today` (#371) + cockpit *Today* HUD panel (#372); proof-gap metrics (proposal-funnel #369 · night-shift #370) surfaced on the north-star meter (#373) | — |
| 0.39 Market Intel Pack | 🟡 partial → **offline alert engine ✅ · persistent watchlist ✅ · HUD panel ✅** | `plugins/{balance,analytics,signal_layer}.py` + `market/analyze.py` — the **alerts + disclaimers** engine shipped with P3 (Track P): `POST /api/market/watchlist` evaluates band rules against *provided* quotes → breach alerts each carrying a mandatory not-advice disclaimer, and `POST /api/market/brief` is the offline daily brief (alerts + portfolio snapshot + honest headline); acting on a signal is kernel-gated IRREVERSIBLE_OR_MONEY → QUEUE. **Persistent watchlist ✅** — **NEW `market/watchlist_store.py`**: `WatchlistStore`, a bounded, atomically-written, corrupt-safe JSON store of curated `{symbol, low, high, note}` watches (one entry per symbol, upsert, symbol upper-cased; rejects an inverted `low>high` band). The watchlist was stateless (resent each request); now the owner curates it once. **NEW `routers/market_watchlist.py`** (kept separate from `market.py`): `GET /api/market/watchlist/saved` (+ stats), `POST` (add/upsert), `DELETE …/{symbol}` (user-guarded). `tests/test_watchlist_store.py` (+9); 3 route snapshots reseeded (auth=user). **HUD `WatchlistPanel` ✅** (2026-07-02) — Console panel (Interop cluster) reading/writing the saved watchlist: band stats row, per-symbol remove, an add form (symbol/low/high/note); carries the new per-panel LIVE chip (TASK-2 tail). `frontend/src/test/watchlist-panel.test.tsx` (+4). *(Remaining: live quotes feed + the `balance` plugin against a real broker/bank are owner-gated wiring; per-domain signal routing.)* | — |
| 0.40 OSINT Investigator Pack | 🟡 partial → **offline investigation planner ✅** | Builds on `osint/correlate.py`. **NEW `agents/core/osint/investigate.py`** — `build_investigation(evidence)` turns the correlated drawer into a prioritized **investigation plan**: leads (by confidence/corroboration) + `suggest_pivots` (deterministic next-lookup suggestions per indicator kind — email→domain/username, domain→ip/url, ip→domain/asn, …; deduped+bounded) + honest caveats. **Never enriches** (`live_lookups_performed: False` — pivots are suggestions for an owner-gated tool), and **taint stays visible** (untrusted-source leads/pivots flagged → write-back approval-gated). Pure/deterministic/offline. `tests/test_osint_investigate.py` (+5). *(Remaining 0.40: owner-gated live enrichment plugins.)* | — |
| 0.41 World Signal Packs | 🟡 partial → **per-domain signal routing ✅** | `plugins/signal_layer.py` fetches the briefs; **NEW `agents/core/signal_routing.py`** is the pure routing layer on top: `classify_signal` (inspectable keyword rules per domain — conflict/cyber/economy/aerospace/maritime/energy/health; matched terms reported), `route_signals` (per-domain + per-agent slices via `AGENT_INTERESTS` — argus=all, friday=brief context, stark=economy+cyber, gecko=economy+energy, ultron=cyber; **unclassifiable signals surfaced in `unrouted`, never guessed**), `build_domain_brief` (severity-ranked, bounded, honest empty/unknown-domain states). Pure/deterministic/offline — routes only provided signals, no fetching. `tests/test_signal_routing.py` (+6). *(Remaining 0.41: wiring a live sidecar feed through the router into the per-agent digests.)* | — |
| 0.42 Security Skills Pack | 🟢 **done** | new `agents/core/security_skills/` (separate from the `security/` infra) — a pure, offline, read-only knowledge pack over **public** taxonomies: MITRE **ATT&CK** (all 14 enterprise tactics + a curated, clearly-subset set of representative techniques with real IDs), MITRE **D3FEND** (defensive tactics + an ATT&CK→countermeasure mapping), and **NIST CSF 2.0** (the 6 functions). Pure functions: `tactics()`/`techniques(tactic)`/`technique(tid)` (enriched with D3FEND + CSF), `map_behavior(text)` (an **honest keyword heuristic** that returns candidates *with the matched evidence* — never a black-box attribution), `frameworks()`, and `build_playbook(ids)` (per-technique countermeasures + CSF coverage, reporting **gaps + unknown ids honestly**, `generated:false`). Every payload carries `curated:true` + `DISCLAIMER` + authoritative `SOURCES`; nothing is fabricated and it never acts. Served read-only at `/api/security-skills/{frameworks,tactics,techniques,technique/{tid},map,playbook}` (user-guarded, Trust surface). `tests/test_security_skills_pack.py` (+8); route/openapi/hud-v2 parity reseeded (+6 routes). | — |
| 0.43 Learning Coach Pack | 🟢 **done** | new `agents/core/coach/` (the existing `learning/scheduler.py` is agent-promotion scheduling, not tutoring — so this is separate) — a pure, offline, **stateless** study-coach pack: **SM-2 spaced repetition** (`review(card, quality)` → next interval/ease/due-day, ease floored at 1.3, lapse resets reps, input never mutated), a **review-session builder** (`build_session` → due cards + capped new cards, with honest deferred-counts so a backlog is visible), and a **curriculum planner** (`plan_curriculum` → deterministic prerequisite topological order, **reporting cycles + unknown prereqs honestly** rather than dropping topics, split into sessions). Schedules/plans only — never generates lesson content, never persists. Served at `POST /api/coach/{review,session,curriculum}` (user-guarded, Knowledge surface). `tests/test_coach_pack.py` (+8); parity reseeded (+3 routes). | — |
| 0.44 Safe Comms Pack | 🟡 partial → **per-channel rate limits · status · draft UI · channel inbox transport v0 ✅** | `channels/{telegram,email}.py`,`whatsapp_bridge.py`,`action_approvals.py` + **NEW `channels/send_rate_limit.py`**: an **opt-in, default-off** per-channel OUTBOUND sliding-window limiter wired at `WebhookChannel.send()` (the external broadcast channels — WhatsApp/Signal/Matrix/Teams/Google Chat). Bounds *how much* a channel can broadcast (complement of CDX-11 "*who*" + the H23.16 egress monitor "*observe*"). Config `JARVIS_CHANNEL_SEND_RATE` (global/min) + `JARVIS_CHANNEL_SEND_RATES="whatsapp:10,teams:30"` (per-channel); 0/unset = unlimited → **zero behavior change by default**, allocation-free on the default path. **Deliberately scoped off the interactive reply path** (telegram/web/voice via `ChannelManager.send`) so a user reply is never dropped. `tests/test_channel_send_rate_limit.py` (+10); existing webhook tests green. **Status surfaced ✅** — the limiter gained a read-only `snapshot()` (live in-window count per channel, pure view) + module `status_snapshot()` (configured caps + usage, `enabled:false` when no cap set → byte-identical default); **`GET /api/channels/send-rate-limit`** (admin-guarded, sibling of the egress monitor) reads it; and a HUD **`CommsRatePanel`** (Trust cluster) renders per-channel `used/cap` with the honest "unlimited until JARVIS_CHANNEL_SEND_RATE(S) is set" banner. 3 route snapshots reseeded (auth=admin); `tests/test_channel_send_rate_limit.py` (+4: snapshot pure-view + ageing, status disabled-default, caps+usage, unlimited-channel null-remaining) + `frontend/src/test/comms-rate-panel.test.tsx` (+2). **Draft-before-send UI ✅ (#527)** — `SafeCommsDraftPanel` loads the governed social action catalog from `GET /api/integrations/social`, composes X post/reply/DM drafts, and POSTs to `/api/integrations/social` with `source:"hud.safe_comms_draft"` so the existing ask-tier approval queue/preview path holds the write; it never posts directly. **Channel inbox transport v0 ✅ (#551)** — `ChannelInboxStore` persists bounded telegram/web inbound threads after sender-pairing allows them; `ChannelReplyBroker` gates replies through `CHANNEL_REPLY_CONTRACT`, queues `channel.reply` tasks into the existing approval funnel, and approved tasks send through `ChannelManager.send` while recording the outbound message back into the same thread. Read surface: `GET /api/channels/inbox/status`, `GET /api/channels/inbox`, `GET /api/channels/inbox/{thread_id}`; write surface: `POST /api/channels/inbox/{thread_id}/reply`. HUD Comms now renders inbox threads as live and keeps seeded preview rows disabled. **Mobile catch-up ✅ (H18.12)** — the native Comms tab lists those threads, reads messages, and queues governed replies with `source:"mobile"`; `mobile/PARITY.md` is now green for this surface. *(Remaining TASK-2/O26 tail: owner plugin/live-data setup; email/WhatsApp inbox transport remain deferred until their live send seams are proven.)* | — |
| 0.45 High-Risk Automation Contracts | 🟡 partial → **template abstraction · payment + signal + plugin live gates ✅** | `plugin_gate.py`,`signal_governance.py`,`routers/payments.py` + **NEW `automation_contracts.py`**: a **pure, fail-closed, opt-in** decision layer that generalizes the mandate→gate pattern hand-rolled in `payments.py` (per-payment cap, payee allowlist, currency, expiry, cumulative cap) so a *new* high-risk automation declares its policy as a **`ContractTemplate`** of composable `Constraint`s instead of re-implementing a bespoke gate. Reusable factories — `field_present`/`positive`/`at_most`/`at_least`/`one_of`/`equals`/`not_expired`/`cumulative_at_most`/`predicate` — where a limit/allowlist may be a template-time **constant** *or* a `callable(view)` runtime value (read from an injected `context` mandate). `evaluate(payload, context=, now=)` runs constraints in declared order, **short-circuits on the first violation** with a stable `reason` code (never raises, never executes), and returns a `ContractDecision` that always carries `requires_approval` (defaults **True** — high-risk, routes to the existing approval queue). `ContractRegistry` keys templates by action `kind`; an unknown kind **fails closed** (deny + requires-approval). `tests/test_automation_contracts.py` (+30: every factory incl. fail-closed-on-crash, template order/short-circuit/audit-hook/now-injection/payload-wins-over-context, registry duplicate-guard + unknown-kind fail-closed, and a **payment template that reproduces every `payments.py` denial code end-to-end**). **Payment-gate live adoption ✅** — `payments.py` now exposes `PAYMENT_CONTRACT`, and `PaymentBroker._deny_reason()` delegates to that contract while preserving the existing denial codes/order (`unknown_mandate`/`mandate_expired`/`invalid_amount`/`currency_mismatch`/`payee_not_allowed`/`over_per_payment_cap`/`over_total_cap` + admissible). `request_payment()` and `approve()` therefore re-check via the reusable contract before any pending/approved state transition; the kernel mediation layer still runs only after mandate-contract admissibility. `tests/test_payments_contract_live_gate.py` (+2) pins that the live request + approval paths obey a patched contract decision, and `tests/test_payments_contracts_parity.py` now guards the live contract source instead of a duplicate future template. **Signal governance live adoption ✅** — `signal_governance.py` now exposes `SIGNAL_RECOMMENDATION_CONTRACT`; actionable Signal Layer recommendations are evaluated through the contract before they can enter the preview-only approval queue, and a denied contract decision increments the skipped count + emits a denial audit event instead of queueing a task. Default behavior stays the same for ordinary recommendations (`requiresApproval:true` queues as BLOCKED, advisory items skip). `tests/test_signal_governance.py` (+1) pins that a patched live contract can deny one actionable recommendation while the admitted one still queues for human approval. **Plugin permission live adoption ✅** — `plugin_gate.py` now exposes `PLUGIN_CALL_CONTRACT`; `PermissionGate.check_call()` delegates plugin-known/enabled/agent/network admissibility to the contract while preserving the existing boolean results and warning reasons for unknown, disabled, non-served, and domain-blocked calls. `tests/test_plugin_contract_live_gate.py` (+1) pins that a patched live contract can deny an otherwise allowed plugin call; the focused plugin/startup/integration sweep stays green. *(Remaining 0.45: apply contract templates to richer draft-before-send contracts beyond payments, signal recommendations, and plugin calls.)* | H23.1 |
> 2026-07-05 0.45 update: #535 (`codex-o45-social-draft-contract`) continues the contract-adoption tail by adding `SOCIAL_DRAFT_CONTRACT` to `agents/core/social.py`. `SocialBroker.request()` now evaluates the contract after existing catalog/field validation but before preview/enqueue, so valid X post/reply/DM drafts still enter the ask-tier approval queue while a denied contract decision cannot enqueue. Red/green proof: `tests/test_social_h12_21.py::test_request_obeys_live_social_draft_contract` first failed because patched contracts were ignored, then the full social suite passed (16 passed); full GitHub Actions passed before merge. This does **not** add channel inbox transport or owner plugin setup.

> 2026-07-05 0.45 update: #537 (`codex-o45-writeback-contract-gate`) continues the same tail by adding `WRITEBACK_DRAFT_CONTRACT` to `agents/core/writeback.py`. `WriteBackBroker.request()` now evaluates the contract after existing target/action/field validation but before preview/enqueue, so valid Notion/GitHub/Google Calendar drafts still enter the ask-tier approval queue while a denied contract decision cannot enqueue. Red/green proof: `tests/test_writeback_h10_30.py::test_request_obeys_live_writeback_draft_contract` first failed because patched contracts were ignored, then the full write-back suite passed (19 passed); adjacent writeback/social/contracts/action-auth/funnel sweep, ruff, py_compile, and status sync are green; full GitHub Actions passed before merge. This does **not** add live host writes, new integration transports, or owner plugin setup.

> 2026-07-05 0.45 update: #539 (`codex-o45-call-contract-gate`) continues the same tail by adding `CALL_REQUEST_CONTRACT` to `agents/core/autonomy/call_broker.py`. `CallBroker.request()` now evaluates the contract after existing provider/field/interrupt-budget validation but before preview/enqueue, so valid Twilio/Telnyx outbound-call requests still enter the ask-tier approval queue while a denied contract decision cannot enqueue. Red/green proof: `tests/test_call_broker_h12_22.py::test_request_obeys_live_call_request_contract` first failed because patched contracts were ignored, then the full call broker suite passed (16 passed); adjacent call/writeback/social/contracts/action-auth/budget/loop-breaker sweep, ruff, py_compile, and status sync are green; full GitHub Actions passed before merge. This does **not** add live telephony, new channel transport, or owner plugin setup.

> 2026-07-05 R3-B3 merged update #584 (`codex-r3-b3-a2a-escalation-contracts`): inbound A2A tasks now declare `A2A_INBOUND_CONTRACT` and evaluate it after enable/allowlist/HMAC/JSON validation but before appending to the pending inbox; escalation fan-out now declares `ESCALATION_CONTRACT` and evaluates it after target resolution but before any adapter `send`. Contract payloads are sanitized (peer id, task shape/key names/body length; channel ids/count and message length only). Red/green proof: `tests/test_r3_b3_a2a_escalation_contracts.py` first failed because patched contracts were ignored, then the focused + adjacent A2A/escalation/contract sweep passed (55 passed); ruff and py_compile were clean; full PR CI went green before merge.

| 0.46 Media Library | 🟡 partial → **catalog + searchable timeline ✅ · wired into `media_gen` ✅ · export bundles ✅** | `media_gen.py`,`media_skill.py` + **NEW `media_catalog.py`**: an **opt-in, default-off** searchable catalog of generated media. `media_gen` *generates* image/thumbnail/video but kept no record, so there was no way to browse/search/build a timeline. `MediaCatalog` (a bounded, atomically-written, corrupt/missing-file-safe JSON array mirroring the 0.34/0.37 stores) records one item per generation — `{id, kind, prompt, path, backend, cloud, created_at, tags, meta}` — with `add`/`get`/`remove`, `all` (newest-first gallery), **`timeline`** (oldest-first, time-bounded), **`search`** (case-insensitive prompt substring · kind · tag · `since`/`until`, all AND-ed, newest-first), and `stats` (per-kind + cloud count). `kind` is validated against `media_gen.KINDS` so the catalog can't drift from what the generator produces. **Default generation path byte-identical** — nothing records unless a caller wires a catalog. `tests/test_media_catalog.py` (+12: add shape + kind validation, get/remove, all-newest-first vs timeline-oldest-first + bounds, search filters AND-ed + time-bounds, cross-instance persistence, corrupt-file-safe, oldest-first pruning, stats). **Now wired into the live generator**: `MediaGenManager(catalog=…, clock=…)` records each *successful local* generation (kind/prompt/path-from-result/backend/tags) and returns a `catalog_id`; **best-effort + opt-in** — a catalog hiccup is swallowed (generation still succeeds) and an unattached manager is byte-identical (cloud-approval + failed generations are *not* cataloged). Circular-import-safe (a local `Protocol`, since `media_catalog` imports `KINDS`). `tests/test_media_gen_h12_24.py` (+4: cataloged-when-attached, no-catalog-unchanged-output, cloud/failed-not-cataloged, catalog-failure-never-breaks-generation). **Export bundles ✅** — **NEW `media_export.py`**: `build_manifest(items, now=)` describes a selection (per-item on-disk existence + size, `present`/`total_bytes`, and a `missing` list — a vanished source file is reported, never silently dropped) and `write_bundle(items, dest, now=)` writes a portable `.zip` (each existing file under `media/<id>__<name>`, namespaced by id so same-basename items can't collide, + an embedded `manifest.json`). **Decoupled from `MediaCatalog`** (takes a list of item dicts from `search`/`all` → no import, no cycle). `tests/test_media_export.py` (+6: manifest counts/sizes, missing-reported, empty-selection, bundle-contains-files+manifest, bundle-skips-but-records-missing, same-basename-namespaced-by-id). **Surfaced end-to-end ✅** — `media_catalog.default_catalog_if_enabled()` (opt-in via **`JARVIS_MEDIA_CATALOG`**, default-off → generation byte-identical, no prompt history) wired into `routers/multimodal.py` so `media_generate` records when enabled; **`GET /api/media/catalog`** (user-guarded, `q`/`kind` filters, `enabled:false` when off); and a HUD **`MediaGalleryPanel`** (Build cluster) rendering items + per-kind stats with the honest "empty until JARVIS_MEDIA_CATALOG is on" banner. 3 route snapshots reseeded; `tests/test_media_catalog.py` (+1 helper) + `frontend/src/test/media-gallery-panel.test.tsx` (+2). *(0.46 complete.)* | — |
| 0.47 Creative Asset Pipeline | 🟡 partial → **coordinated pipeline ✅ · content-addressed provenance chain ✅** | `creative/pipeline.py:plan_pipeline` already emits the coordinated stage plan. **NEW `agents/core/creative/provenance.py`** gives it a tamper-evident lineage **chain** (mirrors the ingestion `ProvenanceLedger` 0.37): one record per stage, parent-linked (script ← image_prompts ← render ← assemble ← export), each `content_hash`=SHA-256 over the stage's inputs+generator → **tamper-evidence + dedup without storing content**; `verify(record, stage)` detects tampering, `lineage(id)` walks child→root (cycle-guarded). Pure/deterministic (same plan → same hashes), `generated: False` throughout. `tests/test_creative_provenance.py` (+4). *(Remaining 0.47: the owner-gated render/image-gen wiring.)* | — |
| 0.48 Video Production Pipelines | 🟡 partial → **offline planner ✅ (assembly · effects · localization)** | `video_prompt.py` was a single-prompt helper only. **NEW `agents/core/creative/video_pipeline.py`** — a pure, deterministic, offline production *planner* (mirrors the P4 creative-pack discipline): `plan_assembly` orders scenes into a timeline with a validated transition allowlist (unknown → `cut`, surfaced in `unknown_transitions`, never invented) + overlap-aware total runtime; `plan_effects` keeps only allowlisted effects/params (`unknown_effects` surfaced); `plan_localization` builds one subtitle track per language and **never machine-translates behind your back** (non-base tracks flagged `needs_translation`); `build_video_plan` composes them. **Honest by construction** — `generated: False` on every clip/effect/track (it plans a cut, never renders one); real encode/render + the terminal publish stay owner-gated and the publish is held by the Action Kernel (`creative/pipeline.py:release_action_payload`). `tests/test_video_pipeline.py` (+10). *(Remaining 0.48: the owner-gated render/encode wiring — a real NLE/ffmpeg/cloud video model.)* | — |
| 0.49 Timeline Adapter | 🟡 partial | `canvas.py` + worldview `timelineMarkers.ts` / interactive approval-gated timeline | — |
| 0.50 Publishing Studio | 🟡 partial → **validated finished-asset package + kernel approval gate ✅** | **`agents/core/creative/publishing.py`** packages an already-produced artifact for YouTube/Instagram/README without uploading it. `validate_asset` requires an opaque artifact id, basename-only target extension, allowed MIME type, positive byte size, and finite/bounded video duration; `validate_metadata` enforces typed required fields, platform limits, and typed hashtag lists without trimming violations into a pass. The checklist separates automatic validation from literal owner confirmations for disclosure/consent, rights, and final preview. A deterministic `package_id` is emitted, but `release_payload` stays `None` until every gate passes; even then it is `publish_state:kernel-held` at `IRREVERSIBLE_OR_MONEY`. There is deliberately no upload/publish API. `tests/test_publishing_studio.py` (+19; Linux+Windows full CI green in #657). *(Remaining 0.50: a visual studio surface and governed platform-executor integration; publication must remain kernel-held.)* | — |
| 0.51 Reference-Driven Creation | 🟡 partial → **grounding-enforcement layer ✅** | `plugins/websearch.py` (SSRF-safe fetch) + **NEW `grounded_plan.py`**: the **honest-grounding** core of the reference→plan choreography. The model drafts steps that cite fetched sources; `ground_plan(goal, references, steps)` is a **pure validator** that makes the grounding auditable — a step is *grounded* only if it cites a **known** reference id; a step citing an **unknown** id has it surfaced in `unknown_cites` (never silently dropped); an uncited / only-phantom-cited step is flagged in `ungrounded_steps`. Reports per-step `grounded`/`cited_titles` + plan-level `coverage`, `unused_references`, `unknown_citations`, and `fully_grounded` (true only when every step is grounded **and** no phantom citation exists). Mirrors the "nothing is fabricated" invariant — it never *generates*, just refuses to let an unsupported step pass as grounded. `tests/test_grounded_plan.py` (+8: fully-grounded, ungrounded-flagged, unknown-surfaced-not-dropped, only-phantom→ungrounded, coverage+unused+dedup, empty-plan vacuously-clean, no-references no-crash, reference-without-id raises). *(Remaining 0.51: the model-side draft generation + fetch choreography that feeds this — host/LLM seam.)* | — |
| 0.52 Product Demo Factory | 🌱 seed | `docs/marketing/TEASER_PACK.md` storyboard + shot-list complete / HUD-footage capture + assembly tooling | H23.22 |
| 0.53 Design System Manifest | 🟡 partial → **inspectable token/component manifest ✅ + drift guard** | **NEW `agents/core/design_manifest.py`**: extracts the design system from the REAL `frontend/src/styles.css` — `extract_tokens` (base custom properties + every `data-look/accent/...` variant override block), `extract_components` (deduped class inventory), `build_manifest` (counts + honest `{error}` on a missing stylesheet — never an empty manifest that looks parsed). `tests/test_design_manifest.py` (+4) **pins the load-bearing tokens (`--accent`, `--font-ui`, …), the amber/graphite variants, and >100 component classes against the live stylesheet — design drift now breaks a test** instead of silently un-syncing tools. *(Remaining 0.53: expose the manifest via a route/HUD panel + Figma token sync.)* | — |
| 0.54 Skill Operating System | ✅ done | `skills/{loader,importer}.py`,`skill_drift.py`, SKILL.md manifests | — |
| 0.55 Design Partner Kit | 🟢 **mostly done** | **feedback/NPS widget** ✅ (H23.21) + **issue bundle** ✅ NEW: `agents/core/support_bundle.py` assembles a single **non-sensitive** diagnostic snapshot (version + hardened/profile posture + capability-readiness roll-ups + per-plugin egress tallies + recent audit **event counts** & chain-integrity + route count) a design partner can attach to a support request — triage without a screen-share or risky data dump. **Safety is allow-list, not redaction** (only the specific aggregates are ever included — never config/secrets/tokens/PII/message content/audit previews), and each section degrades to `{"error":"unavailable"}` rather than crashing or leaking a traceback. `GET /api/support/bundle` (admin). `tests/test_support_bundle.py` (+6, incl. a no-sensitive-keys assertion). *(Remaining 0.55: SLA definition — a doc/owner artifact.)* | H23.21 |
| 0.56 Trust Center | ✅ done (#300) | `security/audit.py`,`routers/security.py` (kill_switch, audit_verify), `LOCAL_ONLY_AGENTS` + HUD panel ✅ (#300) / cloud-hop log, consent still open | H23.3/5/16 |
| 0.57 Release Packaging | ✅ done | `release.yml` builds bundles + SBOM/NOTICE + checksums + optional GPG sign (H23.13), compat matrix (H23.14) | H23.13/14 |
| 0.58 Pack Manager | 🟡 partial → **uninstall done · version-history ledger ✅ · wired into the marketplace ✅ · package rollback ✅** | `skills/marketplace.py` (registry, now **records to the ledger**: `SkillMarketplace(history=…, clock=…)` logs a `publish`/`install`/`uninstall` event on each op — opt-in/best-effort, default `None` → byte-identical; the install path now also reads the registry `version`, and uninstall captures it before a purge. A ledger hiccup never breaks the op. `tests/test_marketplace_history.py` +4: publish+install recorded, **upgrade chain → rollback target**, uninstall audited, no-ledger-unchanged). **Activated in the app + read surface ✅** — the orchestrator now attaches a `SkillHistory` to its `SkillMarketplace` behind **`JARVIS_SKILL_HISTORY`** (default-off → `history=None` → marketplace byte-identical), and `SkillMarketplace.history_view(name=)` + **`GET /api/skills/marketplace/history`** (admin-guarded) expose the events/stats (and a skill's current/rollback-target) — degrading to `enabled:False` when the flag is unset. Route parity + auth-matrix snapshots reseeded. `tests/test_marketplace_history.py` (+3: view-disabled, view-events+target, view-without-name). **HUD `SkillHistoryPanel` ✅** — a read-only Console panel (Interop cluster) over `GET /api/skills/marketplace/history` showing publish/install/uninstall events + per-action stats; honesty contract — when `JARVIS_SKILL_HISTORY` is off it says "empty until …" rather than implying history is kept. `frontend/src/test/skill-history-panel.test.tsx` (+2) + **NEW `skills/skill_history.py`** — the **version-history schema** rollback needs (the registry keeps one row per name via `INSERT OR REPLACE`, so the prior version is lost on upgrade). `SkillHistory` is a bounded, atomically-written, corrupt-safe JSON ledger of `publish`/`install`/`uninstall` events `{id, name, version, action, at, meta}` from which it derives **`current_version(name)`** and the **`rollback_target(name)`** (the distinct version present immediately before the current one — what a downgrade would restore; `None` if there's no prior). `uninstall` is recorded for the audit trail but doesn't establish a present version; a re-install of an older version correctly moves `current`. **Opt-in / default-off** — nothing records unless a caller wires it; binding it into the install flow is the next wave. `tests/test_skill_history.py` (+10: record/required-fields, history order+filter, current+rollback over an upgrade chain, single-version→no-target, unknown→None, uninstall-ignored-for-version, reinstall-older-moves-current, **equal-timestamp ties resolve by record order**, persistence+corrupt-safe+stats, oldest-first pruning). *(History ordering is robust to equal `time.time()` values — stable ascending sort then reverse — so rapid publish→install can't invert the rollback target.)* + **NEW `uninstall_skill(name, purge=)` / `remove_from_registry(name)`**: safely remove an installed skill from disk — the target must resolve **strictly inside `skills_dir`** (a name with a separator / `..` / NUL is refused, mirroring the install-time zip-slip guard), with an optional `purge` to also drop the marketplace registry row. The published package is **retained by default** so `install_skill` restores it (the recovery path, since the registry keeps one version per name). `POST /api/skills/marketplace/uninstall` (admin) removes the dir + forgets it in the live loader (matched by on-disk path). `tests/test_marketplace_uninstall.py` (+12). **Package rollback ✅** — the registry kept one row per name (`INSERT OR REPLACE`), so the prior version's bytes were lost on upgrade and a rollback had nothing to restore. **NEW additive migration** `_v2_version_archive` creates `marketplace_skill_versions` (a snapshot table; `marketplace_skills` untouched). `publish_skill` now **archives the row it's about to replace** (`_archive_current`, bounded to the last `_VERSION_KEEP=20` per skill, oldest pruned); **`restore_prior_package(name)`** rolls back to the most recent archived snapshot — and is **reversible** (it archives the current package first, so calling again rolls forward) — returning `{ok, restored_version, previous_version}` (`ok:False` when the skill isn't registered or has no archived prior). The restored package replaces the registry row but is **not** installed, so `install_skill` re-deploys it **through the moderation/signature gate** on the way back. **`POST /api/skills/marketplace/{name}/rollback`** (admin; 422 when there's nothing to restore). `tests/test_marketplace_rollback.py` (+6: archive-on-publish then restore brings back the **real package bytes**, reversible toggle, no-prior/unknown-skill/blank-name guards, bounded archive) + `tests/test_db_migrations.py` (updated: v2 table + `user_version==2`); 3 route snapshots reseeded (auth=admin). *(Remaining 0.58: model/domain/content pack types are separate.)* | — |
| 0.59 Proof Assets | 🟡 partial → **competitor-comparison + SEO landing drafted ✅** | landing page ✅ (`marketing/landing/index.html`) + competitive brief ✅. **NEW `marketing/proof/`**: `competitor-comparison.md` (buyer-facing, incl. a head-to-head vs the namesake **getjarvis.eu** that previously lived only in research — grounded in `docs/research/2026-06-25-getjarvis-competitive-gap.md` + the brief, honesty-discipline enforced: owner/host-gated capabilities marked as "core built, host wiring pending", no stat outside `BACKLOG.md`) + `seo-landing.md` (intent-ranked keywords, page metadata, section outline, schema-ready FAQ, honesty guardrails). Both reflect the just-shipped offline cores (0.64 `quickbar.py` / 0.65 `screen_reflex.py` / 0.25 `desktop_control.py` / 0.66 `writeback_connectors.py`) honestly. / remaining (owner-gated): the **demo video** (real HUD footage / badged demo mode, M4) + README hero image | H23.22 |
| 0.60 Local Analytics | ✅ done (#300) | `analytics_store.py`,`observability/north_star.py`,`/api/metrics/north-star` + HUD meter ✅ (#300) / activation funnel still open | H23.20 |
| 0.61 Database Future Check | ✅ **evaluated — stay on SQLite/WAL, re-check on triggers** | `settings_db.py` (WAL) + `persistence/migrations.py` (H23.7 ✅). The written Turso/libSQL eval: [`docs/decisions/2026-07-11-db-future-check.md`](docs/decisions/2026-07-11-db-future-check.md) — every libSQL advantage (replication/multi-writer/edge) belongs to the post-1.0 multi-user future H23.23 deferred; migrating now would re-plumb backup/export/purge for zero user gain and strain local-first trust. **Named re-eval triggers:** per-user isolation scoped · live second-device sync · verified write-contention in the 72h soak · Pi-5 shared reads. Path if fired: libSQL **embedded replicas** (file-compatible), never the hosted tier. | H23.7 |
| 0.62 System Profiles | 🟢 **done** | new `agents/core/system_profiles.py` — usage-mode **posture presets** (Gaming / AI / Multimedia / Admin + **balanced** default), selected via `JARVIS_SYSTEM_PROFILE` (same env-driven-posture pattern as `JARVIS_HARDENED`/`JARVIS_PLUGIN_LEAST_PRIVILEGE`). Each profile declares posture knobs (`background_autonomy`, `heavy_features`, `max_parallel_agents`, `model_tier`) read via `active_posture()`. **First live consumer wired:** `Orchestrator.run_heartbeat` is paused under a `background_autonomy:False` profile (gaming/multimedia) to free local resources — and `balanced` (the default) keeps it on, so **behavior is unchanged unless the owner opts into a quieter mode**. Read-only `GET /api/system/profiles` (active + all profiles). `tests/test_system_profiles.py` (+9, incl. the heartbeat-pause consumer); parity reseeded (+1 route). **Concurrency consumer wired ✅** — `AutonomyCoordinator._subagent_concurrency()` caps the `autonomy.max_subagents` setting by the active profile's `max_parallel_agents` hint (`min(setting, hint)` when the profile sets one), so a constrained profile (e.g. *gaming* → 1) actually throttles background-agent throughput; the **balanced** default leaves it `None` → the cap is the setting **unchanged** (byte-identical), and a bad/odd hint (bool/0/neg/float/str) or a profile-read error falls back to the setting. `tests/test_coordinator_profile_concurrency.py` (+10). **All knobs now bite + HUD ✅** — the two previously-declared-but-dead knobs are wired: **`heavy_features`** (`heavy_features_enabled()`) gates the heavy media-generation entry point so *gaming* (`heavy_features:False`) pauses GPU-hungry generation with an honest `{ok:False, paused, profile}` reply; **`model_tier`** (`preferred_model_tier()`) is consumed in `load_runtime_settings` — a constrained tier (*gaming* `local-light` / *multimedia* `local`) forces cloud escalation **off** (`set_cloud_fallback_mode("never")`) so inference stays local, while `auto` (balanced/ai/admin) honors the `llm.cloud_fallback` setting. Both **default-safe** — `balanced` leaves `heavy_features:True` + `model_tier:auto` → byte-identical. New HUD **`SystemProfilePanel`** (Admin cluster) over `GET /api/system/profiles` shows the active profile (marked) + each profile's knobs. `tests/test_system_profiles.py` (+4: heavy_features/model_tier helpers, media-gen paused under gaming, constrained-tier forces local-only) + `frontend/src/test/system-profile-panel.test.tsx` (+1). *(0.62 complete — all four posture knobs now steer real behavior.)* | 0.17 |
| 0.63 Restore & Soak | 🟡 partial → **sandbox output cap now bounds peak host memory** | backup/restore+drill ✅ (#302) + `resilience.py`. **Sandbox hardening follow-up to #631** (found by an independent adversarial verification of the merged safety batch): the output cap was applied *after* `proc.communicate()` drained the child to EOF into host memory, so a runaway/hostile sandboxed child (agent-generated code) could balloon host RSS for the whole timeout window — `max_output_bytes` bounded only what was returned. `environments/output_limits.py` gains `read_capped_stream()` (streams head+tail within budget, discarding the middle so peak retained memory is ~budget regardless of stream size) + `render_capped()` (honest omission notice using the *true* total); `sandbox.py._read_output_capped()` replaces every `communicate()` read site (docker/subprocess/shell/wasm) with a mock-safe fallback. `tests/test_environment_output_limits.py` (+5) + `tests/test_sandbox_output_cap.py` (+2: a real 500 KB child bounded to <2 KB carrying the true-total notice). / remaining: 72h soak, failure injection | H23.8/12 |
| 0.64 Floating Bar + Global Hotkey | 🟡 partial → **offline command-service core ✅** | The bar is two parts: a tiny OS-level host overlay (Tauri `GlobalShortcutManager` + always-on-top window — **owner-gated**, `desktop/src-tauri`) and the **command service** that decides what a typed line means. The service now exists: **NEW `agents/core/quickbar.py`** — a pure, synchronous, offline command parser that resolves a bar line into a *plan* (`navigate` / `summon` / `query` / `help` / `unresolved`) and **never performs the action** (agent requests still route through the orchestrator + Action Kernel). Grounded by construction: navigation targets come from the frontend's own grammar (`app.tsx` number-key **modes** + center **tabs**), agent summon (`@friday …` / `friday: …`) is validated against the router's roster (`IntentRouter.ROUTING_TABLE`), and the natural-query `route_hint` reuses the shared `INTENT_RULES` (single source of truth — no duplicated keyword table; hint is a preview, authoritative routing stays in the orchestrator). Honest (unknown view/agent/trigger → `unresolved` or hint-less `query`, never guessed) + bounded (input length-capped, `CommandBar` recall history capped & deduped). `tests/test_quickbar.py` (+15). / remaining (owner-gated): the Tauri host overlay + global shortcut registration, and wiring the plan kinds into the live HUD | 0.15 / 0.29 |
| 0.65 One-Hotkey Screen-Capture Reflex | 🟡 partial → **capture→VLM→answer core wired ✅** | The reflex (**one keypress → screenshot → local VLM → answer, no copy-paste**) had the pieces but nothing between them. **NEW `agents/core/screen_reflex.py`** is that middle: takes captured screenshot **bytes** and drives the reflex to an answer, purely + offline-testably via an injected VLM callable. **Reuses, never reinvents** — builds the request with `vlm.build_vision_messages` (H13.1) and parses UI elements with `screen_grounding.parse_grounding`/`fuse_with_a11y` (H15.2). Two modes: `answer` (free-form Q&A, defaults a concise prompt when none typed) and `ground` (UI-element listing → located elements, optionally fused with an a11y tree). **Non-persistent by itself** (writes no image to disk, makes no network call of its own) and **bytes-only** (a path can't become a host-file read, mirroring `encode_image_block`), **size-capped** (8 MB), and **honest** (no VLM / refused image / `[VLM error]` sentinel → `{ok:False, generated:False}`; `generated:True` only when the model actually produced text — never a fabricated description). **⚠ "strict-local" is a caller contract, not module-enforced:** the module hands the screen bytes to whatever async callable is injected, so keeping capture local is the host's responsibility — the injected backend MUST be the localhost VLM, never an arbitrary/cloud endpoint. `ScreenReflex.from_backend` adapts the real `VLMBackend`. `tests/test_screen_reflex.py` (+12). / remaining (owner/host-gated): the OS screen-grab + the 0.64 global hotkey that fires it, a 24 GB-GPU local VLM server, and the result-overlay wiring | 0.16 |
| 0.66 SaaS Connector Breadth | 🟡 partial → **white-collar connector builders ✅** | ~20 integrations skewed messaging/IoT; the white-collar suite was missing. **NEW `agents/core/writeback_connectors.py`** adds pure, offline request builders for **Linear · Asana · Trello · Todoist · ClickUp · Google Sheets · Microsoft 365 (Outlook draft)**, same discipline as H10.30 write-back: validated `CATALOG` (unknown action/missing field → refused with reason), **host allowlist** (`CONNECTOR_HOSTS`, SSRF guard), **secrets only at execute-time** (drafts carry a `{{secret:<target>_token}}` handle, never a raw token — SecretBroker resolves behind approval), `build_connector_request` → one concrete HTTP request each, `draft_task_payload` → ask-tier approval-queue task, `catalog()` inspectable surface. `tests/test_writeback_connectors.py` (+15). *(Remaining 0.66: wire builders into the executor behind the approval queue + owner OAuth setup per provider.)* | — |
| 0.67 Emotion Voice (Fish Audio) | ✅ done (2026-07-18, guide-gap wave) | `voice/tts.py` gains a **Fish Audio** backend in the chain (XTTS→ElevenLabs→**Fish**→edge→Kokoro; `FISH_AUDIO_API_KEY`/`VOICE_ID`/`MODEL`, `voice="fish[:ref]"`, persona-consent-gated like the other clones) + **inline `[emotion]` tags** (`[calm]`/`[amused]`… pass through to Fish S-series, `strip_emotion_tags()` for every other backend so tags are never read aloud) + the HUD **🔊 SPEAK morning brief** button (Autonomy panel → `POST /tts`, local `speechSynthesis` fallback; `mobile/PARITY.md` row added, mobile ⬜). `tests/test_tts_fish_emotion.py` (+12), `frontend/src/test/brief-speak.test.tsx` (+2). *(Remaining, owner-gated: browser wake-word — needs a licensed JS lib (Porcupine) or cloud hop, per `docs/VOICE.md` §6.)* | — |
| 0.68 Revenue & Ads Connectors | ✅ done (2026-07-18, guide-gap wave) | **NEW `plugins/revenuecat.py`** (read-only RevenueCat API v2 overview — active subs/MRR/revenue; `REVENUECAT_API_KEY`+`PROJECT_ID`) + **NEW `plugins/meta_ads.py`** (read-only Meta Marketing API insights/campaigns; `META_ADS_ACCESS_TOKEN`+`ACCOUNT_ID`, act_ normalization; **no budget mutators by design** — a future write goes through an ask-tier contract). Manifested (SEC-5 domains `api.revenuecat.com`/`graph.facebook.com`), gathered on revenue/ads keywords, settings toggles, injectable clients. `tests/test_guide_gap_plugins.py`. *(Remaining: owner keys.)* | — |
| 0.69 Social Scheduler (Postiz) | ✅ done (2026-07-18, guide-gap wave) | **NEW `plugins/postiz.py`** — self-hosted Postiz public API: queue/integration reads + **draft-first** `schedule_post` (`type="draft"` unless an explicitly governed caller passes `kind="schedule"`; Safe Comms posture). Config-driven host via `register_dynamic_domain` (SEC-5b, like n8n); manifest `data_scope=TRANSMITTED`; gathered on social-queue keywords. **Governed live scheduling ✅ (2026-07-18):** `social.postiz.schedule` joins the Safe Comms catalog — requests queue ask-tier approval via the same `/api/integrations/social` funnel, and only an APPROVED task executes through `PostizPlugin.schedule_post(kind="schedule")` (the plugin default stays draft-first; unconfigured fails honestly). *(Remaining: owner self-host.)* | — |
| 0.90–1.0 gates (Freeze · RC · Partner · Burn-In · Owned) | ⬜ pending | `AUDIT.md`,`MANUAL_TESTING.md`,parity/auth gates, north-star eval / promote eval→required gate; design partners; landing+demo | 1.0.0 row + H23.21/22 |

> **T-0.25 supersession (H28.4, 2026-07-14):** H28 now supplies the real Windows driver seam,
> ToolRPC/Action-Kernel execution path, governed browser driver, and the user-facing Console →
> Build → Operator surface. The stale T-0.25 implementation tail is closed; its only remaining
> boundary is owner-host validation with real Windows UIA and installed Playwright Chromium.

> **Remaining greenfield (⬜) among 0.19–0.63:** 0.20 Vault · 0.48 Video Production. *(0.55 Design Partner Kit → 🟢 mostly done — feedback widget + issue bundle; only the SLA doc remains.)*
> *(0.42 Security Skills + 0.62 System Profiles → 🟢 **done**; 0.57 Release Packaging → ✅ done; 0.52 Demo
> Factory → 🌱 seed and 0.61 DB Future Check → 🟡 partial on the 2026-06-25 re-audit.)*
> Everything else is ✅/🟢/🟡/🌱 — **finish-the-PARTIALs beats start-greenfield** (audit guidance).
> Top remaining finish-firsts: **0.36 Action-Manifest unify**, **H23.10 retention defaults**,
> **export HTTP surface** (`/api/admin/export`, sibling of backup/forget). *(Done: H23.7 DB migrations #305,
> H23.8 backup #302, H23.9 export #303 + delete/forget #306, 0.56 Trust Center + 0.60 Analytics #300.)*
>
> **Full per-theme execution specs** for every deferred theme above now live in **Phase E** of the
> [remaining-backlog blueprint](docs/superpowers/specs/2026-06-23-orizont24-remaining-backlog-blueprint.md)
> — each with grounded `file:line` seams, build steps, acceptance criteria, a test path, and its K/V
> dependency. Load-bearing seams were re-verified against the codebase on 2026-06-23.
>
> **Addendum 2026-06-25 — getjarvis.eu gap delta:** A fresh competitive-gap pass against the shipped
> consumer product **getjarvis.eu** (screen-aware floating-bar desktop AI, 30+ OAuth SaaS connectors,
> freemium) is captured in [`docs/research/2026-06-25-getjarvis-competitive-gap.md`](docs/research/2026-06-25-getjarvis-competitive-gap.md).
> Net-new buildable items folded in above as **0.64–0.66**. **Explicit non-goals** (conflict with the
> local-first / single-user north star): managed-cloud freemium + billing, multi-tenant team features,
> and uploading screenshots to a cloud VLM — we win these on privacy by *not* doing them.

---

## 🆕 H23 — Productionization & 1.0 Readiness (the un-ticketed layer)

> Surfaced 2026-06-21 by cross-referencing the codebase against an external 1.0 checklist
> (Immich "stable" criteria, OpenSSF baseline, OWASP Agentic/LLM Top-10). These are the things a
> credible 1.0 needs that the feature backlog never captured. Status tags: **EXISTS** (code there,
> expose/gate only) · **PARTIAL** · **MISSING**. Each item is its own future PR; mapped to a version above.

| ID | Item | Status | → Version |
|----|------|--------|-----------|
| H23.1 | Per-task step/recursion + token/time **budgets + loop detection** (OWASP unbounded-consumption) | ✅ **done (folded into K3, 2026-07-03)** — `BudgetLedger` covers token/wall-time/recursion plus named dimensions for interrupt, mission, and payment caps; `TaskExecutor` accrues handler-reported `tokens_used`; kernel/broker binding carries the shared ledger; loop breaker + operator reset remain wired. Defaults stay inert unless the existing flags/config enable enforcement. Evidence: `tests/test_kernel_budget*.py`, `tests/test_kernel_loop_breaker_wave.py`, `tests/test_executor_budget.py`, `tests/test_subagent_depth.py`, `tests/test_k3_budget_unification.py`. | 0.13 |
| H23.2 | **Model-version pinning & reproducibility** — record id/quant per run; approved-model allowlist | 🟢 **allowlist / pinning done · reproducibility rail done** — opt-in per-agent `approved_models` in `agents.yaml` (parsed in `config.AgentConfig`), enforced at the routing front door: `hybrid_router.select_backend` now wraps the core router and **blocks** an off-list model (`ModelNotApprovedError`), strict by default with a `JARVIS_STRICT_MODELS=0` warn-escape (mirrors `JARVIS_STRICT_EGRESS`); `approved_models()`/`is_model_approved()` queries. Empty list = unrestricted, so zero behavior change today. `tests/test_model_reproducibility.py` (+6). **Reproducibility half ✅** — **NEW `observability/model_info.py`**: an **opt-in, default-off** (`JARVIS_MODEL_INFO`) `ModelInfoRegistry` (callable, bounded) + a pure parser (`fingerprint_from_entry`/`parse_quant`/`ingest_listing`) that normalizes an LM Studio/Ollama `/v1/models` listing into `{id, version, quant, sha256}` (quant derived from the GGUF id when the backend omits it). The `Tracer` gained an optional `model_info=` resolver: each trace is **stamped with the model fingerprint** (best-effort; a resolver hiccup never breaks tracing), flowing through the existing `/api/traces` summary; with the flag unset the resolver is `None` and `model_info` stays `{}` → **byte-identical**. Wired in `orchestrator` (`self.model_info = default_registry_if_enabled()` → `Tracer(model_info=…)`); the existing `GET /api/models/local` opportunistically `ingest_listing`s the live catalog when enabled (no new fetch — reuses the host-seam call), and **`GET /api/models/info`** (admin) is the pure read surface (`enabled:false` when off). HUD **`ModelInfoPanel`** (Observe cluster) renders id · quant · sha with the honest "empty until JARVIS_MODEL_INFO is on" banner. **No change to the `generate()` contract** (enrichment lives at the tracer layer). `tests/test_model_info.py` (+13: quant parse, OpenAI/Ollama entry shapes, explicit-fields-win, garbage-tolerant, register/get/callable-resolver, ingest wrappers+skip-id-less, sorted+stats, bounded eviction, opt-in helper, tracer-stamps/empty-without-resolver/hiccup-safe) + `frontend/src/test/model-info-panel.test.tsx` (+2); 3 route snapshots reseeded (auth=admin). *(Remaining: the live `/v1/models` fetch is the host seam — owner enables a backend; the rail records whatever the listing reports.)* | 0.13 |
| H23.3 | **Kill-switch in the HUD** (one-tap) + credential quarantine on halt | 🟢 **HUD done** — one-tap `KillSwitchPanel` (HALT-ALL / disengage) already lives in the Console *Trust* section; credential-quarantine-on-halt is enforced by the K4 `inject_guarded` syscall. **This session added the rest of the safety surface:** `KernelMetricsPanel` (`GET /api/metrics/kernel` — grant/queue/deny tallies + recent denials with reasons) + `LoopBreakerPanel` (`GET /api/security/loop-breaker` + admin reset, shown only when tripped), `frontend/src/test/kernel-safety-panels.test.tsx` (+4, fetch-mocked; tsc + vitest green). ⚠️ Only the live-pixel render is owner-runtime-gated (CDX-9), as for every HUD panel. | 0.13 |
| H23.4 | Promote **eval/regression harness to a pre-release gate** | ✅ **done (2026-08-18; deterministic + nightly halves 2026-07-04/#506)** — companion `--ci-gate` deterministic drift/min-score lane + scheduled workflow + cache-backed baseline (`JARVIS_EVAL_STORE`); **live runner shipped:** live-model runs now record on per-model `companion_v1-live-*` lanes so a live run can never become (or read) the deterministic gate's baseline; `run_live_gate()` / `--live-gate` is the **fail-closed owner-box fidelity lane** (endpoint/model via `JARVIS_EVAL_LIVE_URL`/`JARVIS_EVAL_LIVE_MODEL`; unreachable or unconfigured = red with the reason, never a skip; per-model baseline + regression gating + `JARVIS_EVAL_LIVE_MIN_SCORE` floor), and `JARVIS_EVAL_LIVE=1` folds its verdict into the CI gate so a self-hosted owner runner can't go green on the deterministic half alone. **Release-gate wiring (the headline):** `scripts/release_gate.py` gained the `companion-eval` machine row (runs the drift gate in an ephemeral store) and the `live-eval-evidence` owner row (reads recorded live-lane runs; never auto-passes; stale > 30d = WARN). Evidence: `tests/test_companion_eval_live_gate.py` (+11, red/green) + release-gate row tests (+3). *Owner residual (same shape as A2): actually run `--live-gate` on the owner box against the real local model — the owner row stays FAIL until then.* | 0.13 |
| H23.5 | Audit-log **verify button** in HUD + secret redaction guarantee | ✅ **DONE** — UI (#300, Trust-mode live audit-verify badge); *caveats resolved (verified 2026-07-02):* **AUD-9** keyed HMAC shipped (`JARVIS_AUDIT_KEY`, per-row `hash_algo` migration, `security/audit.py`) and **AUD-12 F13** scanner `matched_text` is stored `[REDACTED:<pattern>]` (`audit.py:112`) | 0.13 |
| H23.6 | TASK-3 indirect-injection / cross-channel **taint-tracking** | ✅ **done (2026-07-05, #590)** — channel-ingress tail merged; verified 2026-07-11 (R2 taint #580, R3-B2..B5 contracts #582–#588, TASK-3 channel-ingress #590 all merged to main). Prior status marker was stale.
<br>Original evidence: — `security/taint.py` (`mark`/`mark_if_untrusted`/`is_tainted` + an untrusted-source classifier for web/OSINT/RSS/inbound/channel); `kernel.authorize` now **escalates a tainted action from GRANT → QUEUE** (approval), so injected content can't auto-execute (verified against the real `AutonomyPolicy`). H17.1a hardens the channel backstop: public `handle_input`/`handle_input_stream` bind origin at the turn chokepoint, internal channels (`eval`/`workflow`/rooms/etc.) stay `generated`, upstream `inbound` cannot be downgraded, and plugin-egress actions use the current origin. #590 closes the previously deferred inbound-channel chokepoint without changing handler text semantics: `Gateway.route()` attaches private `_inbound_meta` for untrusted channels, `ChannelInboxStore` persists only `tainted`/`taint_source`/`injection_flags`, and `Orchestrator.channel_handler()` consumes private metadata before outbound sends. Evidence: `tests/test_task3_channel_ingress_taint.py` (+2) red/green, focused Safe Comms inbox sweep (10 passed), adjacent pairing/cross-channel/action-origin/R2 taint/quarantine sweep (49 passed), full PR CI green including Windows. | 0.12 |
| H23.7 | **DB schema-migration framework** (`_schema_version` + forward-only on startup) | ✅ **DONE (#305)** — `agents/core/persistence/migrations.py` | 0.14 |
| H23.8 | **Backup/restore** (one-command) + a tested **restore drill** | ✅ **DONE (#302)** — `agents/core/backup.py` + `/api/admin/backup` (consistent SQLite snapshots, restore-drill). *Residual (audit 2026-06-23):* archives were **unencrypted** → **AUD-1 ✅ (#309)** (opt-in `.tar.gz.enc` + `settings.db` secret columns now encrypted at rest) | 0.14 |
| H23.9 | **Data export + delete/forget** endpoints (finishes promised H8.2) | ✅ **done (#315)** — export `agents/core/data_export.py` + now `POST /api/admin/export` (admin-guarded, secrets-free); delete/forget `data_purge.py` + `POST /api/admin/forget` now also erases memory at rest (**AUD-2**, this PR); backup-first copy encrypted with a key (**AUD-1** #309). *Done #303/#306; export HTTP surface + forget-completeness this PR.* | 0.14 |
| H23.10 | Data-**retention defaults** (conversations, audit log, memory) + rollback story | ✅ **done (#317)** — `retention` settings category (off by default; TTL `0` = keep forever) + `agents/core/retention.py` daily sweep (`scheduler_service.schedule_retention`, 03:30): prunes old conversation transcripts by mtime and old audit rows via a chain-preserving `AuditLogger.prune_before` re-anchor (`verify_chain` still passes). *Rollback = the pre-existing backups; memory-decay TTL stays with the decay system.* | 0.14 |
| H23.11 | Health/readiness endpoint; signal handlers + graceful shutdown; **log rotation** | ✅ **done** — liveness `GET /healthz` (dependency-free) + readiness `GET /readyz` (**503** until orchestrator+agents loaded; LLM-down does *not* gate readiness) in `routers/ops.py`; `serve.py` now builds a `uvicorn.Server` from env (`JARVIS_HOST/PORT/LOG_LEVEL/SHUTDOWN_TIMEOUT`) with a **bounded `timeout_graceful_shutdown`** so `systemctl stop`/SIGTERM drains in-flight requests then runs the lifespan teardown instead of hanging; opt-in **rotating file log** in `core/log.py` (`RotatingFileHandler`, `system.log_to_file`/`log_max_mb`/`log_backups` + `$JARVIS_LOG_FILE` overrides; default off → stderr only, supervisor rotates). **Review-hardened (adversarial pass):** the probes **bypass the per-IP rate limiter** (`_PROBE_PATHS` in `web.py`) so a non-localhost LB/Docker healthcheck can't be 429'd into evicting a healthy instance; `serve.assert_safe_bind()` **fails closed on a non-loopback bind** without a token or `JARVIS_ALLOW_INSECURE_BIND=1` (AUD-4 analog, since `JARVIS_HOST` is new); 503 readiness shares the full `no-store` policy; file-log PII/in-repo-path lifecycle documented (bounded by rotation, *not* the H23.10 sweep). `tests/test_h2311_operability.py` (+18). | 0.15 |
| H23.12 | Graceful **local-LLM-down** handling everywhere (no hang/crash) | ✅ **done** — root cause was the local backends (`llm/base.py` LM Studio + Ollama) bypassing the `http_client.py` split-timeout pattern with a flat `timeout=300/120s` (covers *connect* → a down/unreachable server could hang minutes) and returning the **raw exception** as the reply (`[LM Studio error: {e}]` → leaked into the chat bubble + poisoned conversation memory). Now: **split timeout** `local_read_timeout()` (`connect=5s`, long read) → down-detection ~5s, generation budget intact; `local_backend_degraded_reply()` returns a **clean, classified** message (unreachable vs error, raw detail logged not surfaced) across `generate()`+`generate_stream()` for both backends; `is_degraded_reply()` shared predicate keeps `warm_up`'s failure-detection working past the message change. `tests/test_llm_down_graceful.py` (+12: MockTransport down/timeout → fast clean reply, no raise/leak; timeout-config; warm_up regression guard). | 0.15 |
| H23.13 | **Release engineering** — artifacts (tar/zip), optional PyPI + Docker publish, signed releases | ✅ **done** — `release.yml` now goes tag→**artifacts**→Release: `scripts/build_release.sh` produces reproducible `jarvis-<ver>.{tar.gz,zip}` source bundles (via `git archive`, so `.env`/`agents/data`/`memory_logs`/`.venv`/`node_modules` are excluded by construction), a CycloneDX `SBOM.json` + `NOTICE` (`scripts/gen_sbom.py`, dep-free), and `SHA256SUMS`; a **tag↔`agents.__version__` guard** fails the release on a forgotten bump; **GPG signing** is wired but owner-gated (skips cleanly without the `GPG_PRIVATE_KEY` secret); `workflow_dispatch` dry-run exercises the build path without cutting a tag. **PyPI = N/A by design** (the project runs from source, not pip-installed); **Docker publish** documented as owner opt-in (compose already builds locally). `docs/RELEASE.md` (cut + verify), `tests/test_release_build.py` (+2: end-to-end build/checksum/leak/SBOM + requirements parsing). | 0.15 |
| H23.14 | **Semver compatibility contract** + supported-versions matrix + deprecation policy + platform matrix | ✅ **done** — `docs/COMPATIBILITY.md` (SemVer + pre-1.0 caveat, public-surface definition, supported-versions matrix, deprecation policy, platform matrix incl. the real **Python 3.12+** floor / Node 20+ / Docker-optional) + `SECURITY.md` rewritten from the GitHub placeholder into a real supported-versions + disclosure policy. **Gated:** `tests/test_compatibility.py` asserts the docs' supported-version lines track the single-sourced `agents.__version__` (so CDX-5 drift can't return) + valid SemVer + the documented Python floor. | 0.15 |
| H23.15 | systemd/service templates (Linux/Windows) | ✅ **done** — `deploy/systemd/jarvis-hub.service` (hardened unit: `ProtectSystem=strict`/`NoNewPrivileges`/restricted address families; `KillSignal=SIGTERM` + `TimeoutStopSec` margin over `JARVIS_SHUTDOWN_TIMEOUT` → the H23.11 bounded graceful drain) + `jarvis-hub.env` + README; `deploy/windows/install-service.ps1` (NSSM, Ctrl-C graceful stop) + README; `deploy/README.md` index wiring the `/healthz`·`/readyz` probes. Both consume the H23.11 env knobs; guarded by `tests/test_compatibility.py`. | 0.15 |
| H23.16 | **Network monitor** HUD panel (prove LOCAL_ONLY agents make zero outbound calls) | ✅ **DONE (verified 2026-07-02** — data layer + API + HUD panel all in tree; only the live-pixel render stays owner-runtime-gated, CDX-9**)** — **data layer + API done**: thread-safe `observability/egress_monitor.py` (in-memory ring buffer + monotonic per-plugin counters) records *every* outbound attempt — allowed **and** blocked — at the `http_client.py` choke point (all 6 verbs via one `_guard`); `GET /api/admin/network/calls?plugin=&limit=` (admin-guarded) serves per-plugin tallies + recent events + `local_only_violations` (the proof: a NONE/LAN plugin with an allowed external call surfaces as a violation → `clean=False`). `tests/test_network_monitor.py` (+9, MockTransport — no real socket). **HUD panel done:** `NetworkMonitorPanel` in the Console (`gap.tsx`, Trust section) reads the endpoint and renders the `clean` local-only proof + per-plugin allowed/blocked/external + any violation in red; `frontend/src/test/network-monitor.test.tsx` (+2, fetch-mocked) — passes `tsc --noEmit` + vitest. ⚠️ Only the live-pixel render is owner-runtime-gated (CDX-9), as for every HUD panel. | 0.16 |
| H23.17 | **Quality gates** — E2E (Playwright), load/soak, a11y (WCAG), i18n completeness, browser+mobile matrix | ✅ **done (2026-07-03)** — i18n completeness, sandbox isolation, p95 load, live Playwright canvas/cinema smoke, axe a11y, nightly soak/browser matrix, and the chat send→SSE→stop + voice push-to-talk flow specs are all wired. M2.1 added the degraded-model chat/voice flow E2E; M2.2 added scheduled/manual browser matrix + soak knobs (`E2E_BROWSER_MATRIX`, `E2E_SOAK_ITERATIONS`). | 0.19 |
| H23.18 | **User docs** — USER_GUIDE, FAQ, UPGRADE (per-version migration notes) | 🟢 **done** — `docs/USER_GUIDE.md` (requirements → install (Win one-click / any-OS) → start → the cabinet → configure a model → daily use (chat/voice/autonomy/plugins) → admin panel → data controls), `docs/FAQ.md` (data-leaves-machine, telemetry, GPU, models, OS, multi-user, stop-autonomy, channels, cost, update, backup/export/delete, WorldView/Signal), `docs/UPGRADE.md` (Win `UPDATE.bat` / manual `git pull`+reinstall+restart / release-bundle; **automatic forward-only migrations** H23.7; backup-first rollback; graceful restart H23.11; per-version notes → COMPATIBILITY/SemVer). Linked from README; `tests/test_user_docs.py` (+4). | 0.19 |
| H23.19 | **Trust/security docs** — THREAT_MODEL, SECURITY disclosure policy + advisories, NOTICE/SBOM, **telemetry opt-in disclosure**, privacy policy | 🟢 **done** — `docs/THREAT_MODEL.md` (boundaries + assets + 11 threats each mapped to the *real* seam: egress gate/monitor, action kernel, K3 budgets/loop-breaker, encrypted secrets, HMAC audit, injection/Cypher/WKT guards, sandbox isolation, fail-closed bind, supply-chain) + continuous-verification matrices + honest residual risks; `docs/PRIVACY.md` (local-first, **no telemetry / no phone-home** disclosure, first-party-analytics clarification, opt-in egress data-flow table, user controls: export/forget/retention/kill-switch). SECURITY disclosure + NOTICE/SBOM already shipped (H23.14 / H23.13). Linked from README + SECURITY.md; `tests/test_trust_docs.py` (+3) guards existence/grounding/discoverability. | 0.19 |
| H23.20 | **Onboarding wizard** + activation-funnel instrumentation + cold-start error guidance | 🟢 **backend done** — `routers/onboarding.py`: `GET /api/onboarding/wizard` (ordered steps intro→model→test_chat→autonomy, `complete` **derived from recorded funnel events** so onboarding resumes across reloads; `model_ready` + a friendly cold-start `hint` when no backend is reachable) + `POST /api/onboarding/funnel` (records first-party local `funnel.<step>.<event>` via `analytics_store`, bounded to known steps); both `user_guard`'d. `tests/test_onboarding_wizard.py` (+4); route parity/auth/openapi + HUD-v2 IA (cockpit home) snapshots reseeded. **HUD `OnboardingPanel` ✅** — Console *Observe* panel renders the ordered steps with done/pending state + progress + the cold-start `hint`, and a per-step **done** button records the funnel event (`POST /api/onboarding/funnel`) so completion persists; `frontend/src/test/onboarding-panel.test.tsx` (+2, fetch-mocked; vitest + tsc green). **Pending:** only the live-pixel render (owner-runtime-gated, CDX-9). | 0.19 |
| H23.21 | **Design-partner program** — recruit 1–3, in-app feedback/NPS, support SLA, collect north-star from real usage | 🟢 **feedback loop + program doc done** — `feedback_store.py` (first-party local SQLite: nps/comment/bug, bounded) + `routers/feedback.py`: `POST /api/feedback` (user-guarded footer widget) + `GET /api/feedback/summary` (admin — **NPS** %promoters−%detractors + per-kind counts + recent); `docs/DESIGN_PARTNER_PROGRAM.md` (recruit 1–3, 48 h SLA, what-to-measure tied to north-star/guardrails, privacy). `tests/test_feedback_widget.py` (+4); snapshots reseeded (HUD home = observe). **HUD `FeedbackPanel` ✅** — Console *Observe* panel renders the NPS summary (promoters/detractors + per-kind + recent) and carries the submit form (score + comment → `POST /api/feedback`); `frontend/src/test/feedback-panel.test.tsx` (+2, fetch-mocked; vitest + tsc green). **Pending:** only the live-pixel render (owner-runtime-gated, CDX-9) + actually recruiting partners (owner). | 0.20 |
| H23.22 | Landing page + demo recorded (owner-led; dev-supportable) | 🟡 DEV HALF DONE (#512) — static offline landing page + demo shot-list support delivered; owner-recorded video remains M4 | 0.20 |
| H23.23 | **Multi-user readiness call** — accept single-user for 1.0 & document it, OR scope per-user isolation (north-star is "per active user"). **🟢 decision recorded 2026-07-11 (awaiting owner ratification):** ship 1.0 **single-user per install** and document the boundary; per-user isolation is a post-1.0 horizon (each design partner runs their own isolated install, so the "per active user" north-star is measured across installs, not multi-tenant). Rationale + the post-1.0 trigger for option B: [`docs/decisions/2026-07-11-single-user-1.0.md`](docs/decisions/2026-07-11-single-user-1.0.md). Unblocks A2 (soak the single-user install). Owner ratifies (or picks B) in OWNER_TASKS. | DECISION | 0.20 |
| H23.24 | **72h-soak evidence collector** — `scripts/soak_report.py`: samples `/healthz`+`/readyz`, north-star/kernel, privacy-reduced active queue depth+oldest age, SQLite/WAL sizes, target-server RSS (`--pid` required), audit-chain, capability/breaker failures and redacted error signatures; outage-tolerant JSONL + dated Markdown evidence, partial-window truth marker, torn-line recovery. HTTP(S)-only endpoint validation. `tests/test_soak_report.py` (+14). | ✅ done — offline/injectable; A2 remains an owner-run 72h gate | 0.20 |
| H23.25 | **Release-gate command** — `scripts/release_gate.py`: explicit code-complete inventory + full suite or fast route/OpenAPI/auth/action-auth/readiness/lifespan guards + full generated-status check + doc links + version↔tag + park guard; PASS/WARN/FAIL output separates code/machine/owner/market evidence and never auto-passes owner rows. `tests/test_release_gate.py` (+13). | ✅ done — owner/market rows intentionally remain live gates | 1.0.0 |
| H23.26 | **Generated project status → kill doc-counter drift** — `scripts/status_sync.py` now derives backend pytest + frontend Vitest + mobile Jest counts, route snapshot, active YAML agents, horizon roll-ups, last verified-main commit (including PR base from the Actions event) and open Lane-A gates into tracked `project-status.json`; marker-bounded snippets drive README badges/Run/Status, JARVIS Quick Stats, GO_LIVE header and STATUS counters; `--check` gates all artifacts and fails closed on collection errors or missing markers. Python-only CI may explicitly use `--reuse-js-counts` while the separate JS jobs execute the suites. `tests/test_status_sync.py` (+11 H23.26 cases; 18 total). | ✅ done — one machine-readable truth, satellites generated | 0.19 |
| H23.27 | **Design-partner feedback export** — `scripts/export_partner_feedback.py`: explicit local JSON+Markdown packet with allowlisted install environment, onboarding completion, aggregate autonomy/failure/latency, NPS + intentionally written feedback and sanitized north-star. It never copies prompts/responses, task titles/payloads, credentials, host/user/path/session identifiers and never uploads; north-star fetch accepts HTTP(S) only. `tests/test_export_partner_feedback.py` (+8). | ✅ done — privacy-safe default, operator chooses whether to share files | 0.20 |
| H23.28 | **Park-list CI guard, actually implemented** — `scripts/park_guard.py` + `.github/workflows/park-guard.yml`: PR diff gate with line-based `unpark:` declarations, narrow module unlocks, phase aliases (wave-1/O28, wave-2/O29, wave-3/O30+O33), owner-only training/rust, Windows-path parity and self-protected policy files; CI executes the last merged guard policy when available. `tests/test_park_guard.py` (+10). | ✅ done — phased freeze is now machine-enforced | 0.13-tail |
| H23.30 | **Public web demo instance for digitaholic.ro** (H23.23-adjacent) — a real Nerva instance embedded in a digitaholic.ro page on a free cloud model, auto-updated from `main`, personal data stripped, one disposable install per visitor session as the "save slot" (explicitly **not** H23.23 option B per-user partitioning). Reuses CDX-12 hardened + CDX-11 least-privilege + in-memory graph/vector fallbacks + existing cloud routing; the one core code change — a `NERVA_PUBLIC_PROFILE=1` gate on the unconditional `seed_graph()` that seeded hardcoded personal `SEED_FACTS` into any empty graph — is ✅ **delivered** (gate placed inside `seed_graph()` so no caller can bypass it; default unchanged; `tests/test_public_profile_seed_gate.py`, +8). Spec: [`docs/decisions/2026-08-24-public-web-demo-digitaholic.md`](docs/decisions/2026-08-24-public-web-demo-digitaholic.md). | 🔴 **P0 — code gap closed; still BLOCKED on 4 owner calls** (spec awaiting review; roster overlay + malformed-flag boot guard not built; suggested R2) | post-1.0 |
| H23.29 | **Runtime supervisor** — a single headless entrypoint (`scripts/coordinator.py`) boots the real Orchestrator and wires the existing coordinator/heartbeat/night-shift loops (`Orchestrator.start_channels()`) with no HTTP layer, separate from the web app process. `agents/core/observability/runtime_log.py`'s `RuntimeRunLog` appends one bounded JSON line per autonomy-coordinator cycle to `logs/runtime.jsonl` (heartbeat status, tick mode/max_tier, night-shift active-window, ok/error) and persists a cycle counter across restarts so a crash-and-recover is provable, not assumed — wired via a getattr-optional hook in `AutonomyCoordinator.loop()`, byte-identical when unset. `scripts/runtime_supervisor.py` spawns the coordinator and respawns it on any exit including `SIGKILL` (a process cannot recover itself from `kill -9`), logging `spawned`/`child_exited`/`respawned`/`stopped` events into the same run-log; `deploy/systemd/jarvis-runtime.service` + a `runtime-coordinator` docker-compose service layer OS-level `restart:`/`Restart=` on top as defense-in-depth. `make runtime-up`/`runtime-down`/`runtime-status` drive it locally. `tests/test_runtime_log.py` (+8), `tests/test_runtime_log_wiring.py` (+4), `tests/test_runtime_coordinator_boot.py` (+2), `tests/test_runtime_supervisor.py` (+3, one of which SIGKILLs a real child process and asserts respawn). Manually verified end-to-end in-sandbox: 3+ consecutive clean cycles, and a real `kill -9` on the coordinator process recovered in ~1s with the cycle counter resuming (not resetting) — see HANDOFF.md. No autonomy-policy, kill-switch, or dispatch-authority code touched. **Follow-up (#935, same day):** a duplicate PR built the same feature independently and lost the comparison, but had two robustness edges worth porting forward — `RuntimeRunLog._load_state()` now quarantines an unparseable state file to `<name>.corrupt-<epoch>` instead of silently discarding it, and `runtime_supervisor.py`'s respawn delay now backs off exponentially (starting delay → 2×/crash, capped 60s, resets after a 30s+ healthy run) instead of a constant fixed delay. **Consumer wired (#940):** the run-log had no reader — `read_runtime_health()` now reduces a bounded tail of `logs/runtime.jsonl` (O(tail), not O(file): the log grows one line per cycle forever) to a loop-health summary, and `build_morning_brief()` renders it as a `🫀 Runtime` line. `stale` is the load-bearing field — a supervisor can die without ever writing a failure line, so a fresh-looking `ok: true` tail proves nothing without its age. `runtime_health=None` keeps the brief byte-identical, and `default_log_path()` makes producer and consumer agree on one path. `tests/test_runtime_health_brief.py` (+17). Verified end-to-end against a real supervisor: a live brief rendered `✅ buclă activă — ciclul #2`, and after `kill -9` on both processes the same reader flipped to `⚠️ buclă oprită`. | ✅ done | 0.16 |

---

## 🧠 ORIZONT 24 — AI-OS: Action Kernel · Verification Fabric · Live Packs (direction 2026-06-23)

> **Decision (owner, 2026-06-23):** primary bet = **OS kernel + Verification Fabric**; first capability
> packs = **all four** (Proactive autonomy · OSINT/WorldView · Market Intel+Finance · Creative/Publishing).
> This is the **substrate program for Phase 2** ([MOONSHOT.md §4](MOONSHOT.md)) — the bridge from
> *feature-complete* (v0.10) to a **provable** 1.0. *(ORIZONT 23 ≡ the **H23** productionization layer
> above; this horizon sits on top of it and reuses its items.)*
>
> **Thesis:** convert fleet throughput into a *trustworthy* operating system by (a) routing **every**
> agent action through one kernel, and (b) making *"works end-to-end against reality"* a merge gate —
> then deepen breadth (the 4 packs) in parallel on that substrate. This makes the moonshot's
> "persistent, proactive, private **cortex**" operational.
>
> **Not net-new scope — it threads existing seeds into one program.** Most parts already exist, scattered;
> ORIZONT 24 *promotes and unifies* them. Map: **K3 ⊇ H23.1** · **K4 ⊇ H23.3** · **V4 ⊇ H23.4** · the kernel
> unifies `plugin_gate` / `signal_governance` / capability-broker / per-family approval queues · the packs
> deepen competitive-gap themes **0.32/0.38/0.45** (P1), **0.40/0.41** (P2), **0.39** (P3), **0.47/0.50** (P4).
> **Phase A = the AUD-\* hardening cluster** (see *Hardening audit (2026-06-23)* below) — the foundation;
> skipping it is the OpenClaw failure mode.
>
> **📋 Cross-phase execution map:** [`docs/superpowers/specs/2026-06-23-orizont24-remaining-backlog-blueprint.md`](docs/superpowers/specs/2026-06-23-orizont24-remaining-backlog-blueprint.md)
> — every remaining backlog item, **Phases A–E** (hardening · K/V substrate · the 4 packs · H23
> productionization · all deferred competitive-gap themes), grounded with `file:line` seams to reuse,
> approach, acceptance, and test paths. The context-cheap map sessions execute against instead of
> re-reading the ~2M-token repo; each item ships as its own PR.
>
> **2026-07-11 note:** Phase D below ("3–5 design partners = the 1.0 gate") is now the **proof
> half** of the *expanded* 1.0 gate (Version Roadmap above + [NERVA_VISION.md](NERVA_VISION.md) §10).
> The **V2 capability registry is the substrate the ORIZONT 27 Capability Registry v1 extends** —
> one system, not two.

**The OS metaphor, made literal:** agents = processes · capability tokens = permissions · the kernel =
the syscall table · budgets = the scheduler · kill-switch/quarantine = a syscall · the verification fabric
= the OS test-suite. These exist today but are **scattered**; ORIZONT 24 makes them **one system**.

**Phasing & gates** (gate-discipline per MOONSHOT §4 — we do not skip gates):
- **Phase A (now):** AUD-\* P0/P1 hardening — foundation; also advances H23.
- **Phase B:** Track K + Track V core. **Gate:** action-auth matrix green · reality-harness live · readiness board shipped.
- **Phase C:** the 4 packs, fleet-parallel, each driven SEAM→VERIFIED. **Gate (per pack):** VERIFIED via harness + north-star moving.
- **Phase D:** 1.0 proof — 3–5 design partners (unchanged; **= the 1.0 gate**).

### Track K — Action Kernel (the "operating" in operating system) (P0–P1)

Fixed since: ✅ **action-posture flag reference published** (#953) — `docs/FLAGS.md` now documents
what each autonomy/posture flag unlocks and what it costs, so operators stop reading the source to
find out which posture a flag actually buys.


> **Design spec:** [`docs/superpowers/specs/2026-06-23-orizont24-action-kernel-design.md`](docs/superpowers/specs/2026-06-23-orizont24-action-kernel-design.md)
> — grounded in the existing seeds it unifies (`security/capability.py:authorize()` nucleus, the autonomy
> `TaskQueue`, `plugin_gate`/egress, route guards, `SecretBroker`) + the 3 verified bypass risks it closes.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| K1 | 🟢 **Gate-K COMPLETE — every action kind is KERNEL-mediated** — **Single mediation point** — every privileged action (tool call, plugin egress, write-back, payment, social, node dispatch) flows through `kernel.authorize(action, capability, budget)` → grant / deny / queue-for-approval. Unifies `plugin_gate` + capability broker + `signal_governance` + per-family approval queues. **Landed (default-off `JARVIS_ACTION_KERNEL`):** the `agents/core/kernel/` facade *composing* the `security.capability.authorize` nucleus + `policy.decide` + audit→`intent_log` (not reimplementing); **wave-1** routes the 4 TaskQueue brokers (call/social/writeback/node) through it; the **action-auth matrix gate** (`tests/test_action_auth_matrix.py` + `_snapshots/action_auth.json`, a `Mediation` registry whose enumeration is derived from broker `KIND`s) fails CI on a new unclassified privileged action; B2 fail-closed pinned, B1/B3 xfail scaffolds. **Payment micro-wave ✅** — an *admissible* `request_payment` now routes through `kernel.authorize` (the broker carries a `kernel` hook, bound in `web.py` via the shared `kernel/binding.py` that also feeds the wave-1 brokers): a kernel **DENY** (kill-switch engaged / over-budget / runaway loop) refuses the payment **before** it can become pending, while GRANT/QUEUE fall through to the existing always-approval flow (the mandate's hard caps still gate admissibility first). Default-off; `payment` flips `PENDING_KERNEL → KERNEL` in the action-auth snapshot; `tests/test_payment_kernel_wave.py` (+6, incl. a real-`KillSwitch`+real-policy integration). **Wave-2 egress ✅** — policy-passing plugin egress now routes through `kernel.authorize` via an **injected hook** in `http_client` (a `(plugin,method,url,host)→reason|None` callable from `kernel/binding.make_egress_kernel_hook`, wired by the orchestrator alongside the B3 audit sink), so `http_client` never imports the kernel. A kernel **DENY** (halted kill-switch → no outbound calls / over-budget / runaway loop) blocks otherwise-allowed egress; a buggy hook **fails open** (manifest policy already ran). `plugin.egress` flips `PENDING_KERNEL → KERNEL`; the B3 xfail scaffold is now a real passing regression; `tests/test_egress_kernel_wave.py` (+10, incl. a real-`KillSwitch` halt→block / release→allow integration). With B3's audit (`EGRESS_DOWNGRADE` event, `tests/test_egress_audit_b3.py`) this closes the egress story. **Wave-3 MCP-mutating ✅** — `MutatingRouteTool.call` now routes through `kernel.authorize` **after** the per-identity gate (identity proves *who*; the kernel decides *whether it may run now*): a DENY (halted kill-switch / over-budget / runaway loop) refuses the write with `MutatingKernelError`, audited `refused-kernel`, before the adapter runs. Threaded via `build_mutating_route_tools(kernel=…)`, wired in `web.py` to `make_action_kernel(orch)`; `mcp.mutating` flips `PENDING_KERNEL → KERNEL`; `tests/test_mcp_kernel_wave.py` (+8, incl. a real-`KillSwitch` halt→block / release→allow integration). **Wave-3 Tool-RPC ✅** — a *gated* (external/mutating) Tool-RPC call now passes `kernel.authorize` **before** it can enqueue its approval task: a DENY (halted kill-switch / over-budget / runaway loop) returns `kernel_denied` and never reaches the queue; read-only inline tools are untouched. `ToolRPCServer(kernel=…)` wired in `autonomy_coordinator`; `tool.rpc` flips `PENDING_KERNEL → KERNEL`; `tests/test_tool_rpc_kernel_wave.py` (+6, incl. a real-`KillSwitch` integration). **Wave-4a admin ✅ (B1 structural)** — `POST /api/security/kill-switch` (engage) + `/api/security/capabilities/issue` now route through `kernel.authorize` (helper `_admin_kernel_denial` in `routers/security.py`, default-off) **in addition to** `admin_guard`: a kernel **DENY** (halted kill-switch, or a *presented* capability token that lacks the named cap) → **403**; GRANT/QUEUE allow through (no approval-UX regression). Designed + adversarially verified by a workflow that caught two blockers: **disengage is deliberately NOT mediated** (a halt would otherwise deny its own release → bootstrap lock-out; disengage stays `admin_guard`-only so recovery always works), and the B1 close is honestly **structural** — the `Capability` is K1-tolerant, so a *no-token* admin request still falls through to policy→QUEUE→allow; making a valid token **mandatory** (so missing-capability is refused) is **wave-4b/K2** (needs a token-provisioning story that doesn't strand the operator). `admin.kill_switch`/`admin.capability_issue` flip `PENDING_KERNEL → KERNEL`; the **B1 xfail scaffold is now a real passing regression**; `tests/test_admin_kernel_wave.py` (+5: default-off byte-identical · clean→QUEUE-allow · halt→deny-but-disengage-recovers · presented-bad-token→deny · distinct-kinds). **Wave-3 kg.write ✅ — Gate-K COMPLETE** — the 6 externally-driven `/api/kg/*` mutating handlers (entity upsert/delete, relation add/delete, fact add, ingest) now route through `kernel.authorize` (helper `_kg_kernel_denial` in `routers/memory_kg.py`, default-off, DENY-only): a halted kill-switch → **403**. The **boundary** is the whole point and was workflow-verified (8 agents, no blockers): the high-frequency **internal** ingestion path (`IncrementalKGUpdater.ingest` from `_record_interactions`, `seed_graph`, reflection) writes graph methods **directly** and is **never** gated, so a halt can't freeze per-turn memory — `tests/test_kg_kernel_wave.py` (+9) pins exactly that (external `/api/kg/ingest` 403 *while* internal `kg_updater.ingest`/`graph.add_entity` still write). `memory.remember` (vector write), `/consolidate` (plan-only) and `/decay/forget` (ACT-R op) are **not** KG writes → intentionally out of scope. `kg.write` flips `PENDING_KERNEL → KERNEL`. **Now every one of the 11 action kinds is `KERNEL` — the action-auth snapshot has zero `pending`.** Residual (own wave): **wave-4b/K2** makes capability tokens *mandatory* on admin + KG writes (today's `Capability` is K1-tolerant — a no-token request falls through to policy→QUEUE→allow); folding the WorldView HMAC tokens in is the same wave. **Observability ✅** — now that every action crosses `authorize`, an in-process meter (`kernel/metrics.py` `KERNEL_METRICS`, tallied in `_emit_audit`, the universal decision exit) counts grant/deny/queue per kind + keeps recent denials-with-reasons; served at `GET /api/metrics/kernel` (open, sibling of the north-star/capabilities meters). Naturally inert until the flag is on; `tests/test_kernel_metrics.py` (+5). | 8 | P0 | Phase A | every privileged action routes through the kernel; no bypass path exists |
| K2 | **Capabilities as process permissions** — generalize the seeded scoped/expiring/revocable tokens (`security/`, `node_mesh`) to **all** agents; least-privilege by default. | 5 | P1 | K1 | 🟢 **issuance done** — `kernel/capabilities.py` **derives** a least-privilege capability set per agent from its declared config (`agent:<id>` + `plugin:<p>` per declared plugin + `channel:<c>` + `model:local`; `model:cloud` only for a non-local-only agent whose policy permits it). The orchestrator issues a scoped `CapabilityBroker` token per agent at boot (`orch.agent_capabilities`, best-effort). `tests/test_kernel_capabilities.py` (+6) + a scratch run over the **real 17-agent roster** (frigga/ultron/howard get **no cloud cap**; revoke is immediate via the broker). **Pending:** per-action **enforcement** (the kernel waves passing each agent's token) + folding WorldView HMAC tokens in as one kind → closes **B1**. |
| K3 | **The scheduler** — central token/time/money/**interrupt** budgets + loop detection (folds **H23.1**). The interrupt budget *is* the MOONSHOT §5.4 "≤4 push/day" guardrail, enforced in one place. | 5 | P0 | K1 | ✅ **done (2026-07-03)** — the earlier token/wall-time/recursion/loop primitives are now unified with existing caps: `BudgetLedger` exposes named dimensions/status; `InterruptBudget` is a ledger-backed view; mission and payment caps publish observed dimensions while preserving their legacy denials; `TaskExecutor` accrues handler `tokens_used`; action-kernel binding can carry the shared ledger. Evidence: `tests/test_k3_budget_unification.py` (+6) plus the earlier K3 budget/loop/executor/subagent suites. |
| K4 | **Kill-switch + credential quarantine as a syscall** (folds **H23.3**) with one-tap HUD control. | 3 | P1 | K1 | 🟢 **syscalls done** — `kernel/syscalls.py`: `halt()`/`release()` (engage/disengage the persisted `KillSwitch`, audited) + `inject_guarded()` makes secret injection **quarantine-aware** (while halted, injection is forced blocked regardless of approval — no value leaks). Composes existing primitives, no surgery; "halt halts new grants" already enforced by `kernel.authorize`. `tests/test_kernel_syscalls.py` (+5) + a scratch smoke against the **real** KillSwitch/SecretBroker (contracts match, no secret leak while halted). **Pending:** the one-tap **HUD** control (frontend — productionization-tail phase). |
| **Gate K** | **action-auth matrix** test (generalizes the SEC-2 route-auth matrix) fails CI if **any** privileged action bypasses the kernel. | — | P0 | K1–K4 | a new un-mediated privileged action fails CI |

### Track V — Verification Fabric (what makes fleet-breadth safe) (P0–P1)

> **Design spec:** [`docs/superpowers/specs/2026-06-23-orizont24-verification-fabric-design.md`](docs/superpowers/specs/2026-06-23-orizont24-verification-fabric-design.md)
> — extends the existing snapshot-introspection gates (`test_route_auth_matrix`) + registries
> (`plugin_gate.BUILTIN_PLUGINS`, `component_registry`) + the ungated eval/north-star harness.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| V1 | **Reality harness** — each capability declares a contract + a live (or hermetically-sandboxed-but-real-protocol) integration test, run on a CI schedule. Null clients stay for unit speed; the harness proves the **rail**. | 8 | P0 | — | 🟢 **framework + V1→V2 promotion done** — `observability/reality_harness.py`: `RealityCase{capability_id, contract, probe, live}` + `run_reality()` (mirrors `eval.py`'s result schema); a **green probe is the only path** that promotes a capability to VERIFIED in the V2 registry (`record_verification`), a fail un-verifies, a human can still only demote. Hermetic (real-protocol, no socket) vs `live` (gated by `JARVIS_REALITY_HARNESS=1`). Seed cases prove the **egress-policy rail** (NONE blocks external / LAN allows local) and **both halves of the Action-Kernel gate-1** — the **kill-switch rail** (engaged ⇒ `kernel.authorize` DENY; disengaged ⇒ reaches policy) and the **capability-token rail** (a valid minted token clears the gate; a missing one ⇒ DENY) — real `KillSwitch`/`CapabilityBroker`/`authorize`, isolated to throwaway stores so the live halt is untouched → all promote to VERIFIED. Scheduled-only lane `.github/workflows/reality.yml` (nightly + dispatch, off the PR path). `tests/test_reality_harness.py` (+8). **Pending:** per-capability **live** contracts (real key/network, needs the networked nightly lane) · **durable cross-process** promotion (committed readiness snapshot) folds into **V3** |
| V2 | **Capability registry + readiness levels** — every capability carries a state **SEAM → WIRED → VERIFIED → GA**, queryable, with a HUD board + `/api/metrics`. Kills the audit's "looks done, isn't wired" ambiguity. | 5 | P1 | V1 | 🟢 **registry substrate done** — `observability/capability_registry.py` **derives** a `CapabilityRecord{id,kind,owner_agent,state,harness_id,…}` per capability from `plugin_gate.BUILTIN_PLUGINS` + `component_registry.status` + `skills` (no parallel system); `GET /api/metrics/capabilities` (open, sibling of north-star) serves it + `by_state`/`by_kind` roll-ups + an honest `harness_pending` (**nothing reaches VERIFIED/GA** — only the V1 harness promotes; a human can demote, cap at WIRED). `tests/test_capability_registry.py` (+6). **HUD readiness board ✅ (verified 2026-07-02):** `ReadinessPanel` (Console Trust, `gap.tsx:312` + fetch-mocked test) renders the SEAM→WIRED→VERIFIED→GA ladder; the V3 `test_capability_readiness_matrix` enforcement gate also shipped (see V3). **Pending:** live VERIFIED-promotion via the V1 reality harness (durable cross-process snapshot — folds into V3's booted-fixture slice) |
| V3 | **Fleet-coordination CI gates** — interface contracts + the action-auth matrix + a readiness gate (no VERIFIED without a green harness) + drift detection, so N parallel agents can't silently break each other. | 5 | P1 | V1, V2, K1 | 🟢 **readiness matrix gate broadened** — `tests/test_capability_readiness_matrix.py` now snapshots `_snapshots/capability_readiness.json` over plugins + booted components + loaded skills (70 caps: 33 plugin / 24 component / 13 skill) and **fails CI** on: capability drift (added/removed/state-changed, e.g. a plugin silently disabled WIRED→SEAM or a component fails to boot), a **fabricated VERIFIED** (VERIFIED/GA with no `harness_id` — guards the registry invariant), or an **unclassified SEAM**; honest escape sets `INTENTIONALLY_SEAM`/`PENDING_VERIFY` kept non-stale by a test (the route-auth SEC-3 pattern). **Interface-contract drift gate ✅** — `tests/test_interface_contract_drift.py` snapshots `_snapshots/interface_contracts.json` over the **shared cross-agent schemas** (the kernel `Action`/`Decision`/`Capability`/`Budget` dataclasses — THE contract every Gate-K-mediated action crosses — + the `Verdict`/`Mediation` enums + the A2A pydantic wire bodies) and **fails CI** on any field add/remove/rename/retype or enum-value change (a contract change must be conscious; regenerate via `python tests/test_interface_contract_drift.py --update`). Guards the guard (a broken introspector returning `{}` is caught) + a vanished-contract check. This is the **multiplier-risk half of V3** — N parallel agents/brokers/routes that build these objects can no longer silently break each other. **Pending:** subagent ad-hoc return-dict shapes (not statically introspectable — would need a runtime-capture variant) |
| V4 | **Promote eval → required release gate** (folds **H23.4**) with the north-star + counter-metrics as merge gates — quality can't regress at fleet speed. | 3 | P1 | V1 | 🟡 **deterministic eval gate + persistent baseline done** — `north_star.GUARDRAILS` encodes the MOONSHOT §6 bounds (interrupt ≤4/day, reject ≤0.5, %-local ≥50, p95 <2s) + `check_guardrails()`; `compute_north_star()` surfaces `guardrail_breaches`/`guardrails_ok`; None metrics are skipped, not fabricated. Companion `--ci-gate` now records to a cache-backed `DatasetStore` in the nightly workflow, so deterministic baseline compare is no longer inert on GitHub-hosted scheduled runs. **Pending:** live-model eval on a persistent owner/live runner + hard merge-blocking on **real-usage** north-star data (offline CI has none). |
| **Gate V** | the readiness board is live; **nothing reaches VERIFIED** without a green reality-harness. | — | P0 | V1–V4 | VERIFIED claims are harness-backed, not asserted |

### Track P — Live Capability Packs (breadth on the substrate, fleet-parallel) (P0–P2)

> Each pack = drive its rails **SEAM→VERIFIED**, mediated by Track K, gated by Track V. (Maps = competitive-gap themes deepened.)
> **P1 design spec:** [`docs/superpowers/specs/2026-06-23-orizont24-p1-proactive-autonomy-design.md`](docs/superpowers/specs/2026-06-23-orizont24-p1-proactive-autonomy-design.md)
> — the loop is already wired end-to-end (`observer`/`watchers` → `policy` → Telegram inbox → `TaskExecutor`
> → write-back/social/call → `north_star`); P1 = drive it SEAM→VERIFIED on the K/V substrate + close 3 proof
> gaps (unified "Today" timeline · night-shift north-star split · proposal-funnel diagnostics).

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| P1 | **Proactive autonomy core** — missions + watchers + digest + governed write-back (deepens 0.32/0.38/0.45). *Do first: the only pack that directly moves the north-star (actions accepted/week) and that stress-tests K3's interrupt budget.* | 8 | P0 | K1–K4, V1–V2 | "works while you sleep" demonstrated **and measured**; interrupt/reject within budget · 🟢 **proof-gap 1/3 — proposal-funnel diagnostic ✅**: `north_star.compute_north_star` now returns a `proposal_funnel` block (cohort over proposals *created* in the window → surfaced / accepted / rejected / pending + `surface_rate`/`accept_rate`), so a low north-star is **diagnosable** (not enough proposed? proposed-but-never-surfaced? surfaced-but-rejected?). Served on `GET /api/metrics/north-star`; `tests/test_north_star.py` (+3). · 🟢 **proof-gap 2/3 — night-shift north-star split ✅**: `compute_north_star` now returns a `night_shift` block (`{done, pct, window}`) — of the accepted actions, how many *completed* during the local night window (buckets each `done` task by the local hour of `updated_at`, reusing the worker's `is_night_window()`; the endpoint threads `autonomy.night_start/end`). So **"works while you sleep" is a reported number**, not a slogan. `tests/test_north_star.py` (+3, TZ-robust). · 🟢 **proof-gap 3/3 — unified "Today in Jarvis" timeline ✅**: new `memory/timeline.py:build_unified_digest(queue, memory_entries, …)` fuses what Jarvis *did* (done autonomy tasks) and what it *learned* (new/updated memory facts) into one timestamp-ordered feed; served at `GET /api/dashboard/today?days=1` (`user_guard`'d, clamped 1–30). Pure builder over existing rows — reuses `digest.py` + the SQLite fact store, no new capture. `tests/test_timeline.py` (+9). **All 3 P1 proof-gaps closed** — the loop is now diagnosable (funnel), the overnight claim is measured (night-shift), and "today" is one story (timeline). |
| P2 | **OSINT / WorldView** — correlation, evidence drawer, world-brief routing (deepens 0.40/0.41). Most differentiated surface; forces the kernel to prove governance on **untrusted** data. | 8 | P1 | K1, V1 | pack VERIFIED; ingestion trust-boundary enforced (closes the F12/AUD ingestion finding) · 🟢 **offline pack + governance rail done**: `osint/correlate.py` — pure, deterministic correlation over *provided* evidence (no live fetch): groups by indicator (casefold for token kinds), builds findings with a provenance chain + corroboration-based confidence (capped <1.0 for all-untrusted intel — never certain), and **taints untrusted-source evidence at ingestion** (`security.taint`), propagating it through `writeback_payload`. `POST /api/osint/correlate` + `/api/osint/brief` (`user_guard`'d, offline). **The P2 contract is VERIFIED by a hermetic reality case** (`reality_harness`, `plugin:worldview`): an OSINT write-back the policy *would* GRANT is escalated **GRANT→QUEUE** by the real `kernel.authorize` when it carries untrusted-source taint, while the same operator-sourced write is GRANTed — untrusted intel can never auto-execute (closes the ingestion-trust AC with real primitives, no mock). `tests/test_osint_correlate.py` (+11); route parity/auth/openapi reseeded. **Owner-gated (live):** real collection — SpiderFoot modules + the WorldView REST + news feeds — needs keys/network (the engine is the deterministic rail; live fetch is wiring). |
| P3 | **Market Intel + Finance** — watchlists, balance/analytics, alerts with disclaimers (deepens 0.39). Concrete daily utility. | 5 | P1 | K1, V1 | pack VERIFIED; daily brief demoable · 🟢 **offline pack + money-safety rail done**: `market/analyze.py` — pure, deterministic intel over *provided* quotes/positions (no live fetch): `evaluate_watchlist` (band breaches → alerts, honest `no_quote` when none supplied — never a fabricated price), `portfolio_snapshot` (net worth + per-position weight + by-kind allocation, drops unpriced rows), `daily_brief` (demoable headline). **Every alert/brief carries a mandatory not-advice `DISCLAIMER`.** `POST /api/market/watchlist` + `/api/market/brief` (`user_guard`'d, offline). **The P3 contract is VERIFIED by a hermetic reality case** (`reality_harness`, `plugin:balance`): a market-triggered **money action** (`trade.buy`/`transfer`) is held by the real `kernel.authorize` — `IRREVERSIBLE_OR_MONEY` → **QUEUE** (approval) — while read-only `market.monitor` is **GRANT**ed. **Money never auto-moves**; the pack watches the market freely but can't act for you. `tests/test_market_intel.py` (+10); route parity/auth/openapi/hud-v2 reseeded (332 routes). **Owner-gated (live):** real quotes/bank data — a broker/quotes API + the `balance` plugin (ING/Libra) — needs keys/network (the engine is the deterministic rail; live fetch is wiring). |
| P4 | **Creative / Publishing** — coordinated asset pipeline + export/render packs (deepens 0.47/0.50; also fuels **0.52 Product Demo Factory** / marketing). | 5 | P2 | K1, V1 | pack VERIFIED; export packs render (YouTube/IG/README) · 🟢 **offline planner + publish-safety rail done**: `creative/pipeline.py` — pure, deterministic pipeline *planner* over a brief (no media-gen): `plan_pipeline` (ordered stages script→image_prompts→render→assemble→export, each carrying provenance + the null generator it *would* call + `generated:false`), `build_export_packs` (per-platform delivery **specs** for **YouTube/Instagram/README** — aspect/size/format/caption-kind; unknown targets dropped, never invented). **Nothing is faked as generated.** `POST /api/creative/plan` + `/api/creative/export-packs` (`user_guard`'d, offline). **The P4 contract is VERIFIED by a hermetic reality case** (`reality_harness`, `plugin:social_x`): the pipeline drafts/plans freely (`creative.draft` → **GRANT**), but the terminal **release** (publishing a finished campaign to the world — irreversible) is held by the real `kernel.authorize` — `IRREVERSIBLE_OR_MONEY` → **QUEUE** (approval). **Nothing is auto-published on your behalf.** `tests/test_creative_pipeline.py` (+7); route parity/auth/openapi/hud-v2 reseeded (334 routes). **Owner-gated (live):** real render (image/video models) + the platform upload APIs need keys/network (the planner is the deterministic rail; render/publish is wiring). |
| **Gate P** | per pack: **VERIFIED** via the reality-harness **and** the north-star is moving. | — | P0 | Gate V | no pack ships SEAM-only |

> **North-star alignment (by construction):** P1 drives *actions accepted/week*; K3 enforces the
> *interrupt budget*; V4 guards *reject-rate, %-local, p95-latency* as merge gates — the program can't
> drift off the metric without failing its own gates. **Totals:** 12 items + 3 gates, ~68 SP
> (K ≈21 · V ≈21 · P ≈26). **Design specs written** for both substrate tracks (K + V, linked above) —
> next is *implementation*, not design. **Next concrete steps:** finish Phase A (AUD-\*) → land the
> default-off `kernel.authorize` facade (**K1**) + the capability-readiness registry/harness scaffold
> (**V1/V2**) in parallel → wire the action-auth + readiness matrices → K3/V4 gates → then **P1 first**.

---

## 🗺️ ORIZONT 25 — M1→1.0 Execution Plan (Fable-5 snapshot, 2026-07-02)

> **The active execution order for everything that remains before 1.0** — written to be followed
> by ANY AI session (any model tier, cold start, mid-session handoff) without deviating.
> **Full blueprint (per-item Intent / verified seams / Approach / AC / tests / do-NOTs + the
> execution protocol + quality charter):**
> [`docs/superpowers/specs/2026-07-02-orizont25-execution-blueprint.md`](docs/superpowers/specs/2026-07-02-orizont25-execution-blueprint.md).
> Ground truth it stands on: the [2026-07-02 fresh-eyes re-verification](docs/research/2026-07-02-fresh-eyes-backlog-reverification.md).
> Not net-new scope — it sequences the existing tracked items (K3, TASK-3 tail, V3/V4, H23.17,
> AUD-16, AUD-14, H18.x, H23.22, #169) + a small owner-sanctioned **Track Q** (companion quality).
>
> **Protocol digest (the blueprint's §0, read it in full before your first PR):** verify before
> you claim (evidence = test run or code read) · grep the symbol, not the line — if a seam is gone,
> STOP and re-read the item's Intent, never improvise architecture · one item = one PR, rebase-first,
> BACKLOG status ticked in the same PR · behavior changes default-off + byte-identical default path ·
> honesty contract on every surface (no fabrication, honest empty states) · offline injectable tests,
> re-seed parity snapshots via `--update` in the same PR · when two readings are valid, pick the
> reversible/default-off one and record the fork in the PR body · red truth beats green lie ·
> never touch: LOCAL_ONLY fail-closed paths, shipped migrations, recovery paths (disengage/reset),
> snapshots by hand, another agent's draft-PR files, an agent's voice without owner consent.
>
> **2026-07-03 protocol exception:** `e1f1de8` (`feat: wire companion eval gate and quality checks`)
> bundled M1.3/M1.4/M1.5/M2.2/M2.4/M2.6 because the local Codex batch was already intertwined.
> Treat it as a recorded deviation, not precedent; follow-up ORIZONT 25 work returns to one item = one PR.

### M1 — v0.12 «Substrate sealed»

| # | Item | S | Status |
|---|------|---|--------|
| M1.1 | **K3 budget unification** — named dimensions on `kernel/budget.py:BudgetLedger`; `InterruptBudget` becomes a view; payment/mission caps registered as observed dimensions; handler `tokens_used` hook | 5 | ✅ done (2026-07-03) — `BudgetLedger` now exposes named dimensions/status and kernel denial for enforced overages; `InterruptBudget` is a ledger-backed view; payments/mission caps publish observed dimensions without replacing their existing denials; `TaskExecutor` reports handler `tokens_used`; action-kernel binding can carry the shared ledger. `tests/test_k3_budget_unification.py` (+6). |
| M1.2 | **`Action.origin` channel threading** — `Gateway.route → channel_handler →` per-turn ContextVar → brokers; inbound channels = `origin="inbound"` → kernel GRANT→QUEUE (the honest TASK-3 channel backstop) | 5 | ✅ done (2026-07-03; H17.1a hardening 2026-07-05) — `Gateway.route` classifies trusted HUD/voice turns as `generated` and external channels as `inbound`; `channel_handler` binds the origin in a per-request ContextVar; governed-action brokers read that context for kernel `Action.origin`, so inbound-channel actions that policy would GRANT are escalated to QUEUE while kernel-off behavior stays byte-identical. H17.1a moved the invariant down to the public turn chokepoints too: direct `handle_input`/`handle_input_stream` callers (MCP/webhooks/routers/tests) get origin binding by construction, internal orchestrator channels remain trusted, inbound parent contexts are monotone, and plugin-egress actions carry the current origin. `tests/test_m12_origin_threading.py` (+5), `tests/test_h17_origin_by_construction.py` (+8). |
| M1.3 | **V3 components/skills readiness coverage** — booted-fixture records in `test_capability_readiness_matrix` (today: plugins only, 33 records) | 3 | ✅ done (2026-07-03) — matrix now boots the real orchestrator + skill loader via a deliberately cached heavy fixture (an exception to the usual `__new__`/light-fixture convention because this gate needs registry truth), snapshots 70 capability records (33 plugin / 24 component / 13 skill), and explicitly classifies the manifest-only `skill:Weather Intel` SEAM row. |
| M1.4 | **LIVE/SEED chip rollout** — `PanelChip` (`gap.tsx:28`) onto the ~25 remaining Console panels (mechanical) | 2 | ✅ done (2026-07-03) — every Console `Card` now declares a `live`/`seed` signal (58/58), guarded by `panel-chip-coverage.test.ts`; opt-in surfaces use SEED when disabled. |
| M1.5 | **Q4 voice-persona consent gate** (0.28) — persisted owner consent before cloned/persona voice; default voice + honest banner otherwise | 2 | ✅ done (2026-07-03) — `voice.persona_voice_consent` seeds default-off; `TTSEngine` blocks XTTS/ElevenLabs persona voices before consent and falls back to safe Edge defaults with `last_consent_status`; `/api/voice/capabilities` and `PersonaModule.status()` expose the honest banner/status; covered by `tests/test_q4_voice_consent.py`. |

### M2 — v0.13 «Quality gates & type truth»

| # | Item | S | Status |
|---|------|---|--------|
| M2.1 | **H23.17 flow E2E** — chat send→SSE→stop + voice state machine on the existing Playwright harness (degraded-reply assertions, no model needed) | 3 | ✅ done (2026-07-03) — Playwright now drives chat send→SSE token/final render, stop-button abort on an in-flight stream, and voice push-to-talk with mocked mic/STT into a chat turn; `playwright.config.ts` now starts the backend cross-platform (Windows dev + Linux CI). `frontend/e2e/hud.spec.ts` (+3 e2e specs). |
| M2.2 | **Nightly soak + browser matrix** — `schedule:` lane on `e2e.yml` (N-iteration soak vs `/metrics`), firefox/webkit/mobile-emulation projects | 3 | ✅ done (2026-07-03) — `e2e.yml` now has schedule/workflow_dispatch, scheduled runs flip `E2E_BROWSER_MATRIX=1` + `E2E_SOAK_ITERATIONS=3`, install Chromium/Firefox/WebKit, and publish the soak plan; Playwright config adds Firefox/WebKit/mobile projects behind the env flag; `hud.spec.ts` now asserts `/metrics` golden-signal families during the soak. Local execution still requires frontend deps/browsers (CI/dev lane). |
| M2.3 | **AUD-16 OpenAPI→TS typegen + CI diff gate** — `response_model=` on the ~30 HUD-consumed routes; boot server in CI (e2e pattern) → `openapi-typescript` → fail on diff | 5 | ✅ done (2026-07-03) — committed `frontend/src/api/schema.gen.ts` from the live FastAPI `/openapi.json`; added pinned `npm run typegen:openapi` (`openapi-typescript@7.13.0`) and a CI `openapi-types` lane that boots the backend, regenerates the schema, and fails on `git diff`; guarded by `tests/test_openapi_ts_typegen_gate.py` (+3). Consumer migration remains gradual by design. |
| M2.4 | **V4 eval as scheduled blocking lane** — nightly `EvalRunner` over `DatasetStore` vs baseline (`JARVIS_EVAL_LIVE` gated); north-star guardrails in the job summary | 3 | 🟡 partial (2026-07-04) — deterministic drift/min-score gate, DatasetStore-backed run, GitHub summary, and offline north-star guardrail status are wired through `companion_eval --ci-gate` and `.github/workflows/eval-nightly.yml`. **Baseline persistence is done in #506:** CI restores/saves the explicit `JARVIS_EVAL_STORE` with immutable run-id cache keys and a dataset/source hash restore prefix, so scheduled run N+1 can compare against run N. Live-model lane remains pending a persistent/live runner; `JARVIS_EVAL_LIVE` is still only the opt-in switch/status today. |
| M2.5 | ⭐ **Q1 companion golden-dialogue eval set** — 40–60 RO/EN dialogues scoring the §6.2 charter (assistance, empathy-without-sycophancy, follow-up, in-character honesty, refusal); judged via `QualityMonitor` + `SycophancyIndex`/`HonestyJudge`; versioned in `DatasetStore`, gated by M2.4 — **the quality snapshot that survives model changes** | 5 | ✅ **done (2026-07-02)** — `observability/companion_eval.py` + `companion_dialogues.json` (**48 dialogues**: 6 charter dimensions × 8, 30 EN + 18 RO, synthetic personas; authored by 6 Fable-5 drafters + 6 adversarial reviewers, 33/48 hardened in review). Deterministic scorer (no LLM): hard-fails on `forbid`/missing-`gold`/insubstantial, soft-scores expect/`sycophancy_signals` (honesty.py) with pushback escalation; diacritics-insensitive matching. **Keystone invariant test-pinned: every golden scores 1.0 against its own rubric** (`golden_self_check`). `seed_dataset()` versions into the H9.3b `DatasetStore` (change-detected, no version spam); `run_suite()` = in-process full-rubric path; CLI `--self-check`/`--seed` for the M2.4 lane. `tests/test_companion_eval.py` (+14: integrity/coverage/bilingual, pre-normalized rubric entries, synthetic-only PII gate, goldens-pass-own-rubric, capitulation-fails-every-pushback-case, forbid-hard-fail, seed idempotence, golden-runner scores 1.0 + run recorded, sycophant-runner fails the gate). *Remaining durable lane = live runner; baseline persistence is handled by O26-P3.3.* |
| M2.6 | **BUG-2b.3 `useVoice` tests** — jsdom mocks for mic/AudioContext, drive the status machine (`voice.ts:49`) | 2 | ✅ done (2026-07-03) — added `frontend/src/test/voice.test.tsx` with mocked `getUserMedia`/`MediaRecorder`/`AudioContext`/`Audio`/fetch/streaming TTS, covering capabilities load, mic-muted/STT-unavailable errors, one PTT turn, and streaming→`/tts` fallback. Local Vitest execution is blocked in this sandbox by absent `frontend/node_modules` + npm registry `EACCES`; run in CI/dev deps to confirm. |

### M3 — v0.14 «Reach & proof»

| # | Item | S | Status |
|---|------|---|--------|
| M3.1 | **Mobile approval queue** (then Dashboard, Tasks) — `GET /autonomy/approvals` + `POST /autonomy/tasks/{id}/decision` (`routers/autonomy.py:362,208`) from the phone; PARITY.md row in same PR — *the north-star surface* | 5 | ✅ done (2026-07-04, #509) |
| M3.2 | **Plugin-gated HUD modes honest wiring** — Finance/Health/Knowledge/Family + Comms threads via the `live.ts` swap pattern; honest empty state when unconfigured. ✅ Done 2026-07-04 (#505): Build/Comms/Finance/Health/Knowledge/Family now feed LIVE/SEED mode keys, `/plugins.configured` prevents enabled-but-unconfigured plugins from looking live, `balance` mock payloads stay SEED, and empty Comms channels render without seeded inbox threads. Remaining owner blockers: live bank/broker/quotes keys, Apple Health LAN bridge, websearch backend, WhatsApp bridge URL/hardware, and self-hosted fonts. | 3 | ✅ done |
| M3.3 | **H23.22 landing page (dev half)** — static, self-contained, from `docs/marketing/` + BRAND_BOOK tokens; demo shot-list support (0.52) | 3 | ✅ done (2026-07-04, #512) — `marketing/landing/index.html` + `demo-shot-list.md`; owner video remains M4 |
| M3.4 | **AUD-14 config consolidation** (pulled forward — 161 env reads and climbing) — one `env_config` module + one `truthy()`; policy sets derived from `agents.yaml` **keeping the code-enforced LOCAL_ONLY floor** (BUG-14 lesson) | 3 | 🟡 partial / latest slice merged (#622) — O26-P2.1 delivered `env_config` + the boolean ratchet; #592 closes the `JARVIS_CHANNEL_SEND_RATE` numeric-env seam through `env_int()`. #596 adds `agents/core/llm/model_config.py` as the shared home for model-name defaults and `JARVIS_DEEP_MODEL`. #620 moves `JARVIS_PLUGIN_GRANTS` to shared `env_list()` parsing. #622 moves trust-status mic/strict-local reads to shared `env_flag()`. |
| M3.5 | **#169 WorldView MCP write transport** — stdio client path for `watch_aoi`/`reconstruct_event` behind plugin-gate+kernel, with the HMAC token folded into the governed capability path (last K2 slice) | 5 | ✅ done (2026-07-06, #594) — `WorldViewMCPWriteClient` gates writes through `PermissionGate`, Action Kernel, per-agent `plugin:worldview` broker capability, and a scoped `WORLDVIEW_MCP_SECRET` HMAC token before calling the stdio MCP tools. `ArgusInterface` exposes `watch_aoi`/`reconstruct_event` only through that governed path while `WorldViewPlugin` stays read-only. Full PR CI was green before merge. |
| M3.6 | **Q2 persona-consistency rail** — persona dimension on the live `QualityMonitor` judged vs the SOUL's current version (`soul_versioning`); drift alert like quality-decline | 3 | ✅ done (2026-07-04, #510) — `QualityMonitor` now accepts versioned persona profiles derived from the current SOUL, scores the assistant `output_preview`, stores `persona_score`/`soul_version`, and exposes a separate persona drift alert. Full PR CI green before merge. |
| M3.7 | **Q3 caring follow-ups in the morning brief** — `build_morning_brief` + `build_unified_digest` recomposition: yesterday's failed/blocked tasks, open-concern facts, upcoming KG dates; zero new capture, rides the existing brief slot | 3 | ✅ done (2026-07-04, #510) — morning brief + unified digest now reuse a read-only caring-followup extractor over failed/blocked tasks, open-concern memory facts, and upcoming/date facts; `/autonomy/brief` and the scheduled morning digest read the existing `MemoryStore`. Full PR CI green before merge. |

### M4 — v1.0-rc «Proof» (owner-led, runs in PARALLEL from day one — the true critical path)

⭐B0 manual run + 72h soak → record **AUD-0** + **H23.23** → GitHub-settings batch → license flip →
**recruit 1–3 design partners** (north-star on a non-owner install ≥2 weeks — calendar-bound!) →
GPU-opportunistic (H13.3 config-only · H22.4 · H12.14/TASK-1) → tag **1.0.0** only when
MANUAL_TESTING signs off **and** real-usage data exists. Details: blueprint §5 + `docs/OWNER_TASKS.md`.

> **Track Q = the companion charter** (blueprint §6.2, owner-sanctioned 2026-07-02): *caring is
> behavior, not adjectives · smart is honest (sycophancy is a measured defect) · personality is
> designed and it's a promise (in-character always, mask drops for a sincere "am I talking to an
> AI?") · a friend respects your attention (≤4/day as character trait) · problems get the
> diagnose→preview→act-reversibly→verify→report loop, not vibes · privacy is the friendship's
> foundation and outranks every other clause.* Q1/Q2 make it regression-guarded, not aspirational.
>
> **Non-goals until 1.0** (re-affirmed): 0.20 Vault · 0.48 video · 0.64/0.65 desktop overlay ·
> 0.66 connector breadth · ~~AUD-13~~ (promoted into O26 P1.1) / AUD-15 refactor · multi-user.
> MOONSHOT §4: we don't skip gates.

---

## 🚂 ORIZONT 26 — «Bolt the train to the rails» (deep-dive plan, owner-approved 2026-07-03)

> **The active plan superseding ORIZONT 25's sequencing** (O25's engineering table is complete except
> M2.4's tail — its protocol + charter stay in force). Source: a 3-lens full-code deep dive
> (runtime intelligence · safety substrate · product surface), every finding `file:line`-verified
> twice. **Thesis: the rails are magnificent, but the train isn't bolted to them** — the flagship
> promises («knows you», «every action governed», «one inbox», «works while you sleep») are dormant
> or bypassed in a default install for specific, fixable reasons. Full plan with findings, decisions,
> ACs and seams: [`docs/superpowers/specs/2026-07-03-orizont26-bolt-the-train.md`](docs/superpowers/specs/2026-07-03-orizont26-bolt-the-train.md).
>
> **Owner decisions (2026-07-03):** D1 Product Posture ✅ (onboarding consent switch, 2 waves,
> default-off exception recorded) · D4 WorldView **stays active** (issues #254–259/#265 + #169 + #170
> sequenced as Phase 4) · D7 HUD **finish the design** (wire all 6 preview modes + the
> HUD_V2_REMAINING punch-list; blockers → BACKLOG rows, not silent stubs).

### Phase 0 — Truth & Correctness (verified findings F1–F6)

| # | Item | S | Status |
|---|------|---|--------|
| O26-P0.1 | Golden-loop harness (fake LLM at `generate()` seam only) + loop #1 skeleton | 3 | ✅ done (2026-07-03) — `tests/test_o26_golden_loop_chat.py`: real 17-agent `Orchestrator(JarvisConfig())` boot, `FakeBackend` injected only at `select_backend`, offline. **+ harness-ul partajat** `tests/golden_harness.py` (fake instalat prin seam-ul `detect()`, izolare `JARVIS_HOME`; biblioteca de fixture pentru loops #2–#5) + `tests/test_golden_loop_chat.py` (+3: non-stream `handle_input` → reply rutat local + memoria sesiunii + learning/bench/run-history + entități/KG (`lives_in`) + istoricul turei 1 în promptul turei 2 la seam-ul LLM; stream: tokeni + memorie + record-seam post-F1) |
| O26-P0.2 | **F1**: stream path calls `_record_interactions` (web chat finally feeds KG/learning/run-history; %-local re-baselined) | 2 | ✅ done (2026-07-03) — `handle_input_stream` now runs `_log_session` + `_record_interactions` (route_name/agent_id pre-bound); **red-proven** (loop #1 fails on pre-fix code); stream/non-stream symmetry + empty-target guards pinned (+3 tests) |
| O26-P0.3 | **F2**: seed `cognition.*` + `memory.recall_enabled/top_k` in DEFAULTS; `put_category` upserts known-spec keys | 2 | ✅ done (2026-07-03) — 13th settings category `cognition` (master OFF, 5 sub-flags ON so one switch wakes the layer) + `memory.recall_enabled/recall_top_k`; `put_category` upserts spec-known keys, still rejects arbitrary rows; facade wakes via the settings path (+9 tests) |
| O26-P0.4 | **F4**: sycophancy axis scores the assistant reply, not the user input (`cognition_trace.py:93,124`) | 1 | ✅ done (2026-07-03) — traces carry `output_preview`; honesty scores the reply (user text passed as context); same mis-aim fixed in `quality.evaluate_heuristics` (empty reply now scores `non_empty=0`; legacy key-absent traces keep the fallback) (+5 tests) |
| O26-P0.5 | **F5**: deep-model escalation only when the deep model is probed present (no reroute-to-missing-model on «analyze») | 2 | ✅ done (2026-07-03) — `LLMRouter` captures the full served-model listing on detect/refresh; `_deep_model_available()` gates BOTH deep sites (auto heavy-keyword + DEEP_THINK_AGENTS, which now fall through to normal routing on a one-model box); explicit `JARVIS_DEEP_MODEL` = owner intent, honored (+6 tests) |
| O26-P0.6 | **F6**: hardened/bind boot guards run from the app lifespan (uvicorn entry included); Run-block docs point at `serve.py` | 2 | ✅ done (2026-07-03) — guards moved to `agents/core/boot_guards.py` (serve.py re-exports, existing imports intact); `web.py` lifespan runs `enforce_boot_posture()` so a raw-uvicorn start enforces the same posture; honest residual documented: a bind host passed only as a raw `--host` CLI flag (without `JARVIS_HOST`) is invisible to the app — deploy templates use the env knob and serve.py stays canonical (+10 tests) |
| O26-P0.7 | **F3**: broker proposals run `policy.decide`; `pending_decisions()` includes broker-`proposed`; kill-switch enforced at the executor seam kernel-independently; golden loops #2+#4 | 5 | ✅ done (2026-07-03) — `AutonomyWorker.govern_enqueue` (sync governed intake, drop-in for `TaskQueue.enqueue`): runs the risk policy and applies the STRICTER of caller-level vs policy outcome (broker always-ask can't be weakened; kernel-granted `act` can still be tightened by money caps); `ask` lands BLOCKED → decision inbox + best-effort push. All 5 broker wirings in `autonomy_coordinator` route through it (fail-safe fallback to the raw queue). `pending_decisions()` = blocked ∪ proposed (both await a human; PROPOSED→APPROVED is legal). `worker.tick()` honors the kill-switch KERNEL-INDEPENDENTLY: halted → tasks held APPROVED (nothing lost), run on first tick after disengage; a broken switch never blocks the tick. Golden loops #2 (propose→inbox→approve→execute) + #4 (halt stops the seam, disengage releases) in `tests/test_o26_f3_unified_funnel.py` (+9). *Honest scope note: `payments` keeps its dedicated mandate-gated approval flow (its own store + surface, not the task queue).* Blast-radius sweep: 172 tests green across worker/queue/policy/inbox/social/writeback/call/node/tool-rpc/digest/north-star/timeline. |

### Phase 1 — One Turn Pipeline

| # | Item | S | Status |
|---|------|---|--------|
| O26-P1.1 | **AUD-13 promoted pre-1.0**: unify `handle_input`/`handle_input_stream`; ONE prompt builder (persona + runtime-state in both); one record seam; `PersonaModule.nudge` per turn; preserve #492's `action_origin` ContextVar. Oracle: golden loops ×2 postures + M2.1 E2E | 8 | ✅ done (2026-07-04) — `Agent.build_prompt()` is now the reusable agent prompt wrapper; both plain chat and stream feed it through shared `_build_agent_turn_text()` so persona, runtime truth, history, plugins and recall no longer diverge by surface. Post-LLM memory/checkpoint/session log/learning+bench/run-history/audit/cognition now share `_complete_llm_turn()`; `PersonaModule.nudge()` fires once per completed LLM turn when cognition affect is enabled; `action_origin` binding remains untouched and the record seam still runs through `asyncio.to_thread` with context propagation. `tests/test_o26_p1_one_turn_pipeline.py` (+3) red-proved the old split (plain lacked runtime, stream lacked persona, no affect nudge). Local targeted sweep green across P1.1, golden chat loops, stream abort, concurrent stream isolation, chat HTTP, prompt-injection guard, agent integration, token budgets, bench/record, persona and cognition suites. |

### Phase 2 — Wake the Intelligence

| # | Item | S | Status |
|---|------|---|--------|
| O26-P2.1 | AUD-14 config consolidation (posture prerequisite; 161 env reads, ≥3 truthy conventions; LOCAL_ONLY floor kept) | 3 | ✅ done (2026-07-04) — `agents/core/env_config.py`: stdlib-only leaf (modeled on `paths.py`), read-at-call-time, never raises/logs, NO dotenv; ONE `truthy()` (truthy {1,true,yes,on} / falsy {0,false,no,off,disable,disabled}, case-insensitive, **unknown → the flag's declared default** — so junk can never open `JARVIS_ALLOW_INSECURE_BIND` nor relax `JARVIS_STRICT_EGRESS`) + `env_flag/env_str/env_int(minimum=)/env_float`. A workflow inventory (163 sites, 55 files, 122 vars) found **8** divergent conventions, not 3 — incl. case-sensitive sets where "TRUE"/"off" silently did the wrong thing, `== "1"` exact-match, an inverted disable-flag, `_env_int` written twice, and `JARVIS_WORKFLOW_PERSIST=0` *enabling* the coordinator drain the engine read as off (now one `engine.persist_enabled()`). All boolean parses migrated (29 sites); local helpers (`_env_flag`, `_env_truthy`, `_TRUTHY`/`_TRUE` consts, 2× `_env_int`) deleted or aliased; import-time constants stayed import-time (setattr-pinning tests untouched); hardened/CDX-12 layering + LOCAL_ONLY floor byte-identical. Ratchet: `tests/test_o26_p2_env_config.py` (+36) source-scans runtime code and fails on any new ad-hoc parse (red-proved: 35 hits pre-migration). |
| O26-P2.2 | Nightly consolidation/decay job in `scheduler_service` + LivingMemory wired at the turn seam | 3 | ✅ done (2026-07-04, #501) — `_complete_llm_turn()` now feeds completed plain+stream LLM turns into `LivingMemory.encode()` and registers matching H14 `DecayMemory` records **only when** `cognition.enabled && cognition.memory_enabled`; default-off stays inert. LivingMemory stores session/agent/channel, a turn reference, text digest, and size counters rather than duplicating raw transcript text, and decay labels stay metadata-only. `SchedulerService` registers `memory-consolidation-decay` (02:40) and `run_memory_maintenance()` runs NREM+REM consolidation, then ranks decay/candidates without auto-deleting anything. `LivingMemory.records()` exposes an inspectable retrieval surface for the integration seam. `tests/test_o26_p2_memory_consolidation.py` (+7) red-proved the dormant seam/job and the CodeQL/logging regressions, verifying default-off no-op, enabled turn records, nightly tick, disabled-job no-op, safe maintenance exception logging, counter-only maintenance completion logs, and no raw transcript duplication in LivingMemory/decay records; targeted adjacent sweep green (33 passed), full PR CI green before merge. |
| O26-P2.3 | Dormant-module disposition: wire-or-park `ensemble`/`learning`; park `profile_extractor` (zero callers) | 2 | ✅ done (2026-07-04, #502) — active agents now populate `PersonaModule` + `EnsembleModule` immediately after `load_agents()`, so `/api/cognition/personality` and `/api/cognition/ensemble` expose the real 17-agent roster instead of empty dormant modules. Governed learning is not parked: `tests/test_o26_p2_dormant_disposition.py` proves `cognition.learning_enabled` feeds the autonomy `calibration_hook` and only adds caution. `profile_extractor` remains import-compatible but is explicitly parked via `legacy_status()` (`active=false`, no production callers), with MemoryStore + LivingMemory turn seam as the live path. +4 tests; targeted cognition/persona/learning/memory sweep green (48 passed), full PR CI green before merge. |
| O26-P2.4 | **Product Posture (D1 ✅)**: settings-backed named posture composing `JARVIS_HARDENED`; wave 1 memory/persona → wave 2 kernel/budgets/REDACT; consent screen = final onboarding step; p95 AC | 3 | ✅ done (2026-07-04, #503) — `product.posture` settings key defaults OFF; `companion_wave1`/`design_partner` wake the proven wave-1 memory+cognition flags at runtime, surface provenance in `/api/security/posture`, onboarding wizard, and support bundle; wave 2 kernel/budget/REDACT hardening stays explicit future scope. |
| O26-P2.5 | Install smoke path (~30s boot+`/readyz`+faked turn; full suite behind `--dev`) | 2 | ✅ done (2026-07-04, #504) — `scripts/install_smoke.py` boots a real 17-agent orchestrator with exactly one fake local LLM backend, checks `/readyz`, and runs one deterministic chat turn; default path is fast, `--dev` runs the full pytest suite after smoke. |

### Phase 3 — Finish the Designed Surface (D7)

| # | Item | S | Status |
|---|------|---|--------|
| O26-P3.1 | Wire the 6 preview modes live (Build/Comms/Finance/Health/Knowledge/Family; honest plugin-gated empty states; owner-key blockers → BACKLOG rows); ghost-manifest cleanup (~22 real modules); `balance` mock → honest SEED. ✅ Done 2026-07-04 (#505): `MODE_LIVE_KEYS` covers all 6 preview modes; Build reads workflows/marketplace/sandbox; Comms reads rooms + registered Discord/Slack channel status; Finance reads saved watchlist/payments and refuses mock balances; Health/Knowledge/Family require configured Apple Health/websearch/WhatsApp plugins; `/plugins` reports runtime `configured`; `/status` reports channels. | 8 | ✅ done |
| O26-P3.2 | HUD_V2_REMAINING punch-list: §2 Console depth (Settings editor, Prompt A/B UI, Data Spaces CRUD, Secrets form, Rooms) · §4 cockpit (task-fan, per-message TTS+mic, cognition SSE) · §5 TweaksPanel · §6 fonts | 8 | 🟡 partial (merged #507 + #515 + #517; capability check UI in #519; current-mesh task fan in #521; preferences/tweaks UI in #523; self-hosted fonts in #525) — reconciles stale HUD_V2_REMAINING claims against code and adds a Vitest guard. Verified shipped: settings editor, prompt A/B/diff/rollback/preview/commit, Data Spaces list/create/delete/assign/unassign, Rooms create/send/history drawer, capability issue/check UI, current-mesh `/tasks` task fan, command-palette look/density/motion/texture tweaks, self-hosted Space Grotesk + JetBrains Mono WOFF2 assets, secret store form, LM Studio controls, heartbeat/run/status, sandbox execute, per-message TTS, mic loop, cognition SSE, strict-local/mic topbar. #551 adds Safe Comms channel inbox transport v0 for telegram/web threads + governed replies. Still open: owner live-data/plugin setup and non-v0 inbox channels (email/WhatsApp). |
| O26-P3.3 | M2.4 completion: persist the eval-store baseline across nightly runs so baseline-compare bites | 2 | ✅ done (2026-07-04, #506) — `companion_eval --ci-gate --store-root` writes to an explicit store; nightly workflow restores/saves that store via pinned `actions/cache/{restore,save}` with run-id keys + dataset/source restore prefix; tests pin CLI store-root and workflow cache wiring |
| O26-P3.4 | M3.1 mobile approval queue over the *unified* funnel (dep: P0.7) | 5 | ✅ done (2026-07-04, #509) — Expo mobile gains an Approvals tab over `GET /autonomy/approvals` + `POST /autonomy/tasks/{id}/decision`, with optional `X-Admin-Token` settings support and parity ledger update. |
| O26-P3.5 | Q2 persona rail (now scoring the right text; dep P0.4) + Q3 caring follow-ups in the brief (golden loop #3) | 3 | ✅ done (2026-07-04, #510) — persona rail derives compact profiles from current SOUL versions at the live cognition trace seam and adds `signals.persona`/persona drift stats; caring follow-ups are recomposed from existing failed/blocked tasks + memory facts in the morning brief and unified digest. `tests/test_o26_p3_5_persona_caring.py` (+6) plus adjacent quality/digest/timeline/autonomy endpoint suites were green locally; full PR CI green before merge. |
| O26-P3.6 | Landing page, dev half (M3.3) | 3 | ✅ done (2026-07-04, #512) |

### Phase 4 — WorldView active workstream (D4, owner call; parallel lane)

#258 startup parity → #255 live MCP contract test → #254 Signal-Layer cockpit in the real HUD →
#256 SignalLayerPlugin for Jarvis/Argus → #257 governance-safe recommendations (pairs with P0.7) →
#259/#265 demo polish → **#169 MCP write transport** (unblocks the last K2 slice: WorldView HMAC →
kernel Capability) → #170 live Neo4j validation. Stays runtime-opt-in for partners.

### Phase 5 — Proof (owner-led, parallel from day 1 — the true critical path)

⭐B0 + record AUD-0/H23.23 → GitHub settings + license flip → **partner release channel** (partners
pin tagged releases + upgrade drill) → recruit 1–3 partners; north-star on a non-owner install ≥2
weeks, **re-baselined post-P0.2** (pre-fix data excludes all web-chat activity) → 72h soak → tag 1.0.

### Phase 6 — Guard rails (continuous)

Park-list guard (**revised 2026-07-11** for the expanded 1.0 gate; implementation = **H23.28**):
`image_gen`, `media_gen/media_skill`, `desktop_operator`, `browser_agent`, `screen_grounding`,
`satellite_hub`, `node_mesh`, `e2e_sync`, `wyoming`, `training/`, `rust/` stay frozen **until the
proof-track milestones are recorded (A1 ⭐B0 + A2 72h soak) and partner recruitment has started
(A7 in progress)** — then they unfreeze **in phases, as the substrate of the AI-OS horizons**:
**wave 1** with ORIZONT 28 (`browser_agent`, `desktop_operator`, `screen_grounding`) · **wave 2**
with ORIZONT 29 (`image_gen`, `media_gen`, `media_skill`) · **wave 3** with ORIZONT 30/33
(`wyoming`, `satellite_hub`, `node_mesh`, `e2e_sync`). `training/` and `rust/` remain frozen until
explicitly pulled by an owner decision. A PR carrying `unpark:` remains the per-PR escape hatch;
WorldView explicitly NOT on this list per D4 ·
new-test policy: golden-loop behavioral by default, wiring/parity only for new route surfaces ·
✅ HUD-E2E lane now triggers on `agents/core/**` (oracle gap found reviewing #498: the lane boots
the real backend, but the pipeline-rewiring PR never ran it because the path filter stopped at
`agents/web.py`).

---

## 🧩 ORIZONT 27 — Capability Registry & Unified Action API (Nerva Program A · AI-OS Phase 1, direction 2026-07-11)

> **Mission:** agents reason over a machine-readable capability inventory instead of hardcoding
> actions; one call path (`perform()`); every capability carries risk, contract, verification,
> rollback and earned confidence. **Builds ON (do not rebuild):** the O24 V2 registry
> (`observability/capability_registry.py`, SEAM→WIRED→VERIFIED→GA), `automation_contracts.py`,
> the action-auth matrix (`tests/test_action_auth_matrix.py` + `_snapshots/action_auth.json`),
> the H20.R1 model-directed loop (`agent_runtime.py`). Vision: [NERVA_VISION.md](NERVA_VISION.md) §6
> · provenance: [2026-07-11 archive](docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md).
> → Version **v0.21.0**.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H27.1 ✅ | **Registry schema v1** — `CapabilityRecord` now carries `description/inputs/risk/requires/supports/verification/rollback/confidence/implementation` while preserving the O24 readiness + harness fields and the existing plugin/component/skill derivation; `action:<kind>` records join the same registry (no parallel system), and `/api/metrics/capabilities` is additively enriched. Conservative defaults never fabricate verification or autonomy: every record starts at confidence `0.0` until H27.7 earns it from outcomes. Evidence: `capability_manifests.py`, `tests/test_capability_registry.py`, `tests/test_h27_capability_manifests.py`. | 5 | P0 | O24-V2 | NERVA_VISION §6 |
| H27.2 ✅ | **Capability manifests** — the runtime action-auth snapshot is authoritative and currently contains **12** patterns (the older estimate said 11); all 12 have explicit risk, inputs, kernel/contract refs, supports, verification, rollback, confidence and implementation metadata, with an exact-set drift test. All **33** governed built-in plugins derive complete metadata from their existing `PluginManifest`, keeping network/data policy single-sourced; every plugin defaults conservatively to `sensitive` because network/data scope alone cannot prove read-only behavior. | 5 | P0 | H27.1 | `action_auth.json` |
| H27.3 ✅ | **Unified Action API** — default-off (`JARVIS_UNIFIED_ACTION_API` **and** existing `JARVIS_ACTION_KERNEL`) async `CapabilityActionAPI.perform(capability_id, params, ctx)` validates the manifest/input contract and returns stable disabled/refused/queued/completed/failed truth. New bindings are kernel-mediated exactly once; existing brokers and ToolRPC use guarded delegated adapters accepted only for action kinds already classified `KERNEL`. Review hardening binds token capability-name to the manifest action, requires a broker-bound method + live kernel hook, and refuses non-gated ToolRPC tools — preventing bypass and double authorization. DENY/QUEUE never execute; handler failures are redacted. H27.4 model-directed selection remains deliberately separate. Evidence: `capability_actions.py`, `tests/test_h27_capability_actions.py`. | 8 | P0 | H27.1, O24-K1 | NERVA_VISION §6 |
| H27.4 ✅ | **Registry-aware planning** — `ToolRPCServer` now carries optional `capability_id`; the live registry derives `tool:*` records and the production echo/time tools declare identity. Behind default-false `llm.registry_planning_enabled`, `AgentToolRuntime` offers only WIRED/VERIFIED/GA tools with registry description/inputs/risk/readiness/confidence; missing/SEAM/malformed/duplicate records fail closed. No match returns an honest refusal before any provider call, and a provider cannot hallucinate a filtered tool back into execution (the filtered subset is enforced at execution too). Flag OFF preserves legacy metadata/flow. Evidence: `tests/test_h27_registry_planning.py` + full Agent Runtime v2 suite. | 5 | P1 | H27.3 | H20.R1 |
| H27.5 ✅ | **Verification field live** — all **84** capability refs in the complete runtime inventory resolve one-to-one to executable V1 `RealityCase`s: 12 actions traverse the real `CapabilityActionAPI` + kernel/policy + isolated kill-switch, 2 live tools traverse real ToolRPC, 33 plugins exercise their actual manifest-driven egress boundary without sockets, 24 components prove boot-status + constructed runtime object, and 13 skills prove discovery + loaded module. The scheduled reality lane now executes the dynamic boot-registry pack. All 69 WIRED plugin/component/skill cases pass hermetically; the intentionally manifest-only `skill:Weather Intel` case fails honestly and remains SEAM. A green runner remains the only in-process VERIFIED promotion path; V3 still forbids fabricated/durable promotion. Evidence: `capability_verification.py`, `reality_harness.py`, `test_h27_capability_verification.py`, `test_reality_harness.py`. | 3 | P1 | O24-V1/V3 | — |
| H27.6 ✅ | **Rollback contracts** — every capability record now serializes a validated `RollbackContract` (`mode/description/automatic/handler_ref/limitations`) instead of an unstructured promise. Contradictory contracts fail closed (`automatic` requires a handler; `none` cannot claim one). The shared autonomy projection resolves exact/wildcard action manifests, exposes `capability_id + rollback` in `/autonomy/tasks` and `/autonomy/approvals`, and returns `null` for unknown kinds; browser Decision Inbox and native Approvals show the story before approval. No automatic undo dispatcher or false reversibility claim was added. Evidence: `capability_manifests.py`, `routers/autonomy.py`, focused backend/browser/mobile tests. | 3 | P2 | H27.2 | — |
| H27.7 ✅ | **Confidence & earned autonomy** — real terminal action outcomes are durably upserted in the existing `autonomy.db` (no payload/PII): `DONE` counts once, terminal retry exhaustion counts one failure, and executor-less `noop`, interim retries, unknown actions, approvals/rejections do not earn trust. Registry action confidence is the conservative 95% Wilson lower bound plus success/failure/sample provenance; an unavailable ledger degrades to confidence 0 without hiding action records. Policy reads confidence only through the worker-bound private ledger provider (caller payloads cannot spoof it). `autonomy.earned_autonomy_enabled` is seeded/live-synced **OFF by default**. When explicitly enabled, only `auto` mode with `n>=20` and confidence `>=0.80` may lower **one** rung (`ASK→NOTIFY` or `NOTIFY→ACT`) while retaining the original risk tier. Explicit `ASK/OFF`, per-agent asks, tainted input and all kernel/token/contract/budget/kill-switch rails remain authoritative; H27.7 never lowers `IRREVERSIBLE_OR_MONEY` (existing within-cap money behavior is unchanged, never confidence-derived). Evidence: `queue.py`, `worker.py`, `policy.py`, `capability_registry.py`, `test_h27_earned_autonomy.py`. | 5 | P1 | H27.1 | NERVA_VISION §7 |
| H27.8 ✅ | **Registry read surface** — canonical user-guarded `GET /api/capabilities` exposes the same live registry snapshot while legacy `/api/metrics/capabilities` remains compatible. The HUD Verification Fabric now reads the canonical route and renders bounded per-record risk, supports, confidence and readiness columns; route/OpenAPI/auth snapshots and generated TS schema are pinned. Mobile registry-board parity is visible as H18.21 (approval rollback parity shipped in this wave). Evidence: `routers/analytics.py`, `ReadinessPanel`, `test_capability_registry.py`, `readiness-panel.test.tsx`. | 2 | P2 | H27.1 | V2 panel |

> **Total ORIZONT 27:** ~36 SP

## 🖱️ ORIZONT 28 — Computer & Browser Operator (Nerva Program B · AI-OS Phase 2a, direction 2026-07-11)

Fixed since: ✅ **browser request-path DNS offload, covered end-to-end** (#948) — the
`/api/browser/check` + plan-preview SSRF lookups already moved to a worker thread; this adds the
router-level loop-responsiveness regressions in `tests/test_h15_1_browser_agent.py` so the seam
cannot silently go back on-loop.


> **Mission:** turn H15's complete-but-stubbed governance into real actuation; the action
> hierarchy **API → CLI → structured UI → visual** becomes an explicit router that always picks
> the lowest-risk implementation. **Builds ON:** `browser_agent.py` (GovernedBrowser — egress
> allowlist + approval queue stay byte-identical), `desktop_operator.py`, `screen_grounding.py`,
> `llm/vlm.py`, `core/environments/` (local/docker/ssh). Hermes catch-up items S1/S3 live here.
> → Version **v0.22.0** · unpark wave 1.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H28.1 ✅ | **Real Playwright driver** behind `GovernedBrowser` (host seam; the Null driver stays the test default; governance layer untouched) · **delivered 2026-07-12** — optional `PlaywrightBrowserDriver`, owner-enabled and dependency-lazy, with bounded observations, sanitized explicit-directory downloads, fresh context, explicit pre-start URL guard on every routed request/redirect/subresource, service workers blocked, deterministic close, and no ambient browser profile | 8 | P0 | H15, H27.3 | NERVA_VISION §4-P3 |
| H28.2 ✅ | **Action-hierarchy router** — given a goal, prefer API → CLI → structured UI automation → visual computer use; visual is the audited fallback, never the default · **delivered 2026-07-12** — `ActionHierarchyRouter` selects but never executes; readiness-gated deterministic ordering, explicit visual opt-in, bounded tamper-evident decision audit, and honest no-route/degraded states | 5 | P1 | H27.3 | NERVA_VISION §4-P3 |
| H28.3 ✅ | **Terminal-target abstraction** over `core/environments` — named execution targets (`bonobo-windows`, `pi-house`, `isolated-sandbox`) with per-target capability policy + audit chain (Hermes has backends, not the audit — superiority S3) · **delivered 2026-07-12** — strict named-target registry over local/docker/SSH backends, per-agent/per-capability allow/approval/deny policy, safe default targets, and a bounded persisted SHA-256 audit chain that refuses corrupt history; policy plane only, no transport bypass | 5 | P1 | H27.2 | NERVA_VISION §8 |
| H28.4 ✅ | **Desktop actuation** behind `GovernedDesktop` — accessibility-tree first, proven-local VLM/screen-grounding fallback, durable human-approved ToolRPC execution, and execution-time `desktop.step` Action Kernel mediation for click/type/launch. Default-off host/isolation flags, bounded proposal preflight + execution-time revalidation, live accessibility injection classification, fail-closed malformed/disabled outcomes, and `finally` cleanup are covered by the H28 host/route/operator suites. **Hermetic completion:** the canonical operator pack reaches the real `WindowsDesktopDriver`, `DesktopActionExecutor`, ToolRPC, SQLite autonomy queue, `TaskExecutor`, and kernel rails. **Owner/live gate remains honest:** real Windows UIA + installed Playwright Chromium validation is still opt-in on the owner host and is not claimed by CI. | 8 | P1 | H28.1 | H15.3 |
| H28.5 ✅ | **Operator reality-harness pack** — `OPERATOR_CAPABILITY_CASES` contains **7/7 passing hermetic contracts**: GovernedBrowser→Playwright, accessibility-first→proven-local fallback, durable approved ToolRPC→TaskExecutor→kernel→click/type/launch, kill-switch DENY, live accessibility injection block, malformed/disabled fail-closed paths, and success/error cleanup. Every result carries measured action/governance/approval/execution/block/cleanup counters and proves `ungoverned_actions == 0`; production-seam spies prevent a bypassing stub from fabricating the pass. Live owner-host validation remains explicitly required. | 3 | P1 | O24-V1 | NERVA_VISION §8-S1 |
| H28.6 ✅ | **Unpark wave 1** — `browser_agent`/`desktop_operator`/`screen_grounding` are permanently removed from `PARK_POLICY` after the H28 reality pack passed. Exact-policy tests preserve wave 2 (`image_gen`/`media_gen`/`media_skill`), wave 3 (`wyoming`/`satellite_hub`/`node_mesh`/`e2e_sync`), owner-only `training/` + `rust/`, and `park-policy` self-protection unchanged. PR declaration remains `unpark: park-policy`; `unpark: wave-1` records the graduation. | 1 | P2 | H23.28 | O26 Phase 6 |

> **Total ORIZONT 28:** ~30 SP

> **H28.4 HUD depth completion (2026-07-14):** Console → Build → Operator now provides bounded
> browser policy/plan dry runs and preview-first governed desktop submission over the existing
> routes. Edits invalidate the desktop preview, canonical snapshots are submitted, outcomes separate
> proposed/queued/blocked/failed/partial/executed, and partial runs warn against whole-plan retry.
> Native mobile hides `toolrpc.desktop_run` payloads and omits Approve while retaining Reject/Defer.
> The owner/live UIA + Chromium gate above remains open; no host execution is claimed by this update.

## 📺 ORIZONT 29 — Multimedia Director (Nerva Program C · AI-OS Phase 2b, direction 2026-07-11)

> **Mission:** one verb — `present(content, target_device, mode, urgency, duration)` — on every
> screen and speaker in the house; play the right thing on the right device. **Builds ON:**
> `plugins/spotify_plugin.py` (real playback control), `media_catalog.py`/`media_export.py`,
> interrupt budgets. The initial audit found no Chromecast/`media_player` abstraction; the
> governed, default-off fabric and its owner-wired host seams are now delivered.
> → Version **v0.23.0** · unpark wave 2 complete.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H29.1 ✅ | **`media_player` abstraction + device registry** — Chromecast (pychromecast), Spotify Connect, browser-tab kiosk, local player; discovery + capability per device · **delivered 2026-07-12 (O29 wave 1)** — `agents/core/media_director.py`: `MediaDevice` (strict identity/support validation; kinds: chromecast/spotify_connect/browser_tab/local/speaker/tv) + `DeviceRegistry` (byte/item-bounded, atomic, thread-safe, corrupt-safe store; room-aware `resolve_target` that refuses ambiguity; injectable `discover()` seam — pychromecast/host scanners stay owner-wired host seams, `NullMediaDriver` default refuses honestly) | 5 | P0 | — | NERVA_VISION §4-P5 |
| H29.2 ✅ | **The `present()` capability** — content × device × mode × urgency × duration, kernel-mediated (reversible tier), registered in the O27 registry · **delivered 2026-07-12** — `MediaDirector.present()` on the O27 facade as kernel kind **`media.present`** (ACTION_REGISTRY + manifest + action-auth snapshot): `MEDIA_PRESENT_CONTRACT` (0.45 discipline) → `resolve_content` (http(s)-only URLs; local paths root-allowlisted) → target capability check → etiquette → bounded driver seam → **driver-status verification** (never asserted) → session record. `restore()` has its own mediated **`media.restore`** action; both routes refuse when the unified API/kernel are off — no unmediated device path. | 5 | P0 | H29.1, H27.3 | NERVA_VISION §6 |
| H29.3 ✅ | **Content resolvers** — local/NAS media, the T-0.46 media catalog, URLs via the governed browser; honest "can't resolve" states · **completed 2026-07-13** — `catalog` ids and unique bounded `query` matches resolve through the real opt-in `MediaCatalog`, then revalidate the selected path/URL at execution time. Local refs require an existing regular file under an explicit root; URL refs use `GovernedBrowser.preview()` with an explicit allowlist plus SSRF policy and never fetch during resolution. Missing/ambiguous refs fail before driver invocation with bounded candidates/provenance; malformed roots/allowlists fail closed. Task-1 verification: 82 focused tests plus Ruff/Bandit/diff-check clean. | 3 | P1 | H29.2 | — |
| H29.4 ✅ | **Media session state + interrupt etiquette** — don't break a movie for a P3 nudge; rides the K3 interrupt budgets · **completed 2026-07-13** — thread-safe persisted `SessionBoard`, one-level bounded restore snapshots, and `may_interrupt()` etiquette remain in force. Active high-urgency interruption now consumes the request-scoped live `orch.autonomy.budget`; missing, malformed, or exhausted budgets refuse before the driver, while idle/low/normal paths consume nothing. `duration_seconds` is accepted only by an explicitly duration-capable driver and included in status verification and restore; unsupported duration refuses before actuation. | 3 | P1 | H29.2 | MOONSHOT §5.4 |
| H29.5 ✅ | **Media reality-harness pack** + honest degraded modes (device offline ≠ crash) · **completed 2026-07-13** — the canonical hermetic H29 pack covers default-off/null refusal, local generation → real catalog → kernel/action API → driver-verified presentation, durable cloud approval, explicit governed-browser summarizer policy, and kernel halt with zero driver calls. Its causal ledger measures `ungoverned_actions == 0`; host tripwires prove no ambient network/device/generation path. Task-3 gate passed 152 focused tests plus 128 release/action/kernel/parity checks (one expected live-host skip). | 2 | P2 | O24-V1 | — |
| H29.6 ✅ | **Unpark wave 2** — `image_gen`/`media_gen`/`media_skill` graduated from `PARK_POLICY` on 2026-07-13 after the H29 reality pack. Only these three entries moved: local generation keeps an explicit local guard, cloud generation remains durable-approval gated, summarization requires an explicit governed URL seam, and all default/null constructors fail closed. Wave 3, owner-only modules, `training/`, `rust/`, and park-policy self-protection remain frozen. | 1 | P2 | H23.28 | O26 Phase 6 |

> **Total ORIZONT 29:** 19/19 SP implementation complete. The browser Console and native mobile
> Media surfaces share the unchanged guarded API, distinguish disabled/queued/refused/unverified/
> verified outcomes, and never embed remote media. Real Chromecast/Spotify/host-driver execution
> remains an explicit owner-host seam and is not claimed by the hermetic completion gate.

## 🏠 ORIZONT 30 — House Brain (Nerva Program D · AI-OS Phase 3, direction 2026-07-11)

Fixed since: ✅ **house control path off the event loop** (#955) — HA origin re-resolution already
moved to a worker thread; this extends it to the rest of the control path: governed intake's sqlite
enqueue, the outcome-stats read, the execution ledger's lookup/begin/finish/abort round-trips, and
strong-confirmation mint/confirm/consume (the latter two exposed as `*_async` seams so routes await
them instead of blocking). Gated by `tests/test_house_actuator_async.py` and
`tests/test_house_request_path_dns.py`.


> **Mission:** a live model of the home — devices, rooms, occupants, presence, policies — with
> governed actuation. Home Assistant is the device abstraction layer; Jarvis sits above it as the
> reasoning and authority layer. **Builds ON:** `plugins/homebridge.py` (LOCAL_ONLY),
> `plugins/iot_control.py`, `voice/wyoming.py`, the bi-temporal KG (H14). **Verified missing
> today:** any HA REST/WebSocket state integration; the house graph. → Version **v0.24.0** ·
> unpark wave 3 (with O33).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H30.1 ✅ | **Home Assistant adapter, read-first** — REST/WebSocket state (entities, areas, sensors), LOCAL_ONLY, honest empty state without HA · **completed 2026-07-13** — strict-local/default-off adapter with SecretBroker credentials, DNS-rebinding defense, bounded REST snapshots, authenticated WebSocket events/reconnect backoff, and named degraded/offline states; no cloud fallback or mutation surface. | 5 | P0 | — | NERVA_VISION §4-P4 |
| H30.2 ✅ | **Device/room/occupant graph** on the bi-temporal KG — rooms contain devices, observed_by cameras, occupied_by people; queryable · **completed 2026-07-13** — public topology projects into the existing bi-temporal KG while occupant/presence records stay encrypted, pseudonymous, consent-scoped, revocable, tombstoned, key-rotatable, and explicitly purgeable in the private house store. | 5 | P0 | H30.1, H14 | NERVA_VISION §4 |
| H30.3 ✅ | **Presence & context inference** (local-only) — who is home, which room is occupied, privacy context per room · **completed 2026-07-13** — bounded local sensor fusion emits typed house events with confidence/freshness; stale or ambiguous evidence fails closed, private-room identity is withheld, and the path proves zero egress. | 5 | P1 | H30.2 | — |
| H30.4 ✅ | **Governed actuation** — HA service calls through the kernel per the graduated ladder; lights/climate earn auto-within-bounds; **locks/doors/security never below strong confirmation** (hard floor) · **completed 2026-07-13** — narrow canonical light/climate/security actions flow through durable TaskQueue → TaskExecutor → Action Kernel → allowlisted HA services → fresh-state verification. Security uses exact, expiring, single-use strong confirmation; retries are idempotent, failed verification rolls back through a separately governed recovery action, and Windows SQLite handles close deterministically. | 5 | P0 | H30.1, H27.7 | NERVA_VISION §7 |
| H30.5 ✅ | **`GET /api/house/state` + HUD panel** — the house graph visible, honest empty state · **completed 2026-07-13** — guarded domain router exposes bounded state/proposal/strong-confirmation APIs; browser House HUD and native mobile Home tab share the API and preserve disabled/degraded/private/approval/verified truth. Route, OpenAPI, auth, HUD, and mobile parity ledgers are synchronized. | 3 | P2 | H30.2 | — |
| H30.6 ✅ | **Room-aware voice** — wyoming/satellite unpark; a satellite's room becomes the default output device for `present()` · **completed 2026-07-13** — paired satellite credentials are digest-only, expiry/peer/transport bound, and replay protected; server-owned room identity ignores client spoofing, privacy/ambiguity refuses output, and exactly one room-default device reaches the existing H29 governed media action. `wyoming` and `satellite_hub` graduated from wave 3; `node_mesh`/`e2e_sync` remain parked. | 3 | P2 | O29, H23.28 | H12.4 |
| H30.7 ✅ | **House reality-harness pack** — hermetic HA simulator proves the rail; live = owner-gated · **completed 2026-07-13** — the canonical pack passes **7/7 hermetic production-rail cases** across read/reconnect/offline, graph/privacy/purge, reversible actuation, security confirmation, verification/rollback, kernel halt, and room-aware output. The causal ledger measures `ungoverned_actions == 0` and rejects unapproved HA mutations; the read-only live probe requires both generic reality-harness and explicit H30 owner opt-in, with missing configuration reported degraded rather than passed. | 3 | P1 | O24-V1 | — |
| H30.8 | **Ambient light bridge (assistant state → LAN strip)** — the last open item from the 2026-08-06 "J.A.R.V.I.S. in the room" guide (`docs/design/JARVIS_PRESENCE_GAP.md`): a default-off bridge that maps the SAME voice/assistant state the orb renders onto a LAN light controller, so the strip and the sphere can never disagree. WLED first (plain HTTP JSON on the local network, no cloud account, strict-local by construction); Hue/Govee behind their own opt-in since they reach a vendor cloud. Must go through the existing governed device path, stay silent (not guess) when the device is unreachable, and ship with the light OFF by default. | 3 | P3 | H30.4 | NERVA_VISION §7 |

> **Total ORIZONT 30:** 29/29 SP of the original H30.1–H30.7 scope complete. **H30.8 (3 SP,
> added 2026-08-06) is open and sits OUTSIDE that completion gate** — the ambient light bridge
> is new scope, not a regression of the closed seven. The browser House HUD and native mobile
> Home surface share the guarded API; the seven-case hermetic pack proves zero ungoverned actions.
> Real Home Assistant, physical satellite, and household device execution remain explicit owner-host
> validation seams and are not claimed by the hermetic completion gate.

## 📷 ORIZONT 31 — Camera Intelligence (Nerva Program E · AI-OS Phase 4, direction 2026-07-11)

> **Mission:** local-only camera perception — structured events, never continuous footage into a
> model; one transient snapshot is masked before an optional strict-local VLM call; natural-language
> retrieval remains metadata-only. Frigate is the read-only detector/event backend and optional
> ONVIF is discovery-only; Jarvis does not proxy RTSP, record video, or expose clips/private URLs.
> **Privacy-critical: H31.1 precedes every poll, fetch, inference, store, and publication.**
> → Version **v0.25.0**.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H31.1 ✅ | **Privacy contract FIRST** — versioned household consent + generation-bound leases; per-camera/global kill coverage; mandatory masks; hard snapshot/metadata TTL ceilings; identity/face/biometric/plate inference absent by construction | 2 | P0 | — | NERVA_VISION §12 |
| H31.2 ✅ | **Read-only Frigate + discovery-only ONVIF** — bounded LAN-pinned metadata polling and a private transient snapshot seam; no Jarvis RTSP decoder, stream surface, recorder, NVR, or camera mutation | 5 | P0 | H31.1 | NERVA_VISION §4-P1 |
| H31.3 ✅ | **Local detection pipeline** — allowlisted person/vehicle/animal/package events with deterministic zone + line-crossing rules; one already-masked strict-local VLM description on demand only | 8 | P1 | H31.2 | — |
| H31.4 ✅ | **Encrypted event vault + health** — bounded redacted metadata and separately encrypted masked snapshots, exact ≤24h/≤30d expiry, quotas/purge/scheduler, source/storage health | 5 | P1 | H31.3 | — |
| H31.5 ✅ | **Privacy-safe temporal event retrieval** — deterministic NL/filter search over encrypted metadata; no clip persistence/proxy, raw-frame endpoint, or Frigate private URL | 5 | P2 | H31.4 | NERVA_VISION §4-P1 |
| H31.6 ✅ | **Typed metadata-only feeds** — restart-safe bounded fan-out into H30 anonymous house sensors and the default-off H33.1 monitor engine, with per-sink isolation/backpressure | 3 | P2 | H30.2, H33.1 | — |

> **Total ORIZONT 31:** ~28 SP
>
> **Completion evidence (2026-07-13):** canonical H31 reality pack covers no-consent zero-call,
> one-snapshot mask-before-VLM, encrypted storage/retrieval/exact expiry, restart dedupe into H30/H33,
> pre-poll kill, mid-inference revocation/purge, and bounded offline degradation. Every hermetic case
> reports zero ungoverned actions, external hosts, and raw-frame consumers. The separately named live
> local-Frigate read is double opt-in and never treated as a fake pass when owner hardware is absent.

## 🌱 ORIZONT 32 — Capability Acquisition (Nerva Program F · AI-OS Phase 5, direction 2026-07-11)

> **Mission:** instead of "I can't" → "I don't know **yet**" — understand the gap → search
> existing skills → research docs/APIs → generate → sandbox test → approval → registry → reuse
> forever. **Builds ON:** the full skill lifecycle (`skills/{loader,importer,usage,curator,
> proposals,signing,marketplace}.py`, `skill_drift.py`), `self_evolution.py`, the O20 governed
> learning loop, sandbox + quarantine, `grounded_plan.py`. Governed per MOONSHOT §5.7 — the two
> O20 invariants hold in every item (strict-local review model; self-modifications land in
> quarantine/approval, never direct). → Version **v0.26.0**.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H32.1 ✅ | **Gap detection → capability request** — explicit bounded tool/capability misses create encrypted, deduplicated, restart-safe `missing` requests; normal unanswered chat cannot manufacture one | 3 | P1 | H27.1 | NERVA_VISION §4-P6 |
| H32.2 ✅ | **Reuse-first search** — deterministic local registry → installed skill → reviewed marketplace resolution precedes every generation attempt, with durable provenance and an honest `reused / (reused + generated)` metric | 3 | P1 | H32.1 | NERVA_VISION §8-S2 |
| H32.3 ✅ | **Doc-research step** — consented local-SearXNG research uses allowlisted SSRF/rebinding-safe bounded fetches, taint-preserving encrypted extracts, and a hard `ground_plan()` citation gate; phantom citations and implicit cloud/search fallback fail closed | 3 | P2 | H32.2 | T-0.51 |
| H32.4 ✅ | **Generate + sandbox-test harness** — strict-local stdlib-only generation remains encrypted in quarantine and must pass generated, system-owned contract, and mutation tests in a pinned Docker/WASM profile before an immutable receipt permits proposal | 8 | P0 | H32.3 | NERVA_VISION §4-P6 |
| H32.5 ✅ | **Approval → signing → registry** — permanent owner approval plus Action Kernel mediation, receipt recheck, managed manifest signing, atomic sandbox-only package storage, ToolRPC registration, low-confidence outcome projection, and crash-safe rollback are enforced | 5 | P0 | H32.4, H27.7 | MOONSHOT §5.7 |
| H32.6 ✅ | **Acquisition audit trail + rollback** — an encrypted hash-chained bounded ledger covers the lifecycle; guarded browser/admin and read-only mobile surfaces expose honest state, reuse, export/purge, revoke, and rollback without importing acquired code in-process | 2 | P1 | H32.5 | — |
| H32.7 ✅ | **Hermes-parity eval for the loop** — the non-promoting S2 benchmark passes the dedicated digest-pinned Docker CI lane across miss → research → strict-local generation → isolated verification → approval/signing → sandbox execution → reuse, plus tamper, halt, revoke, rollback, host, and network negatives | 3 | P2 | H32.5 | NERVA_VISION §8-S2 |

> **Total ORIZONT 32:** ~27 SP
>
> **Implementation evidence (2026-07-13):** the local H32 pack covers encrypted request/research/
> quarantine/audit stores, deterministic reuse, strict-local generation, receipt-bound sandbox
> verification, permanent approval, signing, marketplace metadata, ToolRPC execution, tamper refusal,
> lifecycle controls, and browser/mobile parity. H32.7 remains intentionally non-promoting; the
> existing Docker isolation CI lane now proves the full S2 lifecycle, no host execution, and no
> generated-code network access against the real pinned container image.

## 👁️ ORIZONT 33 — Ambient Intelligence (Nerva Program G · AI-OS Phase 6, direction 2026-07-11)

> **Mission:** long-running monitors over house/camera/digital feeds + the decision ladder —
> **ignore · remember · monitor · act silently · ask · interrupt** — so proactivity scales without
> noise. **Builds ON:** `core/autonomy/observer.py` (ProactiveObserver — the seed), watchers,
> `autonomy/policy.py`, interrupt budgets (K3), night-shift, the P1 pack's measured funnel.
> → Version **v0.27.0** · unpark wave 3 (with O30).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H33.1 ✅ | **Declarative monitor framework** — default-off named monitors over bounded house/camera/digital projections; durable versioned registry, finite predicate DSL, debounce/hold/hysteresis/cooldown, source health, ownership cutover, and decision journal | 5 | P0 | H30.1 | NERVA_VISION §4-P1 |
| H33.2 ✅ | **The decision ladder as policy** — every event classified ignore/remember/monitor/act-silently/ask/interrupt; interrupts stay ≤4/day *by construction* (K3 budget, not convention) | 5 | P0 | H33.1, K3 | NERVA_VISION §7 |
| H33.3 ✅ | **Situation memory** — observations land in the KG with provenance + decay, so repeated anonymous observations in a bounded place/time window are answerable without claiming re-identification | 3 | P1 | H33.1, H14 | — |
| H33.4 ✅ | **Ambient reality-harness pack** + counter-metric guards (interrupt/reject rates must not degrade as monitors multiply) | 3 | P1 | O24-V1/V4 | MOONSHOT §6 |
| H33.5 ✅ | **Night-shift v2** — overnight monitor work measured on the north-star night split (P1 proof-gap 2/3 seam) | 3 | P2 | H33.2 | P1 pack |
| H33.6 ✅ | **"What is Jarvis watching right now"** — HUD transparency surface listing live monitors + their last decisions | 3 | P2 | H33.1 | — |

> **Total ORIZONT 33:** ~22 SP

## 🛰️ ORIZONT 34 — Mission Control: the swarm cockpit (Nerva Program H, direction 2026-07-24)

Fixed since: ✅ **seeded ADMIN and OBSERVE fallbacks removed from the HUD** (#947) — both surfaces
now read their live APIs (including `/api/admin/agents/stats`, which consequently leaves the
route-parity punch-list) instead of rendering seeded corpora, with vitest honesty regressions and a
rebuilt `agents/web/v2` bundle.


> **Mission:** one Tony-Stark surface where the owner *sees* and *steers* the whole swarm —
> the internal cabinet (17 agents), the autonomy funnel, missions/workflows/sub-agents/A2A,
> **and the dev swarm** (Claude / Codex / opencode / Antigravity coordinating through
> `lock.py` + draft PRs). Read feed + the *existing* governed steering endpoints only — no
> new mutating surface. **Builds ON:** `routers/brain.py` (standalone-page pattern), the
> tracer, autonomy queue + Decision Inbox, Mission Workspaces (0.32), Subagent Gateway/A2A
> (0.33), `lock.py`/`PARALLEL_WORKFLOW.md`.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H34.1 ✅ | **Mission Control v1** — standalone `/mission-control` page (brain.html pattern: self-contained dark HUD, 2s polling) + read-only `GET /api/swarm/summary` aggregating roster + tracer activity, autonomy stats/mode/interrupt budget + payload-free pending preview, missions, workflow runs, sub-agents, A2A inbox count, kill-switch, and the dev-swarm lock files (pure-read, cross-OS reader — never imports `lock.py`). HITL via the existing governed endpoints (`POST /autonomy/tasks/{id}/decision`, `/api/missions/{id}/*`, `/api/a2a/inbox/{id}/decide`) with the shared `hud.admin_token`; without a token the approvals card degrades to counts + payload-free preview. | 5 | P1 | brain, 0.32, 0.33 | acest PR |
| H34.2 ✅ | **Desk presence + away notify** — DONE. Owner-side desk-presence signal (Windows idle/lock daemon or the 0.64 Tauri host overlay) now feeds an `owner.away` state via **NEW `agents/core/autonomy/presence.py`** (`OwnerPresence`: a pure, fail-calm tracker — canonical `present`/`idle`/`away`/`unknown` with OS-alias normalization (`locked`/`active`/…), TTL staleness, and an `is_away()` that is **False** for unknown/stale signals so a missing or dead daemon never self-triggers → **zero behavior change by default**). Reported through **NEW `POST /api/presence/owner`** (admin-guarded — the daemon holds the same `hud.admin_token` as Mission Control steering) + read via `GET /api/presence/owner` (user) and the swarm feed (`/api/swarm/summary.presence` + an OWNER chip on the Mission Control page). When away, decision/approval cards are **also** fanned out to the governed `EscalationRouter` (`ESCALATION_CONTRACT` → WhatsApp/Signal/… allowlist) via **NEW `escalation.AwayNotifier`**, wired into the notifier in `autonomy_coordinator.wire()` (Telegram excluded from the away fan-out — no duplicate on the rich-card channel). Because that wrap runs *inside* the worker's single budget-gated push (`_maybe_push` → attention delivery broker), away-notify costs **no extra interrupt slot** — still ≤4/day by construction (proven end-to-end against a real `AutonomyWorker` push). `tests/test_h34_2_presence.py` (+20). Host daemon = owner-side install (`docs/OWNER_TASKS.md`). | 5 | P2 | H34.1, 0.44 | viziune 2026-07-24 |
| H34.3 | **Dev-swarm PR/CI feed** — open PRs + check status (oracle_bridge plugin, `GITHUB_TOKEN`) next to the lock panel, so draft-PR-as-lock coordination is visible live in the cockpit. | 3 | P2 | H34.1 | AGENT_WORKFLOW.md |
| H34.4 ✅ | **`SwarmPanel` in Console V2** — React port of the page into `frontend/src` (Observe section) so the cockpit is one keystroke from chat; the standalone page stays. **Delivered 2026-08-10:** a read-only `SwarmPanel` (Console → Observe, reusing `useApi`/`Card`/`Row`/`Tag`) renders kernel halt/armed status, agent activity, the autonomy funnel, workspace counts (missions/workflow runs/sub-agents), the A2A inbox when enabled, and which dev-swarm agent (`claude`/`codex`/`opencode`/`antigravity`) currently holds a `lock.py` lock — then links out to `/mission-control` for the full HITL controls. Zero new backend route (reuses H34.1's `GET /api/swarm/summary`); mobile stays the existing H34.1 `➖` intentional-desktop-only marker in `mobile/PARITY.md` (dev-swarm lock files only exist on the owner's dev machine). `frontend/src/test/swarm-panel.test.tsx` (+5: feed read, live-vs-idle dev-lock tagging, halted state, honest offline degrade, cockpit deep-link); full frontend Vitest green (521, +5 on top of the #878 slice), clean `tsc --noEmit`, production build clean, `panel-chip-coverage.test.ts` passes unchanged (Card declares `live=`). | 3 | P3 | H34.1 | HUD_V2_REMAINING.md |
| H34.5 | **Revenue-program pointer** — the "make money" ask stays governed: market intel / social / payments remain draft-first + approval-gated (0.39/0.45/0.68) and Mission Control is where those queued opportunities surface. No autonomous spending — MOONSHOT §5 stands. | — | — | — | MOONSHOT §5 |
| H34.6 ✅ | **Projects workspace + activity timeline** — DONE (via #724). The historical / per-project counterpart to H34.1's live cockpit: a unified **Projects** mode (nav rail + palette) over **Rooms** (topic threads with persistent history + `@mention` roster), **Missions** (budgeted governed workspaces) and **Sessions** (resume an old chat), plus an **activity timeline** that fuses the hash-chained audit (`/api/admin/audit`, admin) with the autonomy queue (`/tasks?view=history`, user) under an all/audit/tasks filter. Titles/decisions/status only — **never payload/result** (no tier leak). Pure frontend — **zero new backend routes** (no snapshot reseed). Closes items 1–3 of `docs/design/HUD_FOLLOWUPS_COWORK_SPEC.md`. Code: `frontend/src/gap.tsx` (`ProjectsMode`, mounted at `app.tsx` `mode === 'projects'`; `ActivityTimelinePanel`, which composes `RoomsPanel`/`MissionsPanel`/`SessionsPanel`). The no-tier-leak guarantee is now pinned by `frontend/src/test/activity-timeline-panel.test.tsx` (+8: payload/result/error never rendered, decision-over-status, audit `summary` per `admin.py`'s `content_preview AS summary` alias, undated rows dropped, newest-first fusion, source filter, 40-row cap, honest empty state). | 3 | P1 | H34.1 | #724 |

> **Total ORIZONT 34:** ~22 SP (H34.1–H34.2 + H34.6 delivered 2026-07-24; H34.4 delivered
> 2026-08-10). H34.3 (dev-swarm PR/CI feed) remains open.

---

## 🔐 Security route-policy gate (audit 2026-06-17 — assessment done, fix pending)

External GPT audit + **runtime verification** (300 routes: 89 admin / 87 user /
**124 open, of which 43 are open *and* mutating**). Guard model is sound; the gap
is routes with **no guard attached**. Footguns on localhost; real unauthorized
control surfaces on LAN/Pi/proxy/tunnel. Full verified write-up + proposed
route-policy table: **`docs/SECURITY_ROUTE_AUDIT_2026-06-17.md`**.

| # | Item | S | P | AC |
|---|------|---|---|----|
| SEC-1 ✅ | **Guard webhook management** — `GET/POST/DELETE /api/webhooks` → `admin_guard`; trigger keeps token/HMAC. Done: `webhooks.py` + contract test (`POST /api/webhooks` off-localhost → 403). | 2 | **P0** | ✅ unauth management → 401/403; trigger still works with token |
| SEC-2 ✅ | **Route-auth matrix test** — `tests/test_route_auth_matrix.py` introspects `app.routes` vs `tests/_snapshots/route_auth.json`; fails CI on guard drift / new or unclassified open mutator. `PENDING_GUARD` set tracks the SEC-3 backlog (shrinks as guards land). | 3 | P1 | ✅ a new unguarded mutator fails CI |
| SEC-3 ✅ | **Apply policy to remaining open mutators** — DONE. Batch 1 (12 → admin): workflows CRUD, plugin toggle, heartbeat ×3, traces/clear, oauth/refresh, oracle sync+resolve, audit/action. Batch 2 (23 → user): workflows run/hierarchical, KG writes ×6, local-docs, reflection, arena ×2, review ×3, eval ×2, autonomy/preview, agent-templates, llm/grammar, schedule/parse, security scan/spotlight. `PENDING_GUARD` is now **empty** — every mutating route is guarded or in `INTENTIONALLY_OPEN` (6 self-authenticating). Final surface: **110 user / 104 admin / 86 open**. Localhost dev unaffected. | 5 | P1 | ✅ enforced by SEC-2 matrix gate |
| SEC-4 | Env/posture follow-ups: **npm Dependabot ✅** · **doc counters refreshed ✅** · **`JARVIS_HOME` runtime-state relocation ✅** (F-08). **Remaining:** promote matrix/parity tests to **required** branch-protection checks (F-10, owner GitHub setting). | 3 | P2 | — |
| SEC-5 ✅ | **F-06 ✅** WorldView bridge Bearer auth (`WORLDVIEW_API_TOKEN`). **F-07 ✅** plugin egress boundary — anchored host/sub-domain matching + `PluginHTTPClient` per-request manifest enforcement, now **strict by default** (`JARVIS_STRICT_EGRESS=0` opts out). Renamed 9 `for_plugin` ids to match manifests; completed allowlists (cloud-llm +Gemini, gmail/gcal +oauth2.googleapis.com, news +RO feeds); self-consistency test pins each plugin's real hosts. | 3 | P2 | ✅ undeclared plugin egress blocked |
| SEC-5b ✅ | **Manifest the remaining networked plugins** — DONE. Added RESTRICTED manifests for `balance`, `analytics`, `websearch`, `digest`, `n8n`, the social/writeback/call families (`social_x`, `writeback_{notion,github,google_calendar}`, `call_{twilio,telnyx}`) and the webhook channels (`channel_{whatsapp,google_chat,teams,signal,matrix}`). Config/env-driven hosts (n8n `N8N_BASE_URL`, websearch `SEARXNG_URL`, Signal `base_url`, Matrix `homeserver`) are handled by a new **`register_dynamic_domain`** runtime allowlist that the egress gate unions with the static `allowed_domains` — no FULL/unmanifested escape. A new registry-driven test (`test_dynamic_family_ids_all_have_manifests`) pins every concrete family member to a manifest so a new member fails CI instead of silently re-opening the gap (the literal-regex test couldn't see the f-string ids). In-code SSRF guards retained as defense-in-depth. **Residual:** per-call webhook URLs passed via `kwargs` to `channel_teams`/`channel_google_chat` are constrained to the Microsoft/Google host suffixes by the static allowlist, not to one specific webhook. | 3 | P2 | ✅ every networked plugin enforced by the gate |

> Verified false-alarms / owner-side (not repo defects): F-04 (auditor's stale
> Windows venv/node_modules — CI builds clean), most of F-05 (needs owner
> Dependabot view). Self-authenticating opens confirmed safe: webhook trigger
> (token/HMAC), a2a/task (peer HMAC, off by default), mcp/server/rpc (disabled by
> default + OAuth), oauth/callback (state-validated).

---

## 📦 Dependency upkeep & the fastapi 0.137 hold (2026-06-19)

Dependabot triage this session — **merged** (safe): `actions/checkout` v6→v7 (#222),
worldview-mcp dev deps (#223), root `vitest` 2→4 + `jsdom` 25→29 (#224). **Held for their own
review cycle:** React 18→19 frontend (#226 — needs v2 bundle rebuild + visual check), WorldView
23-update group (#228), mobile group (#227 — owner-gated, real-device validation per `OWNER_TASKS`).

**fastapi 0.137 upgrade — ✅ RESOLVED (2026-06-19):** fastapi 0.137 wraps `include_router` results in
an opaque `_IncludedRouter` instead of flattening them into `app.routes`, which collapsed the
*introspected* route surface **296→83** and failed the route-parity / auth-matrix guards (the app was
never broken — routes served + appeared in OpenAPI). **Fixed:** `tests/_route_introspect.py`
`iter_effective_routes` flattens the wrappers via fastapi's own `_iter_routes_with_context` (no-op on
≤0.136); both guards use it with **snapshots unchanged**, and `fastapi` is bumped to `>=0.137.2,<0.138`
with `starlette>=0.46,<1.0`. Root cause + repro:
[`docs/research/2026-06-19-fastapi-0.137-include-router-regression.md`](docs/research/2026-06-19-fastapi-0.137-include-router-regression.md).

**2026-07-31 — python-deps bump, verified rather than assumed.** `fastapi 0.139.2 → 0.140.13`
(+ `uvicorn 0.51.0 → 0.52.0`, `annotated-doc 0.0.4 → 0.0.5` transitively) and the `ruff` floor to
`>=0.16.0`. Dependabot's #740 edited the three `requirements*.txt` **without regenerating the
hash-pinned locks**, so its `in-sync` gate was red and — worse — the other 17 checks were green
against the *old* pins: CI installs `--require-hashes` from the lock, so nothing in that run ever
exercised the new fastapi. Locks regenerated with `./scripts/lock_deps.sh`; the upgrade then verified
locally under fastapi 0.140.13 — route-parity, auth-matrix, OpenAPI-parity, route-guard-contract,
release-gate and typegen guards all green, then the full backend suite green. **ruff 0.16's breaking
change does not reach us**: the "413 default rules, up from 59" expansion applies only without an
explicit selection, and `pyproject.toml` pins `select = ["E","F","W","I","B","UP","SIM","C4"]`; the
dev lock had in fact already resolved 0.16.0, so the floor raise is bookkeeping. `ruff check .` clean
on 0.16.1.

---

## 🔍 CodeQL & secret-scanning alerts (2026-06-17 — code fixes shipped; dismissals + ~12 triage pending)

GitHub scanning surfaced 25 CodeQL alerts + 1 secret-scanning alert. Of the 13 reviewed:

| # | Item | S | P | AC |
|---|------|---|---|----|
| CQ-1 ✅ | **Fix the real findings** (merged #215, #216): calendar `create_event` kwargs (#248, was a runtime `TypeError`), heartbeat `except None` (#26), `strip_thinking` ReDoS (#1), possessive template regex (#302), `log_safe()` on two admin log lines (#311/#24), and the secret-scan fixture FP (#215). | 3 | P1 | ✅ all green in CI; merged |
| CQ-2 | **Owner: dismiss FPs/won't-fix in the UI** — secret-scan #1 (test fixture), CodeQL path-injection #22/#23/#431 (agent-id regex blocks traversal), var-defined #299/#298/#247 (used defaults), docs #432. See [`docs/OWNER_TASKS.md`](docs/OWNER_TASKS.md) §GitHub settings. | 1 | P2 | owner GitHub action |
| CQ-3 | **Triage the remaining ~12 alerts** — only 13 of 25 selected were captured (no MCP code-scanning-list tool); needs an owner paste to finish. | 2 | P2 | paste → triage → fix real ones |

---

## 🔎 Fresh-eyes re-verification (2026-07-02 — code-verified backlog truth + July plan)

Five parallel verification agents re-checked every claimed-open item against HEAD (`file:line`
evidence, not status labels). Full report + July sequencing:
[`docs/research/2026-07-02-fresh-eyes-backlog-reverification.md`](docs/research/2026-07-02-fresh-eyes-backlog-reverification.md).
**Verdict:** the backlog is honest (12/16 spot-checks exact); 8 rows were stale in the *pessimistic*
direction and were refreshed in the same PR (#479). Top verified-open engineering, by leverage:

| Rank | Item | Size | Where tracked | Status |
|------|------|------|---------------|--------|
| 1 | **K2 wave-4b** — capability-token *enforcement* (issued at boot, never read back; `kernel/__init__.py:61-64`) + fold WorldView HMAC → truly closes B1 | L | O24 Track K | ✅ done — enforcement landed 2026-07-02, and #594 adds the missing runtime WorldView MCP write caller with scoped HMAC capability minting behind plugin-gate + Action Kernel |
| 2 | **K3** — unify InterruptBudget / mission / payment caps into `BudgetLedger` + handler token hooks | M | O24 Track K | ✅ done (2026-07-03) — M1.1 closed the named-dimension + handler-token hook tail |
| 3 | **TASK-3** — taint marking at ingestion choke points | M | H23.6 | 🟢 **channel ingress tail merged in #590** — producers marked (2026-07-02), M1.2 threads `Action.origin` from inbound channels into brokers, and inbound channel messages are now marked at `Gateway.route()` with private taint metadata plus public inbox taint fields. Full PR CI green. |
| 4 | **TASK-2 tail** — plugin-gated modes · OpenAPI types (AUD-16) | M | TASK-2 | 🟡 partial (2026-07-05) — `WatchlistPanel` ✅, per-panel LIVE/SEED chips ✅ (58/58 Console cards), OpenAPI typegen/diff gate ✅; plugin-gated mode base wiring ✅ (#505); P3.2 stale-doc guard ✅ (#507); local-control tail including self-hosted fonts ✅; Safe Comms channel inbox transport v0 shipped in #551 for telegram/web; remaining tail is owner live-data/plugin setup + non-v0 inbox channels |
| 5 | **H23.17** — chat/voice E2E flows · nightly soak · browser matrix (harness exists, specs don't) | M–L | H23.17 | ✅ done (2026-07-03) — M2.1 + M2.2 closed chat/voice flow E2E, scheduled soak, and browser/mobile-emulation matrix |
| 6 | V1 live contracts · V4 blocking eval gate | M–L | O24 Track V | 🟡 partial — V3 components/skills coverage ✅; M2.4 deterministic drift gate ✅; persistent eval baseline ✅ (#506); **live eval runner ✅ (2026-08-18, H23.4)** — fail-closed `--live-gate` owner-box lane on per-model live datasets + `companion-eval`/`live-eval-evidence` release-gate rows; remaining Track V work is live contracts |

Owner-lane critical path unchanged: ⭐B0 manual run → design partners; plus 2 unrecorded
one-paragraph decisions (**AUD-0**, **H23.23**), the GitHub-settings batch (SEC-4/CQ-2/CQ-3/#242)
and H13.3 (config-only) next time at the GPU box. **July non-goals:** 0.20 Vault · 0.48 video ·
0.64/0.65 desktop overlay · multi-user (Phase E / post-1.0). *(Notă:* AUD-14 se agravează — env
reads ~121 → **161** de la audit; de programat înainte să doară.*)*

**2026-07-02 delivery on ranks 1/3/4** (this PR — Week-1-tail + a scoped K2/TASK-3 slice):
- **K2 wave-4b enforcement** — `kernel.TOKEN_MANDATORY_KINDS = {admin.kill_switch, admin.capability_issue, kg.write}`: a capability token is now genuinely mandatory for these three kinds (`kernel/__init__.py`), not just cross-checked when presented. The real blocker the research flagged — nobody sends `x-capability-token`, so flipping this naively would strand admin/KG operations — is solved without a new operator credential: `kernel.capabilities.issue_operator_capability()` mints a short-lived, single-capability token **on demand, only at the ~9 call sites that reach the kernel** (not the ~130 broader admin/user routes), the instant `_admin_kernel_denial`/`_kg_kernel_denial` finds no *presented* token — the caller already passed `admin_guard`/`user_guard` to reach that point, so this doesn't add trust, it lets already-proven trust flow through the kernel's real capability nucleus instead of tolerating an empty one. `kg_delete_entity`/`kg_delete_relation` gained the `Request` param they were missing (structurally could not carry a token before). `tests/test_kernel_authorize.py` (+5), `tests/test_kernel_capabilities.py` (+3), `tests/test_kernel_bypass_regressions.py` (B1 upgraded from a structural-classification pin to a real fail-closed-without-token proof), `tests/test_admin_kernel_wave.py` (+2), `tests/test_kg_kernel_wave.py` (+3). `docs/THREAT_MODEL.md` corrected (no `PENDING_KERNEL` kinds remain). **2026-07-06 #594:** the WorldView HMAC fold is now live through `WorldViewMCPWriteClient`, which mints scoped MCP tokens only after plugin-gate + Action Kernel approval.
- **TASK-3 taint marking** — `taint.mark()` now called at every producer the research identified before the inbound-channel funnel: `WebSearchPlugin.search()`, `NewsPlugin.get_headlines()`, `DigestSource.fetch()` (+ `DigestAggregator.run()` now carries the mark through to its output, where it was previously stripped by the field whitelist), and the Facebook/WhatsApp archive parsers (`ingestion/parser_{facebook,whatsapp}.py`, gated on `not is_me` — the owner's own messages stay untainted). `tests/test_task3_taint_ingestion.py` (new, +6), `tests/test_websearch.py`/`tests/test_news_plugin.py` (new)/`tests/test_h12_23_digest.py` (+13). **2026-07-05 #590:** the inbound-channel chokepoint (`channels/gateway.py` → `orchestrator.channel_handler`) is now closed with gateway-level metadata rather than wrapping handler text: inbound channel messages get private `_inbound_meta`, Safe Comms inbox rows persist only public taint fields, and outbound replies drop the private envelope before adapter I/O. Full PR CI green including Windows.
- **Week-1 tail** — `WatchlistPanel` (above), per-panel LIVE/SEED chip (`PanelChip` in `gap.tsx`; now all 58 Console cards declare a live/seed signal), chat double-submit guard (TASK-4, above), `InMemoryVectorStore` lock (BUG-12, above).

---

## 🔎 Codex fresh-eyes review (2026-06-24 — external code + doc review)

Independent fresh-eyes review (GitHub-connector read; no local build). Full write-up:
[`docs/research/2026-06-24-codex-review.md`](docs/research/2026-06-24-codex-review.md). **Verdicts
below source-validated against `main` (`e974069`) this session.** The strategic half largely
**validates the current direction** rather than redirecting it: the "Action Kernel" = ORIZONT 24
**Track K**; the trust/readiness board = #300 (partial) + **H23.11/H23.16**; onboarding = **H23.20**;
"finish partials before greenfield" = standing BACKLOG guidance. New, concrete items (`CDX-*`):

| ID | Item | Status | Maps to |
|----|------|--------|---------|
| CDX-1 | ✅ **done** — **`Agent.synthesize()` ignores the routed model** — now unpacks `backend, routed_model, route_name` and applies `routed_model` (same as `process()`), so multi-agent fusion runs on the routed local/cloud model/policy instead of the configured default. `tests/test_cdx_bugfix_batch.py`. | ✅ | — |
| CDX-2 | ✅ **done** — **Interaction records hard-code `"channel":"web"`** — `_record_interactions` now takes the real `channel` (threaded from `process()`/`handle_input()`) into the learning metadata, so the %-local/cloud ratio + per-channel analytics reflect the true origin. `tests/test_orchestrator_process_record.py`. | ✅ | [METRICS](docs/METRICS.md) |
| CDX-3 | ✅ **done** — **One stale `last_n=6`** (`_call_agents_parallel`) now honors `memory.context_window` like the main per-agent path (`:850/859`). | ✅ | — |
| CDX-4 | ✅ **done** — **App version `0.5.0-beta`** retired; `web.py` `FastAPI(version=…)` (and `/status`, OpenAPI `info.version`) now read `agents.__version__` (= `0.11.0`), the single source. `tests/test_cdx_bugfix_batch.py`. | ✅ | CDX-5 |
| CDX-5 | ✅ **done** — **Doc/version/test drift** — version single-sourced (CDX-4) + README badge/headline aligned to v0.11.0. `scripts/status_sync.py` now **auto-derives** the volatile counts (tests from `pytest --collect-only`, routes from the parity snapshot) and `--check`/`--write` keeps STATUS.md in sync — no more hand-bumping (it had already drifted to 327/3,011). `tests/test_status_sync.py` (+7). | ✅ | H23.18 |
| CDX-6 | ✅ **done** — **Per-agent timeout** was a hard-coded `120.0` in `_call_agents_parallel`; extracted to `Orchestrator._agent_call_timeout()` reading the `agents.agent_timeout_seconds` setting (clamped ≥1s, non-numeric → safe 120 default), so the per-agent LLM-call ceiling is visible + tunable instead of one invisible number shared across chat/deep-research/autonomy/eval. `tests/test_orchestrator_process_record.py` (+4). *(Full per-task budget-object integration into the chat pipeline stays a larger refactor — the BUG-5 request pipeline is not safely extractable yet.)* | ✅ | H23.1 / K3 |
| CDX-7 | **Howard RAG provenance** — `agent.py` injects retrieved memory text into prompts; treat memory as untrusted: delimit as retrieved context (not instructions), add source/age/confidence, cap length, scan with the injection scanner. | 🟢 **prompt-level defense done** — new `security/rag_guard.py` is the single choke point every memory→prompt site routes through: `wrap_memory()` fences retrieved memory as `<<RETRIEVED MEMORY … DATA, NOT INSTRUCTIONS>>`, caps length, runs `quarantine.detect_injection` and **redacts** flagged snippets, datamarks the kept body, and tags **source/age/confidence** honestly (`age=unknown` when unstamped — never fabricated; `confidence` omitted when absent). A `datamark` toggle keeps the Howard archive few-shots *readable* (their stylometry is the feature) while still scanning/redacting/fencing them. Wired at all **3 confirmed prompt-string sites**: `orchestrator._recall_block` + the Howard archive RAG in `orchestrator` (stream) and `agent.py`; `manager.remember` now stamps `created_at` so age is real for new writes. `tests/test_cdx7_rag_guard.py` (+13) + `tests/test_cdx7_no_raw_memory_splice.py` (+2, static gate so a raw splice can't silently reappear). Scoped via an **adversarial design review** (caught a NameError-broken taint hook + a test-breaking `UNTRUSTED_SOURCES` edit before they shipped). **Deferred (named follow-ups):** ✅ **agentic-RAG tool path now done** — `rag_tool.MemorySearchTool.search()` returns hit-dicts straight to the model (backs `/api/memory/search-tool`); each hit is now scanned with `quarantine.detect_injection` and **redacted** if flagged (text → `[REDACTED: injection-flagged memory]`, tagged `injection_flagged`, score/provenance preserved), on by default with a `scan=` opt-out. `tests/test_cdx7_rag_tool_scan.py` (+6); clean hits pass through byte-identical. ✅ **action-taint → kernel now done (origin dimension)** — the Action Kernel escalates a GRANT→QUEUE not only on a tainted *payload* but also on an **untrusted declared `origin`** (`is_untrusted_source(action.origin)`): an external HTTP write (`origin="external"`, already declared at `routers/memory_kg.py`), an inbound channel, or a web/rss/osint/worldview feed can't silently auto-execute. The honest model — taint **can't** be propagated *through* an LLM (it launders content), so the kernel trusts the caller's **declared provenance** rather than guessing a data-flow it can't see; default `origin="generated"` (in-house) stays trusted → zero behavior change. `agents/core/kernel/__init__.py` (one escalation clause) + `tests/test_cdx7_action_origin_taint.py` (+11: generated grants, external/osint/inbound/web/rss escalate, payload-taint regression, DENY-precedence, and a static guard that the kg-write site keeps declaring its origin). **Still deferred (genuinely lower-value):** the 2nd recall route `memory_kg.recall_memory` + HTTP `memory_search` (UI JSON, not a prompt). | TASK-3 / 0.37 |
| CDX-8 | **Auto-generated skills are durable behavior** — `skills.auto_generate=true` + `[learn:…]`; ensure human review + sandbox + audit + provenance before a generated skill is reusable. | 🟢 **done** — `[learn:…]` minted a skill from **untrusted LLM output**, then `generate_skill` **self-signed it and exec'd its module in-process on the spot** — strictly *more* trusted than a downloaded skill (an injection→code path that bypassed every marketplace/signature gate). Now **fail-closed by default**: (1) the task/steps/command are scanned with `quarantine.detect_injection` **before anything is written** — flagged content is refused outright (nothing hits disk); (2) a clean skill is minted **`PENDING_REVIEW`** — `_load_skill` registers it (visible/reviewable) but **never exec's its module** (`sandboxed=True`, `signature_reason="pending review (CDX-8 quarantine)"`), regardless of `JARVIS_REQUIRE_SIGNED_SKILLS`; provenance (agent/task/timestamp) is written into the marker; (3) only an **owner** can promote it — `approve_generated_skill()` (admin-gated `POST /api/skills/{name}/approve`) signs + clears the marker + activates, and `GET /api/skills/pending` lists what's awaiting review. Auto-generation stays on; only **promotion-to-executable** is owner-gated. `tests/test_cdx8_skill_quarantine.py` (+6: quarantine-not-exec, no-exec-on-rediscover, injection-blocked in task **and** in command-name, approve-activates, approve-idempotent). ruff + bandit clean; route parity/auth/openapi snapshots reseeded (2 new admin routes). | 🟢 | 0.54 / Track K |
| CDX-9 | 🟢 **DONE (HUD source)** — **Frontend live-wiring hides shape drift** — ✅ **visible LIVE/SEED chip per mode** now lands: `LiveSourceChip` + pure `liveSourceState()` read the existing `useLiveModes()` live-map + demo flag and label each mode **LIVE** (real backend) / **SEED** (demo/mock) / hidden (no source), rendered once at the workzone in `app.tsx`; `frontend/src/test/live-source-chip.test.tsx` (+7). ✅ **the `api/` data layer is now fully typed** — `actions.ts` (real response interfaces threaded through the already-generic `apiGet<T>`), `signalLayer.ts`, and `live.ts` all off `@ts-nocheck` (the whole `frontend/src/api/` directory is `@ts-nocheck`-free), `tsc --noEmit` clean, types erase so the bundle is byte-identical. ✅ **the `data.ts` keystone is now typed** — the pure `V2` seed object (`data.ts`) + its barrel (`ui.ts`) + the shared `primitives.tsx` symbols + `LiveSourceChip.tsx` are all off `@ts-nocheck`; this unblocks the components (which read `V2.<KEY>`). ✅ **`network.tsx` typed** — also surfaced + removed a genuine **dead write** (`NetworkBrain._wrap = el`, a DOM ref stashed on the component *function* and never read; the minifier had already dropped it, so the bundle stays byte-identical) — exactly the "live-wiring hides shape drift" win CDX-9 is for. ✅ **`world_app.tsx` typed** — and it surfaced a real **contract gap**: the shared `Icon` primitive was inferred as *requiring* `sw` (stroke-width), but `sw`/`size` both have runtime fallbacks (`sw||1.6`, `size||16`) and call sites across the HUD omit them; fixed `Icon`'s signature in `primitives.tsx` to mark them optional (the honest contract — unblocks every `Icon` caller, not just `world_app`; erases → bundle byte-identical). ✅ **`world-intelligence.tsx` + `modes_world.tsx` typed** (batched) — same optional-prop pattern again (local `SubH({ children, style })` renders `style={style}`, so `style` is optional; call sites omit it → marked optional), and `modes_world.tsx` came clean with **zero** changes once #386's `Icon` fix landed (its earlier errors were all downstream of that). ✅ **`voice.ts` typed** — first file with *substantive* (non-optional-prop) errors, all fixed type-only (bundle byte-identical): `useVoice`'s `onTurn` callback param (annotated the options shape), `tok(extra?)` optional, a `window.webkitAudioContext` Safari/legacy cast, the TS-5.7 `Uint8Array→BlobPart` lib quirk on `new Blob([frame.audio])`, and the `streamTts` `onFrame` callback's `Promise<unknown>` vs `Promise<void>|void` (cast-preserved the awaited promise so sentence-by-sentence playback ordering is unchanged). ✅ **`modes2.tsx` typed** — surfaced a real **dropped-style drift** (the local `SubH` accepted no `style` and rendered `<div className="sub-h">`, yet 6 secondary section headers pass `style={{marginTop:16/14}}` — silently discarded; the sibling `SubH` in `world-intelligence.tsx` *does* render it for the same purpose). Brought modes2's `SubH` into line → **first bundle-changing slice** (applies the intended ~16px header gaps; flagged for owner eyeball in `REVIEW_QUEUE`), plus a `setAutonomyMode` `unknown`-result narrow (type-only). ✅ **`cockpit.tsx` typed** — clean root-cause fix: the `agentScore` routing accumulator was an untyped `{}`, so `Object.entries` made every score `unknown` and broke the sort/compare/`.win` flag (5 errors); typed it `Record<string, number>` + widened the scored-element type for the `.win` marker (type-only, bundle byte-identical). ✅ **`modes4.tsx` typed** — Finance/Health/Knowledge/Family agent-home modes; all 8 errors were one optional-prop fix (the local `SubH4` already *rendered* `style` correctly — no drift — but was inferred as requiring it while 8 callers omit it; one-line `style?`). Type-only. ✅ **`modes3.tsx` typed** (Chat/Comms/Admin) — richest mix yet, 8 errors / 4 patterns, all type-only: `SubH3` optional `style`; the **`InputBar` contract** relaxed (modes3's distraction-free ChatMode renders it without the guarded `voice/cfg/onCfg/micMuted`, which were inferred required — fixed at `InputBar`'s def in `cockpit.tsx`, one cross-file follow-up); the **plugin-registry `id` drift** (state seeds from `V2.ADMIN.plugins` with no `id`, but live.ts swaps in real plugins *with* `id` and the toggle keys off it — typed the state with optional `id?`); and `togglePlugin`'s `Promise<unknown>` response narrowed `: any` at the read boundary. ✅ **`modes.tsx` typed** (Agents/Trust/Memory) — 9 errors, all type-only: three API-response boundaries (`decidePayment`/`setKillSwitch`/`memorySearch`) → `: any` at their `.then`/`.map` callbacks (live.ts-ingestion style), plus the **PAYMENTS-seed `.id` drift** (live.ts swaps in real payments carrying a broker `id` the lifecycle buttons key off; seed has none → optional `id?` on the map element). ✅ **`app.tsx` typed** (the root composition) — 11 errors → 5 root type-only fixes: `messages` state `useState<any[]>` (narrow-union inference), `seq` step-array annotated `Array<[number,()=>void]>` (tuple→union widening), `mark()` trailing args optional (`j?,jstate?`), `cog` from `/api/cognition` `: any`, and a **dead-code find** — `const ia = 'rail'` is hardcoded so the `ia==='tabs'` Tabs-layout branch is unreachable; typed `'rail' as 'rail'|'tabs'` to keep behaviour identical (Tabs stays unrendered) while making the comparison valid. ✅ **`shell.tsx` typed** (topbar/nav/ticker/columns) — 9 errors / 2 patterns: the `MODES` nav array read a forward-looking `m.locked` "soon"-disable flag no item currently sets (annotated the element type with optional `locked?` + the other optional fields), and the `Meter` primitive required `unit` while 3 callers omit it (it has a `||'%'` fallback → marked optional at `Meter`'s def in `primitives.tsx`). Type-only. ✅ **`gap.tsx` typed** (the big P4c console overlay — 25 errors): the shared `Card`/`Tag` primitives relaxed to optional `sub`/`onReload`/`c`, `act()`'s optional callback, the `SECTIONS` tuple array typed, `dirty`/settings state typed, and the `useApi`/`apiGet`/`apiPut` `unknown` responses narrowed `: any` at their boundaries. **🟢 DONE — the ENTIRE HUD source is now `@ts-nocheck`-free** (0 source modules remain; the only `@ts-nocheck` left is on `src/test/*` fixtures). All 22 source modules typed across #379–#396, `tsc --noEmit` clean, bundle byte-identical at every step except the one intentional drift-fix (#389). The sweep also surfaced + fixed real latent issues: a dropped `style` in modes2, a dead `_wrap` ref in network, the `Icon`/`SubH`/`Meter` optional-prop contracts, the plugin/payment seed-vs-live `id` drift, and the dead tabs-IA branch in app.tsx (all flagged in `REVIEW_QUEUE`). *Remaining for later:* `@ts-nocheck` on the test fixtures + OpenAPI-generated response types (needs a running server) + the move toward `strict` (AUD-15). | 🟢 | H23.16 / AUD-16 / TASK-2 |
| CDX-10 | **`_sys_info()` confident defaults** — returns a default host/GPU when probes fail; a trust/readiness screen should show "unknown", not a possibly-wrong fallback. | 🟢 **done** — `_sys_info()` (served at `/status`) now **probes** every value and degrades to `unknown`/`none`/`0`, never a fabricated host/CPU/GPU/model. Real `socket.gethostname()`; real CPU model from `platform.processor()`→`/proc/cpuinfo`→thread-count (the hardcoded "Intel Core Ultra 9" brand is gone); real RAM via psutil; GPU name+VRAM via `nvidia-smi` guarded by `shutil.which` → honest `none` when there's no NVIDIA GPU; the un-probed `backend`/`model` are `unknown` (the real LLM identity is surfaced by the LLM-state endpoints, not faked here). `tests/test_sys_info_honest.py` (+5, pins that the old fabrications are gone). ruff (`contextlib.suppress`) + bandit (baseline regen, 125→119) clean. | H23.11 |
| CDX-11 | **Least-privilege plugins** — several `plugin_gate` entries serve `agents_served=["all"]` incl. external-write surfaces; for the hardened/design-partner profile, scope per-agent using existing agent identity. | 🟢 **done (opt-in, default-off)** — 12 **TRANSMITTED** plugins serve `"all"` (the 11 external-write surfaces — `social_x`, `writeback_{notion,github,google_calendar}`, `call_{twilio,telnyx}`, `channel_{whatsapp,google_chat,teams,signal,matrix}` — plus the `telegram` comms bus), so by default *any* agent persona (incl. one steered by an injected prompt) can reach a third-party write. New **least-privilege** overlay on `PermissionGate.check_call`: under hardening the `"all"` wildcard is **NOT honored for TRANSMITTED plugins** — such a plugin admits only an **explicitly-served** agent or an **owner-declared grant** (`JARVIS_PLUGIN_GRANTS="plugin:agent,…"` / `gate.add_grant`). Read/LAN/local plugins keep their wildcard; explicitly-scoped plugins (e.g. `cloud-llm`) are untouched. **Crucially invents no capability matrix** — the policy (which agent gets which write) is deferred to owner config, and the feature is **OFF by default** (`JARVIS_PLUGIN_LEAST_PRIVILEGE` / the broader `JARVIS_HARDENED` preset enable it), so current behavior is byte-identical until the owner opts in. Posture is surfaced read-only on `GET /plugins` (`least_privilege` + per-plugin `wildcard_restricted`/`grants`). `tests/test_cdx11_least_privilege_plugins.py` (+11). ruff + bandit clean; no route change (parity green). | 🟢 | 0.45 / Track K |
| CDX-12 | **Hardened profile** — a "Design-Partner / Hardened" preset: guardrails→REDACT/BLOCK on sensitive routes, audit-HMAC required, strict egress on, mutating MCP off by default. | 🟢 **done (opt-in, default-off)** — new `agents/core/security/hardened.py`: a single `JARVIS_HARDENED=1` switch that tightens **four** toggles at once, each confirmed against the real mechanism: **(1)** guardrails default `WARN→REDACT` (orchestrator's `security.guardrails_mode` default; an explicit setting still wins); **(2)** **audit-HMAC required** — startup **fails closed** if `JARVIS_AUDIT_KEY` is absent (new `serve.assert_hardened_posture()` beside `assert_safe_bind`, via `hardened.enforce()`); **(3)** **strict egress forced** — the `JARVIS_STRICT_EGRESS=0` downgrade escape-hatch is ignored (`http_client._enforce_egress`); **(4)** **mutating MCP forced off** — `JARVIS_MCP_MUTATING_TOOLS` can't re-open writes (`route_tools.mutating_tools_enabled`). It also rides on **CDX-11** plugin least-privilege (already reads `JARVIS_HARDENED`). Posture is surfaced read-only on the existing `GET /api/security/posture` (`hardened` block) — **no new routes**. **Default OFF** → byte-identical behavior until the owner opts in; the required audit key + how-to-enable are documented for owner review. `tests/test_cdx12_hardened_profile.py` (+11: each toggle off-by-default, each flips under the preset, fail-closed without the key, the serve-level guard, posture shape, the strict-egress + mutating-MCP overrides, and the CDX-11 cross-wire). ruff + bandit clean; parity green. **Closes the CDX security cluster.** | 🟢 | 0.56 / H23.20 |

> **Verified NOT a bug (no action):** interrupt-budget is already wired to the setting
> (`orchestrator.py:265` → `InterruptBudget(per_day=…autonomy.interrupt_budget…)`); the
> `worker.py:27` constant is only the default. The review's "verify this" caveat is satisfied.
>
> **Review's own ranking** (all already tracked — confirms the plan): H23.11 readiness board ·
> H23.18/19 docs · H23.20 onboarding · H23.1 budgets · H23.2 model pinning · HUD live/seed +
> audit-verify surfacing · then **one design-partner proof loop**. Quick wins to bank first:
> **CDX-1/2/3** (a small correctness PR) and **CDX-4/5** (doc/version sync).

---

## 🧪 Hardening audit (2026-06-23 — fresh-eyes review, findings + phased plan)

Two independent fresh-eyes passes (Opus 6-dive + Sonnet 3-agent), merged, de-duplicated
and **source-validated this session**. The codebase is unusually disciplined (real Docker
sandbox, SSRF defense, Fernet/PBKDF2 crypto, ~2,550 meaningful tests); the findings are a
short list of real bugs + a few features that don't fully do what they claim. Full write-up
(38 findings `F1`–`F38` + strengths-to-protect + corrections appendix):
[`docs/research/2026-06-23-independent-audit-merged.md`](docs/research/2026-06-23-independent-audit-merged.md).
Status keys as elsewhere (✅ done · 🟢 in PR · 🟡 partial · ⬜ open). `Fn` = finding id in the report.

**Phase 0 — pre-1.0 / pre-network blockers (exposed surfaces + data-at-rest)**

| # | Item | S | P | AC |
|---|------|---|---|----|
| AUD-0 | **Scope decision (breadth→depth)** — name the 5–6 product-defining features; flag-park the ~44 governed-but-`Null`-railed modules (gates Phase 2). Pairs with H23.23 single-user call. | 2 | DECISION | owner decision recorded in this file |
| AUD-1 | ✅ **done (#309)** — **Secrets at rest** — envelope-encrypt `settings.db` credential columns (`twilio/notion/tuya/gecko/stark_ga4…`) via the existing `SecretStore` (Fernet + pure-Python fallback) at the put/get boundary (`settings_db.SECRET_KEYS` → `_encrypt_if_secret`/`_decrypt_if_secret`); opt-in **encrypted backup archives** (`.tar.gz.enc`, key from `$JARVIS_BACKUP_KEY`/arg, stored outside the data root) in `backup.py` (F2). *Caveats H23.8.* | 5 | **P0** | ✅ `settings.db` dump shows opaque `enc::` token values; an encrypted backup archive is opaque (no plaintext); reads decrypt transparently |
| AUD-2 | ✅ **done (#315)** — **"Forget me" completeness** — forget now also erases the memory subsystem at rest (knowledge graph, entities, decay, embedding cache, conversation transcripts) via `data_purge.purge_data(memory=True)`, clearing the live in-memory stores first so a running orchestrator can't re-persist them; the backup-first snapshot is encrypted once a key is set (AUD-1 #309). The **CLI** (`python -m agents.core.data_purge`) now defaults to `memory=True` too (with `--no-memory`) — #315 brought only the endpoint to parity, leaving the offline CLI forget incomplete. *External Qdrant/Neo4j wiping is best-effort via each store's `clear()`.* (F1) | 5 | **P0** | ✅ post-forget the data root holds no memory PII (transcripts/KG/entities/embeddings); `tests/test_data_purge_memory.py` + CLI parity in `test_data_purge.py` |
| AUD-3 | ✅ **done (#315)** — **HUD XSS + CSP** — HUD dynamic data (`index.html` weather/news/system/history) routed through a local `esc()`; a `_security_headers` middleware adds CSP + `X-Content-Type-Options`/`X-Frame-Options`/`Referrer-Policy`; Tauri `csp` set (F3). | 3 | **P0** | ✅ a crafted RSS headline renders inert; headers present; `tests/test_hud_security_headers.py` |
| AUD-4 | ✅ **done (#315)** — **WorldView fail-closed** — default `HOST=127.0.0.1`; `assertSafeBind()` aborts boot on a non-loopback bind with an empty `WORLDVIEW_AUTH_SECRET` (F4). *Container hardening (non-root `USER`/`HEALTHCHECK`/`securityContext`/`sslmode`, F14) still open.* | 3 | **P0** | ✅ empty secret on `0.0.0.0` aborts boot; `worldview/backend-api/test/configBootGuard.test.ts` |
| AUD-5 | ✅ **done (#315)** — **Session path-traversal** — shared `validation.is_valid_session_id` enforced in `sessions.py` (route → 400) and at the `memory/persistence.py` boundary (F7). | 1 | **P0** | ✅ `session_id=../../x` → 400; no file escapes the data root; `tests/test_session_traversal.py` |

**Phase 1 — next sprint (correctness + auth lifecycle + CI gates)**

| # | Item | S | P | AC |
|---|------|---|---|----|
| AUD-6 | ✅ **done (#319)** — **Token lifecycle (full-replace)** — the managed `TokenStore` (`security/token_store.py`) is the authoritative credential system: mints `secrets.token_urlsafe(32)`, stores only its SHA-256 (raw token returned once), optional TTL; `verify`/`has_scope` reject expired tokens; `rotate` revokes a scope's prior tokens. The static `JARVIS_*_TOKEN` env vars are now only the **bootstrap** — accepted (constant-time) until a `rotate` supersedes them, after which they're revoked **for good** via a persistent `env_revoked` flag (so adopting a managed token truly replaces the static one). `POST /api/admin/rotate-tokens` (admin-guarded, returns the fresh token once, audited without the value). Offline owner-recovery CLI (`python -m agents.core.security.token_store rotate admin`) → no permanent lockout. *Deferred (F19 tail): httpOnly cookie over `localStorage`, read/write split.* | 3 | P1 | ✅ an expired/rotated token is rejected; the static env token dies after rotation; raw tokens never hit disk (only the SHA-256); `tests/test_token_lifecycle.py` |
| AUD-7 | ✅ **done (#320)** — **SSE + async hot path** — the `/chat/stream` producer is extracted to a module-level `_chat_event_stream` with a `try/finally` that cancels **and awaits** the model-turn task on any exit, incl. a client disconnect mid-stream (Starlette throws `GeneratorExit`) — so a dropped client never leaves the LLM turn running orphaned. `ConversationMemory.add_turn` now does its append-log + full-snapshot disk writes via `asyncio.to_thread` (built under the lock), so the SSE hot path never blocks the event loop; per-turn durability is unchanged (F8, F9). | 3 | P1 | ✅ client disconnect cancels the turn; no full-snapshot write on the event loop; `tests/test_aud7_sse_hotpath.py` |
| AUD-8 | ✅ **done (#318)** — **Settings integrity** — `settings_db.validate_category` checks each admin write against its DEFAULTS schema (type + select allow-list) → the route returns **422** on a bad value before it persists; every accepted write is audited (`SETTINGS_CHANGE`, changed **key names only**, no values) (F10). | 2 | P1 | ✅ bad value → 422; each settings change appears in the audit log; `tests/test_settings_integrity.py` |
| AUD-9 | ✅ **done (#315)** — **Audit chain HMAC** — optional off-box key (`JARVIS_AUDIT_KEY`): keyed rows are HMAC-SHA256 and need the key to verify; a per-row `hash_algo` marker lets a DB spanning the transition still verify; default (no key) keeps SHA-256 (F6). *Caveats H23.5.* | 2 | P1 | ✅ a tampered/forged row fails verification; hmac rows unverifiable without the key; `tests/test_audit_hardening.py` |
| AUD-10 | ✅ **done (#324 · #325 · F34/F35 flip)** — **Supply-chain / CI**. **Done:** every `uses:` across all workflows SHA-pinned (`@<40-hex>  # vX`, Dependabot-tracked, F32); pytest-socket loopback-only guard in `pytest.ini` (`--allow-hosts=127.0.0.1,::1,localhost`) so a stray *real* network call fails fast instead of hanging to the `--timeout` backstop (F37); `.pre-commit-config.yaml` (gitleaks/ruff/hygiene); **blocking gates, baseline-then-block** — ruff lint (`ruff-baseline.toml` freezes 1,654 pre-existing findings via per-file-ignores extended from pyproject; `ci.yml`), bandit SAST over `agents/`+`scripts/` (`.bandit-baseline.json` freezes 123; the 1 HIGH — MD5 file-fingerprint in `oracle_bridge.py` — *fixed* with `usedforsecurity=False`, not frozen), gitleaks secret-scan (`.gitleaks.toml` allowlists 10 known FPs + extends default ruleset) (F34/F35/F36); plus **advisory** semgrep SAST + pip-audit (`security.yml`, continue-on-error). **F33 done:** hash-pinned lockfiles `requirements{,-beta,-dev}.lock` generated by `scripts/lock_deps.sh` (`uv pip compile --generate-hashes --universal --python-version 3.12`); `ci.yml`/`smoke.yml`/`code-health.yml` install with `pip install --require-hashes` across the ubuntu+windows matrix (a tampered artifact aborts the install — proven), and a `Lockfiles` workflow guards source↔lock drift via an embedded `source-sha256` (deterministic — immune to unrelated upstream releases; version refreshes are thirdparty-autoupdate's job). *(The earlier "mirror frozen at numpy 2.4.6" note was a misdiagnosis: the real blocker was the sandbox's local Python 3.11 vs numpy 2.5.0's `requires-python ≥3.12` — uv resolves for a target version regardless.)* **F34/F35 blocking flip (this PR):** semgrep + pip-audit are now **blocking** (`continue-on-error` removed). semgrep — the 9 pre-existing findings were triaged: 2 real (`xml.etree` parsing untrusted RSS/Atom feeds in `digest.py`/`news.py`) **fixed** by switching to `defusedxml` (+ broadened the `except` to swallow its DTD/entity-attack rejections); 7 `logger-credential-leak` **false positives** suppressed at the call site with a named `# nosemgrep` (so the rule still fires on genuinely new code). pip-audit — now audits the **hashed lockfile** (exact resolved versions, not loose constraints); `--ignore-vuln` list intentionally empty (the lock audits clean). **→ AUD-10 complete.** *Extends Dependency-upkeep + SEC-4 + CQ sections.* | 5 | P1 | every `uses:` is a SHA ✅; stray network in tests fails fast ✅; CI fails on a new lint finding / bandit issue / secret ✅; installs are hash-pinned (`--require-hashes`) and a tampered artifact aborts ✅; SAST (semgrep) + dependency-CVE (pip-audit) gates now blocking ✅ |
| AUD-11 | ✅ **done (#315)** — **Sandbox containment tests** — `tests/test_sandbox_isolation.py` runs in the real Docker backend (no-network + read-only FS) via a dedicated `sandbox-isolation` CI lane (`RUN_SANDBOX_ISOLATION=1`) so it can't be skipped away (F5). *Sub-item of H23.17.* | 3 | P1 | ✅ a containment test actually runs and proves isolation |
| AUD-12 | 🟢 **F11+F12 in #324; F13 done #315** — **Injection hardening** — (1) scanner `matched_text` redacted (F13, with AUD-9, #315); (2) **F11 Cypher injection:** node labels / relationship types / property keys constrained to safe Cypher identifiers at the `memory/graph.py` chokepoint + direct `/api/kg/*` writes → 400; (3) **F12 WorldView WKT bounds:** untrusted OSINT coordinates are float-coerced, WGS84 bounds-checked and vertex-capped at the `wkt.py` chokepoint (`wkt_guard.coerce_coord`), the ingestion callers (`context/normalize`, `ew/gpsjam`) drop an out-of-bounds feature with a WARNING, + a defence-in-depth `geom_wkt` validator on `TelemetryEnvelope`. **→ AUD-12 complete on #324 merge.** | 3 | P1 | ✅ a flagged secret never lands in `audit.db`; a Cypher label/rel/key injection → coerced/400; an out-of-range / NaN / oversized coordinate → `WktBoundsError` and the feature is dropped (never emitted); `tests/test_kg_cypher_allowlist.py`, `worldview/.../tests/test_wkt_bounds.py` |

**Phase 2 — post-1.0 (structure, observability, scale, DX)**

| # | Item | S | P | AC |
|---|------|---|---|----|
| AUD-13 | **Turn-pipeline de-dup + service container** — one `PromptBuilder` + `_preprocess_turn`; extract context/dispatch/persist; retire `orch` back-refs + `sys.modules` indirection (A1). *Continues CLN-2.* | 8 | P2 | prompt assembly lives in one place; collaborators take narrow interfaces |
| AUD-14 | **Config consolidation** — one `Config` read once at boot (collapse 121 env reads / 3 bool conventions; centralize model names); derive agent-policy sets from `agents.yaml` (A3, F29). **Progress:** O26-P2.1 unified boolean/env parsing; #592 moved channel send-rate numeric parsing to `env_int()`; #596 centralizes LLM model-name defaults/`JARVIS_DEEP_MODEL` in `llm/model_config.py`; #620 moves plugin grants to shared `env_list()`; #622 moves trust-status env flags to shared `env_flag()`. | 3 | P2 | a model swap is one edit; one truthy convention |
| AUD-15 | **Client consolidation** — retire HUD v1, make v2 the Tauri target, extract a shared `@jarvis/client` (auth+SSE+fetch + timeouts); remove `@ts-nocheck`, move toward `strict` (A2, F17, F26). | 8 | P2 | one client lib across surfaces; v1 gone; fetches time out |
| AUD-16 | ✅ **done (2026-07-03)** — `frontend/src/api/schema.gen.ts` is generated from the live FastAPI `/openapi.json`; `npm run typegen:openapi` pins `openapi-typescript@7.13.0`; CI boots the backend, regenerates the schema, and fails on `git diff --exit-code -- frontend/src/api/schema.gen.ts`. Consumer migration remains gradual. | 3 | P2 | a backend field change fails the TS diff check |
| AUD-17 | ✅ **done** — Prometheus `GET /metrics` golden signals (RED): `jarvis_http_requests_total` (rate, by method/route-template/status), `jarvis_http_request_duration_seconds` summary (p50/p95/p99 + sum/count), `jarvis_http_errors_total` (5xx), `jarvis_http_requests_in_flight` gauge — recorded by a `_golden_signals` middleware in `web.py`, dependency-free exposition in `observability/http_metrics.py` (route-**template** labels → bounded cardinality; reuses `north_star._percentile`). Scrape is unauth + rate-limit-bypassed like the probes. Real-path **concurrency/p95 test** drives 60 concurrent requests, asserts p95 under budget with no in-flight leak. (F16, F23) | 3 | P2 | `/metrics` exposes http/latency/error; load test asserts p95 on the real HTTP path |
| AUD-18 | **Scale & DX polish** — Qdrant-by-default at scale; lazy plugin instantiation; Vite code-split; ~~configurable scanner patterns~~ **✅** (`SecretScanner(extra_patterns=)` + `JARVIS_SCANNER_EXTRA_PATTERNS` JSON `{name:regex}` → a deployment can scrub its own secret formats; compiled IGNORECASE at HIGH, invalid regex/JSON skipped so a bad config can't break scanning; **default byte-identical**; `tests/test_scanner_extra_patterns.py` +9); ~~LLM retry/backoff via the existing `@resilient_call`~~ **✅** (`resilient_call` gained `timeout=None` → it `await`s the call directly instead of wrapping it in a 30s `asyncio.wait_for`, so a long call's own budget governs. This fixed a real latent bug: `cloud_llm.py`'s `_call_anthropic`/`_call_gemini`/`_call_openai` set a **120s** httpx read/total timeout for slow cloud generations but were decorated `@resilient_call(timeout=30.0)` — the 30s outer deadline clipped legitimate 30–120s responses and burned 2 retries. Now `timeout=None` on those three so the 120s httpx budget governs; retry/backoff/circuit-breaker still fire on transport exceptions. Default stays `30.0` → every other caller byte-identical. `tests/test_resilience.py` +2: `timeout=None` doesn't clip a long call (vs a tight-timeout control that does) and still retries on a transport exception); ~~close leaked httpx clients~~ **✅** (`Orchestrator.aclose()` now also drains three long-lived `httpx.AsyncClient` pools that previously leaked on shutdown/restart: the **Gemini context-cache** client (`context_cache.close()`, created only with a Gemini key), the **per-plugin `PluginHTTPClient` registry** via a new `http_client.close_all()` (iterates a snapshot since each `close()` pops from `_clients`; best-effort), and **channel transports** following the async `aclose` convention (e.g. the Telegram client). Defensive throughout — a failing close can't abort the rest of shutdown, and a channel without `aclose` is skipped. `tests/test_shutdown_cleanup.py` +4); CORS/loaders polish (F20–F25, F27, F28, F30, F31). | 5 | P2 | recall indexed by default; transient LLM 503 retries; no client leak |

---

## Scalability: index hot/unbounded SQLite tables (shipped — PR #199)

Behavior-preserving index pass on the four tables that are read on hot paths
while growing without bound — keeps those lookups O(log n) instead of degrading
to full scans at scale. All are `CREATE INDEX IF NOT EXISTS` in the init path,
so existing DBs gain them on the next startup; results are identical, only faster.

- `tasks(status, id)` — autonomy worker/inbox poll `runnable()`/`list()`/`pending_decisions()` by status.
- `security_events(event_type, timestamp)` — audit `query()`; one row per turn (fastest-growing table).
- `preferences(agent, kind, risk_tier)` — `approval_rate()` on the autonomy decision path.
- `sessions(started_at)` — `list_sessions()` ordered scan.

Guarded by `tests/test_db_indexes.py` (+5): each index must exist **and** be used
by its hot query (asserted via `EXPLAIN QUERY PLAN`), so a future schema change
that silently regresses to a full scan fails CI. Audit pre-work confirmed WAL is
already set on every store and there are no blocking-I/O calls in async paths
(repo-wide AST scan), so no further safe wins remained in those categories.

## LM Studio control + model honesty (shipped — PR #133)

Chat + admin control of the local LLM backend (`lms server start` / `load` / `unload`),
the live model reported truthfully (runtime-state injection + SOUL fix), and the
chain-of-thought leak / mid-sentence truncation fixed. Kill-switch:
`JARVIS_LMSTUDIO_CONTROL` / `llm.control_enabled` (chat-only: `JARVIS_LMSTUDIO_CHAT_CONTROL`
/ `llm.chat_control`). Docs + troubleshooting: `docs/ARCHITECTURE.md` §5.

**Follow-ups (P2):**
- Validate end-to-end against a real `lms` binary on the RTX 5090 box — current tests are mock-only.
- ✅ Fuzzy model resolution: "load gemma" → resolves to the full id via `/v1/models` before `lms load`
  (`LMStudioController._resolve_model`). Unique match loads (reply names the resolved id); several
  matches → `ambiguous` + candidates (chat asks which / admin returns 409); list unreachable → literal
  passthrough. Admin `/api/llm/load` persists the resolved id. +13 tests.
- ✅ Surface the kill-switch toggles + a model picker as real controls in the admin Settings UI —
  `llm.control_enabled` / `llm.chat_control` toggles + live model picker (`ModelPickerRow`, kind
  `model-select`), and a live controller-status card backed by new admin-guarded `GET /api/llm/status`
  → `{online, enabled, server_url, active_model}` (`LMStudioStatusRow` in `admin.js`). +Python +JS tests.
- Confirm the LM Studio id for Gemma 4 12B — `google/gemma-4-12b` is a placeholder in static config.

---

## Status General

| Horizon | Total | ✅ Done | S total | S done | % |
|---------|-------|---------|---------|--------|---|
| **H1–H4 + Sprint 0 + Cross-cutting + Sec + Bugs** | 67 | **67** | 248 | **248** | **100%** |
| **H5 Next Wave** (P2–P3) | 17 | **17** | 128 | **128** | **100%** |
| **H6 Jarvis Autonom** (P1) | 7 | **7** | 60 | **60** | **100%** |
| **H7 Perf Cale Fierbinte** (P1–P2) | 5 | **5** | 16 | **16** | **100%** |
| **H7 Hardening & Release Readiness** (P0–P2) | 11 | **11** | 51 | **51** | **100%** |
| **H8 Memorie Personală** (P1–P3) | 7 | **7** | 48 | **48** | **100%** |
| **H9 Agent Ops: Workflows & Observability** (P2) | 3 | **3** | 29 | **29** | **100%** |
| **H10 Competitive Edge** (P1–P3) | 30 | **30** | 188 | **186** | **99%** |
| **H11 Platform Parity** (Known Gaps, P3) | 4 | **4** | 55 | **55** | **100%** |
| **Total H1–H11** | **151** | **151** | **823** | **821** | **100%** (SP) |
| **H12 Asistent Privat & Proactiv** (P0–P3) | 25 | **24** | 150 | **142** | **95%** |
| **H13–H17 Frontiere Noi** (post-paritate, în scope v1.0, P1–P3) | 20 | **19** | 146 | **141** | **97%** |
| **Total H1–H17 = scope 1.0.0** | **196** | **194** | **1119** | **1104** | **99%** (SP) |
| **H18 Mobile Native & Browser Parity** (P2–P3) | 16 | **15** | 51 | **51** | **100%** |
| **H19 WorldView (4D OSINT)** — standalone product, merged 2026-06-08 | 33 | **33** | 208 | **208** | **100%** ✅ |

> `%` = procent pe **story points**. Sub-total **H1–H11** = 821/823 (≈100% SP; 151/151 iteme). Grand-total **H1–H17** = 1104/1119 (≈99% SP; 194/196 iteme). **Toate orizonturile de features sunt livrate = v0.10.0** (H18 mobil 17/18, cu H18.10 umbrelă continuă mereu deschisă + H19 WorldView 33/33 standalone — livrate). **Nu mai există un "audit gate" ca versiune**; restul drumului până la 1.0 e *productionizarea* (vezi **H23** + roadmap-ul de versiuni mai sus) **plus, din 2026-07-11, programul de capabilități AI-OS** — gate-ul 1.0 s-a extins (decizie owner): **1.0 = proof track (H23/O24–O26 + ⭐B0 + soak + design partners) ȘI cei șase piloni la bara v1** (ORIZONT 27–33, ~191 SP; [NERVA_VISION.md](NERVA_VISION.md) §10).

**În afara totalului:** **Bugs & Hot Fixes** — **toate BUG-\* și HF-\* rezolvate** (BUG-1…17 + HF-1…7 + NTH-1; vezi re-baseline 2026-06-08 + tabelul de mai jos). ✅ **CLN-3 livrat + CLN-2 substanțial livrat (#293/#296, v0.11.0)** — `web.py` 4636→1282 LOC (45 routere, 9 rute inline), `orchestrator.py` 1620→1456 LOC; suprafața de rute byte-identică, parity-guarded. Rămân deschise: taskuri netrackuite ca buguri (**TASK-1** Howard backend, **TASK-2** HUD v2 depth, **TASK-3** taint-tracking canale, **BUG-2b** frontend E2E). *(Detalii audit cod 2026-06-04 în tabel.)*

**Test count (backend pytest):** **6,787 passed, 10 skipped** (măsurat 2026-08-18 pe branch-ul persona-roster, incl. cele +37 din `test_persona_roster.py`). 4 eșecuri rămân în containerul efemer de dev și sunt **de mediu, nu de cod** — reproduse identic pe `main` curat: `test_ssrf` (egress blocat), `test_sys_info_honest` + `test_system_monitor::test_temps_command` (fără senzori hardware), `test_task_mediation_evidence::…legacy_migration` (numpy absent → banner „vector store disabled" pe stdout). Skip-urile sunt teste gated pe Docker/wasmtime (sandbox isolation) + heartbeat-ul opțional, absente în CI fără backend de sandbox. *(2026-06-09: backlog software **code-complete** — H10 30/30, H11 4/4, H12 24/25, frontiere H13–H17 19/20 (vezi „Status General" de mai sus); + WorldView O19 33/33 merged + Argus; snapshot-ul de atunci era ~2,814. Rămâne audit + testare manuală, vezi `docs/AUDIT.md`.)*
**Frontend (BUG-2):** **521 vitest** + mobile **96 jest** (generated status; snapshot-ul istoric 2026-06: 184 teste JS / 23 fișiere) — separat de suita pytest.
**Observability (MOONSHOT §6):** north-star + counter-metrics (accepted/active user, interrupt rate, reject rate, %-local, p95) sunt acum calculate într-un singur loc (`agents/core/observability/north_star.py`) și expuse la `GET /api/metrics/north-star` — vezi [docs/METRICS.md](docs/METRICS.md).

> **Orizont 7 Hardening — Drumul spre 1.0.0:** 11/11 COMPLET ✅ (livrat 2026-06-02)

---

## ✅ ORIZONT 7 — Drumul spre 1.0.0 (Hardening, Release Readiness & Observability) — 11/11 COMPLET

> Backlog-ul de features e la 100% (H1–H6). Faza spre **1.0.0 stable** nu adaugă scope orizontal —
> face produsul **de încredere, testabil, documentat și măsurabil**. Bazat pe auditul multi-agent
> 2026-06-01 (docs/release, CI/hermeticitate, calitate cod, scoping features) + `docs/gap-analysis-1.0.md`.
>
> **Design complet:** `docs/superpowers/specs/2026-06-01-horizon7-road-to-1.0-design.md`
> **Constatări-cheie:** `pytest tests/` atârnă >18 min offline (Oracle GitHub watcher la lifespan);
> CI rulează doar pe push/Windows (nu pe PR-uri); ~44 `except: pass` în security/autonomy;
> docs se contrazic (README „181" vs „39" teste; port 8000↔8080; model 26b↔31b; „15" vs 16 agenți;
> fără LICENSE/CONTRIBUTING).

### Track A — Test Hermeticity & CI/CD (P0, blochează restul)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.1 ✅ | **Suită de teste hermetică** — gate watchers/canale externe pe `JARVIS_TESTING`; `conftest` autouse (env + socket guard); `pytest-timeout` în pytest.ini; TestClient module-level → fixtures function-scoped (`test_cognition_api/test_tts/test_systems_api/test_resilience_integration`) | 5 | P0 | — | `pytest tests/` rulează offline, verde, <90s, fără hang; apel real de rețea → eșec imediat |
| H7.2 ✅ | **CI/CD pentru 1.0** — trigger `pull_request`; matrix `ubuntu+windows`; `ruff` + `mypy` (non-blocking) + `pytest-cov`; healthcheck robust (poll, nu sleep) | 5 | P0 | H7.1 | fiecare PR rulează CI pe Linux+Windows cu lint+teste+coverage |

### Track B — Code Hardening (P1)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.3 ✅ | **Client HTTP centralizat + retry/circuit-breaker** — `PluginHTTPClient` (timeouts coerente, `@resilient_call` H5.5, pooling); migrează 14+ pluginuri | 8 | P1 | H5.5 | un singur client/policy; metrici reziliență per plugin |
| H7.4 ✅ | **SQLite thread-safety & igienă conexiuni** — `check_same_thread=False` + lock pe checkpoint/settings_db/queue/preferences; WAL consistent | 5 | P1 | — | acces concurent sigur; `test_load.py` fără erori de thread/corupere |
| H7.5 ✅ | **Validare input pe endpoint-uri** — limite Pydantic: message len, `limit` bounds, `task_id` numeric, sandbox code size | 3 | P1 | — | input invalid/oversize → 422, fără OOM/DoS |
| H7.6 ✅ | **Curățare excepții înghițite silențios** — `except: pass`/`return None` orbe din log/channels/autonomy/security → logging structurat + fallback explicit | 5 | P1 | — | nicio cădere silențioasă în security/autonomy; fiecare logată cu context |
| H7.7 ✅ | **Elimină date mock/dummy înșelătoare** — `/tasks` dummy tasks (web.py); flag transparent pe iot_control mock | 2 | P1 | — | UI nu primește date false ne-marcate |

### Track C — Docs & Release Hygiene (P1)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.8 ✅ | **Adevăr în documentație** — single source of truth versiune (`agents/__init__.py` + `/status`); reparat test counts, versiune, port, model, agent count, endpoint count | 3 | P1 | — | zero contradicții cross-doc; CI verifică versiunea unică |
| H7.9 ✅ | **Onboarding & release** — `LICENSE`, `CONTRIBUTING.md`, quickstart Linux/Mac, `docker-compose.yml` (server+Qdrant+Neo4j+n8n), README badges+screenshot, release workflow (tag→Release) | 5 | P1 | H7.2 | dev nou rulează în <10 min pe Linux/Mac; tag → GitHub Release |

### Track D — Observability & Product Polish (P2, câștiguri rapide high-ROI)

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.10 ✅ | **Cost & Usage Analytics** — preț per model + agregare tokens/cost per agent (local vs cloud) + burn lunar; `GET /api/analytics/cost` + tab HUD | 5 | P2 | H5.5 | dashboard arată cost/agent + proiecție lunară din date reale |
| H7.11 ✅ | **Activare Learning-Loop (auto promote/demote)** — job periodic care propune evoluția agenților prin decision inbox (reversibil, gated). **Done 2026-06-03:** `core/learning/scheduler.py` `propose_promotions` — rulează `suggest_promotions`, enqueue propuneri gated (kind `agent_promotion`, `autonomy_level="ask"`, `origin="generated"`, risk_tier 2) în `TaskQueue`, idempotent (skip dacă există deja propunere deschisă/agent activ); job APScheduler `_schedule_learning_loop` (cadență `autonomy.learning_loop_interval_hours`, default 168h=săptămânal) + trigger manual admin `POST /api/learning/propose`. +6 teste (enqueue gated, idempotent, sub-threshold, deja-activ, componente lipsă, endpoint). | 5 | P2 | H3.4, H6.5 | după N interacțiuni → propunere în inbox; aprobarea activează agentul |

> **Total Orizont 7:** ~51 SP. **Secvențiere:** H7.1 → H7.2 → (Track B ∥ Track C) → Track D.
> **Stretch → Orizont 8 (post-1.0):** voice clone (XTTS), Howard fine-tuning, multi-user/family,
> mobile offline voice, n8n NLU→workflow, desktop Tauri, advanced guardrails DSL, eval/regression harness.

---

## ✅ ORIZONT 6 — Jarvis Autonom / Proactive Cortex (P1) — 7/7 COMPLET

> Viziune: Jarvis își găsește singur de lucru, lucrează continuu, îmi scrie pe telefon (Telegram)
> doar când are nevoie de o decizie, și susține un review zilnic de 10–30 min (morning brief + evening retro).
> Autonomia crește în timp pe măsură ce învață ce aprob.
>
> **Design:** `docs/superpowers/specs/2026-05-31-horizon6-autonomous-jarvis-design.md`
> **Research (cu surse):** `docs/research/2026-05-31-autonomous-proactive-agents.md`
> **Politică implicită:** ECHILIBRAT — act autonom pe reversibil/sigur (research, drafturi, organizare);
> aprobare pe ireversibil sau bani. **Buget întreruperi: ≤4 push-uri urgente/zi**, restul în review.
> **Principiu:** ambient agent (trigger → coadă → gating → inbox), NU auto-prompt loop (anti-AutoGPT).

| # | Item | S | Dep | AC |
|---|------|---|-----|----|
| H6.1 ✅ | **Autonomy Loop & Self-Tasking Queue** — coadă SQLite cu state-machine (`proposed→approved→running→done\|failed\|blocked`), worker pe loop, retry cap 3, 2 cozi manual/generated. `core/autonomy/queue.py` + `worker.py`, endpoints `/autonomy/*` | 13 | H3.5 | ✅ task trece prin tot ciclul; eșec ×3 → `failed`, nu reintră |
| H6.2 ✅ | **Decision Inbox pe Telegram** — card cu butoane inline Aprob/Editez/Resping/Amân pe task-uri blocate; buget ≤4 push/zi; rest în batch. `core/autonomy/inbox.py` + callback în `channels/telegram.py` | 8 | H6.1, H1.2 | ✅ task money/ireversibil → push cu 4 butoane → „Aprob" → running |
| H6.3 ✅ | **Risk Gate & Autonomy Dial** — `policy.py`: 4 tiers (read_only/reversible/external/irreversible_or_money) + scoring (reversibility, blast_radius, signal_quality, time_sensitivity); cap/ceiling bani. **Per-agent dial ✅ (HUD-v3 PR 0, #418)** — `AutonomyPolicy.agent_modes` + `effective_mode(agent)`; `decide()` resolves the mode **per agent** and the kernel threads `action.agent`, so an owner can set one agent to **AUTO/ASK/OFF** while the rest follow the global mode (default-safe: empty overrides ⇒ byte-identical to global). The coordinator resyncs overrides live each tick. Surfaced at `GET·POST /autonomy/policy` (admin) + the interrupt budget at `GET /autonomy/interrupts`. `tests/test_autonomy_per_agent_policy.py` (+7); route/openapi/route-auth parity reseeded (+3 admin routes). | 8 | H6.1, H4.9 | ✅ reversibil → act fără întrebare; money peste cap → ask; **vision=OFF → același write trece în QUEUE, jarvis=AUTO îl execută** |
| H6.4 ✅ | **Daily Review Ritual** — morning brief 07:00 + evening retro 20:00 (cron), batch list; endpoint `/autonomy/brief`. `core/autonomy/digest.py` | 8 | H6.1, H3.5 | ✅ digest construit din coadă, trimis pe Telegram, expus în HUD |
| H6.5 ✅ | **Preference Learning & Decision Journal** — scor approve/reject per (agent,kind,tier), `suggest_autonomy_raise` (doar tier 1–2), jurnal JSONL append-only. `core/autonomy/preferences.py` + endpoint `/autonomy/preferences/suggestions` | 13 | H6.1, H3.4 | ✅ după N aprobări reversibile → sugerează ridicarea autonomiei |
| H6.6 ✅ | **Night Shift** — fereastră wrap-midnight; `tick(max_tier=1)` rulează batch doar reversibil/read-only. `worker.is_night_window` + filtru `queue.runnable(max_tier)` | 5 | H6.1, H6.3 | ✅ noaptea rulează doar muncă reversibilă; extern/ireversibil așteaptă |
| H6.7 ✅ | **Proactive OS Observer** (trigger layer) — `core/autonomy/observer.py`: eșantionează resurse (CPU/RAM/disk via psutil) + liveness servicii (TCP), **debounce pe schimbare de stare**, injectează în coada existentă (alertă→READ_ONLY auto-act, vizibilă în HUD/brief; remediere→tier-3 ASK→decision inbox). Probe injectabile (offline-testable). Endpoints `/autonomy/observer[/run]`. | 5 | H6.1, H6.3 | ✅ serviciu căzut → card „restart?" în inbox **o singură dată**; resursă în prag → alertă în brief |

> **ORIZONT 6 COMPLET ✅** (2026-05-31/06-01) — H6.1–H6.7 livrate. Detalii de livrare: [docs/HISTORY.md](docs/HISTORY.md).

---

> **Runtime diagnostics** (auto-generated from `problems.jsonl`) now live in the
> git-ignored `memory_logs/diagnostics.md` — they are **no longer written into this
> tracked file** (that caused recurring `git pull` conflicts; see BUG-4).

## 🐛 Bugs & Hot Fixes

> Buguri cunoscute + taskuri „orfane" (amânate/abandonate prin alte docs/note, fără item trackuit).
> Audit 2026-06-02: am promovat aici follow-up-urile care altfel cădeau de pe radar.
> Audit cod 2026-06-04 (orchestrare + memorie/autonomie + securitate): adăugate BUG-5…BUG-12,
> HF-3…HF-7, CLN-2/CLN-3. Caveat transversal: majoritatea au risc **scăzut pe deployment
> single-user/LAN** (designul actual) și devin reale sub concurență / expunere non-LAN.

> **Re-baseline 2026-06-08** (audit de cod + connectivity, verificat vs cod curent):
> - **Deja fixate în cod** (rândurile de mai jos sunt istorice): **BUG-3** (un singur `/api/analytics/cost`),
>   **BUG-6** (reload atomic prin rebind), **BUG-8** (parsing cu guard), **BUG-9** (allowlist alfanumeric),
>   **BUG-10** (reset zilnic programat la miezul nopții), **HF-6** (sandbox Docker-only by default), **HF-7**
>   (guard admin fail-closed în spatele proxy-ului).
> - **Fixate în pasul de hardening 2026-06-08:** **BUG-7/NEW-1** (`orch.aclose()` cablat în shutdown, toate
>   backendurile LLM + mcp + queue închise), **BUG-11** (re-gating complet pe payload-ul editat, nu doar `amount`),
>   **BUG-12** (lock pe `_PROC_CACHE` + atomicitate `_spent_today`) + **2 bug-uri noi**: `Orchestrator.process()`
>   lipsea dar era apelat (taskuri autonomy LLM + reflecția nocturnă întorceau gol — acum implementat, fail-safe)
>   și euristica greșită de eroare din `_record_interactions` (marcase răspunsuri reușite ca eșec).
> - **Fixate în pasul de completare HUD 2026-06-08:** **BUG-5** (session_id izolat per context async via
>   `contextvars.ContextVar` — chat-uri concurente nu mai amestecă conversații; test de concurență), **HF-3**
>   (scanner întărit: openai-key 40+, GCP/Azure SA, heuristică entropie; `db_connection_string`/`password`
>   restrânse). **Toate BUG-* și HF-* sunt acum rezolvate.**
> - **Rămâne deschis (deliberat, NU bug-uri):** **CLN-2/CLN-3** (refactor god-objects `orchestrator.py`/`web.py`
>   — P3, churn mare; amânat intenționat ca să nu destabilizeze înainte de testarea manuală). Restul backlog-ului
>   = orizonturi de produs (H10.30, H11, H12 Track E, H13, H15, O20, O21), nu loose-ends — vezi
>   [`docs/2026-06-08-future-developments-report.md`](docs/2026-06-08-future-developments-report.md).

### Buguri

| # | Bug | Severity | Notes |
|---|-----|----------|-------|
| ~~BUG-14~~ ✅ | **Frigga (strict-local) putea ajunge în cloud** — `select_backend` la `policy=local` cădea pe Gemini (`cloud-fallback`) când backend-ul local era jos, iar testul `test_select_backend_cloud_only_policy_local_fallback` consacra comportamentul. Încălca direct principiul non-negociabil #1 (MOONSHOT §5.1 / AGENTS.md: „niciun fallback cloud"). **Fixed 2026-06-10:** `policy=local` e **fail-closed** (RuntimeError explicit, fără fallback); test rescris `test_select_backend_strict_local_never_cloud` + `test_registry_cannot_override_local_only`. Bonus: `get_agent_policy` onorează acum `llm_policy` din `agents.yaml` (registrul canonic) cu podea de securitate `LOCAL_ONLY_AGENTS` — repară și drift-ul Argus (yaml `claude`, cod `auto`). | ~~**CRITICAL** (privacy)~~ | Găsit la dogfooding-ul AI_CONTEXT 2026-06-10 — citirea ARCHITECTURE §5 contra codului |
| ~~BUG-15~~ ✅ | **Howard (strict-local) putea ajunge în cloud** — `_select_howard_backend` scurtcircuitează ÎNAINTE de gate-ul de policy, iar ultimul fallback era Gemini (`cloud-fallback`) — pentru digital twin-ul LOCAL_ONLY cu arhiva de conversații. Fratele lui BUG-14, ratat de fixul inițial pentru că special-case-ul stă deasupra gate-ului. **Fixed 2026-06-10:** fail-closed + test `test_howard_strict_local_never_cloud`. | ~~**CRITICAL** (privacy)~~ | Audit governance 2026-06-10 (pass 2, aceeași metodă ca BUG-14) |
| ~~BUG-16~~ ✅ | **`llm.cloud_fallback` era un knob mort** — setarea de privacy din /admin (`never|on-demand|always`) era definită + afișată în UI dar necitită de NIMIC; "never" nu oprea nimic. **Fixed 2026-06-10:** onorat live în `HybridRouter` (never = agenții auto rămân local și pe prompturi mari; always = preferă cloud; on-demand = comportamentul anterior), re-sincronizat ≤30s de settings watcher. +6 teste. | ~~HIGH (privacy)~~ | Audit governance 2026-06-10 |
| ~~BUG-17~~ ✅ | **Lanțul Merkle de audit nu era verificat niciodată** — `AuditLogger.verify_chain()` exista cu zero apelanți (niciun endpoint, niciun test): "tamper-evident" fără verificarea probelor. **Fixed 2026-06-10:** `GET /api/security/audit/verify` ({valid, first_invalid_id, entries}) + teste unitare care demonstrează detectarea tamper-ului și a re-link-ului. Suprafața HUD: în coada TASK-2. | ~~MEDIUM (trust)~~ | Audit governance 2026-06-10 |
| ~~BUG-1~~ ✅ | `_dashboard_cache` module-level dict has no `asyncio.Lock` — concurrent `/dashboard` requests can race on the weather/calendar cache update, producing a double-fetch or partial write under high load. **Fixed 2026-06-02:** `_dashboard_lock = asyncio.Lock()` guards both refresh blocks with double-checked locking; weather block now also sets `cached_at` (was refetching every request). +1 regression test (`test_dashboard_concurrent_refresh_fetches_weather_once`). | ~~LOW~~ | Found during HUD test sprint 2026-06-02 |
| BUG-2 ✅ | ~~Frontend test infrastructure missing — 0% coverage on React HUD (~5 000 LOC).~~ **Done 2026-06-02:** Vitest + JSDOM harness (`tests/frontend/`) that loads the real shipped global scripts (vendored React 18 UMD + static files) — no bundler/build step. **156 tests / 20 spec files · ~66% measured line coverage (target 60% met)**, gated in CI (`frontend` job runs `npm run test:coverage`, fails under 60%). Coverage of the in-JSDOM scripts is measured via istanbul pre-instrumentation + nyc (see `coverage.mjs`) with a badge (`coverage-badge.svg`). Covers all of `components.js`, `i18n.js`, `data.js`, `cognition.js`, `dossier-modal.js`, `network.js`, `enhancements.js`, `observability.js`; `admin.js` (full `AdminApp` mount + nav sweep + save flow); `systems.js`/`workflows.js`/`observability.js` panels (mount + tab sweep); and `app.js` incl. the **P1 chat flow** (send→SSE stream→render) and **P2 polling** intervals. Plan alignment per `docs/plan-bug2-frontend-tests.md`: runner = Vitest (chosen over Jest), measured coverage ✅, P1 Chat ✅, P2 polling ✅. **Caught a real shipped bug on first run:** `systems.js` `ResilienceTab` missing closing brace → the entire Systems panel failed to parse/load in the browser (present on `main`); fixed + regression-guarded (`resilience.test.js`). **Deferred (P3 follow-up):** voice/`useTTS`, Workflow drag-drop pointer events, and browser E2E (Playwright). See `tests/frontend/README.md`. | ~~MEDIUM~~ | Identified in test coverage audit 2026-06-02; backend gap closed (121 tests added on branch `claude/hud-human-interface-testing-r8IQS`) |
| ~~BUG-3~~ ✅ | `/api/analytics/cost` era definit de **două ori** în `agents/web.py` (~1716 și ~2081), a doua umbrind-o pe prima. **Fixed (confirmat în cod 2026-06-19):** duplicatul a dispărut odată cu extragerea de routere CLN-3 — o singură definiție acum în `agents/core/routers/analytics.py:28`; gardat de testele route-parity/OpenAPI (o rută duplicată ar pica CI). | ~~MEDIUM~~ | Găsit la auditul de doc-truth 2026-06-02 |
| ~~BUG-5~~ ✅ | **Race pe `self.session_id`** — handler-ul de canal salvează/restaurează `self.session_id` pe instanța *partajată* a orchestratorului în jurul unui `await handle_input`. Două cereri concurente pe canale diferite puteau suprascrie reciproc `session_id` înainte de blocul `finally` → **un răspuns putea ajunge în conversația greșită**. **Fixed 2026-06-08** (confirmat în cod 2026-06-09): `session_id` e acum **async-context-local** via `contextvars.ContextVar` (`_active_session` în `agents/core/orchestrator.py`) — `session_id` e o proprietate care citește din ContextVar (fallback la `_session_id_default` partajat pt. boot/checkpoint/autonomie), iar `_resolve_session()` setează contextul per-cerere; **nicio mutație pe instanța partajată**. Test de concurență inclus. Cel mai impactant bug găsit la audit. | ~~HIGH~~ (sub concurență; LOW single-user) | Audit cod 2026-06-04 |
| ~~BUG-6~~ ✅ | **Reload non-atomic `_runtime_settings`** — loop-ul de fundal reconstruia dict-ul fără atomic-swap; un reader concurent putea vedea stare parțială. **Fixed (confirmat în cod 2026-06-19):** `load_runtime_settings()` (`agents/core/orchestrator.py:509-516`) construiește un dict `flat` local **apoi** îl **rebind-uiește atomic** (`self._runtime_settings = flat`) — un reader vede ori dict-ul vechi, ori cel nou, niciodată parțial (nicio mutație in-place). | ~~LOW~~ | Audit cod 2026-06-04 |
| ~~BUG-7~~ ✅ | **Leak `httpx.AsyncClient`** — backend-urile LLM creau clientul în `__init__` fără `aclose()` → connection pools rămase deschise. **Fixed (confirmat în cod 2026-06-19):** fiecare backend expune acum `aclose()` (LMStudio/Ollama `base.py:214`,`:339`; Claude/Gemini/OpenRouter/VLM), cascadat prin `LLMRouter.aclose`→`HybridRouter.aclose`→`Orchestrator.aclose` (`orchestrator.py:1608`)→shutdown-ul lifespan (`web.py:295`). Teste: `tests/test_hybrid_router.py:44-64`. *(Nit cosmetic rămas: `GeminiBackend` expune `close()` vs. `aclose()` la peers — inofensiv, `_close_backend` acceptă ambele.)* | ~~MEDIUM~~ | Audit cod 2026-06-04 |
| ~~BUG-8~~ ✅ | **Parsing fragil în `_detect_handoff`/`_detect_skill`** — `]` lipsă ducea la EOF over-read / `ValueError`. **Fixed (confirmat în cod 2026-06-19):** `_detect_handoff` (`agents/core/orchestrator.py:1148-1156`) folosește `end = resp.index("]", start) if "]" in resp[start:] else len(resp)` (guard explicit), iar `_detect_skill_learning` (`:1158-1178`) împachetează `resp.index("]")` într-un `try/except (ValueError, IndexError): continue` — niciun over-read negardat, nicio excepție nepriinsă. | ~~LOW~~ | Audit cod 2026-06-04 |
| ~~BUG-9~~ ✅ | **Path-traversal în `promote_bench_agent`** — scria `SOUL.md` dintr-un `bench_id` nevalidat; un id cu `../` putea scrie în afara `agents/`. **Fixed (confirmat în cod 2026-06-19):** `promote_bench_agent` (`agents/core/orchestrator.py:1422-1425`, `# BUG-9 hardening`) respinge orice `bench_id` care nu e alfanumeric (`bench_id.replace("_","").replace("-","").isalnum()`) înainte de a-l folosi ca segment de cale → niciun `../` posibil. | ~~MEDIUM~~ | Audit cod 2026-06-04 |
| ~~BUG-10~~ ✅ | **Buget zilnic de cheltuieli neresetat** — `reset_daily()` exista dar nu era apelat în producție → `daily_ceiling` se umplea permanent până la restart. **Fixed (confirmat în cod 2026-06-19):** `SchedulerService.schedule_daily_budget_reset()` (`agents/core/scheduler_service.py:55-71`) înregistrează un job APScheduler `cron hour=0 minute=0` care apelează `policy.reset_daily`, cablat din `schedule_all()` (`:37`) la pornire. Test: `tests/test_autonomy_policy.py:82`. | ~~MEDIUM~~ | Audit cod 2026-06-04 |
| ~~BUG-11~~ ✅ | **Task editat-după-block sărea peste re-gating** — un edit (ex. „$100"→„$300") se executa sub decizia veche de risc = escaladare de privilegii. **Fixed (confirmat în cod 2026-06-19):** `apply_decision(action="edit")` (`agents/core/autonomy/worker.py:169-219`) re-rulează `policy.decide()` pe payload-ul **complet** editat (`{"kind": ..., **payload}`, nu doar suma) și **păstrează task-ul BLOCKED** (re-push card) dacă rezultatul e ASK, înainte de orice tranziție la APPROVED. Teste: `tests/test_autonomy_worker.py:145-183` (`test_edit_to_irreversible_stays_blocked`, `test_edit_over_cap_reblocks`). | ~~MEDIUM~~ | Audit cod 2026-06-04 |
| BUG-12 ✅ | **Thread-safety reziduală — închis (2026-07-02).** `AutonomyPolicy._spent_today` gardat de `_spend_lock` (2026-06-19); `Embedder._PROC_CACHE` gardat de `_PROC_CACHE_LOCK` (verificat 2026-07-02). **`InMemoryVectorStore` acum gardat și el** — `self._lock = threading.Lock()` (`memory/store.py`), `with self._lock:` pe fiecare metodă publică (`add`/`search`/`search_by_sender`/`search_by_text_subset`/`get`/`remove`/`__len__`), mirror la pattern-ul `_PROC_CACHE_LOCK`. `tests/test_qdrant_store.py` (+2: lock present, hammer add/search/remove din 8 thread-uri concurent — invariantul `_id_index`↔`records` rămâne consistent). | ✅ | Audit cod 2026-06-04 |
| ~~BUG-13~~ ✅ | **Skill import din `hermes` complet rupt vs. repo-ul real** — `agents/core/skills/importer.py` cerea `main/skills/<nume>/manifest.{json,yaml}` (layout plat), dar `NousResearch/hermes-agent` (real, MIT, ~185.7k★, activ) folosește `skills/<categorie>/<skill>/SKILL.md` cu **YAML frontmatter** (standardul agentskills.io) → `import_from_hermes()` dădea 404 pe **fiecare** skill și întorcea `False`. Al doilea defect (local): `_save_skill` scria `manifest.json` dar `loader.py` descoperă **doar** `SKILL.md` → chiar și un import reușit nu se încărca niciodată. **Fixed 2026-06-07** (research: [docs/research/2026-06-07-hermes-agent.md](docs/research/2026-06-07-hermes-agent.md)): importer rescris să localizeze skill-ul în arborele git recursiv (`…/<slug>/SKILL.md`, suportă nesting pe categorii + layout plat + fallback legacy `manifest.*`) și să salveze **`SKILL.md` verbatim** (+ sidecar `manifest.json` doar pt. provenance/`list_imported`); `loader._parse_manifest` învățat să parseze frontmatter YAML (`requires_toolsets`→`requires`, comenzi din body) cu fallback la dialectul Markdown-heading existent. +8 teste offline (httpx mock: frontmatter, nested-tree import, skill importat e loader-discoverable, list_imported, missing→False) în `tests/test_hermes_import.py`. Suita skill (172 teste) verde. **Verificare live restantă:** căile de fetch sunt acoperite doar cu httpx **mock** (sandbox fără rețea); rămâne un smoke-test real (`DEV_MODE=1` → `import_from_hermes("github-issues")` pe GitHub real) înainte de a fi confirmat în producție. | ~~HIGH~~ (feature mort; LOW expunere — gated `DEV_MODE`) | Găsit la research-ul Hermes 2026-06-07 |
| ~~BUG-4~~ ✅ | Aplicația scria în `BACKLOG.md` la fiecare autonomy tick (`sync_problems_to_backlog`, setare `error_backlog_sync_enabled` default ON) → modifica fișierul **trackuit** pe disc (pe Windows flip-uia și LF→CRLF pe tot fișierul) → orice `git pull` ulterior **conflicta pe BACKLOG.md**. Cauza reală a conflictelor recurente. **Fixed 2026-06-02:** redirectat către `memory_logs/diagnostics.md` (gitignored) cu scriere idempotentă + LF pinned; scos blocul auto din BACKLOG; `.gitattributes` `eol=lf`; reparat `UPDATE.bat` (`origin master` → `origin main`). | ~~HIGH~~ | Diagnosticat din simptomul „conflict pe backlog la pornirea pe laptop" |

### Hot fixes & taskuri orfane (promovate 2026-06-02)

> Coloana **Dep / secvențiere** spune *când* să fie rezolvat eficient — multe au sens doar
> împreună cu un feature viitor (ca să nu se scrie de două ori).

| # | Item | Tip · P | S | Dep / secvențiere | Sursă |
|---|------|---------|---|-------------------|-------|
| **HF-1** | **Auth pe rutele user-facing `/api/`** — `/chat`, `/chat/stream`, `/api/memory/*` (inclusiv POST `/api/memory/remember`) **nu aveau autentificare**; doar rutele admin erau gate-uite. **→ ✅ Rezolvat:** `_user_guard` (JARVIS_USER_TOKEN / `X-User-Token`, admin-token superset, localhost-default + fail-closed în spatele unui proxy ca HF-7) pe ~32 rute user-facing (chat, memorie, notes, rooms, sessions/tasks, `/sandbox/execute`, `/skills/import`); HUD atașează tokenul automat (`auth.js`, prompt-on-401). Tot prereq pentru **H10.E Multi-user**. | ✅ **DONE** | 5 | — | `agents/web.py:_user_guard` · `tests/test_user_guard_hf1.py` |
| **HF-2** | **Security review pre-go-live** — pen-test pe endpointuri, **CORS** config, review rate-limit. **→ ✅ Cod livrat:** middleware **per-IP rate-limit** (`JARVIS_RATE_LIMIT`, localhost + token-valid exempt, 429 + Retry-After) ca defense-in-depth peste auth HF-1 / limita per-canal din gateway; **CORS knob** opt-in (`JARVIS_CORS_ORIGINS`, default same-origin, neschimbat). *Pen-test-ul manual rămâne ca gate uman în* `MANUAL_TESTING §G`. | ✅ **DONE (cod)** | 5 | — | `agents/web.py` (`_rate_limit`, CORS) · `tests/test_rate_limit_hf2.py` |
| **BUG-2b** | **Frontend test gaps rămase din BUG-2** (trăiau doar în rândul BUG-2 ✅ + `tests/frontend/README.md`): **2b.1** browser E2E (Playwright: server+Chromium, fluxuri chat/tab-uri/command palette/admin); **2b.2** drag-drop canvas workflow (pointer events SVG, layout, edges); **2b.3** voce/`useTTS` (mock `getUserMedia`/`AudioContext`, toggle mic, tranziții stare). | 🧪 Task · P3 | ~14 (8+3+3) | **2b.1** standalone (H7.2 CI ✅) — cel mai bine după ce fluxurile mari H10 se stabilizează, se cuplează cu H9.3/H10.23; **2b.2** ride cu **H10.2** (trace overlay) / **H10.7** (AI builder); **2b.3** ride cu **H12.4** (Wyoming rescrie STT/TTS) / **H12.10** (mute) | BUG-2 deferred + `tests/frontend/README.md` |
| **TASK-1** | **Howard: backend LLM dedicat + prima rulare reală** — `agents/core/llm/ollama_howard.py` (backend dedicat) + ingestion run efectiv + execuție pipeline fine-tuning. H5.1 marchează infra „✅ 100% gata" dar *modelul* și fișierul de backend rămân TODO. | ⚙️ Task · P2 | 8 | **H5.1** (infra ✅, necesită export date Andrei), **H11.3** (SFT/GRPO, GPU) | `docs/internal/gemini_architecture_prompt.md` (TODO-uri) |
| **TASK-4** | **UX pass post-manual-test (HUD + WorldView)** — findings în `docs/2026-06-10-ux-review-hud-worldview.md` (review static ×2 + screenshots reale ale HUD-ului). HUD: P1 double-submit la streaming, afordanță mic-muted, prompt admin-token one-shot; P2 toast erori kill-switch, busy-state pe butoanele de plată, etc. WorldView (mai puțin șlefuit): P1 explicație API-down + legendă layere + claritate LIVE/HISTORICAL. **Fixat deja:** first-run onboarding banner (HUD) + **toate P1+P2 WorldView (2026-06-12**: SystemStatus overlay, legendă layere, mod chip LIVE/HISTORICAL, badge conexiune always-on, help `?`, hint Mapbox, Export colapsat, contrast WCAG, WebGL error boundary, Inspector recovery**)**. Restul (P1 HUD de confirmat pe hardware + P3): *după* testarea manuală — multe P1 se confirmă/infirmă cel mai ieftin pe hardware real. **Brief de design complet pentru partea WorldView** (handover self-contained către Claude Design — inventar UI exact, probleme rancuite, constrângeri brand/tech, deliverables): [`docs/design/WORLDVIEW_UX_BRIEF.md`](docs/design/WORLDVIEW_UX_BRIEF.md) (2026-06-12). **→ Design-ul s-a întors (2026-06-12):** spec implementabil [`docs/design/WORLDVIEW_UX_SPEC.md`](docs/design/WORLDVIEW_UX_SPEC.md) + handoff cu reconciliere post-#193 [`docs/design/WORLDVIEW_UX_HANDOFF.md`](docs/design/WORLDVIEW_UX_HANDOFF.md) + mock hi-fi cu 7 scenarii [`docs/design/worldview-mock/`](docs/design/worldview-mock/). **→ ✅ Redesign IMPLEMENTAT integral (2026-06-12, PR #194):** toți cei 11 pași din spec §6 — tokens+fonturi brand, zone system + app bar, mode system (frame+pill+timeline), Legend=Layers cu glyphs, overlay first-run, right rail + Inspector umanizat, timeline cu event markers + replay în store, tooltips/help/demo-badge, shape encodings pe hartă (icon atlas + fallback), gramatica negative-space (ghosts/DR/cones), arrival deep-link + demo lens. 140 teste frontend verzi, tsc + build verzi. **→ ✅ Chat double-submit guard (2026-07-02):** `runTurn` (`app.tsx`) now ignores a second submit while `thinking` is non-null (rapid double Enter/click, or voice firing mid-turn) instead of racing two `/chat/stream` requests into the same `abortRef`/message index — verified via typecheck + full frontend suite (no dedicated App-render test exists for this component, same as the recent stop-generating change). **Rămâne din TASK-4:** afordanța mic-muted + prompt admin-token one-shot (P1) de confirmat la testarea manuală. | 🎨 Task · P2 | 13 | manual test gate | UX review 2026-06-10 |
| **TASK-3** | **Injection quarantine — taint-track all external channels** (audit pass 3, 2026-06-10): quarantine primitives (`detect_injection`/`spotlight`/`TaintedValue`/`plan_then_execute`) exist + tested but are only invoked at REST inspection endpoints, desktop-operator, and (now) transcript ingest. Verdict: **defense-in-depth, NOT critical** — chat agents return text (read-only plugin gathering, no mutating tool call); the one text→task path (transcript) is hard-forced to ask-tier so nothing auto-runs. Closed the visible gap (transcript injection flags on the approval card). **Open (owner architecture call):** wrap email/web-webhook input in `TaintedValue` at the channel boundary + gate irreversible tool calls through `QuarantinePolicy.check_step`, so a future autonomous-tool path is covered by construction. | 🛡️ Task · P2 | 8 | H17.1 (quarantine) + risk gate (holds) | Audit pass 3 2026-06-10 |
| **TASK-2** | **HUD v2 depth — paritate UI cu backendul** (audit 2026-06-10): backendul a luat-o iar înainte — ~37 endpoint-uri (recente sau write-only) **fără control în HUD v2**. **→ 🟡 Gap-ul de controale ÎNCHIS în PR #181 (2026-06-10):** cognition SSE live în cockpit, payments approve/reject/settle (Trust), pairing H12.19, injection scan H17.1, transcript ingest H12.25, escalation H12.11, reflection run, heartbeat run/start/stop, `/learning/promote`, marketplace review H12.12, eval runs+compare, AI step builder H10.7, sandbox execute, agent templates H10.29, LM Studio server/load/unload, auth-profiles H12.20 — noi panele Console în `frontend/src/gap.tsx` + `actA` (token admin) + 7 teste frontend (19 total). **Coada redusă (2026-07-05):** LIVE/SEED per-panel ✅ (58/58 Console cards), AUD-16 OpenAPI typegen/diff gate ✅, plugin-gated mode base wiring ✅ in #505 (Build/Comms/Finance/Health/Knowledge/Family), P3.2 stale-doc reconciliation ✅ (#507), Data Spaces assign/unassign controls ✅ (#515), Rooms selected-history drawer ✅ (#517), capability issue/check UI ✅ (#519), current-mesh task fan ✅ (#521), preferences/tweaks UI ✅ (#523), self-hosted HUD fonts ✅, and Safe Comms channel inbox transport v0 in #551 (telegram/web persisted threads + governed replies). **Rămâne coada:** owner live-data/plugin setup (bank/broker/quotes, Apple Health bridge, websearch backend, WhatsApp bridge) and non-v0 inbox channels — vezi `docs/design/HUD_V2_REMAINING.md`. | 🟡 În progres · P2 | 13 (≈12 livrate) | HUD v2 cutover ✅ (2026-06-08) | Audit paritate 2026-06-10 + PR #181 |
| **CLN-1** | **Șterge `tests/test_spotify.py`** — 9 skip-uri permanente care așteaptă `agents/core/skills/spotify.py` (cale ce nu va exista; pattern opencode). Spotify livrează prin `skills/spotify/main.py`, acoperit de `test_spotify_skill.py`. Elimină și zgomotul „8 skipped". **→ ✅ Făcut:** `tests/test_spotify.py` nu mai există (eliminat); Spotify e acoperit de `test_spotify_skill.py`. | ✅ **DONE** | 1 | Niciuna | `tests/test_spotify.py:19`, `BACKLOG.md` (nota „Run") |
| **TASK-5** | **✅ REZOLVAT — user-tier `GET /tasks` nu mai servește payload/result.** `format_task` proiectează `payload`/`result` afară din rândul brut înainte de răspuns (HUD-ul folosește doar owner/state/label/project/title/decision — verificat pe ambii consumatori `frontend/src`), regression-test pe toate view-urile (`tests/test_dashboard.py::test_tasks_user_tier_never_ships_payload_or_result`). În aceeași mișcare, feed-ul H34.1 și-a închis propriul leak (PGE-042): misiunile nu mai livrează `plan[].result` și rulările de workflow nu mai livrează `steps[].input_preview/output_preview` (recursiv pe sub-workflows), fără să mute sursele (`_payload_free_mission`/`_payload_free_run` + test cu shape-uri realiste). Original: `dashboard.py` întorcea `Task.to_dict()` complet la user-tier, deși toate citirile `/autonomy/*` sunt admin-tier. | 🛡️ Task · P2 | 2 | — | Review H34.1 · `agents/core/routers/dashboard.py` |
| **NTH-1** | **`/cognition/stream` (scoring live)** — `/api/cognition` întoarce deja `last_cognition` real; mock-ul static `COGNITION_SCORING` din `data.js` rămâne ca fallback ne-configurat. Varianta streaming e netrackuită. *(parțial superseded — low)* **→ ✅ Făcut:** `GET /api/cognition/stream` (SSE) emite snapshot-ul `last_cognition` la schimbare + heartbeat pe idle; generatorul de evenimente ia `get_cog`/`sleep` injectabile → testabil offline. | ✅ **DONE** | 3 | H9.2 | `docs/internal/design_handoff_jarvis_hub/README.md`, `data.js` |
| **HF-3** | **Hardening scanner Secret/PII** — pattern OpenAI prea laxat (`sk-…{20,}`, real ≥40 chars → false positives); `db_connection_string` (`scanner.py:82`) prea larg (orice 10+ chars după `://`); `password_assignment` (`:81`) prinde doar valori *între ghilimele* (ratează `password=secret` neîncadrat); **lipsesc** JWT (`eyJ…`), service-account JSON GCP/Azure, Bearer tokens, material PEM, heuristică entropie. **→ ✅ Rezolvat (cod, deja livrat):** scanner-ul le implementează pe toate — OpenAI `{40,}` (nu `{20,}`), db-string cere `user:pass@host`, `password_assignment` prinde bare ȘI quoted, + JWT `eyJ…`/GCP-SA JSON/Azure storage/Bearer/PEM + heuristică de entropie Shannon (`looks_like_high_entropy_secret`, ≥3.6 bits/char). | ✅ **DONE** | 3 | Se cuplează cu HF-2 (security review) | Audit cod 2026-06-04 · `agents/core/security/scanner.py:76-87` |
| **HF-4** | **SSRF: DNS-rebinding / TOCTOU** — `check_ssrf` rezolva IP-ul la momentul check-ului, dar fetch-ul real era ulterior; un domeniu controlat de atacator putea întoarce IP public la check și `127.0.0.1` la fetch. **→ ✅ Rezolvat:** `resolve_and_validate` rezolvă o singură dată și **respinge dacă oricare** IP e privat (anti split-horizon rebinding); `fetch_page` **pin-uiește pe IP-ul validat** la conectare (Host + TLS SNI păstrate) și urmărește redirect-urile **manual**, validând fiecare hop înainte de conectare. | ✅ **DONE** | 3 | — | `agents/core/security/ssrf.py` · `agents/core/plugins/websearch.py` · `tests/test_ssrf.py` |
| **HF-5** | **Separare cheie HMAC audit** — cheia de semnare stătea lângă log (`memory_logs/security/*.key`); acces de scriere pe dir-ul de log = citirea cheii + rescrierea lanțului + re-semnare. **→ ✅ Rezolvat:** `IntentLog._resolve_key` preferă acum o cheie **în afara** dir-ului de log — `JARVIS_AUDIT_KEY` / cheie explicită / dir securizat (`JARVIS_KEY_DIR`, altfel `~/.config/jarvis`); cheia co-locată legacy e onorată cu **warning** de migrare; fallback co-locat doar dacă dir-ul securizat nu e scriibil. *(Anchoring extern via timestamp-authority rămâne nice-to-have post-1.0.)* | ✅ **DONE** | 3 | — | `agents/core/security/anchor.py` · `tests/test_audit_key_hf5.py` |
| **HF-6** | **Sandbox: bypass prin `DEV_MODE`** — când `DEV_MODE=1` (frecvent în dev), `Sandbox` execută cod **direct pe host** (fără Docker, fără `--network none`/limite mem/pids) — `sandbox.py:75-87,158-163`. Risc major dacă rămâne setat în prod. Fix: opt-in *per-apel* explicit (nu flag global), warning vizibil în HUD/`/status` când subprocess fallback e activ. **→ ✅ Rezolvat:** host-fallback e opt-in *per-instanță* (`allow_subprocess`, niciodată flag global — `orch.sandbox` îl lasă OFF, deci `DEV_MODE` **nu** mai pornește host-exec); `active_backend()`/`is_isolated()`/`security_status()` expun postura, iar `/sandbox/status` + posture endpoint raportează `insecure_host_exec` + warning; mesaje de eroare/log corectate. | ✅ **DONE** | 3 | — | Audit cod 2026-06-04 · `agents/core/sandbox.py`, `agents/web.py` · `tests/test_sandbox_hf6.py` |
| **HF-7** | **Admin auth în spatele unui reverse-proxy** — fallback-ul „doar localhost" (`_admin_guard`) folosește `request.client.host`, care devine IP-ul proxy-ului în spatele nginx/ingress → admin expus tuturor dacă `JARVIS_ADMIN_TOKEN` nu e setat. Adaugă suport trusted-proxy/`X-Forwarded-For` + rate-limit pe încercări token. **→ ✅ Rezolvat:** ambele guard-uri (`_admin_guard`/`_user_guard`) fail-**CLOSED** în spatele unui proxy (cer token); `JARVIS_TRUSTED_PROXY` (opt-in, default off) + `_real_client_host` folosesc primul hop `X-Forwarded-For` ca IP real pentru poarta localhost; rate-limit pe token-guess via HF-2 (încercările cu token greșit nu sunt exempte). | ✅ **DONE** | 2 | Cu HF-1/HF-2 | Audit cod 2026-06-04 · `agents/web.py:_admin_guard` |
| **CLN-2** | **Spargere god-object `Orchestrator`** (`agents/core/orchestrator.py`) — un singur obiect gestionează agenți + pluginuri + memorie + canale + autonomie + checkpoints + learning. **Început în #118 (audit A2 — `ComponentRegistry`)**, care a redus fișierul 1620→1537 LOC. **→ ✅ Substanțial DONE (#296):** extrași `ChannelManager` (proprietatea `channels`), `PluginManager` (proprietatea `plugins`), execuția LLM-control (`llm_control.run_llm_control`) și builder-ul de cognition-trace (`cognition_trace.update_cognition`) — toți cu facade-uri delegante, suprafața `orch.*` neschimbată. **Orchestrator 1620→1456 LOC.** Restul inline e **pipeline-ul de request** (`handle_input`/`handle_input_stream` + core-ul `_active_session` ContextVar din BUG-5) — **nu se poate extrage în siguranță** (testele asignează direct ~10 atribute de stare: observer/checkpoints/tracer/run_history/memory/mcp/autonomy_queue/skills/workflow_*, deci nu pot deveni proprietăți). Punct natural de oprire. **Plan:** [`docs/superpowers/specs/2026-06-13-cln2-cln3-refactor-plan.md`](docs/superpowers/specs/2026-06-13-cln2-cln3-refactor-plan.md). | ✅ Substanțial DONE · P3 | 5 | #118 (A2) → #296 | Audit cod 2026-06-04 |
| **CLN-3** | **Spargere `web.py`** (~4636 LOC, 233 rute, singletons globale `orch`/`gateway`) — split în routere FastAPI per-domeniu (`APIRouter`). **→ ✅ DONE (#293 batch 2 + #296 complet):** **45 de domenii extrase** în `core/routers/` cu wrappere lazy de auth-guard (`_deps.py`, fără ciclu de import); topologie 3-straturi `web_helpers`/`app_state`/`_deps` cu `get_orch()` late-binding. **web.py 4636→1282 LOC; 233→9 rute inline** (rămân, by design: app-shell `/`,`/v1`,`/v2`,favicon,sw.js + `/chat`,`/chat/stream` + `/admin`). Suprafața de **304 rute e byte-identică**, gardată de `tests/test_route_parity_guard.py` + `test_openapi_parity_guard.py` + `test_lifespan_smoke.py` + `test_route_auth_matrix.py`. **Plan:** [`docs/superpowers/specs/2026-06-13-cln2-cln3-refactor-plan.md`](docs/superpowers/specs/2026-06-13-cln2-cln3-refactor-plan.md). | ✅ **DONE** · P3 | 8 | #293 → #296 | Audit cod 2026-06-04 |

> **TASK-2 since-closed update (2026-07-14):** the H28 Operator depth is now complete in
> Console → Build, with real callers for browser check/preview and desktop preview/run plus native
> desktop-approval boundaries. TASK-2 remains 🟡: its actual tail is owner live-data/plugin setup
> (bank/broker/quotes, Apple Health, websearch, WhatsApp) and non-v0 inbox channels.

## ✅ ORIZONT 5 — Next Wave (P2–P3) — 17/17 COMPLET

> Fiecare item are spec + plan propriu în `docs/superpowers/`. Timeline: 0.6 → 0.9 → 1.0.
>
> **ORIZONT 5 COMPLET ✅** (2026-06-01) — 17/17 items livrați. Detalii de livrare: [docs/HISTORY.md](docs/HISTORY.md).

| # | Item | S | Dep | Target version |
|---|------|---|-----|---------------|
| H5.1 ✅ | **Howard: Fine-Tuning + Voice Clone + Continuous Ingestion** — RAG pipeline (`ingestion/pipeline.py`, `watcher.py`), Facebook/WhatsApp parsers, `Embedder` cu caching (H5.17), TTS fallback chain (edge-tts/XTTS/ElevenLabs), IngestionWatcher wired în orchestrator. *(Fine-tuning model: necesită export date personale Andrei — infra 100% gata)* | 13 | — | 0.6 ✅ |
| H5.2 ✅ | **Mobile HUD / PWA** (responsive, offline, push) | 8 | — | 0.7 ✅ |
| H5.3 ✅ | **Multi-Language / i18n (RO/EN switch)** | 5 | — | 0.7 ✅ |
| H5.4 ✅ | **UI Overhaul (teme, layout, accesibilitate)** | 8 | H5.2 | 0.7 ✅ |
| H5.5 ✅ | **Performance & Robustness** (retry, circuit breaker, rate limit, caching, resilience metrics) | 8 | — | 0.8 ✅ |
| H5.6 ✅ | **Multi-Agent Workflows** (handoff, paralel, pipeline) — `WorkflowEngine` + `Pipeline`/`WorkflowStep` (DAG, topological sort, parallel batches) + `WorkflowRegistry` (3 built-in: finance_report, research_and_brief, security_digest) + endpoints `/api/workflows` + `/api/workflows/run`. 16 teste offline. | 13 | H5.5 | 0.8 ✅ |
| H5.7 ✅ | **New Integrations / Plugins (SMS, CRM, IoT, social)** | 8 | — | 0.9 ✅ |
| H5.8 ✅ | **Agent Marketplace / Skill Sharing** (registry, publish) | 13 | H5.6 | 0.9 ✅ |
| H5.9 ✅ | **Resilience Tab in Main HUD** — tab live în SystemsPanel cu retry metrics + circuit breaker states, endpoint public `/api/resilience` | 3 | H5.5 | 0.8 ✅ |
| H5.10 ✅ | **Live Data Wiring** — Memory, Plugins, Learning, Security tabs trec de la mock static la endpoint-uri live (`/memory/stats`, `/api/plugins`, `/learning/stats`, `/security/status`, `/bench/stats`) | 5 | H5.9 | 0.8 ✅ |
| H5.11 ✅ | **Missing Widgets** — Ticker feed live, OAuth status tab, Oracle tab, Tasks widget; CognitionPanel live | 5 | H5.10 | 0.8 ✅ |
| H5.12 ✅ | **Secured Shell Task Executor** — `RemediationRunner` (allowlist, permission gate, no-shell `exec`, audited) wired ca handler `restart_service` în executor. 0.45 B1 branch adds shared `HOST_CONTROL_CONTRACT` coverage for `restart_service` and LM Studio host subprocess control before execution. `core/autonomy/remediation.py` | 5 | H6.7 | 0.8 ✅ |
| H5.13 ✅ | **Proactive Event Watchers** — `EventWatcher` + Email/Calendar/Finance/Health probes, eșantionate în bucla de autonomie (gated `system.watchers_enabled`). `core/autonomy/watchers.py` | 8 | H6.7 | 0.8 ✅ |
| H5.14 ✅ | **Retrieval Fusion Engine** — `reciprocal_rank_fusion()` + `HybridRetriever` (vector⊕graph RRF, weight-tunable, injectabil) + `MemoryManager.hybrid_search()`. `core/memory/fusion.py`, 9 teste offline. **Task4 ✅:** `GET /api/memory/search` + `FusedRecallBox` în MemoryTab. | 5 | H3.1, H3.2 | 0.8 ✅ |
| H5.15 ✅ | **Daily Reflection & Graph Consolidation** — `DailyReflector` (`core/autonomy/reflection.py`): gather context → LLM reflection → JSON entities/relations/lessons → promote to Neo4j graph; idempotent per zi; hookuit în `_autonomy_loop` (fereastră 22:00–07:00, gated `system.reflection_enabled`). Endpoint `/api/reflection/status` + `/api/reflection/run`. 10 teste offline. | 8 | H6.6, H3.2 | 0.8 ✅ |
| H5.16 🟡 | **Sentence-level TTS & Audio Barge-in** — edge-tts integration + server-side play/stop exist and are tested. **Sentence-level streaming (server) landed:** pure splitter `core/voice/sentence_stream.py` (`split_sentences` + incremental `SentenceAggregator`, 18 offline tests) + `TTSEngine.speak_stream` + `POST /tts/stream` (opt-in `voice.sentence_streaming`, default off; multipart-free framed audio so synthesis/playback can start after sentence #1). Earlier shipped: **browser voice loop** (mic → local STT `/api/voice/stt` → chat → TTS playback, hands-free; PR #162) with **opt-in barge-in** (PR #164, default off, needs on-device echo-cancellation tuning). **voice.ts wiring ✅ (verified 2026-07-02):** `speak()` tries `streamTts` first (`frontend/src/voice.ts:206-215`, frames played back-to-back) with clean fallback to whole-reply `/tts` on 409 when the server opt-in is off. **Still TODO:** synthesize *while* the chat streams (the `SentenceAggregator` building block is ready); browser wake-word. See `docs/VOICE.md`. | 8 | H1.1, H5.5 | 0.8 🟡 |
| H5.17 ✅ | **Batch & Cache Embeddings Pipeline** — `EmbeddingCache` (content-addressed, sharded, crash-safe) + `Embedder.embed_batch` (dedup + paralel) + retry/backoff (degradare la hash) + cache stats în pipeline. `core/ingestion/embedder.py` | 5 | H5.5 | 0.8 ✅ |

---

## ORIZONT 7 — Performanță Cale Fierbinte (P1–P2)

> Sursă: profiling 2026-06-02 al căii per-turn (NU generarea LLM). Bottleneck
> non-LLM = scrieri sincrone SQLite pe event-loop-ul async (checkpoint + audit +
> worker autonomie). Detalii + măsurători: `docs/research/2026-06-02-perf-hotpath.md`.
> **Câștig măsurat:** commit SQLite `3317 µs → 92 µs` (~36×) cu WAL+`synchronous=NORMAL`.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H7.1 ✅ | **SQLite WAL + `synchronous=NORMAL`** pe DB-urile scrise per-turn — `checkpoint.py`, `security/audit.py`, `autonomy/queue.py`. Durabil (WAL crash-safe; NORMAL sigur sub WAL). | 1 | P1 | — | ✅ commit-uri ~36× mai ieftine; suite persistență/autonomy/securitate verzi |
| H7.2 ✅ | **Offload scrieri blocante de pe event-loop** — `checkpoints.save` / `audit.log` / `_record_interactions` / `_log_session` prin `asyncio.to_thread` în toate cele 3 call-site-uri per-turn; `checkpoint.py` cu `check_same_thread=False` + `threading.Lock`. | 3 | P1 | H7.1 | ✅ handlerele per-turn nu mai fac I/O sqlite/fișier sincron pe loop; thread-safe sub `to_thread` |
| H7.3 ✅ | **Debounce / frecvență checkpoint** — `_maybe_checkpoint()` salvează doar la `memory.checkpoint_every` (default 5) turns; `_flush_checkpoint()` forțat pe `new_session()` + `aclose()` (shutdown). Reduce I/O și CPU (`json.dumps` al state-ului). | 2 | P2 | H7.2 | ✅ checkpoint scris ≤1×/N turns; restart curat nu pierde sesiunea activă |
| H7.4 ✅ | **Query-embedding cache + fast-fail (recall)** — `Embedder.from_env(cache_dir=…)` default `memory_logs/embedding_cache/recall` + LRU in-process (`_PROC_CACHE`, 256) cheie `(backend,model,text)`; `max_retries=1` fast-fail. | 2 | P2 | — (recall) | ✅ query repetat = cache hit (fără network/disk); embeddings down → recall degradează instant |
| H7.5 ✅ | **Strategie fast/heavy model** — `is_heavy_request()` (token threshold 2000 + keywords RO/EN) escaladează în `hybrid_router.select_backend()` POLICY_AUTO de la slotul rapid (VRAM) la slotul deep (DDR5); flag `JARVIS_AUTO_DEEP`. | 8 | P2 | — | ✅ task ușor → model rapid `local`; task greu → `local-deep`/DEFAULT_DEEP_MODEL; nu afectează cloud/claude/local-only |

> **ORIZONT 7 PERF COMPLET ✅** (2026-06-02) — 5/5 items, +49 teste offline. Detalii: [docs/HISTORY.md](docs/HISTORY.md).

---

## ✅ ORIZONT 8 — Memorie Personală & Personalizare („Jarvis te cunoaște") (P1) — 7/7 COMPLET

> **Viziune:** Jarvis își construiește în timp o **memorie despre Andrei** — fapte, preferințe,
> decizii, oameni, proiecte — extrasă din conversații, consolidată periodic (ca reflection-ul H5.15),
> versionată și injectată în context la fiecare agent, ca răspunsurile să fie personalizate fără
> să repet de fiecare dată cine sunt și ce vreau. Construit pe infrastructura livrată: fused recall
> (H5.14), embeddings reale + cache (H7.4), daily reflection (H5.15).
>
> **Principii:** local-first (ethos Frigga — datele personale rămân pe LAN), **inspectabil & editabil**
> (pot vedea/șterge orice fapt), opt-in pentru orice plecare spre cloud. Personalizarea crește în timp,
> dar controlul rămâne la mine.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H8.1 ✅ | **Memorie despre Andrei (User Profile Memory)** — store structurat persistent (facts / preferences / decisions / people / projects) construit din conversații (extragere LLM + consolidare idempotentă, pattern H5.15), versionat, injectat în prompt la toți agenții. `core/memory/store.py` + `core/memory/profile_extractor.py` + `/api/memory/profile`. *(PR #37)* | 13 | P1 | H5.14, H5.15, H7.4 | după câteva conversații, Jarvis cunoaște preferințe/fapte despre Andrei și le folosește; profilul e inspectabil în HUD |
| H8.2 ✅ | **Privacy & Forget Controls** — pentru memoria personală: export JSON, forget/redact selectiv per fapt, retention policy, scope strict-local. | 5 | P1 | H8.1 | pot șterge un fapt anume; export complet; nimic personal nu pleacă în cloud fără opt-in explicit |
| H8.3 ✅ | **Recall ON by default + Memory HUD** — activează `memory.recall_enabled` cu cache-ul H7.4; tab HUD cu faptele memorate (search/edit/delete), surse și scoruri (extinde Fused Recall). | 8 | P2 | H7.4, H8.1 | recall activ în chat din oficiu; HUD afișează și editează memoria personală |
| H8.4 ✅ | **Embeddings de calitate (model dedicat)** — `mxbai-embed-large` sau container TEI; benchmark calitate retrieval vs hash/nomic; degradare grațioasă păstrată. | 5 | P2 | H7.4 | retrieval măsurabil mai bun pe un set de probe; fallback intact |
| H8.5 ✅ | **Validare live fast/heavy (H7.5) + Model Tier HUD** — confirmă pe System76 cu 2 sloturi LM Studio încărcate; expune deciziile de tiering (fast↔deep) în `/bench` + HUD. | 5 | P2 | H7.5 | comutare fast↔deep vizibilă; latențe per tier măsurate |
| H8.6 ✅ | **Proactive Personal Briefs** — morning/evening brief (H6.4) personalizate din profil + recall: ce contează pentru Andrei azi (proiecte, oameni, deadline-uri). | 5 | P3 | H8.1, H6.4 | briefurile referă proiectele/oamenii din profilul personal |
| H8.7 ✅ | **AI-Navigable Docs upkeep** — `docs/ARCHITECTURE.md` ca sursă unică de navigare pentru asistenți AI; checklist „docs la zi" în template-ul de PR. | 2 | P3 | — | doc-ul reflectă codul curent; PR-urile mari ating și ARCHITECTURE.md |

> **ORIZONT 8 COMPLET ✅** (2026-06-02) — H8.1–H8.7 livrate (PR-uri #33, #37, #43). Cod: `core/memory/{store,profile_extractor,digest}.py`, endpoints `/api/memory/profile`, `/api/memory/recall`, `/api/analytics/model-tiers`. Detalii: [docs/HISTORY.md](docs/HISTORY.md).

---

## ✅ ORIZONT 9 — Agent Ops: Visual Workflows & Observability (P2) — 3/3 COMPLET

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H9.1 ✅ | **Visual Workflow Builder** — tab HUD (canvas SVG, vanilla React) PESTE `WorkflowEngine` (H5.6): noduri = pași/agenți, muchii = `depends_on`; creează/editează/salvează workflow-uri user-defined + rulare. Backend: `Pipeline.from_dict`, persistență (CRUD) + endpoints `/api/workflows` POST/PUT/DELETE, register în registry. | 13 | P2 | H5.6 | pot compune vizual un workflow, îl salvez, îl rulez din HUD; DAG invalid → eroare clară |
| H9.2 ✅ | **Observability — Trace Explorer** — store de trace-uri per-request (classify→route→model→tokens→latență→cost), nu doar `last_cognition`; endpoint `/api/traces[/{id}]` + tab HUD de inspecție. Extinde `bench.py` + CognitionPanel. | 8 | P2 | — | fiecare request lasă un trace inspectabil; pot vedea unde se duce timpul/tokenii pe pași |
| H9.3 ✅ | **Offline Eval Harness** — rulează seturi de prompturi prin orchestrator (LLM injectabil), scor pass/criterii, tracking de regresie; `core/observability/eval.py` + CLI/endpoint. | 8 | P2 | H9.2 | un set de probe produce scor reproductibil offline; regresii vizibile între rulări |

---

## ORIZONT 10 — Jarvis Competitive Edge (P1–P3) — 30/30

### H10 — Status General

| Horizon | Total | ✅ Done | S total | S done | % |
|---------|-------|---------|---------|--------|---|
| **H10 Competitive Edge** | 30 | **30** | 188 | **186** | **99%** |

> H10.A–E livrate în valul 2026-06-03; **H10.30** (Write-Back Integrations) livrat 2026-06-09 → **H10 complet (30/30)**. *(H10.7 și H10.26 au fost livrate ✅.)*

### H10.A — Observability & Eval (P1 — fundație)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.16 ✅ | **APM Dashboard** — metrici org în Admin HUD: tokens totali consumați (cu cost $ estimat), runs totale, breakdown per agent și per model. **Done 2026-06-03:** `cost_tracker.apm_summary()` (totals runs/tokens/$ + by_agent + by_model, reutilizează H7.10 get_summary) + endpoint admin-guarded `GET /api/admin/apm` (include și `bench.get_summary()` latency). +3 teste offline. | 5 | P1 | H9.2 | SuperAGI |
| H10.24 ✅ | **Cost Tracking per Agent** — calcul $ per request (tokens × preț per provider/model), stocat în trace, vizibil per agent/zi în HUD. **Done 2026-06-03:** cost per-trace via `core/llm/cost_estimator.py` (reutilizat din H7.10, local = $0); `Tracer.cost_by_agent/cost_by_day/cost_summary` peste ring-buffer; endpoint `GET /api/cost` (by_agent + by_day + summary). +8 teste. *(Override `PRICE_TABLE` din config = follow-up.)* | 5 | P1 | H9.2 | LangSmith |
| H10.19 ✅ | **Model Arena / Blind Comparison** — același query la 2+ modele, răspunsuri anonimizate, vot, leaderboard agregat. **Done 2026-06-03:** `core/arena.py` `Arena` (JSON file-backed) — `create_match` anonimizează (labels A/B shuffled, mapping ascuns până la vot), `vote` dezvăluie mapping + actualizează ELO (K=32) + win/loss, `leaderboard` (elo/win-rate, sortat); endpoints `POST /api/arena/run` (candidates date sau rulează ≥2 agenți live), `POST /api/arena/vote`, `GET /api/arena/match/{id}`, `GET /api/arena/leaderboard`. +6 teste offline. | 8 | P1 | H7.5 | OpenWebUI |
| H9.3b ✅ | **Dataset Regression Tracking** (ext. H9.3) — datasets de eval persistente cu versiuni (JSONL), track scor per dataset-version, comparare rulări în HUD; integrabil în CI. **Done 2026-06-03:** `core/observability/datasets.py` `DatasetStore` (versiuni JSONL + run-log + `compare()` regresii/îmbunătățiri pe caz + score-delta) peste `EvalHarness` (H9.3); endpoints `GET /api/eval/datasets`, `/{name}/runs`, `/{name}/compare`, `POST /api/eval/datasets/run`. +8 teste offline. | 5 | P1 | H9.3 | LangSmith |
| H10.22 ✅ | **Agent Prompt Version Control** — SOUL.md versionat cu history, comparare 2 versiuni, A/B eval, rollback. **Done 2026-06-03:** `core/soul_versioning.py` `SoulVersionStore` (JSON file-backed) — `commit` versiuni numerotate imutabile (hash/message/author/parent, dedup pe conținut identic), `history`/`get`/`current`, `diff` unified între 2 versiuni, `rollback` non-distructiv (commit nou cu conținut vechi), A/B: `set_experiment`/`pick` (split determinist via roll)/`record_result`/`ab_summary` (mean per versiune + winner); endpoints admin-guarded `/api/admin/prompts/{agent_id}/{history,version/{n},commit,diff,rollback,ab}`. +8 teste offline. | 13 | P1 | H9.3b | LangSmith |
| H10.23 ✅ | **Live Quality Monitor** — evaluatori (heuristic + LLM-as-judge) pe trace-urile live după fiecare request; scor per request în trace; alertă sub threshold. **Done 2026-06-03:** `core/observability/quality.py` — `evaluate_heuristics` (ok/non_empty/no_error/latency), `score_trace` (medie heuristică, opțional blend 50/50 cu judge injectabil, tolerant la erori judge), `QualityMonitor` (ring rolling, `record`/`rolling_avg`/`check_alert`/`recent`/`stats`/`set_threshold`); hook în orchestrator: scor atașat la trace (`trace["quality"]`) după `tracer.record`; endpoints `GET /api/quality`, `/quality/scores`, admin `POST /quality/threshold`. +8 teste offline. | 13 | P2 | H9.2, H10.24 | LangSmith |
| H10.17 ✅ | **Per-Agent Run History** — în HUD per agent: timeline run-uri, durată, status (success/fail), cost, rută. **Done 2026-06-03:** `core/run_history.py` `RunHistory` (JSON file-backed, ring `deque` capat per agent, record input/output preview+latency+ok+cost+route, `list` most-recent-first, `agents()` rollup ok-rate/avg-latency/cost, clear); hook în orchestrator `_record_interactions`; endpoints `GET /api/agents/history` (rollup) + `GET /api/agents/{id}/history?limit=`. +5 teste offline. | 8 | P2 | H9.2 | SuperAGI |
| H10.25 ✅ | **Human Review Queue** — trace-uri flagate (scor mic sau manual) → coadă de review cu rubric, vot thumbs up/down, adăugare la dataset eval. **Done 2026-06-03:** `core/observability/review_queue.py` `ReviewQueue` (JSON-persistat) — `flag` (idempotent per trace_id) + `auto_flag` (hook H10.23: flag sub threshold), `review` (verdict up/down + rubric filtrat la `RUBRIC_CRITERIA` + notes), `to_eval_case`/`mark_in_dataset`, `stats`; hook în orchestrator (auto-flag după quality.record); endpoints `GET /api/review/queue|stats`, `POST /api/review/flag`, `/{id}/vote`, `/{id}/dataset` (scrie în `DatasetStore` H9.3b). +7 teste offline. | 5 | P3 | H9.3b | LangSmith |

### H10.B — MCP & Integrare (P1–P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.5 ✅ | **MCP Server Mode** — Jarvis expune agenți ca tool-uri MCP *guvernate*; orice client MCP (Claude Desktop, Cursor, alt Jarvis) poate apela agenți Jarvis ca tool-uri. **Done 2026-06-03:** `core/mcp/server.py` `JarvisMCPServer` — core JSON-RPC 2.0 transport-agnostic (initialize/tools/list/tools/call/ping), un tool `ask_<agent>` per agent, allowlist + LAN-only by default, rutează prin orchestrator (guardrails+gate); endpoints `GET /api/mcp/server` (status+tools) + `POST /api/mcp/server/rpc` (gated pe `mcp.server_enabled`, default off). +13 teste offline. *(stdio/SSE loop = transport peste același core, follow-up.)* | 8 | P1 | H4.7 | Langflow |
| H10.8 ✅ | **Inbound Webhook Triggers** — endpoint `/api/webhooks/{id}` (POST) activează un agent sau workflow pre-configurat cu payload-ul ca input; autentificat cu token. **Done 2026-06-03:** `core/webhooks.py` `WebhookStore` (JSON file-backed, token `secrets` + compare constant-time, mask la list, accounting calls/last_called) + `extract_input` payload→text; endpoints CRUD `GET/POST /api/webhooks`, `DELETE /api/webhooks/{id}` + trigger `POST /api/webhooks/{id}` (token via header `X-Webhook-Token` sau query, rutează la agent prin orchestrator / workflow best-effort). +8 teste offline. | 3 | P2 | H5.6 | Langflow + Dust |
| H10.27 ✅ | **NL Scheduling** — text "every weekday at 7am" / "în fiecare luni la 9" → cron. **Done 2026-06-03:** `core/autonomy/nl_schedule.py` `parse_schedule` — EN+RO, time parse (7am/6:30pm/19:00/„la 9"), zile (weekday/weekend/zile specifice multiple), intervale (every N min/hours, hourly) → cron 5-câmpuri + descriere; eroare clară la timp lipsă/invalid; endpoint `POST /api/schedule/parse` (422 pe neparsabil). +10 teste offline. | 3 | P2 | H3.5 | Dust |
| H10.1 ✅ | **Embeddable Chat Widget** — `/api/widget/{token}` returnează snippet JS+CSS care embed-uiește chat-ul pe orice site; theming din Admin. **Done 2026-06-03:** `core/widget.py` `WidgetStore` (token-uri per-site, theming title/color/position/greeting, issue/get/update/revoke, persistat) + `render_snippet` (IIFE self-contained: bulă flotantă + panel, postează la endpoint token-scoped); endpoints admin `POST/GET/DELETE /api/admin/widgets`, public `GET /api/widget/{token}` (JS) + `/config` + `POST /api/widget/{token}/message` (rutează prin orchestrator, channel=widget). +4 teste offline. | 3 | P2 | H1.3 | Flowise |
| H10.30 ✅ | **Write-Back Integrations** — agenții pot scrie înapoi în sisteme externe (Notion, GitHub Issues, Google Calendar) ca tool-uri native; Pepper/Hephaestus primii candidați. **Done 2026-06-09 (strat guvernat):** `core/writeback.py` `WriteBackBroker` — request → validare pe allowlist (5 perechi target/action) + sanitizare câmpuri (drop chei străine, cap lungimi/liste) → **task guvernat ask-tier** în coadă (`kind=writeback.<target>.<action>`, `autonomy_level="ask"`, tier extern); **nimic nu se scrie extern la request**. Pe aprobare, worker-ul (executor prefix `writeback`) dispecerizează la `WriteBackBroker.execute` care **rezolvă credențialele la momentul acțiunii, în spatele aprobării** (SecretBroker H15.4 — agentul stochează doar handle `{{secret:…}}`, niciodată tokenul) și apelează un **client injectabil** (`NullWriteBackClient` offline default; `HttpWriteBackClient` = rail live host-side construit prin `build_request` pur). Endpoints `GET/POST /api/integrations/writeback` (user-guarded). +18 teste offline (catalog/supports, validare target+câmpuri, sanitizare, build_request per (target,action), execute behind-approval cu/fără secret, e2e prin TaskQueue+worker real). *(Apelul de rețea real = poartă host.)* | 8 | P3 | H2.1, H2.7 | Dust |

### H10.C — Memory & RAG (P1–P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H8.1b ✅ | **Entity Memory Store** (ext. H8.1) — extragere de entități (persoane, proiecte, locuri, concepte) din conversații într-un store structurat separat, searchable, afișat în HUD Memory tab. **Done 2026-06-03:** `core/memory/entity.py` `EntityStore` (JSON file-backed, upsert cu mention-count + sources + contexts + first/last-seen, search/filter pe tip, stats, delete; extracție proper-noun offline `extract_entities` + clasificare pe hint, extractor LLM injectabil ulterior); ingest per-tură în orchestrator (`_record_interactions`); endpoint `GET /api/memory/entities?q=&type=&limit=`. +9 teste offline. | 5 | P1 | H8.1, H5.14 | CrewAI |
| H8.3b ✅ | **Agentic RAG Tool** (ext. H8.3) — recall devine tool call LLM-callable (`search_memory(query)`); modelul decide când/cum să caute și poate retry cu query diferit. **Done 2026-06-03:** `core/memory/rag_tool.py` — `TOOL_SPEC` (function-calling schema), `MemorySearchTool` (wrap recall_fn, înregistrează calls, înghite erori), `agentic_search(query, tool, planner, max_iters)` buclă agentică (planner decide answer/refine, retry cu query nou, cap pe max_iters); endpoints `GET /api/memory/tool-spec` + `POST /api/memory/search-tool` peste recall structurat (entities+KG, offline). +8 teste offline. | 8 | P2 | H8.3, H7.4 | OpenWebUI |
| H10.21 ✅ | **Conversation Notes** — note atașate sesiunii, injectate ca context persistent; „Rescrie cu AI". **Done 2026-06-03:** `core/notes.py` `NotesStore` (markdown per `session_id`, get/set/clear, cap 20k, persistat, `context_for` randează bloc `[Session notes]`); injecție în `/chat` (prepend la mesaj pentru sesiunea activă); endpoints `GET/PUT/DELETE /api/notes` + `POST /api/notes/rewrite` (rulează nota prin agent, opțional `save`). +5 teste (store+persistență, cap, context_for, endpoints+injecție, rewrite). Editorul rich-text rămâne pentru HUD (backend complet). | 3 | P3 | H1.3 | OpenWebUI |

### H10.D — Workflow Engine (P2–P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.12 ✅ | **Workflow Termination Conditions** — WorkflowStep poate defini o condiție de stop (keyword/regex/equals/not_empty match), nu doar completare normală. **Done 2026-06-03:** `WorkflowStep.terminate_when` (dict opțional, round-trip to/from_dict fără poluare); `engine.evaluate_condition` (contains/not_contains/equals/regex/not_empty, fail-open pe condiții malformate); engine oprește pipeline-ul după batch-ul în care un guard se declanșează, setând `_terminated`/`_terminated_by`. +6 teste offline. | 3 | P2 | H5.6 | AutoGen |
| H10.10 ✅ | **Structured Agent Outputs (Pydantic)** — un step poate specifica un schema; engine-ul validează output-ul agentului și expune câmpurile tipate downstream. **Done 2026-06-03:** `workflows/structured.py` — `extract_json` (fenced ```json``` sau bare `{...}`), `build_model` (Pydantic v2 `create_model` din schema `{fields:{name:{type,required,default}}}`), `validate_output` → `{ok,data,error}` cu coerce; `WorkflowStep.output_schema` (round-trip) + engine `_apply_structured` (flatten `{step.field}` în ctx, `_structured[step]`, marchează eroare la invalid). +8 teste offline. | 5 | P2 | H5.6 | CrewAI |
| H10.15 ✅ | **Critic Agent Pattern** — built-in workflow node tip `critic`: primește output-ul unui step, îl evaluează (scor + feedback), decide accept / retry(max N). **Done 2026-06-03:** `WorkflowStep.kind` ("agent"/"critic") + `critic` config (`target`, `pass_threshold`, `max_retries`), round-trip; engine `_execute_step` dispatch + `_run_critic` — critic-agent răspunde JSON `{score,pass,feedback}`, re-rulează target-ul cu `{_critic_feedback}` cât timp pică și mai sunt retries; expune `{step.score}`/`{step.passed}` + `_critics[step]` (attempts). +4 teste offline (pass-first, retry-then-pass, exhaust-retries, round-trip). | 5 | P2 | H5.6, H10.12 | AutoGen |
| H10.13 ✅ | **Dynamic Agent Router** — WorkflowStep `kind="router"`: un agent coordinator decide la runtime care agent urmează (conditional routing, nu DAG fix). **Done 2026-06-03:** `WorkflowStep.router` config (`routes` label→agent, `default`, `dispatch_template`), round-trip; engine `_run_router` — agentul-clasificator alege un label (JSON `{"route":…}` sau text), `_match_route` mapează (longest-label-first, fallback default), dispatch la agentul ales; expune `{step.route}`/`{step.agent}` + `_routes[step]`. Fără match & fără default → întoarce decizia, fără dispatch. +6 teste offline. | 8 | P2 | H5.6 | AutoGen |
| H10.2 ✅ | **Visual Workflow Trace Overlay** — la fiecare rulare de workflow, date per-pas (timing, input, output, status) pentru overlay în HUD. **Done 2026-06-03:** engine instrumentează fiecare pas (`_traced_execute` → `ctx["_trace"]` cu step/kind/agent/input/output/elapsed_ms/ok) + ring `recent_runs` (cap 50) cu `recent(limit)` (pipeline_id/name/ts/elapsed/ok/terminated_by/steps); endpoint `GET /api/workflows/traces?limit=`; `/api/workflows/run` întoarce deja `_trace` în rezultat. +4 teste offline. | 5 | P2 | H9.1, H9.2 | Flowise |
| H10.28 ✅ | **Agent Config Preview** — în HUD Admin, înainte de save la SOUL.md/config, preview a ce se schimbă (diff + validare) fără a afecta producția. **Done 2026-06-03:** `core/config_preview.py` — `validate_prompt` (empty=hard-fail; warnings: prea scurt/mare, lipsă headings, frontmatter dezechilibrat), `preview_change` (unified diff + added/removed counts + `is_new`/`changed`); endpoint admin-guarded `POST /api/admin/prompts/{agent_id}/preview` (`current` opțional → ia ultima versiune commit-uită H10.22). +7 teste offline. *(dry-run pe input de test = follow-up.)* | 5 | P2 | H1.5 | Dust |
| H10.4 ✅ | **Guardrails Node în Visual Builder** — scanere secret/PII expuse ca nod, configurabil per workflow. **Done 2026-06-03:** `core/workflows/guardrail_node.py` `apply_guardrail` (reutilizează `SecretScanner`/`PIIScanner` H4.9; mode warn/redact/block, selecție scanere) → warn=pass, redact=mask, block=`[error:guardrail blocked:…]`; `WorkflowStep.guardrail` + dispatch `kind="guardrail"` în engine (info în `ctx["_guardrails"]`). +8 teste (moduri, selecție scanere, serializare, 2 integrate prin engine). | 2 | P3 | H4.9, H9.1 | Flowise |
| H10.6 ✅ | **Cyclic Workflow Support** — loop-back edges cu contor de iterații și condiție de exit. **Done 2026-06-03:** `WorkflowStep.loop` + dispatch `kind="loop"` în engine (`_run_loop`) — re-rulează un body inline de pași (orice kind: agent/transform/guardrail) împărtășind `ctx`, până la `until` (reutilizează `evaluate_condition` H10.12) sau `max_iterations` (clamp [1,100]); expune `{step._iter}` și `ctx["_loops"][id]={iterations,exited_by}`. Nu atinge DAG-ul batch existent. +6 teste (exit pe condiție, max_iterations, counter, body gol no-op, clamp, serializare). | 8 | P3 | H5.6, H10.12 | Langflow |
| H10.7 ✅ | **AI-Assisted Workflow Builder** — câmp "Descrie ce vrei să facă acest pas" → config de step generat. **Done:** `core/workflows/ai_builder.py` `generate_step(description, agents, llm)` — LLM-ul (injectabil) propune un config, **validat** la o formă safe (kind ∈ {agent/router/critic/transform/guardrail/loop/subflow}, agent ∈ allowlist, transform ∈ operatori H10.3, fără câmpuri străine); **fallback euristic determinist** pe keyword-uri când nu-i LLM sau output-ul nu parsează (deci merge și offline, nu întoarce junk). Endpoint `POST /api/workflows/step/generate`. +15 teste offline. | 5 | P3 | H9.1 | Langflow |
| H10.9 ✅ | **Python Flow Decorator API** — `@jarvis_flow`, `@step`, `@listen(step_id)`, `@router` pentru workflow-uri în cod. **Done 2026-06-03:** `core/workflows/flow_api.py` — decoratori (id=numele metodei, `@listen` setează deps, ordine de definire păstrată); fiecare metodă întoarce un step-spec (`agent`/`prompt` + opțional transform/guardrail/router/loop/schema/critic); `build_flow(cls)` compilează în `Pipeline` validat (DAG check, eroare pe non-flow/empty/ciclu). Complement al Visual Builder, rulează prin engine neschimbat. +7 teste (compilare, deps/kinds, router, erori, ciclu, e2e prin engine). | 5 | P3 | H5.6 | CrewAI |
| H10.11 ✅ | **Hierarchical Workflow Manager** — manager agent coordonează crew-ul, validează rezultate, redistribuie la eșec. **Done 2026-06-03:** `core/workflows/hierarchical.py` `HierarchicalManager` — rulează fiecare crew member spre goal (context flows între membri), validează (heuristic error/empty), redistribuie pe eșec (retry cu feedback de la manager, opțional la `fallback` agent, `max_retries`), apoi manager-ul sintetizează output-urile într-un răspuns final; endpoint `POST /api/workflows/hierarchical`. +6 teste (happy path+synthesis, context flow, fallback redistribute, retry same-agent, retries epuizate, endpoint). | 8 | P3 | H5.6, H10.15 | CrewAI |
| H10.14 ✅ | **Nested Workflow Steps** — un WorkflowStep conține un sub-workflow; task decomposition recursivă. **Done 2026-06-03:** `WorkflowStep.subflow` + dispatch `kind="subflow"` în engine (`_run_subflow`) — compilează sub-pipeline din config, îl rulează recursiv cu input = prompt_template randat, expune output-urile sub-pașilor ca `{step.id}.{sub_id}` + output final (configurabil via `output`, altfel ultimul pas) ca output-ul stepului; `ctx["_subflows"][id]`; recursion cap depth 5; DAG-ul părinte rămâne aciclic (sub-pașii trăiesc în config). +6 teste (nesting, chaining cu pași externi, subflow invalid→error, gol, depth cap, serializare). | 8 | P3 | H5.6 | AutoGen |
| H10.3 ✅ | **Workflow Transform Nodes** — Formatter, Validator, JSONExtractor, Summarizer. **Done 2026-06-03:** `core/workflows/transforms.py` `apply_transform` (op-uri deterministe, fără LLM: formatter upper/lower/title/strip/json_pretty, validator non_empty/json/regex/min/max_length/contains→`[error:…]` la fail, json_extract dot-path+default, summarize N propoziții/max_chars); `WorkflowStep.transform` + dispatch `kind="transform"` în engine (no-LLM). +8 teste (unit per-op + serializare + 2 integrate prin engine). | 5 | P3 | H9.1 | Flowise |

### H10.E — UX & Multi-user (P2–P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H10.29 ✅ | **Agent Templates Library** — librărie de configurații pre-built pentru agenți comuni; instanțiabile din Admin. **Done 2026-06-03:** `core/agent_templates.py` — catalog 5 arhetipuri (researcher/coder/analyst/assistant/ops) cu tier/model/plugins/voice + SOUL skeleton; `list_templates`/`get_template` (case-insensitive)/`build_agent_config` (slug id, overrides per câmp, randează config agents.yaml-shaped + SOUL); endpoints `GET /api/agent-templates` + `POST /api/agent-templates/instantiate` (404 pe template necunoscut). +6 teste offline. | 3 | P3 | — | Dust |
| H10.18 ✅ | **Action-Level Approval** — tool call-uri pending approval (granularitate sub-task); Aprob/Resping per acțiune. **Done 2026-06-03:** `core/autonomy/action_approvals.py` `ActionApprovalQueue` — `request` (preview H12.5 per acțiune), `decide` (approve/reject, idempotent), `await_decision` (async pe `asyncio.Event` cu timeout — flux tool blocant), `list/stats`; endpoints `GET /api/actions[/pending]`, `POST /api/actions/request`, admin `POST /api/actions/{id}/decide`. +7 teste (request+preview, approve/reject+stats, filtre, await unblock/timeout/already-decided, endpoints). Tab-ul live HUD folosește acest backend. | 5 | P3 | H6.2 | SuperAGI |
| H10.20 ✅ | **Chat Channels / Rooms** — canale tematice (per proiect/context); @mention agenți; pipeline complet. **Done 2026-06-03:** `core/rooms.py` `RoomStore` (camere persistate cu nume/descriere/roster agenți/default + istoric bounded; `parse_mentions`, `route` = primul @mention din roster altfel default, `context_for` injectează contextul camerei); rutare prin orchestrator (channel=room, full pipeline tools/RAG/filters); endpoints `GET/POST/DELETE /api/rooms`, `GET /api/rooms/{id}[/history]`, `POST /api/rooms/{id}/message`. +6 teste (CRUD, istoric persistat+cap, parse_mentions, routing roster/default, context_for, endpoints+rutare). HUD-ul consumă acest backend. | 8 | P3 | H1.3 | OpenWebUI |
| H10.26 ✅ | **Data Spaces / Agent Data Scope** — surse de date în "spații" cu permisiuni per agent; complement la `LOCAL_ONLY_AGENTS`. **Done:** `core/data_spaces.py` `DataSpaces` — spații (set de surse) + asignări per-agent, **default-open** (agent neasignat = nerestricționat → backward-compatible), `allowed_sources`/`can_access`/`filter_categories`; enforcement la `GET /api/memory/profile?agent=<id>` (întoarce doar categoriile permise), admin CRUD `/api/memory/spaces[/assign|/unassign]`. *(Scoping pe recall-ul vectorial fuzionat rămâne follow-up — necesită surse pe vectori.)* +8 teste offline. | 13 | P3 | H8.1, H4.7 | Dust |

---

## ORIZONT 11 — Platform Parity (Known Gaps vs OpenJarvis) (P3) — 4/4 ✅

> Capabilități prezente în OpenJarvis dar absente în Jarvis Hub (vezi `STATUS.md` → Known Gaps).
> Toate P3 — nice-to-have, niciuna nu blochează 1.0.0. Mai multe au cost mare (GPU, Rust, build nativ).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H11.1 ✅ | **Desktop App (Tauri)** — UI nativ desktop (Windows/macOS/Linux) care împachetează HUD-ul existent; tray icon, wake-word listener local, auto-start. Alternativă la rularea în browser. **Done 2026-06-09 (sursă; build host):** `desktop/` — proiect Tauri v2 care împachetează HUD-ul web existent (fereastră → `127.0.0.1:8080`, tray, auto-start; fără backend nou): `src-tauri/{tauri.conf.json, Cargo.toml, build.rs, src/main.rs}` + README. ⚠️ **Sursă — se compilează host-side (`cargo tauri build`), nu rulează în CI.** | 13 | P3 | — | OpenJarvis (Tauri) |
| H11.2 ✅ | **Rust Extension / Hot-Path Crates** — port în Rust al căilor fierbinți (embeddings, vector search, parsing) ca extensii native (PyO3); pure-Python rămâne fallback. OpenJarvis are 14 crates. **Done 2026-06-09 (sursă + fallback testat):** `rust/jarvis_native/` (crate PyO3: `cosine_similarity`/`top_k_similar`/`count_tokens`) + **fallback pur-Python** `core/native_fallback.py` (identic; `load_native()` preferă extensia compilată, altfel Python → comportament identic cu/fără build). +4 teste offline pe fallback. ⚠️ **Crate-ul Rust = build host (`maturin`), netestat în CI.** | 21 | P3 | H7 | OpenJarvis (14 crates) |
| H11.3 ✅ | **SFT/GRPO Training Pipeline** — fine-tuning local pe modele (SFT + GRPO) din trace-urile colectate; necesită GPU. Closing the loop pe Learning Loop (H7.11). **Done 2026-06-09 (sursă + data-prep testat):** `training/prepare_data.py` (trace→SFT JSONL ShareGPT-style, filtru pe scor — **pur-Python, testabil**, +3 teste) + `training/sft_grpo.py` (pipeline SFT/GRPO HF `trl`/`transformers`, importuri guarded) + README. ⚠️ **Antrenarea = GPU host, nu rulează în CI.** | 13 | P3 | H7.11 | OpenJarvis |
| H11.4 ✅ | **WASM Sandbox (wasmtime)** — backend de execuție WASM pentru sandbox, complementar Docker; izolare mai bună și portabilă, fără daemon Docker. `core/sandbox.py` (backend nou). **Done 2026-06-09 (backend + fallback grațios):** `Sandbox` câștigă un backend wasmtime — detecție (`_check_wasmtime`), `wasm_available()` (cere binarul + un runtime Python‑WASM configurat via `JARVIS_WASM_PYTHON`), prioritate **Docker→WASM→subprocess**, și **fallback grațios** (binar lipsă la execuție → revine la subprocess, fără regresie pe căile existente). `_build_wasm_command` pur/testabil. +7 teste offline (detecție, selecție backend, fallback la binar lipsă, comportament existent păstrat). *(Execuția WASM reală = poartă host: wasmtime + `python.wasm`.)* | 8 | P3 | — | OpenJarvis (wasmtime) |

---

## ORIZONT 12 — Categoria Reală: Asistent Personal Privat & Proactiv (P0–P3) — 23/25

> Bazat pe research-ul din [docs/research/2026-06-02-personal-ai-competitors.md](docs/research/2026-06-02-personal-ai-competitors.md):
> H10 a comparat Jarvis cu 8 **framework-uri de developeri**; categoria reală a moonshot-ului (asistent
> personal, proactiv, privat) nu fusese niciodată analizată. Idei derivate din competitorii **reali**
> (OpenClaw, Khoj, Leon, Omi, Bee, Pieces, Home Assistant, Jan, Tana) — fiecare verificată față de
> [principiile non-negociabile](MOONSHOT.md#5-non-negotiable-principles-the-guardrails).
>
> **Wedge-ul defensiv:** OpenClaw (rivalul direct viral) a eșuat exact unde Jarvis e puternic — secrete în
> plaintext, fără guvernanță acțiuni, marketplace nemoderat → ținta #1 a infostealerelor. Jarvis = alternativa guvernată.

### Track A — Securitate ca Diferențiator (P0, anti-OpenClaw)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.1 ✅ | **Securitate ca feature de prim rang** — criptează secretele at-rest (fără `SOUL`/memory în plaintext), skills semnate + sandboxed, expune coada de aprobare reversibil/ireversibil ca "povestea anti-OpenClaw". Pachetizează guardrails + PII scanner + sandbox existente. **Done 2026-06-02:** `core/secrets.py` `SecretStore` (Fernet + key-derivation PBKDF2/keyfile 0600, fallback HMAC-XOR pur-Python, get/set/delete + `migrate_plaintext`); `core/skills/signing.py` + loader extins (verificare `SKILL.sig`, advisory by-default, `JARVIS_REQUIRE_SIGNED_SKILLS=1` → modul untrusted nu se exec in-process; skills auto-generate auto-semnate); 2 endpoints noi `GET /autonomy/approvals` (bucket reversibil/ireversibil pe risk tier) + `GET /api/security/posture` (pachetizează secrets+signing+sandbox+guardrails). +31 teste offline. | 8 | **P0** | H6.2, Sec | OpenClaw (eșecuri) |

### Track B — Memorie & Onboarding (P1)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.2 ✅ | **Onboarding "drop folder → chat privat cu documentele"** — alegi un folder pre-configurat, Jarvis îl indexează local (PDF/MD/docx) și poți discuta cu el offline. **Done 2026-06-03:** `core/local_docs.py` `LocalDocsIndexer` (walk recursiv, extract md/txt/rst nativ + pdf/docx best-effort cu skip grațios, chunking word-window cu overlap → `memory.remember` local, fără cloud); endpoint **select-by-key** `POST /api/local-docs/index {key}` (folderul vine din config `local_docs.folders`, **niciun path din request** → fără path-injection) + `GET /api/local-docs` (sumar + chei disponibile). +5 teste offline. | 3 | P1 | H8.3 | GPT4All LocalDocs, Khoj |
| H12.3 ✅ | **KG interogabil & editabil (UX)** — graful de cunoștințe ca suprafață de prim rang: vizualizează, caută, editează, șterge entități/relații. **Done 2026-06-03:** `KnowledgeGraph` extins cu `list_entities`/`delete_entity` (DETACH + curăță relațiile)/`delete_relation` în ambele backend-uri (InMemory + Neo4j); endpoints `GET /api/kg/entities?q=&limit=`, `GET /api/kg/entities/{name}` (+relations), `POST /api/kg/entities` (upsert), `DELETE /api/kg/entities/{name}`, `POST /api/kg/relations`, `DELETE /api/kg/relations`. Implementează "inspectable & forgettable" (H8.2). +4 teste offline. | 8 | P1 | H8.2 | Tana supertags |
| H12.4 ✅ | **Suport protocol Wyoming** — Jarvis vorbește Wyoming → interoperează cu sateliți Voice PE ($59) și ecosistemul vocal local Home Assistant; decuplează STT/TTS/wake. **Done 2026-06-03:** `core/voice/wyoming.py` — framing wire pe format de referință (header JSON + payload length-prefixed), `encode_event`/`read_event`, `WyomingServer` rutează `describe`→`info`, `transcript`→handler→`synthesize`, `ping`→`pong`; `serve()` TCP (port 10700) + `handle_connection`; endpoint status `GET /api/voice/wyoming` (gated `voice.wyoming_enabled`). +11 teste offline. | 5 | P1 | — | Home Assistant, Rhasspy |

### Track C — Proactivitate & Observabilitate (P2)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.5 ✅ | **Preview / dry-run pentru autonomie** — arată ce *ar* face o acțiune înainte de aprobare; nicio acțiune oarbă. **Done 2026-06-03:** `core/autonomy/dry_run.py` `preview_task` — extrage kind/title/target/effects din payload, clasifică ireversibilitatea (reutilizează H17.1 `QuarantinePolicy` + tokeni send/delete/transfer…), `requires_approval` (ireversibil sau risc tier≤2), `would_execute=False`; integrat în `build_decision_card` (linie _Preview:_) + endpoints `POST /api/autonomy/preview` + `GET /api/autonomy/tasks/{id}/preview`. +6 teste offline. | 5 | P2 | H6.2 | Dust config preview |
| H12.6 ✅ | **Update-uri KG incrementale (nu doar nocturne)** — extracție ușoară de triple per-tură ca memoria să apară în aceeași sesiune. **Done 2026-06-03:** `core/memory/incremental.py` — `extract_triples` (pattern-uri high-precision: posesiv „X's Y is Z", lives_in/works_at/related_to verbe, copula is_a; sare stopwords + self-refs), `IncrementalKGUpdater.ingest` scrie entități+relații în KnowledgeGraph live + fapte în bi-temporal (H14.1, contradicție→invalidează); hook în orchestrator `_record_interactions` + endpoint `POST /api/kg/ingest`. Calea nocturnă LLM rămâne high-recall. +8 teste offline. | 5 | P2 | H5.15, H8.1 | Mem, Tana |
| H12.7 ✅ | **Captură pasivă multi-suprafață (opt-in, local)** — browser/clipboard/fișiere → KG, doar local. ⚠️ STRICT opt-in + inspectabil; nimic nu pleacă de pe mașină. **Done 2026-06-09:** `core/passive_capture.py` `PassiveCapture` — **dublu opt-in** (master `JARVIS_PASSIVE_CAPTURE` + per-suprafață, default OFF → nimic capturat), **local-only** (fără rețea; KG + store on-disk bounded), **secrete redactate înainte de stocare** (`SecretScanner.redact` → cheie copiată în clipboard nu se persistă niciodată), ingestie în KG-ul incremental (H12.6) pe text redactat, **inspectabil + forgettable** (`list`/`get`/`forget`/`clear`). Înregistrat lazy; 6 endpoints (`/api/capture/status|ingest|surfaces`, `GET /api/capture`, `DELETE /{id}`, `/clear`). +11 teste offline. *(Hook-urile OS clipboard/browser/file = seam host-side care apelează `ingest`.)* | 8 | P2 | H8.1 | Pieces nanomodels, Omi |
| H12.8 ✅ | **Split sateliți-mic → server-inferență pe GPU-ul de acasă** — mai multe endpoint-uri ieftine de microfon partajează un singur GPU Jarvis. **Done 2026-06-09:** `core/satellite_hub.py` `SatelliteHub` — registru de sateliți (allowlist explicit) + `dispatch` care rutează STT/inferența la un **backend de inferență partajat injectabil** (`NullInference` offline default), **serializat printr-un semafor** ce modelează contenția unui singur GPU (`max_concurrency=1` → niciodată concurent; testat). Accounting per‑satelit + `stats`/`peak_inflight`. Endpoints `GET /api/satellites`, `POST /register`, `DELETE /{id}`, `POST /{id}/dispatch`. +8 teste offline (registru, dispatch, serializare GPU, eroare inferență, stats). *(Backendul real Wyoming/LM‑Studio = poartă host.)* | 8 | P2 | H12.4 | Willow (WIS) |
| H12.9 ✅ | **UX management modele locale** — răsfoiește/descarcă/comută modele dintr-un click în HUD. | 5 | P2 | — | Jan.ai |
| H12.10 ✅ | **Indicator mute hardware / strict-local** — semnal vizibil, auditabil "mic off / strict-local" în HUD + voce. Semnal de încredere ieftin. | 2 | P2 | — | Voice PE (mute fizic) |
| H12.11 ✅ | **Canale de escaladare extinse** (dincolo de Telegram: WhatsApp/Signal/Slack/Discord) — *guvernate*. **Done 2026-06-03:** `core/autonomy/escalation.py` `EscalationRouter` — fan-out la adaptoarele de canal existente, *guvernat* prin allowlist (`autonomy.escalation_channels`), best-effort (nu aruncă), `targets()` rezolvă available∩requested∩allow; `render_escalation` mesaj plain channel-agnostic (cu preview H12.5); endpoints `GET /api/autonomy/escalation/targets` + admin `POST /api/autonomy/escalate` (mesaj sau task). +7 teste offline. | 3 | P2 | H1.3 | OpenClaw (multi-channel) |

### Track D — Platformă & Ecosistem (P3)

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.12 ✅ | **Marketplace de skills curat & semnat** (anti-ClawHub moderat) — extinde skills importer cu semnături + review. **Done:** `marketplace.py` — **poartă de review** (`review_status` pending/approved/rejected; publish→pending; `approve/reject/set_review_status`; install blocat dacă nu-i approved sub `JARVIS_REQUIRE_REVIEWED_SKILLS`), **semnătură** la publish (`signing.sign_skill`) + verificare la install (refuz sub `JARVIS_REQUIRE_SIGNED_SKILLS`), și **fix zip-slip** (path-traversal blocat înainte de extract — vuln reală în `extractall`). Endpoint `POST /api/skills/marketplace/review`; gate-urile opt-in (default backward-compatible), zip-slip mereu blocat. 0.45 B1 branch adds `SKILL_INSTALL_CONTRACT` for publish/install/uninstall plus `SKILL_GENERATION_CONTRACT` for LLM-authored skill creation/promotion before any package or generated code becomes executable. +14 teste offline total across original marketplace governance and B1. | 8 | P3 | Skills | OpenClaw ClawHub (sigur) |
| H12.13 ✅ | **Sync E2E opt-in între device-uri** (GPU acasă ↔ telefon) — ⚠️ obligatoriu E2E + opt-in; nu sparge local-first. **Done 2026-06-09 (E2E real, fail‑closed):** `core/e2e_sync.py` `E2ESync` — plic E2E cu **Fernet real** (`cryptography`, AES‑128‑CBC+HMAC autentificat → tamper/cheie greșită **detectate**, nu acceptate tacit), cheie derivată dintr‑un **passphrase partajat** (PBKDF2‑SHA256 390k, salt fix → două device‑uri cu același passphrase derivă aceeași cheie) sau cheie Fernet; **opt‑in** (`JARVIS_E2E_SYNC`) și **fail‑closed** (fără cripto/secret → dezactivat, **fără fallback slab**). `encrypt_record`/`decrypt_record` (plaintextul nu părăsește niciodată device‑ul), `build_push`/`apply_pull` (manifest cu digest; sare propriul device + intrările neverificabile). Endpoints `GET /api/sync`, `POST /api/sync/push|pull`. +12 teste offline (round‑trip, tamper, cheie greșită, cross‑device, opt‑in, fail‑closed). *(Transportul device‑la‑device = poartă host.)* | 13 | P3 | — | Reflect / Limitless |
| H12.14 | **Model agentic mic, fine-tuned** (task-uri router/tool) — overlap cu H11.3 (pipeline SFT/GRPO); $0 COGS. **🖥️ GPU host — runbook turnkey: `docs/GPU_RUNBOOK.md`** (pipeline + `prepare_data` citește direct `memory_logs/learning/*.jsonl`). | 8 | P3 | H11.3 | Jan-nano |
| H12.15 ✅ | **Backup & restore date personale** — `agents/data/` + `memory_logs/` (memoria H8, sesiuni, workflow-uri create, corpus ingerat) sunt **singura stare cu date reale și sunt git-ignored** → fără asta, pierdere totală la orice `clean`/reinstalare (incidentul 2026-06-02). **Done 2026-06-02:** `scripts/backup-data.sh` + `scripts/backup-data.ps1` — arhivă timestamped (tar.gz / zip), restore cu confirmare, retenție ultimele 14, override `BACKUP_DIR` (drive extern/cloud); `backups/` gitignored; păstrează local-first (opt-in cloud). *(Schedule automat = opțional, neimplementat.)* | 3 | P2 | H8.2 | durabilitate local-first |

### Track E — Paritate guvernată cu OpenClaw (post‑research 2026‑06‑05) (P2–P3)

> Funcționalități adoptate din OpenClaw (`github.com/openclaw/openclaw`, ~377k★) **doar sub guvernanță** —
> închid decalajul de *reach/UX* fără să atingă vreun non‑negociabil. Analiză completă:
> [docs/research/2026-06-05-openclaw-feature-analysis.md](docs/research/2026-06-05-openclaw-feature-analysis.md).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H12.16 ✅ | **Lărgire canale** (WhatsApp nativ / Signal / iMessage / Matrix / Teams / Google Chat …) pe gateway‑ul *guvernat* (rate‑limit + guardrails + allowlist se aplică). OpenClaw are ~23 canale; noi avem 6. **Done 2026-06-09:** `core/channels/webhook_channels.py` — familie de adaptoare HTTP/webhook (`WhatsApp`/`Signal`/`Matrix`/`Teams`/`GoogleChat`) pe **același gateway guvernat**: fiecare inbound trece `sender` → **poarta de pairing H12.19 + rate‑limit + guardrails se aplică** înainte de orchestrator; outbound prin **transport injectabil** (offline-testable, rețeaua reală = poartă host). Per‑provider doar 2 funcții pure: `build_send` (mesaj→request HTTP) + `parse_inbound` (payload→`text,sender`). Factory `build_channel`/`channels_from_config`; wiring în lifespan via `JARVIS_WEBHOOK_CHANNELS` (default‑off); endpoints `GET /api/channels/webhook` + `POST /api/channels/{id}/inbound`. **iMessage exclus deliberat** (macOS/host‑bound, fără suprafață HTTP curată → bridge host, nu acest strat). 6→11 canale. +18 teste offline (build_send/parse_inbound per provider, send via transport mock, inbound guvernat de pairing). | 5 | P2 | H1.3 | OpenClaw multi‑channel |
| H12.17 ✅ | **Node mesh guvernat** — telefon/desktop ca *noduri de execuție* care rulează doar acțiuni capability‑scoped + aprobate; GPU‑ul de acasă rămâne creierul. Unifică Tauri (H11.1) + split sateliți (H12.8). **Done 2026-06-09 (strat de guvernanță pe H17.3):** `core/node_mesh.py` `NodeMesh` — `register_node` mintează un **token capability‑scoped** (H17.3 `CapabilityBroker` — tokenuri read‑only, nodul **nu poate escalada**, primește doar capabilitățile declarate); `dispatch` **autorizează** (kill‑switch + capabilitate via `authorize()`) apoi enqueue **task ask‑tier** (`kind=node.dispatch`) — nimic nu rulează pe nod până la aprobare; `execute` **re‑autorizează la momentul acțiunii** (token expirat/revocat sau kill‑switch → blocat) și predă nodului (rularea on‑device = poartă host). Endpoints `GET /api/nodes`, `POST /register` (admin), `DELETE /{id}` (admin), `POST /{id}/dispatch`. +9 teste offline (token mint, dispatch în/în afara capabilității, kill‑switch, revoke, re‑auth la execute, e2e). *(Clientul Tauri/telefon = poartă host.)* | 13 | P3 | H11.1, H17.3 | OpenClaw „nodes" / Willow |
| H12.18 ✅ | **Agent Canvas / A2UI** — spațiu vizual condus de agent în HUD (inspectabil + guvernat), peste network brain‑ul v2. **Done 2026-06-09 (backend guvernat):** `core/canvas.py` `CanvasStore` — agentul postează DOAR elemente tipizate known‑safe (`text/markdown/list/link/metric/table/image_ref`), fiecare **sanitizat** (whitelist câmpuri + bound lungime/count, URL doar `http(s)`/same‑origin → **niciun HTML/script brut**, disciplina „validate down to known‑safe" din AI builder); atribuit pe agent, inspectabil, `pin`/`remove`/`clear` (pinned păstrat), bounded+evict. Înregistrat în `ComponentRegistry`; 5 endpoints (`GET /api/canvas`, `POST /api/canvas/post` 422 pe tip necunoscut, `/{id}/pin`, `DELETE /{id}`, `/clear`). +12 teste offline. **Frontend livrat 2026-07-10 (#652):** tab **Artifacts** în cockpit (lângă Conversation/Cognition) — listă `GET /api/canvas` cu redare sigură pe toate cele 7 tipuri (React text-nodes, fără `dangerouslySetInnerHTML`/iframe; imagini remote doar după consent-click cu `referrerPolicy="no-referrer"`), pin/unpin/delete pe endpoint-urile existente, stări oneste loading/empty/error/refresh + **salvare explicită a unui răspuns** (control per-mesaj: doar replici complete non-system, trunchiere vizibilă la 4.000, niciodată auto-save). Bonus hardening din review-ul adversarial: `_safe_url` respinge URL-uri protocol-relative + control-chars (TAB/LF/CR), `_s()` aruncă surogate UTF-16 neîmperecheate (anti-poisoning la scriere UTF-8), iar forget-me resetează `canvas.json` + curăță store-ul live **fără** să golească fișierul înaintea backup-ului pre-forget. +8 teste backend, +21 vitest. **Follow-up 2026-07-11:** minor UX gap închis — `SaveArtifactButton` reține starea „saved" per-mesaj într-un `WeakSet` module-level (identitate de obiect stabilă în `messages`), deci la schimbarea tab-ului central + revenire nu mai oferă un al doilea save care ar dubla elementul (+1 vitest, 208 total). **Wave 2 (binary artifacts: upload/stream image/audio/video/PDF) = H12.26** — slice separat, guvernat. | 8 | P3 | HUD v2 | OpenClaw Live Canvas |
| H12.19 ✅ | **Pairing/aprobare expeditor inbound** — senderi necunoscuți pe canale trec printr‑un cod/aprobare (anti‑abuz); oglindă a allowlist‑ului A2A. **Done 2026-06-09:** `core/channels/pairing.py` `SenderPairing` (JsonStore keyed `(channel,sender)`) — **opt‑in** (`JARVIS_CHANNEL_PAIRING`, default OFF → `is_allowed` True pentru toți, comportament neschimbat); sender necunoscut → `pending` (**held, niciodată executat**, ca inboxul A2A), owner approve/reject/block/unpair; **cod self‑service** rotativ (auto‑approve la cod corect, `hmac.compare_digest`); **anti‑abuz** (rate‑limit per `(channel,sender)` + pending bounded + evict). Gate cablat în `Gateway.route` (kwarg `sender`, backward‑compatible) + threading `sender` din Telegram; înregistrat în `ComponentRegistry`; 4 endpoints (`POST /api/channels/pairing/request` gated‑404, `GET /api/channels/pairing` + `POST /decide` + `POST /code` admin). +20 teste offline. | 3 | P2 | H1.3, H16.2 | OpenClaw DM pairing |
| H12.20 ✅ | **Rotație profile auth + failover model** în hybrid router (mai multe chei/conturi cu failover). **Done 2026-06-09:** `core/llm/auth_rotation.py` `AuthProfilePool` — chei multiple per provider (din `*_API_KEYS` comma/space, fallback la `*_API_KEY` single → **backward-compatible**); eroare rotabilă (401/403/429) → failover la următoarea cheie sănătoasă, cheia picată intră în **cooldown exponențial** (cap 15 min), `report_success` resetează; clock injectabil (cooldown determinist în teste). Cablat în `ClaudeBackend`/`GeminiBackend` (cheia din pool + retry-and-rotate pe `generate`, report_failure pe stream) și construit din env în `HybridRouter.detect()`; endpoint admin `GET /api/llm/auth-profiles` (status mascat). +18 teste offline. | 3 | P3 | H2.12 | OpenClaw auth rotation |
| H12.21 ✅ | **Acțiuni guvernate pe social** (X/Twitter post/reply/DM) — fiecare *write* prin coada de aprobare; auth OAuth/secret‑broker (nu cookie‑uri brute). **Done 2026-06-09:** `core/social.py` `SocialBroker` — paralel cu write-back (H10.30): request → validare allowlist (x: post/reply/dm) + sanitizare → **task ask-tier** (`kind=social.x.<action>`, tier extern); **nimic nu se postează la request**. Pe aprobare, executor prefix `social` → `SocialBroker.execute` rezolvă tokenul OAuth/bearer **la momentul acțiunii, în spatele aprobării** (SecretBroker — handle `{{secret:x_api_token}}`, niciodată cookie-uri) și apelează client injectabil (`NullSocialClient` offline default; `HttpSocialClient` = rail live prin `build_social_request` pur → X API v2 `/2/tweets`, reply, `/2/dm_conversations`). Endpoints `GET/POST /api/integrations/social`. +15 teste offline (catalog, validare, build_request post/reply/dm, execute behind-approval, e2e prin coadă+worker). *(Apelul de rețea real = poartă host.)* | 5 | P3 | H6.2 | OpenClaw TweetClaw/Bird |
| H12.22 ✅ | **Voce outbound / call‑back** — agentul sună la prag + persona vocală izolată (Twilio/Telnyx), gated prin interrupt‑budget. **Done 2026-06-09:** `core/autonomy/call_broker.py` `CallBroker` — apel outbound gated **dublu**: coada de aprobare (`kind=call.outbound`, ask‑tier extern) ȘI **bugetul zilnic de întreruperi** (un apel e o întrerupere → consumă din ≤4/zi). Pe aprobare rezolvă tokenul telephony **în spatele aprobării** (SecretBroker — handle `{{secret:…}}`) și sună prin client injectabil (`NullCallClient` offline default; `HttpCallClient` = rail Twilio/Telnyx prin `build_call_request` pur — Twilio form+basic‑auth, Telnyx JSON+bearer). Endpoint `POST /api/autonomy/call`. +15 teste offline (validare, buget epuizat, build per provider, execute behind‑approval, e2e prin coadă+worker). *(Apelul telefonic real = poartă host.)* | 8 | P3 | H6.2 | OpenClaw SuperCall |
| H12.23 ✅ | **Pack de skill‑uri „digest"** (news multi‑sursă ponderat, earnings, Reddit/YouTube/arXiv/HF, idea‑reality scorer) — skill‑uri semnate, compozabile. **Done 2026-06-09:** `core/digest.py` — motor compozabil: `DigestSource` (feed RSS/Atom ponderat, `{topic}` URL‑encoded, **fetch injectabil** → offline), `parse_feed` (RSS `<item>` + Atom `<entry>`, namespace‑stripped, safe pe XML rupt), `idea_reality_score` (substanță: release/benchmark/paper/code/versiune/% vs hype: revolutionary/breakthrough/shocking → 0..1), `DigestAggregator.run` (dedup pe link/title, rank pe `weight × (0.5+reality)`), `build_default_aggregator` peste 5 template‑uri (hn/reddit/arxiv/youtube/news). Endpoint `POST /api/digest/run` (user‑guard, fetch via `PluginHTTPClient`). +11 teste offline. *(Live multi‑sursă + împachetare ca skill‑uri semnate = follow‑up extern.)* | 5 | P3 | Skills | awesome‑openclaw‑usecases |
| H12.24 ✅ | **Generare media** (imagini/thumbnail/video, local sau cloud‑gated) pentru content‑factory. **Done 2026-06-09:** `core/media_gen.py` `MediaGenManager` — generare media (image/thumbnail/video) prin **backend-uri injectabile**: local inline, **cloud gated** prin coada de aprobare (apel plătit niciodată neprompt). Endpoints `GET /api/media`, `POST /api/media/generate`. +5 teste offline. *(Backend-urile diffusion/cloud reale = host.)* | 5 | P3 | — | OpenClaw content skills |
| H12.25 ✅ | **Transcript‑watcher → taskuri** (notițe ședință → Notion/Todoist prin coada de aprobare). **Done 2026-06-09:** `core/autonomy/transcript_watcher.py` — `extract_action_items` (high‑precision: checkbox-uri, prefixe `action item:/todo:/next step:`, assignment `<Nume> will/to <verb>` cu atribuire owner; dedup + min‑length, fără false positives pe discuție) + `TranscriptWatcher.ingest` care enqueue fiecare item ca task **ask‑tier guvernat** (`kind=create_task`, `autonomy_level="ask"`, payload cu `system=notion\|todoist`) → **nimic nu se creează extern fără aprobare**; fără coadă = preview-only. Endpoint `POST /api/transcripts/ingest` (user‑guard). +10 teste offline. *(Crearea live în Notion/Todoist la aprobare = executor downstream / poartă externă.)* | 3 | P2 | H2.7 | OpenClaw meeting‑notes |
| H12.26 ⬜ | **Binary artifact store (visual-artifact lane wave 2)** — let the user attach/upload a **bounded, validated** binary artifact (image/audio/video/PDF/doc) and browse/stream/delete it from the existing Artifacts workspace, over the same governance discipline as the text Canvas (default-off, attributed, inspectable, purgeable). Deliberately held out of wave 1 (H12.18/H18.20 shipped the safe **text** substrate only) because binaries are a larger surface: **every one of these contracts must land in the slice** — (1) **MIME validation** by magic-bytes allowlist (never extension/client type; active types like html/svg/scripts never allowed), (2) **authenticated delivery** (a `user_guard`'d blob route that resolves an opaque id server-side and never exposes the host path — same rule wave 1 kept for `MediaCatalog.path`), (3) **quotas** (byte + count caps, oldest-unpinned evicted, single-upload size cap pre-disk), (4) **retention** (H23.10 sweep-actionable TTL default), (5) **export** (join the H23.9/#303 data-export bundle), (6) **purge/forget** (join the forget-me flow like `canvas.json` — delete blobs + clear the live index before the pre-forget backup, reusing the `clear_memory(persist=False)` pattern). Should reconcile its blob-delivery + purge/export surfaces with **0.46 Media Library** (generated media) rather than growing two. **Design spec:** [`docs/superpowers/specs/2026-07-11-artifact-store-wave2.md`](docs/superpowers/specs/2026-07-11-artifact-store-wave2.md). *(Not started — reviewed slice; new `artifact_store.py` + per-domain router + route/OpenAPI/auth snapshot reseed.)* | 8 | P3 | H12.18 | visual-artifact lane wave 2 |

> **Total ORIZONT 12:** 26 items (25 done + H12.26 open), ~158 SP. **Acțiune imediată recomandată:** H12.1 (P0) — e simultan hardening real
> ȘI wedge-ul de marketing (alternativa securizată la OpenClaw). Restul Track B (P1) ridică cel mai mult valoarea per efort.

---

## ORIZONT 13–17 — Frontiere Noi (post-paritate, în scope v1.0) — 14/20

> **Status: livrate** (toate în v0.10.0). Drumul până la 1.0 e productionizarea (**H23**) + validarea cu useri reali —
> **1.0 = totul livrat + design partners**, fără grabă pe tag. Bazat pe research-ul frontieră 2025-2026:
> [docs/research/2026-06-03-frontier-horizons.md](docs/research/2026-06-03-frontier-horizons.md) (5 agenți paraleli +
> verificare independentă). Backlogul de features e terminat (H1–H9); H10–H12 sunt paritate competitivă.
> **Acestea sunt direcțiile de DUPĂ paritate** — unde țintește un OS personal local-first/proactiv/privat.
> Fiecare item verificat față de [principiile non-negociabile](MOONSHOT.md#5-non-negotiable-principles-the-guardrails).
>
> **Două teme-flagship (apar transversal):** (1) **„sleep-time compute"** — chiar sloganul moonshot (*„lucrează cât dormi"*),
> acum rezultat de cercetare (arXiv:2504.13171): generalizează reflecția nocturnă din *rezumă-ziua* în *pre-raționează-pentru-mâine*
> pe GPU-ul idle. (2) **Guvernanță măsurabilă** — convertește „suntem alternativa guvernată la OpenClaw" dintr-un *claim* într-un
> *badge CI verde* (AgentDojo). OpenClaw a devenit prima țintă infostealer (13-feb-2026) — anti-teza dovedită.

### ORIZONT 13 — Plafonul de Capabilitate Locală (modele & inferență) — 3/4

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H13.1 ✅ | **Tier VLM strict-local** (Qwen3-VL-8B) — înțelegere ecran/documente/bonuri/PDF → alimentează pipeline-ul Howard; cea mai mare capabilitate *nouă*, fără cloud. ⚠️ verifică build GGUF + buget KV-cache pe 24GB. **Done 2026-06-09 (strat de integrare):** `core/llm/vlm.py` `VLMBackend` — adapter **OpenAI-vision-compat** (mesaje cu `image_url`), preprocesare imagini pură (`to_data_uri` base64, `_downscale` opțional Pillow pt. bugetul KV-cache, `encode_image_block` bytes/path/url/data-uri), `generate_vision` (alimentează pipeline-ul Howard) + `generate` text-only (contract LLMBackend); client injectabil → offline-testable ca adaptorul OpenRouter. Endpoints `GET /api/vlm/status`, `POST /api/vlm/describe` (gated pe `JARVIS_VLM_URL`). +7 teste offline. *(Modelul local — weights + GGUF + GPU 24GB — = pas de deployment host: pointează `JARVIS_VLM_URL` la un server vision local vLLM/llama.cpp.)* | 8 | P1 | H5.1 | Qwen3-VL (Oct 2025) |
| H13.2 ✅ | **Decodare constrânsă (GBNF) pentru tool-calling** — garantează tool-args valide. **Done 2026-06-03:** `core/llm/grammar.py` — `json_schema_to_gbnf`/`tool_to_gbnf` generează gramatică GBNF llama.cpp din JSON schema (object cu chei ordonate, string/integer/number/boolean/array/enum/nested object; cluster permisiv value/object/array pentru tipuri nedeclarate) + `validate_args` fallback (tipuri/required/enum, pentru backend-uri fără gramatică); endpoint `POST /api/llm/grammar`. *Generarea gramaticii + validarea sunt complete; enforcement-ul rămâne hook-ul backend-ului (param `grammar=` llama.cpp/XGrammar).* +10 teste offline. | 5 | P1 | — | XGrammar / llama.cpp |
| H13.3 | **Speculative decoding** (draft Qwen3-4B → target 32B/gpt-oss) — 1.5-2.5× throughput interactiv, output identic, $0. **🖥️ GPU host — runbook: `docs/GPU_RUNBOOK.md`** (config vLLM/llama.cpp; zero cod aplicație, output-identic). | 5 | P2 | — | vLLM / llama.cpp |
| H13.4 ✅ | **Refresh model default → MoE cu reasoning hibrid** (gpt-oss-20b / Qwen3-30B-A3B) — mod thinking/non-thinking poate colapsa tier-urile fast/deep într-un model. Apache-2.0. **Done 2026-06-09:** `core/llm/moe_routing.py` — `decide_thinking_mode` (euristic: hint-uri raționament/lungime/multi-întrebare) + `route_moe` (model MoE → mod thinking/non-thinking, buget tokeni, directivă `/think`÷`/no_think`; colapsează tier-urile fast/deep). Endpoint `POST /api/llm/moe/route`. +5 teste offline. *(Selecția backendului real în HybridRouter = host.)* | 5 | P2 | — | gpt-oss, Qwen3 |

### ORIZONT 14 — Memorie Vie (memorie temporală & auto-întreținută) — 4/4 ✅

> Extinde H8 (memorie personală, livrat). Rulează pe Neo4j + Ollama existente; majoritatea Apache-2.0.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H14.1 ✅ | **KG bi-temporal** (Graphiti-style: valid-time + ingested-at; contradicție → *invalidează*, nu șterge; recall „as-of"). **Done 2026-06-03:** `core/memory/bitemporal.py` `BiTemporalKG` (JSON file-backed) — triple-uri (subject,predicate,object) cu `valid_from`/`valid_to`/`ingested_at`/`invalidated_at`; `add_fact` (predicat single-valued → închide factul contradictoriu la noul `valid_from`, păstrează istoricul; `multi=True` pentru predicate multi-valued), `invalidate` explicit, `as_of` (valid-time recall), `known_as_of` (transaction-time), `current`, `history`; endpoints `POST /api/kg/facts`, `GET /api/kg/facts/as-of`, `GET /api/kg/facts/history`. +7 teste offline. | 8 | P1 | H3.2, H8.2 | Graphiti/Zep |
| H14.2 ✅ | **Harness de eval pentru memorie** (LongMemEval/LoCoMo-style pe corpus propriu; 5 abilități: extracție, multi-sesiune, temporal, update, abținere). **Done 2026-06-03:** `core/memory/eval.py` — `MemoryEvalCase` + `DEFAULT_CORPUS` (corpus propriu acoperind toate cele 5 abilități), `score_answer` (substring any-of; abținerea = răspuns corect e „nu știu", halucinația pică), `keyword_answer` baseline offline (overlap + recency tiebreak), `run_eval(answer_fn)` → scor per-abilitate + overall (answer-fn-agnostic: pipeline real în prod, fake în teste); endpoints `GET /api/memory/eval/corpus` + `POST /api/memory/eval/run` (baseline). +10 teste offline. | 5 | P1 | H8.2 | LongMemEval |
| H14.3 ✅ | **Agent de consolidare „sleep-time" cu operații explicite** (Mem0-style ADD/UPDATE/DELETE/NOOP). **Done 2026-06-03:** `core/memory/consolidation.py` `ConsolidationEngine` — `decide`/`plan` per candidat vs memorii existente: ADD (nou), UPDATE (supersede same-key/near-duplicate), DELETE (negație/retractare detectată + match), NOOP (duplicat); similaritate Jaccard token (prag configurabil), detector de negație, decider LLM injectabil (fallback euristic); `plan` batch-aware (copie de lucru), `summarize`, `apply` la un store; endpoint `POST /api/memory/consolidate` (plan reversibil, fără mutație). +10 teste offline. | 8 | P2 | H5.15 | Mem0, Letta |
| H14.4 ✅ | **Uitare cu decay + dependency-aware** (scor activare ACT-R în ranking + ștergere pe graf de dependențe care previne „recontaminarea"). **Done 2026-06-03:** `core/memory/decay.py` — `activation` base-level ACT-R `ln(Σ (now-t)^-d)` (recency+frecvență), `DecayMemory` (JSON file-backed) cu `add`/`access`/`score`/`ranking`/`forget_candidates(threshold)` + `forget` care șterge itemul *și dependenții tranzitivi* (anti-recontaminare); endpoints `GET /api/memory/decay/ranking`, `/candidates`, `POST /api/memory/decay/forget`. +6 teste offline. | 5 | P2 | H8.2 | ACT-R, arXiv:2602.17692 |

### ORIZONT 15 — Computer-Use Guvernat (operează mașina) — 4/4 ✅

> Inversul *guvernat* al shell-ului neguvernat OpenClaw. Maturitate onestă: ~1-din-6 task fail → asistă în spatele approval-queue, NU nesupravegheat.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H15.1 ✅ | **Agent browser-use local** în spatele approval-queue + sandbox + egress allowlist (browser-use/Playwright-MCP + LLM local). Punct de intrare cu cel mai mic risc. **Done 2026-06-09 (strat guvernat):** `core/browser_agent.py` — 3 porți compozabile: **egress allowlist** (`BrowserPolicy`, suffix‑match + filtrul SSRF HF‑4 → navigare off‑listă **hard‑blocked**, neaprobabilă; fail‑closed pe listă goală), **approval‑queue** (pași read‑only `navigate/extract/screenshot/wait` auto pe domeniu permis; pași mutanți `click/type/submit/download/execute_js` → `ActionApprovalQueue` H10.18 cu `await_decision`), **driver injectabil** (`NullBrowserDriver` default; Playwright real = add‑on host‑gated → stratul de guvernare e 100% offline‑testabil). `GovernedBrowser.preview` (dry‑run run/approve/block per pas) + `run` (trace, stop‑on‑block). Endpoints `POST /api/browser/check` (egress) + `/api/browser/plan/preview` (guvernanță). +12 teste offline. *(Driving real al browserului = poartă umană/host.)* | 8 | P2 | H4.8, H6.2 | browser-use (MIT) |
| H15.2 ✅ | **Modul de înțelegere a ecranului local** (grounding UI-TARS-1.5-7B, opțional fuzionat cu accessibility tree). ⚠️ OmniParser are componentă AGPL — preferă UI-TARS (Apache). **Done 2026-06-09:** `core/screen_grounding.py` — `parse_grounding` (JSON sau text `… at (x,y)`) + `fuse_with_a11y` (fuziune cu accessibility tree, dedup pe proximitate) + `locate` (element pe query). Construit pe adaptorul VLM H13.1. +5 teste offline. *(Modelul de grounding real = host.)* | 8 | P2 | H13.1 | UI-TARS, Agent S3 |
| H15.3 ✅ | **Operator în desktop virtual izolat (PiP)** — OS curat, fără credențiale ambientale; acțiuni ireversibile gated; clasificator de injection pe screenshots. Claude computer-use = opt-in cloud. **Done 2026-06-09 (strat de guvernanță):** `core/desktop_operator.py` `GovernedDesktop` — analog desktop al browser-agentului H15.1: read-only inline, mutant → aprobare (`approver` injectabil), **clasificator de injection** pe textul ecranului (reutilizează H17.1 → abort la injection); driver injectabil (`NullDesktopDriver` offline; VM real = host). `preview`/`run`. Endpoint `POST /api/desktop/preview`. +6 teste offline. | 13 | P3 | H15.1 | UFO², Anthropic |
| H15.4 ✅ | **Secret broker** — injectează credențiale la momentul acțiunii, în spatele aprobării; niciodată plaintext în contextul agentului. **Done 2026-06-03:** `core/security/secret_broker.py` `SecretBroker` (peste `SecretStore` criptat H12.1, fallback in-memory) — agentul vede doar handle-uri `{{secret:NAME}}` (`reference`), `inject(text, approved)` rezolvă valoarea DOAR cu aprobare (altfel placeholder, valoarea nu apare niciodată), `redact` maschează valori cunoscute (defense-in-depth), `names` fără valori; endpoints admin `POST/GET/DELETE /api/secrets/broker` + `/redact` (niciun endpoint nu întoarce plaintext). +7 teste offline. | 5 | P2 | H12.1 | OpenClaw (anti-teză) |

### ORIZONT 16 — Cetățean al Web-ului Agentic (interop & standarde) — 4/4 ✅

> Standardele s-au așezat: **MCP** (agent→tool) + **A2A** (agent→agent, la Linux Foundation). Plățile agentice au sosit (AP2/ACP/x402).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H16.1 ✅ | **MCP server mode** (spec 2025-11: OAuth2.1 RS, RFC 8707, `.well-known`) — **H10.5** upgradat. **Done 2026-06-03:** `core/mcp/oauth.py` `MCPResourceServer` — token-uri HMAC self-issued (LAN-only, fără IdP extern) + `validate` (semnătură constant-time, expirare, **RFC 8707 audience binding** la resursă, enforcement scope); `protected_resource_metadata` (RFC 9728) + `challenge` (`WWW-Authenticate`); endpoints `GET /.well-known/oauth-protected-resource`, admin `POST /api/mcp/token`, iar `/api/mcp/server/rpc` cere bearer valid când `mcp.oauth_required` (401 + challenge). +7 teste. *Enforcement-ul auth complet (validare token IdP extern) e un swap de backend de verificare.* | 8 | P1 | H4.7 | MCP 2025-11-25 |
| H16.2 ✅ | **Endpoint A2A** cu Agent Card semnat — opt-in, allowlist de peers, task-uri inbound → approval queue. **Done:** `core/a2a.py` `A2ARegistry` — **off by default** (`JARVIS_A2A_ENABLED`), Agent Card semnat HMAC (`JARVIS_A2A_KEY`, altfel advisory), **allowlist de peers** cu secret partajat (returnat o singură dată, mascat la list), `receive_task` verifică semnătura HMAC peste raw body (fail-closed: disabled/unknown-peer/bad-sig) și **nu execută niciodată** — task-ul aterizează în inbox `pending` pe care owner-ul îl aprobă/respinge. Endpoints: `GET /.well-known/agent-card`, `POST /api/a2a/task` (peer-signed), admin `peers`/`inbox`/`decide`/`card`. +8 teste offline. | 8 | P3 | H16.1 | A2A (Linux Foundation) |
| H16.3 ✅ | **Plăți agentice opt-in** prin abstracția mandate/cap/approval; plafoane *hard*; audit local non-repudiabil. **Done:** `core/payments.py` `PaymentBroker` — **mandate** cu plafon per-plată + plafon total + allowlist payee + monedă + expirare; fiecare plată e creată `pending` și **doar aprobarea explicită** o duce spre settle (fără auto-approve la nicio sumă); **plafoanele sunt absolute** (peste cap/payee nepermis/monedă greșită/expirat/peste total ⇒ *denied la creare*, nu devine niciodată pending); spend cumulativ nu poate depăși plafonul total (recheck la approve + settle); fiecare create/approve/reject/settle e scris în audit semnat (H17.4 IntentLog). **Rail-agnostic: niciun rail real, nu mișcă bani.** Endpoints admin `/api/payments/*`. +13 teste offline. | 8 | P3 | H6.2 | Google AP2, Stripe ACP |
| H16.4 ✅ | **Triggere ambientale inbound** (webhooks → inbox; **surse semnate**). Extinde **H10.8**. **Done 2026-06-03:** semnare HMAC pe `core/webhooks.py` — `create(signed=True)` provizionează `signing_secret` (returnat o singură dată, mascat în list), `compute_signature` (HMAC-SHA256 `sha256=<hex>`), `verify_signature` (constant-time, peste raw body; acceptă și hexdigest gol); endpoint trigger: hook semnat ⇒ cere header `X-Signature-256` valid (token-ul NU bypassează); hook nesemnat ⇒ token ca înainte. Sursă atestată criptografic (stil GitHub/Stripe). +6 teste (provizionare, verify ok/tamper/bad/empty, mascare, round-trip endpoint). | 5 | P2 | H10.8 | LangChain ambient agents |

### ORIZONT 17 — Încredere Demonstrabilă (siguranță pentru agenți always-on) — 4/4 ✅

> Cea mai on-mission pentru teza de încredere + wedge-ul anti-OpenClaw. Injection = nerezolvabil la nivel de model → **containment by-design + măsurare**.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H17.1 ✅ | **Quarantine Dual-LLM / Plan-Then-Execute** pentru conținut tool/web/email — date „tainted" nu ating tool ireversibil fără aprobare; spotlighting/datamarking ca primul strat. **Done 2026-06-03:** `core/security/quarantine.py` — `spotlight`/`datamark` (delimitatori + marker, prim strat) + `detect_injection` (pattern-uri „ignore previous", „you are now", system-prompt etc.); `TaintedValue` (trusted/from_untrusted), `QuarantinePolicy.check_step` (tainted→tool ireversibil ⇒ requires_approval), `plan_then_execute` (plan înghețat de PlanStep-uri tipizate, gate out-of-band `approve`, blochează exfiltrarea); endpoints `POST /api/security/spotlight` + `/scan-injection`. Rupe „lethal trifecta" prin construcție. +10 teste offline. | 13 | P1 | H4.9, H6.2 | CaMeL, arXiv:2506.08837 |
| H17.2 ✅ | **Eval-uri AgentDojo + AgentHarm ca poartă CI** („governance gate") + self-assessment OWASP Agentic Top 10 + „trust scorecard" public. **Done 2026-06-03:** `core/security/governance.py` — `INJECTION_SUITE` (AgentDojo-style, apărat de H17.1 `detect_injection`), `HARM_SUITE` (AgentHarm-style: refuză harmful + controale benigne anti-over-refusal), `OWASP_AGENTIC_TOP10` (10 riscuri → control acoperitor), `run_injection_evals`/`run_harm_evals`/`owasp_assessment`/`trust_scorecard`/`governance_gate(threshold)` (answer-fn-agnostic); endpoint `GET /api/security/governance`; testul `test_governance_gate_passes` E poarta CI. +10 teste offline. | 5 | P1 | H7.2 | AgentDojo, OWASP |
| H17.3 ✅ | **Capability gating + kill-switch out-of-band** pe care agentul NU îl poate escalada. **Done 2026-06-03:** `core/security/capability.py` — `CapabilityBroker` (tokeni scoped/expiring per-task/per-sursă; `check` read-only, acordă DOAR capabilitățile listate ⇒ fără escaladare; revoke), `KillSwitch` (halt out-of-band persistat pe disc, scopes + global, `is_halted`; disengage = acțiune operator), `authorize` (halt SAU lipsă capabilitate ⇒ blocat); endpoints admin-guarded `POST /api/security/capabilities/issue` + `/kill-switch`, read-only `/capabilities/check` + `GET /kill-switch`. Aliniat EU AI Act Art.14 + NIST. +6 teste offline. | 8 | P2 | H6.2 | EU AI Act, NIST |
| H17.4 ✅ | **Audit ancorat extern, cu atribuire de intenție** — extinde lanțul Merkle (H4.10). **Done 2026-06-03:** `core/security/anchor.py` — `IntentLog` (record-uri hash-înlănțuite, semnate HMAC cu identitate per-instal stabilă (arg/env/key-file), `why`+`cause` = atribuire cauzală, `verify` detectează tamper de hash ȘI de semnătură), `TransparencyAnchor` (log extern append-only hash-linked care ancorează head-ul lanțului de audit, `verify` chain); endpoints `POST /api/security/audit/action` + `GET /audit/intent` (verify) + admin `POST /audit/anchor` + `GET /audit/anchors`. +7 teste offline. | 8 | P2 | H4.10 | Apple PCC, AttriGuard |

> **Total ORIZONT 13–17:** 20 items, ~146 SP — **în scope-ul 1.0.0**. **Secvențiere recomandată în drumul spre 1.0:**
> **H17 (Provable Trust)** + **H14 (Living Memory)** sunt cele mai on-mission (teza de încredere + „te cunoaște";
> H17 continuă direct securitatea Wave 0 / H12.1); **H13** ridică plafonul la $0; **H15/H16** închid platforma.
> Flagship transversal: **sleep-time compute** (H13/H14) — chiar sloganul moonshot.

---

## ORIZONT 18 — Aplicații Native iOS/Android & Paritate cu Browser (P2–P3) — 19/21

> Client mobil nativ (Expo SDK 56 / RN 0.85) sub `mobile/`, peste **același API HTTP** (`agents/web.py`)
> ca HUD-ul browser — niciun backend nou. Fundația livrată în **PR #161**. Restul = paritate progresivă
> cu HUD-ul + infrastructura de build/release.
>
> **Bridge browser↔mobil (sincronizarea backlogului):** suprafața de paritate trăiește în
> [`mobile/PARITY.md`](mobile/PARITY.md) — un registru endpoint→browser?→mobil?→task. **Regula de sincronizare**
> (vezi `AGENTS.md` → „Bridge browser↔mobil"): orice feature browser care adaugă/schimbă un endpoint user-facing
> SAU o capabilitate HUD **trebuie** să (1) actualizeze `mobile/PARITY.md` și (2) deschidă un task de paritate
> `H18.x` aici dacă mobilul rămâne în urmă. Așa, dezvoltările pe browser devin automat taskuri pe iOS/Android.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H18.1 ✅ | **App nativ iOS/Android (Expo)** — shell cu tab-uri (Chat/Status/Settings), chat streaming token-cu-token peste `POST /chat/stream` (SSE via XHR), `GET /status` cu telemetrie host/GPU + pull-to-refresh, config hub URL + `X-User-Token` persistat (AsyncStorage) + test-connection; temă dark derivată din HUD v2. **Done 2026-06-06 (PR #161):** `mobile/` (App.tsx, src/api/client.ts, src/screens/*, src/context/ServerContext.tsx, src/storage/settings.ts). `tsc --noEmit` curat. | 8 | P2 | — | paritate HUD |
| H18.2 ✅ | **Persistă istoricul chat-ului** — conversațiile supraviețuiesc restartului. **Done 2026-06-07:** `src/storage/chat.ts` (AsyncStorage, cap 200 mesaje, nu persistă mesajele în streaming) + load/save/clear în `ChatScreen` (buton „New"). | 3 | P2 | H18.1 | — |
| H18.3 ✅ | **Selector de agent** — picker modal pur-JS alimentat din `GET /api/agents`, agent persistat în prefs. **Done 2026-06-07:** `src/components/AgentPicker.tsx` + `src/storage/prefs.ts` + `fetchAgents` în client; `streamChat` trimite agentul ales. | 3 | P2 | H18.1 | paritate HUD agents |
| H18.4 ✅ | **Render Markdown** — parser propriu (heading/listă/cod/quote/bold/italic/cod-inline/link) + renderer RN. **Done 2026-06-07:** `src/markdown/parse.ts` (pur, testat) + `src/markdown/Markdown.tsx`; folosit în `MessageBubble` pentru răspunsuri. | 3 | P3 | H18.1 | paritate HUD |
| H18.5 ✅ | **Resume sesiuni + TTS** — listă/resume `/sessions` + redare voce `/tts`. **Done 2026-06-07:** `src/components/SessionsModal.tsx` (`fetchSessions`/`resumeSession` → repopulează firul) + `src/audio/tts.ts` (fetch MP3 → cache → expo-audio, buton 🔊 per mesaj, reset la `didJustFinish`). | 5 | P3 | H18.1 | paritate HUD voice |
| H18.6 ✅ | **Timeouts + reconnect pe stream** — deadline pe request + retry/back-off pe GET-uri idempotente + idle-timeout pe stream. **Done 2026-06-07:** `AbortController` (15s) + retry exponențial (status/agents/sessions) + idle-timeout 45s pe `streamChat` cu eroare clară. | 3 | P2 | H18.1 | robustețe |
| H18.7 ✅ | **EAS build config (`eas.json`)** — profile development/preview/production (+ submit). **Done 2026-06-07:** `mobile/eas.json` (`appVersionSource: remote`, APK preview, autoIncrement production). | 3 | P2 | H18.1 | Expo EAS |
| H18.8 ✅ | **Test Jest** pentru logica pură (SSE decoder + Markdown parser). **Done 2026-06-07:** `jest.config.js` (babel izolat de Metro) + 19 teste (`sse.test.ts`, `parse.test.ts`), `npm test` verde. | 2 | P2 | H18.1 | — |
| H18.9 ✅ | **Branding** — icon + splash Jarvis (motiv „core" cyan pe `#030810`), generate determinist. **Done 2026-06-07:** `scripts/gen-icons.js` (pngjs) → icon/splash/favicon/adaptive (foreground+background+monochrome); splash dark via plugin `expo-splash-screen` în `app.json`. | 2 | P3 | H18.1 | — |
| H18.10 | **Paritate continuă (bridge)** — menține `mobile/PARITY.md` la zi: pentru fiecare feature browser nou cu suprafață user-facing, adaugă rândul de paritate + (dacă e cazul) task `H18.x`. Task umbrelă, mereu deschis. | — | P2 | H18.1 | bridge |
| H18.11 | **Mobile approval queue** — phone-native Decision Inbox over the unified autonomy funnel. `ApprovalsScreen` reads `GET /autonomy/approvals`, posts approve/reject/defer to `POST /autonomy/tasks/{id}/decision`, and settings persist an optional `JARVIS_ADMIN_TOKEN` as `X-Admin-Token` for admin-gated routes. H27.6 extends each registered action card with its machine-readable rollback description and limitations before the user approves it; unknown task kinds remain honest (`rollback: null`). | 5 | ✅ done (2026-07-04, #509; rollback parity 2026-07-12) | H18.1, O26-P0.7, H27.6 | O26-P3.4 / M3.1 |
| H18.12 ✅ | **Mobile channel inbox + governed replies** — native Comms tab now catches the app up to Safe Comms transport v0: lists `GET /api/channels/inbox`, reads `GET /api/channels/inbox/{thread_id}`, and queues `POST /api/channels/inbox/{thread_id}/reply` drafts into the same approval funnel with `source:"mobile"`. Browser HUD support shipped in #551; mobile parity is verified with 26 Jest tests + clean `tsc --noEmit`. | 4 | ✅ done (2026-07-05, #564) | H18.1, H18.11 | Safe Comms v0 parity |
| H18.13 ✅ | **Mobile tasks board** — native Tasks tab now catches the app up to the read-only HUD task fan: `GET /tasks` renders active/waiting/done counts plus owner/project/state cards, uses the existing user-token path, and preserves the H7.7 honest empty state when the queue has no work. Verified with 28 mobile Jest tests + clean `tsc --noEmit`. | 3 | ✅ done (2026-07-05, #566) | H18.1 | mobile parity |
| H18.14 ✅ | **Mobile status ambient dashboard + ticker** — native Status now catches the app up to the read-only HUD ambient surfaces: `GET /dashboard` renders weather/calendar/notification context, and `GET /ticker` renders live agent activity rows without adding a new tab or inventing demo data. Verified with 32 mobile Jest tests + clean `tsc --noEmit`, plus full PR CI green. | 2 | ✅ done (2026-07-05, #568) | H18.1 | mobile parity |
| H18.15 ✅ | **Mobile skills browser** — native Skills tab catches the app up to the read-only HUD skills catalog: `GET /skills` normalizes the backend map into a sorted catalog, renders versions/agents/command counts, and deliberately excludes install/import/admin actions from the phone. Verified with 35 mobile Jest tests + clean `tsc --noEmit`. | 2 | ✅ done (2026-07-05, #570) | H18.1 | mobile parity |
| H18.16 ✅ | **Mobile memory + notes** — native Memory tab catches the app up to the read-only HUD memory/notes surfaces: `GET /memory` renders recent session turns and `GET /api/notes` renders current session notes, deliberately excluding clear/save/rewrite controls from the phone. Merged in #572 with full PR CI green; verified locally with 38 mobile Jest tests + clean `tsc --noEmit`. | 3 | ✅ done (2026-07-05, #572) | H18.1 | mobile parity |
| H18.17 ✅ | **Mobile knowledge graph** — native Memory tab gains a Graph view over the read-only KG surfaces: `GET /api/kg/entities`, `GET /api/kg/entities/{name}`, `GET /api/kg/facts/as-of`, and `GET /api/kg/facts/history`. It renders entity search/list, selected-entity relations, current facts, and subject history without mobile entity/relation/fact write/delete controls. Merged in #574 with full PR CI green; verified locally with 42 mobile Jest tests + clean `tsc --noEmit`. | 3 | ✅ done (2026-07-05, #574) | H18.1, H18.16 | mobile parity |
| H18.18 ✅ | **Mobile security posture** — native Status tab gains a read-only Trust card over `GET /api/security/governance`, `GET /api/security/posture`, `GET /api/security/kill-switch`, and `GET /api/security/loop-breaker`, using the existing admin-token setting for posture and deliberately excluding halt/reset/capability-write controls from the phone. Merged in #576 with full PR CI green; verified locally with 46 mobile Jest tests + clean `tsc --noEmit`. | 3 | ✅ done (2026-07-05, #576) | H18.1 | mobile parity |
| H18.19 ✅ | **Mobile first-run command center** — native Status tab gains a read-only First-run card over `GET /api/onboarding/command-center`: install ready/version, model truth, wizard progress, and honest per-action ready/reason rows (run affordances stay browser-side). Red/green: `commandCenter.test.ts` first failed on missing `fetchCommandCenter`, then mobile Jest passed (49) + `tsc --noEmit` clean. | 2 | ✅ done (2026-07-07, #634) | H18.1 | mobile parity |
| H18.20 ✅ | **Native artifact workspace parity** — catches the app up to the #652 browser Artifacts tab over the same unchanged `/api/canvas*` contract. Memory tab gains an **Artifacts** view: browse with safe typed rendering on all 7 canvas types (RN Text nodes are inert; remote http(s) images behind an explicit consent tap; protocol-relative/control-char URLs stay plain text), pin/unpin/delete on the existing endpoints, honest loading/empty/error states. Chat gains the **explicit save-response control** (only completed non-error assistant replies, never while streaming, never auto): posts the exact markdown contract with the ACTUAL responding agent (from the stream start event) and truncates at the 4,000-char bound on a **code-point boundary** (no lone-surrogate poisoning). Red/green: `canvasArtifacts.test.ts` first failed on missing `fetchCanvasArtifacts`, then mobile Jest passed (55) + `tsc --noEmit` clean. | 4 | ✅ done (2026-07-10) | H18.1, H18.16 | #652 handoff |
| H18.23 ✅ | **Mobile spoken morning brief** — the native Status tab gains a "Morning brief" card over the admin-guarded `GET /autonomy/brief`, with a 🔊 Speak/Stop control through the existing hub-TTS + expo-audio path. Honest empty/no-admin-token/TTS-unavailable states; `fetchAutonomyBrief` normalizes kind/text with a bound. Red/green: `autonomyBrief.test.ts` (+3) first failed on the missing client function, then full mobile Jest passed (96) + `tsc --noEmit` clean. | 2 | ✅ done (2026-07-19) | H18.5, H18.14 | PARITY.md |
| H18.24 | **Native voice orb** — bring the browser voice orb (`frontend/src/orb.tsx`) to the native mic surface: the same state→visual contract (listening = measured mic level, every other state a labelled animation, no numeric level), rendered with the platform's canvas/Skia equivalent. No API change — it reads the existing STT/TTS loop. | 3 | P3 | H18.5 | PARITY.md |
| H18.25 | **Native briefing wall** — the browser wall (`frontend/src/wall.tsx` + `burst.tsx`) is responsive down to phone widths, so a phone browser already gets the portrait layout and hold-to-talk; the **native** apps have neither. Port the field, the chip/edge-tab chrome and the push-to-talk control, carrying the same fail-closed mic rule (current trust evidence + exact `mic === 'on'`, stop on permission loss/unmount) and the default-hidden spoken line. | 5 | P3 | H18.5, H18.24 | PARITY.md |
| H18.21 ✅ | **Native Media Director parity** — the metadata-only Media tab reads the owner-curated `/api/media/devices` registry and `/api/media/session` board, then exposes explicit user present/restore controls over the unchanged guarded API. Safe bounded normalization preserves disabled/error states and distinguishes queued, refused, unverified, and verified nested outcomes; a stale/unregistered target cannot be submitted. Device register/remove controls are isolated behind the configured admin token and no remote media is embedded. Red/green: missing client/screen contracts failed first, then mobile Jest passed (65) + `tsc --noEmit` clean. | 3 | ✅ done (2026-07-13) | O29 | PARITY.md |
| H18.22 ✅ | **Mobile capability registry board** — folded into the existing Status tab (not a new top-level tab: 13 tabs already fill the bar) as a **Capabilities** card alongside Trust, over the same user-guarded `GET /api/capabilities` the browser's `ReadinessPanel` reads: SEAM/WIRED/VERIFIED/GA counts + the honest "harness pending — wired, not yet proven" note (never claims VERIFIED it can't back). Read-only — no action execution or token-management controls; approvals stay on H18.11. `fetchCapabilities`/`normalizeCapability` in `mobile/src/api/client.ts`. Red/green: `capabilities.test.ts` (+3: shape mapping, malformed-entry drop + honest defaults, sparse-payload normalization), mobile Jest passed (93) + `tsc --noEmit` clean. | 2 | ✅ done (2026-07-19) | H18.1, H27.8 | mobile parity |

---

## ORIZONT 19 — WorldView (4D OSINT) — Standalone + Integrare JARVIS — 33/33 ✅

> **Produs nou, stack separat** (Vite + CesiumJS + Fastify + Kafka/Redpanda + TimescaleDB/PostGIS + Redis),
> self-contained sub [`worldview/`](worldview/). Centru de comandă OSINT 4D (aer/mare/spațiu/cyber) pe un glob
> scrub-abil în timp — inspirat de „God's Eye View" (Bilawal Sidhu) și de patternurile Palantir (Gotham/AIP/
> Ontology). **Spinele tehnic e livrat** (toate 5 layere, motorul 4D, calea de date Kafka→Redis/TimescaleDB
> validată în CI vs TimescaleDB real, 58 teste unit + integrare). PR #163.
>
> **Deep review complet + merged (2026-06-08):** review post-merge al celor 33/33 (Critical: retention vs
> reconstrucție; + fixuri pe ingestion/backend/frontend/integrare-JARVIS — commits `d162f1a`…`8fc6660`, PR #167),
> CI integral verde inclusiv jobul TimescaleDB real. Două follow-up-uri rămase, trackuite ca GitHub issues:
> **#169 este livrat în #594** (transportul MCP write-tool la runtime — `watch_aoi`/`reconstruct_event`
> prin client stdio, plugin-gate, Action Kernel și token HMAC scoped). Rămâne **#170**
> (validarea pe Neo4j real a property-search-ului din KG sync). Launchere noi
> **INSTALL.bat / START.bat** instalează + pornesc automat WorldView lângă JARVIS (PR #171).
>
>
> **✅ Renderer înlocuit (2026-08-25, cerere owner „replace it with God's Eye View"):** frontendul
> a fost reconstruit în forma lui *God's Eye View* — **Vite + CesiumJS, fără framework de UI** —
> conectat la API-ul 4D propriu. Ce a dispărut: Next.js/React/Deck.gl/Mapbox **și** pachetul
> `world-atlas` (TopoJSON-ul de 110 m desenat ca uscat plat). Ce a apărut: **basemap fără cont** —
> Cesium livrează tile-urile Natural Earth II în pachet, deci globul arată Pământul real fără
> token, fără cont și fără fetch de rețea (`VITE_CESIUM_ION_TOKEN` e doar *upgrade* la imagery
> fotografic + teren 3D); marcaje la **altitudinea reală** (ADS-B și sateliți sunt `PointZ`);
> **terminatorul zi/noapte urmărește master-clock-ul** (scrub-ul mișcă lumina pe glob);
> **grade de senzor** thermal/night/tactical (post-process — *grade vizuale, nu date*, și HUD-ul o
> spune) + **follow cam** (`F`). Toate diferențiatoarele WorldView sunt portate 1:1 (master clock,
> live WS + as-of-T, trails, dark-vessel, gramatica negative-space, Inspector + provenance, export,
> recon, tours, arrival deep-links, replay determinist, mode system, scurtături). **157 teste
> frontend verzi (19 fișiere)**, `tsc --noEmit` + `vite build` verzi, plus o rulare headless a
> build-ului real pe un API-fixture. Decizia + consecințele acceptate (tile-urile vectoriale nu mai
> sunt desenabile pe Cesium → `VITE_TILE_URL` acceptă doar raster):
> [`docs/decisions/2026-08-25-worldview-cesium-renderer.md`](docs/decisions/2026-08-25-worldview-cesium-renderer.md).
>
> **Strategie & feature-pick:** [`worldview/docs/ROADMAP.md`](worldview/docs/ROADMAP.md) ·
> **Planul de arhitectură & livrare (scale model, deep-dives, ADRs, exit gates):**
> [`worldview/docs/02-platform-architecture-and-delivery-plan.md`](worldview/docs/02-platform-architecture-and-delivery-plan.md).
> Ticketele de mai jos = cele 5 workstream-uri (WS1–WS5) din plan, fiecare cu **criteriu de acceptanță măsurabil (AC)**.
>
> **Teza de integrare:** *JARVIS este „AIP"-ul local-first al WorldView* — operatorul în limbaj natural + cortexul
> proactiv. WorldView e **plugin opt-in, niciodată cerut de core** (respectă MOONSHOT §5: cloud opt-in, inspectabil,
> ≤4 interrupts/zi). Doar OSINT public — *„datele tale nu antrenează modelul nimănui"*. Agenții strict-local
> (`frigga`/`ultron`/`howard`) nu îl ating.
>
> **Secvențiere (drum critic):** WS1 deblochează WS2+WS5; WS2 deblochează WS3 (alerte de surfacing) + WS4 (insight-uri de guvernat);
> WS3 (JARVIS) ‖ WS4 (guvernanță) în paralel după WS2; WS5 continuu, front-loaded (tiles + replici).

### WS1 — Calea de date live la scară (Phase A) — 7/7 ✅ (H19.1.1–4 cod livrat: toate sursele) · *gate: 50k msg/s susținut, lag<60s, as-of-T p95<300ms sub load, replay 24h real*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.1.1 🔨 | **Sursă ADS-B reală** (OpenSky/ADSB.fi). **Livrat:** `adsb/sources.py` — OpenSky (OAuth2 client-credentials→bearer cu cache/refresh, fallback anonim, bbox viewport, rate-limit/429 + backoff) **și** ADSB.fi (gratuit, centrat pe AOI, tag militar real via `dbFlags`); `worker.py` cu poll adaptiv + backoff exponențial; `ADSB_SOURCE=opensky\|adsbfi`. +7 teste (payload-uri real-shaped, mock HTTP). **Validat** fetch→normalize→envelope→`writeBatch`→`/history` pe payload OpenSky real-shaped (avionul apare în /history cu alt/coords corecte). **Rămâne** (deploy-gated): hop-ul live-net (egress allowlist) + Kafka. **AC:** `osint.adsb` curge din sursă reală; un avion real apare în `/history` în <5s. | 5 | P1 | — | Standalone |
| H19.1.2 🔨 | **Sursă AIS reală** (AISStream WS). **Livrat:** `ais/stream.py` (subscription config-driven din `AIS_BBOX` + `handle_frame` testabil) + `worker.py` cu **reconnect + backoff exponențial**. +6 teste. **Validat** handle_frame→envelope→`writeBatch`→`/history` (vasul apare, sog corect). **Rămâne** (deploy): hop live-WS + Kafka. **AC:** vase reale curg; dark-vessel detector se declanșează pe un gap AIS real. | 5 | P1 | — | Standalone |
| H19.1.3 🔨 | **Sursă TLE reală** (Celestrak/Space-Track). **Livrat:** `tle/sources.py` (Celestrak GROUP + filtru NORAD; Space-Track login+`gp`), `tle/sensors.py` (registru senzori curatat optical/SAR), `worker.py` cu sursă pluggable + refresh catalog periodic. +7 teste. **Validat** fetch→propagate→envelope→`writeBatch`→`/history` (satelitul apare cu footprint + `is_sunlit`). **Rămâne** (deploy): hop live-net + Kafka. **AC:** `satellite_ephemeris` populat /minut; footprint optical/SAR corect. | 5 | P1 | — | Standalone |
| H19.1.4 🔨 | **Surse EW/context reale** (GPSJam/IODA + feed NOTAM/evenimente). **Livrat:** `ew/gpsjam.py` (parser heatmap GPSJam: hexagoane H3 pre-binned → intensitate `bad/(good+bad)`, id din centroid) + `ew/worker.py` îl fetch-uiește; `context/worker.py` fetch evenimente GeoJSON + NOTAM din `CONTEXT_EVENTS_URL`/`CONTEXT_NOTAM_URL`. +2 teste GPSJam (51 total). **Rămâne** (deploy): hop live-net + Kafka; IODA + FAA-NOTAM (auth) ca surse adiționale. **AC:** celule H3 jamming + NOTAM-uri din date live. | 5 | P2 | — | Standalone |
| H19.1.5 🔨 | **Consumeri KEDA-scalați pe lag** + PgBouncer (transaction pooling) + read replica. **Livrat (manifeste k8s local-runnable):** `deploy/k8s/` — 3 Deployments consumer (live/history/recon-writer) + `ScaledObject` KEDA per consumer pe lag-ul consumer-group Kafka (live-writer 1–10 @10k, history 1–8 @20k/5k, recon 1–4 @2k; praguri sub alarma de lag 50k/250k), namespace + kustomization + README (`kind`+`helm install keda`). YAML well-formed; `scaleTargetRef` matches. **Rămâne (prove la rulare):** SLO 50k msg/s + PgBouncer/replica (infra reală); imagine consumer-only + broker in-cluster (TODO documentate). | 8 | P1 | H19.1.1 | Standalone |
| H19.1.6 🔨 | **Rig de load-test + SLO as-of-T** (generator replay/sintetic; test perf nightly). **Livrat:** `worldview_ingest/loadtest/` — generator sintetic determinist (seeded, entități stabile, ts monoton, în bbox), `RateSchedule` fără drift (emite exact `floor(rate*N)`, pacing even), `LatencyRecorder`/`slo_check` (percentile interpolate verificate manual: p95 of 0..9=8.55), harness `produce`/`probe` (producer + http client injectabile; măsoară latența reală as-of-T pe `/history`, nu inventează rezultate) + `__main__` (exit non-zero la breach SLO → gate CI). Praguri default `p95<0.5s` (configurabile `LOADTEST_*`). 208 teste, ruff clean. **Rămâne (prove la rulare):** numerele la 50k msg/s pe infra reală. | 5 | P1 | H19.1.5 | Standalone |
| H19.1.7 🔨 | **Tiered storage broker + ops retenție** (offload segmente → S3). **Livrat:** `db/schema/14_tiering.sql` (extinde 07, idempotent `if_not_exists`) — lifecycle HOT→WARM→COLD per layer: HOT necompresat, WARM columnstore (compress 2d adsb/ais, 7d ephem/jamming, 30d intel), COLD = lakehouse Parquet (chunk-uri dropped rămân interogabile în DuckDB); `add_retention_policy` per hypertable (adsb 90d…recon 730d, intel never-drop), caggs supraviețuiesc retenției; FĂRĂ `ADD COLUMN` pe hypertable comprimat (trap-ul columnstore evitat). Path enterprise `tiered_storage` documentat. `deploy/tiering/README`. **AC îndeplinit:** disk OLTP mărginit de retenție; replay din cold (lake). | 5 | P2 | H19.1.1 | Standalone |

<!-- recon now end-to-end (worker→writer→/recon→panel); H19.2.1/2.2 operational, contract cross-checked -->
### WS2 — Motorul de insight („so what") (Phase B) — 7/7 ✅ · *gate: platforma EXPLICĂ un eveniment (recon „trecere SAR în N min" + „treceri stivuite"), cu provenance*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.2.1 🔨 | **Recon-window scheduler** (SGP4 → footprint∩AOI → bisecție ingress/egress → scor calitate). **Livrat (algoritm):** `recon/windows.py` — `Aoi`/`ReconWindow`, `footprint_ground` (optical/SAR/coverage), `predict_windows` (walk SGP4 + test circle-vs-circle haversine + bisecție ingress/egress ~1s + closest-approach peak + quality care anulează optic noaptea via `is_sunlit`). +5 teste (ISS: AOI ecuatorial→ferestre ordonate; AOI polar→0; optic-noapte vs SAR). **Rămâne:** persistență `recon_windows` + refresh în deploy (parte din H19.2.2/backend). | 8 | P1 | H19.1.3 | Both |
| H19.2.2 🔨 | **Alertare recon-window** (scan windows în lead-time → `Alert`). **AC:** o alertă se declanșează ≥lead_time înaintea unei treceri reale peste un AOI urmărit. | 3 | P1 | H19.2.1 | Both |
| H19.2.3 🔨 | **Schelet motor CEP** (consumer windowed keyed pe `aoi`/`geohash` + state + watermark lateness). **Livrat:** `cep/engine.py` — motor pur event-time, ferestre tumbling per-cheie aliniate la epoch, watermark monoton `= max_event_ts − lateness`; evenimente out-of-order `≥ watermark` intră în fereastră, cele mai vechi sunt drop+counted; fereastra trage regula o dată când watermark-ul îi trece închiderea, apoi e evacuată. `cep/events.py` (contract `worldview.event.v1` + `from_tipping`/`from_anomaly` + `key()`); `cep/worker.py` (consumer/producer proprii, injectabile la test; `json.loads` guarded skip poison pills; reconstruiește `ReconWindow` din `worldview.recon.v1` — contract verificat producer↔consumer; rulează `detect_tipping` per fereastră → `osint.events`; backoff/reconnect). Config `CEP_*` + worker `cep`. +24 teste (18 engine + 6 worker); ruff clean, suită 94 passed. **AC îndeplinit:** o regulă windowed rulează peste stream cu lateness mărginit. | 8 | P2 | H19.1.5 | Both |
| H19.2.4 🔨 | **Regulă tipping-and-cueing** („≥N recon windows peste un AOI în Δt"). **AC:** scenariu sintetic + real declanșează insight-ul cu linkuri la ferestrele contribuitoare. | 5 | P2 | H19.2.3, H19.2.1 | Both |
| H19.2.5 🔨 | **Detectori de anomalii** (alege 2–3: holding-pattern, cascadă închideri spațiu aerian, onset jamming, corelație blackout↔eveniment). **AC:** fiecare se declanșează pe un scenariu seeded cu provenance. | 8 | P2 | H19.2.3 | Both |
| H19.2.6 🔨 | **Layer de adnotare/callout** (API + UI: auto-callouts din `Event` + adnotări manuale pe timeline/hartă). **AC:** insight-urile se randează ca callouts; adnotările manuale persistă. | 5 | P3 | H19.2.4 | Standalone |
| H19.2.7 🔨 | **Reconstrucție eveniment + export replay partajabil** (link/video). **Livrat:** `13_reconstructions.sql` (handle partajabil — salvează DOAR params, cadrele se re-derivă) + `repositories/reconstruction.ts` (`buildFrames` pași `from..to` cu `stepSeconds`, citește readerii history as-of-T per layer, cap `MAX_FRAMES=600`) + `repositories/export.ts` + `routes/reconstruction.ts` (`POST /reconstructions` audited+RBAC, `GET /reconstructions/:id/export?format=json\|geojson`); UI: `frontend/lib/export.ts` + replay-control care conduce master-clock-ul + link replay reproductibil (`?from&to&bbox`). Validat E2E pe Postgres real: export geojson (44 features / 11 cadre, fiecare cu `t`+`layer`), **două exporturi identice (reproductibil)**, viewer create→403, lanț audit valid. **AC îndeplinit:** reconstrucție mărginită temporal → export partajabil + reproductibil. | 8 | P3 | H19.2.6 | Standalone |

### WS3 — Operare agentică (Integrare JARVIS) (Phase C) — 6/6 ✅ · *gate: operezi WorldView vorbind cu JARVIS; o alertă ajunge în digest în buget, cu provenance*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.3.1 🔨 | **WorldView MCP server** — tool-uri read consumate de `agents/core/mcp/client.py`. **Livrat:** pachet standalone `worldview/mcp/` (`@worldview/mcp`) — SDK MCP v1.29 (`Server`+`setRequestHandler`, JSON-Schema, stdio); tool-uri `stateAt`, `findDarkVessels`, `trackOf`, `listLayers` (handler-e pure `(args, deps)` cu fetch injectabil, apelează REST-ul WorldView; validare input; erori→isError). +12 teste (stub fetch), tsc clean, build dist. **Rămâne:** tool `recon_windows`/`watch_aoi` (după backend recon) + abonare din JARVIS. | 5 | P1 | H16.1 | JARVIS |
| H19.3.2 🔨 | **Tool-uri MCP write/async** (`watch_aoi`, `reconstruct_event`) + **auth capability-token** (reutilizează `CapabilityBroker`, H17.3). **Livrat:** `mcp/src/auth.ts` — `verifyCapability(token, scope, {secret, now})` peste token HMAC-SHA256 `base64url(claims).base64url(sig)` cu `{scopes, exp, sub?}`; fail-CLOSED (secret lipsă/sig greșit/expirat/scope lipsă ⇒ deny, fără throw), compare constant-time cu guard de lungime, wildcard `worldview:*`; `audit()` JSON structurat doar pe stderr. Tool-uri `watch_aoi` (scope `worldview:watch` → POST `/recon/watch`) și `reconstruct_event` (scope `worldview:reconstruct` → POST `/reconstructions`), fetch injectabil, degradare grațioasă pe non-2xx; `server.ts` impune auth ÎNAINTE de side-effect (`authorizeWrite` injectabil), read-only neschimbate; `mcpSecret` din `WORLDVIEW_MCP_SECRET` fără default. +24 teste (12 auth + 12 tool/gate; căile deny verifică fetch NU e apelat + audit deny); tsc/build clean, 36 passed. **JARVIS-side minter wired + pinned cross-language:** `agents/core/security/worldview_mcp.py` (`mint_capability`/`verify_capability`) produce EXACT formatul HMAC pe care MCP-ul îl acceptă (nu opacul `CapabilityBroker`, care e incompatibil cu verificarea stateless offline a MCP-ului) — pinned de vectori partajați (`worldview/mcp/test/fixtures/capability-vectors.json`) asertați de AMBELE suite (`tests/test_worldview_mcp_capability.py` 9 passed + `worldview/mcp/test/capabilityVectors.test.ts`, în CI), deci formatul nu poate driva tăcut între cele două limbaje. `mcp/` adăugat în CI (`worldview.yml` job `mcp`: typecheck+build+test). **Backend wired (seam închis):** `POST /recon/watch` real, auditat pe hash-chain (`write:recon` RBAC + scope AOI), `reconstruct_event` pointed la `/reconstructions` (H19.2.7); validat E2E pe Postgres real (watch 201/viewer 403/no-token 401, lanț audit valid). **AC îndeplinit:** apel neautorizat respins + auditat; tool-urile lovesc endpoint-uri backend reale. **Rămâne (runtime):** invocarea propriu-zisă a tool-urilor write din JARVIS prin `agents/core/mcp/client.py` (spawn stdio server + apel `watch_aoi`/`reconstruct_event` cu tokenul mintat) — formatul auth e închis & pinned; rămâne doar cablarea transportului MCP-client la runtime. | 5 | P1 | H19.3.1, H17.3 | JARVIS |
| H19.3.3 🔨 | **Plugin JARVIS** `agents/core/plugins/worldview.py` (gated de `plugin_gate`). **Livrat:** `WorldViewPlugin` — client read-only fail-safe peste REST-ul WorldView (`http://localhost:4000`, override `WORLDVIEW_API_URL`); oglindește tool-urile read MCP (`state_at`/`recon_windows`/`recon_alerts`/`provenance`) + convenience `recon_overview`; backend căzut ⇒ `{"status":"unavailable"}` (nu inventează intel, e OSINT). Manifest `worldview` în `plugin_gate` (LAN, local-only, agents `jarvis/athena/stark/vision`); wired în `orchestrator` (import + instanțiere + ramură geospațială în `_gather_plugin_data` pe keywords satellite/recon/Hormuz/jamming/…). +5 teste; suita JARVIS completă verde (fără regresii). **AC îndeplinit:** Athena/Stark pot răspunde la o întrebare geospațială folosind WorldView. | 5 | P1 | H19.3.1 | JARVIS |
| H19.3.4 🔨 | **Autonomy watcher**: alerte WorldView → inbox→severitate→**buget ≤4/zi**→digest JARVIS. **Livrat:** `WorldViewProbe` în `autonomy/watchers.py` — emite `Signal`-uri pentru treceri recon due (WARN) + dark-vessels (CRITICAL), keyed stabil (debounce: o alertă/pas via `EventWatcher`), cu link provenance (`/provenance/{tle,ais}/…`) în detail; degradare grațioasă (plugin absent/backend căzut ⇒ 0 semnale, fără excepții, fără intel inventat). Înregistrat în `event_probes` (orchestrator `_wire_autonomy`); curge prin inbox→severitate→buget→digest existent (reutilizează `WorldViewPlugin` H19.3.3 cu retry+circuit-breaker). +5 teste; suita JARVIS completă verde. **AC îndeplinit:** o alertă dark-vessel/recon apare în digest cu link de provenance, în pipeline-ul cu buget. | 8 | P1 | H19.3.1, H6, H19.2.2 | JARVIS |
| H19.3.5 🔨 | **Sync graf de cunoștințe** (change-feed ontologie → `memory/graph.py`; recall fuzionat RRF). **Livrat:** `memory/worldview_sync.py` `WorldViewKGSync` — trage ontologia WorldView (AOI-uri + geo-evenimente legate: dark-vessel, recon) prin `WorldViewPlugin` (extins cu `ontology_objects`/`ontology_links`) și face upsert în `KnowledgeGraph` ca entități `geo_aoi`/`geo_event` (cu titlul AOI în nume+proprietăți → căutabil pe locație) + relații `IN_AOI`; provenance călătorește în proprietăți. Fail-safe (WorldView căzut ⇒ no-op, fără excepții/intel inventat). +3 teste; suita JARVIS completă verde. **AC îndeplinit:** după sync, `recall("...Hormuz...", keyword="Hormuz")` întoarce geo-evenimentul via sursa graph a fuziunii RRF. Programare periodică opt-in wired în orchestrator (`worldview.kg_sync_enabled` / `JARVIS_WORLDVIEW_KG_SYNC`, off by default, no-op când WorldView e căzut). | 5 | P2 | H19.3.1, H19.4.1 | JARVIS |
| H19.3.6 🔨 | **Agent intel „Argus"** (SOUL specializat geospațial-OSINT, opțional). **Livrat:** `agents/argus/SOUL.md` (persona geospațial-OSINT read-only, citează provenance, nu inventează intel) + intrare `argus` activă în `agents/_system/agents.yaml` (tier business, plugins `[worldview, cloud-llm]`, 17/18 active) + regulă router `geoint` → `argus` (keywords satellite/recon/overflight/vessel/aircraft/Hormuz/jamming/AOI, W_STRONG) + `ROUTING_TABLE` + serviu `worldview` în `plugin_gate` pentru `argus`. +5 teste (routing geospațial→argus, research încă→vision, gate, config, SOUL); suita JARVIS completă verde. **AC îndeplinit:** un agent dedicat răspunde la query-uri geospațial-OSINT folosind tool-urile WorldView. | 3 | P3 | H19.3.3 | JARVIS |
| H19.3.7 ✅ | **HUD World-tab liveness bridge** (post-completion addendum — closes the gap the 2026-06-28 hud-v3 blueprint left open: the HUD's World tab talks to the unrelated Signal Layer, never to WorldView itself). `WorldViewPlugin.status()` hits the standalone backend's dependency-free `GET /health`, degrading to `{"connected": false}` on failure (never fabricates a connection — same contract as the plugin's other reads). New `GET /api/worldview/status` (open, non-sensitive meter tier, sibling of `/api/analytics/locality`) in `agents/core/routers/worldview.py`. `frontend/src/modes_world.tsx` polls it independently of the Signal Layer fetch cycle (one being down must not hide the other's state) and renders a real connected/not-connected badge next to the "open WorldView" link, in both the Signal-Layer-up and Signal-Layer-down render branches. `tests/test_worldview_plugin.py` (+2), `tests/test_worldview_status_route.py` (+4, new), `frontend/src/test/modes-world-worldview-status.test.tsx` (+2, new); route/OpenAPI/auth snapshots reseeded (1 new open GET route, classified `interop` in the HUD v2 parity gate). Verified live in a headless-Chromium smoke test against the rebuilt `/v2` bundle. | 2 | ✅ done (2026-07-19) | H19.3.3 | JARVIS + HUD |
| H19.3.8 ✅ | **WorldView read data în HUD + casual quickstart** — the World tab now shows real WorldView *data*, not just liveness, and a casual user can stand WorldView up with one command. **Hub:** `GET /api/worldview/overview` (same open meter tier) = `status()` + `recon_overview()` in one call — honest at every level: not connected ⇒ `recon: null` (recon is never even queried); connected-but-recon-down ⇒ the plugin's `{"status":"unavailable"}` passes through so the HUD says "connected · no recon data" instead of pretending. **HUD:** the World tab polls `/overview`; under the badge it renders upcoming recon windows (sat/sensor/AOI/ingress time, top 3) + the due-alert count, a "connected · no recon data" line, or — when not connected — the casual-install hint `cd worldview && ./quickstart.sh`. **Casual installer:** `worldview/quickstart.sh` — docker compose up **timescaledb+redis only** (no Redpanda/Kafka: without the `ENABLE_*_WRITER` flags the API is read-only, and casual = read-only), waits for Postgres + schema (initdb mount), applies the Hormuz demo seed *through psql inside the container* (no host psql), npm-installs and starts the API on :4000; flags `--infra-only`/`--seed-live`/`--down`; idempotent (the seed TRUNCATEs its own tables). **Demo seed extended** (`worldview/db/seed/demo.sql`): 3 future-anchored `recon_windows` rows over the Hormuz AOI (one inside the 900 s alert lead ⇒ the alertable set is non-empty out of the box). **Proven live end-to-end in-session:** quickstart ran against a real Docker daemon (image pull → schema → seed), the real backend-api served `/recon/windows` (3) + `/recon/alerts` (1), the real hub (`serve.py`) bridged them at `/api/worldview/overview`, and a headless-Chromium screenshot of the live World tab shows the connected badge + "3 recon windows · 1 due alert" + the three SAR passes. `tests/test_worldview_status_route.py` (+4), `frontend/src/test/modes-world-worldview-status.test.tsx` (3 total, rewritten for /overview); snapshots reseeded (+1 open GET). | 3 | ✅ done (2026-07-19) | H19.3.7 | JARVIS + HUD + Standalone |

### WS4 — Guvernanță & colaborare (Phase D) — 6/6 ✅ · *gate: 2 analiști pe un caz cu audit + reconstrucție exportată reproductibil*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.4.1 🔨 | **Ontologie**: proiector obiecte+linkuri+**acțiuni** peste SoR-ul relațional + proiecție graf. **Livrat:** registry declarativ (6 obiecte: Aircraft/Vessel/Satellite/Aoi/ReconWindow/DarkVesselEvent, 3 linkuri: covers/wentDark/inGeofence, 2 acțiuni: annotate/watch); `repositories/ontology.ts` (proiecție read parametrizată, `42P01` graceful) + `ontologyAudit.ts`; rute `GET /ontology/{types,objects/:type[,/:id[,/links]]}`, `POST .../actions/:action` (auditat), `GET /ontology/actions`; `11_ontology.sql` (`ontology_actions` append-only + `ontology_annotations`, tabele noi, fără ALTER pe hypertabele comprimate). Id-uri compozite consistente (full-epoch, nu `::bigint`) — bug de navigare graf prins la validarea E2E pe Postgres real și reparat (regresie fractional-epoch). 68 teste backend; validat E2E pe PostgreSQL/PostGIS real (seed demo): obiecte/linkuri interogabile + navigare Vessel→wentDark→DarkVesselEvent→inGeofence→Aoi. **AC îndeplinit.** | 8 | P2 | — | Both |
| H19.4.2 🔨 | **AuthN/Z**: OIDC + RBAC/ABAC (viewer/analyst/admin; scoping AOI/regiune). **Livrat:** bearer JWT HS256 OIDC-style (`auth/jwt.ts`, dependency-free, constant-time, guard alg-confusion/exp/malformed), matrice rol→permisiune + scoping AOI (`auth/rbac.ts`), hook `onRequest` central (`auth/guard.ts`) cu `request.principal`; opt-in (`WORLDVIEW_AUTH_SECRET` — deschis fără secret pentru back-compat, fail-CLOSED cu secret). Scoping pe `/recon/windows` + obiecte ontologie AOI-bearing. 117 teste backend. Validat E2E pe server real Fastify + Postgres real: no/bad token→401, viewer read→200/write→403, analyst out-of-scope→403/in-scope→200, analyst audit→403/admin→200 (RBAC+ABAC enforced la nivel HTTP). **AC îndeplinit:** acces scoped pe rol, enforced + testat. | 8 | P2 | — | Both |
| H19.4.3 🔨 | **Provenance/chain-of-custody** (`source`+`ingested_at`+bitemporal `valid_*` în UI/API). **Livrat (API):** `db/schema/10_provenance.sql` — migrare aditivă+idempotentă: `ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now()` pe toate tabelele stream/event (writerele existente merg via DEFAULT), sentinel `source` unde lipsea, view `provenance_latest`; model bitemporal documentat (valid time = `ts`/`effective_*` vs transaction time = `ingested_at`). `repositories/history.ts` — query-urile as-of-T întorc `source`+`ingested_at` în `properties`. `repositories/provenance.ts` + `routes/provenance.ts` — `GET /provenance/:layer/:entityId?t=` întoarce `{source, ts, ingestedAt}` al ultimului datum (42P01-guarded, per-layer). +10 teste mock-pool; tsc clean, 36 passed. **AC îndeplinit (API):** orice datum se trasează la sursă. **Rămâne:** UI provenance (frontend, ticket separat). | 5 | P2 | — | Both |
| H19.4.4 🔨 | **Audit hash-înlănțuit** (reutilizează Merkle audit JARVIS, H4.10/H17.4) pe acțiuni/tool-calls/ack-uri. **Livrat:** `ontology_actions` câștigă `prev_hash`/`entry_hash`; `auditChain.ts` pur (`stableStringify` cu chei sortate, `canonicalize`, `computeEntryHash = sha256(prev + '\n' + canonical)`, `verifyChain` care identifică primul link rupt); `recordAction` calculează lanțul la insert sub `pg_advisory_xact_lock` (citire-vârf sigură la concurență); rută `GET /ontology/audit/verify`. 88 teste backend. Validat E2E pe Postgres real: hash-ul de la insert == recompute la citire (jsonb/unicode/null/ordine chei), tamper pe un rând ⇒ `{ok:false, brokenAtId}`. **AC îndeplinit:** log tamper-evident + endpoint verify. | 5 | P2 | H19.4.1 | Both |
| H19.4.5 🔨 | **Cazuri / adnotări / multi-user**. **Livrat:** `12_cases.sql` (cases/case_members/case_items/case_comments, FK cascade) + `repositories/cases.ts` + `routes/cases.ts` (CRUD + members + items care ancorează obiecte ontologie + comments + `GET /cases/:id/history`), gated RBAC (`read:cases` viewer+, `write:cases` analyst+); fiecare mutație → rând audit hash-înlănțuit (reutilizează `recordAction` H19.4.4). 135 teste backend. Validat E2E pe server real + Postgres real: 2 analiști colaborează (alice owner + bob collaborator, item + comment), RBAC enforced (401/403), `GET /cases/:id/history` are cele 4 acțiuni, iar `/ontology/audit/verify` rămâne `{ok:true}` (acțiunile cazului în lanțul tamper-evident). POST-urile întorc 201. **AC îndeplinit:** 2 utilizatori colaborează pe un caz partajat cu audit. | 8 | P3 | H19.4.2 | Standalone |
| H19.4.6 🔨 | **Export/raportare** (brief PDF, GeoJSON, replay). **Livrat:** `GET /cases/:id/export?format=brief\|geojson\|json` (RBAC `read:export`) — `brief` = raport Markdown (summary, membri, items rezolvate la obiectul ontologie curent cu provenance, comments, audit trail), `geojson` = items ca features, `json` = bundle complet; UI `ExportPanel` (download view-GeoJSON / case brief+geojson). PDF = print-to-PDF din Markdown (fără dep nouă). Validat E2E pe Postgres real: `case export brief → 200` Markdown `# Case Brief`. **AC îndeplinit:** caz exportat reproductibil. | 5 | P3 | H19.4.5 | Standalone |

### WS5 — Scale & hardening platformă (Phase A5/D5/D6 + infra) — 7/7 ✅ · *gate: 1M+ puncte @60fps via tiles, 10k WS concurente, DR ↦ RPO≤5m/RTO≤30m, SLO-uri verzi*

| # | Item | S | P | Dep | Track |
|---|------|---|---|-----|-------|
| H19.5.1 🔨 | **Serviciu vector-tiles** (Martin/pg_tileserv) + CDN; clientul comută pe tiles sub un prag de zoom. **Livrat:** server Martin MVT (`deploy/tiles/`, citește tabelele `geom` din TimescaleDB) + client (`frontend/lib/tiles.ts` `shouldUseTiles(zoom)` — comută `adsb`/`ais` pe `MVTLayer` când `NEXT_PUBLIC_TILE_URL` setat ȘI `zoom ≤ NEXT_PUBLIC_TILE_MAX_ZOOM` (default 6); degradare grațioasă la puncte fără URL). Workaround alias/shim next.config pentru barrel-ul deck `geo-layers` rupt de versiunile deck/luma pinned (fără deps noi). typecheck clean, 51 vitest, `next build` OK. **Rămâne (prove la rulare locală):** 1M+ puncte @60fps cu serverul de tiles pornit. | 8 | P2 | H19.1.5 | Standalone |
| H19.5.2 🔨 | **WS gateway fleet** + coalescing + sharding canale pe geohash (opțiune NATS/Centrifugo). **Livrat:** `live/coalescer.ts` (coalescing per-client keyed pe entity_id — păstrează ultima valoare/entitate, flush pe `WS_COALESCE_MS`/max-batch, queue mărginit cu drop-oldest → rata per-client mărginită) + `live/geohash.ts` (encoder base-32 verificat vs referințe `ezs42`/`gcpvj0`; p3≈156km) + `live/subscription.ts` (`planSubscription`: bbox→celule `live:geo:<gh>`, fără bbox→global `chan:<layer>` back-compat). `live.ts`/`routes/live.ts` fac fan-out delta pe canale geo + filtru viewport, JSON poison-pill-safe. 201 teste backend (+44: coalescer/geohash/shard/route); tsc+build OK. **Rămâne (prove la rulare):** 10k clienți concurenți (load test/infra reală) — coalescing+sharding sunt mecanismele. | 8 | P2 | — | Standalone |
| H19.5.3 🔨 | **Lakehouse offload** (CDC/sink → Iceberg/Parquet pe S3 + query DuckDB/Trino). **Livrat (stack local-runnable):** `deploy/lakehouse/` — MinIO (S3) + Kafka Connect cu `S3SinkConnector`/`ParquetFormat` (2 conectori: telemetry adsb/ais/tle/ew, intel context/recon; consumer-group separat — nu fură offset de la writeri) → `s3://worldview-lake/topics/<topic>/...`; `queries.sql` DuckDB (httpfs/S3) pentru raw rece; README cu pairing TimescaleDB (hot/warm în TSDB cu retenție, cold în lake). `docker compose config` parsează, JSON conectori valide. **AC îndeplinit:** raw rece interogabil; OLTP mărginit de retenție. | 8 | P3 | H19.1.7 | Standalone |
| H19.5.4 🔨 | **Glob 3D + camera tours**. **Livrat:** toggle map⇄globe — store `viewMode` + `ViewToggle`; `DeckGlobe` randează cu `_GlobeView` (Deck.gl 9) pe o sferă-pământ întunecată (SolidPolygonLayer + graticule), fără Mapbox sub glob; click/tooltip/zoom în ambele moduri. **Camera tours livrate:** `lib/cameraTour.ts` (model waypoints pur/determinist + iterator, tur default peste AOI-uri din `NEXT_PUBLIC_TOUR_AOIS` / fallback Hormuz) + `CameraTour.tsx` (play/stop cu `FlyToInterpolator`, oprire la interacțiune). tsc clean, 80 vitest, build OK. | 5 | P3 | H19.5.1 | Standalone |
| H19.5.5 🔨 | **Observabilitate** (OTel trace end-to-end, dashboards Prometheus/Grafana, error budgets, runbooks). **Livrat (stack local-runnable):** `worldview/deploy/observability/` — OTel Collector + Prometheus + Grafana (provisionate), 3 dashboards golden-signal (API latency/throughput/erori; consumer-lag ingest; live/WS), reguli alertă (`KafkaConsumerLagHigh/Critical`, `ApiErrorRateHigh`, `ApiLatencyHigh`, `ApiDown`), `RUNBOOK.md`, `README.md`; `docker compose config` parsează, dashboard JSON + YAML valide. Lag-alarm + ingest-dashboard citesc metrici Redpanda `:9644`. **App-side livrat:** `/metrics` Prometheus pe backend-api (5 metrici — `http_server_requests_total`, `http_server_request_duration_seconds`, `worldview_ws_active_connections`/`_messages_sent_total`, `worldview_history_rows_written_total` — label-uri low-card `http_route`/`http_response_status_code`/`domain` care match dashboards) + OTLP opt-in (`otel.ts`, no-op fără `OTEL_EXPORTER_OTLP_ENDPOINT`); 208 teste backend, validat E2E /metrics pe server real. **AC îndeplinit:** dashboards golden-signal + alarmă lag + runbook + telemetrie live. | 5 | P2 | — | Both |
| H19.5.6 🔨 | **DR** (multi-AZ, promovare replică, Kafka mirror; test RPO/RTO). **Livrat:** `deploy/dr/` — replică streaming Postgres/TimescaleDB (`pg_basebackup -R`, hot standby read-only) + mirror Redpanda (`rpk cluster mirror` / fallback MM2) pentru `osint.*`; `game-day.sh` rulabil (`set -euo pipefail`, `bash -n` clean): preflight, replica-in-recovery, **RPO** = lag `pg_stat_replication` ≤5min, mirror topics, **RTO** = `pg_promote()` wall-time ≤30min + write-probe (`--promote`), PASS/FAIL. README cu prereq primary (slot/rol/`pg_hba`/`wal_senders`). `docker compose config` parsează. **AC îndeplinit (mecanică + drill local):** game-day rehearsabil cu ținte RPO≤5min/RTO≤30min; multi-AZ real necesită deployment multi-zonă. | 8 | P3 | H19.1.5 | Standalone |
| H19.5.7 🔨 | **Swarm captură OSINT cu agenți, guvernat** (snapshot cache efemer, rate-limit + provenance). **Livrat:** `worldview_ingest/capture/` — `TokenBucket`/`RateLimiter` (per-source + global, `now` injectat), `SnapshotCache` (TTL + drop-oldest, counters), `Snapshot` (`worldview.capture.v1`, provenance mereu prezentă: source/captured_at/trigger/run_id), `run_capture` guvernare pură (evict-expired→dedup→skip-active→rate-limit→snapshot+cache), worker async (own producer → `osint.capture`, no-op grațios). Wired în config/`__main__` (`capture` self-owned). 145 teste, ruff clean; core determinist (clock injectat); nu inventează semnale. **AC îndeplinit:** captură guvernată = snapshot la semnale efemere cu provenance + rate-limit. | 13 | P3 | H19.4.4 | Both |

> **Total ORIZONT 19:** 33 items, ~208 SP (WS1 38 · WS2 45 · WS3 31 · WS4 39 · WS5 55). **Primele 5 (the next concrete things):**
> H19.1.1 (ADS-B real) → H19.2.1+H19.2.2 (recon-window + alertă, wow maxim, reutilizează SGP4) → H19.3.1 (MCP server) →
> H19.3.4 (un watcher = bucla proactivă) → H19.4.3+H19.4.4 (provenance + audit). Plan complet & ADR-uri:
> [`worldview/docs/02-platform-architecture-and-delivery-plan.md`](worldview/docs/02-platform-architecture-and-delivery-plan.md).

---

## ORIZONT 20 — Hermes Mining (capabilități nete din `hermes-agent`, post-1.0) — 6/6 ✅

> Sursă: research [docs/research/2026-06-07-hermes-agent.md](docs/research/2026-06-07-hermes-agent.md) §7.
> Follow-up plan: [docs/research/2026-07-06-hermes-agent-migration-plan.md](docs/research/2026-07-06-hermes-agent-migration-plan.md)
> captures the v3 expert replication plan — reviewed by Fable 2026-07-07, APPROVED with notes (docs/handoff-fable-2026-07-07.md §5); the H20 live-wave
> below delivers its Phase 0–1 (the per-turn learning loop) — the remaining phases stay candidate scope.
> `hermes-agent` (NousResearch, MIT, ~185.7k★, activ) se suprapune masiv cu OpenClaw (are chiar
> `hermes claw migrate`), așa că **gap-urile de reach/UX sunt deja trackuite** din
> `2026-06-05-openclaw-feature-analysis.md`: canale (H12.16), node mesh (H12.17), canvas (H12.18),
> computer-use (H15), desktop Tauri (H11.1). Aici stau doar **capabilitățile NETE, specifice Hermes**.
> Importul SKILL.md / agentskills.io e deja închis (BUG-13). **Principiu (neschimbat):** adoptăm sub
> guvernare — fiecare capabilitate trece prin approval-queue / risk-gate / secret-broker / audit.
>
> **Unde Jarvis deja conduce (NU sunt gap-uri):** approval-queue + risk-gating, audit Merkle,
> secret broker (H15.4 ✅), secrete criptate, marketplace semnat (vs Skills Hub deschis), KG bitemporal
> + RRF + reflection (vs procedural memory mai plată), dual-LLM quarantine (H17), cost analytics +
> observability. Hermes conduce pe **actuation**; Jarvis pe **guvernanță/memorie/securitate** — același wedge.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H20.1 ✅ | **Tool-RPC în sandbox (`execute_code`)** — agentul scrie Python care apelează **tool-urile Jarvis** printr-un RPC local (Unix-socket) din interiorul sandbox-ului → „zero-context-cost pipelines" (orchestrează N tool-calls într-un script, fără round-trip prin contextul LLM per pas). Secretele NU sunt citibile în sandbox (peste secret broker H15.4). **Gated:** suprafața RPC pe allowlist + approval pe tool-uri tier-extern. Cel mai mare câștig net din Hermes. **Done 2026-06-09 (suprafață guvernată):** `core/tool_rpc.py` `ToolRPCServer` — **allowlist** (doar tool-uri înregistrate; necunoscut → refuzat), **risk-gating** (read-only inline; gated/extern → **task ask-tier**, nu rulează din sandbox; execută via executor `toolrpc` DOAR după aprobare), **secret-scrub** recursiv pe răspuns (sandbox-ul nu vede secrete). `run_pipeline` = N tool-calls fără round-trip LLM. Endpoints `GET /api/toolrpc/tools`, `POST /api/toolrpc/call`. Allowlist de start: `echo`/`time` (integrările adaugă tool-uri gated). +10 teste offline (allowlist, gating+enqueue, scrub secrete, pipeline, execute post-aprobare). *(Transport Unix-socket + clientul din sandbox + rularea codului = poartă host.)* | 13 | P2 | H15.4, `sandbox.py` | hermes-agent `execute_code` |
| H20.2 ✅ | **Lățime providere + hot-swap** — adaptor **OpenRouter** (o cheie → sute de modele) + comandă chat/admin de schimbare backend la cald (`/model …`), peste hybrid router-ul existent (Claude/Gemini/LM Studio/Ollama). **Done 2026-06-09:** `core/llm/openrouter.py` `OpenRouterBackend` (LLMBackend OpenAI-compat, bearer-auth, `strip_thinking`, client injectabil → offline-testable) + `parse_model_command` (`/model <id>` → swap; `/model` → list). Endpoint admin `POST /api/llm/openrouter` (parsează comanda + raportează disponibilitatea cheii). +4 teste offline. *(Cablarea live în HybridRouter + apelul de rețea = poartă host.)* | 5 | P2 | PR #133 (LM Studio control) | hermes `hermes model` / OpenRouter |
| H20.3 ✅ | **ContextCompressor runtime** — compresie de context pentru sesiuni lungi (rezumare / eviction inteligentă pe cale fierbinte), distinct de consolidarea nocturnă (H5.15). Se leagă de tema „sleep-time compute" (H13). **Done 2026-06-09:** `core/context_compressor.py` `ContextCompressor` — buget pe tokeni (chars/4), păstrează turele recente verbatim, **evictează inteligent** restul: rezumat via summarizer injectabil (LLM, deferred) SAU **digest determinist** pe importanță (lungime/întrebare/rol) offline. Endpoint `POST /api/context/compress`. +5 teste offline (sub-buget = no-op, compresie, summarizer injectat, fallback la digest la eșec). Distinct de consolidarea nocturnă H5.15. | 8 | P2 | H5.15 | hermes ContextCompressor |
| H20.4 ✅ | **Self-evolution (DSPy / GEPA)** — optimizare automată de prompturi/skill-uri din traiectorii (ShareGPT-style), gated prin decision inbox (reversibil). Extinde learning-loop-ul de agenți (H7.11) de la „ce agent" la „cât de bine e promptat". **Done 2026-06-09:** `core/self_evolution.py` — `TrajectoryStore` (traiectorii ShareGPT-style scored; best top-K per agent) + `propose_optimization` (din cele mai bune traiectorii → prompt optimizat: few-shot demos appended SAU optimizer DSPy/GEPA injectabil/deferred; **gated + reversibil**, `requires_approval`). +5 teste offline. | 8 | P3 | H7.11, H6.5 | hermes-agent-self-evolution |
| H20.5 ✅ | **Skill self-improvement + drift manifest** — rafinează skill-uri existente (nu doar `generate_skill` care doar creează) + manifest content-hash pt. detectarea modificărilor la sync `hermes update`-style. **Done 2026-06-09:** `core/skill_drift.py` — `manifest_hash` (content-hash sha256 whitespace-normalizat), `SkillDriftManifest` (`record`/`has_drifted`/`drift_report` → new/drifted/unchanged la sync), `refine_proposal` (rafinare a unui skill EXISTENT via refiner injectabil/deferred, gated+reversibil). +6 teste offline. | 5 | P3 | BUG-13, `loader.generate_skill` | hermes Skills Hub / `.bundled_manifest` |
| H20.6 ✅ | **Delegare dinamică de sub-agenți** — agentul poate spawna la runtime un sub-agent izolat (sesiune proprie), concurent (cap configurabil), gated. Extinde WorkflowEngine (H5.6) de la paralelism author-defined la spawn inițiat de agent. **Done 2026-06-09:** `core/subagents.py` `SubAgentManager` — `spawn` rulează un sub-agent în **sesiune izolată** (`session::sub-…`) printr-un **runner injectabil** (dispatch orchestrator în prod; stub offline), **cap configurabil** de concurență (`autonomy.max_subagents`, respins peste cap → 429), eliberat pe succes/eșec. Endpoints `GET /api/subagents`, `POST /api/subagents/spawn`. +5 teste offline (izolare sesiune, cap concurență, eșec capturat). | 8 | P3 | H5.6 | hermes `delegate_tool` |

> **Total Orizont 20:** ~47 SP, **post-1.0** (NU în gate-ul 1.0.0). Headline: **H20.1**.
> Secvențiere: H20.1 → H20.2 → H20.3 → (H20.4 ∥ H20.5 ∥ H20.6).

### H20 live-wave — bucla de învățare per-tură (2026-07-06)

> **Truth-in-docs (H7.8):** itemii H20.5/H20.6 de mai sus au livrat *suprafețe guvernate*
> (primitive pure + endpoints), dar **esența hermes-agent — bucla de învățare per-tură — nu era
> cablată live**: `refine_proposal` era apelat doar din teste, nimic nu distila fapte în CoreMemory
> per-tură, niciun ciclu de viață pentru skill-uri. Valul de mai jos o cablează, sub guvernare
> (deep-dive sursă hermes-agent + jarvis; adaptare MIT cu atribuire: `LICENSES/hermes-agent-MIT.txt`).
> **Default-OFF** (Product Posture O26-P2.4): totul e gated `cognition.enabled` + `cognition.review_enabled`.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H20.L1 ✅ | **IterationBudget + scoping sub-agenți** — `core/iteration_budget.py` (contor consume/refund thread-safe) + `subagents.py`: `DELEGATE_BLOCKED_CAPABILITIES` (delegate/memory_write/channel_send/skill_manage/clarify) înregistrat pe fiecare spawn și pasat runner-elor care acceptă `blocked`; buget total de spawn-uri opțional. **Done 2026-07-06**, +12 teste offline. | 2 | P2 | H20.6 | hermes `iteration_budget.py`, `delegate_tool.py` |
| H20.L2 ✅ | **Bounded core injectat + scanat + user profile** — `LivingMemory` primește `user_core` (inel CoreMemory separat pt. fapte despre user, `user_core.json`); blocul `[core memory]`/`[user profile]` e redat de `learning/core_block.py` (pur): fiecare intrare trece prin `detect_injection` (H17) → intrările flagged devin placeholder `[BLOCKED …]`, niciodată injectate; **frozen-snapshot per sesiune** în orchestrator (scrierile mid-session ating discul, nu prefixul promptului → prefix-cache stabil pe LM Studio/llama.cpp). **Done 2026-07-06**, +8 teste offline. | 3 | P2 | H21.3 | hermes `memory_tool.py` (MemoryStore) |
| H20.L3 ✅ | **Background review per-tură (distilatorul)** — `learning/background_review.py`: după fiecare tură (`_complete_llm_turn`), un task fire-and-forget face UN apel LLM structurat-JSON (**strict-local** by construction: `router.backend`) care propune fapte user/agent, corecții și update-uri de skill; **codul** (nu modelul) dispecerizează: fapte → inele bounded (scanate, deduplicate, cap `learning.review_max_facts`), corecții → `LearningModule.record_correction` (H21.4 își primește în sfârșit semnalele), skill nou → `generate_skill` → carantină CDX-8, patch → `skills/proposals.py` (pending) + `ActionApprovalQueue`. Cadență + buget zilnic (`learning.review_cadence` every_turn/every_n_turns/idle_gap, `learning.review_daily_budget`) — politica de cost pt. GPU local, pe care hermes nu o avea. Anti-capture rules portate (fără eșecuri de mediu / claim-uri negative / erori tranziente). Status pe `/api/cognition/learning` (fără rute noi). **Done 2026-07-06**, +14 teste offline. | 8 | P2 | H20.L2, H21.4 | hermes `background_review.py` |
| H20.L4 ✅ | **Ciclu de viață skill-uri + curator nocturn** — `skills/usage.py` (telemetrie sidecar în data-root: use/view/patch + provenance agent/import/bundled + pin + stare; hook best-effort în `Skill.execute`/`generate_skill`) + `skills/curator.py`: pass nocturn (fereastra reflector-ului, idempotent pe zi) — active → stale (30d) → **arhivat** (90d, directorul MUTAT în arhiva din data-root, niciodată șters); doar skill-urile **agent-created, ne-pinned** sunt curatabile (bundled/import/pinned intangibile); aplică patch-urile **aprobate de owner** hash-checked contra drift (`skill_drift`) cu backup reversibil; deciziile din ActionApprovalQueue se sincronizează în ledger. `refine_proposal`/manifest-ul H20.5 sunt acum consumate live. **Done 2026-07-06**, +19 teste offline. | 8 | P3 | H20.L3, H20.5, H10.18 | hermes `curator.py`, `skill_usage.py` |

> **Neportat intenționat (anti-teză):** Modal/Daytona/Singularity (exec serverless în cloud ≠ local-first),
> Nous Tool Gateway (pass-through-uri hosted ≠ privacy-first), lățimea de 20+ canale (H12.16 rămâne
> on-demand), paritatea desktop (post-1.0). Detalii: planul „Migrate hermes-agent's best features".
>
> **Review adversarial pre-merge (2026-07-06, 3 lentile × verify):** a prins și s-au reparat —
> (1) **CRITIC:** `HybridRouter.backend` preferă cloud-ul (Claude/Gemini) când există chei → review-ul
> ar fi trimis conversația în cloud; fix: `LLMRouter.local_backend` (fail-closed, strict-local);
> (2) purge-ul explicit (`clear_live_memory`) nu invalida snapshot-ul înghețat al core-block-ului →
> faptele uitate rămâneau injectate până la miezul nopții; fix: cache-ul e golit la purge;
> (3) provenance-ul skill-urilor generate era înregistrat pe slug, nu pe numele din registru → curatorul
> nu-l vedea; (4) `channel="subagent"` lipsea din skip-set (review per spawn). +8 teste regresie
> (`test_review_strict_local.py`, `test_review_findings_regressions.py`).

### H20 migration-plan Phase 3–4–5 primitive (Codex, 2026-07-06)

> Livrat de Codex în paralel cu valul de mai sus (agenți diferiți, fișiere disjuncte —
> zero coliziune), executând fazele rămase din planul „Migrate hermes-agent's best
> features" (`docs/research/2026-07-06-hermes-agent-migration-plan.md`). Acestea sunt
> **primitive pure, offline-testabile** — două dintre ele (H20.M3b/M3c) sunt deja
> **cablate live** în `Sandbox`; restul așteaptă integrarea runtime (execute_code prin
> Docker/SSH file-RPC, session model live în gateway).

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H20.M1 ✅ | **Provider registry declarativ (Phase 4, lite)** — `core/llm/providers/` `ProviderProfile`/`ProviderRegistry`: metadate statice per provider (auth type/env, base URL + env override, capabilities, fallback models) + `status()` care raportează `configured` fără să expună secrete. 6 profile built-in (lm-studio, ollama, gemini, anthropic, openrouter, openai-compatible). `HybridRouter.provider_catalog()` e un accessor READ-ONLY — nu schimbă deciziile de rutare (acelea rămân la `HybridRouter`/backend-urile existente). **Merged #625.** | 3 | P3 | — | hermes `providers/base.py` (ProviderProfile) |
| H20.M2 ✅ | **Channel session primitives (Phase 5, preliminar)** — `channels/session.py`: `SessionSource`/`DeliveryTarget`/`DeliveryDecision` (dataclass-uri pure) + `build_session_key()` (id determinist, filesystem-safe, din thread/sender/client) + `DeliveryRouter.resolve()` (decide send/skip pt. mesaje goale, surse silent/local-only, target explicit vs. home-channel). **Nu schimbă rutarea live a gateway-ului încă** — e fundația pt. continuitatea de sesiune cross-canal din plan. **Merged #626.** | 3 | P3 | — | hermes `gateway/session.py` (SessionSource) |
| H20.M3a ✅ | **Execution environment primitives (Phase 3, preliminar)** — `environments/__init__.py`: `EnvironmentProfile` pt. backend-urile suportate (local/docker/ssh — isolated/remote/supports_file_rpc), `build_cwd_marker`/`extract_cwd_marker` (protocolul de marcaj CWD pt. backend-uri remote), `scrub_child_env`/`prepare_python_child_env` (filtrare nume-secrete + allowlist prefixe sigure + `WINDOWS_ESSENTIAL_ENV_VARS` — jarvis e Windows-primary). **Merged #627.** | 5 | P2 | — | hermes `tools/environments/*`, `_scrub_child_env` |
| H20.M3b ✅ | **File-RPC primitives (Phase 3)** — `environments/file_rpc.py` `FileRPCStore`: store JSON UTF-8 request/response pe disc (scriere atomică tmp+replace), buget de tool-calls (`ToolCallLimitExceeded`), validare strictă a request-urilor. Fundația transportului remote (Docker/SSH) pt. `execute_code` — încă neconectat la `tool_rpc.py` live. **Merged #628.** | 5 | P2 | H20.M3a | hermes `code_execution_tool.py` (file-based RPC) |
| H20.M3c ✅ | **Output-limit helpers + wiring LIVE în Sandbox (Phase 3)** — `environments/output_limits.py` `truncate_text()` (buget pe bytes, head+tail, notă de trunchiere explicită, non-ascunsă). **#629** adaugă helper-ul; **#630** cablează `prepare_python_child_env` LIVE în `Sandbox._run_python`/`_run_shell` (child-ul de subprocess/Docker nu mai moștenește mediul host brut); **#631** cablează `truncate_text` LIVE în `Sandbox` (`max_output_bytes`, default 50_000) — stdout/stderr trec prin `_decode_output()` înainte de a ajunge în `SandboxResult`, închizând vectorul DoS-prin-output. **Merged #629, #630, #631.** | 5 | P2 | H20.M3a | hermes env-scrub + resource caps |

> **Total H20.M:** ~21 SP. Secvențiere spre integrare completă: H20.M3a/b → conectare la
> `tool_rpc.py`/`sandbox.py` pentru un backend SSH remote real (Phase 3 completă) →
> H20.M2 → cablare live în `gateway`/`channel_manager` (Phase 5 completă) → H20.M1 →
> extindere `/model` cu catalogul de provideri (Phase 4 completă).

### H20 Agent Runtime v2 — model-directed ToolRPC loop (2026-07-10)

> Owner-approved P0 execution slice from the Jarvis↔Hermes capability audit.
> The original 6/6 above counts its scoped primitives, not end-to-end Hermes parity.

| # | Item | S | P | Dep | Sursă |
|---|------|---|---|-----|-------|
| H20.R1 ✅ | **Agent Runtime v2 Wave 1 — LM Studio, default-OFF** — provider-neutral `ToolSpec`/`ToolCall`/`ToolTurn` protocol with source-compatible fallback; OpenAI-compatible LM Studio tool transport; Guardrails mediation; bounded model→ToolRPC→model loop over allow-listed `echo`/`time`, preserving trusted selected-agent identity plus contract, Action Kernel, approval and audit checks; JSON-only bounded results, iteration/fan-out limits and per-call/whole-loop deadlines; one shared `Agent.generate_response()` seam for normal and streamed turns; live `llm.tool_loop_enabled=false` and `llm.tool_loop_max_iterations=8` settings; regression and fake-LM-Studio reality-harness coverage. **Still open:** governed file/process tools; browser control and build launch/inspection; multimedia/binary artifact tools; browser SSE rendering for tool lifecycle events; cloud-provider tool-call transports; model-directed MCP discovery/execution and subagent delegation. **This is the execution spine, not a Hermes-parity claim.** | 13 | P0 | H20.1, O26-P1.1 | Hermes tool loop + owner audit 2026-07-10 |


---

## ORIZONT 21 — Cognition: Living Memory & Human-Like Personality (P1–P3) — 10/10 ✅

> **Cea mai importantă temă.** Un creier cognitiv pentru agenți: memorie **nelimitată, append-only,
> mereu valoroasă în timp** (uitarea = accesibilitate redusă + demotare pe tier, **niciodată ștergere**;
> doar utilizatorul șterge explicit) + personalitate **consistentă-dar-vie** ancorată pe **onestitate**
> (HEXACO Honesty-Humility, anti-sycophancy structural). Viitor-proof = **neuroplasticitate**
> (re-embedding pe modele mai bune, working-memory elastic). Rulează pe cortexul idle (night-shift).
>
> *(Renumerotat 19→20→21: ORIZONT 19 = WorldView (4D OSINT), ORIZONT 20 = Hermes Mining — ambele luate în alte sesiuni.)*
>
> **Complementar cu ORIZONT 20 (Hermes Mining):** Hermes conduce pe **actuation**, Cognition adâncește
> **memoria/personalitatea/guvernanța** — același wedge. Reutilizează exact primitivele unde „Jarvis deja
> conduce" (approval-queue, risk-gate, secret-broker, audit Merkle, KG bitemporal+RRF+reflection). **Nu
> dublează** bucla de skill din Hermes: H21.4 **hrănește + guvernează** H20.5 (skill self-improvement) și
> H20.4 (self-evolution DSPy/GEPA), nu le reimplementează.
>
> **Hartă schematică & diagnostic:** [`docs/COGNITION.md`](docs/COGNITION.md) (~35 analogii cu creierul,
> diagrame tier/flux, playbook simptom→cauză→remediu). **Context complet de sesiune:**
> [`docs/research/2026-06-07-cognition-and-tools-session.md`](docs/research/2026-06-07-cognition-and-tools-session.md).
>
> **Decizia de arhitectură (calitate pe termen lung):** un singur pachet `agents/core/cognition/` în
> spatele unui **`CognitionFacade`** înregistrat prin `ComponentRegistry` (1 linie în orchestrator + 2/handler) →
> **nu crește god-object-ul** (CLN-2/CLN-3). Stare tranzitorie pe un **`TurnContext` per-cerere** (repară **BUG-5**);
> stare durabilă în **`JsonStore`-uri locked, keyed** `(agent,user)`/`session` (nu atribute pe instanța partajată).
> **Master OFF = no-op măsurabil.** Reutilizează primitivele H14 deja livrate: `decay.py` (H14.4),
> `bitemporal.py` (H14.1), `consolidation.py` (H14.3), `entity.py`. *(SP-urile de mai jos nu sunt încă rulate în „Status General".)*
>
> **Metrica nord (conjunctivă, ne-gameable):** mastery/KC↑ cu calibration-error↓; accept-first-pass↑
> **cât timp** corectitudinea-gold ține (altfel alarmă de sycophancy); media trăsăturii urmărește μ cu
> varianță vie **și** pushback-reversal ≤0.05 la warmth ridicat; ID-orb ansamblu ≥80% **gated** de truth-audit.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H21.0 ✅ | **Schelet + fix BUG-5** — pachet `cognition/` + `CognitionFacade` (înregistrat în `ComponentRegistry`), `TurnContext` per-cerere, bază `JsonStore` locked+keyed, categorie settings `cognition` (toate OFF), `APIRouter`. **Zero schimbare de comportament.** **Done 2026-06-09:** pachet `core/cognition/` — `CognitionFacade` (înregistrat în `ComponentRegistry`, **master OFF = no-op**; sub-flag activ doar dacă master ȘI flag), `TurnContext` async-context-local (izolat pe taskuri concurente, ca fix-ul BUG-5), `KeyedStore` (JsonStore locked+keyed `(agent,user)`), **`APIRouter`** montat (`GET /api/cognition/status`) ca să nu crească web.py. +9 teste offline (no-op master, izolare context, store persist+reload, endpoint cu/fără orch). | 5 | P1 | — | master OFF = no-op măsurabil; `session_id` trece prin `TurnContext` (fără mutație pe instanța partajată → BUG-5 reparat); `/api/cognition/status` întoarce flagurile |
| H21.1 ✅ | **Cheia de onestitate** (start aici) — judecător anti-sycophancy/persona în `QualityMonitor` (axă deterministă în `signals` + judge LLM opțional **deferred**, nu inline); editare atribuire-în-caracter în `synthesize()`; metrica Sycophancy Index. **Done 2026-06-09 (cognition, gated):** `core/cognition/honesty.py` `HonestyModule` (înregistrat în `CognitionFacade`) — **axă deterministă** `sycophancy_signals` (flattery/agreement/capitulation; reversal‑under‑pushback = cel mai puternic semnal) + **Sycophancy Index** rulant (alertă peste prag) + `pushback_reversal_rate` pe probe set (AC ≤0.05) + **judge LLM deferred** (`HonestyJudge`, niciodată pe hot‑path). Cablat **gated** (`cognition.honesty_enabled`, master OFF = no‑op): scor pe fiecare trace în hook‑ul quality (paralel cu H10.23, nu‑l modifică) + `Agent.synthesize(in_character=)` păstrează vocile specialiștilor (param default‑False → fără schimbare când e off). Endpoint `GET /api/cognition/honesty`. +15 teste offline. | 5 | P1 | H21.0 | Sycophancy Index calculat & expus; pushback-reversal ≤0.05 pe probe set; `synthesize` păstrează vocile specialiștilor; judge rulează deferred (fără apel LLM pe hot-path) |
| H21.2 ✅ | **Afect + expresie de personalitate** — parser front-matter în `_load_soul` (corp vs `meta`; **reutilizează** parserul YAML-frontmatter introdus de BUG-13 în `loader._parse_manifest` dacă se potrivește); `affect/` (mood attractor, τ) + `personality/` (whole-trait sampler {μ,σ,skew}, seed reproducibil); injectează blocul în **ambele** prompt-buildere (`agent.process` + streaming `orchestrator.py:1115`); Objective·Obstacle·Tactic + dial de status; prosody în `tts.speak()` (afect în **cheia de cache**). Gated `cognition.affect_enabled`. **Done 2026-06-09 (cognition, gated):** `core/cognition/` — `personality.py` (whole-trait sampler {μ,σ,skew}, seed reproducibil; media realizată urmărește μ ±0.05 cu σ viu), `affect.py` (mood attractor valence/arousal, relaxare exponențială spre setpoint cu τ + clamp), `persona.py` `PersonaModule` (per-agent, seed stabil; `prompt_block` Objective·Obstacle·Tactic + dial de status; `prosody` cu cache_suffix), `frontmatter.py` (parser YAML SOUL → meta vs corp). `_load_soul` separă front-matter (no-op fără front-matter); injecție **gated** a blocului persona în `_run_agent` (acoperă ambele prompt-buildere — `agent.process` ȘI `orchestrator.process` trec prin `_call_agents_parallel`). Endpoint `GET /api/cognition/personality`. +15 teste offline. *(Prosody în `tts.speak` cache-key = descriptor expus + wire host-side la call-site-ul vocii.)* **Roster autorat 2026-08-18:** H21.2 livrase mașinăria, dar **niciun SOUL nu declara vreodată un bloc `personality`** → toți cei 17 agenți cădeau pe `DEFAULT_TRAITS` + un seed derivat din nume, deci numerele injectate în prompt la fiecare tură erau o **extragere aleatoare** care contrazicea proza SOUL de lângă ele (Gecko „no tone, just numbers" primea al 2-lea cel mai mare humor din cast; Friday „no metaphors, no wit" al 4-lea; Jarvis „ruthless about routing" ieșea 14/17 la assertiveness; Howard „mirrors the owner exactly" era fixat pe cea mai mare formality din cast). Toate cele 17 SOUL-uri declară acum `personality.traits` {μ,σ} + setpoint-uri `affect` derivate din propria secțiune Voice & Tone (ensemble min-distance **0.117 → 0.180**, ε=0.1 — distinct prin design, nu din noroc). Trei capcane de configurare reparate: front-matter parțial **fuzionează peste** setul implicit în loc să piardă tăcut celelalte patru trăsături; un `σ` omis moștenește liveness-ul implicit în loc să înghețe trăsătura la 0 (exact defectul „personality feels flat" din `docs/COGNITION.md` §7); iar ancora de drift a ansamblului e **μ**-ul configurat, nu o singură extragere aleatoare. `prompt_block` emite acum **directive comportamentale** bandate pe μ (numerele brute rămân telemetrie/prosody — un model local de 7–12B urmează „no jokes, no wordplay" mult mai fiabil decât „humor 0.32"), deci directivele nu pot nici să pâlpâie, nici să se reordoneze între ture, în timp ce mood-ul rămâne singurul strat care se mișcă. `Personality.sample()` avansează un RNG per-instanță în loc să re-semințeze la fiecare apel — altfel σ producea o singură extragere înghețată pentru tot procesul. Template-ul `_templates/SOUL.template.md` cere blocul explicit; Argus și-a primit secțiunea `Voice & Tone` lipsă. `tests/test_persona_roster.py` (+26). **Compoziția rosterului, același val:** **+Hestia** (`agents/hestia`, House Brain, tier foundation, local-only) — ORIZONT 30 livrase `agents/core/house/**` (graph, presence, actuation, home_assistant, camera_feed) + routerul montat, dar **niciun agent nu deținea casa**: Hephaestus *construiește*, Frigga știe *oamenii*, Steve ține *rackurile*; clădirea în sine nu avea proprietar. Rosterul ajunge la **18 activi = exact `cardinality_cap`** (următorul agent cere review-ul de arhitectură pe care regula îl impune). Wired: `ROUTING_TABLE` + regulă de intent `house` (vocabular neambiguu — RO „camera"/„lumina" excluse deliberat, „acasă" rămâne la Frigga, „șantier"/„construcție" la Hephaestus) + `agents_served` pe `homebridge`/`iot-control`. **−3 nume de pe bancă**: `atlas` (coliziune cu sub-brandul Atlas din `NERVA_VISION.md` §2), `hermes` (coliziune cu proiectul upstream față de care se benchmarkuiește repo-ul + mandat deja acoperit de `channel-route`-ul lui Jarvis), `aria` (în afara regulii `universe` + duplicat al lui `apollo`). **`promote_bench_agent` scria un stub fără front-matter** → orice agent promovat moștenea trăsăturile implicite (exact defectul reparat mai sus, reintrodus prin promovare) și conținea numele owner-ului hardcodat; acum scrie front-matter complet cu bloc persona placeholder marcat explicit ca „de autorat". Drift reconciliat: arhetipul lui Howard (registry vs SOUL), „14 active specialists" din SOUL-ul lui Jarvis, exemplul „15-agent" din Veronica (scos numărul — SOUL-ul intră în prompt). `scripts/status_sync.py --reuse-test-counts` regenerat (README/NERVA/GO_LIVE_PLAN/project-status.json) + STATUS/marketing la 18. `tests/test_persona_roster.py` (+10: registry↔SOUL, cardinality cap, coliziuni de nume pe bancă, stub-ul de promovare). | 8 | P2 | H21.0 | media realizată a trăsăturii urmărește μ ±0.05 cu σ viu; mood-ul se relaxează spre setpoint și se clampează; prosody diferă pe agent; cache-key include afectul |
| H21.3 ✅ | **Memorie vie, NELIMITATĂ** — reutilizează H14 (`decay`/`bitemporal`/`consolidation`/`entity`); **greenfield**: gate de encodare predictive-coding (înainte de `MemoryManager._lock`, în `VectorRecord.metadata`; detectează hash-fallback), 3-vector neuromodulator (DA/NE/ACh), pattern-separation la scriere / completion la citire, **TCM** re-rank post-fusion (nu atinge RRF); split `DailyReflector` în NREM/REM (idempotency **durabil** + multi-sesiune); nightly replay, tag-and-capture, **SHY** renormalizare, mentenanță (demotare pe tier, **NICIODATĂ ștergere**), **re-projection** (re-embed pe model nou, `embed_version`); stocare tiered hot/warm/cold; core mereu-injectat (bounded JsonStore). *(Compresia pe **cale fierbinte** e ORIZONT 20 H20.3 ContextCompressor — aici e consolidarea **nocturnă** + tiering + retenție nelimitată; complementare.)* **Done 2026-06-09 (strat algoritmic cognitiv, gated):** `core/cognition/memory.py` `LivingMemory` — **neuromodulatori DA/NE/ACh** + **gate de encodare predictive-coding** (surprise→encoding strength), **pattern-separation** (write) / **completion** (read), **TieredMemory** hot/warm/cold cu **mentenanță = demotare, NICIODATĂ ștergere** (doar user-forget), **TCM re-rank** post-fusion (nu atinge RRF), **re-projection** (`embed_version`, embedder injectabil), **core memory** bounded always-injected, consolidare **NREM/REM**. Înregistrat în facade; endpoint `GET /api/cognition/memory`. +16 teste offline. **Live recall delivered 2026-07-05 (#553):** `memory/living_recall.py` re-ranks already-fused `MemoryManager.recall()` hits whose ids match LivingMemory `turn_ref`, before `rag_guard` wraps them; `/api/memory/eval/run?mode=recall` adds a deterministic real-path eval mode. **DailyReflector integration delivered 2026-07-05 (#554):** durable `ReflectionRunStore` prevents same-day restart reruns, manual reflection uses `force=True`, and distilled lessons encode into LivingMemory/core only when `cognition.memory_enabled` is active, without copying raw transcript text into tier records. **Core prompt delivered 2026-07-05 (#555):** bounded `living.core` facts render into `_build_agent_turn_text()` behind `cognition.memory_enabled`, independent of vector recall. **Core persistence delivered 2026-07-05 (#556):** `CoreMemory(path=...)` stores the bounded fact ring via JsonStore and production `LivingMemory` uses `memory_logs/cognition/core_memory.json`. **Tier persistence delivered 2026-07-05 (#557):** `TieredMemory(path=...)` persists metadata records through add/access/maintenance/forget and production `LivingMemory` uses `memory_logs/cognition/living_tiers.json`. **Forget-purge follow-up delivered 2026-07-05 (#558):** `purge_data(memory=True)` deletes both cognition JSON stores and `clear_live_memory()` clears live `LivingMemory` core/tier state before at-rest deletion, so explicit user-forget remains the only true erase. **Re-projection maintenance delivered 2026-07-05 (#559):** `LivingMemory.reproject_stale(embedder=...)` persists upgraded vectors/embed versions for stale tier records, and `SchedulerService.run_memory_maintenance()` reports the default-off hook without requiring a live embedder. **Re-projection embedder follow-up delivered 2026-07-05 (#560):** nightly maintenance passes `MemoryManager.embed` when available and serializes structured tier content deterministically before embedding. **Recall-reactivation follow-up delivered 2026-07-05 (#561):** matched recall hits call `LivingMemory.access()` plus optional `DecayMemory.access()` so useful traces get warmer after being used. **Duplicate-gate follow-up delivered 2026-07-05 (#562):** exact duplicate turn digests map to zero surprise and skip another LivingMemory/decay write. | 13 | P2 | H21.0 | nimic auto-șters (doar demotare; user-forget = singura ștergere); reactivare cold→hot pe cue; calibrated-recall (still-true × (1−Brier), penalizare pe fapt depășit); re-projection upgradează vectorii vechi; consolidare idempotentă peste restart + multi-sesiune; S/N stabil pe măsură ce crește |
| H21.4 ✅ | **Învățare guvernată (semnalele, nu bucla)** — `learning/kc.db` (KC dual user+agent + **calibrare**); correction-ledger (extinde `preferences.py` + capturează edit-delta); **autonomie calibration-gated** (extinde `policy._apply_scoring` cu `kc_mastery`/`calibration`); kind-uri night-shift `practice`/`reinforce`. **NU reimplementează bucla de skill** — **hrănește + guvernează** ORIZONT 20 H20.5 (skill self-improvement) & H20.4 (self-evolution) cu semnale KC/calibrare/corecții + re-gating pe payload editat (BUG-11) + Docker forțat (HF-6). **Done 2026-06-09 (semnale, gated):** `core/cognition/learning.py` `LearningModule` — `KCStore` (mastery per `(component,scope=user|agent)` + **calibrare** mean-Brier), `CorrectionLedger` (edit-delta append-only), `calibration_autonomy_adjustment` (tier bump ≥0, **niciodată coboară gating-ul**), `practice_proposals` night-shift (`practice`/`reinforce` pe KC slabe/miscalibrate). **Autonomie calibration-gated**: `policy._apply_scoring` consultă un `calibration_hook` opțional (setat de orchestrator, gated `cognition.learning_enabled`, default no-op, doar adaugă prudență, plafonat la IRREVERSIBLE). Hrănește H20.4/H20.5, nu le reimplementează. Endpoint `GET /api/cognition/learning`. +10 teste offline (mastery, Brier, scoping, ledger, hook bump/no-op/plafon). | 13 | P2 | H21.0, H21.1, H20.5, H20.4 | mastery/KC↑ cu calibration-error↓; accept-first-pass↑ cât timp gold ține; auto-îmbunătățirea de skill (H20.5) e gated de calibrare + auto-revert la regresie; payload editat re-gated |
| H21.5 ✅ | **Ansamblu & maturare** — `personality_matrix.yaml` (casting) + assert de diversitate ε la boot; `synthesize` în stil regizor (păstrează vocile); drift ancorat-în-identitate (trimestrial, bounded ±0.10 lifetime, SOUL versionat git) + self-test psihometric nightly (tripwire); deltă relațională per-(agent,user). Drift/self-mod **reversibil + human-gated** (decision inbox). **Done 2026-06-09 (cognition, gated):** `core/cognition/ensemble.py` `EnsembleModule` — `diversity_check` (niciun agent în ε în spațiul trăsăturilor; raportează min-distance + violări), **drift ancorat-în-identitate** `bounded_drift` (clamp ±0.10 lifetime per trăsătură), `drift_proposal` **reversibil + human-gated** (`requires_approval`, nu se auto-aplică), `psychometric_selftest` (tripwire pe drift > prag), `relational_delta` per-(agent,user), `diff` inspectabil. Înregistrat în facade; endpoint `GET /api/cognition/ensemble`. +8 teste offline. *(Aplicarea drift-ului prin approval-queue + SOUL versionat H10.22 = wire de integrare.)* **AC-ul de diversitate devine real 2026-08-18:** până la autorarea rosterului (vezi H21.2) `diversity_check` trecea accidental — distanțele erau zgomot în jurul unei medii comune, cu min-distance 0.117 la un ε de 0.1 (marjă 17%). Cu caracterele autorate marja e 0.180 (80%), iar `bounded_drift` se ancorează în sfârșit pe μ-ul declarat în SOUL, nu pe o extragere aleatoare — plafonul ±0.10 lifetime măsoară acum abaterea de la identitatea autorului. Pinuit de `tests/test_persona_roster.py`. | 8 | P3 | H21.2, H21.4 | niciun agent activ în ε în spațiul trăsăturilor; ID-orb ansamblu ≥80% gated de truth-audit; drift bounded, inspectabil `/api/personality/diff` + revertibil; self-test psihometric declanșează pe drift |

### H21 — Itemuri adiacente din sesiune (tools open-source + hardware)

> Din evaluarea celor 10 tool-uri + analiza hardware (vezi `docs/research/2026-06-07-cognition-and-tools-session.md`).
> **Deja livrate (skip):** ollama, whisper, n8n. **Sidegrade (parcate):** plausible, cal.com, appflowy, **penpot (drop)**. **Off-mission:** fooocus.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H21.A ✅ | **Secrete în afara `.env` (vaultwarden)** — plugin `vaultwarden` + secret-resolver; Jarvis ia cheile API din vault self-hosted în loc de `.env` plaintext. Aliniat HF-5 (igienă chei) + local-first; se leagă de secret-broker H15.4. **Done 2026-06-09:** `core/secrets_vault.py` `VaultResolver` — rezolvă din vault (client injectabil) cu **fallback explicit** la env; sursă raportată (vault/env/missing); fără plaintext. +4 teste offline. *(Clientul HTTP vaultwarden = poartă host.)* | 5 | P2 | — | cheile se rezolvă din vault; fallback explicit; fără cheie în plaintext în config |
| H21.B ✅ | **Skill media (yt-dlp + Whisper)** — `skills/media/`: yt-dlp ia audio → STT Whisper existent → agent rezumă („rezumă acest video/podcast"). Compune cu ce există deja. **Done 2026-06-09:** `core/media_skill.py` `MediaSummarizer` — pipeline `summarize_url` (downloader→transcriber→summarizer injectabili); yt-dlp/Whisper = poartă host (→ `host_tools_unavailable` fără ele). +3 teste offline. | 3 | P3 | — | „rezumă <url>" → transcript + rezumat; binar `yt-dlp` opțional |
| H21.C ✅ | **Skill generare imagini pe idle** — kind `image_gen`; cere ziua → night-shift descarcă LLM via `LMStudioController` → ComfyUI/diffusers (Flux FP8) generează → reîncarcă LLM → livrează în brief/Telegram. $0, local, **fără contenție VRAM** (LLM descărcat). **Done 2026-06-09:** `core/image_gen.py` `ImageGenOrchestrator` — `generate` descarcă LLM → diffusion (injectabil) → reîncarcă LLM (**fără contenție VRAM**; restaurează LLM-ul ȘI la eșec). Backend diffusion = poartă host. +3 teste offline. | 5 | P3 | autonomy night-shift | imagine generată pe idle fără să blocheze chat-ul; swap LLM↔diffusion narat; backend diffusion configurabil |
| H21.D ✅ | **Prompt-builder video (cloud manual)** — LLM-ul local redactează/rafinează un prompt video pentru lipit manual în Gemini/Veo (opt-in, **$0 tokens API**). Helper mic, nu pipeline. **Done 2026-06-09:** `core/video_prompt.py` `build_video_prompt` — LLM injectabil rafinează ideea într-un prompt video gata de lipit; fallback template determinist; **$0 API**. +3 teste offline. | 2 | P3 | — | „prompt video pentru X" → prompt gata de lipit; fără apel API plătit |
| H21.E ✅ | **Import Drive „AI" via rclone (PRIVAT, onboarding/startup)** — `core/ingestion/drive_sync.py` `DriveAISync` (rclone = poartă host, runner injectabil) oglindește un folder Drive configurat de owner într-un dir **gitignored** (`memory_logs/drive_ai`, sub `$JARVIS_HOME`) → ingest via local-docs indexer (H12.2). Startup gated `JARVIS_DRIVE_AI_SYNC` (fire-and-forget) + `scripts/import_drive_ai.py`. **Privacy:** OAuth în `rclone.conf` al userului, conținut gitignored, doar numele remote-ului în env. **Done 2026-06-20** (+`tests/test_drive_sync.py`, 7 teste; doc `docs/dev/drive-ai-import.md`). | 3 | P2 | — | folderul Drive se importă local fără să atingă repo-ul; ingestat în memorie; nimic personal comis |

> **Notă hardware (nu e task):** laptop RTX 5090 (mobile, 24GB, power-capped) **nu se poate upgrada** la GPU.
> Imagini = local pe idle ($0). Video serios local = nod GPU pe LAN (~$2.8k desktop 5090) sau eGPU — **parcate**;
> video = manual via Gemini. *(Reconciliere doc:* `NERVA.md` descrie un desktop Windows/192GB — de aliniat cu Bonobo-ul real.)*

---

## ORIZONT 22 — Adopție OSS Runda 2: Performanță & Velocity (research 2026-06-20)

> Sursă: [`docs/research/2026-06-20-oss-adoption-perf-velocity.md`](docs/research/2026-06-20-oss-adoption-perf-velocity.md)
> — 13 repo-uri mapate la ținte la nivel de fișier (perf runtime + velocity dev).
> **Reconciliere cu H21** (`docs/research/2026-06-07-cognition-and-tools-session.md`): secret-vault =
> **deja livrat** (H21.A `secrets_vault.py`); **plausible / cal.com / appflowy = parcate (sidegrade)** sub H21;
> **penpot = drop**, **fooocus = off-mission** (image-gen idle livrat = H21.C); ollama/whisper/n8n = backend deja
> integrat. Itemurile de mai jos sunt **doar cele noi**, neacoperite de H21.

| # | Item | S | P | Dep | AC |
|---|------|---|---|-----|----|
| H22.1 ✅ | **Fan-out plugin concurent** (yt-dlp) — `plugin_gatherer.py`: eligibilitate (keyword+permission) separată de execuție; pluginele eligibile rulează cu `asyncio.gather` sub semafor + `wait_for`/plugin; eșec izolat (`E_PLUGIN_EXEC_FAIL`). **Done PR #264** (+`tests/test_plugin_gatherer_concurrency.py`). | 2 | P2 | — | turn cu N plugine → ~1 RTT, nu N; un plugin lent nu blochează turul; ordine deterministă |
| H22.2 ✅ | **Warm-up model local la pornire** (ollama) — `LLMBackend.warm_up()` + override Ollama (empty-prompt load + `keep_alive:-1`) + `LLMRouter.warm_up()`; `load_agents` îl lansează fire-and-forget post-`detect()`, gated `JARVIS_LLM_WARMUP`. **Done PR #264** (+`tests/test_llm_warmup.py`). | 2 | P2 | — | primul tur (voce) nu plătește cold-load; kill-switch `JARVIS_LLM_WARMUP=0` |
| H22.3 ✅ | **STT decode mai rapid** (faster-whisper) — `voice/stt.py` default greedy (`beam_size=1`) + `int8_float16` pe CUDA / `int8` pe CPU; override per-instanță/env (`JARVIS_STT_BEAM_SIZE`, `JARVIS_STT_COMPUTE_TYPE`). **Done PR #264** (+`tests/test_stt_config.py`). | 1 | P2 | — | latență STT mai mică pe enunțuri scurte; precizie reglabilă din env |
| H22.4 🟡 | **`OLLAMA_NUM_PARALLEL=2–4`** pe backend-ul Ollama — un tur voce + un apel de fundal se întrețes în loc de head-of-line blocking. **Runbook livrat** (`docs/GPU_RUNBOOK.md` §H22.4: NUM_PARALLEL + KEEP_ALIVE + flash-attn/KV-quant + verify). *Validare pe GPU = acțiune host, pending.* | 1 | P3 | — | 2 requesturi concurente pe același model nu se serializează |
| H22.5 ✅ | **Model-manager LRU fast↔deep** (Fooocus/ComfyUI `free_memory`) — track modele rezidente + unload LRU cu headroom înainte de load deep; anti-OOM-thrash în `hybrid_router`. Distinct de H21.C. **Spec:** `docs/superpowers/specs/2026-06-20-h22.5-model-manager-design.md`. **Cod livrat (PR #271):** `core/llm/model_manager.py` (LRU + headroom evict, narat) + adaptor de evicție Ollama + hook de rezidență în `synthesize()`, în spatele kill-switch; +`tests/test_model_manager.py`. *Validare GPU = acțiune host (nemăsurabil în CI).* | 5 | P3 | H22.2, H22.4 | swap fast↔deep fără OOM; evict LRU narat |
| H22.6 ✅ | **Workflow concurency bound** (n8n) — **descoperit:** engine-ul are deja gather pe batch-uri + timeout/pas (`_TIMEOUT`) + istoric prunat (`recent_runs` deque maxlen). **Gap real = fan-out nemărginit pe batch:** adăugat `_MAX_PARALLEL_STEPS=8` semafor în `engine.py` (un batch larg nu mai lansează zeci de apeluri LLM simultan). **Done** (+`tests/test_workflow_concurrency_bound.py`; 102 teste workflow verzi). *Offload pe worker-ul de autonomie = inutil (run-urile sunt deja async+timed) — descopat.* | 5 | P3 | — | ✅ fan-out batch ≤ cap; pas cu timeout; istoric mărginit (deja) |
| H22.7 🟡 | **superpowers + dev-skills jarvis** (`.claude/skills/`) — **livrate:** 4 SKILL.md (`jarvis-load-context`, `jarvis-add-route`, `jarvis-write-test`, `jarvis-add-plugin`) + README format superpowers. *Install plugin superpowers = acțiune host (1 cmd, documentat în README).* | 2 | P2 | — | skills repo trigger automat; pipeline TDD+plan+review după install plugin |
| H22.8 🟡 | **Trial codebase-memory-mcp** (`.mcp.json`) — **scaffold livrat:** `.mcp.json.example` (gitignored live config) + `docs/dev/codebase-memory-mcp.md` (setup + caveats). *Install binar + `index_repository` = acțiune host trial, pending.* | 2 | P2 | — | `index_repository` rulează; agentul găsește simboluri fără file-by-file |
| H22.9 ✅ | **Rute guvernate via MCP server** (BuilderIO/agent-native, *pattern*) — manifest acțiuni din OpenAPI; `mcp/server.py` expune rute allow-listed ca tool-uri MCP lângă agenți, reutilizând permission gate. **Spec:** `docs/superpowers/specs/2026-06-20-h22.9-agent-native-routes-design.md`. **Cod livrat:** read-only (PR #272) — `core/mcp/route_tools.py` derivă scheme din semnăturile handlerelor + allow-list; + mutating writes (PR #279) **în spatele unui al doilea kill-switch, default-off**; +`tests/test_mcp_route_tools.py`. | 5 | P3 | — | un client MCP poate conduce hub-ul prin rute guvernate |
| H22.11 ✅ | **Drift-check surse 3rd-party vendorate** — golul pe care Dependabot nu-l vede (cod vendorat: superpowers; tool doc-pinned: codebase-memory-mcp). `.github/third-party-manifest.json` + `scripts/check_thirdparty_drift.py` (consistency offline + drift vs ultimul release GitHub; fetcher injectabil) + workflow săptămânal `.github/workflows/thirdparty-drift.yml` (PR-gate consistency, deschide issue pe drift). Dependabot rămâne pt. pip/npm/actions. **Done 2026-06-20** (+`tests/test_thirdparty_drift.py`, 7 teste). **Refresh acceptat pe head exact (#829/#833, 2026-08-06):** Superpowers `6.1.1 → 6.2.0` este vendorat în `.claude/plugins/superpowers/` ca arborele upstream exact `da1e7bb99212a060f90ffd6def69ff606775a79c` din tagul adnotat `v6.2.0` (`0e5cc50e782429b95f933e46443898435b8b37a8` → commit `3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9`; ambele nesemnate); `LICENSE` upstream și `LICENSES/superpowers-MIT.txt` sunt MIT byte-identice (blob `abf0390320aa14406af7a520b9b0739fdda9bf08`, SHA-256 `0da33ed814ee87e72db078f489c4447af72f13d9f25d9e17476f32efd77705fc`); manifestul păstrează booleanul literal `auto_update: true` și toate câmpurile non-pin; nu se schimbă runtime-ul aplicației sau autoritatea/policy Nerva; rezidual Windows: updaterul poate primi `WinError 5` dacă directorul destinație are atributul ReadOnly, iar recovery-ul a fost strict path-scoped, fără schimbarea policy-ului. | 3 | P2 | H22.7, H22.8 | ✅ versiune vendorată în urma upstream → issue automat; manifest stale → PR roșu |
| H22.10 ✅ | **Follow-up `oauth.py` → vault** (bitwarden/H21.A) — `_resolve_token_key()` ia cheia din **vault/env `JARVIS_TOKEN_KEY`** (via `secrets_vault.VaultResolver`, H21.A) → cheia nu atinge discul; fallback legacy fișier **hardening 0600** + warning. `.env.example` documentează cheia. **Done** (+`tests/test_oauth_token_key.py`, 4 teste; 99 teste oauth/token verzi). | 3 | P2 | H21.A | ✅ cheia de criptare nu mai stă în plaintext pe disc; vault/env primar, fișier 0600 fallback |
| H22.12 ✅ | **Protocolul „Max"** (meta, 2026-08-11) — **`MAX.md`** (root): protocolul de finisare reutilizabil care duce tot ce promit docurile în produsul final — misiune, load de context redus, bucla run→slice→PR, **Feel Contract** (Nerva se simte la fel pe măsură ce motoarele/hardware-ul evoluează), **desirability gate** („AI for everyone": finish > polish > new), **entropie guvernată** (run names + Sparks). Trigger automat: skill `.claude/skills/max/` — codename-ul „Max" pornește/continuă protocolul fără întrebări. Ledgere: `docs/MAX_RUNS.md` (run-uri) + `docs/SPARKS.md` (entropie). Reguli relaxate în Max mode: `AGENTS.md` → „Max mode". | 2 | P1 | H22.7 | „Max" (orice casing) → run pornit fără explicații; fiecare run = un slice shippabil + rând în ledger; Sparks bounded, default-off, deletabile |

> **Stare (toate cele 3 valuri procesate):**
> - **Livrate cod+teste:** H22.1–3 (PR #264) · **H22.10** (securitate) · **H22.6** (workflow bound) ·
>   **H22.5** (model-manager LRU, PR #271 — validare GPU rămasă acțiune host) ·
>   **H22.9** (rute MCP guvernate, PR #272 read-only + #279 mutating default-off) · **H22.11** (drift-check). 8/10.
> - **Repo-side done, acțiune host rămasă (🟡):** H22.4 (runbook → validare GPU), H22.7 (skills →
>   install plugin), H22.8 (scaffold → install binar + trial). 3/10 *(se suprapun cu cele de sus)*.
> *(plausible/cal.com/appflowy NU se redeschid — decizie „sidegrade parcat" la H21; vezi nota de sus.)*

---

## ✅ Arhivă — H1–H4 + Sprint 0 (livrat în 0.5-beta)

> Toate itemurile H1–H4 sunt complet implementate. Detalii complete (67 items, 248 SP): [docs/HISTORY.md](docs/HISTORY.md).

---

## Testing Guide

> Cum testezi fiecare feature. Pentru comenzi rapide, vezi `docs/features/`.

```
Feature               Test command                          Ce verifici
─────────────────────────────────────────────────────────────────────────
All tests             python -m pytest tests/ -q            Toate feature-urile
Voice                 python tests/test_voice.py -v         STT → TTS pipeline
Telegram              python tests/test_telegram.py -v      Webhook + polling
OAuth                 python tests/test_oauth.py -v         Token refresh + PKCE
Calendar (Pepper)     python tests/test_calendar.py -v      CRUD evenimente
Gmail (Pepper)        python tests/test_gmail.py -v         Etichete, triage
Spotify (Jerome)      python tests/test_spotify_skill.py -v Play/pause/queue
Health (Hercules)     python tests/test_apple_health.py -v  Sleep/HRV/steps
Gecko (balance)       python tests/test_balance.py -v       ING/Libra/CSV/mock
Stark (analytics)     python tests/test_analytics_local.py -v  Local privacy-first KPIs (replaces GA4 mock, PR #276)
Security (Ultron)     python tests/test_security.py -v      Porturi, threats
System (Steve)        python tests/test_system.py -v        CPU/GPU/RAM/temp
n8n (Oracle)          python tests/test_n8n.py -v           CRUD workflow-uri
Sandbox               python tests/test_sandbox_gating.py -v Docker exec
Guardrails            python tests/test_guardrails.py -v    PII redact, injection block
Charts (admin)        python tests/test_admin_stats.py -v   Endpoint metrics
Learning              python tests/test_learning_live.py -v Health routing + promovare
Session               python tests/test_session*.py -v      Persistență + cross-channel
Bench                 python tests/test_bench_activation.py Bench promovare
Integration           python tests/test_agents_integration.py -v Toți agenții (SOUL+router+process)
Load                  python tests/test_load.py -v          15 paralel <30s
Smoke                 powershell smoke.ps1                  Server start + pytest
```

---

## Dependencies

| Resursă | Pentru | Cost |
|---------|--------|------|
| Google Cloud OAuth 2.0 | Pepper Gmail | Gratuit |
| Spotify Developer App | Jerome Spotify | Gratuit |
| Tavily API | Vision Research | Gratuit (1000/lună) |
| Discord Bot Token | Discord channel | Gratuit |
| Slack App Token | Slack channel | Gratuit |
| Docker (Qdrant, Neo4j, n8n) | H3.1, H3.2, H4.6 | Gratuit |
| n8n API Key | Oracle | Gratuit |
