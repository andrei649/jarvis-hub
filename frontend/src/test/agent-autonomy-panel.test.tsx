// @ts-nocheck
/* HUD-v3 C2 (per-agent half) — the Console Per-Agent Autonomy panel reads the
   admin-guarded /autonomy/policy ({global, agents}) and lets an owner set/clear a
   per-agent AUTO/ASK/OFF override (the control surface for PR 0's agent_modes).
   fetch is mocked, like kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { AgentAutonomyPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('AgentAutonomyPanel — the per-agent autonomy dial is live', () => {
  it('GETs /autonomy/policy and shows the global mode + an existing override', async () => {
    const fn = mockFetch({ global: 'auto', agents: { vision: 'off' } });
    render(<AgentAutonomyPanel />);
    await waitFor(() => expect(screen.getByText('vision')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/policy'))).toBe(true);
    expect(screen.getByText('global: auto')).toBeTruthy();
    // the override is rendered as a Tag <span> (the select also has an <option>off</option>)
    expect(screen.getByText('off', { selector: 'span' })).toBeTruthy();
  });

  it('clears an override (POST mode=default) when the ✕ is clicked', async () => {
    const fn = mockFetch({ global: 'auto', agents: { vision: 'off' } });
    render(<AgentAutonomyPanel />);
    await waitFor(() => expect(screen.getByText('vision')).toBeTruthy());
    fireEvent.click(screen.getByTitle('clear (follow global)'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/policy')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('"mode":"default"')
        && String(c[1]?.body).includes('"agent":"vision"'))
    ).toBe(true));
  });

  it('shows the honest empty-state when no overrides exist', async () => {
    mockFetch({ global: 'ask', agents: {} });
    render(<AgentAutonomyPanel />);
    await waitFor(() => expect(screen.getByText(/every agent follows the global mode/)).toBeTruthy());
  });

  it('sets a new override (POST {agent, mode}) only when an agent name is given', async () => {
    const fn = mockFetch({ global: 'auto', agents: {} });
    render(<AgentAutonomyPanel />);
    await waitFor(() => expect(screen.getByText('set')).toBeTruthy());
    // empty agent → no POST
    fireEvent.click(screen.getByText('set'));
    expect(fn.mock.calls.some((c) => c[1]?.method === 'POST')).toBe(false);
    // typed agent → POST
    fireEvent.change(screen.getByPlaceholderText('agent'), { target: { value: 'howard' } });
    fireEvent.click(screen.getByText('set'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/policy')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('"agent":"howard"'))
    ).toBe(true));
  });
});
