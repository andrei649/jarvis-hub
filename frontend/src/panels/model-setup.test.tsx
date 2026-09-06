// @ts-nocheck
/* MODEL SETUP panel — `fetch` is mocked (not api/client) so the REAL client path runs:
   apiPost THROWS on 4xx, so a refusal branch that is never wired would be dead code here.

   Claims pinned:
   · the plan is read from the backend and the pick + its "not benchmarked" basis render verbatim;
   · an unreachable Ollama renders the backend's reason (amber SEED chip), not an empty list;
   · with the flag unset the pull button is withheld and the backend's hint is shown;
   · the pull POSTs the recommended model tag and renders "pull started";
   · a 403 kernel refusal reaches the screen with the backend reason and no success line;
   · a 202 queue is rendered as queued, never as started. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ModelSetupPanel } from './model-setup';

const PLAN = {
  hardware: { gpu: { name: 'RTX 4070', kind: 'nvidia', vram_total_mb: 12282, measured: true }, cpu_threads: 16, ram_total_gb: 64 },
  recommendation: {
    tier: '12-16gb', model: 'qwen2.5:14b', approx_gb: 9, gpu_kind: 'nvidia', vram_mb: 12282,
    basis: 'spec-based, not benchmarked',
    reasons: ['RTX 4070 · 12282 MB usable VRAM (nvidia)', '64 GB RAM', 'fits a 12–16 GB card at Q4'],
  },
  tiers: [],
  ollama: { present: true, url: 'http://localhost:11434', models: ['qwen2.5:3b'], reason: '' },
  recommended_installed: false,
  pull: { enabled: true, max_gb: 20, job: null, hint: null },
  basis: 'spec-based, not benchmarked',
};

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });
const refuse = (status, payload) => ({ ok: false, status, json: async () => payload });

/* route-keyed, most-specific first (String(url).includes) */
function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve(hit ? hit[1] : ok({}));
  });
  global.fetch = fn;
  return fn;
}

const postTo = (fn, path) => fn.mock.calls.find((c) => String(c[0]).includes(path) && c[1] && c[1].method === 'POST');

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('ModelSetupPanel — the zero-key first-value card, wired honestly', () => {
  it('GETs the plan and renders the pick with its spec-based basis verbatim', async () => {
    const fn = mockFetch({ '/api/onboarding/model-plan': ok(PLAN) });
    render(<ModelSetupPanel />);
    await waitFor(() => expect(screen.getByText('qwen2.5:14b')).toBeTruthy());
    expect(screen.getByText('spec-based, not benchmarked')).toBeTruthy();
    expect(screen.getByText('RTX 4070 · 12282 MB')).toBeTruthy();
    expect(screen.getByText('qwen2.5:3b')).toBeTruthy();       // installed row
    expect(screen.getByText('LIVE')).toBeTruthy();
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/onboarding/model-plan'))).toBe(true);
  });

  it('renders the backend reason when Ollama is not reachable, under a SEED chip', async () => {
    mockFetch({ '/api/onboarding/model-plan': ok({ ...PLAN, ollama: { present: false, url: 'http://localhost:11434', models: [], reason: 'ollama_unreachable' }, recommended_installed: false }) });
    render(<ModelSetupPanel />);
    await waitFor(() => expect(screen.getByText(/ollama_unreachable/)).toBeTruthy());
    expect(screen.getByText('SEED')).toBeTruthy();
    expect(screen.getByText('pull qwen2.5:14b').disabled).toBe(true);
  });

  it('withholds the pull and shows the hint while the flag is unset', async () => {
    const fn = mockFetch({ '/api/onboarding/model-plan': ok({ ...PLAN, pull: { enabled: false, max_gb: 20, job: null, hint: 'set JARVIS_MODEL_PULL=1 to allow governed pulls' } }) });
    render(<ModelSetupPanel />);
    await waitFor(() => expect(screen.getByText(/pulls disabled/)).toBeTruthy());
    expect(screen.getByText(/JARVIS_MODEL_PULL=1/)).toBeTruthy();
    const btn = screen.getByText('pull qwen2.5:14b');
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(postTo(fn, '/api/onboarding/model-pull')).toBeUndefined();
  });

  it('POSTs the recommended tag and renders that the pull started', async () => {
    const fn = mockFetch({
      '/api/onboarding/model-pull': ok({ ok: true, enabled: true, status: 'completed', reason: '', model: 'qwen2.5:14b', output: { ok: true, started: true } }),
      '/api/onboarding/model-plan': ok(PLAN),
    });
    render(<ModelSetupPanel />);
    await waitFor(() => expect(screen.getByText('qwen2.5:14b')).toBeTruthy());
    fireEvent.click(screen.getByText('pull qwen2.5:14b'));
    await waitFor(() => expect(screen.getByText(/pull started · qwen2.5:14b/)).toBeTruthy());
    const post = postTo(fn, '/api/onboarding/model-pull');
    expect(JSON.parse(post[1].body)).toEqual({ model: 'qwen2.5:14b' });
  });

  it('renders a 403 kernel refusal with the backend reason and no success line', async () => {
    mockFetch({
      '/api/onboarding/model-pull': refuse(403, { ok: false, status: 'refused', reason: 'kill switch engaged' }),
      '/api/onboarding/model-plan': ok(PLAN),
    });
    render(<ModelSetupPanel />);
    await waitFor(() => expect(screen.getByText('qwen2.5:14b')).toBeTruthy());
    fireEvent.click(screen.getByText('pull qwen2.5:14b'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('refused · kernel denied'));
    expect(screen.getByRole('alert').textContent).toContain('kill switch engaged');
    expect(screen.queryByText(/pull started/)).toBeNull();
  });

  it('renders a queued pull as queued, never as started', async () => {
    mockFetch({
      '/api/onboarding/model-pull': ok({ ok: false, enabled: true, status: 'queued', reason: 'ask', model: 'qwen2.5:14b', output: null }),
      '/api/onboarding/model-plan': ok(PLAN),
    });
    render(<ModelSetupPanel />);
    await waitFor(() => expect(screen.getByText('qwen2.5:14b')).toBeTruthy());
    fireEvent.click(screen.getByText('pull qwen2.5:14b'));
    await waitFor(() => expect(screen.getByText(/queued for approval · ask/)).toBeTruthy());
    expect(screen.queryByText(/pull started/)).toBeNull();
  });

  it('renders a running job with its bytes and holds the button (one pull at a time)', async () => {
    mockFetch({
      '/api/onboarding/model-plan': ok({ ...PLAN, pull: { enabled: true, max_gb: 20, hint: null, job: { id: 'j1', model: 'qwen2.5:14b', status: 'running', stage: 'pulling', bytes_total: 4 * 1024 ** 3, bytes_completed: 1024 ** 3, reason: '' } } }),
    });
    render(<ModelSetupPanel />);
    await waitFor(() => expect(screen.getByTestId('pull-job').textContent).toContain('qwen2.5:14b · running · pulling · 1.0 / 4.0 GB'));
    expect(screen.getByText('pull qwen2.5:14b').disabled).toBe(true);
  });
});
