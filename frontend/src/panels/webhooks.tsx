/* H200 / H153 — inbound webhooks, managed from the cockpit.

   The hub's admin-only hook routes (list, create, switch, delete) were reachable
   only by a hand-built admin request; Interop mode showed a read-only list. This
   panel lists every hook (target, HMAC or token, on or off, calls, last call),
   and creates, switches and deletes them with the admin credential.

   A new hook's token or signing secret is shown exactly once. It lives only in this
   component's state, is dropped on dismiss or unmount, and the list never carries
   it (the hub masks it to a four-character hint). Deleting asks first, because the
   sender's credential dies with the hook; switching a hook off keeps it. */
import React, { useState } from 'react';
import { appUrl } from '../base-path';
import { apiDelete, apiPatch, apiPost } from '../api/client';
import { Card, Row, State, Tag, arr, asLive, inpS, mono, refusalReason, useApi } from '../panel-kit';

const HOOKS_PATH = '/api/webhooks';

/** The absolute URL an external sender posts to. */
export function triggerUrl(id: string): string {
  const path = appUrl(`${HOOKS_PATH}/${encodeURIComponent(id)}`);
  try {
    return new URL(path, window.location.origin).href;
  } catch {
    return path;
  }
}

function when(ts: any): string {
  const seconds = Number(ts);
  if (!Number.isFinite(seconds) || seconds <= 0) return 'never';
  try {
    return `${new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
  } catch {
    return 'never';
  }
}

function Copy({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    try {
      const pending = navigator.clipboard && navigator.clipboard.writeText(value);
      if (pending && typeof pending.then === 'function') pending.then(() => setCopied(true), () => setCopied(false));
    } catch {
      /* no clipboard: the value stays on screen to select by hand */
    }
  };
  return <button className="tool-btn" onClick={copy} aria-label={`copy the ${label}`}>{copied ? 'copied' : 'copy'}</button>;
}

/** Right after creation, and never again: nothing else ever holds the secret. */
function Reveal({ hook, onDismiss }: { hook: any; onDismiss: () => void }) {
  const kind = hook.signed ? 'signing secret' : 'token';
  const secret = String((hook.signed ? hook.signing_secret : hook.token) || '');
  const url = triggerUrl(hook.id);
  return (
    <div role="alert" style={{ border: '1px solid var(--amber)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div style={{ ...mono, color: 'var(--amber)', marginBottom: 4 }}>
        Save these now. The {kind} is shown once and never again.
      </div>
      <Row>
        <span style={mono}>URL</span>
        <code style={{ ...mono, overflowWrap: 'anywhere' }}>{url}</code>
        <Copy value={url} label="URL" />
      </Row>
      <Row>
        <span style={mono}>{kind}</span>
        <code data-testid="webhook-secret" style={{ ...mono, overflowWrap: 'anywhere' }}>{secret}</code>
        <Copy value={secret} label={kind} />
      </Row>
      <div style={{ ...mono, color: 'var(--ink-2)', margin: '4px 0 6px' }}>
        {hook.signed
          ? 'The sender signs each raw body: X-Signature-256: sha256=<HMAC-SHA256 with this secret>.'
          : 'The sender puts it in the X-Webhook-Token header.'}
      </div>
      <button className="tool-btn" onClick={onDismiss}>I have saved it</button>
    </div>
  );
}

export function WebhooksPanel() {
  const list = useApi(HOOKS_PATH, true, true);
  const hooks = arr(list.d, 'webhooks');
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [targetType, setTargetType] = useState('agent');
  const [signed, setSigned] = useState(false);
  const [created, setCreated] = useState<any>(null);
  const [open, setOpen] = useState('');
  const [confirming, setConfirming] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const refused = (err: any) => setNote(`refused · ${refusalReason(err)}`);
  const create = () => {
    if (!target.trim()) {
      setNote(`name the ${targetType} this webhook runs`);
      return;
    }
    setBusy(true);
    apiPost(HOOKS_PATH, { name: name.trim(), target: target.trim(), target_type: targetType, signed }, { admin: true })
      .then((rec: any) => {
        setCreated(rec);
        setName('');
        setTarget('');
        setNote('');
        list.reload();
      })
      .catch(refused)
      .finally(() => setBusy(false));
  };
  const toggle = (hook: any) => apiPatch(`${HOOKS_PATH}/${encodeURIComponent(hook.id)}`, { enabled: !hook.enabled }, { admin: true })
    .then(() => { setNote(''); list.reload(); })
    .catch(refused);
  const remove = (id: string) => apiDelete(`${HOOKS_PATH}/${encodeURIComponent(id)}`, { admin: true })
    .then(() => { setConfirming(''); setNote(''); list.reload(); })
    .catch(refused);

  return (
    <Card title="WEBHOOKS" live={asLive(list.d)} sub={`${hooks.length} inbound`} onReload={list.reload}>
      {created && <Reveal hook={created} onDismiss={() => setCreated(null)} />}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 8 }}>
        <input aria-label="webhook name" placeholder="name" value={name} maxLength={128}
          onChange={(e) => setName(e.target.value)} style={inpS} />
        <select aria-label="target type" value={targetType} onChange={(e) => setTargetType(e.target.value)} style={inpS}>
          <option value="agent">agent</option>
          <option value="workflow">workflow</option>
        </select>
        <input aria-label="target" placeholder={`${targetType} id`} value={target} maxLength={128}
          onChange={(e) => setTarget(e.target.value)} style={inpS} />
        <label style={mono}>
          <input type="checkbox" checked={signed} onChange={(e) => setSigned(e.target.checked)} /> HMAC-signed
        </label>
        <button className="tool-btn" disabled={busy} onClick={create}>create</button>
      </div>
      {note && <div role="status" style={{ ...mono, color: 'var(--amber)', marginBottom: 6 }}>{note}</div>}
      <State e={list.e} loading={list.loading && !list.d} n={hooks.length} />
      {hooks.map((hook: any) => (
        <div key={hook.id}>
          <Row>
            <button className="tool-btn" aria-expanded={open === hook.id} style={{ ...mono, textAlign: 'left' }}
              onClick={() => setOpen(open === hook.id ? '' : hook.id)}>
              {hook.name || hook.target}
            </button>
            <span style={mono}>{hook.target_type}:{hook.target}</span>
            <Tag c={hook.signed ? 'var(--green)' : undefined}>{hook.signed ? 'HMAC' : `token ${hook.token_hint || ''}`}</Tag>
            <Tag c={hook.enabled ? 'var(--green)' : 'var(--amber)'}>{hook.enabled ? 'on' : 'off'}</Tag>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
              <button className="tool-btn" onClick={() => toggle(hook)}>{hook.enabled ? 'switch off' : 'switch on'}</button>
              {confirming === hook.id ? (
                <>
                  <button className="tool-btn" onClick={() => remove(hook.id)}>delete for good</button>
                  <button className="tool-btn" onClick={() => setConfirming('')}>keep it</button>
                </>
              ) : (
                <button className="tool-btn" onClick={() => setConfirming(hook.id)}>delete…</button>
              )}
            </span>
          </Row>
          {confirming === hook.id && (
            <div role="status" style={{ ...mono, color: 'var(--amber)', padding: '2px 0 6px' }}>
              Deleting ends the sender's {hook.signed ? 'secret' : 'token'}; switching it off keeps it.
            </div>
          )}
          {open === hook.id && (
            <div style={{ ...mono, color: 'var(--ink-2)', padding: '2px 0 8px 8px' }}>
              <div>POST {triggerUrl(hook.id)}</div>
              <div>{hook.signed ? 'X-Signature-256 (HMAC-SHA256 of the raw body)' : `X-Webhook-Token (${hook.token_hint || '…'})`}</div>
              <div>{hook.calls ?? 0} calls · last {when(hook.last_called)} · created {when(hook.created_at)}</div>
              <div>Each delivery runs as an inbound, untrusted turn.</div>
            </div>
          )}
        </div>
      ))}
    </Card>
  );
}
