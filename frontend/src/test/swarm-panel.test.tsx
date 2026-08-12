// @ts-nocheck
/* Swarm Control panel (H34.4) — reads the real H34.1 feed (/api/swarm/summary,
   open/user-tier) and renders the compact cockpit-summary state: kernel status,
   autonomy funnel, workspaces, and which dev-swarm agents currently hold a
   lock.py lock. fetch is mocked, like self-improvement-panel.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { SwarmPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

const SUMMARY_PAYLOAD = {
  generated_at: 1780900000,
  initialized: true,
  halted: false,
  agents: [
    { id: 'jarvis', model: 'local', events: 12, tokens_out: 400, cost_eur: 0, last_ts: 1780899000 },
    { id: 'friday', model: 'local', events: 0, tokens_out: 0, cost_eur: 0, last_ts: 0 },
  ],
  activity: [],
  autonomy: { stats: {}, mode: 'auto', budget: { remaining: 3, per_day: 4 }, pending_count: 2, pending_preview: [] },
  presence: null,
  missions: [{ id: 'm1' }],
  workflows: { runs: [{ id: 'r1' }, { id: 'r2' }] },
  subagents: { spawns: 5, stats: {} },
  a2a: { enabled: true, pending: 1 },
  dev_locks: {
    known: ['claude', 'codex', 'opencode', 'antigravity'],
    agents: [{ agent: 'opencode', message: 'building oracle', since: 't', age_s: 60, stale: false }],
    components: [{ component: 'web.py', path: '/x/web.py', entity: 'opencode', task: '', age_s: 60, stale: false }],
    available: true,
  },
};

describe('SwarmPanel — the swarm cockpit summary is live', () => {
  it('GETs /api/swarm/summary and shows the kernel + autonomy + workspace state', async () => {
    const fn = mockFetch(SUMMARY_PAYLOAD);
    render(<SwarmPanel />);
    await waitFor(() => expect(screen.getByText('armed')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/swarm/summary'))).toBe(true);
    expect(screen.getByText('1/2 agents active')).toBeTruthy();
    expect(screen.getByText('auto')).toBeTruthy();
    expect(screen.getByText('2 pending')).toBeTruthy();
    expect(screen.getByText('1 missions')).toBeTruthy();
    expect(screen.getByText('2 workflow runs')).toBeTruthy();
    expect(screen.getByText('5 sub-agents')).toBeTruthy();
  });

  it('marks the currently-locked dev-swarm agent distinctly from idle ones', async () => {
    mockFetch(SUMMARY_PAYLOAD);
    render(<SwarmPanel />);
    const opencodeTag = await screen.findByText('opencode');
    const claudeTag = await screen.findByText('claude');
    expect(opencodeTag.style.color).toBe('var(--green)');
    expect(claudeTag.style.color).not.toBe('var(--green)');
  });

  it('shows HALTED in red when the kill-switch is engaged', async () => {
    mockFetch({ ...SUMMARY_PAYLOAD, halted: true });
    render(<SwarmPanel />);
    const tag = await screen.findByText('HALTED');
    expect(tag.style.color).toBe('var(--red)');
  });

  it('degrades honestly when the feed is offline', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('network down'));
    render(<SwarmPanel />);
    await waitFor(() => expect(screen.getByText(/offline/)).toBeTruthy());
    expect(screen.queryByText('armed')).toBeNull();
  });

  it('links out to the full standalone cockpit', async () => {
    mockFetch(SUMMARY_PAYLOAD);
    render(<SwarmPanel />);
    const link = await screen.findByText('open full cockpit →');
    expect(link.closest('a')?.getAttribute('href')).toBe('/mission-control');
  });
});
