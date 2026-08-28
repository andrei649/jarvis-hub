// @ts-nocheck
/* T-0.58 — the Console PacksPanel reads the typed pack inventory
   (GET /api/packs, user-guarded). Asserts the read wiring, that skill and
   knowledge packs are both listed with their type, that verify calls the
   per-pack endpoint, and — the honesty rule — that an UNSUPPORTED pack type is
   shown with its reason rather than quietly omitted. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PacksPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const INVENTORY = {
  available: true,
  types: [
    { type: 'skill', supported: true },
    { type: 'knowledge', supported: true },
    { type: 'model', supported: false, reason: 'Nerva does not distribute model weights' },
  ],
  packs: [
    { pack_type: 'skill', name: 'weather', version: '2.1.0' },
    { pack_type: 'knowledge', name: 'ro-law', version: '3.0.0', key: 'law', files: 12 },
  ],
  unmanifested: ['loose'],
  counts: { skill: 1, knowledge: 1, total: 2 },
};

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve({ ok: true, status: 200, json: async () => (hit ? hit[1] : {}) });
  });
  global.fetch = fn;
  return fn;
}

describe('PacksPanel — the typed pack inventory is live', () => {
  it('GETs /api/packs and lists both pack types', async () => {
    const fn = mockFetch({ '/api/packs': INVENTORY });
    render(<PacksPanel />);
    await waitFor(() => expect(screen.getByText('weather')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/packs'))).toBe(true);
    expect(screen.getByText('ro-law')).toBeTruthy();
    expect(screen.getByText('2 packs')).toBeTruthy();
    expect(screen.getByText('v2.1.0')).toBeTruthy();
  });

  it('shows an unsupported type with its reason instead of hiding it', async () => {
    mockFetch({ '/api/packs': INVENTORY });
    render(<PacksPanel />);
    await waitFor(() => expect(screen.getByText('model · n/a')).toBeTruthy());
    expect(screen.getByText(/does not distribute model weights/)).toBeTruthy();
  });

  it('reports drop-folders separately from packs', async () => {
    mockFetch({ '/api/packs': INVENTORY });
    render(<PacksPanel />);
    await waitFor(() => expect(screen.getByText(/drop-folders, not packs/)).toBeTruthy());
  });

  it('verifies a knowledge pack through its own endpoint', async () => {
    const fn = mockFetch({
      '/api/packs/law/verify': { ok: true, key: 'law', verify: { checked: 12, missing: [], modified: [], unexpected: [] } },
      '/api/packs': INVENTORY,
    });
    render(<PacksPanel />);
    await waitFor(() => expect(screen.getByText('ro-law')).toBeTruthy());
    fireEvent.click(screen.getByText('verify'));
    await waitFor(() => expect(screen.getByText(/intact \(12 file/)).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/packs/law/verify'))).toBe(true);
  });

  it('names discrepancies when verification fails', async () => {
    mockFetch({
      '/api/packs/law/verify': { ok: false, key: 'law', verify: { checked: 12, missing: ['a.md'], modified: ['b.md'], unexpected: [] } },
      '/api/packs': INVENTORY,
    });
    render(<PacksPanel />);
    await waitFor(() => expect(screen.getByText('ro-law')).toBeTruthy());
    fireEvent.click(screen.getByText('verify'));
    await waitFor(() => expect(screen.getByText(/1 missing/)).toBeTruthy());
    expect(screen.getByText(/1 modified/)).toBeTruthy();
  });
});
