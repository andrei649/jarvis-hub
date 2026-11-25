// Shared public mode IDs: frontend navigation and the native route allowlist.
// Phase B (PHASE_B_PLAN.md §3.2) adds four views at the end: work, timeline, artifacts, glance.
// After editing, regenerate desktop/src-tauri/hud-routes.json:
//   node --experimental-strip-types frontend/scripts/generate-desktop-routes.mjs
export const HUD_MODES = ['cockpit', 'chat', 'projects', 'agents', 'trust', 'memory', 'autonomy', 'build', 'observe', 'interop', 'comms', 'admin', 'finance', 'health', 'knowledge', 'family', 'jobs', 'world', 'work', 'timeline', 'artifacts', 'glance'] as const;
export type HudMode = typeof HUD_MODES[number];

// Bolt Optimization: O(1) Set lookup index for route validation avoiding array scan on parseHudRoute
export const HUD_MODES_SET: ReadonlySet<string> = new Set<string>(HUD_MODES);
