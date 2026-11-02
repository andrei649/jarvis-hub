// @ts-nocheck
/* H046 — the TODAY card is the HUD's learning timeline (Hermes `hermes journey`): each
   learned entry carries a stable id, and is edited (PATCH) or forgotten (DELETE, after a
   two-step confirmation) by it under /api/dashboard/today/entries/{entry_id}. The hub
   crosses kg.write, so a halted kernel refuses: the refusal must be shown, never read as
   a success. An action is the hub's record of what it did and has no controls. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { TodayPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const FEED = {
  period: '30d', days: 30,
  counts: { actions: 1, learnings: 1, followups: 1, total: 3 },
  items: [
    { entry_id: 'learning:12', ts: '2026-06-27T11:00:00+00:00', kind: 'learning', category: 'fact', key: 'city', value: 'Bucharest' },
    { entry_id: 'followup:failed_task:task:9', ts: '2026-06-27T10:00:00+00:00', kind: 'followup', reason: 'failed_task', source: 'task', title: 'Failed sync', detail: 'failed autonomy task', id: 9 },
    { entry_id: 'action:7', ts: '2026-06-27T09:00:00+00:00', kind: 'action', title: 'synced calendar', id: 7, tier: 1 },
  ],
};

function hub(answers = {}) {
  const fn = vi.fn().mockImplementation(async (url, init = {}) => {
    const method = init.method || 'GET';
    const key = `${method} ${String(url).replace(/^https?:\/\/[^/]+/, '')}`;
    const answer = answers[key];
    if (answer) return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
    return { ok: true, status: 200, json: async () => FEED };
  });
  global.fetch = fn;
  return fn;
}

const calls = (fn, method) => fn.mock.calls.filter(([, init]) => (init?.method || 'GET') === method);
const ENTRY = '/api/dashboard/today/entries/learning%3A12';

describe('TodayPanel (H046) — edit and forget a learned entry by its id', () => {
  it('edits a learned entry with PATCH and reloads the feed', async () => {
    const fn = hub({ [`PATCH ${ENTRY}`]: { status: 200, body: { ok: true, changed: true, entry: { entry_id: 'learning:12', value: 'Cluj' } } } });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('city: Bucharest')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('edit city'));
    const box = screen.getByLabelText('new text for city');
    expect(box.value).toBe('Bucharest');
    fireEvent.change(box, { target: { value: 'Cluj' } });
    fireEvent.click(screen.getByText('save'));
    await waitFor(() => expect(screen.getByText('saved · city')).toBeTruthy());
    const patch = calls(fn, 'PATCH');
    expect(patch.length).toBe(1);
    expect(String(patch[0][0])).toContain(ENTRY);
    expect(JSON.parse(patch[0][1].body)).toEqual({ value: 'Cluj' });
    expect(calls(fn, 'GET').length).toBeGreaterThan(1);   // reloaded after the save
  });

  it('forgets a learned entry only after the second step, with DELETE', async () => {
    const fn = hub({ [`DELETE ${ENTRY}`]: { status: 200, body: { ok: true, deleted: 'learning:12' } } });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('city: Bucharest')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('forget city'));
    expect(calls(fn, 'DELETE').length).toBe(0);           // armed, not sent
    fireEvent.click(screen.getByText('confirm forget'));
    await waitFor(() => expect(screen.getByText('forgot · city')).toBeTruthy());
    const del = calls(fn, 'DELETE');
    expect(del.length).toBe(1);
    expect(String(del[0][0])).toContain(ENTRY);
  });

  it('shows the kernel refusal and does not claim the edit', async () => {
    hub({ [`PATCH ${ENTRY}`]: { status: 403, body: { error: 'kernel denied: kill switch engaged' } } });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('city: Bucharest')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('edit city'));
    fireEvent.change(screen.getByLabelText('new text for city'), { target: { value: 'Cluj' } });
    fireEvent.click(screen.getByText('save'));
    await waitFor(() => expect(screen.getByText('refused · kernel denied: kill switch engaged')).toBeTruthy());
    expect(screen.queryByText(/saved ·/)).toBeNull();
    expect(screen.getByLabelText('new text for city')).toBeTruthy();   // still open to retry
  });

  it('gives an action and a follow-up no controls, and labels the follow-up', async () => {
    hub();
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('synced calendar')).toBeTruthy());
    expect(screen.getByText('follow-up')).toBeTruthy();
    expect(screen.getByText('Failed sync: failed autonomy task')).toBeTruthy();
    expect(screen.getAllByText('edit').length).toBe(1);    // only the learned entry
    expect(screen.getAllByText('forget').length).toBe(1);
  });
});
