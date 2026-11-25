// @ts-nocheck — reads the stylesheet as source with node:fs (src/ builds against the DOM lib only)
/* home.css draws through roles only (PHASE_B_PLAN.md §1.3), as frame/kit/kit-css.test.ts checks
   for the kit and the frame: no colour literal, no font size but a --n-fs-* step, no hard-coded
   uppercase or tracking, no Phase A primitive or legacy class redefined; and the spread's grid
   follows the Ledger widths (§5.1). */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const css = readFileSync(join(process.cwd(), 'src', 'home', 'home.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const PRIMITIVES = ['n-btn', 'n-seg', 'n-field', 'n-input', 'n-textarea', 'n-link', 'n-kbd', 'n-tag', 'n-chip', 'n-row', 'n-state', 'n-json', 'n-card', 'n-meter'];
const LEGACY = ['topbar', 'rail-btn', 'inputbar', 'transmit', 'msg', 'bubble', 'convo', 'dcard', 'panel', 'badge', 'ticker', 'workzone', 'rail', 'tool-btn', 'scrollcol', 'col'];

describe('home/home.css', () => {
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

  it('lays the spread out at the Ledger widths', () => {
    const flat = css.replace(/\s+/g, ' ');
    expect(flat).toContain('.n-spread--home { grid-template-columns: 396px minmax(0, 1fr) 664px;');
    expect(flat).toMatch(/@media \(min-width: 2200px\) \{[^@]*grid-template-columns: 432px minmax\(0, 1fr\) 712px 404px;/);
    expect(flat).toMatch(/@media \(max-width: 1679px\) \{[^@]*grid-template-columns: minmax\(0, 1fr\) minmax\(500px, 44\.5%\);/);
    expect(flat).toMatch(/@media \(max-width: 1339px\) \{[^@]*grid-template-columns: minmax\(0, 1fr\) minmax\(480px, 43\.5%\);/);
    expect(flat).toMatch(/@media \(max-width: 1099px\) \{[^@]*grid-template-columns: minmax\(0, 1fr\);/);
  });
});
