/* CONTEXT METER (H412) — what fills the model's window for one conversation.

     · GET /sessions/{session_id}/context   (admin tier)  routers/sessions.py

   The route reads the SAME policy object the compaction loop uses (the window, the soft
   tier where images go first, the hard tier where older text is summarised), so the bar and
   the tier names here are the compressor's own, never a second estimate. Every figure is an
   estimate from the runtime's token estimator and the panel says so; when the provider
   measured the last request (H673) that number is shown beside it.

   The categories (system, tools, skills, memory, history, attachments) add up to `used`;
   `free` is the rest of the window. Read-only: nothing here compacts or changes the
   conversation — /compress in the chat reports what the next turn's compaction will do. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, inpS } from '../panel-kit';

export const CATEGORY_COLORS: Record<string, string> = {
  system: 'var(--accent-light)',
  tools: 'var(--amber)',
  skills: 'var(--violet, #a78bfa)',
  memory: 'var(--green)',
  history: 'var(--ink)',
  attachments: 'var(--red)',
  free: 'var(--panel-line)',
};

const TIER_TEXT: Record<string, string> = {
  none: 'below the soft tier — the next request sends this conversation unchanged',
  images: 'above the soft tier — older images are dropped first',
  summarize: 'above the hard tier — older text is summarised (first and latest turns kept)',
};

export function MeterBar({ meter }: { meter: any }) {
  const window = Number(meter?.window) || 0;
  const cats = arr(meter, 'categories');
  if (!window) return null;
  return (
    <div role="img" aria-label={`context ${meter.used} of ${window} tokens`}
      style={{ display: 'flex', height: 12, border: '1px solid var(--panel-line)', borderRadius: 3, overflow: 'hidden' }}>
      {cats.map((c: any) => (
        <div key={c.name} data-cat={c.name} title={`${c.name}: ${c.tokens} tokens`}
          style={{ width: `${Math.min(100, (100 * (Number(c.tokens) || 0)) / window)}%`, background: CATEGORY_COLORS[c.name] }} />
      ))}
    </div>
  );
}

export function ContextMeterPanel() {
  const sessions = useApi('/sessions');
  const first = arr(sessions.d, 'sessions')[0];
  const fallback = first?.session_id || first?.id || '';
  const [typed, setTyped] = useState('');
  const sid = (typed || fallback || '').trim();
  const { d, e, loading, reload } = useApi(sid ? `/sessions/${encodeURIComponent(sid)}/context` : '/sessions/-/context', !!sid, true);
  const meter = sid ? d : null;
  return (
    <Card title="Context meter" sub="what fills the model's window · estimates" live={asLive(meter)} onReload={reload}>
      <Row>
        <span style={{ ...mono }}>session</span>
        <input aria-label="session id" style={{ ...inpS, flex: 1 }} placeholder={fallback || 'session id'}
          value={typed} onChange={(ev) => setTyped(ev.target.value)} />
      </Row>
      {!sid ? <div style={{ fontSize: 12, color: 'var(--ink-2)' }}>No conversation to measure yet.</div> : null}
      {sid ? <State e={e} loading={loading && !meter} n={meter ? 1 : 0} /> : null}
      {meter ? (
        <div>
          <div style={{ ...mono, margin: '6px 0' }}>
            {Number(meter.used).toLocaleString()} of {Number(meter.window).toLocaleString()} tokens ({meter.percent}%) · model {meter.model || 'default'}
          </div>
          <MeterBar meter={meter} />
          {arr(meter, 'categories').map((c: any) => (
            <Row key={c.name}>
              <span style={{ width: 10, height: 10, background: CATEGORY_COLORS[c.name], display: 'inline-block' }} />
              <span style={{ ...mono, width: 90 }}>{c.name}</span>
              <span style={{ ...mono, marginLeft: 'auto' }}>{Number(c.tokens).toLocaleString()}</span>
              <Tag>{(Number(c.share) * 100).toFixed(1)}%</Tag>
            </Row>
          ))}
          <Row>
            <span style={{ ...mono, width: 100 }}>free</span>
            <span style={{ ...mono, marginLeft: 'auto' }}>{Number(meter.free).toLocaleString()}</span>
          </Row>
          <div style={{ fontSize: 12, marginTop: 6 }} data-testid="tier">
            Compaction tier <Tag>{meter.compaction_tier}</Tag> {TIER_TEXT[meter.compaction_tier] || ''}
          </div>
          {meter.measured ? (
            <div style={{ fontSize: 12, color: 'var(--ink-2)' }}>The provider measured the last request at {Number(meter.measured).toLocaleString()} tokens.</div>
          ) : null}
          <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>{meter.note}</div>
        </div>
      ) : null}
    </Card>
  );
}
