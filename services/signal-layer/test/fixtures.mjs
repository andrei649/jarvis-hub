// Integrity + coverage checks for the replay fixtures. Keeps the deterministic
// demo data self-consistent: every signal's evidence must resolve, and coverage
// stays broad enough for a meaningful demo.
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = join(dirname(fileURLToPath(import.meta.url)), '../fixtures/worldmonitor');
const load = async (f) => JSON.parse(await readFile(join(dir, f), 'utf8'));

const signals = await load('signals.json');
const evidence = await load('evidence.json');
const evidenceIds = new Set(evidence.map((e) => e.id));

// Coverage: enough signals, all six types, several countries.
assert.ok(signals.length >= 16, `expected >=16 signals, got ${signals.length}`);
const types = new Set(signals.map((s) => s.type));
for (const t of ['aviation', 'market', 'cyber', 'conflict', 'geopolitical_news', 'natural_disaster']) {
  assert.ok(types.has(t), `missing signal type: ${t}`);
}
const countries = new Set(
  signals.flatMap((s) => (s.entities || []).filter((e) => e.type === 'country').map((e) => e.id))
);
assert.ok(countries.size >= 6, `expected >=6 distinct countries, got ${[...countries].join(',')}`);

// Referential integrity: every evidenceId on every signal resolves to a record.
for (const s of signals) {
  assert.ok(Array.isArray(s.evidenceIds) && s.evidenceIds.length, `${s.id} has no evidenceIds`);
  for (const id of s.evidenceIds) {
    assert.ok(evidenceIds.has(id), `${s.id} references missing evidence ${id}`);
  }
  assert.ok(s.id && s.type && s.severity, `${s.id || 'signal'} missing required fields`);
}

// Claim taxonomy stays within the documented set (facts / leads / inference /
// forecast stay separate) — guards against typos, not against any single value.
const CLAIM_STATUSES = ['confirmed', 'raw_osint_lead', 'model_inference', 'forecast', 'unknown'];
for (const s of signals) {
  assert.ok(CLAIM_STATUSES.includes(s.claimStatus), `${s.id} bad claimStatus: ${s.claimStatus}`);
}

// Every country-risk fixture is well-formed.
const countryFiles = (await readdir(dir)).filter((f) => /^country-risk-[A-Z]{2}\.json$/.test(f));
assert.ok(countryFiles.length >= 4, `expected >=4 country-risk files, got ${countryFiles.length}`);
for (const f of countryFiles) {
  const c = await load(f);
  assert.ok(c.subject?.id, `${f} missing subject.id`);
  assert.equal(typeof c.risk?.score, 'number', `${f} risk.score must be numeric`);
  assert.ok(['low', 'moderate', 'elevated', 'high', 'critical'].includes(c.risk?.level), `${f} bad risk.level`);
  for (const id of c.evidenceIds || []) {
    assert.ok((c.evidence || []).some((e) => e.id === id), `${f} evidenceId ${id} not embedded`);
  }
}

console.log(JSON.stringify({
  ok: true, suite: 'fixtures',
  signals: signals.length, types: types.size, countries: countries.size, countryFiles: countryFiles.length,
}, null, 2));
