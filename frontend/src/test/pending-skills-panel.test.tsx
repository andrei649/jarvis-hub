// @ts-nocheck
/* DRA-17 — the CDX-8 quarantine review surface. `GET /api/skills/pending` and
   `POST /api/skills/{name}/approve` (both admin) shipped with zero client callers, so the
   owner-approval gate for LLM-authored skill code was backend-only. These assert the panel
   reads the right admin endpoint, renders the quarantine state honestly, and that ✓ posts
   to the approve route for the right skill. fetch is mocked (like skill-history-panel). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { PendingSkillsPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

const PENDING = {
  count: 2,
  pending: [
    { name: 'summarize-inbox', description: 'condense the overnight mail', agents: ['jarvis', 'argus'] },
    { name: 'tidy-notes', description: '', agents: [] },
  ],
};

describe('PendingSkillsPanel — the CDX-8 approval gate is reachable', () => {
  it('GETs the admin pending endpoint and renders each quarantined skill', async () => {
    const fn = mockFetch(PENDING);
    render(<PendingSkillsPanel />);

    await waitFor(() => expect(screen.getByText('summarize-inbox')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/skills/pending'))).toBe(true);

    expect(screen.getByText('tidy-notes')).toBeTruthy();
    expect(screen.getByText('condense the overnight mail')).toBeTruthy();
    // Both rows are quarantined; only the one with agents shows the agent tag.
    expect(screen.getAllByText('quarantined').length).toBe(2);
    expect(screen.getByText('2 agent(s)')).toBeTruthy();
  });

  it('approves the skill the button belongs to, not the first one', async () => {
    const fn = mockFetch(PENDING);
    render(<PendingSkillsPanel />);
    await waitFor(() => expect(screen.getByText('tidy-notes')).toBeTruthy());

    // second row's ✓ — pins that the name is per-row, which a shared handler would break
    fireEvent.click(screen.getAllByTitle(/approve/)[1]);

    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/skills/tidy-notes/approve')),
    ).toBe(true));
    // and never the wrong skill
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/skills/summarize-inbox/approve'))).toBe(false);
  });

  it('states the quarantine property rather than implying the code is live', async () => {
    mockFetch({ count: 0, pending: [] });
    render(<PendingSkillsPanel />);

    await waitFor(() => expect(screen.getByText(/never exec'd in-process until approved/)).toBeTruthy());
    // Approve-only by design: no reject control is offered, and the panel says why.
    expect(screen.getByText(/No reject action/)).toBeTruthy();
    expect(screen.queryByTitle(/reject/)).toBeNull();
  });
});
