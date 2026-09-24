// @ts-nocheck
/* H200 / H153 — the Webhooks console panel creates, switches and deletes inbound hooks
   with the admin credential, shows a new hook's token or secret exactly once, and asks
   before deleting. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { WebhooksPanel, triggerUrl } from '../panels/webhooks';
import { CONSOLE_PANELS } from '../console-routes';

let hooks;
let calls;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
  hooks = [{ id: 'hk1', name: 'ci', target: 'jarvis', target_type: 'agent', signed: false, enabled: true,
             token_hint: 'AbCd…', calls: 3, last_called: 1790000000, created_at: 1780000000 }];
  calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, url: u, body, admin: (init.headers || {})['X-Admin-Token'] });
    if (method === 'GET' && u.endsWith('/api/webhooks')) return reply(200, { webhooks: hooks });
    if (method === 'POST' && u.endsWith('/api/webhooks')) {
      if (body.target === 'refuse-me') return reply(400, { error: 'invalid webhook target' });
      const rec = { id: 'hk2', name: body.name || body.target, target: body.target, target_type: body.target_type,
                    signed: body.signed, enabled: true, token: 'tok-ONE-TIME', calls: 0, last_called: null,
                    signing_secret: body.signed ? 'sec-ONE-TIME' : null, created_at: 1790000100 };
      hooks = [{ ...rec, token: undefined, signing_secret: undefined, token_hint: 'tok-…' }, ...hooks];
      return reply(200, rec);
    }
    if (method === 'PATCH') return reply(200, { ok: true, webhook: { ...hooks[0], enabled: body.enabled } });
    if (method === 'DELETE') return reply(200, { ok: true });
    return reply(404, { error: 'unexpected' });
  });
});

const sent = (method) => calls.filter((c) => c.method === method);

describe('WebhooksPanel', () => {
  it('is registered in the console Interop group', () => {
    expect(CONSOLE_PANELS.find((p) => p.id === 'webhooks')).toEqual(
      { id: 'webhooks', label: 'Webhooks', group: 'Interop', component: 'WebhooksPanel' });
  });

  it('lists hooks with the admin credential and never shows a secret from the list', async () => {
    const { container } = render(<WebhooksPanel />);
    await waitFor(() => expect(screen.getByText('ci')).toBeTruthy());
    expect(sent('GET')[0].admin).toBe('admin-secret');
    expect(container.textContent).toContain('agent:jarvis');
    expect(container.textContent).toContain('token AbCd…');
    fireEvent.click(screen.getByText('ci'));
    expect(container.textContent).toContain(triggerUrl('hk1'));
    expect(container.textContent).toContain('3 calls');
    expect(screen.queryByTestId('webhook-secret')).toBeNull();
  });

  it('shows a new token once, and drops it on dismiss', async () => {
    const { container } = render(<WebhooksPanel />);
    await waitFor(() => expect(screen.getByText('ci')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'friday' } });
    fireEvent.click(screen.getByText('create'));
    await waitFor(() => expect(screen.getByTestId('webhook-secret').textContent).toBe('tok-ONE-TIME'));
    expect(sent('POST')[0]).toMatchObject({ admin: 'admin-secret',
      body: { name: '', target: 'friday', target_type: 'agent', signed: false } });
    expect(container.textContent).toContain(triggerUrl('hk2'));
    expect(container.textContent).toContain('X-Webhook-Token');
    await waitFor(() => expect(sent('GET').length).toBe(2));   // the list reloaded, without the token
    fireEvent.click(screen.getByText('I have saved it'));
    expect(screen.queryByTestId('webhook-secret')).toBeNull();
    expect(container.textContent).not.toContain('tok-ONE-TIME');
  });

  it('shows a signed hook its signing secret, not the unused token', async () => {
    render(<WebhooksPanel />);
    await waitFor(() => expect(screen.getByText('ci')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('target type'), { target: { value: 'workflow' } });
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'triage' } });
    fireEvent.click(screen.getByLabelText(/HMAC-signed/));
    fireEvent.click(screen.getByText('create'));
    await waitFor(() => expect(screen.getByTestId('webhook-secret').textContent).toBe('sec-ONE-TIME'));
    expect(sent('POST')[0].body).toMatchObject({ target: 'triage', target_type: 'workflow', signed: true });
    expect(screen.getByRole('alert').textContent).toContain('X-Signature-256');
    expect(screen.getByRole('alert').textContent).not.toContain('tok-ONE-TIME');
  });

  it('does not delete until asked twice', async () => {
    render(<WebhooksPanel />);
    await waitFor(() => expect(screen.getByText('ci')).toBeTruthy());
    fireEvent.click(screen.getByText('delete…'));
    expect(sent('DELETE')).toEqual([]);
    fireEvent.click(screen.getByText('keep it'));
    expect(screen.queryByText('delete for good')).toBeNull();
    fireEvent.click(screen.getByText('delete…'));
    fireEvent.click(screen.getByText('delete for good'));
    await waitFor(() => expect(sent('DELETE').length).toBe(1));
    expect(sent('DELETE')[0]).toMatchObject({ admin: 'admin-secret' });
    expect(sent('DELETE')[0].url).toContain('/api/webhooks/hk1');
  });

  it('switches a hook off with the admin credential', async () => {
    render(<WebhooksPanel />);
    await waitFor(() => expect(screen.getByText('ci')).toBeTruthy());
    fireEvent.click(screen.getByText('switch off'));
    await waitFor(() => expect(sent('PATCH').length).toBe(1));
    expect(sent('PATCH')[0]).toMatchObject({ admin: 'admin-secret', body: { enabled: false } });
    expect(sent('PATCH')[0].url).toContain('/api/webhooks/hk1');
  });

  it("says why the hub refused, and asks for a target before posting", async () => {
    render(<WebhooksPanel />);
    await waitFor(() => expect(screen.getByText('ci')).toBeTruthy());
    fireEvent.click(screen.getByText('create'));
    expect(screen.getByRole('status').textContent).toContain('name the agent');
    expect(sent('POST')).toEqual([]);
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'refuse-me' } });
    fireEvent.click(screen.getByText('create'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('refused · invalid webhook target'));
    expect(screen.queryByTestId('webhook-secret')).toBeNull();
  });
});
