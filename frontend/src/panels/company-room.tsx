/* COMPANY ROOM — what the night shift is working on, and what it actually achieved
   (GET /api/company/runs, GET /api/company/runs/{id}, POST /api/company/runs/{id}/stop,
   POST /api/company/runs/{id}/barrier/clear, POST /api/company/runs/{id}/subgoals; all
   user-guarded — and POST /api/company/goals, admin-guarded, H462).

   A work run is one owner-approved goal worked across turns and reboots. This card is
   where the owner sees it — and the whole design problem is that a long-running agent
   looks impressive by default. Forty steps and a spinner reads as progress whether or
   not anything was achieved. So the card is built to make the unflattering facts the
   loudest ones:

   · the backend's `headline` is rendered VERBATIM as the run's status line. It is the
     verdict, not the effort, and this panel never composes its own from step counts;
   · a run that took a step with no approved task behind it renders red, above its own
     achievements, and those runs are also called out at the top of the card;
   · "waiting on your approval" is shown as its own state with a pointer to the inbox,
     because "in progress" is not actionable — and each outstanding ask is listed with
     HOW LONG it has been waiting (GET /api/company/waiting), because "3 waiting" and
     "3 waiting, the oldest since 11pm last night" call for different responses;
   · an ask with no durable task behind it is flagged red: no decision can ever answer
     it, so it would otherwise sit in the list looking like ordinary patience;
   · an empty card prints the backend's own `reason` — "company mode is off" and "no run
     has been opened" are different facts and must never look the same;
   · a run PARKED on real async work (H464: a build, a webhook, a clock) is tagged
     `waiting`, and its headline says what on and until when. "Stop waiting" clears the
     barrier behind a two-step confirm: it grants nothing, it only returns the run to
     the cadence it was already approved for, inside its budget.

   There is deliberately NO start control. Opening a run needs an owner-approved goal,
   which is decided in the inbox like every other privileged act; a start button here
   would be a second, weaker approval path. Stop is offered, because narrowing never
   needs approval — the same shape as revoking a permission.

   H462 — what IS here is a way to ASK: "propose a goal" composes the same text `/goal`
   takes in chat (a headline plus verify / scope / step / must not / stop when lines)
   and sends it to the hub's one front door. The card crosses the Action Kernel and
   waits in the decision inbox; the note says so and names the task. And a live run
   takes an extra acceptance criterion ("add criterion", `/subgoal`): narrowing only,
   it resets nothing, and the run is not done until that criterion holds too — the
   criteria the owner added are listed under the run in the owner's own words.

   NOTE: never spell a route path in this comment unless the panel calls it —
   tests/test_hud_v2_parity.py:_has_caller matches comment text as a caller. */
import React, { useState } from 'react';
import { apiGet } from '../api/client';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, actA, inpS, taS } from '../panel-kit';
import { ConfirmAction, RISK_TIER } from '../confirm';

const RUNS_PATH = '/api/company/runs';
const WAITING_PATH = '/api/company/waiting';
const GOALS_PATH = '/api/company/goals';

const EM = '—';

const Note = ({ c, children }: { c?: any; children?: any }) => (
  <div style={{ fontSize: 10, lineHeight: 1.5, color: c || 'var(--ink-2)', padding: '3px 0 5px' }}>{children}</div>
);

const Head = ({ k }: { k: any }) => (
  <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)', marginTop: 10, marginBottom: 2 }}>{k}</div>
);

/* Status → chip colour. `unknown` is never green: a state this panel does not
   recognise is not evidence that everything is fine. */
const STATUS_COLOR: Record<string, string> = {
  succeeded: 'var(--green)',
  working: 'var(--accent-light)',
  planning: 'var(--accent-light)',
  blocked: 'var(--amber)',
  stopping: 'var(--amber)',
  exhausted: 'var(--amber)',
  stopped: 'var(--ink-2)',
  failed: 'var(--red)',
};

const LIVE_STATES = new Set(['planning', 'working', 'blocked', 'stopping']);

/* Elapsed, in the coarsest unit that is still honest. "2d" and "49h" say the same
   thing; "2d" is the one a person reads at a glance. Never rounds down to "just now":
   an ask that has been waiting rounds UP, because under-reporting the wait is the
   direction that lets it be ignored. */
export const waitedFor = (seconds: number): string => {
  const s = Math.max(0, Number(seconds) || 0);
  if (s < 60) return `${Math.ceil(s)}s`;
  if (s < 3600) return `${Math.ceil(s / 60)}m`;
  if (s < 86400) return `${Math.ceil(s / 3600)}h`;
  return `${Math.ceil(s / 86400)}d`;
};

const refusalText = (err: any) => {
  const reason = err?.body?.reason || err?.body?.error;
  return reason ? `refused · ${String(reason)}` : `refused · ${err?.status || 'error'}`;
};

/* The goal form's fields, in the order the text lists them. Each multi-line field
   becomes one `prefix: value` line per line typed — the same text `/goal` takes. */
export type GoalFields = {
  goal: string; verify: string; scope: string; steps: string; mustNot: string; stopWhen: string;
};
const EMPTY_GOAL: GoalFields = { goal: '', verify: '', scope: '', steps: '', mustNot: '', stopWhen: '' };

const linesOf = (v: string) => String(v || '').split('\n').map((l) => l.trim()).filter(Boolean);

export const composeGoalText = (f: GoalFields): string => {
  const out = [String(f.goal || '').trim()];
  for (const l of linesOf(f.verify)) out.push(`verify: ${l}`);
  if (String(f.scope || '').trim()) out.push(`scope: ${String(f.scope).trim()}`);
  for (const l of linesOf(f.steps)) out.push(`step: ${l}`);
  for (const l of linesOf(f.mustNot)) out.push(`must not: ${l}`);
  for (const l of linesOf(f.stopWhen)) out.push(`stop when: ${l}`);
  return out.filter(Boolean).join('\n');
};

/* A refused proposal says why in the backend's own sentence (`detail`), else its code. */
const proposalRefusal = (err: any) => {
  const detail = err?.body?.detail;
  return typeof detail === 'string' && detail ? `refused · ${detail}` : refusalText(err);
};

const Field = ({ label, children }: { label: string; children?: any }) => (
  <label style={{ display: 'block', fontSize: 10, color: 'var(--ink-2)', marginTop: 6 }}>
    {label}
    <div style={{ marginTop: 2 }}>{children}</div>
  </label>
);

export function CompanyRoomPanel() {
  const { d, e, loading, reload } = useApi(RUNS_PATH);
  const waitingApi = useApi(WAITING_PATH);
  const waiting = arr(waitingApi.d, 'waiting');
  const raw: any = d;
  const runs = arr(raw, 'runs');
  const enabled = !!(raw && raw.enabled);
  const empty = !!(raw && raw.empty);
  const needsYou: string[] = (raw && raw.needs_you) || [];
  const unauthorised: string[] = (raw && raw.unauthorised) || [];
  const [note, setNote] = useState(null);
  const [detail, setDetail] = useState(null);
  const [open, setOpen] = useState(null);
  const [proposing, setProposing] = useState(false);
  const [fields, setFields] = useState<GoalFields>(EMPTY_GOAL);
  const [card, setCard] = useState<string[] | null>(null);
  const [criterion, setCriterion] = useState<Record<string, string>>({});
  const setField = (k: keyof GoalFields) => (ev: any) => setFields({ ...fields, [k]: ev.target.value });

  /* H462 — ask for a goal. Admin-guarded: it reaches the decision inbox, never a run. */
  const propose = () => {
    setNote(null); setCard(null);
    actA(GOALS_PATH, { text: composeGoalText(fields) },
      (r: any) => {
        if (r && r.ok) {
          setNote(`proposed as task ${r.task_id} · decide it in the decision inbox — nothing runs until you accept it there`);
          setCard(Array.isArray(r.card) ? r.card : null);
          setFields(EMPTY_GOAL); setProposing(false);
        } else {
          setNote(`refused · ${(r && (r.detail || r.reason)) || 'proposal failed'}`);
        }
      },
      (err: any) => setNote(proposalRefusal(err)));
  };

  /* H462 — add an acceptance criterion to a live run (`/subgoal`). Narrowing only. */
  const addCriterion = (id: string) => {
    const text = String(criterion[id] || '').trim();
    if (!text) return;
    setNote(null);
    act(`/api/company/runs/${id}/subgoals`, { text },
      (r: any) => {
        setNote(r && r.ok
          ? `criterion ${r.subgoal?.id || ''} added to ${id} · the run goes on where it was`
          : `refused · ${(r && r.reason) || 'criterion not added'}`);
        if (r && r.ok) setCriterion({ ...criterion, [id]: '' });
        reload();
      },
      (err: any) => { setNote(refusalText(err)); reload(); });
  };

  const stop = (id: string) => {
    setNote(null);
    act(`/api/company/runs/${id}/stop`, {},
      (r: any) => {
        setNote(r && r.ok
          ? `stop requested · ${id} is ${String(r.run?.status || 'stopping')}`
          : `refused · ${(r && r.reason) || 'stop failed'}`);
        reload();
      },
      (err: any) => { setNote(refusalText(err)); reload(); });
  };

  /* H464 — let a parked run go. Resolves false on a refusal so the confirm stays
     armed for a retry; the refusal itself reaches the screen either way. */
  const stopWaiting = (id: string) => new Promise<boolean>((resolve) => {
    setNote(null);
    act(`/api/company/runs/${id}/barrier/clear`, {},
      (r: any) => {
        setNote(r && r.ok
          ? (r.cleared ? `${id} is no longer waiting`
            // H464 review F8: `cleared` is what this call did — a newer wait that
            // raced it is named, never reported as "not waiting on anything".
            : r.waiting_on ? `${id} is now waiting on ${r.waiting_on}`
            : `${id} was not waiting on anything`)
          : `refused · ${(r && r.reason) || 'clear failed'}`);
        reload();
        resolve(!!(r && r.ok));
      },
      (err: any) => { setNote(refusalText(err)); reload(); resolve(false); });
  });

  const inspect = (id: string) => {
    if (open === id) { setOpen(null); setDetail(null); return; }
    setOpen(id); setDetail(null);
    apiGet(`/api/company/runs/${id}`)
      .then((body: any) => setDetail(body))
      .catch((err: any) => setNote(refusalText(err)));
  };

  return (
    <Card
      title="COMPANY ROOM"
      live={asLive(d, enabled)}
      sub={raw ? `${runs.length} run(s)` : null}
      onReload={reload}
    >
      <State e={e} loading={loading} n={d ? 1 : 0} />
      <Row>
        <span style={{ ...mono, fontSize: 10, color: 'var(--ink-2)' }}>PROPOSE A GOAL</span>
        <button
          className="tool-btn" style={{ marginLeft: 'auto' }}
          title="write a goal and send it to the decision inbox for your approval"
          onClick={() => setProposing(!proposing)}
        >{proposing ? 'close' : 'propose a goal'}</button>
      </Row>
      {proposing && (
        <div style={{ padding: '4px 0 8px' }}>
          <Field label="goal — what you want done">
            <input aria-label="goal" style={{ ...inpS, width: '100%' }} value={fields.goal} onChange={setField('goal')} />
          </Field>
          <Field label="verify — how anyone would know it is done (one per line)">
            <textarea aria-label="verify" style={{ ...taS, minHeight: 40 }} value={fields.verify} onChange={setField('verify')} />
          </Field>
          <Field label="scope — step kinds it may use, e.g. research, write — or unrestricted">
            <input aria-label="scope" style={{ ...inpS, width: '100%' }} value={fields.scope} onChange={setField('scope')} />
          </Field>
          <Field label="steps — the plan you approve, one per line as kind: what">
            <textarea aria-label="steps" style={{ ...taS, minHeight: 40 }} value={fields.steps} onChange={setField('steps')} />
          </Field>
          <Field label="must not — constraints (one per line)">
            <textarea aria-label="must not" style={{ ...taS, minHeight: 32 }} value={fields.mustNot} onChange={setField('mustNot')} />
          </Field>
          <Field label="stop when — when to give up (one per line)">
            <textarea aria-label="stop when" style={{ ...taS, minHeight: 32 }} value={fields.stopWhen} onChange={setField('stopWhen')} />
          </Field>
          <Row>
            <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>
              20 steps, a day to run; it waits in the decision inbox until you accept it.
            </span>
            <button
              className="tool-btn" style={{ marginLeft: 'auto' }}
              title="send this goal to the decision inbox"
              disabled={!fields.goal.trim()}
              onClick={propose}
            >send for approval</button>
          </Row>
        </div>
      )}
      {card && card.length > 0 && (
        <>
          <Head k="PROPOSED — WAITING IN THE INBOX" />
          {card.map((line, i) => <Note key={i}>{line}</Note>)}
        </>
      )}
      {raw && empty && (
        <Note c="var(--ink-2)">{String(raw.reason || 'nothing to report')}.</Note>
      )}
      {raw && !empty && (
        <>
          {/* Above every success: the one finding that changes what to do next. */}
          {unauthorised.length > 0 && (
            <Row>
              <span style={{ ...mono, color: 'var(--red)' }} role="alert">
                {unauthorised.length} run(s) changed something with no approved task
              </span>
            </Row>
          )}
          {needsYou.length > 0 && (
            <Row>
              <span style={{ ...mono, color: 'var(--amber)' }}>
                {needsYou.length} run(s) waiting on your approval — decide them in the inbox
              </span>
            </Row>
          )}

          {/* What each of those runs is actually waiting on, oldest first. A count
              alone leaves the reader to work out the urgency. */}
          {waiting.length > 0 && (
            <>
              <Head k="WAITING ON YOU" />
              {waiting.map((ask: any) => (
                <Row key={`${ask.run_id}:${ask.step_seq}`}>
                  <span style={{ fontSize: 11 }}>{ask.summary || ask.kind || EM}</span>
                  <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                    <Tag c="var(--amber)">{waitedFor(ask.waiting_seconds)}</Tag>
                    {/* No durable task means no decision can ever answer this ask. */}
                    <Tag c={ask.answerable ? 'var(--ink-2)' : 'var(--red)'}>
                      {ask.answerable ? `task ${ask.task_id}` : 'no task to decide'}
                    </Tag>
                  </span>
                </Row>
              ))}
            </>
          )}

          {runs.map((run: any) => {
            const bad = (run.unauthorised_steps || []).length > 0;
            const live = LIVE_STATES.has(String(run.status));
            return (
              <div key={run.run_id} style={{ padding: '4px 0' }}>
                <Row>
                  <span style={{ fontSize: 12, color: bad ? 'var(--red)' : 'var(--ink-1)' }}>
                    {run.title || EM}
                  </span>
                  <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                    <Tag c={STATUS_COLOR[String(run.status)] || 'var(--ink-2)'}>
                      {run.status || 'unknown'}
                    </Tag>
                    {run.waiting_on && <Tag c="var(--amber)">waiting</Tag>}
                    <Tag>{run.steps ?? 0} step(s)</Tag>
                    <button
                      className="tool-btn" title="show this run's steps and verdicts"
                      onClick={() => inspect(run.run_id)}
                    >{open === run.run_id ? 'hide' : 'steps'}</button>
                    {live && run.waiting_on && (
                      <ConfirmAction
                        tier={RISK_TIER.REVERSIBLE} label="stop waiting"
                        title={`stop waiting on ${run.waiting_on}`}
                        onConfirm={() => stopWaiting(run.run_id)}
                      />
                    )}
                    {live && (
                      <button
                        className="tool-btn" title="stop this run"
                        onClick={() => stop(run.run_id)}
                      >stop</button>
                    )}
                  </span>
                </Row>
                {/* The backend's sentence, verbatim: the verdict, not the effort. */}
                <Note c={bad ? 'var(--red)' : 'var(--ink-2)'}>{run.headline}</Note>
                {(run.verdict_lines || []).map((line: string, i: number) => (
                  <Note key={i}>{line}</Note>
                ))}
                {(run.subgoals || []).length > 0 && (
                  <Note>
                    criteria you added: {(run.subgoals || []).map((s: string) => `“${s}”`).join(' · ')}
                  </Note>
                )}
                {live && run.status !== 'stopping' && (
                  <Row>
                    <input
                      aria-label={`criterion for ${run.run_id}`}
                      placeholder="add an acceptance criterion (it resets nothing)"
                      style={{ ...inpS, flex: 1 }}
                      value={criterion[run.run_id] || ''}
                      onChange={(ev: any) => setCriterion({ ...criterion, [run.run_id]: ev.target.value })}
                    />
                    <button
                      className="tool-btn" title="add this criterion to the running goal"
                      disabled={!String(criterion[run.run_id] || '').trim()}
                      onClick={() => addCriterion(run.run_id)}
                    >add criterion</button>
                  </Row>
                )}
                {open === run.run_id && detail && detail.steps && (
                  <>
                    <Head k="STEPS" />
                    {detail.steps.map((step: any) => (
                      <Row key={step.seq}>
                        <span style={{ ...mono, fontSize: 10, color: 'var(--ink-2)' }}>
                          {step.seq}
                        </span>
                        <span style={{ fontSize: 11 }}>{step.summary}</span>
                        <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
                          <Tag c={step.outcome === 'failed' ? 'var(--red)' : undefined}>
                            {step.outcome}
                          </Tag>
                          {/* No task id means nothing authorised this step. Say it. */}
                          <Tag c={step.task_id ? 'var(--ink-2)' : 'var(--red)'}>
                            {step.task_id ? `task ${step.task_id}` : 'no approved task'}
                          </Tag>
                        </span>
                      </Row>
                    ))}
                  </>
                )}
              </div>
            );
          })}
        </>
      )}
      {note && (
        <div role="alert" style={{ ...mono, marginTop: 6, color: note.startsWith('refused') ? 'var(--red)' : 'var(--green)' }}>
          {note}
        </div>
      )}
      <Note>
        A run works one <b>owner-approved</b> goal across turns and reboots. Every action it
        takes still enters the approval queue, and only the graders can call a run
        successful — this card never composes a verdict of its own. There is no start
        control on purpose: proposing a goal only asks, and a goal is approved in the
        decision inbox, like everything else.
      </Note>
    </Card>
  );
}

export default CompanyRoomPanel;
