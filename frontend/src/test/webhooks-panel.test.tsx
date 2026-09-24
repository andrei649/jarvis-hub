// @ts-nocheck
/* H200 / H153 — the Webhooks console panel creates, switches and deletes inbound hooks
   with the admin credential, shows a new hook's token or secret exactly once, and asks
   before deleting. fetch is mocked. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup, act } from '@testing-library/react';
import { WebhooksPanel, parseEvents, triggerUrl } from '../panels/webhooks';
import { CONSOLE_PANELS } from '../console-routes';

let hooks;
let calls;
let receiverSetting;   // null: the settings route answers 404

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
  hooks = [{ id: 'hk1', name: 'ci', target: 'jarvis', target_type: 'agent', signed: false, enabled: true,
             token_hint: 'AbCd…', calls: 3, last_called: 1790000000, created_at: 1780000000 }];
  calls = [];
  receiverSetting = null;
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, url: u, body, admin: (init.headers || {})['X-Admin-Token'] });
    if (u.endsWith('/api/admin/settings/webhooks')) {
      if (method === 'PUT') { receiverSetting = body.values.receiver_enabled; return reply(200, { ok: true, updated: 1 }); }
      return receiverSetting === null ? reply(404, { error: 'unknown category: webhooks' })
        : reply(200, { webhooks: [{ key: 'receiver_enabled', value: receiverSetting, kind: 'toggle', source: 'set' }] });
    }
    if (method === 'GET' && u.endsWith('/api/webhooks')) return reply(200, { webhooks: hooks });
    if (method === 'POST' && u.endsWith('/api/webhooks')) {
      if (body.target === 'refuse-me') return reply(400, { error: 'invalid webhook target' });
      const rec = { id: 'hk2', name: body.name || body.target, target: body.target, target_type: body.target_type,
                    signed: body.signed, enabled: true, token: 'tok-ONE-TIME', calls: 0, last_called: null,
                    signing_secret: body.signed ? 'sec-ONE-TIME' : null, created_at: 1790000100 };
      hooks = [{ ...rec, token: undefined, signing_secret: undefined, token_hint: 'tok-…' }, ...hooks];
      return reply(200, rec);
    }
    const id = decodeURIComponent(u.split('/api/webhooks/')[1] || '');
    const known = hooks.find((h) => h.id === id);
    if (method === 'PATCH') {
      if (!known) return reply(404, { error: 'webhook not found' });
      hooks = hooks.map((h) => (h.id === id ? { ...h, ...body } : h));
      return reply(200, { ok: true, webhook: { ...known, ...body } });
    }
    if (method === 'DELETE') {
      if (!known) return reply(404, { ok: false, error: 'webhook not found' });
      hooks = hooks.filter((h) => h.id !== id);
      return reply(200, { ok: true });
    }
    return reply(404, { error: 'unexpected' });
  });
});

const sent = (method) => calls.filter((c) => c.method === method);
// reads of the hook list only: the panel also reads the receiver setting
const listReads = () => calls.filter((c) => c.method === 'GET' && c.url.endsWith('/api/webhooks'));

describe('WebhooksPanel', () => {
  it('is registered in the console Interop group', () => {
    expect(CONSOLE_PANELS.find((p) => p.id === 'webhooks')).toEqual(
      { id: 'webhooks', label: 'Webhooks', group: 'Interop', component: 'WebhooksPanel' });
  });

  it('lists hooks with the admin credential and never shows a secret from the list', async () => {
    const { container } = render(<WebhooksPanel />);
    await waitFor(() => expect(screen.getByText('ci')).toBeTruthy());
    expect(listReads()[0].admin).toBe('admin-secret');
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
    await waitFor(() => expect(listReads().length).toBe(2));   // the list reloaded, without the token
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
    const reveal = screen.getByTestId('webhook-reveal');
    expect(reveal.textContent).toContain('X-Signature-256');
    expect(reveal.textContent).not.toContain('tok-ONE-TIME');
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

/* H200 review — the list is reloaded after every switch or delete, whatever the hub
   answered; a row's buttons are held while its call is pending; each button names its
   hook; focus follows the control that replaced the one clicked; the one-time secret
   is not inside the alert; the trigger URL is pinned to a literal. */
describe('WebhooksPanel after review', () => {
  const second = { id: 'hk3', name: 'deploy', target: 'triage', target_type: 'workflow', signed: true, enabled: false,
                   token_hint: 'WxYz…', calls: 0, last_called: null, created_at: 1770000000 };
  const ready = async () => { await waitFor(() => expect(screen.getByText('ci')).toBeTruthy()); };
  const gets = () => listReads().length;
  afterEach(() => {
    vi.restoreAllMocks();
    delete navigator.clipboard;
  });

  it('reloads the list after a switch', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.click(screen.getByText('switch off'));
    await waitFor(() => expect(gets()).toBe(2));
    await waitFor(() => expect(screen.getByText('switch on')).toBeTruthy());   // the reloaded row says off
  });

  it('reloads the list after a delete, and the row is gone', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.click(screen.getByText('delete…'));
    fireEvent.click(screen.getByText('delete for good'));
    await waitFor(() => expect(gets()).toBe(2));
    await waitFor(() => expect(screen.queryByText('ci')).toBeNull());
  });

  it('holds a row while its call is pending: a double click sends one DELETE and no refusal', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.click(screen.getByText('delete…'));
    const confirm = screen.getByText('delete for good');
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(gets()).toBe(2));
    expect(sent('DELETE')).toHaveLength(1);
    expect(screen.queryByRole('status')?.textContent || '').not.toContain('refused');
  });

  it('holds the switch while its call is pending, and frees it after', async () => {
    let release;
    const real = global.fetch;
    global.fetch = vi.fn((url, init = {}) => ((init.method || 'GET') === 'PATCH'
      ? new Promise((resolve) => { release = () => resolve(real(url, init)); })
      : real(url, init)));
    render(<WebhooksPanel />);
    await ready();
    const toggle = screen.getByRole('button', { name: 'switch off ci' });
    fireEvent.click(toggle);
    expect(toggle.disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'delete ci…' }).disabled).toBe(true);
    fireEvent.click(toggle);
    await act(async () => { release(); });
    await waitFor(() => expect(screen.getByRole('button', { name: 'switch on ci' }).disabled).toBe(false));
    expect(sent('PATCH')).toHaveLength(1);
  });

  it('a hook deleted elsewhere: the switch says so and the ghost row goes', async () => {
    render(<WebhooksPanel />);
    await ready();
    hooks = [];                                    // deleted by another tab or the CLI
    fireEvent.click(screen.getByText('switch off'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('ci no longer exists'));
    await waitFor(() => expect(screen.queryByText('agent:jarvis')).toBeNull());
    expect(gets()).toBe(2);
  });

  it('a hook deleted elsewhere: the delete says it was already gone and reloads', async () => {
    render(<WebhooksPanel />);
    await ready();
    hooks = [];
    fireEvent.click(screen.getByText('delete…'));
    fireEvent.click(screen.getByText('delete for good'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('ci was already deleted'));
    await waitFor(() => expect(screen.queryByText('agent:jarvis')).toBeNull());
    expect(screen.queryByText('delete for good')).toBeNull();
  });

  it('a refused delete keeps the confirmation, says why, and still reloads', async () => {
    const real = global.fetch;
    global.fetch = vi.fn((url, init = {}) => ((init.method || 'GET') === 'DELETE'
      ? Promise.resolve(reply(401, { detail: 'admin token required' })) : real(url, init)));
    vi.spyOn(window, 'prompt').mockReturnValue('');
    render(<WebhooksPanel />);
    await ready();
    fireEvent.click(screen.getByText('delete…'));
    fireEvent.click(screen.getByText('delete for good'));
    await waitFor(() => expect(screen.getAllByRole('status').map((n) => n.textContent)).toContain('refused · admin token required'));
    expect(screen.getByText('delete for good')).toBeTruthy();
    await waitFor(() => expect(gets()).toBe(2));
  });

  it('creates once per click burst, and not again until the secret is dismissed', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'friday' } });
    const create = screen.getByText('create');
    fireEvent.click(create);
    fireEvent.click(create);
    await waitFor(() => expect(screen.getByTestId('webhook-secret')).toBeTruthy());
    expect(sent('POST')).toHaveLength(1);
    expect(create.disabled).toBe(true);            // a second hook would replace this secret
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'pepper' } });
    fireEvent.click(create);
    expect(sent('POST')).toHaveLength(1);
    fireEvent.click(screen.getByText('I have saved it'));
    expect(create.disabled).toBe(false);
  });

  it('names the hook in every row button', async () => {
    hooks = [...hooks, second];
    render(<WebhooksPanel />);
    await ready();
    expect(screen.getByRole('button', { name: 'switch off ci' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'switch on deploy' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'delete deploy…' }));
    expect(screen.getByRole('button', { name: 'delete deploy for good' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'keep deploy' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'delete ci…' })).toBeTruthy();   // the other row is untouched
  });

  it('moves focus to the control that replaced the one clicked', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'delete ci…' }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'delete ci for good' }));
    fireEvent.click(screen.getByRole('button', { name: 'keep ci' }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'delete ci…' }));
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'friday' } });
    fireEvent.click(screen.getByText('create'));
    await waitFor(() => expect(screen.getByTestId('webhook-secret')).toBeTruthy());
    fireEvent.click(screen.getByText('I have saved it'));
    expect(document.activeElement).toBe(screen.getByLabelText('webhook name'));
  });

  it('alerts with the warning sentence only: the secret is not read aloud', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'friday' } });
    fireEvent.click(screen.getByText('create'));
    await waitFor(() => expect(screen.getByTestId('webhook-secret').textContent).toBe('tok-ONE-TIME'));
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toBe('Save these now. The token is shown once and never again.');
    expect(alert.contains(screen.getByTestId('webhook-secret'))).toBe(false);
  });

  it('says "copied" in a polite live region', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<WebhooksPanel />);
    await ready();
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'friday' } });
    fireEvent.click(screen.getByText('create'));
    await waitFor(() => expect(screen.getByTestId('webhook-secret')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'copy the token' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('tok-ONE-TIME'));
    const regions = () => [...document.querySelectorAll('[aria-live="polite"]')].map((n) => n.textContent);
    await waitFor(() => expect(regions()).toContain('the token is copied'));
    expect(regions()).not.toContain('the URL is copied');
  });

  it('warns that a loopback URL is not reachable from another machine', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'friday' } });
    fireEvent.click(screen.getByText('create'));
    await waitFor(() => expect(screen.getByTestId('webhook-secret')).toBeTruthy());
    expect(new URL(window.location.origin).hostname).toBe('localhost');
    expect(screen.getByTestId('webhook-reveal').textContent).toContain('A sender elsewhere needs one it can reach');
  });
});

describe('triggerUrl', () => {
  afterEach(() => { delete window.__NERVA_BASE_PATH__; });

  it('is the page origin, the base path and the encoded id', () => {
    window.__NERVA_BASE_PATH__ = '/nerva';
    expect(triggerUrl('a b/c?d#e%')).toBe(`${window.location.origin}/nerva/api/webhooks/a%20b%2Fc%3Fd%23e%25`);
    delete window.__NERVA_BASE_PATH__;
    expect(triggerUrl('hk1')).toBe(`${window.location.origin}/api/webhooks/hk1`);
  });

  it('never throws while rendering an id no URL can carry', () => {
    expect(() => triggerUrl('\ud800')).not.toThrow();
  });
});

/* H153 — the rest of a Hermes subscription: the receiver switch, and each hook's
   event list and prompt template. */
describe('WebhooksPanel subscriptions', () => {
  const ready = async () => { await waitFor(() => expect(screen.getByText('ci')).toBeTruthy()); };

  it('switches the receiver through the audited settings route and says when it is off', async () => {
    receiverSetting = true;
    render(<WebhooksPanel />);
    await ready();
    const toggle = await screen.findByRole('button', { name: 'switch the receiver off' });
    expect(screen.queryByTestId('receiver-off')).toBeNull();
    fireEvent.click(toggle);
    await waitFor(() => expect(sent('PUT')).toHaveLength(1));
    expect(sent('PUT')[0]).toMatchObject({ admin: 'admin-secret', body: { values: { receiver_enabled: false } } });
    expect(sent('PUT')[0].url).toContain('/api/admin/settings/webhooks');
    await waitFor(() => expect(screen.getByTestId('receiver-off').textContent).toContain('every delivery is refused'));
    fireEvent.click(screen.getByRole('button', { name: 'switch the receiver on' }));
    await waitFor(() => expect(screen.queryByTestId('receiver-off')).toBeNull());
    expect(sent('PUT')[1].body).toEqual({ values: { receiver_enabled: true } });
  });

  it('never guesses the receiver: unread, it cannot be switched', async () => {
    render(<WebhooksPanel />);
    await ready();
    expect(screen.getByText('not read')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'switch the receiver off' }).disabled).toBe(true);
    expect(screen.queryByTestId('receiver-off')).toBeNull();
  });

  it('creates a hook with an event list and a prompt template', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.change(screen.getByLabelText('target'), { target: { value: 'friday' } });
    fireEvent.change(screen.getByLabelText('events'), { target: { value: ' push, issues ,, ' } });
    fireEvent.change(screen.getByLabelText('prompt template'), { target: { value: 'New {event} by {sender.login}' } });
    fireEvent.click(screen.getByText('create'));
    await waitFor(() => expect(sent('POST')).toHaveLength(1));
    expect(sent('POST')[0].body).toMatchObject({ target: 'friday', events: ['push', 'issues'], prompt: 'New {event} by {sender.login}' });
    await waitFor(() => expect(screen.getByTestId('webhook-secret')).toBeTruthy());
    expect(screen.getByLabelText('events').value).toBe('');
    expect(screen.getByLabelText('prompt template').value).toBe('');
  });

  it('changes a hook’s events and template in its detail pane, with the admin credential', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.click(screen.getByText('ci'));
    const events = screen.getByLabelText('events for ci');
    expect(events.value).toBe('');
    fireEvent.change(events, { target: { value: 'push' } });
    fireEvent.change(screen.getByLabelText('prompt template for ci'), { target: { value: '{event}!' } });
    fireEvent.click(screen.getByRole('button', { name: 'save the events and template of ci' }));
    await waitFor(() => expect(sent('PATCH')).toHaveLength(1));
    expect(sent('PATCH')[0]).toMatchObject({ admin: 'admin-secret', body: { events: ['push'], prompt: '{event}!' } });
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('ci saved'));
    await waitFor(() => expect(listReads()).toHaveLength(2));
    await waitFor(() => expect(screen.getByText('1 event')).toBeTruthy());
    expect(screen.getByLabelText('events for ci').value).toBe('push');
  });

  it('refreshes the editor when the hook changed elsewhere', async () => {
    render(<WebhooksPanel />);
    await ready();
    fireEvent.click(screen.getByText('ci'));
    expect(screen.getByLabelText('events for ci').value).toBe('');
    hooks = [{ ...hooks[0], events: ['issues'], prompt: 'from the CLI' }];
    fireEvent.click(screen.getByText('↻'));
    await waitFor(() => expect(screen.getByLabelText('events for ci').value).toBe('issues'));
    expect(screen.getByLabelText('prompt template for ci').value).toBe('from the CLI');
  });

  it('shows what the event list turned away', async () => {
    hooks = [{ ...hooks[0], events: ['push'], prompt: '{event}', skipped: 3, last_skipped_event: 'ping' }];
    const { container } = render(<WebhooksPanel />);
    await ready();
    fireEvent.click(screen.getByText('ci'));
    expect(container.textContent).toContain('3 skipped · last skipped: ping');
    expect(container.textContent).toContain('events: push');
    expect(container.textContent).toContain('a prompt template');
  });

  it('flags an event list the hub could not read', async () => {
    hooks = [{ ...hooks[0], events: [], events_unreadable: true }];
    render(<WebhooksPanel />);
    await ready();
    expect(screen.getByText('event list unreadable')).toBeTruthy();
  });

  it('parses a comma-separated event list', () => {
    expect(parseEvents(' push, issues ,, Merge Request Hook ')).toEqual(['push', 'issues', 'Merge Request Hook']);
    expect(parseEvents('')).toEqual([]);
  });
});
