// @ts-nocheck
/* VLM status line on the LOCAL MODELS panel — GET /api/vlm/status is user-guarded
   and deliberately never probes the backend (reachable:null), so the line must say
   "reachable not probed" and never render an up/down claim. */
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { LMStudioPanel } from '../gap';

function mockRoutes(vlmPayload) {
  const fn = vi.fn((url) => Promise.resolve({
    ok: true,
    status: 200,
    json: async () => (String(url).includes('/api/vlm/status') ? vlmPayload : { models: [] }),
  }));
  global.fetch = fn;
  return fn;
}

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

describe('LMStudioPanel VLM status line', () => {
  it('renders the configured backend without claiming reachability', async () => {
    mockRoutes({
      configured: true,
      backend: 'lmstudio',
      base_url: 'http://127.0.0.1:1234',
      default_model: 'qwen-vl',
      local: true,
      reachable: null,
    });
    render(<LMStudioPanel />);
    await waitFor(() => expect(screen.getByText(/VLM · lmstudio · qwen-vl · local · reachable not probed/)).toBeTruthy());
    expect(screen.queryByText(/reachable · (up|down)/i)).toBeNull();
  });

  it('renders the refusal reason when the VLM backend is off', async () => {
    mockRoutes({ configured: false, backend: 'off', reason: 'vlm_backend_unknown', default_model: null, reachable: null });
    render(<LMStudioPanel />);
    await waitFor(() => expect(screen.getByText(/VLM · off · vlm_backend_unknown/)).toBeTruthy());
  });

  it('reads /api/vlm/status with the user token only, never the admin token', async () => {
    localStorage.setItem('hud.admin_token', 'admin-secret');
    const fn = mockRoutes({ configured: false, backend: 'off', reason: 'vlm_backend_unknown', default_model: null, reachable: null });
    render(<LMStudioPanel />);
    await waitFor(() => expect(screen.getByText(/VLM · off/)).toBeTruthy());
    const vlmCall = fn.mock.calls.find(([url]) => String(url).includes('/api/vlm/status'));
    expect(vlmCall[1].headers['X-Admin-Token']).toBeUndefined();
    const modelsCall = fn.mock.calls.find(([url]) => String(url) === '/api/models/local');
    expect(modelsCall[1].headers['X-Admin-Token']).toBe('admin-secret');
  });
});
