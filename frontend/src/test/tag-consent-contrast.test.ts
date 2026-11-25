// @ts-nocheck
/* The shared <Tag> chip carries consent copy, so its default colour is a contrast
   contract, not a style preference.

   An axe sweep of the first-run gate found 17 color-contrast failures at 2.82-2.88:1
   against AA's 4.5:1, and 14 of them were untinted <Tag> chips rendering the privacy
   rows: "connected account · cloud model may receive context", "external websites",
   "read-only". That is the text telling a new user what leaves their machine.

   Why this is a unit test and not an e2e scan. The failing surface is `FirstRunGate`,
   a modal gated on both backend state (`shouldShowFirstRun`: model not ready or wizard
   incomplete) and a viewer flag (localStorage `hud.firstrun.dismissed`). It is not
   deterministically reachable from a spec — measured, `a11y-modes.spec.ts` never sees
   it (`.pal-scrim` count 0 across all 40 of its scans), and an e2e pin that waits for
   it fails on a run where it does not open. The token contract IS deterministic, so
   that is what gets pinned: the ratio is recomputed from styles.css rather than
   hard-coded, so lightening or darkening the palette re-runs the check. */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { toneOf } from '../panel-kit';

const root = process.cwd();
// Comments first: a `--ink-3:` written inside a /* ... */ note is prose, not a definition,
// and matching it makes every ratio below read a sentence as a colour. (Found by this test.)
const styles = readFileSync(join(root, 'src', 'styles.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const panelKit = readFileSync(join(root, 'src', 'panel-kit.tsx'), 'utf8');
const kitCss = readFileSync(join(root, 'src', 'theme', 'kit.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

/** WCAG 2.x relative luminance of an sRGB triple. */
function luminance([r, g, b]: number[]): number {
  const f = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function ratio(fg: number[], bg: number[]): number {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

/** `rgba(r,g,b,a)` composited over an opaque backdrop — what the eye and axe both see. */
function composite(rgba: string, bg: number[]): number[] {
  const m = /rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)/.exec(rgba);
  if (!m) throw new Error(`not an rgb(a) colour: ${rgba}`);
  const [r, g, b] = [+m[1], +m[2], +m[3]];
  const a = m[4] === undefined ? 1 : +m[4];
  return [r, g, b].map((c, i) => c * a + bg[i] * (1 - a));
}

/** Every definition of a token, in source order — styles.css redefines the palette per
    `[data-look=...]`, and a check that reads only the first one guards a single theme. */
function tokens(name: string): string[] {
  const all = [...styles.matchAll(new RegExp(`--${name}\\s*:\\s*([^;]+);`, 'g'))].map((m) => m[1].trim());
  if (!all.length) throw new Error(`token --${name} not found in styles.css`);
  return all;
}

function hex(h: string): number[] {
  const m = /#([0-9a-f]{6})/i.exec(h);
  if (!m) throw new Error(`not a hex colour: ${h}`);
  return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
}

describe('the <Tag> chip carries consent copy, so its colour is a contract', () => {
  // Both backdrops the chips are painted on: the app ground and the modal surface.
  const grounds = [...tokens('void'), ...tokens('void-2')].map(hex);
  const inks2 = tokens('ink-2');
  const inks3 = tokens('ink-3');

  it('defaults to the readable secondary ink, never the decorative third one', () => {
    // the default is what the 203 uncoloured call sites inherit; the 199 that pass `c` opt out.
    // The default is the theme role --n-text-2: theme-contrast.test.ts holds every Nerva theme
    // to 4.5:1 with it on every ground, and in Classic bridge.css derives it from --ink-2
    // (contract §6), whose ratio on every HUD v2 ground is checked below.
    expect(panelKit).toContain("color: c || 'var(--n-text-2)'");
    for (const decorative of ['var(--ink-3)', 'var(--n-text-3)', 'var(--ink-4)']) {
      expect(panelKit).not.toContain(`color: c || '${decorative}'`);
    }
    // kit.css draws the chip; its own text colour (for markup that uses the class without the
    // component) is the same ink, and no tag rule colours text with the third ink.
    const tagRule = /(?:^|\})\s*\.n-tag\s*\{([^}]*)\}/.exec(kitCss);
    expect(tagRule, '.n-tag rule not found in theme/kit.css').not.toBeNull();
    expect(tagRule![1]).toMatch(/(?:^|;)\s*color:\s*var\(--n-text-2\)/);
    const tagRules = [...kitCss.matchAll(/([^{}]*\.n-tag[^{}]*)\{([^}]*)\}/g)];
    for (const [, selector, body] of tagRules) {
      expect(body, `${selector.trim()} must not colour tag text with the third ink`).not.toMatch(/(?:^|;)\s*color:\s*var\(--(?:n-text-3|ink-3)\)/);
      expect(body, `${selector.trim()} must not colour tag text with the accent fill role`).not.toMatch(/(?:^|;)\s*color:\s*var\(--(?:n-)?accent\)/);
    }
    // On the accent wash the text is the accent *text* role. Until 2026-11-23 bridge.css turned
    // a caller's legacy --accent into the accent fill role, which read at 1.2-3.3:1 on that wash
    // in five light schemes; it now maps it to the emphasis ink (contract §6), but a caller's
    // colour is still inline, so the theme rule stays !important to keep the wash and its text
    // one pair whatever the caller passes.
    const accentWash = tagRules.find(([, selector, body]) => /\.n-tag--accent/.test(selector) && /background:\s*var\(--n-accent-wash\)/.test(body));
    expect(accentWash, 'the .n-tag--accent wash rule in theme/kit.css').toBeTruthy();
    expect(accentWash![2]).toMatch(/(?:^|;)\s*color:\s*var\(--n-accent-text\)\s*!important/);
  });

  it('reads a legacy accent tint as emphasis, never as the owner\'s accent (contract §6, 2026-11-23)', () => {
    // bridge.css maps --accent and --accent-light to --n-emph: in Ledger that is the ink, and
    // the vermilion accent is spent only on the owner's hand. A tag a caller tinted with the
    // legacy accent ('configured', 'pinned', a space name) is a highlighted word, so it takes
    // the emphasis tone; only the theme's own accent roles take the accent tone and its wash.
    for (const c of ['var(--accent)', 'var(--accent-light)', 'var(--n-emph)']) expect(toneOf(c), c).toBe('emph');
    for (const c of ['var(--n-accent)', 'var(--n-accent-text)']) expect(toneOf(c), c).toBe('accent');
    // a wash, dim or glow variant is drawn in its own colour, so it stays a neutral tag
    for (const c of ['var(--accent-faint)', 'var(--accent-dim)', 'var(--accent-glow)', 'var(--n-emph-wash)', 'var(--n-accent-wash)']) {
      expect(toneOf(c), c).toBe('neutral');
    }
    // The emphasis tag is the emphasis ink on no wash: --n-emph is held to 4.5:1 on every ground
    // (theme-contrast.test.ts), and no wash role is held to anything against it. The caller's
    // colour is inline, so in a Nerva theme the rule replaces it with !important.
    const emphRules = [...kitCss.matchAll(/([^{}]*\.n-tag--emph[^{}]*)\{([^}]*)\}/g)];
    const nerva = emphRules.find(([, , body]) => /!important/.test(body));
    expect(nerva, 'the Nerva .n-tag--emph rule in theme/kit.css').toBeTruthy();
    expect(nerva![2]).toMatch(/(?:^|;)\s*color:\s*var\(--n-emph\)\s*!important/);
    for (const [, selector, body] of emphRules) {
      expect(body, `${selector.trim()} must not put the emphasis ink on a wash`).not.toMatch(/background/);
    }
  });

  it('--ink-2 meets AA for normal text in every palette styles.css defines', () => {
    // styles.css defines the palette more than once (`[data-look="graphite"]`); a check
    // that read only the first definition would leave the other themes unguarded.
    expect(inks2.length, 'expected at least one --ink-2 definition').toBeGreaterThan(0);
    for (const ink of inks2) {
      for (const ground of grounds) {
        const r = ratio(composite(ink, ground), ground);
        expect(r, `--ink-2 "${ink}" on ${JSON.stringify(ground)} is ${r.toFixed(2)}:1, AA needs 4.5:1`)
          .toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('--ink-3 does NOT, which is why the default moved off it', () => {
    // Guards the reasoning, not just the outcome: if the palette is ever retuned so
    // --ink-3 clears AA, this fails and the move can be revisited on evidence.
    for (const ink of inks3) {
      for (const ground of grounds) {
        const r = ratio(composite(ink, ground), ground);
        expect(r, `--ink-3 "${ink}" on ${JSON.stringify(ground)} is now ${r.toFixed(2)}:1 — if that clears 4.5:1 the premise changed`)
          .toBeLessThan(4.5);
      }
    }
  });

  it('the command palette chrome is off --ink-4 — it was the worst ratio in the HUD', () => {
    // Measured with axe on the open overlay: .pal-group and .pal-foot at 1.59:1, the
    // keyboard hints telling you how to leave it. --ink-4 is a background/border token.
    for (const sel of ['.pal-group', '.pal-foot']) {
      const rule = new RegExp(`\\${sel}\\s*\\{[^}]*\\}`).exec(styles);
      expect(rule, `${sel} rule not found`).not.toBeNull();
      expect(rule![0], `${sel} must not colour text with --ink-4`).not.toMatch(/color:var\(--ink-4\)/);
    }
  });
});
