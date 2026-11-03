// @ts-nocheck
/* H046 — the TODAY card is the HUD's learning timeline (Hermes `hermes journey`): each
   learned entry carries a stable id, and is edited (PATCH) or forgotten (DELETE) by it
   under /api/dashboard/today/entries/{entry_id}, as the admin. What it learned is kept in
   three stores, and forgetting costs what the store says: a note or profile fact keeps an
   undo (two steps), a skill is archived (two steps, no inline edit: its text is a whole
   SKILL.md) and one still awaiting review is discarded, a stored fact is gone for good (a
   typed FORGET). The hub crosses kg.write, so
   a halted kernel refuses: the refusal must be shown, never read as a success. An action
   is the hub's record of what it did and has no controls. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { TodayPanel } from '../gap';

beforeEach(() => {
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
});

const NOTE = 'memory:user:0123456789abcdef';
const FEED = {
  period: '30d', days: 30,
  counts: { actions: 1, learnings: 3, followups: 1, total: 5 },
  items: [
    { entry_id: NOTE, ts: '2026-06-27T12:00:00+00:00', kind: 'learning', store: 'user', label: 'user profile', category: 'user', key: null, value: 'lives in Bucharest' },
    { entry_id: 'skill:tidy-notes', ts: '2026-06-27T11:30:00+00:00', kind: 'learning', store: 'skill', label: 'tidy-notes', category: 'skill', key: 'tidy-notes', value: 'Use when tidying notes' },
    { entry_id: 'learning:12', ts: '2026-06-27T11:00:00+00:00', kind: 'learning', store: 'facts', label: 'fact/city', category: 'fact', key: 'city', value: 'Bucharest' },
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
const path = (id) => '/api/dashboard/today/entries/' + encodeURIComponent(id);
const asAdmin = (call) => expect(call[1].headers['X-Admin-Token']).toBe('adm');

describe('TodayPanel (H046) — what it learned, edited and forgotten by id', () => {
  it('shows the user profile, a learned skill and a stored fact as learned entries', async () => {
    hub();
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('user profile: lives in Bucharest')).toBeTruthy());
    expect(screen.getByText('skill tidy-notes: Use when tidying notes')).toBeTruthy();
    expect(screen.getByText('fact/city: Bucharest')).toBeTruthy();
    expect(screen.getAllByText('learned').length).toBe(3);
  });

  it('edits a profile fact with PATCH as the admin and reloads the feed', async () => {
    const fn = hub({ [`PATCH ${path(NOTE)}`]: { status: 200, body: { ok: true, changed: true, entry: { entry_id: 'memory:user:fedcba9876543210', value: 'lives in Cluj' } } } });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('user profile: lives in Bucharest')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('edit user profile'));
    const box = screen.getByLabelText('new text for user profile');
    expect(box.value).toBe('lives in Bucharest');
    expect(box.maxLength).toBe(300);                         // a ring fact is one line of at most 300
    fireEvent.change(box, { target: { value: 'lives in Cluj' } });
    fireEvent.click(screen.getByText('save'));
    await waitFor(() => expect(screen.getByText('saved · user profile')).toBeTruthy());
    const patch = calls(fn, 'PATCH');
    expect(patch.length).toBe(1);
    expect(String(patch[0][0])).toContain(path(NOTE));
    expect(JSON.parse(patch[0][1].body)).toEqual({ value: 'lives in Cluj' });
    asAdmin(patch[0]);
    expect(calls(fn, 'GET').length).toBeGreaterThan(1);   // reloaded after the save
  });

  it('forgets a profile fact after the second step (an undo is kept), as the admin', async () => {
    const fn = hub({ [`DELETE ${path(NOTE)}`]: { status: 200, body: { ok: true, deleted: NOTE, undo_ref: 'r1' } } });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('user profile: lives in Bucharest')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('forget user profile'));
    expect(calls(fn, 'DELETE').length).toBe(0);           // armed, not sent
    expect(screen.getByText(/an undo is kept/)).toBeTruthy();
    fireEvent.click(screen.getByText('confirm forget'));
    await waitFor(() => expect(screen.getByText('forgot · user profile')).toBeTruthy());
    const del = calls(fn, 'DELETE');
    expect(del.length).toBe(1);
    expect(String(del[0][0])).toContain(path(NOTE));
    asAdmin(del[0]);
  });

  it('archives a learned skill after the second step and offers no inline edit', async () => {
    const fn = hub({ [`DELETE ${path('skill:tidy-notes')}`]: { status: 200, body: { ok: true, deleted: 'skill:tidy-notes', archived_to: '/x' } } });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('skill tidy-notes: Use when tidying notes')).toBeTruthy());
    expect(screen.queryByLabelText('edit skill tidy-notes')).toBeNull();
    fireEvent.click(screen.getByLabelText('archive skill tidy-notes'));
    expect(screen.getByText(/it can be restored/)).toBeTruthy();
    fireEvent.click(screen.getByText('confirm archive'));
    await waitFor(() => expect(screen.getByText('archived · skill tidy-notes')).toBeTruthy());
    asAdmin(calls(fn, 'DELETE')[0]);
    expect(screen.queryByTestId('today-archive-references')).toBeNull();     // nothing names it
  });

  it('tells the owner what still names a skill it archived (H330)', async () => {
    const references = [{ skill: 'tidy-notes', absorbed_into: null, migrated: [], left: [
      { holder: 'bundle', name: 'notes', member: 'tidy-notes' },
      { holder: 'skill', name: 'follow-up', field: 'related_skills' },
      { holder: 'job', id: 'j1', name: 'morning', field: 'prompt', lines: [1] },
    ] }];
    hub({ [`DELETE ${path('skill:tidy-notes')}`]: { status: 200, body: { ok: true, deleted: 'skill:tidy-notes', archived_to: '/x', references } } });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('skill tidy-notes: Use when tidying notes')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('archive skill tidy-notes'));
    fireEvent.click(screen.getByText('confirm archive'));
    await waitFor(() => expect(screen.getByTestId('today-archive-references')).toBeTruthy());
    const shown = screen.getByTestId('today-archive-references').textContent || '';
    expect(shown).toContain('tidy-notes deleted · no absorbing skill');
    expect(shown).toContain('still names it: bundle notes · lists tidy-notes');
    expect(shown).toContain('still names it: skill follow-up · related_skills');
    expect(shown).toContain('still names it: job morning (j1) · prompt');
  });

  it('discards a learned skill still awaiting review (the hub rejects it, never archives it)', async () => {
    const PENDING = { entry_id: 'skill:new-idea', ts: '2026-06-27T11:40:00+00:00', kind: 'learning', store: 'skill', label: 'new-idea', category: 'skill', key: 'new-idea', value: 'Use when ideating', pending_review: true };
    const fn = hub({
      'GET /api/dashboard/today': { status: 200, body: { ...FEED, items: [PENDING, ...FEED.items] } },
      [`DELETE ${path('skill:new-idea')}`]: { status: 200, body: { ok: true, deleted: 'skill:new-idea', discarded: true, archived_to: '/d' } },
    });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('skill new-idea: Use when ideating')).toBeTruthy());
    expect(screen.queryByLabelText('archive skill new-idea')).toBeNull();
    fireEvent.click(screen.getByLabelText('discard skill new-idea'));
    expect(screen.getByText(/it awaits review/)).toBeTruthy();
    fireEvent.click(screen.getByText('confirm discard'));
    await waitFor(() => expect(screen.getByText('discarded · skill new-idea')).toBeTruthy());
    const del = calls(fn, 'DELETE');
    expect(del.length).toBe(1);
    expect(String(del[0][0])).toContain(path('skill:new-idea'));
    asAdmin(del[0]);
  });

  it('forgets a stored fact for good only once FORGET is typed', async () => {
    const fn = hub({ [`DELETE ${path('learning:12')}`]: { status: 200, body: { ok: true, deleted: 'learning:12' } } });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('fact/city: Bucharest')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('forget fact/city'));
    const confirm = screen.getByText('confirm forget');
    expect(confirm.closest('button').disabled).toBe(true);
    fireEvent.click(confirm);
    expect(calls(fn, 'DELETE').length).toBe(0);
    fireEvent.change(screen.getByPlaceholderText('FORGET'), { target: { value: 'FORGET' } });
    fireEvent.click(screen.getByText('confirm forget'));
    await waitFor(() => expect(screen.getByText('forgot · fact/city')).toBeTruthy());
    expect(calls(fn, 'DELETE').length).toBe(1);
  });

  it('shows the kernel refusal and does not claim the edit', async () => {
    hub({ [`PATCH ${path(NOTE)}`]: { status: 403, body: { error: 'kernel denied: kill switch engaged' } } });
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('user profile: lives in Bucharest')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('edit user profile'));
    fireEvent.change(screen.getByLabelText('new text for user profile'), { target: { value: 'lives in Cluj' } });
    fireEvent.click(screen.getByText('save'));
    await waitFor(() => expect(screen.getByText('refused · kernel denied: kill switch engaged')).toBeTruthy());
    expect(screen.queryByText(/saved ·/)).toBeNull();
    expect(screen.getByLabelText('new text for user profile')).toBeTruthy();   // still open to retry
  });

  it('gives an action and a follow-up no controls, and labels the follow-up', async () => {
    hub();
    render(<TodayPanel />);
    await waitFor(() => expect(screen.getByText('synced calendar')).toBeTruthy());
    expect(screen.getByText('follow-up')).toBeTruthy();
    expect(screen.getByText('Failed sync: failed autonomy task')).toBeTruthy();
    expect(screen.getAllByText('edit').length).toBe(2);       // the profile fact and the stored fact
    expect(screen.getAllByText('forget').length).toBe(2);
    expect(screen.getAllByText('archive').length).toBe(1);
  });
});
