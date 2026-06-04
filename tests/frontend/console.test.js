// console.js — shared fetch helpers (api / adminToken / adminFetch) and the ⚙
// SettingsMenu. These ship as globals (window.*) and had zero automated coverage;
// here we exercise the real shipped artifact in JSDOM via the harness.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

function json(body, { ok = true, status = 200 } = {}) {
  return Promise.resolve({ ok, status, json: async () => body });
}

let env;
beforeEach(() => {
  env = loadHud({ files: ['i18n', 'data', 'components', 'console'], lang: 'ro' });
});
afterEach(() => env.cleanup());

describe('shared fetch helpers', () => {
  it('api() resolves JSON on ok and throws on non-2xx', async () => {
    env.window.fetch = vi.fn(() => json({ hello: 'world' }));
    await expect(env.window.api('/x')).resolves.toEqual({ hello: 'world' });

    env.window.fetch = vi.fn(() => json({}, { ok: false, status: 500 }));
    await expect(env.window.api('/x')).rejects.toThrow('HTTP 500');
  });

  it('adminToken() reads the token from localStorage', () => {
    expect(env.window.adminToken()).toBe('');
    env.window.localStorage.setItem('hud.admin_token', 'sekret');
    expect(env.window.adminToken()).toBe('sekret');
  });

  it('adminFetch() injects the X-Admin-Token header', async () => {
    env.window.localStorage.setItem('hud.admin_token', 'sekret');
    const fetch = vi.fn(() => json({ done: true }));
    env.window.fetch = fetch;
    await env.window.adminFetch('/api/admin/thing');
    const [, opts] = fetch.mock.calls[0];
    expect(opts.headers['X-Admin-Token']).toBe('sekret');
  });

  it('adminFetch() raises a friendly error on 401', async () => {
    env.window.fetch = vi.fn(() => json({}, { ok: false, status: 401 }));
    await expect(env.window.adminFetch('/api/admin/thing')).rejects.toThrow(/admin token/i);
  });
});

describe('SettingsMenu', () => {
  function rowByLabel(container, label) {
    return [...container.querySelectorAll('.set-row')].find(
      (r) => r.querySelector('.set-label') && r.querySelector('.set-label').textContent === label,
    );
  }
  function openMenu(props = {}) {
    const { container } = env.render(env.React.createElement(env.window.SettingsMenu, props));
    env.click(container.querySelector('.set-gear'));
    return container;
  }

  it('renders just the gear button when closed', () => {
    const { container } = env.render(env.React.createElement(env.window.SettingsMenu, {}));
    expect(container.querySelector('.set-gear')).not.toBeNull();
    expect(container.querySelector('.set-menu')).toBeNull();
  });

  it('opens a menu with Appearance / Panels / Admin groups + version footer', () => {
    const container = openMenu({ version: '9.9.9' });
    expect(container.querySelector('.set-menu')).not.toBeNull();
    const titles = [...container.querySelectorAll('.set-group-title')].map((e) => e.textContent);
    expect(titles).toEqual(expect.arrayContaining(['Appearance', 'Panels', 'Admin']));
    expect(container.querySelector('.set-foot').textContent).toContain('v9.9.9');
  });

  it('theme change writes localStorage, sets the attribute, and dispatches an event', () => {
    const container = openMenu();
    const onTheme = vi.fn();
    env.window.addEventListener('jarvis:theme_changed', onTheme);
    env.selectOption(rowByLabel(container, 'Theme').querySelector('select'), 'cyberpunk');
    expect(env.window.localStorage.getItem('hud.theme')).toBe('cyberpunk');
    expect(env.document.documentElement.getAttribute('data-theme')).toBe('cyberpunk');
    expect(onTheme).toHaveBeenCalled();
    expect(onTheme.mock.calls[0][0].detail).toBe('cyberpunk');
  });

  it('scanline toggle flips the localStorage pref (on → off)', () => {
    const container = openMenu();
    env.click(rowByLabel(container, 'Scanline').querySelector('.set-toggle'));
    expect(env.window.localStorage.getItem('hud.scanline')).toBe('off');
  });

  it('language toggle calls window.setLocale with the other locale', () => {
    env.window.setLocale = vi.fn();
    const container = openMenu();
    env.click(rowByLabel(container, 'Language').querySelector('.set-toggle'));
    expect(env.window.setLocale).toHaveBeenCalledWith('en');
  });

  it('admin token input persists to hud.admin_token', () => {
    const container = openMenu();
    env.type(rowByLabel(container, 'Admin token').querySelector('input'), 'tok-123');
    expect(env.window.localStorage.getItem('hud.admin_token')).toBe('tok-123');
  });

  it('panel toggles invoke their callbacks', () => {
    const toggles = {
      network: false, onNetwork: vi.fn(),
      cognition: false, onCognition: vi.fn(),
      systems: true, onSystems: vi.fn(),
      workflows: false, onWorkflows: vi.fn(),
      observability: true, onObservability: vi.fn(),
    };
    const container = openMenu({ toggles });
    env.click(rowByLabel(container, 'Cognition').querySelector('.set-toggle'));
    expect(toggles.onCognition).toHaveBeenCalled();
    env.click(rowByLabel(container, 'Network graph').querySelector('.set-toggle'));
    expect(toggles.onNetwork).toHaveBeenCalled();
  });

  it('closes via the × button', () => {
    const container = openMenu();
    expect(container.querySelector('.set-menu')).not.toBeNull();
    env.click(container.querySelector('.set-x'));
    expect(container.querySelector('.set-menu')).toBeNull();
  });
});
