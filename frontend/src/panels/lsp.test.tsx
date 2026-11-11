// @ts-nocheck
/* LANGUAGE SERVERS section (H055) — GET /api/codeintel/lsp/status (user) and the admin
   install/start/stop POSTs. fetch is mocked like codeintel.test.tsx. Install must say it
   queued an approval card (nothing is downloaded); a refusal shows the backend's code. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { LspSection } from './lsp';

const STATUS = {
  enabled: true, isolation: 'bwrap', idle_seconds: 600, tools_dir: '/data/tools/lsp',
  servers: [
    { id: 'pyright', name: 'Pyright', languages: ['python'], available: true, source: 'nerva',
      installable: true, recipe: { kind: 'npm', packages: ['pyright@1.1.389'], version: '1.1.389', hint: '' } },
    { id: 'gopls', name: 'gopls', languages: ['go', 'go.mod'], available: false, source: null,
      installable: true, recipe: { kind: 'go', packages: ['golang.org/x/tools/gopls@v0.16.2'], version: 'v0.16.2', hint: '' } },
    { id: 'clangd', name: 'clangd', languages: ['c', 'cpp'], available: false, source: null,
      installable: false, recipe: { kind: 'manual', packages: [], version: '', hint: 'install clangd from your system package manager' } },
  ],
  running: [{ server: 'pyright', root: '/w', pid: 42, diagnostics_served: 3 }],
  broken: [],
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

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } vi.restoreAllMocks(); });

describe('LspSection', () => {
  it('lists servers with where each was found, the running one, and the manual hint', async () => {
    mockRoutes((u) => (u.includes('/api/codeintel/lsp/status') ? { status: 200, body: STATUS } : null));
    render(<LspSection />);
    await waitFor(() => expect(screen.getByText('found · nerva')).toBeTruthy());
    expect(screen.getByText('isolation bwrap')).toBeTruthy();
    expect(screen.getByText('pid 42')).toBeTruthy();
    expect(screen.getByText(/system package manager/)).toBeTruthy();
  });

  it('install queues an approval card and says so', async () => {
    const fn = mockRoutes((u, m) => {
      if (u.includes('/api/codeintel/lsp/status')) return { status: 200, body: STATUS };
      if (u.includes('/api/codeintel/lsp/install') && m === 'POST') {
        return { status: 202, body: { ok: true, task_id: 5, server: 'gopls', packages: ['golang.org/x/tools/gopls@v0.16.2'] } };
      }
      return null;
    });
    render(<LspSection />);
    await waitFor(() => expect(screen.getByText('install…')).toBeTruthy());
    fireEvent.click(screen.getByText('install…'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/approval card #5 queued/));
    const post = fn.mock.calls.find((c) => String(c[0]).includes('/lsp/install'));
    expect(JSON.parse(post[1].body)).toEqual({ server: 'gopls' });
  });

  it('a refused stop renders the backend refusal verbatim', async () => {
    mockRoutes((u, m) => {
      if (u.includes('/api/codeintel/lsp/status')) return { status: 200, body: STATUS };
      if (u.includes('/api/codeintel/lsp/stop') && m === 'POST') return { status: 403, body: { detail: 'admin token required' } };
      return null;
    });
    render(<LspSection />);
    await waitFor(() => expect(screen.getByText('stop')).toBeTruthy());
    fireEvent.click(screen.getByText('stop'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/refused · 403 · admin token required/));
  });
});
