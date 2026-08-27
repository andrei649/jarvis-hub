// @ts-nocheck
/* ActivityTimelinePanel (H34.6) — the "what it did" feed in Projects.

   BACKLOG's H34.6 row promises this panel shows "Titles/decisions/status only —
   never payload/result (no tier leak)". That guarantee lived only in the prose:
   the panel shipped in #724 with zero tests, while every sibling panel it renders
   beside (RoomsPanel, MissionsPanel, SessionsPanel) has one. These tests pin the
   guarantee to the component so a future edit to the row mapper can't quietly
   start rendering task payloads.

   fetch is mocked and both endpoints are the REAL ones the panel calls:
     GET /api/admin/audit?limit=40  (admin-guarded)
     GET /tasks?view=history        (user)
   The audit response shape follows agents/core/routers/admin.py:220, whose SQL
   selects `content_preview AS summary` — so `summary` is the field the API
   actually returns. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ActivityTimelinePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve({ ok: true, status: 200, json: async () => (hit ? hit[1] : {}) });
  });
  global.fetch = fn;
  return fn;
}

describe('ActivityTimelinePanel (H34.6) — the no-tier-leak guarantee', () => {
  it('renders a task title + decision but never its payload, result or error body', async () => {
    mockFetch({
      '/api/admin/audit': { rows: [] },
      '/tasks': {
        tasks: [{
          id: 't1',
          kind: 'email.send',
          title: 'Send the quarterly update',
          decision: 'approved',
          status: 'done',
          created_at: '2026-07-24T10:00:00',
          // None of the following may ever reach the DOM:
          payload: { to: 'investor@example.com', body: 'SECRET-PAYLOAD-BODY' },
          result: 'SECRET-RESULT-TEXT',
          error: 'SECRET-ERROR-TRACE',
        }],
      },
    });

    const { container } = render(<ActivityTimelinePanel />);
    await waitFor(() => expect(screen.getByText(/Send the quarterly update/)).toBeTruthy());

    // What it promises to show: the title, and the decision (which wins over status).
    expect(container.textContent).toContain('Send the quarterly update');
    expect(container.textContent).toContain('approved');
    expect(container.textContent).toContain('email.send');

    // What it promises never to show.
    expect(container.textContent).not.toContain('SECRET-PAYLOAD-BODY');
    expect(container.textContent).not.toContain('SECRET-RESULT-TEXT');
    expect(container.textContent).not.toContain('SECRET-ERROR-TRACE');
    expect(container.textContent).not.toContain('investor@example.com');
  });

  it('falls back to status only when a task carries no decision', async () => {
    mockFetch({
      '/api/admin/audit': { rows: [] },
      '/tasks': {
        tasks: [{
          id: 't2', kind: 'calendar.hold', title: 'Hold Friday review',
          status: 'blocked', created_at: '2026-07-24T09:00:00',
          result: 'SECRET-RESULT-TEXT',
        }],
      },
    });

    const { container } = render(<ActivityTimelinePanel />);
    await waitFor(() => expect(screen.getByText(/Hold Friday review/)).toBeTruthy());
    expect(container.textContent).toContain('blocked');
    expect(container.textContent).not.toContain('SECRET-RESULT-TEXT');
  });

  it('renders audit rows from `summary` — the field admin.py aliases content_preview to', async () => {
    mockFetch({
      '/api/admin/audit': {
        rows: [{ timestamp: '2026-07-24T11:00:00', event_type: 'settings.update', summary: 'settings.autonomy updated: [mode]' }],
      },
      '/tasks': { tasks: [] },
    });

    const { container } = render(<ActivityTimelinePanel />);
    await waitFor(() => expect(screen.getByText(/settings.autonomy updated/)).toBeTruthy());
    expect(container.textContent).toContain('settings.update');
  });

  it('drops rows with no timestamp instead of sorting them to the top', async () => {
    mockFetch({
      '/api/admin/audit': { rows: [{ event_type: 'orphan.event', summary: 'UNDATED-AUDIT-ROW' }] },
      '/tasks': {
        tasks: [
          { id: 'a', kind: 'k', title: 'DATED-TASK', created_at: '2026-07-24T08:00:00' },
          { id: 'b', kind: 'k', title: 'UNDATED-TASK' },
        ],
      },
    });

    const { container } = render(<ActivityTimelinePanel />);
    await waitFor(() => expect(screen.getByText(/DATED-TASK/)).toBeTruthy());
    expect(container.textContent).not.toContain('UNDATED-AUDIT-ROW');
    expect(container.textContent).not.toContain('UNDATED-TASK');
  });

  it('orders the fused feed newest-first across both sources', async () => {
    mockFetch({
      '/api/admin/audit': { rows: [{ timestamp: '2026-07-24T12:00:00', event_type: 'e', summary: 'NEWEST-AUDIT' }] },
      '/tasks': {
        tasks: [
          { id: 'a', kind: 'k', title: 'MIDDLE-TASK', created_at: '2026-07-24T11:00:00' },
          { id: 'b', kind: 'k', title: 'OLDEST-TASK', created_at: '2026-07-24T10:00:00' },
        ],
      },
    });

    const { container } = render(<ActivityTimelinePanel />);
    await waitFor(() => expect(screen.getByText(/NEWEST-AUDIT/)).toBeTruthy());
    const text = container.textContent;
    expect(text.indexOf('NEWEST-AUDIT')).toBeLessThan(text.indexOf('MIDDLE-TASK'));
    expect(text.indexOf('MIDDLE-TASK')).toBeLessThan(text.indexOf('OLDEST-TASK'));
  });

  it('filters the fused feed down to one source and back', async () => {
    mockFetch({
      '/api/admin/audit': { rows: [{ timestamp: '2026-07-24T12:00:00', event_type: 'e', summary: 'AUDIT-ONLY-ROW' }] },
      '/tasks': { tasks: [{ id: 'a', kind: 'k', title: 'TASK-ONLY-ROW', created_at: '2026-07-24T11:00:00' }] },
    });

    const { container } = render(<ActivityTimelinePanel />);
    await waitFor(() => expect(screen.getByText(/AUDIT-ONLY-ROW/)).toBeTruthy());
    expect(container.textContent).toContain('TASK-ONLY-ROW');

    fireEvent.click(screen.getByText('audit'));
    await waitFor(() => expect(container.textContent).not.toContain('TASK-ONLY-ROW'));
    expect(container.textContent).toContain('AUDIT-ONLY-ROW');

    fireEvent.click(screen.getByText('tasks'));
    await waitFor(() => expect(container.textContent).not.toContain('AUDIT-ONLY-ROW'));
    expect(container.textContent).toContain('TASK-ONLY-ROW');

    fireEvent.click(screen.getByText('all'));
    await waitFor(() => expect(container.textContent).toContain('AUDIT-ONLY-ROW'));
    expect(container.textContent).toContain('TASK-ONLY-ROW');
  });

  it('caps the feed at 40 rows', async () => {
    const tasks = Array.from({ length: 60 }, (_, i) => ({
      id: `t${i}`, kind: 'k',
      title: `TASK-${String(i).padStart(2, '0')}`,
      // Descending timestamps: TASK-00 newest, TASK-59 oldest.
      created_at: `2026-07-24T${String(23 - Math.floor(i / 3)).padStart(2, '0')}:00:00`,
    }));
    mockFetch({ '/api/admin/audit': { rows: [] }, '/tasks': { tasks } });

    const { container } = render(<ActivityTimelinePanel />);
    await waitFor(() => expect(screen.getByText(/TASK-00/)).toBeTruthy());
    // The 41st-oldest onwards must be cut.
    expect(container.textContent).not.toContain('TASK-59');
  });

  it('shows an honest empty state rather than a blank card', async () => {
    mockFetch({ '/api/admin/audit': { rows: [] }, '/tasks': { tasks: [] } });
    const { container } = render(<ActivityTimelinePanel />);
    await waitFor(() => expect(container.textContent).toContain('no activity yet'));
  });
});
