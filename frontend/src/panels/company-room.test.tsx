// @ts-nocheck
/* COMPANY ROOM panel — `fetch` is mocked (not api/client) so the REAL client path runs:
   apiPost THROWS on 4xx, so a refusal branch that is never wired would be dead code here.

   A long-running agent looks impressive by default, so the claims pinned are all about
   the panel refusing to flatter it:

   · the backend's `headline` is rendered verbatim — the panel never composes a verdict
     from step counts, so forty steps and no verdict cannot read as achievement;
   · an unauthorised run is called out at the top AND rendered red on its own row;
   · a step with no task id says "no approved task" in red, not a blank cell;
   · "company mode is off" and "no run has been opened" render as different sentences;
   · there is NO start control — only stop, which needs no approval; "propose a goal"
     (H462) only asks, through the admin route, and the run opens in the inbox;
   · a refused stop reaches the screen instead of reading as success;
   · an outstanding ask says HOW LONG it has waited, because "3 waiting" and "3 waiting,
     the oldest since 11pm" call for different responses;
   · an ask with no durable task is flagged red — no decision can ever answer it, so it
     would otherwise sit in the list looking like ordinary patience. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CompanyRoomPanel, waitedFor, composeGoalText } from './company-room';

const RUN = {
  run_id: 'run-1',
  title: 'Prepare the quarterly brief',
  status: 'working',
  headline: 'in progress',
  steps: 40,
  outcomes: { ok: 40 },
  steps_left: 10,
  interrupts_used: 0,
  unauthorised_steps: [],
  verdict_lines: ['· nobody has graded it yet'],
  recent: [{ summary: 'drafted the summary', outcome: 'ok', task_id: 12 }],
};

const BRIEF = {
  schema: 'nerva.company.brief.v1',
  enabled: true,
  empty: false,
  reason: '',
  counts: { runs: 1, by_status: { working: 1 } },
  needs_you: [],
  unauthorised: [],
  runs: [RUN],
};

const DETAIL = {
  ok: true,
  enabled: true,
  run: { id: 'run-1', title: 'Prepare the quarterly brief', status: 'working' },
  budget: { steps_used: 2, steps_left: 10, exceeded: null },
  steps: [
    { seq: 1, summary: 'read the numbers', outcome: 'ok', task_id: 11 },
    { seq: 2, summary: 'wrote a file', outcome: 'ok', task_id: null },
  ],
  verdicts: [],
  tampered: false,
  unauthorised_steps: [2],
};

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });
const refuse = (status, payload) => ({ ok: false, status, json: async () => payload });

/* route-keyed, most-specific first (String(url).includes) */
function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve(hit ? hit[1] : ok({}));
  });
  global.fetch = fn;
  return fn;
}

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('CompanyRoomPanel — the night shift, reported without flattery', () => {
  it('renders the backend headline verbatim rather than composing one from step counts', async () => {
    mockFetch({ '/api/company/runs': ok(BRIEF) });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText('Prepare the quarterly brief')).toBeTruthy());
    // 40 steps, no verdict — and the card says exactly that, not "40 steps completed"
    expect(screen.getByText('in progress')).toBeTruthy();
    expect(screen.getByText('· nobody has graded it yet')).toBeTruthy();
    expect(screen.queryByText(/completed/i)).toBeNull();
  });

  it('calls out unauthorised runs above everything and renders them red', async () => {
    mockFetch({
      '/api/company/runs': ok({
        ...BRIEF,
        unauthorised: ['run-1'],
        runs: [{
          ...RUN,
          status: 'succeeded',
          unauthorised_steps: [3],
          headline: '1 step changed something without an approved task behind it',
        }],
      }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(
      screen.getByText(/1 run\(s\) changed something with no approved task/)).toBeTruthy());
    // and the run's own line is the unflattering one, not "met its goal"
    expect(screen.getByText(/1 step changed something without an approved task/)).toBeTruthy();
  });

  it('points a blocked run at the inbox rather than calling it in progress', async () => {
    mockFetch({
      '/api/company/runs': ok({
        ...BRIEF,
        needs_you: ['run-1'],
        runs: [{ ...RUN, status: 'blocked', headline: 'waiting on your approval' }],
      }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(
      screen.getByText(/waiting on your approval — decide them in the inbox/)).toBeTruthy());
  });

  it('distinguishes "company mode is off" from "nothing has run"', async () => {
    mockFetch({
      '/api/company/runs': ok({
        ...BRIEF, enabled: false, empty: true, runs: [], counts: { runs: 0, by_status: {} },
        reason: 'company mode is off, so no run was opened',
      }),
    });
    const { unmount } = render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText(/company mode is off/)).toBeTruthy());
    unmount();

    mockFetch({
      '/api/company/runs': ok({
        ...BRIEF, enabled: true, empty: true, runs: [], counts: { runs: 0, by_status: {} },
        reason: 'no work runs have been opened',
      }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText(/no work runs have been opened/)).toBeTruthy());
  });

  it('shows a step with no task id as "no approved task", not as a blank', async () => {
    mockFetch({
      '/api/company/runs/run-1': ok(DETAIL),
      '/api/company/runs': ok(BRIEF),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByTitle(/show this run/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/show this run/));
    await waitFor(() => expect(screen.getByText('read the numbers')).toBeTruthy());
    expect(screen.getByText('task 11')).toBeTruthy();
    expect(screen.getByText('no approved task')).toBeTruthy();
  });

  it('offers no way to start a run', async () => {
    mockFetch({ '/api/company/runs': ok(BRIEF) });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText('Prepare the quarterly brief')).toBeTruthy());
    expect(screen.queryByText(/^start$/i)).toBeNull();
    expect(screen.queryByTitle(/start/i)).toBeNull();
    expect(screen.getByText(/no start control on purpose/)).toBeTruthy();
  });

  it('stops a live run and reports the status the backend read back', async () => {
    const fn = mockFetch({
      '/stop': ok({ ok: true, run: { id: 'run-1', status: 'stopping' } }),
      '/api/company/runs': ok(BRIEF),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByTitle(/stop this run/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/stop this run/));
    await waitFor(() => {
      const call = fn.mock.calls.find((c) => String(c[0]) === '/api/company/runs/run-1/stop');
      expect(call).toBeTruthy();
      expect(call[1].method).toBe('POST');
    });
    await waitFor(() => expect(screen.getByText(/run-1 is stopping/)).toBeTruthy());
  });

  it('offers no stop on a finished run', async () => {
    mockFetch({
      '/api/company/runs': ok({
        ...BRIEF, runs: [{ ...RUN, status: 'succeeded', headline: 'met its goal' }],
      }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText('met its goal')).toBeTruthy());
    expect(screen.queryByTitle(/stop this run/)).toBeNull();
  });

  it('surfaces a refused stop instead of reading as success', async () => {
    mockFetch({
      '/stop': refuse(409, { ok: false, reason: 'run_stopped' }),
      '/api/company/runs': ok(BRIEF),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByTitle(/stop this run/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/stop this run/));
    // apiPost rejects on the 409 — this only renders because stop() passes an onErr
    await waitFor(() => expect(screen.getByText(/refused · run_stopped/)).toBeTruthy());
  });

  /* ── what each blocked run is actually waiting on ────────────────────── */

  const WAITING = {
    ok: true,
    enabled: true,
    count: 2,
    oldest_seconds: 46_800,
    waiting: [
      {
        run_id: 'run-1', step_seq: 4, kind: 'writeback', summary: 'update the quarterly doc',
        task_id: 12, waiting_seconds: 46_800, answerable: true,
      },
      {
        run_id: 'run-1', step_seq: 5, kind: 'social.post', summary: 'post the summary',
        task_id: null, waiting_seconds: 120, answerable: false,
      },
    ],
  };

  it('says how long each ask has been waiting, not just how many there are', async () => {
    mockFetch({
      '/api/company/waiting': ok(WAITING),
      '/api/company/runs': ok({
        ...BRIEF, needs_you: ['run-1'],
        runs: [{ ...RUN, status: 'blocked', headline: 'waiting on your approval' }],
      }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText('update the quarterly doc')).toBeTruthy());
    expect(screen.getByText('13h')).toBeTruthy();   // 46_800s, rounded up
    expect(screen.getByText('task 12')).toBeTruthy();
  });

  it('flags an ask no decision can ever answer', async () => {
    mockFetch({
      '/api/company/waiting': ok(WAITING),
      '/api/company/runs': ok({
        ...BRIEF, needs_you: ['run-1'],
        runs: [{ ...RUN, status: 'blocked', headline: 'waiting on your approval' }],
      }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText('no task to decide')).toBeTruthy());
  });

  it('renders nothing extra when nothing is outstanding', async () => {
    mockFetch({
      '/api/company/waiting': ok({ ok: true, enabled: true, count: 0, waiting: [], oldest_seconds: 0 }),
      '/api/company/runs': ok(BRIEF),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText('in progress')).toBeTruthy());
    expect(screen.queryByText('WAITING ON YOU')).toBeNull();
  });

  it('rounds an elapsed wait UP, because under-reporting it lets it be ignored', () => {
    expect(waitedFor(0)).toBe('0s');
    expect(waitedFor(1)).toBe('1s');
    expect(waitedFor(61)).toBe('2m');
    expect(waitedFor(3_601)).toBe('2h');
    expect(waitedFor(86_401)).toBe('2d');
    expect(waitedFor(-5)).toBe('0s');
    expect(waitedFor(undefined)).toBe('0s');
  });

  /* ── H464: a run parked on real async work ─────────────────────────────── */

  const PARKED = {
    ...RUN,
    headline: 'parked — waiting on task 412 to finish (at most until 14:00)',
    waiting_on: 'task 412 to finish',
  };

  it('tags a parked run as waiting and lets the owner stop the wait, after a confirm', async () => {
    const fn = mockFetch({
      '/barrier/clear': ok({ ok: true, cleared: true, run: { id: 'run-1', status: 'working', barrier: null } }),
      '/api/company/runs': ok({ ...BRIEF, runs: [PARKED], parked: ['run-1'] }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText(/parked — waiting on task 412/)).toBeTruthy());
    expect(screen.getByText('waiting')).toBeTruthy();
    fireEvent.click(screen.getByTitle(/stop waiting/));
    // two-step: arming alone posts nothing
    expect(fn.mock.calls.find((c) => String(c[0]).includes('/barrier/clear'))).toBeFalsy();
    fireEvent.click(screen.getByText(/confirm stop waiting/));
    await waitFor(() => {
      const call = fn.mock.calls.find((c) => String(c[0]) === '/api/company/runs/run-1/barrier/clear');
      expect(call).toBeTruthy();
      expect(call[1].method).toBe('POST');
    });
    await waitFor(() => expect(screen.getByText(/run-1 is no longer waiting/)).toBeTruthy());
  });

  it('says so when there was nothing to stop waiting on', async () => {
    mockFetch({
      '/barrier/clear': ok({ ok: true, cleared: false, run: { id: 'run-1' } }),
      '/api/company/runs': ok({ ...BRIEF, runs: [PARKED] }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByTitle(/stop waiting/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/stop waiting/));
    fireEvent.click(screen.getByText(/confirm stop waiting/));
    await waitFor(() => expect(screen.getByText(/run-1 was not waiting on anything/)).toBeTruthy());
  });

  it('says what the run waits on now when a new wait raced the clear', async () => {
    // H464 review F8: this call cleared nothing because a new barrier was set in
    // between; "was not waiting on anything" would be false while it is parked.
    mockFetch({
      '/barrier/clear': ok({ ok: true, cleared: false, waiting_on: 'task 8 to finish', run: { id: 'run-1' } }),
      '/api/company/runs': ok({ ...BRIEF, runs: [PARKED] }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByTitle(/stop waiting/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/stop waiting/));
    fireEvent.click(screen.getByText(/confirm stop waiting/));
    await waitFor(() => expect(screen.getByText(/run-1 is now waiting on task 8 to finish/)).toBeTruthy());
    expect(screen.queryByText(/was not waiting on anything/)).toBeNull();
  });

  it('surfaces a refused clear instead of reading as success', async () => {
    mockFetch({
      '/barrier/clear': refuse(404, { ok: false, reason: 'unknown_run' }),
      '/api/company/runs': ok({ ...BRIEF, runs: [PARKED] }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByTitle(/stop waiting/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/stop waiting/));
    fireEvent.click(screen.getByText(/confirm stop waiting/));
    await waitFor(() => expect(screen.getByText(/refused · unknown_run/)).toBeTruthy());
  });

  it('offers no waiting tag and no stop-waiting control on a run that is not parked', async () => {
    mockFetch({ '/api/company/runs': ok(BRIEF) });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText('in progress')).toBeTruthy());
    expect(screen.queryByText('waiting')).toBeNull();
    expect(screen.queryByTitle(/stop waiting/)).toBeNull();
  });
});

/* H462 — the owner can ASK for a goal here; the run still opens only in the inbox. */
describe('CompanyRoomPanel — proposing a goal and adding a criterion (H462)', () => {
  it('composes the same text /goal takes, one prefixed line per line typed', () => {
    expect(composeGoalText({
      goal: '  Prepare the quarterly brief ', verify: 'the brief is in docs/\n\n a reviewer signs it ',
      scope: 'research, write', steps: 'research: read the Q3 figures', mustNot: 'touch the ledger',
      stopWhen: 'the figures are missing',
    })).toBe([
      'Prepare the quarterly brief',
      'verify: the brief is in docs/',
      'verify: a reviewer signs it',
      'scope: research, write',
      'step: research: read the Q3 figures',
      'must not: touch the ledger',
      'stop when: the figures are missing',
    ].join('\n'));
  });

  it('sends a proposal to the admin route and says it waits in the inbox, opening nothing', async () => {
    localStorage.setItem('hud.admin_token', 'owner-token');
    const fn = mockFetch({
      '/api/company/goals': ok({ ok: true, task_id: 12, title: 'Prepare the brief',
        card: ['goal: Prepare the brief', 'scope: research'] }),
      '/api/company/runs': ok(BRIEF),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText('Prepare the quarterly brief')).toBeTruthy());
    fireEvent.click(screen.getByText('propose a goal'));
    fireEvent.change(screen.getByLabelText('goal'), { target: { value: 'Prepare the brief' } });
    fireEvent.change(screen.getByLabelText('scope'), { target: { value: 'research' } });
    fireEvent.change(screen.getByLabelText('verify'), { target: { value: 'the brief is in docs/' } });
    fireEvent.click(screen.getByText('send for approval'));
    await waitFor(() => expect(screen.getByText(/proposed as task 12/)).toBeTruthy());
    const call = fn.mock.calls.find((c) => String(c[0]) === '/api/company/goals');
    expect(call[1].method).toBe('POST');
    expect(call[1].headers['X-Admin-Token']).toBe('owner-token');
    expect(JSON.parse(call[1].body)).toEqual({
      text: 'Prepare the brief\nverify: the brief is in docs/\nscope: research',
    });
    expect(screen.getByText(/nothing runs until you accept it there/)).toBeTruthy();
    expect(screen.getByText('scope: research')).toBeTruthy();
    // Proposing never reaches a run route: no stop, no start, no clear.
    expect(fn.mock.calls.some((c) => /\/(stop|start|barrier)/.test(String(c[0])))).toBe(false);
  });

  it("surfaces a refused proposal in the backend's own sentence", async () => {
    mockFetch({
      '/api/company/goals': refuse(400, { ok: false, reason: 'scope_required_or_declare_unrestricted',
        detail: 'say what the run may do: a `scope:` line naming step kinds' }),
      '/api/company/runs': ok(BRIEF),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText('propose a goal')).toBeTruthy());
    fireEvent.click(screen.getByText('propose a goal'));
    fireEvent.change(screen.getByLabelText('goal'), { target: { value: 'Prepare it' } });
    fireEvent.click(screen.getByText('send for approval'));
    await waitFor(() => expect(screen.getByText(/refused · say what the run may do/)).toBeTruthy());
  });

  it('adds a criterion to a live run without stopping it', async () => {
    const fn = mockFetch({
      '/subgoals': ok({ ok: true, subgoal: { id: 'subgoal:1', describe: 'the brief has a summary' },
        subgoals: [] }),
      '/api/company/runs': ok(BRIEF),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByLabelText('criterion for run-1')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('criterion for run-1'),
      { target: { value: 'the brief has a summary' } });
    fireEvent.click(screen.getByText('add criterion'));
    await waitFor(() => expect(screen.getByText(/criterion subgoal:1 added to run-1/)).toBeTruthy());
    const call = fn.mock.calls.find((c) => String(c[0]) === '/api/company/runs/run-1/subgoals');
    expect(call[1].method).toBe('POST');
    expect(JSON.parse(call[1].body)).toEqual({ text: 'the brief has a summary' });
    expect(fn.mock.calls.some((c) => String(c[0]).endsWith('/stop'))).toBe(false);
  });

  it('surfaces a refused criterion instead of reading as success', async () => {
    mockFetch({
      '/subgoals': refuse(409, { ok: false, reason: 'run_already_graded' }),
      '/api/company/runs': ok(BRIEF),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByLabelText('criterion for run-1')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('criterion for run-1'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('add criterion'));
    await waitFor(() => expect(screen.getByText(/refused · run_already_graded/)).toBeTruthy());
  });

  it("lists the criteria the owner added in the owner's words, and offers none on a finished run", async () => {
    mockFetch({
      '/api/company/runs': ok({ ...BRIEF, runs: [
        { ...RUN, subgoals: ['the brief has a summary'] },
        { ...RUN, run_id: 'run-2', title: 'Done already', status: 'succeeded', headline: 'met its goal' },
      ] }),
    });
    render(<CompanyRoomPanel />);
    await waitFor(() => expect(screen.getByText(/criteria you added: “the brief has a summary”/)).toBeTruthy());
    expect(screen.getByLabelText('criterion for run-1')).toBeTruthy();
    expect(screen.queryByLabelText('criterion for run-2')).toBeNull();
  });
});
