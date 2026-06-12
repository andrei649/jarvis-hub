# Research: Bilawal Sidhu's "God's Eye" / WorldView — reverse-engineering report

> Provenance: supplied by the owner on 2026-06-12 (originally compiled 2026-04-23 by an external
> research agent, lightly adapted for jarvis-hub). Sidhu's WorldView is the **direct benchmark**
> for our WorldView (`worldview/`, see `worldview/docs/ROADMAP.md` §1). The UX-relevant findings
> of this report are absorbed into `docs/design/WORLDVIEW_UX_BRIEF.md` (§1, §7, §8, §11);
> engineering-relevant ideas (shader lenses, particle flow, NACp-derived jamming, photoreal
> tiles) are candidate post-1.0 backlog inputs, **not** committed scope.

---

## 1. Who is Bilawal Sidhu?

- **Former role:** Senior/Principal PM at Google (6 years) — AR/VR, 3D Maps, ARCore Geospatial
  API, Google Maps Immersive View. Helped build Google's **Photorealistic 3D Tiles** (the
  volumetric city models behind Google Earth's 3D cities).
- **Current:** solo creator; TED Tech Curator; A16z Scout; "Map the World" newsletter
  ([spatialintelligence.ai](https://www.spatialintelligence.ai), 35K+ subscribers); YouTube
  `@bilawalsidhu` (~180K subs); 1.6M+ cross-platform audience. Austin, TX.
- **GitHub:** no public repos for this project — **closed source**.

## 2. Key content

- **"Ex-Google PM Builds God's Eye to Monitor Iran in 4D"** (Mar 2026, 1.8M+ views) — WorldView
  reconstructing Operation Epic Fury: 6 data layers fused on a 3D globe, scrubbable
  minute-by-minute. *"Actual flight paths, actual satellite passes, actual GPS interference
  zones, actual ship movements. All from public data."*
- **"Ex-Google Maps PM Vibe Coded Palantir in a Weekend"** (Feb 2026, 290K+ views) — first demo:
  live air traffic, satellite orbits, CCTV feeds, shader effects. *"I didn't write this code by
  hand. I described features in voice notes and screenshots, threw them at multiple AI agents
  running simultaneously."*
- **"Your WiFi Can See You"** (Mar 2026) — WiFi sensing (CSI, 802.11bf, DensePose-from-WiFi);
  signals his ambient-sensing interests, not part of WorldView.

## 3. WorldView architecture (reverse-engineered)

### 3.1 Globe engine
- **Base:** Google **Photorealistic 3D Tiles API** (he states this explicitly) — volumetric
  photogrammetry city models, global scale.
- **Rendering:** custom WebGL pipeline + custom GLSL shaders directly over the native tile
  renderer (not Cesium / Mapbox / Three.js). UI layer: likely React/Next.js.

### 3.2 Data layers (8 feeds)

| # | Layer | Source / method |
|---|---|---|
| 1 | Live air traffic | OpenSky Network (~7,000+ aircraft) + **ADS-B Exchange** (uncensored crowdsourced military tracking) |
| 2 | Satellite constellations | CelesTrak NORAD TLE, 180+ sats (Capella SAR, Planet, Maxar; KH-11, BARS-M, Gaofen) — clickable 3D orbits |
| 3 | GPS jamming | **Derived**: aggregates NACp (GPS-confidence) from commercial ADS-B transponders — "mining the global fleet as a distributed EW sensor network"; red degraded-reliability zones |
| 4 | Maritime (AIS) | Commercial shipping, chokepoint focus (Hormuz tanker scatter) |
| 5 | Airspace restrictions | Live NOTAMs as dynamic 3D containment zones (the Iran→Iraq→Kuwait cascade) |
| 6 | Strike / geolocated events | OSINT geolocation, cross-referenced; "only graduated highest-confidence events to the map" |
| 7 | CCTV (beta) | Public municipal camera feeds **projected onto 3D building photogrammetry** |
| 8 | OSM vehicle flow | Street networks rendered as a moving **particle system** |

### 3.3 Shader / "lens" pipeline (the signature aesthetic)

Custom GLSL post-processing lenses: **CRT scan lines**, **night-vision (NVG)** green monochrome,
**FLIR thermal** (white-hot/black-hot), **anime cel-shading**, **military reticle** (screen-space
crosshairs/bounding boxes). His stated rationale:

> "Built from studying actual military display specifications — not for the aesthetics, but
> because those display systems were engineered to extract maximum information from sensor data."

### 3.4 Development & data handling
- Multi-agent "vibe coding": up to **8 concurrent AI agents** (Gemini/Claude/Codex), each owning
  a subsystem (satellite math, CCTV pipeline, GLSL, timeline sync); voice notes + screenshots as
  spec; terminal, no IDE.
- Ephemeral capture: an agent (triggered via WhatsApp) snapshotted all feeds **before caches
  cleared** during the event.
- All layers normalized to one epoch timeline → scrubbable replay. Polling-based feeds (no WS).

## 4. The larger vision: SpatialOS

WorldView is the demo. **SpatialOS** = a continuously-updating, queryable model of the physical
world, ingesting satellites/cameras/IoT, built to be read and acted on **by AI agents**, not just
humans. WorldView's public launch was slated ~April 2026 — *monitor for releases and any
open-source components*.

## 5. Key principles worth stealing

- **"Intelligence from nothing":** each public stream is meaningless alone; fused on one
  timeline + globe, "you get an understanding that *feels* like it should be classified."
- **"Negative space" intelligence:** what *disappears* is the story — transponders off → holes
  in the map; GPS confidence drops → EW active; "when 3,400 flights simultaneously clear an
  airspace, you don't need a security clearance to tell you what's coming."
- **Sousveillance framing:** "Same data streams. Same satellite feeds. Same CCTV cameras. But
  the interface is in your browser, and you control it." (Aligns with our ownership thesis.)

## 6. Gap analysis vs our WorldView

**He has / we don't:** photorealistic 3D city tiles; shader lenses; CCTV projection; OSM particle
flow; ADS-B-Exchange military feed; NACp-derived jamming (we use gpsjam.org's pre-binned H3);
his polish + audience.

**We have / he doesn't:** a production data path (Kafka→Redis/TimescaleDB, CI vs real infra);
true live WS + historical as-of-T API; provenance/chain-of-custody, RBAC, hash-chained audit,
cases, reproducible replay exports; recon-window *prediction*; **local-first + self-hosted +
open source**; and NL/agentic operation via the user's own AI (JARVIS/Argus) — his SpatialOS
ambition, but private and governed.

## 7. Candidate follow-ups (NOT committed; post-1.0 triage)

| Idea | Note |
|---|---|
| One restrained "demo lens" shader (view mode) | UX call first — see `WORLDVIEW_UX_BRIEF.md` §7; reject reticle/targeting cosplay |
| Trail/motion encodings (recency fade; particle restraint) | design-spec'd in the UX brief deliverables |
| ADS-B Exchange as additional ADS-B source | engineering; complements adsb.fi/OpenSky |
| NACp-derived jamming (own derivation vs gpsjam.org) | engineering; independence from one source |
| Photorealistic 3D tiles for focus AOIs | conflicts with local-first/opt-in-cloud — would need an explicit owner decision |
| Watch his April-2026 public launch | competitive monitoring; update `worldview/docs/ROADMAP.md` scorecard when it ships |

## 8. Sources (as supplied)

1. [I Built a Spy Satellite Simulator](https://www.spatialintelligence.ai/p/i-built-a-spy-satellite-simulator) — Substack (Feb 24, 2026)
2. [The Intelligence Monopoly Is Over](https://www.spatialintelligence.ai/p/the-intelligence-monopoly-is-over) — Substack (Mar 4, 2026)
3. [Your WiFi Can See You](https://www.spatialintelligence.ai/p/your-wifi-can-see-you-heres-how) — Substack (Mar 17, 2026)
4. [Ex-Google PM Builds God's Eye](https://www.youtube.com/watch?v=0p8o7AeHDzg) — YouTube (Mar 2026)
5. [Ex-Google Maps PM Vibe Coded Palantir](https://www.youtube.com/watch?v=rXvU7bPJ8n4) — YouTube (Feb 2026)
6. [The War You Can Watch in a Browser](https://kbssidhu.substack.com/p/the-war-you-can-watch-in-a-browser) — KBS Sidhu Substack (Mar 2026)
7. [LinkedIn](https://www.linkedin.com/in/bilawalsidhu) · [GitHub](https://github.com/bilawalsidhu) · [bilawal.ai](https://bilawal.ai)
