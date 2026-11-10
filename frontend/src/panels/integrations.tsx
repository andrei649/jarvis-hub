/* Integrations — one place for everything that needs the owner's setup.

   Before this panel, turning on a search backend or a model provider meant editing `.env`
   and restarting, the providers sat in a long settings select, the search backends in an
   environment variable and the Hermes skills catalog inside Skills Import. Here they are
   one list (`GET /api/admin/integrations`): name, kind, where it comes from (native or
   adopted from Hermes), status, and the facts the owner weighs before using it — the host,
   its country when Nerva knows it, the data policy, whether a price is known.

   - A key is typed here once (`PUT …/{id}/key`), stored encrypted by the hub, and in effect
     without a restart. It is never shown again: only "set" and at most its last four
     characters. A key set in `.env` wins and is edited there.
   - "Test" asks the hub to try that one provider (`POST …/{id}/test`) and says what happened
     in plain words.
   - "Use" chooses it (`POST …/{id}/use`). When the hub asks for acknowledgements (an
     unverified data policy, an unknown price) one consent card shows the facts and one
     "I understand, use it" sends the same acknowledgements the hub's selection guards
     require; the hub records the consent in the audit log and stays the one that decides.
   - The Hermes skills catalog is summarised and opens in Skills Import, where it lives. */
import React, { useMemo, useRef, useState } from 'react';
import { apiDelete, apiPost, apiPut } from '../api/client';
import { navigateHud } from '../hud-routing';
import { Card, Tag, inpS, mono, refusalReason, useApi } from '../panel-kit';
import { guardFlags, guardRefusal, type GuardFlags, type GuardRefusal } from '../selection-guard';

export const INTEGRATIONS_PATH = '/api/admin/integrations';

type KeyState = { names: string[]; name: string; primary?: string; set: boolean; source: 'env' | 'hub' | null; hint: string | null;
  editable: boolean; own: boolean; shared_with: string[]; primary_shared_with?: string[]; stored_copy?: boolean };
type Facts = { host: string; host_country: string | null; data_policy: string; data_policy_note: string;
  price_known: 'yes' | 'some' | 'no'; price_note: string; receives: string };
export type Integration = {
  id: string; kind: 'search' | 'model' | 'video'; name: string; display_name: string; origin: 'native' | 'hermes';
  status: 'not_set_up' | 'key_set' | 'shared' | 'active' | 'error'; key: KeyState; facts: Facts;
  selectable: boolean; selected: boolean; choice_editable: boolean; models: string[];
  last_test?: { ok: boolean; message: string } | null;
};

const STATUS: Record<string, [string, string]> = {
  not_set_up: ['not set up', 'var(--ink-2)'],
  key_set: ['key set', 'var(--amber)'],
  shared: ['shared key', 'var(--ink-2)'],
  active: ['active', 'var(--green)'],
  error: ['error', 'var(--red)'],
};
const POLICY: Record<string, string> = {
  'no-training': 'does not train on your data (vendor terms)',
  'trains-on-inputs': 'may train on your data',
  unknown: 'not verified',
  local: 'stays on this machine',
};

function policyText(f: Facts) { return POLICY[f.data_policy] || f.data_policy; }
function priceText(f: Facts) { return f.price_known === 'yes' ? 'known' : f.price_known === 'some' ? 'partly known' : 'unknown'; }

/** One card, the facts, one action: the acknowledgements the hub asked for, nothing more. */
export function ConsentCard({ item, refusal, onConfirm, onCancel }: {
  item: Integration; refusal: GuardRefusal; onConfirm: (flags: GuardFlags) => void; onCancel: () => void;
}) {
  const f = item.facts;
  const titleId = `consent-${item.id}`;
  return (
    <div role="alertdialog" aria-labelledby={titleId} style={{ marginTop: 8, padding: 8, border: '1px solid var(--amber)', borderRadius: 4, background: 'var(--surface)' }}>
      <div id={titleId} style={{ ...mono, fontSize: 10.5, color: 'var(--amber)', marginBottom: 4 }}>before you use {item.display_name}</div>
      <dl style={{ margin: 0, fontSize: 11, display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '2px 8px' }}>
        <dt>Who receives {f.receives}</dt><dd style={{ margin: 0 }}>{item.display_name}{f.host ? ` (${f.host})` : ''}</dd>
        <dt>Host country</dt><dd style={{ margin: 0 }}>{f.host_country || 'not recorded'}</dd>
        <dt>Data policy</dt><dd style={{ margin: 0 }}>{policyText(f)}</dd>
        <dt>Price</dt><dd style={{ margin: 0 }}>{priceText(f)} · {f.price_note}</dd>
      </dl>
      <ul style={{ margin: '6px 0 6px 16px', padding: 0, fontSize: 10.5, color: 'var(--ink-2)' }}>
        {refusal.guards.map((g, i) => <li key={i}>{g.message}</li>)}
      </ul>
      <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginBottom: 6 }}>Your acknowledgement is written to the audit log. Nerva asks again the next time you choose.</div>
      <div style={{ display: 'flex', gap: 6 }}>
        <button className="tool-btn" onClick={() => onConfirm(guardFlags(refusal))}>I understand, use it</button>
        <button className="tool-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function IntegrationDetail({ item, onChanged }: { item: Integration; onChanged: () => void }) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [testMsg, setTestMsg] = useState<string | null>(item.last_test ? item.last_test.message : null);
  const [model, setModel] = useState(item.models[0] || '');
  const [consent, setConsent] = useState<{ refusal: GuardRefusal; forKey: boolean } | null>(null);
  const [shared, setShared] = useState<string | null>(null);
  // The key waiting for the owner's answer (same key for the siblings? the consent card),
  // never rendered and dropped on cancel or once sent.
  const pending = useRef('');
  const inputId = `key-${item.id}`;
  const modelId = `model-${item.id}`;
  const f = item.facts;

  const run = (p: Promise<unknown>, done: string) => {
    setBusy(true); setMsg(null);
    return p.then(() => { setMsg(done); onChanged(); })
      .catch((err: any) => setMsg(`not done · ${refusalReason(err, String(err?.status || 'error'))}`))
      .finally(() => setBusy(false));
  };
  const drop = () => { pending.current = ''; setShared(null); setConsent(null); };
  const saveKey = (extra: { same_key?: true; acknowledge_training?: true } = {}) => {
    const v = value.trim() || pending.current;
    if (!v) return;
    pending.current = v;
    setValue('');   // the typed key leaves the input at once
    setBusy(true); setMsg(null); setShared(null); setConsent(null);
    apiPut(`/api/admin/integrations/${item.id}/key`, { value: v, ...extra }, { admin: true })
      .then((r: any) => {
        pending.current = '';
        setMsg(r?.applied === 'now' ? 'key saved · in effect now' : 'key saved');
        onChanged();
      })
      .catch((err: any) => {
        const refusal = guardRefusal(err);
        if (refusal) { setConsent({ refusal, forKey: true }); return; }
        if (err?.status === 409 && err?.body?.error === 'shared_key') { setShared(String(err.body.detail || '')); return; }
        pending.current = '';
        setMsg(`not saved · ${refusalReason(err, String(err?.status || 'error'))}`);
      })
      .finally(() => setBusy(false));
  };
  const sameKeyFlags = useRef<{ same_key?: true }>({});
  const removeKey = () => void run(apiDelete(`/api/admin/integrations/${item.id}/key`, { admin: true }), 'key removed');
  const test = () => {
    setBusy(true); setTestMsg('testing…');
    apiPost(`/api/admin/integrations/${item.id}/test`, {}, { admin: true })
      .then((r: any) => { setTestMsg(String(r?.test?.message || 'no answer')); onChanged(); })
      .catch((err: any) => setTestMsg(`the test could not run · ${refusalReason(err, String(err?.status || 'error'))}`))
      .finally(() => setBusy(false));
  };
  const use = (flags: GuardFlags = {}) => {
    setBusy(true); setMsg(null); setConsent(null);
    const body: any = { ...flags };
    if (item.kind === 'model') body.model = model;
    // The hub's "this needs your say-so" (409 selection_guard) is the expected first answer,
    // not a failed action: it opens the consent card instead of the failure banner.
    const asksConsent = (status: number, b: any) => status === 409 && !!b && b.error === 'selection_guard';
    apiPost(`/api/admin/integrations/${item.id}/use`, body, { admin: true, accept: asksConsent })
      .then((r: any) => {
        const refusal = guardRefusal({ status: r?.error === 'selection_guard' ? 409 : 200, body: r });
        if (refusal) { setConsent({ refusal, forKey: false }); return; }
        setMsg(item.kind === 'search' ? 'searches use it now' : item.kind === 'video'
          ? 'videos use it now · each video still asks your approval with its cost' : `in use now · ${model}`);
        onChanged();
      })
      .catch((err: any) => setMsg(`not chosen · ${refusalReason(err, String(err?.status || 'error'))}`))
      .finally(() => setBusy(false));
  };

  return (
    <div style={{ padding: '6px 0 8px 10px', borderLeft: '2px solid var(--panel-line)', marginBottom: 6 }}>
      <dl style={{ margin: '0 0 6px', fontSize: 11, display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '2px 8px' }}>
        <dt>Receives</dt><dd style={{ margin: 0 }}>{f.receives}</dd>
        <dt>Host</dt><dd style={{ margin: 0, ...mono }}>{f.host || 'not recorded'}</dd>
        <dt>Host country</dt><dd style={{ margin: 0 }}>{f.host_country || 'not recorded'}</dd>
        <dt>Data policy</dt><dd style={{ margin: 0 }}>{policyText(f)}{f.data_policy_note ? ` · ${f.data_policy_note}` : ''}</dd>
        <dt>Price</dt><dd style={{ margin: 0 }}>{priceText(f)} · {f.price_note}</dd>
      </dl>

      <div style={{ fontSize: 11, marginBottom: 4 }}>
        {item.key.set && !item.key.own
          ? <>Key <b>shared</b>: <span style={mono}>{item.key.name}</span> was set for {item.key.shared_with.join(', ') || 'another use'}, not for {item.display_name}.
              It is not tested here, and using {item.display_name} asks for its own consent.</>
          : item.key.set
            ? <>Key <b>set</b>{item.key.hint ? <span style={mono}> ({item.key.hint})</span> : null}
                {item.key.source === 'env' ? <> · in <span style={mono}>.env</span>, edit it there ({item.key.name})</> : ' · stored encrypted by Nerva'}</>
            : <>No key yet{item.key.names.length ? <> · <span style={mono}>{item.key.names.join(' / ')}</span></> : null}</>}
      </div>
      {item.key.stored_copy && (
        <div style={{ fontSize: 10.5, marginBottom: 4 }}>
          Nerva still holds an older copy of this key from this panel; the .env key is the one in use.
          <button className="tool-btn" style={{ marginLeft: 6 }} disabled={busy} onClick={removeKey}>remove the stored copy</button>
        </div>
      )}
      {item.key.editable && (
        <form onSubmit={(ev) => { ev.preventDefault(); saveKey(sameKeyFlags.current); }} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <label htmlFor={inputId} style={{ fontSize: 10.5 }}>{item.key.set && item.key.own ? 'Replace the key' : 'API key'} for {item.display_name}</label>
          <input id={inputId} type="password" autoComplete="off" spellCheck={false} value={value}
            onChange={(ev) => setValue(ev.target.value)} style={{ ...inpS, minWidth: 180 }} />
          <button className="tool-btn" type="submit" disabled={busy || !value.trim()}>save key</button>
          {item.key.set && item.key.own && item.key.source === 'hub' && (
            <button className="tool-btn" type="button" disabled={busy} onClick={removeKey}>remove key</button>
          )}
        </form>
      )}
      {shared && (
        <div role="alertdialog" aria-label="the same key for other providers" style={{ marginTop: 6, padding: 6, border: '1px solid var(--amber)', borderRadius: 4, fontSize: 10.5 }}>
          <div>{shared}</div>
          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
            <button className="tool-btn" onClick={() => { sameKeyFlags.current = { same_key: true }; saveKey({ same_key: true }); }}>yes, it is the same key</button>
            <button className="tool-btn" onClick={drop}>Cancel</button>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
        <button className="tool-btn" disabled={busy || !item.key.set} onClick={test} aria-label={`test ${item.display_name}`}>test</button>
        {item.kind === 'model' && item.selectable && (
          <>
            <label htmlFor={modelId} style={{ fontSize: 10.5 }}>Model</label>
            <input id={modelId} list={`${modelId}-list`} value={model} onChange={(ev) => setModel(ev.target.value)} style={{ ...inpS, minWidth: 160 }} />
            <datalist id={`${modelId}-list`}>{item.models.map((m) => <option key={m} value={m} />)}</datalist>
          </>
        )}
        {(item.selectable || item.kind === 'search') && (
          <button className="tool-btn" disabled={busy || !item.key.set || ((item.kind === 'search' || item.kind === 'video') && !item.choice_editable)
            || (item.kind === 'model' && !model.trim())} onClick={() => use()}>
            {item.kind === 'search' ? 'use for searches' : item.kind === 'video' ? 'use for videos' : 'use this provider'}
          </button>
        )}
        {!item.selectable && item.kind === 'model' && <span style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>used as soon as its key is set</span>}
        {item.kind === 'search' && !item.choice_editable && <span style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>the search choice is set in .env (JARVIS_WEB_BACKEND)</span>}
        {item.kind === 'video' && !item.choice_editable && <span style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>the video choice is set in .env (JARVIS_VIDEO_PROVIDER)</span>}
      </div>
      {testMsg && <div role="status" style={{ fontSize: 10.5, marginTop: 4 }}>{testMsg}</div>}
      {msg && <div role="status" style={{ fontSize: 10.5, marginTop: 4, color: msg.startsWith('not ') ? 'var(--amber)' : 'var(--ink-2)' }}>{msg}</div>}
      {consent && <ConsentCard item={item} refusal={consent.refusal} onCancel={drop}
        onConfirm={(flags) => (consent.forKey
          ? saveKey({ ...sameKeyFlags.current, ...(flags.acknowledge_training ? { acknowledge_training: true as const } : {}) })
          : use(flags))} />}
    </div>
  );
}

const KINDS = [['all', 'all'], ['search', 'search'], ['model', 'models'], ['video', 'video']] as const;

export function IntegrationsPanel() {
  const { d, e, reload } = useApi(INTEGRATIONS_PATH, true, true);
  const [kind, setKind] = useState<'all' | 'search' | 'model' | 'video'>('all');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const rows: Integration[] = Array.isArray((d as any)?.integrations) ? (d as any).integrations : [];
  const skills = (d as any)?.skills;
  const search = (d as any)?.search;
  const video = (d as any)?.video;
  const shown = useMemo(() => rows.filter((r) => (kind === 'all' || r.kind === kind)
    && (!q.trim() || `${r.display_name} ${r.name} ${r.facts.host}`.toLowerCase().includes(q.trim().toLowerCase()))), [rows, kind, q]);
  const counts = rows.reduce((acc: Record<string, number>, r) => { acc[r.status] = (acc[r.status] || 0) + 1; return acc; }, {});
  const auto = () => apiDelete('/api/admin/integrations/search-choice', { admin: true })
    .then(() => { setNote('searches choose automatically again'); reload(); })
    .catch((err: any) => setNote(`not changed · ${refusalReason(err, String(err?.status || 'error'))}`));
  const videoOff = () => apiDelete('/api/admin/integrations/video-choice', { admin: true })
    .then(() => { setNote('video generation is off'); reload(); })
    .catch((err: any) => setNote(`not changed · ${refusalReason(err, String(err?.status || 'error'))}`));

  return (
    <Card title="INTEGRATIONS" live={d ? 'live' : undefined} onReload={reload}
      sub={d ? `${counts.active || 0} active · ${counts.key_set || 0} key set · ${counts.error || 0} error` : null}>
      {e && <div role="status" style={{ color: 'var(--amber)', fontSize: 11 }}>not loaded · {String(e)}</div>}
      <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginBottom: 6 }}>
        Keys are stored encrypted by Nerva and take effect without a restart. A key in <span style={mono}>.env</span> wins. Keys are never shown again.
      </div>
      {search && (
        <div style={{ fontSize: 11, marginBottom: 6 }}>
          Searches use <b>{search.answers || 'nothing configured'}</b> · choice <span style={mono}>{search.backend}</span>
          {search.choice_source === 'env' ? ' (set in .env)' : null}
          {search.choice_source === 'hub' && <button className="tool-btn" style={{ marginLeft: 6 }} onClick={() => void auto()}>choose automatically</button>}
          {note && <span role="status" style={{ marginLeft: 6, color: 'var(--ink-2)' }}>{note}</span>}
        </div>
      )}
      {video && (
        <div style={{ fontSize: 11, marginBottom: 6 }}>
          Videos use <b>{video.provider || 'nothing (off)'}</b>
          {video.choice_source === 'env' ? ' (set in .env)' : null}
          {video.choice_source === 'hub' && <button className="tool-btn" style={{ marginLeft: 6 }} onClick={() => void videoOff()}>turn video off</button>}
        </div>
      )}
      {skills && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--panel-line)', fontSize: 11 }}>
          <span>{skills.display_name}</span><Tag>skills</Tag><Tag>from Hermes</Tag>
          {skills.available
            ? <span style={{ color: 'var(--ink-2)' }}>{skills.installable} installable{skills.commit ? ` · @${skills.commit}` : ''} · no key needed</span>
            : <Tag c="var(--red)">unavailable</Tag>}
          <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={() => navigateHud('/v2/console/skills-import')}>open the catalog</button>
        </div>
      )}
      <div role="group" aria-label="filter integrations" style={{ display: 'flex', gap: 6, alignItems: 'center', margin: '6px 0' }}>
        {KINDS.map(([k, label]) => (
          <button key={k} className="tool-btn" aria-pressed={kind === k} onClick={() => setKind(k as any)}>{label}</button>
        ))}
        <label htmlFor="integrations-filter" style={{ fontSize: 10.5, marginLeft: 6 }}>Find</label>
        <input id="integrations-filter" value={q} onChange={(ev) => setQ(ev.target.value)} style={{ ...inpS, minWidth: 120 }} />
      </div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }} aria-label="integrations">
        {shown.map((r) => {
          const [label, color] = STATUS[r.status] || [r.status, 'var(--ink-2)'];
          const expanded = open === r.id;
          return (
            <li key={r.id} style={{ borderBottom: '1px solid var(--panel-line)' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 0', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11.5 }}>{r.display_name}</span>
                <Tag>{r.kind}</Tag>
                <Tag>{r.origin === 'hermes' ? 'from Hermes' : 'native'}</Tag>
                <Tag c={color}>{label}</Tag>
                {r.selected && r.status !== 'not_set_up' && <Tag c="var(--green)">in use</Tag>}
                <span style={{ ...mono, fontSize: 10, color: 'var(--ink-2)' }}>{r.facts.host}{r.facts.host_country ? ` · ${r.facts.host_country}` : ''}</span>
                <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>data {policyText(r.facts)} · price {priceText(r.facts)}</span>
                <button className="tool-btn" style={{ marginLeft: 'auto' }} aria-expanded={expanded}
                  aria-label={`${expanded ? 'close' : r.status === 'not_set_up' ? 'set up' : 'manage'} ${r.display_name}`}
                  onClick={() => setOpen(expanded ? null : r.id)}>{expanded ? 'close' : r.status === 'not_set_up' ? 'set up' : 'manage'}</button>
              </div>
              {expanded && <IntegrationDetail item={r} onChanged={reload} />}
            </li>
          );
        })}
      </ul>
      {d && !shown.length && <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>nothing matches</div>}
    </Card>
  );
}
