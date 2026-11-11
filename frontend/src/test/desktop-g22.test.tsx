import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/react';
import { DECISION_POLL_MS, useDesktopDecisionNotifications, useQuickEntryFocus } from '../desktop';

// G22 (H179, H181): the HUD side of Quick Entry and decision notifications.

const invoke = vi.fn();
beforeEach(() => {
  window.history.replaceState({}, '', '/v2/');
  (window as any).__TAURI__ = { core: { invoke } };
  invoke.mockReset();
  invoke.mockResolvedValue(true);
  localStorage.setItem('hud.admin_token', 'test-admin-token');
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete (window as any).__TAURI__;
  localStorage.removeItem('hud.admin_token');
});

const reply = (pending: any[]) => ({ ok: true, status: 200, json: async () => ({ pending }) });

it('quick entry focuses the composer and sends nothing', () => {
  function Harness() { useQuickEntryFocus(); return <input data-composer="1" aria-label="composer" />; }
  const view = render(<Harness />);
  window.dispatchEvent(new Event('nerva-desktop-quick-entry'));
  expect(document.activeElement).toBe(view.getByLabelText('composer'));
  expect(invoke).not.toHaveBeenCalled();
});

it('only a new pending approval asks the shell for a notification, once', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fetch = vi.fn()
    .mockResolvedValueOnce(reply([{ id: 'old', title: 'already waiting' }]))
    .mockResolvedValueOnce(reply([{ id: 'old' }, { id: 'new-1', title: 'Send the invoice' }]))
    .mockResolvedValue(reply([{ id: 'old' }, { id: 'new-1', title: 'Send the invoice' }]));
  vi.stubGlobal('fetch', fetch);
  function Harness() { useDesktopDecisionNotifications(true); return null; }
  render(<Harness />);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  expect(invoke).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(DECISION_POLL_MS);
  await waitFor(() => expect(invoke).toHaveBeenCalledTimes(1));
  expect(invoke).toHaveBeenCalledWith('desktop_notify', { kind: 'approval', id: 'new-1', title: 'Nerva needs a decision', body: 'Send the invoice' });
  await vi.advanceTimersByTimeAsync(DECISION_POLL_MS);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  expect(invoke).toHaveBeenCalledTimes(1);
  // The HUD reads the approvals with its own admin header; the shell gets no credential.
  expect(fetch).toHaveBeenCalledWith('/autonomy/approvals', expect.objectContaining({ headers: expect.objectContaining({ 'X-Admin-Token': 'test-admin-token' }) }));
  for (const call of invoke.mock.calls) expect(JSON.stringify(call)).not.toContain('test-admin-token');
});

it('without an admin session the watch stops and nothing is notified', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fetch = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) });
  vi.stubGlobal('fetch', fetch);
  function Harness() { useDesktopDecisionNotifications(true); return null; }
  render(<Harness />);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  const calls = fetch.mock.calls.length;
  await vi.advanceTimersByTimeAsync(DECISION_POLL_MS * 3);
  expect(fetch.mock.calls.length).toBe(calls);
  expect(invoke).not.toHaveBeenCalled();
});

it('the floating window and a plain browser never watch', async () => {
  const fetch = vi.fn().mockResolvedValue(reply([]));
  vi.stubGlobal('fetch', fetch);
  function Harness() { useDesktopDecisionNotifications(true); return null; }
  window.history.replaceState({}, '', '/v2/?desktop=floating');
  render(<Harness />);
  cleanup();
  window.history.replaceState({}, '', '/v2/');
  delete (window as any).__TAURI__;
  render(<Harness />);
  await new Promise((r) => setTimeout(r, 20));
  expect(fetch).not.toHaveBeenCalled();
});
