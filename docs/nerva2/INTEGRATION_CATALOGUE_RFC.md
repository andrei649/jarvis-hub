# Nerva Innovation Lab — external integration catalogue (RFC)

Status: `PRECURSOR CATALOGUE · DISCOVERY HYPOTHESES ONLY · DOES NOT DELIVER #805`.

Owner request: survey existing open-source projects Nerva could wire in,
broadly, without worrying about storage cost.

**Scope statement, stated truthfully.** This document is a *precursor* idea
catalogue. It does **not** implement the #805 control slice — the versioned RFC
template, status transitions, Knowledge Garden links, authority boundary and
integrity check — and its acceptance would not satisfy #805. Those remain
separate work, independently revertible, and are deliberately not bundled here.

**Dependency status.** This flow was serialized behind the #804 handoff. That
handoff is delivered as PR #819 but **#819 is open and unaccepted**, so this
document does not claim the dependency is satisfied. It is a discovery artifact
produced alongside, not downstream of, an accepted map.

This document proposes nothing for production and promotes nothing.

## 0. Evidence level — read this before using any row below

Two very different verification levels appear in the Nerva discovery documents,
and conflating them would be the exact failure the program forbids:

| Level | Meaning | Example |
|---|---|---|
| **Primary** | a canonical artifact was read directly | `docs/nerva2/EXECUTION_PROVIDER_E8_1A.md` — `pyproject.toml`, release tag and commit read at source |
| **Secondary** | search results and third-party articles | **everything in this document** |

**Every candidate below is secondary-verified only.** License, activity and
capability claims come from search summaries, not from reading each project's
`LICENSE`, release history or source. No project here has been installed, run,
benchmarked or read.

Consequence: **no row here is adoption-ready.** Each requires the same
primary-source pass E8.1a did — exact pin, license file, dependency surface,
API-stability assessment — before it can be proposed for an adapter.

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
| **MCP Registry** | maintainers state the registry codebase **is not designed for self-hosting** and is unsupported if forked | consume the API; do not plan to run it |
| **Hermes Agent** | **no public API contract found** (primary-verified in E8.1a) | argues for thin adapters everywhere, not deep coupling |

## 3. Catalogue

Classes reuse the E8.1a vocabulary: `reuse`, `thin_adapter`, `native_fallback`,
`reject`.

**Status vocabulary is #805 canonical:** `ACCEPTED_FOR_EPIC`, `PARKED`,
`REJECTED`. An earlier revision invented `Accepted for RFC`, which is not a
governed state.

**Every row below is `PARKED`.** None has a primary-source pass, and #805 does
not permit `ACCEPTED_FOR_EPIC` on secondary evidence. Durable `REJECTED` is also
withheld: a rejection whose premise came from a third-party article could be
wrong or already stale, and a wrong durable rejection is worse than a park
because it stops reconsideration. Each row therefore carries an explicit
**reconsideration trigger** — the evidence that would move it.

### 3.1 Tier A — closest to Nerva's accepted contracts

| Candidate | Gives Nerva | License (secondary) | Class | Status | Reconsideration trigger |
|---|---|---|---|---|---|
| **MCP servers ecosystem** | a standardised tool surface behind a protocol Nerva already speaks | mixed per server | `thin_adapter` | `PARKED` | primary pass on one chosen server: LICENSE read, exact pin, interface inventory |
| **Home Assistant** | device/room/occupant graph and governed actuation (B6) | Apache-2.0 (unverified) | `thin_adapter` | `PARKED` | primary pass; Hermes also ships a `homeassistant` extra |
| **Frigate** | local camera event detection, no cloud | MIT (unverified) | `thin_adapter` | `PARKED` | primary pass; matches the local-first non-negotiable |
| **Playwright** (already in-repo) | deterministic browser control | Apache-2.0 | `reuse` | `PARKED` as a *provider surface* | already a dependency for tests; promoting it to a governed capability needs the §4 gate |

### 3.2 Tier B — strong candidates, real open questions

| Candidate | Gives Nerva | License (secondary) | Class | RFC status |
|---|---|---|---|---|
| **E2B** | Firecracker microVM isolation for untrusted code | Apache-2.0 | `thin_adapter` | `PARKED` — self-host needs Firecracker/KVM + a Nomad/Consul control plane; heavy, and sessions are reported short-lived |
| **browser-use** | LLM-driven browser agent over DOM + vision | permissive (verify) | `thin_adapter` | `PARKED` — overlaps Hermes' browser tools; pick one, do not run two |
| **Stagehand** | typed `act`/`extract`/`observe` over Playwright | permissive (verify) | `thin_adapter` | `PARKED` — cleanest abstraction, but TypeScript in a Python core |
| **Letta** | OS-style tiered agent memory | Apache-2.0 | `reject` **as memory authority**, `thin_adapter` as experiment | `PARKED` — Atlas/Episodes are canonical; a second memory authority is the drift B3 warns about |
| **Graphiti** | temporal knowledge graph, time-aware facts | open source (verify) | `native_fallback` | `PARKED` — Nerva already has a bi-temporal KG (`memory/bitemporal.py`); compare, do not replace |
| **Whisper / faster-whisper** | local STT | MIT/permissive (unverified) | `thin_adapter` | `PARKED` — primary pass needed |
| **openWakeWord** | always-listening wake word without running STT continuously | permissive (unverified) | `thin_adapter` | `PARKED` — primary pass needed |
| **Kokoro / Coqui XTTS** | local TTS | unverified per project | `thin_adapter` | `PARKED` — candidate *instead of* Piper, on the secondary claim that Piper is archived |
| **n8n** | 400+ prebuilt integrations, visual workflows | Sustainable Use (source-available, **not OSI**) | `thin_adapter` | `PARKED` — **license flag** — the fair-code terms must be read before any dependency |

### 3.3 Tier C — parked against a negative hypothesis

These carry a *negative* secondary finding. Per §0 they cannot become durable
`REJECTED` on secondary evidence alone: if the premise is wrong or has already
changed, a durable rejection would silently stop reconsideration.

| Candidate | Status | Negative hypothesis (secondary) | What would confirm or overturn it |
|---|---|---|---|
| **Daytona** | `PARKED` | production code moved closed-source 2026-06; OSS repo unmaintained | repository state and last-commit date read directly |
| **Piper TTS** | `PARKED` for new work | archived read-only since 2025-10-06 | repository archive flag read directly |
| **Zep (self-hosted)** | `PARKED` | self-hosted Community Edition retired | upstream docs/release notes read directly |
| **Self-hosting the MCP Registry** | `PARKED` | maintainers state it is not designed for self-hosting | maintainer statement read at its source |
| Any external agent framework as Nerva's brain | **`REJECTED`** | — | **the one durable rejection here, and it rests on a primary in-repo source, not on a survey:** `NERVA_VISION.md` §8 and #778 assign planning to Cortex. Overturning it needs an architecture decision, not a better project |

## 4. What every accepted RFC must pass before it becomes an adapter

No exceptions, and none of these are satisfied by any row above today:

1. **Primary-source pass** — read the `LICENSE`, pin an exact tag/commit, inventory the real interfaces, record the dependency surface. Same standard as E8.1a.
2. **Manifest entry** — added to `.github/third-party-manifest.json` so `check_thirdparty_drift.py` tracks it. Anything not in that manifest is untracked supply chain.
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
pass and the §4 gate before touching a second. One governed capability is worth
more than ten parked rows.

## 6. Nothing is forgotten

Every idea above carries exactly one #805-canonical status. All are `PARKED`
except a single `REJECTED` that rests on an in-repo primary source rather than on
this survey. Each park records the evidence that would move it, so
reconsideration is triggered by new facts rather than by a new opinion — and so
that no row is quietly stuck.

## 7. What this document is not

- not the #805 control slice — no RFC template, status-transition machinery,
  Knowledge Garden linkage or integrity check is implemented here;
- not a claim that the #804 handoff is accepted — #819 is open;
- not adoption-ready — no row has a primary-source pass;
- not a capability promotion, dependency, manifest change or adapter.

## Sources

Secondary sources consulted for §2 and §3, recorded so the claims are auditable
and re-checkable:

- [Frigate — blakeblackshear/frigate](https://github.com/blakeblackshear/frigate)
- [Frigate documentation](https://docs.frigate.video/)
- [awesome-sandbox — restyler](https://github.com/restyler/awesome-sandbox)
- [Daytona vs E2B (Northflank)](https://northflank.com/blog/daytona-vs-e2b-ai-code-execution-sandboxes)
- [Self-hosting a code execution sandbox (Beam)](https://www.beam.cloud/blog/how-to-self-host-code-sandbox)
- [Browser Use vs Stagehand vs Playwright MCP](https://fp8.co/articles/Browser-Use-vs-Stagehand-vs-Playwright-MCP-AI-Agent-Browser-Automation)
- [Browser automation for AI agents (fastCRW)](https://fastcrw.com/blog/browser-automation-ai-agents)
- [Self-hosting voice services — Andreas Schneider](https://blog.cryptomilk.org/2026/07/20/self-hosting-voice-services-tts-asr-wake-word/)
- [Local AI voice assistant stack 2026](https://dev.to/kunal_d6a8fea2309e1571ee7/local-ai-voice-assistant-stack-2026-whisper-piper-ollama-wired-together-572l)
- [Open-source memory layers comparison (GeniOS)](https://thegenios.com/blog/open-source-memory-layers-2026/)
- [Mem0 vs Zep vs Letta (Rohit Raj)](https://rohitraj.tech/en/notes/open-source-ai-agent-memory-mem0-vs-zep-letta-2026)
- [MCP Registry — modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry)
- [MCP Registry — about](https://modelcontextprotocol.io/registry/about)
- [MCP servers — modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
- [n8n self-hosted AI starter kit](https://github.com/n8n-io/self-hosted-ai-starter-kit)
