// @ts-nocheck
/* OSINT panel — POST /api/osint/correlate + POST /api/osint/brief (user tier) and
   GET /api/signals/brief/{domain} (user tier). fetch is mocked, like src/test/kg-panel.test.tsx.

   The refusal and the three distinct empty states are the point: apiPost throws on 4xx and
   carries the parsed body, so a 422 must render as a visible refusal with the backend's own
   msg — never as a success drawer — and the Signal Layer's `available:false` must never be
   rendered as "no signals" / "0 signals". */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { OsintPanel } from './osint';

/* url/method -> {status, body}. Anything unmatched answers 200 {}. */
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

const typeRow = (kind, value) => {
  fireEvent.change(screen.getByLabelText('kind 1'), { target: { value: kind } });
  fireEvent.change(screen.getByLabelText('value 1'), { target: { value } });
};

const FINDING = {
  kind: 'domain',
  value: 'evil.example',
  confidence: 0.35,
  tainted: true,
  sources: ['rss'],
  count: 1,
  provenance: [{ source: 'rss', kind: 'domain', value: 'evil.example', observed_at: '', detail: '', url: '', tainted: true }],
};

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } vi.restoreAllMocks(); });

describe('OsintPanel — the offline correlator is reachable and never overstates itself', () => {
  it('issues no request at all until the operator acts', async () => {
    const fn = mockRoutes(() => null);
    render(<OsintPanel />);
    await waitFor(() => expect(screen.getByText('pick a domain — nothing is requested until you do')).toBeTruthy());
    expect(fn).not.toHaveBeenCalled();
    // no drawer, no borrowed headline, no fabricated zero
    expect(screen.queryByText('0 findings returned')).toBeNull();
  });

  it('POSTs the typed evidence to /api/osint/brief and prints the backend headline verbatim', async () => {
    const fn = mockRoutes((u, method) => {
      if (u === '/api/osint/brief' && method === 'POST') {
        return {
          status: 200,
          body: {
            headline: '1 indicator(s) · 0 corroborated · 1 from untrusted source(s)',
            top: [FINDING],
            counts: { evidence: 1, findings: 1, tainted: 1, corroborated: 0 },
            untrusted_ingestion: true,
          },
        };
      }
      return null;
    });
    render(<OsintPanel />);
    typeRow('domain', 'evil.example');
    fireEvent.click(screen.getByText('brief (top-N)'));

    await waitFor(() => expect(screen.getByText('1 indicator(s) · 0 corroborated · 1 from untrusted source(s)')).toBeTruthy());
    const call = fn.mock.calls.find((c) => String(c[0]) === '/api/osint/brief');
    expect(call).toBeTruthy();
    expect(JSON.parse(call[1].body)).toEqual({
      evidence: [{ source: '', kind: 'domain', value: 'evil.example', observed_at: '', url: '', detail: '' }],
      top: 8,
    });
    expect(screen.getByText('view: brief')).toBeTruthy();
    expect(screen.getByText('domain:evil.example')).toBeTruthy();
    expect(screen.getByText('TAINTED')).toBeTruthy();
    expect(screen.getByText('UNTRUSTED INGESTION')).toBeTruthy();
    // counts come from the backend
    expect(screen.getByText(/evidence 1 · findings 1 ·/)).toBeTruthy();
    // untrusted_ingestion is a flag on a read: no button claims to queue, escalate or submit it
    const labels = screen.getAllByRole('button').map((b) => b.textContent || '');
    expect(labels.some((t) => /queue|escalat|approve|submit|write.?back/i.test(t))).toBe(false);
  });

  it('prints the empty-drawer headline verbatim and surfaces rows the correlator silently dropped', async () => {
    mockRoutes((u, method) => (u === '/api/osint/brief' && method === 'POST'
      ? {
        status: 200,
        body: {
          headline: 'no intel correlated',
          top: [],
          counts: { evidence: 0, findings: 0, tainted: 0, corroborated: 0 },
          untrusted_ingestion: false,
        },
      }
      : null));
    render(<OsintPanel />);
    typeRow('domain', 'evil.example');
    fireEvent.click(screen.getByText('brief (top-N)'));

    await waitFor(() => expect(screen.getByText('no intel correlated')).toBeTruthy());
    expect(screen.getByText(/1 of 1 row\(s\) sent were dropped by the correlator/)).toBeTruthy();
    expect(screen.getByText('0 findings returned')).toBeTruthy();
  });

  it('renders a 422 from /api/osint/correlate as a visible refusal with the backend msg, and no drawer', async () => {
    mockRoutes((u, method) => (u === '/api/osint/correlate' && method === 'POST'
      ? {
        status: 422,
        body: {
          detail: [{
            type: 'string_too_long',
            loc: ['body', 'evidence', 0, 'kind'],
            msg: 'String should have at most 32 characters',
          }],
        },
      }
      : null));
    render(<OsintPanel />);
    typeRow('domain', 'evil.example');
    fireEvent.click(screen.getByText('correlate'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(screen.getByText('refused · HTTP 422 · POST /api/osint/correlate')).toBeTruthy();
    // the backend's own msg/loc, verbatim — not a client-invented cause
    expect(screen.getByRole('alert').textContent).toContain('String should have at most 32 characters');
    expect(screen.getByRole('alert').textContent).toContain('evidence');
    // and NOT a success drawer
    expect(screen.queryByText('view: correlate')).toBeNull();
    expect(screen.queryByText('0 findings returned')).toBeNull();
  });

  it('renders the Signal Layer reason verbatim and never as "no signals" / "0 signals"', async () => {
    const fn = mockRoutes((u) => (u.startsWith('/api/signals/brief/')
      ? {
        status: 200,
        body: {
          domain: 'cyber', known_domain: null, available: false, reason: 'unavailable',
          top: [], count: 0, headline: 'signal layer unavailable', freshness: {},
        },
      }
      : null));
    render(<OsintPanel />);
    fireEvent.click(screen.getByText('cyber'));

    await waitFor(() => expect(screen.getByText(/signal layer unavailable · reason: unavailable/)).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]) === '/api/signals/brief/cyber?top=5&limit=20')).toBe(true);
    expect(screen.queryByText('no signals')).toBeNull();
    expect(document.body.textContent).not.toMatch(/0 signals/);
    // count/known_domain are placeholders in this branch, so neither is shown as a number
    expect(screen.getByText('count —')).toBeTruthy();
    expect(screen.queryByText('count 0')).toBeNull();
    expect(screen.getByText('known_domain —')).toBeTruthy();
    // known_domain is null here, so it must NOT be reported as "unknown domain"
    expect(screen.queryByText('unknown domain')).toBeNull();
    // and no control is offered for a sidecar that has no start/enable route
    const labels = screen.getAllByRole('button').map((b) => b.textContent || '');
    expect(labels.some((t) => /enable|start|configure|restart/i.test(t))).toBe(false);
  });

  it('keeps an unknown domain distinct from an unavailable sidecar', async () => {
    mockRoutes((u) => (u.startsWith('/api/signals/brief/')
      ? {
        status: 200,
        body: {
          domain: 'weather', known_domain: false, available: true, reason: null,
          top: [], count: 0, headline: 'unknown domain', freshness: {},
        },
      }
      : null));
    render(<OsintPanel />);
    fireEvent.change(screen.getByLabelText('domain'), { target: { value: 'weather' } });
    fireEvent.keyDown(screen.getByLabelText('domain'), { key: 'Enter' });

    await waitFor(() => expect(screen.getByText('unknown domain')).toBeTruthy());
    expect(document.body.textContent).not.toMatch(/signal layer unavailable/);
    expect(document.body.textContent).toMatch(/known_domain false/);
  });

  it('never presents the truncated top list as the domain total', async () => {
    mockRoutes((u) => (u.startsWith('/api/signals/brief/')
      ? {
        status: 200,
        body: {
          domain: 'cyber', known_domain: true, available: true, reason: null,
          top: [{ title: 'ransomware crew hits port', severity: 4 }],
          count: 9, headline: '9 cyber signal(s)', freshness: { fetched_at: '2026-09-01T00:00:00Z' },
        },
      }
      : null));
    render(<OsintPanel />);
    fireEvent.click(screen.getByText('cyber'));

    await waitFor(() => expect(screen.getByText('9 cyber signal(s)')).toBeTruthy());
    expect(screen.getByText('count 9 routed into cyber')).toBeTruthy();
    expect(screen.getByText('showing top 1 of 9 (severity-ranked)')).toBeTruthy();
    expect(screen.getByText('ransomware crew hits port')).toBeTruthy();
    expect(screen.getByText('sev 4')).toBeTruthy();
  });
});
