// @ts-nocheck — reads the stylesheet as source with node:fs (src/ builds against the DOM lib only)
/* docket.css draws through roles only (PHASE_B_PLAN.md §1.3), as frame/kit/kit-css.test.ts checks
   the kit: no colour literal, no font size but a --n-fs-* step (so nothing under 12px), no
   hard-coded uppercase or tracking, no Phase A primitive or legacy class (re)defined, and only
   the blocks the docket owns (n-docket, n-entry, n-signline) — plus the kit's mark inside them. */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const css = readFileSync(join(process.cwd(), 'src', 'docket', 'docket.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const PRIMITIVES = ['n-btn', 'n-seg', 'n-field', 'n-input', 'n-textarea', 'n-link', 'n-kbd', 'n-tag', 'n-chip', 'n-row', 'n-state', 'n-json', 'n-card', 'n-meter'];
const LEGACY = ['topbar', 'rail-btn', 'inputbar', 'transmit', 'msg', 'bubble', 'convo', 'dcard', 'panel', 'badge', 'ticker', 'workzone', 'rail', 'tool-btn'];
const selectors = [...css.matchAll(/([^{}]+)\{/g)].map((m) => m[1].trim()).filter((s) => !s.startsWith('@'));

describe('docket.css', () => {
  it('holds no colour literal', () => {
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\(/i);
  });

  it('sizes type only from the scale', () => {
    const sizes = [...css.matchAll(/(?:^|[;{\s])font-size\s*:\s*([^;}]+)/g)].map((m) => m[1].trim());
    expect(sizes.length).toBeGreaterThan(10);
    for (const size of sizes) expect(size).toMatch(/^var\(--n-fs-(?:meta|label|ui|own|prose|title|verdict|figure)\)$/);
    for (const m of css.matchAll(/(?:^|[;{\s])font\s*:\s*([^;}]+)/g)) expect(m[1].trim()).toBe('inherit');
  });

  it('leaves case and tracking to the label voice', () => {
    expect(css).not.toMatch(/text-transform\s*:\s*uppercase/);
    for (const m of css.matchAll(/letter-spacing\s*:\s*([^;}]+)/g)) {
      expect(m[1].trim()).toMatch(/^(?:var\(--n-(?:label|title)-track\)|normal|inherit|0)$/);
    }
  });

  it('defines no Phase A primitive and no legacy class', () => {
    for (const name of [...PRIMITIVES, ...LEGACY]) {
      for (const s of selectors) expect(new RegExp(`\\.${name}(?![\\w-])`).test(s), `${name} in ${s}`).toBe(false);
    }
  });

  it('styles only its own blocks (and the kit\'s mark inside them)', () => {
    for (const s of selectors) {
      for (const m of s.matchAll(/\.([a-z][\w-]*)/g)) {
        expect(/^n-(?:docket|entry|signline)(?:__[\w-]+|--[\w-]+)?$|^n-mk$/.test(m[1]), `${m[1]} in ${s}`).toBe(true);
      }
    }
  });

  /* 2026-11-25: in Classic, its label voice (mono capitals, tracked .1em) broke the open entry's terms ("IF
     YOU SIGN", "CA SĂ ANULEZI") onto two lines in the kit's 74px column, each row two lines tall, and at
     1280×800 the sign line went below what the docket's body shows (22px in English, 49px in Romanian). */
  it('keeps the open entry\'s terms on one line in every look: its consequence opts in to the look\'s term column', () => {
    const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ selector: m[1].trim(), body: m[2].trim() }));
    const optIn = rules.filter((r) => /--consequence-term-max\s*:/.test(r.body));
    expect(optIn).toEqual([{ selector: '.n-entry__consequence', body: '--consequence-term-max: var(--n-term-max, 0px);' }]);
    // the docket sets no width of its own: the kit's column (74px, 82px from 2200px) and the look's role decide
    expect(css).not.toMatch(/\.n-entry__consequence[^{]*\{[^}]*grid-template-columns/);
  });

  it('spends the accent only on the owner\'s hand: the live figure, the signature line and the confirmation\'s title', () => {
    const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ selector: m[1].trim(), body: m[2] }));
    const accented = rules.filter((r) => /var\(--n-accent(?:-text)?\)/.test(r.body)).map((r) => r.selector);
    expect(accented.length).toBeGreaterThan(0);
    for (const s of accented) expect(s, s).toMatch(/n-docket__figure\[data-figure-state="live"\]|n-signline|n-entry__confirm-title/);
  });
});
