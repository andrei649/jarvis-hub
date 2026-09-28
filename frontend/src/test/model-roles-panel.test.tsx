import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { ModelInfoPanel } from '../gap';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('shows configured roles without claiming model reachability or a video consumer', async () => {
  const fetcher = vi.fn(async (url: string) => ({
    ok: true, status: 200,
    json: async () => url === '/api/llm/roles' ? { reachable: null, roles: [
      { role: 'approval_judge', configured: true, provider: 'lm-studio', model: 'judge-model', local: true },
      { role: 'video', configured: true, provider: 'ollama', model: 'video-model', local: true, note: 'Declared only; no consumer' },
      { role: 'vision', configured: false, reason: 'vlm_model_unset' },
    ] } : { enabled: false, models: [] },
  }));
  vi.stubGlobal('fetch', fetcher);
  render(<ModelInfoPanel />);
  await waitFor(() => expect(screen.getByText(/judge-model/)).toBeTruthy());
  expect(screen.getByText(/Connectivity has not been checked/)).toBeTruthy();
  expect(screen.getByText('Declared only; no consumer')).toBeTruthy();
  expect(screen.getByText(/vlm_model_unset/)).toBeTruthy();
  expect(fetcher.mock.calls.some(([url]) => url === '/api/llm/roles')).toBe(true);
});

it('keeps model fingerprints usable when role configuration is unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: url !== '/api/llm/roles', status: url === '/api/llm/roles' ? 503 : 200,
    json: async () => ({ enabled: true, models: [{ id: 'resident-model' }], stats: { total: 1 } }),
  })));
  render(<ModelInfoPanel />);
  await waitFor(() => expect(screen.getByText('resident-model')).toBeTruthy());
  expect(screen.getByText('MODEL ROLES')).toBeTruthy();
  expect(screen.queryByText(/judge-model/)).toBeNull();
});
