// @ts-nocheck
/* The kit's class names are an interface (theme/CONTRACT.md §8b): Phase B builds on them and
   does not redefine them, so this pins that each one exists in theme/kit.css and is drawn
   from the role the contract names for it. kit.css is read as source, comments stripped;
   jsdom does not apply stylesheets, so a rendered element could not tell us this. */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { codeS, inpS, mono, note, taS } from '../panel-kit';

const kitCss = readFileSync(join(process.cwd(), 'src', 'theme', 'kit.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const rules = [...kitCss.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
  selector: m[1].replace(/\s+/g, ' ').trim(),
  body: m[2],
}));
/** The value of a declaration in a rule body (null when the rule does not set it). */
const decl = (body: string, prop: string): string | null => {
  const m = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`).exec(body);
  return m ? m[1].trim() : null;
};
/** Rules with a selector that names the class (the whole class name, not a longer one). */
const rulesFor = (cls: string) => rules.filter((r) => new RegExp(`\\.${cls}(?![\\w-])`).test(r.selector));
/** A selector list split at its top-level commas (not the ones inside :is(), :not(), :where()). */
function selectorsOf(list: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = '';
  for (const ch of list) {
    if (ch === '(') depth++;
    if (ch === ')') depth--;
    if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}
/** The rule whose selector list opens with exactly this selector. */
const ruleOpening = (first: string) => rules.find((r) => selectorsOf(r.selector)[0] === first);
const NERVA = ':is(:root, .n-theme-scope):not([data-look="obsidian"], [data-look="graphite"])';

describe('the kit class names Phase B builds on (contract §8b)', () => {
  it('defines every primitive the contract lists', () => {
    const names = [
      'n-btn', 'n-btn--sm', 'n-btn--primary', 'n-btn--ink', 'n-btn--accent', 'n-btn--quiet', 'n-btn--bare', 'n-btn--danger',
      'n-seg', 'n-field', 'n-input', 'n-textarea', 'n-field--code', 'n-link', 'n-kbd',
      'n-tag', 'n-chip', 'n-row', 'n-state', 'n-json', 'n-card', 'n-meter',
    ];
    const missing = names.filter((n) => rulesFor(n).length === 0);
    expect(missing).toEqual([]);
  });

  it('draws buttons in the control shape, and each fill from the role the contract names', () => {
    const base = ruleOpening('.n-btn:not(.tool-btn)');
    expect(base, 'the base .n-btn rule').toBeTruthy();
    expect(decl(base.body, 'border-radius')).toBe('var(--n-r-control)');
    for (const r of rules.filter((x) => /\.n-btn/.test(x.selector))) {
      const radius = decl(r.body, 'border-radius');
      if (radius) expect(radius, r.selector).toBe('var(--n-r-control)');
    }
    const fills = {
      'n-btn--primary': ['var(--n-primary)', 'var(--n-on-primary)'],
      'n-btn--ink': ['var(--n-text)', 'var(--n-bg)'],
      'n-btn--accent': ['var(--n-accent)', 'var(--n-on-accent)'],
      'n-btn--danger': ['var(--n-stop)', 'var(--n-on-stop)'],
    };
    for (const [cls, [fill, ink]] of Object.entries(fills)) {
      const rule = ruleOpening(`.${cls}:not(.tool-btn)`);
      expect(rule, `the .${cls} rule`).toBeTruthy();
      expect(decl(rule.body, 'background'), cls).toBe(fill);
      expect(decl(rule.body, 'border-color'), cls).toBe(fill);
      expect(decl(rule.body, 'color'), cls).toBe(ink);
      // both tiers: in a Nerva page the NERVA base rule outranks a standalone variant
      expect(rule.selector, `${cls} needs its Nerva twin`).toContain(`${NERVA} .${cls}`);
      // a filled button keeps its fill under the pointer and when pressed
      expect(rule.selector, `${cls} keeps its fill`).toContain(`.${cls}:not(.tool-btn):is(:hover, :active, [aria-pressed="true"])`);
    }
    // a primary action that is not a signature is never the accent (in Ledger, the owner's hand)
    expect(ruleOpening('.n-btn--primary:not(.tool-btn)').body).not.toMatch(/--n-accent/);
  });

  it('frames the quiet button with the quiet edge and leaves the bare one frameless, in the emphasis ink', () => {
    const quiet = ruleOpening('.n-btn--quiet:not(.tool-btn)');
    expect(decl(quiet.body, 'border-color')).toBe('var(--n-rule-2)');
    expect(decl(quiet.body, 'color')).toBe('var(--n-text-2)');
    const bare = ruleOpening('.n-btn--bare:not(.tool-btn)');
    expect(decl(bare.body, 'border-color')).toBe('transparent');
    expect(decl(bare.body, 'background')).toBe('transparent');
    expect(decl(bare.body, 'color')).toBe('var(--n-emph)');
    // its focus is the ring every control has, and no rule takes the ring away
    const focus = ruleOpening('.n-btn:not(.tool-btn):focus-visible');
    expect(decl(focus.body, 'outline')).toBe('2px solid var(--n-focus)');
    expect(decl(focus.body, 'outline-offset')).toBe('2px');
    for (const r of rulesFor('n-btn--bare')) expect(decl(r.body, 'outline'), r.selector).toBeNull();
  });

  it('draws the segmented control as joined buttons whose choice is aria-checked, in the emphasis treatment', () => {
    expect(decl(ruleOpening('.n-seg').body, 'display')).toBe('inline-flex');
    const child = ruleOpening('.n-seg > *');
    expect(decl(child.body, 'border-radius')).toBe('0');
    expect(decl(ruleOpening('.n-seg > :first-child').body, 'border-start-start-radius')).toBe('var(--n-r-control)');
    expect(decl(ruleOpening('.n-seg > :last-child').body, 'border-end-end-radius')).toBe('var(--n-r-control)');
    const checked = ruleOpening('.n-seg > :is([aria-checked="true"], [aria-pressed="true"])');
    expect(checked, 'the aria-checked rule').toBeTruthy();
    expect(decl(checked.body, 'background')).toBe('var(--n-emph-wash)');
    // the word stays in the ink the contract holds to 4.5:1 on the emphasis wash, and the
    // choice carries a weight and a bar as well as the wash
    expect(decl(checked.body, 'color')).toBe('var(--n-text)');
    expect(decl(checked.body, 'font-weight')).toBe('var(--n-w-semi)');
    expect(decl(checked.body, 'box-shadow')).toBe('inset 0 -2px 0 var(--n-emph)');
    expect(decl(ruleOpening('.n-seg > :focus-visible').body, 'outline')).toBe('2px solid var(--n-focus)');
  });

  it('fills every field with the field role, and n-input / n-textarea are n-field', () => {
    const field = ruleOpening(':is(.n-field, .n-input, .n-textarea)');
    expect(field, 'the shared field rule').toBeTruthy();
    expect(decl(field.body, 'background')).toBe('var(--n-field-bg)');
    for (const r of rulesFor('n-field')) {
      if (/\.n-field--code/.test(r.selector)) continue;
      expect(r.selector, 'an n-field rule that its aliases do not share').toMatch(/\.n-input/);
      expect(r.selector, 'an n-field rule that its aliases do not share').toMatch(/\.n-textarea/);
      expect(r.body, r.selector).not.toMatch(/background:\s*var\(--n-sheet\)/);
    }
    // the inline objects >300 call sites spread are the same fill
    for (const [name, style] of Object.entries({ inpS, taS, codeS })) expect(style.background, name).toBe('var(--n-field-bg)');
  });

  it('draws an in-app link in the emphasis ink, underlined under the pointer and the keyboard, visited the same', () => {
    const link = ruleOpening('.n-link');
    expect(decl(link.body, 'color')).toBe('var(--n-emph)');
    expect(decl(link.body, 'text-decoration-line')).toBe('underline');
    expect(decl(ruleOpening('.n-link:visited').body, 'color')).toBe('var(--n-emph)');
    expect(decl(ruleOpening('.n-link:is(:hover, :focus-visible)').body, 'text-decoration-color')).toBe('currentColor');
    expect(decl(ruleOpening('.n-link:focus-visible').body, 'outline')).toBe('2px solid var(--n-focus)');
  });

  it('draws a key cap in the label face on the quiet fill, in a hairline frame', () => {
    const kbd = ruleOpening('.n-kbd');
    expect(decl(kbd.body, 'font-family')).toBe('var(--n-font-label)');
    expect(decl(kbd.body, 'font-size')).toMatch(/^var\(--n-fs-(?:meta|label)\)$/);
    expect(decl(kbd.body, 'border')).toBe('var(--n-hair) solid var(--n-rule-2)');
    expect(decl(kbd.body, 'border-radius')).toBe('var(--n-r-1)');
    expect(decl(kbd.body, 'background')).toBe('var(--n-bg-2)');
  });

  it('sets figures that line up in a column in tabular numerals', () => {
    for (const first of ['.n-row', '.n-meter__value', '.n-tag']) {
      const r = ruleOpening(first);
      expect(r, first).toBeTruthy();
      expect(decl(r.body, 'font-variant-numeric'), first).toMatch(/\btabular-nums\b/);
    }
    const sub = rules.find((r) => /\.n-card__sub/.test(r.selector) && decl(r.body, 'font-variant-numeric'));
    expect(decl(sub.body, 'font-variant-numeric')).toMatch(/\btabular-nums\b/);
  });

  it('holds no colour literal and nothing below the 12px step', () => {
    // colours come from roles; a literal here would not follow the theme
    expect(kitCss).not.toMatch(/#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\(/i);
    const sizes = [...kitCss.matchAll(/(?:^|[;{\s])font-size\s*:\s*([^;}]+)/g)].map((m) => m[1].trim());
    expect(sizes.length).toBeGreaterThan(0);
    for (const s of sizes) expect(s).toMatch(/^var\(--n-fs-(?:meta|label|ui|own|prose|title|verdict|figure)\)$/);
  });

  it('keeps mono for identifiers and note for words (contract §5)', () => {
    expect(mono.fontFamily).toBe('var(--n-font-mono)');
    // note is the label step in the interface face: it inherits the UI face (or names it), never mono
    expect(note.fontFamily ?? 'var(--n-font-ui)').toBe('var(--n-font-ui)');
    expect(note.fontSize).toBe('var(--n-fs-label)');
  });
});
