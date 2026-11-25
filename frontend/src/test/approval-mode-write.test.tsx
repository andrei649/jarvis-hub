// @ts-nocheck
/* H484 — the HUD tells the truth when an approval-mode write is refused.

   POST /autonomy/mode and POST /autonomy/policy answer 503 `mode_not_saved` (nothing was
   stored) or 503 `mode_not_effective` (stored, but the live policy runs another mode —
   `live` — because another write got there, safe mode drops a looser override, or the
   store could not be read back), and 422 `invalid_agent`. The controls used to revert
   silently or ignore the failure. They now show the mode that is in force and why. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { AutonomyMode } from '../modes2';
import { AgentAutonomyPanel } from '../gap';

const T = { autonomy: 'Autonomy' };
const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });

function route(handlers) {
  global.fetch = vi.fn((url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase();
    for (const [match, answer] of handlers) {
      if (String(url).includes(match[1]) && method === match[0]) return Promise.resolve(answer());
    }
    return Promise.resolve(reply(200, {}));
  });
}

beforeEach(() => {
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
});

describe('the global mode control', () => {
  it('shows the mode in force and the reason when a loosening did not take effect', async () => {
    route([
      [['GET', '/autonomy/mode'], () => reply(200, { mode: 'off' })],
      [['POST', '/autonomy/mode'], () => reply(503, { error: 'mode_not_effective', requested: 'auto', live: 'off' })],
    ]);
    render(<AutonomyMode t={T} />);
    const auto = await screen.findByRole('button', { name: 'AUTO' });
    await screen.findByText(/global · OFF/);
    fireEvent.click(auto);
    // Off → Auto asks less: two steps, as in the running head (PHASE_B_PLAN.md §4.2)
    const confirm = await screen.findByRole('button', { name: 'Switch to Auto' });
    expect(screen.getByText('Auto lets reversible actions run without asking.')).toBeTruthy();
    expect(global.fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
    fireEvent.click(confirm);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('AUTO did not take effect');
    expect(alert.textContent).toContain('OFF is in force');
    expect(screen.getByRole('button', { name: 'OFF' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'AUTO' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('shows the stricter mode that holds when the store went another way', async () => {
    route([
      [['GET', '/autonomy/mode'], () => reply(200, { mode: 'auto' })],
      [['POST', '/autonomy/mode'], () => reply(503, { error: 'mode_not_effective', requested: 'ask', live: 'off' })],
    ]);
    render(<AutonomyMode t={T} />);
    await screen.findByText(/global · AUTO/);
    fireEvent.click(screen.getByRole('button', { name: 'ASK' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('OFF is in force');
    expect(screen.getByRole('button', { name: 'OFF' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('says nothing was saved, and keeps showing the mode the hub reports', async () => {
    let asked = 0;
    route([
      [['GET', '/autonomy/mode'], () => { asked += 1; return reply(200, { mode: 'ask' }); }],
      [['POST', '/autonomy/mode'], () => reply(503, { error: 'mode_not_saved', mode: 'ask' })],
    ]);
    render(<AutonomyMode t={T} />);
    await screen.findByText(/global · ASK/);
    fireEvent.click(screen.getByRole('button', { name: 'OFF' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('OFF was not saved');
    expect(alert.textContent).toContain('ASK is in force');
    expect(screen.getByRole('button', { name: 'ASK' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('shows no alert after a write that took effect', async () => {
    route([
      [['GET', '/autonomy/mode'], () => reply(200, { mode: 'auto' })],
      [['POST', '/autonomy/mode'], () => reply(200, { mode: 'off', ok: true, effective: true })],
    ]);
    render(<AutonomyMode t={T} />);
    await screen.findByText(/global · AUTO/);
    fireEvent.click(screen.getByRole('button', { name: 'OFF' }));
    await screen.findByText(/global · OFF/);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  // PHASE_B_PLAN.md §4.2 (owner question 3) and §0.5: Work › Autonomy is no way around the running
  // head's two steps; which of the two is decided on the mode asked again at the press
  it('takes a looser mode in two steps and cancels without a write', async () => {
    route([
      [['GET', '/autonomy/mode'], () => reply(200, { mode: 'ask' })],
      [['POST', '/autonomy/mode'], () => reply(200, { mode: 'auto', ok: true, effective: true })],
    ]);
    render(<AutonomyMode t={T} />);
    await screen.findByText(/global · ASK/);
    fireEvent.click(screen.getByRole('button', { name: 'AUTO' }));
    await screen.findByRole('button', { name: 'Switch to Auto' });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('button', { name: 'Switch to Auto' })).toBeNull();
    expect(global.fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
    expect(screen.getByRole('button', { name: 'ASK' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('decides the friction on the mode in force at the press, not on the last read', async () => {
    let live = 'auto';
    route([
      [['GET', '/autonomy/mode'], () => reply(200, { mode: live })],
      [['POST', '/autonomy/mode'], () => reply(200, { mode: 'ask', ok: true, effective: true })],
    ]);
    render(<AutonomyMode t={T} />);
    await screen.findByText(/global · AUTO/);
    // by the last read, Ask would be stricter (one click); the hub went to Off in another tab since,
    // so Ask asks less than the mode in force and takes the second step
    live = 'off';
    fireEvent.click(screen.getByRole('button', { name: 'ASK' }));
    expect(await screen.findByRole('button', { name: 'Switch to Ask' })).toBeTruthy();
    expect(screen.getByText(/Ask resumes the proactive loop/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'OFF' }).getAttribute('aria-pressed')).toBe('true');
    expect(global.fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Switch to Ask' }));
    await screen.findByText(/global · ASK/);
    expect(global.fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });

  it('neither reads nor changes the mode while the demo sample is on', async () => {
    route([[['GET', '/autonomy/mode'], () => reply(200, { mode: 'ask' })]]);
    render(<AutonomyMode t={T} demo />);
    expect(screen.getByText(/global · DEMO SAMPLE/)).toBeTruthy();
    for (const name of ['AUTO', 'ASK', 'OFF']) expect(screen.getByRole('button', { name }).hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'AUTO' }));
    expect(screen.getByRole('note').textContent).toMatch(/Demo sample: the approval mode is not read or changed here/);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

describe('the per-agent override control', () => {
  const policy = () => reply(200, { global: 'ask', agents: { friday: 'off' }, looser: {} });

  // `looser`: the override asks less than the agent does now, so it takes its second step first
  async function set(agent, answer, looser = false) {
    route([[['GET', '/autonomy/policy'], policy], [['POST', '/autonomy/policy'], answer]]);
    render(<AgentAutonomyPanel />);
    await screen.findByText('friday');
    fireEvent.change(screen.getByPlaceholderText('agent'), { target: { value: agent } });
    fireEvent.click(screen.getByRole('button', { name: 'set' }));
    if (looser) fireEvent.click(await screen.findByRole('button', { name: `Switch ${agent} to ask` }));
    return screen.findByRole('alert');
  }

  it('says what the agent runs when the override is stored but not in force', async () => {
    const alert = await set('scout', () => reply(503, {
      error: 'mode_not_effective', agent: 'scout', requested: 'ask', live: 'off' }));
    expect(alert.textContent).toContain('scout');
    expect(alert.textContent).toContain('ask did not take effect');
    expect(alert.textContent).toContain('runs off');
  });

  it('shows why an agent id was refused', async () => {
    const alert = await set('nobody', () => reply(422, {
      error: 'invalid_agent', detail: "no agent named 'nobody' on this hub" }));
    expect(alert.textContent).toContain("no agent named 'nobody' on this hub");
  });

  it('says when nothing was saved', async () => {
    // friday runs Off; Ask asks less, so the write follows the second step
    const alert = await set('friday', () => reply(503, { error: 'mode_not_saved' }), true);
    expect(alert.textContent).toContain('not saved');
  });
});
