// @ts-nocheck
/* H200 review — Interop mode was stamped LIVE over seeded rows.

   All four Interop sources are admin-only routes (/api/a2a/peers, /api/admin/mcp,
   /api/admin/widgets, /api/webhooks), but only the webhooks fetch carried the admin
   credential. The view started from the seed (`{ ...V2.INTEROP }`) and the whole
   mode was marked live when any one source loaded. So on a hub whose HUD holds the
   admin token (the Webhooks panel needs it), the real webhooks list sat under a
   green LIVE chip next to the fabricated peers `home-assistant` and `partner-crm`,
   the MCP servers `github` and `sqlite-ledger`, and the seed widgets.

   Rule under test: every source is fetched with the admin credential; a section
   whose source failed is empty and says "not connected", never the seed; when no
   source answers nothing is overwritten (the mode stays "Not connected", and DEMO
   keeps its seed). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { V2 } from '../data';
import { hydrateInterop, useLiveModes } from '../api/live';
import { InteropMode } from '../modes2';

const SEED_FICTION = ['home-assistant', 'partner-crm', 'research-swarm', 'sqlite-ledger', 'qdrant-memory',
  'Decision queue', 'Compute locality', 'payment.pending', 'tg://andrei'];
const HOOK = { id: 'hk1', name: 'ci', target: 'jarvis', target_type: 'agent', enabled: true };

let saved;
beforeEach(() => { saved = V2.INTEROP; });
afterEach(() => { V2.INTEROP = saved; cleanup(); vi.restoreAllMocks(); });

describe('hydrateInterop builds the view from the sources alone', () => {
  it('returns null when no source answered, so nothing is overwritten', () => {
    expect(hydrateInterop(null, null, null, null)).toBeNull();
    expect(hydrateInterop({}, { error: 'not initialized' }, undefined, { detail: 'admin token required' })).toBeNull();
  });

  it('leaves a failed section empty and names it unavailable, never the seed', () => {
    const I = hydrateInterop(null, null, null, { webhooks: [HOOK] });
    expect(I.a2a).toEqual([]);
    expect(I.mcp).toEqual([]);
    expect(I.widgets).toEqual([]);
    expect(I.unavailable).toEqual({ a2a: true, mcp: true, widgets: true, webhooks: false });
    expect(JSON.stringify(I)).not.toMatch(/home-assistant|filesystem|Decision queue|payment\.pending/);
  });

  it('maps each real row, a switched-off hook included', () => {
    const I = hydrateInterop(
      { peers: [{ name: 'office-hub', connected: true, agents: ['jarvis'] }] },
      { servers: [{ name: 'fs', tools: [{}, {}], connected: true, scope: '/srv' }] },
      { widgets: [{ title: 'Brief', surface: 'watch', enabled: false }] },
      { webhooks: [HOOK, { id: 'hk2', name: 'deploy', target: 'triage', target_type: 'workflow', enabled: false }] },
    );
    expect(I.a2a).toEqual([{ peer: 'office-hub', protocol: 'A2A', status: 'connected', agents: ['jarvis'] }]);
    expect(I.mcp).toEqual([{ server: 'fs', tools: 2, status: 'up', scope: '/srv' }]);
    expect(I.widgets).toEqual([{ name: 'Brief', surface: 'watch', enabled: false }]);
    expect(I.webhooks).toEqual([
      { event: 'ci', dir: 'in', url: 'agent:jarvis', status: 'active' },
      { event: 'deploy', dir: 'in', url: 'workflow:triage', status: 'off' },
    ]);
    expect(I.unavailable).toEqual({ a2a: false, mcp: false, widgets: false, webhooks: false });
  });

  it('an empty list is real (none), not unavailable', () => {
    const I = hydrateInterop({ peers: [] }, null, null, null);
    expect(I.a2a).toEqual([]);
    expect(I.unavailable.a2a).toBe(false);
  });
});

describe('InteropMode renders what the sources said', () => {
  it('says "not connected" for a failed section and shows none of the seed', () => {
    V2.INTEROP = hydrateInterop(null, null, { widgets: [] }, { webhooks: [HOOK] });
    const { container } = render(<InteropMode t={{ interop: 'Interop' }} />);
    for (const fiction of SEED_FICTION) expect(container.textContent).not.toContain(fiction);
    expect(screen.getAllByText('not connected')).toHaveLength(2);    // A2A and MCP
    expect(screen.getAllByText('none')).toHaveLength(1);             // widgets: an empty real list
    expect(container.textContent).toContain('agent:jarvis');
  });

  it('keeps the seed in the corpus it was given (DEMO)', () => {
    const { container } = render(<InteropMode t={{ interop: 'Interop' }} />);
    expect(container.textContent).toContain('home-assistant');
    expect(screen.queryByText('not connected')).toBeNull();
  });

  it('links to the console panel with a name that says what it manages', () => {
    render(<InteropMode t={{ interop: 'Interop' }} />);
    const link = screen.getByRole('link', { name: 'manage webhooks' });
    expect(link.getAttribute('href')).toBe('/v2/console/webhooks');
  });
});

/* ---------- the shipped hook, against admin-guarded routes ---------- */

const ADMIN_ROUTES = ['/api/a2a/peers', '/api/admin/mcp', '/api/admin/widgets', '/api/webhooks'];
const reply = (status, body) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) });

function install(answer) {
  const seen = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').split('?')[0];
    const admin = (init.headers || {})['X-Admin-Token'];
    if (ADMIN_ROUTES.includes(path)) {
      seen.push({ path, admin: admin || null });
      if (admin !== 'admin-secret') return reply(401, { detail: 'admin token required' });
      return answer(path);
    }
    return reply(404, { error: 'not found' });
  });
  return seen;
}

let liveRef;
function Harness() { liveRef = useLiveModes(); return null; }

describe('useLiveModes hydrates Interop with the admin credential', () => {
  beforeEach(() => {
    liveRef = null;
    try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
    vi.spyOn(window, 'prompt').mockReturnValue('');
  });

  it('sends the admin token to all four sources and marks only real rows live', async () => {
    const seen = install((path) => (path === '/api/webhooks' ? reply(200, { webhooks: [HOOK] })
      : path === '/api/admin/mcp' ? reply(503, { error: 'not initialized' })
        : reply(200, path === '/api/a2a/peers' ? { peers: [] } : { widgets: [] })));
    render(<Harness />);
    await waitFor(() => expect(liveRef && liveRef.live.INTEROP).toBe(true), { timeout: 8000 });
    expect(seen.map((s) => s.path).sort()).toEqual([...ADMIN_ROUTES].sort());
    expect(seen.every((s) => s.admin === 'admin-secret')).toBe(true);
    expect(V2.INTEROP.a2a).toEqual([]);
    expect(V2.INTEROP.mcp).toEqual([]);
    expect(V2.INTEROP.unavailable).toEqual({ a2a: false, mcp: true, widgets: false, webhooks: false });
    expect(V2.INTEROP.webhooks).toEqual([{ event: 'ci', dir: 'in', url: 'agent:jarvis', status: 'active' }]);
  }, 15000);

  it('overwrites nothing and marks nothing when every source refuses', async () => {
    const seen = install(() => reply(401, { detail: 'admin token required' }));
    render(<Harness />);
    await waitFor(() => expect(seen.length).toBe(4), { timeout: 8000 });
    await new Promise((r) => setTimeout(r, 50));
    expect(liveRef.live.INTEROP).toBeFalsy();
    expect(V2.INTEROP).toBe(saved);                  // the seed, untouched, for DEMO
  }, 15000);
});
