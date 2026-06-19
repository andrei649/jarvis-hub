export function loadConfig(env = process.env) {
  const mode = env.JARVIS_WORLDVIEW_MODE === 'live' ? 'live' : 'replay';
  return {
    mode,
    host: env.SIGNAL_LAYER_HOST || '0.0.0.0',
    port: Number.parseInt(env.SIGNAL_LAYER_PORT || '8787', 10),
    worldMonitor: {
      baseUrl: trimTrailingSlash(env.WORLDMONITOR_BASE_URL || 'http://localhost:3000'),
      mcpUrl: env.WORLDMONITOR_MCP_URL || 'http://localhost:3000/api/mcp',
      timeoutMs: Number.parseInt(env.WORLDMONITOR_TIMEOUT_MS || '8000', 10)
    }
  };
}

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}
