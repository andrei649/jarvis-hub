// @ts-nocheck
/* CODE INTEL panel — GET /api/codeintel/stats + /search (user tier) and
   POST /api/codeintel/reindex (admin). fetch is mocked, like src/test/kg-panel.test.tsx.

   The refusal cases are the point: apiPost throws on 4xx and carries the parsed body, so a
   403 and a 429 must render as two DIFFERENT visible strings, taken verbatim from the
   backend, and never as a success. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CodeIntelPanel } from './codeintel';

const STATS = {
  files_indexed: 3411,
  symbol_count: 53632,
  // async_function deliberately ABSENT — by_kind omits zero-count kinds.
  by_kind: { function: 15657, class: 7099, method: 28545 },
  errors: [],
};

const HIT = {
  name: 'build_index',
  qualname: 'build_index',
  kind: 'function',
  file: 'agents/core/codeintel/index.py',
  lineno: 62,
  doc: 'Index every ``*.py`` under *root*.',
};

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

const statsOnly = (overrides = {}) => mockRoutes((u) =>
  u.includes('/api/codeintel/stats') ? { status: 200, body: { ...STATS, ...overrides } } : null);

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } vi.restoreAllMocks(); });

describe('CodeIntelPanel — the code index is reachable and honest about its scope', () => {
  it('renders the stats roll-up and one tag per by_kind key the backend actually sent', async () => {
    const fn = statsOnly();
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/codeintel/stats'))).toBe(true);
    expect(screen.getByText('53,632 symbols')).toBeTruthy();
    expect(screen.getByText('method 28,545')).toBeTruthy();
    // by_kind omitted async_function → no fabricated "async_function 0" anywhere.
    expect(screen.queryByText(/async_function/)).toBeNull();
  });

  it('issues NO search request before a query is committed, and says so rather than "nothing found"', async () => {
    const fn = statsOnly();
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/codeintel/search'))).toBe(false);
    expect(screen.getByText(/enter a symbol substring to search/)).toBeTruthy();
    expect(screen.queryByText('nothing yet')).toBeNull();
  });

  it('commits on Enter, GETs /api/codeintel/search with the query, and renders file:lineno + the doc line', async () => {
    const fn = mockRoutes((u) => {
      if (u.includes('/api/codeintel/stats')) return { status: 200, body: STATS };
      if (u.includes('/api/codeintel/search')) {
        return { status: 200, body: { query: 'build_index', kind: null, count: 1, results: [HIT] } };
      }
      return null;
    });
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('symbol substring (e.g. build_index)'), { target: { value: 'build_index' } });
    fireEvent.keyDown(screen.getByPlaceholderText('symbol substring (e.g. build_index)'), { key: 'Enter' });
    await waitFor(() => expect(screen.getByText('agents/core/codeintel/index.py:62')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]) === '/api/codeintel/search?q=build_index&kind=&limit=50')).toBe(true);
    expect(screen.getByText('build_index')).toBeTruthy();
    expect(screen.getByText('Index every ``*.py`` under *root*.')).toBeTruthy();
    expect(screen.getByText('results for "build_index"')).toBeTruthy();
    expect(screen.getByText('1 match(es)')).toBeTruthy();
  });

  it('warns that a result set is capped when count === the requested limit (count is post-slice)', async () => {
    const results = Array.from({ length: 50 }, (_, i) => ({ ...HIT, qualname: `sym_${i}`, lineno: i + 1 }));
    mockRoutes((u) => {
      if (u.includes('/api/codeintel/stats')) return { status: 200, body: STATS };
      if (u.includes('/api/codeintel/search')) return { status: 200, body: { query: 'get', kind: null, count: 50, results } };
      return null;
    });
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('symbol substring (e.g. build_index)'), { target: { value: 'get' } });
    fireEvent.click(screen.getByText('search'));
    await waitFor(() => expect(screen.getByText(/capped at limit 50, more matches may exist/)).toBeTruthy());
    expect(screen.queryByText('50 match(es)')).toBeNull();
  });

  it('surfaces parse errors as missing symbols, with the exception class verbatim', async () => {
    statsOnly({ errors: [{ file: 'x/broken.py', error: 'SyntaxError' }] });
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText(/symbols are MISSING from the index/)).toBeTruthy());
    expect(screen.getByText('x/broken.py')).toBeTruthy();
    expect(screen.getByText('SyntaxError')).toBeTruthy();
  });

  it('does not render a parse-error line when errors is empty', async () => {
    statsOnly();
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    expect(screen.queryByText(/MISSING from the index/)).toBeNull();
  });

  it('POSTs the admin reindex and shows the before → after delta', async () => {
    try { localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
    const fn = mockRoutes((u, m) => {
      if (u.includes('/api/codeintel/reindex') && m === 'POST') {
        return { status: 200, body: { ok: true, files_indexed: 3412, symbol_count: 53700 } };
      }
      if (u.includes('/api/codeintel/stats')) return { status: 200, body: STATS };
      return null;
    });
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    fireEvent.click(screen.getByTitle('reindex (admin)'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('files 3,411 → 3,412'));
    expect(screen.getByRole('alert').textContent).toContain('symbols 53,632 → 53,700');
    const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/codeintel/reindex'));
    expect(post[1].method).toBe('POST');
    expect(post[1].headers['X-Admin-Token']).toBe('adm');
  });

  it('renders a 403 refusal with the backend detail verbatim, and NOT as a success', async () => {
    const detail = 'admin disabled from network — set JARVIS_ADMIN_TOKEN to enable remote access';
    mockRoutes((u, m) => {
      if (u.includes('/api/codeintel/reindex') && m === 'POST') return { status: 403, body: { detail } };
      if (u.includes('/api/codeintel/stats')) return { status: 200, body: STATS };
      return null;
    });
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    fireEvent.click(screen.getByTitle('reindex (admin)'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain(detail));
    expect(screen.getByRole('alert').textContent).toContain('refused · 403');
    expect(screen.getByRole('alert').textContent).not.toContain('reindexed');
  });

  it('renders a 429 with its own distinct cause — refusals are not collapsed into one sentence', async () => {
    mockRoutes((u, m) => {
      if (u.includes('/api/codeintel/reindex') && m === 'POST') {
        return { status: 429, body: { error: 'rate limit exceeded', code: 429 } };
      }
      if (u.includes('/api/codeintel/stats')) return { status: 200, body: STATS };
      return null;
    });
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    fireEvent.click(screen.getByTitle('reindex (admin)'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('rate limit exceeded'));
    expect(screen.getByRole('alert').textContent).toContain('refused · 429');
  });

  /* The depth limit is FIXED (index.py now descends every statement body and skips venvs by
     their pyvenv.cfg marker), and this test moved with it rather than being deleted. It was
     correct when written: `credential_ref_matches` is defined three times under agents/ and
     search_symbols returned 0 hits; measured after the fix it returns 3, each with a qualname
     locating it inside its enclosing function. What the panel must still do is DISCLOSE the
     scope honestly — including that the old numbers were the before, not the now — because a
     zero-hit search must never read as "no such symbol in the repo". */
  it('discloses the SYMBOL-DEPTH scope, and states it as fixed rather than current', async () => {
    statsOnly();
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    expect(screen.getByText(/Symbol scope/)).toBeTruthy();
    expect(screen.getByText(/inner functions and closures/)).toBeTruthy();
    // the fixed behaviour, not the old measurement, is what the operator is told
    expect(screen.getByText(/any nesting depth/)).toBeTruthy();
    expect(screen.getByText(/dotted qualname/)).toBeTruthy();
  });

  it('renders a zero-hit search as "not in the index", never as the bare shared "nothing yet"', async () => {
    mockRoutes((u) => {
      if (u.includes('/api/codeintel/stats')) return { status: 200, body: STATS };
      // The real backend answer for a symbol that exists 3x in the repo but is nested.
      if (u.includes('/api/codeintel/search')) {
        return { status: 200, body: { query: 'credential_ref_matches', kind: null, count: 0, results: [] } };
      }
      return null;
    });
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText('3,411 files')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('symbol substring (e.g. build_index)'), { target: { value: 'credential_ref_matches' } });
    fireEvent.click(screen.getByText('search'));
    await waitFor(() => expect(screen.getByText(/not proof the name is absent from the repo/)).toBeTruthy());
    // The shared zero-state would flatly assert the symbol was not found.
    expect(screen.queryByText('nothing yet')).toBeNull();
  });

  it('renders a failed stats GET verbatim and never as zero files / zero symbols', async () => {
    mockRoutes((u) => (u.includes('/api/codeintel/stats') ? { status: 403, body: { detail: 'nope' } } : null));
    render(<CodeIntelPanel />);
    await waitFor(() => expect(screen.getByText(/GET \/api\/codeintel\/stats -> 403/)).toBeTruthy());
    expect(screen.queryByText('0 files')).toBeNull();
    expect(screen.queryByText('0 symbols')).toBeNull();
  });
});
