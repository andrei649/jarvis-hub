import React from 'react';
import { CapabilitiesPanel } from 'jarvis-hud-v2';

/* CapabilitiesPanel is the one gap.tsx panel that does NOT fetch on mount — it renders
   its full issue/check composition from initial state (caps input prefilled with
   'fs.read,memory.write', check row prefilled with 'memory.write'). Issued grants and
   check verdicts only exist after admin POSTs, so the honest static story set is the
   single initial state. */
const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 380 };

/** The mint-and-verify surface at rest — issue a capability token, check a token id. */
export function IssueAndCheck() {
  return <div className="hud-root" style={wrap}><CapabilitiesPanel /></div>;
}
