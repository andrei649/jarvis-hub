# H178 floating desktop chat implementation plan

Goal: a usable native floating chat, sharing the normal HUD's authenticated transport and server conversation.
Generated: 2026-09-15. Base/head at planning: f75d7c326dfd378a22edc53564cdbdb6f17cc1fa.
Authorization: owner-approved desktop brief; isolated codex/floating-desktop-chat worktree; no owner confirmation needed.

Architecture: Tauri owns two fixed windows loading exact local /v2 URLs and exposes two app commands (capabilities and a finite action enum). Floating window is frameless/resizable/always-on-top where the compositor supports this; tray and normal HUD open it, close hides, handoff focuses main. Shared same-origin storage and existing app ChatMode/postStream retain authentication and server session. Focus refresh and a same-origin completion notification reconcile server-persisted messages without replacing a streaming turn. Geometry is local UI metadata only, stored in the app config directory, recovered against current physical monitor work areas at every show. One native capability object makes unsupported Wayland placement/topmost, transparency/frost, click-through, global shortcut, game overlay and move-to-pointer explicit.

Non-goals: underlying-window reading, capture, input automation, shell access, autostart daemon, new backend/session transport, full twenty-part Hermes parity.

Paths: desktop/src-tauri/{src,build.rs,tauri.conf.json,Cargo.toml,Cargo.lock,capabilities,icons}; frontend/src/{desktop.tsx,app.tsx,main.tsx,styles.css,test}; built agents/web/v2; desktop README, mobile/PARITY, HUD_V2_REMAINING, narrow BACKLOG/Hermes evidence and generated metadata.

1. Write native geometry and trust-boundary tests first; prove red. Implement sanitization/clamp for missing/corrupt/oversized/offscreen and multiple-monitor bounds, native action allowlist, capability detection.
2. Wire exact URL windows, persistent geometry, executable tray, show/hide/reset/handoff, explicit errors. Remove unused autostart plugin; copy existing mobile icon.
3. Write frontend failing tests for native gating/control errors, focused ChatMode and same-session refresh. Implement compact mode, drag/resize controls and main opener using fixed actions only. Keep normal main chat unchanged except safe refresh.
4. Run targeted/full frontend Vitest JSON with maxWorkers1, typecheck and tracked normal build; preserve mobile count137. cargo test/check --jobs2 with dev/test debug0; launch local native process if possible, no real model calls. Review diff and guards, document observed limits.
5. Refresh narrow ledgers/counts and report evidence. Commit coherent rollback unit; no push/merge. Controller conducts independent review.

Rollback: revert this single feature commit and rebuild frontend; native saved geometry may remain harmlessly in app config. Dependencies: existing local HUD running on127.0.0.1:8080, Tauri host prerequisites. Next action: failing native geometry tests.

## Independent review follow-up — 2026-09-15

Base/head before repair: 8fd7e680405cfa31c83ac99feb98d8226772f8e2. P2: a completion received while busy was discarded, leaving queued-window transcripts stale. Retain one pending invalidation through busy periods, keep the channel/listeners stable across busy transitions, and replay on idle. Generation checks and committed busy state must still reject stale reads. Regression: two real asynchronous BroadcastChannel subscribers with overlapping turns converge without focus; repeated busy invalidations coalesce. Frontend-only repair; no repeated native build. Preserve late GO_LIVE_PLAN/NERVA count updates and regenerate all status/Hermes outputs. Validate full frontend/typecheck/build and Hermes/status guards, then commit for independent re-review.
