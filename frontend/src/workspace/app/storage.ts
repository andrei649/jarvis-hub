/* Per-browser conveniences only (last theme for the sign-in screen, last department).
   The source of truth for preferences is the server (PATCH /me); storage can be blocked or
   cleared at any time, so every access is guarded and a miss simply means "use the default". */
import type { Locale, Theme } from '../api/types';

const PREFIX = 'nerva.workspace.';

export function readPref(key: string): string | null {
  try {
    return window.localStorage.getItem(PREFIX + key);
  } catch {
    return null;
  }
}

export function writePref(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(PREFIX + key);
    else window.localStorage.setItem(PREFIX + key, value);
  } catch {
    // Storage blocked (private mode, policy): the preference just is not remembered.
  }
}

/** Survives reloads of this tab only; used to stop SSO from signing the user straight back in after logout. */
export function readSessionFlag(key: string): boolean {
  try {
    return window.sessionStorage.getItem(PREFIX + key) === '1';
  } catch {
    return false;
  }
}

export function writeSessionFlag(key: string, on: boolean): void {
  try {
    if (on) window.sessionStorage.setItem(PREFIX + key, '1');
    else window.sessionStorage.removeItem(PREFIX + key);
  } catch {
    // Storage blocked: SSO may sign the user in again on reload, which is still correct behaviour.
  }
}

export function cachedTheme(): Theme {
  const value = readPref('theme');
  return value === 'dark' || value === 'system' ? value : 'light';
}

export function cachedLocale(): Locale | null {
  const value = readPref('locale');
  return value === 'ro' || value === 'en' ? value : null;
}
