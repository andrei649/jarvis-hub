import React from 'react';
import { Dossier, V2 } from 'jarvis-hud-v2';

/* Dossier — the right-hand agent drawer (fixed scrim + slide-in panel,
   contained here by the relative/overflow-hidden/translateZ(0) stage). Seed
   archetype/personality/runtime come from V2.DOSSIER; the soul + run history
   are LIVE (GET /api/agents/{id}/soul and /history) with the seed soul as
   fallback. Two provenance stories:
   - LiveSoul     — both endpoints stubbed → "Soul · SOUL.md" label, real
     SOUL.md text, and the "Recent runs" roll-up incl. a red failed run.
   - SeedFallback — NO stubs: the real 404s are swallowed by design and the
     drawer renders wholly from the seed dossier (runs section hidden). */
const STORIES: Record<string, Record<string, unknown>> = {
  LiveSoul: {
    /* Soul kept to two lines and runs to three so the plugins + collaborates
       sections stay above the 620px stage fold (the drawer body scrolls). */
    '/api/agents/pepper/soul': {
      agent_id: 'pepper',
      soul: 'You are Pepper, chief of staff. Reconcile calendar conflicts before Andrei sees them; triage email ruthlessly; protect deep-work blocks.',
    },
    '/api/agents/pepper/history': {
      agent_id: 'pepper',
      runs: [
        { kind: 'calendar.reconcile', status: 'ok', latency_ms: 412 },
        { kind: 'schedule.propose', status: 'error', latency_ms: 1904 },
        { kind: 'email.triage', status: 'ok', latency_ms: 238 },
      ],
    },
  },
  SeedFallback: {}, // nothing stubbed — real 404s → seeded soul, runs hidden (designed fallback)
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.LiveSoul;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 792 };
const stage: React.CSSProperties = { position: 'relative', overflow: 'hidden', transform: 'translateZ(0)', width: 760, height: 620, borderRadius: 6 };

function Drawer({ id }: { id: string }) {
  return (
    <div className="hud-root" style={frame}>
      <div style={stage}>
        <Dossier id={id} onClose={() => {}} onOpen={() => {}} />
      </div>
    </div>
  );
}

/** Pepper with live backend data — SOUL.md-labelled soul, runtime grid, recent runs incl. one failure, collab links. */
export function LiveSoul() {
  return <Drawer id="pepper" />;
}

/** Vision offline — seeded dossier fallback (archetype, personality, runtime, plugins), runs section honestly hidden. */
export function SeedFallback() {
  return <Drawer id="vision" />;
}
