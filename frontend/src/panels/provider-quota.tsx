/* H373 — how much quota each cloud provider says is left. `GET /api/llm/quota` answers what
   the providers' own responses reported (requests and tokens left, when they reset), from
   every process on this hub, and any shared 429 hold: after a 429 every process holds
   requests on that key until the provider's retry-after. Read-only; keys show only as a
   short fingerprint. */
import React from 'react';
import { Card, Row, State, Tag, arr, asLive, mono, useApi } from '../panel-kit';

export const QUOTA_PATH = '/api/llm/quota';

function Bar({ left }: { left: number | null }) {
  if (left == null) return null;
  const pct = Math.round(left * 100);
  const color = pct <= 10 ? 'var(--red)' : pct <= 30 ? 'var(--amber)' : 'var(--green)';
  return (
    <span aria-label={`${pct}% left`} style={{ display: 'inline-block', width: 80, height: 5, borderRadius: 3, background: 'var(--panel-line)', overflow: 'hidden' }}>
      <span style={{ display: 'block', height: '100%', width: `${pct}%`, background: color }} />
    </span>
  );
}

function secs(n: number | null) {
  if (n == null) return '';
  return n >= 60 ? `${Math.round(n / 60)}m` : `${Math.round(n)}s`;
}

export function ProviderQuotaPanel() {
  const d = useApi(QUOTA_PATH, true, true);
  const rows = d.e ? [] : arr(d.d, 'providers');
  const held = rows.filter((row: any) => row.blocked).length;
  return (
    <Card title="PROVIDER QUOTA" live={asLive(d.e ? null : d.d)} sub={held ? `${held} held after a 429` : `${rows.length} seen`} onReload={d.reload}>
      <State e={d.e} loading={d.loading} n={rows.length} />
      {!d.e && !d.loading && !rows.length ? <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>it is read from each cloud provider's responses</div> : null}
      {rows.map((row: any) => (
        <div key={`${row.backend}:${row.key}`} style={{ marginBottom: 6 }}>
          <Row>
            <span style={{ ...mono }}>{row.backend}{row.key ? ` · key ${String(row.key).slice(0, 6)}` : ''}</span>
            {row.blocked ? <Tag c="var(--red)">held {secs(row.blocked_for)} after a {row.block_status}</Tag> : null}
          </Row>
          {Object.entries(row.quota || {}).map(([kind, q]: [string, any]) => (
            <Row key={kind}>
              <span style={{ fontSize: 10, color: 'var(--ink-3)', minWidth: 90 }}>{kind}</span>
              <Bar left={q.left} />
              <span style={{ ...mono, fontSize: 10 }}>{q.remaining ?? '?'}{q.limit != null ? `/${q.limit}` : ''}</span>
              {q.resets_in != null ? <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>resets in {secs(q.resets_in)}</span> : null}
            </Row>
          ))}
        </div>
      ))}
    </Card>
  );
}
