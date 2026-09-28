// @ts-nocheck
/* H222 — the HUD tells the desktop shell's tray only about changes; a refused call is
   sent again with the next report. Outside the desktop app nothing is sent. */
import { describe, it, expect, afterEach, vi } from 'vitest';

afterEach(() => { delete window.__TAURI__; vi.resetModules(); });

async function load() { return import('../desktop'); }
const flush = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };

describe('desktop listening push — H222', () => {
  it('sends a change once, with the state, to desktop_listening', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    window.__TAURI__ = { core: { invoke } };
    const d = await load();
    expect(d.hasDesktopBridge()).toBe(true);
    d.setDesktopListening('armed');
    d.setDesktopListening('armed');
    d.setDesktopListening('listening');
    expect(invoke.mock.calls).toEqual([['desktop_listening', { state: 'armed' }], ['desktop_listening', { state: 'listening' }]]);
  });

  it('a refused call is sent again next time', async () => {
    const invoke = vi.fn().mockRejectedValueOnce(new Error('denied')).mockResolvedValue(undefined);
    window.__TAURI__ = { core: { invoke } };
    const d = await load();
    d.setDesktopListening('armed');
    await flush();
    d.setDesktopListening('armed');
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it('outside the desktop app nothing is sent', async () => {
    const d = await load();
    expect(d.hasDesktopBridge()).toBe(false);
    expect(() => d.setDesktopListening('listening')).not.toThrow();
  });
});
