// @ts-nocheck
/* H380 — the owner asks each cloud provider whether its key works; nothing is probed
   until asked; a failing key, a throttled re-check and a refused request are shown. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { PROBE_PATH, ProviderCheckPanel } from '../panels/provider-check';
import { CONSOLE_PANELS } from '../console-routes';

let calls;
let replies;

function reply(status, data) {
  return { ok: status < 400, status, json: async () => data, text: async () => JSON.stringify(data) };
}

const ROWS = [
  { provider: 'anthropic', display_name: 'Anthropic Claude', verdict: 'ok', working: true, models: 7, status_code: 200 },
  { provider: 'gemini', display_name: 'Google Gemini', verdict: 'auth_failed', working: false, models: null, status_code: 401 },
  { provider: 'xai', display_name: 'xAI Grok', verdict: 'not_configured', working: false, models: null },
  { provider: 'openrouter', display_name: 'OpenRouter', verdict: 'error', working: false, status_code: 500 },
];

beforeEach(() => {
  cleanup();
  calls = [];
  replies = [() => reply(200, { providers: ROWS })];
  global.fetch = vi.fn(async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined });
    const next = replies.length > 1 ? replies.shift() : replies[0];
    return next();
  });
});

describe('ProviderCheckPanel — H380', () => {
  it('probes nothing until asked, then shows each verdict', async () => {
    render(<ProviderCheckPanel />);
    expect(calls).toHaveLength(0);
    fireEvent.click(screen.getByText('check all providers'));
    await waitFor(() => expect(screen.getByText('key works')).toBeTruthy());
    expect(calls[0].url.endsWith(PROBE_PATH)).toBe(true);
    expect(calls[0].body).toEqual({ force: false });
    expect(screen.getByText('7 model(s)')).toBeTruthy();
    expect(screen.getByText('key rejected (401)')).toBeTruthy();
    expect(screen.getByText('no key set')).toBeTruthy();
    expect(screen.getByText('HTTP 500')).toBeTruthy();
    expect(screen.queryByLabelText('re-check xai')).toBeNull();          // nothing to re-check
    expect(screen.getByText('2 failing')).toBeTruthy();
  });

  it('re-checks one provider with force and says when it was throttled', async () => {
    render(<ProviderCheckPanel />);
    fireEvent.click(screen.getByText('check all providers'));
    await waitFor(() => expect(screen.getByLabelText('re-check gemini')).toBeTruthy());
    replies = [() => reply(200, { providers: [{ ...ROWS[1], verdict: 'ok', working: true, models: 3, throttled: true, cached: true }] })];
    fireEvent.click(screen.getByLabelText('re-check gemini'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('checked moments ago; showing that result'));
    expect(calls[1].body).toEqual({ force: true, provider: 'gemini' });
    expect(screen.getByText('3 model(s)')).toBeTruthy();
    expect(screen.getAllByText('key works')).toHaveLength(2);
    expect(screen.getByText('1 failing')).toBeTruthy();
  });

  it('shows a refused request and is an admin console panel', async () => {
    replies = [() => reply(403, { detail: 'admin token required' })];
    render(<ProviderCheckPanel />);
    fireEvent.click(screen.getByText('check all providers'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('not checked'));
    expect(CONSOLE_PANELS.find((p) => p.component === 'ProviderCheckPanel')?.group).toBe('Admin');
  });
});
