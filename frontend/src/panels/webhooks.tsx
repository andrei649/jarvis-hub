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
   leaves no ghost row.

   H153 — the rest of a Hermes subscription: the receiver switch (the setting
   webhooks.receiver_enabled: off, every delivery is refused until it is switched
   back on), and each hook's event list and prompt template, set on create and
   changed in its detail pane. Neither needs a restart.

   H153 review — where a delivery goes (Deliver to: the log, or one of the owner's own
   channels; "deliver only" skips the agent), a description, the last delivery, and a
   receiver row that never shows a stale or unread state as on: a failed read says why,
   and ↻ re-reads it with the list.

   H153 third round — the channels offered are the ones something receives (web is not
   one), deliver only needs one of them, a receiver row the store does not hold yet is
   the hub's default (on) and can be switched off, and a hook that vanished hands focus
   to the create form.

   H039 — the rest of the Hermes row: "test" posts a correctly signed sample through the
   hook's own receive path, dry (nothing runs, nothing is pushed, no call is counted), and
   the detail pane shows what a real delivery like it would do; and the payload filter (a
   JSON list of {path, op, value} rules, all of which must hold), edited in the detail
   pane, with what it turned away. The filter is the safe stand-in for Hermes' --script
   transform, which ran owner code over attacker-controlled text and was not copied. */
import React, { useEffect, useRef, useState } from 'react';
import { appUrl } from '../base-path';
import { apiDelete, apiPatch, apiPost, apiPut } from '../api/client';
import type { components } from '../api/schema.gen';
import { ConfirmAction, RISK_TIER } from '../confirm';
import { Card, Row, State, Tag, arr, asLive, inpS, mono, refusalReason, taS, useApi } from '../panel-kit';

const HOOKS_PATH = '/api/webhooks';
const RECEIVER_PATH = '/api/admin/settings/webhooks';
/** Where a delivery can go: the log, or the owner's own channels that something
    receives. The web channel is not one: nothing in the hub receives a push there. */
export const DESTINATIONS = ['log', 'telegram', 'voice', 'ntfy'];
export const DELIVER_ONLY_NEEDS_A_CHANNEL = 'deliver only needs a channel: with log the sender’s text would go nowhere';
export const FILTER_NOT_JSON = 'the filter is a JSON list of rules, e.g. [{"path": "ref", "op": "eq", "value": "refs/heads/main"}]';
/** What a test delivery found (H039), as the hub's schema spells it. */
export type TestReport = components['schemas']['WebhookTestReport'];
const PUSH_NOTE = 'A push is the text as written (nothing is formatted; a link shows its address), is not sent '
  + 'in quiet hours, and a hook makes at most 30 push attempts an hour (one the channel refused counts).';
const RECEIVER = ':receiver';   // its pending key; hook ids are URL-safe and never start with ':'
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

/** "push, issues" → ["push", "issues"]: the hub strips, deduplicates and checks them. */
export function parseEvents(text: string): string[] {
  return text.split(',').map((name) => name.trim()).filter(Boolean);
}

export type SubscriptionChange = {
  events: string[]; prompt: string; deliver: string; deliver_only: boolean; description: string; filter: unknown[];
};

/** The filter editor's text for a hook: one rule per line, or nothing for no rule. */
function filterText(hook: any): string {
  const rules = arr(hook, 'filter');
  return rules.length ? JSON.stringify(rules, null, 1) : '';
}

/** The editor's text as the rules it names: a JSON list, blank for none, or null when it
    is neither (the hub validates each rule; this only refuses what is not a list). */
export function parseFilter(text: string): unknown[] | null {
  if (!text.trim()) return [];
  try {
    const rules = JSON.parse(text);
    return Array.isArray(rules) ? rules : null;
  } catch {
    return null;
  }
}

/** A hook's event list, prompt template, destination, description and payload filter,
    changed in place (H153, H039). An unreadable event list is not pre-filled: saving it
    empty says, on the button, that it now runs every event. A filter that is not a JSON
    list is refused here, before anything is posted. */
function Subscription({ hook, label, held, onSave, onProblem }: {
  hook: any; label: string; held: boolean; onSave: (change: SubscriptionChange) => void; onProblem: (text: string) => void;
}) {
  const unreadable = !!hook.events_unreadable;
  const [events, setEvents] = useState(unreadable ? '' : arr(hook, 'events').join(', '));
  const [prompt, setPrompt] = useState(String(hook.prompt || ''));
  const [deliver, setDeliver] = useState(DESTINATIONS.includes(hook.deliver) ? hook.deliver : 'log');
  const [deliverOnly, setDeliverOnly] = useState(hook.deliver_only === true);
  const [description, setDescription] = useState(String(hook.description || ''));
  const [filter, setFilter] = useState(hook.filter_unreadable ? '' : filterText(hook));
  const everyEvent = unreadable && parseEvents(events).length === 0;
  const save = () => {
    const rules = parseFilter(filter);
    if (rules === null) {
      onProblem(FILTER_NOT_JSON);
      return;
    }
    onSave({ events: parseEvents(events), prompt, deliver, deliver_only: deliverOnly, description, filter: rules });
  };
  return (
    <div style={{ display: 'grid', gap: 4, margin: '4px 0' }}>
      <input aria-label={`events for ${label}`} placeholder="events, comma-separated (empty: every event)" value={events}
        onChange={(e) => setEvents(e.target.value)} style={inpS} />
      <textarea aria-label={`prompt template for ${label}`} placeholder="prompt template, e.g. {event} on {repository.full_name} (empty: the payload's text)"
        value={prompt} maxLength={2000} onChange={(e) => setPrompt(e.target.value)} style={{ ...taS, minHeight: 40 }} />
      <textarea aria-label={`filter for ${label}`} value={filter} onChange={(e) => setFilter(e.target.value)}
        placeholder='filter: JSON rules every delivery must satisfy, e.g. [{"path": "ref", "op": "eq", "value": "refs/heads/main"}] (ops: eq ne contains in exists missing matches; empty: no rule)'
        style={{ ...taS, minHeight: 40 }} />
      <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <select aria-label={`deliver ${label} to`} value={deliver} onChange={(e) => setDeliver(e.target.value)} style={inpS}>
          {DESTINATIONS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <label style={mono}>
          <input type="checkbox" checked={deliverOnly} onChange={(e) => setDeliverOnly(e.target.checked)}
            aria-label={`deliver only for ${label} (skip the agent)`} /> deliver only
        </label>
        <input aria-label={`description of ${label}`} placeholder="description" value={description} maxLength={500}
          onChange={(e) => setDescription(e.target.value)} style={{ ...inpS, flex: 1 }} />
      </span>
      <span><button className="tool-btn" disabled={held} onClick={save}
        aria-label={everyEvent ? `save ${label}: every event` : `save ${label}`}>{everyEvent ? 'save: every event' : 'save'}</button></span>
    </div>
  );
}

function lastDelivery(hook: any): string {
  const d = hook.last_delivery;
  if (!d || typeof d !== 'object') return 'no delivery yet';
  const outcome = d.ok ? `delivered to ${d.channel}` : `not delivered to ${d.channel}${d.reason ? `: ${d.reason}` : ''}`;
  return `last delivery ${when(d.at)} · ${outcome}`;
}

function lastTest(hook: any): string {
  const t = hook.last_test;
  if (!t || typeof t !== 'object') return '';
  return `last test ${when(t.at)} · ${t.outcome}${t.reason ? `: ${t.reason}` : ''}`;
}

/** A test report in two lines: how the sample authenticated and what it named, then
    what a real delivery like it would do (H039). */
export function testSummary(t: TestReport): string[] {
  const head = `${t.auth} ${t.authenticated ? 'verified' : 'NOT verified'} · event ${t.event} · receiver ${t.receiver}`
    + ` · hook ${t.enabled ? 'on' : 'off'}`;
  let would: string;
  if (t.outcome === 'run') would = `would run ${t.target}, reply to ${t.deliver}`;
  else if (t.outcome === 'deliver_only') would = `would deliver only to ${t.deliver}: no turn`;
  else if (t.outcome === 'skipped' || t.outcome === 'filtered') would = `would be ${t.outcome}: ${t.reason}`;
  else would = `would be refused (${t.status}): ${t.reason}`;
  const lines = [head, would];
  if (t.text) lines.push(`text: ${t.text}`);
  return lines;
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
  const receiver = useApi(RECEIVER_PATH, true, true);
  // A failed re-read drops what was read before: a stale "on" is not shown as the state.
  const receiverRow = receiver.e ? undefined
    : arr(receiver.d, 'webhooks').find((row: any) => row && row.key === 'receiver_enabled');
  // The store holds no row for it: the hub's own 404 names the category. The hub reads
  // the declared default, on, and a write creates the row, so switching it off is
  // offered. Any other 404 (a proxy's, a route that is not there) is a failed read.
  const receiverMissing = !!receiver.e && receiver.status === 404
    && (receiver.refusal as any)?.error === 'unknown category: webhooks';
  // The hub treats only a literal true as on (it fails closed), and so does this row.
  const receiverOn: boolean | null = receiverRow ? receiverRow.value === true
    : receiverMissing ? true : null;   // null: not read
  const receiverOdd = !!receiverRow && typeof receiverRow.value !== 'boolean';
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [targetType, setTargetType] = useState('agent');
  const [signed, setSigned] = useState(false);
  const [events, setEvents] = useState('');
  const [prompt, setPrompt] = useState('');
  const [deliver, setDeliver] = useState('log');
  const [deliverOnly, setDeliverOnly] = useState(false);
  const [description, setDescription] = useState('');
  const [created, setCreated] = useState<any>(null);
  const [open, setOpen] = useState('');
  const [confirming, setConfirming] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  // H039 — the last test report per hook, kept until the next test of that hook.
  const [tests, setTests] = useState<Record<string, TestReport>>({});
  // A click that unmounts the focused button hands focus to the control that
  // replaced it (M3): "delete…" → "delete for good" (ConfirmAction's own), "keep it"
  // → "delete…", "I have saved it" → the create form.
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
    if (deliverOnly && deliver === 'log') {
      setNote(DELIVER_ONLY_NEEDS_A_CHANNEL);
      return;
    }
    setBusy(true);
    apiPost(HOOKS_PATH, { name: name.trim(), target: target.trim(), target_type: targetType, signed,
      events: parseEvents(events), prompt, deliver, deliver_only: deliverOnly, description: description.trim() },
      { admin: true })
      .then((rec: any) => {
        setCreated(rec);
        setName('');
        setTarget('');
        setEvents('');
        setPrompt('');
        setDeliver('log');
        setDeliverOnly(false);
        setDescription('');
        setNote('');
        list.reload();
      })
      .catch(refused)
      .finally(() => setBusy(false));
  };
  // A hook that is gone (deleted here or elsewhere) takes its row, and the focused button
  // with it, on the reload: focus goes to the create form, which stays.
  const toggle = (hook: any) => {
    hold(hook.id, true);
    let gone = false;
    apiPatch(`${HOOKS_PATH}/${encodeURIComponent(hook.id)}`, { enabled: !hook.enabled }, { admin: true })
      .then(() => setNote(''))
      .catch((err: any) => {
        if (err && err.status === 404) {
          gone = true;
          setNote(`${hookName(hook)} no longer exists`);
        } else {
          refused(err);
        }
      })
      .finally(() => { hold(hook.id, false); list.reload(); if (gone) setFocusKey('create'); });
  };
  // H168 — the confirmation is ConfirmAction's (tier 1, two steps), opened and closed by
  // this page: it stays open when the hub refuses, so the owner can fix the credential and
  // try again, and the returned promise holds its buttons while the DELETE is in flight.
  const remove = (hook: any): Promise<void> => {
    hold(hook.id, true);
    let gone = false;
    return apiDelete(`${HOOKS_PATH}/${encodeURIComponent(hook.id)}`, { admin: true })
      .then(() => { gone = true; setConfirming(''); setNote(''); })
      .catch((err: any) => {
        if (err && err.status === 404) {
          gone = true;
          setConfirming('');
          setNote(`${hookName(hook)} was already deleted`);
        } else {
          refused(err);
        }
      })
      .finally(() => { hold(hook.id, false); list.reload(); if (gone) setFocusKey('create'); });
  };
  const save = (hook: any, change: SubscriptionChange) => {
    if (change.deliver_only && change.deliver === 'log') {
      setNote(DELIVER_ONLY_NEEDS_A_CHANNEL);
      return;
    }
    hold(hook.id, true);
    let gone = false;
    apiPatch(`${HOOKS_PATH}/${encodeURIComponent(hook.id)}`, change, { admin: true })
      .then(() => setNote(`${hookName(hook)} saved`))
      .catch((err: any) => {
        if (err && err.status === 404) {
          gone = true;
          setNote(`${hookName(hook)} no longer exists`);
        } else {
          refused(err);
        }
      })
      // The editor re-mounts with what the hub stored, taking the focused button with
      // it: focus goes to the hook's own row button, which stays (or to the create form
      // when the hook is gone).
      .finally(() => { hold(hook.id, false); list.reload(); setFocusKey(gone ? 'create' : `open:${hook.id}`); });
  };
  // H039 — a signed sample through the hook's receive path, dry: the hub runs nothing and
  // pushes nothing, so no confirmation is asked. The report lands in the detail pane,
  // which opens to show it; the list reloads for the hook's last_test note.
  const runTest = (hook: any) => {
    if (pending[hook.id]) return;
    hold(hook.id, true);
    let gone = false;
    apiPost(`/api/webhooks/${encodeURIComponent(hook.id)}/test`, {}, { admin: true })
      .then((reply: any) => {
        const report = reply && reply.test;
        if (!report || typeof report !== 'object') {
          setNote('the hub answered without a test report');
          return;
        }
        setTests((t) => ({ ...t, [hook.id]: report as TestReport }));
        setOpen(hook.id);
        setNote('');
      })
      .catch((err: any) => {
        if (err && err.status === 404) {
          gone = true;
          setNote(`${hookName(hook)} no longer exists`);
        } else {
          refused(err);
        }
      })
      .finally(() => { hold(hook.id, false); list.reload(); if (gone) setFocusKey('create'); });
  };
  const switchReceiver = () => {
    if (receiverOn === null) return;
    hold(RECEIVER, true);
    apiPut(RECEIVER_PATH, { values: { receiver_enabled: !receiverOn } }, { admin: true })
      .then(() => setNote(''))
      .catch(refused)
      .finally(() => { hold(RECEIVER, false); receiver.reload(); });
  };
  const ask = (id: string) => setConfirming(id);   // ConfirmAction takes focus as it opens
  const keep = (id: string) => { setConfirming(''); setFocusKey(`ask:${id}`); };
  const dismiss = () => { setCreated(null); setFocusKey('create'); };

  return (
    <Card title="WEBHOOKS" live={asLive(list.d)} sub={`${hooks.length} inbound`}
      onReload={() => { list.reload(); receiver.reload(); }}>
      <Row>
        <span style={mono}>receiver</span>
        <Tag c={receiverOn === false ? 'var(--amber)' : receiverOn ? 'var(--green)' : undefined}>
          {receiverOn === null ? (receiver.e ? `not read · ${receiver.e}` : 'not read')
            : receiverMissing ? 'on · not stored (the default)' : receiverOn ? 'on' : 'off'}
        </Tag>
        <span style={{ ...mono, color: 'var(--ink-2)' }}>takes effect at once, no restart</span>
        <span style={{ marginLeft: 'auto' }}>
          <button className="tool-btn" disabled={receiverOn === null || !!pending[RECEIVER]} onClick={switchReceiver}>
            {receiverOn === null ? 'receiver state not read' : receiverOn ? 'switch the receiver off' : 'switch the receiver on'}
          </button>
        </span>
      </Row>
      {receiverOn === false && (
        <div role="status" data-testid="receiver-off" style={{ ...mono, color: 'var(--amber)', padding: '4px 0 6px' }}>
          {receiverOdd ? 'The stored receiver setting is not true or false, so the hub treats it as off. ' : ''}
          The receiver is off: every delivery is refused until it is switched back on. Hooks keep their credentials.
          A sender that retries on an error (GitHub, Stripe) may deliver again once it is back on.
        </div>
      )}
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
      </div>
      <div style={{ display: 'grid', gap: 4, marginBottom: 8 }}>
        <input aria-label="description" placeholder="description" value={description} maxLength={500}
          onChange={(e) => setDescription(e.target.value)} style={inpS} />
        <input aria-label="events" placeholder="events, comma-separated (empty: every event)" value={events} maxLength={2400}
          onChange={(e) => setEvents(e.target.value)} style={inpS} />
        <textarea aria-label="prompt template" placeholder="prompt template, e.g. {event} on {repository.full_name} (empty: the payload's text)"
          value={prompt} maxLength={2000} onChange={(e) => setPrompt(e.target.value)} style={{ ...taS, minHeight: 40 }} />
        <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={mono}>deliver to{' '}
            <select aria-label="deliver to" value={deliver} onChange={(e) => setDeliver(e.target.value)} style={inpS}>
              {DESTINATIONS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label style={mono}>
            <input type="checkbox" checked={deliverOnly} onChange={(e) => setDeliverOnly(e.target.checked)}
              aria-label="deliver only (skip the agent)" /> deliver only
          </label>
          {/* Last in the tab order: every field above is filled before create is reached. */}
          <button className="tool-btn" disabled={busy || !!created} onClick={create}
            title={created ? 'save the new hook’s credentials first' : undefined}>create</button>
        </span>
      </div>
      {note && <div role="status" style={{ ...mono, color: 'var(--amber)', marginBottom: 6 }}>{note}</div>}
      <State e={list.e} loading={list.loading && !list.d} n={hooks.length} />
      {hooks.map((hook: any) => {
        const label = hookName(hook);
        const held = !!pending[hook.id];
        return (
          <div key={hook.id}>
            <Row>
              <button ref={focusRef(`open:${hook.id}`)} className="tool-btn" aria-expanded={open === hook.id}
                style={{ ...mono, textAlign: 'left' }} onClick={() => setOpen(open === hook.id ? '' : hook.id)}>
                {hook.name || hook.target}
              </button>
              <span style={mono}>{hook.target_type}:{hook.target}</span>
              <Tag c={hook.signed ? 'var(--green)' : undefined}>{hook.signed ? 'HMAC' : `token ${hook.token_hint || ''}`}</Tag>
              <Tag c={hook.enabled ? 'var(--green)' : 'var(--amber)'}>{hook.enabled ? 'on' : 'off'}</Tag>
              {hook.deliver && hook.deliver !== 'log' && <Tag>{`→ ${hook.deliver}`}</Tag>}
              {hook.deliver_only === true && <Tag>deliver only</Tag>}
              {hook.events_unreadable
                ? <Tag c="var(--amber)">event list unreadable</Tag>
                : arr(hook, 'events').length > 0 && <Tag>{`${arr(hook, 'events').length} event${arr(hook, 'events').length === 1 ? '' : 's'}`}</Tag>}
              {hook.filter_unreadable
                ? <Tag c="var(--amber)">filter unreadable</Tag>
                : arr(hook, 'filter').length > 0 && <Tag>{`${arr(hook, 'filter').length} rule${arr(hook, 'filter').length === 1 ? '' : 's'}`}</Tag>}
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                <button className="tool-btn" disabled={held} onClick={() => runTest(hook)} aria-label={`test ${label}`}
                  title="post a signed sample through this hook's receive path, dry: nothing runs, nothing is pushed">test</button>
                <button className="tool-btn" disabled={held} onClick={() => toggle(hook)}
                  aria-label={`${hook.enabled ? 'switch off' : 'switch on'} ${label}`}>
                  {hook.enabled ? 'switch off' : 'switch on'}
                </button>
                {confirming === hook.id ? (
                  <ConfirmAction tier={RISK_TIER.REVERSIBLE} armed onCancel={() => keep(hook.id)} onConfirm={() => remove(hook)}
                    label={`delete ${label}`} armedLabel="delete for good" confirmAriaLabel={`delete ${label} for good`}
                    cancelLabel="keep it" cancelAriaLabel={`keep ${label}`} busy={held} />
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
                {hook.description ? <div>{hook.description}</div> : null}
                <div>{hook.calls ?? 0} calls · last {when(hook.last_called)} · created {when(hook.created_at)}</div>
                <div>
                  {hook.skipped ?? 0} skipped{hook.last_skipped_event ? ` · last skipped: ${hook.last_skipped_event}` : ''}
                  {' · '}{hook.events_unreadable ? 'event list unreadable: every delivery is skipped'
                    : arr(hook, 'events').length ? `events: ${arr(hook, 'events').join(', ')}` : 'every event'}
                  {' · '}{hook.prompt ? 'a prompt template' : "the payload's text"}
                </div>
                <div>
                  {hook.filtered ?? 0} filtered{hook.last_filtered_rule ? ` · last filtered: ${hook.last_filtered_rule}` : ''}
                  {' · '}{hook.filter_unreadable ? 'filter unreadable: every delivery is filtered'
                    : arr(hook, 'filter').length ? `${arr(hook, 'filter').length} filter rule${arr(hook, 'filter').length === 1 ? '' : 's'}, all must hold` : 'no filter rule'}
                </div>
                <div>
                  {hook.deliver_only === true ? `deliver only: no turn, the text goes to ${hook.deliver || 'log'}`
                    : `the reply goes to ${hook.deliver || 'log'}`}
                  {' · '}{lastDelivery(hook)}
                </div>
                {lastTest(hook) ? <div>{lastTest(hook)}</div> : null}
                {tests[hook.id] && (
                  <div role="status" data-testid="webhook-test-outcome" aria-label={`test outcome for ${label}`}
                    style={{ border: '1px solid var(--line, #444)', borderRadius: 4, padding: '4px 6px', margin: '4px 0' }}>
                    {testSummary(tests[hook.id]).map((line, i) => <div key={i}>{line}</div>)}
                  </div>
                )}
                <div>{hook.deliver_only === true ? 'The sender’s text reaches you labelled with this hook.'
                  : 'Each delivery runs as an inbound, untrusted turn.'}</div>
                {hook.deliver && hook.deliver !== 'log' ? <div>{PUSH_NOTE}</div> : null}
                <Subscription key={`${hook.id}:${hook.events_unreadable ? '!' : arr(hook, 'events').join(',')}:${hook.prompt || ''}:${hook.deliver}:${hook.deliver_only}:${hook.description || ''}:${hook.filter_unreadable ? '!' : filterText(hook)}`}
                  hook={hook} label={label} held={held} onSave={(change) => save(hook, change)} onProblem={setNote} />
              </div>
            )}
          </div>
        );
      })}
    </Card>
  );
}
