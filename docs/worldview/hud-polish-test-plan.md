# World Intelligence HUD Polish Test Plan

Branch: `feature/world-intelligence-hud-polish`

## Manual checks

### Signal Layer down

1. Ensure no service is listening on `:8787`.
2. Open Jarvis HUD.
3. Open Observe mode.
4. Expected:

```text
World Intelligence panel appears.
Signal Layer status is OFF.
Fallback explains START.bat/start.sh and /healthz.
No claims of live data.
```

### Signal Layer replay mode

1. Start Signal Layer:

```bash
cd services/signal-layer
JARVIS_SIGNAL_LAYER_MODE=replay npm start
```

2. Open Jarvis HUD → Observe.
3. Expected:

```text
Signal Layer status is OK.
Global brief appears.
Top signals appear.
Freshness, source, relevance, confidence, and claim status are visible.
Recommendations are marked preview-only.
```

### Direct endpoint fallback

```bash
curl http://127.0.0.1:8787/healthz
curl http://127.0.0.1:8787/briefs/world
curl "http://127.0.0.1:8787/signals?limit=8&relevantOnly=true"
```

## Build checks before merge

```bash
cd frontend
npm test
npm run build
```

If `agents/web/v2` changes after build, commit the generated bundle before merging into the integration branch.

## Copy checks

Do not claim:

```text
WorldMonitor live mode is validated.
Recommendations are submitted to approval queue.
Raw OSINT is confirmed fact.
```

Allowed wording:

```text
Replay mode is deterministic and demo-safe.
Recommendations are preview-only until approved.
Live WorldMonitor can be validated through the optional contract test.
```
