/* The masthead (PHASE_B_PLAN.md §4.1), header[data-frame="masthead"]:

     (N) Nerva   Home  Work 9 need you  Agents … Settings   [⌕ Search or run a command  Ctrl K]
                                                            EN|RO  ◐  Glance  [■ Stop all agents]

   - the brand: the ring and N, and "Nerva" in the title face; it links to Today (/v2/cockpit);
   - AreaNav: the nine areas with their attention notes; below 760px the "Areas" drawer;
   - Find: opens the search and command sheet, carries data-anchor="console", shows its key;
   - LangSeg: a radio group EN | RO that sets the appearance language;
   - SchemeToggle: switches the resolved scheme; its name says the current and the next one; it
     is unavailable, with the reason, when the theme designs one scheme only (Classic);
   - Glance; and the StopButton (useKillSwitch), whose refusals the frame lists in its notices.
   Find's accessible name begins with the words it shows ("Search or run a command", whose
   short form "Search" is its first word), so a voice user can say what they see (WCAG 2.5.3).
   The name ends with the key, so the key cap is drawn by frame.css from data-key, not as text:
   text on screen between the words and the name's own key fails axe's label-in-name check.

   Fitting the row. From 1100px the brand, the nine areas, Find and the tools share one row, and
   whether they fit depends on what is drawn — the language, the look and its typeface, the
   density, every attention note — not on the width alone. So the masthead measures itself
   (frame/fit.ts: before the first paint, then whenever its words, what it draws, the width, a
   font, the look, typeface or density change, or the tools change size, as the stop's "Stopping…"
   does; never on a render that changed nothing) and takes the steps of FIT_STEPS in order, the
   least loss first, until nothing spills, then takes back, the lossiest first, every step a later
   one made unneeded, writing them on the header (data-fit; frame.css draws each one). The nine
   areas keep their names (the Ledger gives them no short forms), the tools
   are never hidden, and every word a step takes off the screen stays in the control's name and
   its tooltip. Find's words, the field's placeholder, are never cut: a placeholder that does not
   fit is a spill like any other, and its words give way at their own steps ("search", "find"). */
import React, { useRef, useState } from 'react';
import { routeHref } from '../hud-routing';
import type { RoutePage } from '../nav/routes';
import type { Attention } from '../signals/types';
import type { Scheme, SchemePreference, ThemeInfo } from '../theme/registry';
import { AreaDrawer } from './AreaDrawer';
import { AreaNav, inAppClick } from './AreaNav';
import { fitRow, mediaMatches, spillsOver, stepsOf, textCut, useFitWatch, writeSteps } from './fit';
import { MASTHEAD_STRINGS } from './frame-strings';
import { StopButton } from './StopButton';
import { fmt, LANGS, pick, type Lang } from './strings';
import { useKillSwitch } from './useKillSwitch';
import './frame.css';

const HOME_PATH = '/v2/cockpit';

/* ---- fitting the row ------------------------------------------------------------------------ */

/** What the masthead gives up when its row is too narrow, in order, the least loss first:
 *
 *    search   Find's placeholder says "Search" (from 1680px; below it that is its form already):
 *             the field is the row's flexible part, so it narrows first, and "or run a command"
 *             is the least informative words on the row (the key cap stays)
 *    notes    a problem note keeps its mark and count ("Observe ■ 4"; a broken record its mark)
 *    glance   Glance keeps its icon
 *    hand     the owner's notes keep their count ("Work 12": need you, waits)
 *    tight    the areas, the gaps and the switches sit closer
 *    brand    the brand keeps its ring and N
 *    stop     the stop says "Stop" (still the stop's own colours and mark); halted, "Halted"
 *    find     Find keeps its icon (no words, no key cap), so its box can narrow
 *    tighter  the areas and the margins closer still
 *    scroll   the last resort: the areas row scrolls instead of spilling under Find
 *
 *  Each word a step takes off the screen stays in the control's accessible name and its tooltip:
 *  "Work — 12 need you", "Stop all agents", "All agents are halted. Resume in Trust › Emergency
 *  stop", "Search or run a command — … · Ctrl K". */
export const FIT_STEPS = ['search', 'notes', 'glance', 'hand', 'tight', 'brand', 'stop', 'find', 'tighter', 'scroll'] as const;
export type FitStep = typeof FIT_STEPS[number];

/** The width from which the masthead is one row (frame.css); narrower, the areas take a second
 *  row that scrolls (760–1099px) or the drawer (below 760px), and nothing is compacted. */
export const ONE_ROW_QUERY = '(min-width: 1100px)';
/** The width from which Find's placeholder is drawn whole ("Search or run a command"). */
export const LONG_FIND_QUERY = '(min-width: 1680px)';

/** The steps the row takes (fit.ts fitRow): the fewest, in FIT_STEPS order, after which `spills`
 *  says the row fits, then each taken back, the lossiest first, where the row still fits without
 *  it (Find's icon frees so much that the stop's words, the brand's name or a note's words the walk
 *  gave up before it can come back); every step that applies when the row never fits. `spills` is
 *  asked with the steps tried, starting from `from`; `long` says whether Find's placeholder is
 *  drawn whole (the "search" step applies). */
export function fitSteps(spills: (steps: readonly FitStep[]) => boolean, from: readonly FitStep[] = [], long = true): FitStep[] {
  return fitRow(FIT_STEPS, { spills, from, applies: (step) => step !== 'search' || long });
}

/** Whether the masthead's row spills: the header, the areas strip or the tools wider than their
 *  room, or Find's words cut (a placeholder is never cut: its words give way at their steps).
 *  Find's words are measured in fractions of a pixel (fit.ts textCut): Chromium draws the ellipsis
 *  for an overflow of a layout unit, which whole pixels miss ("Sear…" at 1440px in Atlas). */
export function rowSpills(header: HTMLElement): boolean {
  return spillsOver(header) || spillsOver(header.querySelector('.n-masthead__areas')) || spillsOver(header.querySelector('.n-masthead__tools'))
    || textCut(header.querySelector('.n-masthead__find-words'));
}

const oneRow = (): boolean => mediaMatches(ONE_ROW_QUERY, () => window.innerWidth >= 1100);
const longFind = (): boolean => mediaMatches(LONG_FIND_QUERY, () => window.innerWidth >= 1680);

/** Fits the masthead's row (FIT_STEPS), synchronously (call it before a paint). `fresh` starts
 *  again from nothing (what is drawn or the width changed); otherwise it goes on from the steps
 *  already taken. Either way it never undoes a step that is still needed, and takes back one that
 *  no longer is. */
export function fitMasthead(header: HTMLElement, { fresh = true, wide = oneRow(), long = longFind() }: { fresh?: boolean; wide?: boolean; long?: boolean } = {}): void {
  if (fresh || !wide) writeSteps(header, []);
  if (!wide) return;
  const steps = fitSteps((tried) => { writeSteps(header, tried); return rowSpills(header); }, stepsOf(header, FIT_STEPS), long);
  writeSteps(header, steps);
}

/** What, inside the masthead, changes a width when it changes: the page's area (its link is
 *  bold), the language's choice (semibold), Find's key cap (drawn from data-key), the stop's form,
 *  a note's tone, a control shown or hidden. Its words are watched as text. */
const MASTHEAD_ATTRIBUTES = ['aria-current', 'aria-checked', 'data-key', 'data-stop', 'class', 'hidden', 'disabled'];
const mastheadTools = (header: HTMLElement) => [header.querySelector('.n-masthead__tools')];
const refitMasthead = (header: HTMLElement) => fitMasthead(header);

export interface MastheadProps {
  page: RoutePage;
  lang: Lang;
  setLang: (lang: Lang) => void;
  /** The resolved scheme (never 'system') and the owner's preference. */
  scheme: Scheme;
  schemePreference: SchemePreference;
  setScheme: (scheme: SchemePreference) => void;
  theme: ThemeInfo;
  attention: Attention;
  /** displayChord(chordOf(overrides, 'session.palette')): '' when unbound. */
  findChord: string;
  onFind: () => void;
  onGlance: () => void;
  navigate: (path: string) => void;
  demo: boolean;
  /** Where a stop's refusal is shown (the frame's notices). Without it the masthead shows it. */
  onStopResult?: (refusal: string | null) => void;
}

/** The ring and the neural N (three strokes, four nodes), in ink. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 128 128" aria-hidden="true" focusable="false">
      <circle cx="64" cy="64" r="59" fill="none" stroke="currentColor" strokeWidth="5" />
      <g stroke="currentColor" strokeWidth="9" strokeLinecap="round" fill="none">
        <line x1="42" y1="90" x2="42" y2="38" /><line x1="42" y1="38" x2="86" y2="90" /><line x1="86" y1="90" x2="86" y2="38" />
      </g>
      <g fill="currentColor"><circle cx="42" cy="38" r="8" /><circle cx="42" cy="90" r="8" /><circle cx="86" cy="38" r="8" /><circle cx="86" cy="90" r="8" /></g>
    </svg>
  );
}

/** EN | RO as a radio group: arrow keys move the choice, one stop in the tab order. */
function LangSeg({ lang, setLang }: { lang: Lang; setLang: (lang: Lang) => void }) {
  const s = pick(MASTHEAD_STRINGS, lang);
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const names: Record<Lang, string> = { en: s.langEn, ro: s.langRo };
  const choose = (next: Lang, focus = false) => {
    if (next !== lang) setLang(next);
    if (focus) refs.current[LANGS.indexOf(next)]?.focus();
  };
  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const at = LANGS.indexOf(lang);
    choose(LANGS[(at + step + LANGS.length) % LANGS.length], true);
  };
  return (
    <div className="n-seg n-masthead__lang" role="radiogroup" aria-label={s.language} onKeyDown={onKeyDown}>
      {LANGS.map((code, i) => (
        <button key={code} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={code === lang}
          aria-label={names[code]} tabIndex={code === lang ? 0 : -1} lang={code} onClick={() => choose(code)}>
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

function SchemeToggle({ lang, scheme, theme, setScheme }: Pick<MastheadProps, 'lang' | 'scheme' | 'theme' | 'setScheme'>) {
  const s = pick(MASTHEAD_STRINGS, lang);
  const locked = theme.schemes.length < 2;
  const next: Scheme = scheme === 'dark' ? 'light' : 'dark';
  const word = (value: Scheme) => (value === 'dark' ? s.schemeDark : s.schemeLight);
  const label = locked ? fmt(s.schemeLocked, { current: word(scheme) }) : fmt(s.schemeSwitch, { current: word(scheme), next: word(next) });
  return (
    <button type="button" className="n-masthead__tool" data-scheme-toggle={scheme} aria-label={label} title={label}
      aria-disabled={locked || undefined} onClick={() => { if (!locked) setScheme(next); }}>
      <svg className="n-masthead__icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 2.4a5.6 5.6 0 0 1 0 11.2z" fill="currentColor" />
      </svg>
    </button>
  );
}

export function Masthead(props: MastheadProps) {
  const { page, lang, setLang, scheme, setScheme, theme, attention, findChord, onFind, onGlance, navigate, onStopResult } = props;
  const s = pick(MASTHEAD_STRINGS, lang);
  const killSwitch = useKillSwitch(lang);
  const [ownRefusal, setOwnRefusal] = useState<string | null>(null);
  const stopResult = onStopResult ?? setOwnRefusal;
  const header = useRef<HTMLElement>(null);
  useFitWatch(header, refitMasthead, { attributes: MASTHEAD_ATTRIBUTES, sized: mastheadTools });
  const findName = findChord ? fmt(s.findLabel, { key: findChord }) : s.findLabelPlain;
  return (
    <header ref={header} className="n-masthead" data-frame="masthead">
      <a className="n-masthead__brand" href={routeHref(HOME_PATH)} aria-label={s.brandLabel} title={s.brandLabel}
        onClick={(event) => { if (!inAppClick(event)) return; event.preventDefault(); navigate(HOME_PATH); }}>
        <BrandMark className="n-masthead__mark" />
        <span className="n-masthead__name">{s.brand}</span>
      </a>
      <div className="n-masthead__areas" data-show-from="xs">
        <AreaNav current={page.area} lang={lang} attention={attention} navigate={navigate} />
      </div>
      <AreaDrawer current={page.area} lang={lang} attention={attention} navigate={navigate} />
      <button type="button" className="n-masthead__find" data-anchor="console" aria-label={findName} title={findName} onClick={() => onFind()}>
        <svg className="n-masthead__icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M10.4 10.4L14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <span className="n-masthead__find-words" data-show-from="xs">
          <span data-show-from="l">{s.find}</span>
          <span data-show-upto="m">{s.findShort}</span>
        </span>
        {findChord && <kbd className="n-kbd n-masthead__key" data-key={findChord} aria-hidden="true" />}
      </button>
      <div className="n-masthead__tools">
        <LangSeg lang={lang} setLang={setLang} />
        <SchemeToggle lang={lang} scheme={scheme} theme={theme} setScheme={setScheme} />
        <button type="button" className="n-masthead__tool" data-anchor="glance" aria-label={s.glanceLabel} title={s.glanceLabel} onClick={() => onGlance()}>
          <svg className="n-masthead__icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <rect x="1.8" y="3" width="12.4" height="8.4" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M5.5 14h5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span className="n-masthead__glance-word" data-show-from="m">{s.glance}</span>
        </button>
        <StopButton killSwitch={killSwitch} lang={lang} navigate={navigate} onResult={stopResult} />
      </div>
      {!onStopResult && ownRefusal && <p className="n-masthead__alert" role="alert">{ownRefusal}</p>}
    </header>
  );
}
