import React from 'react';
import { FinanceMode, V2 } from 'jarvis-hud-v2';

/* FinanceMode (Gecko's home) is pure seed data (V2.FINANCE) — no fetches. The Ring-less
   money view: net-worth hero, accounts, FX watches, budget meters, pending approvals. */
const T = V2.I18N.en;
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, zoom: 0.65 } as React.CSSProperties;
const stage: React.CSSProperties = { width: 1300, height: 600, display: 'flex' };
/* 900px capture viewport < the 1300px breakpoint collapsing .admin-grid (styles.css:544)
   — scoped desktop re-assert; config-level fix needs viewport ≥1301px (see learnings). */
const Wide = () => <style>{'.w2wide .admin-grid{grid-template-columns:1fr 1fr;gap:var(--gap) 28px}'}</style>;

/** Gecko's overview — €312k net worth hero, four accounts, FX watch bands (BTC warn), budget meters, €4.2k sweep pending approval. */
export function GeckoOverview() {
  return (
    <div className="hud-root w2wide" style={wrap}>
      <Wide />
      <div style={stage}><FinanceMode t={T} /></div>
    </div>
  );
}

/** The same desk on the green accent family — the money-mode accent variant of the DS theme axis. */
export function GreenAccent() {
  return (
    <div className="hud-root w2wide" data-accent="green" style={wrap}>
      <Wide />
      <div style={stage}><FinanceMode t={T} /></div>
    </div>
  );
}
