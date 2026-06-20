# WorldView + WorldMonitor Fusion Strategy

## Product thesis

Jarvis should take the best parts of both systems, but merge them at the product and architecture layer rather than blindly mixing code.

```text
WorldView    = Jarvis-owned 4D geospatial OSINT surface
WorldMonitor = external public-world intelligence provider
Signal Layer = Jarvis-owned fusion brain
Argus        = agent interface over the fusion brain and geospatial tools
```

## What to keep from Jarvis WorldView

| Capability | Why it stays |
|---|---|
| 4D globe / map surface | Jarvis-native situational UI and time-scrubbable visual context |
| Existing `worldview/` stack | Already integrated with `START.bat`, local Docker infra, and Argus bridge |
| Provenance and ontology routes | Strong fit for Jarvis governance and graph memory |
| Local-first posture | Matches Jarvis privacy and approval architecture |
| Argus agent identity | Best existing agent wrapper for geospatial and OSINT questions |

## What to take from WorldMonitor

| Capability | How Jarvis should use it |
|---|---|
| 500+ feed breadth | Feed Signal Layer as external-world signals |
| Country Instability Index / country risk | Normalize into Jarvis `Assessment` objects |
| Market/cyber/aviation/disaster coverage | Normalize into typed `Signal` objects |
| MCP resources/tools | Consume through `WorldMonitorProvider` instead of scraping UI |
| Freshness/source discipline | Carry into Jarvis evidence ledger and source drawer |
| Local AI / self-host options | Optional live provider mode; replay remains demo-safe |

## Non-negotiable boundary

WorldMonitor is AGPL-licensed. Do not copy WorldMonitor implementation code into Jarvis's MIT codebase unless the licensing strategy changes. Prefer one of these patterns:

1. Run WorldMonitor as an external sidecar and call it through MCP/HTTP.
2. Reimplement specific concepts clean-room inside Jarvis.
3. Keep an AGPL component clearly separated with correct notices and source availability.
4. Obtain separate commercial/private-source terms before proprietary reuse.

## Target architecture

```text
Existing WorldView stack (:3000 UI, :4000 API)
        │
        ├── 4D layers, recon windows, provenance, ontology
        │
        ▼
Argus / WorldViewPlugin

WorldMonitor sidecar (:3100 by Jarvis convention)
        │
        ├── MCP tools/resources: world brief, country risk, markets, cyber, aviation
        │
        ▼
WorldMonitorProvider
        │
        ▼
Jarvis Signal Layer (:8787)
        │
        ├── Evidence ledger
        ├── Signal schema
        ├── Relevance scoring
        ├── Assessments
        ├── Briefs
        └── Recommended actions
        │
        ▼
SignalLayerPlugin + HUD cockpit + future memory/action queue
```

## Fusion rule

WorldView and WorldMonitor should not compete for the same port, name, or role.

- `WorldView` remains the Jarvis-owned visual/geospatial product.
- `WorldMonitor` becomes an optional provider.
- `Signal Layer` is the durable Jarvis brain that can absorb both.

## Sunday demo target

The demo should show the fused product story:

```text
Jarvis starts WorldView and Signal Layer.
Signal Layer runs in replay mode by default.
Argus/Jarvis can ask Signal Layer what changed and what matters.
The answer shows evidence, relevance, freshness, and recommended actions.
WorldView remains available for the geospatial layer.
WorldMonitor live mode is shown as the next switch to flip once MCP contract validation is complete.
```

## Next implementation checkpoints

1. Keep WorldMonitor off `:3000`; use `:3100` by Jarvis convention.
2. Use `JARVIS_SIGNAL_LAYER_MODE`, not `JARVIS_WORLDVIEW_MODE`, for replay/live mode.
3. Keep `WorldViewPlugin` for 4D geospatial queries.
4. Add `SignalLayerPlugin` for evidence-backed world intelligence.
5. Mount the WorldView/Signal cockpit into the actual Vite HUD, not an unused app path.
6. Add live-contract tests against a running WorldMonitor sidecar.
