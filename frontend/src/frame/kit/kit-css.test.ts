// @ts-nocheck — reads the stylesheets as source with node:fs (src/ builds against the DOM lib only)
/* The Phase B stylesheets draw through roles only (PHASE_B_PLAN.md §1.3): no colour literal,
   no font size but a --n-fs-* step (so nothing under 12px), no hard-coded uppercase or
   tracking, and no Phase A primitive (n-btn, n-seg, …) or legacy class redefined. */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const read = (...path) => readFileSync(join(process.cwd(), 'src', ...path), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const FILES = { 'frame/kit/kit.css': read('frame', 'kit', 'kit.css'), 'frame/frame.css': read('frame', 'frame.css') };
const PRIMITIVES = ['n-btn', 'n-seg', 'n-field', 'n-input', 'n-textarea', 'n-link', 'n-kbd', 'n-tag', 'n-chip', 'n-row', 'n-state', 'n-json', 'n-card', 'n-meter'];
const LEGACY = ['topbar', 'rail-btn', 'inputbar', 'transmit', 'msg', 'bubble', 'convo', 'dcard', 'panel', 'badge', 'ticker', 'workzone', 'rail', 'tool-btn'];

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
});

describe('frame/kit/kit.css', () => {
  it('draws a disclosure\'s popover opaque: the sheet over the page\'s own ground', () => {
    // Classic's sheet is translucent (--surface): alone, it drew the page's words through the popover
    const panel = FILES['frame/kit/kit.css'].match(/\.n-disclosure__panel\s*\{([^}]*)\}/)?.[1];
    expect(panel).toMatch(/background-color:\s*var\(--n-bg\);\s*background-image:\s*linear-gradient\(var\(--n-sheet\), var\(--n-sheet\)\);/);
    expect(panel).not.toMatch(/background:\s*var\(--n-sheet\)/);
  });
});

describe('frame/frame.css', () => {
  it("draws the masthead Find button's key cap from data-key (Masthead.tsx writes no key text)", () => {
    expect(FILES['frame/frame.css']).toMatch(/\.n-masthead__key::before\s*\{\s*content:\s*attr\(data-key\);?\s*\}/);
  });
});

/* The heads' rows: a section head (title, aside), a register head (title, meta) and a total (its
   sentence, its aside). One rule at every width (Register.tsx, kit.css): where the title and the flow
   beside it do not fit, the flow takes the line under the title, so the title is never squeezed to
   one word per line ("While you were away" in the 396px day register, the last gate) and the flow
   never runs past its row; a flow wider than the row wraps between its parts, and a part wider than
   the row alone is cut with an ellipsis. Each rule is read with the @-rules it sits in. */
type Rule = { at: string[]; selector: string; body: Record<string, string> };
function rulesOf(css: string): Rule[] {
  const out: Rule[] = [];
  const stack: string[] = [];
  let text = '';
  for (const ch of css) {
    if (ch === '{') { stack.push(text.trim().replace(/\s+/g, ' ')); text = ''; continue; }
    if (ch === '}') {
      const selector = stack.pop() ?? '';
      if (!selector.startsWith('@') && text.includes(':')) {
        const body: Record<string, string> = {};
        for (const decl of text.split(';')) {
          const at = decl.indexOf(':');
          if (at > 0) body[decl.slice(0, at).trim()] = decl.slice(at + 1).trim().replace(/\s+/g, ' ');
        }
        out.push({ at: stack.filter((s) => s.startsWith('@')), selector, body });
      }
      text = '';
      continue;
    }
    text += ch;
  }
  return out;
}
const KIT_RULES = rulesOf(FILES['frame/kit/kit.css']);
/** The declarations of the top-level rules whose selector is exactly `selector`, merged in order. */
const top = (selector: string) => Object.assign({}, ...KIT_RULES.filter((r) => !r.at.length && r.selector === selector).map((r) => r.body));
const FLOW = ':is(.n-sec__aside, .n-register__meta, .n-total__main, .n-total__aside)';

describe('frame/kit/kit.css — the heads\' rows', () => {
  it('lets a section head\'s aside take the line under its title, so the title is never squeezed', () => {
    expect(top('.n-sec')).toMatchObject({ display: 'flex', 'flex-wrap': 'wrap', 'align-items': 'baseline' });
    // the title keeps the whole row where it needs it (as wide as the row, never narrower than it must
    // be), and grows on its line: an aside beside it ends at the row's end, one below starts under it
    expect(top('.n-sec__title')).toMatchObject({ flex: '1 1 auto', 'min-width': '0', 'max-width': '100%' });
    expect(top('.n-sec__title')['white-space']).toBeUndefined();
    // over the same quiet rule, in the meta voice
    expect(top('.n-sec')['border-top']).toBe('var(--n-hair) solid var(--n-rule-2)');
    expect(top('.n-sec__aside')).toMatchObject({ 'font-size': 'var(--n-fs-meta)', color: 'var(--n-text-3)' });
  });

  it('draws a section head with one rule at every width: no breakpoint names it', () => {
    const named = KIT_RULES.filter((r) => /\.n-sec(?![\w-])|\.n-sec__/.test(r.selector) || r.selector === FLOW || r.selector.startsWith(`${FLOW} >`));
    expect(named.length).toBeGreaterThan(0);
    for (const r of named) expect(r.at, r.selector).toEqual([]);
  });

  it('wraps a flow between its parts and never lets it run past its row', () => {
    expect(top(FLOW)).toMatchObject({ display: 'inline-flex', 'flex-wrap': 'wrap', 'min-width': '0', 'max-width': '100%', 'white-space': 'nowrap' });
    expect(top(`${FLOW} > *`)).toMatchObject({ 'min-width': '0', 'max-width': '100%' });
    // the old flow: one unbreakable line (inline-flex, nowrap, no wrap) that ran past its row
    for (const selector of ['.n-sec__aside', '.n-register__meta', '.n-total__main, .n-total__aside']) {
      const own = top(selector);
      expect(own['white-space'], selector).toBeUndefined();
      expect(own['margin-left'], selector).toBeUndefined();
    }
  });

  it('cuts a part wider than its row with an ellipsis (a source label at its reason), never a link or a button', () => {
    expect(top(`${FLOW} > :not(a, button, .n-src)`)).toMatchObject({ overflow: 'hidden', 'text-overflow': 'ellipsis' });
    expect(top(`${FLOW} > .n-src > :last-child`)).toMatchObject({ 'min-width': '0', overflow: 'hidden', 'text-overflow': 'ellipsis' });
  });

  it('puts a register head\'s meta under its title where they do not fit, keeping the strut, and never cuts the title', () => {
    expect(top('.n-register__head')).toMatchObject({ display: 'flex', 'flex-wrap': 'wrap', 'align-items': 'baseline' });
    expect(top('.n-register__head::before')).toMatchObject({ content: '""', width: '0', height: 'var(--register-strut)' });
    const title = top('.n-register__title');
    expect(title).toMatchObject({ flex: '1 1 auto', 'min-width': '0', 'max-width': '100%' });
    expect(title['white-space']).toBeUndefined();
    expect(title['text-overflow']).toBeUndefined();
    expect(title.overflow).toBeUndefined();
  });

  it('lets a total\'s aside take the line under its sentence', () => {
    expect(top('.n-total')).toMatchObject({ display: 'flex', 'flex-wrap': 'wrap' });
    expect(top('.n-total__main')).toMatchObject({ flex: '1 1 auto' });
  });

  it('keeps a register\'s body and foot in one box after the head (the row a spread of registers shares)', () => {
    expect(top('.n-register__main')).toMatchObject({ display: 'flex', 'flex-direction': 'column', flex: '1 1 auto', 'min-height': '0' });
  });

  /* The review of the heads' round: the docket's large figure (--n-fs-figure at its own --n-lh-figure)
     set the docket's title 8px under the strut (13px in Presence from 2200px) and its head 1 to 8px
     taller with nothing wrapping, and every head beside it on Home took that height (one row). */
  it('lets nothing inside a register title make its line taller than a title\'s: a figure takes the title\'s line height', () => {
    const rule = KIT_RULES.find((r) => r.selector === '.n-register__head > .n-register__title *');
    expect(rule?.at).toEqual([]);
    expect(rule?.body).toEqual({ 'line-height': 'inherit' });
    // it outranks a page's own line height for what it sets in a title (the docket's figure: one class)
    const docket = rulesOf(read('docket', 'docket.css')).filter((r) => /\.n-docket__figure(?![\w-])/.test(r.selector) && 'line-height' in r.body);
    expect(docket.length).toBeGreaterThan(0);
    const classes = (selector: string) => (selector.match(/\.[\w-]+/g) ?? []).length;
    for (const r of docket) expect(classes(r.selector), r.selector).toBeLessThan(classes(rule?.selector ?? ''));
  });

  it('holds a head no shorter than its own minimum, up to the tallest head beside it (useHeadRow), and does not transition it', () => {
    // a min-height in transition is read at its old value (calm motion transitions `all` for 0.01ms), and
    // useHeadRow reads each head's own height right after it takes the shared height away
    expect(top('.n-register__head')).toMatchObject({ 'min-height': 'max(var(--register-head-h), var(--register-head-row, 0px))', 'transition-property': 'none' });
  });
});

/* The final renders after the last gate (2026-11-25): in every card look (Atlas, Console, Threshold and
   Workbench, light and dark, Classic · Obsidian and Graphite) a register is a framed card, and its
   title, meta, rows and controls touched the frame on the left and the right (Atlas light at 2560px:
   "Wednesday 25 November" 1px inside the day register's left border, "02:19" ending at its right one;
   Trust's "The record" flush with its frame in Obsidian), and a total's double rule sat on its bottom
   edge. The register now takes the look's inner margin, --n-register-pad (theme/tokens.css: 0 in the
   rule looks), as its own padding on the sides and at the bottom, and asks no look which it is. */
describe('frame/kit/kit.css — a register keeps its words off its frame', () => {
  const RULE = top('.n-register');

  it('takes the look\'s inner margin (the role) as its own padding, on the sides and at the bottom', () => {
    expect(RULE['--register-pad']).toBe('var(--n-register-pad, 0px)');
    expect(RULE.padding).toBe('0 var(--register-pad) var(--register-pad)');
    // nothing else pads it: one padding, the shorthand above
    for (const r of KIT_RULES.filter((rule) => rule.selector === '.n-register')) {
      for (const name of Object.keys(r.body)) if (name.startsWith('padding')) expect(`${name}: ${r.body[name]}`, r.at.join(' ') || 'top level').toBe(`padding: ${RULE.padding}`);
    }
  });

  it('pads no top (the head\'s strut sets the title; the heads\' shared row on Home is as it was) and leaves the column to Ledger\'s rules', () => {
    expect(RULE.padding.split(' ')[0]).toBe('0');
    // the head, the body and the foot add no side margin of their own: the rule under the head, the rows'
    // hairlines and the body's scrollbar end at the column's edge, in every look
    expect(top('.n-register__head').padding).toBe('var(--n-s-1) 0');
    for (const part of ['.n-register__main', '.n-register__body', '.n-register__foot']) {
      expect(Object.keys(top(part)).filter((name) => name.startsWith('padding') || name.startsWith('margin')), part).toEqual([]);
    }
  });

  /* The review of the round: the margin is taken from the column, and the pages' columns were drawn for
     the width they had without it. At 320–390px 12px a side cut words that had been whole (Work's
     "— switched off on the hub", the docket's fine print, Memory's and Settings' rows), ran Timeline's
     source labels 27px past the frame in Classic and squeezed Trust's capabilities into overlapping
     columns; at 760px 16px a side made Health's figures 7px wider than their register's body. */
  it('takes at most --n-s-2 below 1100px (one column), and 0 stays 0', () => {
    const column = KIT_RULES.filter((r) => r.selector === '.n-register' && r.at.join() === '@media (max-width: 1099px)');
    expect(column).toHaveLength(1);
    expect(column[0].body).toEqual({ '--register-pad': 'min(var(--n-register-pad, 0px), var(--n-s-2))' });
  });

  it('draws a register with rules in every look below 760px: its top rule stays, no frame, no fill, no margin', () => {
    const phone = KIT_RULES.filter((r) => r.selector === '.n-register' && r.at.join() === '@media (max-width: 759px)');
    expect(phone).toHaveLength(1);
    expect(phone[0].body).toEqual({
      '--register-pad': '0px', background: 'none', 'border-right': '0', 'border-bottom': '0', 'border-left': '0', 'border-radius': '0', 'box-shadow': 'none',
    });
    // the rule that opens it is the look's own, at every width
    expect(RULE['border-top']).toBe('var(--n-panel-top)');
    // no other width changes the margin
    const others = KIT_RULES.filter((r) => r.selector === '.n-register' && r.at.length && '--register-pad' in r.body
      && !['@media (max-width: 1099px)', '@media (max-width: 759px)'].includes(r.at.join()));
    expect(others).toEqual([]);
  });

  /* The review of the round: the docket's total keeps 16px under its double rule (docket/docket.css) and the
     composer 16px under its frame (home/talk/talk.css). The register's bottom margin was added to them, 32 to
     36px under the total, and the docket's body lost 16 to 20px at 1280×800: the open entry's sign line went
     below what the body shows (5px of it in Atlas, Romanian, where it had been whole). */
  it('leaves the bottom margin of a register with a foot to the foot, where it collapses with its last part\'s own margin instead of adding to it', () => {
    const footed = KIT_RULES.filter((r) => r.selector === '.n-register:has(> .n-register__main > .n-register__foot)');
    expect(footed).toHaveLength(1);
    expect(footed[0]).toEqual({ at: [], selector: '.n-register:has(> .n-register__main > .n-register__foot)', body: { 'padding-bottom': '0' } });
    // an empty block after the foot's last part: its top margin and that part's bottom margin collapse
    expect(top('.n-register__foot::after')).toEqual({ content: '""', display: 'block', 'margin-top': 'var(--register-pad)' });
    // the foot is a block (no padding, border or display of its own to keep the margins apart) and a flex
    // item, so it holds the collapsed margin inside itself
    expect(top('.n-register__foot')).toEqual({ flex: 'none' });
    expect(top('.n-register__main').display).toBe('flex');
    // the reason: a foot's last part that keeps its own margin
    const docket = Object.assign({}, ...rulesOf(read('docket', 'docket.css')).filter((r) => r.selector === '.n-docket__total' && !r.at.length).map((r) => r.body));
    expect(docket['margin-bottom']).toBe('var(--n-s-4)');
  });

  it('asks no stylesheet of Phase B which look is on: the role decides', () => {
    const SHEETS = ['frame/kit/kit.css', 'frame/frame.css', 'home/home.css', 'home/day/day.css', 'home/talk/talk.css',
      'docket/docket.css', 'pages/pages.css', 'nav/contents.css', 'nav/sheet.css'];
    for (const sheet of SHEETS) expect(read(...sheet.split('/')), sheet).not.toMatch(/data-look|data-scheme/);
  });
});

/* The area page's own frame (2026-11-25, after the register-inset round). frame.css drew the column every
   area page draws (.n-areapage__main: Trust, Work, Timeline, the conversation page, every mode and panel
   page) with the look's panel treatment and no margin inside it: in every card look the page's title sat
   0px from that frame at every width, and every register inside it was a card whose frame lay on the area
   frame's edge, a card inside a card. The column now keeps its top rule only, in every look (the
   coordinator's variant A): the title stands on the page's ground, as Home's heads do, and the registers
   are the cards. In Ledger, Briefing and Presence the panel treatment was already a transparent ground, a 0
   border, no radius and no shadow, so the values below are theirs: nothing moves there. */
describe('frame/frame.css — the area page\'s column is not a card', () => {
  const FRAME_RULES = rulesOf(FILES['frame/frame.css']);
  const MAIN = /\.n-areapage__main(?![\w-])(?!::)/;
  const main = Object.assign({}, ...FRAME_RULES.filter((r) => !r.at.length && r.selector === '.n-areapage__main').map((r) => r.body));

  it('opens with the look\'s top rule and draws no fill, no side or bottom border, no radius and no shadow', () => {
    expect(main['border-top']).toBe('var(--n-panel-top)');
    expect(main).toMatchObject({ background: 'transparent', border: '0 solid transparent', 'border-radius': '0', 'box-shadow': 'none' });
    // the rule looks' own panel treatment (theme/themes/ledger.css, briefing.css, presence.css): the same values
    for (const look of ['ledger', 'briefing', 'presence']) {
      const theme = read('theme', 'themes', `${look}.css`);
      expect(theme, look).toMatch(/--n-panel-bg:\s*transparent;/);
      expect(theme, look).toMatch(/--n-panel-border:\s*0 solid transparent;/);
      expect(theme, look).toMatch(/--n-panel-radius:\s*0;/);
      expect(theme, look).toMatch(/--n-panel-shadow:\s*none;/);
    }
  });

  it('takes no part of the panel treatment but its top rule, at any width', () => {
    const named = FRAME_RULES.filter((r) => MAIN.test(r.selector));
    expect(named.length).toBeGreaterThan(0);
    for (const r of named) {
      for (const [name, value] of Object.entries(r.body)) {
        if (name === 'border-top') continue;
        expect(`${name}: ${value}`, `${r.at.join(' ')} ${r.selector}`).not.toMatch(/--n-panel-(?:bg|border|radius|shadow|pad)\b/);
        if (/^(?:background(?:-color)?|box-shadow)$/.test(name)) expect(value, `${r.selector} ${name}`).toMatch(/^(?:transparent|none)$/);
        if (/^border(?:-(?:left|right|bottom))?(?:-width)?$/.test(name)) expect(value, `${r.selector} ${name}`).toMatch(/^0(?:px)?(?: solid transparent)?$/);
      }
    }
  });
});

/* A consequence's term column (2026-11-25): 74px (82px from 2200px), drawn for a label voice in sentence
   case. Classic's label voice (mono capitals, tracked .1em) broke "IF YOU SIGN" and "CA SĂ ANULEZI" onto two
   lines there, each row of the docket's open entry two lines tall: 21px (English) to 44px (Romanian) of the
   1280×800 docket's view, its sign line below it. A page that needs its terms on one line opts in, and the
   column grows to the look's --n-term-max (0px in every Nerva look: no growth, nothing moves). */
describe('frame/kit/kit.css — a consequence\'s term column', () => {
  it('is 74px (82px from 2200px) unless a page opts in, and then grows to the look\'s --n-term-max', () => {
    expect(top('.n-consequence')['grid-template-columns']).toBe('minmax(74px, var(--consequence-term-max, 0px)) minmax(0, 1fr)');
    const wide = KIT_RULES.filter((r) => r.selector === '.n-consequence' && r.at.join() === '@media (min-width: 2200px)');
    expect(wide).toHaveLength(1);
    expect(wide[0].body).toEqual({ 'grid-template-columns': 'minmax(82px, var(--consequence-term-max, 0px)) minmax(0, 1fr)' });
    // the kit opts no page in: the hook is set by the page that needs it (the docket)
    for (const r of KIT_RULES) expect(r.body['--consequence-term-max'], r.selector).toBeUndefined();
  });
});

/* The review of the heads' round: at a 320px window the day band's popovers (at least 320px wide,
   home/day/day.css, opening from their cell at the page's 20px margin) reached 20px past the window,
   which cut "While you were away" and Today's "· checked 10:50" with no ellipsis. */
describe('frame/kit/kit.css — a popover inside the window', () => {
  const narrow = KIT_RULES.filter((r) => r.selector === '.n-disclosure > .n-dayband__panel');

  it('caps the day band\'s popovers at their cell and the page\'s margin where the window is narrower than their minimum and the margin', () => {
    expect(narrow).toHaveLength(1);
    expect(narrow[0].body).toEqual({ 'min-width': '0', 'max-width': 'calc(100% + var(--n-page-x))' });
    const [query] = narrow[0].at;
    const below = Number(/^@media \(max-width: ([\d.]+)px\)$/.exec(query)?.[1]);
    // every window narrower than the page's minimum plus its margin, and no wider one
    const day = rulesOf(read('home', 'day', 'day.css')).filter((r) => r.selector === '.n-dayband__panel' && !r.at.length);
    const minimum = parseFloat(Object.assign({}, ...day.map((r) => r.body))['min-width']);
    const tokens = rulesOf(read('theme', 'tokens.css')).filter((r) => r.selector === ':root' && r.at.join() === '@media (max-width: 1339px)');
    const margin = parseFloat(Object.assign({}, ...tokens.map((r) => r.body))['--n-page-x']);
    expect(minimum).toBe(320);
    expect(margin).toBe(20);
    expect(below).toBeGreaterThanOrEqual(minimum + margin - 0.02);
    expect(below).toBeLessThan(minimum + margin);
  });
});

describe('home/home.css — the heads of the registers side by side', () => {
  const HOME = rulesOf(read('home', 'home.css'));
  const SHARED = ['@supports (grid-template-rows: subgrid)', '@media (min-width: 1100px)'];
  const shared = (selector: string) => Object.assign({}, ...HOME.filter((r) => r.selector === selector && r.at.join(' ') === SHARED.join(' ')).map((r) => r.body));

  it('gives them one row: the spread\'s first row is the heads\', taken by every cell and register as a subgrid', () => {
    expect(shared('.n-spread--home')).toEqual({ 'grid-template-rows': 'auto minmax(0, 1fr) auto' });
    expect(shared('.n-spread--home > .n-spread__cell')).toMatchObject({ display: 'grid', 'grid-row': '1 / -1', 'grid-template-rows': 'subgrid' });
    expect(shared('.n-spread--home > .n-spread__cell > .n-register')).toMatchObject({ display: 'grid', 'grid-row': '1 / -1', 'grid-template-rows': 'subgrid' });
    expect(shared('.n-spread--home > .n-spread__cell > .n-register > .n-register__head')).toEqual({ 'grid-row': '1' });
    expect(shared('.n-spread--home > .n-spread__cell > .n-register > .n-register__main')).toEqual({ 'grid-row': '2 / -1' });
    // what follows the day register has the third row; the day register ends before it
    expect(shared('.n-spread--home > .n-spread__cell--day > .n-register')).toEqual({ 'grid-row': '1 / 3' });
    expect(shared('.n-spread--home > .n-spread__cell > .n-home__more')).toEqual({ 'grid-row': '3' });
  });

  it('keeps a meta under its title at the right on Home and the conversation page, and starts it at the left below 760px', () => {
    const meta = ':is(.n-spread__cell, .n-chatpage__talk) > .n-register > .n-register__head > .n-register__meta';
    expect(Object.assign({}, ...HOME.filter((r) => r.selector === meta && !r.at.length).map((r) => r.body)))
      .toMatchObject({ 'justify-content': 'flex-end', 'margin-left': 'auto' });
    expect(Object.assign({}, ...HOME.filter((r) => r.selector === meta && r.at.join() === '@media (max-width: 759px)').map((r) => r.body)))
      .toMatchObject({ 'justify-content': 'flex-start', 'margin-left': '0' });
  });
});
