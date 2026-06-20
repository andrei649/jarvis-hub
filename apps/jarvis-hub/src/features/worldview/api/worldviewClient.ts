const SIGNAL_LAYER_URL = process.env.NEXT_PUBLIC_SIGNAL_LAYER_URL || 'http://localhost:8787';

export async function fetchWorldBrief() {
  return getJson('/briefs/world');
}

export async function fetchSignals(params: { limit?: number; relevantOnly?: boolean } = {}) {
  const search = new URLSearchParams();
  if (params.limit) search.set('limit', String(params.limit));
  if (params.relevantOnly) search.set('relevantOnly', 'true');
  return getJson(`/signals?${search.toString()}`);
}

export async function fetchProviderHealth() {
  return getJson('/provider-health/worldmonitor');
}

export async function fetchWatchlist() {
  return getJson('/watchlist');
}

export async function askWorld(question: string) {
  const response = await fetch(`${SIGNAL_LAYER_URL}/ask/world`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question })
  });
  if (!response.ok) throw new Error(`Signal Layer returned ${response.status}`);
  return response.json();
}

async function getJson(path: string) {
  const response = await fetch(`${SIGNAL_LAYER_URL}${path}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Signal Layer returned ${response.status}`);
  return response.json();
}
