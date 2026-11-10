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
   its own words, and both views are re-read.

   H443 — the memory writes the post-turn review (or a /refine) holds for the owner.
   `GET /api/memory/proposals` (admin) lists each held write with its facts, the ring each
   would go to and why it waits; approve or reject posts to
   `POST /api/memory/proposals/{id}/decide` and the hub's answer is shown as it is (what
   landed, what a ring refused). `memory.write_approval` is switched here too
   (`POST /api/memory/approval`): it holds the review's and /refine's writes only — the
   model's memory tool and /api/memory/remember still write at once, and the panel says so. */
import React, { useState } from 'react';
import { ConfirmAction, RISK_TIER } from '../confirm';
import { Card, Row, State, Tag, actA, arr, asLive, inpS, mono, refusalReason, useApi } from '../panel-kit';

export const CORE_PATH = '/api/memory/core';
export const UNDO_PATH = '/api/memory/core/undo';
export const STATUS_PATH = '/api/memory';
export const SWITCH_PATH = '/api/memory/switch';
export const RESET_PATH = '/api/memory/reset';
export const PROPOSALS_PATH = '/api/memory/proposals';
export const APPROVAL_PATH = '/api/memory/approval';
export const decidePath = (id: string) => `${PROPOSALS_PATH}/${encodeURIComponent(id)}/decide`;
/** Why a write waits, in the owner's words (review_policy.STAGE_REASONS). */
export const HELD_REASONS: Record<string, string> = {
  write_approval: 'memory write approval is on',
  untrusted_content: 'the conversation read untrusted content, or was not watched from its start',
  no_principal: 'the turn had no owner signed in',
  memory_tool_withheld: 'the turn was not offered the memory tool',
  approval_mode_ask: 'the approval dial is on ask',
  approval_mode_off: 'the approval dial is off',
};
const OUTCOMES: Record<string, string> = {
  added: 'written', duplicate: 'already kept', blocked: 'blocked as prompt-injection',
  refused: 'refused: the ring is full or the fact too long', memory_off: 'not written: memory is off',
};

/** H443 — the held writes' status in words: the oldest one's age and how many were not
    kept because the waiting list was full. Counts only; empty when there is nothing to say. */
export function heldStats(s: any): string {
  if (!s) return '';
  const parts: string[] = [];
  const age = s.oldest_pending_age_s;
  if (typeof age === 'number' && Number.isFinite(age) && num(s.pending) > 0) {
    parts.push(`oldest waiting ${age < 3600 ? `${Math.floor(age / 60)} min` : age < 86400 ? `${Math.floor(age / 3600)} h` : `${Math.floor(age / 86400)} d`}`);
  }
  if (num(s.dropped_at_cap) > 0) {
    parts.push(`${n(s.dropped_at_cap)} not kept: ${n(s.max_pending)} were already waiting`);
  }
  return parts.join(' · ');
}

/** What the hub answered to a decision, in its own terms: never "approved" for a write that did not land. */
export function decisionMessage(r: any, approved: boolean): string {
  if (!approved) return r?.status === 'rejected' ? 'rejected · nothing written' : `not rejected · ${String(r?.reason || r?.status || 'unknown')}`;
  const ops = arr(r?.proposal, 'operations');
  const told = ops.map((op: any) => OUTCOMES[String(op.outcome)] || 'not written yet').join(' · ');
  if (r?.applied === true) return `approved · ${num(r.written)} written${ops.length ? ` (${told})` : ''}`;
  return `approved, nothing written · ${told || String(r?.reason || r?.status || 'unknown')}`;
}
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
  const held = useApi(PROPOSALS_PATH, true, true);
  const h: any = held.d;
  const s: any = status.d;
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [target, setTarget] = useState('all');
  const enabled = d?.enabled === true;
  const undoable = arr(d, 'undoable');
  const stores = (s && s.stores) || {};
  const reloadAll = () => { reload(); status.reload(); held.reload(); };
  const decide = (id: string, approved: boolean) => {
    setBusy(id);
    setMsg(null);
    actA(decidePath(id), { approved },
      (r: any) => { setMsg(decisionMessage(r, approved)); setBusy(null); reloadAll(); },
      (err) => {
        const body = err?.body;
        setMsg(body && body.proposal ? decisionMessage(body, approved)
          : `not decided · ${refusalReason(err, String(err?.status || 'error'))}`);
        setBusy(null);
        reloadAll();
      });
  };
  const gate = (on: boolean) => actA(APPROVAL_PATH, { enabled: on },
    (r: any) => {
      setMsg(r && r.write_approval === on
        ? (on ? 'write approval on · the review\'s and /refine\'s memory writes now wait for you'
          : 'write approval off · the review writes memory on its own again')
        : `not switched · the hub still reads ${r && r.write_approval ? 'on' : 'off'}`);
      held.reload();
    },
    (err) => { setMsg(`not switched · ${refusalReason(err, String(err?.status || 'error'))}`); held.reload(); });
  const pending = arr(h, 'pending');
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
      {held.e && (
        <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>
          held memory writes could not be read ({String(held.e)}); nothing here says none are waiting
        </div>
      )}
      {h && (
        <div style={{ marginTop: 8 }}>
          <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', letterSpacing: '.08em' }}>
            HELD MEMORY WRITES · {pending.length}
          </div>
          {heldStats(h.stats) && (
            <div aria-label="held writes status" style={{ fontSize: 10, color: num(h.stats?.dropped_at_cap) > 0 ? 'var(--amber)' : 'var(--ink-2)' }}>
              {heldStats(h.stats)}
            </div>
          )}
          <div style={{ fontSize: 11, margin: '2px 0 4px' }}>
            {h.write_approval === true
              ? 'write approval is on: the post-turn review and /refine ask before they write.'
              : 'write approval is off: the post-turn review and /refine write on their own, except from a conversation that read untrusted content or was not watched from its start.'}
            {' '}The model's memory tool and /api/memory/remember are not held by it.
          </div>
          <ConfirmAction tier={RISK_TIER.REVERSIBLE}
            label={h.write_approval === true ? 'switch write approval off' : 'switch write approval on'}
            armedLabel={h.write_approval === true ? 'confirm off' : 'confirm on'}
            prompt={h.write_approval === true ? 'let the post-turn review write memory on its own again?'
              : 'hold the post-turn review\'s and /refine\'s memory writes for your approval?'}
            onConfirm={() => gate(h.write_approval !== true)} />
          {h.available === false && <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>not available on this hub</div>}
          {h.available !== false && pending.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>none waiting</div>}
          {pending.map((p: any) => (
            <div key={p.id} style={{ borderTop: '1px solid var(--panel-line)', marginTop: 6, paddingTop: 4 }}>
              <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>
                <span style={{ ...mono }}>{p.id}</span>{' · '}
                {p.origin === 'refine' ? '/refine' : 'background review'}{' · '}
                {HELD_REASONS[String(p.reason)] || String(p.reason || 'held')}
                {p.status === 'applying' ? ' · approved, not written yet (retried)' : ''}
              </div>
              {p.tainted === true && (
                <div style={{ fontSize: 10, color: 'var(--amber)' }}>
                  from a conversation that read untrusted content (a message from outside, a guest, web text, an attached file) or was not watched from its start: read each fact as a claim, not as yours
                </div>
              )}
              {arr(p, 'operations').map((op: any, i: number) => (
                <Row key={i}>
                  <Tag>{RING_LABELS[String(op.target)] || String(op.target)}</Tag>
                  <span style={{ fontSize: 12 }}>{String(op.text)}</span>
                  {op.outcome && <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>{OUTCOMES[String(op.outcome)] || String(op.outcome)}</span>}
                </Row>
              ))}
              {p.status === 'pending' && (
                <div style={{ display: 'flex', gap: 6, marginTop: 3 }}>
                  <button className="tool-btn" disabled={busy === p.id} aria-label={`approve ${p.id}`}
                    onClick={() => decide(p.id, true)}>approve</button>
                  <button className="tool-btn" disabled={busy === p.id} aria-label={`reject ${p.id}`}
                    onClick={() => decide(p.id, false)}>reject</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {msg && <div role="status" style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
    </Card>
  );
}
