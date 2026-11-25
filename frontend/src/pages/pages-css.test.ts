// @ts-nocheck — reads the stylesheet as source with node:fs (src/ builds against the DOM lib only)
/* pages.css draws through roles only (PHASE_B_PLAN.md §1.3), like the kit's stylesheets
   (frame/kit/kit-css.test.ts): no colour literal, type only from the scale (nothing under 12px),
   no hard-coded case or tracking, and no Phase A primitive or legacy class redefined. */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const css = readFileSync(join(process.cwd(), 'src', 'pages', 'pages.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const PRIMITIVES = ['n-btn', 'n-seg', 'n-field', 'n-input', 'n-textarea', 'n-link', 'n-kbd', 'n-tag', 'n-chip', 'n-row', 'n-state', 'n-json', 'n-card', 'n-meter'];
const LEGACY = ['topbar', 'rail-btn', 'inputbar', 'transmit', 'msg', 'bubble', 'convo', 'dcard', 'panel', 'badge', 'ticker', 'workzone', 'rail', 'tool-btn'];
// blocks another engineer owns (PHASE_B_INTERFACES.md §4)
const OTHERS = ['n-verdict', 'n-causes', 'n-dayband', 'n-schedule', 'n-away', 'n-machine', 'n-docket', 'n-entry', 'n-signline', 'n-transcript', 'n-turn', 'n-working', 'n-steps', 'n-footnote', 'n-composer', 'n-masthead', 'n-areas', 'n-runhead', 'n-signals', 'n-runfoot', 'n-notices', 'n-spread', 'n-areapage', 'n-contents', 'n-toc', 'n-cmd'];

describe('pages.css', () => {
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

  it('defines no Phase A primitive, no legacy class and no block another engineer owns', () => {
    const selectors = [...css.matchAll(/([^{}]+)\{/g)].map((m) => m[1]).filter((s) => !s.trim().startsWith('@'));
    for (const name of [...PRIMITIVES, ...LEGACY, ...OTHERS]) {
      for (const s of selectors) expect(new RegExp(`\.${name}(?![\w-])`).test(s), `${name} in ${s.trim()}`).toBe(false);
    }
  });
});
