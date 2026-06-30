// @ts-nocheck
/* H23.2 — the Console ModelInfoPanel reads recorded model fingerprints
   (GET /api/models/info, admin) and renders {id, quant, sha256} per model build.
   fetch is mocked (like comms-rate-panel.test.tsx). Asserts the wiring, model rows,
   and the honesty banner when recording is disabled (flag off). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ModelInfoPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('ModelInfoPanel — the model-fingerprint read surface is live', () => {
  it('GETs /api/models/info and renders model rows with quant/sha', async () => {
    const fn = mockFetch({
      enabled: true,
      stats: { total: 2, with_sha256: 1, with_quant: 2 },
      models: [
        { id: 'qwen2.5-7b-Q4_K_M', version: 'v1', quant: 'Q4_K_M', sha256: 'deadbeefcafe' },
        { id: 'llama3.1:8b', version: '', quant: 'Q8_0', sha256: '' },
      ],
    });
    render(<ModelInfoPanel />);
    await waitFor(() => expect(screen.getByText('qwen2.5-7b-Q4_K_M')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/models/info'))).toBe(true);
    expect(screen.getByText('Q4_K_M · deadbeef')).toBeTruthy();   // quant · sha256[:8]
    expect(screen.getByText('Q8_0')).toBeTruthy();                // no sha → quant only
  });

  it('shows the honesty banner when recording is disabled (flag off)', async () => {
    mockFetch({ enabled: false, models: [], stats: { total: 0, with_sha256: 0, with_quant: 0 } });
    render(<ModelInfoPanel />);
    await waitFor(() => expect(screen.getByText(/JARVIS_MODEL_INFO is on/)).toBeTruthy());
  });
});
