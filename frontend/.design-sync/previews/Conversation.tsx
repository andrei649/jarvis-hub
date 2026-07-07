import React from 'react';
import { Conversation, V2 } from 'jarvis-hud-v2';

const noop = () => {};
const wrap: React.CSSProperties = { width: 680, background: 'var(--void, #04070e)', borderRadius: 8, padding: 16 };

const MESSAGES = [
  ...V2.SEED_MESSAGES,
  { role: 'user', text: 'Draft the churn-cohort slide for the Raiffeisen deck.', ts: '08:04' },
  {
    role: 'agent', who: 'stark', role_label: 'Biz Intel', ts: '08:05',
    text: 'Done — slide drafted from the current KPI store. **Churn 2.3%**, down 0.4pt QoQ, cohort table framed the way Raiffeisen asked last quarter. Staged in the prep deck for 13:15.',
    prov: { agents: ['stark'], plugins: ['gmail'], local: true, conf: 0.85 },
  },
];

/** Canonical exchange — user bubbles, agent replies with provenance chips. */
export function MorningBriefing() {
  return (
    <div className="hud-root" style={wrap}>
      <Conversation messages={MESSAGES} thinking={null} onStop={null} onProv={noop} lang="en" t={V2.I18N.en} />
    </div>
  );
}

/** Mid-generation — thinking indicator with routing pill and stop control. */
export function Thinking() {
  return (
    <div className="hud-root" style={wrap}>
      <Conversation
        messages={[{ role: 'user', text: 'What does my day look like?', ts: '08:02' }]}
        thinking={{ label: 'thinking', route: ['PEPPER', 'STARK', 'FRIDAY'] }}
        onStop={noop} onProv={noop} lang="en" t={V2.I18N.en} />
    </div>
  );
}
