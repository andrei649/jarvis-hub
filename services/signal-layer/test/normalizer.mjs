// Offline contract tests for the WorldMonitor → Signal Layer translation layer.
// These pin the shapes we expect from a live WorldMonitor so that, when a real
// sidecar is connected, `npm run test:live-contract` is the only thing left to run.
import assert from 'node:assert/strict';
import {
  normalizeWorldMonitorToolResult,
  normalizeWorldMonitorBrief,
  normalizeWorldMonitorCountryAssessment,
} from '../src/normalizers/worldMonitor.mjs';

// Helper: wrap a payload the way an MCP tool result delivers it (content[].text JSON).
const mcp = (obj) => ({ content: [{ type: 'text', text: JSON.stringify(obj) }] });

// --- Tool result: MCP envelope unwrap + record mapping (snake_case, score→severity, entities) ---
{
  const raw = mcp({
    events: [
      {
        headline: 'Border incident reported',
        country_code: 'ro',
        published_at: '2026-06-19T20:00:00Z',
        risk_score: 78,
        url: 'https://example.test/a',
        source: 'OSINT feed',
      },
      { title: 'Quiet sector', countryCode: 'AE', severity: 'low', url: 'https://example.test/b' },
    ],
  });
  const out = normalizeWorldMonitorToolResult('get_conflict_events', raw);
  assert.equal(out.signals.length, 2, 'unwraps MCP text envelope and maps each record');
  assert.equal(out.evidence.length, 2, 'emits paired evidence');

  const s0 = out.signals[0];
  assert.equal(s0.type, 'conflict', 'type derived from tool name');
  assert.equal(s0.severity, 'high', 'numeric risk_score 78 → high');
  assert.equal(s0.claimStatus, 'raw_osint_lead', 'conflict/news are raw leads, not confirmed');
  assert.deepEqual(s0.entities[0], { type: 'country', id: 'RO', label: 'RO' }, 'country_code → uppercased entity');
  assert.equal(s0.publishedAt, '2026-06-19T20:00:00Z', 'snake_case published_at carried through');
  assert.equal(out.evidence[0].url, 'https://example.test/a', 'evidence keeps the source url');

  assert.equal(out.signals[1].severity, 'low', 'explicit severity string respected');
}

// --- Tool name → type/severity mapping for the other feeds ---
{
  const aviation = normalizeWorldMonitorToolResult('get_aviation_status', mcp({ items: [{ airport: 'dxb', symbol: null }] }));
  assert.equal(aviation.signals[0].type, 'aviation');
  assert.deepEqual(aviation.signals[0].entities[0], { type: 'airport', id: 'DXB', label: 'DXB' });
  assert.equal(aviation.signals[0].claimStatus, 'confirmed', 'non-news tools are confirmed');

  const market = normalizeWorldMonitorToolResult('get_market_data', mcp({ data: [{ symbol: 'btc-usd', score: 20 }] }));
  assert.equal(market.signals[0].type, 'market');
  assert.deepEqual(market.signals[0].entities[0], { type: 'market', id: 'BTC-USD', label: 'BTC-USD' });
  assert.equal(market.signals[0].severity, 'low', 'score 20 → low');
}

// --- Empty / unrecognized payloads degrade safely ---
{
  const empty = normalizeWorldMonitorToolResult('get_cyber_threats', mcp({}));
  assert.deepEqual(empty.signals, [], 'no records → empty signals, no throw');
  assert.deepEqual(empty.evidence, []);
}

// --- World brief normalization (camelCase + snake_case + sources) ---
{
  const brief = normalizeWorldMonitorBrief(mcp({
    title: 'World Brief',
    summary: 'Things are happening.',
    generated_at: '2026-06-20T06:00:00Z',
    status: 'elevated',
    topRisks: [{ title: 'r1' }, { title: 'r2' }],
    sources: [{ name: 'Reuters', url: 'https://r.test', reliability: 'high' }],
    stale: false,
  }));
  assert.equal(brief.type, 'brief');
  assert.equal(brief.provider, 'worldmonitor');
  assert.equal(brief.executiveSummary, 'Things are happening.', 'summary→executiveSummary fallback');
  assert.equal(brief.globalStatus, 'elevated', 'status→globalStatus fallback');
  assert.equal(brief.topSignals.length, 2);
  assert.equal(brief.sources.length, 1);
  assert.equal(brief.evidenceIds.length, 1, 'evidenceIds derived from sources');
  assert.equal(brief.sources[0].id, brief.evidenceIds[0], 'source id matches evidence id');
}

// --- Country assessment merges multiple payloads + derives level from score ---
{
  const a = normalizeWorldMonitorCountryAssessment({
    iso2: 'RO',
    payloads: [mcp({ risk_score: 72, country: 'Romania' }), mcp({ drivers: [{ title: 'd1' }], sources: [{ url: 'https://s.test' }] })],
    errors: [],
  });
  assert.equal(a.subject.id, 'RO');
  assert.equal(a.subject.label, 'Romania', 'country name merged from a second payload');
  assert.equal(a.risk.score, 72);
  assert.equal(a.risk.level, 'high', 'score 72 → high');
  assert.equal(a.drivers.length, 1, 'drivers merged');
  assert.equal(a.evidence.length, 1, 'sources → evidence');

  // Missing score falls back to a default, still valid.
  const b = normalizeWorldMonitorCountryAssessment({ iso2: 'XX', payloads: [mcp({})] });
  assert.ok(Number.isFinite(b.risk.score), 'defaulted score is numeric');
  assert.ok(['low', 'moderate', 'elevated', 'high', 'critical'].includes(b.risk.level));
}

console.log(JSON.stringify({ ok: true, suite: 'normalizer', checks: ['tool-result', 'entities', 'brief', 'country', 'empty-safe'] }, null, 2));
