import React from 'react';
import { ModelInfoPanel } from 'jarvis-hud-v2';

/* ModelInfoPanel is a live-dashboard panel: zero props, fetches the
   admin-guarded GET /api/models/info on mount. Each story serves its own
   backend payload through a scoped fetch shim keyed off the card's ?story=
   param, so the REAL exported panel renders real data end-to-end — nothing is
   hand-drawn. */
const STORIES: Record<string, Record<string, unknown>> = {
  Recorded: {
    '/api/models/info': {
      enabled: true,
      stats: { total: 4 },
      models: [
        { id: 'gemma-4-26b-a4b', quant: 'Q4_K_M', sha256: '8c31f0a29e77d410b52ce6a1' },
        { id: 'qwen3-14b-instruct', quant: 'Q5_K_S', sha256: '1de77b9034aa20c4f18d02e9' },
        { id: 'whisper-large-v3', quant: 'f16', sha256: 'aa20c4d19b31e0f27c55a8d3' },
        { id: 'piper-tts-ro', quant: 'onnx-fp16', sha256: '4f2a9c1d8830bb17e6d40a52' },
      ],
    },
  },
  Disabled: {
    '/api/models/info': { enabled: false, models: [], stats: { total: 0 } },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.Recorded;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 400 };

/** Fingerprints on — every model build seen, with quant and sha prefix for reproducibility. */
export function Recorded() {
  return <div className="hud-root" style={frame}><ModelInfoPanel /></div>;
}

/** JARVIS_MODEL_INFO off — SEED chip and the honest empty-until hint. */
export function Disabled() {
  return <div className="hud-root" style={frame}><ModelInfoPanel /></div>;
}
