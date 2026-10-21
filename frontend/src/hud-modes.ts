// Shared public mode IDs: frontend navigation and the native route allowlist.
export const HUD_MODES = ['cockpit', 'chat', 'projects', 'agents', 'trust', 'memory', 'autonomy', 'build', 'observe', 'interop', 'comms', 'admin', 'finance', 'health', 'knowledge', 'family', 'jobs', 'world'] as const;

// Bolt Optimization: O(1) Set lookup index for route validation avoiding array scan on parseHudRoute
export const HUD_MODES_SET: ReadonlySet<string> = new Set<string>(HUD_MODES);
