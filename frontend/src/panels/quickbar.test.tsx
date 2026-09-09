// @ts-nocheck
/* QUICKBAR panel — `fetch` is mocked (not api/client) so the REAL client path runs.

   A command bar is the most tempting place in a product to put a shortcut past the
   rules, so every claim pinned here is about the panel refusing to be one:

   · the plan is rendered and NOT acted on — no navigation, no send;
   · `unresolved` gets its own state with the backend's reason verbatim, and it is
     never green: a bar that did not understand you has not succeeded at anything;
   · a query's route_hint is labelled a GUESS, because routing is decided on submit;
   · recall lives in localStorage and is never sent anywhere;
   · a browser that blocks storage leaves the bar working rather than throwing. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QuickbarPanel, describePlan, readHistory, pushHistory } from './quickbar';

const HELP = {
  ok: true,
  commands: [
    { command: '/memory', does: 'go to memory' },
    { command: '@<agent>: …', does: 'summon one of friday, athena…' },
  ],
  agents: ['friday', 'athena'],
  modes: ['memory', 'cockpit'],
  tabs: ['conversation'],
};

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });
const refuse = (status, payload) => ({ ok: false, status, json: async () => payload });

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve(hit ? hit[1] : ok({}));
  });
  global.fetch = fn;
  return fn;
}

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('QuickbarPanel — a preview, never an execution', () => {
  it('renders a resolved plan and does not act on it', async () => {
    const fetchMock = mockFetch({
      '/api/quickbar/resolve': ok({ ok: true, plan: { kind: 'navigate', mode: 'memory', input: '/memory' } }),
      '/api/quickbar/help': ok(HELP),
    });
    render(<QuickbarPanel />);
    fireEvent.change(screen.getByLabelText('quickbar line'), { target: { value: '/memory' } });
    fireEvent.click(screen.getByTitle('resolve this line'));
    await waitFor(() => expect(screen.getByText('would go to memory')).toBeTruthy());
    // Only read-only catalogs and the existing preview resolver — nothing executed.
    const called = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(called.every((u) => u.includes('/api/quickbar/') || u.endsWith('/api/commands'))).toBe(true);
  });

  it('says a summon WOULD ask, rather than asking', async () => {
    mockFetch({
      '/api/quickbar/resolve': ok({
        ok: true,
        plan: { kind: 'summon', agent: 'friday', text: 'what is on my calendar', input: '@friday …' },
      }),
      '/api/quickbar/help': ok(HELP),
    });
    render(<QuickbarPanel />);
    fireEvent.change(screen.getByLabelText('quickbar line'), { target: { value: '@friday hi' } });
    fireEvent.click(screen.getByTitle('resolve this line'));
    await waitFor(() =>
      expect(screen.getByText('would ask friday: what is on my calendar')).toBeTruthy());
  });

  it('gives an unresolved line its own state with the backend reason', async () => {
    mockFetch({
      '/api/quickbar/resolve': ok({
        ok: true, plan: { kind: 'unresolved', reason: 'unknown command /nope', input: '/nope' },
      }),
      '/api/quickbar/help': ok(HELP),
    });
    render(<QuickbarPanel />);
    fireEvent.change(screen.getByLabelText('quickbar line'), { target: { value: '/nope' } });
    fireEvent.click(screen.getByTitle('resolve this line'));
    await waitFor(() => expect(screen.getByText('unknown command /nope')).toBeTruthy());
    expect(screen.getByText('unresolved')).toBeTruthy();
  });

  it('labels a routing hint as a guess', async () => {
    mockFetch({
      '/api/quickbar/resolve': ok({
        ok: true, plan: { kind: 'query', route_hint: 'athena', input: 'what is the weather' },
      }),
      '/api/quickbar/help': ok(HELP),
    });
    render(<QuickbarPanel />);
    fireEvent.change(screen.getByLabelText('quickbar line'), { target: { value: 'weather' } });
    fireEvent.click(screen.getByTitle('resolve this line'));
    await waitFor(() => expect(screen.getByText(/is a/)).toBeTruthy());
    expect(screen.getByText(/routing is decided when you actually send it/)).toBeTruthy();
  });

  it('surfaces a refusal instead of reading as success', async () => {
    mockFetch({
      '/api/quickbar/resolve': refuse(401, { reason: 'user token required' }),
      '/api/quickbar/help': ok(HELP),
    });
    render(<QuickbarPanel />);
    fireEvent.change(screen.getByLabelText('quickbar line'), { target: { value: '/memory' } });
    fireEvent.click(screen.getByTitle('resolve this line'));
    await waitFor(() => expect(screen.getByText(/refused · user token required/)).toBeTruthy());
  });

  it('keeps recall in this browser and never sends it anywhere', async () => {
    const fetchMock = mockFetch({
      '/api/quickbar/resolve': ok({ ok: true, plan: { kind: 'navigate', mode: 'memory', input: '/memory' } }),
      '/api/quickbar/help': ok(HELP),
    });
    render(<QuickbarPanel />);
    fireEvent.change(screen.getByLabelText('quickbar line'), { target: { value: '/memory' } });
    fireEvent.click(screen.getByTitle('resolve this line'));
    await waitFor(() => expect(screen.getByText('RECENT (this browser only)')).toBeTruthy());
    expect(readHistory()).toContain('/memory');
    // no request body ever carried the history
    const bodies = fetchMock.mock.calls.map((c) => String((c[1] && c[1].body) || ''));
    expect(bodies.every((b) => !b.includes('history'))).toBe(true);
  });

  it('does not recall a line that resolved to nothing actionable', async () => {
    mockFetch({
      '/api/quickbar/resolve': ok({ ok: true, plan: { kind: 'help', commands: [], input: '/help' } }),
      '/api/quickbar/help': ok(HELP),
    });
    render(<QuickbarPanel />);
    fireEvent.change(screen.getByLabelText('quickbar line'), { target: { value: '/help' } });
    fireEvent.click(screen.getByTitle('resolve this line'));
    await waitFor(() => expect(screen.getByText('the command menu')).toBeTruthy());
    expect(readHistory()).toEqual([]);
  });

  it('renders the command menu the backend grounded', async () => {
    mockFetch({ '/api/quickbar/help': ok(HELP) });
    render(<QuickbarPanel />);
    await waitFor(() => expect(screen.getByText('/memory')).toBeTruthy());
    expect(screen.getByText('go to memory')).toBeTruthy();
  });

  it('lists the live chat commands with usage and owner tier without invoking one', async () => {
    localStorage.setItem('hud.admin_token', 'existing-owner-token');
    const fetchMock = mockFetch({
      '/api/quickbar/help': ok(HELP),
      '/api/commands': ok({ ok: true, commands: [
        { name: 'status', command: '/status', description: 'Hub status', tier: 'user', usage: '' },
        { name: 'stop', command: '/stop', description: 'Emergency stop', tier: 'admin', usage: '[reason]' },
      ] }),
    });
    render(<QuickbarPanel />);
    await waitFor(() => expect(screen.getByText('/status')).toBeTruthy());
    expect(screen.getByText('/stop [reason]')).toBeTruthy();
    expect(screen.getByText('owner')).toBeTruthy();
    expect(screen.getByText('Emergency stop')).toBeTruthy();
    expect(screen.getByText(/Send a command in chat/)).toBeTruthy();
    expect(fetchMock.mock.calls.every(([, opts]) => !opts?.method || opts.method === 'GET')).toBe(true);
    const catalogCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/commands'));
    expect(catalogCall[1].headers['X-Admin-Token']).toBe('existing-owner-token');
    expect(screen.queryByRole('button', { name: /stop/ })).toBeNull();
    expect(readHistory()).toEqual([]);
  });

  it('does not invent owner commands absent from the returned catalog', async () => {
    mockFetch({ '/api/quickbar/help': ok(HELP), '/api/commands': ok({ ok: true, commands: [
      { name: 'status', command: '/status', description: 'Hub status', tier: 'user', usage: '' },
    ] }) });
    render(<QuickbarPanel />);
    await waitFor(() => expect(screen.getByText('/status')).toBeTruthy());
    expect(screen.queryByText('/stop')).toBeNull();
    expect(screen.queryByText('owner')).toBeNull();
  });

  it('shows catalog unavailability while keeping the existing quickbar menu usable', async () => {
    mockFetch({ '/api/quickbar/help': ok(HELP),
      '/api/commands': refuse(503, { reason: 'commands_unavailable' }) });
    render(<QuickbarPanel />);
    await waitFor(() => expect(screen.getByText('Chat commands unavailable.')).toBeTruthy());
    expect(screen.getByText('/memory')).toBeTruthy();
    expect(screen.queryByText('/status')).toBeNull();
    expect(screen.getByTitle('resolve this line')).toBeTruthy();
  });

  it('distinguishes a live empty command registry from an unavailable one', async () => {
    mockFetch({ '/api/quickbar/help': ok(HELP), '/api/commands': ok({ ok: true, commands: [] }) });
    render(<QuickbarPanel />);
    await waitFor(() => expect(screen.getByText('No chat commands available for this session.')).toBeTruthy());
    expect(screen.queryByText('Chat commands unavailable.')).toBeNull();
  });

  /* ── the pure helpers ─────────────────────────────────────────────── */

  it('describes every plan kind without inventing an outcome', () => {
    expect(describePlan({ kind: 'navigate', tab: 'artifacts' })).toBe('would go to artifacts');
    expect(describePlan({ kind: 'summon', agent: 'friday' })).toBe('would ask friday');
    expect(describePlan({ kind: 'query' })).toBe('would ask — no routing guess');
    expect(describePlan({ kind: 'empty' })).toBe('nothing typed');
    expect(describePlan({ kind: 'unresolved', reason: 'nope' })).toBe('nope');
    expect(describePlan(null)).toBe('—');
  });

  it('bounds recall and moves a repeat to the front rather than duplicating it', () => {
    for (let i = 0; i < 30; i += 1) pushHistory(`line ${i}`);
    expect(readHistory().length).toBeLessThanOrEqual(20);
    pushHistory('line 5');
    expect(readHistory()[0]).toBe('line 5');
    expect(readHistory().filter((x) => x === 'line 5').length).toBe(1);
  });

  it('keeps working when the browser blocks storage', () => {
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage');
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() { throw new Error('blocked'); },
    });
    try {
      expect(readHistory()).toEqual([]);
      expect(() => pushHistory('x')).not.toThrow();
    } finally {
      if (original) Object.defineProperty(window, 'localStorage', original);
    }
  });
});
