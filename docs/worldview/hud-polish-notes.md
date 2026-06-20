# World Intelligence HUD Polish Notes

Branch: `feature/world-intelligence-hud-polish`

## Scope

This branch is intentionally frontend-only and low-conflict.

Target files:

```text
frontend/src/world-intelligence.tsx
frontend/src/api/signalLayer.ts
frontend/src/modes2.tsx
```

Avoid touching conflict-heavy files while `main` is moving:

```text
README.md
START.bat
start.sh
agents/core/orchestrator.py
agents/core/plugin_gate.py
```

## UX goals

1. Make the Signal Layer state obvious.
2. Make replay/demo safety obvious.
3. Show top signals with severity, confidence, relevance, and evidence/freshness.
4. Keep recommendations clearly preview-only.
5. Show a helpful fallback when `:8787` is down.
6. Keep WorldView, Signal Layer, and WorldMonitor port boundaries visible.

## Sunday acceptance

```text
Open Jarvis HUD → Observe mode → World Intelligence panel is visible.
If Signal Layer is running, brief and signals appear.
If Signal Layer is down, the panel explains how to start/check it.
No user-facing copy claims actions were executed or live WorldMonitor is validated.
```
