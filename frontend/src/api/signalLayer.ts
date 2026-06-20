// @ts-nocheck

const SIGNAL_LAYER_URL = import.meta.env?.VITE_SIGNAL_LAYER_URL || 'http://localhost:8787';

async function getJson(path) {
  const response = await fetch(`${SIGNAL_LAYER_URL}${path}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

export async function loadWorldIntelligence() {
  const [health, brief, signals] = await Promise.allSettled([
    getJson('/healthz'),
    getJson('/briefs/world'),
    getJson('/signals?limit=8&relevantOnly=true'),
  ]);

  return {
    baseUrl: SIGNAL_LAYER_URL,
    health: health.status === 'fulfilled' ? health.value : null,
    brief: brief.status === 'fulfilled' ? brief.value : null,
    signals: signals.status === 'fulfilled' ? (signals.value.signals || []) : [],
    evidence: signals.status === 'fulfilled' ? (signals.value.evidence || []) : [],
    errors: [health, brief, signals]
      .filter(item => item.status === 'rejected')
      .map(item => item.reason?.message || 'request failed'),
  };
}
