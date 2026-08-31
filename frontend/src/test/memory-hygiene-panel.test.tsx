// @ts-nocheck
/* DRA-27 (hygiene cut) — `GET /api/memory/decay/candidates` had no client caller, so the
   forget loop was half-built: KgPanel could forget an item by id, but nothing said which ids
   had decayed far enough to be worth forgetting. Also pins the KgPanel refusal fix: its old
   `r.error ? 'not found'` branch was DEAD because apiPost throws on the 404. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryHygienePanel, KgPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const CANDIDATES = {
  threshold: 0.3,
  candidates: [
    { id: 'm-1', activation: 0.08, label: 'stale note about a closed ticket' },
    { id: 'm-2', activation: 0.21, label: '' },
  ],
};

/* GET → gets; POST → posts. `posts` records every POST url for assertions. */
function mockApi({ get = CANDIDATES, post = { ok: true, removed: ['m-1', 'm-9'] }, postStatus = 200 } = {}) {
  const fn = vi.fn().mockImplementation((url, init) => {
    const isPost = (init && init.method) === 'POST';
    const payload = isPost ? post : get;
    const ok = !isPost || postStatus < 400;
    return Promise.resolve({ ok, status: isPost ? postStatus : 200, json: async () => payload });
  });
  global.fetch = fn;
  return fn;
}

describe('MemoryHygienePanel — decay candidates are visible and forgettable', () => {
  it('lists candidates below the threshold with their activation', async () => {
    const fn = mockApi();
    render(<MemoryHygienePanel />);

    await waitFor(() => expect(screen.getByText('stale note about a closed ticket')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/memory/decay/candidates?threshold=0.3'))).toBe(true);
    expect(screen.getByText('0.08')).toBeTruthy();
    // an unlabelled item still has to be identifiable — it falls back to its id
    expect(screen.getByText('m-2')).toBeTruthy();
  });

  it('refetches at a new threshold rather than filtering the old list client-side', async () => {
    const fn = mockApi();
    render(<MemoryHygienePanel />);
    await waitFor(() => expect(screen.getByText('stale note about a closed ticket')).toBeTruthy());

    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '0.9' } });

    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('threshold=0.9')),
    ).toBe(true));
  });

  it('reports how many items a transitive forget actually removed', async () => {
    const fn = mockApi();
    render(<MemoryHygienePanel />);
    await waitFor(() => expect(screen.getByText('stale note about a closed ticket')).toBeTruthy());

    fireEvent.click(screen.getAllByTitle(/forget this item/)[0]);

    // decay.forget removes the item AND its dependents; saying "1" would understate it.
    await waitFor(() => expect(screen.getByText('forgot m-1 · 2 item(s)')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/memory/decay/forget'))).toBe(true);
  });

  it('surfaces a 404 forget instead of reporting success', async () => {
    mockApi({ post: { error: 'not found' }, postStatus: 404 });
    render(<MemoryHygienePanel />);
    await waitFor(() => expect(screen.getByText('stale note about a closed ticket')).toBeTruthy());

    fireEvent.click(screen.getAllByTitle(/forget this item/)[0]);

    await waitFor(() => expect(screen.getByText('not found · m-1')).toBeTruthy());
  });
});

describe('KgPanel — the forget-by-id refusal was a dead branch', () => {
  it('shows a 404 for an unknown id rather than silently clearing the box', async () => {
    mockApi({ get: { entities: [] }, post: { error: 'not found' }, postStatus: 404 });
    render(<KgPanel />);

    fireEvent.change(screen.getByPlaceholderText('memory item id to forget'), { target: { value: 'nope' } });
    fireEvent.click(screen.getByText('forget'));

    // apiPost throws on the 404, so this only appears because forget() passes onErr.
    await waitFor(() => expect(screen.getByText('not found · nope')).toBeTruthy());
  });
});
