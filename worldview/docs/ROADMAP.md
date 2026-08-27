# WorldView — Evaluation & Roadmap

> Where WorldView stands against the platforms that define this space, which of their ideas are
> worth adopting, and the phased plan to get there — as a **standalone product** *and* as a
> **JARVIS capability**.
>
> Benchmarks: **Bilawal Sidhu's "God's Eye View" / WorldView** (the consumer/journalist OSINT
> north star) and **Palantir** (Gotham + Foundry/AIP/Ontology + MetaConstellation/Apollo Edge —
> the enterprise/defense ceiling). Sources at the bottom.
>
> **The build-grade refinement of this roadmap** — target architecture, a quantified scalability
> model, component deep-dives, reliability/security/observability, deployment topologies, and a
> sequenced delivery plan with exit gates — is in
> [`02-platform-architecture-and-delivery-plan.md`](02-platform-architecture-and-delivery-plan.md).

---

## 1. The two reference points

### God's Eye View (Bilawal Sidhu / "WorldView")
A one-developer, public-data 4D OSINT reconstruction. For *Operation Epic Fury* (the June 2026
Iran strikes) he set an **AI-agent swarm** loose to capture ephemeral OSINT signals *before the
caches cleared*, then fused **six layers** — ADS-B (3,400+ aircraft), satellite constellations
(NORAD TLEs), GPS-jamming (aggregated from aircraft GPS-confidence), airspace closures / no-fly
zones, the Strait of Hormuz shipping halt, and electronic-warfare zones — into a **minute-by-minute,
scrub-able 3D globe**. The standout was an *analytical* moment, not just a map: **satellite passes
stacking over the strike zones** before and after impact — textbook collect → strike → battle-damage-
assessment behavior. Public launch was slated for ~April 2026.

**What makes it strong:** accessibility ("intelligence-grade analysis without a clearance"), the
**ephemeral-capture agent swarm**, the **insight/narrative** layer (it *explains*, not just shows),
and cinematic 3D. This is our **direct comparable** — we are at parity on the *layer set* and ahead
on *engineering rigor*, but behind on the capture swarm, the insight layer, and polish.

### Palantir (Gotham · Foundry/AIP/Ontology · MetaConstellation/Apollo)
The enterprise ceiling. **Gotham**: fuse structured + unstructured data, link/network analysis,
geospatial + mixed-reality, mission planning, **autonomous sensor tasking (human-in-the-loop)**,
strict access control. **Foundry + Ontology + AIP**: the **Ontology** is a semantic + kinetic model
of the world (objects, links, **actions**); **AIP** runs LLM agents *on* that ontology (AIP Logic,
Agent Studio, Evals) and — newest — **AI FDE: operate the whole platform in natural language**.
**MetaConstellation / Skykit / Apollo Edge AI**: dynamically task *across* satellite constellations,
run micro-models **on** the satellites, and do **tipping-and-cueing** between sensors.

**What makes it strong:** the **Ontology** (objects + actions, not just layers), **agents that
operate the platform in NL**, **tipping-and-cueing / sensor tasking**, and **governance** (access
control, audit, provenance) at scale. We will **not** match the data-integration breadth, classified
feeds, or real satellite tasking — but the **patterns** (ontology, NL-agentic operation, tipping-and-
cueing, governance) are exactly what we can adopt at an open-source, local-first scale.

---

## 2. Honest scorecard — WorldView today

`✅ have · ◑ partial · ⬜ gap` — measured against both benchmarks.

| Capability | God's Eye View | Palantir | WorldView today |
| --- | :--: | :--: | --- |
| Air / sea / space / cyber / context layers | ✅ | ✅ | ✅ schema + ingestion + render for all 5 |
| 4D time-scrub (live ↔ historical, one master clock) | ✅ | ✅ | ✅ the core engine, validated end-to-end |
| Dark-vessel detection (geofenced AIS gaps) | ✅ | ◑ | ✅ detector + dead-reckoning, tested |
| Satellite footprints + **recon-window** awareness | ✅ | ✅ | ◑ SGP4 + footprints + `is_sunlit`; no *prediction/alerting* yet |
| H3 EW / GPS-jamming grids | ✅ | ◑ | ✅ aggregation + render |
| Production data path (stream → store → serve) | ◑ | ✅ | ✅ Kafka→Redis/TimescaleDB, idempotent, **CI-tested vs real TimescaleDB** |
| Entity trails, tooltips, inspector, stats HUD | ◑ | ✅ | ✅ |
| **Live sources actually wired** | ✅ | ✅ | ⬜ workers are structured but endpoints are stubs |
| **AI-agent OSINT capture swarm** (ephemeral) | ✅ | ◑ | ⬜ |
| **Insight layer** (anomaly / tipping-cueing / pattern-of-life) | ✅ (manual) | ✅ | ⬜ only dark-vessel so far |
| Link / network analysis | ⬜ | ✅ | ⬜ |
| **Ontology / object model + actions** | ⬜ | ✅ | ⬜ (have a flat layer model) |
| **NL / agentic operation** of the platform | ⬜ | ✅ (AIP) | ⬜ — *this is the JARVIS opportunity* |
| Alerting / tipping-and-cueing rules | ◑ | ✅ | ⬜ |
| Provenance / chain-of-custody | ◑ | ✅ | ◑ envelope carries `source` + `ingested_at`; not surfaced |
| Collaboration / cases / multi-user | ⬜ | ✅ | ⬜ |
| Access control + audit | ⬜ | ✅ | ⬜ (JARVIS has Merkle audit + SSRF to reuse) |
| Sensor / satellite **tasking** | ⬜ | ✅ | ⬜ (out of scope — but *recon-window prediction* is our analogue) |
| Cinematic 3D globe + camera tours / export | ✅ | ✅ | ✅ CesiumJS globe + AOI tours + follow cam + sensor grades + export |

**Read:** WorldView has a **stronger technical spine** than a one-dev demo (validated streaming
data path, continuous aggregates, idempotent writers, 58 unit tests + real-infra integration tests,
CI) and full **layer breadth**. It is **behind** on (1) *live sources actually flowing*, (2) the
**AI capture + insight layer** (Sidhu's swarm; Palantir's AIP), (3) **governance/collaboration**
(Palantir), and (4) **cinematic polish**. The single biggest *differentiating* opportunity is the
one neither benchmark gives an individual: **operate it with your own private AI (JARVIS).**

---

## 3. What to adopt, what to skip

**Adopt from God's Eye View**
- The **AI-agent OSINT capture swarm** with **ephemeral-cache snapshotting** (record signals before they vanish) — *governed* (rate-limited, provenance-tagged).
- The **insight/annotation layer**: auto-callouts ("3 SAR passes stacking over this AOI", "airspace closing in a cascade").
- **Event reconstruction → shareable replay export** (the journalism use case).
- **Cinematic 3D globe** + camera tours.
- Actually wire the **live sources** (OpenSky/ADSB.fi, AISStream, Celestrak/Space-Track, IODA, GPSJam) + broader **AOIs** beyond Hormuz.

**Adopt from Palantir (the patterns, at our scale)**
- A lightweight **Ontology**: entities (vessel, aircraft, satellite, AOI, event) + **links** + **actions** — so the platform reasons about *objects*, not just points.
- **AIP-style NL / agentic operation** → **this is where JARVIS plugs in as our local-first "AIP."**
- **Tipping-and-cueing / alerting rules** and **AOI watchboards** (our *recon-window prediction* is the open-source analogue of MetaConstellation tasking — we can't task a satellite, but with SGP4 we can predict & alert *"a SAR pass will cover this AOI in 22 min"*).
- **Governance**: provenance / chain-of-custody, access control, audit — reuse JARVIS's Merkle audit + SSRF + guardrails.
- **Collaboration**: cases, annotations, multi-analyst.

**Explicitly skip / park** (stay in the open-source-intel, local-first lane): real satellite tasking,
edge-AI-on-satellites, petabyte data integration, classified feeds, a full Foundry-style pipeline
builder. Dual-use discipline: **OSINT analysis & reconstruction, not operational targeting.**

---

## 4. Dual-track architecture — standalone **and** JARVIS

WorldView is engineered as a self-contained stack (its own `frontend` / `backend-api` /
`ingestion-workers` / DB), so it ships **standalone** (journalists, OSINT researchers, maritime /
commodity desks, defense analysts) on the same self-host-free / hosted-pro model as JARVIS.

The multiplier is the **JARVIS integration: JARVIS becomes WorldView's "AIP"** — the natural-language,
proactive operator that no standalone competitor offers an individual. Integration design, mapped to
JARVIS's actual surfaces (see `docs/ARCHITECTURE.md`):

| JARVIS surface | WorldView integration |
| --- | --- |
| **MCP server** (`agents/core/mcp/client.py`) | WorldView exposes an **MCP server** with tools: `state_at(t, bbox, layers)`, `find_dark_vessels(aoi, window)`, `recon_windows(aoi, horizon)`, `watch_aoi(aoi, rules)`, `reconstruct_event(t0,t1,bbox)`, `track_of(entity)`. JARVIS already speaks MCP (H10.B / H16.1) → every WorldView capability becomes an **agent tool**. Cleanest, most-aligned path; keeps WorldView a separate process. |
| **Plugin** (`agents/core/plugins/`) | A thin `worldview.py` calling the WorldView API/MCP, behind `plugin_gate` (permissions). Lets **Athena / Stark (intel)** and **Vision (comms)** pull geospatial context into answers. |
| **Agent** (`SOUL.md`) | Optionally promote a bench agent to a geospatial-OSINT specialist ("Argus") that wields the WorldView tools. |
| **Autonomy / proactive cortex** (`autonomy/` inbox, digest, watchers) | WorldView **alerts** (dark vessel in Hormuz, recon window over an AOI, internet blackout, airspace-closure cascade) flow into JARVIS's autonomy queue → surfaced within the **≤4 urgent/day** budget. *This is the killer feature: JARVIS watches the world for you and tells you only what matters.* |
| **Memory / knowledge graph** (`memory/graph.py`, fused recall RRF) | WorldView entities/events become **facts + edges** in JARVIS's graph, so fused recall answers *"what happened in Hormuz last Tuesday"* and ties it to the rest of your memory. |
| **Channels** (web / telegram / voice) | Alerts + replies delivered through JARVIS channels, within the interrupt budget. |
| **Security** (`security/` SSRF, audit, guardrails) | Reuse for WorldView's outbound OSINT fetches + provenance audit. |

**Honoring JARVIS's non-negotiables** (MOONSHOT §5): WorldView is inherently *cloud-source-dependent*
(it fetches public APIs) — so it ships as an **opt-in plugin, never required by core**, every outbound
hop gated/auditable (principle #2), every alert **inspectable** back to its source signal (#3),
proactive-not-noisy (#4), and production-grade (#5, already true of the data path). It ingests **public
OSINT only** — aligned with *"your data trains no one's model."* The strict-local agents
(`frigga`/`ultron`/`howard`) never touch it.

---

## 5. The roadmap (phased, gated)

Gate discipline mirrors MOONSHOT: each phase has a "done when…" and we don't skip gates. Track:
**S**tandalone · **J**ARVIS · **B**oth.

### Phase A — Real sources & hardening · *gate: a real 24-hour replay from live data*
| # | Feature | Track | Notes |
| --- | --- | --- | --- |
| A1 | Wire real live feeds end-to-end (OpenSky/ADSB.fi, AISStream, Celestrak, IODA, GPSJam) | B | workers are structured; implement the `_fetch_*` bodies + creds/rate-limits |
| A2 | Run live-writer + history-writer in a real deployment (the Docker templates) | B | validate the Kafka→Redis/TimescaleDB path under live volume |
| A3 | AOI management beyond Hormuz (CRUD geofences, named AOIs) | B | generalize the `geofences` table; AOI picker in UI |
| A4 | Surface provenance (`source` + `ingested_at`) in the UI + API | B | chain-of-custody groundwork |
| A5 | Basemap / 3D polish: globe view, terrain, better styling | ✅ | Delivered on CesiumJS: keyless Natural Earth II basemap, optional ion imagery + world terrain |

### Phase B — The insight layer ("so what") · *gate: the platform explains an event, not just shows it*
| # | Feature | Track | Notes |
| --- | --- | --- | --- |
| B1 | **Recon-window prediction & alerting** (SGP4 → "SAR pass over AOI in 22 min") | B | our open-source analogue of MetaConstellation tasking; reuses propagation |
| B2 | **Tipping-and-cueing detector** ("N satellite passes stacking over an AOI") | B | Sidhu's headline insight, automated |
| B3 | More anomaly detectors: holding-pattern, airspace-closure cascade, jamming onset, blackout correlation | B | extends the dark-vessel pattern |
| B4 | Annotation / callout layer (auto + manual) on the timeline & map | B | the narrative layer |
| B5 | Event reconstruction + **shareable replay export** (video / link) | S | the journalism use case |

### Phase C — Agentic operation (JARVIS integration) · *gate: you can operate WorldView by talking to JARVIS, and it proactively surfaces world-events within budget*
| # | Feature | Track | Notes |
| --- | --- | --- | --- |
| C1 | **WorldView MCP server** with the tool suite (§4) | J | the linchpin; JARVIS already consumes MCP |
| C2 | JARVIS **plugin** + optional **intel agent** ("Argus") | J | `plugin_gate`-governed |
| C3 | **Autonomy watchers**: WorldView alerts → JARVIS inbox/digest within the ≤4/day budget | J | the killer proactive feature |
| C4 | **Knowledge-graph sync**: entities/events → JARVIS graph; fused recall over geo-events | J | "what happened in Hormuz last Tuesday" |
| C5 | NL querying ("dark vessels in Hormuz, last 6h"; "alert me on a SAR pass over this AOI") | J | AIP-equivalent, local-first |

### Phase D — Collaboration, governance & scale (Palantir patterns) · *gate: multiple analysts collaborate with provenance + audit; a reproducible event reconstruction*
| # | Feature | Track | Notes |
| --- | --- | --- | --- |
| D1 | Lightweight **Ontology**: objects + links + **actions** over the layers | B | reason about objects, not points |
| D2 | **Cases / annotations / multi-user**, sharing | S | analyst collaboration |
| D3 | **Access control + audit** (reuse JARVIS Merkle audit + SSRF + guardrails) | B | governance |
| D4 | Export / reporting (PDF/brief, GeoJSON, replay) | S | deliverables |
| D5 | Scale: validated LOD/cagg path under millions of points; perf budget | S | we built the LOD + caggs; load-test them |
| D6 | **Governed AI-agent OSINT capture swarm** (ephemeral-cache snapshotting) | B | Sidhu's swarm, rate-limited + provenance-tagged |

### Phase E — Product & ecosystem (business leaps, mirrors JARVIS Phases 2–3)
Hosted standalone tier · mobile/PWA · broader regions/AOIs · community AOI/rule sharing ·
(stretch) "recon-window-as-a-service" alerts.

---

## 6. Positioning / differentiation

- **vs God's Eye View:** the *engineered, self-hostable, agent-operable* version — a production data
  path with tests/CI **and** (uniquely) operable by your **own private AI** rather than a hosted SaaS.
  Own-your-data extends to your intelligence.
- **vs Palantir:** the *open-source-intel, local-first, personal/SMB* counterpart — not petabyte
  enterprise fusion or satellite tasking, but the same **patterns** (ontology, NL-agentic operation,
  tipping-and-cueing, governance) at an accessible scale, owned by the user. **"Palantir for the rest
  of us, on your own hardware."**
- **The moat is the synergy:** JARVIS is the local-first AIP; WorldView is its geospatial-intel
  domain. Together: a **private, proactive intelligence cortex that watches the world and tells you
  what matters** — exactly the MOONSHOT thesis (proactivity compounds; trust via inspectability)
  applied to OSINT.

## 7. The next five concrete things
1. **A1** — implement one real source end-to-end (ADS-B via OpenSky) so a live replay works.
2. **B1** — recon-window prediction + alert (highest-wow, reuses SGP4 we already have).
3. **C1** — stand up the WorldView **MCP server** with 3 tools (`state_at`, `find_dark_vessels`, `recon_windows`).
4. **C3** — one **autonomy watcher** (dark-vessel-in-Hormuz → JARVIS digest) to prove the proactive loop.
5. **A4 + D3** — surface provenance and add an audit trail (governance groundwork, reuses JARVIS security).

---

## Sources
- Bilawal Sidhu — God's Eye View / WorldView (Operation Epic Fury): [threads.com/@bilawal.ai](https://www.threads.com/@bilawal.ai/video/DVWrDNZiOyK/) · [x.com/bilawalsidhu](https://x.com/bilawalsidhu/status/2028708525484953912) · [analysis](https://informedclearly.com/en/ai/44408/osint-ai-agents-iran-strikes-4d-reconstruction-2024)
- Palantir **Gotham**: [palantir.com/platforms/gotham](https://www.palantir.com/platforms/gotham/)
- Palantir **Foundry / AIP / Ontology**: [AIP overview](https://www.palantir.com/docs/foundry/aip/overview) · [Ontology](https://www.palantir.com/platforms/ontology/) · [Nov 2025 announcements (AI FDE)](https://www.palantir.com/docs/foundry/announcements/2025-11)
- Palantir **MetaConstellation / Apollo Edge AI**: [Edge AI in Space](https://blog.palantir.com/edge-ai-in-space-93d793433a1e) · [Skykit](https://www.palantir.com/assets/xrfr7uokpv1b/6t9l63sr943zBFXimGUvva/f5839dd52211d3adf204623cce47a05b/AUSA_Skykit.pdf)
