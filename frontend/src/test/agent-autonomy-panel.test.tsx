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

  const posted = (fn, agent, mode) => fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/policy')
    && c[1]?.method === 'POST' && String(c[1]?.body).includes(`"mode":"${mode}"`) && String(c[1]?.body).includes(`"agent":"${agent}"`));

  it('clears an override that asks more than the global mode (POST mode=default) in one click', async () => {
    const fn = mockFetch({ global: 'ask', agents: { vision: 'auto' } });
    render(<AgentAutonomyPanel />);
    await waitFor(() => expect(screen.getByText('vision')).toBeTruthy());
    fireEvent.click(screen.getByTitle('clear (follow global)'));
    await waitFor(() => expect(posted(fn, 'vision', 'default')).toBe(true));
  });

  // PHASE_B_PLAN.md §4.2 / §0.5: an agent made to ask less takes two steps here too, decided on the
  // policy asked again at the press (vision on Off, the global mode Auto: clearing it loosens it)
  it('clears an override that would let the agent ask less only after a second step', async () => {
    const fn = mockFetch({ global: 'auto', agents: { vision: 'off' } });
    render(<AgentAutonomyPanel />);
    await waitFor(() => expect(screen.getByText('vision')).toBeTruthy());
    fireEvent.click(screen.getByTitle('clear (follow global)'));
    const confirm = await screen.findByRole('button', { name: "Clear vision's override" });
    expect(screen.getByText(/vision on Auto: its reversible actions run without asking/)).toBeTruthy();
    expect(posted(fn, 'vision', 'default')).toBe(false);
    fireEvent.click(confirm);
    await waitFor(() => expect(posted(fn, 'vision', 'default')).toBe(true));
  });

  it('cancels a looser override without posting, and makes an agent stricter in one click', async () => {
    const fn = mockFetch({ global: 'ask', agents: {} });
    render(<AgentAutonomyPanel />);
    await waitFor(() => expect(screen.getByText('set')).toBeTruthy());
    fireEvent.change(screen.getByRole('textbox', { name: 'Agent id' }), { target: { value: 'pepper' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Approval mode for that agent' }), { target: { value: 'auto' } });
    fireEvent.click(screen.getByText('set'));
    await screen.findByRole('button', { name: 'Switch pepper to auto' });
    fireEvent.click(screen.getByRole('button', { name: 'cancel' }));
    expect(screen.queryByRole('button', { name: 'Switch pepper to auto' })).toBeNull();
    expect(posted(fn, 'pepper', 'auto')).toBe(false);
    fireEvent.change(screen.getByRole('textbox', { name: 'Agent id' }), { target: { value: 'pepper' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Approval mode for that agent' }), { target: { value: 'off' } });
    fireEvent.click(screen.getByText('set'));
    await waitFor(() => expect(posted(fn, 'pepper', 'off')).toBe(true));
  });

  it('changes no agent while the demo sample is on', async () => {
    window.history.replaceState(null, '', '/v2/console/agent-autonomy?demo=1');
    try {
      const fn = mockFetch({ global: 'ask', agents: { vision: 'auto' } });
      render(<AgentAutonomyPanel />);
      await waitFor(() => expect(screen.getByText('vision')).toBeTruthy());
      expect(screen.getByRole('note').textContent).toMatch(/demo sample is on/);
      expect(screen.getByTitle('clear (follow global)').hasAttribute('disabled')).toBe(true);
      expect(screen.getByText('set').hasAttribute('disabled')).toBe(true);
      expect(screen.getByRole('combobox', { name: 'Approval mode for that agent' }).hasAttribute('disabled')).toBe(true);
      fireEvent.click(screen.getByText('set'));
      expect(fn.mock.calls.some((c) => c[1]?.method === 'POST')).toBe(false);
    } finally {
      window.history.replaceState(null, '', '/');
    }
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
