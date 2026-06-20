import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const fixtureDir = join(__dirname, '../../fixtures/worldmonitor');

export class ReplayProvider {
  constructor() {
    this.id = 'worldmonitor';
    this.name = 'WorldMonitor Replay Provider';
    this.mode = 'replay';
  }

  async health() {
    return loadJson('provider-health.json');
  }

  async fetchSignals(input = {}) {
    const [signals, evidence, freshness] = await Promise.all([
      loadJson('signals.json'),
      loadJson('evidence.json'),
      loadJson('freshness.json')
    ]);

    let filtered = [...signals];
    if (input.type) filtered = filtered.filter(signal => signal.type === input.type);
    if (input.country) filtered = filtered.filter(signal => signal.entities.some(entity => entity.type === 'country' && entity.id === input.country));
    if (input.minSeverity) filtered = filtered.filter(signal => severityRank(signal.severity) >= severityRank(input.minSeverity));
    if (input.limit) filtered = filtered.slice(0, input.limit);

    return { provider: this.id, mode: this.mode, signals: filtered, evidence, freshness };
  }

  async fetchBrief(input = {}) {
    if (input.scope === 'world' || !input.scope) {
      return { provider: this.id, mode: this.mode, brief: await loadJson('world-brief.json') };
    }
    return { provider: this.id, mode: this.mode, brief: null };
  }

  async fetchEntityAssessment(input) {
    if (input.type === 'country') {
      const filename = `country-risk-${String(input.id || '').toUpperCase()}.json`;
      try {
        return { provider: this.id, mode: this.mode, assessment: await loadJson(filename) };
      } catch {
        return { provider: this.id, mode: this.mode, assessment: null };
      }
    }
    return { provider: this.id, mode: this.mode, assessment: null };
  }
}

async function loadJson(filename) {
  const raw = await readFile(join(fixtureDir, filename), 'utf8');
  return JSON.parse(raw);
}

function severityRank(value) {
  return ({ low: 0, normal: 1, elevated: 2, high: 3, critical: 4 })[value] ?? 0;
}
