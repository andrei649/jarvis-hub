// Mock WorldMonitor sidecar for exercising the LIVE code path without the real
// service. It encodes our ASSUMPTIONS about WorldMonitor's API (health + MCP
// JSON-RPC tools/resources). Passing the live contract against this validates OUR
// client/provider/normalizer in live mode — it does NOT prove the real WorldMonitor
// behaves identically. Real validation still needs a real WorldMonitor on :3100.
import http from 'node:http';
import { once } from 'node:events';

const TOOL_PAYLOADS = {
  get_world_brief: {
    title: 'Global Intelligence Brief', summary: 'Mock world brief.', status: 'elevated',
    topRisks: [{ title: 'Risk A' }], sources: [{ name: 'Reuters', url: 'https://r.test', reliability: 'high' }],
  },
  get_conflict_events: { events: [{ headline: 'Border incident', country_code: 'RO', risk_score: 78, url: 'https://x.test/1', source: 'OSINT' }] },
  get_aviation_status: { items: [{ title: 'DXB delays', airport: 'DXB', severity: 'elevated', url: 'https://x.test/2' }] },
  get_market_data: { data: [{ title: 'BTC move', symbol: 'BTC-USD', score: 55, url: 'https://x.test/3' }] },
  get_cyber_threats: { items: [{ title: 'Botnet uptick', severity: 'high', url: 'https://x.test/4' }] },
  get_natural_disasters: { items: [{ title: 'Storm', severity: 'normal', url: 'https://x.test/5' }] },
  get_news_intelligence: { items: [{ headline: 'Policy shift', country_code: 'AE', url: 'https://x.test/6' }] },
  get_country_brief: { country: 'Romania', risk_score: 72, drivers: [{ title: 'd1' }], sources: [{ url: 'https://c.test' }] },
};
const RESOURCES = {
  'worldmonitor://countries/RO/risk': { risk_score: 70, country: 'Romania', sources: [{ url: 'https://c.test/ro' }] },
};

const json = (res, status, obj) => {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(obj));
};
const mcpText = (obj) => ({ content: [{ type: 'text', text: JSON.stringify(obj) }] });

function handler(req, res) {
  if (req.url === '/api/health') return json(res, 200, { status: 'ok', fresh: 6, stale: 1 });
  if (req.method === 'POST' && req.url === '/api/mcp') {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      let rpc = {};
      try { rpc = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'); } catch { /* ignore */ }
      const reply = (result) => json(res, 200, { jsonrpc: '2.0', id: rpc.id, result });
      const rpcError = (message) => json(res, 200, { jsonrpc: '2.0', id: rpc.id, error: { code: -32601, message } });
      if (rpc.method === 'tools/list') return reply({ tools: Object.keys(TOOL_PAYLOADS).map((name) => ({ name })) });
      if (rpc.method === 'tools/call') {
        const payload = TOOL_PAYLOADS[rpc.params?.name];
        return payload ? reply(mcpText(payload)) : rpcError('unknown tool');
      }
      if (rpc.method === 'resources/read') return reply(mcpText(RESOURCES[rpc.params?.uri] || {}));
      return rpcError('unknown method');
    });
    return;
  }
  json(res, 404, { error: 'not found' });
}

// Start the mock on an ephemeral port (0) by default so it never collides in CI.
// Returns { server, url } once listening.
export async function startMockWorldMonitor(port = 0) {
  const server = http.createServer(handler);
  server.listen(port, '127.0.0.1');
  await once(server, 'listening');
  const { port: actual } = server.address();
  return { server, url: `http://127.0.0.1:${actual}` };
}

// Standalone manual use: `node test/_mock-worldmonitor.mjs` → fixed :3100.
if (import.meta.url === `file://${process.argv[1]}`) {
  startMockWorldMonitor(Number(process.env.PORT || 3100)).then(({ url }) =>
    console.log(`mock-worldmonitor listening on ${url}`)
  );
}
