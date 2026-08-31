// @ts-nocheck
/* DRA-37 — `POST /api/skills/marketplace/{name}/rollback` (0.58) had no caller: the
   marketplace could publish and review packages but nothing could revert one, even though
   the version archive that backs the rollback is present in a default install. The control
   belongs in MarketplacePanel, not SkillHistoryPanel — the latter renders zero rows when
   JARVIS_SKILL_HISTORY is unset, so a button hung off it would vanish exactly when rollback
   is still perfectly usable. The 422 "no prior version archived" branch is the COMMON case,
   so the refusal assertion is a first-class part of this file: apiPost throws on 4xx, and a
   caller written without `onErr` would read as success. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MarketplacePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const LIST = { skills: [{ name: 'weather', version: '2.0.0', signed: true, review_status: 'approved' }] };

function mockApi(post) {
  const fn = vi.fn().mockImplementation((url, init) => {
    const method = (init && init.method) || 'GET';
    if (method !== 'POST') return Promise.resolve({ ok: true, status: 200, json: async () => LIST });
    return post(url, init);
  });
  global.fetch = fn;
  return fn;
}

describe('MarketplacePanel — package rollback', () => {
  it('shows each package version and rolls back through the admin route', async () => {
    try { localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
    const fn = mockApi(() => Promise.resolve({
      ok: true, status: 200,
      json: async () => ({ ok: true, name: 'weather', restored_version: '1.0.0', previous_version: '2.0.0' }),
    }));
    render(<MarketplacePanel />);
    await waitFor(() => expect(screen.getByText('weather')).toBeTruthy());
    expect(screen.getByText('2.0.0')).toBeTruthy();

    fireEvent.click(screen.getByTitle(/roll back/));

    await waitFor(() => {
      const call = fn.mock.calls.find((c) => String(c[0]).includes('/api/skills/marketplace/weather/rollback'));
      expect(call).toBeTruthy();
      expect(call[1].method).toBe('POST');
      expect(call[1].headers['X-Admin-Token']).toBe('adm');
    });
    await waitFor(() => expect(screen.getByText(/restored 1\.0\.0/)).toBeTruthy());
  });

  it('renders the 422 refusal rather than a silent success', async () => {
    mockApi(() => Promise.resolve({
      ok: false, status: 422,
      json: async () => ({ ok: false, error: "no prior version archived for 'weather'" }),
    }));
    render(<MarketplacePanel />);
    await waitFor(() => expect(screen.getByText('weather')).toBeTruthy());

    fireEvent.click(screen.getByTitle(/roll back/));

    await waitFor(() => expect(screen.getByText(/refused/)).toBeTruthy());
  });

  /* BLOCKER-hud — GET /api/skills/marketplace is admin_guard'ed. The panel read it
     without the admin flag, so on a token-configured install the list 401'd, no rows
     rendered, and DRA-37's rollback control was unreachable. */
  it('sends the admin token on the guarded list read, not just on the mutations', async () => {
    try { localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
    const fn = mockApi(() => Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true }) }));
    render(<MarketplacePanel />);
    await waitFor(() => expect(screen.getByText('weather')).toBeTruthy());
    const list = fn.mock.calls.find((c) => String(c[0]).includes('/api/skills/marketplace') && ((c[1] && c[1].method) || 'GET') === 'GET');
    expect(list).toBeTruthy();
    expect(list[1].headers['X-Admin-Token']).toBe('adm');
  });

  it('says the restored package is a registry revert, not a redeploy', async () => {
    mockApi(() => Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true }) }));
    render(<MarketplacePanel />);
    await waitFor(() => expect(screen.getByText(/registry package/)).toBeTruthy());
  });
});
