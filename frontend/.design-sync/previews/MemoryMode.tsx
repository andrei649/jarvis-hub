import React from 'react';
import { MemoryMode, V2 } from 'jarvis-hud-v2';

/* MemoryMode self-fetches GET /api/memory/search?q=recent&top_k=8 on mount and swaps
   the seed RECALLS for real hits (mapping {score,payload,sources} → {rx,rsrc,score}).
   The stub is keyed with the full URL incl. query string. SeedCorpus/TimeTravel stub
   nothing — the designed offline path keeps the seed corpus. */
const STORY = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
function stubFetch(routesByStory: Record<string, Record<string, unknown>>, fallback: string) {
  const routes = routesByStory[STORY] || routesByStory[fallback] || {};
  const real = window.fetch.bind(window);
  (window as any).fetch = (input: any, init?: any) => {
    const url = typeof input === 'string' ? input : ((input && (input as any).url) || '');
    const path = String(url).split('?')[0];
    const hit = Object.prototype.hasOwnProperty.call(routes, url) ? routes[url]
      : Object.prototype.hasOwnProperty.call(routes, path) ? routes[path] : undefined;
    if (hit === undefined) return real(input as any, init);
    return Promise.resolve(new Response(JSON.stringify(hit), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  };
}

stubFetch({
  LiveRecalls: {
    '/api/memory/search?q=recent&top_k=8': {
      results: [
        { score: 0.94, payload: { text: 'Raiffeisen QBR: lead with the churn-cohort slide — M. Pop asked for it twice' }, sources: ['kg', 'vector'] },
        { score: 0.91, payload: { text: 'Deep-work mornings — never schedule before 09:00 (standing preference)' }, sources: ['pref'] },
        { score: 0.88, payload: { text: 'Cosmina OOO Mon–Tue for family — Frigga keeps this on-device' }, sources: ['gcal', 'kg'] },
        { score: 0.83, payload: { text: 'BMW build blocked on part #4471 — shipped, ETA Thursday' }, sources: ['kg'] },
        { score: 0.79, payload: { text: 'Cycles to work when weather is clear and under 22°' }, sources: ['pattern', 'vector'] },
      ],
    },
  },
  SeedCorpus: {},
  TimeTravelMarch: {},
}, 'LiveRecalls');

/* Real-DOM-event staging (wave-1 recipe): the bitemporal slider state is internal, so
   the TimeTravelMarch story rewinds the REAL range input to mark 0 via the native value
   setter + a bubbling input event — never lookalike markup. */
function TimeTravelDriver({ mark }: { mark: number }) {
  React.useEffect(() => {
    let tries = 0;
    const id = window.setInterval(() => {
      const input = document.querySelector('.timeslider input[type="range"]') as HTMLInputElement | null;
      if (input) {
        const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
        set.call(input, String(mark));
        input.dispatchEvent(new Event('input', { bubbles: true }));
        window.clearInterval(id);
      } else if (++tries > 25) window.clearInterval(id);
    }, 100);
    return () => window.clearInterval(id);
  }, [mark]);
  return null;
}

const T = V2.I18N.en;
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, zoom: 0.62 } as React.CSSProperties;
const stage: React.CSSProperties = { width: 1340, height: 830, display: 'flex' };

/** Live recalls from /api/memory/search replace the seed corpus — fused kg+vector hits with scores; full KG at the latest mark. */
export function LiveRecalls() {
  return (
    <div className="hud-root" style={wrap}>
      <div style={stage}><MemoryMode t={T} /></div>
    </div>
  );
}

/** Offline/seed fallback — memory search unreachable, the seed recall corpus and topic-decay bars stand in (designed degrade). */
export function SeedCorpus() {
  return (
    <div className="hud-root" style={wrap}>
      <div style={stage}><MemoryMode t={T} /></div>
    </div>
  );
}

/** Bitemporal time travel — slider rewound to 2026-03: later-born entities (Raiffeisen, BMW, savings ladder) fade to ghosts. */
export function TimeTravelMarch() {
  return (
    <div className="hud-root" style={wrap}>
      <TimeTravelDriver mark={0} />
      <div style={stage}><MemoryMode t={T} /></div>
    </div>
  );
}
