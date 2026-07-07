import React from 'react';
import { MediaGalleryPanel } from 'jarvis-hud-v2';

/* MediaGalleryPanel is a live-dashboard panel: zero props, fetches
   GET /api/media/catalog on mount. Each story serves its own backend payload
   through a scoped fetch shim keyed off the card's ?story= param, so the REAL
   exported panel renders real data end-to-end — nothing is hand-drawn. */
const STORIES: Record<string, Record<string, unknown>> = {
  Cataloged: {
    '/api/media/catalog': {
      enabled: true,
      stats: { total: 34, by_kind: { image: 22, audio: 9, video: 3 } },
      items: [
        { id: 'med-081', kind: 'image', prompt: 'BMW E30 restoration — hero shot, golden hour' },
        { id: 'med-080', kind: 'image', prompt: 'Digitaholic Q3 deck cover, neural grid motif' },
        { id: 'med-079', kind: 'audio', prompt: 'Jerome — focus playlist intro sting, 12s' },
        { id: 'med-078', kind: 'image', prompt: 'Max birthday invite — astronaut theme' },
        { id: 'med-077', kind: 'video', prompt: 'HUD walkthrough for the Raiffeisen demo' },
      ],
    },
  },
  Disabled: {
    '/api/media/catalog': { enabled: false, items: [], stats: { total: 0, by_kind: {} } },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.Cataloged;
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

/** Catalog on — per-kind stats row plus the most recent generated items with prompts. */
export function Cataloged() {
  return <div className="hud-root" style={frame}><MediaGalleryPanel /></div>;
}

/** JARVIS_MEDIA_CATALOG off — SEED chip; prompts are sensitive, nothing recorded by default. */
export function Disabled() {
  return <div className="hud-root" style={frame}><MediaGalleryPanel /></div>;
}
