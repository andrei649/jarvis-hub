# Nerva Innovation Lab — external integration catalogue (RFC)

Status: `PRECURSOR CATALOGUE · DISCOVERY HYPOTHESES ONLY · DOES NOT DELIVER #805`.

Owner request: survey existing open-source projects Nerva could wire in,
broadly, without worrying about storage cost.

**Scope statement, stated truthfully.** This document is a *precursor* idea
catalogue. It does **not** implement the #805 control slice — the versioned RFC
template, status transitions, Knowledge Garden links, authority boundary and
integrity check — and its acceptance would not satisfy #805. Those remain
separate work, independently revertible, and are deliberately not bundled here.

**Dependency status — satisfied.** This flow was serialized behind the #804
handoff. That handoff is now delivered **and independently accepted**: PR #819
merged as `a6e8585`, landing `docs/nerva2/EXECUTION_PROVIDER_E8_1A.md` as the
accepted E8.1a discovery gate. The serialization condition is met.

That does not upgrade anything below. The E8.1a map is primary-verified; this
catalogue now records one bounded upstream README/commit read for MCP Registry,
not a complete adoption assessment. Its external adoption and
provider-promotion hypotheses stay `PARKED` for the reason in §0.

This document proposes nothing for production and promotes nothing.

## 0. Evidence level — read this before using any row below

Four evidence labels appear in Nerva discovery work, and conflating them would
be the exact failure the program forbids:

| Level | Meaning | Example |
|---|---|---|
| **Primary (read)** | a canonical upstream artifact was read directly and the read was recorded | accepted `docs/nerva2/EXECUTION_PROVIDER_E8_1A.md`; the immutable MCP Registry README/commit evidence recorded in §2 and Sources |
| **In-repository fact** | current Nerva code, dependency locks, tests or operator documentation prove a local surface, but not upstream suitability | Playwright's existing dependency, host-gated runtime and test surfaces |
| **Secondary** | search summaries or third-party articles support a discovery hypothesis | the unconfirmed activity, licence and capability findings in §2 and §3 |
| **Queued primary artifact** | an official repository or documentation link is identified for a future direct read, but was not read for this survey | the official links separated in Sources below |

**External adoption and provider-promotion hypotheses below remain secondary or
unverified unless a row says otherwise.** With the bounded MCP Registry
README/commit exception recorded below, upstream licence, activity and
capability claims still come from search summaries rather than a complete read
of each project's `LICENSE`, release history and source. No external project was
installed, run or benchmarked as part of this survey or correction.

Playwright is the bounded local exception to the old blanket statement: this
repository already pins `@playwright/test`, carries the host-gated
`agents/core/browser_playwright.py` runtime, and exercises it in tests and
operator documentation. Those in-repository facts do **not** verify the separate
hypothesis that Playwright should be promoted as a governed provider capability;
only that promotion hypothesis is parked below.

Consequence: **no external adoption or provider-promotion hypothesis here is
ready.** MCP Registry's README establishes technical local runnability, but not
adoption readiness. Each candidate still requires the same complete upstream
primary-source pass E8.1a did — an adoption pin, licence file, dependency
surface and API-stability assessment — before it can be proposed for an adapter
or deployment.

## 1. Why a catalogue does not make Nerva "able to do anything"

The owner's own program (#778) defines executability as five simultaneous
conditions:

```text
Executable(task) = technically_feasible
                ∧ capability_available_or_acquirable
                ∧ resources_and_credentials_available
                ∧ authority_and_policy_allow
                ∧ outcome_verifiable
```

A catalogue of integrations moves **one** of those — `capability_available`. It
does nothing for `authority_and_policy_allow` or `outcome_verifiable`, and it
actively *worsens* the security posture until each integration is governed.

So the ordering principle in this document is **verifiability first**, not
capability breadth. A capability Nerva cannot verify the outcome of is not a
capability; it is an unbounded risk with a nice name.

## 2. Findings that contradict common assumptions

These are the most valuable results of the survey, because each one would have
been wrong if taken from memory or from a year-old blog post:

| Project | Finding | Why it matters |
|---|---|---|
| **Daytona** | reported to have moved its production codebase **closed source in June 2026**, citing security; the original OSS repo remains public but unmaintained | a "self-hostable sandbox" assumption is now stale |
| **Piper TTS** | reported **archived / read-only since 2025-10-06**; still functions as a Home Assistant Wyoming add-on | fine to consume, wrong to build new work on |
| **Zep** | reported to have **retired the self-hosted Community Edition**; Graphiti itself stays open source | self-hosting story changed under the same brand |
| **MCP Registry** | its official README documents a local PostgreSQL development environment, offline file seeding and pre-built GHCR images | the previous categorical claim against self-hosting was false; local runnability does not establish production suitability or support |
| **Hermes Agent** | **no public API contract found** (primary-verified in accepted E8.1a) | argues for thin adapters everywhere, not deep coupling |
| **This repository's auto-update lane** | `update_thirdparty.py` rewrites the version token throughout a source's `update_doc` with no awareness of what else that file asserts, and the scheduled workflow has no opt-out (primary-verified in accepted E8.1a §4) | any integration added to `sources` inherits this; it is a gate on §4, not a detail |

**MCP Registry correction evidence — Primary (read), 2026-08-06.** A live read
found upstream `main` at
[`0b5cc0f6a9ba326d7982b4f03ea7da83bf7817a2`](https://github.com/modelcontextprotocol/registry/commit/0b5cc0f6a9ba326d7982b4f03ea7da83bf7817a2),
whose immutable
[`README.md`](https://github.com/modelcontextprotocol/registry/blob/0b5cc0f6a9ba326d7982b4f03ea7da83bf7817a2/README.md#L32-L63)
is Git blob `33ce33790ca4d4a56ccc36b7afb340cba8c26bad`. It documents:

- `make dev-compose`, which builds the registry image locally with `ko` and
  starts `localhost:8080` with PostgreSQL using ephemeral development storage;
- offline file seeding with `MCP_REGISTRY_SEED_FROM=data/seed.json` and
  `MCP_REGISTRY_ENABLE_REGISTRY_VALIDATION=false` — explicitly without registry
  validation;
- pre-built `ghcr.io/modelcontextprotocol/registry` images tagged `latest`, a
  release version, `main`, or `main-<date>-<sha>`. Those images do not bundle
  PostgreSQL; the operator must provide it and set `MCP_REGISTRY_DATABASE_URL`.

This directly proves a technically runnable local/self-managed path. It does
not prove a supported production topology, operational fitness, Nerva API
compatibility or safe adoption.

## 3. Catalogue

Classes reuse the E8.1a vocabulary: `reuse`, `thin_adapter`, `native_fallback`,
`reject`.

**Status vocabulary is #805 canonical:** `ACCEPTED_FOR_EPIC`, `PARKED`,
`REJECTED`. An earlier revision invented `Accepted for RFC`, which is not a
governed state.

**Every row below is `PARKED`, with exactly one stated exception.** No row has a
complete adoption-grade primary-source pass; the MCP Registry row has only the
bounded README/commit feasibility read recorded in §2. #805 does not permit
`ACCEPTED_FOR_EPIC` on partial or secondary evidence. Durable `REJECTED` is also
withheld for survey findings: a rejection whose premise came from a third-party
article could be wrong or already stale, and a wrong durable rejection is worse
than a park because it stops reconsideration.

**The exception** is the last row of Tier C — an external agent framework as
Nerva's brain. That one is `REJECTED` durably because it rests on an in-repo
primary source (`NERVA_VISION.md` §8 and #778 assigning planning to Cortex), not
on this survey.

Every parked row carries an explicit **reconsideration trigger**: the concrete
primary artifact or decision that would reopen it.

### 3.1 Tier A — closest to Nerva's accepted contracts

| Candidate | Gives Nerva | License (secondary) | Class | Status | Reconsideration trigger |
|---|---|---|---|---|---|
| **MCP servers ecosystem** | a standardised tool surface behind a protocol Nerva already speaks | mixed per server | `thin_adapter` | `PARKED` | primary pass on one chosen server: LICENSE read, exact pin, interface inventory |
| **MCP Registry codebase** | an official registry service with a documented local PostgreSQL development path | not assessed in this correction | `reuse` | `PARKED` — README feasibility only | select an exact adoption pin; assess `LICENSE`, dependencies, API stability and operations; then complete the full #805 contract and every §4 gate |
| **Home Assistant** | device/room/occupant graph and governed actuation (B6) | Apache-2.0 (unverified) | `thin_adapter` | `PARKED` | primary pass; Hermes also ships a `homeassistant` extra |
| **Frigate** | local camera event detection, no cloud | MIT (unverified) | `thin_adapter` | `PARKED` | primary pass; matches the local-first non-negotiable |
| **Playwright** (already in-repo) | deterministic browser control | Apache-2.0 (not re-read upstream here) | `reuse` | `PARKED` as a *provider surface* | dependency, runtime and test surfaces already exist; only promotion to a governed capability needs the additive §4 gates |

### 3.2 Tier B — strong candidates, real open questions

| Candidate | Gives Nerva | License (secondary) | Class | Status | Reconsideration trigger |
|---|---|---|---|---|---|
| **E2B** | Firecracker microVM isolation for untrusted code | Apache-2.0 | `thin_adapter` | `PARKED` — self-host is heavy | self-host requirements and session-lifetime limits read in upstream docs at source, plus an owner decision that a KVM control plane is acceptable |
| **browser-use** | LLM-driven browser agent over DOM + vision | permissive (unverified) | `thin_adapter` | `PARKED` — overlaps Hermes | an E8.1b decision on which single browser surface Nerva adopts; two stacks are not an option |
| **Stagehand** | typed `act`/`extract`/`observe` over Playwright | permissive (unverified) | `thin_adapter` | `PARKED` — TypeScript in a Python core | a decision that a TypeScript sidecar is acceptable, plus a LICENSE and API pass at source |
| **Letta** | OS-style tiered agent memory | Apache-2.0 (unverified) | `reject` **as memory authority** | `PARKED` — experiment only | an architecture decision that Atlas/Episodes cede memory authority. Currently forbidden by B3, so this is a CEO-level call, not a project comparison |
| **Graphiti** | temporal knowledge graph | open source (unverified) | `native_fallback` | `PARKED` — native surface exists | a measured comparison against `agents/core/memory/bitemporal.py` on a real temporal query set, through the E9 lane |
| **Whisper / faster-whisper** | local STT | MIT/permissive (unverified) | `thin_adapter` | `PARKED` | `LICENSE` **and model-weight licence** read at source — they can differ |
| **openWakeWord** | always-listening wake word without running STT continuously | permissive (unverified) | `thin_adapter` | `PARKED` | `LICENSE` and bundled-model licence read at source |
| **Kokoro / Coqui XTTS** | local TTS | unverified per project | `thin_adapter` | `PARKED` | per-project `LICENSE` read at source, **and** confirmation of the Piper archive claim that made these the candidates |
| **n8n** | 400+ prebuilt integrations, visual workflows | Sustainable Use (source-available, **not OSI**) | `thin_adapter` | `PARKED` — **license flag** | the Sustainable Use terms read in full at source and cleared for this deployment model. Until then it is not a candidate, it is a question |

### 3.3 Tier C — parked against a negative hypothesis

These carry a *negative* secondary finding. Per §0 they cannot become durable
`REJECTED` on secondary evidence alone: if the premise is wrong or has already
changed, a durable rejection would silently stop reconsideration.

| Candidate | Status | Negative hypothesis (secondary) | What would confirm or overturn it |
|---|---|---|---|
| **Daytona** | `PARKED` | production code moved closed-source 2026-06; OSS repo unmaintained | repository state and last-commit date read directly |
| **Piper TTS** | `PARKED` for new work | archived read-only since 2025-10-06 | repository archive flag read directly |
| **Zep (self-hosted)** | `PARKED` | self-hosted Community Edition retired | upstream docs/release notes read directly |
| Any external agent framework as Nerva's brain | **`REJECTED`** | — | **the one durable rejection here, and it rests on a primary in-repo source, not on a survey:** `NERVA_VISION.md` §8 and #778 assign planning to Cortex. Overturning it needs an architecture decision, not a better project |

## 4. Additional external-integration gates after the #805 minimum contract

These six gates are **additive** to #805's full RFC minimum contract; they do
not replace or narrow it. An RFC must first retain every #805 field, including
the owner outcome and alternatives, evidence and reuse/build/reject analysis,
authority/security/privacy/data-retention impact, baseline and falsification
plan, isolation rules, migration and rollback, and the decision record with its
reviewer and reconsideration trigger. Only then do these external-integration
gates apply. No row above satisfies both layers today:

1. **Primary-source pass** — read the `LICENSE`, pin an exact tag/commit, inventory the real interfaces, record the dependency surface. Same standard as E8.1a.
2. **Updater safety first, then a manifest entry.** Accepted E8.1a §4 establishes that adding a source to `.github/third-party-manifest.json` today enrols it in unattended auto-update that rewrites version tokens through its `update_doc`. Until a `drift_only`/manual policy or an honoured opt-out exists, a manifest entry is **not** a safe step. Anything not in the manifest is untracked supply chain — but enrolling it badly is worse.
3. **`nerva.capability.v1` declaration** — typed inputs/outputs, preconditions, privacy class, risk tier, verifier, rollback.
4. **Ultron mediation** — every privileged effect crosses `nerva.action.v1`. `grants_authority=false` immutable on any provider record.
5. **E9 measurement** — compared against the native baseline, with unmeasured dimensions left `not_measured`.
6. **Native fallback** — Nerva keeps working with the integration removed.

## 5. Honest cost note

The owner explicitly accepted large storage cost. Storage is genuinely the cheap
part. The expensive parts a catalogue this size actually incurs are:

- **maintenance surface** — every pinned upstream needs drift review;
- **security surface** — every integration is a new trust boundary, and today
  Hermes alone is already an untracked one (E8.1a §4);
- **verification debt** — an unverified capability cannot satisfy
  `outcome_verifiable`, so it cannot complete a governed task.

Recommendation: take **one** Tier A candidate — most plausibly the MCP server
surface, since Nerva already speaks the protocol — through a full primary-source
pass and the additive §4 gates before touching a second. One governed capability
is worth more than ten parked rows.

## 6. Nothing is forgotten

Every idea above carries exactly one #805-canonical status. All are `PARKED`
except a single `REJECTED` — the last Tier C row — which rests on an in-repo
primary source rather than on this survey. Every parked row, in all three tiers,
records the concrete artifact or decision that would move it, so reconsideration
is triggered by new facts rather than by a new opinion, and no row is quietly
stuck.

## 7. What this document is not

- not the #805 control slice — no RFC template, status-transition machinery,
  Knowledge Garden linkage or integrity check is implemented here, and accepting
  this catalogue would satisfy no #805 checkbox;
- not the #804 handoff — that separate E8.1a artifact was accepted through PR
  #819 as `a6e85854dfef82106d3f5c9980fa634de58a38c7`; this catalogue neither
  re-delivers nor advances it;
- not adoption-ready — the MCP Registry README/commit read establishes only
  local feasibility; no external adoption or provider-promotion hypothesis has
  completed the required adoption-grade primary-source and operational pass;
- not a capability promotion, dependency, manifest change or adapter.

## Source taxonomy and queue

Links are recorded so every hypothesis can be re-checked. Merely listing an
official repository or documentation page does **not** mean it was read: those
links remain queued until a direct-read pass records the exact artifact and
result. The MCP Registry evidence below is the bounded exception. The remaining
links are secondary discovery sources; none is promoted to primary evidence by
appearing here.

### Primary artifacts read directly

- [MCP Registry README blob `33ce33790ca4d4a56ccc36b7afb340cba8c26bad` at commit `0b5cc0f6a9ba326d7982b4f03ea7da83bf7817a2`](https://github.com/modelcontextprotocol/registry/blob/0b5cc0f6a9ba326d7982b4f03ea7da83bf7817a2/README.md#L32-L63)
  — read 2026-08-06; the commit was re-verified as upstream `main` and the read
  was limited to the local-run/seeding/image claims recorded in §2.

### Queued primary artifacts — official, not read in this survey

- [Frigate — blakeblackshear/frigate](https://github.com/blakeblackshear/frigate)
- [Frigate documentation](https://docs.frigate.video/)
- [MCP Registry — about (not read in this correction)](https://modelcontextprotocol.io/registry/about)
- [MCP servers — modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
- [n8n self-hosted AI starter kit](https://github.com/n8n-io/self-hosted-ai-starter-kit)

### Secondary discovery sources behind the survey hypotheses

- [awesome-sandbox — restyler](https://github.com/restyler/awesome-sandbox)
- [Daytona vs E2B (Northflank)](https://northflank.com/blog/daytona-vs-e2b-ai-code-execution-sandboxes)
- [Self-hosting a code execution sandbox (Beam)](https://www.beam.cloud/blog/how-to-self-host-code-sandbox)
- [Browser Use vs Stagehand vs Playwright MCP](https://fp8.co/articles/Browser-Use-vs-Stagehand-vs-Playwright-MCP-AI-Agent-Browser-Automation)
- [Browser automation for AI agents (fastCRW)](https://fastcrw.com/blog/browser-automation-ai-agents)
- [Self-hosting voice services — Andreas Schneider](https://blog.cryptomilk.org/2026/07/20/self-hosting-voice-services-tts-asr-wake-word/)
- [Local AI voice assistant stack 2026](https://dev.to/kunal_d6a8fea2309e1571ee7/local-ai-voice-assistant-stack-2026-whisper-piper-ollama-wired-together-572l)
- [Open-source memory layers comparison (GeniOS)](https://thegenios.com/blog/open-source-memory-layers-2026/)
- [Mem0 vs Zep vs Letta (Rohit Raj)](https://rohitraj.tech/en/notes/open-source-ai-agent-memory-mem0-vs-zep-letta-2026)
