// @ts-nocheck — reads the stylesheets as source with node:fs (src/ builds against the DOM lib only)
/* The navigation stylesheets draw through roles only (PHASE_B_PLAN.md §1.3): no colour literal,
   no font size but a --n-fs-* step, no hard-coded uppercase or tracking, and no Phase A
   primitive or legacy class redefined. Same checks as frame/kit/kit-css.test.ts. */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const read = (...path) => readFileSync(join(process.cwd(), 'src', ...path), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const FILES = { 'nav/sheet.css': read('nav', 'sheet.css'), 'nav/contents.css': read('nav', 'contents.css') };
const PRIMITIVES = ['n-btn', 'n-seg', 'n-field', 'n-input', 'n-textarea', 'n-link', 'n-kbd', 'n-tag', 'n-chip', 'n-row', 'n-state', 'n-json', 'n-card', 'n-meter'];
const LEGACY = ['topbar', 'rail-btn', 'inputbar', 'transmit', 'msg', 'bubble', 'convo', 'dcard', 'panel', 'badge', 'ticker', 'workzone', 'rail', 'tool-btn', 'pal', 'pal-scrim', 'pal-item'];

describe.each(Object.entries(FILES))('%s', (_name, css) => {
  it('holds no colour literal', () => {
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\(/i);
  });
  it('sizes type only from the scale', () => {
    for (const m of css.matchAll(/(?:^|[;{\s])font-size\s*:\s*([^;}]+)/g)) {
      expect(m[1].trim()).toMatch(/^var\(--n-fs-(?:meta|label|ui|own|prose|title|verdict|figure)\)$/);
    }
    for (const m of css.matchAll(/(?:^|[;{\s])font\s*:\s*([^;}]+)/g)) expect(m[1].trim()).toBe('inherit');
  });
  it('leaves case and tracking to the label voice', () => {
    expect(css).not.toMatch(/text-transform\s*:\s*uppercase/);
    for (const m of css.matchAll(/letter-spacing\s*:\s*([^;}]+)/g)) {
      expect(m[1].trim()).toMatch(/^(?:var\(--n-(?:label|title)-track\)|normal|inherit|0)$/);
    }
  });
  it('defines no Phase A primitive and no legacy class', () => {
    const selectors = [...css.matchAll(/([^{}]+)\{/g)].map((m) => m[1]);
    for (const name of [...PRIMITIVES, ...LEGACY]) {
      for (const s of selectors) expect(new RegExp(`\\.${name}(?![\\w-])`).test(s), `${name} in ${s.trim()}`).toBe(false);
    }
  });
  it('uses only roles and tokens that exist', () => {
    const tokens = readFileSync(join(process.cwd(), 'src', 'theme', 'tokens.css'), 'utf8');
    for (const m of css.matchAll(/var\((--n-[a-z0-9-]+)/g)) expect(tokens.includes(`${m[1]}:`), m[1]).toBe(true);
  });
});
