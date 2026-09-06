/* COMPANY ROOM — what the night shift is working on, and what it actually achieved
   (GET /api/company/runs, GET /api/company/runs/{id}, POST /api/company/runs/{id}/stop;
   all user-guarded).

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
     because "in progress" is not actionable;
   · an empty card prints the backend's own `reason` — "company mode is off" and "no run
     has been opened" are different facts and must never look the same.

   There is deliberately NO start control. Opening a run needs an owner-approved goal,
   which is decided in the inbox like every other privileged act; a start button here
   would be a second, weaker approval path. Stop is offered, because narrowing never
   needs approval — the same shape as revoking a permission.

   NOTE: never spell a route path in this comment unless the panel calls it —
   tests/test_hud_v2_parity.py:_has_caller matches comment text as a caller. */
import React, { useState } from 'react';
import { apiGet } from '../api/client';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act } from '../panel-kit';

const RUNS_PATH = '/api/company/runs';

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
  stopped: 'var(--ink-3)',
  failed: 'var(--red)',
};

const LIVE_STATES = new Set(['planning', 'working', 'blocked', 'stopping']);

const refusalText = (err: any) => {
  const reason = err?.body?.reason || err?.body?.error;
  return reason ? `refused · ${String(reason)}` : `refused · ${err?.status || 'error'}`;
};

export function CompanyRoomPanel() {
  const { d, e, loading, reload } = useApi(RUNS_PATH);
  const raw: any = d;
  const runs = arr(raw, 'runs');
  const enabled = !!(raw && raw.enabled);
  const empty = !!(raw && raw.empty);
  const needsYou: string[] = (raw && raw.needs_you) || [];
  const unauthorised: string[] = (raw && raw.unauthorised) || [];
  const [note, setNote] = useState(null);
  const [detail, setDetail] = useState(null);
  const [open, setOpen] = useState(null);

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
                    <Tag c={STATUS_COLOR[String(run.status)] || 'var(--ink-3)'}>
                      {run.status || 'unknown'}
                    </Tag>
                    <Tag>{run.steps ?? 0} step(s)</Tag>
                    <button
                      className="tool-btn" title="show this run's steps and verdicts"
                      onClick={() => inspect(run.run_id)}
                    >{open === run.run_id ? 'hide' : 'steps'}</button>
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
                          <Tag c={step.task_id ? 'var(--ink-3)' : 'var(--red)'}>
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
        control on purpose: a goal is approved in the decision inbox, like everything else.
      </Note>
    </Card>
  );
}

export default CompanyRoomPanel;
