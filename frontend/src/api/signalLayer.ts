/* HUD v2 · signal-layer client (WorldView). Reads the optional external signal-layer
   service; every request degrades to null/[] so a missing service never breaks a panel.
   CDX-9: typed (was @ts-nocheck). `import.meta.env` is cast because the project has no
   vite/client types wired; `getJson` stays `any` (arbitrary external JSON). */

// Vite injects env at build; no vite/client types here, so read it through a cast.
const SIGNAL_LAYER_URL =
  (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_SIGNAL_LAYER_URL
  || 'http://localhost:8787';

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- arbitrary external JSON
async function getJson(path: string): Promise<any> {
  const response = await fetch(`${SIGNAL_LAYER_URL}${path}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

export interface WorldIntelligence {
  baseUrl: string;
  health: unknown;
  brief: unknown;
  signals: unknown[];
  evidence: unknown[];
  errors: string[];
}

export async function loadWorldIntelligence(): Promise<WorldIntelligence> {
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
      .filter((item): item is PromiseRejectedResult => item.status === 'rejected')
      .map((item) => (item.reason as { message?: string })?.message || 'request failed'),
  };
}
