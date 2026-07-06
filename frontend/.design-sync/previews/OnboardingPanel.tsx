import React from 'react';
import { OnboardingPanel } from 'jarvis-hud-v2';

/* OnboardingPanel is a live-dashboard panel: zero props, fetches
   GET /api/onboarding/wizard on mount. Each story serves its own backend
   payload through a scoped fetch shim keyed off the card's ?story= param, so
   the REAL exported panel renders real data end-to-end — nothing is hand-drawn. */
const WIZARD_STEPS = [
  { key: 'backend', title: 'Connect the backend' },
  { key: 'agents', title: 'Meet your agent roster' },
  { key: 'channels', title: 'Pair a messaging channel' },
  { key: 'voice', title: 'Calibrate the wake-word' },
  { key: 'memory', title: 'Seed the knowledge graph' },
];

const STORIES: Record<string, Record<string, unknown>> = {
  FreshInstall: {
    '/api/onboarding/wizard': { complete: false, steps: WIZARD_STEPS, completed: [] },
  },
  InProgress: {
    '/api/onboarding/wizard': {
      complete: false,
      hint: 'wake-word not calibrated — say "Jarvis" three times',
      steps: WIZARD_STEPS,
      completed: ['backend', 'agents', 'channels'],
    },
  },
  Complete: {
    '/api/onboarding/wizard': {
      complete: true,
      steps: WIZARD_STEPS,
      completed: WIZARD_STEPS.map((s) => s.key),
    },
  },
};

const pick = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
const routes = STORIES[pick] || STORIES.InProgress;
const realFetch = window.fetch.bind(window);
window.fetch = ((input: any, init?: any) => {
  let path = '';
  try { path = new URL(typeof input === 'string' ? input : input && input.url, window.location.href).pathname; } catch { /* fall through */ }
  if (Object.prototype.hasOwnProperty.call(routes, path)) {
    return Promise.resolve(new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return realFetch(input, init);
}) as typeof window.fetch;

const frame: React.CSSProperties = { background: 'var(--void, #04070e)', borderRadius: 8, padding: 16, width: 380 };

/** Day zero — all five wizard steps open, each with its done control. */
export function FreshInstall() {
  return <div className="hud-root" style={frame}><OnboardingPanel /></div>;
}

/** Mid-setup (3/5) with the amber hint pointing at the next blocker. */
export function InProgress() {
  return <div className="hud-root" style={frame}><OnboardingPanel /></div>;
}

/** Everything checked off — "complete ✓" in the header. */
export function Complete() {
  return <div className="hud-root" style={frame}><OnboardingPanel /></div>;
}
