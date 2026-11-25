// @ts-nocheck — reads the stylesheet as source with node:fs (src/ builds against the DOM lib only)
/* talk.css draws through roles only (PHASE_B_PLAN.md §1.3), as frame/kit/kit-css.test.ts checks
   the kit: no colour literal, no font size but a --n-fs-* step (so nothing under 12px), no
   hard-coded uppercase or tracking, no Phase A primitive or legacy class redefined, and only the
   motion the plan allows (hover and press). */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const css = readFileSync(join(process.cwd(), 'src', 'home', 'talk', 'talk.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const PRIMITIVES = ['n-btn', 'n-seg', 'n-field', 'n-input', 'n-textarea', 'n-link', 'n-kbd', 'n-tag', 'n-chip', 'n-row', 'n-state', 'n-json', 'n-card', 'n-meter'];
const KIT = ['n-mk', 'n-tier', 'n-src', 'n-register', 'n-sec', 'n-total', 'n-consequence', 'n-disclosure', 'n-key'];
const LEGACY = ['topbar', 'rail-btn', 'inputbar', 'transmit', 'msg', 'bubble', 'convo', 'dcard', 'panel', 'badge', 'ticker', 'workzone', 'rail',
  'tool-btn', 'thinking', 'mtag', 'chan', 'field', 'mic', 'vault-trigger', 'office-trigger', 'direct-reply-option', 'blender-composer-option'];

describe('home/talk/talk.css', () => {
  it('holds no colour literal', () => {
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\(/i);
  });

  it('sizes type only from the scale', () => {
    for (const m of css.matchAll(/(?:^|[;{\s])font-size\s*:\s*([^;}]+)/g)) {
      expect(m[1].trim()).toMatch(/^var\(--n-fs-(?:meta|label|ui|own|prose|title|verdict|figure)\)$/);
    }
    for (const m of css.matchAll(/(?:^|[;{\s])font\s*:\s*([^;}]+)/g)) expect(m[1].trim()).toBe('inherit');
    for (const m of css.matchAll(/(?:^|[;{\s])font-family\s*:\s*([^;}]+)/g)) expect(m[1].trim()).toMatch(/^var\(--n-font-(?:ui|label|text|title|display|mono)\)$/);
  });

  it('leaves case and tracking to the label voice', () => {
    expect(css).not.toMatch(/text-transform\s*:\s*uppercase/);
    for (const m of css.matchAll(/letter-spacing\s*:\s*([^;}]+)/g)) {
      expect(m[1].trim()).toMatch(/^(?:var\(--n-(?:label|title)-track\)|normal|inherit|0)$/);
    }
  });

  it('defines no Phase A primitive, no kit block and no legacy class', () => {
    const selectors = [...css.matchAll(/([^{}]+)\{/g)].map((m) => m[1]).filter((s) => !/^\s*@/.test(s));
    for (const name of [...PRIMITIVES, ...KIT, ...LEGACY]) {
      for (const s of selectors) expect(new RegExp(`\\.${name}(?![\\w-])`).test(s), `${name} in ${s.trim()}`).toBe(false);
    }
  });

  it('animates nothing but hover and press, at the plan\'s durations', () => {
    expect(css).not.toMatch(/@keyframes|animation\s*:/);
    for (const m of css.matchAll(/transition\s*:\s*([^;}]+)/g)) expect(m[1]).toMatch(/var\(--n-dur-1\)/);
  });

  it('uses only the shared breakpoints', () => {
    // §1.3's shared widths (the composer uses four of them), plus the no-hover input query
    const allowed = new Set(['min-width: 2200px', 'max-width: 1339px', 'max-width: 1099px', 'max-width: 759px', 'hover: none']);
    for (const m of css.matchAll(/@media\s*\(([^)]+)\)/g)) expect(allowed.has(m[1].trim()), m[1]).toBe(true);
  });
});
