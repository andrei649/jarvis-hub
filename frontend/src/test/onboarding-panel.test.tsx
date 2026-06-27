// @ts-nocheck
/* H23.20 — the Console OnboardingPanel reads the first-run wizard state
   (GET /api/onboarding/wizard) and renders the steps + cold-start hint + a mark-done
   control (POST /api/onboarding/funnel). fetch is mocked, like network-monitor.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { OnboardingPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('OnboardingPanel (H23.20) — first-run wizard state', () => {
  it('GETs the wizard, marks completed steps, and offers "done" on the rest', async () => {
    const fn = mockFetch({
      steps: [{ key: 'intro', title: 'Welcome to Jarvis' }, { key: 'model', title: 'Connect a model' }],
      completed: ['intro'], complete: false, model_ready: true, hint: null,
    });
    render(<OnboardingPanel />);
    await waitFor(() => expect(screen.getByText(/Welcome to Jarvis/)).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/onboarding/wizard'))).toBe(true);
    expect(screen.getByText('1/2')).toBeTruthy();              // progress (1 of 2 done)
    expect(screen.getByText(/Connect a model/)).toBeTruthy();
    expect(screen.getByText('done')).toBeTruthy();             // mark-done on the incomplete step
  });

  it('surfaces the cold-start hint when no model backend is reachable', async () => {
    mockFetch({
      steps: [{ key: 'model', title: 'Connect a model' }], completed: [], complete: false,
      model_ready: false, hint: 'No model backend reachable — start LM Studio or Ollama.',
    });
    render(<OnboardingPanel />);
    await waitFor(() => expect(screen.getByText(/No model backend reachable/)).toBeTruthy());
  });
});
