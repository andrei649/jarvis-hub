// @ts-nocheck
/* PERMISSIONS — the consent ledger panel reads GET /api/permissions and narrows through
   POST /api/permissions/{id}/revoke. Pinned here:
     1. the read wiring and the grant rows (surface / key / scope / status);
     2. `enabled:false` is said plainly (legacy callers allowed, nothing recorded) instead of
        an empty list under a green chip;
     3. revoke POSTs the row id (computed URL) and only exists for active, non-never rows —
        `never` rows are locked with no button;
     4. a refused revoke is rendered as a refusal carrying the backend's reason, never as a
        silent success;
     5. there is no grant / widen control anywhere on the panel. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PermissionsPanel } from './permissions';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

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

const ACTIVE = {
  id: 'g1', surface: 'site', key: 'docs.example.com', scope: 'always', status: 'active',
  requested_by: 'browser', granted_by: 'owner', task_id: 101, created_at: 1_700_000_000, immutable: false,
};
const NEVER = {
  id: 'n1', surface: 'site', key: 'tracker.example', scope: 'never', status: 'never',
  requested_by: 'owner', granted_by: 'owner', task_id: null, created_at: 1_700_000_000, immutable: true,
};
const REVOKED = { ...ACTIVE, id: 'g2', key: 'old.example', status: 'revoked' };

const PAYLOAD = {
  enabled: true,
  flag: 'JARVIS_PERMISSION_LEDGER',
  active: 1,
  surfaces: ['app', 'site', 'os_input', 'file_root', 'terminal_target'],
  grants: [ACTIVE, NEVER, REVOKED],
  default_deny: [
    { surface: 'site', match: 'suffix', value: 'chase.com', category: 'bank' },
    { surface: 'app', match: 'token', value: '1password', category: 'password_manager' },
  ],
  audit: [],
};

describe('PermissionsPanel — the consent ledger is live', () => {
  it('GETs /api/permissions and lists the grants with scope + status', async () => {
    const fn = mockFetch({ '/api/permissions': PAYLOAD });
    render(<PermissionsPanel />);
    await waitFor(() => expect(screen.getByText('docs.example.com')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/permissions'))).toBe(true);
    expect(screen.getByText('always')).toBeTruthy();
    expect(screen.getByText('tracker.example')).toBeTruthy();
    expect(screen.getByText(/default-deny: 2 rules/).textContent).toContain('bank');
    // revoked rows are hidden until asked for
    expect(screen.queryByText('old.example')).toBeNull();
    fireEvent.click(screen.getByLabelText(/show consumed/));
    expect(screen.getByText('old.example')).toBeTruthy();
  });

  it('says the ledger is off instead of showing an empty list as "nothing granted"', async () => {
    mockFetch({ '/api/permissions': { ...PAYLOAD, enabled: false, active: 0, grants: [] } });
    render(<PermissionsPanel />);
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/ledger off/));
    expect(screen.getByRole('status').textContent).toContain('JARVIS_PERMISSION_LEDGER');
    expect(screen.getByRole('status').textContent).toContain('nothing is recorded');
    expect(screen.getByText('SEED')).toBeTruthy();
  });

  it('POSTs the revoke for the active row only; never rows are locked', async () => {
    const fn = mockFetch({ '/api/permissions/g1/revoke': { ok: true, grant: { ...ACTIVE, status: 'revoked' } }, '/api/permissions': PAYLOAD });
    render(<PermissionsPanel />);
    await waitFor(() => expect(screen.getByText('docs.example.com')).toBeTruthy());
    const buttons = screen.getAllByText('revoke');
    expect(buttons).toHaveLength(1);
    expect(screen.getByLabelText('immutable').textContent).toBe('locked');
    fireEvent.click(buttons[0]);
    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/permissions/g1/revoke') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
    });
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('revoked · site docs.example.com'));
  });

  it('renders a refused revoke with the backend reason instead of silently succeeding', async () => {
    mockFetch({
      '/api/permissions/g1/revoke': { __status: 409, body: { ok: false, reason: 'never_is_immutable' } },
      '/api/permissions': PAYLOAD,
    });
    render(<PermissionsPanel />);
    await waitFor(() => expect(screen.getByText('docs.example.com')).toBeTruthy());
    fireEvent.click(screen.getByText('revoke'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('refused · 409 · never_is_immutable'));
  });

  it('renders a 403 as a kernel refusal', async () => {
    mockFetch({ '/api/permissions/g1/revoke': { __status: 403, body: { detail: 'kernel denied' } }, '/api/permissions': PAYLOAD });
    render(<PermissionsPanel />);
    await waitFor(() => expect(screen.getByText('docs.example.com')).toBeTruthy());
    fireEvent.click(screen.getByText('revoke'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('refused · 403 · kernel denied'));
  });

  it('exposes no grant / widen control', async () => {
    mockFetch({ '/api/permissions': PAYLOAD });
    render(<PermissionsPanel />);
    await waitFor(() => expect(screen.getByText('docs.example.com')).toBeTruthy());
    expect(screen.queryByText(/^grant$/i)).toBeNull();
    expect(screen.queryByText(/^allow$/i)).toBeNull();
    expect(document.querySelectorAll('input[type="text"], textarea, select')).toHaveLength(0);
  });
});
