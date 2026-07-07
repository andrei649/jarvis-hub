// @ts-nocheck
/* Owner B0 finding (2026-07-07): "I didn't see the onboarding." The wizard and
   Command Center existed only as Console-overlay panels — onboarding you have to
   FIND is not onboarding. FirstRunGate makes the Command Center the landing
   surface: it renders as a front-and-center overlay whenever the install isn't
   usable yet (no model reachable / wizard incomplete) and the user hasn't
   dismissed it. Dismiss persists in localStorage. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { FirstRunGate, shouldShowFirstRun, FIRST_RUN_DISMISS_KEY } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const COLD = {
  install: { ready: true, version: '0.11.0', checks: {} },
  model: { backend: 'none', active_model: null, ready: false, cloud_configured: false },
  wizard: { steps: [{ key: 'intro', title: 'Welcome' }], completed: [], complete: false, hint: 'No model backend reachable — start LM Studio or Ollama.' },
  first_actions: [
    { key: 'say_hello', title: 'Say hello', kind: 'chat', path: '/chat', ready: false, reason: 'model not reachable' },
  ],
};

const READY = {
  ...COLD,
  model: { backend: 'lmstudio', active_model: 'gemma', ready: true, cloud_configured: false },
  wizard: { steps: [{ key: 'intro', title: 'Welcome' }], completed: ['intro'], complete: true, hint: null },
};

describe('shouldShowFirstRun — the gate opens only when the install needs help', () => {
  it('true when no model is reachable', () => {
    expect(shouldShowFirstRun(COLD)).toBe(true);
  });
  it('true when the wizard is incomplete even with a model', () => {
    expect(shouldShowFirstRun({ ...READY, wizard: { ...READY.wizard, complete: false } })).toBe(true);
  });
  it('false when model ready AND wizard complete', () => {
    expect(shouldShowFirstRun(READY)).toBe(false);
  });
  it('false on missing/failed data (never block the cockpit on an error)', () => {
    expect(shouldShowFirstRun(null)).toBe(false);
    expect(shouldShowFirstRun(undefined)).toBe(false);
  });
});

describe('FirstRunGate — the Command Center as the landing surface', () => {
  it('renders the command center front and center with the setup hint', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => COLD });
    render(<FirstRunGate onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText('COMMAND CENTER')).toBeTruthy());
    expect(screen.getByText(/FIRST RUN/)).toBeTruthy();
    expect(screen.getByText(/No model backend reachable/)).toBeTruthy();
  });

  it('dismiss closes and persists so it never nags twice', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => COLD });
    const onClose = vi.fn();
    render(<FirstRunGate onClose={onClose} />);
    await waitFor(() => expect(screen.getByText('COMMAND CENTER')).toBeTruthy());
    fireEvent.click(screen.getByText(/continue to cockpit/i));
    expect(onClose).toHaveBeenCalled();
    expect(localStorage.getItem(FIRST_RUN_DISMISS_KEY)).toBe('1');
  });
});
