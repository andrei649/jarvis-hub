/* Theme contract v1 §2/§7 — apply.ts mirrors the appearance onto <html> before React renders and
   on every change, and survives a browser without matchMedia or with blocked storage. The
   attributes it writes drive the owner axes (overrides.css) and the legacy bridge (bridge.css),
   whose rules are checked at the end of this file. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  applyAppearanceToDocument, applyInitialAppearance, readPrefersDark, subscribePrefersDark, toHexColor,
} from '../theme/apply';
import { THEMES } from '../theme/registry';

const root = () => document.documentElement;
const attrs = () => Object.fromEntries(['data-look', 'data-scheme', 'data-font', 'data-density', 'data-motion']
  .map((name) => [name, root().getAttribute(name)]));
const CACHE = 'hud.appearance.v1:/';

/** A matchMedia stub: `matches` per query, `change` listeners per query. */
function stubMedia(state: Record<string, boolean>) {
  const listeners = new Map<string, Set<() => void>>();
  const matchMedia = vi.fn((query: string) => ({
    get matches() { return !!state[query]; },
    media: query,
    addEventListener: (_type: string, fn: () => void) => { if (!listeners.has(query)) listeners.set(query, new Set()); listeners.get(query)!.add(fn); },
    removeEventListener: (_type: string, fn: () => void) => { listeners.get(query)?.delete(fn); },
  }));
  vi.stubGlobal('matchMedia', matchMedia);
  return {
    set(query: string, value: boolean) { state[query] = value; listeners.get(query)?.forEach((fn) => fn()); },
    count: (query: string) => listeners.get(query)?.size ?? 0,
  };
}

beforeEach(() => {
  localStorage.clear();
  delete window.__NERVA_BASE_PATH__;
  for (const name of ['data-look', 'data-scheme', 'data-font', 'data-density', 'data-motion', 'style']) root().removeAttribute(name);
  document.head.querySelectorAll('meta[name="theme-color"], style[data-test-theme]').forEach((node) => node.remove());
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('applyAppearanceToDocument', () => {
  it('puts every axis on <html>, defaulting to Ledger · dark, and returns the resolved scheme', () => {
    expect(window.matchMedia).toBeUndefined();   // src/test/setup.ts has no polyfill: tolerated
    expect(applyAppearanceToDocument({}, null)).toBe('dark');
    expect(attrs()).toEqual({ 'data-look': 'ledger', 'data-scheme': 'dark', 'data-font': 'theme', 'data-density': 'normal', 'data-motion': 'lively' });
    expect(root().style.colorScheme).toBe('dark');
  });

  it('mirrors explicit choices and coerces an unknown look or scheme to the defaults', () => {
    applyAppearanceToDocument({ look: 'atlas', scheme: 'light', font: 'system-serif', density: 'compact', motion: 'calm' }, true);
    expect(attrs()).toEqual({ 'data-look': 'atlas', 'data-scheme': 'light', 'data-font': 'system-serif', 'data-density': 'compact', 'data-motion': 'calm' });
    expect(root().style.colorScheme).toBe('light');
    applyAppearanceToDocument({ look: 'retired-look', scheme: 'sepia' }, false);
    expect(attrs()['data-look']).toBe('ledger');
    expect(attrs()['data-scheme']).toBe('dark');
  });

  it('resolves system from the OS, and falls back to the theme default when the OS says nothing', () => {
    expect(applyAppearanceToDocument({ look: 'ledger', scheme: 'system' }, true)).toBe('dark');
    expect(applyAppearanceToDocument({ look: 'ledger', scheme: 'system' }, false)).toBe('light');
    expect(applyAppearanceToDocument({ look: 'ledger', scheme: 'system' }, null)).toBe('dark');
    expect(applyAppearanceToDocument({ look: 'briefing', scheme: 'system' }, null)).toBe('light');
    expect(root().getAttribute('data-scheme')).toBe('light');
  });

  it('keeps Classic dark whatever the scheme preference', () => {
    expect(applyAppearanceToDocument({ look: 'obsidian', scheme: 'light' }, false)).toBe('dark');
    expect(applyAppearanceToDocument({ look: 'graphite', scheme: 'system' }, false)).toBe('dark');
    expect(attrs()['data-look']).toBe('graphite');
    expect(attrs()['data-scheme']).toBe('dark');
  });

  it('resolves system motion from prefers-reduced-motion, as .hud-root does', () => {
    stubMedia({ '(prefers-reduced-motion: reduce)': true });
    applyAppearanceToDocument({ motion: 'system' }, null);
    expect(attrs()['data-motion']).toBe('calm');
    applyAppearanceToDocument({ motion: 'lively' }, null);
    expect(attrs()['data-motion']).toBe('lively');
  });

  it('sets <meta name="theme-color"> from the resolved --n-bg, as #rrggbb', () => {
    const meta = document.createElement('meta');
    meta.setAttribute('name', 'theme-color');
    meta.setAttribute('content', '#04070e');
    document.head.appendChild(meta);
    const style = document.createElement('style');
    style.setAttribute('data-test-theme', '');
    style.textContent = ':root[data-look="ledger"] { --n-bg: oklch(0.176 0.008 165); }'
      + ' :root[data-look="ledger"][data-scheme="light"] { --n-bg: oklch(0.979 0.006 150); }';
    document.head.appendChild(style);
    applyAppearanceToDocument({ look: 'ledger', scheme: 'dark' }, null);
    expect(meta.getAttribute('content')).toBe('#0e1210');
    applyAppearanceToDocument({ look: 'ledger', scheme: 'light' }, null);
    expect(meta.getAttribute('content')).toBe('#f5f9f6');
  });

  it('leaves the theme colour alone when no theme stylesheet resolved a ground', () => {
    const meta = document.createElement('meta');
    meta.setAttribute('name', 'theme-color');
    meta.setAttribute('content', '#04070e');
    document.head.appendChild(meta);
    applyAppearanceToDocument({ look: 'atlas' }, null);
    expect(meta.getAttribute('content')).toBe('#04070e');
  });
});

describe('applyInitialAppearance', () => {
  it('lands a fresh browser on Ledger · dark', () => {
    expect(applyInitialAppearance()).toBe('dark');
    expect(attrs()).toEqual({ 'data-look': 'ledger', 'data-scheme': 'dark', 'data-font': 'theme', 'data-density': 'normal', 'data-motion': 'lively' });
  });

  it('applies the cached choices and the pending journal synchronously', () => {
    localStorage.setItem(CACHE, JSON.stringify({ version: 2, preferences: { look: 'workbench', scheme: 'light', density: 'comfy' } }));
    applyInitialAppearance();
    expect(attrs()).toMatchObject({ 'data-look': 'workbench', 'data-scheme': 'light', 'data-density': 'comfy' });
    localStorage.setItem(CACHE + ':edit:one', JSON.stringify({ time: 1, patch: { look: 'console' } }));
    applyInitialAppearance();
    expect(attrs()['data-look']).toBe('console');
    expect(localStorage.getItem(CACHE + ':edit:one')).not.toBeNull();   // read, never consumed
  });

  it('follows the deployment prefix', () => {
    window.__NERVA_BASE_PATH__ = '/two';
    localStorage.setItem(CACHE, JSON.stringify({ version: 2, preferences: { look: 'atlas' } }));
    localStorage.setItem('hud.appearance.v1:/two', JSON.stringify({ version: 2, preferences: { look: 'presence' } }));
    applyInitialAppearance();
    expect(attrs()['data-look']).toBe('presence');
  });

  it('moves an unconfigured version-1 cache off the old default, but keeps a real choice', () => {
    localStorage.setItem(CACHE, JSON.stringify({ version: 1, preferences: { look: 'obsidian', density: 'compact' } }));
    applyInitialAppearance();
    expect(attrs()).toMatchObject({ 'data-look': 'ledger', 'data-density': 'compact' });
    localStorage.setItem(CACHE, JSON.stringify({ version: 1, preferences: { look: 'graphite' } }));
    applyInitialAppearance();
    expect(attrs()['data-look']).toBe('graphite');
    localStorage.setItem(CACHE, JSON.stringify({ version: 1, preferences: { look: 'obsidian' } }));
    localStorage.setItem(CACHE + ':edit:one', JSON.stringify({ time: 1, patch: { look: 'obsidian' } }));
    applyInitialAppearance();
    expect(attrs()['data-look']).toBe('obsidian');   // an explicit pending choice of the old default
  });

  it('treats the pre-H135 hud.look the same way', () => {
    localStorage.setItem('hud.look', 'obsidian');
    applyInitialAppearance();
    expect(attrs()['data-look']).toBe('ledger');
    localStorage.setItem('hud.look', 'graphite');
    applyInitialAppearance();
    expect(attrs()['data-look']).toBe('graphite');
  });

  it('keeps a version-2 obsidian: it was chosen after the migration', () => {
    localStorage.setItem(CACHE, JSON.stringify({ version: 2, preferences: { look: 'obsidian' } }));
    applyInitialAppearance();
    expect(attrs()['data-look']).toBe('obsidian');
  });

  it('survives storage that throws and resolves system from the OS', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage blocked'); });
    vi.spyOn(Storage.prototype, 'key').mockImplementation(() => { throw new Error('storage blocked'); });
    expect(() => applyInitialAppearance()).not.toThrow();
    expect(attrs()['data-look']).toBe('ledger');
  });

  it('resolves a cached system scheme from prefers-color-scheme', () => {
    stubMedia({ '(prefers-color-scheme: light)': true });
    localStorage.setItem(CACHE, JSON.stringify({ version: 2, preferences: { look: 'atlas', scheme: 'system' } }));
    expect(applyInitialAppearance()).toBe('light');
  });
});

describe('the OS colour scheme', () => {
  it('reads dark, light or unknown', () => {
    expect(readPrefersDark()).toBeNull();
    const media = stubMedia({});
    expect(readPrefersDark()).toBeNull();
    media.set('(prefers-color-scheme: light)', true);
    expect(readPrefersDark()).toBe(false);
    media.set('(prefers-color-scheme: dark)', true);
    expect(readPrefersDark()).toBe(true);
  });

  it('notifies changes until unsubscribed, and is inert without matchMedia', () => {
    expect(subscribePrefersDark(() => {})).toBeTypeOf('function');
    const media = stubMedia({ '(prefers-color-scheme: dark)': true });
    const seen: Array<boolean | null> = [];
    const stop = subscribePrefersDark((value) => seen.push(value));
    media.set('(prefers-color-scheme: dark)', false);
    media.set('(prefers-color-scheme: light)', true);
    expect(seen).toEqual([null]);   // only the dark query is followed; it reports the new reading
    stop();
    expect(media.count('(prefers-color-scheme: dark)')).toBe(0);
  });
});

describe('toHexColor', () => {
  it('converts the colour syntaxes a theme may use', () => {
    expect(toHexColor('#0E1210')).toBe('#0e1210');
    expect(toHexColor('#abc')).toBe('#aabbcc');
    expect(toHexColor(' oklch(0.176 0.008 165) ')).toBe('#0e1210');
    expect(toHexColor('oklch(17.6% 0.008 165deg / 0.5)')).toBe('#0e1210');
    expect(toHexColor('rgb(4, 7, 14)')).toBe('#04070e');
    expect(toHexColor('rgb(4 7 14 / 50%)')).toBe('#04070e');
    expect(toHexColor('var(--void)')).toBeNull();
    expect(toHexColor('')).toBeNull();
  });
});

/* ---- the stylesheets these attributes drive --------------------------------------------
   jsdom does not cascade custom properties, so these read the CSS as text. */
const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
type Rule = { selector: string; decls: Record<string, string> };
/** Every innermost rule (an @media block's rules included) with its custom-property declarations. */
function rules(css: string): Rule[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selector: m[1].replace(/\s+/g, ' ').trim(),
    decls: Object.fromEntries([...m[2].matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)].map((d) => [d[1], d[2].trim()])),
  }));
}
/** The same rules with every declaration, properties as well as custom properties. */
function allRules(css: string): Rule[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selector: m[1].replace(/\s+/g, ' ').trim(),
    decls: Object.fromEntries([...m[2].matchAll(/(-?-?[a-z][a-z0-9-]*)\s*:\s*([^;]+);/gi)]
      .map((d) => [d[1], d[2].replace(/\s+/g, ' ').trim()])),
  }));
}
/** A selector list split at its top-level commas (commas inside :is() / :not() stay). */
function complexSelectors(list: string): string[] {
  const parts: string[] = [];
  let depth = 0, start = 0;
  for (let i = 0; i < list.length; i++) {
    if (list[i] === '(') depth++;
    else if (list[i] === ')') depth--;
    else if (list[i] === ',' && depth === 0) { parts.push(list.slice(start, i).trim()); start = i + 1; }
  }
  parts.push(list.slice(start).trim());
  return parts;
}
/** The CSS math a density rule may use (calc, min, max, + - * /) on px values, as numbers. */
function cssMath(source: string): number {
  const tokens = source.replace(/px/g, '').match(/\d*\.?\d+|[a-z-]+|[()+*/,]/gi) ?? [];
  let at = 0;
  const take = (want?: string) => {
    const token = tokens[at++];
    if (want !== undefined && token !== want) throw new Error(`expected ${want} in ${source}, got ${token}`);
    return token;
  };
  const expr = (): number => {
    let value = term();
    while (tokens[at] === '+' || tokens[at] === '-') value = take() === '+' ? value + term() : value - term();
    return value;
  };
  const term = (): number => {
    let value = factor();
    while (tokens[at] === '*' || tokens[at] === '/') value = take() === '*' ? value * factor() : value / factor();
    return value;
  };
  const factor = (): number => {
    const token = take();
    if (token === '(') { const value = expr(); take(')'); return value; }
    if (token === 'calc' || token === 'min' || token === 'max') {
      take('(');
      const args = [expr()];
      while (tokens[at] === ',') { take(','); args.push(expr()); }
      take(')');
      return token === 'min' ? Math.min(...args) : token === 'max' ? Math.max(...args) : args[0];
    }
    const value = Number(token);
    if (!Number.isFinite(value)) throw new Error(`cannot evaluate "${token}" in ${source}`);
    return value;
  };
  const value = expr();
  if (at !== tokens.length) throw new Error(`unexpected ${tokens.slice(at).join(' ')} in ${source}`);
  return value;
}

describe('the owner axes (overrides.css)', () => {
  const overrides = rules(read('src/theme/overrides.css'));
  const rule = (selector: string) => overrides.find((r) => r.selector === selector)?.decls ?? {};
  const nervaFiles = THEMES.filter((theme) => theme.family === 'nerva').map((theme) => `src/theme/themes/${theme.id}.css`);
  /** Every control height a look can resolve: tokens.css's (Ledger, Classic) and each theme's, breakpoints included. */
  const drawn = { 'control-h': new Set<number>(), 'control-h-sm': new Set<number>() };
  for (const file of ['src/theme/tokens.css', ...nervaFiles].filter((path) => existsSync(join(process.cwd(), path)))) {
    for (const m of read(file).matchAll(/--n-(control-h(?:-sm)?)\s*:\s*([\d.]+)px/g)) drawn[m[1] as keyof typeof drawn].add(Number(m[2]));
  }

  it('scales the height each look draws: compact never raises one nor goes under 24px, comfy grows each by a fifth', () => {
    expect(drawn['control-h'].size, 'the looks draw different heights').toBeGreaterThan(2);
    const compact = rule(':root[data-look][data-density="compact"] body');
    const comfy = rule(':root[data-look][data-density="comfy"] body');
    for (const [name, heights] of Object.entries(drawn)) {
      for (const own of heights) {
        const at = (formula: string | undefined) => cssMath(String(formula).split(`var(--n-look-${name})`).join(String(own)));
        const small = at(compact[`--n-${name}`]);
        const large = at(comfy[`--n-${name}`]);
        expect(small, `compact --n-${name} for a look drawing ${own}px`).toBeLessThanOrEqual(own);
        expect(small, `compact --n-${name} for a look drawing ${own}px`).toBeGreaterThanOrEqual(Math.min(24, own));
        if (own * 0.875 >= 24) expect(small, `compact --n-${name} for ${own}px`).toBeCloseTo(own * 0.875, 5);
        expect(large, `comfy --n-${name} for a look drawing ${own}px`).toBeCloseTo(own * 1.2, 5);
      }
    }
  });

  it('reads the look\'s heights on <html> and declares the scaled ones on <body>: a property cannot scale itself', () => {
    const capture = rule(':root[data-look]:is([data-density="compact"], [data-density="comfy"])');
    expect(capture['--n-look-control-h']).toBe('var(--n-control-h)');
    expect(capture['--n-look-control-h-sm']).toBe('var(--n-control-h-sm)');
    for (const { selector, decls } of overrides) {
      if (!selector.includes('data-density') || !('--n-control-h' in decls || '--n-control-h-sm' in decls)) continue;
      expect(selector, 'a density rule that sets a control height on <html> replaces the look\'s own').toMatch(/ body$/);
    }
  });

  it('lets the typeface choice replace every face but mono in a Nerva theme, and only the interface and reading faces in Classic', () => {
    const looks = (family: 'nerva' | 'classic') =>
      `:is(${THEMES.filter((theme) => theme.family === family).map((theme) => `[data-look="${theme.id}"]`).join(', ')})`;
    // the choices are the ones styles.css draws for Classic's .hud-root (`theme` sets nothing)
    const legacy = rules(read('src/styles.css'));
    const choices = legacy.map((r) => /^\.hud-root\[data-font="([a-z-]+)"\]$/.exec(r.selector)?.[1]).filter((id): id is string => !!id);
    expect(choices.length, 'styles.css\'s .hud-root[data-font] blocks').toBeGreaterThanOrEqual(4);
    /** The rule that hands the chosen stack to a family's roles: one compound selector on <html>, naming every choice. */
    const typeface = (family: 'nerva' | 'classic') => {
      const found = overrides.filter((r) => r.selector.startsWith(`:root${looks(family)}:is(`)
        && choices.every((id) => r.selector.includes(`[data-font="${id}"]`)) && !/\s/.test(r.selector.replace(/,\s/g, ',')));
      expect(found, `one ${family} typeface rule naming every choice`).toHaveLength(1);
      return found[0]?.decls ?? {};
    };
    const stack = 'var(--n-font-chosen)';
    expect(typeface('nerva')).toEqual({
      '--n-font-ui': stack, '--n-font-label': stack, '--n-font-text': stack, '--n-font-title': stack, '--n-font-display': stack,
    });
    // Classic's labels stay mono; its titles follow --font-ui through bridge.css
    expect(typeface('classic')).toEqual({ '--n-font-ui': stack, '--n-font-text': stack });
    // each choice is the stack styles.css gives Classic's --font-ui, so it reads the same in every look
    const flat = (value: string | undefined) => String(value).replace(/\s+/g, ' ');
    for (const id of choices) {
      const own = legacy.find((r) => r.selector === `.hud-root[data-font="${id}"]`)?.decls['--font-ui'];
      expect(flat(rule(`:root[data-font="${id}"]`)['--n-font-chosen']), id).toBe(flat(own));
    }
    for (const { selector, decls } of overrides) {
      if (selector.includes('data-font')) expect(Object.keys(decls), `${selector} must leave mono alone`).not.toContain('--n-font-mono');
    }
  });
});

describe('the legacy bridge (bridge.css)', () => {
  const bridge = read('src/theme/bridge.css');
  const custom = (css: string, selector: string) => {
    const found = rules(css).find((r) => r.selector === selector);
    expect(found, `no rule ${selector}`).toBeTruthy();
    return Object.fromEntries(Object.entries(found?.decls ?? {}).map(([name, value]) => [name, value.replace(/\s+/g, '')]));
  };

  const nerva = THEMES.filter((theme) => theme.family === 'nerva').map((theme) => theme.id);
  const NERVA = `:is(${nerva.map((id) => `[data-look="${id}"]`).join(', ')})`;
  const CLASSIC = ':is([data-look="obsidian"], [data-look="graphite"])';
  const DEFAULTS = '.n-theme-scope[data-look="obsidian"], .n-theme-scope[data-look="graphite"]';
  const GRAPHITE = ':root[data-look="graphite"], .n-theme-scope[data-look="graphite"]';
  const ACCENTS = ['cyan', 'amber', 'green', 'violet'];
  const accentScope = (accent: string) => `.n-theme-scope:where([data-look="obsidian"], [data-look="graphite"])[data-accent="${accent}"]`;
  const block = (selectorPart: string) => {
    const found = rules(bridge).find((r) => r.selector.includes(selectorPart));
    expect(found, `no rule naming ${selectorPart}`).toBeTruthy();
    return found?.decls ?? {};
  };

  it('restates Classic exactly as styles.css draws it, for a Classic preview and for Graphite\'s <html>', () => {
    const styles = read('src/styles.css');
    expect(custom(bridge, DEFAULTS)).toEqual(custom(styles, ':root, .hud-root'));
    expect(custom(bridge, GRAPHITE)).toEqual(custom(styles, '.hud-root[data-look="graphite"]'));
  });

  it('restates each Classic accent exactly as styles.css draws it, at the place styles.css gives it in the cascade', () => {
    const styles = read('src/styles.css');
    for (const accent of ACCENTS) {
      expect(custom(bridge, accentScope(accent)), accent).toEqual(custom(styles, `.hud-root[data-accent="${accent}"]`));
    }
    // The blocks weigh the same, so source order decides, in both files: the defaults, then the
    // accent, then Graphite (whose own --panel-line and --bracket beat the accent's).
    const at = (css: string, selector: string) => rules(css).findIndex((r) => r.selector === selector);
    for (const accent of ACCENTS) {
      expect(at(styles, ':root, .hud-root'), accent).toBeLessThan(at(styles, `.hud-root[data-accent="${accent}"]`));
      expect(at(styles, `.hud-root[data-accent="${accent}"]`), accent).toBeLessThan(at(styles, '.hud-root[data-look="graphite"]'));
      expect(at(bridge, DEFAULTS), accent).toBeLessThan(at(bridge, accentScope(accent)));
      expect(at(bridge, accentScope(accent)), accent).toBeLessThan(at(bridge, GRAPHITE));
    }
  });

  it('turns the legacy accent into the emphasis ink in a Nerva theme, and never into the theme accent (contract §6)', () => {
    const legacy = block(':root[data-look="ledger"] .hud-root');
    expect(legacy['--accent']).toBe('var(--n-emph)');
    expect(legacy['--accent-light']).toBe('var(--n-emph)');
    expect(legacy['--accent-faint']).toBe('var(--n-emph-wash)');
    // in Ledger the accent is the owner's hand: no legacy token may reach it
    for (const [name, value] of Object.entries(legacy)) {
      expect(value, name).not.toMatch(/var\(--n-(?:accent|accent-text|accent-wash|on-accent)\)/);
    }
  });

  it('gives Classic every derived colour role from its own legacy tokens, on .hud-root as well as <html>', () => {
    // a derived role is one tokens.css defaults to another colour role (contract §3)
    const tokens = rules(read('src/theme/tokens.css')).find((r) => r.selector === ':is(:root, .n-theme-scope)')?.decls ?? {};
    const derived = Object.entries(tokens).filter(([, value]) => {
      const ref = /^var\((--n-[a-z0-9-]+)\)$/.exec(value);
      return !!ref && /^(?:oklch\(|#)/.test(tokens[ref[1]] ?? '');
    }).map(([name]) => name);
    expect(derived.length, 'tokens.css\'s derived roles').toBeGreaterThanOrEqual(5);
    const classic = block(':root[data-look="obsidian"] .hud-root');
    for (const name of derived) expect(classic[name], `${name} needs a Classic value in bridge.css`).toBeTruthy();
    expect(classic).toMatchObject({
      '--n-emph': 'var(--accent-light)', '--n-emph-wash': 'var(--accent-faint)',
      '--n-primary': 'var(--accent)', '--n-on-primary': 'var(--void)', '--n-field-bg': 'var(--surface)',
    });
  });

  it('sets a Nerva page in the theme\'s face, body weight and figures, and fields on the field fill', () => {
    const all = allRules(bridge);
    const find = (test: (selector: string) => boolean, what: string) => {
      const at = all.findIndex((r) => test(r.selector));
      expect(at, what).toBeGreaterThan(-1);
      return { at, decls: all[at]?.decls ?? {} };
    };
    expect(find((s) => s === `:root${NERVA} body`, 'the body rule').decls).toMatchObject({
      'font-family': 'var(--n-font-ui)', 'font-weight': 'var(--n-w-reg)', 'font-variant-numeric': 'var(--n-numerals)',
    });
    const fields = find((s) => s.includes(', select, textarea, button)'), 'the base form-control rule');
    expect(fields.decls['background-color']).toBe('var(--n-field-bg)');
    expect(find((s) => s.includes(':is(option, optgroup)'), 'the option rule').decls['background-color']).toBe('var(--n-field-bg)');
    // a bare button is not a field: the same zero weight, later, puts it back on the raised sheet
    // in the control shape (contract §3: --n-r-control for buttons, a pill in Atlas)
    const buttons = find((s) => / button:not\(/.test(s) && !s.includes('select'), 'the bare-button rule');
    expect(buttons.decls).toMatchObject({ 'background-color': 'var(--n-sheet)', 'border-radius': 'var(--n-r-control)' });
    expect(buttons.at).toBeGreaterThan(fields.at);
    // a preview restates what the page hands down, in its own look; a Classic one takes back its own
    const scope = find((s) => s === `:where(.n-theme-scope${NERVA})`, 'the Nerva preview rule').decls;
    const classicScope = find((s) => s === `:where(.n-theme-scope${CLASSIC})`, 'the Classic preview rule').decls;
    expect(scope).toMatchObject({ 'font-weight': 'var(--n-w-reg)', 'font-variant-numeric': 'var(--n-numerals)' });
    expect(Object.keys(classicScope).sort()).toEqual(Object.keys(scope).sort());
  });

  it('styles what lies under a Nerva look in a Nerva preview too, and nothing inside a Classic preview (contract §2)', () => {
    // <html>, its light scheme and <body> belong to the page; the two preview rules to the scope element
    const own = [`:root${NERVA}`, `:root${NERVA}[data-scheme="light"]`, `:root${NERVA} body`, `:where(.n-theme-scope${NERVA})`];
    let checked = 0;
    for (const { selector } of allRules(bridge)) {
      for (const complex of complexSelectors(selector)) {
        if (!complex.includes(NERVA) || own.includes(complex)) continue;
        checked++;
        expect(complex.includes(`.n-theme-scope${NERVA}`) || complex.includes(`.n-theme-scope)${NERVA}`),
          `${complex} must also match under a Nerva .n-theme-scope (a preview on a Classic page)`).toBe(true);
        expect(complex, 'must skip a Classic .n-theme-scope on a Nerva page').toContain(`:not(.n-theme-scope${CLASSIC}`);
        expect(complex, 'must skip a Classic .n-theme-scope on a Nerva page').toContain(`.n-theme-scope${CLASSIC} *)`);
      }
    }
    expect(checked, 'rules under a Nerva look').toBeGreaterThan(12);
  });

  it('names every Nerva theme wherever it names one', () => {
    const mentions = (id: string) => bridge.split(`[data-look="${id}"]`).length - 1;
    expect(mentions('ledger')).toBeGreaterThan(10);
    for (const id of nerva) expect(mentions(id), id).toBe(mentions('ledger'));
  });
});
