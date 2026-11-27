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
  it('shows the live Obsidian index and refreshes its status after reindexing', async () => {
    const fn = mockFetch({
      '/api/os/status': { vaultAvailable: true, vaultPath: 'Library', indexedNotes: 3,
        skippedHardlinks: 2, excludedZones: ['Archive'], lastIndexedAt: '2030-01-01', copilotConnected: true },
      '/api/os/brain/reindex': { ok: true },
    });
    render(<VaultPanel />);
    expect(await screen.findByText('Library · 3 indexed notes')).toBeTruthy();
    expect(screen.getByText(/Memory Copilot connected/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Reindex vault' }));
    await waitFor(() => expect(fn.mock.calls.filter(([url]) => url === '/api/os/status')).toHaveLength(2));
    expect(fn.mock.calls.some(([url, init]) => url === '/api/os/brain/reindex' && init.method === 'POST')).toBe(true);
  });
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

  it('searches Obsidian notes, inspects a matched note, and captures into the vault inbox', async () => {
    const fn = mockFetch({
      '/api/os/status': {
        vaultAvailable: true,
        vaultPath: 'Library',
        indexedNotes: 4,
        copilotConnected: true,
        secondBrain: { connected: true, mcpConfigured: true, vaultFtsConfigured: false, aiKbConfigured: true },
        captureTarget: true,
        inboxFolder: 'Journal/Inbox',
      },
      '/api/os/brain/retrieve': {
        ok: true,
        attachments: [{ name: 'Projects/Roadmap.md', text: 'Finish Second Brain HUD controls' }],
      },
      '/api/os/brain/note': {
        ok: true,
        title: 'Roadmap',
        tags: ['active', 'nerva'],
        wikilinks: ['Architecture'],
        body: '# Roadmap\nFinish Second Brain HUD controls.',
      },
      '/api/os/brain/capture': { ok: true, relPath: 'Journal/Inbox/Quick Idea.md' },
      '/api/vault': { items: [], stats: { items: 0, bytes: 0 } },
    });
    render(<VaultPanel />);
    expect(await screen.findByText(/Local MCP ready · AI KB FTS ready/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open /os/' }).getAttribute('href')).toContain('/os/');

    fireEvent.change(screen.getByPlaceholderText('Search vault notes…'), { target: { value: 'Second Brain' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search vault' }));
    expect(await screen.findByText('Projects/Roadmap.md')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Inspect note' }));
    expect(await screen.findByText('Tags: active, nerva')).toBeTruthy();
    expect(screen.getByText('Links: Architecture')).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText('Note title'), { target: { value: 'Quick Idea' } });
    fireEvent.change(screen.getByPlaceholderText('Markdown note for vault inbox…'), { target: { value: 'Test capture body' } });
    fireEvent.change(screen.getByPlaceholderText('Wikilinks (comma-separated)'), { target: { value: 'Roadmap, Today' } });
    fireEvent.click(screen.getByRole('button', { name: 'Capture to inbox' }));

    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/os/brain/capture') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({
        title: 'Quick Idea',
        content: 'Test capture body',
        links: ['Roadmap', 'Today'],
      });
    });
    expect(await screen.findByText('Saved Journal/Inbox/Quick Idea.md')).toBeTruthy();
  });
});
