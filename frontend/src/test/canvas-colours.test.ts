/* Theme roles for canvas drawing (src/theme/canvas-colours.ts): which looks are Nerva, how a role
   becomes an [r, g, b] through a 1×1 probe canvas, the (look, scheme) cache and its invalidation,
   and that nothing throws where there is no 2D context (jsdom), so a canvas keeps its own palette.
   jsdom has no canvas, so the probe here is a stub that paints like a browser for one pixel: it
   accepts what a browser parses (hex, rgb(), oklch() through apply.ts's converter, transparent),
   keeps its previous fillStyle for anything else, and reads the painted pixel back. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { toHexColor } from '../theme/apply';
import { THEMES } from '../theme/registry';
import {
  NERVA_LOOKS, invalidateRoleColours, isNervaLook, paletteKey, readRole, readRoleColours, rgb, rgba, themeOf, watchLook,
} from '../theme/canvas-colours';

const root = () => document.documentElement;
const realGetContext = HTMLCanvasElement.prototype.getContext;

const triple = (hex: string | null) => (hex
  ? [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)]
  : null);

/** A one-pixel 2D context that parses and paints a colour as a browser would. */
function pixelContext({ readBack }: { readBack?: (pixel: number[]) => number[] } = {}) {
  let style = '#000000';
  let pixel = [0, 0, 0, 0];
  const ctx = {
    reads: 0,
    get fillStyle() { return style; },
    set fillStyle(value: string) {
      const text = String(value).trim();
      if (text === 'transparent') { style = 'rgba(0, 0, 0, 0)'; return; }
      const hex = toHexColor(text);
      if (hex) style = hex;            // an unparsable colour leaves the old one, as in a browser
    },
    clearRect() { pixel = [0, 0, 0, 0]; },
    fillRect() { pixel = style.startsWith('#') ? [...triple(style)!, 255] : [0, 0, 0, 0]; },
    getImageData() {
      ctx.reads += 1;
      return { data: Uint8ClampedArray.from(readBack ? readBack(pixel) : pixel) };
    },
  };
  return ctx;
}

function useProbe(ctx: unknown) {
  const getContext = vi.fn(() => ctx);
  HTMLCanvasElement.prototype.getContext = getContext as any;
  return getContext;
}

function element() {
  const el = document.createElement('div');
  document.body.appendChild(el);
  return el;
}

beforeEach(() => {
  invalidateRoleColours();
  for (const name of ['data-look', 'data-scheme', 'data-font', 'style']) root().removeAttribute(name);
  document.head.querySelectorAll('style[data-test-theme]').forEach((node) => node.remove());
  document.body.innerHTML = '';
});
afterEach(() => {
  HTMLCanvasElement.prototype.getContext = realGetContext;
  invalidateRoleColours();
});

describe('Nerva or Classic', () => {
  it('takes the seven Nerva looks from the registry; Classic and unknown looks are not Nerva', () => {
    const nerva = THEMES.filter((theme) => theme.family === 'nerva').map((theme) => theme.id);
    expect([...NERVA_LOOKS].sort()).toEqual([...nerva].sort());
    expect(NERVA_LOOKS).toHaveLength(7);
    for (const id of nerva) expect(isNervaLook(id)).toBe(true);
    for (const id of ['obsidian', 'graphite', 'retired-look', '', null]) expect(isNervaLook(id)).toBe(false);
  });

  it('reads <html data-look> when no look is given; no look at all is not Nerva', () => {
    expect(isNervaLook()).toBe(false);
    root().setAttribute('data-look', 'ledger');
    expect(isNervaLook()).toBe(true);
    root().setAttribute('data-look', 'atlas');
    expect(isNervaLook()).toBe(true);
    root().setAttribute('data-look', 'obsidian');
    expect(isNervaLook()).toBe(false);
    root().setAttribute('data-look', 'graphite');
    expect(isNervaLook()).toBe(false);
  });

  it('follows the .n-theme-scope preview an element is drawn in, else <html>', () => {
    root().setAttribute('data-look', 'ledger');
    root().setAttribute('data-scheme', 'dark');
    const scope = element();
    scope.className = 'n-theme-scope';
    scope.setAttribute('data-look', 'atlas');
    scope.setAttribute('data-scheme', 'light');
    const inside = document.createElement('span');
    scope.appendChild(inside);
    expect(themeOf(inside)).toEqual({ look: 'atlas', scheme: 'light' });
    expect(paletteKey(inside)).toBe('atlas|light');
    expect(themeOf(element())).toEqual({ look: 'ledger', scheme: 'dark' });
    expect(themeOf()).toEqual({ look: 'ledger', scheme: 'dark' });
    expect(paletteKey()).toBe('ledger|dark');
  });
});

describe('readRoleColours', () => {
  it('resolves each role through the probe, a derived var() role included', () => {
    useProbe(pixelContext());
    root().setAttribute('data-look', 'ledger');
    root().setAttribute('data-scheme', 'dark');
    root().style.setProperty('--n-text', '#102030');
    root().style.setProperty('--n-emph', 'var(--n-text)');
    root().style.setProperty('--n-ok', 'oklch(0.780 0.060 150)');
    const colours = readRoleColours(element(), ['n-text', '--n-emph', 'n-ok', 'n-unset']);
    expect(colours).not.toBeNull();
    expect(colours!['n-text']).toEqual([16, 32, 48]);
    expect(colours!['--n-emph']).toEqual([16, 32, 48]);
    expect(colours!['n-ok']).toEqual(triple(toHexColor('oklch(0.780 0.060 150)')));
    expect(colours!['n-unset']).toBeNull();
  });

  it('gives null for a transparent role and for a value the canvas cannot parse', () => {
    useProbe(pixelContext());
    root().setAttribute('data-look', 'ledger');
    root().style.setProperty('--n-panel-bg', 'transparent');
    root().style.setProperty('--n-odd', 'not-a-colour');
    root().style.setProperty('--n-text', '#010203');     // the probe's own sentinel is still a colour
    const colours = readRoleColours(element(), ['n-panel-bg', 'n-odd', 'n-text']);
    expect(colours).toEqual({ 'n-panel-bg': null, 'n-odd': null, 'n-text': [1, 2, 3] });
  });

  it('resolves the real theme files: Ledger · Carbon and Ledger · Paper, emphasis pointing at the ink', () => {
    useProbe(pixelContext());
    const css = ['src/theme/tokens.css', 'src/theme/themes/ledger.css']
      .map((path) => readFileSync(join(process.cwd(), path), 'utf8')).join('\n');
    const style = document.createElement('style');
    style.setAttribute('data-test-theme', '');
    style.textContent = css;
    document.head.appendChild(style);
    const el = element();
    root().setAttribute('data-look', 'ledger');
    root().setAttribute('data-scheme', 'dark');
    const dark = readRoleColours(el, ['n-text', 'n-emph', 'n-bg', 'n-panel-bg']);
    expect(dark!['n-text']).toEqual(triple(toHexColor('oklch(0.912 0.014 138)')));
    expect(dark!['n-emph']).toEqual(dark!['n-text']);
    expect(dark!['n-bg']).toEqual(triple(toHexColor('oklch(0.176 0.008 165)')));
    expect(dark!['n-panel-bg']).toBeNull();          // Ledger draws registers without a box
    root().setAttribute('data-scheme', 'light');
    const light = readRoleColours(el, ['n-text', 'n-bg']);
    expect(light!['n-text']).toEqual(triple(toHexColor('oklch(0.205 0.022 165)')));
    expect(light!['n-bg']).toEqual(triple(toHexColor('oklch(0.979 0.006 150)')));
  });
});

describe('the (look, scheme) cache', () => {
  it('serves a role from the cache until the look or scheme changes, then reads it afresh', () => {
    const probe = pixelContext();
    useProbe(probe);
    const el = element();
    root().setAttribute('data-look', 'ledger');
    root().setAttribute('data-scheme', 'dark');
    root().style.setProperty('--n-text', '#102030');
    expect(readRoleColours(el, ['n-text'])!['n-text']).toEqual([16, 32, 48]);
    const reads = probe.reads;

    root().style.setProperty('--n-text', '#405060');
    expect(readRoleColours(el, ['n-text'])!['n-text']).toEqual([16, 32, 48]);   // cached
    expect(probe.reads).toBe(reads);

    root().setAttribute('data-look', 'atlas');
    expect(readRoleColours(el, ['n-text'])!['n-text']).toEqual([64, 80, 96]);   // a look change re-reads
    root().style.setProperty('--n-text', '#708090');
    root().setAttribute('data-look', 'ledger');
    expect(readRoleColours(el, ['n-text'])!['n-text']).toEqual([112, 128, 144]); // nothing stale comes back
    root().style.setProperty('--n-text', '#a0b0c0');
    root().setAttribute('data-scheme', 'light');
    expect(readRoleColours(el, ['n-text'])!['n-text']).toEqual([160, 176, 192]); // so does a scheme change
  });

  it('invalidateRoleColours() drops the cache and the probe', () => {
    const probe = pixelContext();
    const getContext = useProbe(probe);
    const el = element();
    root().setAttribute('data-look', 'ledger');
    root().style.setProperty('--n-text', '#102030');
    readRoleColours(el, ['n-text']);
    root().style.setProperty('--n-text', '#405060');
    expect(readRoleColours(el, ['n-text'])!['n-text']).toEqual([16, 32, 48]);
    expect(getContext).toHaveBeenCalledTimes(1);
    invalidateRoleColours();
    expect(readRoleColours(el, ['n-text'])!['n-text']).toEqual([64, 80, 96]);
    expect(getContext).toHaveBeenCalledTimes(2);
  });

  it('watchLook() drops the cache and calls back when the look, scheme or typeface changes', async () => {
    const probe = pixelContext();
    useProbe(probe);
    const el = element();
    root().setAttribute('data-look', 'ledger');
    root().setAttribute('data-scheme', 'dark');
    root().style.setProperty('--n-text', '#102030');
    readRoleColours(el, ['n-text']);
    // the callback runs after the drop, so a read inside it is already fresh
    const seen: unknown[] = [];
    const onChange = vi.fn(() => { seen.push(readRoleColours(el, ['n-text'])?.['n-text']); });
    const stop = watchLook(onChange);
    const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

    root().style.setProperty('--n-text', '#405060');
    root().setAttribute('data-look', 'presence');
    await flush();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(seen).toEqual([[64, 80, 96]]);

    // a typeface change keeps the (look, scheme) key: only the watcher's drop makes it re-read
    root().style.setProperty('--n-text', '#708090');
    root().setAttribute('data-font', 'system-serif');
    await flush();
    expect(seen[seen.length - 1]).toEqual([112, 128, 144]);
    root().setAttribute('data-scheme', 'light');
    await flush();
    expect(onChange).toHaveBeenCalledTimes(3);

    root().setAttribute('data-density', 'compact');        // not a canvas concern
    await flush();
    expect(onChange).toHaveBeenCalledTimes(3);

    stop();
    root().setAttribute('data-look', 'ledger');
    await flush();
    expect(onChange).toHaveBeenCalledTimes(3);
  });
});

describe('no 2D context: null, never a throw', () => {
  const read = () => {
    root().setAttribute('data-look', 'ledger');
    root().style.setProperty('--n-text', '#102030');
    return readRoleColours(element(), ['n-text']);
  };

  it('in jsdom as it is (no canvas implementation; jsdom logs "Not implemented" for each probe)', () => {
    expect(() => read()).not.toThrow();
    invalidateRoleColours();
    expect(read()).toBeNull();
  });

  it('when getContext returns null, and asks only once until invalidated', () => {
    const getContext = useProbe(null);
    expect(read()).toBeNull();
    expect(read()).toBeNull();
    expect(getContext).toHaveBeenCalledTimes(1);
    invalidateRoleColours();
    expect(read()).toBeNull();
    expect(getContext).toHaveBeenCalledTimes(2);
  });

  it('when getContext throws, or the context cannot read pixels back', () => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => { throw new Error('blocked'); }) as any;
    expect(read()).toBeNull();
    invalidateRoleColours();
    useProbe({ fillStyle: '', fillRect() {}, clearRect() {} });   // no getImageData
    expect(read()).toBeNull();
    invalidateRoleColours();
    const throwing = pixelContext();
    throwing.getImageData = () => { throw new Error('read-back blocked'); };
    useProbe(throwing);
    expect(read()).toBeNull();
  });

  it('when the read-back is blanked or randomised (anti-fingerprinting): wrong colours are not used', () => {
    useProbe(pixelContext({ readBack: () => [255, 255, 255, 255] }));
    expect(read()).toBeNull();
    invalidateRoleColours();
    useProbe(pixelContext({ readBack: ([r, g, b, a]) => [r ^ 0x55, g ^ 0x2a, b, a] }));
    expect(read()).toBeNull();
  });

  it('with no element: <html> is read', () => {
    useProbe(pixelContext());
    root().setAttribute('data-look', 'ledger');
    root().style.setProperty('--n-text', '#102030');
    expect(readRoleColours(null, ['n-text'])!['n-text']).toEqual([16, 32, 48]);
  });
});

describe('helpers', () => {
  it('readRole returns the trimmed computed value, or an empty string', () => {
    root().style.setProperty('--n-fs-meta', '13px');
    const el = element();
    expect(readRole(el, 'n-fs-meta')).toBe('13px');
    expect(readRole(el, '--n-fs-meta')).toBe('13px');
    expect(readRole(null, 'n-fs-meta')).toBe('13px');
    expect(readRole(el, 'n-not-a-role')).toBe('');
  });

  it('rgb() and rgba() write canvas colours; alpha is clamped', () => {
    expect(rgb([1, 2, 3])).toBe('rgb(1, 2, 3)');
    expect(rgba([1, 2, 3], 0.5)).toBe('rgba(1, 2, 3, 0.5)');
    expect(rgba([1, 2, 3], 2)).toBe('rgba(1, 2, 3, 1)');
    expect(rgba([1, 2, 3], -1)).toBe('rgba(1, 2, 3, 0)');
    expect(rgba([1, 2, 3], Number.NaN)).toBe('rgba(1, 2, 3, 1)');
  });
});
