/* Channels — each messaging channel's settings, edited in the HUD (G21 · H151/H160).

   The hub owns the rules (agents/core/channel_config.py). A secret (a bot token, a mail
   password, the ntfy topic) is typed once, stored encrypted by the hub and never shown
   again: the panel only says whether it is set and where. Plain settings (hosts, ports,
   allowlists, switches) are stored in the hub's settings. A value set in `.env` wins and is
   changed there; a value the administrator pinned cannot be changed here. Channels start
   with the hub, so most changes need a restart: the panel says when one is waiting. */
import React, { useState } from 'react';
import { apiDelete, apiPut } from '../api/client';
import { Card, Tag, inpS, mono, refusalReason, useApi } from '../panel-kit';

export const CHANNELS_CONFIG_PATH = '/api/admin/channels/config';

type FieldState = { name: string; label: string; kind: string; secret: boolean; applies: 'now' | 'restart';
  set: boolean; source: 'env' | 'hub' | 'managed' | null; editable: boolean; value?: string | null };
type ChannelRow = { id: string; label: string; note: string; running: boolean; fields: FieldState[];
  restart_required: boolean; changed: string[] };

const SOURCE: Record<string, string> = { env: 'set in .env', hub: 'set here', managed: '🔒 managed by your administrator' };

const why = (err: any) => {
  const body = err?.body;
  if (body && typeof body === 'object') {
    if (body.error === 'invalid_value') return `${body.field || 'a value'} is not valid`;
    if (typeof body.detail === 'string') return body.detail;
  }
  return refusalReason(err, String(err?.status || 'error'));
};

function FieldEditor({ channel, field, onChanged }: { channel: string; field: FieldState; onChanged: (msg: string) => void }) {
  const [value, setValue] = useState(field.secret ? '' : (field.value ?? ''));
  const [busy, setBusy] = useState(false);
  const id = `ch-${channel}-${field.name}`;
  const done = (p: Promise<unknown>, msg: string) => {
    setBusy(true);
    p.then(() => { if (field.secret) setValue(''); onChanged(msg); })
      .catch((e: any) => onChanged(`${field.name} not changed · ${why(e)}`))
      .finally(() => setBusy(false));
  };
  const save = () => {
    if (field.secret) {
      const v = value.trim();
      if (!v) return;
      setValue('');   // the typed secret leaves the input at once
      done(apiPut(`/api/admin/channels/${channel}/secret`, { name: field.name, value: v }, { admin: true }), `${field.name} saved`);
      return;
    }
    const v: any = field.kind === 'bool' ? value === '1' : (value === '' ? null : value);
    done(apiPut(`/api/admin/channels/${channel}/config`, { values: { [field.name]: v } }, { admin: true }), `${field.name} saved`);
  };
  const clear = () => done(apiDelete(`/api/admin/channels/${channel}/secret/${field.name}`, { admin: true }), `${field.name} removed`);
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', padding: '3px 0' }}>
      <label htmlFor={id} style={{ fontSize: 10.5, minWidth: 180 }}>{field.label}</label>
      {field.secret ? <Tag c={field.set ? 'var(--green)' : 'var(--ink-2)'}>{field.set ? 'set' : 'not set'}</Tag> : null}
      {field.source && <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>{SOURCE[field.source] || field.source}</span>}
      {field.editable ? (
        <>
          {field.kind === 'bool'
            ? (
              <select id={id} value={value === '1' ? '1' : '0'} onChange={(e) => setValue(e.target.value)} style={inpS}>
                <option value="0">off</option><option value="1">on</option>
              </select>
            )
            : <input id={id} type={field.secret ? 'password' : 'text'} autoComplete="off" value={value}
                placeholder={field.secret ? (field.set ? 'type to replace' : 'type to set') : ''}
                onChange={(e) => setValue(e.target.value)} style={{ ...inpS, minWidth: 180 }} />}
          <button className="tool-btn" disabled={busy} onClick={save}>save</button>
          {field.secret && field.set && field.source === 'hub' && <button className="tool-btn" disabled={busy} onClick={clear}>remove</button>}
        </>
      ) : !field.secret && field.value ? <span style={{ ...mono, fontSize: 10.5 }}>{field.value}</span> : null}
      {field.applies === 'now' && <Tag>applies now</Tag>}
    </div>
  );
}

export function ChannelsConfigPanel() {
  const { d, e, reload } = useApi(CHANNELS_CONFIG_PATH, true, true);
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const rows: ChannelRow[] = Array.isArray((d as any)?.channels) ? (d as any).channels : [];
  const waiting = rows.filter((r) => r.restart_required).map((r) => r.label);
  const changed = (msg: string) => { setNote(msg); reload(); };
  return (
    <Card title="CHANNELS" live={d ? 'live' : undefined} onReload={reload}
      sub={d ? `${rows.filter((r) => r.running).length} running of ${rows.length}` : null}>
      {e && <div role="status" style={{ color: 'var(--amber)', fontSize: 11 }}>not loaded · {String(e)}</div>}
      <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginBottom: 6 }}>
        Secrets are stored encrypted and never shown again. A value in <span style={mono}>.env</span> wins. Channels start with Nerva, so most changes apply after a restart.
      </div>
      {waiting.length > 0 && (
        <div role="status" style={{ fontSize: 11, color: 'var(--amber)', marginBottom: 6 }}>
          Restart Nerva to apply the changes to {waiting.join(', ')} (Console → Admin → Restart / Update).
        </div>
      )}
      {note && <div role="status" style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 4 }}>{note}</div>}
      <ul aria-label="channels" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {rows.map((r) => (
          <li key={r.id} style={{ borderBottom: '1px solid var(--panel-line)', padding: '5px 0' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 11.5 }}>{r.label}</span>
              <Tag c={r.running ? 'var(--green)' : 'var(--ink-2)'}>{r.running ? 'running' : 'not running'}</Tag>
              {r.restart_required && <Tag c="var(--amber)">restart to apply</Tag>}
              <button className="tool-btn" style={{ marginLeft: 'auto' }} aria-expanded={open === r.id}
                onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? 'close' : 'configure'}</button>
            </div>
            {open === r.id && (
              <div style={{ marginTop: 4 }}>
                {r.note && <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginBottom: 4 }}>{r.note}</div>}
                {r.fields.map((f) => <FieldEditor key={`${f.name}:${f.value ?? ""}:${f.set}`} channel={r.id} field={f} onChanged={changed} />)}
              </div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
