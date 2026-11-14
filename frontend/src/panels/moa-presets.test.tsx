// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MoaPresetsPanel } from './moa-presets';

const samplePreset = {
  name: 'council',
  model_id: 'moa:council',
  description: 'Local fast + deep synthesis',
  proposers: ['local', 'local-deep'],
  aggregator: 'local-deep',
  min_quorum: 2,
  timeout_s: 45,
  temperature: 0.6,
  pure_local: true,
};

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('MoaPresetsPanel (H032)', () => {
  it('lists presets, saves, activates, runs synthesis, clears active, and deletes', async () => {
    let presets = [];
    let active = null;
    const calls: Array<[string, string]> = [];

    global.fetch = vi.fn(async (url, init = {}) => {
      const u = String(url);
      const method = (init.method || 'GET').toUpperCase();
      calls.push([method, u]);

      if (method === 'GET' && u.endsWith('/api/llm/moa/presets')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ presets, active, recent_runs: [] }),
        };
      }
      if (method === 'PUT' && u.endsWith('/api/llm/moa/presets/council')) {
        presets = [samplePreset];
        return {
          ok: true,
          status: 200,
          json: async () => ({ ok: true, preset: samplePreset }),
        };
      }
      if (method === 'POST' && u.endsWith('/api/llm/moa/active')) {
        const body = JSON.parse(init.body || '{}');
        active = body.name || null;
        return {
          ok: true,
          status: 200,
          json: async () => ({ ok: true, active }),
        };
      }
      if (method === 'POST' && u.endsWith('/api/llm/moa/run')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            model: 'moa:council',
            route: 'local-moa',
            answer: 'Synthesized committee response',
            telemetry: {
              ts: 1,
              preset: 'council',
              agent: 'jarvis',
              ok: true,
              quorum_met: true,
              succeeded: 2,
              min_quorum: 2,
              total_proposers: 2,
              proposer_wall_ms: 82,
              sum_proposer_ms: 160,
              parallel_speedup: 1.95,
              total_ms: 110,
              proposers: [],
            },
          }),
        };
      }
      if (method === 'DELETE' && u.endsWith('/api/llm/moa/presets/council')) {
        presets = [];
        active = null;
        return {
          ok: true,
          status: 200,
          json: async () => ({ ok: true, deleted: 'council', active: null }),
        };
      }
      return { ok: false, status: 404, json: async () => ({ error: 'not_found' }) };
    });

    render(<MoaPresetsPanel />);
    await screen.findByText(/no MoA presets configured yet/);

    fireEvent.change(screen.getByLabelText('preset name'), { target: { value: 'council' } });
    fireEvent.change(screen.getByLabelText('proposer specs'), { target: { value: 'local,local-deep' } });
    fireEvent.change(screen.getByLabelText('aggregator spec'), { target: { value: 'local-deep' } });
    fireEvent.click(screen.getByText('save preset'));

    await screen.findByText('saved moa:council');
    expect(screen.getByText('moa:council')).toBeTruthy();

    fireEvent.click(screen.getByText('activate council'));
    await screen.findByText('activated moa:council');

    fireEvent.change(screen.getByLabelText('committee prompt'), { target: { value: 'Compare RAID-1 vs ZFS mirror' } });
    fireEvent.click(screen.getByText('run committee'));
    await screen.findByText('Synthesized committee response');
    expect(screen.getByText(/speedup 1.95x/)).toBeTruthy();

    fireEvent.click(screen.getByText('clear active'));
    await screen.findByText('cleared active MoA preset');

    fireEvent.click(screen.getByText('delete council'));
    await screen.findByText('deleted moa:council');

    await waitFor(() => {
      expect(calls.some(([m, u]) => m === 'PUT' && u.endsWith('/api/llm/moa/presets/council'))).toBe(true);
      expect(calls.some(([m, u]) => m === 'POST' && u.endsWith('/api/llm/moa/active'))).toBe(true);
      expect(calls.some(([m, u]) => m === 'POST' && u.endsWith('/api/llm/moa/run'))).toBe(true);
      expect(calls.some(([m, u]) => m === 'DELETE' && u.endsWith('/api/llm/moa/presets/council'))).toBe(true);
    });
  });
});
