// @ts-nocheck
/* H314 — the owner sees what the model saved and undoes a write; a refused undo is shown. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { CORE_PATH, LongTermMemoryPanel, UNDO_PATH } from '../panels/long-term-memory';
import { CONSOLE_PANELS } from '../console-routes';

let calls;
let body;
let undoReply;

function reply(status, data) {
  return { ok: status < 400, status, json: async () => data, text: async () => JSON.stringify(data) };
}

beforeEach(() => {
  cleanup();
  calls = [];
  body = { enabled: true, memory: ['the repo uses uv'], user: ['prefers short answers'],
           undoable: [{ ref: 'abc123', ts: 1, targets: ['memory', 'user'] }] };
  undoReply = () => reply(200, { ok: true, ref: 'abc123', memory: [], user: [] });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    calls.push({ url: u, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined });
    if (u.endsWith(UNDO_PATH)) return undoReply();
    if (u.endsWith(CORE_PATH)) return reply(200, body);
    return reply(404, {});
  });
});

describe('LongTermMemoryPanel — H314', () => {
  it('lists both rings and undoes a write', async () => {
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByText('the repo uses uv')).toBeTruthy());
    expect(screen.getByText('prefers short answers')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('undo abc123'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('undone · abc123'));
    const post = calls.find((c) => c.url.endsWith(UNDO_PATH));
    expect(post.method).toBe('POST');
    expect(post.body).toEqual({ ref: 'abc123' });
    expect(calls.filter((c) => c.url.endsWith(CORE_PATH)).length).toBeGreaterThanOrEqual(2);
  });

  it('shows a refused undo and re-reads the list', async () => {
    undoReply = () => reply(409, { ok: false, reason: 'memory_changed_meanwhile', detail: 'memory changed after that write' });
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByLabelText('undo abc123')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('undo abc123'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('not undone'));
    expect(calls.filter((c) => c.url.endsWith(CORE_PATH)).length).toBeGreaterThanOrEqual(2);
  });

  it('says when memory is off, and is a console panel', async () => {
    body = { enabled: false, memory: [], user: [], undoable: [] };
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByText(/Memory is switched off/)).toBeTruthy());
    expect(screen.queryByText('RECENT WRITES')).toBeNull();
    expect(CONSOLE_PANELS.find((p) => p.component === 'LongTermMemoryPanel')?.group).toBe('Memory');
  });
});
