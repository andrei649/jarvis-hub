/* MISSION & CANVAS — two shipped, user-reachable routes that had no client at all, plus
   one route in this lane that is deliberately NOT built.

     · POST /api/missions/{mission_id}/steps/{idx}/finish   (user tier)  missions.py:139
     · POST /api/canvas/clear                               (user tier)  canvas.py:64
     · the context-compress route                          REFUSED — see (F) below.

   Handlers read in full (agents/core/routers/missions.py, agents/core/autonomy/missions.py,
   agents/core/routers/canvas.py, agents/core/canvas.py). What they really do, and therefore
   what this panel is forbidden to imply:

   (A) THE BUDGET 409 IS NOT A NO-OP. `MissionStore.finish_step` (missions.py:243-263) writes
       the plan row, increments `steps_used`, COMMITS, logs a "step" event — and only THEN, if
       `new_used >= max_steps`, calls `self.fail(mission_id, reason="step budget exhausted")`
       and raises BudgetExceeded, which the router turns into
       409 {"error": "mission step budget exhausted", "budget_exceeded": true}.
       So the operator sees an HTTP error for a request that DID land: the step is recorded and
       the mission is now FAILED. Rendering that as "failed, nothing happened, retry" would be a
       lie. This panel reloads on the error branch too and says the side effect out loud, and it
       offers no retry there.

   (B) THE 409 NOW NAMES ITS CAUSE. `_transition` used to catch MissionError and answer one
       fixed string, 409 {"error": "operation not allowed in current mission state"}, for
       every refusal. For finish_step that covered four — mission gone, mission not active,
       step index out of range, invalid step status — and for two of them the string was not
       merely vague but WRONG: an out-of-range index is not a mission-state problem, yet the
       body blamed mission state and this panel duly told the operator to start or resume the
       mission, advice that could not be followed. The raise sites now carry a literal `code`
       and the router maps it to one fixed sentence per cause; the exception TEXT still never
       reaches the body (it interpolates ids and statuses). The panel renders the backend's
       string verbatim, as before — it is simply true now.

   (C) AN EMPTY MISSION BOARD IS AMBIGUOUS. `missions_list` (missions.py:36) has NO 503 branch:
       when `_store()` is None it answers 200 {"missions": []}. So {"missions": []} means EITHER
       "no missions" OR "the mission store is unavailable", and the read cannot tell them apart.
       This panel refuses to draw that as a clean "nothing yet" and says so in amber. (Backend
       gap — the fix belongs in the router, not here.)

   (D) MISSION-LEVEL TRANSITIONS ARE OUT OF LANE. gap.tsx MissionsPanel already ships
       start/pause/resume/complete/cancel over the mission-op routes. This card is the
       per-step half that had no UI at all. When a mission is not ACTIVE the finish controls are
       not rendered at all — because finish_step raises unless status == "active" — and the
       panel points at the MISSIONS panel only for the two statuses that can actually get back
       to active: planned → start, paused → resume. done/failed/cancelled are TERMINAL with an
       EMPTY exit set in `_TRANSITIONS` (agents/core/autonomy/missions.py), every status write
       goes through `_set_status`, which raises unless the target is in that set, and the
       MissionsPanel renders no button for them — so for those three the panel names no control
       at all and says the mission cannot return to active. (Sending the operator hunting for a
       start/resume there would be a dead control AND a 409.)

   (E) /api/canvas/clear TAKES NO REQUEST BODY. Both handler args are bare scalars, so FastAPI
       binds them as QUERY parameters (`agent: Optional[str] = None`, `keep_pinned: bool = True`;
       the generated schema.gen.ts:10730 has `requestBody?: never`). A JSON body is silently
       ignored and the DEFAULTS apply — meaning a caller that put {agent, keep_pinned:false} in
       the body would sweep EVERY agent's elements while believing it had scoped the sweep. The
       parameters are composed into the query string below and the body is `undefined`.
       The operation is irreversible: CanvasStore.clear filters the list and calls `_save()`;
       there is no undo route.

   (F) The context-compress route IS REFUSED and stays on UNCALLED_BACKLOG. Its path is spelled
       out only in tests/test_hud_v2_parity.py, not here: the parity matcher counts any literal
       occurrence in a client file as a caller, so writing it in this comment would delist the
       route and claim a UI that does not exist. Its entire request
       is `turns: list[dict]` — a conversation transcript of {role, content} produced by a
       running session (orch.memory.get_history), never typed by a person; a textarea asking the
       owner to paste JSON turns is a fake surface. There is also no honest read to source it
       from: /sessions returns checkpoint metadata with no turns, /api/agents/history returns run
       rollups, and the only route that yields real turns — POST /sessions/resume — SWITCHES THE
       LIVE SESSION (it reassigns orch.session_id), so using it as a preview would be a
       destructive side effect disguised as a read. And the route changes nothing: it builds a
       throwaway ContextCompressor, returns the result and persists none of it. The production
       compression path is in-process (orchestrator.get_context, agents/core/orchestrator.py:2241)
       under the memory.context_compression / memory.compression_* settings, which no route
       exposes — so a button here could not enable, tune or influence it. Nothing is built for it.

   (G) THIS IS NOT A SECOND ARTIFACT BROWSER. frontend/src/artifacts.tsx already lists canvas
       element bodies with pin/unpin/delete. Card 2 renders AGGREGATES ONLY (per-author counts)
       and exists for the one thing no client has: the bulk sweep and its {"removed": n}.

   Both routes are USER tier (Depends(user_guard)) — act(), not actA(). */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, inpS } from '../panel-kit';

/* The backend's own words, never ours. apiPost throws on 4xx/5xx and rides the parsed refusal
   body along on `err.body` (api/client.ts:104), so the real `error`/`detail` string is reachable
   — a call site that invents a plausible cause instead is exactly what this HUD exists to
   remove. Falls back to err.message only when the response carried no JSON at all (a 500 from
   the ASGI layer, or a network failure). */
const reason = (err: any): string => {
  const b = err && err.body;
  if (b && typeof b.error === 'string') return b.error;
  if (b && typeof b.detail === 'string') return b.detail;
  if (b && b.detail != null) return JSON.stringify(b.detail);
  return (err && err.message) || 'request failed';
};

const RED = 'var(--red)';
const AMBER = 'var(--amber)';
const GREEN = 'var(--green)';
const INK3 = 'var(--ink-3)';

const missionColor = (s: string) => s === 'active' ? GREEN : s === 'paused' ? AMBER
  : s === 'failed' ? RED : s === 'done' ? 'var(--accent-light)' : INK3;
const stepColor = (s: string) => s === 'running' ? AMBER : s === 'done' ? GREEN
  : s === 'failed' ? RED : INK3;

/* Why a mission that is not active gets three different sentences, not one.

   `_TRANSITIONS` (agents/core/autonomy/missions.py) is the whole state machine, and every
   status write goes through `_set_status`, which raises MissionError unless the target status
   is in the current status's exit set:

     planned → {active, cancelled}     paused → {active, cancelled, failed}
     done / failed / cancelled → {}    ← TERMINAL, no exit at all

   So only planned (start) and paused (resume) can return to active, and each accepts exactly
   ONE of those two ops — not "start or resume". For the three terminal statuses NO caller can
   revive the mission: the mission-op routes answer 409 and gap.tsx MissionsPanel renders no
   button for them, so naming a control there would point at one that does not exist. */
const REVIVE: Record<string, string> = { planned: 'start', paused: 'resume' };
const TERMINAL_MISSION: Record<string, boolean> = { done: true, failed: true, cancelled: true };

const notActiveHint = (raw: any): string => {
  const s = typeof raw === 'string' && raw ? raw : '';
  const head = s
    ? 'finish_step runs only while the mission is active (this one is ' + s + ')'
    : 'finish_step runs only while the mission is active (this row carries no status)';
  if (REVIVE[s]) return head + ' — ' + REVIVE[s] + ' it from the MISSIONS panel.';
  if (TERMINAL_MISSION[s]) {
    return head + '. ' + s + ' is terminal — the mission state machine has no transition out of '
      + 'done, failed or cancelled, so nothing can put this mission back to active and these '
      + 'steps can no longer be finished.';
  }
  return head + '.';
};

const note = (children: any, c = INK3) => (
  <div style={{ ...mono, fontSize: 10, lineHeight: 1.5, color: c, padding: '4px 0' }}>{children}</div>
);
const foot = (children: any) => (
  <div style={{ ...mono, fontSize: 9.5, color: INK3, marginTop: 8, lineHeight: 1.5 }}>{children}</div>
);

export function MissionCanvasPanel() {
  /* ── Card 1 state ─────────────────────────────────────────────── */
  const { d, e, loading, reload } = useApi('/api/missions');
  const missions = arr(d, 'missions');
  const [sel, setSel] = useState<any>(null);           // expanded mission id
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [last, setLast] = useState<any>(null);         // last successful finish
  const [errFor, setErrFor] = useState<any>(null);     // last refused finish

  /* ── Card 2 state ─────────────────────────────────────────────── */
  const { d: cd, e: ce, loading: cl, reload: creload } = useApi('/api/canvas');
  const els = arr(cd, 'elements');
  const [scope, setScope] = useState('');              // '' = every author
  const [keepPinned, setKeepPinned] = useState(true);
  const [armed, setArmed] = useState(false);
  const [removed, setRemoved] = useState<number | null>(null);
  const [removedAt, setRemovedAt] = useState<number | null>(null);  // predicted at fire time
  const [cErr, setCErr] = useState<any>(null);

  const key = (mid: any, idx: any) => String(mid) + ':' + String(idx);

  const finish = (m: any, s: any, status: string) => {
    const draft = (drafts[key(m.id, s.idx)] || '').trim();
    // `result` is omitted when blank so the handler's `(body or {}).get("result")` → None
    // default applies, rather than storing an empty string into the plan row.
    const body: any = draft ? { status, result: draft } : { status };
    // Single-line URL on purpose: the parity matcher needs the stem, '/steps/' and '/finish'
    // on ONE line with ≤60 chars of interpolation between them.
    act('/api/missions/' + m.id + '/steps/' + s.idx + '/finish', body, (r: any) => { setErrFor(null); setLast({ id: m.id, idx: s.idx, mission: r && r.mission }); setDrafts((p) => ({ ...p, [key(m.id, s.idx)]: '' })); reload(); }, (err: any) => { setLast(null); setErrFor({ id: m.id, idx: s.idx, status: err && err.status, msg: reason(err), budget: !!(err && err.body && err.body.budget_exceeded), code: (err && err.body && typeof err.body.code === 'string') ? err.body.code : null }); reload(); });
  };

  /* Authors seen in the LAST fetch. There is no route listing canvas authors, so the choices
     are derived from real elements — never a hardcoded list. */
  const authors: string[] = [];
  const counts: Record<string, { n: number; p: number }> = {};
  els.forEach((el: any) => {
    const a = String(el && el.agent != null ? el.agent : 'agent');
    if (!counts[a]) { counts[a] = { n: 0, p: 0 }; authors.push(a); }
    counts[a].n += 1;
    if (el && el.pinned) counts[a].p += 1;
  });
  const pinnedTotal = els.filter((el: any) => el && el.pinned).length;
  const matches = (el: any) => (scope === '' || String(el && el.agent != null ? el.agent : 'agent') === scope)
    && !(keepPinned && el && el.pinned);
  const predicted = els.filter(matches).length;

  const rearm = (fn: () => void) => { fn(); setArmed(false); setRemoved(null); setRemovedAt(null); setCErr(null); };

  const clear = () => {
    if (!armed) { setArmed(true); return; }   // never fire on a single click — irreversible
    const fired = predicted;
    /* /api/canvas/clear takes NO body — agent and keep_pinned are QUERY params
       (schema.gen.ts:10730 requestBody?: never). A JSON body is silently ignored and the
       defaults apply, which would sweep the whole canvas. */
    const url = '/api/canvas/clear?keep_pinned=' + (keepPinned ? 'true' : 'false') + (scope ? '&agent=' + encodeURIComponent(scope) : '');
    act(url, undefined, (r: any) => { setCErr(null); setRemoved(typeof (r && r.removed) === 'number' ? r.removed : null); setRemovedAt(fired); setArmed(false); creload(); }, (err: any) => { setRemoved(null); setRemovedAt(null); setArmed(false); setCErr({ status: err && err.status, msg: reason(err) }); });
  };

  const b = last && last.mission && last.mission.budget;
  /* Read the finished step back OFF THE RESPONSE, by its own `idx`, rather than echoing the
     status we asked for: the store coerces through StepStatus and the response is the only
     record of what was actually written. */
  const finishedStep = last && last.mission && Array.isArray(last.mission.plan)
    ? (last.mission.plan.find((p: any) => p && p.idx === last.idx) || last.mission.plan[last.idx])
    : null;

  return (
    <>
      <Card title="MISSION STEPS" live={asLive(d)} sub={d ? `${missions.length} workspaces` : null} onReload={reload}>
        {/* State is used for loading/offline only. Its n===0 branch prints "nothing yet",
            which would be a confident claim this read cannot make — see (C). */}
        {(loading || e) && <State e={e} loading={loading} n={missions.length} />}
        {!loading && !e && missions.length === 0 && note(
          'no missions returned — GET /api/missions answers {"missions": []} both when there are none and when the mission store is unavailable (it has no 503 branch), so this board cannot tell the two apart. A finish against an unavailable store would answer 503 "missions not available".',
          AMBER,
        )}

        {missions.slice(0, 12).map((m: any, i: number) => {
          const open = sel === m.id;
          const plan = Array.isArray(m.plan) ? m.plan : [];
          return (
            <div key={m.id ?? i}>
              <Row>
                <span style={{ ...mono, color: 'var(--ink-2)' }}>{m.title || '(untitled)'}</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                  <Tag c={missionColor(m.status)}>{m.status}</Tag>
                  <Tag>{m.steps_used ?? 0}/{m.max_steps ?? '—'} steps</Tag>
                  <button
                    className="tool-btn"
                    aria-label={'steps of mission ' + m.id}
                    onClick={() => setSel(open ? null : m.id)}
                  >{open ? 'hide steps' : 'steps'}</button>
                </span>
              </Row>

              {open && (
                <div style={{ padding: '2px 0 8px 10px', borderLeft: '1px solid var(--panel-line)' }}>
                  {plan.length === 0 && note('this mission has no plan steps — nothing to finish')}

                  {m.status !== 'active' && plan.length > 0 && note(notActiveHint(m.status), AMBER)}

                  {plan.map((s: any, si: number) => {
                    const idx = typeof s.idx === 'number' ? s.idx : si;
                    const open2 = m.status === 'active' && (s.status === 'pending' || s.status === 'running');
                    return (
                      <div key={idx}>
                        <Row>
                          <span style={{ ...mono, color: INK3 }}>#{idx}</span>
                          <span style={{ ...mono, color: 'var(--ink-2)' }}>{s.title || '(untitled step)'}</span>
                          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                            <Tag c={stepColor(s.status)}>{s.status}</Tag>
                            {s.ended_at && <Tag>{String(s.ended_at)}</Tag>}
                          </span>
                        </Row>
                        {s.result != null && (
                          <div style={{ ...mono, fontSize: 10, color: 'var(--ink-2)', padding: '2px 0 4px 12px' }}>
                            result: {String(typeof s.result === 'string' ? s.result : JSON.stringify(s.result)).slice(0, 240)}
                          </div>
                        )}
                        {open2 && (
                          <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap', padding: '2px 0 6px 12px' }}>
                            <input
                              style={{ ...inpS, flex: '1 1 160px' }}
                              aria-label={'result note for step ' + idx + ' of mission ' + m.id}
                              placeholder="result note (optional)"
                              value={drafts[key(m.id, idx)] || ''}
                              onChange={(ev) => setDrafts((p) => ({ ...p, [key(m.id, idx)]: ev.target.value }))}
                            />
                            {['done', 'failed', 'skipped'].map((st) => (
                              <button
                                key={st}
                                className="tool-btn"
                                aria-label={st + ' step ' + idx + ' of mission ' + m.id}
                                onClick={() => finish(m, { ...s, idx }, st)}
                              >{st}</button>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}

                  {last && last.id === m.id && b && (
                    <div style={{ ...mono, fontSize: 10, color: GREEN, padding: '4px 0', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span>
                        step #{last.idx} → {finishedStep ? finishedStep.status : '(status not in response)'}
                        {' · '}budget {b.steps_used}/{b.max_steps} used, {b.steps_remaining} left
                        {' · '}{b.elapsed_seconds == null ? 'elapsed: not started' : b.elapsed_seconds + 's of ' + b.max_seconds + 's'}
                      </span>
                      {b.over_time === true && <Tag c={AMBER}>over time</Tag>}
                    </div>
                  )}

                  {errFor && errFor.id === m.id && (
                    <div style={{ padding: '4px 0' }}>
                      <div style={{ ...mono, fontSize: 10, color: RED, display: 'flex', gap: 6, alignItems: 'center' }}>
                        <Tag c={RED}>{errFor.status}</Tag>
                        <span>step #{errFor.idx} refused: {errFor.msg}</span>
                      </div>
                      {/* (A) — the refusal is NOT a rollback. */}
                      {errFor.budget && note(
                        'the step WAS recorded and the mission was auto-failed by the backend before it raised — the row above is reloaded from the server, check its status. There is nothing to retry.',
                        AMBER,
                      )}
                      {/* (B) — the 409 names its cause now, so the message above IS the cause
                          and there is nothing to hedge. A refusal WITHOUT a code came from an
                          older backend that answered one string for every cause; only then is
                          the hedge still the honest thing to say. */}
                      {errFor.status === 409 && !errFor.budget && errFor.code == null && note(
                        'this refusal carries no `code`: an older backend answered one fixed string for every cause, so which one it was is not knowable here.',
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {foot(<>user-tier · POST /api/missions/{'{id}'}/steps/{'{idx}'}/finish · charges the mission step budget; exhausting it auto-fails the mission. Mission-level start/pause/resume/complete/cancel live in the MISSIONS panel.</>)}
      </Card>

      <Card
        title="CANVAS SWEEP"
        live={asLive(cd)}
        sub={cd ? `${els.length} elements · ${pinnedTotal} pinned` : null}
        onReload={creload}
      >
        <State e={ce} loading={cl} n={els.length} />

        {!cl && !ce && els.length > 0 && (
          <>
            <Row>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>all agents</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                <Tag>{els.length} total</Tag>
                <Tag c={pinnedTotal > 0 ? AMBER : INK3}>{pinnedTotal} pinned</Tag>
              </span>
            </Row>
            {authors.map((a) => (
              <Row key={a}>
                <span style={{ ...mono, color: INK3 }}>{a}</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                  <Tag>{counts[a].n} total</Tag>
                  <Tag c={counts[a].p > 0 ? AMBER : INK3}>{counts[a].p} pinned</Tag>
                </span>
              </Row>
            ))}
          </>
        )}

        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', paddingTop: 6 }}>
          <select
            style={{ ...inpS }}
            aria-label="sweep scope"
            value={scope}
            onChange={(ev) => rearm(() => setScope(ev.target.value))}
          >
            <option value="">all agents</option>
            {authors.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <label style={{ ...mono, fontSize: 10, color: INK3, display: 'flex', gap: 4, alignItems: 'center' }}>
            <input
              type="checkbox"
              aria-label="keep pinned elements"
              checked={keepPinned}
              onChange={(ev) => rearm(() => setKeepPinned(ev.target.checked))}
            />
            keep pinned
          </label>
          <button
            className="tool-btn"
            aria-label="clear canvas elements in scope"
            disabled={predicted === 0}
            onClick={clear}
          >{armed ? 'confirm clear ' + predicted : 'clear…'}</button>
        </div>

        {predicted === 0
          ? note('nothing matches this scope' + (keepPinned && pinnedTotal > 0 ? ' — pinned elements are kept while "keep pinned" is on' : ''))
          : note(predicted + ' element(s) would match — predicted from the last fetch; the backend\'s returned count is authoritative.')}

        {armed && note('irreversible — there is no undo route. Click again to send the sweep.', AMBER)}

        {removed != null && (
          <div style={{ ...mono, fontSize: 10, color: GREEN, padding: '4px 0' }}>
            {removed === 0 ? 'removed 0 — nothing matched (a real 200, not an error)' : 'removed ' + removed + ' element(s)'}
          </div>
        )}
        {removed != null && removedAt != null && removed !== removedAt && note(
          'predicted ' + removedAt + ' from the last fetch — the canvas changed in between; ' + removed + ' is what the backend removed.',
        )}

        {cErr && (
          <div style={{ ...mono, fontSize: 10, color: RED, display: 'flex', gap: 6, alignItems: 'center', padding: '4px 0' }}>
            <Tag c={RED}>{cErr.status}</Tag>
            <span>sweep refused: {cErr.msg}</span>
          </div>
        )}

        {foot(<>user-tier · POST /api/canvas/clear?agent=&amp;keep_pinned= (query params, no body) · irreversible; pinned elements survive unless keep-pinned is off · reads GET /api/canvas. Element bodies, pin and per-element delete live in the ARTIFACTS panel.</>)}
      </Card>
    </>
  );
}
