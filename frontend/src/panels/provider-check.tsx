/* H380 — does each configured cloud provider accept its key? `POST
   /api/admin/llm/providers/probe` sends one authenticated read of the provider's model
   list (nothing generated) and answers a verdict per provider; the hub caches it for a
   few minutes, so "check" is cheap and "re-check" (force) is refused while a verdict is
   fresher than its minimum interval. The key and the provider's reply are never shown:
   only the verdict, the HTTP status and how many models the key can see. Nothing is
   probed until the owner asks. */
import React, { useState } from 'react';
import { Card, Row, Tag, actA, arr, mono, refusalReason } from '../panel-kit';

export const PROBE_PATH = '/api/admin/llm/providers/probe';

const LABELS: Record<string, [string, string]> = {
  ok: ['key works', 'var(--green)'],
  no_listing: ['key not refused (no model list)', 'var(--green)'],
  auth_failed: ['key rejected (401)', 'var(--red)'],
  forbidden: ['key forbidden (403)', 'var(--red)'],
  rate_limited: ['rate limited (429)', 'var(--amber)'],
  error: ['provider error', 'var(--red)'],
  unreachable: ['unreachable', 'var(--red)'],
  refused: ['refused by the hub (wrong host protocol)', 'var(--red)'],
  not_configured: ['no key set', 'var(--ink-3)'],
  not_cloud: ['local', 'var(--ink-3)'],
};

export function ProviderCheckPanel() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const run = (provider?: string, force = false) => {
    setBusy(true);
    setMsg(null);
    const body: any = { force };
    if (provider) body.provider = provider;
    actA(PROBE_PATH, body,
      (r: any) => {
        const got = arr(r, 'providers');
        setRows((prev) => {
          if (!provider || !prev) return got;
          return prev.map((row) => (row.provider === provider && got[0] ? got[0] : row));
        });
        if (got.some((row: any) => row.throttled)) setMsg('checked moments ago; showing that result');
        setBusy(false);
      },
      (err: any) => { setMsg(`not checked · ${refusalReason(err, String(err?.status || 'error'))}`); setBusy(false); });
  };

  const bad = (rows || []).filter((row) => row.verdict !== 'not_configured' && !row.working).length;
  return (
    <Card title="CLOUD PROVIDER CHECK" live={rows ? 'live' : undefined} sub={rows ? (bad ? `${bad} failing` : 'ok') : null}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
        <button className="tool-btn" disabled={busy} onClick={() => run()}>{busy ? 'checking…' : 'check all providers'}</button>
        <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>one authenticated model-list read per provider with a key</span>
      </div>
      {(rows || []).map((row: any) => {
        const [label, color] = LABELS[row.verdict] || [String(row.verdict || '?'), 'var(--ink-3)'];
        return (
          <Row key={row.provider}>
            <span style={{ ...mono }}>{row.display_name || row.provider}</span>
            <Tag c={color}>{label}</Tag>
            {row.verdict === 'error' && row.status_code ? <Tag>HTTP {row.status_code}</Tag> : null}
            {row.models != null && row.working ? <Tag>{row.models} model(s)</Tag> : null}
            {row.cached ? <Tag>cached</Tag> : null}
            {row.verdict !== 'not_configured' && row.verdict !== 'not_cloud' && (
              <button className="tool-btn" style={{ marginLeft: 'auto' }} disabled={busy}
                aria-label={`re-check ${row.provider}`} onClick={() => run(row.provider, true)}>re-check</button>
            )}
          </Row>
        );
      })}
      {msg && <div role="status" style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>{msg}</div>}
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>keys and provider replies are never shown</div>
    </Card>
  );
}
