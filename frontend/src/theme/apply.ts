/**
 * Mirrors the owner's appearance onto <html> (contract v1, see ./CONTRACT.md §2 and §7).
 *
 * The theme files select on `<html data-look data-scheme>`, so these attributes colour the whole
 * document: the page behind `.hud-root` and anything rendered outside it. `applyInitialAppearance()`
 * runs in main.tsx before React renders, from the browser's cached choices, so the first paint is
 * already in the owner's theme (there is no inline script: the CSP forbids one). `App` then calls
 * `applyAppearanceToDocument()` whenever a preference or the OS colour scheme changes.
 *
 * Every browser API used here may be missing (jsdom, an old engine) or throw (blocked storage); the
 * page then keeps what it has and the HUD still renders.
 */
import { readCachedAppearance } from '../appearance';
import {
  DEFAULT_SCHEME_PREFERENCE, SCHEME_PREFERENCES, resolveScheme, themeById, type Scheme, type SchemePreference,
} from './registry';

type Preferences = Readonly<Partial<Record<string, string>>>;

const DARK = '(prefers-color-scheme: dark)';
const LIGHT = '(prefers-color-scheme: light)';
const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

function media(query: string): MediaQueryList | null {
  try {
    return typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query) || null : null;
  } catch {
    return null;
  }
}

/** The OS colour scheme: true dark, false light, null when it cannot be read. */
export function readPrefersDark(): boolean | null {
  if (media(DARK)?.matches) return true;
  if (media(LIGHT)?.matches) return false;
  return null;
}

/** Calls `listener` with `readPrefersDark()` whenever the OS colour scheme changes. Returns the unsubscribe. */
export function subscribePrefersDark(listener: (prefersDark: boolean | null) => void): () => void {
  const query = media(DARK);
  if (!query) return () => {};
  const changed = () => listener(readPrefersDark());
  try {
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', changed);
      return () => { try { query.removeEventListener('change', changed); } catch { /* already gone */ } };
    }
    if (typeof query.addListener === 'function') {   // Safari before 14
      query.addListener(changed);
      return () => { try { query.removeListener(changed); } catch { /* already gone */ } };
    }
  } catch { /* a partial MediaQueryList: nothing to follow */ }
  return () => {};
}

function schemePreference(value: string | undefined): SchemePreference {
  return (SCHEME_PREFERENCES as readonly string[]).includes(value ?? '') ? value as SchemePreference : DEFAULT_SCHEME_PREFERENCE;
}

/** `motion` as `.hud-root` carries it: `system` resolved from prefers-reduced-motion. */
function resolvedMotion(value: string | undefined): string {
  if (value === 'calm' || value === 'lively') return value;
  return media(REDUCED_MOTION)?.matches ? 'calm' : 'lively';
}

function setAttribute(element: Element, name: string, value: string) {
  if (element.getAttribute(name) !== value) element.setAttribute(name, value);
}

function oklchToHex(l: number, c: number, hue: number): string {
  const h = (hue * Math.PI) / 180;
  const a = c * Math.cos(h), b = c * Math.sin(h);
  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;
  const [L, M, S] = [l_ ** 3, m_ ** 3, s_ ** 3];
  const linear = [
    4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ];
  return '#' + linear.map((value) => {
    const x = Math.min(1, Math.max(0, value));
    const encoded = x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055;
    return Math.round(encoded * 255).toString(16).padStart(2, '0');
  }).join('');
}

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;
const OKLCH = /^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)(%?)\s+([\d.]+)(?:deg)?\s*(?:\/\s*[\d.]+%?\s*)?\)$/i;
const RGB = /^rgba?\(\s*([\d.]+)\s*[,\s]\s*([\d.]+)\s*[,\s]\s*([\d.]+)\s*(?:[,/]\s*[\d.]+%?\s*)?\)$/i;

/**
 * A theme colour as `#rrggbb` for `<meta name="theme-color">`, which older engines read only in
 * sRGB syntax. Accepts hex, `rgb()` and `oklch()` (alpha is dropped); null for anything else.
 */
export function toHexColor(value: string): string | null {
  const text = value.trim();
  const hex = HEX.exec(text);
  if (hex) {
    const digits = hex[1].toLowerCase();
    return '#' + (digits.length === 3 ? digits.split('').map((d) => d + d).join('') : digits);
  }
  const ok = OKLCH.exec(text);
  if (ok) return oklchToHex(Number(ok[1]) / (ok[2] ? 100 : 1), Number(ok[3]) * (ok[4] ? 0.004 : 1), Number(ok[5]));
  const rgb = RGB.exec(text);
  if (rgb) {
    return '#' + [rgb[1], rgb[2], rgb[3]]
      .map((v) => Math.round(Math.min(255, Math.max(0, Number(v)))).toString(16).padStart(2, '0')).join('');
  }
  return null;
}

/** `<meta name="theme-color">` follows the page ground the theme actually resolved. */
function syncThemeColor(root: HTMLElement) {
  let ground = '';
  try {
    // .hud-root once React has rendered it (styles.css restates Classic's tokens there, accent
    // axis included); before that <html>, where the theme files, and bridge.css for Graphite,
    // resolve the same ground, so the first theme colour is already the look's own.
    const surface = document.querySelector<HTMLElement>('.hud-root') ?? root;
    ground = getComputedStyle(surface).getPropertyValue('--n-bg').trim();
  } catch { return; }
  const color = toHexColor(ground);
  if (!color) return;
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (!meta) {
    if (!document.head) return;
    meta = document.createElement('meta');
    meta.setAttribute('name', 'theme-color');
    document.head.appendChild(meta);
  }
  if (meta.getAttribute('content') !== color) meta.setAttribute('content', color);
}

/**
 * Puts the appearance on <html>: `data-look` (an unknown look becomes the default theme),
 * `data-scheme` (resolved, never `system`), `data-font`, `data-density`, `data-motion` (resolved),
 * `color-scheme`, and the theme colour from the resolved `--n-bg`. Returns the resolved scheme.
 * `prefersDark` is the OS preference (`readPrefersDark()`); it only matters for `scheme: system`.
 */
export function applyAppearanceToDocument(preferences: Preferences, prefersDark: boolean | null): Scheme {
  const theme = themeById(preferences.look);
  const scheme = resolveScheme(theme, schemePreference(preferences.scheme), prefersDark);
  if (typeof document === 'undefined') return scheme;
  const root = document.documentElement;
  setAttribute(root, 'data-look', theme.id);
  setAttribute(root, 'data-scheme', scheme);
  setAttribute(root, 'data-font', preferences.font || 'theme');
  setAttribute(root, 'data-density', preferences.density || 'normal');
  setAttribute(root, 'data-motion', resolvedMotion(preferences.motion));
  try { root.style.colorScheme = scheme; } catch { /* an engine without color-scheme */ }
  syncThemeColor(root);
  return scheme;
}

/** main.tsx, before React renders: the cached choices onto <html>, so the first paint is themed. */
export function applyInitialAppearance(): Scheme {
  let preferences: Preferences = {};
  try { preferences = readCachedAppearance(); } catch { /* storage blocked: the defaults */ }
  return applyAppearanceToDocument(preferences, readPrefersDark());
}
