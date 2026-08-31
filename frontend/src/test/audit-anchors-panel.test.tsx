// @ts-nocheck
/* DRA-36 (transparency-anchor half) — `GET /api/security/audit/anchors` and
   `POST /api/security/audit/anchor` (H17.4) had no caller: the Trust Center rendered the
   sibling /audit/verify badge but the external-anchor receipts, the half that makes the
   audit chain externally checkable, had no surface at all. The load-bearing assertions:
   a broken chain must render as broken (a panel hardcoding "intact" fails), and an EMPTY
   anchor log must NOT claim a verified chain — verify() returns ok:true over zero rows. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { AuditAnchorsPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const ANCHORS = [
  { seq: 5, ts: 1750000000, source: 'audit', root: 'aaaaaaaaaaaabbbb', prev_anchor_hash: 'cccc', anchor_hash: 'ddddddddddddeeee' },
  { seq: 4, ts: 1749990000, source: 'intent', root: '1111111111112222', prev_anchor_hash: '', anchor_hash: 'ffffffffffff3333' },
];

function mockApi(get, post) {
  const fn = vi.fn().mockImplementation((url, init) => {
    const method = (init && init.method) || 'GET';
    if (method !== 'POST') return Promise.resolve({ ok: true, status: 200, json: async () => get });
    return (post || (() => Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true, receipt: { seq: 6 } }) })))(url, init);
  });
  global.fetch = fn;
  return fn;
}

describe('AuditAnchorsPanel — the transparency-anchor log is visible', () => {
  it('GETs the anchors endpoint and lists the receipts', async () => {
    const fn = mockApi({ verify: { ok: true, bad_seq: null, n: 2 }, anchors: ANCHORS });
    render(<AuditAnchorsPanel />);
    await waitFor(() => expect(screen.getByText('#5')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/security/audit/anchors'))).toBe(true);
    expect(screen.getByText(/anchor chain intact · 2 receipt/)).toBeTruthy();
    expect(screen.getByText('audit')).toBeTruthy();
    expect(screen.getByText('intent')).toBeTruthy();
    expect(screen.getByText(/aaaaaaaaaaaa/)).toBeTruthy();
  });

  it('renders a broken chain as broken', async () => {
    mockApi({ verify: { ok: false, bad_seq: 3, n: 5 }, anchors: ANCHORS });
    render(<AuditAnchorsPanel />);
    await waitFor(() => expect(screen.getByText(/chain broken @ #3/)).toBeTruthy());
    expect(screen.queryByText(/intact/)).toBeNull();
  });

  it('does not claim a verified chain when nothing has been anchored', async () => {
    mockApi({ verify: { ok: true, bad_seq: null, n: 0 }, anchors: [] });
    render(<AuditAnchorsPanel />);
    await waitFor(() => expect(screen.getByText(/nothing anchored yet/)).toBeTruthy());
    expect(screen.queryByText(/intact/)).toBeNull();
    expect(screen.getByText('SEED')).toBeTruthy();
  });

  it('anchors on demand through the admin route and reloads', async () => {
    try { localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
    const fn = mockApi({ verify: { ok: true, bad_seq: null, n: 2 }, anchors: ANCHORS });
    render(<AuditAnchorsPanel />);
    await waitFor(() => expect(screen.getByText('#5')).toBeTruthy());
    const before = fn.mock.calls.filter((c) => String(c[0]).includes('/api/security/audit/anchors')).length;

    fireEvent.click(screen.getByTitle(/anchor now/));

    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]) === '/api/security/audit/anchor' && (c[1] || {}).method === 'POST');
      expect(post).toBeTruthy();
      expect(post[1].headers['X-Admin-Token']).toBe('adm');
    });
    await waitFor(() => expect(screen.getByText(/anchored · receipt #6/)).toBeTruthy());
    await waitFor(() => expect(
      fn.mock.calls.filter((c) => String(c[0]).includes('/api/security/audit/anchors')).length,
    ).toBeGreaterThan(before));
  });

  it('shows a refusal when the admin anchor call is denied', async () => {
    mockApi(
      { verify: { ok: true, bad_seq: null, n: 2 }, anchors: ANCHORS },
      () => Promise.resolve({ ok: false, status: 403, json: async () => ({ error: 'admin token required' }) }),
    );
    render(<AuditAnchorsPanel />);
    await waitFor(() => expect(screen.getByText('#5')).toBeTruthy());
    fireEvent.click(screen.getByTitle(/anchor now/));
    await waitFor(() => expect(screen.getByText(/refused · POST \/api\/security\/audit\/anchor -> 403/)).toBeTruthy());
  });
});
