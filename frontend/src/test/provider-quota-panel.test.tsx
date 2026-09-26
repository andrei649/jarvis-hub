// @ts-nocheck
/* H373 — the Provider Quota panel shows what each cloud provider said is left (bars, numbers,
   reset times) and a shared 429 hold; it is an admin console panel. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { QUOTA_PATH, ProviderQuotaPanel } from '../panels/provider-quota';
import { CONSOLE_PANELS } from '../console-routes';

let reply;
let calls;

beforeEach(() => {
  cleanup();
  calls = [];
  reply = { status: 200, body: { ok: true, providers: [
    { backend: 'anthropic', key: 'abcdef123456', blocked: false, quota: {
      requests: { limit: 100, remaining: 5, left: 0.05, resets_in: 42 },
      tokens: { limit: 1000, remaining: 800, left: 0.8, resets_in: 150 } } },
    { backend: 'gemini', key: '', blocked: true, blocked_for: 20, block_status: 429, quota: {} },
  ] } };
  global.fetch = vi.fn(async (url) => {
    calls.push(String(url));
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body, text: async () => JSON.stringify(reply.body) };
  });
});

describe('ProviderQuotaPanel — H373', () => {
  it('shows each provider\'s quota left and a 429 hold', async () => {
    render(<ProviderQuotaPanel />);
    await waitFor(() => expect(screen.getByText('5/100')).toBeTruthy());
    expect(calls[0].endsWith(QUOTA_PATH)).toBe(true);
    expect(screen.getByText('anthropic · key abcdef')).toBeTruthy();
    expect(screen.getByLabelText('5% left')).toBeTruthy();
    expect(screen.getByLabelText('80% left')).toBeTruthy();
    expect(screen.getByText('resets in 42s')).toBeTruthy();
    expect(screen.getByText('resets in 3m')).toBeTruthy();
    expect(screen.getByText('held 20s after a 429')).toBeTruthy();
    expect(screen.getByText('1 held after a 429')).toBeTruthy();
  });

  it('says where the numbers come from when none were seen yet, and is an admin panel', async () => {
    reply = { status: 200, body: { ok: true, providers: [] } };
    render(<ProviderQuotaPanel />);
    await waitFor(() => expect(screen.getByText("it is read from each cloud provider's responses")).toBeTruthy());
    expect(CONSOLE_PANELS.find((p) => p.component === 'ProviderQuotaPanel')?.group).toBe('Admin');
  });
});
