// @ts-nocheck
/* H262 — pin a chat: a pinned chat is never auto-archived and never deleted by retention.
   The chats and archived tabs both carry the toggle, and a pinned row says so. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { SessionsPanel, pinPath, unpinPath } from '../panels/sessions';

let calls;
let pinReply;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

beforeEach(() => {
  cleanup();
  calls = [];
  pinReply = () => reply(200, { ok: true });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    calls.push({ url: u, method: init.method || 'GET' });
    if (u.endsWith('/sessions?archived=true')) {
      return reply(200, { sessions: [{ id: 's-kept', title: 'Kept trip', archived_at: 'x', pinned_at: '2026-09-01T10:00:00+00:00' }] });
    }
    if (u.endsWith('/sessions')) {
      return reply(200, { sessions: [{ id: 's-live', title: 'Today', pinned_at: null }, { id: 's-pin', title: 'Pinned plan', pinned_at: '2026-09-02T08:00:00+00:00' }] });
    }
    if (u.endsWith('/pin') || u.endsWith('/unpin')) return pinReply();
    return reply(404, {});
  });
});

const posts = () => calls.filter((c) => c.method === 'POST').map((c) => c.url.replace(/^.*?(\/sessions)/, '$1'));

describe('SessionsPanel — H262 pin', () => {
  it('builds the paths, escaping the id', () => {
    expect(pinPath('a b')).toBe('/sessions/a%20b/pin');
    expect(unpinPath('s/x')).toBe('/sessions/s%2Fx/unpin');
  });

  it('shows the pinned badge only on a pinned chat, with when it was pinned', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Pinned plan');
    const badges = screen.getAllByTestId('pinned-badge');
    expect(badges).toHaveLength(1);
    expect(badges[0].textContent).toContain('pinned');
    expect(badges[0].getAttribute('title')).toContain('2026-09-02');
    expect(screen.getByRole('button', { name: 'pin s-live' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'unpin s-pin' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'unpin s-live' })).toBeNull();
  });

  it('pins a chat, says what the pin does, and reloads the list', async () => {
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'pin s-live' }));
    expect((await screen.findByRole('status')).textContent).toContain('pinned s-live');
    expect(screen.getByRole('status').textContent).toContain('never archived or deleted by retention');
    expect(posts()).toEqual(['/sessions/s-live/pin']);
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/sessions')).length).toBeGreaterThan(1));
  });

  it('unpins a chat', async () => {
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'unpin s-pin' }));
    expect((await screen.findByRole('status')).textContent).toContain('unpinned s-pin');
    expect(posts()).toEqual(['/sessions/s-pin/unpin']);
  });

  it('the archived tab carries the badge and the toggle too, beside unarchive', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Today');
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    await screen.findByText('Kept trip');
    expect(screen.getAllByTestId('pinned-badge')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'unarchive s-kept' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'unpin s-kept' }));
    expect((await screen.findByRole('status')).textContent).toContain('unpinned s-kept');
    expect(posts()).toEqual(['/sessions/s-kept/unpin']);
  });

  it('says why a pin was refused', async () => {
    pinReply = () => reply(503, { error: 'the session store is unavailable', reason: 'store_unavailable' });
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'pin s-live' }));
    expect((await screen.findByRole('alert')).textContent).toContain('not pinned');
  });
});
