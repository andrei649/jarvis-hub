import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChannelsConfigPanel } from './channels-config';

const CONFIG = { channels: [{ id: 'telegram', label: 'Telegram', note: '', running: true,
  restart_required: false, changed: [], fields: [] }] };
const STATES = ['sent', 'failed', 'partial', 'unknown', 'pending', 'attempting', 'skipped'] as const;
const receipt = (state: typeof STATES[number], index: number) => ({
  id: `row-${index}`, channel: 'telegram', target: String(100 + index), state,
  attempt: 1, error: state === 'failed' ? 'not_connected' : null, chars: 12,
  created: 1_700_000_000 + index, updated: 1_700_000_000 + index, keyed: true,
  text: 'SECRET_BODY_MUST_NOT_RENDER', key: 'SECRET_KEY_MUST_NOT_RENDER',
});
const VIEW = {
  stats: { by_state: Object.fromEntries(STATES.map((state) => [state, 1])),
    needs_attention: 3, dead_targets: 2 },
  deliveries: STATES.map(receipt), dead_targets: [], dead_targets_truncated: false, health: {},
  retention: { window_seconds: 86_400, protected_limit: 700, protected_count: 23,
    retention_seconds: 604_800, ordinary_row_limit: 400 },
};

function hub(deliveries: () => { status: number; body: unknown }) {
  const calls: { url: string; init: RequestInit }[] = [];
  global.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    calls.push({ url: String(url), init: init ?? {} });
    const answer = String(url).includes('/api/channels/deliveries')
      ? deliveries() : { status: 200, body: CONFIG };
    return new Response(JSON.stringify(answer.body), { status: answer.status,
      headers: { 'Content-Type': 'application/json' } });
  });
  return calls;
}

async function openReceipts() {
  await screen.findByText('Telegram');
  fireEvent.click(screen.getByRole('button', { name: /delivery receipts/i }));
}

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('owner delivery receipts in Channels', () => {
  it('fetches only after disclosure, with the admin credential and a 50-row limit', async () => {
    localStorage.setItem('hud.admin_token', 'owner-test-token');
    const calls = hub(() => ({ status: 200, body: VIEW }));
    render(<ChannelsConfigPanel />);
    await screen.findByText('Telegram');
    expect(calls.every((call) => !call.url.includes('/api/channels/deliveries'))).toBe(true);

    await openReceipts();
    await screen.findByText(/platform acknowledged all parts/i);
    const reads = calls.filter((call) => call.url.includes('/api/channels/deliveries'));
    expect(reads).toHaveLength(1);
    expect(reads[0].url).toContain('/api/channels/deliveries?limit=50');
    expect((reads[0].init.headers as Record<string, string>)['X-Admin-Token']).toBe('owner-test-token');
    expect(reads[0].init.method).toBe('GET');
  });

  it('shows every state truthfully, live retention metadata, and no body or action controls', async () => {
    hub(() => ({ status: 200, body: VIEW }));
    const { container } = render(<ChannelsConfigPanel />);
    await openReceipts();
    await screen.findByText(/may have arrived/i);

    for (const state of STATES) expect(screen.getAllByText(state).length).toBeGreaterThan(0);
    expect(screen.getByText(/platform acknowledged all parts/i)).toBeTruthy();
    expect(screen.getByText(/some parts may have been accepted/i)).toBeTruthy();
    expect(screen.getByText(/automatic resend is off/i)).toBeTruthy();
    expect(screen.getByText(/23 of 700 occupied/i)).toBeTruthy();
    expect(screen.getByText(/when full, new sends requiring this protection are withheld/i)).toBeTruthy();
    expect(screen.getByText(/ordinary row budget is 400/i)).toBeTruthy();
    expect(screen.getByText(/keyed duplicate protection lasts 1 day/i)).toBeTruthy();
    expect(container.textContent).not.toContain('500 total');
    expect(container.textContent).not.toContain('SECRET_BODY_MUST_NOT_RENDER');
    expect(container.textContent).not.toContain('SECRET_KEY_MUST_NOT_RENDER');
    expect(screen.queryByRole('button', { name: /retry|resend|send|clear dead/i })).toBeNull();
  });

  it('hides previously loaded receipts when an owner refresh is refused', async () => {
    let allowed = true;
    hub(() => allowed ? { status: 200, body: VIEW } : { status: 403, body: {} });
    render(<ChannelsConfigPanel />);
    await openReceipts();
    await screen.findByText('row-0');

    allowed = false;
    fireEvent.click(screen.getByRole('button', { name: /refresh receipts/i }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/owner access required/i));
    expect(screen.queryByText('row-0')).toBeNull();
    expect(screen.queryByText(/No receipt rows/i)).toBeNull();
  });

  it('distinguishes an unavailable ledger and malformed data from a valid empty read', async () => {
    let response: { status: number; body: unknown } = { status: 503, body: { error: 'unavailable' } };
    hub(() => response);
    render(<ChannelsConfigPanel />);
    await openReceipts();
    await screen.findByText(/ledger unavailable/i);
    expect(screen.queryByText(/No receipt rows/i)).toBeNull();

    response = { status: 200, body: { deliveries: [] } };
    fireEvent.click(screen.getByRole('button', { name: /refresh receipts/i }));
    await screen.findByText(/could not be checked/i);
    expect(screen.queryByText(/No receipt rows/i)).toBeNull();

    response = { status: 200, body: { ...VIEW, deliveries: [],
      stats: { ...VIEW.stats, by_state: Object.fromEntries(STATES.map((state) => [state, 0])) } } };
    fireEvent.click(screen.getByRole('button', { name: /refresh receipts/i }));
    await screen.findByText(/No receipt rows returned/i);

    response = { status: 200, body: { ...VIEW, deliveries: [{ ...receipt('sent', 0), updated: 9e15 }] } };
    fireEvent.click(screen.getByRole('button', { name: /refresh receipts/i }));
    await screen.findByText(/could not be checked/i);
  });

  it('allows lifting the gone flag on a listed dead target (H081)', async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    let deadRows = [{ channel: 'telegram', target: 'chat-77', reason: 'bot_blocked', marked: 1_700_000_100 }];
    global.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const u = String(url);
      calls.push({ url: u, init: init ?? {} });
      if (u.includes('/api/channels/dead-targets/clear')) {
        deadRows = [];
        return new Response(JSON.stringify({ cleared: true }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (u.includes('/api/channels/deliveries')) {
        return new Response(JSON.stringify({ ...VIEW, dead_targets: deadRows }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify(CONFIG), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });

    render(<ChannelsConfigPanel />);
    await openReceipts();
    await screen.findByText(/telegram → chat-77/);
    fireEvent.click(screen.getByRole('button', { name: 'lift gone flag' }));
    await screen.findByText(/lifted gone flag for telegram → chat-77/);
    const clearCall = calls.find((c) => c.url.includes('/api/channels/dead-targets/clear'));
    expect(clearCall).toBeTruthy();
    expect(JSON.parse(String(clearCall!.init.body))).toEqual({ channel: 'telegram', target: 'chat-77' });
  });
});
