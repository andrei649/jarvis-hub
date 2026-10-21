// @ts-nocheck
/* SENDER PAIRING — the 60-second deeplink path.

   Copying a code between two devices is where people give up, so the owner mints
   a link and opens it on their phone. The token is a live credential until it is
   spent, so the panel pins three things:

   · it is shown ONCE, from the mint response — never re-fetched or stored;
   · the screen says plainly that it is one-use and when it expires, because a
     link that looks reusable gets treated as one;
   · revoke is offered only when something is actually outstanding, and clears the
     token from the screen. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PairingPanel } from '../gap';

const LIST = {
  senders: [{ channel: 'telegram', sender_id: '42', status: 'pending' }],
  summary: { enabled: true, has_code: false, pending: 1, deeplinks_outstanding: 0 },
};

const LIST_WITH_LINK = {
  ...LIST,
  summary: { ...LIST.summary, deeplinks_outstanding: 1 },
};

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });

function mockApi(routes, list = LIST) {
  const fn = vi.fn().mockImplementation((url, init) => {
    const method = (init && init.method) || 'GET';
    if (method !== 'POST') return Promise.resolve(ok(list));
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve(hit ? hit[1] : ok({}));
  });
  global.fetch = fn;
  return fn;
}

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('PairingPanel — the 60-second deeplink path', () => {
  it('mints a link and shows the URL exactly once', async () => {
    const fn = mockApi({
      '/pairing/link': ok({
        ok: true, token: 'tok-abc', url: 'https://t.me/nervabot?start=tok-abc',
        ttl_seconds: 300, single_use: true,
      }),
    });
    render(<PairingPanel />);
    await waitFor(() => expect(screen.getByPlaceholderText(/bot @username/)).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText(/bot @username/), {
      target: { value: '@nervabot' },
    });
    fireEvent.click(screen.getByTitle(/mint a one-use pairing link/));

    await waitFor(() => {
      const call = fn.mock.calls.find((c) => String(c[0]).includes('/pairing/link'));
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({
        channel: 'telegram', bot_username: '@nervabot',
      });
    });
    await waitFor(() => expect(
      screen.getByText('https://t.me/nervabot?start=tok-abc')).toBeTruthy());
  });

  it('says plainly that the link is one-use and when it dies', async () => {
    mockApi({
      '/pairing/link': ok({
        ok: true, token: 'tok', url: 'https://t.me/b?start=tok', ttl_seconds: 300,
      }),
    });
    render(<PairingPanel />);
    await waitFor(() => expect(screen.getByTitle(/mint a one-use/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/mint a one-use/));
    await waitFor(() => expect(
      screen.getByText(/One use, then dead/)).toBeTruthy());
    expect(screen.getByText(/Expires in\s*5 min/)).toBeTruthy();
  });

  it('falls back to the bare token when no bot username was given', async () => {
    mockApi({
      '/pairing/link': ok({ ok: true, token: 'tok-only', url: '', ttl_seconds: 300 }),
    });
    render(<PairingPanel />);
    await waitFor(() => expect(screen.getByTitle(/mint a one-use/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/mint a one-use/));
    await waitFor(() => expect(screen.getByText('tok-only')).toBeTruthy());
  });

  it('offers revoke only when a link is actually outstanding', async () => {
    mockApi({}, LIST);
    const { unmount } = render(<PairingPanel />);
    await waitFor(() => expect(screen.getByTitle(/mint a one-use/)).toBeTruthy());
    expect(screen.queryByTitle(/invalidate every outstanding link/)).toBeNull();
    unmount();

    mockApi({}, LIST_WITH_LINK);
    render(<PairingPanel />);
    await waitFor(() => expect(
      screen.getByTitle(/invalidate every outstanding link/)).toBeTruthy());
  });

  it('clears the token from the screen when the owner revokes', async () => {
    const fn = mockApi({
      '/pairing/link/revoke': ok({ ok: true, revoked: 1 }),
      '/pairing/link': ok({ ok: true, token: 'tok', url: 'https://t.me/b?start=tok', ttl_seconds: 300 }),
    }, LIST_WITH_LINK);
    render(<PairingPanel />);
    await waitFor(() => expect(screen.getByTitle(/mint a one-use/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/mint a one-use/));
    await waitFor(() => expect(screen.getByText('https://t.me/b?start=tok')).toBeTruthy());

    fireEvent.click(screen.getByTitle(/invalidate every outstanding link/));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/pairing/link/revoke'))).toBe(true));
    await waitFor(() => expect(screen.queryByText('https://t.me/b?start=tok')).toBeNull());
  });
});

/* H154: a flooded inbox is cleared in one move, not one ✕ at a time. The button
   only appears when something is actually pending, and the bulk drop goes through
   the admin-guarded, audited route — after a confirm, because it cannot be undone. */
describe('PairingPanel — clear pending', () => {
  const EMPTY = { senders: [], summary: { enabled: true, has_code: false, pending: 0, deeplinks_outstanding: 0 } };

  it('offers clear pending only when something is pending', async () => {
    mockApi({}, EMPTY);
    const { unmount } = render(<PairingPanel />);
    await waitFor(() => expect(screen.getByTitle(/mint a one-use/)).toBeTruthy());
    expect(screen.queryByTitle(/drop every pending request/)).toBeNull();
    unmount();

    mockApi({}, LIST);
    render(<PairingPanel />);
    await waitFor(() => expect(screen.getByTitle(/drop every pending request/)).toBeTruthy());
  });

  it('posts to the clear-pending route as admin after a two-step confirm', async () => {
    localStorage.setItem('hud.admin_token', 'admin-secret');
    const fn = mockApi({ '/pairing/clear-pending': ok({ ok: true, cleared: 1 }) });
    render(<PairingPanel />);
    await waitFor(() => expect(screen.getByTitle(/drop every pending request/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/drop every pending request/));
    // arming alone sends nothing — the drop needs the second, explicit click
    expect(fn.mock.calls.some((c) => String(c[0]).includes('clear-pending'))).toBe(false);
    fireEvent.click(screen.getByText(/^drop \d+ pending$/));
    await waitFor(() => {
      const call = fn.mock.calls.find((c) => String(c[0]).includes('/api/channels/pairing/clear-pending'));
      expect(call).toBeTruthy();
      expect(call[1].method).toBe('POST');
      expect(call[1].headers['X-Admin-Token']).toBe('admin-secret');
    });
    localStorage.removeItem('hud.admin_token');
    await waitFor(() => expect(screen.getByText(/cleared 1 pending/)).toBeTruthy());
  });

  it('says so when the server could not write the audit row', async () => {
    mockApi({ '/pairing/clear-pending': ok({ ok: true, cleared: 2, audited: false }) });
    render(<PairingPanel />);
    await waitFor(() => expect(screen.getByTitle(/drop every pending request/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/drop every pending request/));
    fireEvent.click(screen.getByText(/^drop \d+ pending$/));
    await waitFor(() => expect(screen.getByText(/cleared 2 pending · not audited/)).toBeTruthy());
  });

  it('does nothing when the owner cancels the confirm', async () => {
    const fn = mockApi({});
    render(<PairingPanel />);
    await waitFor(() => expect(screen.getByTitle(/drop every pending request/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/drop every pending request/));
    fireEvent.click(screen.getByText('cancel'));
    expect(fn.mock.calls.some((c) => String(c[0]).includes('clear-pending'))).toBe(false);
    expect(screen.getByTitle(/drop every pending request/)).toBeTruthy();   // disarmed, back to the trigger
  });
});
