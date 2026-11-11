import React, { useState } from 'react';
import { apiPost } from '../api/client';
import { mono } from '../panel-kit';

// H496 — guest turns use none of the owner's credentials unless the owner shares one
// integration here. Each share is recorded (who, when) and written to the audit log.
const KIND_LABELS = {
  provider: 'cloud model provider',
  mcp: 'MCP server',
  web_search: 'web search backend',
  skill: 'skill setup values',
  secret: 'secret handle',
};

export function CredentialShares({ value, reload }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [kind, setKind] = useState('mcp');
  const [name, setName] = useState('');
  if (!value) return null;
  const shares = Array.isArray(value.shares) ? value.shares : [];
  const post = async (integration: string, shared: boolean) => {
    setBusy(true);
    setError('');
    try {
      const result = await apiPost<{ shared: boolean }>('/api/security/credential-shares',
        { integration, shared }, { admin: true });
      if (result?.shared !== shared) throw new Error('The share was not recorded.');
      setName('');
      await reload();
    } catch (err) {
      setError(typeof err?.body?.error === 'string' ? err.body.error
        : err?.message || 'The share could not be changed.');
    } finally {
      setBusy(false);
    }
  };
  return <section aria-label="Credentials shared with guests" style={{ marginTop: 12 }}>
    <div style={mono}>credentials shared with guests</div>
    <p style={{ fontSize: 11, color: 'var(--ink-2)' }}>
      Guests (household tokens, paired chat senders, other API keys) use none of your
      credentials. Share one integration only when guests should spend it.
    </p>
    {value.error && <div role="alert" style={{ color: 'var(--amber)' }}>{value.error}</div>}
    {shares.length === 0 && <div style={{ fontSize: 11 }}>Nothing is shared.</div>}
    {shares.map(row => <div key={row.integration} style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
      <span style={mono}>{row.integration}</span>
      {row.note && <span style={{ fontSize: 11, color: 'var(--ink-2)' }}> · {row.note}</span>}
      <button className="tool-btn" style={{ marginLeft: 8 }} disabled={busy}
        aria-label={`Stop sharing ${row.integration}`} onClick={() => post(row.integration, false)}>
        stop sharing
      </button>
    </div>)}
    <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
      <select aria-label="Credential kind" value={kind} onChange={e => setKind(e.target.value)} disabled={busy}>
        {Object.entries(KIND_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
      </select>
      <input aria-label="Integration name" value={name} placeholder="name" maxLength={128}
        onChange={e => setName(e.target.value)} disabled={busy} />
      <button className="tool-btn" disabled={busy || !name.trim()}
        onClick={() => post(`${kind}:${name.trim()}`, true)}>share with guests</button>
    </div>
    {error && <div role="alert" style={{ color: 'var(--red)', marginTop: 6 }}>{error}</div>}
  </section>;
}
