/* H329 — switch a skill off without uninstalling it, everywhere or on one channel.
   `GET /skills` lists the installed skills with where each is switched off; every switch
   posts to the admin-only `POST /api/skills/switch` ({skill | category, enabled,
   channel?}). A switched-off skill stays installed, signed and approved: the model is
   not told about it and a command naming it is refused. Essential skills have no off
   switch. Switching back on is pending until a human approves and the worker applies
   it; the list is re-read whatever the hub answered. A skill
   for another operating system is marked unsupported (H328).
   H026 — a named bundle (`GET /api/skills/bundles`) is switched as one unit with the same
   route ({bundle}); its members that are not installed are named, never matched. Its chat
   command is shown too: the owner's `/<slug> [instruction]` in the chat loads every member
   into that turn (the hub does it; this panel only names the command).
   H349 — each skill row also shows what the hub's usage sidecar recorded: where the skill
   came from (shipped, imported and from where, made by the agent, or local with no install
   record), how often it ran, was viewed and was patched, and the owner's pin. Pin and unpin
   post to the admin-only `POST /api/skills/pin` ({skill, pinned}); a refusal or a failed
   write is shown in the hub's own words and the list is re-read, so the row never shows a
   pin the hub did not store. */
import React, { useState } from 'react';
import { Card, Row, State, Tag, actA, arr, asLive, inpS, mono, refusalReason, useApi } from '../panel-kit';

export const SKILLS_PATH = '/skills';
export const SWITCH_PATH = '/api/skills/switch';
export const BUNDLES_PATH = '/api/skills/bundles';
export const PIN_PATH = '/api/skills/pin';

const ORIGIN_LABEL: Record<string, string> = {
  bundled: 'ships with Nerva', import: 'imported', agent: 'made by the agent', local: 'local · no install record',
};

/* Where a skill came from, as the hub recorded it; nothing for an origin it never recorded. */
export function originLabel(usage: any): string {
  const origin = usage && typeof usage.origin === 'string' ? usage.origin : '';
  const label = ORIGIN_LABEL[origin];
  if (!label) return '';
  const source = origin === 'import' && typeof usage.source === 'string' ? usage.source.trim() : '';
  return source ? `${label} · ${source}` : label;
}

const count = (v: any) => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? Math.floor(v) : 0);

/* "used 3× · viewed 1× · patched 0×", or null when the hub sent no counters (an older hub). */
export function usageCounts(usage: any): string | null {
  if (!usage || typeof usage !== 'object' || typeof usage.use_count !== 'number') return null;
  return `used ${count(usage.use_count)}× · viewed ${count(usage.view_count)}× · patched ${count(usage.patch_count)}×`;
}
const CHANNEL_RE = /^[a-z0-9][a-z0-9_.-]{0,31}$/;

export function SkillSwitchesPanel() {
  const { d, e, loading, reload: reloadSkills } = useApi(SKILLS_PATH);
  const bundleApi = useApi(BUNDLES_PATH);
  const reload = () => { reloadSkills(); bundleApi.reload(); };
  const bundles = arr(bundleApi.d, 'bundles');
  const [channel, setChannel] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const map = (d && typeof (d as any).skills === 'object' && (d as any).skills) || {};
  const names = Object.keys(map).sort((a, b) => a.localeCompare(b));
  const where = channel.trim().toLowerCase();
  const channelOk = where === '' || CHANNEL_RE.test(where);
  const categories = Array.from(new Set(names.map((n) => map[n]?.category).filter((c) => typeof c === 'string' && c))).sort();

  const flip = (target: { skill?: string; category?: string; bundle?: string }, enabled: boolean, here = where) => {
    if (!channelOk) return;
    const key = `${target.skill || target.category || target.bundle}:${enabled}`;
    const body: any = { ...target, enabled };
    if (here) body.channel = here;
    setBusy(key);
    setMsg(null);
    actA(SWITCH_PATH, body,
      (r: any) => {
        // H026: a bundle member that is not installed was skipped; say which.
        const missing = arr(r, 'missing');
        const absent = missing.length ? ` · not installed: ${missing.join(', ')}` : '';
        if (r?.status === 'pending') {
          const offAll = arr(r, 'off_everywhere');
          setMsg(`pending owner approval · task ${r.task_id} · ${arr(r, 'pending').join(', ')}`
            + (offAll.length ? ` · still off everywhere: ${offAll.join(', ')}` : '') + absent);
          setBusy(null); reload();
          return;
        }
        const changed = arr(r, 'changed');
        const kept = arr(r, 'essential');
        const note = r && r.audited === false && changed.length ? ' · not recorded in the intent log' : '';
        // review-H329 F3/F6: a skill still off everywhere, or a switch the hub could not store.
        const offAll = arr(r, 'off_everywhere');
        const unstored = arr(r, 'unstorable');
        const more = (offAll.length && changed.length ? ` · still off everywhere: ${offAll.join(', ')}` : '')
          + (unstored.length ? ` · could not be stored: ${unstored.join(', ')}` : '') + absent;
        setMsg(changed.length
          ? `switched ${enabled ? 'on' : 'off'} ${here ? `on ${here}` : 'everywhere'} · ${changed.join(', ')}${note}${more}`
          : offAll.length ? `still off everywhere · ${offAll.join(', ')}`
          : unstored.length ? `not switched off · could not be stored: ${unstored.join(', ')}`
          : kept.length ? `essential, stays on · ${kept.join(', ')}` : `nothing to change${absent}`);
        setBusy(null); reload();
      },
      (err: any) => { setMsg(`not switched · ${refusalReason(err, String(err?.status || 'error'))}`); setBusy(null); reload(); });
  };

  const pin = (skill: string, pinned: boolean) => {
    setBusy(`pin:${skill}`);
    setMsg(null);
    actA(PIN_PATH, { skill, pinned },
      (r: any) => {
        // Only what the hub confirmed: its answer says whether the pin is stored now.
        const stored = r && r.ok === true && r.pinned === pinned;
        setMsg(!stored ? `${pinned ? 'not pinned' : 'not unpinned'} · the hub did not confirm it`
          : r.changed === false ? `${skill} was already ${pinned ? 'pinned' : 'not pinned'}`
          : `${pinned ? 'pinned' : 'unpinned'} · ${skill}${r.audited === false ? ' · not recorded in the intent log' : ''}`);
        setBusy(null); reload();
      },
      (err: any) => {
        setMsg(`${pinned ? 'not pinned' : 'not unpinned'} · ${refusalReason(err, String(err?.status || 'error'))}`);
        setBusy(null); reload();
      });
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
        // Off everywhere: a switch-on for one channel would leave it off there too (review-H329 F3).
        const onEverywhere = !!s.disabled && !!where;
        const usage = s.usage && typeof s.usage === 'object' ? s.usage : null;
        const from = originLabel(usage);
        const counts = usageCounts(usage);
        const pinned = usage?.pinned === true;
        return (
          <Row key={n}>
            <span style={{ ...mono, color: offHere ? 'var(--ink-2)' : 'var(--accent-light)' }}>{n}</span>
            {s.essential && <Tag>essential</Tag>}
            {from && <Tag>{from}</Tag>}
            {pinned && <Tag c="var(--accent-light)">pinned</Tag>}
            {counts && <span style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)' }}
              title={usage.last_used_at ? `last used ${usage.last_used_at}` : 'never used'}>{counts}</span>}
            {s.readiness === 'unsupported' && <Tag c="var(--red)">{s.readiness_reason || 'unsupported here'}</Tag>}
            {s.disabled && <Tag c="var(--amber)">off everywhere</Tag>}
            {!s.disabled && chans.map((c: string) => <Tag key={c} c="var(--amber)">off on {c}</Tag>)}
            {s.essential
              ? <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-2)' }}>always on</span>
              : <button className="tool-btn" style={{ marginLeft: 'auto' }} disabled={!channelOk || busy !== null}
                  aria-label={`${offHere ? 'switch on' : 'switch off'} ${n}`}
                  onClick={() => flip({ skill: n }, !!offHere, onEverywhere ? '' : where)}>
                  {offHere ? (onEverywhere ? 'switch on everywhere' : 'switch on') : 'switch off'}</button>}
            {(pinned || usage?.pinnable === true) && (
              <button className="tool-btn" disabled={busy !== null} aria-label={`${pinned ? 'unpin' : 'pin'} ${n}`}
                onClick={() => pin(n, !pinned)}>{pinned ? 'unpin' : 'pin'}</button>)}
          </Row>
        );
      })}
      {categories.length > 0 && (
        <>
          <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', letterSpacing: '.08em', marginTop: 8 }}>BY CATEGORY</div>
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
      {bundleApi.d && (
        <>
          <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', letterSpacing: '.08em', marginTop: 8 }}>BY BUNDLE</div>
          {bundles.length === 0 && (
            <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>no bundles · nerva skills bundles create NAME --skill A --skill B</div>
          )}
          {bundles.map((b: any) => {
            const missing = arr(b, 'missing');
            return (
              <Row key={b.slug}>
                <span style={{ ...mono }} title={b.description || undefined}>{b.name}</span>
                <Tag>{arr(b, 'skills').length} skills</Tag>
                {missing.length > 0 && <Tag c="var(--amber)">{missing.length} not installed</Tag>}
                <span style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)' }}
                  title="send it in the chat to load every skill of the bundle into that turn">/{b.slug}</span>
                <button className="tool-btn" style={{ marginLeft: 'auto' }} disabled={!channelOk || busy !== null}
                  aria-label={`switch off bundle ${b.name}`} onClick={() => flip({ bundle: b.slug }, false)}>all off</button>
                <button className="tool-btn" disabled={!channelOk || busy !== null}
                  aria-label={`switch on bundle ${b.name}`} onClick={() => flip({ bundle: b.slug }, true)}>all on</button>
              </Row>
            );
          })}
        </>
      )}
      <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 6, lineHeight: 1.5 }}>
        A switched-off skill stays installed, signed and approved; the model is not told about it and a command
        naming it is refused. Switching back on requires owner approval; the switch changes after the task runs.
        {' '}A pinned skill is never marked stale or archived by the curator, and a skill batch or the journey's
        forget refuses to delete it until it is unpinned; it can still be patched, and uninstalling it or
        rejecting it from review yourself is not blocked. A skill that ships with Nerva has no pin.
        {bundles.length > 0 && ' The owner sends /<bundle> [instruction] in the chat to load a bundle\'s skills into that turn.'}
      </div>
      {msg && <div role="status" style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
    </Card>
  );
}
