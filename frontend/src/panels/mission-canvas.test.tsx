// @ts-nocheck
/* MISSION & CANVAS panel — `fetch` is mocked (not the api/client module) so the REAL client
   path runs. That matters: apiPost THROWS on 4xx/5xx, so a `.then`-only call site would make
   every refusal branch dead code, and these tests would be asserting against markup that can
   never appear in production.

   The claims this file exists to pin:
   · the finish URL is composed from the mission id and the step index the operator actually
     picked — '/api/missions/7/steps/2/finish' — and never from a placeholder;
   · a null `elapsed_seconds` reads "elapsed: not started", never 0;
   · 409 {"error":"mission step budget exhausted","budget_exceeded":true} reaches the screen
     VERBATIM, carries the backend's side effect (the step WAS recorded, the mission WAS
     auto-failed) and leaves no success line behind it;
   · the generic 409 is rendered verbatim and the panel does NOT name which of its three
     collapsed causes fired;
   · 503 "missions not available" is rendered verbatim;
   · an empty {"missions": []} is drawn as the ambiguity it is, never as a clean "nothing yet";
   · the canvas sweep sends its scope as QUERY PARAMS with NO request body (a JSON body is
     ignored by FastAPI and the defaults would sweep everything), and needs two clicks;
   · a mission that is NOT active is routed only to a control that exists: planned → start,
     paused → resume, and for the three TERMINAL statuses (done/failed/cancelled, whose exit set
     in `_TRANSITIONS` is empty and for which gap.tsx MissionsPanel renders no button) the panel
     names no control at all. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MissionCanvasPanel } from './mission-canvas';

const step = (idx, title, status = 'pending', extra = {}) => ({
  idx, title, status, result: null, started_at: null, ended_at: null, ...extra,
});

const MISSION = (over = {}) => ({
  id: 7,
  title: 'ship the sweep',
  goal: 'g',
  status: 'active',
  plan: [step(0, 'read the handler', 'done'), step(1, 'draft', 'running'), step(2, 'validate')],
  max_steps: 20,
  max_seconds: 3600,
  steps_used: 2,
  started_at: null,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
  ...over,
});

const CANVAS = {
  status: 200,
  body: {
    elements: [
      { id: 'a1', agent: 'vision', type: 'markdown', payload: {}, pinned: false, created_at: 3 },
      { id: 'a2', agent: 'vision', type: 'markdown', payload: {}, pinned: true, created_at: 2 },
      { id: 'a3', agent: 'scout', type: 'table', payload: {}, pinned: false, created_at: 1 },
    ],
  },
};

/* Exact-path router. An array value is a queue: successive fetches of the same path get the
   next entry (the last one repeats), which is how a reload-after-refusal is modelled. */
function mockRoutes(map) {
  const fn = vi.fn(async (url) => {
    const k = String(url);
    let res = map[k];
    if (Array.isArray(res)) res = res.length > 1 ? res.shift() : res[0];
    if (!res) throw new Error('unexpected fetch ' + k);
    const status = res.status || 200;
    return { ok: status < 400, status, json: async () => res.body };
  });
  global.fetch = fn;
  return fn;
}

const callsTo = (fn, path) => fn.mock.calls.filter((c) => String(c[0]) === path);
const spans = () => Array.from(document.querySelectorAll('span,div')).map((el) => el.textContent || '');
const hasText = (re) => spans().some((t) => re.test(t));
const exactSpan = (s) => Array.from(document.querySelectorAll('span')).some((el) => el.textContent === s);

/* The one amber line the expanded card prints for a non-active mission, isolated from its
   containers: every ancestor div's textContent starts with it too, so the SHORTEST match is
   the note element itself. Asserted with toBe, not a substring — the pre-fix text
   ("… — start or resume it from the MISSIONS panel.") contains the paused wording as a
   substring, so a loose matcher would pin nothing. */
const hint = () => {
  const texts = Array.from(document.querySelectorAll('div'))
    .map((n) => n.textContent || '')
    .filter((t) => t.indexOf('finish_step runs only while the mission is active') === 0)
    .sort((a, b) => a.length - b.length);
  return texts.length ? texts[0] : null;
};
const TERMINAL_HINT = (st) => 'finish_step runs only while the mission is active (this one is '
  + st + '). ' + st + ' is terminal — the mission state machine has no transition out of done, '
  + 'failed or cancelled, so nothing can put this mission back to active and these steps can no '
  + 'longer be finished.';

const openSteps = async () => {
  await waitFor(() => expect(screen.getByLabelText('steps of mission 7')).toBeTruthy());
  fireEvent.click(screen.getByLabelText('steps of mission 7'));
};

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  vi.restoreAllMocks();
});

describe('MissionCanvasPanel · finishing a step', () => {
  it('POSTs the composed URL with {status} and renders the budget, with a null elapsed as "not started"', async () => {
    const fn = mockRoutes({
      '/api/missions': { status: 200, body: { missions: [MISSION()] } },
      '/api/canvas': CANVAS,
      '/api/missions/7/steps/2/finish': {
        status: 200,
        body: {
          ok: true,
          mission: MISSION({
            steps_used: 3,
            plan: [step(0, 'read the handler', 'done'), step(1, 'draft', 'running'), step(2, 'validate', 'done', { ended_at: '2026-09-01T11:00:00Z' })],
            budget: { max_steps: 20, steps_used: 3, steps_remaining: 17, max_seconds: 3600, elapsed_seconds: null, over_time: false },
          }),
        },
      },
    });
    render(<MissionCanvasPanel />);
    await openSteps();

    fireEvent.click(screen.getByLabelText('done step 2 of mission 7'));

    await waitFor(() => expect(callsTo(fn, '/api/missions/7/steps/2/finish').length).toBe(1));
    const init = callsTo(fn, '/api/missions/7/steps/2/finish')[0][1];
    expect(init.method).toBe('POST');
    // `result` is OMITTED when the note is blank so the handler's None default applies.
    expect(JSON.parse(init.body)).toEqual({ status: 'done' });

    await waitFor(() => expect(
      exactSpan('step #2 → done · budget 3/20 used, 17 left · elapsed: not started'),
    ).toBe(true));
    // a null elapsed is never drawn as a zero
    expect(hasText(/elapsed: 0/)).toBe(false);
  });

  it('sends the operator note as `result` when one was typed', async () => {
    const fn = mockRoutes({
      '/api/missions': { status: 200, body: { missions: [MISSION()] } },
      '/api/canvas': CANVAS,
      '/api/missions/7/steps/1/finish': {
        status: 200,
        body: { ok: true, mission: MISSION({ budget: { max_steps: 20, steps_used: 3, steps_remaining: 17, max_seconds: 3600, elapsed_seconds: 12.5, over_time: false } }) },
      },
    });
    render(<MissionCanvasPanel />);
    await openSteps();

    fireEvent.change(screen.getByLabelText('result note for step 1 of mission 7'), { target: { value: '  bench was flat  ' } });
    fireEvent.click(screen.getByLabelText('failed step 1 of mission 7'));

    await waitFor(() => expect(callsTo(fn, '/api/missions/7/steps/1/finish').length).toBe(1));
    expect(JSON.parse(callsTo(fn, '/api/missions/7/steps/1/finish')[0][1].body))
      .toEqual({ status: 'failed', result: 'bench was flat' });
  });
});

describe('MissionCanvasPanel · refusals reach the screen as refusals', () => {
  it('renders the budget 409 verbatim AND its side effect, with no success line', async () => {
    const fn = mockRoutes({
      // the reload on the error branch sees the mission the backend already auto-failed
      '/api/missions': [
        { status: 200, body: { missions: [MISSION()] } },
        { status: 200, body: { missions: [MISSION({ status: 'failed', steps_used: 20 })] } },
      ],
      '/api/canvas': CANVAS,
      '/api/missions/7/steps/2/finish': {
        status: 409,
        body: { error: 'mission step budget exhausted', budget_exceeded: true },
      },
    });
    render(<MissionCanvasPanel />);
    await openSteps();
    fireEvent.click(screen.getByLabelText('done step 2 of mission 7'));

    await waitFor(() => expect(exactSpan('step #2 refused: mission step budget exhausted')).toBe(true));
    expect(screen.getByText('409')).toBeTruthy();
    // the backend already wrote the step and failed the mission before it raised
    expect(hasText(/the step WAS recorded and the mission was auto-failed by the backend/)).toBe(true);
    expect(hasText(/There is nothing to retry/)).toBe(true);
    // no success block, and the panel does not offer the three-causes caveat here
    expect(hasText(/budget \d+\/\d+ used/)).toBe(false);
    expect(hasText(/does not disclose which/)).toBe(false);
    // the reload really happened, so the refreshed status is what is on screen
    await waitFor(() => expect(callsTo(fn, '/api/missions').length).toBe(2));
    await waitFor(() => expect(exactSpan('failed')).toBe(true));
  });

  it('renders the generic 409 verbatim and names none of its three collapsed causes', async () => {
    mockRoutes({
      '/api/missions': { status: 200, body: { missions: [MISSION()] } },
      '/api/canvas': CANVAS,
      '/api/missions/7/steps/2/finish': {
        status: 409,
        body: { error: 'operation not allowed in current mission state' },
      },
    });
    render(<MissionCanvasPanel />);
    await openSteps();
    fireEvent.click(screen.getByLabelText('done step 2 of mission 7'));

    await waitFor(() => expect(
      exactSpan('step #2 refused: operation not allowed in current mission state'),
    ).toBe(true));
    expect(hasText(/does not disclose which/)).toBe(true);
    // it must not assert a cause the router deliberately discarded
    expect(hasText(/step index is out of range/)).toBe(false);
    expect(hasText(/invalid step status:/)).toBe(false);
    expect(hasText(/budget \d+\/\d+ used/)).toBe(false);
  });

  it('renders a 503 "missions not available" verbatim', async () => {
    mockRoutes({
      '/api/missions': { status: 200, body: { missions: [MISSION()] } },
      '/api/canvas': CANVAS,
      '/api/missions/7/steps/2/finish': { status: 503, body: { error: 'missions not available' } },
    });
    render(<MissionCanvasPanel />);
    await openSteps();
    fireEvent.click(screen.getByLabelText('done step 2 of mission 7'));

    await waitFor(() => expect(exactSpan('step #2 refused: missions not available')).toBe(true));
    expect(screen.getByText('503')).toBeTruthy();
  });
});

describe('MissionCanvasPanel · an empty board is ambiguous, not empty', () => {
  it('renders the amber ambiguity line instead of a bare "nothing yet"', async () => {
    mockRoutes({
      '/api/missions': { status: 200, body: { missions: [] } },
      '/api/canvas': CANVAS,
    });
    render(<MissionCanvasPanel />);

    await waitFor(() => expect(hasText(/no missions returned/)).toBe(true));
    expect(hasText(/it has no 503 branch/)).toBe(true);
    // the canvas card has elements, so nothing else could be printing this
    expect(hasText(/nothing yet/)).toBe(false);
  });
});

describe('MissionCanvasPanel · canvas sweep', () => {
  it('needs two clicks and then sends scope as QUERY params with no request body', async () => {
    const fn = mockRoutes({
      '/api/missions': { status: 200, body: { missions: [MISSION()] } },
      '/api/canvas': CANVAS,
      '/api/canvas/clear?keep_pinned=false&agent=vision': { status: 200, body: { removed: 2 } },
    });
    render(<MissionCanvasPanel />);
    await waitFor(() => expect(screen.getByLabelText('sweep scope')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('sweep scope'), { target: { value: 'vision' } });
    fireEvent.click(screen.getByLabelText('keep pinned elements'));   // → keep_pinned=false

    // ONE click only arms it — irreversible, so it must not fire
    fireEvent.click(screen.getByLabelText('clear canvas elements in scope'));
    expect(fn.mock.calls.filter((c) => String(c[0]).indexOf('/api/canvas/clear') === 0).length).toBe(0);
    expect(hasText(/irreversible — there is no undo route/)).toBe(true);

    fireEvent.click(screen.getByLabelText('clear canvas elements in scope'));
    await waitFor(() => expect(
      callsTo(fn, '/api/canvas/clear?keep_pinned=false&agent=vision').length,
    ).toBe(1));
    // NO body: FastAPI would ignore one and apply the defaults, sweeping every agent
    const init = callsTo(fn, '/api/canvas/clear?keep_pinned=false&agent=vision')[0][1];
    expect(init.body).toBeUndefined();
    expect(init.headers['Content-Type']).toBeUndefined();

    await waitFor(() => expect(hasText(/removed 2 element\(s\)/)).toBe(true));
  });

  it('renders removed 0 as a true 200, and flags a prediction the backend did not match', async () => {
    mockRoutes({
      '/api/missions': { status: 200, body: { missions: [MISSION()] } },
      '/api/canvas': CANVAS,
      '/api/canvas/clear?keep_pinned=true': { status: 200, body: { removed: 0 } },
    });
    render(<MissionCanvasPanel />);
    await waitFor(() => expect(screen.getByLabelText('clear canvas elements in scope')).toBeTruthy());

    fireEvent.click(screen.getByLabelText('clear canvas elements in scope'));
    fireEvent.click(screen.getByLabelText('clear canvas elements in scope'));

    await waitFor(() => expect(hasText(/removed 0 — nothing matched \(a real 200, not an error\)/)).toBe(true));
    // 2 unpinned elements were predicted; the backend removed 0 — the gap is stated
    expect(hasText(/predicted 2 from the last fetch — the canvas changed in between/)).toBe(true);
  });

  it('renders a sweep refusal verbatim and shows no removal count', async () => {
    mockRoutes({
      '/api/missions': { status: 200, body: { missions: [MISSION()] } },
      '/api/canvas': CANVAS,
      '/api/canvas/clear?keep_pinned=true': {
        status: 403,
        body: { detail: 'user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access' },
      },
    });
    render(<MissionCanvasPanel />);
    await waitFor(() => expect(screen.getByLabelText('clear canvas elements in scope')).toBeTruthy());

    fireEvent.click(screen.getByLabelText('clear canvas elements in scope'));
    fireEvent.click(screen.getByLabelText('clear canvas elements in scope'));

    await waitFor(() => expect(exactSpan(
      'sweep refused: user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access',
    )).toBe(true));
    expect(screen.getByText('403')).toBeTruthy();
    expect(hasText(/removed \d+ element/)).toBe(false);
  });
});

/* REGRESSION — a non-active mission must not be pointed at a control that cannot exist.
   done/failed/cancelled are TERMINAL: `_TRANSITIONS` gives them an EMPTY exit set
   (agents/core/autonomy/missions.py) and every status write goes through `_set_status`, so the
   mission-op routes answer 409 "operation not allowed in current mission state"; gap.tsx
   MissionsPanel's actionsFor returns [] for exactly those three, so there is no button to
   press either. The panel used to print one fixed line — "start or resume it from the MISSIONS
   panel" — for EVERY non-active status. */
describe('MissionCanvasPanel · a non-active mission is routed only to a control that exists', () => {
  const board = (status) => ({
    '/api/missions': { status: 200, body: { missions: [MISSION({ status })] } },
    '/api/canvas': CANVAS,
  });

  it('names no control for a terminal mission and says it cannot return to active', async () => {
    mockRoutes(board('failed'));
    render(<MissionCanvasPanel />);
    await openSteps();

    await waitFor(() => expect(hint()).toBe(TERMINAL_HINT('failed')));
    // the dead control: no start, no resume, no pointer at another panel
    expect(hint()).not.toMatch(/MISSIONS panel/);
    expect(hint()).not.toMatch(/start|resume/);
    // …and no finish button either, since finish_step needs an ACTIVE mission
    expect(screen.queryByLabelText('done step 2 of mission 7')).toBe(null);
  });

  it('says the same for cancelled', async () => {
    mockRoutes(board('cancelled'));
    render(<MissionCanvasPanel />);
    await openSteps();

    await waitFor(() => expect(hint()).toBe(TERMINAL_HINT('cancelled')));
  });

  it('names start — and only start — for a planned mission', async () => {
    mockRoutes(board('planned'));
    render(<MissionCanvasPanel />);
    await openSteps();

    await waitFor(() => expect(hint()).toBe(
      'finish_step runs only while the mission is active (this one is planned) — start it from the MISSIONS panel.',
    ));
    // planned → {active, cancelled}: there is no resume out of it, and no resume button
    expect(hint()).not.toMatch(/resume/);
  });

  it('names resume — and only resume — for a paused mission', async () => {
    mockRoutes(board('paused'));
    render(<MissionCanvasPanel />);
    await openSteps();

    await waitFor(() => expect(hint()).toBe(
      'finish_step runs only while the mission is active (this one is paused) — resume it from the MISSIONS panel.',
    ));
    expect(hint()).not.toMatch(/start/);
  });

  it('does not contradict itself after the budget 409 auto-fails the mission', async () => {
    mockRoutes({
      '/api/missions': [
        { status: 200, body: { missions: [MISSION()] } },
        { status: 200, body: { missions: [MISSION({ status: 'failed', steps_used: 20 })] } },
      ],
      '/api/canvas': CANVAS,
      '/api/missions/7/steps/2/finish': {
        status: 409,
        body: { error: 'mission step budget exhausted', budget_exceeded: true },
      },
    });
    render(<MissionCanvasPanel />);
    await openSteps();
    fireEvent.click(screen.getByLabelText('done step 2 of mission 7'));

    // the side-effect note stays…
    await waitFor(() => expect(hasText(/There is nothing to retry/)).toBe(true));
    // …and the same expanded card must not, in the same breath, offer to restart the mission
    await waitFor(() => expect(hint()).toBe(TERMINAL_HINT('failed')));
  });
});
