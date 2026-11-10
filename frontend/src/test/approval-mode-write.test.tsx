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
});

describe('the per-agent override control', () => {
  const policy = () => reply(200, { global: 'ask', agents: { friday: 'off' }, looser: {} });

  async function set(agent, answer) {
    route([[['GET', '/autonomy/policy'], policy], [['POST', '/autonomy/policy'], answer]]);
    render(<AgentAutonomyPanel />);
    await screen.findByText('friday');
    fireEvent.change(screen.getByPlaceholderText('agent'), { target: { value: agent } });
    fireEvent.click(screen.getByRole('button', { name: 'set' }));
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
    const alert = await set('friday', () => reply(503, { error: 'mode_not_saved' }));
    expect(alert.textContent).toContain('not saved');
  });
});
