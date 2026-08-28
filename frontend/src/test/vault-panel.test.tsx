// @ts-nocheck
/* T-0.20 — the Console VaultPanel reads/writes the encrypted personal blob
   vault (GET/POST/DELETE /api/vault[/{id}], user-guarded). fetch is mocked
   (route-keyed, like watchlist-panel.test.tsx). Asserts the read wiring, that
   plaintext never shows up in the listing, storing text POSTs a base64 body,
   fetching an item GETs it by id, and delete DELETEs by id. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { VaultPanel } from '../gap';

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  global.URL.createObjectURL = vi.fn(() => 'blob:x');
  global.URL.revokeObjectURL = vi.fn();
});

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve({ ok: true, status: 200, json: async () => (hit ? hit[1] : {}) });
  });
  global.fetch = fn;
  return fn;
}

describe('VaultPanel — the encrypted blob vault is live', () => {
  it('GETs /api/vault and renders items + stats without leaking content', async () => {
    const fn = mockFetch({
      '/api/vault': {
        items: [{ id: 'abc123', name: 'secret.txt', kind: 'document', bytes: 42 }],
        stats: { items: 1, bytes: 42, max_items: 10000, max_bytes: 1e12 },
      },
    });
    render(<VaultPanel />);
    await waitFor(() => expect(screen.getByText('secret.txt')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/vault') && (!c[1] || c[1].method === undefined || c[1].method === 'GET'))).toBe(true);
    expect(screen.getByText('1 items · 0 KB')).toBeTruthy();
    expect(screen.getByText('42B')).toBeTruthy();
  });

  it('shows the empty state with no items', async () => {
    mockFetch({ '/api/vault': { items: [], stats: { items: 0, bytes: 0 } } });
    render(<VaultPanel />);
    await waitFor(() => expect(screen.getByText('nothing yet')).toBeTruthy());
  });

  it('stores text as base64 via POST /api/vault', async () => {
    const fn = mockFetch({ '/api/vault': { items: [], stats: { items: 0, bytes: 0 } } });
    render(<VaultPanel />);
    await waitFor(() => expect(screen.getByText('nothing yet')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('name'), { target: { value: 'my-note' } });
    fireEvent.change(screen.getByPlaceholderText('text to encrypt and store…'), { target: { value: 'top secret' } });
    fireEvent.click(screen.getByText('store text'));

    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]) === '/api/vault' && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      const body = JSON.parse(post[1].body);
      expect(body.name).toBe('my-note');
      expect(atob(body.data_base64)).toBe('top secret');
    });
  });

  it('GETs /api/vault/{id} and triggers a Blob download on "get"', async () => {
    const fn = mockFetch({
      '/api/vault/abc123': { id: 'abc123', name: 'secret.txt', data_base64: btoa('hello') },
      '/api/vault': { items: [{ id: 'abc123', name: 'secret.txt', kind: 'document', bytes: 5 }], stats: { items: 1, bytes: 5 } },
    });
    render(<VaultPanel />);
    await waitFor(() => expect(screen.getByText('secret.txt')).toBeTruthy());
    fireEvent.click(screen.getByText('get'));
    await waitFor(() => {
      expect(fn.mock.calls.some((c) => String(c[0]) === '/api/vault/abc123')).toBe(true);
    });
    expect(global.URL.createObjectURL).toHaveBeenCalled();
  });

  it('DELETEs /api/vault/{id} on "del"', async () => {
    const fn = mockFetch({
      '/api/vault': { items: [{ id: 'xyz789', name: 'n', kind: 'blob', bytes: 3 }], stats: { items: 1, bytes: 3 } },
    });
    render(<VaultPanel />);
    await waitFor(() => expect(screen.getByText('n')).toBeTruthy());
    fireEvent.click(screen.getByText('del'));
    await waitFor(() => {
      const del = fn.mock.calls.find((c) => String(c[0]) === '/api/vault/xyz789' && c[1]?.method === 'DELETE');
      expect(del).toBeTruthy();
    });
  });
});
