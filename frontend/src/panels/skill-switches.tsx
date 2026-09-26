/* H329 — switch a skill off without uninstalling it, everywhere or on one channel.
   `GET /skills` lists the installed skills with where each is switched off; every switch
   posts to the admin-only `POST /api/skills/switch` ({skill | category, enabled,
   channel?}). A switched-off skill stays installed, signed and approved: the model is
   not told about it and a command naming it is refused. Essential skills have no off
   switch. Switching back on is refused when the hub cannot record it, and a refusal is
   shown, never read as success; the list is re-read whatever the hub answered. A skill
   for another operating system is marked unsupported (H328). */
import React, { useState } from 'react';
import { Card, Row, State, Tag, actA, arr, asLive, inpS, mono, refusalReason, useApi } from '../panel-kit';

export const SKILLS_PATH = '/skills';
export const SWITCH_PATH = '/api/skills/switch';
const CHANNEL_RE = /^[a-z0-9][a-z0-9_.-]{0,31}$/;

export function SkillSwitchesPanel() {
  const { d, e, loading, reload } = useApi(SKILLS_PATH);
  const [channel, setChannel] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const map = (d && typeof (d as any).skills === 'object' && (d as any).skills) || {};
  const names = Object.keys(map).sort((a, b) => a.localeCompare(b));
  const where = channel.trim().toLowerCase();
  const channelOk = where === '' || CHANNEL_RE.test(where);
  const categories = Array.from(new Set(names.map((n) => map[n]?.category).filter((c) => typeof c === 'string' && c))).sort();

  const flip = (target: { skill?: string; category?: string }, enabled: boolean) => {
    if (!channelOk) return;
    const key = `${target.skill || target.category}:${enabled}`;
    const body: any = { ...target, enabled };
    if (where) body.channel = where;
    setBusy(key);
    setMsg(null);
    actA(SWITCH_PATH, body,
      (r: any) => {
        const changed = arr(r, 'changed');
        const kept = arr(r, 'essential');
        const note = r && r.audited === false && changed.length ? ' · not recorded in the intent log' : '';
        setMsg(changed.length
          ? `switched ${enabled ? 'on' : 'off'} ${where ? `on ${where}` : 'everywhere'} · ${changed.join(', ')}${note}`
          : kept.length ? `essential, stays on · ${kept.join(', ')}` : 'nothing to change');
        setBusy(null); reload();
      },
      (err: any) => { setMsg(`not switched · ${refusalReason(err, String(err?.status || 'error'))}`); setBusy(null); reload(); });
  };

  const offCount = names.filter((n) => map[n]?.disabled || arr(map[n], 'disabled_channels').length).length;
  return (
    <Card title="SKILL SWITCHES" live={asLive(d)} sub={d ? `${offCount} off · ${names.length}` : null} onReload={reload}>
      <State e={e} loading={loading} n={names.length} />
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
        <input style={{ ...inpS, flex: 1 }} aria-label="channel" placeholder="channel (empty = everywhere)"
          value={channel} onChange={(ev) => setChannel(ev.target.value)} />
      </div>
      {!channelOk && <div role="alert" style={{ fontSize: 10, color: 'var(--red)' }}>a channel is lower-case letters, digits, _ . -</div>}
      {names.map((n) => {
        const s = map[n] || {};
        const chans = arr(s, 'disabled_channels');
        const offHere = where ? chans.includes(where) || s.disabled : s.disabled;
        return (
          <Row key={n}>
            <span style={{ ...mono, color: offHere ? 'var(--ink-3)' : 'var(--accent-light)' }}>{n}</span>
            {s.essential && <Tag>essential</Tag>}
            {s.readiness === 'unsupported' && <Tag c="var(--red)">{s.readiness_reason || 'unsupported here'}</Tag>}
            {s.disabled && <Tag c="var(--amber)">off everywhere</Tag>}
            {!s.disabled && chans.map((c: string) => <Tag key={c} c="var(--amber)">off on {c}</Tag>)}
            {s.essential
              ? <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>always on</span>
              : <button className="tool-btn" style={{ marginLeft: 'auto' }} disabled={!channelOk || busy !== null}
                  aria-label={`${offHere ? 'switch on' : 'switch off'} ${n}`}
                  onClick={() => flip({ skill: n }, !!offHere)}>{offHere ? 'switch on' : 'switch off'}</button>}
          </Row>
        );
      })}
      {categories.length > 0 && (
        <>
          <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.08em', marginTop: 8 }}>BY CATEGORY</div>
          {categories.map((c: string) => (
            <Row key={c}>
              <span style={{ ...mono }}>{c}</span>
              <button className="tool-btn" style={{ marginLeft: 'auto' }} disabled={!channelOk || busy !== null}
                aria-label={`switch off category ${c}`} onClick={() => flip({ category: c }, false)}>all off</button>
              <button className="tool-btn" disabled={!channelOk || busy !== null}
                aria-label={`switch on category ${c}`} onClick={() => flip({ category: c }, true)}>all on</button>
            </Row>
          ))}
        </>
      )}
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6, lineHeight: 1.5 }}>
        A switched-off skill stays installed, signed and approved; the model is not told about it and a command
        naming it is refused. Switching back on is recorded in the intent log.
      </div>
      {msg && <div role="status" style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
    </Card>
  );
}
