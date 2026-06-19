import assert from 'node:assert/strict';
import { loadConfig } from '../src/config.mjs';
import { createProvider } from '../src/providers/index.mjs';
import { scoreSignalsForWatchlist } from '../src/core/relevance.mjs';
import { buildWorldBriefFromSignals } from '../src/core/assessment.mjs';
import { defaultWatchlist } from '../src/core/watchlist.mjs';

process.env.JARVIS_WORLDVIEW_MODE = 'replay';
const config = loadConfig();
const provider = createProvider(config);

const health = await provider.health();
assert.equal(health.status, 'ok');

const payload = await provider.fetchSignals({ limit: 20 });
assert.ok(payload.signals.length >= 5, 'expected replay signals');
assert.ok(payload.evidence.length >= 5, 'expected replay evidence');

const scored = scoreSignalsForWatchlist(payload.signals, defaultWatchlist);
assert.ok(scored[0].relevance.score > 0, 'expected relevant signal');
assert.ok(scored.some(signal => signal.relevance.reasons.length > 0), 'expected relevance reasons');

const brief = buildWorldBriefFromSignals({
  signals: scored,
  evidence: payload.evidence,
  provider: payload.provider,
  freshness: payload.freshness
});
assert.equal(brief.type, 'brief');
assert.ok(brief.topSignals.length > 0, 'expected brief top signals');
assert.ok(brief.recommendations.length > 0, 'expected recommendations');

const ro = await provider.fetchEntityAssessment({ type: 'country', id: 'RO' });
assert.equal(ro.assessment.subject.id, 'RO');

console.log(JSON.stringify({
  ok: true,
  mode: config.mode,
  signalCount: payload.signals.length,
  topSignal: scored[0].title,
  topRelevance: scored[0].relevance.score,
  briefStatus: brief.globalStatus
}, null, 2));
