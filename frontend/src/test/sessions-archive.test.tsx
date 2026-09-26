// @ts-nocheck
/* H218 — archive a chat, see the archived ones, bring one back or delete it for good. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { SessionsPanel, archivePath, deletePath, unarchivePath } from '../panels/sessions';

let calls;
let deleteReply;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

beforeEach(() => {
  cleanup();
  calls = [];
  deleteReply = () => reply(200, { ok: true, session: 's-away', backup: '/home/x/backups/sessions/s-away-1.json' });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    calls.push({ url: u, method: init.method || 'GET' });
    if (u.endsWith('/sessions?archived=true')) return reply(200, { sessions: [{ id: 's-away', title: 'Old trip', archived_at: 'x' }] });
    if (u.endsWith('/sessions')) return reply(200, { sessions: [{ id: 's-live', title: 'Today' }] });
    if (u.includes('/archive') || u.includes('/unarchive')) return reply(200, { ok: true });
    if ((init.method || '') === 'DELETE') return deleteReply();
    return reply(404, {});
  });
});

const posts = (m) => calls.filter((c) => c.method === m).map((c) => c.url.replace(/^.*?(\/sessions)/, '$1'));

describe('SessionsPanel — H218 archive', () => {
  it('builds the paths, escaping the id', () => {
    expect(archivePath('a b')).toBe('/sessions/a%20b/archive');
    expect(unarchivePath('s')).toBe('/sessions/s/unarchive');
    expect(deletePath('s/x')).toBe('/sessions/s%2Fx?confirm=DELETE');
  });

  it('archives a chat from the list and reloads it', async () => {
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'archive s-live' }));
    expect(await screen.findByText('archived s-live')).toBeTruthy();
    expect(posts('POST')).toEqual(['/sessions/s-live/archive']);
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/sessions')).length).toBeGreaterThan(1));
    expect(screen.queryByRole('button', { name: 'unarchive s-live' })).toBeNull();
  });

  it('shows the archived chats with unarchive and no resume', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Today');
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    expect(await screen.findByText('Old trip')).toBeTruthy();
    expect(screen.getByText('ARCHIVED CHATS')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'archived' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.queryByRole('button', { name: 'resume s-away' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'unarchive s-away' }));
    expect(await screen.findByText('back in the list: s-away')).toBeTruthy();
    expect(posts('POST')).toEqual(['/sessions/s-away/unarchive']);
    fireEvent.click(screen.getByRole('tab', { name: 'chats' }));
    expect(await screen.findByText('Today')).toBeTruthy();
    expect(screen.queryByText('back in the list: s-away')).toBeNull();
  });

  it('deletes only after a second, explicit confirmation, and names the backup', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Today');
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    fireEvent.click(await screen.findByRole('button', { name: 'delete s-away permanently' }));
    expect(posts('DELETE')).toEqual([]);
    expect(screen.getByRole('note').textContent).toContain('A backup is written first');
    fireEvent.click(screen.getByRole('button', { name: 'confirm delete s-away' }));
    expect(await screen.findByText('deleted s-away · backup at /home/x/backups/sessions/s-away-1.json')).toBeTruthy();
    expect(posts('DELETE')).toEqual(['/sessions/s-away?confirm=DELETE']);
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('says why a delete was refused', async () => {
    deleteReply = () => reply(409, { error: 'active session', reason: 'active_session' });
    render(<SessionsPanel />);
    await screen.findByText('Today');
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    fireEvent.click(await screen.findByRole('button', { name: 'delete s-away permanently' }));
    fireEvent.click(screen.getByRole('button', { name: 'confirm delete s-away' }));
    expect((await screen.findByRole('alert')).textContent).toContain('not deleted');
  });

  it('a deleted chat without a backup path just says deleted', async () => {
    deleteReply = () => reply(200, { ok: true });
    render(<SessionsPanel />);
    await screen.findByText('Today');
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    fireEvent.click(await screen.findByRole('button', { name: 'delete s-away permanently' }));
    fireEvent.click(screen.getByRole('button', { name: 'confirm delete s-away' }));
    expect(await screen.findByText('deleted s-away')).toBeTruthy();
  });

  it('switching views drops a pending confirmation', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Today');
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    fireEvent.click(await screen.findByRole('button', { name: 'delete s-away permanently' }));
    fireEvent.click(screen.getByRole('tab', { name: 'chats' }));
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    expect(await screen.findByRole('button', { name: 'delete s-away permanently' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'confirm delete s-away' })).toBeNull();
  });
});
