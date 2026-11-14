import React, { useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { useDesktopConversation } from '../desktop';
import { apiGet } from '../api/client';
import { SessionRecovery } from '../session-recovery';

const missing = (id: string) => new Response(JSON.stringify({ error: `session '${id}' not found` }), { status: 404 });
const response = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

beforeEach(() => {
  sessionStorage.clear(); localStorage.clear();
  (window as any).__TAURI__ = { core: { invoke: vi.fn() } };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as any).__TAURI__; });

it('recovers exact terminal 404 once and persists the current authorized session', async () => {
  sessionStorage.setItem('nerva.chat.session_id', 'old');
  localStorage.setItem('hud.user_token', 'current-principal');
  let selected = 'old';
  let selectionGeneration = 0;
  const fetch = vi.fn(async (path: string, init?: { body?: string; headers?: Record<string, string> }) => {
    if (path === '/sessions/resume') {
      const id = JSON.parse(init?.body || '{}').session_id;
      return id === 'old' ? missing('old') : response(200, { session: 'current', turns: [] });
    }
    return response(200, { session: 'current', turns: [{ role: 'assistant', content: 'current transcript' }] });
  });
  vi.stubGlobal('fetch', fetch);
  const setMessages = vi.fn();
  const recovery = new SessionRecovery(() => apiGet('/memory'), (snapshot) => {
    selectionGeneration++;
    selected = snapshot.session;
    sessionStorage.setItem('nerva.chat.session_id', snapshot.session);
    setMessages(snapshot.turns.map((turn) => ({ text: turn.content })));
  });
  const selectedId = () => selected;
  const selectedGeneration = () => selectionGeneration;
  function Window() { useDesktopConversation(setMessages, false, false, selectedId, recovery, selectedGeneration); return <output>{selected}</output>; }

  render(<Window />);
  act(() => { window.dispatchEvent(new Event('focus')); });
  await waitFor(() => expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('current'));
  expect(fetch.mock.calls.map(([path]) => path)).toEqual(['/sessions/resume', '/memory']);
  expect(fetch.mock.calls[1][1].headers['X-User-Token']).toBe('current-principal');
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('current');
  expect(setMessages).toHaveBeenCalledWith([{ text: 'current transcript' }]);

  await act(async () => { window.dispatchEvent(new Event('focus')); });
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  expect(fetch.mock.calls[2][0]).toBe('/sessions/resume');
  expect(JSON.parse(fetch.mock.calls[2][1].body).session_id).toBe('current');
});

it.each([
  ['protected 403', 403, { error: "session 'old' not found" }],
  ['transient 503', 503, { error: "session 'old' not found" }],
  ['bare proxy 404', 404, { detail: "session 'old' not found" }],
  ['mismatched 404', 404, { error: "session 'other' not found" }],
])('%s preserves the stored session and displayed messages', async (_name, status, body) => {
  sessionStorage.setItem('nerva.chat.session_id', 'old');
  const fetch = vi.fn(async (_path: string) => response(status, body));
  vi.stubGlobal('fetch', fetch);
  const setMessages = vi.fn();
  const recovery = new SessionRecovery(() => apiGet('/memory'), vi.fn());
  function Window() { useDesktopConversation(setMessages, false, false, () => 'old', recovery); return null; }
  render(<Window />);
  act(() => { window.dispatchEvent(new Event('focus')); });
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
  expect(fetch.mock.calls[0][0]).toBe('/sessions/resume');
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('old');
  expect(setMessages).not.toHaveBeenCalled();
});

it('network failure keeps the old selection and does not attempt fallback', async () => {
  sessionStorage.setItem('nerva.chat.session_id', 'old');
  const fetch = vi.fn(async () => { throw new TypeError('offline'); });
  vi.stubGlobal('fetch', fetch);
  const setMessages = vi.fn();
  const recovery = new SessionRecovery(() => apiGet('/memory'), vi.fn());
  function Window() { useDesktopConversation(setMessages, false, false, () => 'old', recovery); return null; }
  render(<Window />);
  act(() => { window.dispatchEvent(new Event('focus')); });
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('old');
  expect(setMessages).not.toHaveBeenCalled();
});

it.each(['selection-change', 'busy'])('%s while fallback is pending cannot replace stored id or messages', async (change) => {
  sessionStorage.setItem('nerva.chat.session_id', 'old');
  let selected = 'old';
  let selectedGeneration = 0;
  let release!: (value: Response) => void;
  const fetch = vi.fn(async (path: string) => path === '/sessions/resume'
    ? missing('old')
    : new Promise<Response>(resolve => { release = resolve; }));
  vi.stubGlobal('fetch', fetch);
  const setMessages = vi.fn();
  const recovery = new SessionRecovery(() => apiGet('/memory'), (snapshot) => {
    selected = snapshot.session;
    sessionStorage.setItem('nerva.chat.session_id', snapshot.session);
    setMessages(snapshot.turns.map((turn) => ({ text: turn.content })));
  });
  const selectedId = () => selected;
  const selectedVersion = () => selectedGeneration;
  function Window({ busy }: { busy: boolean }) {
    useDesktopConversation(setMessages, busy, false, selectedId, recovery, selectedVersion);
    return null;
  }
  const view = render(<Window busy={false} />);
  act(() => { window.dispatchEvent(new Event('focus')); });
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  if (change === 'selection-change') {
    selected = 'other'; selectedGeneration++;
    sessionStorage.setItem('nerva.chat.session_id', 'other');
    setMessages.mockClear();
    view.rerender(<Window busy={false} />);
  } else {
    setMessages.mockClear();
    view.rerender(<Window busy />);
  }
  await act(async () => release(response(200, { session: 'current', turns: [{ role: 'assistant', content: 'late' }] })));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe(change === 'selection-change' ? 'other' : 'old');
  expect(setMessages).not.toHaveBeenCalled();
});
