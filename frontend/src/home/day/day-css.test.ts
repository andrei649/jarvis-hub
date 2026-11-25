// @ts-nocheck — reads the stylesheet and sources with node:fs (src/ builds against the DOM lib only)
/* The day's stylesheet draws through roles only (PHASE_B_PLAN.md §1.3), as frame/kit/kit-css.test.ts
   checks for the kit: no colour literal, no font size but a --n-fs-* step (so nothing under 12px),
   no hard-coded uppercase or tracking, no Phase A primitive or legacy class defined here. And no
   module of the day or the signals carries a colour literal or a pixel font size of its own. */
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const strip = (text) => text.replace(/\/\*[\s\S]*?\*\//g, '');
const read = (...path) => strip(readFileSync(join(process.cwd(), 'src', ...path), 'utf8'));
const css = read('home', 'day', 'day.css');
const PRIMITIVES = ['n-btn', 'n-seg', 'n-field', 'n-input', 'n-textarea', 'n-link', 'n-kbd', 'n-tag', 'n-chip', 'n-row', 'n-state', 'n-json', 'n-card', 'n-meter'];
const LEGACY = ['topbar', 'rail-btn', 'inputbar', 'transmit', 'msg', 'bubble', 'convo', 'dcard', 'panel', 'badge', 'ticker', 'workzone', 'rail', 'tool-btn'];

describe('home/day/day.css', () => {
  it('holds no colour literal', () => {
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\(/i);
  });
  it('sizes type only from the scale', () => {
    const sizes = [...css.matchAll(/(?:^|[;{\s])font-size\s*:\s*([^;}]+)/g)];
    expect(sizes.length).toBeGreaterThan(5);
    for (const m of sizes) expect(m[1].trim()).toMatch(/^var\(--n-fs-(?:meta|label|ui|own|prose|title|verdict|figure)\)$/);
    for (const m of css.matchAll(/(?:^|[;{\s])font\s*:\s*([^;}]+)/g)) expect(m[1].trim()).toBe('inherit');
  });
  it('leaves case and tracking to the label voice', () => {
    expect(css).not.toMatch(/text-transform\s*:\s*uppercase/);
    for (const m of css.matchAll(/letter-spacing\s*:\s*([^;}]+)/g)) expect(m[1].trim()).toMatch(/^(?:var\(--n-(?:label|title)-track\)|normal|inherit|0)$/);
  });
  it('defines no Phase A primitive and no legacy class', () => {
    const selectors = [...css.matchAll(/([^{}]+)\{/g)].map((m) => m[1]);
    for (const name of [...PRIMITIVES, ...LEGACY]) {
      for (const s of selectors) expect(new RegExp(`\\.${name}(?![\\w-])`).test(s), `${name} in ${s.trim()}`).toBe(false);
    }
  });
  it('owns only the day\'s blocks', () => {
    const own = new Set(['n-day', 'n-verdict', 'n-causes', 'n-machine', 'n-schedule', 'n-away', 'n-dayband']);
    const names = new Set([...css.matchAll(/\.(n-[a-z]+)(?:__[a-z]+)?/g)].map((m) => m[1]));
    // the day's own blocks, plus the kit classes it only sits beside (n-mk, n-disclosure)
    const foreign = [...names].filter((n) => !own.has(n) && !['n-mk', 'n-disclosure'].includes(n));
    expect(foreign).toEqual([]);
  });
});

describe('the day and signal modules', () => {
  const dirs = [['home', 'day'], ['signals']];
  const files = dirs.flatMap((d) => readdirSync(join(process.cwd(), 'src', ...d)).filter((f) => /\.(ts|tsx)$/.test(f) && !/\.test\./.test(f) && f !== 'test-support.ts').map((f) => [...d, f]));
  it.each(files.map((f) => [f.join('/'), f]))('%s has no colour literal and no pixel font size', (_name, path) => {
    const source = read(...path).replace(/'[^'\n]*'|"[^"\n]*"|`[^`\n]*`/g, (m) => (/#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|oklch)\(/i.test(m) ? m : ''));
    expect(source).not.toMatch(/#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|oklch)\(/i);
    expect(readFileSync(join(process.cwd(), 'src', ...path), 'utf8')).not.toMatch(/fontSize\s*:\s*\d/);
  });
  it('the day imports no legacy styles', () => {
    for (const f of files.filter((f) => f[0] === 'home')) expect(readFileSync(join(process.cwd(), 'src', ...f), 'utf8'), f.join('/')).not.toMatch(/styles\.css/);
  });
});
