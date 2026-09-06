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
