/* H403 / H443 — what one conversation has used, by purpose: its turns (`turn`) and the
   post-turn learning reviews made for it (`background_review`, a /refine included).
   `GET /api/analytics/session-usage?session_id=…` (admin) reads the cost ledger's
   per-session row; the review's calls are a line of their own there, never folded into the
   turn's. `unmeasured` is calls that were dispatched and never certified by the provider (a
   review cancelled or failed mid-call): shown as a count, with no tokens invented for them.
   Shown inside the APM card; a conversation the ledger has no row for says so. */
import React, { useState } from 'react';
import { apiGet } from '../api/client';
import { Row, inpS, mono, refusalReason } from '../panel-kit';

export const SESSION_USAGE_PATH = '/api/analytics/session-usage';
const PURPOSE_LABELS: Record<string, string> = { turn: 'turns', background_review: 'background review' };

const num = (v: any): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const n = (v: any): string => num(v).toLocaleString('en-US');

/** One row of the ledger in words: calls, tokens in and out, and what was not measured. */
export function usageLine(slot: any): string {
  const parts = [`${n(slot?.calls)} calls`, `${n(slot?.input_tokens)} in`, `${n(slot?.output_tokens)} out`];
  if (num(slot?.unmeasured_calls) > 0) parts.push(`${n(slot.unmeasured_calls)} unmeasured`);
  return parts.join(' · ');
}

export function SessionUsage() {
  const [sid, setSid] = useState('default');
  const [out, setOut] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const read = () => {
    const id = sid.trim();
    if (!id) return;
    setErr(null);
    apiGet(`${SESSION_USAGE_PATH}?session_id=${encodeURIComponent(id)}`, { admin: true })
      .then((r: any) => setOut(r))
      .catch((e: any) => { setOut(null); setErr(refusalReason(e, String(e?.status || 'error'))); });
  };
  const purposes = (out && out.usage && out.usage.purposes) || {};
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', letterSpacing: '.08em' }}>ONE CONVERSATION</div>
      <div style={{ display: 'flex', gap: 6, marginTop: 3 }}>
        <input aria-label="conversation id" value={sid} onChange={(ev) => setSid(ev.target.value)}
          onKeyDown={(ev) => { if (ev.key === 'Enter') read(); }} style={{ ...inpS, flex: 1 }} />
        <button className="tool-btn" onClick={read}>usage</button>
      </div>
      {err && <div role="status" style={{ fontSize: 10, color: 'var(--amber)' }}>not read · {err}</div>}
      {out && out.found === false && (
        <div role="status" style={{ fontSize: 11, color: 'var(--ink-2)' }}>no usage recorded for {String(out.session_id)}</div>
      )}
      {out && out.found === true && (
        <div style={{ ...mono, fontSize: 11 }}>
          <Row><span>all</span><span style={{ marginLeft: 'auto' }}>{usageLine(out.usage)}</span></Row>
          {Object.keys(purposes).sort().map((name) => (
            <Row key={name}>
              <span>{PURPOSE_LABELS[name] || name}</span>
              <span aria-label={`${PURPOSE_LABELS[name] || name} usage`} style={{ marginLeft: 'auto' }}>{usageLine(purposes[name])}</span>
            </Row>
          ))}
        </div>
      )}
    </div>
  );
}
