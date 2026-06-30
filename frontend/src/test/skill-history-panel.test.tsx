// @ts-nocheck
/* 0.58 — the Console SkillHistoryPanel reads the version-history read surface
   (GET /api/skills/marketplace/history, admin) and renders publish/install/uninstall
   events + per-action stats. fetch is mocked (like readiness-panel.test.tsx). Asserts
   the wiring, the event rows, and the honesty banner when the ledger is disabled. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { SkillHistoryPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('SkillHistoryPanel — the version-history read surface is live', () => {
  it('GETs the history endpoint and renders events + per-action stats', async () => {
    const fn = mockFetch({
      enabled: true,
      stats: { total: 3, skills: 1, by_action: { publish: 1, install: 2 } },
      events: [
        { id: 'sh-1', name: 'weather', action: 'install', version: '2.0.0' },
        { id: 'sh-2', name: 'weather', action: 'install', version: '1.0.0' },
      ],
    });
    render(<SkillHistoryPanel />);
    // both events are named 'weather' → getAllByText (multiple matches)
    await waitFor(() => expect(screen.getAllByText('weather').length).toBe(2));
    // hit the right (admin) endpoint
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/skills/marketplace/history'))).toBe(true);
    // per-action stat tags + an event detail (the 2.0.0 row is unique)
    expect(screen.getByText('2 install')).toBeTruthy();
    expect(screen.getByText(/install · 2\.0\.0/)).toBeTruthy();
  });

  it('shows the honesty banner when the ledger is disabled (flag off)', async () => {
    mockFetch({ enabled: false, events: [], stats: { total: 0, skills: 0, by_action: {} } });
    render(<SkillHistoryPanel />);
    await waitFor(() => expect(screen.getByText(/JARVIS_SKILL_HISTORY is on/)).toBeTruthy());
  });
});
