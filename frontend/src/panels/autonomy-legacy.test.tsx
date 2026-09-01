// @ts-nocheck
/* AUTONOMY CONTROL — GET /autonomy/status, GET /autonomy/observer,
   POST /autonomy/observer/run, GET /autonomy/preferences/suggestions (all admin) and the
   user-tier POST /api/autonomy/call. fetch is mocked, like src/panels/payments.test.tsx.

   The refusals carry the weight here. apiPost throws on 4xx/5xx and apiGet throws with no
   body at all, so the assertions that matter are: a 503 must never render as a census of
   zeroes, the observer run's two distinct 503 strings must reach the screen verbatim, and
   `ok:true, queued:false` from the call route must read as NOT queued — it is the one
   response on this panel that looks like success and is not. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { AutonomyControlPanel } from './autonomy-legacy';

const STATUS_OK = {
  stats: { proposed: 2, blocked: 1, done: 5 },
  interrupt_budget_remaining: 3,
  interrupt_budget_per_day: 4,
  pending_decisions: [
    { id: 12, agent: 'ops', kind: 'monitor.restart', title: 'Restart qdrant', status: 'blocked', risk_tier: 3, origin: 'generated' },
    // A `proposed` row: this half of the list is invisible under the status=blocked
    // filter DECISION INBOX uses, so it is the genuinely new content on this panel.
    { id: 13, agent: 'scout', kind: 'brief.propose', title: 'Draft the morning brief', status: 'proposed', risk_tier: 1, origin: 'broker' },
  ],
};

const OBSERVER_OK = { enabled: true, probes: 5, tracked: 5, unhealthy: [{ key: 'qdrant', detail: 'qdrant unreachable on :6333', severity: 'CRITICAL' }] };

function mockRoutes(handler) {
  const fn = vi.fn(async (url, init) => {
    const u = String(url);
    const method = String((init && init.method) || 'GET').toUpperCase();
    const r = handler(u, method, init) || { status: 200, body: {} };
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  });
  global.fetch = fn;
  return fn;
}

/* Default: every read answers 200 so a test can focus on the one route it is about. */
const baseline = (over = {}) => (u, m) => {
  const o: any = over;
  if (u === '/autonomy/status') return o.status || { status: 200, body: STATUS_OK };
  if (u === '/autonomy/observer' && m === 'GET') return o.observer || { status: 200, body: OBSERVER_OK };
  if (u === '/autonomy/preferences/suggestions') return o.suggestions || { status: 200, body: { suggestions: [] } };
  if (u === '/autonomy/observer/run' && m === 'POST') return o.run || { status: 200, body: { ok: true, summary: { sampled: 0, findings: 0, submitted: 0, unhealthy: [] } } };
  if (u === '/api/autonomy/call' && m === 'POST') return o.call || { status: 200, body: { ok: true, queued: true, task_id: 7, kind: 'call.outbound', title: 'Call +40712 via twilio' } };
  return null;
};

const lastPost = (fn, path) => {
  const c = fn.mock.calls.filter((x) => String(x[0]) === path && String(x[1].method).toUpperCase() === 'POST').pop();
  return c || null;
};

beforeEach(() => {
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
  vi.restoreAllMocks();
});

describe('AutonomyControlPanel — the queue census, the observer and the governed call request', () => {
  it('renders the per-status census, the budget and both blocked AND proposed pending rows', async () => {
    const fn = mockRoutes(baseline());
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText('proposed 2')).toBeTruthy());

    const get = fn.mock.calls.find((c) => String(c[0]) === '/autonomy/status');
    expect(get[1].headers['X-Admin-Token']).toBe('adm');      // admin-tier read

    expect(screen.getByText('blocked 1')).toBeTruthy();
    expect(screen.getByText('done 5')).toBeTruthy();
    expect(screen.getByText('8 total')).toBeTruthy();
    expect(screen.getByText('3 / 4 interrupts left today')).toBeTruthy();
    // the interrupt budget is disclosed as already-shipped, not sold as new
    expect(screen.getByText(/same budget GET \/autonomy\/interrupts already feeds to DECISION INBOX/)).toBeTruthy();

    expect(screen.getByText('#12 · Restart qdrant')).toBeTruthy();
    const proposedRow = screen.getByText('#13 · Draft the morning brief').parentElement;
    // the row carries its REAL queue status — `proposed`, which a status=blocked filter never returns
    expect(proposedRow.textContent).toContain('proposed');
    expect(proposedRow.textContent).toContain('tier 1');
    expect(screen.getByText('#12 · Restart qdrant').parentElement.textContent).toContain('blocked');
    expect(screen.getByText('AWAITING A DECISION · 2 row(s)')).toBeTruthy();
    // read-only: resolving a decision belongs to DECISION INBOX's route
    expect(screen.queryByText('accept')).toBeNull();
    expect(screen.queryByText('reject')).toBeNull();
    expect(screen.queryByText('defer')).toBeNull();
  });

  it('renders a 503 on /autonomy/status verbatim as unavailable and never as a zero census', async () => {
    mockRoutes(baseline({ status: { status: 503, body: { error: 'not initialized' } } }));
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText(/GET \/autonomy\/status -> 503/)).toBeTruthy());

    expect(screen.getByText(/Unavailable, NOT zero/)).toBeTruthy();
    expect(screen.getByText(/"not initialized"/)).toBeTruthy();
    // nothing numeric may leak through: no census, no total, no budget, no pending list
    expect(screen.queryByText('0 total')).toBeNull();
    expect(screen.queryByText(/interrupts left today/)).toBeNull();
    expect(screen.queryByText(/queue empty/)).toBeNull();
    expect(screen.queryByText(/AWAITING A DECISION/)).toBeNull();
  });

  it('renders an empty stats dict as a true zero, distinct from the 503', async () => {
    mockRoutes(baseline({ status: { status: 200, body: { stats: {}, interrupt_budget_remaining: 0, interrupt_budget_per_day: 4, pending_decisions: [] } } }));
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText(/no rows in the tasks table/)).toBeTruthy());
    expect(screen.getByText('0 / 4 interrupts left today')).toBeTruthy();
    expect(screen.queryByText(/Unavailable, NOT zero/)).toBeNull();
  });

  it('renders the observer run refusal string verbatim and no summary numbers', async () => {
    mockRoutes(baseline({ run: { status: 503, body: { error: 'observer not initialized' } } }));
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText('sample now')).toBeTruthy());
    fireEvent.click(screen.getByText('sample now'));

    await waitFor(() => expect(screen.getByText(/run refused · HTTP 503/)).toBeTruthy());
    // the backend's own string, not a fixed sentence — and NOT the sibling "not initialized"
    expect(screen.getByText(/run refused · HTTP 503/).textContent).toContain('observer not initialized');
    expect(screen.queryByText(/^sampled /)).toBeNull();
    expect(screen.queryByText(/submitted to the autonomy queue/)).toBeNull();
  });

  it('renders a successful sample from the backend summary and names the enqueue', async () => {
    const fn = mockRoutes(baseline({ run: { status: 200, body: { ok: true, summary: { sampled: 5, findings: 2, submitted: 2, unhealthy: ['qdrant', 'neo4j'] } } } }));
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText('sample now')).toBeTruthy());
    fireEvent.click(screen.getByText('sample now'));

    await waitFor(() => expect(screen.getByText('sampled 5')).toBeTruthy());
    expect(screen.getByText('findings 2')).toBeTruthy();
    expect(screen.getByText('submitted 2')).toBeTruthy();
    expect(screen.getByText(/2 finding\(s\) submitted to the autonomy queue as task\(s\)/)).toBeTruthy();
    expect(lastPost(fn, '/autonomy/observer/run')[1].headers['X-Admin-Token']).toBe('adm');
  });

  it('renders ok:true + queued:false as NOT queued, never as success', async () => {
    const preview = { kind: 'call.outbound', title: 'Call +40712 via twilio', target: '+40712', effects: [], irreversible: false, risk_tier: 2, requires_approval: true, summary: "Would run 'call.outbound' → +40712; reversible; approval required.", would_execute: false };
    const fn = mockRoutes(baseline({ call: { status: 200, body: { ok: true, queued: false, kind: 'call.outbound', title: 'Call +40712 via twilio', payload: {}, preview } } }));
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText('request approval')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('to (number, ≤ 40 chars)'), { target: { value: '+40712' } });
    fireEvent.change(screen.getByPlaceholderText('message to be spoken on the call (≤ 2000 chars)'), { target: { value: 'the boiler is off' } });
    fireEvent.click(screen.getByText('request approval'));

    await waitFor(() => expect(screen.getByText(/NOT queued/)).toBeTruthy());
    expect(screen.getByText(/PREVIEW ONLY/)).toBeTruthy();
    expect(screen.queryByText(/queued for approval/)).toBeNull();
    // user tier: no admin header on this write
    expect(lastPost(fn, '/api/autonomy/call')[1].headers['X-Admin-Token']).toBeUndefined();
  });

  it('renders a queued call as an approval request and never as a placed call', async () => {
    const fn = mockRoutes(baseline());
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText('request approval')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('to (number, ≤ 40 chars)'), { target: { value: ' +40712 ' } });
    fireEvent.change(screen.getByPlaceholderText('reason (optional, ≤ 200)'), { target: { value: 'boiler' } });
    fireEvent.change(screen.getByPlaceholderText('message to be spoken on the call (≤ 2000 chars)'), { target: { value: 'the boiler is off' } });
    fireEvent.click(screen.getByText('request approval'));

    await waitFor(() => expect(screen.getByText(/queued for approval · task #7/)).toBeTruthy());
    const body = JSON.parse(lastPost(fn, '/api/autonomy/call')[1].body);
    expect(body).toEqual({ to: '+40712', message: 'the boiler is off', provider: 'twilio', reason: 'boiler' });
    expect(screen.queryByText(/call placed/i)).toBeNull();
    expect(screen.queryByText(/calling/i)).toBeNull();
    expect(screen.getByText(/Nothing dials here, ever/)).toBeTruthy();
  });

  it('renders a 422 call refusal with the broker reason verbatim via onErr', async () => {
    mockRoutes(baseline({ call: { status: 422, body: { ok: false, reason: 'interrupt_budget_exhausted' } } }));
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText('request approval')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('to (number, ≤ 40 chars)'), { target: { value: '+40712' } });
    fireEvent.change(screen.getByPlaceholderText('message to be spoken on the call (≤ 2000 chars)'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('request approval'));

    await waitFor(() => expect(screen.getByText(/refused · HTTP 422/)).toBeTruthy());
    expect(screen.getByText(/refused · HTTP 422/).textContent).toContain('interrupt_budget_exhausted');
    expect(screen.queryByText(/queued for approval/)).toBeNull();
    expect(screen.queryByText(/NOT queued/)).toBeNull();
  });

  it('renders the unknown_provider refusal with the backend supported list, not the hardcoded one', async () => {
    mockRoutes(baseline({ call: { status: 422, body: { ok: false, reason: 'unknown_provider', supported: ['telnyx', 'twilio'] } } }));
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText('request approval')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('to (number, ≤ 40 chars)'), { target: { value: '+40712' } });
    fireEvent.change(screen.getByPlaceholderText('message to be spoken on the call (≤ 2000 chars)'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('request approval'));

    await waitFor(() => expect(screen.getByText(/refused · HTTP 422/)).toBeTruthy());
    expect(screen.getByText(/refused · HTTP 422/).textContent).toContain('unknown_provider');
    expect(screen.getByText('supported: telnyx · twilio')).toBeTruthy();
  });

  it('renders an empty suggestions list as ambiguous-by-construction and offers no apply control', async () => {
    mockRoutes(baseline());
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText(/0 suggestions/)).toBeTruthy());
    expect(screen.getByText(/0 suggestions/).textContent).toContain('preference store has no');
    expect(screen.queryByText(/no candidates/i)).toBeNull();
    expect(screen.queryByText(/^raise$/i)).toBeNull();
    expect(screen.queryByText(/^apply$/i)).toBeNull();
  });

  it('renders a suggestion row with the backend suggestion string and still no button', async () => {
    const s = { agent: 'scout', kind: 'brief.propose', risk_tier: 1, approval_rate: 0.917, samples: 12, suggestion: 'raise autonomy → act autonomously on this class' };
    mockRoutes(baseline({ suggestions: { status: 200, body: { suggestions: [s] } } }));
    render(<AutonomyControlPanel />);
    await waitFor(() => expect(screen.getByText('scout · brief.propose')).toBeTruthy());

    expect(screen.getByText('approval_rate 0.917 over 12 sample(s)')).toBeTruthy();
    expect(screen.getByText('raise autonomy → act autonomously on this class')).toBeTruthy();
    expect(screen.getByText(/NO endpoint applies a per-\(agent, kind, risk_tier\) raise/)).toBeTruthy();
    // the only buttons on the panel are the reload arrow, the observer sample and the call request
    const labels = Array.from(document.querySelectorAll('button')).map((b) => b.textContent);
    expect(labels.sort()).toEqual(['request approval', 'sample now', '↻']);
  });
});
