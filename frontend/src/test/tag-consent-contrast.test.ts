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

const root = process.cwd();
const styles = readFileSync(join(root, 'src', 'styles.css'), 'utf8');
const panelKit = readFileSync(join(root, 'src', 'panel-kit.tsx'), 'utf8');

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

function token(name: string): string {
  const m = new RegExp(`--${name}\\s*:\\s*([^;]+);`).exec(styles);
  if (!m) throw new Error(`token --${name} not found in styles.css`);
  return m[1].trim();
}

function hex(h: string): number[] {
  const m = /#([0-9a-f]{6})/i.exec(h);
  if (!m) throw new Error(`not a hex colour: ${h}`);
  return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
}

describe('the <Tag> chip carries consent copy, so its colour is a contract', () => {
  const void_ = hex(token('void'));

  it('uses --ink-2, the token that clears AA over --void', () => {
    // the default is what 92 uncoloured call sites inherit; the 83 that pass `c` opt out
    expect(panelKit).toContain("color: c || 'var(--ink-2)'");
    expect(panelKit).not.toContain("color: c || 'var(--ink-3)'");
  });

  it('--ink-2 over --void meets AA for normal text', () => {
    const r = ratio(composite(token('ink-2'), void_), void_);
    expect(r, `--ink-2 on --void is ${r.toFixed(2)}:1, AA normal text needs 4.5:1`)
      .toBeGreaterThanOrEqual(4.5);
  });

  it('--ink-3 does NOT, which is why the default moved off it', () => {
    // Guards the reasoning, not just the outcome: if the palette is ever retuned so
    // --ink-3 clears AA, this fails and the move can be revisited on evidence.
    const r = ratio(composite(token('ink-3'), void_), void_);
    expect(r, `--ink-3 on --void is now ${r.toFixed(2)}:1 — if that clears 4.5:1 the premise changed`)
      .toBeLessThan(4.5);
  });
});
