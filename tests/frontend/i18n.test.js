// i18n layer (i18n.js): translation lookup, locale detection, and the
// setLocale() event contract the React App relies on for re-render.
import { afterEach, describe, expect, it } from 'vitest';
import { loadHud } from './harness.js';

const envs = [];
function boot(opts) {
  const env = loadHud({ files: ['i18n'], ...opts });
  envs.push(env);
  return env;
}
afterEach(() => {
  while (envs.length) envs.pop().cleanup();
});

describe('_t', () => {
  it('translates a known key in the active locale', () => {
    const env = boot({ lang: 'ro' });
    expect(env.window._t('app.tab_chat')).toBe('Chat');
    expect(env.window._t('app.loading')).toBe('SE INIȚIALIZEAZĂ JARVIS HUB…');
  });

  it('returns the key itself for an unknown key (graceful fallback)', () => {
    const env = boot({ lang: 'ro' });
    expect(env.window._t('does.not.exist')).toBe('does.not.exist');
  });

  it('serves English strings when locale is en', () => {
    const env = boot({ lang: 'en' });
    env.window.setLocale('en');
    // ro and en differ for the loading string; en must not be the ro text.
    expect(env.window._t('app.loading')).not.toBe('SE INIȚIALIZEAZĂ JARVIS HUB…');
  });
});

describe('detectLocale (bootstrap)', () => {
  it('honours a persisted hud.lang', () => {
    const env = boot({ lang: 'en' });
    expect(env.window.currentLocale).toBe('en');
  });

  it('reflects the locale on the <html lang> attribute', () => {
    const env = boot({ lang: 'ro' });
    expect(env.document.documentElement.getAttribute('lang')).toBe('ro');
  });
});

describe('setLocale', () => {
  it('updates currentLocale, persists, and sets <html lang>', () => {
    const env = boot({ lang: 'ro' });
    env.window.setLocale('en');
    expect(env.window.currentLocale).toBe('en');
    expect(env.window.localStorage.getItem('hud.lang')).toBe('en');
    expect(env.document.documentElement.getAttribute('lang')).toBe('en');
  });

  it('dispatches jarvis:locale_changed so the App can re-render', () => {
    const env = boot({ lang: 'ro' });
    let detail = null;
    env.window.addEventListener('jarvis:locale_changed', (e) => { detail = e.detail; });
    env.window.setLocale('en');
    expect(detail).toBe('en');
  });

  it('ignores unsupported locales', () => {
    const env = boot({ lang: 'ro' });
    env.window.setLocale('fr');
    expect(env.window.currentLocale).toBe('ro');
  });
});
