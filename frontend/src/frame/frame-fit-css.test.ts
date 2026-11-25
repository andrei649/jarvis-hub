// @ts-nocheck — reads the stylesheet as source with node:fs (src/ builds against the DOM lib only)
/* The fit steps of the masthead (Masthead.tsx FIT_STEPS) and of the running head (RunningHead.tsx
   RUNHEAD_FIT_STEPS) are drawn by frame.css, and only from 1100px, where each row is one line: a
   step the walk can take must change something on screen, or the walk would take it for nothing
   and go on to a costlier one. Both rows measure themselves right after writing a step, so neither
   may transition (calm motion gives every element a 0.01ms transition: a step would be measured a
   frame late). The running head's items are never narrower than what they draw, whatever a
   measurement says; its marks below 760px, and the running foot's folding there, are frame.css's
   too. */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { FIT_STEPS } from './Masthead';
import { RUNHEAD_FIT_STEPS } from './RunningHead';

const CSS = readFileSync(join(process.cwd(), 'src', 'frame', 'frame.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

/** Every block opened by exactly `prelude` (an @media query), whole. */
function blocks(css, prelude) {
  const found = [];
  for (let at = css.indexOf(prelude); at >= 0; at = css.indexOf(prelude, at + prelude.length)) {
    if (css.slice(at + prelude.length).trimStart()[0] !== '{') continue;
    let depth = 0;
    for (let i = css.indexOf('{', at); i < css.length; i += 1) {
      if (css[i] === '{') depth += 1;
      else if (css[i] === '}' && --depth === 0) { found.push(css.slice(at, i + 1)); break; }
    }
  }
  return found;
}
const ONE_LINE = blocks(CSS, '@media (min-width: 1100px)');
const WIDE = ONE_LINE.join('\n');
const NARROW = blocks(CSS, '@media (max-width: 759px)').join('\n');
/** Below 1100px: the one fold a held approval mode keeps (RunningHead.tsx writes "mode" there only
 *  while its looser choice waits for the second step). */
const HELD = blocks(CSS, '@media (max-width: 1099px)').filter((block) => block.includes('data-fit'));

describe('frame.css — the fit steps', () => {
  it('draws every masthead step, and only from 1100px', () => {
    for (const step of FIT_STEPS) expect(WIDE, `no rule for the masthead step "${step}"`).toContain(`.n-masthead[data-fit~="${step}"]`);
    // Find's words give way at their own steps: no attribute of their own any more
    expect(CSS).not.toMatch(/data-find/);
  });

  it('draws every running-head step, and only from 1100px', () => {
    for (const step of RUNHEAD_FIT_STEPS) {
      expect(WIDE, `no rule for the running-head step "${step}"`).toMatch(new RegExp(`\\.n-runhead(--full)?\\[data-fit~="${step}"\\]`));
    }
    // nothing outside the one-line blocks reads a fit step, but the held fold below 1100px, which
    // reads the "mode" step alone
    let outside = CSS;
    for (const block of [...ONE_LINE, ...HELD]) outside = outside.replace(block, '');
    expect(outside).not.toMatch(/data-fit/);
    expect(HELD).toHaveLength(1);
    expect([...HELD[0].matchAll(/data-fit~="([a-z]+)"/g)].map((m) => m[1]).every((step) => step === 'mode')).toBe(true);
    expect(HELD[0]).toMatch(/\.n-runhead\[data-fit~="mode"\] \.n-runhead__fold\s*\{\s*display:\s*inline-flex;\s*\}/);
  });

  it('lets neither row transition while it measures itself', () => {
    expect(CSS).toContain(':where(.n-masthead, .n-masthead *) { transition-property: none; }');
    expect(CSS).toContain(':where(.n-runhead, .n-runhead *) { transition-property: none; }');
  });

  it('keeps every running-head item at least as wide as what it draws', () => {
    // the two free-length values narrow inside a grid track that never goes below its floor: the
    // mark, the gaps and an ellipsis of each value part
    expect(WIDE).toMatch(/\.n-signals__item:is\(\[data-signal="egress"\], \[data-signal="model"\]\)\s*\{[^}]*grid-template-columns:\s*auto minmax\(var\(--n-runhead-floor\), max-content\)/);
    expect(WIDE).toMatch(/--n-runhead-floor:\s*calc\(12px \+ var\(--n-s-1\) \* 1\.5 \+ 1\.25em\)/);
    expect(WIDE).toMatch(/\.n-signals__item\[data-signal="model"\]\s*\{\s*--n-runhead-floor:\s*calc\(12px \+ var\(--n-s-1\) \* 3 \+ 2\.5em\)/);
    expect(WIDE).toMatch(/:is\(\.n-signals__ident, \.n-signals__text\)\s*\{[^}]*min-width:\s*1\.25em/);
    // the list of signals keeps its automatic minimum, and no rule lets an item be narrower
    expect(WIDE).toMatch(/\.n-signals\s*\{[^}]*min-width:\s*auto/);
    expect(CSS).not.toMatch(/\.n-signals__item(:is\([^)]*\))?\s*\{[^}]*min-width:\s*0/);
  });

  it('cuts the model id first, then its backend, and the egress statement only after them', () => {
    // a weight so large that the other part's share of a cut rounds below a layout unit (1/64px)
    const weight = (re) => Number((WIDE.match(re) || [])[1]);
    expect(weight(/\.n-runhead\[data-fit~="cut"\] \.n-signals__item\[data-signal="model"\]\s*\{\s*flex-shrink:\s*(\d+)/)).toBeGreaterThanOrEqual(10000);
    expect(weight(/\.n-signals__item\[data-signal="model"\] \.n-signals__ident\s*\{\s*flex-shrink:\s*(\d+)/)).toBeGreaterThanOrEqual(10000);
  });

  it('keeps a note\'s count hidden until a step draws it', () => {
    expect(CSS).toMatch(/\.n-areas__count\s*\{\s*display:\s*none;\s*\}/);
  });

  it('lays the running head out as one line of marks below 760px, its popovers under the whole head', () => {
    expect(CSS).toMatch(/\.n-runhead--compact\s*\{[^}]*flex-wrap:\s*nowrap/);
    expect(CSS).toMatch(/\.n-runhead--compact :is\(\.n-disclosure, \.n-runhead__mode, \.n-runhead__interrupts\)\s*\{\s*position:\s*static;\s*\}/);
    expect(CSS).toMatch(/\.n-runhead--compact \.n-runhead__button\s*\{[^}]*min-width:\s*24px/);
    // the marks are never wider than the room another page gives them (Glance's foot)
    expect(CSS).toMatch(/\.n-runhead--marks\s*\{[^}]*max-width:\s*100%/);
    // where below would leave the window (Glance's foot, at its bottom: kit Disclosure `contain`),
    // a popover opens above the whole head instead
    expect(CSS).toMatch(/\.n-runhead--compact \.n-disclosure__panel\[data-place="above"\]\s*\{\s*top:\s*auto;\s*bottom:\s*calc\(100% \+ var\(--n-s-1\)\);\s*\}/);
  });

  it('draws the main window\'s approval mode below 760px as its button and its popover under the whole head', () => {
    // one tree in every form (RunningHead.tsx): the fold's own button is the mark, its box the popover
    expect(CSS).toMatch(/\.n-runhead--compact \.n-runhead__fold\s*\{\s*display:\s*inline-flex;\s*\}/);
    expect(CSS).toMatch(/\.n-runhead--compact \.n-runhead__box\s*\{\s*display:\s*none;\s*\}/);
    const open = CSS.match(/\.n-runhead--compact \.n-runhead__mode\[data-open\] > \.n-runhead__box\s*\{([^}]*)\}/);
    expect(open?.[1]).toMatch(/position:\s*absolute/);
    expect(open?.[1]).toMatch(/left:\s*var\(--n-s-2\);\s*right:\s*var\(--n-s-2\)/);
    expect(CSS).toMatch(/\.n-runhead__box\[hidden\]\s*\{\s*display:\s*none;\s*\}/);
    // a popover above, where below would leave the window, and moved in from an edge (placeInside)
    expect(CSS).toMatch(/\.n-runhead--compact \.n-runhead__mode\[data-open\] > \.n-runhead__box\[data-place="above"\]\s*\{\s*top:\s*auto;/);
    expect(CSS).toMatch(/:is\(\.n-runhead__pop, \.n-runhead__box\)\[data-shift\]\s*\{\s*transform:\s*translateX\(var\(--n-disclosure-shift, 0px\)\);\s*\}/);
    expect(WIDE).toMatch(/\.n-runhead\[data-fit~="mode"\] \.n-runhead__mode\[data-open\] > \.n-runhead__box\[data-place="above"\]/);
    expect(HELD[0]).toMatch(/\.n-runhead\[data-fit~="mode"\] \.n-runhead__mode\[data-open\] > \.n-runhead__box\[data-place="above"\]/);
  });

  it('draws every surface it lays over the page opaque: the sheet over the page\'s own ground', () => {
    // Classic's sheet is translucent (--surface, rgba(10, 22, 38, .55) in Obsidian): alone, it drew
    // the page's words through a popover
    const OPAQUE = /background-color:\s*var\(--n-bg\);\s*background-image:\s*linear-gradient\(var\(--n-sheet\), var\(--n-sheet\)\);/;
    const surfaces = [
      /\.n-runhead__pop\s*\{([^}]*)\}/,
      /\.n-runhead--compact \.n-runhead__mode\[data-open\] > \.n-runhead__box\s*\{([^}]*)\}/,
      /\.n-areadrawer__sheet\s*\{([^}]*)\}/,
    ];
    for (const re of surfaces) expect(CSS.match(re)?.[1], String(re)).toMatch(OPAQUE);
    const fold = /\.n-runhead\[data-fit~="mode"\] \.n-runhead__mode\[data-open\] > \.n-runhead__box\s*\{([^}]*)\}/;
    expect(WIDE.match(fold)?.[1]).toMatch(OPAQUE);
    expect(HELD[0].match(fold)?.[1]).toMatch(OPAQUE);
    // no surface paints the sheet alone any more (the Find field is a control on the row, not a surface)
    const alone = [...CSS.matchAll(/([^{}]+)\{[^}]*background:\s*var\(--n-sheet\)[^}]*\}/g)].map((m) => m[1].trim());
    expect(alone).toEqual(['.n-masthead__find']);
  });

  it('folds the running foot onto lines below 760px, an unknown machine reading as its mark', () => {
    expect(NARROW).toMatch(/\.n-runfoot__group\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(NARROW).toMatch(/\.n-runfoot__item\[data-machine\]\[data-state="unknown"\] > \.n-runfoot__words\s*\{[^}]*clip-path:\s*inset\(50%\)/);
  });
});
