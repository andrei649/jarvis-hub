import assert from 'node:assert/strict';
import { loadConfig } from '../src/config.mjs';
import { McpClient } from '../src/providers/mcpClient.mjs';
import { normalizeWorldMonitorBrief, normalizeWorldMonitorToolResult, normalizeWorldMonitorCountryAssessment } from '../src/normalizers/worldMonitor.mjs';

process.env.JARVIS_SIGNAL_LAYER_MODE = 'live';
process.env.WORLDMONITOR_BASE_URL ||= 'http://localhost:3100';
process.env.WORLDMONITOR_MCP_URL ||= 'http://localhost:3100/api/mcp';

const config = loadConfig();
const mcp = new McpClient(config.worldMonitor);

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function required(name, fn) {
  try {
    return await fn();
  } catch (error) {
    console.error(JSON.stringify({
      ok: false,
      skipped: true,
      reason: 'WorldMonitor live contract could not run. Start WorldMonitor on :3100 first.',
      step: name,
      error: error.message,
      expected: {
        WORLDMONITOR_BASE_URL: config.worldMonitor.baseUrl,
        WORLDMONITOR_MCP_URL: config.worldMonitor.mcpUrl
      }
    }, null, 2));
    process.exit(0);
  }
}

const health = await required('health', () => getJson(`${config.worldMonitor.baseUrl}/api/health`));
const tools = await required('mcp.tools.list', () => mcp.listTools());
const briefRaw = await required('mcp.get_world_brief', () => mcp.callTool('get_world_brief', { scope: 'world' }));
const conflictRaw = await required('mcp.get_conflict_events', () => mcp.callTool('get_conflict_events', { limit: 5 }));
const aviationRaw = await required('mcp.get_aviation_status', () => mcp.callTool('get_aviation_status', { limit: 5 }));
const marketRaw = await required('mcp.get_market_data', () => mcp.callTool('get_market_data', { limit: 5 }));
const countryRaw = await required('resource.country.RO.risk', () => mcp.readResource('worldmonitor://countries/RO/risk'));

const brief = normalizeWorldMonitorBrief(briefRaw);
const conflict = normalizeWorldMonitorToolResult('get_conflict_events', conflictRaw);
const aviation = normalizeWorldMonitorToolResult('get_aviation_status', aviationRaw);
const market = normalizeWorldMonitorToolResult('get_market_data', marketRaw);
const country = normalizeWorldMonitorCountryAssessment({ iso2: 'RO', payloads: [countryRaw] });

assert.equal(brief.type, 'brief');
assert.equal(brief.provider, 'worldmonitor');
assert.ok(Array.isArray(conflict.signals), 'conflict signals must be an array');
assert.ok(Array.isArray(aviation.signals), 'aviation signals must be an array');
assert.ok(Array.isArray(market.signals), 'market signals must be an array');
assert.equal(country.subject.id, 'RO');
assert.equal(country.provider, 'worldmonitor');

console.log(JSON.stringify({
  ok: true,
  provider: 'worldmonitor',
  healthStatus: health.status || 'ok',
  toolsCount: Array.isArray(tools?.tools) ? tools.tools.length : undefined,
  briefTitle: brief.title,
  conflictSignals: conflict.signals.length,
  aviationSignals: aviation.signals.length,
  marketSignals: market.signals.length,
  countryRisk: country.risk.level
}, null, 2));
