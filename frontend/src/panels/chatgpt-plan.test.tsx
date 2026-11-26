import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { IntegrationsPanel } from './integrations';

const AUTH_URL = 'https://auth.openai.com/api/accounts/authorize?state=synthetic';
const reply = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });

function hub(handler: (url: string, method: string, body: unknown) => unknown) {
  const calls: Array<{ url: string; method: string; body: unknown }> = [];
  global.fetch = vi.fn(async (input, init = {}) => {
    const url = String(input);
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url.endsWith('/api/admin/integrations')) return reply({ integrations: [], search: {}, video: {} });
    return handler(url, method, body) as ReturnType<typeof reply>;
  }) as unknown as typeof fetch;
  return calls;
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.lang = 'en';
});

describe('ChatGPT plan in Integrations', () => {
  it('keeps the owner account and its status request out of the demo', async () => {
    const calls = hub(() => reply({ connected: true }));
    const previous = window.location.href;
    window.history.replaceState({}, '', '?demo=1');
    try {
      render(<IntegrationsPanel />);
      await screen.findByRole('list', { name: 'integrations' });
      expect(screen.queryByRole('listitem', { name: /ChatGPT plan/i })).toBeNull();
      expect(calls.some(call => call.url.includes('/api/admin/chatgpt-plan'))).toBe(false);
    } finally {
      window.history.replaceState({}, '', previous);
    }
  });
  it('appears in all and model views, separated from OpenAI API keys', async () => {
    const calls = hub(() => reply({ connected: false }));
    render(<IntegrationsPanel />);
    const card = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    expect(within(card).getByText(/account connection/i)).toBeTruthy();
    expect(within(card).queryByLabelText(/API key/i)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'models' }));
    expect(screen.getByRole('listitem', { name: /ChatGPT plan/i })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'search' }));
    expect(screen.queryByRole('listitem', { name: /ChatGPT plan/i })).toBeNull();
    expect(calls.some(c => c.url.endsWith('/api/admin/chatgpt-plan') && c.method === 'GET')).toBe(true);
  });

  it('starts only on user action, validates the official authorization URL and hides the link without a cancellation claim', async () => {
    const calls = hub((url, method) => url.endsWith('/connect') && method === 'POST'
      ? reply({ url: AUTH_URL }) : reply({ connected: false }));
    render(<IntegrationsPanel />);
    const card = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    expect(calls.some(c => c.method === 'POST')).toBe(false);
    fireEvent.click(within(card).getByRole('button', { name: 'Continue with ChatGPT' }));
    const link = await within(card).findByRole('link', { name: /open ChatGPT sign-in/i });
    expect(link.getAttribute('href')).toBe(AUTH_URL);
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(link.getAttribute('rel')).toContain('noreferrer');
    expect(calls.find(c => c.url.endsWith('/connect'))?.body).toEqual({});
    fireEvent.click(within(card).getByRole('button', { name: 'Hide sign-in link' }));
    expect(within(card).queryByRole('link', { name: /open ChatGPT sign-in/i })).toBeNull();
  });

  it('rejects an off-host authorization URL without opening a link', async () => {
    hub((url) => url.endsWith('/connect') ? reply({ url: 'https://example.test/api/accounts/authorize' }) : reply({ connected: false }));
    render(<IntegrationsPanel />);
    const card = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    fireEvent.click(within(card).getByRole('button', { name: 'Continue with ChatGPT' }));
    expect(await within(card).findByRole('status')).toHaveProperty('textContent', expect.stringMatching(/sign-in link unavailable/i));
    expect(within(card).queryByRole('link')).toBeNull();
  });

  it('refreshes connection explicitly, lists models in backend order, then disconnects', async () => {
    let connected = false;
    const calls = hub((url, method) => {
      if (url.endsWith('/models')) return reply({ models: [
        { slug: 'first', display_name: 'First' }, { slug: 'second', display_name: 'Second' },
      ] });
      if (url.endsWith('/disconnect') && method === 'POST') { connected = false; return reply({}); }
      return reply({ connected });
    });
    render(<IntegrationsPanel />);
    const card = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    await within(card).findByText(/not connected/i);
    connected = true;
    fireEvent.click(within(card).getByRole('button', { name: /Refresh connection/i }));
    await within(card).findByText(/connected/i);
    expect(calls.some(c => c.url.endsWith('/models'))).toBe(false);
    fireEvent.click(within(card).getByRole('button', { name: /Show available models/i }));
    const models = await within(card).findByRole('list', { name: /available models/i });
    expect(within(models).getAllByRole('listitem').map(node => node.textContent)).toEqual(['First (first)', 'Second (second)']);
    fireEvent.click(within(card).getByRole('button', { name: /Disconnect/i }));
    await within(card).findByText(/not connected/i);
    expect(within(card).getByRole('status').textContent).toMatch(/removed from this hub/i);
    expect(within(card).queryByRole('list', { name: /available models/i })).toBeNull();
    expect(calls.find(c => c.url.endsWith('/disconnect'))?.body).toEqual({});
  });

  it('ignores a connect response after cancellation and a model response after disconnect', async () => {
    let finishConnect!: (value: unknown) => void;
    let finishModels!: (value: unknown) => void;
    let connected = false;
    hub((url) => {
      if (url.endsWith('/connect')) return new Promise(resolve => { finishConnect = resolve; });
      if (url.endsWith('/models')) return new Promise(resolve => { finishModels = resolve; });
      if (url.endsWith('/disconnect')) { connected = false; return reply({}); }
      return reply({ connected });
    });
    render(<IntegrationsPanel />);
    const card = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    fireEvent.click(within(card).getByRole('button', { name: 'Continue with ChatGPT' }));
    fireEvent.click(within(card).getByRole('button', { name: 'Cancel' }));
    finishConnect(reply({ url: AUTH_URL }));
    await waitFor(() => expect(within(card).queryByRole('link')).toBeNull());
    connected = true;
    fireEvent.click(within(card).getByRole('button', { name: /Refresh connection/i }));
    await within(card).findByText(/connected/i);
    fireEvent.click(within(card).getByRole('button', { name: /Show available models/i }));
    fireEvent.click(within(card).getByRole('button', { name: /Disconnect/i }));
    finishModels(reply({ models: [{ slug: 'late', display_name: 'Late' }] }));
    await within(card).findByText(/not connected/i);
    expect(within(card).queryByText('Late')).toBeNull();
  });

  it('uses Romanian text when HUD language changes', async () => {
    hub(() => reply({ connected: false }));
    render(<IntegrationsPanel />);
    const card = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    document.documentElement.lang = 'ro';
    await within(card).findByRole('button', { name: /Continuă cu ChatGPT/i });
    expect(within(card).getByText(/conectare cont/i)).toBeTruthy();
    expect(screen.getByRole('listitem', { name: /plan ChatGPT/i })).toBeTruthy();
  });

  it('reports a refused sign-in without claiming a connection or offering an external link', async () => {
    hub((url) => url.endsWith('/connect') ? reply({ detail: 'unavailable' }, 409) : reply({ connected: false }));
    render(<IntegrationsPanel />);
    const card = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    fireEvent.click(within(card).getByRole('button', { name: 'Continue with ChatGPT' }));
    expect(await within(card).findByRole('status')).toHaveProperty('textContent', expect.stringMatching(/sign-in could not start/i));
    expect(within(card).getByText('not connected')).toBeTruthy();
    expect(within(card).queryByRole('link')).toBeNull();
  });

  it('explains the local-hub requirement with the current port', async () => {
    hub(url => url.endsWith('/connect') ? reply({ detail: 'chatgpt_requires_local_hub' }, 403) : reply({ connected: false }));
    render(<IntegrationsPanel />);
    const card = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    fireEvent.click(within(card).getByRole('button', { name: 'Continue with ChatGPT' }));
    const message = await within(card).findByRole('status');
    expect(message.textContent).toContain('127.0.0.1');
    if (window.location.port) expect(message.textContent).toContain(window.location.port);
    expect(message.textContent).toMatch(/hub machine/i);
    expect(within(card).queryByRole('link')).toBeNull();
  });

  it('drops a pending sign-in when filtering unmounts the account card', async () => {
    let finishConnect!: (value: unknown) => void;
    hub(url => url.endsWith('/connect')
      ? new Promise(resolve => { finishConnect = resolve; }) : reply({ connected: false }));
    render(<IntegrationsPanel />);
    const card = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    fireEvent.click(within(card).getByRole('button', { name: 'Continue with ChatGPT' }));
    fireEvent.click(screen.getByRole('button', { name: 'search' }));
    finishConnect(reply({ url: AUTH_URL }));
    fireEvent.click(screen.getByRole('button', { name: 'models' }));
    const fresh = await screen.findByRole('listitem', { name: /ChatGPT plan/i });
    expect(within(fresh).queryByRole('link')).toBeNull();
    expect(within(fresh).getByText('not connected')).toBeTruthy();
  });
});
