import React from 'react';
import { ChatMode, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
/* ChatMode's .chat-wrap is flex:1 — definite-height flex stage; the 840px chat
   column centers itself, so the stage stays near-natural width at zoom .9. */
const stage: React.CSSProperties = { width: 880, height: 640, background: 'var(--void, #04070e)',
  borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', zoom: 0.9 } as React.CSSProperties;

const MESSAGES = [
  ...V2.SEED_MESSAGES,
  { role: 'user', text: 'Protect the Raiffeisen prep — and draft the churn slide Stark flagged.', ts: '08:04' },
  {
    role: 'agent', who: 'stark', role_label: 'Biz Intel', ts: '08:05',
    text: 'Slide drafted from the current KPI store — **churn 2.3%**, down 0.4pt QoQ, cohort table framed the way Raiffeisen asked last quarter. Pepper blocked 13:15–14:00 for prep.',
    prov: { agents: ['stark', 'pepper'], plugins: ['gmail', 'google-calendar'], local: true, conf: 0.85 },
  },
];

/** Distraction-free direct line — header with live/local chip, exchange with provenance, idle input bar. */
export function DirectLine() {
  return (
    <div className="hud-root" style={stage}>
      <ChatMode messages={MESSAGES} thinking={null} onStop={noop} onSubmit={noop} onProv={noop}
        mic={false} setMic={noop} lang="en" t={T} />
    </div>
  );
}

/** Mid-turn — thinking indicator with the routing pill while Jarvis composes. */
export function Thinking() {
  return (
    <div className="hud-root" style={stage}>
      <ChatMode
        messages={[{ role: 'user', text: 'What does my day look like?', ts: '08:02' }]}
        thinking={{ label: 'thinking · route', route: ['PEPPER', 'STARK', 'FRIDAY'] }}
        onStop={noop} onSubmit={noop} onProv={noop} mic={false} setMic={noop} lang="en" t={T} />
    </div>
  );
}
