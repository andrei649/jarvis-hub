// @ts-nocheck
/* TODAY & RECEIPTS — `fetch` is mocked (not api/client) so the real client path runs:
   apiPost throws on 4xx, so a refusal branch that never renders would be dead code.

   Claims pinned here:
   · the panel reads GET /api/report/today and renders the allow-listed counts + titles;
   · an empty day renders the backend's own reason, not a row of zeros, under a SEED chip
     when the queue source is missing;
   · export POSTs {format} to /api/report/today/export and prints the returned path;
   · a kernel refusal (403 {reason}) is rendered with its reason, never swallowed;
   · a receipt lookup GETs /api/report/receipt/<id> and shows VERIFIED / UNVERIFIED
     exactly as the backend computed it, with 404 / 400 named. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { TodayReceiptPanel } from './today-receipt';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const REPORT = {
  schema: 'nerva.day-report.v1',
  date: '2026-09-06',
  empty: false,
  reason: null,
  sources: { queue: true, north_star: true },
  counts: { accepted: 3, rejected: 1, failed: 0, pending: 2, night_shift: 1, interrupts: 1 },
  north_star: { local_pct: 91.5, reject_rate: 0.25, guardrails_ok: true },
  actions: [
    { task_id: 11, title: 'renamed the invoices folder', kind: 'fs.rename', status: 'done', night: true },
    { task_id: 12, title: 'mail [REDACTED:email]', kind: 'mail.send', status: 'rejected', night: false },
  ],
  model: { name: 'qwen3-8b', backend: 'lmstudio' },
  fingerprint: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
};

const EMPTY = {
  ...REPORT, empty: true, reason: 'autonomy queue not available — nothing can be counted',
  sources: { queue: false, north_star: false }, counts: { accepted: 0, rejected: 0 }, actions: [], north_star: null,
  model: { name: null, backend: null },
};

const RECEIPT = {
  schema: 'nerva.receipt.v1', audit_id: 7, action: 'authorize:call.outbound', why: 'grant:policy allows',
  decision: { verdict: 'grant', tier: 2 }, signed: true, verified: true, reason: null,
  chain: { ok: true, entries: 12 }, entry_hash: 'deadbeef' + 'a'.repeat(56),
};

// route-keyed, most-specific first (String(url).includes)
function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    const val = hit ? hit[1] : {};
    if (val && typeof val === 'object' && '__status' in val) {
      return Promise.resolve({ ok: false, status: val.__status, json: async () => val.body });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => val });
  });
  global.fetch = fn;
  return fn;
}

describe('TodayReceiptPanel — the day report is live', () => {
  it('GETs /api/report/today and renders counts, titles and the model', async () => {
    const fn = mockFetch({ '/api/report/today': REPORT });
    render(<TodayReceiptPanel />);
    await waitFor(() => expect(screen.getByText('renamed the invoices folder')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/report/today'))).toBe(true);
    expect(screen.getByText('ACCEPTED')).toBeTruthy();
    expect(screen.getByText('qwen3-8b')).toBeTruthy();
    expect(screen.getByText('local 91.5%')).toBeTruthy();
    expect(screen.getByText('mail [REDACTED:email]')).toBeTruthy();
    expect(screen.getByText('night')).toBeTruthy();
    expect(screen.getByText('LIVE')).toBeTruthy();
  });

  it('renders the backend reason for an empty day under a SEED chip, not zeros', async () => {
    mockFetch({ '/api/report/today': EMPTY });
    render(<TodayReceiptPanel />);
    await waitFor(() => expect(screen.getByText(/autonomy queue not available/)).toBeTruthy());
    expect(screen.queryByText('ACCEPTED')).toBeNull();
    expect(screen.getByText('SEED')).toBeTruthy();
    expect(screen.getByText('— not reported')).toBeTruthy();
  });

  it('POSTs {format} to /api/report/today/export and prints the path', async () => {
    const fn = mockFetch({
      '/api/report/today/export': { ok: true, path: '/data/reports/2026-09-06-abcdef012345.html' },
      '/api/report/today': REPORT,
    });
    render(<TodayReceiptPanel />);
    await waitFor(() => expect(screen.getByText('renamed the invoices folder')).toBeTruthy());
    fireEvent.click(screen.getByText('export card'));
    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/report/today/export') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ format: 'html' });
    });
    await waitFor(() => expect(screen.getByText(/exported html · \/data\/reports/)).toBeTruthy());
  });

  it('renders a kernel refusal with its reason instead of silently succeeding', async () => {
    mockFetch({
      '/api/report/today/export': { __status: 403, body: { ok: false, reason: 'kernel_denied:kill-switch engaged' } },
      '/api/report/today': REPORT,
    });
    render(<TodayReceiptPanel />);
    await waitFor(() => expect(screen.getByText('renamed the invoices folder')).toBeTruthy());
    fireEvent.click(screen.getByText('export json'));
    await waitFor(() => expect(screen.getByText('refused · kernel_denied:kill-switch engaged')).toBeTruthy());
    expect(screen.queryByText(/exported/)).toBeNull();
  });
});

describe('TodayReceiptPanel — Proof-of-Action receipts', () => {
  it('GETs /api/report/receipt/<id> and shows VERIFIED as the backend computed it', async () => {
    const fn = mockFetch({ '/api/report/receipt/7': RECEIPT, '/api/report/today': REPORT });
    render(<TodayReceiptPanel />);
    await waitFor(() => expect(screen.getByText('renamed the invoices folder')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('audit id'), { target: { value: '7' } });
    fireEvent.click(screen.getByText('verify'));
    await waitFor(() => expect(screen.getByText('VERIFIED')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]) === '/api/report/receipt/7')).toBe(true);
    expect(screen.getByText('authorize:call.outbound')).toBeTruthy();
    expect(screen.getByText('chain ok')).toBeTruthy();
    expect(screen.getByText('12 entries')).toBeTruthy();
    expect(screen.getByText('signed')).toBeTruthy();
  });

  it('shows an unverified receipt in amber with the chain reason', async () => {
    mockFetch({
      '/api/report/receipt/3': { ...RECEIPT, audit_id: 3, verified: false, reason: 'chain_broken:1', chain: { ok: false, entries: 12, bad_seq: 1 } },
      '/api/report/today': REPORT,
    });
    render(<TodayReceiptPanel />);
    await waitFor(() => expect(screen.getByText('renamed the invoices folder')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('audit id'), { target: { value: '3' } });
    fireEvent.click(screen.getByText('verify'));
    await waitFor(() => expect(screen.getByText('UNVERIFIED · chain_broken:1')).toBeTruthy());
    expect(screen.getByText('chain broken')).toBeTruthy();
    expect(screen.queryByText('VERIFIED')).toBeNull();
  });

  it('names a 404 and a bad id, and refuses an empty lookup without a request', async () => {
    const fn = mockFetch({
      '/api/report/receipt/99': { __status: 404, body: { error: 'not_found' } },
      '/api/report/receipt/abc': { __status: 400, body: { error: 'bad_audit_id' } },
      '/api/report/today': REPORT,
    });
    render(<TodayReceiptPanel />);
    await waitFor(() => expect(screen.getByText('renamed the invoices folder')).toBeTruthy());
    const before = fn.mock.calls.length;
    fireEvent.click(screen.getByText('verify'));
    await waitFor(() => expect(screen.getByText(/enter an audit id/)).toBeTruthy());
    expect(fn.mock.calls.length).toBe(before);
    fireEvent.change(screen.getByLabelText('audit id'), { target: { value: '99' } });
    fireEvent.click(screen.getByText('verify'));
    await waitFor(() => expect(screen.getByText('not found · no such entry')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('audit id'), { target: { value: 'abc' } });
    fireEvent.click(screen.getByText('verify'));
    await waitFor(() => expect(screen.getByText('bad audit id')).toBeTruthy());
  });
});
