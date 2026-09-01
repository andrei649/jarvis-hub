// @ts-nocheck
/* DRA-15 (H21 cognition cut) — the six user-tier cognition reads
   (/api/cognition/status|honesty|personality|memory|learning|ensemble) shipped with no
   client caller anywhere, so the whole H21 subsystem was invisible from the Console.
   These pin (a) that all six are actually fetched, (b) that a disabled subsystem renders
   as disabled rather than blank, (c) that a module reporting available:false renders an
   explicit "unavailable" instead of a silent 0, and (d) that the panel is reachable from
   the Observe section. fetch is mocked (like pending-skills-panel.test.tsx). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { CognitionPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const PATHS = [
  '/api/cognition/status',
  '/api/cognition/honesty',
  '/api/cognition/personality',
  '/api/cognition/memory',
  '/api/cognition/learning',
  '/api/cognition/ensemble',
];

function mockApi(map) {
  const fn = vi.fn().mockImplementation((url) => {
    const payload = map[String(url)] ?? {};
    return Promise.resolve({ ok: true, status: 200, json: async () => payload });
  });
  global.fetch = fn;
  return fn;
}

const ALL_OFF = {
  '/api/cognition/status': {
    enabled: false, available: true,
    flags: { honesty_enabled: false, affect_enabled: false, memory_enabled: false,
             learning_enabled: false, personality_enabled: false, review_enabled: false },
    modules: ['honesty', 'memory'],
  },
  '/api/cognition/honesty': { available: true, sycophancy_index: 0.8, alerting: true, threshold: 0.6, n: 12 },
  '/api/cognition/personality': { available: true, agents: ['jarvis', 'argus'] },
  '/api/cognition/memory': { available: true, core: 4, user_core: 2, embed_version: 'v3', tiers: {} },
  '/api/cognition/learning': { available: true, kc_count: 7, corrections: 1 },
  '/api/cognition/ensemble': { available: false },
};

describe('CognitionPanel — the H21 subsystem is readable from the Console', () => {
  it('fetches every one of the six cognition reads', async () => {
    const fn = mockApi(ALL_OFF);
    render(<CognitionPanel />);
    await waitFor(() => expect(screen.getByText('COGNITION (H21)')).toBeTruthy());
    for (const p of PATHS) {
      await waitFor(() => expect(fn.mock.calls.some((c) => String(c[0]) === p)).toBe(true));
    }
  });

  it('renders a disabled subsystem as disabled (SEED chip + off flags), not blank', async () => {
    mockApi(ALL_OFF);
    render(<CognitionPanel />);
    await waitFor(() => expect(screen.getByText('SEED')).toBeTruthy());
    // one row per sub-flag, each reading "off"
    await waitFor(() => expect(screen.getAllByText('off').length).toBeGreaterThanOrEqual(6));
    expect(screen.getByText('honesty')).toBeTruthy();
    expect(screen.getByText('review')).toBeTruthy();
    expect(screen.getByText('0/6 on')).toBeTruthy();
  });

  it('renders the honesty index and its alerting state', async () => {
    mockApi(ALL_OFF);
    render(<CognitionPanel />);
    await waitFor(() => expect(screen.getByText('sycophancy 0.80')).toBeTruthy());
    expect(screen.getByText('alerting')).toBeTruthy();
    expect(screen.getByText('12 sample(s)')).toBeTruthy();
    // the other modules' real numbers, not placeholders
    expect(screen.getByText('2 persona(s)')).toBeTruthy();
    expect(screen.getByText('core 4 · user 2')).toBeTruthy();
    expect(screen.getByText('7 kc')).toBeTruthy();
  });

  it('says "unavailable" for a module that reports available:false instead of showing 0', async () => {
    mockApi(ALL_OFF);
    render(<CognitionPanel />);
    // ensemble is available:false in the fixture
    await waitFor(() => expect(screen.getByText('unavailable')).toBeTruthy());
    expect(screen.queryByText('0 agent(s) · diversity 0')).toBeNull();
  });

  it('renders the master flag as live when cognition is switched on', async () => {
    mockApi({ ...ALL_OFF, '/api/cognition/status': {
      enabled: true, available: true,
      flags: { honesty_enabled: true, affect_enabled: false, memory_enabled: true,
               learning_enabled: false, personality_enabled: false, review_enabled: false },
      modules: ['honesty', 'memory'],
    } });
    render(<CognitionPanel />);
    await waitFor(() => expect(screen.getByText('LIVE')).toBeTruthy());
    expect(screen.getByText('2/6 on')).toBeTruthy();
  });

  it('is registered in the Observe section so the Console can reach it', () => {
    const src = readFileSync(join(process.cwd(), 'src', 'gap.tsx'), 'utf8');
    const observe = src.match(/\['Observe', \[([^\]]*)\]\]/);
    expect(observe).toBeTruthy();
    expect(observe[1]).toContain('CognitionPanel');
  });
});
