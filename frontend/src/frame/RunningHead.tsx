/* The running head (PHASE_B_PLAN.md §4.2), div[data-frame="runhead"]: the six trust signals,
   then the approval mode and the interrupts — eight items, on every page, at every width.

     ≥ 2200px    long labels, long values (the ledger count, the checked and verified times)
     1680–2199   long labels, short values      1340–1679   short labels, short values
     1100–1339   compact: the signals' labels are read, not drawn (the value keeps its mark,
                 the button its name "Label: value", the popover the rest), one line
     760–1099    short labels, wraps to two lines
     ≤ 759       one line of marks (n-runhead--compact, from the media query below; §4.2, §5.1):
                 each signal is its mark, the approval mode its word ("Ask"), the interrupts their
                 count ("1 of 4"), an unread one the mark of its state. Every item is a button
                 named "Label: value" (the words it no longer draws) with its popover, which drops
                 below the whole running head, inside the window; the approval mode is changed in
                 its popover, with the same friction. Nothing is cut and nothing wraps (§11), and
                 nothing holds the head in another form below 760px.
   A source label's reason (the approval mode or the interrupts unread) is written from 1680px
   and read below it, with the whole sentence in its title. The approval mode's word is "Mode"
   below 1680px, and the interrupts drop "used today" there.
     'marks'     the 420px floating window and Glance: marks and short words, still all eight
                 items; there the approval mode is read, not changed (it is changed in the main
                 window's running head), and a signal's popover has no page link (the floating
                 window shows no other page). Below 760px the marks are the same one line of marks
                 as the frame's (measured at 420px, a mark and a short word per item took four
                 lines and ran past the window), the mode a read-only button named "Approval
                 mode: Ask" with its meaning in its popover. They never take more room than the
                 page gives them (Glance's foot), and from 1100px they fit themselves too.

   Fitting the line (from 1100px). The forms above are where each width starts; whether the
   eight items then fit depends on what they say (a cloud model with its ledger count, a long
   model id, Romanian, a look's label voice and type size, the density), not on the width alone.
   So the head measures itself (frame/fit.ts: before the first paint, then whenever its words,
   the width, a font, the look, typeface or density change, never on a render that changed
   nothing) and takes RUNHEAD_FIT_STEPS in order, the least loss first, until nothing spills; then
   it takes back, the lossiest first, every step a later one made unneeded (at 2560px the egress
   statement's short form frees more than the long labels the walk gave up before it), never so
   that a value is cut further or the items take more lines; and it writes them on the head
   (data-fit; frame.css draws each one). Overlap is impossible by construction, whatever a
   measurement says: no item is ever narrower than what it draws — its label when drawn, its mark,
   and at least an ellipsis of its value (frame.css). Every word a step takes off the screen stays
   in the button's name, its title and its popover.

   A value the spec keeps whole is measured in fractions of a pixel (fit.ts textCut): Chromium
   draws an ellipsis for an overflow of a layout unit, which whole-pixel widths cannot see.

   The approval mode is one tree in every form (the line, the fold, the marks), so a change of form
   never draws a control again elsewhere. While its looser choice waits for the second step the fit
   keeps the mode where the choice was asked (data-hold="line" | "fold": never folded when asked in
   the line, never unfolded when asked in a popover, from 760px), then refits once it is answered.
   The head itself always follows the window: below 760px it is the marks whatever waits, and what
   waits goes with the mode into the marks' popover, open, inside the window, the focus where it
   was. The hub's answer to a write holds nothing: where a fit folds the mode while it is on screen,
   the popover opens with it. When a fit or the window moves the mode, its popover closes with the
   fold, and a focus on a control the new form does not draw goes to the control that stands for it
   now (its button, or the checked radio). Whatever floats over the page (the popover, or in the
   line the confirmation and the answer) is kept inside the window (kit placeInside).

   Every signal is a disclosure: its button carries the mark and the value, its popover what it
   means, its basis and the time it was checked, and a link to the page that acts on it. The
   words are the signals engineer's (signals/trust-signals.ts): egress as a configuration ("No
   cloud model configured", declared), the local route as a count with its window and basis,
   never a bare %, the microphone, the model id with its backend, the data on screen (stale on
   its own when the loader stalls) and the audit chain (GET /api/security/audit/verify, 5 min).

   Approval mode: GET /autonomy/mode (admin, every 60 s, signals/hooks.ts useApprovalMode) drawn
   as Auto · Ask · Off. A stricter mode is one click; a looser one is two steps through
   ConfirmAction tier 1 ("Auto lets reversible actions run without asking."), whose confirming
   button takes only a fresh press: a held Enter's auto-repeat or the second click of a
   double-click never confirms (repeatConfirms={false}), in every form of the mode. Which of the two is
   decided on the hub's answer asked again at the click, never on the last poll: a mode changed
   since (in another tab, by the hub) could otherwise make a looser choice one click. A refused
   or unanswered read leaves it disabled and says why; demo disables it. A write the hub refuses
   is shown in the hub's terms, with the mode in force. No key changes the mode: arrow keys only
   move between the choices.
   Interrupts: GET /autonomy/interrupts (admin, every 60 s, useInterrupts): "1 of 4 used today",
   or Unknown. Like every signal it is a disclosure in every form: a button named with the whole
   reading ("Interrupts: 1 of 4 used today", where "used today" is not drawn below 1680px, after the
   "short" step and in the marks) whose popover says it and what the budget is. */
import React, { memo, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { setAutonomyMode } from '../api/actions';
import { ConfirmAction } from '../confirm';
import { parseHudRoute, routeHref } from '../hud-routing';
import { textOf } from '../nav/areas';
import { pageForRoute } from '../nav/routes';
import { refusalReason } from '../panel-kit';
import { useApprovalMode, useAuditVerify, useEgressLedger, useInterrupts } from '../signals/hooks';
import { pollSnapshot, refreshPolled } from '../signals/poll';
import { trustSignals } from '../signals/trust-signals';
import type { HubSnapshot, Reading, ReadingState, SignalView } from '../signals/types';
import { APPROVAL_MODE_VALUES, parseApprovalMode, type ApprovalModeReading, type ApprovalModeValue } from '../signals/wire';
import { inAppClick } from './AreaNav';
import { CUT_EPSILON, fitRow, mediaMatches, stepsOf, textCut, textOverflow, useFitWatch, writeSteps } from './fit';
import { Disclosure, KIT_STRINGS, Mark, SourceLabel, placeInside, reasonWords, stateWord, unplace, type MarkKind } from './kit';
import { RUNHEAD_STRINGS } from './frame-strings';
import { useStaleNow } from './stale-now';
import { fmt, pick, type Lang } from './strings';
import './frame.css';

/** How much each mode asks (agents/core/autonomy/mode.py _RANK): higher is stricter. */
const RANK: Record<ApprovalModeValue, number> = { auto: 0, ask: 1, off: 2 };

/** The width below which the running head is one line of marks (frame.css xxs). */
export const MARKS_QUERY = '(max-width: 759px)';

/* ---- fitting the line (from 1100px) ------------------------------------------------------------ */

/** What the running head gives up when its line is too narrow, in order, the least loss first,
 *  from the form its width starts in (the header). A step that would change nothing at a width, or
 *  in the marks variant, is passed over (runheadStepApplies; the marks take only source, tight, cut
 *  and lines):
 *
 *    source   a source label's reason and time are read, not drawn: the approval mode's and the
 *             interrupts' when not live ("Refused", the whole sentence in its title)  — from 1680px
 *    short    the short labels ("Local route", "Data", "Chain", "Mode") and the interrupts'
 *             count without "used today" (in its title)                               — from 1680px
 *    egress   the egress value's short form ("Cloud model configured"; the requests that left the
 *             machine and the provider are in its name and its popover)               — from 2200px
 *    values   every value's short form: the route without its window ("all time"), the data and
 *             the chain without the time they were checked (their popovers say both) — from 2200px
 *    tight    the items sit closer
 *    labels   the six signals' labels are read, not drawn: each value keeps its mark and its
 *             button the name "Label: value"; the approval mode and interrupts keep their keys
 *                                                                                     — from 1340px
 *    mode     the approval mode is its word ("Ask") or the mark of what is known, a button named
 *             "Approval mode: Ask"; the choice opens in its popover with the same friction (a
 *             looser mode is two steps there too, never one click)
 *    cut      the egress statement and the model id may be cut with an ellipsis inside their own
 *             button (its name, its title and its popover keep the whole value)
 *    lines    the last resort: the eight items take two lines
 *
 *  Each fit the page makes (fitRunningHead, with fit.ts fitRow) starts afresh from no step, so a
 *  width reached by narrowing the window takes the same steps as one reached by widening it, and
 *  has two parts:
 *
 *    the walk       the steps in this order, each taken only while the line still spills
 *                   (runheadSpills: an item past the line or over another, a part past its item's
 *                   box, or, before "cut", a value cut at all), until it fits. A line that spills
 *                   even with every step keeps them all.
 *    the step back  once the walk fits, the steps it took are taken back one at a time, the
 *                   lossiest first (the last in this order first), each only where the line still
 *                   fits without it and neither loss that grows as the room shrinks is larger than
 *                   the walk left it (runheadLoss: the px the free-length values are cut by, the
 *                   lines the items take). So a width keeps no step a later one made unneeded (at
 *                   2560px the egress statement's short form frees more than the long labels the
 *                   walk gave up before it), and no step is taken back at the price of cutting a
 *                   value further or adding a line: "labels", "tight" and "mode" are never traded
 *                   for a deeper cut or a second line. A "mode" held while the approval mode's
 *                   looser choice waits for its second step (data-hold) is left as it is by both.
 *
 *  A cut is measured in fractions of a pixel (fit.ts textOverflow, textCut): Chromium draws an
 *  ellipsis for an overflow of one layout unit, 1/64 of a device pixel, which the whole pixels of
 *  scrollWidth and clientWidth cannot see. Before "cut", a value whose text runs past its box by
 *  more than CUT_EPSILON spills, and the step back compares the cut in the same fractions.
 *
 *  The order is the one the second polish round measured, by what each step costs on screen: words
 *  a title, a button's name or a short form keeps go first; the spacing, which loses no word, before
 *  the labels, which take every signal's name off the line; folding the approval mode, whose word
 *  stays readable, before cutting a value, which makes it unreadable; two lines last. Which steps
 *  each width keeps, look by look and in both languages, is measured by the render matrix
 *  (e2e/ledger-shots.spec.ts, runhead-fit) and kept in its run records
 *  (e2e/artifacts/ledger/runs/<run>/runhead-fit-*.json), not here. */
export const RUNHEAD_FIT_STEPS = ['source', 'short', 'egress', 'values', 'tight', 'labels', 'mode', 'cut', 'lines'] as const;
export type RunheadFitStep = typeof RUNHEAD_FIT_STEPS[number];

/** The form a width starts in: xl ≥ 2200, l 1680–2199, m 1340–1679, s 1100–1339; null below 1100,
 *  where the head is not fitted (two lines from 760px, one line of marks below). */
export type RunheadForm = 'xl' | 'l' | 'm' | 's';
const FORMS: ReadonlyArray<readonly [RunheadForm, number]> = [['xl', 2200], ['l', 1680], ['m', 1340], ['s', 1100]];
export function runheadForm(): RunheadForm | null {
  for (const [form, px] of FORMS) if (mediaMatches(`(min-width: ${px}px)`, () => window.innerWidth >= px)) return form;
  return null;
}

const EVERY: readonly RunheadForm[] = ['xl', 'l', 'm', 's'];
const STEP_FORMS: Record<RunheadFitStep, readonly RunheadForm[]> = {
  source: ['xl', 'l'], short: ['xl', 'l'], egress: ['xl'], values: ['xl'], labels: ['xl', 'l', 'm'], tight: EVERY, mode: EVERY, cut: EVERY, lines: EVERY,
};
/** The marks (Glance, the floating window) draw no label, no long value and no choice: only a
 *  source label's reason, their spacing, the cut and the second line apply to them. */
const MARKS_STEPS: readonly RunheadFitStep[] = ['source', 'tight', 'cut', 'lines'];

/** Whether a step changes anything on screen in a form (and a variant). */
export function runheadStepApplies(step: RunheadFitStep, form: RunheadForm, variant: 'full' | 'marks' = 'full'): boolean {
  if (variant === 'marks' && !MARKS_STEPS.includes(step)) return false;
  return STEP_FORMS[step].includes(form);
}

/** The eight items, and what each draws (a part 1px wide or less is read, not drawn). */
const ITEMS = '[data-signal], [data-runhead="mode"], [data-runhead="interrupts"]';
const PARTS = ':scope > dt, :scope > dd, .n-signals__button, .n-runhead__key, .n-runhead__seg, .n-runhead__fold, .n-runhead__said, .n-runhead__figure';
/** What opens over the head rather than in its line: never measured as part of an item. */
const POPOVERS = '.n-disclosure__panel, .n-runhead__pop';

const overlaps = (a: DOMRect, b: DOMRect): boolean =>
  Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.5 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5;

/** The free-length values a step may cut with an ellipsis (the egress statement, the model id and
 *  its backend), drawn in the line (not in a popover). */
const cutValues = (head: HTMLElement): HTMLElement[] =>
  Array.from(head.querySelectorAll<HTMLElement>('.n-signals__ident, .n-signals__text')).filter((el) => !el.closest(POPOVERS));

/** Whether the running head's line spills: an item past the head's line or under another, a part
 *  of an item past the item's box, or (before the "cut" step) a value cut with an ellipsis — by as
 *  little as a layout unit (fit.ts textCut), since Chromium draws the ellipsis for any overflow. */
export function runheadSpills(head: HTMLElement): boolean {
  const steps = stepsOf(head, RUNHEAD_FIT_STEPS);
  const folded = steps.includes('mode');
  const style = getComputedStyle(head);
  const line = head.getBoundingClientRect();
  const left = line.left + (parseFloat(style.paddingLeft) || 0) - 1;
  const right = line.right - (parseFloat(style.paddingRight) || 0) + 1;
  const items = Array.from(head.querySelectorAll<HTMLElement>(ITEMS));
  const boxes = items.map((item) => item.getBoundingClientRect());
  for (let i = 0; i < items.length; i += 1) {
    const box = boxes[i];
    if (box.width <= 0) continue;
    if (box.left < left || box.right > right) return true;
    for (const part of Array.from(items[i].querySelectorAll<HTMLElement>(PARTS))) {
      if (part.closest(POPOVERS) || (folded && part.closest('.n-runhead__box'))) continue;
      const r = part.getBoundingClientRect();
      if (r.width <= 1) continue;
      if (r.left < box.left - 1 || r.right > box.right + 1) return true;
    }
    for (let j = 0; j < i; j += 1) if (boxes[j].width > 0 && overlaps(box, boxes[j])) return true;
  }
  if (!steps.includes('cut') && cutValues(head).some(textCut)) return true;
  return false;
}

/** What the steps whose loss grows as the room shrinks give up with the steps written: the px the
 *  free-length values are cut by ("cut" lets them be cut; measured in fractions of a pixel, fit.ts
 *  textOverflow) and the lines the items take ("lines" lets them wrap). Taking a step back may not
 *  make either larger. */
export function runheadLoss(head: HTMLElement): { cut: number; lines: number } {
  let cut = 0;
  for (const el of cutValues(head)) cut += textOverflow(el);
  const boxes = Array.from(head.querySelectorAll<HTMLElement>(ITEMS)).map((item) => item.getBoundingClientRect()).filter((r) => r.width > 0 && r.height > 0);
  const middles = boxes.map((r) => r.top + r.height / 2).sort((a, b) => a - b);
  const half = boxes.length ? Math.min(...boxes.map((r) => r.height)) / 2 : 0;
  let lines = middles.length ? 1 : 0;
  for (let i = 1; i < middles.length; i += 1) if (middles[i] - middles[i - 1] > half) lines += 1;
  return { cut, lines };
}

/** The event a fit sends the approval mode when it folds or unfolds it (detail: { folded }). */
export const MODE_FOLD_EVENT = 'n-runhead-modefold';

/** Where a looser choice waiting for its second step was asked, as the approval mode's data-hold
 *  says it: in the line, or in a popover (the fold's, or below 760px the mark's). The fit keeps the
 *  mode there while it waits: never folded when asked in the line, never unfolded when asked in a
 *  popover (folded from 760px, wherever the window goes). */
export type ModeHold = 'line' | 'fold';

/** The control that stands for the approval mode in a form: its button (the fold's, which is also
 *  its mark below 760px), or the checked radio (the one in the tab order where none is checked, the
 *  group where every radio is disabled). */
function modeControl(mode: HTMLElement, button: boolean): HTMLElement | null {
  if (button) return mode.querySelector<HTMLElement>('.n-runhead__fold');
  const radios = Array.from(mode.querySelectorAll<HTMLButtonElement>('[role="radio"]')).filter((r) => !r.disabled);
  return radios.find((r) => r.getAttribute('aria-checked') === 'true') ?? radios.find((r) => r.tabIndex === 0)
    ?? mode.querySelector<HTMLElement>('[role="radiogroup"]');
}

/** A focus that was in the approval mode, on a control its form no longer draws, goes to the control
 *  that stands for it now (`button`: the fold's or the mark's) rather than to the page. A focus still
 *  drawn (the confirmation, which every form draws) stays where it is. */
function keepModeFocus(mode: HTMLElement, button: boolean): void {
  const active = document.activeElement;
  if (active instanceof HTMLElement && mode.contains(active) && active.getClientRects().length > 0) return;
  modeControl(mode, button)?.focus();
}

/** A fit folded or unfolded the approval mode: the mode is told (its popover closes with the fold,
 *  or opens with it on the hub's answer), and a focus that was in it follows it (keepModeFocus). */
function modeMoved(mode: HTMLElement, folded: boolean, focusIn: boolean): void {
  mode.dispatchEvent(new CustomEvent(MODE_FOLD_EVENT, { detail: { folded } }));
  if (focusIn) keepModeFocus(mode, folded);
}

/** Fits the running head's line (RUNHEAD_FIT_STEPS), synchronously (call it before a paint): the
 *  walk, then the steps it no longer needs taken back (fit.ts fitRow). `fresh` starts again from
 *  the width's form; otherwise it goes on from the steps taken. While the approval mode's looser
 *  choice waits for its second step (data-hold), its "mode" step is held where the choice was asked:
 *  unfolded for one asked in the line, folded for one asked in a popover — below 1100px too, where
 *  no other step is drawn. */
export function fitRunningHead(head: HTMLElement, { fresh = true, form = runheadForm(), variant = 'full' }:
  { fresh?: boolean; form?: RunheadForm | null; variant?: 'full' | 'marks' } = {}): void {
  const before = stepsOf(head, RUNHEAD_FIT_STEPS);
  const mode = variant === 'full' ? head.querySelector<HTMLElement>('[data-runhead="mode"]:not([data-compact])') : null;
  const hold = mode?.getAttribute('data-hold');
  const active = typeof document !== 'undefined' ? document.activeElement : null;
  const focusIn = !!mode && active instanceof HTMLElement && mode.contains(active);
  if (fresh || !form) writeSteps(head, []);
  if (form) {
    const holds = (hold === 'line' || hold === 'fold') && runheadStepApplies('mode', form, variant);
    let walked: { cut: number; lines: number } | null = null;
    const steps = fitRow(RUNHEAD_FIT_STEPS, {
      spills: (tried) => { writeSteps(head, tried); return runheadSpills(head); },
      fitsBack: (tried) => {
        // the walk's own steps are still written at the first try: their loss is the bar
        const bar = walked ?? (walked = runheadLoss(head));
        writeSteps(head, tried);
        if (runheadSpills(head)) return false;
        const loss = runheadLoss(head);
        return loss.cut <= bar.cut + CUT_EPSILON && loss.lines <= bar.lines;
      },
      from: fresh ? [] : before,
      applies: (step) => runheadStepApplies(step, form, variant),
      held: holds ? { mode: hold === 'fold' } : undefined,
    });
    writeSteps(head, steps);
  } else if (hold === 'fold') {
    // below 1100px no step is drawn, but a choice asked in a popover keeps its popover: the mode
    // stays folded (frame.css draws "mode" there only then) until the choice is answered
    writeSteps(head, ['mode']);
  }
  const folded = stepsOf(head, RUNHEAD_FIT_STEPS).includes('mode');
  if (mode && folded !== before.includes('mode')) modeMoved(mode, folded, focusIn);
}

/** What, inside the head, changes a width when it changes: a reading's state (its weight), the
 *  mode's choice (semibold), a source label's state, a control enabled or not, the head's form; and
 *  the approval mode's hold (released, the head refits). Its words are watched as text. */
const RUNHEAD_ATTRIBUTES = ['class', 'data-state', 'data-source-state', 'data-mode', 'aria-checked', 'disabled', 'data-hold'];
const refitFull = (head: HTMLElement) => fitRunningHead(head, { variant: 'full' });
const refitMarks = (head: HTMLElement) => fitRunningHead(head, { variant: 'marks' });

/** Whether the window is narrower than 760px, following changes. Where the DOM cannot say (no
 *  matchMedia, as in a test DOM) it is not. */
function useNarrow(): boolean {
  const list = () => {
    try {
      return typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(MARKS_QUERY) || null : null;
    } catch {
      return null;
    }
  };
  const [narrow, setNarrow] = useState(() => !!list()?.matches);
  useEffect(() => {
    const media = list();
    if (!media) return undefined;
    const update = () => setNarrow(!!media.matches);
    update();
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update);
      return () => media.removeEventListener('change', update);
    }
    media.addListener?.(update);
    return () => media.removeListener?.(update);
  }, []);
  return narrow;
}

/** The mark an unread approval mode or interrupt budget is drawn with, as its source label draws it. */
const STATE_MARK: Record<ReadingState, MarkKind> = {
  live: 'ok', empty: 'idle', stale: 'stale', unknown: 'unknown', refused: 'blocked', offline: 'unknown', demo: 'idle', disabled: 'idle',
};
/** The path and credential useApprovalMode reads, so asking again shares its request. */
const APPROVAL_MODE_PATH = '/autonomy/mode';

/** Whether moving from one mode to another asks less (needs the two-step confirmation). */
export function isLooser(from: ApprovalModeValue, to: ApprovalModeValue): boolean {
  return RANK[to] < RANK[from];
}

/** The mode a reading shows: only a current answer (live, or stale and said so). */
function shownMode(reading: Pick<Reading<ApprovalModeReading>, 'state' | 'value'>): ApprovalModeValue | null {
  return (reading.state === 'live' || reading.state === 'stale') && reading.value ? reading.value.mode : null;
}

/** The mode in force as the hub says it now: asked again (the shared reading updates with it),
 *  or null when it does not answer with one. */
async function modeNow(): Promise<ApprovalModeValue | null> {
  try { await refreshPolled(APPROVAL_MODE_PATH, { admin: true }); } catch { return null; }
  const snap = pollSnapshot(APPROVAL_MODE_PATH, { admin: true });
  if (snap.outcome !== 'ok' || !snap.hasRaw) return null;
  try { return parseApprovalMode(snap.raw).mode; } catch { return null; }
}

function modeWord(mode: ApprovalModeValue, lang: Lang): string {
  const s = pick(RUNHEAD_STRINGS, lang);
  return mode === 'auto' ? s.auto : mode === 'ask' ? s.ask : s.off;
}

function modeMeaning(mode: ApprovalModeValue, lang: Lang): string {
  const s = pick(RUNHEAD_STRINGS, lang);
  return mode === 'auto' ? s.autoMeaning : mode === 'ask' ? s.askMeaning : s.offMeaning;
}

/** What to say when the hub answered a mode write with a refusal (null when it took). */
export function modeRefusalText(asked: ApprovalModeValue, answer: unknown, lang: Lang): string | null {
  if (!answer || typeof answer !== 'object' || typeof (answer as { error?: unknown }).error !== 'string') return null;
  const s = pick(RUNHEAD_STRINGS, lang);
  const r = answer as { error: string; live?: unknown; mode?: unknown };
  const known = (v: unknown): v is ApprovalModeValue => typeof v === 'string' && (APPROVAL_MODE_VALUES as readonly string[]).includes(v);
  const live = known(r.live) ? r.live : known(r.mode) ? r.mode : null;
  const mode = modeWord(asked, lang);
  const first = r.error === 'mode_not_saved' ? fmt(s.modeNotSaved, { mode })
    : r.error === 'mode_not_effective' ? fmt(s.modeNotEffective, { mode })
      : r.error === 'managed' ? fmt(s.modeManaged, { mode })
        : fmt(s.modeRefused, { mode, reason: r.error });
  return live ? `${first} ${fmt(s.modeInForce, { mode: modeWord(live, lang) })}` : first;
}

/** A source label's whole sentence ("Unknown — switched off on the hub"), for the title it keeps
 *  where its reason is read rather than drawn (below 1680px). */
export function sourceSentence(reading: Pick<Reading<unknown>, 'state' | 'reason' | 'status'>, lang: Lang): string {
  if (reading.state === 'unknown' && reading.reason === 'checking') return pick(KIT_STRINGS, lang).checking;
  const why = reading.state === 'unknown' || reading.state === 'refused' ? reasonWords(reading.reason, lang, reading.status) : null;
  return why ? `${stateWord(reading.state, lang)} — ${why}` : stateWord(reading.state, lang);
}

/** What to say when a mode write failed outright (refused by the guard, managed, no answer). */
function modeFailureText(asked: ApprovalModeValue, err: unknown, lang: Lang): string {
  const fromBody = modeRefusalText(asked, (err as { body?: unknown } | null)?.body, lang);
  if (fromBody) return fromBody;
  const s = pick(RUNHEAD_STRINGS, lang);
  return fmt(s.modeRefused, { mode: modeWord(asked, lang), reason: refusalReason(err) });
}

/** The page a signal's `href` opens, named as the registry names it ("Model setup"). */
function SignalLink({ href, lang, navigate }: { href: string; lang: Lang; navigate?: (path: string) => void }) {
  const route = parseHudRoute(href);
  if (!route.valid) return null;
  const label = textOf(pageForRoute(route).entry.label, lang);
  return (
    <a className="n-link n-signals__link" href={routeHref(href)}
      onClick={(event) => { if (!navigate || !inAppClick(event)) return; event.preventDefault(); navigate(href); }}>{label}</a>
  );
}

function SignalItem({ view, lang, variant, compact, navigate, links }: {
  view: SignalView; lang: Lang; variant: 'full' | 'marks'; compact: boolean; navigate?: (path: string) => void; links: boolean;
}) {
  const s = pick(RUNHEAD_STRINGS, lang);
  const name = fmt(s.signalItem, { label: view.label.long, value: [view.ident, view.value.long].filter(Boolean).join(' ') });
  return (
    <div className="n-signals__item" data-signal={view.id} data-state={view.state}>
      {variant === 'full' && !compact ? (
        <dt className="n-signals__label">
          <span data-show-from="l">{view.label.long}</span>
          <span data-show-from="xs" data-show-upto="m">{view.label.short}</span>
        </dt>
      ) : <dt data-visually-hidden="">{view.label.long}</dt>}
      <dd className="n-signals__value">
        {/* below 760px the mark alone: its words are the button's name and the popover's; the
            popover stays inside the window (above its button where below would leave it: Glance's foot) */}
        <Disclosure ariaLabel={name} title={name} buttonClassName={compact ? 'n-signals__button n-runhead__button' : 'n-signals__button'} contain
          label={compact ? <Mark kind={view.mark} size="sm" lang={lang} /> : <>
            <Mark kind={view.mark} size="sm" lang={lang} />
            {view.ident && <code className="n-signals__ident">{view.ident}</code>}
            {variant === 'full' ? <>
              <span className="n-signals__text" data-show-from="xl">{view.value.long}</span>
              <span className="n-signals__text" data-show-from="xs" data-show-upto="l">{view.value.short}</span>
              <span className="n-signals__text" data-show-upto="xxs">{view.value.marks}</span>
            </> : <span className="n-signals__text">{view.value.marks}</span>}
          </>}>
          <p className="n-signals__detail-title">{view.label.long}</p>
          {/* the value the button no longer draws, whole */}
          {compact && (
            <p className="n-signals__said">
              <Mark kind={view.mark} size="sm" lang={lang} />
              {view.ident && <code className="n-signals__ident">{view.ident}</code>}
              <span>{view.value.long}</span>
            </p>
          )}
          <ul className="n-signals__detail">{view.detail.map((line, i) => <li key={i}>{line}</li>)}</ul>
          {view.href && links && <SignalLink href={view.href} lang={lang} navigate={navigate} />}
        </Disclosure>
      </dd>
    </div>
  );
}

/** The approval mode in the main window's running head, in one tree for every form: from 760px the
 *  key and the choice in the line, or — folded by the fit (the "mode" step), and always below 760px —
 *  a button with the mode in force as its word (or the mark of what is known instead), named
 *  "Approval mode: Ask", whose popover holds the same choice, source and friction. frame.css draws
 *  each form from the head's class and data-fit; only one of the two is ever drawn. Because every
 *  form is the same tree, a change of form never draws a control again elsewhere: a confirmation
 *  waiting for its second step keeps its place in the tree and its focus wherever the window goes. */
function ApprovalMode({ lang, demo, compact }: { lang: Lang; demo: boolean; compact: boolean }) {
  const s = pick(RUNHEAD_STRINGS, lang);
  const reading = useApprovalMode({ demo });
  const [pending, setPending] = useState<ApprovalModeValue | null>(null);
  // where the looser choice was asked (the line, or a popover): the fit keeps the mode there while it
  // waits for the second step (data-hold)
  const [asked, setAsked] = useState<ModeHold>('line');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // the popover the owner opened (the fold's, or the mark's below 760px)
  const [open, setOpen] = useState(false);
  // the radio to take the focus once a written choice's confirmation has left the screen
  const [refocus, setRefocus] = useState<ApprovalModeValue | null>(null);
  const radios = useRef<Partial<Record<ApprovalModeValue, HTMLButtonElement | null>>>({});
  const root = useRef<HTMLDivElement>(null);
  const fold = useRef<HTMLButtonElement>(null);
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const labelId = `n-runhead-mode-${uid}`;
  const boxId = `n-runhead-modebox-${uid}`;
  const current = shownMode(reading);
  const usable = current !== null && !demo;
  // read by the listeners, which outlive a render
  const live = useRef({ compact, note });
  live.current = { compact, note };
  /** Whether the head has folded the mode into its word (frame.css draws the "mode" step). */
  const folded = () => !!root.current?.closest('[data-frame="runhead"]')?.matches('[data-fit~="mode"]');
  /** Whether the mode is drawn as a button with a popover now: below 760px, or folded by the fit. */
  const asButton = () => live.current.compact || folded();
  // What waits in the mode is never hidden by a change of form: below 760px the popover is open while
  // a confirmation or the hub's answer is in it, and a choice asked in a popover keeps it open
  // wherever the window goes (the fit keeps that mode folded from 760px).
  const popover = open || (pending !== null && (compact || asked === 'fold')) || (compact && note !== null);
  /** Closing the popover drops a looser choice that was not confirmed (nothing is written) and the
   *  hub's answer it showed. */
  const close = (focusButton = false) => {
    setOpen(false);
    setPending(null);
    setNote(null);
    if (focusButton) fold.current?.focus();
  };
  // the fit unfolded the mode: its popover goes with the fold (an open state would otherwise survive
  // into the line, and come back open on the next fold); it folded the mode while the hub's answer is
  // on screen: the popover opens, so the answer is still seen
  useEffect(() => {
    const el = root.current;
    if (!el) return undefined;
    const onFold = (event: Event) => {
      if (!(event as CustomEvent<{ folded?: boolean }>).detail?.folded) setOpen(false);
      else if (live.current.note !== null) setOpen(true);
    };
    el.addEventListener(MODE_FOLD_EVENT, onFold);
    return () => el.removeEventListener(MODE_FOLD_EVENT, onFold);
  }, []);
  // a press outside closes the popover, and only that: a confirmation or an answer drawn in the line
  // stays until it is answered or closed there
  useEffect(() => {
    if (!popover) return undefined;
    const away = (event: MouseEvent) => {
      if (!root.current || !(event.target instanceof Node) || root.current.contains(event.target)) return;
      if (asButton()) close(); else setOpen(false);
    };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [popover]);   // eslint-disable-line react-hooks/exhaustive-deps
  const say = (words: string) => {
    setNote(words);
    // a refusal that lands while the mode is folded opens its popover, so it is seen (below 760px the
    // popover opens with it by itself)
    if (folded()) setOpen(true);
  };
  // The window crossed 760px: the head follows it (§4.2: below 760px one line of marks), and the
  // mode goes with the head. What waits in it goes along — the same controls, never drawn again —
  // in the marks' popover below 760px; from 760px in the line, or in the fold's popover where the
  // choice was asked in one. A focus on a control the new form does not draw goes to the control that
  // stands for the mode there (its button, or the checked radio), never to the page.
  const formWas = useRef(compact);
  const focusWas = useRef(false);
  if (formWas.current !== compact) {
    const active = typeof document !== 'undefined' ? document.activeElement : null;
    focusWas.current = !!root.current && !!active && root.current.contains(active);
    formWas.current = compact;
  }
  useLayoutEffect(() => {
    if (compact) { if (pending !== null || note !== null) setOpen(true); }
    else setOpen(pending !== null && asked === 'fold');
    if (!focusWas.current) return;
    focusWas.current = false;
    if (root.current) keepModeFocus(root.current, compact || folded());
  }, [compact]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!refocus) return;
    setRefocus(null);
    const active = document.activeElement;
    if (active && active !== document.body && !root.current?.contains(active)) return;   // the owner went elsewhere
    const radio = radios.current[refocus];
    if (radio && !radio.disabled) radio.focus();
    if (root.current && document.activeElement !== radio) modeControl(root.current, asButton())?.focus();
  }, [refocus]);   // eslint-disable-line react-hooks/exhaustive-deps
  // What floats over the page — the popover, or in the line the confirmation and the hub's answer —
  // is kept inside the window (kit placeInside: below, or above where below would leave it, moved in
  // from an edge it would cross), when it is drawn or changes, when the window is resized and when a
  // fit moves the mode. In the line the box lays its parts out in the line (display: contents) and
  // the confirmation floats; as a popover the box floats and the confirmation sits in its flow.
  const shown = popover || pending !== null || note !== null;
  useLayoutEffect(() => {
    const el = root.current;
    if (!shown || !el) return undefined;
    const parts = () => {
      const box = el.querySelector<HTMLElement>(':scope > .n-runhead__box');
      return { box, pops: box ? Array.from(box.querySelectorAll<HTMLElement>(':scope > .n-runhead__pop')) : [] };
    };
    const place = () => {
      const { box, pops } = parts();
      if (!box) return;
      if (getComputedStyle(box).display === 'contents') {
        unplace(box);
        pops.forEach(placeInside);
      } else {
        pops.forEach(unplace);
        placeInside(box);
      }
    };
    place();
    let frame = 0;
    const later = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(place); };
    window.addEventListener('resize', later);
    el.addEventListener(MODE_FOLD_EVENT, later);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', later);
      el.removeEventListener(MODE_FOLD_EVENT, later);
      // as the stylesheet places them, until they are drawn again
      const { box, pops } = parts();
      if (box) unplace(box);
      pops.forEach(unplace);
    };
  }, [shown, popover, pending, note, compact, busy]);

  const focusCurrent = () => { if (current) radios.current[current]?.focus(); };
  const write = async (mode: ApprovalModeValue) => {
    const was = current;
    let took = false;
    setBusy(true);
    setNote(null);
    try {
      const answer = await setAutonomyMode(mode);
      const refusal = modeRefusalText(mode, answer, lang);
      if (refusal) say(refusal); else took = true;
    } catch (err) {
      say(modeFailureText(mode, err, lang));
    } finally {
      setBusy(false);
      setPending(null);
      // the confirmation that had the focus leaves the screen: the focus goes to the mode written,
      // or back to the one still in force
      setRefocus(took ? mode : was);
    }
    try { await reading.refresh(); } catch { /* the reading says what is known */ }
  };
  const choose = async (mode: ApprovalModeValue) => {
    if (!usable || busy || !current || mode === current) return;
    setBusy(true);
    setNote(null);
    // the friction is decided on the mode in force now, not on the last poll
    const from = await modeNow();
    if (from === null || mode === from) { setBusy(false); return; }
    if (isLooser(from, mode)) {
      setBusy(false);
      setAsked(asButton() ? 'fold' : 'line');
      setPending(mode);
      return;
    }
    await write(mode);
  };
  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const focused = APPROVAL_MODE_VALUES.findIndex((m) => radios.current[m] === document.activeElement);
    const at = focused < 0 ? 0 : focused;
    radios.current[APPROVAL_MODE_VALUES[(at + step + APPROVAL_MODE_VALUES.length) % APPROVAL_MODE_VALUES.length]]?.focus();
  };
  const showSource = demo || reading.state !== 'live';
  const name = fmt(s.signalItem, { label: s.mode, value: current ? modeWord(current, lang) : sourceSentence(reading, lang) });
  return (
    <div ref={root} className="n-runhead__mode" data-runhead="mode" data-compact={compact ? '' : undefined}
      data-open={popover ? '' : undefined} data-hold={pending !== null ? asked : undefined}
      onKeyDown={(event) => {
        if (event.key !== 'Escape' || !popover || !asButton()) return;
        event.preventDefault();
        event.stopPropagation();   // this popover's Escape, not an overlay's beneath it
        close(true);
      }}>
      {!compact && (
        <span className="n-runhead__key" id={labelId} title={s.mode}>
          <span data-show-from="l">{s.mode}</span>
          <span data-show-upto="m">{s.modeShort}</span>
        </span>
      )}
      <button ref={fold} type="button" className="n-runhead__fold" aria-expanded={popover} aria-controls={boxId}
        aria-label={name} title={current ? `${name}. ${modeMeaning(current, lang)}` : name}
        onClick={() => { if (popover) close(); else setOpen(true); }}>
        {current
          ? <b className="n-runhead__figure" data-mode={current}>{modeWord(current, lang)}</b>
          : <Mark kind={STATE_MARK[reading.state]} size="sm" lang={lang} />}
      </button>
      {/* below 760px, closed, the popover is not in the page's reading order either (hidden) */}
      <div className="n-runhead__box" id={boxId} hidden={compact && !popover ? true : undefined}>
        <p className="n-signals__detail-title n-runhead__box-title">{s.mode}</p>
        {/* the group itself takes the focus (tabIndex -1: never in the tab order) only where a change
            of form moves the mode while every radio is disabled (the mode unread, or demo) */}
        <div className="n-seg n-runhead__seg" role="radiogroup" aria-label={s.mode} aria-busy={busy || undefined} tabIndex={-1} onKeyDown={onKeyDown}>
          {APPROVAL_MODE_VALUES.map((mode) => (
            // while a choice is being checked or written the radios stay focusable (aria-disabled,
            // and choose() ignores the click), so a keyboard user's focus is not dropped
            <button key={mode} ref={(el) => { radios.current[mode] = el; }} type="button" role="radio" data-mode={mode}
              aria-checked={current === mode} tabIndex={(current ?? 'auto') === mode ? 0 : -1}
              title={modeMeaning(mode, lang)} disabled={!usable} aria-disabled={busy || undefined} onClick={() => { void choose(mode); }}>
              {modeWord(mode, lang)}
            </button>
          ))}
        </div>
        {showSource && <span className="n-runhead__said" title={sourceSentence(reading, lang)}><SourceLabel reading={reading} lang={lang} className="n-runhead__source" /></span>}
        {/* One confirmation for every form. Only a fresh press confirms it (repeatConfirms={false},
            as every other loosening or signing control): the press that chose the looser mode moves
            the focus onto "Switch to Auto" (confirm.tsx), so a key held down on the radio, or a
            double-click, would otherwise choose and confirm in one gesture. */}
        {pending && current && (
          <div className="n-runhead__pop" data-runhead="confirm">
            <ConfirmAction tier={1} armed block repeatConfirms={false} label={modeWord(pending, lang)} ariaLabel={s.confirming} groupLabel={s.confirming}
              prompt={pending === 'auto' ? s.toAuto : s.toAsk}
              armedLabel={fmt(s.switchTo, { mode: modeWord(pending, lang) })} cancelLabel={s.cancel}
              className="n-btn n-btn--sm n-btn--quiet" confirmClassName="n-btn n-btn--sm n-btn--primary"
              onCancel={() => { setPending(null); focusCurrent(); }}
              onConfirm={() => write(pending)} />
          </div>
        )}
        {note && (
          <div className="n-runhead__pop n-runhead__pop--note" role="alert" data-runhead="mode-note">
            <span>{note}</span>
            <button type="button" className="n-btn n-btn--sm n-btn--quiet" onClick={() => { setNote(null); focusCurrent(); }}>{s.close}</button>
          </div>
        )}
      </div>
    </div>
  );
}

/** The approval mode where it is read, not changed (the floating window, Glance): the mode in
 *  force in a short word, its meaning in the title, and what is known instead when it is not
 *  (its reason read, not drawn, below 1680px, as in the main head; its title says it). Below 760px
 *  (the 420px floating window) it is one mark among the line's marks, as the main head's is there:
 *  a button named "Approval mode: Ask" whose popover says the mode, its meaning or its source,
 *  still with no choice in it. */
function ApprovalModeReadout({ lang, demo, compact }: { lang: Lang; demo: boolean; compact: boolean }) {
  const s = pick(RUNHEAD_STRINGS, lang);
  const reading = useApprovalMode({ demo });
  const current = shownMode(reading);
  const unread = demo || reading.state !== 'live';
  if (compact) {
    const name = fmt(s.signalItem, { label: s.mode, value: current ? modeWord(current, lang) : sourceSentence(reading, lang) });
    return (
      <div className="n-runhead__mode" data-runhead="mode" data-readonly="" data-compact="">
        <Disclosure ariaLabel={name} title={current ? `${name}. ${modeMeaning(current, lang)}` : name}
          buttonClassName="n-signals__button n-runhead__button" contain
          label={current
            ? <b className="n-runhead__figure" data-mode={current}>{modeWord(current, lang)}</b>
            : <Mark kind={STATE_MARK[reading.state]} size="sm" lang={lang} />}>
          <p className="n-signals__detail-title">{s.mode}</p>
          {current && <p className="n-signals__said"><b data-mode={current}>{modeWord(current, lang)}</b></p>}
          {current && <ul className="n-signals__detail"><li>{modeMeaning(current, lang)}</li></ul>}
          {unread && <span className="n-runhead__said"><SourceLabel reading={reading} lang={lang} showTime={false} className="n-runhead__source" /></span>}
        </Disclosure>
      </div>
    );
  }
  return (
    <div className="n-runhead__mode" data-runhead="mode" data-readonly="" title={current ? modeMeaning(current, lang) : undefined}>
      <span className="n-runhead__key">
        <span data-visually-hidden="">{s.mode}</span>
        <span aria-hidden="true">{s.modeShort}</span>
      </span>
      {current && <b className="n-runhead__figure" data-mode={current}>{modeWord(current, lang)}</b>}
      {unread && (
        <span className="n-runhead__said" title={sourceSentence(reading, lang)}>
          <SourceLabel reading={reading} lang={lang} showTime={false} className="n-runhead__source" />
        </span>
      )}
    </div>
  );
}

/** The interrupt budget, in every form a disclosure like the signals: a button named with the whole
 *  reading ("Interrupts: 1 of 4 used today") and a popover that says it and what the budget is.
 *  What the button draws is unchanged by being a button (the kit's button has no padding, border
 *  or gap of its own around one part), so the fit measures the same width as before. */
function Interrupts({ lang, demo, variant, compact }: { lang: Lang; demo: boolean; variant: 'full' | 'marks'; compact: boolean }) {
  const s = pick(RUNHEAD_STRINGS, lang);
  const reading = useInterrupts({ demo });
  const value = (reading.state === 'live' || reading.state === 'stale') ? reading.value : null;
  const known = value && value.used !== null && value.perDay !== null ? { used: value.used, perDay: value.perDay } : null;
  const unread = reading.state === 'live' || reading.state === 'stale' ? { state: 'unknown' as const, reason: 'not-reported' as const, lastGoodAt: null } : reading;
  const said = known ? fmt(s.interruptsUsed, known) : sourceSentence(unread, lang);
  const name = fmt(s.signalItem, { label: s.interrupts, value: said });
  const detail = <>
    <p className="n-signals__detail-title">{s.interrupts}</p>
    <ul className="n-signals__detail"><li>{said}</li><li>{s.interruptsDetail}</li></ul>
  </>;
  if (compact) {
    // below 760px: the count ("1 of 4") or the mark of what is known instead
    return (
      <div className="n-runhead__interrupts" data-runhead="interrupts" data-compact="">
        <Disclosure ariaLabel={name} title={name} buttonClassName="n-signals__button n-runhead__button" contain
          label={known
            ? <b className="n-runhead__figure">{fmt(s.interruptsShort, known)}</b>
            : <Mark kind={STATE_MARK[unread.state]} size="sm" lang={lang} />}>
          {detail}
        </Disclosure>
      </div>
    );
  }
  // from 760px: the key, then the count — "used today" drawn from 1680px until the "short" step,
  // never in the marks — or the source label of what is known instead (its reason read, not
  // drawn, below 1680px and after the "source" step); the popover opens towards the line's end
  return (
    <div className="n-runhead__interrupts" data-runhead="interrupts">
      <span className="n-runhead__key">{s.interrupts}</span>
      <Disclosure ariaLabel={name} title={name} align="end" contain buttonClassName="n-signals__button"
        label={known ? (
          <b className="n-runhead__figure">
            {variant === 'marks' ? fmt(s.interruptsShort, known) : <>
              <span data-show-from="l">{fmt(s.interruptsUsed, known)}</span>
              <span data-show-upto="m">{fmt(s.interruptsShort, known)}</span>
            </>}
          </b>
        ) : <span className="n-runhead__said"><SourceLabel lang={lang} showTime={false} reading={unread} /></span>}>
        {detail}
      </Disclosure>
    </div>
  );
}

export interface RunningHeadProps {
  hub: HubSnapshot;
  lang: Lang;
  demo: boolean;
  variant?: 'full' | 'marks';
  /** useVoice().status: the microphone's "listening now". */
  voiceStatus?: string | null;
  /** In-app navigation for a signal's page link (without it the link loads the page). */
  navigate?: (path: string) => void;
  /** A signal's popover links to the page that acts on it (default). False where no other page
   *  can be shown (the floating window, whose router accepts only the conversation). */
  links?: boolean;
}

export const RunningHead = memo(function RunningHead({ hub, lang, demo, variant = 'full', voiceStatus = null, navigate, links = true }: RunningHeadProps) {
  const s = pick(RUNHEAD_STRINGS, lang);
  const now = useStaleNow(hub);
  const audit = useAuditVerify({ demo });
  const egress = useEgressLedger({ demo });
  const signals = useMemo(() => trustSignals({ hub, now, demo, audit, egress, voiceStatus }, lang),
    // the readings' fields are what changes; their objects are new on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hub, lang, now, demo, voiceStatus, audit.state, audit.value, audit.lastGoodAt, audit.reason, egress.state, egress.value]);
  // below 760px the running head is one line of marks (§4.2): the frame's, and the marks of the
  // 420px floating window and of Glance on a narrow window, where the approval mode stays read-only.
  // The head always follows the window: what waits in the approval mode goes with it into the new
  // form (ApprovalMode), so nothing is ever drawn past the window to keep it where it was.
  const compact = useNarrow();
  // from 1100px the line fits itself (RUNHEAD_FIT_STEPS); below it fitRunningHead writes no step
  const head = useRef<HTMLDivElement>(null);
  useFitWatch(head, variant === 'marks' ? refitMarks : refitFull, { attributes: RUNHEAD_ATTRIBUTES });
  return (
    <div ref={head} className={`n-runhead n-runhead--${variant}${compact ? ' n-runhead--compact' : ''}`} data-frame="runhead"
      data-compact={compact ? '' : undefined} role="region" aria-label={s.region}>
      <dl className="n-signals" aria-label={s.signals}>
        {signals.map((view) => <SignalItem key={view.id} view={view} lang={lang} variant={variant} compact={compact} navigate={navigate} links={links} />)}
      </dl>
      <div className="n-runhead__controls">
        {variant === 'full' ? <ApprovalMode lang={lang} demo={demo} compact={compact} /> : <ApprovalModeReadout lang={lang} demo={demo} compact={compact} />}
        <span className="n-runhead__sep" aria-hidden="true" />
        <Interrupts lang={lang} demo={demo} variant={variant} compact={compact} />
      </div>
    </div>
  );
});
