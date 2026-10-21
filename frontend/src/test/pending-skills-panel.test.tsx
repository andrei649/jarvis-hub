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
    expect(screen.getByText(/safe outcome/)).toBeTruthy();
  });
});

/* H331 — the gate completed: the whole content before approval, a discard, and one move
   over several pending skills, proposals and batches. fetch answers by URL. */
const DETAIL = {
  name: 'tidy-notes', folder: 'tidy_notes', quarantined: true, more_files: 0,
  review_note: 'agent=pepper\ntask=tidy the notes\n',
  warnings: [{ path: 'main.py', rule: 'subprocess-shell', line: 3, message: 'x' }],
  files: [
    { path: 'SKILL.md', size: 40, text: '# Tidy Notes\nsteps', truncated: false },
    { path: 'main.py', size: 60, text: 'async def tidy(args):\n    return "ok"', truncated: false },
    { path: 'blob.bin', size: 4, text: null, binary: true },
  ],
};
const PROPOSALS = { proposals: [{ id: 'p1', skill: 'plan', diff: '-old\n+new', drifted: false, card: 'c1' }], count: 1 };
const BATCHES = { batches: [{ id: 'b1', skills: ['notes', 'alpha'], preview: [], card: 'c2' }], count: 1 };

function routeFetch(extra = {}) {
  const fn = vi.fn().mockImplementation(async (url, init) => {
    const u = String(url);
    const method = (init && init.method) || 'GET';
    const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });
    if (method === 'POST' && u.includes('/api/skills/review/bulk')) {
      return reply(200, extra.bulk || { ok: true, decided: 3, failed: 0, results: [] });
    }
    if (method === 'POST' && u.includes('/discard')) return reply(200, { discarded: true });
    if (u.includes('/api/skills/pending/')) return reply(200, DETAIL);
    if (u.includes('/api/skills/pending')) return reply(200, PENDING);
    if (u.includes('/api/skills/proposals')) return reply(200, PROPOSALS);
    if (u.includes('/api/skills/batches')) return reply(200, BATCHES);
    return reply(200, {});
  });
  global.fetch = fn;
  return fn;
}
const posts = (fn, part) => fn.mock.calls.filter((c) => String(c[0]).includes(part) && c[1] && c[1].method === 'POST');

describe('PendingSkillsPanel — H331 review, discard and bulk decisions', () => {
  it('shows the full SKILL.md and code of a quarantined skill before approval', async () => {
    const fn = routeFetch();
    render(<PendingSkillsPanel />);
    await waitFor(() => expect(screen.getByText('tidy-notes')).toBeTruthy());
    fireEvent.click(screen.getAllByTitle(/^review/)[1]);

    await waitFor(() => expect(screen.getByTestId('pending-detail-tidy-notes')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/skills/pending/tidy-notes'))).toBe(true);
    await waitFor(() => expect(screen.getByText(/async def tidy/)).toBeTruthy());
    expect(screen.getByText(/# Tidy Notes/)).toBeTruthy();
    expect(screen.getByText('main.py')).toBeTruthy();
    expect(screen.getByText(/binary · not shown/)).toBeTruthy();
    expect(screen.getByText(/subprocess-shell/)).toBeTruthy();
    expect(screen.getByText(/agent=pepper/)).toBeTruthy();
  });

  it('discards a pending skill through a two-step confirmation', async () => {
    const fn = routeFetch();
    render(<PendingSkillsPanel />);
    await waitFor(() => expect(screen.getByText('tidy-notes')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('discard tidy-notes'));
    expect(posts(fn, '/discard').length).toBe(0);          // arming alone discards nothing
    fireEvent.click(screen.getByText('discard'));

    await waitFor(() => expect(posts(fn, '/api/skills/tidy-notes/discard').length).toBe(1));
    expect(posts(fn, '/api/skills/summarize-inbox/discard').length).toBe(0);
    await waitFor(() => expect(screen.getByText('discarded tidy-notes')).toBeTruthy());
  });

  it('approves several skills, a proposal and a batch in one move', async () => {
    const fn = routeFetch();
    render(<PendingSkillsPanel />);
    await waitFor(() => expect(screen.getByText('plan')).toBeTruthy());
    await waitFor(() => expect(screen.getByText('notes, alpha')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('select summarize-inbox'));
    fireEvent.click(screen.getByLabelText('select tidy-notes'));
    fireEvent.click(screen.getByLabelText('select change to plan'));
    fireEvent.click(screen.getByLabelText('select batch notes, alpha'));
    expect(screen.getByText('4 selected')).toBeTruthy();
    fireEvent.click(screen.getByText('approve 4'));
    expect(posts(fn, '/api/skills/review/bulk').length).toBe(0);   // arming alone decides nothing
    fireEvent.click(screen.getByText('approve 4 selected'));

    await waitFor(() => expect(posts(fn, '/api/skills/review/bulk').length).toBe(1));
    const body = JSON.parse(posts(fn, '/api/skills/review/bulk')[0][1].body);
    expect(body).toEqual({ approved: true, skills: ['summarize-inbox', 'tidy-notes'], proposals: ['p1'], batches: ['b1'] });
    await waitFor(() => expect(screen.getByText('approved 3')).toBeTruthy());
  });

  it('rejects in bulk and names every item that was not decided', async () => {
    const fn = routeFetch({ bulk: { ok: false, decided: 1, failed: 1, results: [
      { kind: 'skill', id: 'tidy-notes', ok: true }, { kind: 'proposal', id: 'p1', ok: false, error: 'not_pending:approved' }] } });
    render(<PendingSkillsPanel />);
    await waitFor(() => expect(screen.getByText('plan')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('select tidy-notes'));
    fireEvent.click(screen.getByLabelText('select change to plan'));
    fireEvent.click(screen.getByText('reject 2'));
    fireEvent.click(screen.getByText('reject 2 selected'));

    await waitFor(() => expect(posts(fn, '/api/skills/review/bulk').length).toBe(1));
    const body = JSON.parse(posts(fn, '/api/skills/review/bulk')[0][1].body);
    expect(body.approved).toBe(false);
    expect(body.skills).toEqual(['tidy-notes']);
    expect(body.proposals).toEqual(['p1']);
    await waitFor(() => expect(screen.getByText(/1 not decided: p1 \(not_pending:approved\)/)).toBeTruthy());
  });

  it('shows a proposal diff inline on demand', async () => {
    routeFetch();
    render(<PendingSkillsPanel />);
    await waitFor(() => expect(screen.getByText('plan')).toBeTruthy());
    fireEvent.click(screen.getAllByTitle(/^diff — the whole proposed change/)[0]);
    await waitFor(() => expect(screen.getByText(/\+new/)).toBeTruthy());
  });
});
