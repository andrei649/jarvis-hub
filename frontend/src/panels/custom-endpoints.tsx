import React, { useEffect, useState } from 'react';
import { apiDelete, apiDeleteBody, apiGet, apiPost, apiPut } from '../api/client';
import { Card } from '../panel-kit';

const BASE = '/api/admin/llm/custom-endpoints';

type Endpoint = {
  key: string; identity: string; name: string; host: string; model: string;
  auth_type: string; data_policy: string; destination_class: string;
  revision: number; active: boolean; credential_configured: boolean;
  credential_generation: number;
};
type Catalog = { endpoints: Endpoint[]; choice_epoch: number; active: string | null;
  legacy_recovery_candidate: string | null; unavailable: boolean };

function refusal(err: unknown): string {
  const response = err as { status?: number; body?: { error?: string; needs?: string[] } };
  const needs = response.body?.needs;
  return `refused · HTTP ${response.status || 'error'} · ${response.body?.error || 'request failed'}` +
    (Array.isArray(needs) && needs.length ? ` · needs ${needs.join(', ')}` : '');
}

export function CustomEndpointsPanel() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [form, setForm] = useState({ key: '', name: '', base_url: '', model: '',
    auth_type: 'none', data_policy: 'unknown', grant_destination: false });
  const [secret, setSecret] = useState('');
  const [secretFor, setSecretFor] = useState('');
  const [ackPrice, setAckPrice] = useState(false);
  const [ackPolicy, setAckPolicy] = useState(false);
  const [grantActive, setGrantActive] = useState(false);

  const reload = async () => {
    const next = await apiGet<Catalog>(BASE, { admin: true });
    setCatalog(next);
  };
  useEffect(() => { void reload().catch((err) => setMessage(refusal(err))); }, []);

  const run = async (operation: () => Promise<unknown>, successful: string, credential = false) => {
    setBusy(true); setMessage('');
    try {
      await operation();
      if (credential) setSecret('');
      await reload();
      setMessage(successful);
    } catch (err) {
      if (credential) setSecret('');
      setMessage(refusal(err) + ' · refresh the list before retrying');
      try { await reload(); } catch { /* keep the refusal visible */ }
    } finally { setBusy(false); }
  };

  const path = (key: string) => `${BASE}/${encodeURIComponent(key)}`;
  return <Card title="NAMED COMPATIBLE ENDPOINTS" live={catalog ? 'live' : undefined}
    sub={catalog?.active || 'no custom endpoint active'}>
    <p>Owner managed OpenAI compatible routes. Creation does not contact the destination. Unknown model price needs an explicit acknowledgment before activation.</p>
    {catalog?.unavailable && <p role="alert">Endpoint metadata unavailable; use the guarded clear action to recover the active choice.</p>}
    {catalog?.legacy_recovery_candidate && <p role="status">Legacy custom name: candidate {catalog.legacy_recovery_candidate}; owner activation is still required.</p>}
    <button type="button" disabled={busy} onClick={() => void reload().catch((err) => setMessage(refusal(err)))}>Refresh revisions</button>
    <form onSubmit={(event) => { event.preventDefault(); void run(
      () => apiPost(BASE, form, { admin: true }), 'Endpoint added; no validation request sent'); }}>
      <h4>Add endpoint</h4>
      {(['key', 'name', 'base_url', 'model'] as const).map((field) => <label key={field}>
        {field.replace('_', ' ')} <input aria-label={field} value={form[field]}
          onChange={(event) => setForm({ ...form, [field]: event.target.value })} required />
      </label>)}
      <label>Authentication <select aria-label="auth type" value={form.auth_type}
        onChange={(event) => setForm({ ...form, auth_type: event.target.value })}>
        <option value="none">none</option><option value="bearer">bearer</option><option value="api-key">API key</option>
      </select></label>
      <label>Data policy <select aria-label="data policy" value={form.data_policy}
        onChange={(event) => setForm({ ...form, data_policy: event.target.value })}>
        <option value="unknown">unknown</option><option value="local">local loopback</option>
        <option value="no-training">no training</option><option value="trains-on-inputs">trains on inputs</option>
      </select></label>
      <label><input type="checkbox" checked={form.grant_destination}
        onChange={(event) => setForm({ ...form, grant_destination: event.target.checked })} />
        Grant the exact LAN or public destination</label>
      <button type="submit" disabled={busy}>Add without probing</button>
    </form>
    <label><input type="checkbox" checked={ackPrice} onChange={(event) => setAckPrice(event.target.checked)} />
      I acknowledge unknown model price</label>
    <label><input type="checkbox" checked={ackPolicy} onChange={(event) => setAckPolicy(event.target.checked)} />
      I acknowledge the selected data policy</label>
    <label><input type="checkbox" checked={grantActive} onChange={(event) => setGrantActive(event.target.checked)} />
      Grant this exact LAN or public destination for activation</label>
    {(catalog?.endpoints || []).map((item) => <section key={item.key} aria-label={item.identity}>
      <h4>{item.name} · {item.identity}</h4>
      <p>{item.host} · {item.model} · {item.destination_class} · {item.data_policy} ·
        revision {item.revision} · credential {item.credential_configured ? 'configured' : 'absent'}
        {item.active ? ' · active' : ''}</p>
      <button disabled={busy || !ackPrice || (item.destination_class !== 'loopback' && !grantActive)} onClick={() => void run(
        () => apiPut(path(item.key) + '/activate', {
          expected_revision: item.revision, expected_choice_epoch: catalog!.choice_epoch,
          acknowledge_unknown_price: ackPrice, acknowledge_data_policy: ackPolicy,
          grant_destination: grantActive,
        }, { admin: true }), `${item.identity} selected`)}>Activate</button>
      <button disabled={busy || !item.active} onClick={() => void run(
        () => apiPost(path(item.key) + '/validate', {}, { admin: true }),
        `${item.identity} validation completed`)}>Validate /models</button>
      <button disabled={busy} onClick={() => {
        const name = window.prompt('New display name', item.name);
        if (name && name !== item.name) void run(() => apiPut(path(item.key),
          { name, expected_revision: item.revision }, { admin: true }), 'Name updated');
      }}>Rename</button>
      <button disabled={busy} onClick={() => void run(() => apiDeleteBody(path(item.key),
        { expected_revision: item.revision }, { admin: true }), 'Endpoint deleted')}>Delete</button>
      <button disabled={busy} onClick={() => { setSecretFor(item.key); setSecret(''); }}>Credential</button>
      {secretFor === item.key && <div>
        <label>Secret (never shown after submit) <input aria-label={`secret for ${item.key}`}
          type="password" autoComplete="off" value={secret}
          onChange={(event) => setSecret(event.target.value)} /></label>
        <button disabled={busy || !secret} onClick={() => void run(
          () => apiPut(path(item.key) + '/credential', { secret }, { admin: true }),
          'Credential stored', true)}>Set or rotate</button>
        <button disabled={busy} onClick={() => void run(
          () => apiDelete(path(item.key) + '/credential', { admin: true }),
          'Credential removed', true)}>Remove credential</button>
      </div>}
    </section>)}
    {catalog?.active && <button disabled={busy} onClick={() => void run(
      () => apiDeleteBody(BASE + '/active', { expected_choice_epoch: catalog.choice_epoch },
        { admin: true }), 'Custom choice cleared')}>Clear active choice</button>}
    {message && <p role="status">{message}</p>}
  </Card>;
}
