// @ts-nocheck
/* Live System Map panel (H34.7) — reads /api/system-map and renders the
   topology SVG with honest per-node statuses. Pins the plan's invariants:
   unknown never renders green, absent edge counters render no number, and
   the panel degrades honestly when the feed is unreachable. fetch is mocked,
   like swarm-panel.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { SystemMapPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 503, json: async () => payload });
  global.fetch = fn;
  return fn;
}

const TOPOLOGY = {
  version: '2026-08-31',
  title: 'Nerva — Live System Map',
  view_box: [0, 40, 1290, 560],
  nodes: [
    { id: 'orch', label: 'Orchestrator', sublabel: 's', type: 'backend', pos: [530, 300], size: [160, 68], health_source: 'orchestrator', href: '/brain' },
    { id: 'local', label: 'Local LLM', sublabel: 's', type: 'backend', pos: [1050, 120], size: [170, 64], health_source: 'local_llm', href: '/admin' },
    { id: 'cloud', label: 'Cloud LLM', sublabel: 's', type: 'cloud', pos: [1050, 480], size: [170, 64], health_source: 'cloud_llm', href: '/admin' },
    { id: 'memory', label: 'Memory', sublabel: 's', type: 'database', pos: [530, 120], size: [160, 64], health_source: 'memory_manager', href: null },
  ],
  edges: [
    { id: 'orch-to-memory', from: 'orch', to: 'memory', label: 'add_turn', activity_source: 'turns_60s' },
    { id: 'orch-to-local', from: 'orch', to: 'local', label: 'x', activity_source: 'local_turns_60s' },
  ],
};

function feed(nodes, edges = {}) {
  return {
    version: 1, topology_version: TOPOLOGY.version, generated_at: 1780900000,
    initialized: true, nodes, edges, topology: TOPOLOGY,
  };
}

describe('SystemMapPanel — the architecture lit by live health', () => {
  it('GETs /api/system-map and renders each node with its reduced status', async () => {
    const fn = mockFetch(feed({
      orch: { status: 'ok', stats: { agents: 18 }, evidence: 'orchestrator' },
      local: { status: 'attention', stats: { available: false }, evidence: 'hybrid_router.local' },
      cloud: { status: 'off', stats: { configured: false }, evidence: 'hybrid_router.cloud' },
      memory: { status: 'unknown', stats: {}, evidence: null },
    }, { 'orch-to-memory': { count: 4, source: 'turns_60s' } }));
    render(<SystemMapPanel />);
    await waitFor(() => expect(screen.getByText('Orchestrator')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/system-map'))).toBe(true);
    expect(screen.getByText('attention')).toBeTruthy();
    expect(screen.getByText('off')).toBeTruthy();
    expect(screen.getByText('unknown')).toBeTruthy();
    // the summary line counts ok nodes and surfaces attention
    expect(screen.getByText('1/4 ok · 1 attention')).toBeTruthy();
  });

  it('unknown never renders green: the unknown node text is not var(--green)', async () => {
    mockFetch(feed({ memory: { status: 'unknown', stats: {}, evidence: null } }));
    render(<SystemMapPanel />);
    await waitFor(() => expect(screen.getByText('Memory')).toBeTruthy());
    const statusText = screen.getAllByText('unknown').find((el) => el.tagName === 'text');
    expect(statusText).toBeTruthy();
    expect(statusText.getAttribute('fill')).not.toBe('var(--green)');
  });

  it('renders a counter only for edges the feed measured', async () => {
    mockFetch(feed(
      { orch: { status: 'ok', stats: {}, evidence: 'x' } },
      { 'orch-to-memory': { count: 7, source: 'turns_60s' } },  // orch-to-local absent
    ));
    render(<SystemMapPanel />);
    await waitFor(() => expect(screen.getByText('7')).toBeTruthy());
    // absent counter → no fabricated number on the other edge
    expect(screen.queryByText('0')).toBeNull();
  });

  it('links out to the standalone wall map', async () => {
    mockFetch(feed({}));
    render(<SystemMapPanel />);
    const link = await screen.findByText('open wall map →');
    expect(link.getAttribute('href')).toBe('/map');
  });

  it('degrades honestly when the feed is unreachable', async () => {
    mockFetch({}, false);
    render(<SystemMapPanel />);
    await waitFor(() => expect(document.querySelector('svg')).toBeNull());
    expect(screen.queryByText('Orchestrator')).toBeNull();
  });
});
