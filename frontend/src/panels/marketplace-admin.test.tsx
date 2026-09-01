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
     · the destructive control must ARM first: the row button posts nothing.
     · `purged` in the uninstall response is the REQUEST FLAG ECHOED (skills.py:356 returns
       body.purge), and the registry DELETE underneath matches the MANIFEST TITLE while the
       panel sends the FOLDER — so the panel may never print "registry row purged", and the
       purge control may not be labelled as an unpublish it cannot perform. */
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
    fireEvent.click(screen.getByLabelText('purge registry row matching the folder string'));
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
    const { container } = render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.click(screen.getAllByText('uninstall…')[0]);
    fireEvent.change(screen.getByLabelText('skills/ folder'), { target: { value: 'weather' } });
    fireEvent.click(screen.getByText('confirm remove'));

    await waitFor(() => expect(screen.getByText(/removed skills\/weather/)).toBeTruthy());
    // purge was NOT requested, so the registry row is genuinely untouched — that is the
    // one branch where the panel may speak about the registry without hedging.
    expect(container.textContent).toContain('purge was not requested');
    expect(container.textContent).toContain('the registry row and its package blob are untouched');
  });

  /* ── REGRESSION · the `purged` echo and the folder-vs-title purge key ───────────────
     agents/core/routers/skills.py:356 answers `"purged": body.purge` — the request flag,
     not an outcome — and agents/core/skills/marketplace.py:635-636 discards
     remove_from_registry()'s boolean while DELETEing `WHERE name = ?` on a registry keyed
     by the MANIFEST TITLE. Reproduced against the real class: publish('weather') registers
     'Weather Intel'; uninstall_skill('weather', purge=True) returns removed=True and
     list_skills() still shows ['Weather Intel']. */

  it('never reports the purged ECHO as a purged registry row (folder ≠ manifest title)', async () => {
    mockRoutes((u, method) => {
      if (u === '/api/skills/marketplace/uninstall' && method === 'POST') {
        // exactly what the route sends back: purged is body.purge, handed straight back
        return { status: 200, body: { ok: true, uninstalled: 'weather', removed: true, purged: true } };
      }
      return null;
    });
    const { container } = render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.click(screen.getAllByText('uninstall…')[0]);
    fireEvent.change(screen.getByLabelText('skills/ folder'), { target: { value: 'weather' } });
    fireEvent.click(screen.getByLabelText('purge registry row matching the folder string'));
    fireEvent.click(screen.getByText('confirm remove'));

    await waitFor(() => expect(screen.getByText(/removed skills\/weather/)).toBeTruthy());
    const txt = container.textContent || '';
    // the lie: the registry row survives under the title 'Weather Intel'
    expect(txt).not.toContain('registry row purged');
    // what is actually knowable
    expect(txt).toContain('purge was requested');
    expect(txt).toContain('does not say whether a registry row was deleted');
    expect(txt).toContain('so that row was not deleted');
  });

  it('says a purge was IN RANGE only when the folder sent equals the manifest title', async () => {
    mockRoutes((u, method) => {
      if (u === '/api/skills/marketplace/uninstall' && method === 'POST') {
        return { status: 200, body: { ok: true, uninstalled: 'Weather Intel', removed: true, purged: true } };
      }
      return null;
    });
    const { container } = render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.click(screen.getAllByText('uninstall…')[0]);
    // folder == manifest title: the DELETE's string and the registry key coincide
    fireEvent.change(screen.getByLabelText('skills/ folder'), { target: { value: 'Weather Intel' } });
    fireEvent.click(screen.getByLabelText('purge registry row matching the folder string'));
    fireEvent.click(screen.getByText('confirm remove'));

    await waitFor(() => expect(screen.getByText(/removed skills\/Weather Intel/)).toBeTruthy());
    const txt = container.textContent || '';
    expect(txt).toContain('was in range of the delete');
    expect(txt).not.toContain('so that row was not deleted');
    // still never asserted as done — the row count never reaches the wire
    expect(txt).not.toContain('registry row purged');
    expect(txt).toContain('does not say whether a registry row was deleted');
  });

  it('labels the purge box as the literal string-match it is, not as an unpublish', async () => {
    mockRoutes(() => null);
    const { container } = render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.click(screen.getAllByText('uninstall…')[0]);   // prefills folder 'weather_intel'
    const txt = container.textContent || '';
    expect(txt).not.toContain('deletes the published package too');
    expect(txt).toContain('also delete the registry row whose name equals the folder string');
    // prefilled folder 'weather_intel' ≠ title 'Weather Intel' → the box is a no-op here
    expect(txt).toContain('deletes no row published from this skill');
  });

  it('does not print the purged echo beside "nothing was deleted from disk"', async () => {
    mockRoutes((u, method) => {
      if (u === '/api/skills/marketplace/uninstall' && method === 'POST') {
        return { status: 200, body: { ok: true, uninstalled: 'weather_intel', removed: false, purged: true } };
      }
      return null;
    });
    const { container } = render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText('Weather Intel')).toBeTruthy());

    fireEvent.click(screen.getAllByText('uninstall…')[0]);
    fireEvent.click(screen.getByLabelText('purge registry row matching the folder string'));
    fireEvent.click(screen.getByText('confirm remove'));

    await waitFor(() => expect(screen.getByText(/nothing was deleted from disk/)).toBeTruthy());
    const txt = container.textContent || '';
    expect(txt).not.toContain('purged: true');
    expect(txt).toContain('purge was requested');
  });

  it('renders a 503 from GET /skills as offline, never as an empty installed tree', async () => {
    mockRoutes((u) => (u === '/skills' ? { status: 503, body: { error: 'not initialized' } } : null));
    render(<MarketplaceAdminPanel />);
    await waitFor(() => expect(screen.getByText(/offline · GET \/skills -> 503/)).toBeTruthy());
    expect(screen.queryByText('nothing yet')).toBeNull();
  });
});
