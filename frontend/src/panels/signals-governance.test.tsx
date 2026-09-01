// @ts-nocheck
/* SIGNAL GOVERNANCE panel — GET /api/signals/governance and POST
   /api/signals/governance/submit (both user-tier). fetch is mocked, like
   src/panels/payments.test.tsx.

   The refusals are the point, and this route inverts the usual trap: it answers 200 for
   every refusal, so the refusal arrives in act()'s `then` branch. The assertions that
   matter are therefore the negative ones — `available:true` + `status:"disabled"` must NOT
   render as a queued submission, and a hardcoded `pending: 0` on the unavailable branch
   must NOT reach the screen as a count. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SignalGovernancePanel } from './signals-governance';

const STATUS = '/api/signals/governance';
const SUBMIT = '/api/signals/governance/submit';

const NOTE = 'Preview only. Every queued item lands BLOCKED, awaiting a human decision.';

const DISABLED_STATUS = {
  available: true, reason: null, enabled: false,
  flag: 'JARVIS_SIGNAL_GOVERNANCE', kind: 'signal_recommendation',
  pending: 3, note: NOTE,
};
const ENABLED_STATUS = { ...DISABLED_STATUS, enabled: true, pending: 0 };
/* Shape (A): the bridge is not constructed. `pending: 0` here is a hardcoded filler
   shipped beside the reason (signals.py:141), NOT a measurement. */
const UNAVAILABLE_STATUS = {
  available: false, reason: 'signal_governance_unavailable', enabled: false,
  flag: 'JARVIS_SIGNAL_GOVERNANCE', kind: 'signal_recommendation', pending: 0,
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

const withStatus = (status, post) => mockRoutes((u, m) => {
  if (u === SUBMIT && m === 'POST') return post || { status: 200, body: {} };
  if (u === STATUS) return { status: 200, body: status };
  return null;
});

const getCount = (fn) => fn.mock.calls.filter(
  (c) => String(c[0]) === STATUS && String((c[1] && c[1].method) || 'GET').toUpperCase() === 'GET',
).length;

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  vi.restoreAllMocks();
});

describe('SignalGovernancePanel — a bridge that is off by default, said as a fact', () => {
  it('renders enabled:false as DISABLED naming the flag from the payload, never as an error', async () => {
    const fn = withStatus(DISABLED_STATUS);
    render(<SignalGovernancePanel />);
    await waitFor(() => expect(screen.getByText('DISABLED')).toBeTruthy());

    expect(fn.mock.calls.some((c) => String(c[0]) === STATUS)).toBe(true);
    // user tier: no admin header is attached to the read
    const get = fn.mock.calls.find((c) => String(c[0]) === STATUS);
    expect(get[1].headers['X-Admin-Token']).toBeUndefined();

    expect(screen.getByText(/JARVIS_SIGNAL_GOVERNANCE is not set/)).toBeTruthy();
    expect(screen.getByText(/3 × signal_recommendation awaiting a human decision/)).toBeTruthy();
    expect(screen.getByText(NOTE)).toBeTruthy();
    expect(screen.getByText('SEED')).toBeTruthy();
    expect(screen.queryByText('LIVE')).toBeNull();

    // off is not broken and not an outage
    expect(screen.queryByText(/offline/i)).toBeNull();
    expect(screen.queryByText(/UNAVAILABLE/)).toBeNull();
    expect(document.body.textContent).not.toMatch(/\bbroken\b|\berror\b/i);
    // the disabled state itself is worded as a fact, never as a failure
    expect(screen.getByText(/JARVIS_SIGNAL_GOVERNANCE is not set/).textContent)
      .not.toMatch(/error|broken|fail/i);

    // no enable/disable control exists on the backend, so none is drawn: reload + submit only
    const buttons = screen.getAllByRole('button');
    expect(buttons.length).toBe(2);
    expect(buttons.map((b) => b.textContent).join(' ')).not.toMatch(/enable|turn on|toggle|switch/i);
    expect(screen.getByText(/owner-side env change plus a\s+restart/)).toBeTruthy();
  });

  it('renders available:false with the reason VERBATIM and prints no pending number', async () => {
    withStatus(UNAVAILABLE_STATUS);
    render(<SignalGovernancePanel />);
    await waitFor(() => expect(screen.getByText(/signal_governance_unavailable/)).toBeTruthy());

    expect(screen.getByText(/signal_governance_unavailable/).textContent).toContain('bridge unavailable');
    expect(screen.getByText(/pending not measured/)).toBeTruthy();
    // the filler zero must never surface as a count (\b keeps "100 pending" in the
    // footer's limit disclosure from matching)
    expect(document.body.textContent).not.toMatch(/\b0 pending/);
    expect(screen.queryByText(/0 × signal_recommendation/)).toBeNull();
    expect(screen.getByText('unavailable')).toBeTruthy();   // the head sub, not a count
    expect(screen.getByText('SEED')).toBeTruthy();
  });

  it('renders available:true + status:"disabled" as a REFUSAL, never as a queued submission', async () => {
    withStatus(DISABLED_STATUS, {
      status: 200,
      body: { available: true, reason: null, status: 'disabled', queued: 0, task_ids: [], skipped: 0 },
    });
    render(<SignalGovernancePanel />);
    await waitFor(() => expect(screen.getByText('DISABLED')).toBeTruthy());
    fireEvent.click(screen.getByText('submit brief → inbox'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('disabled · nothing queued');
    expect(alert).toContain('JARVIS_SIGNAL_GOVERNANCE is not set');
    // the anti-dead-code assertion: the success branch must NOT have rendered
    expect(alert).not.toMatch(/queued \d/);
    expect(screen.queryByText(/await_human_approval/)).toBeNull();
  });

  it('renders a 200 refusal body (available:false) with the backend reason VERBATIM', async () => {
    withStatus(ENABLED_STATUS, {
      status: 200,
      body: {
        available: false, reason: 'signal_layer_plugin_unavailable',
        status: 'unavailable', queued: 0, task_ids: [], skipped: 0,
      },
    });
    render(<SignalGovernancePanel />);
    await waitFor(() => expect(screen.getByText('ENABLED')).toBeTruthy());
    fireEvent.click(screen.getByText('submit brief → inbox'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('refused · signal_layer_plugin_unavailable');
    expect(alert).toContain('Nothing was queued');
    expect(alert).not.toMatch(/queued \d/);
    // a router-emitted reason: no sidecar detail is claimed to have been dropped
    expect(alert).not.toMatch(/provider/);
  });

  it('renders a real success with the ids and the backend note, then re-reads the status', async () => {
    const fn = withStatus(ENABLED_STATUS, {
      status: 200,
      body: {
        available: true, reason: null, status: 'ok', queued: 2, task_ids: [7, 8], skipped: 1,
        note: 'Preview only. Route through Jarvis approval before action.',
      },
    });
    render(<SignalGovernancePanel />);
    await waitFor(() => expect(screen.getByText('ENABLED')).toBeTruthy());
    const before = getCount(fn);
    fireEvent.click(screen.getByText('submit brief → inbox'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('queued 2 · skipped 1');
    expect(screen.getByText('#7')).toBeTruthy();
    expect(screen.getByText('#8')).toBeTruthy();
    expect(alert).toContain('Preview only. Route through Jarvis approval before action.');
    // `skipped` is printed bare, with no cause attributed to it
    expect(alert).toContain('1 not queued');
    expect(alert).toContain('no breakdown');
    expect(alert).not.toMatch(/advisory/);
    // nothing is claimed to have been approved or run
    expect(alert).toContain('BLOCKED with decision=await_human_approval');
    expect(alert).not.toMatch(/\bapproved\b(?! )|\bexecuted\b|\bscheduled\b/);
    // the POST carried no body: this route takes no request fields
    const post = fn.mock.calls.find((c) => String(c[0]) === SUBMIT);
    expect(post[1].body).toBeUndefined();
    // and the count is re-read from the server rather than incremented here
    await waitFor(() => expect(getCount(fn)).toBeGreaterThan(before));
  });

  it('renders a transport refusal (403) as a visible failure carrying the status', async () => {
    withStatus(ENABLED_STATUS, { status: 403, body: { detail: 'user token required' } });
    render(<SignalGovernancePanel />);
    await waitFor(() => expect(screen.getByText('ENABLED')).toBeTruthy());
    fireEvent.click(screen.getByText('submit brief → inbox'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('submit failed · HTTP 403');
    expect(alert).toContain('user token required');
    expect(alert).toContain('nothing was queued');
    expect(alert).not.toMatch(/queued \d/);
  });
});
