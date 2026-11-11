// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChannelsConfigPanel } from './channels-config';
import { CONSOLE_PANELS } from '../console-routes';

const SECRET = '123456789:typed-telegram-token-AAAA';
const field = (over) => ({ name: 'X', label: 'X', kind: 'text', secret: false, applies: 'restart', set: false,
  source: null, editable: true, value: null, ...over });
const LISTING = { precedence: 'env', setting: 'channels.config', channels: [
  { id: 'telegram', label: 'Telegram', note: '', running: false, restart_required: true, changed: ['TELEGRAM_BOT_TOKEN'], fields: [
    field({ name: 'TELEGRAM_BOT_TOKEN', label: 'Bot token', kind: 'secret', secret: true, set: true, source: 'hub' }),
    field({ name: 'TELEGRAM_ALLOWED_USER_IDS', label: 'Owner ids', kind: 'int_list', set: true, source: 'env', editable: false, value: '42' }),
  ] },
  { id: 'email', label: 'Email', note: '', running: true, restart_required: false, changed: [], fields: [
    field({ name: 'SMTP_HOST', label: 'SMTP host', kind: 'host' }),
  ] },
] };

function hub(routes) {
  const calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: String(url), method, body });
    const answer = routes(String(url), method, body);
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
  });
  return calls;
}

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('Channels panel', () => {
  it('is registered as an admin console panel', () => {
    expect(CONSOLE_PANELS).toContainEqual({ id: 'channels-config', label: 'Channels', group: 'Admin', component: 'ChannelsConfigPanel' });
  });

  it('shows running state, a waiting restart, and a secret only as set', async () => {
    hub(() => ({ status: 200, body: LISTING }));
    render(<ChannelsConfigPanel />);
    expect(await screen.findByText(/Restart Nerva to apply the changes to Telegram/)).toBeTruthy();
    expect(screen.getByText('running')).toBeTruthy();
    fireEvent.click(screen.getAllByText('configure')[0]);
    expect(screen.getByText('set')).toBeTruthy();
    expect(screen.getByText('set in .env')).toBeTruthy();
    expect((screen.getByLabelText('Bot token') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Bot token') as HTMLInputElement).type).toBe('password');
  });

  it('sends a secret once, clears the input, and never renders it', async () => {
    const calls = hub((url, method) => (method === 'PUT'
      ? { status: 200, body: { ok: true, secret: { name: 'TELEGRAM_BOT_TOKEN', set: true, source: 'hub' } } }
      : { status: 200, body: LISTING }));
    const { container } = render(<ChannelsConfigPanel />);
    await screen.findByText('Telegram');
    fireEvent.click(screen.getAllByText('configure')[0]);
    const input = screen.getByLabelText('Bot token') as HTMLInputElement;
    fireEvent.change(input, { target: { value: SECRET } });
    fireEvent.click(screen.getAllByText('save')[0]);
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
    const put = calls.find((c) => c.method === 'PUT');
    expect(put.url).toContain('/api/admin/channels/telegram/secret');
    expect(put.body).toEqual({ name: 'TELEGRAM_BOT_TOKEN', value: SECRET });
    await waitFor(() => expect(container.innerHTML).not.toContain(SECRET));
  });

  it('writes a plain setting and says why a refused one was refused', async () => {
    const calls = hub((url, method) => (method === 'PUT'
      ? { status: 422, body: { error: 'invalid_value', field: 'SMTP_HOST' } }
      : { status: 200, body: LISTING }));
    render(<ChannelsConfigPanel />);
    await screen.findByText('Email');
    fireEvent.click(screen.getAllByText('configure')[1]);
    fireEvent.change(screen.getByLabelText('SMTP host'), { target: { value: 'bad host' } });
    fireEvent.click(screen.getByText('save'));
    expect(await screen.findByText(/SMTP_HOST not changed · SMTP_HOST is not valid/)).toBeTruthy();
    expect(calls.find((c) => c.method === 'PUT').body).toEqual({ values: { SMTP_HOST: 'bad host' } });
  });
});
