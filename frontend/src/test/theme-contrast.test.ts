/**
 * Theme contract v1 (frontend/src/theme/CONTRACT.md): every theme file declares every
 * colour role for every scheme it supports, uses the contract's selectors, and every
 * text-bearing role clears WCAG 2.2 AA on every ground it can sit on.
 *
 * Colours are resolved from literal oklch()/hex values. OKLCH is converted to sRGB the way
 * the CSS Color 4 reference does and then clipped; contrast is computed on the clipped
 * colour, which is what Chromium paints today.
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { THEMES } from '../theme/registry';

const dir = join(process.cwd(), 'src', 'theme', 'themes');
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');

export const COLOUR_ROLES = [
  'bg', 'bg-2', 'bg-3', 'sheet', 'sheet-2', 'scrim',
  'text', 'text-2', 'text-3',
  'rule', 'rule-2', 'rule-field', 'rule-heavy',
  'accent', 'accent-text', 'accent-wash', 'on-accent',
  'stop', 'on-stop',
  'ok', 'warn', 'bad', 'info', 'cloud', 'ok-wash', 'warn-wash', 'bad-wash',
  'focus', 'selection',
] as const;

type Rgb = [number, number, number];

function oklchToRgb(l: number, c: number, hDeg: number): Rgb {
  const h = (hDeg * Math.PI) / 180;
  const a = c * Math.cos(h);
  const b = c * Math.sin(h);
  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;
  const [L, M, S] = [l_ ** 3, m_ ** 3, s_ ** 3];
  const lin: Rgb = [
    4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ];
  return lin.map((v) => Math.min(1, Math.max(0, v))) as Rgb;
}

const toLinear = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);

/** Linear-light sRGB, or null for a value that is not an opaque literal. */
export function parseColour(raw: string): Rgb | null {
  const value = raw.trim().toLowerCase();
  const ok = /^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)(?:deg)?\s*\)$/.exec(value);
  if (ok) {
    const l = Number(ok[1]) / (ok[2] ? 100 : 1);
    return oklchToRgb(l, Number(ok[3]), Number(ok[4]));
  }
  const hex = /^#([0-9a-f]{6})$/.exec(value);
  if (hex) return [0, 2, 4].map((i) => toLinear(parseInt(hex[1].slice(i, i + 2), 16) / 255)) as Rgb;
  return null;
}

const luminance = (rgb: Rgb) => 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
export function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Declarations of the first block whose selector matches exactly (after whitespace normalisation). */
function block(css: string, selector: string): Record<string, string> | null {
  const norm = (s: string) => s.replace(/\s+/g, ' ').trim();
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (norm(m[1]) !== norm(selector)) continue;
    const out: Record<string, string> = {};
    for (const d of m[2].matchAll(/--n-([a-z0-9-]+)\s*:\s*([^;]+);/g)) out[d[1]] = d[2].trim();
    return out;
  }
  return null;
}

const GROUNDS = ['bg', 'bg-2', 'sheet', 'sheet-2'] as const;
const TEXT_ROLES = ['text', 'text-2', 'text-3', 'accent-text', 'emph', 'ok', 'warn', 'bad', 'info', 'cloud'] as const;
const STATUS_ROLES = ['ok', 'warn', 'bad', 'info', 'cloud'] as const;

/** Derived roles (tokens.css): a theme may set them; otherwise they take these defaults. */
export const DERIVED_DEFAULTS: Record<string, string> = {
  emph: 'var(--n-accent-text)',
  'emph-wash': 'var(--n-accent-wash)',
  primary: 'var(--n-accent)',
  'on-primary': 'var(--n-on-accent)',
  'field-bg': 'var(--n-sheet)',
};

/** A role's literal, following var(--n-…) references through the same set of roles. */
function resolve(roles: Record<string, string> | null | undefined, name: string, depth = 0): string {
  const raw = roles?.[name] ?? DERIVED_DEFAULTS[name] ?? '';
  const ref = /^var\(\s*--n-([a-z0-9-]+)\s*\)$/.exec(raw.trim());
  if (ref && depth < 6) return resolve(roles, ref[1], depth + 1);
  return raw;
}

/** OKLab coordinates of the colour Chromium paints for an opaque literal (null otherwise):
 *  the literal goes through parseColour (so an out-of-gamut oklch() is clipped first), then
 *  linear sRGB → OKLab. */
function oklab(raw: string): [number, number, number] | null {
  const rgb = parseColour(raw);
  if (!rgb) return null;
  const [r, g, b] = rgb;
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}
const deltaE = (a: [number, number, number], b: [number, number, number]) =>
  Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

const themeFiles = THEMES.filter((t) => t.family === 'nerva');

describe('theme contract v1', () => {
  it('has one file per Nerva theme in the registry, and no stray files', () => {
    const files = readdirSync(dir).filter((f) => f.endsWith('.css')).map((f) => f.replace(/\.css$/, '')).sort();
    expect(files).toEqual(themeFiles.map((t) => t.id).sort());
  });

  for (const theme of themeFiles) {
    describe(theme.id, () => {
      const path = join(dir, `${theme.id}.css`);
      if (!existsSync(path)) {
        it('has its theme file', () => expect(existsSync(path), `${path} is missing`).toBe(true));
        return;
      }
      const css = strip(readFileSync(path, 'utf8'));
      for (const scheme of theme.schemes) {
        const darkSel = `:is(:root, .n-theme-scope)[data-look="${theme.id}"]`;
        const lightSel = `${darkSel}[data-scheme="light"]`;
        const base = block(css, darkSel);
        const roles = scheme === 'dark' ? base : { ...(base ?? {}), ...(block(css, lightSel) ?? {}) };

        it(`${scheme}: uses the contract selectors and declares every colour role`, () => {
          expect(base, `missing block ${darkSel}`).not.toBeNull();
          if (scheme === 'light') expect(block(css, lightSel), `missing block ${lightSel}`).not.toBeNull();
          const declared = scheme === 'light' ? block(css, lightSel) ?? {} : base ?? {};
          const missing = COLOUR_ROLES.filter((r) => !(r in declared));
          expect(missing, `${theme.id} ${scheme} must declare every colour role in its own block`).toEqual([]);
        });

        it(`${scheme}: text roles reach 4.5:1 on every ground`, () => {
          const failures: string[] = [];
          for (const fg of TEXT_ROLES) for (const bg of GROUNDS) {
            const a = parseColour(resolve(roles, fg));
            const b = parseColour(resolve(roles, bg));
            if (!a || !b) { failures.push(`${fg}/${bg}: not an opaque oklch() or #rrggbb literal`); continue; }
            const ratio = contrast(a, b);
            if (ratio < 4.5) failures.push(`${fg} on ${bg} = ${ratio.toFixed(2)}`);
          }
          expect(failures).toEqual([]);
        });

        it(`${scheme}: on-accent / on-stop / on-primary read on their fills; edges, focus and the stop reach 3:1`, () => {
          const pairs: [string, string, number][] = [
            ['on-accent', 'accent', 4.5], ['on-stop', 'stop', 4.5], ['on-primary', 'primary', 4.5],
            ['rule-field', 'bg', 3], ['rule-field', 'sheet', 3], ['focus', 'bg', 3], ['focus', 'sheet', 3],
            // a field's edge must also show on the quiet ground popovers and the Console are drawn
            // on, and against the field's own fill (WCAG 1.4.11)
            ['rule-field', 'bg-2', 3], ['rule-field', 'field-bg', 3],
            ['stop', 'bg', 3], ['stop', 'sheet', 3], ['primary', 'bg', 3], ['primary', 'sheet', 3],
            ['text', 'accent-wash', 4.5], ['text', 'ok-wash', 4.5], ['text', 'warn-wash', 4.5], ['text', 'bad-wash', 4.5],
            ['text', 'bg-3', 4.5], ['text', 'selection', 4.5], ['text', 'emph-wash', 4.5], ['text', 'field-bg', 4.5],
            ['text-3', 'field-bg', 4.5],
          ];
          const failures: string[] = [];
          for (const [fg, bg, min] of pairs) {
            const a = parseColour(resolve(roles, fg));
            const b = parseColour(resolve(roles, bg));
            if (!a || !b) { failures.push(`${fg}/${bg}: not an opaque literal`); continue; }
            const ratio = contrast(a, b);
            if (ratio < min) failures.push(`${fg} on ${bg} = ${ratio.toFixed(2)} (< ${min})`);
          }
          expect(failures).toEqual([]);
        });

        it(`${scheme}: a selected row's wash shows on the page, the quiet ground and a sheet`, () => {
          // emph-wash marks the current row in menus, the palette and radio groups, which are
          // drawn on bg, bg-2 (popovers, the Console) or a sheet: it must not vanish into any of them.
          const failures: string[] = [];
          const wash = oklab(resolve(roles, 'emph-wash'));
          if (!wash) failures.push('emph-wash: not an opaque literal');
          for (const ground of ['bg', 'bg-2', 'sheet'] as const) {
            const g = oklab(resolve(roles, ground));
            if (wash && g && deltaE(wash, g) < 0.02) failures.push(`emph-wash ≈ ${ground} (ΔE ${deltaE(wash, g).toFixed(3)})`);
          }
          expect(failures).toEqual([]);
        });

        it(`${scheme}: the five status colours stay apart from each other and from the text ink`, () => {
          // Legacy screens still encode status, locality and categories by hue (legends, rings,
          // meters), so a theme may keep its status colours quiet but never collapse them.
          // OKLab distance ≥ 0.05 (about two and a half just-noticeable differences).
          const failures: string[] = [];
          const lab = (r: string) => oklab(resolve(roles, r));
          for (let i = 0; i < STATUS_ROLES.length; i++) {
            const a = lab(STATUS_ROLES[i]);
            if (!a) { failures.push(`${STATUS_ROLES[i]}: not an opaque oklch() or #rrggbb literal`); continue; }
            const t = lab('text');
            if (t && deltaE(a, t) < 0.05) failures.push(`${STATUS_ROLES[i]} ≈ text (ΔE ${deltaE(a, t).toFixed(3)})`);
            for (let j = i + 1; j < STATUS_ROLES.length; j++) {
              const b = lab(STATUS_ROLES[j]);
              if (b && deltaE(a, b) < 0.05) failures.push(`${STATUS_ROLES[i]} ≈ ${STATUS_ROLES[j]} (ΔE ${deltaE(a, b).toFixed(3)})`);
            }
          }
          expect(failures).toEqual([]);
        });
      }
    });
  }
});

/* The register's inner margin (contract §3, 2026-11-25). The final renders after the last gate found
   every register drawn as a card (Atlas, Console, Threshold and Workbench, light and dark; Classic ·
   Obsidian and Graphite) with its title, meta, rows and controls touching its frame: the register drew
   the look's panel treatment and no margin inside it. Now a look that frames its panels (a side border
   wider than 0, or a fill) gives a register its own panel margin, and a look that draws registers with
   rules leaves the role at its default, 0, so nothing moves there. */
describe('the register\'s inner margin (--n-register-pad, contract §3)', () => {
  const source = (path: string) => strip(readFileSync(join(process.cwd(), 'src', ...path.split('/')), 'utf8'));
  const tokens = block(source('theme/tokens.css'), ':is(:root, .n-theme-scope)') ?? {};
  /** The `--n-*` declarations of the first block whose selector list holds `part`. */
  const blockWith = (css: string, part: string): Record<string, string> | null => {
    for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!m[1].replace(/\s+/g, ' ').includes(part)) continue;
      return Object.fromEntries([...m[2].matchAll(/--n-([a-z0-9-]+)\s*:\s*([^;]+);/g)].map((d) => [d[1], d[2].trim()]));
    }
    return null;
  };
  /** Whether a look's panel treatment draws a frame or a fill (its own values, else tokens.css's). */
  const frames = (roles: Record<string, string>) => {
    const border = roles['panel-border'] ?? tokens['panel-border'] ?? '';
    const ground = roles['panel-bg'] ?? tokens['panel-bg'] ?? '';
    return parseFloat(border) > 0 || !/^transparent$/i.test(ground.trim());
  };
  const CARDS = ['atlas', 'console', 'threshold', 'workbench'];
  const RULES = ['ledger', 'briefing', 'presence'];

  it('defaults to 0 in tokens.css, as a length (the kit takes min() of it below 1100px)', () => {
    expect(tokens['register-pad']).toBe('0px');
    // the default looks draw registers with rules, not boxes: no frame, no fill
    expect(frames({})).toBe(false);
  });

  it('is set by every Nerva look that frames its panels, from its own --n-panel-pad, and by no look that draws rules', () => {
    const drawn: Record<'cards' | 'rules', string[]> = { cards: [], rules: [] };
    for (const theme of themeFiles) {
      const css = strip(readFileSync(join(dir, `${theme.id}.css`), 'utf8'));
      const base = block(css, `:is(:root, .n-theme-scope)[data-look="${theme.id}"]`) ?? {};
      const declared = [...css.matchAll(/--n-register-pad\s*:\s*([^;]+);/g)].map((m) => m[1].trim());
      if (frames(base)) {
        drawn.cards.push(theme.id);
        expect(base['register-pad'], `${theme.id} frames its panels: its base block sets the register's margin`).toBe('var(--n-panel-pad)');
        expect(declared, `${theme.id}: one value in every scheme and width`).toEqual(declared.map(() => 'var(--n-panel-pad)'));
      } else {
        drawn.rules.push(theme.id);
        expect(declared, `${theme.id} draws rules: the register keeps the default, 0`).toEqual([]);
      }
    }
    expect(drawn.cards.sort()).toEqual([...CARDS].sort());
    expect(drawn.rules.sort()).toEqual([...RULES].sort());
  });

  /* The review of the round: Classic's register margin was its --pad, 20px in Graphite, 4px a side more than
     Obsidian's; at 1280px in Romanian the docket's foot then wrapped onto a second line and the open entry's
     sign line went 18px further below the docket body's view than in Obsidian. Both looks take one margin. */
  it('is set for Classic once, one margin for both looks (--n-s-4, not Graphite\'s wider --pad), on the page, its .hud-root and a preview, and the Nerva bridge leaves it to the theme files', () => {
    const bridge = source('theme/bridge.css');
    for (const look of ['obsidian', 'graphite']) {
      const classic = blockWith(bridge, `:root[data-look="${look}"] .hud-root`);
      expect(classic, `the Classic block naming ${look}'s .hud-root`).not.toBeNull();
      expect(frames(classic ?? {}), `${look} frames its panels`).toBe(true);
      expect(classic?.['panel-pad']).toBe('var(--pad)');
      expect(classic?.['register-pad'], look).toBe('var(--n-s-4)');
    }
    const classicSelectors = [...bridge.matchAll(/([^{}]+)\{[^{}]*--n-register-pad\s*:/g)].map((m) => m[1].replace(/\s+/g, ' ').trim());
    expect(classicSelectors).toHaveLength(1);
    for (const part of [':root[data-look="obsidian"]', '.n-theme-scope[data-look="obsidian"]', ':root[data-look="graphite"] .hud-root', '.n-theme-scope[data-look="graphite"]']) {
      expect(classicSelectors[0]).toContain(part);
    }
    expect(blockWith(bridge, ':root[data-look="ledger"] .hud-root')?.['register-pad']).toBeUndefined();
  });
});

/* A consequence's term column (contract §3, 2026-11-25). The kit's 74px column (82px from 2200px) was drawn
   for a label voice in sentence case; Classic's (mono capitals, tracked .1em) broke the docket's open-entry
   terms onto two lines there, and at 1280×800 the entry's sign line went below what the docket's body shows
   (22px in English, 49px in Romanian; 12px in Romanian at 1340–1440×900). The role lets a look whose voice
   needs it grow the column; every Nerva look keeps the default, so nothing moves in them. */
describe('a consequence\'s term column (--n-term-max, contract §3)', () => {
  const source = (path: string) => strip(readFileSync(join(process.cwd(), 'src', ...path.split('/')), 'utf8'));
  const tokens = block(source('theme/tokens.css'), ':is(:root, .n-theme-scope)') ?? {};

  it('defaults to 0px in tokens.css, so the column does not grow', () => {
    expect(tokens['term-max']).toBe('0px');
  });

  it('is set by no Nerva look: their label voices keep the column as it was', () => {
    for (const theme of themeFiles) {
      const css = strip(readFileSync(join(dir, `${theme.id}.css`), 'utf8'));
      expect(css, theme.id).not.toMatch(/--n-term-max\s*:/);
    }
  });

  it('is set for Classic once, to its widest term, on the page, its .hud-root and a preview, and the Nerva bridge leaves it alone', () => {
    const bridge = source('theme/bridge.css');
    const set = [...bridge.matchAll(/([^{}]+)\{([^{}]*--n-term-max\s*:[^{}]*)\}/g)];
    expect(set).toHaveLength(1);
    const selectors = set[0][1].replace(/\s+/g, ' ').trim();
    for (const part of [':root[data-look="obsidian"]', ':root[data-look="obsidian"] .hud-root', '.n-theme-scope[data-look="obsidian"]',
      ':root[data-look="graphite"]', ':root[data-look="graphite"] .hud-root', '.n-theme-scope[data-look="graphite"]']) {
      expect(selectors).toContain(part);
    }
    expect(/--n-term-max\s*:\s*([^;]+);/.exec(set[0][2])?.[1].trim()).toBe('max-content');
    // the same block draws Classic's label voice, the reason for it
    expect(set[0][2]).toMatch(/--n-label-case:\s*uppercase;/);
    expect(set[0][2]).toMatch(/--n-label-track:\s*\.1em;/);
    expect(selectors).not.toContain('ledger');
  });
});
