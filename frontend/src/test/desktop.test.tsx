import React from 'react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { DesktopControls, isFloatingDesktop } from '../desktop';

const invoke = vi.fn();
beforeEach(() => { window.history.replaceState({}, '', '/v2/'); (window as any).__TAURI__ = { core: { invoke } }; invoke.mockReset(); invoke.mockResolvedValue({ positioning: true, alwaysOnTop: true, compositor: 'Cocoa' }); });
afterEach(() => { cleanup(); delete (window as any).__TAURI__; });
it('browser does not expose native window controls', () => { delete (window as any).__TAURI__; render(<DesktopControls />); expect(screen.queryByRole('button')).toBeNull(); });
it('floating route requires the native bridge', () => { window.history.replaceState({}, '', '/v2/?desktop=floating'); expect(isFloatingDesktop()).toBe(true); delete (window as any).__TAURI__; expect(isFloatingDesktop()).toBe(false); });
it('main opener sends only the fixed show action', async () => { render(<DesktopControls />); fireEvent.click(screen.getByRole('button', { name: 'Float chat' })); await waitFor(() => expect(invoke).toHaveBeenCalledWith('desktop_action', { action: 'show' })); });
it('floating controls hide, reset, and hand off using fixed actions', async () => { render(<DesktopControls floating />); for (const [name, action] of [['Hide chat', 'hide'], ['Reset layout', 'reset'], ['Open in app', 'handoff']]) { fireEvent.click(screen.getByRole('button', { name })); await waitFor(() => expect(invoke).toHaveBeenCalledWith('desktop_action', { action })); } });
it('refused native action has visible error feedback', async () => { invoke.mockRejectedValue(new Error('window unavailable')); render(<DesktopControls />); fireEvent.click(screen.getByRole('button', { name: 'Float chat' })); expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'window unavailable'); });
it('unsupported placement is explained from native capability response', async () => { invoke.mockResolvedValue({ positioning: false, alwaysOnTop: false, compositor: 'Wayland' }); render(<DesktopControls floating />); expect(await screen.findByText(/Wayland.*placement.*topmost/i)).toBeTruthy(); });

it('floating app renders existing chat without normal shell or world control', async () => {
  const { default: App } = await import('../app');
  (globalThis as any).fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ turns: [{ role: 'user', content: 'Shared server conversation' }] }) });
  render(<App floating />);
  expect(await screen.findByText('Shared server conversation')).toBeTruthy();
  expect(screen.queryByTitle('console (`)')).toBeNull();
  expect(screen.getByRole('button', { name: 'Open in app' })).toBeTruthy();
});

it('refreshes the same authenticated server conversation on focus', async () => {
  const { useDesktopConversation } = await import('../desktop');
  const setMessages = vi.fn();
  localStorage.setItem('hud.user_token', 'test-desktop-token');
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ turns: [{ role: 'user', content: 'Main window turn' }] }) });
  vi.stubGlobal('fetch', fetch);
  function Harness() { useDesktopConversation(setMessages, false, false); return null; }
  render(<Harness />);
  fireEvent(window, new Event('focus'));
  await waitFor(() => expect(setMessages).toHaveBeenCalledWith([expect.objectContaining({ text: 'Main window turn' })]));
  expect(fetch).toHaveBeenCalledWith('/memory', expect.objectContaining({ headers: expect.objectContaining({ 'X-User-Token': 'test-desktop-token' }) }));
  localStorage.removeItem('hud.user_token');
});
it('a stale focus response cannot overwrite an in-flight turn', async () => {
  const { useDesktopConversation } = await import('../desktop');
  const setMessages = vi.fn();
  let resolve: (r: unknown) => void;
  vi.stubGlobal('fetch', vi.fn(() => new Promise(r => { resolve = r; })));
  function Harness({ busy }: { busy: boolean }) { useDesktopConversation(setMessages, busy, false); return null; }
  const view = render(<Harness busy={false} />);
  fireEvent(window, new Event('focus'));
  view.rerender(<Harness busy />);
  await React.act(async () => { resolve!({ ok: true, json: async () => ({ turns: [{ role: 'user', content: 'old' }] }) }); });
  expect(setMessages).not.toHaveBeenCalled();
});
it('normal app retains its console and native opener', async () => {
  const { default: App } = await import('../app');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
  render(<App />);
  expect(screen.getByTitle('console (`)')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Float chat' })).toBeTruthy();
});
