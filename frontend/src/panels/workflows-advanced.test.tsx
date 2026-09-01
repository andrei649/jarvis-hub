// @ts-nocheck
/* WORKFLOW TRACES panel — GET /api/workflows/traces and POST /api/workflows/hierarchical
   (both user-tier). fetch is mocked, like src/panels/signals-governance.test.tsx.

   The assertions that matter here are the ones that would catch a shape-not-substance
   panel:
     · an empty {"runs": []} must NOT read as "nothing yet" / "engine idle" — the backend
       sends that identical body when the workflow engine is absent;
     · ok:true together with terminated_by must show BOTH tags, since an early stop is not
       a failure;
     · a 400 refusal must render the backend's own string and no success markup (apiPost
       throws, so a panel reading r.error off the then branch would show nothing at all);
     · HTTP 200 with ok:false must render as a FAILED run, not as an answer. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { WorkflowTracesPanel } from './workflows-advanced';

const TRACES = '/api/workflows/traces';
const HIER = '/api/workflows/hierarchical';
const AGENTS = '/api/agents';

const ROSTER = { agents: [{ id: 'jarvis' }, { id: 'vision' }, { id: 'steve' }] };

const RUN_TERMINATED = {
  pipeline_id: 'morning_brief',
  pipeline_name: 'Morning Brief',
  ts: Math.floor(Date.now() / 1000) - 30,
  elapsed: 4.21,
  ok: true,
  terminated_by: 'guard',
  steps: [
    {
      step: 'collect',
      kind: 'agent',
      agent: 'friday',
      input_preview: 'Summarise the overnight inbox for the owner',
      output_preview: 'Three items need a decision before 10:00',
      elapsed_ms: 812.4,
      ok: true,
    },
  ],
};

function mockRoutes(handler) {
  const fn = vi.fn(async (url, init) => {
    const u = String(url);
    const method = String((init && init.method) || 'GET').toUpperCase();
    const r = handler(u, method) || { status: 200, body: {} };
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  });
  global.fetch = fn;
  return fn;
}

const withTraces = (runs, post) => mockRoutes((u, m) => {
  if (u === HIER && m === 'POST') return post || { status: 200, body: {} };
  if (u.startsWith(TRACES)) return { status: 200, body: { runs } };
  if (u === AGENTS) return { status: 200, body: ROSTER };
  return null;
});

/* Fill the minimum a hierarchical run needs: a goal plus one crew member with a roster agent. */
async function fillForm() {
  await waitFor(() => expect(screen.getByLabelText('crew 1 agent')).toBeTruthy());
  fireEvent.change(screen.getByLabelText('goal'), { target: { value: 'brief me' } });
  fireEvent.change(screen.getByLabelText('crew 1 agent'), { target: { value: 'vision' } });
}

const runBtn = () => screen.getByRole('button', { name: /run hierarchical/i });

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  vi.restoreAllMocks();
});

describe('WorkflowTracesPanel — section A, an empty list that cannot be read as health', () => {
  it('renders {"runs": []} as an explicit cannot-distinguish state, never "nothing yet"', async () => {
    const fn = withTraces([]);
    render(<WorkflowTracesPanel />);

    await waitFor(() => expect(screen.getByText(/0 runs · CANNOT DISTINGUISH/)).toBeTruthy());
    expect(screen.getByText(/both when nothing has run AND when the/)).toBeTruthy();

    // the forbidden readings
    expect(screen.queryByText('nothing yet')).toBeNull();
    expect(document.body.textContent).not.toMatch(/no workflow runs yet|engine idle|0 runs · healthy/i);

    // the panel never probes engine health by executing a pipeline
    expect(fn.mock.calls.some((c) => String(c[0]).indexOf('/api/workflows/run') !== -1)).toBe(false);

    // user tier: no admin header on the traces read
    const get = fn.mock.calls.find((c) => String(c[0]).startsWith(TRACES));
    expect(get[1].headers['X-Admin-Token']).toBeUndefined();

    // no toggle is offered for things that have no route
    const labels = screen.getAllByRole('button').map((b) => b.textContent).join(' ');
    expect(labels).not.toMatch(/persist|enable|disable|ring size/i);
    expect(screen.getByText(/JARVIS_WORKFLOW_PERSIST is set/)).toBeTruthy();
  });

  it('shows ok AND the amber terminated tag together, and expands verbatim previews', async () => {
    withTraces([RUN_TERMINATED]);
    render(<WorkflowTracesPanel />);

    await waitFor(() => expect(screen.getByText('Morning Brief')).toBeTruthy());

    // additive, not either/or
    expect(screen.getByText('ok')).toBeTruthy();
    expect(screen.getByText('terminated by guard')).toBeTruthy();
    expect(screen.queryByText('failed')).toBeNull();

    // units are not mixed: elapsed is seconds, elapsed_ms is milliseconds
    expect(screen.getByText('4.21 s total')).toBeTruthy();

    fireEvent.click(screen.getByTitle('expand steps'));

    expect(screen.getByText('Summarise the overnight inbox for the owner')).toBeTruthy();
    expect(screen.getByText('Three items need a decision before 10:00')).toBeTruthy();
    expect(screen.getByText('812.4 ms')).toBeTruthy();
    expect(screen.getByText(/input_preview \(first 160 chars, truncated by the backend\)/)).toBeTruthy();
  });
});

describe('WorkflowTracesPanel — section B, refusals and failed runs', () => {
  it('renders a 400 refusal with the backend string verbatim and no success markup', async () => {
    const REASON = 'max_retries must be between 0 and 10';
    const fn = withTraces([], { status: 400, body: { error: REASON } });
    render(<WorkflowTracesPanel />);
    await fillForm();

    fireEvent.change(screen.getByLabelText('max_retries'), { target: { value: '99' } });
    fireEvent.click(runBtn());

    await waitFor(() => expect(screen.getByText('refused · ' + REASON)).toBeTruthy());
    expect(screen.getByText('REFUSED')).toBeTruthy();

    // the refusal is not dressed up as a result
    expect(screen.queryByText('manager synthesis (final)')).toBeNull();
    expect(screen.queryByText(/members$/)).toBeNull();

    // the value the operator typed reached the backend as typed
    const post = fn.mock.calls.find((c) => String(c[0]) === HIER);
    const sent = JSON.parse(post[1].body);
    expect(sent.max_retries).toBe('99');
    // blank optional keys are DROPPED, never sent as ""
    expect('manager' in sent).toBe(false);
    expect(sent.crew).toEqual([{ agent: 'vision', prompt: '{_goal}' }]);
    // user tier: act(), not actA()
    expect(post[1].headers['X-Admin-Token']).toBeUndefined();
  });

  it('renders HTTP 200 with ok:false as a FAILED run and prints the member output verbatim', async () => {
    const AGENT_ERR = '[error:agent execution failed]';
    withTraces([], {
      status: 200,
      body: {
        goal: 'brief me',
        manager: 'jarvis',
        members: [{ id: 'vision', agent: 'vision', output: AGENT_ERR, attempts: 2, redistributed: false, ok: false }],
        final: 'x',
        ok: false,
        redistributed: [],
      },
    });
    render(<WorkflowTracesPanel />);
    await fillForm();
    fireEvent.click(runBtn());

    await waitFor(() => expect(screen.getByText('run failed')).toBeTruthy());
    expect(screen.getByText(AGENT_ERR)).toBeTruthy();
    expect(screen.getByText('member failed')).toBeTruthy();
    expect(screen.getByText(/HTTP 200 with ok:false/)).toBeTruthy();
    expect(screen.getByText(/this synthesis was produced over FAILED member outputs/)).toBeTruthy();

    // the cause of the agent error is never invented
    expect(screen.getByText(/deliberately\s+withholds the underlying cause/)).toBeTruthy();
  });

  it('disables the run control when the agent roster cannot be read', async () => {
    mockRoutes((u) => {
      if (u.startsWith(TRACES)) return { status: 200, body: { runs: [] } };
      if (u === AGENTS) return { status: 503, body: {} };
      return null;
    });
    render(<WorkflowTracesPanel />);

    await waitFor(() => expect(screen.getByText(/agent roster unavailable/)).toBeTruthy());
    expect(runBtn().disabled).toBe(true);
  });
});
