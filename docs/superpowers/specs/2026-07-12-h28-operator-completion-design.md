# H28 Governed Desktop Completion Design

**Status:** approved by the owner's 2026-07-12 instruction to finish H28.4-H28.6 autonomously.

## Goal

Complete ORIZONT 28 with an explicitly enabled Windows desktop host adapter, accessibility-tree-first targeting, local screen-grounding fallback, execution-time Action Kernel mediation, an agent-callable proposal surface, and hermetic reality cases proving that no desktop mutation bypasses governance.

## Non-goals

- No ambient-session automation by default.
- No arbitrary binary paths, shell strings, coordinate-only clicking, cloud VLM, or credential-profile reuse.
- No automatic approval of mutating desktop steps.
- No mobile actuation surface; desktop execution is intentionally desktop-only.
- No changes to `training/` or `rust/`.

## Architecture

### Optional host driver

`agents/core/desktop_host.py` provides `WindowsDesktopDriver`. Construction is refused unless both `JARVIS_DESKTOP_HOST=1` and `JARVIS_DESKTOP_ISOLATED=1` are set. The dependency-lazy default backend uses Windows UI Automation through optional `pywinauto`; tests inject a backend and screenshot provider, so normal CI remains dependency-free.

The driver exposes `perform(action, args)` for the existing `GovernedDesktop` protocol. `observe`, `read`, and `locate` query a bounded accessibility snapshot first. If a query is absent from that snapshot, `locate` may use an explicitly injected `local_vlm_locator`; no callable means an honest `not_found`, and a callable not marked local is rejected. Screenshots are byte-capped and returned as base64. Mutating `click` and `type` resolve a named accessibility element before actuation. `launch` accepts only a canonical app key resolved through the owner-provided launcher map and starts an argv list with `shell=False`.

### Execution-time governance

`desktop.step` becomes a distinct KERNEL action with a complete capability manifest. `DesktopActionExecutor` binds the real driver behind `CapabilityActionAPI`; it is the only path used by `/api/desktop/run`. A kill switch, missing capability, kernel error, queued approval, or disabled flag returns an honest non-executed result. `GovernedDesktop` keeps its existing offline/manual-approver behavior for `NullDesktopDriver`, but refuses any driver declaring `requires_kernel=True` unless a `DesktopActionExecutor` is supplied.

The route is user-guarded and default-off. It accepts at most 100 steps, builds the action facade from the live orchestrator kernel binding, and never constructs the host driver when the host flags are off. Existing preview behavior stays unchanged.

### Agent proposal surface

The shared ToolRPC server registers a gated `desktop_run` tool. ToolRPC never executes gated tools inline: it validates and enqueues an approval-tier proposal containing only bounded desktop steps. Actual execution still enters `/api/desktop/run` or the equivalent executor path and is re-authorized at execution time.

### Reality harness and unpark

Hermetic H28 cases prove:

1. accessibility results win and the local VLM fallback is not called;
2. the local VLM fallback is used only after an accessibility miss;
3. an engaged kill switch prevents the host driver's mutating call;
4. the operator benchmark trace contains zero ungoverned executed actions.

After those contracts pass, wave-1 modules are removed from `PARK_POLICY`. The PR itself carries both `unpark: wave-1` and `unpark: park-policy` declarations because it changes the protected policy while graduating those modules.

## Data and privacy boundaries

- Accessibility snapshots are bounded, normalized dictionaries and are not persisted.
- Screenshot bytes are bounded before encoding and are not persisted by the driver.
- Screen grounding accepts only the injected local callable; there is no network client in this module.
- Raw host exceptions, window titles beyond configured limits, binary paths, and screenshot bytes never enter audit messages.
- The existing screenshot injection classifier runs before any step.

## HTTP and parity

`POST /api/desktop/run` is added to the existing multimodal domain router. OpenAPI, route, and auth snapshots are reseeded. HUD V2 receives an explicit punch-list entry rather than an incomplete control. `mobile/PARITY.md` marks actuation `➖` because controlling the server's Windows desktop from mobile is intentionally out of product scope.

## Failure behavior

All host/dependency/policy failures are bounded and redacted. Startup is lazy. Missing UIA, non-Windows hosts, disabled flags, missing elements, oversized observations, and driver exceptions return explicit refused/failed results without fabricating successful actuation.

## Acceptance criteria

- Existing 83 H15/H28 adjacent tests remain green.
- New host-driver tests exercise host flags, accessibility-first behavior, local fallback, bounds, canonical launchers, cleanup, and redacted failures.
- Action-auth/manifests/readiness/reality tests include `desktop.step` and prove the real kernel boundary.
- ToolRPC tests prove `desktop_run` is gated and cannot execute inline.
- Route/OpenAPI/auth/parity/park guards are green.
- Ruff, Bandit, status sync, Ubuntu CI, and Windows CI are green before merge.
