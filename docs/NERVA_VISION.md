# Nerva — Personal Intelligence Operating System

> Strategic product vision for the project currently implemented in `jarvis-hub`.
> Nerva is the product brand. Jarvis remains the historical/internal project codename until the repository and package rename is deliberately executed.

## 1. Product thesis

**Nerva is a local-first Personal Intelligence Operating System that can perceive, understand, communicate, act, verify outcomes, and learn new capabilities under explicit human governance.**

Nerva is not optimized around `question → answer`. Its core loop is:

```text
Observe → Understand → Decide → Act → Verify → Learn
```

The target is a persistent intelligence layer across the user's digital and physical life: computers, browser, media, communications, home, cameras, devices, vehicles, projects, family context, and external events.

## 2. Brand architecture

- **Digitaholic** — company and publisher.
- **Nerva** — end-user product and primary identity.
- **Cortex** — cognition: reasoning, planning, memory, orchestration, autonomy, agent coordination.
- **Atlas** — reality model and infrastructure: WorldView, Signal Layer, geospatial intelligence, world events, house model, rooms, devices, vehicles, distributed nodes, servers and synchronization.
- **Synapse** — capabilities and learning: Capability Registry, skills, tools, connectors, discovery, generation, testing, promotion and reuse.
- **Vision** — visual perception: cameras, images, OCR, video understanding, surveillance events and visual computer use.
- **Ultron** — security and governance: Action Kernel, policies, contracts, permissions, taint, approval, audit, budgets and kill switches.
- **Howard** — personal identity and digital twin: voice, style, personal RAG, preference model and user-specific adaptation.
- **Frigga** — family intelligence: people, routines, care context and strict-local family memory.
- **Argus** — external intelligence role operating through Atlas: OSINT, geospatial monitoring and governed situational awareness.

The user should experience one coherent system — Nerva — rather than a collection of unrelated chatbots. Existing named agents may remain as specialist roles, personalities or internal services.

## 3. Atlas definition

Atlas is not merely cluster infrastructure. It is **Nerva's model of reality**.

```text
Atlas
├── WorldView — 3D/4D map, time, geospatial layers, air/sea/space/cyber
├── Signal Layer — evidence, events, signals, assessments and briefs
├── External world — weather, traffic, markets, incidents, news and OSINT
├── House model — properties, floors, rooms, zones, occupants and policies
├── Device graph — PCs, servers, Pi nodes, NAS, routers, TVs, speakers and sensors
├── Vehicle model — location, status, maintenance and telemetry
└── Execution topology — local, Docker, SSH, edge and optional cloud targets
```

Atlas provides the shared state against which Cortex reasons. Vision observes. Atlas locates and contextualizes. Cortex decides. Synapse supplies the capability. Ultron authorizes. Nerva executes and verifies.

## 4. Required product abilities

### 4.1 Perception

Nerva must ingest and correlate:

- surveillance cameras and event clips;
- microphones and room voice input;
- smart-home sensors and presence;
- computer, server, NAS and network health;
- calendar, email, messages and notifications;
- browser and desktop state;
- media devices and playback state;
- vehicles and external data feeds.

Continuous raw streams should be converted locally into structured events. Expensive model inspection should happen only when an event, query or policy requires it.

### 4.2 Communication

Nerva must communicate through:

- voice;
- HUD and generated visual surfaces;
- mobile;
- Telegram, Discord, Slack, email and future messaging adapters;
- televisions, monitors and smart displays;
- room speakers and private headphones.

Conversation context must survive movement between channels and devices. Delivery must account for user identity, room, privacy, urgency and household context.

### 4.3 Media and presentation

Nerva must be able to:

- play, pause, seek and route music, film, podcasts and radio;
- choose the correct TV, speaker or display;
- show webpages, maps, dashboards and camera feeds;
- move media between rooms;
- create temporary interactive visual surfaces;
- present private information only on appropriate devices.

The common abstraction should resemble:

```text
present(content, target, mode, privacy, urgency, duration)
```

### 4.4 Digital and computer action

Execution priority:

```text
API → CLI/script → structured browser/accessibility automation → visual mouse/keyboard fallback
```

Nerva must support:

- browser automation with accessibility-tree and CDP-first interaction;
- PowerShell, Bash, Python and JavaScript execution;
- local, Docker, SSH and edge execution targets;
- application control through native accessibility APIs;
- screenshot/vision-driven desktop operation when no structured interface exists;
- post-action verification and rollback where possible.

### 4.5 House brain

Nerva must model:

- houses and properties;
- rooms and zones;
- occupants, guests and permissions;
- sensors, cameras, displays, speakers and actuators;
- routines, presence and temporal patterns;
- climate, lighting, energy, security and media;
- household privacy and interruption policies.

Home Assistant/Homebridge may provide device abstraction, but Nerva owns reasoning, memory, policy, natural interaction and cross-domain coordination.

### 4.6 Camera intelligence

Vision + Atlas must provide:

- ONVIF/RTSP discovery and health monitoring;
- local motion and object detection;
- user-defined zones and line crossing;
- snapshots and short event clips;
- package, person, animal and vehicle events;
- natural-language retrieval over indexed events;
- privacy masks, retention rules and local-only defaults;
- escalation based on confidence, identity, zone and time.

### 4.7 Personality and humour

Nerva should communicate like a persistent companion rather than a command shell. Personality must include:

- contextual humour and callbacks;
- household-safe modes;
- user-specific tone and timing;
- avoidance of repetitive or forced jokes;
- the ability to shift between concise operational mode and richer conversational mode.

Humour is a social policy of the system, not a standalone joke generator.

### 4.8 Proactivity

Nerva must decide among:

```text
ignore | remember | monitor | act silently | ask approval | interrupt immediately
```

Proactivity requires:

- event bus and durable event history;
- anomaly and trend detection;
- routines and expected-state models;
- relevance scoring;
- notification and interruption budgets;
- confidence-aware escalation;
- verification after silent action.

### 4.9 Capability evolution

When Nerva cannot complete a request, it should be able to:

1. understand the intended outcome;
2. search the Capability Registry;
3. inspect available tools, APIs, devices and documentation;
4. produce a bounded implementation plan;
5. generate a temporary skill or adapter;
6. test it in an isolated environment;
7. verify read-only behavior first;
8. request approval according to risk;
9. execute and verify the real outcome;
10. promote the validated capability for reuse.

Generated capabilities never bypass Synapse validation or Ultron governance.

## 5. Capability Registry

Synapse should expose every action through a machine-readable capability contract.

```yaml
id: media.play
description: Play selected media on a target device
inputs:
  content: media reference or natural-language query
  target: device, room or audience
risk: reversible
implementations:
  - spotify
  - plex
  - jellyfin
  - chromecast
verification:
  - target reports playing
  - active item matches requested content
rollback:
  - restore previous playback state
```

Minimum capability families:

```text
browser.*
computer.*
script.*
file.*
message.*
media.*
display.*
home.*
camera.*
network.*
vehicle.*
world.*
skill.*
```

Capabilities, not agent names, become the stable execution interface.

## 6. Governance model

Nerva must be powerful without requiring approval for every harmless action.

| Action class | Default posture |
|---|---|
| Read sensors, state and public data | automatic |
| Show content or camera feeds | automatic within privacy rules |
| Play/pause media | automatic |
| Adjust lights/climate within learned bounds | automatic and reversible |
| Run diagnostics | automatic in sandbox |
| Modify files | versioned/backup first |
| Send external messages | approval or learned recipient policy |
| Install generated skills | sandbox + tests + approval |
| Purchases, destructive deletion, security disablement | explicit strong approval |
| Unlocking access or exposing private video | strong identity and context verification |

Authority is scoped by user, capability, device, target, location, time and context. Every meaningful action is auditable and outcome-verified.

## 7. Relationship to Hermes Agent

Hermes Agent is a strong reference for the execution plane:

- terminal target abstractions;
- browser automation;
- procedural skills;
- self-improvement loops;
- subagent delegation;
- context compression;
- messaging gateway patterns.

Nerva should adopt or integrate proven mechanisms where appropriate, but retain ownership of:

- personal and household world models;
- Atlas state and WorldView integration;
- Cortex cognition and specialist roles;
- Ultron governance and Action Kernel;
- camera intelligence;
- physical-device authority;
- ambient proactivity;
- media and presentation routing.

Hermes-derived components are hands and procedural learning. Nerva remains the brain, identity, policy layer and house operating model.

## 8. Version strategy

The current v1.0 definition — productionized and proven with real users — remains valid. The broader ambition must shape architecture now without turning v1.0 into an endless feature bucket.

### v1.0 — Trustworthy Nerva foundation

Required outcome: a stranger can install, understand and trust the system.

- productionized Cortex and Ultron foundation;
- persistent memory and governed autonomy;
- Capability Registry v1;
- browser/script execution through governed interfaces;
- media presentation MVP;
- Home Assistant/house-model MVP;
- camera health + event-ingestion MVP;
- first-run success and backup/restore;
- real owner soak and non-owner design-partner proof.

Not every adapter or advanced capability must ship. Each pillar must have one real end-to-end vertical slice.

### v2.0 — House and ambient intelligence

- complete room/device/occupant graph;
- richer media routing;
- local camera event intelligence;
- presence-aware proactive routines;
- distributed Atlas nodes;
- stronger mobile and voice continuity;
- household identity and permissions.

### v3.0 — General personal intelligence layer

- mature computer operator;
- autonomous capability acquisition;
- verified skill self-improvement;
- broad physical and digital orchestration;
- persistent multi-domain world model;
- long-running ambient reasoning;
- adaptive personality and relationship model;
- execution across local, edge and optional remote environments.

## 9. Delivery plan

### Program A — Foundations

1. Define Capability Contract schema and registry APIs.
2. Map existing plugins, skills, tools and actions into the registry.
3. Route all mutation through the Action Kernel.
4. Add outcome verification and rollback contracts.
5. Add execution-target inventory to Atlas.

### Program B — Computer operator

1. Adopt accessibility-tree/CDP browser interaction.
2. Add persistent browser profiles and visible-session handoff.
3. Standardize PowerShell/Bash/Python execution targets.
4. Add accessibility API adapters.
5. Add screenshot-based fallback with step verification.

### Program C — Media and surfaces

1. Define `present()` and target-selection contracts.
2. Add device discovery and room routing.
3. Integrate Spotify plus one local video backend.
4. Add webpage/dashboard/camera display surfaces.
5. Persist and restore media state.

### Program D — Atlas house model

1. Add properties, floors, rooms, zones, people and devices.
2. Import Home Assistant entities.
3. Add presence and room-context events.
4. Link devices, sensors, media and cameras to rooms.
5. Expose Atlas context to Cortex planning.

### Program E — Vision and surveillance

1. Camera discovery and health.
2. Local event pipeline.
3. Event storage with snapshots/clips.
4. Search and timeline integration in Atlas/WorldView.
5. Confidence, privacy and escalation policies.

### Program F — Synapse self-extension

1. Detect missing capabilities.
2. Research documentation through governed browser tools.
3. Generate skill packages from templates.
4. Run contract, security and integration tests.
5. Promote only after verification and approval.
6. Monitor failures and propose skill revisions.

### Program G — Ambient cognition

1. Durable event bus.
2. Monitor definitions and anomaly rules.
3. Relevance and interruption scoring.
4. Silent reversible-action policy.
5. Daily/weekly learning and routine refinement.

## 10. Gap assessment from the current repository

| Pillar | Current strength | Main gap |
|---|---|---|
| Cortex | strong orchestration, memory and specialist agents | unify around capabilities and world state |
| Ultron | unusually strong governance foundation | extend verification to physical/GUI outcomes |
| Synapse | skills/plugins/contracts already exist | mature registry and safe autonomous acquisition |
| Atlas | WorldView and Signal Layer are substantial | unify external world, house, devices and execution topology |
| Vision | image/media primitives exist | continuous local camera event intelligence |
| Computer operation | scripts, tools and MCP exist | mature browser, accessibility and visual desktop operation |
| Communication | broad channel surface | identity, room, privacy and cross-device continuity |
| Media | limited integration | unified device-aware presentation and playback |
| Proactivity | autonomy cortex exists | real-world event fusion and low-noise ambient operation |
| Product proof | extensive tests | real hardware soak, household usage and external users |

## 11. Definition of success

Nerva is succeeding when it can repeatedly demonstrate scenarios such as:

- detect a delivery, show the correct camera on the nearest screen, remember the event and notify only the relevant person;
- understand that a child is sleeping, move media to another room and lower volume without being asked twice;
- research an unsupported device, build and test a connector, request bounded approval and retain the capability;
- operate a browser or desktop application, verify the result and recover safely from failure;
- monitor house, network, NAS and cameras continuously without producing notification noise;
- coordinate information from WorldView, local sensors, calendars and personal priorities into one useful decision.

The product is not complete because it can answer anything. It is complete when it can **understand context, act safely across systems, verify reality and become more capable over time**.
