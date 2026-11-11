// @ts-nocheck
/* H509 — the owner signs in to a networked Nerva from a browser.

   Pinned from the owner's side: on a networked origin a hub with no session shows the
   sign-in screen, a correct secret opens the session and every later write carries the
   session's X-CSRF-Token (never with a header token), a wrong secret is said plainly,
   sign-out reaches the hub; and on loopback nothing changes — no screen, no extra
   request. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const ok = (payload, status = 200, headers = {}) => ({
  ok: status < 400, status, json: async () => payload, headers: { get: (k) => headers[k] ?? null },
  clone() { return this; },
});

let realLocation;
function setHost(hostname) {
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...realLocation, hostname, reload: vi.fn() },
  });
}

async function fresh() {
  vi.resetModules();
  const session = await import('../api/owner-session');
  const client = await import('../api/client');
  const ui = await import('../owner-sign-in');
  return { session, client, ui };
}

beforeEach(() => { realLocation = window.location; localStorage.clear(); });
afterEach(() => { Object.defineProperty(window, 'location', { configurable: true, value: realLocation }); });

describe('owner browser sign-in (H509)', () => {
  it('shows the sign-in screen on a networked origin with no session, then signs in', async () => {
    setHost('nerva.lan');
    const fetchMock = vi.fn().mockImplementation((url, init) => {
      const u = String(url);
      if (u.endsWith('/api/auth/session')) return Promise.resolve(ok({ signed_in: false, sign_in_available: true }));
      if (u.endsWith('/api/auth/login')) return Promise.resolve(ok({ signed_in: true, csrf: 'csrf-1', expires_at: 1 }));
      return Promise.resolve(ok({}));
    });
    global.fetch = fetchMock;
    const { ui } = await fresh();
    render(<ui.OwnerSignIn />);
    const input = await screen.findByLabelText('Owner secret');
    fireEvent.change(input, { target: { value: 'the-owner-secret' } });
    fireEvent.click(screen.getByText('SIGN IN'));
    await waitFor(() => expect(window.location.reload).toHaveBeenCalled());
    const login = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/api/auth/login'));
    expect(login[1].method).toBe('POST');
    expect(JSON.parse(login[1].body)).toEqual({ secret: 'the-owner-secret' });
    expect(login[1].credentials).toBe('same-origin');
    expect(localStorage.length).toBe(0);           // the secret is never stored
  });

  it('says plainly when the secret is wrong', async () => {
    setHost('192.168.1.20');
    global.fetch = vi.fn().mockImplementation((url) => String(url).endsWith('/api/auth/login')
      ? Promise.resolve(ok({ error: 'invalid_secret' }, 401))
      : Promise.resolve(ok({ signed_in: false, sign_in_available: true })));
    const { ui } = await fresh();
    render(<ui.OwnerSignIn />);
    fireEvent.change(await screen.findByLabelText('Owner secret'), { target: { value: 'nope' } });
    fireEvent.click(screen.getByText('SIGN IN'));
    expect((await screen.findByRole('alert')).textContent).toContain("not this hub's owner secret");
  });

  it('cookie writes carry the CSRF token; header-token writes do not', async () => {
    setHost('nerva.lan');
    const fetchMock = vi.fn().mockImplementation((url) => String(url).endsWith('/api/auth/session')
      ? Promise.resolve(ok({ signed_in: true, csrf: 'csrf-xyz' }))
      : Promise.resolve(ok({ ok: true })));
    global.fetch = fetchMock;
    const { client } = await fresh();
    await client.apiPost('/api/notes', { a: 1 });
    const write = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/api/notes'));
    expect(write[1].headers['X-CSRF-Token']).toBe('csrf-xyz');
    client.setToken('guest-token');
    await client.apiPost('/api/notes', { a: 2 });
    const second = fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/api/notes'))[1];
    expect(second[1].headers['X-CSRF-Token']).toBeUndefined();
    expect(second[1].headers['X-User-Token']).toBe('guest-token');
  });

  it('a networked 401 opens the sign-in screen instead of a token prompt', async () => {
    setHost('nerva.lan');
    window.prompt = vi.fn();
    global.fetch = vi.fn().mockResolvedValue(ok({ detail: 'admin token required' }, 401));
    const { client, session } = await fresh();
    await expect(client.apiGet('/api/admin/status')).rejects.toThrow();
    expect(window.prompt).not.toHaveBeenCalled();
    expect(session.signInWanted()).toBe(true);
  });

  it('signed in: the corner control signs out and signs out everywhere', async () => {
    setHost('nerva.lan');
    const fetchMock = vi.fn().mockImplementation((url) => String(url).endsWith('/api/auth/session')
      ? Promise.resolve(ok({ signed_in: true, csrf: 'c-1', sign_in_available: true }))
      : Promise.resolve(ok({ signed_in: false })));
    global.fetch = fetchMock;
    const { ui } = await fresh();
    render(<ui.OwnerSignIn />);
    fireEvent.click(await screen.findByText('OWNER · SIGNED IN'));
    fireEvent.click(screen.getByText('SIGN OUT EVERYWHERE'));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/api/auth/logout-all'))).toBe(true));
    const all = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/api/auth/logout-all'));
    expect(all[1].headers['X-CSRF-Token']).toBe('c-1');
    expect(await screen.findByLabelText('Owner secret')).toBeTruthy();
  });

  it('sign out reaches the hub', async () => {
    setHost('nerva.lan');
    const fetchMock = vi.fn().mockImplementation((url) => String(url).endsWith('/api/auth/session')
      ? Promise.resolve(ok({ signed_in: true, csrf: 'c-2', sign_in_available: true }))
      : Promise.resolve(ok({ signed_in: false })));
    global.fetch = fetchMock;
    const { ui } = await fresh();
    render(<ui.OwnerSignIn />);
    fireEvent.click(await screen.findByText('OWNER · SIGNED IN'));
    fireEvent.click(screen.getByText('SIGN OUT'));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/api/auth/logout'))).toBe(true));
  });

  it('over plain HTTP the screen explains that owner sign-in needs HTTPS', async () => {
    setHost('192.168.1.20');
    global.fetch = vi.fn().mockResolvedValue(
      ok({ signed_in: false, sign_in_available: false, reason: 'https_required' }));
    const { ui, session } = await fresh();
    session.requireSignIn();
    render(<ui.OwnerSignIn />);
    expect((await screen.findByText(/needs HTTPS/)).textContent).toContain('JARVIS_ALLOW_INSECURE_SIGNIN');
  });

  it('a cookie-signed-in owner counts as the owner for admin-only controls', async () => {
    setHost('nerva.lan');
    global.fetch = vi.fn().mockResolvedValue(ok({ signed_in: true, csrf: 'c' }));
    const { session } = await fresh();
    expect(session.ownerSignedIn()).toBe(false);
    await session.loadOwnerSession();
    expect(session.ownerSignedIn()).toBe(true);
  });

  it('loopback is unchanged: no screen and no session request', async () => {
    setHost('localhost');
    const fetchMock = vi.fn().mockResolvedValue(ok({ ok: true }));
    global.fetch = fetchMock;
    const { ui, client } = await fresh();
    const { container } = render(<ui.OwnerSignIn />);
    expect(container.innerHTML).toBe('');
    await client.apiPost('/api/notes', {});
    expect(fetchMock.mock.calls.map(([u]) => String(u))).toEqual([expect.stringMatching(/\/api\/notes$/)]);
    expect(fetchMock.mock.calls[0][1].headers['X-CSRF-Token']).toBeUndefined();
  });
});
