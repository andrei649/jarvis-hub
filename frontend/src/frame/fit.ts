/* Keeping a row fitted: the masthead's (Masthead.tsx) and the running head's (RunningHead.tsx),
   from 1100px, where each is one line.

   Whether a row fits depends on what is drawn — the language, the look and its typeface, the
   density, every reading — not on the width alone, so each row measures itself and takes steps,
   the least loss first, until nothing spills (`walkSteps`); frame.css draws each step from the
   row's data-fit. A later step can free more room than the steps before it needed (at 2560px the
   egress statement's short form frees ~640px, more than the long labels the walk gave up first),
   so once the walk fits, the steps it took are taken back, the lossiest first, each only where
   the row still fits without it (`stepBack`; `fitRow` does both). Every fit starts afresh from the
   row as it is drawn, in the same pass, before the paint: a width reached by narrowing the window
   takes the same steps as one reached by widening it, and nothing flips back and forth.

   A text the spec keeps whole (Find's words; a running-head value before the "cut" step) is
   measured in fractions of a pixel (`textCut`): Chromium draws an ellipsis for an overflow of one
   layout unit, which whole-pixel scrollWidth and clientWidth cannot see.

   When it measures (`useFitWatch`): once before the first paint, then only when something that
   decides the fit changes — the row's words or what it draws (a MutationObserver on the row: its
   text, its children and the attributes that change a width, never the row's own data-fit), the
   window's width, a font arriving, the look, typeface, density or language on <html>, and a box
   of the row changing size by itself (a ResizeObserver; the refit then waits for the next frame,
   so it never resizes an observed box inside the observer's own callback). A render that changes
   nothing on screen — App renders on every streamed token — reads no layout at all. */
import { useLayoutEffect, useRef, type RefObject } from 'react';

/** More than its own box holds: content past its right edge (overflow visible or not), in whole
 *  pixels. For a box of the row's layout (the header, the areas strip, the tools): a box that holds
 *  a pixel more than it shows spills into the gap or the padding beside it, and draws nothing over
 *  anything. A text that may be cut with an ellipsis is measured by `textCut`, never by this. */
export const spillsOver = (el: Element | null): boolean => !!el && el.scrollWidth - el.clientWidth > 1;

/** A text cut by more than this is drawn with an ellipsis: Chromium truncates a line whose content
 *  is wider than its box by one layout unit, 1/64 of a device pixel (1/64px at 1×, 1/96px at the
 *  owner's 1.5×); this is under a layout unit up to 4× and far over a float's rounding. */
export const CUT_EPSILON = 0.003;

/** How far an element's text runs past its own content box, in px, in fractions of a pixel: the
 *  extent of what it holds (a Range over its contents, as laid out before any ellipsis) against its
 *  inner edges, or the whole pixels scrollWidth and clientWidth give where they say more. Whole
 *  pixels alone cannot see a cut of under a pixel or two (text 0.44px wider than its box reads 44 in
 *  43, and 0.11px wider reads equal), which `text-overflow: ellipsis` still draws as an ellipsis.
 *  0 for an element not drawn (it has no box and no text rects); where the layout has no Range
 *  geometry (a test DOM), the whole pixels. */
export function textOverflow(el: Element | null): number {
  if (!el) return 0;
  const box = el as HTMLElement;
  const whole = Math.max(0, (box.scrollWidth || 0) - (box.clientWidth || 0));
  let rects: DOMRect[] = [];
  try {
    const range = document.createRange();
    range.selectNodeContents(box);
    if (typeof range.getClientRects === 'function') rects = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0);
  } catch { /* no Range geometry: the whole pixels say what is known */ }
  if (!rects.length) return whole;
  const style = getComputedStyle(box);
  const outer = box.getBoundingClientRect();
  const left = outer.left + (parseFloat(style.borderLeftWidth) || 0) + (parseFloat(style.paddingLeft) || 0);
  const right = outer.right - (parseFloat(style.borderRightWidth) || 0) - (parseFloat(style.paddingRight) || 0);
  const past = Math.max(Math.max(...rects.map((r) => r.right)) - right, left - Math.min(...rects.map((r) => r.left)));
  return Math.max(whole, past, 0);
}

/** Whether an element's text is cut (drawn with an ellipsis where its style asks for one): it runs
 *  past its box by a layout unit or more (`textOverflow`). */
export const textCut = (el: Element | null): boolean => textOverflow(el) > CUT_EPSILON;

/** Whether a media query matches now; where the DOM cannot say (no matchMedia), `fallback`. */
export function mediaMatches(query: string, fallback: () => boolean): boolean {
  try {
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      const list = window.matchMedia(query);
      if (list && typeof list.matches === 'boolean') return list.matches;
    }
  } catch { /* no media queries: decide by the fallback */ }
  return fallback();
}

/** `steps` in the order of `order` (a row's data-fit lists them so). */
const inOrder = <S extends string>(order: readonly S[], steps: readonly S[]): S[] => order.filter((step) => steps.includes(step));

/** The walk: from `base`, the steps of `order` from `at` on, in order, each taken while `spills`
 *  says the row still spills, a step that `may` not be taken passed over; and whether the row fits
 *  with the steps it ends on (each set of steps is measured once). */
function walk<S extends string>(order: readonly S[], spills: (steps: readonly S[]) => boolean, base: readonly S[], at: number,
  may: (step: S) => boolean): { steps: S[]; fits: boolean } {
  let steps = inOrder(order, base);
  let spilling = spills(steps);
  for (let i = at; i < order.length && spilling; i += 1) {
    const step = order[i];
    if (!may(step) || steps.includes(step)) continue;
    steps = inOrder(order, [...steps, step]);
    spilling = spills(steps);
  }
  return { steps, fits: !spilling };
}

/** The fewest steps of `order`, taken in order, after which `spills` says the row fits; every
 *  step that applies when it never does. `spills` is asked with the steps taken so far, starting
 *  from `from` (steps already taken, in order), and a step that does not apply at this width is
 *  passed over (it would change nothing on screen). */
export function walkSteps<S extends string>(
  order: readonly S[],
  spills: (steps: readonly S[]) => boolean,
  from: readonly S[] = [],
  applies: (step: S) => boolean = () => true,
): S[] {
  const at = from.length ? order.indexOf(from[from.length - 1]) + 1 : 0;
  return walk(order, spills, from, at, applies).steps;
}

/** The steps a fitted row keeps: each step of `steps` is taken back, the lossiest first (the last
 *  in `order` first), and stays back only where `fits` says the row still fits without it; a step
 *  `held` is never taken back. `fits` is asked with the steps that would be left. Deterministic:
 *  the same steps and the same answers give the same result, whatever came before. */
export function stepBack<S extends string>(
  order: readonly S[],
  steps: readonly S[],
  fits: (steps: readonly S[]) => boolean,
  held: (step: S) => boolean = () => false,
): S[] {
  let kept = inOrder(order, steps);
  for (const step of [...kept].reverse()) {
    if (held(step)) continue;
    const without = kept.filter((s) => s !== step);
    if (fits(without)) kept = without;
  }
  return kept;
}

export interface RowFit<S extends string> {
  /** Whether the row spills with these steps (the caller writes them on the row and measures). */
  spills: (steps: readonly S[]) => boolean;
  /** Whether the row fits with these steps once the walk has fitted it, for the steps taken back.
   *  Default: it does not spill. A row with a step whose loss grows as the room shrinks (a value cut
   *  further, a second line) says no where taking a step back would make that loss larger. */
  fitsBack?: (steps: readonly S[]) => boolean;
  /** Steps already taken, in order: the walk goes on from them (a fit afresh starts from none). */
  from?: readonly S[];
  /** Whether a step changes anything at this width; one that does not is never taken. */
  applies?: (step: S) => boolean;
  /** Steps held as they are while something on the row waits on them (the approval mode's pending
   *  confirmation): true, taken whatever the row needs; false, never taken. */
  held?: Partial<Record<S, boolean>>;
}

/** The steps a row takes: the walk (the least loss first, until nothing spills), then, if it fits,
 *  the steps it no longer needs taken back (`stepBack`), the lossiest first. A row that does not
 *  fit even with every step keeps them all: nothing is taken back from a spill. */
export function fitRow<S extends string>(order: readonly S[], fit: RowFit<S>): S[] {
  const { spills, from = [], applies = () => true } = fit;
  const held: Partial<Record<S, boolean>> = fit.held ?? {};
  const pinned = (step: S) => held[step] !== undefined;
  const base = [...from.filter((step) => !pinned(step)), ...order.filter((step) => held[step] === true)];
  const at = from.length ? order.indexOf(from[from.length - 1]) + 1 : 0;
  const walked = walk(order, spills, base, at, (step) => applies(step) && !pinned(step));
  if (!walked.fits) return walked.steps;
  return stepBack(order, walked.steps, fit.fitsBack ?? ((steps) => !spills(steps)), pinned);
}

/** The steps a row's data-fit lists, those of `order` only, in its order. */
export function stepsOf<S extends string>(row: Element, order: readonly S[]): S[] {
  const said = (row.getAttribute('data-fit') || '').split(' ');
  return order.filter((step) => said.includes(step));
}

/** Writes the steps on the row (no attribute when none is taken). */
export function writeSteps(row: Element, steps: readonly string[]): void {
  if (steps.length) row.setAttribute('data-fit', steps.join(' '));
  else row.removeAttribute('data-fit');
}

/** The attributes on <html> that change every width: the look, the typeface, the density, the language. */
const ROOT_ATTRIBUTES = ['data-look', 'data-font', 'data-density', 'lang'];

export interface FitWatchOptions {
  /** Attributes inside the row whose change changes a width (the row's own data-fit never is one). */
  readonly attributes: readonly string[];
  /** Boxes besides the row whose size, changing by itself, calls for a refit (the masthead's tools). */
  readonly sized?: (row: HTMLElement) => ReadonlyArray<Element | null>;
}

/** Keeps a row fitted (see the header): `fit` measures the row and writes its steps. */
export function useFitWatch(ref: RefObject<HTMLElement | null>, fit: (row: HTMLElement) => void, options: FitWatchOptions): void {
  const latest = useRef({ fit, options });
  latest.current = { fit, options };
  const attributes = options.attributes.join(' ');
  useLayoutEffect(() => {
    const row = ref.current;
    if (!row) return undefined;
    let live = true;
    let frame = 0;
    const sizes = new Map<Element, readonly [number, number]>();
    const watched = (): Element[] => [row, ...(latest.current.options.sized?.(row) ?? [])].filter((el): el is Element => !!el);
    const content = typeof MutationObserver === 'function' ? new MutationObserver(() => run()) : null;
    const run = () => {
      if (!live) return;
      if (frame) { cancelAnimationFrame(frame); frame = 0; }
      latest.current.fit(row);
      // the sizes the fit left, so the size observer can tell its own echo from a change
      sizes.clear();
      for (const el of watched()) {
        const r = el.getBoundingClientRect();
        sizes.set(el, [r.width, r.height]);
      }
      content?.takeRecords();
    };
    run();
    content?.observe(row, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: attributes.split(' ').filter(Boolean) });
    const looks = typeof MutationObserver === 'function' ? new MutationObserver(run) : null;
    looks?.observe(document.documentElement, { attributes: true, attributeFilter: ROOT_ATTRIBUTES });
    window.addEventListener('resize', run);
    const fonts = (document as Document & { fonts?: FontFaceSet }).fonts;
    fonts?.addEventListener?.('loadingdone', run);
    fonts?.ready?.then(run, () => {});
    const boxes = typeof ResizeObserver === 'function' ? new ResizeObserver(() => {
      if (!live || frame) return;
      const moved = watched().some((el) => {
        const was = sizes.get(el);
        const r = el.getBoundingClientRect();
        return !was || Math.abs(was[0] - r.width) > 0.5 || Math.abs(was[1] - r.height) > 0.5;
      });
      if (moved) frame = requestAnimationFrame(() => { frame = 0; run(); });
    }) : null;
    for (const el of watched()) boxes?.observe(el, { box: 'border-box' });
    return () => {
      live = false;
      if (frame) cancelAnimationFrame(frame);
      content?.disconnect();
      looks?.disconnect();
      boxes?.disconnect();
      window.removeEventListener('resize', run);
      fonts?.removeEventListener?.('loadingdone', run);
    };
  }, [ref, attributes]);
}
