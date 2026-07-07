import React from 'react';
import { Ticker, V2 } from 'jarvis-hud-v2';

const T = { situation: 'SITUATION', allnominal: 'ALL NOMINAL' };

/** The situation ticker with the repo's own seed feed (V2.TICKER). */
export function LiveFeed() {
  return (
    <div className="hud-root" style={{ width: 720, background: 'var(--void, #04070e)', borderRadius: 8, padding: 8 }}>
      <Ticker items={V2.TICKER} t={T} />
    </div>
  );
}

/** Mixed-status items — ok / warn / plain classes drive the item accents. */
export function Statuses() {
  const items = [
    { agent: 'ULTRON', verb: 'flagged', text: '2 PII matches redacted in outbound draft', cls: 'warn', bar: 40 },
    { agent: 'STARK', verb: 'computed', text: 'MRR +6.2% WoW', cls: 'ok', bar: 88 },
    { agent: 'PEPPER', verb: 'reconciled', text: 'moved prep to 13:15', cls: '', bar: 72 },
  ];
  return (
    <div className="hud-root" style={{ width: 720, background: 'var(--void, #04070e)', borderRadius: 8, padding: 8 }}>
      <Ticker items={items} t={T} />
    </div>
  );
}
