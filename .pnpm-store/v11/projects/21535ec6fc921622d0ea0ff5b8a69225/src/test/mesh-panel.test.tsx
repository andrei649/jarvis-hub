// @ts-nocheck
/* HUD-v3 C10 — the Console Mesh Peers panel reads the admin-guarded A2A peer registry
   (/api/a2a/peers), lists allowlisted peers with the masked secret hint, and offers
   remove + add controls. fetch is mocked, like kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MeshPeersPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('MeshPeersPanel — the A2A mesh peer registry is live', () => {
  it('GETs /api/a2a/peers and lists a peer with its masked secret hint', async () => {
    const fn = mockFetch({ peers: [
      { peer_id: 'laptop-2', name: 'Laptop', secret_hint: 'a1b2…', added_at: 1 },
    ] });
    render(<MeshPeersPanel />);
    await waitFor(() => expect(screen.getByText('Laptop')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/a2a/peers'))).toBe(true);
    expect(screen.getByText('a1b2…')).toBeTruthy();
  });

  it('DELETEs the peer when the remove control is clicked', async () => {
    const fn = mockFetch({ peers: [
      { peer_id: 'phone-9', name: 'Phone', secret_hint: 'ffff…', added_at: 2 },
    ] });
    render(<MeshPeersPanel />);
    await waitFor(() => expect(screen.getByText('Phone')).toBeTruthy());
    fireEvent.click(screen.getByTitle('remove'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/a2a/peers/phone-9') && (c[1]?.method === 'DELETE'))
    ).toBe(true));
  });

  it('POSTs a new peer (and only when a peer_id is given)', async () => {
    const fn = mockFetch({ peers: [] });
    render(<MeshPeersPanel />);
    await waitFor(() => expect(screen.getByText('add')).toBeTruthy());
    // empty peer_id → no POST
    fireEvent.click(screen.getByText('add'));
    expect(fn.mock.calls.some((c) => c[1]?.method === 'POST')).toBe(false);
    // with a peer_id → POST to /api/a2a/peers
    fireEvent.change(screen.getByPlaceholderText('peer_id'), { target: { value: 'tablet-3' } });
    fireEvent.click(screen.getByText('add'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/a2a/peers') && c[1]?.method === 'POST')
    ).toBe(true));
  });
});
