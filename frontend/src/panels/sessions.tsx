/* H441 — getting back into a conversation. Resume switches the hub to a past session
   and now answers with a recap the hub rendered from the stored turns, with no model
   call: the last exchanges, each turn on one line, and the tools a reply used
   collapsed to a count ("[3 tool calls: terminal_run, web_search]"). Before this the
   resume button posted and showed nothing; the owner had to open the chat and re-read
   the raw turns. Text only: a turn is rendered as text, never as markup. */
import React, { useState } from 'react';
import { apiPost } from '../api/client';
import { Card, Row, State, arr, asLive, mono, refusalReason, useApi } from '../panel-kit';

export const RESUME_PATH = '/sessions/resume';

/** "[3 tool calls: a, b]" — the count of calls, then the distinct names. */
export function toolLine(entry: any): string {
  const n = Number(entry?.tool_calls) || 0;
  if (!n) return '';
  const names = Array.isArray(entry?.tools) ? entry.tools.map(String) : [];
  return `[${n} tool call${n === 1 ? '' : 's'}${names.length ? `: ${names.join(', ')}` : ''}]`;
}

export function RecapView({ recap, session }: { recap: any; session: string }) {
  const exchanges = Array.isArray(recap?.exchanges) ? recap.exchanges : [];
  const total = Number(recap?.total) || exchanges.length;
  return <div data-testid="session-recap" style={{ marginTop: 8, borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
    <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.16em', color: 'var(--ink-3)', marginBottom: 4 }}>
      RESUMED {session} · {exchanges.length < total ? `LAST ${exchanges.length} OF ${total} EXCHANGES` : `${total} EXCHANGE${total === 1 ? '' : 'S'}`}
    </div>
    {exchanges.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>This conversation has no turns yet.</div>}
    {exchanges.map((ex: any[], i: number) => <div key={i} data-testid="recap-exchange" style={{ padding: '3px 0' }}>
      {(Array.isArray(ex) ? ex : []).map((t: any, j: number) => (
        <div key={j} style={{ fontSize: 11, lineHeight: 1.45, color: t.role === 'user' ? 'var(--amber)' : 'var(--ink)' }}>
          <span aria-hidden="true">{t.role === 'user' ? '● ' : '◆ '}</span>
          <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>{t.role === 'user' ? 'you' : (t.agent || 'nerva')}: </span>
          {String(t.text ?? '')}
          {toolLine(t) && <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}> {toolLine(t)}</span>}
        </div>
      ))}
    </div>)}
  </div>;
}

export function SessionsPanel() {
  const { d, e, loading, reload } = useApi('/sessions');
  const list = arr(d, 'sessions');
  const [resumed, setResumed] = useState<any>(null);   // { session, recap }
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const resume = (sid: string) => {
    setBusy(sid); setError('');
    apiPost(RESUME_PATH, { session_id: sid })
      .then((r: any) => setResumed({ session: r?.session || sid, recap: r?.recap || null }))
      .catch((err) => { setResumed(null); setError(`not resumed · ${refusalReason(err, 'refused')}`); })
      .finally(() => setBusy(''));
  };
  return <Card title="SESSIONS" live={asLive(d)} sub={list.length} onReload={reload}>
    <State e={e} loading={loading} n={list.length} />
    {list.slice(0, 12).map((s: any, i: number) => {
      const sid = s?.session_id || s?.id || (typeof s === 'string' ? s : '');
      return <Row key={i}>
        {/* H413: the session's title (its first words, then the local model's name); the id stays visible. */}
        {s?.title
          ? <span style={{ fontSize: 12, color: 'var(--ink)' }} title={sid}>{s.title}
              <span style={{ ...mono, fontSize: 9.5, color: 'var(--ink-3)', marginLeft: 6 }}>{sid.slice(0, 8)}</span></span>
          : <span style={{ ...mono, color: 'var(--accent-light)' }}>{sid}</span>}
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>{s?.turns ?? s?.count ?? ''}</span>
        {sid && <button className="tool-btn" disabled={!!busy} aria-label={`resume ${sid}`} onClick={() => resume(sid)}>
          {busy === sid ? 'resuming…' : 'resume'}
        </button>}
      </Row>;
    })}
    {error && <div role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>{error}</div>}
    {resumed && (resumed.recap
      ? <RecapView recap={resumed.recap} session={resumed.session} />
      : <div role="status" style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>resumed {resumed.session}</div>)}
  </Card>;
}
