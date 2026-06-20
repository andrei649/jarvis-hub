export function loadConfig(env = process.env) {
  // Prefer the Signal Layer-specific env. Keep JARVIS_WORLDVIEW_MODE as a
  // deprecated fallback so early sprint scripts still work, but avoid coupling
  // the provider-neutral Signal Layer to the existing Jarvis WorldView stack.
  const modeEnv = env.JARVIS_SIGNAL_LAYER_MODE || env.JARVIS_WORLDVIEW_MODE || 'replay';
  const mode = modeEnv === 'live' ? 'live' : 'replay';
  return {
    mode,
    // Local-only by default (matches the plugin's LAN/LOCAL_ONLY manifest). An
    // unauthenticated 0.0.0.0 bind would expose /ask/world + /watchlist to the
    // whole LAN — opt into that explicitly with SIGNAL_LAYER_HOST=0.0.0.0.
    host: env.SIGNAL_LAYER_HOST || '127.0.0.1',
    port: Number.parseInt(env.SIGNAL_LAYER_PORT || '8787', 10),
    // Optional bearer token. When set, every request must carry
    // `Authorization: Bearer <token>`; when empty (default), auth is off and the
    // 127.0.0.1 bind is the only boundary.
    authToken: (env.SIGNAL_LAYER_API_TOKEN || '').trim(),
    // Extra browser origins allowed for CORS, beyond localhost/127.0.0.1/::1
    // (comma-separated). Needed only if the HUD is served from another host.
    allowedOrigins: (env.SIGNAL_LAYER_ALLOWED_ORIGINS || '')
      .split(',')
      .map(s => s.trim())
      .filter(Boolean),
    worldMonitor: {
      // Keep WorldMonitor off :3000 by default because Jarvis's existing
      // WorldView frontend already owns localhost:3000.
      baseUrl: trimTrailingSlash(env.WORLDMONITOR_BASE_URL || 'http://localhost:3100'),
      mcpUrl: env.WORLDMONITOR_MCP_URL || 'http://localhost:3100/api/mcp',
      timeoutMs: Number.parseInt(env.WORLDMONITOR_TIMEOUT_MS || '8000', 10)
    }
  };
}

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}
