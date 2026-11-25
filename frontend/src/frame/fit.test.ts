/* The fit machinery both rows share (fit.ts): the walk, the steps taken back once it fits, and
   steps held as they are. The row is a model: each step frees a known number of px, and the row
   spills while what it needs is more than its room. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CUT_EPSILON, fitRow, spillsOver, stepBack, textCut, textOverflow, walkSteps } from './fit';

const ORDER = ['a', 'b', 'c', 'd', 'e'] as const;
type Step = typeof ORDER[number];

/** A row `need` px long before any step, in `room` px, each step freeing `frees[step]` px. */
function row(need: number, room: number, frees: Partial<Record<Step, number>>) {
  const tried: string[] = [];
  const spills = (steps: readonly Step[]) => {
    tried.push(steps.join(' '));
    return need - steps.reduce((sum, step) => sum + (frees[step] ?? 0), 0) > room;
  };
  return { spills, tried };
}

describe('fit.ts — the walk', () => {
  it('takes the fewest steps in order, passing over one that does not apply', () => {
    expect(walkSteps(ORDER, row(1000, 1000, {}).spills)).toEqual([]);
    expect(walkSteps(ORDER, row(1100, 1000, { a: 60, b: 60, c: 60 }).spills)).toEqual(['a', 'b']);
    expect(walkSteps(ORDER, row(1100, 1000, { a: 60, b: 60, c: 60 }).spills, [], (step) => step !== 'a')).toEqual(['b', 'c']);
    // a row that never fits takes every step that applies
    expect(walkSteps(ORDER, () => true)).toEqual([...ORDER]);
  });
});

describe('fit.ts — taking steps back once the row fits', () => {
  it('takes back an earlier step a later one made unneeded, the lossiest first', () => {
    // the 2560px case: the long labels (b) and a source's reason (a) were given up before the
    // egress statement's short form (c) freed far more than either
    const { spills } = row(2600, 2000, { a: 150, b: 300, c: 640, d: 100 });
    expect(walkSteps(ORDER, spills)).toEqual(['a', 'b', 'c']);
    expect(fitRow(ORDER, { spills })).toEqual(['c']);
    // only as far as the room allows: with less of it, the lossier of the two comes back alone
    const tight = row(2600, 1900, { a: 150, b: 300, c: 640, d: 100 });
    expect(fitRow(ORDER, { spills: tight.spills })).toEqual(['a', 'c']);
  });

  it('keeps every step the row still needs, and takes nothing back from a row that never fits', () => {
    // each step frees the same: none can come back
    expect(fitRow(ORDER, { spills: row(1300, 1000, { a: 100, b: 100, c: 100, d: 100, e: 100 }).spills })).toEqual(['a', 'b', 'c']);
    // every step and still too long: nothing is taken back from a spill
    expect(fitRow(ORDER, { spills: () => true })).toEqual([...ORDER]);
    expect(stepBack(ORDER, ['a', 'c'], () => false)).toEqual(['a', 'c']);
    expect(stepBack(ORDER, ['a', 'c'], () => true)).toEqual([]);
  });

  it('tries the lossiest step first, and asks with the steps that would be left', () => {
    const asked: string[] = [];
    // d is needed; b comes back; a then cannot, with b back on screen
    expect(stepBack(ORDER, ['a', 'b', 'd'], (steps) => { asked.push(steps.join(' ')); return steps.includes('d') && steps.length >= 2; })).toEqual(['a', 'd']);
    expect(asked).toEqual(['a b', 'a d', 'd']);
  });

  it('is the same whichever way the room changed: a fit afresh depends on the row alone', () => {
    const frees = { a: 150, b: 300, c: 640, d: 100 };
    const at = (room: number) => fitRow(ORDER, { spills: row(2600, room, frees).spills }).join(' ');
    const rooms = [2700, 2400, 2100, 1900, 1700, 1500, 1300];
    const down = rooms.map(at);
    const up = [...rooms].reverse().map(at).reverse();
    expect(up).toEqual(down);
    // the walk alone would keep a at 2400 (a b), and a and b at 2100 (a b c)
    expect(down).toEqual(['', 'b', 'c', 'a c', 'b c', 'a b c d', 'a b c d e']);
  });

  it('asks its own question for a step taken back where a step\'s loss grows as the room shrinks', () => {
    // e: a value may be cut ("cut"): the row "fits" without the earlier steps only by cutting more
    const cut = { amount: 0 };
    const spills = (steps: readonly Step[]) => {
      const short = 1300 - (steps.includes('a') ? 100 : 0) - (steps.includes('b') ? 100 : 0) - 1000;
      cut.amount = Math.max(0, short);
      return short > 0 && !steps.includes('e');
    };
    // the walk needs every step; a plain step back would trade a and b for a deeper cut
    expect(walkSteps(ORDER, spills)).toEqual([...ORDER]);
    expect(fitRow(ORDER, { spills })).toEqual(['e']);
    // with the cut measured, a step comes back only where the cut does not grow
    let bar: number | null = null;
    const fitsBack = (steps: readonly Step[]) => {
      // the walk's own steps were measured last: their cut is the bar
      const most = bar ?? (bar = cut.amount);
      if (spills(steps)) return false;
      return cut.amount <= most;
    };
    expect(fitRow(ORDER, { spills, fitsBack })).toEqual(['a', 'b', 'e']);
  });
});

/* A text the spec keeps whole is measured in fractions of a pixel: Chromium draws an ellipsis for an
   overflow of one layout unit (1/64 of a device pixel), and the whole-pixel scrollWidth and
   clientWidth read a text 0.44px too wide as 44 in 43 and one 0.11px too wide as equal. jsdom lays
   nothing out: the box and its text's Range are given. */
describe('fit.ts — a text cut by less than a pixel', () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ''; });
  const box = (left: number, right: number) => ({ left, right, top: 0, bottom: 18, width: right - left, height: 18, x: left, y: 0, toJSON() { return this; } }) as DOMRect;
  function text(scroll: number, client: number, extent: () => DOMRect[] | null) {
    const el = document.createElement('span');
    el.textContent = 'Search';
    document.body.appendChild(el);
    Object.defineProperty(el, 'scrollWidth', { configurable: true, value: scroll });
    Object.defineProperty(el, 'clientWidth', { configurable: true, value: client });
    vi.spyOn(el, 'getBoundingClientRect').mockReturnValue(box(100, 143));
    vi.spyOn(document, 'createRange').mockImplementation(() => {
      const rects = extent();
      return (rects ? { selectNodeContents: () => {}, getClientRects: () => rects } : { selectNodeContents: () => {} }) as unknown as Range;
    });
    return el;
  }

  it('sees what whole pixels miss: a text past its box by a fraction of a pixel is cut', () => {
    const el = text(43, 43, () => [box(100, 143.11)]);
    expect(spillsOver(el)).toBe(false);
    expect(textOverflow(el)).toBeCloseTo(0.11, 6);
    expect(textCut(el)).toBe(true);
    // a layout unit at the owner's 1.5× (1/96px) is a cut too; a float's rounding is not
    expect(textCut(text(43, 43, () => [box(100, 143 + 1 / 96)]))).toBe(true);
    expect(textCut(text(43, 43, () => [box(100, 143 + 1e-9)]))).toBe(false);
    expect(CUT_EPSILON).toBeLessThan(1 / 96);
  });

  it('counts a text exactly as wide as its box as whole, and takes the whole pixels where they say more', () => {
    expect(textOverflow(text(43, 43, () => [box(100, 143)]))).toBe(0);
    expect(textCut(text(43, 43, () => [box(100, 143)]))).toBe(false);
    // the text's own extent reads less than the whole pixels: the larger is taken
    expect(textOverflow(text(52, 43, () => [box(100, 144)]))).toBe(9);
    // no Range geometry (a test DOM, an engine without it): the whole pixels say what is known
    expect(textOverflow(text(44, 43, () => null))).toBe(1);
    expect(textOverflow(text(43, 43, () => []))).toBe(0);
  });
});

describe('fit.ts — steps held as they are', () => {
  it('keeps a held step taken, and never takes one held out', () => {
    const { spills } = row(1100, 1000, { a: 60, b: 60, c: 200 });
    expect(fitRow(ORDER, { spills })).toEqual(['a', 'b']);
    // c held taken (the approval mode folded while its confirmation waits): the walk starts from it
    expect(fitRow(ORDER, { spills, held: { c: true } })).toEqual(['c']);
    // b held out (unfolded while it waits): the walk goes past it
    expect(fitRow(ORDER, { spills, held: { b: false } })).toEqual(['c']);
    expect(fitRow(ORDER, { spills: row(1150, 1000, { a: 60, b: 60, c: 60, d: 60 }).spills, held: { b: false } })).toEqual(['a', 'c', 'd']);
  });

  it('never takes a held step back, even where the row fits without it', () => {
    const { spills } = row(900, 1000, { c: 200 });
    expect(fitRow(ORDER, { spills })).toEqual([]);
    expect(fitRow(ORDER, { spills, held: { c: true } })).toEqual(['c']);
  });
});
