// @ts-nocheck
/* H422 — the Long-Term Memory panel shows each ring's size against its budget from
   GET /api/memory, switches the curated memory off and on, and resets it behind a typed
   RESET that posts POST /api/memory/reset as the admin. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import {
  CORE_PATH, LongTermMemoryPanel, RESET_PATH, STATUS_PATH, SWITCH_PATH, memoryState,
} from '../panels/long-term-memory';

let calls;
let status;
let resetReply;
let switchReply;

function reply(code, data) {
  return { ok: code < 400, status: code, json: async () => data, text: async () => JSON.stringify(data) };
}

const store = (over) => ({
  label: 'agent notes', file: 'core.json', bytes: 2345, entries: 11, cap: 20, copies: 0, copies_bytes: 0,
  undo_writes: 1, chars: 2144, char_budget: 2200, shown: 11, omitted: 0, blocked: 0, rendered_chars: 2144, ...over,
});

beforeEach(() => {
  cleanup();
  localStorage.setItem('hud.admin_token', 'adm');
  calls = [];
  status = {
    available: true, enabled: true, switch: true, cognition: true, safe_mode: false, injected: true, tool: true,
    stores: {
      memory: store({}),
      user: store({ label: 'user profile', file: 'user.json', bytes: 512, entries: 3, chars: 1400, char_budget: 1375,
                    omitted: 1, rendered_chars: 1300 }),
    },
    builtin_files: { memory: 2345, user: 512 }, block_max_chars: 4500,
  };
  resetReply = () => reply(200, { ok: true, targets: ['memory', 'user'], erased: { memory: 11, user: 3 },
                                  not_erased: [], undo_dropped: 1, audited: true });
  switchReply = (enabled) => reply(200, { ok: true, switch: enabled, changed: true, audited: true, applied: true,
                                          enabled, status: { ...status, enabled, switch: enabled } });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    const body = init.body ? JSON.parse(init.body) : undefined;
    const headers = init.headers || {};
    calls.push({ url: u, method: init.method || 'GET', body, admin: headers['X-Admin-Token'] });
    if (u.endsWith(RESET_PATH)) return resetReply(body);
    if (u.endsWith(SWITCH_PATH)) return switchReply(body.enabled);
    if (u.endsWith(CORE_PATH)) return reply(200, { enabled: true, memory: ['the repo uses uv'], user: [], undoable: [] });
    if (u.endsWith(STATUS_PATH)) return reply(200, status);
    return reply(404, {});
  });
});

const statusReads = () => calls.filter((c) => c.url.endsWith(STATUS_PATH) && c.method === 'GET').length;

describe('LongTermMemoryPanel — H422 sizes, switch and reset', () => {
  it('shows each ring against its budget, read from GET /api/memory', async () => {
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByLabelText('agent notes size')).toBeTruthy());
    expect(screen.getByLabelText('agent notes size').textContent)
      .toBe('2,144/2,200 chars · 11/20 entries · 2,345 bytes on disk');
    expect(screen.getByLabelText('user profile size').textContent)
      .toBe('1,400/1,375 chars · 3/20 entries · 512 bytes on disk');
    expect(screen.getByText(/1 older entry left out of the prompt: over the budget/)).toBeTruthy();
    expect(screen.getByText('on · every prompt carries it')).toBeTruthy();
    expect(calls.some((c) => c.url.endsWith(STATUS_PATH) && c.method === 'GET')).toBe(true);
  });

  it('resets only after RESET is typed, posting the target and the word as the admin', async () => {
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByLabelText('agent notes size')).toBeTruthy());
    fireEvent.click(screen.getByText('reset memory…'));
    expect(screen.getByText('type RESET to erase 14 entries (2,857 bytes) for good:')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('what to reset'), { target: { value: 'memory' } });
    expect(screen.getByText('type RESET to erase 11 entries (2,345 bytes) for good:')).toBeTruthy();
    const confirm = screen.getByText('confirm reset');
    const box = screen.getByLabelText('type RESET to confirm the memory reset');
    fireEvent.change(box, { target: { value: 'reset' } });
    expect(confirm.disabled).toBe(true);                       // the phrase, exactly
    fireEvent.click(confirm);
    expect(calls.some((c) => c.url.endsWith(RESET_PATH))).toBe(false);
    fireEvent.change(box, { target: { value: 'RESET' } });
    expect(confirm.disabled).toBe(false);
    const before = statusReads();
    fireEvent.click(confirm);
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('reset · erased agent notes: 11 · user profile: 3'));
    const post = calls.find((c) => c.url.endsWith(RESET_PATH));
    expect(post.method).toBe('POST');
    expect(post.body).toEqual({ target: 'memory', confirm: 'RESET' });
    expect(post.admin).toBe('adm');
    await waitFor(() => expect(statusReads()).toBeGreaterThan(before));
  });

  it('shows a refused reset in the hub’s own words', async () => {
    resetReply = () => reply(409, { ok: false, not_erased: ['user'], error: 'user could not be erased (another writer holds it)' });
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByLabelText('agent notes size')).toBeTruthy());
    fireEvent.click(screen.getByText('reset memory…'));
    fireEvent.change(screen.getByLabelText('type RESET to confirm the memory reset'), { target: { value: 'RESET' } });
    fireEvent.click(screen.getByText('confirm reset'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('not reset · user could not be erased (another writer holds it)'));
  });

  it('switches memory off through its route and says what the hub now does', async () => {
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByText('switch memory off')).toBeTruthy());
    fireEvent.click(screen.getByText('switch memory off'));
    fireEvent.click(screen.getByText('confirm off'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('memory off · the next turn carries none of it; nothing erased'));
    const post = calls.find((c) => c.url.endsWith(SWITCH_PATH));
    expect(post.body).toEqual({ enabled: false });
    expect(post.admin).toBe('adm');
  });

  it('does not claim memory is on when the hub still reads it off', async () => {
    status = { ...status, enabled: false, switch: false };
    switchReply = () => reply(200, { ok: true, switch: true, changed: true, applied: true, enabled: false,
                                     status: { ...status, switch: true, cognition: false } });
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByText('off · switched off by the owner; the stores stay on disk')).toBeTruthy());
    fireEvent.click(screen.getByText('switch memory on'));
    fireEvent.click(screen.getByText('confirm on'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('switch on · memory stays off until cognition memory is on'));
  });

  it('names why memory is off', () => {
    expect(memoryState({ available: true, enabled: false, switch: true, cognition: false }))
      .toContain('cognition memory is off');
    expect(memoryState({ available: true, enabled: true, safe_mode: true })).toContain('safe mode');
    expect(memoryState({ available: false })).toContain('not available');
  });
});
