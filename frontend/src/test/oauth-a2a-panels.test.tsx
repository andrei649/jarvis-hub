// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { A2AInboxPanel, OAuthPanel } from '../gap';

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  vi.restoreAllMocks();
});

describe('OAuthPanel Nous Portal device flow', () => {
  it('checks status, runs device login + poll, and logs out cleanly', async () => {
    const calls = [];
    let authed = false;
    global.fetch = vi.fn(async (url, init = {}) => {
      const method = init.method || 'GET';
      const u = String(url);
      const body = init.body ? JSON.parse(init.body) : null;
      calls.push({ method, url: u, body });
      if (u === '/api/oauth/status') return { ok: true, status: 200, json: async () => ({ google: { connected: true, scopes: ['mail'] } }) };
      if (u.startsWith('/api/oauth/nous/status')) {
        return { ok: true, status: 200, json: async () => ({ authenticated: authed, usable: authed, profile: 'default' }) };
      }
      if (u === '/api/oauth/nous/login') {
        return { ok: true, status: 200, json: async () => ({ login_id: 'lg-1', user_code: 'ABCD-1234', verification_uri: 'https://portal.nousresearch.com/device' }) };
      }
      if (u === '/api/oauth/nous/poll') {
        authed = true;
        return { ok: true, status: 200, json: async () => ({ state: 'complete' }) };
      }
      if (u === '/api/oauth/nous/logout') {
        authed = false;
        return { ok: true, status: 200, json: async () => ({ cleared: true }) };
      }
      return { ok: false, status: 404, json: async () => ({ error: 'not_found' }) };
    });

    render(<OAuthPanel />);
    await screen.findByText('google');

    fireEvent.click(screen.getByText('check Nous'));
    await screen.findByText('signed out');

    fireEvent.click(screen.getByText('Nous login'));
    await screen.findByText(/code: ABCD-1234/);
    fireEvent.click(screen.getByText('poll Nous'));
    await screen.findByText('usable');

    fireEvent.click(screen.getByText('Nous logout'));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/oauth/nous/logout')).toBe(true));
  });
});

describe('A2AInboxPanel outbound peer configuration (H562)', () => {
  it('loads peers on disclosure, configures outbound URL/token without echoing secret, and clears outbound', async () => {
    const calls = [];
    let outboundUrl = null;
    global.fetch = vi.fn(async (url, init = {}) => {
      const method = init.method || 'GET';
      const u = String(url);
      const body = init.body ? JSON.parse(init.body) : null;
      calls.push({ method, url: u, body });
      if (u === '/api/a2a/inbox') return { ok: true, status: 200, json: async () => ({ inbox: [] }) };
      if (u === '/api/a2a/peers') {
        return { ok: true, status: 200, json: async () => ({ peers: [{ peer_id: 'alpha', outbound: outboundUrl ? { url: outboundUrl, allow_lan: false } : null }] }) };
      }
      if (method === 'PUT' && u === '/api/a2a/peers/alpha/outbound') {
        outboundUrl = body.url;
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
      }
      if (method === 'DELETE' && u === '/api/a2a/peers/alpha/outbound') {
        outboundUrl = null;
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
      }
      return { ok: false, status: 404, json: async () => ({ error: 'not_found' }) };
    });

    render(<A2AInboxPanel />);
    await screen.findByText('outbound peers');
    expect(calls.some((c) => c.url === '/api/a2a/peers')).toBe(false);

    fireEvent.click(screen.getByText('outbound peers'));
    await screen.findByText('alpha');

    fireEvent.change(screen.getByLabelText('peer id'), { target: { value: 'alpha' } });
    fireEvent.change(screen.getByLabelText('peer outbound url'), { target: { value: 'https://alpha.example.test/a2a' } });
    fireEvent.change(screen.getByLabelText('peer bearer token'), { target: { value: 'super-secret-token' } });
    fireEvent.click(screen.getByText('save outbound'));

    await screen.findByText(/outbound configured · alpha/);
    const put = calls.find((c) => c.method === 'PUT' && c.url === '/api/a2a/peers/alpha/outbound');
    expect(put.body.url).toBe('https://alpha.example.test/a2a');
    expect(put.body.token).toBe('super-secret-token');
    expect((screen.getByLabelText('peer bearer token') as HTMLInputElement).value).toBe('');

    fireEvent.click(await screen.findByText('clear outbound'));
    await screen.findByText(/outbound cleared · alpha/);
    expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/a2a/peers/alpha/outbound')).toBe(true);
  });
});
