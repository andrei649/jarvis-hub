// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { McpPanel, deepLinkRequest } from './mcp';
import { CONSOLE_PANELS } from '../console-routes';

const PLAN = {
  name: 'vendor', origin: 'link', catalog_name: null, commit: null, transport: 'stdio',
  command: 'npx -y @vendor/mcp-server@1.2.3', url: null, host: null, env: {}, inputs: [],
  secrets: [{ name: 'VENDOR_API_KEY', prompt: 'API key', required: true, has_default: false }], needs: [],
  auth: 'none', trust: 'read-only', tools_allow: null, tools_deny: null, post_install: '',
  will_run: 'spawn on this hub: npx -y @vendor/mcp-server@1.2.3', starts: 'only when you press connect',
  digest: 'd'.repeat(64), name_taken: false, http_client_enabled: true,
};
const CATALOG = { commit: '9c0560f8e6', total: 66, counts: { ok: 66 }, http_client_enabled: false, entries: [
  { name: 'linear', status: 'ok', auth: 'oauth', description: 'Linear issues', url: 'https://mcp.linear.app/mcp', installed: false },
  { name: 'context7', status: 'ok', auth: 'none', description: 'Library docs', url: 'https://mcp.context7.com/mcp', installed: true },
] };
const SERVERS = { servers: [
  { name: 'remote', transport: 'streamable-http', url: 'https://mcp.example.test/mcp', connected: false, auth: 'oauth',
    secrets: [], oauth: { signed_in: false, pending: false } },
] };

function hub(routes) {
  const calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: String(url), method, body });
    const a = routes(String(url), method, body);
    return { ok: a.status < 400, status: a.status, json: async () => a.body };
  });
  return calls;
}

const base = (url, method) => {
  if (url.includes('/api/admin/mcp/catalog/preview')) return { status: 200, body: { ok: true, plan: PLAN } };
  if (url.includes('/api/admin/mcp/catalog')) return { status: 200, body: CATALOG };
  if (url.endsWith('/api/admin/mcp')) return { status: 200, body: SERVERS };
  return { status: 404, body: { error: 'nope' } };
};

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); window.history.replaceState({}, '', '/v2/console/mcp'); });

describe('MCP panel', () => {
  it('is registered as a console panel', () => {
    expect(CONSOLE_PANELS).toContainEqual({ id: 'mcp', label: 'MCP Servers', group: 'Interop', component: 'McpPanel' });
  });

  it('lists the servers and the catalog, with a search', async () => {
    const calls = hub(base);
    render(<McpPanel />);
    expect(await screen.findByText('remote')).toBeTruthy();
    const catalog = await screen.findByRole('list', { name: 'MCP catalog' });
    expect(within(catalog).getByText('linear')).toBeTruthy();
    expect(within(catalog).getByText('installed')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Find'), { target: { value: 'linear' } });
    await waitFor(() => expect(calls.some((c) => c.url.includes('/api/admin/mcp/catalog?q=linear'))).toBe(true));
  });

  it('shows exactly what will run and installs only after the owner confirms, with the digest', async () => {
    let installed = null;
    const calls = hub((url, method, body) => {
      if (url.includes('/catalog/install')) { installed = body; return { status: 200, body: { ok: true, message: 'installed' } }; }
      return base(url, method);
    });
    window.history.replaceState({}, '', '/v2/console/mcp?link=vendor&config=eyJjb21tYW5kIjoibnB4In0');
    render(<McpPanel />);
    const card = await screen.findByRole('dialog');
    expect(await within(card).findByTestId('will-run')).toHaveProperty('textContent', 'spawn on this hub: npx -y @vendor/mcp-server@1.2.3');
    expect(within(card).getByText(/from a link, not in the reviewed catalog/)).toBeTruthy();
    const install = within(card).getByRole('button', { name: 'Install' });
    expect(install.disabled).toBe(true);
    // The link only opened the card: nothing was installed.
    expect(calls.some((c) => c.url.includes('/catalog/install'))).toBe(false);
    fireEvent.change(within(card).getByLabelText(/API key/), { target: { value: 'sk-typed' } });
    fireEvent.click(within(card).getByLabelText('I have read what will run'));
    expect(install.disabled).toBe(false);
    fireEvent.click(install);
    await waitFor(() => expect(installed).not.toBeNull());
    expect(installed.confirm).toBe(PLAN.digest);
    expect(installed.secrets).toEqual({ VENDOR_API_KEY: 'sk-typed' });
    expect(installed.link_config).toBe('eyJjb21tYW5kIjoibnB4In0');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('starts the sign-in and relays a pasted return address with the binding', async () => {
    let relayed = null;
    hub((url, method, body) => {
      if (url.includes('/oauth/start')) return { status: 200, body: { ok: true, authorization_url: 'https://auth.example.test/authorize?x=1',
        state: 'st', binding: 'bind-1', as_host: 'auth.example.test', server_origin: 'https://mcp.example.test:443' } };
      if (url.includes('/oauth/callback')) { relayed = body; return { status: 200, body: { ok: true } }; }
      return base(url, method);
    });
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    render(<McpPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'sign in' }));
    expect(await screen.findByText(/The token is sent only to/)).toBeTruthy();
    expect(open).toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Paste the address it ended on/), { target: { value: 'http://127.0.0.1:47123/callback?code=c1&state=st' } });
    fireEvent.click(screen.getByRole('button', { name: 'finish sign-in' }));
    await waitFor(() => expect(relayed).toEqual({ state: 'st', binding: 'bind-1', code: 'c1' }));
  });

  it('reads only well-formed deep links', () => {
    expect(deepLinkRequest('?install=linear')).toEqual({ name: 'linear' });
    expect(deepLinkRequest('?install=../x')).toBeNull();
    expect(deepLinkRequest('?link=v&config=' + 'A'.repeat(32 * 1024 + 1))).toBeNull();
    expect(deepLinkRequest('?link=v&config=abc')).toEqual({ name: 'v', link_config: 'abc' });
  });
});
