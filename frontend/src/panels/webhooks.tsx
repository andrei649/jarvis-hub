/* H200 / H153 — inbound webhooks, managed from the cockpit.

   The hub's admin-only hook routes (list, create, switch, delete) were reachable
   only by a hand-built admin request; Interop mode showed a read-only list. This
   panel lists every hook (target, HMAC or token, on or off, calls, last call),
   and creates, switches and deletes them with the admin credential.

   A new hook's token or signing secret is shown exactly once. It lives only in this
   component's state, is dropped on dismiss or unmount, and the list never carries
   it (the hub masks it to a four-character hint). No second hook can be created
   while it is on screen, so a secret is never replaced before it was saved. Deleting
   asks first, because the sender's credential dies with the hook; switching it off
   keeps it. A row's buttons are held while its call is pending, and every switch or
   delete reloads the list whatever the hub answered, so a hook removed elsewhere
   leaves no ghost row. */
import React, { useEffect, useRef, useState } from 'react';
import { appUrl } from '../base-path';
import { apiDelete, apiPatch, apiPost } from '../api/client';
import { Card, Row, State, Tag, arr, asLive, inpS, mono, refusalReason, useApi } from '../panel-kit';

const HOOKS_PATH = '/api/webhooks';
const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);
const SR_ONLY: React.CSSProperties = {
  position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap',
};

/** The absolute URL an external sender posts to. */
export function triggerUrl(id: string): string {
  let path = '';
  try {
    path = appUrl(`${HOOKS_PATH}/${encodeURIComponent(id)}`);
    return new URL(path, window.location.origin).href;
  } catch {
    return path;  // no origin to resolve against, or an id no URL can carry
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

const hookName = (hook: any): string => String(hook.name || hook.target || hook.id || 'webhook');

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
  return (
    <>
      <button className="tool-btn" onClick={copy} aria-label={`copy the ${label}`}>{copied ? 'copied' : 'copy'}</button>
      <span aria-live="polite" style={SR_ONLY}>{copied ? `the ${label} is copied` : ''}</span>
    </>
  );
}

/** Right after creation, and never again: nothing else ever holds the secret. Only
    the warning sentence is an alert; the secret is not read aloud. */
function Reveal({ hook, onDismiss }: { hook: any; onDismiss: () => void }) {
  const kind = hook.signed ? 'signing secret' : 'token';
  const secret = String((hook.signed ? hook.signing_secret : hook.token) || '');
  const url = triggerUrl(hook.id);
  let loopback = false;
  try {
    loopback = LOOPBACK.has(new URL(url).hostname);
  } catch {
    /* not an absolute URL: say nothing about reachability */
  }
  return (
    <div role="group" aria-label="the new webhook's credentials" data-testid="webhook-reveal"
      style={{ border: '1px solid var(--amber)', borderRadius: 4, padding: 8, marginBottom: 8 }}>
      <div role="alert" style={{ ...mono, color: 'var(--amber)', marginBottom: 4 }}>
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
      {loopback && (
        <div style={{ ...mono, color: 'var(--ink-2)', margin: '0 0 6px' }}>
          This URL is this machine's own address. A sender elsewhere needs one it can reach: the hub's
          network name, or a tunnel to it.
        </div>
      )}
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
  const [pending, setPending] = useState<Record<string, boolean>>({});
  // A click that unmounts the focused button hands focus to the control that
  // replaced it (M3): "delete…" → "delete for good", "keep it" → "delete…",
  // "I have saved it" → the create form.
  const focusable = useRef<Record<string, HTMLElement | null>>({});
  const [focusKey, setFocusKey] = useState('');
  useEffect(() => {
    if (!focusKey) return;
    const el = focusable.current[focusKey];
    if (el) el.focus();
    setFocusKey('');
  }, [focusKey]);
  const focusRef = (key: string) => (el: HTMLElement | null) => { focusable.current[key] = el; };

  const hold = (id: string, on: boolean) => setPending((p) => {
    const next = { ...p };
    if (on) next[id] = true; else delete next[id];
    return next;
  });
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
  const toggle = (hook: any) => {
    hold(hook.id, true);
    apiPatch(`${HOOKS_PATH}/${encodeURIComponent(hook.id)}`, { enabled: !hook.enabled }, { admin: true })
      .then(() => setNote(''))
      .catch((err: any) => (err && err.status === 404 ? setNote(`${hookName(hook)} no longer exists`) : refused(err)))
      .finally(() => { hold(hook.id, false); list.reload(); });
  };
  const remove = (hook: any) => {
    hold(hook.id, true);
    apiDelete(`${HOOKS_PATH}/${encodeURIComponent(hook.id)}`, { admin: true })
      .then(() => { setConfirming(''); setNote(''); })
      .catch((err: any) => {
        if (err && err.status === 404) {
          setConfirming('');
          setNote(`${hookName(hook)} was already deleted`);
        } else {
          refused(err);
        }
      })
      .finally(() => { hold(hook.id, false); list.reload(); });
  };
  const ask = (id: string) => { setConfirming(id); setFocusKey(`confirm:${id}`); };
  const keep = (id: string) => { setConfirming(''); setFocusKey(`ask:${id}`); };
  const dismiss = () => { setCreated(null); setFocusKey('create'); };

  return (
    <Card title="WEBHOOKS" live={asLive(list.d)} sub={`${hooks.length} inbound`} onReload={list.reload}>
      {created && <Reveal hook={created} onDismiss={dismiss} />}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 8 }}>
        <input ref={focusRef('create')} aria-label="webhook name" placeholder="name" value={name} maxLength={128}
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
        <button className="tool-btn" disabled={busy || !!created} onClick={create}
          title={created ? 'save the new hook’s credentials first' : undefined}>create</button>
      </div>
      {note && <div role="status" style={{ ...mono, color: 'var(--amber)', marginBottom: 6 }}>{note}</div>}
      <State e={list.e} loading={list.loading && !list.d} n={hooks.length} />
      {hooks.map((hook: any) => {
        const label = hookName(hook);
        const held = !!pending[hook.id];
        return (
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
                <button className="tool-btn" disabled={held} onClick={() => toggle(hook)}
                  aria-label={`${hook.enabled ? 'switch off' : 'switch on'} ${label}`}>
                  {hook.enabled ? 'switch off' : 'switch on'}
                </button>
                {confirming === hook.id ? (
                  <>
                    <button ref={focusRef(`confirm:${hook.id}`)} className="tool-btn" disabled={held}
                      onClick={() => remove(hook)} aria-label={`delete ${label} for good`}>delete for good</button>
                    <button className="tool-btn" disabled={held} onClick={() => keep(hook.id)}
                      aria-label={`keep ${label}`}>keep it</button>
                  </>
                ) : (
                  <button ref={focusRef(`ask:${hook.id}`)} className="tool-btn" disabled={held}
                    onClick={() => ask(hook.id)} aria-label={`delete ${label}…`}>delete…</button>
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
        );
      })}
    </Card>
  );
}
