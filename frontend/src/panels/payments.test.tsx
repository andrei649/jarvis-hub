// @ts-nocheck
/* PAYMENTS panel — GET/POST /api/payments/mandates and POST /api/payments/request,
   all admin-tier. fetch is mocked, like src/panels/codeintel.test.tsx.

   The refusals are the point. apiPost throws on 4xx and carries the parsed body, so a
   denial must render as a VISIBLE refusal carrying the backend's own code, and the
   success line must be absent — that is the assertion that keeps the then-branch from
   swallowing a refusal. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { PaymentsPanel } from './payments';

const M1 = {
  id: 'mnd_abc',
  payees: ['acme-gmbh', 'hetzner'],
  per_payment_cap: 250,
  total_cap: 1000,
  currency: 'EUR',
  spent: 120,
  created_at: 1756000000,
  expires_at: null,
  remaining: 880,      // added by list_mandates only
};
/* Expired, and deliberately WITHOUT `remaining` — the panel must print — rather than
   compute total_cap - spent for itself. */
const M2 = {
  id: 'mnd_old',
  payees: ['stale-vendor'],
  per_payment_cap: 10,
  total_cap: 20,
  currency: 'USD',
  spent: 0,
  created_at: 1500000000,
  expires_at: 1577836800,   // 2020-01-01T00:00:00Z
};

function mockRoutes(handler) {
  const fn = vi.fn(async (url, init) => {
    const u = String(url);
    const method = String((init && init.method) || 'GET').toUpperCase();
    const r = handler(u, method, init) || { status: 200, body: {} };
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  });
  global.fetch = fn;
  return fn;
}

const listOnly = (mandates) => mockRoutes((u, m) =>
  (u.includes('/api/payments/mandates') && m === 'GET' ? { status: 200, body: { mandates } } : null));

const lastPost = (fn, path) => {
  const c = fn.mock.calls.filter((x) => String(x[0]) === path && String(x[1].method).toUpperCase() === 'POST').pop();
  return c ? JSON.parse(c[1].body) : null;
};

beforeEach(() => {
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
  vi.restoreAllMocks();
});

describe('PaymentsPanel — the mandate ledger and the request gate, without implying money moves', () => {
  it('renders caps, spend, the backend-supplied remaining, the payee allowlist and the expiry', async () => {
    const fn = listOnly([M1, M2]);
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText('mnd_abc')).toBeTruthy());

    expect(fn.mock.calls.some((c) => String(c[0]) === '/api/payments/mandates')).toBe(true);
    const get = fn.mock.calls.find((c) => String(c[0]) === '/api/payments/mandates');
    expect(get[1].headers['X-Admin-Token']).toBe('adm');   // admin-tier read

    expect(screen.getByText('per ≤ 250')).toBeTruthy();
    expect(screen.getByText('total 1000')).toBeTruthy();
    expect(screen.getByText('spent 120')).toBeTruthy();
    expect(screen.getByText('remaining 880')).toBeTruthy();
    expect(screen.getByText('acme-gmbh · hetzner')).toBeTruthy();
    expect(screen.getByText('no expiry')).toBeTruthy();
    expect(screen.getByText('2 mandate(s)')).toBeTruthy();
    expect(screen.getByText('LIVE')).toBeTruthy();

    // `remaining` is absent on M2 → an em dash, never total_cap - spent computed here.
    expect(screen.getByText('remaining —')).toBeTruthy();
    expect(screen.queryByText('remaining 20')).toBeNull();
    // expiry in the past → the expired tag plus the note saying the comparison is derived.
    expect(screen.getByText('expired 2020-01-01 00:00:00Z')).toBeTruthy();
    expect(screen.getByText(/is derived here from/)).toBeTruthy();
  });

  it('renders an empty ledger as "no mandates → unknown_mandate", never as an outage', async () => {
    listOnly([]);
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText(/no mandate authorized/)).toBeTruthy());
    expect(screen.getByText(/no mandate authorized/).textContent).toContain('unknown_mandate');
    expect(screen.getByText('SEED')).toBeTruthy();
    expect(screen.queryByText('LIVE')).toBeNull();
    // No 503/unavailable fiction: this router has no component guard.
    expect(screen.queryByText(/unavailable/i)).toBeNull();
  });

  it('renders a failed mandate read verbatim and never as zero mandates', async () => {
    mockRoutes((u) => (u.includes('/api/payments/mandates') ? { status: 403, body: { detail: 'nope' } } : null));
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText(/GET \/api\/payments\/mandates -> 403/)).toBeTruthy());
    expect(screen.queryByText('0 mandate(s)')).toBeNull();
    expect(screen.queryByText(/no mandate authorized/)).toBeNull();
  });

  it('POSTs the mandate with ttl_seconds OMITTED when the ttl box is blank', async () => {
    const created = { ...M1, id: 'mnd_new', spent: 0, expires_at: null };
    delete created.remaining;   // the create response carries no `remaining`
    const fn = mockRoutes((u, m) => {
      if (u === '/api/payments/mandates' && m === 'POST') return { status: 200, body: created };
      if (u === '/api/payments/mandates') return { status: 200, body: { mandates: [] } };
      return null;
    });
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText(/no mandate authorized/)).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('payees, comma-separated (e.g. acme-gmbh, hetzner)'), { target: { value: ' acme-gmbh , hetzner ' } });
    fireEvent.change(screen.getByPlaceholderText('per-payment cap'), { target: { value: '250' } });
    fireEvent.change(screen.getByPlaceholderText('total cap'), { target: { value: '1000' } });
    fireEvent.click(screen.getByText('create mandate'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('mandate created · mnd_new'));
    const body = lastPost(fn, '/api/payments/mandates');
    expect(body).toEqual({ payees: ['acme-gmbh', 'hetzner'], per_payment_cap: 250, total_cap: 1000, currency: 'EUR' });
    expect('ttl_seconds' in body).toBe(false);
    expect(screen.getByRole('alert').textContent).toContain('no expiry');
    // the list is re-read so `remaining` comes from the backend, not from the create response
    expect(fn.mock.calls.filter((c) => String(c[0]) === '/api/payments/mandates' && String(c[1].method).toUpperCase() === 'GET').length).toBeGreaterThan(1);
  });

  it('renders the 400 create refusal string VERBATIM and not as a success', async () => {
    const error = 'invalid mandate (need ≥1 payee and positive caps)';
    mockRoutes((u, m) => {
      if (u === '/api/payments/mandates' && m === 'POST') return { status: 400, body: { error } };
      if (u === '/api/payments/mandates') return { status: 200, body: { mandates: [] } };
      return null;
    });
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText(/no mandate authorized/)).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('payees, comma-separated (e.g. acme-gmbh, hetzner)'), { target: { value: 'acme-gmbh' } });
    fireEvent.change(screen.getByPlaceholderText('per-payment cap'), { target: { value: '5' } });
    fireEvent.change(screen.getByPlaceholderText('total cap'), { target: { value: '5' } });
    fireEvent.click(screen.getByText('create mandate'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain(error));
    expect(screen.queryByText(/mandate created/)).toBeNull();
  });

  it('renders a 422 create rejection as FastAPI\'s detail array, a different shape from the 400', async () => {
    const detail = [{ loc: ['body', 'total_cap'], msg: 'Input should be greater than 0', type: 'greater_than' }];
    mockRoutes((u, m) => {
      if (u === '/api/payments/mandates' && m === 'POST') return { status: 422, body: { detail } };
      if (u === '/api/payments/mandates') return { status: 200, body: { mandates: [] } };
      return null;
    });
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText(/no mandate authorized/)).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('payees, comma-separated (e.g. acme-gmbh, hetzner)'), { target: { value: 'acme-gmbh' } });
    fireEvent.change(screen.getByPlaceholderText('per-payment cap'), { target: { value: '5' } });
    fireEvent.change(screen.getByPlaceholderText('total cap'), { target: { value: '5' } });
    fireEvent.click(screen.getByText('create mandate'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('refused · 422'));
    expect(screen.getByRole('alert').textContent).toContain('Input should be greater than 0');
    expect(screen.getByRole('alert').textContent).not.toContain('invalid mandate');
  });

  it('requests against the SELECTED mandate: its id, its currency, a payee from its allowlist', async () => {
    const payment = {
      id: 'pay_1', mandate_id: 'mnd_abc', payee: 'hetzner', amount: 40,
      currency: 'EUR', memo: 'server', status: 'pending', created_at: 1756000100,
    };
    const fn = mockRoutes((u, m) => {
      if (u === '/api/payments/request' && m === 'POST') return { status: 200, body: payment };
      if (u === '/api/payments/mandates') return { status: 200, body: { mandates: [M1] } };
      return null;
    });
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText('mnd_abc')).toBeTruthy());
    fireEvent.click(screen.getByTitle('use this mandate for the request below'));

    fireEvent.change(screen.getByTitle('payees allowed by this mandate'), { target: { value: 'hetzner' } });
    fireEvent.change(screen.getByPlaceholderText('amount'), { target: { value: '40' } });
    fireEvent.change(screen.getByPlaceholderText('memo (optional, ≤280)'), { target: { value: 'server' } });
    fireEvent.click(screen.getByText('request (pending)'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('pay_1 · pending · 40 EUR → hetzner'));
    expect(lastPost(fn, '/api/payments/request')).toEqual({
      mandate_id: 'mnd_abc', payee: 'hetzner', amount: 40, currency: 'EUR', memo: 'server',
    });
    const post = fn.mock.calls.find((c) => String(c[0]) === '/api/payments/request');
    expect(post[1].headers['X-Admin-Token']).toBe('adm');
    // The success wording must never imply completion.
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('No money has moved');
    expect(alert).not.toMatch(/\bpaid\b|\bcleared\b|\bsettled\b/);
  });

  it('renders a denial with the backend reason code VERBATIM and NO success line', async () => {
    mockRoutes((u, m) => {
      if (u === '/api/payments/request' && m === 'POST') {
        return { status: 400, body: { error: 'payment denied', reason: 'over_per_payment_cap' } };
      }
      if (u === '/api/payments/mandates') return { status: 200, body: { mandates: [M1] } };
      return null;
    });
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText('mnd_abc')).toBeTruthy());
    fireEvent.click(screen.getByTitle('use this mandate for the request below'));
    fireEvent.change(screen.getByTitle('payees allowed by this mandate'), { target: { value: 'acme-gmbh' } });
    fireEvent.change(screen.getByPlaceholderText('amount'), { target: { value: '900' } });
    fireEvent.click(screen.getByText('request (pending)'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('payment denied · over_per_payment_cap'));
    // the anti-dead-code assertion: the then-branch must NOT have rendered
    expect(screen.queryByText(/recorded as a request awaiting approval/)).toBeNull();
    expect(screen.queryByText(/pending · 900/)).toBeNull();
  });

  it('prints an unrecognised denial code bare, inventing no cause for it', async () => {
    mockRoutes((u, m) => {
      if (u === '/api/payments/request' && m === 'POST') {
        return { status: 400, body: { error: 'payment denied', reason: 'constraint_error:under_total_cap' } };
      }
      if (u === '/api/payments/mandates') return { status: 200, body: { mandates: [M1] } };
      return null;
    });
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText('mnd_abc')).toBeTruthy());
    fireEvent.click(screen.getByTitle('use this mandate for the request below'));
    fireEvent.change(screen.getByTitle('payees allowed by this mandate'), { target: { value: 'acme-gmbh' } });
    fireEvent.change(screen.getByPlaceholderText('amount'), { target: { value: '10' } });
    fireEvent.click(screen.getByText('request (pending)'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('payment denied · constraint_error:under_total_cap'));
    expect(screen.getByRole('alert').textContent).toContain('will not invent one');
  });

  it('offers no settle / approve / reject control anywhere on the panel', async () => {
    listOnly([M1]);
    render(<PaymentsPanel />);
    await waitFor(() => expect(screen.getByText('mnd_abc')).toBeTruthy());
    expect(screen.queryByText('settle')).toBeNull();
    expect(screen.queryByText('approve')).toBeNull();
    expect(screen.queryByText('reject')).toBeNull();
  });
});
