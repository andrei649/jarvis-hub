/* H314 — the long-term memory the model writes with its `memory` tool, and the owner's
   undo. `GET /api/memory/core` lists both rings (the agent's notes and the user profile)
   and the newest writes that can still be undone; each undo posts its ref to the
   admin-only `POST /api/memory/core/undo`, which the hub refuses once the rings changed
   after that write. A refusal is shown, never read as success, and the list is re-read
   whatever the hub answered.

   H422 — the dashboard half of Hermes's memory status and reset. `GET /api/memory` says
   whether the curated memory is on as the running hub reads it (the owner's switch and
   cognition memory, a product posture included) and what each ring costs: its characters
   against the section's budget (2200 / 1375), its entries against the cap, its bytes on
   disk. The owner switches it off or on (`POST /api/memory/switch`, admin: nothing is
   erased) and resets a ring or both for good (`POST /api/memory/reset`, admin), the reset
   behind a typed RESET that states what it erases. Whatever the hub answers is shown in
   its own words, and both views are re-read. */
import React, { useState } from 'react';
import { ConfirmAction, RISK_TIER } from '../confirm';
import { Card, Row, State, Tag, actA, arr, asLive, inpS, mono, refusalReason, useApi } from '../panel-kit';

export const CORE_PATH = '/api/memory/core';
export const UNDO_PATH = '/api/memory/core/undo';
export const STATUS_PATH = '/api/memory';
export const SWITCH_PATH = '/api/memory/switch';
export const RESET_PATH = '/api/memory/reset';
/** A reset's targets and the rings each erases (memory_tool.RESET_TARGETS). */
export const RESET_RINGS: Record<string, string[]> = { all: ['memory', 'user'], memory: ['memory'], user: ['user'] };
const RING_TITLES: Record<string, string> = { memory: 'AGENT NOTES', user: 'USER PROFILE' };
const RING_LABELS: Record<string, string> = { memory: 'agent notes', user: 'user profile' };

const num = (v: any): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const n = (v: any): string => num(v).toLocaleString('en-US');

function Facts({ title, facts }: { title: string; facts: string[] }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', letterSpacing: '.08em' }}>{title} · {facts.length}</div>
      {facts.length === 0
        ? <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>nothing saved</div>
        : facts.map((fact, i) => <Row key={i}><span style={{ fontSize: 12 }}>{fact}</span></Row>)}
    </div>
  );
}

/** One ring's size against its budget, as `GET /api/memory` reports it. */
function Usage({ ring, store }: { ring: string; store: any }) {
  const chars = num(store?.chars);
  const budget = num(store?.char_budget);
  const over = budget > 0 && chars > budget;
  const pct = budget > 0 ? Math.min(100, Math.round((chars / budget) * 100)) : 0;
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ ...mono, fontSize: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--ink-2)', letterSpacing: '.08em' }}>{RING_TITLES[ring]}</span>
        <span aria-label={`${RING_LABELS[ring]} size`}>
          {n(chars)}/{n(budget)} chars · {n(store?.entries)}/{n(store?.cap)} entries · {n(store?.bytes)} bytes on disk
        </span>
      </div>
      <div aria-hidden="true" style={{ height: 4, background: 'var(--panel-line)', borderRadius: 2, marginTop: 3 }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 2, background: over ? 'var(--amber)' : 'var(--accent-light)' }} />
      </div>
      {num(store?.omitted) > 0 && (
        <div style={{ fontSize: 10, color: 'var(--amber)' }}>
          {n(store.omitted)} older {num(store.omitted) === 1 ? 'entry' : 'entries'} left out of the prompt: over the budget
        </div>
      )}
      {num(store?.blocked) > 0 && (
        <div style={{ fontSize: 10, color: 'var(--amber)' }}>{n(store.blocked)} blocked as prompt-injection</div>
      )}
    </div>
  );
}

/** What the hub says the curated memory is doing, in the owner's words. */
export function memoryState(s: any): string {
  if (!s) return '';
  if (s.available === false) return 'not available on this hub (no cognition module)';
  if (s.enabled === true) return s.safe_mode ? 'on · safe mode keeps it out of every prompt' : 'on · every prompt carries it';
  if (s.switch === false) return 'off · switched off by the owner; the stores stay on disk';
  return 'off · cognition memory is off (cognition.enabled, cognition.memory_enabled); the stores stay on disk';
}

export function LongTermMemoryPanel() {
  const { d, e, loading, reload } = useApi(CORE_PATH);
  const status = useApi(STATUS_PATH);
  const s: any = status.d;
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [target, setTarget] = useState('all');
  const enabled = d?.enabled === true;
  const undoable = arr(d, 'undoable');
  const stores = (s && s.stores) || {};
  const reloadAll = () => { reload(); status.reload(); };
  const undo = (ref: string) => {
    setBusy(ref);
    setMsg(null);
    actA(UNDO_PATH, { ref },
      () => { setMsg(`undone · ${ref}`); setBusy(null); reload(); },
      (err) => { setMsg(`not undone · ${refusalReason(err, String(err?.status || 'error'))}`); setBusy(null); reload(); });
  };
  const flip = (on: boolean) => actA(SWITCH_PATH, { enabled: on },
    (r: any) => {
      // The reply is the status as the hub now reads it: say what memory really does.
      if (r && r.applied === false) setMsg(`switch saved · ${refusalReason({ body: r }, 'the hub applies it shortly')}`);
      else if (on && r && r.enabled !== true) setMsg('switch on · memory stays off until cognition memory is on');
      else setMsg(on ? 'memory on · the next turn carries it' : 'memory off · the next turn carries none of it; nothing erased');
      reloadAll();
    },
    (err) => { setMsg(`not switched · ${refusalReason(err, String(err?.status || 'error'))}`); reloadAll(); });
  const rings = RESET_RINGS[target] || [];
  const erasing = rings.reduce((acc, ring) => ({
    entries: acc.entries + num(stores[ring]?.entries), bytes: acc.bytes + num(stores[ring]?.bytes),
  }), { entries: 0, bytes: 0 });
  const reset = () => actA(RESET_PATH, { target, confirm: 'RESET' },
    (r: any) => {
      const erased = Object.entries((r && r.erased) || {}).map(([ring, count]) => `${RING_LABELS[ring] || ring}: ${n(count)}`);
      setMsg(`reset · erased ${erased.join(' · ') || 'nothing'}`);
      reloadAll();
    },
    (err) => { setMsg(`not reset · ${refusalReason(err, String(err?.status || 'error'))}`); reloadAll(); });
  const on = s ? s.enabled === true : enabled;
  return (
    <Card title="LONG-TERM MEMORY" live={asLive(d || s, on)} sub={d || s ? (on ? `${undoable.length} undoable` : 'off') : null} onReload={reloadAll}>
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {s && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 11, marginBottom: 4 }}>
            <span style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', letterSpacing: '.08em' }}>CURATED MEMORY</span>{' '}
            <span>{memoryState(s)}</span>
          </div>
          {s.available !== false && ['memory', 'user'].map((ring) => stores[ring]
            ? <Usage key={ring} ring={ring} store={stores[ring]} /> : null)}
          {s.drift && <div style={{ fontSize: 10, color: 'var(--amber)' }}>{String(s.drift)}</div>}
          {s.available !== false && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginTop: 4 }}>
              <ConfirmAction tier={RISK_TIER.REVERSIBLE}
                label={s.switch === false ? 'switch memory on' : 'switch memory off'}
                armedLabel={s.switch === false ? 'confirm on' : 'confirm off'}
                prompt={s.switch === false ? 'bring the notes and the profile back into the prompt?'
                  : 'take the notes and the profile out of every prompt? nothing is erased'}
                onConfirm={() => flip(s.switch === false)} />
              <ConfirmAction tier={RISK_TIER.IRREVERSIBLE_OR_MONEY} phrase="RESET" label="reset memory…"
                armedLabel="confirm reset" style={{ color: 'var(--red)' }}
                extra={(
                  <select aria-label="what to reset" value={target} onChange={(ev) => setTarget(ev.target.value)} style={inpS}>
                    <option value="all">both</option>
                    <option value="memory">agent notes</option>
                    <option value="user">user profile</option>
                  </select>
                )}
                prompt={`type RESET to erase ${n(erasing.entries)} entries (${n(erasing.bytes)} bytes) for good:`}
                inputLabel="type RESET to confirm the memory reset"
                onConfirm={reset} />
            </div>
          )}
        </div>
      )}
      {d && !enabled && (
        <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>
          Memory is switched off (cognition.enabled and cognition.memory_enabled).
        </div>
      )}
      {enabled && (
        <>
          <Facts title="AGENT NOTES" facts={arr(d, 'memory')} />
          <Facts title="USER PROFILE" facts={arr(d, 'user')} />
          <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', letterSpacing: '.08em', marginTop: 6 }}>RECENT WRITES</div>
          {undoable.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>none to undo</div>}
          {undoable.map((w: any) => (
            <Row key={w.ref}>
              <span style={{ ...mono }}>{w.ref}</span>
              {arr(w, 'targets').map((t: string) => <Tag key={t}>{t}</Tag>)}
              <button className="tool-btn" style={{ marginLeft: 'auto' }} disabled={busy === w.ref}
                aria-label={`undo ${w.ref}`} onClick={() => undo(w.ref)}>undo</button>
            </Row>
          ))}
        </>
      )}
      {msg && <div role="status" style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
    </Card>
  );
}
