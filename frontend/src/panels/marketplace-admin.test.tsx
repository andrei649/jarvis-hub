// @ts-nocheck
/* MARKETPLACE ADMIN panel — POST /api/skills/marketplace/{publish,install-zip,uninstall}
   (all admin tier) over the user-tier GET /skills read. fetch is mocked, like
   src/panels/osint.test.tsx.

   The four traps this file exists to pin:
     · GET /skills is an OBJECT MAP — arr() yields [] for it, so a regression there paints
       a full skills tree as "nothing yet".
     · apiPost throws on 4xx with the body on err.body — a refusal must render VERBATIM and
       visibly, never as a success line and never as a paraphrase.
     · uninstall's 200 {"ok":true,"removed":false} means NOTHING WAS DELETED — it must not
       read as a success.
     · the destructive control must ARM first: the row button posts nothing. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MarketplaceAdminPanel } from './marketplace-admin';

const SKILLS = {
  skills: {
    'Weather Intel': { name: 'Weather Intel', version: '1.2.0', description: 'forecast', agents: [], commands: [] },
    'Email Triage': { name: 'Email Triage', version: '0.3.1', description: 'inbox', agents: [], commands: [] },
  },
};

/* url/method -> {status, body}. Anything unmatched answers 200 with the skills map. */
function mockRoutes(handler) {
  const fn = vi.fn(async (url, init) => {
    const u = String(url);
    const method = String((init && init.method) || 'GET').toUpperCase();
    const r = handler(u, method, init) || (u === '/skills' ? { status: 200, body: SKILLS } : { status: 200, body: {} });
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  });
  global.fetch = fn;
  return fn;
}

const posts = (fn) => fn.mock.calls.filter((c) => String((c[1] && c[1].method) || 'GET').toUpperCase() === 'POST');
const bodyOf = (call) => JSON.parse(call[1].body);

async function loadZip() {
  const file = new File(['PK not a real archive'], 'pack.zip', { type: 'application/zip' });
  fireEvent.change(screen.getByLabelText('skill package zip'), { target: { files: [file] } });
  await waitFor(() => expect(screen.getByText('install package').disabled).toBe(false));
}

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } vi.restoreAllMocks(); });

describe('MarketplaceAdminPanel — the installed tree and its three lifecycle writes', () => {
  it('renders GET /skills as the OBJECT MAP it is (arr() would fabricate an empty tree)', async () => {
    mockRoutes(() => null);
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());
    expect(screen.getByText('Email Triage')).toBeTruthy();
    expect(screen.getByText('1.2.0')).toBeTruthy();
    expect(screen.queryByText('nothing yet')).toBeNull();
  });

  it('publishes the TYPED folder name at admin tier and prints only the fields the response carried', async () => {
    localStorage.setItem('hud.admin_token', 'tok');
    const fn = mockRoutes((u, method) => {
      if (u === '/api/skills/marketplace/publish' && method === 'POST') {
        return { status: 200, body: { ok: true, published: { name: 'Weather Intel', version: '1.2.0', author: 'owner', description: 'forecast' } } };
      }
      return null;
    });
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('skills directory name'), { target: { value: 'weather' } });
    fireEvent.click(screen.getByText('publish'));

    await waitFor(() => expect(screen.getByText(/published Weather Intel v1\.2\.0/)).toBeTruthy());
    const call = posts(fn).find((c) => String(c[0]) === '/api/skills/marketplace/publish');
    expect(call).toBeTruthy();
    // the FOLDER name, not the manifest title the read surface reports
    expect(bodyOf(call)).toEqual({ name: 'weather' });
    expect(call[1].headers['X-Admin-Token']).toBe('tok');
  });

  it('renders publish 404 "skill not found" verbatim as a refusal, with no success line', async () => {
    mockRoutes((u, method) => {
      if (u === '/api/skills/marketplace/publish' && method === 'POST') {
        return { status: 404, body: { error: 'skill not found' } };
      }
      return null;
    });
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('skills directory name'), { target: { value: 'Weather Intel' } });
    fireEvent.click(screen.getByText('publish'));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('skill not found');   // the backend's own string
    expect(alert.textContent).toContain('HTTP 404');
    expect(screen.queryByText(/^published /)).toBeNull();
    // the collapsed cause is explained, never split into a guess
    expect(screen.getByText(/no such directory under skills\/, or no SKILL\.md/)).toBeTruthy();
  });

  it('renders install-zip 400 verbatim and never claims a package landed', async () => {
    const fn = mockRoutes((u, method) => {
      if (u === '/api/skills/marketplace/install-zip' && method === 'POST') {
        return { status: 400, body: { error: 'skill package rejected (unsafe path or signature policy)' } };
      }
      return null;
    });
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    await loadZip();
    fireEvent.click(screen.getByText('install package'));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('skill package rejected (unsafe path or signature policy)');
    expect(alert.textContent).toContain('HTTP 400');
    expect(screen.queryByText(/new in \/skills/)).toBeNull();
    expect(screen.queryByText(/backend returned/)).toBeNull();

    // the data: prefix is stripped — an unstripped prefix corrupts into a 500 server-side
    const call = posts(fn).find((c) => String(c[0]) === '/api/skills/marketplace/install-zip');
    expect(bodyOf(call).zip_base64).not.toContain('data:');
    expect(bodyOf(call).zip_base64).not.toContain(',');
  });

  it('reports install-zip {"ok":true} as an empty /skills delta, not as an installed skill', async () => {
    mockRoutes((u, method) => {
      if (u === '/api/skills/marketplace/install-zip' && method === 'POST') return { status: 200, body: { ok: true } };
      return null;
    });
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    await loadZip();
    fireEvent.click(screen.getByText('install package'));

    await waitFor(() => expect(screen.getByText(/no new name in \/skills/)).toBeTruthy());
    expect(screen.getByText(/the response carries no skill name, version or path/)).toBeTruthy();
  });

  it('arms before it removes — the row button posts nothing', async () => {
    const fn = mockRoutes(() => null);
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.click(screen.getAllByText('uninstall…')[0]);
    expect(posts(fn)).toHaveLength(0);

    // the arm step prefills the installer's own derivation, editable and labelled as derived
    expect(screen.getByLabelText('skills/ folder').value).toBe('weather_intel');
    expect(screen.getByText('confirm remove')).toBeTruthy();
  });

  it('renders uninstall 200 {"ok":true,"removed":false} as "nothing was deleted", never as a success', async () => {
    const fn = mockRoutes((u, method) => {
      if (u === '/api/skills/marketplace/uninstall' && method === 'POST') {
        return { status: 200, body: { ok: true, uninstalled: 'weather_intel', removed: false, purged: true } };
      }
      return null;
    });
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.click(screen.getAllByText('uninstall…')[0]);
    fireEvent.click(screen.getByLabelText('purge registry row'));
    fireEvent.click(screen.getByText('confirm remove'));

    await waitFor(() => expect(screen.getByText(/removed:false — nothing was deleted from disk/)).toBeTruthy());
    expect(screen.queryByText(/^removed skills\//)).toBeNull();

    const call = posts(fn).find((c) => String(c[0]) === '/api/skills/marketplace/uninstall');
    expect(bodyOf(call)).toEqual({ name: 'weather_intel', purge: true });
  });

  it('renders a real removal as a removal, naming what the response echoed', async () => {
    mockRoutes((u, method) => {
      if (u === '/api/skills/marketplace/uninstall' && method === 'POST') {
        return { status: 200, body: { ok: true, uninstalled: 'weather', removed: true, purged: false } };
      }
      return null;
    });
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.click(screen.getAllByText('uninstall…')[0]);
    fireEvent.change(screen.getByLabelText('skills/ folder'), { target: { value: 'weather' } });
    fireEvent.click(screen.getByText('confirm remove'));

    await waitFor(() => expect(screen.getByText(/removed skills\/weather/)).toBeTruthy());
    expect(screen.getByText(/package retained/)).toBeTruthy();
  });

  it('renders a 503 from GET /skills as offline, never as an empty installed tree', async () => {
    mockRoutes((u) => (u === '/skills' ? { status: 503, body: { error: 'not initialized' } } : null));
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText(/offline · GET \/skills -> 503/)).toBeTruthy());
    expect(screen.queryByText('nothing yet')).toBeNull();
  });
});
