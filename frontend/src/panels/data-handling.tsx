import React, { useState } from 'react';
import { apiPost } from '../api/client';
import { mono, Tag } from '../panel-kit';

const ROLE_LABELS = {
  'role:approval_judge': 'Approval judge',
  'role:telegram_media_reader': 'Telegram image descriptions',
  'role:camera_descriptions': 'Camera descriptions',
  'role:video_analysis': 'Video analysis',
};

export function DataHandling({ value, reload }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  if (!value) return null;
  const providers = Array.isArray(value.providers) ? value.providers : [];
  const targets = Array.isArray(value.targets) ? value.targets.filter(t => Object.prototype.hasOwnProperty.call(ROLE_LABELS, t?.target_id)) : [];
  const identity = (row) => row.target_id || `provider:${row.provider}`;
  const update = async (provider) => {
    setBusy(identity(provider));
    setError('');
    try {
      const result = await apiPost<{ ok: boolean }>('/api/security/data-handling/ack', {
        provider: provider.provider, acknowledged: !provider.acknowledged, scope: provider.scope,
        ...(provider.target_id ? { target: provider.target_id } : {}),
      }, { admin: true });
      if (result?.ok !== true) throw new Error('Consent was not saved.');
      await reload();
    } catch (err) {
      setError(typeof err?.body?.detail === 'string' ? err.body.detail
        : typeof err?.body?.error === 'string' ? err.body.error
          : err?.message || 'Consent could not be changed.');
    } finally {
      setBusy(null);
    }
  };
  return <section aria-label="Provider data handling" style={{ marginTop: 12 }}>
    <div style={mono}>provider data handling</div>
    <p style={{ fontSize: 11, color: 'var(--ink-2)' }}>
      These controls cover routed agent conversations, tool runs and context caching.
      Separate provider integrations may use their own controls.
    </p>
    {value.settings_readable === false && <div role="alert" style={{ color: 'var(--amber)' }}>
      Consent settings unavailable; unattended use of providers with unknown or training policies is blocked.
    </div>}
    {value.role_settings_readable === false && <div role="alert" style={{ color: 'var(--amber)' }}>
      Role consent settings unavailable; unattended use of role models with unknown or training policies is blocked.
    </div>}
    {targets.some(t => t.target_id === 'role:approval_judge') && <p style={{ fontSize: 11, color: 'var(--ink-2)' }}>
      Approval judge consent is separate from provider consent. Acknowledgment does not enable remote judging.
    </p>}
    {targets.some(t => t.target_id === 'role:telegram_media_reader') && <p style={{ fontSize: 11, color: 'var(--ink-2)' }}>
      Telegram image descriptions require a local VLM on the Nerva server.
      Unknown or training policies require their own acknowledgment.
      Acknowledgment does not enable remote image descriptions.
    </p>}
    {targets.some(t => t.target_id === 'role:camera_descriptions') && <p style={{ fontSize: 11, color: 'var(--ink-2)' }}>
      Camera descriptions require a local VLM on the Nerva server.
      Unknown or training policies require separate model-data acknowledgment.
      Acknowledgment does not enable camera capture, event description or remote destinations,
      and does not replace household consent.
    </p>}
    {targets.some(t => t.target_id === 'role:video_analysis') && <p style={{ fontSize: 11, color: 'var(--ink-2)' }}>
      Video analysis requires a separate owner-approved tool call. Remote model use also
      requires explicit approval and this role's configuration-bound consent.
    </p>}
    {[...providers, ...targets].map((p, index) => <div key={`${identity(p)}:${p.scope || ''}:${index}`} style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
      <span style={mono}>{p.target_id ? ROLE_LABELS[p.target_id] : p.provider}</span>{' '}
      <Tag c={p.warning ? 'var(--amber)' : 'var(--ink-3)'}>{p.policy || 'unknown'}</Tag>
      {p.target_id && <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>{p.provider} · {p.mode} · {p.model}</div>}
      {p.note && <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>{p.note}</div>}
      {p.warning && <>
        <div style={{ fontSize: 11, color: 'var(--amber)', marginTop: 4 }}>{p.warning}</div>
        <div style={{ fontSize: 11, marginTop: 4 }}>
          {p.acknowledged ? 'Unattended use allowed for this configuration.' : 'Unattended use requires your acknowledgment.'}
        </div>
        {p.acknowledgment_unavailable && <div style={{ fontSize: 11, color: 'var(--amber)' }}>{p.acknowledgment_unavailable}</div>}
        <button className="tool-btn" style={{ marginTop: 4 }}
          aria-label={`${p.acknowledged ? 'Revoke' : 'Allow'} unattended use for ${p.target_id ? ROLE_LABELS[p.target_id] : p.provider}`}
          disabled={busy !== null || (p.target_id ? value.role_settings_readable : value.settings_readable) !== true || p.can_acknowledge === false || !p.scope}
          onClick={() => update(p)}>
          {busy === identity(p) ? 'saving…' : p.acknowledged ? 'revoke unattended use' : 'allow unattended use'}
        </button>
      </>}
    </div>)}
    {error && <div role="alert" style={{ color: 'var(--red)', marginTop: 6 }}>{error}</div>}
  </section>;
}
