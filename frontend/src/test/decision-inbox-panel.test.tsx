// @ts-nocheck
/* HUD-v3 B1 (the north-star) — the Console Decision Inbox reads the blocked autonomy
   queue (/autonomy/tasks?status=blocked) and resolves a decision via
   POST /autonomy/tasks/{id}/decision {action}. fetch is mocked, like
   kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { DecisionInboxPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('DecisionInboxPanel — the north-star resolve action is live', () => {
  it('GETs the blocked queue and shows a decision with its risk tier', async () => {
    const fn = mockFetch({ tasks: [
      { id: 5, title: 'Send the follow-up email', kind: 'call.outbound', risk_tier: 2, status: 'blocked' },
    ], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByText('Send the follow-up email')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/tasks') && String(c[0]).includes('status=blocked'))).toBe(true);
    expect(screen.getByText('tier 2')).toBeTruthy();
  });

  it('accepts a decision (POST {action:"accept"}) when ✓ is clicked', async () => {
    const fn = mockFetch({ tasks: [{ id: 5, title: 'X', kind: 'k', risk_tier: 1, status: 'blocked' }], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByTitle('accept')).toBeTruthy());
    fireEvent.click(screen.getByTitle('accept'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/tasks/5/decision')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('"action":"accept"'))
    ).toBe(true));
  });

  it('rejects a decision (POST {action:"reject"}) when ✕ is clicked', async () => {
    const fn = mockFetch({ tasks: [{ id: 9, title: 'Y', kind: 'k', risk_tier: 3, status: 'blocked' }], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByTitle('reject')).toBeTruthy());
    fireEvent.click(screen.getByTitle('reject'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/tasks/9/decision')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('"action":"reject"'))
    ).toBe(true));
  });

  it('shows the honest all-clear state when nothing is blocked', async () => {
    mockFetch({ tasks: [], total: 0 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByText(/all clear/)).toBeTruthy());
  });

  it('edit reveals the payload as JSON and saves an edited decision (POST {action:"edit",payload})', async () => {
    const fn = mockFetch({ tasks: [
      { id: 7, title: 'Wire $200', kind: 'payment', risk_tier: 3, status: 'blocked', payload: { amount: 200 } },
    ], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByTitle('edit')).toBeTruthy());
    fireEvent.click(screen.getByTitle('edit'));
    // the textarea is pre-filled with the task's payload
    const ta = await screen.findByDisplayValue(/"amount": 200/);
    fireEvent.change(ta, { target: { value: '{"amount": 50}' } });
    fireEvent.click(screen.getByText('save & approve'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/tasks/7/decision')
        && c[1]?.method === 'POST'
        && String(c[1]?.body).includes('"action":"edit"')
        && String(c[1]?.body).includes('"amount":50'))
    ).toBe(true));
  });

  it('does NOT POST an edit when the payload JSON is invalid', async () => {
    const fn = mockFetch({ tasks: [
      { id: 8, title: 'X', kind: 'k', risk_tier: 1, status: 'blocked', payload: {} },
    ], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByTitle('edit')).toBeTruthy());
    fireEvent.click(screen.getByTitle('edit'));
    const ta = await screen.findByDisplayValue('{}');
    fireEvent.change(ta, { target: { value: '{not valid json' } });
    fireEvent.click(screen.getByText('save & approve'));
    // invalid JSON is swallowed by the try/catch — no decision POST should fire
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/decision') && c[1]?.method === 'POST')).toBe(false);
  });
});
