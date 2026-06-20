// Unit tests for the Signal Layer core scoring/assessment/evidence logic.
import assert from 'node:assert/strict';
import { scoreSignal, scoreSignalsForWatchlist } from '../src/core/relevance.mjs';
import { buildWorldBriefFromSignals, buildCountryAssessment } from '../src/core/assessment.mjs';
import { createEvidenceLedger } from '../src/core/evidenceLedger.mjs';

const watchlist = [
  { id: 'country:RO', type: 'country', value: 'RO', label: 'Romania', priority: 'high' },
  { id: 'market:BTC-USD', type: 'market', value: 'BTC-USD', label: 'Bitcoin', priority: 'normal' },
];

// --- relevance.scoreSignal ---
{
  // Severity raises the base score; a watchlist entity match adds a country boost.
  const matched = scoreSignal(
    { id: 's1', severity: 'high', title: 'Unrest', entities: [{ type: 'country', id: 'RO' }] },
    watchlist
  );
  const unmatched = scoreSignal({ id: 's2', severity: 'high', title: 'Elsewhere' }, watchlist);
  assert.ok(matched.score > unmatched.score, 'watchlist match must outscore a non-match');
  assert.ok(matched.reasons.some(r => /Romania/.test(r)), 'reason explains the match');
  assert.ok(matched.matchedTargets.length === 1, 'records the matched target');

  // Stale + low confidence apply penalties.
  const penalized = scoreSignal({ id: 's3', severity: 'high', stale: true, confidence: 'low' }, []);
  const clean = scoreSignal({ id: 's4', severity: 'high' }, []);
  assert.ok(penalized.score < clean.score, 'stale + low confidence lowers score');

  // Score is clamped to 0..100.
  for (const s of [matched, unmatched, penalized, clean]) {
    assert.ok(s.score >= 0 && s.score <= 100, 'score within [0,100]');
  }
}

// --- relevance.scoreSignalsForWatchlist sorts by score desc ---
{
  const scored = scoreSignalsForWatchlist([
    { id: 'a', severity: 'low', title: 'minor' },
    { id: 'b', severity: 'critical', title: 'BTC-USD crash', summary: 'BTC-USD' },
  ], watchlist);
  assert.equal(scored[0].id, 'b', 'highest-relevance signal sorts first');
  assert.ok('relevance' in scored[0], 'attaches relevance');
}

// --- assessment.buildWorldBriefFromSignals ---
{
  const signals = scoreSignalsForWatchlist([
    { id: 'avi', type: 'aviation', severity: 'elevated', title: 'Airspace', evidenceIds: ['e1'] },
    { id: 'cyb', type: 'cyber', severity: 'high', title: 'Cyber', evidenceIds: ['e2'] },
  ], watchlist);
  const brief = buildWorldBriefFromSignals({ signals, evidence: [], provider: 'replay', freshness: { stale: false } });
  assert.equal(brief.type, 'brief');
  assert.equal(brief.globalStatus, 'high', 'global status is the highest severity present');
  assert.ok(brief.topSignals.length === 2);
  assert.ok(brief.recommendations.length > 0, 'produces recommendations');
  assert.ok(brief.recommendations.every(r => 'requiresApproval' in r), 'recommendations carry requiresApproval');
}

// --- assessment.buildCountryAssessment ---
{
  const signals = scoreSignalsForWatchlist([
    { id: 'c1', type: 'conflict', severity: 'critical', title: 'Conflict', evidenceIds: ['e3'] },
  ], watchlist);
  const a = buildCountryAssessment({ iso2: 'RO', signals, evidence: [], provider: 'replay', freshness: { stale: false } });
  assert.equal(a.subject.id, 'RO');
  assert.ok(a.risk.score >= 10 && a.risk.score <= 100, 'risk score bounded');
  assert.ok(['low', 'moderate', 'elevated', 'high', 'critical'].includes(a.risk.level));
  assert.ok(a.drivers.length === 1, 'lists drivers');

  // Empty signals → still a valid, low-claim assessment (no crash).
  const empty = buildCountryAssessment({ iso2: 'XX', signals: [], evidence: [], provider: 'replay' });
  assert.match(empty.claim, /no current high-relevance signals/);
}

// --- evidenceLedger.toPublicEvidence dedupes, filters, and shapes ---
{
  const ledger = createEvidenceLedger([
    { id: 'e1', provider: 'wm', sourceFamily: 'news', stale: false, secret: 'should-not-leak' },
    { id: 'e2', provider: 'wm', sourceFamily: 'aviation', stale: true },
  ]);
  const out = ledger.toPublicEvidence(['e1', 'e1', 'missing', 'e2']);
  assert.equal(out.length, 2, 'dedupes ids and drops unknown');
  assert.equal(out[0].id, 'e1');
  assert.equal(out[0].stale, false);
  assert.equal(out[1].stale, true);
  assert.ok(!('secret' in out[0]), 'only whitelisted fields are exposed');
}

console.log(JSON.stringify({ ok: true, suite: 'core', checks: ['relevance', 'world-brief', 'country-assessment', 'evidence-ledger'] }, null, 2));
