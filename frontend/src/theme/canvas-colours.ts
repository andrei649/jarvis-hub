/**
 * Theme roles for canvas drawing (contract v1, see ./CONTRACT.md §3).
 *
 * A 2D canvas cannot paint `var(--n-text)`: it needs a colour it can parse. This module reads a
 * role from the element the canvas sits in (`getComputedStyle(el).getPropertyValue('--n-…')`,
 * which already resolves a derived role's `var()` to the role it points at) and converts it
 * through the browser: the value is painted into a 1×1 probe canvas and read back. So `oklch()`
 * literals, hex and any later colour syntax all come back as sRGB `[r, g, b]` without this file
 * parsing a colour itself.
 *
 * Results are cached per (look, scheme): the `data-look` / `data-scheme` of <html>, or of the
 * nearest `.n-theme-scope` preview the element is drawn in (contract §2). A role is resolved once
 * per theme, not once per frame, and a read under another look or scheme drops what the last one
 * cached. `invalidateRoleColours()` drops the cache outright; `watchLook()` calls it, and its own
 * callback, whenever <html>'s look, scheme or typeface changes. Classic's accent axis lives on
 * `.hud-root` and is not part of the key: a caller that resolves Classic roles must invalidate on
 * an accent change itself (the mesh resolves roles in the Nerva looks only).
 *
 * Nothing here throws. Without a 2D context that can read pixels back (jsdom, a blocked or
 * randomised canvas) `readRoleColours()` returns null and the caller keeps its own palette.
 */
import { THEMES, type ThemeId } from './registry';

/** A resolved colour, sRGB 0–255. Alpha is not kept: a caller adds its own with `rgba()`. */
export type RGB = readonly [number, number, number];
export type RoleColours<R extends string> = { readonly [K in R]: RGB | null };

/** The seven Nerva looks: the registry's `nerva` family (Classic is obsidian and graphite). */
export const NERVA_LOOKS: readonly ThemeId[] = Object.freeze(
  THEMES.filter((theme) => theme.family === 'nerva').map((theme) => theme.id),
);
const NERVA = new Set<string>(NERVA_LOOKS);

function rootAttribute(name: string): string | null {
  try {
    return typeof document === 'undefined' ? null : document.documentElement?.getAttribute(name) ?? null;
  } catch {
    return null;
  }
}

/**
 * True for the seven Nerva looks. With no argument it reads `data-look` from <html>. A missing or
 * unknown look is not Nerva: a canvas then keeps its legacy palette, as Classic does.
 */
export function isNervaLook(look: string | null | undefined = rootAttribute('data-look')): boolean {
  return typeof look === 'string' && NERVA.has(look);
}

/** The look and scheme `el` is drawn in: its nearest `.n-theme-scope` preview's, else <html>'s. */
export function themeOf(el?: Element | null): { look: string | null; scheme: string | null } {
  try {
    const scope = el && typeof el.closest === 'function' ? el.closest('.n-theme-scope[data-look]') : null;
    if (scope) return { look: scope.getAttribute('data-look'), scheme: scope.getAttribute('data-scheme') };
  } catch { /* a detached or foreign node: fall back to the page */ }
  return { look: rootAttribute('data-look'), scheme: rootAttribute('data-scheme') };
}

/** The cache key a read from `el` uses: `look|scheme`. */
export function paletteKey(el?: Element | null): string {
  const { look, scheme } = themeOf(el);
  return `${look ?? ''}|${scheme ?? ''}`;
}

const roleName = (role: string): string => {
  const name = String(role).trim();
  return name.startsWith('--') ? name : `--${name}`;
};

function styleOf(el: Element | null | undefined): CSSStyleDeclaration | null {
  try {
    const target = el ?? (typeof document === 'undefined' ? null : document.documentElement);
    if (!target || typeof getComputedStyle !== 'function') return null;
    return getComputedStyle(target);
  } catch {
    return null;
  }
}

/** A role's computed value on `el` (<html> when omitted) as text, trimmed; '' when unset. */
export function readRole(el: Element | null | undefined, role: string): string {
  try {
    return styleOf(el)?.getPropertyValue(roleName(role)).trim() ?? '';
  } catch {
    return '';
  }
}

/* ---- the probe: a 1×1 canvas the browser paints a colour into ---------------------------- */

// undefined: not tried yet · null: no usable 2D context here (kept until invalidated, so an
// environment without one is asked once, not once per read)
let probe: CanvasRenderingContext2D | null | undefined;
// The roles resolved for one (look, scheme): `cacheKey`.
let cacheKey = '';
const cache = new Map<string, RGB | null>();

/** Paints `value` into the probe and reads the pixel back; null for an unparsable or transparent value. */
function paint(ctx: CanvasRenderingContext2D, value: string): RGB | null {
  if (!value) return null;
  // A colour the canvas cannot parse leaves fillStyle as it was: assign the value over two
  // different sentinels, and a value that left both in place was rejected.
  ctx.fillStyle = '#010203';
  ctx.fillStyle = value;
  const keptFirst = String(ctx.fillStyle) === '#010203';
  ctx.fillStyle = '#030201';
  ctx.fillStyle = value;
  if (keptFirst && String(ctx.fillStyle) === '#030201') return null;
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillRect(0, 0, 1, 1);
  const data = ctx.getImageData(0, 0, 1, 1)?.data;
  if (!data || data.length < 4 || data[3] === 0) return null;
  return Object.freeze([data[0], data[1], data[2]] as const);
}

function probeContext(): CanvasRenderingContext2D | null {
  if (probe !== undefined) return probe;
  probe = null;
  try {
    if (typeof document === 'undefined') return null;
    const canvas = document.createElement('canvas');
    canvas.width = 1;
    canvas.height = 1;
    const ctx = canvas.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D | null;
    if (!ctx || typeof ctx.getImageData !== 'function' || typeof ctx.fillRect !== 'function'
      || typeof ctx.clearRect !== 'function') return null;
    // A browser that blanks or randomises canvas read-back (anti-fingerprinting) would hand back
    // wrong colours: a known red has to come back red, or the probe is not used.
    const red = paint(ctx, '#ff0000');
    if (!red || red[0] < 250 || red[1] > 5 || red[2] > 5) return null;
    probe = ctx;
  } catch {
    probe = null;
  }
  return probe;
}

/**
 * Each role's resolved colour on `el`, as `[r, g, b]` (null for a role that is unset, invalid or
 * transparent), or null when this environment has no 2D context to resolve colours with.
 * `roles` are names with or without the leading dashes: `'n-text'` or `'--n-text'`.
 * `el` must be drawn in the theme its key names (any element of the page, or of one preview).
 */
export function readRoleColours<R extends string>(
  el: Element | null | undefined,
  roles: readonly R[],
): RoleColours<R> | null {
  try {
    const ctx = probeContext();
    if (!ctx) return null;
    const key = paletteKey(el);
    if (key !== cacheKey) {
      cache.clear();
      cacheKey = key;
    }
    let style: CSSStyleDeclaration | null | undefined;
    const out = {} as Record<R, RGB | null>;
    for (const role of roles) {
      const name = roleName(role);
      if (!cache.has(name)) {
        if (style === undefined) style = styleOf(el);
        const value = style ? style.getPropertyValue(name).trim() : '';
        cache.set(name, paint(ctx, value));
      }
      out[role] = cache.get(name) ?? null;
    }
    return out;
  } catch {
    return null;
  }
}

/** Drops every cached colour and the probe, so the next read resolves afresh. */
export function invalidateRoleColours(): void {
  cache.clear();
  cacheKey = '';
  probe = undefined;
}

/**
 * Calls `onChange` after the cache is dropped whenever <html>'s `data-look`, `data-scheme` or
 * `data-font` changes (the typeface matters to a canvas that draws text in the theme's faces).
 * Returns the unsubscribe; a no-op where MutationObserver is missing.
 */
export function watchLook(onChange: () => void): () => void {
  try {
    if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') return () => {};
    const observer = new MutationObserver(() => {
      invalidateRoleColours();
      onChange();
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-look', 'data-scheme', 'data-font'],
    });
    return () => observer.disconnect();
  } catch {
    return () => {};
  }
}

/** `rgb(r, g, b)` for a canvas fillStyle / strokeStyle. */
export const rgb = (c: RGB): string => `rgb(${c[0]}, ${c[1]}, ${c[2]})`;

/** `rgba(r, g, b, a)`, alpha clamped to 0–1. */
export function rgba(c: RGB, alpha: number): string {
  const a = Number.isFinite(alpha) ? Math.min(1, Math.max(0, alpha)) : 1;
  return `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${a})`;
}
