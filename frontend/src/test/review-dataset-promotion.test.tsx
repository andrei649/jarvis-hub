// @ts-nocheck
/* DRA-52 — `POST /api/review/{item_id}/dataset` (H9.3b) had no caller anywhere: a reviewed
   turn could be voted on but never promoted into an eval dataset. The refusal path is the
   part worth pinning — `apiPost` RESOLVES on 4xx rather than throwing, so a naive
   `act(...)` handler would treat WFL-088's "item has no prompt to replay" as success and
   silently reload, which is exactly the swallowed-mutation failure gap.tsx:76-80 warns about. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ReviewPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const QUEUE = {
  queue: [
    { id: 'r-1', text_preview: 'a flagged answer about tax', in_dataset: false },
    { id: 'r-2', text_preview: 'already promoted turn', in_dataset: true },
  ],
};

/* GET returns the queue; POST returns whatever `post` says. */
function mockApi(post) {
  const fn = vi.fn().mockImplementation((url, init) => {
    const method = (init && init.method) || 'GET';
    const payload = method === 'POST' ? post : QUEUE;
    return Promise.resolve({ ok: !(payload && payload.error), status: payload && payload.error ? 400 : 200, json: async () => payload });
  });
  global.fetch = fn;
  return fn;
}

describe('ReviewPanel — review-queue → eval-dataset promotion', () => {
  it('promotes a reviewed item and reports the dataset it landed in', async () => {
    const fn = mockApi({ ok: true, dataset: 'review_flagged', version: 3 });
    render(<ReviewPanel />);
    await waitFor(() => expect(screen.getByText(/a flagged answer about tax/)).toBeTruthy());

    fireEvent.click(screen.getByTitle('promote to eval dataset'));

    await waitFor(() => expect(screen.getByText('→ review_flagged v3')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/review/r-1/dataset'))).toBe(true);
  });

  it('shows a WFL-088 refusal instead of reporting a silent success', async () => {
    mockApi({ error: 'item has no prompt to replay' });
    render(<ReviewPanel />);
    await waitFor(() => expect(screen.getByText(/a flagged answer about tax/)).toBeTruthy());

    fireEvent.click(screen.getByTitle('promote to eval dataset'));

    // apiPost rejects on the 400, so this only appears because promote() passes an onErr.
    // Drop that argument and the row stays silent — which is the bug this pins.
    await waitFor(() => expect(screen.getByText('refused · 400')).toBeTruthy());
  });

  it('offers no promote control for an item already in a dataset', async () => {
    mockApi({ ok: true });
    render(<ReviewPanel />);
    await waitFor(() => expect(screen.getByText(/already promoted turn/)).toBeTruthy());

    // Two rows, but only the un-promoted one gets a button; the other states its status.
    expect(screen.getAllByTitle('promote to eval dataset').length).toBe(1);
    expect(screen.getByText('in dataset')).toBeTruthy();
  });
});
