/* Phase B render matrix (PHASE_B_PLAN.md §9.5, §9.4). Manual lane: playwright.ledger-shots.config.ts.

   For each page × width × theme, live-empty and demo (the Ledger frame is the only one since the
   cleanup deleted the development switch), it takes a screenshot and checks the gates, writing
   every result to report.json whether or not a gate fails:

     overflow-x      no horizontal overflow, ever
     page-scroll     Home and Glance: the page itself does not scroll (1920, 2560, 1280×800);
                     registers scroll inside
     min-font        the smallest drawn text is ≥ 12px in a Nerva theme (reported, not gated,
                     for Classic · Obsidian)
     contrast        axe colour-contrast violations = 0, in all three themes
     console         no uncaught page error and no console error, except Chromium's own line for
                     an HTTP answer ("Failed to load resource: the server responded with a
                     status of 503", or "… net::ERR_…"): the fixture hub runs without its
                     lifespan, so it answers 503 for the components it did not start (the kill
                     switch the masthead reads on every page) and 401/403 on the admin feeds, and
                     the pages draw those as refused or unavailable. Those lines are reported
                     (`http`, as e2e/support/workspace-helpers.ts PageGuard reads them), not gated;
                     a request that leaves the origin has its own gate
     external        no request leaves the origin
     runhead         the eight running-head items are drawn, inside the viewport, none overlapping
                     another, on one line (every width in the matrix is ≥ 1100px)
     masthead        the brand, the areas, Find and the tools do not overlap, and every area link
                     is inside the viewport (from 760px; below it the areas are in the drawer)
     docket-1280     at 1280×800 the open entry's SignLine (its signature: the typed line, or the
                     row with Sign where the request takes one or two steps) is fully visible — inside
                     the window and inside what the docket's scrolling body shows, as the docket first
                     draws it, with the open entry's title and first line (its tier word) still in view
                     (where the layout leaves part of the line below the view, the docket scrolls its body
                     by that much and never past the entry's first line: Classic, Romanian, 1280×800) — and
                     every other entry's sign control can be hit after scrolling inside the docket
                     (nothing covers its centre; a disabled one, as in demo, is checked the same way) —
                     only when the docket draws entries; otherwise reported as not evaluated. Until the
                     review of the register-inset round it measured the line against the window only,
                     and passed with 38px of it below the docket body's view (Classic · Obsidian, demo)
     sec-heads       every section head (.n-sec), register head (.n-register__head) and total
                     (.n-total) the shot draws, each a row of a title and the flow beside it (an
                     aside, a meta): (a) the title takes no more lines than it would alone in the
                     row, and is not cut where alone it would be whole; (b) the flow's box and the
                     title's lie inside the row's box, no text of the row is drawn past it, and the
                     flow's words are not drawn over the title's; (c) a text that is cut (its extent
                     past a box that clips it, by more than fit.ts CUT_EPSILON) is cut by a box in its
                     row that draws an ellipsis for it, and keeps its whole text in a title or an
                     accessible name. And the heads of registers drawn side by side (level, apart
                     across the row: Home's spread from 1100px, Trust's and Work's columns from
                     1340px): (d) the rules under them lie on one line, the tops within 0.5px,
                     whichever head wraps; (e) where none of them wraps, each is as tall as a
                     register head is (--register-head-h), so a shared height adds no space in the
                     usual case. True, with counts of zero, where a page draws none (Glance)
     register-inset  every top-level register the shot draws (an .n-register inside no other): where
                     its frame is drawn (a side border wider than 0, or a ground that is not
                     transparent: the card looks, Classic · Obsidian in this matrix) it keeps a margin m,
                     its own side padding (the look's inner margin, --n-register-pad): (a) m is more than
                     0 and the same on both sides, and the bottom keeps it too, as the register's own
                     padding where it has no foot, and where it has one by its foot (the foot's last box
                     ends m or more above the frame); (b) no visible text (its client rects, via Range,
                     cut to what the register's scrolling boxes show), no control (button, input,
                     textarea, select, a, [role=button]) and no total (.n-total, its double rule) comes
                     closer to the inner edge of its border than m, less 0.5px, on the left, the right
                     and the bottom; where it is drawn with rules (Ledger, Briefing, Presence), (c) it has
                     no padding there, so nothing moves; and (d) below 760px no register is framed, in any
                     look, so a phone's columns are as wide as the rule looks draw them. Found in the
                     final renders after the last gate: in every card look a register's title, meta, rows
                     and controls touched its frame (Atlas light at 2560px, "Wednesday 25 November" 1px
                     inside the day register's left border, "02:19" ending at its right). Found by the
                     review of its fix: at 320–390px a 12px margin cut words that had been whole and
                     squeezed Trust's capabilities into overlapping columns (d). True, with counts of
                     zero, where a page draws no register (Glance)
     area-frame      on an area page (every page shot but Home and Glance): the page's column
                     (.n-areapage__main) is not a card: (a) it draws no fill, no side or bottom border and
                     no shadow (only the look's top rule opens it), in every look; (b) no register drawn as
                     a card (a side border wider than 0, or a ground that is not transparent) has a framed
                     ancestor up to and including that column: no card inside a card. Found after the
                     register-inset round: in every card look the column drew the look's panel treatment,
                     the page's title sat 0px from its frame at every width and every register was a card
                     whose frame lay on the area frame's edge. Not evaluated where a page draws no area
                     column (Home, Glance)

   Geometry gates run beside the matrix (each its own test, in the report too). They measure what
   is drawn: every box, every text node's visible part (clipped by its scrolling and clipped
   ancestors), and what elementFromPoint finds at each item's centre.

     masthead-fit    every attention note at its widest (128 need you, 12 services down, the
                     record broken at entry 412907, stubbed), English and Romanian, Ledger dark and
                     Classic · Obsidian, at 1100, 1180, 1280 (×820, the owner's default shell),
                     1340, 1440, 1680, 1920 and 2560px, and the extra cases — the stop halted
                     (Ledger dark), Presence (the largest UI type) and Ledger at comfy density — at
                     1100, 1180, 1280, 1340, 1680 and 2560px: the header is one row tall; the nine
                     area links and every tool (the brand, Find, EN | RO, the scheme toggle,
                     Glance, the stop) are drawn whole inside that row and the viewport, the links
                     inside their strip (which does not scroll), none overlapping another, each on
                     top at its centre; Find's words, when drawn, are not cut (measured in fractions
                     of a pixel: the text's own extent against its box, since Chromium draws an
                     ellipsis for any overflow of a layout unit, 1/64px, which whole-pixel
                     scrollWidth and clientWidth cannot see); and no step is
                     lossier than needed: none of the steps written can be taken back with the
                     row still fitting by the masthead's own measure (fit-takeback). On a fresh
                     load at each width, and again while the window is resized down through the
                     widths and back up (the steps the same both ways, and the same three frames
                     later: nothing flips back and forth).
     runhead-fit     the eight running-head items from 1100px (§8.2 rows 25, 27), with the widest
                     real values stubbed (a cloud model configured with the readable network
                     ledger's count, a long model id with its backend, the local-route figure, the
                     chain broken at a six-figure entry, the approval mode refused, a two-figure
                     interrupt budget; and at every width also "Offline · last good reading" — its
                     long form from 2200px, "Offline" below, wider than "Live" — the hub stopping
                     after its first answer, measured on the page clock) and with the fixture hub's
                     own answers, English and Romanian, in Ledger dark, Classic · Obsidian, Presence
                     and Atlas light at 1100, 1180, 1280, 1340, 1366, 1440, 1536, 1600, 1680, 1920,
                     2200 and 2560px (a fresh load at each), plus Ledger at comfy density and Ledger
                     with the mono typeface override at 1100, 1340, 1680 and 2200px, and a resize
                     walk down and back up: every item's scrollWidth ≤ clientWidth + 1, every text
                     node's visible part inside its own item and the viewport, no value cut with an
                     ellipsis before the fit's "cut" step (measured in fractions of a pixel, as
                     Find's words), no two items
                     overlapping, each item on top at its centre, all eight on one line unless the
                     fit took its last resort (two lines), which the report says; and no step lossier
                     than needed (fit-takeback, as the masthead's: by the running head's own measure,
                     a value cut further or a line more counting as not fitting). The steps each
                     width took are in the report; the resize walk also checks them three frames
                     later.
     runhead-marks   the running head below 760px, at 320, 390, 600 and 740px, the widest words
                     stubbed (the mode Ask, "Întreabă"; 12 of 24 interrupts), both languages, both
                     looks: one line, every item drawn whole inside the viewport and the head, none
                     overlapping another, each on top at its centre, each a button named with its
                     words that opens its popover (aria-expanded); and runhead-surroundings within
                     32px of the head (below).
     runfoot-phone   on the same pages, the running foot at its widest real form (§4.3; FOOT below),
                     stubbed and checked to have landed before anything is measured: a served
                     roster of 96 agents (24 working, 32 waiting on you, 21 finished today, Athena
                     unavailable with no cloud model, 18 with no activity reported), 23 replies
                     running elsewhere, RAM, VRAM and GPU load known, 10 of 12 channels running, 21
                     sessions, a pre-release version; then, as runfoot-phone-unknown, the fixture
                     hub's own answers (the roster not reported, the machine and channels unknown).
                     Every part the width keeps is drawn whole inside the viewport (the agents, each
                     state's count, the replies elsewhere, the three figures, the channels, the
                     sessions, the version); what §4.3 leaves out below 1680px is not drawn (the
                     agents with no activity, the meters, the latency, the unread sources); every
                     text node's drawn part inside its item and the viewport, no two items
                     overlapping, nothing painted into the foot from around it (the surroundings
                     gate within 24px of it); an unknown machine reading drawn as its label and
                     mark, its words read and in its title.
     runhead-window  the marks the floating window (420 × 620, a mock desktop bridge) and Glance
                     draw (Glance at 420×800, 760×800, 1100×800, 1280×800, 1920×1080, 2560×1353
                     and three short windows, 760×560, 1280×560 and 1920×600), with the widest values, English
                     and Romanian, in Ledger dark, Classic · Obsidian and Atlas light: every item
                     whole inside its own box and the viewport, none overlapping, each on top at its
                     centre, on one line (below 760px and from 1100px) unless the fit took two lines
                     (reported); at 760–1099px the head wraps by design (§4.2). Every popover of the
                     marks (each item's button, opened one at a time; Glance's scrolled into view)
                     opens inside the window, on top at its centre and at four points inside its
                     corners, and opaque: its own ground is a colour with no transparency and
                     nothing above it fades it (opacity), so the page's words under it are covered,
                     not drawn through it (Classic's --surface is translucent). Glance's sheet scrolls where it is taller
                     than the window and is centred where it is not. And runhead-surroundings on the
                     whole floating window and the whole Glance sheet, as each first shows and
                     scrolled to its end (every scroller in the floating window; the marks are
                     measured scrolled into view).
     runhead-surroundings
                     what is painted under and around the head (installGates' __nervaPaint): no text
                     or mark drawn over or under another element's text, mark, fill or rule (text
                     over text, a rule through a word, a button over a sentence, a figure under a
                     mark), and no text cut or out of the reach of scrolling (above or left of where
                     its scroller starts). A positioned ::before / ::after (the current area's
                     underline bar, a gutter's rule) paints its fill and rules like an element, and
                     an underlined text (text-decoration) its underline, placed from the font's own
                     metrics. Its limits: an in-flow pseudo-element (generated text such as Find's
                     key cap) is not seen, nor are box shadows and outlines (the focus ring); a text
                     is compared by the middle half of its line box, so a clash only in ascenders or
                     descenders is not counted; and only what is on screen is checked: Glance's
                     sheet and the floating window are checked as first shown and scrolled to their
                     end, not at every point between, and the other pages' marks and foot only as
                     they first show. It runs with every popover closed: an open popover is checked
                     by the popover gates (inside the window, on top, opaque), not by this one.
     frame-ellipsis  every look and scheme of the theme registry (the seven Nerva themes dark and
                     light, Classic · Obsidian and Graphite), English and Romanian, on Home with the
                     widest running-head values and the docket's 128 requests, the window resized
                     through the twelve fit widths from 1100 to 2560px: Find's words are never cut,
                     and no running-head value is cut before the "cut" step, both measured in
                     fractions of a pixel (where an ellipsis is drawn, Chromium has cut the text).
     runhead-popovers
                     the main window's running head on Home at 1280×820, 1920×1080 and 390×844, in
                     Ledger dark and Classic · Obsidian and Graphite, English and Romanian: every
                     popover of the head (each signal, the interrupts, the approval mode's fold or,
                     below 760px, its mark) opens inside the window, on top and opaque (as above).
     sec-heads       (also its own group) the same gate on Home and Trust in every look and scheme
                     of the theme registry (the seven Nerva themes dark and light, Classic · Obsidian
                     and Graphite), English and Romanian, at 320, 390, 600, 760, 1100, 1280, 1340,
                     1440, 1680, 1920, 2200 and 2560px, with the fixture hub's own answers (its long
                     readings: "Unknown — switched off on the hub", refused and not-reported feeds) and
                     then the demo sample (the docket's, the record's and the payments' totals, and
                     the docket's large figure), and on Home then a live docket of 128 entries (its
                     figure "128" in the owner's hand) from 1100px, where the registers stand side by
                     side: each page walked down the widths from a load at 2560px; below 1680px each of the day
                     band's popovers (the verdict, Today, While you were away) opened and measured
                     inside, the popover itself inside the window, and every word in it whole: one
                     cut by the window or the page around the popover is cut without an ellipsis.
                     The agents and the record's tail are Home's fourth register, drawn from
                     2200px only, so they are measured at 2200 and 2560px. Found by the last gate:
                     "While you were away" squeezed to one word per line in the 396px day register,
                     its aside cut by the register with no ellipsis (42 cases from 1680 to 2560px).
                     Found by the review of its fix: Trust's record and authority heads 16px apart
                     in Classic at 1340-1440px (d); every head beside the docket 1-8px taller with
                     nothing wrapping, the docket's figure taller than the strut (e); and at 320px
                     the day band's popovers 20px past the window, its first or last letters cut.
                     The same walks measure register-inset (above) on the page at every width and
                     pass, in all sixteen looks and schemes, and on Home, where the docket draws
                     entries (the demo sample, the 128 entries), docket-sign at 1280×800 and 1440×900
                     (PHASE_B_PLAN.md §9.5 and §5.1): the open entry's sign line fully inside the
                     window and the docket body's view, as docket-1280 measures it; and again after each
                     pass on a fresh load at 1280×800, 1340×900 and 1440×900 (the docket's first paint at
                     that size, not a window resized down to it); in both, the open entry's first line
                     (its tier word) and the body's first line (the docket's state line, the column
                     heads: whatever the body draws first, by its text's own line box) stay in the
                     body's view too; and on a fresh load at 390×844 and 1100×800, where the signature
                     cannot be whole, the docket does not scroll its body past either line (the final
                     gate found it scrolled 62px in Classic, Romanian, at 1100px and 88-124px at phones,
                     hiding the tier word and the state line; the final round's verifier found its
                     repair, which stopped at the entry's top, still scrolling 21-22px in Classic,
                     English, at 1100×800, the demo's state line cut under the head's rule). Found by the
                     review of the register-inset round: in Atlas, Romanian, the register's bottom
                     margin and narrower column put 5px of it below the body's view at 1280×800, where
                     it had been whole; and by its gate: in Classic, 22px (English) and 49px (Romanian)
                     at 1280×800, 12px in Romanian at 1340–1440×900. The record holds the three gates.
     area-frame      (also its own group) the same gate on Trust, Work, Timeline, the conversation page
                     and four mode pages drawn through PageSection (Agents, Memory, Settings, Connect), in
                     every look and scheme of the theme registry, English and Romanian, the fixture hub's
                     own answers and the demo sample, each loaded at 1920px and walked down to 1280, 760
                     and 390px.
     runhead-held    the approval mode while its looser choice waits for the second step, asked in
                     the line (1600px), folded (1180px) and below 760px (600px), then the window
                     resized through 3–8 widths down to 360px and back: the head follows the window
                     (below 760px one line of marks, from 760px the line), every item inside the
                     window, the page never scrolls sideways, and the confirmation stays drawn,
                     opaque, inside the window with both of its buttons whole and on top, and keeps
                     the focus it took (it is the same control throughout: never drawn again
                     elsewhere). And a refusal shown in the line, then the window narrowed to 600
                     and 390px: the head is the marks, the refusal is seen inside the window, and
                     nothing holds the head's form.

   The theme is chosen before load through Phase A's cache (hud.appearance.v1:/, version 2) and
   the hub's appearance answer is pinned to the same choice, so a sync cannot flip it mid-shot.
   Nothing here writes to the hub: the fixture answers every write. */
import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

type Size = { name: string; width: number; height: number; scale: number };
type Look = {
  look: 'ledger' | 'presence' | 'briefing' | 'workbench' | 'threshold' | 'console' | 'atlas' | 'obsidian' | 'graphite';
  scheme: 'dark' | 'light';
  nerva: boolean;
};
/** The owner's other appearance axes, for the extra fit cases. */
type Settings = { id: string; density?: 'compact' | 'normal' | 'comfy'; font?: string };
type Shot = { id: string; path: string; fixedPage?: boolean; safeMode?: boolean };

const SIZES: Size[] = [
  { name: '2560', width: 2560, height: 1353, scale: 1.5 },
  { name: '1920', width: 1920, height: 1080, scale: 1 },
  { name: '1280', width: 1280, height: 800, scale: 1 },
];
const LOOKS: Look[] = [
  { look: 'ledger', scheme: 'dark', nerva: true },
  { look: 'ledger', scheme: 'light', nerva: true },
  { look: 'obsidian', scheme: 'dark', nerva: false },
];
const PAGES: Shot[] = [
  { id: 'home', path: '/v2/cockpit', fixedPage: true },
  { id: 'glance', path: '/v2/glance', fixedPage: true },
  { id: 'chat', path: '/v2/chat' },
  { id: 'work', path: '/v2/work' },
  { id: 'timeline', path: '/v2/timeline' },
  { id: 'agents', path: '/v2/agents' },
  { id: 'memory', path: '/v2/memory' },
  { id: 'build', path: '/v2/build' },
  { id: 'trust', path: '/v2/trust' },
  { id: 'logs', path: '/v2/console/logs' },
  { id: 'kill-switch', path: '/v2/console/kill-switch' },
  { id: 'settings', path: '/v2/admin' },
  { id: 'model-setup', path: '/v2/console/model-setup' },
  { id: 'all-pages', path: '/v2/console' },
];
const SAMPLES = [{ id: 'live', demo: false }, { id: 'demo', demo: true }];
/** The notices stack: safe mode reported by the hub, with demo on. */
const NOTICES: Shot = { id: 'notices', path: '/v2/cockpit', fixedPage: true, safeMode: true };

const OUT = join(process.cwd(), 'e2e', 'artifacts', 'ledger');
/* Each shot's result is written as it is taken, under this run's folder, and report.json is rebuilt
   from all of them: Playwright starts a new worker after a failed test, and a worker's own list held
   only the shots since then (a report of 1 shot after a run of 255). */
const RUN = process.env.NERVA_SHOTS_RUN || 'single-worker';
const RUN_DIR = join(OUT, 'runs', RUN);
const REPORT: Array<Record<string, unknown>> = [];
/** Chromium's console line for a request's HTTP answer or network failure (PageGuard's rule). */
const FAILED_RESOURCE = /^Failed to load resource: (?:the server responded with a status of (\d{3})|net::(ERR_[A-Z_]+))/;

type Gate = { evaluated: boolean; ok: boolean; detail: string };

/** The running head: all eight items drawn, inside the viewport, none overlapping, one line. */
async function runheadGate(page: Page): Promise<Gate> {
  return page.evaluate(() => {
    const head = document.querySelector('[data-frame="runhead"]');
    if (!head) return { evaluated: false, ok: true, detail: 'no running head on this page' };
    const items = Array.from(head.querySelectorAll<HTMLElement>('[data-signal], [data-runhead="mode"], [data-runhead="interrupts"]'));
    const boxes = items.map((el) => ({ id: el.getAttribute('data-signal') || el.getAttribute('data-runhead') || '?', r: el.getBoundingClientRect() }));
    const problems: string[] = [];
    if (items.length !== 8) problems.push(`${items.length} of 8 items in the DOM`);
    const width = document.documentElement.clientWidth;
    const drawn = boxes.filter(({ id, r }) => {
      if (r.width > 0 && r.height > 0) return true;
      problems.push(`${id} is not drawn`);
      return false;
    });
    for (const { id, r } of drawn) if (r.left < -0.5 || r.right > width + 0.5) problems.push(`${id} is cut by the viewport (${Math.round(r.left)}..${Math.round(r.right)} of ${width})`);
    for (let i = 0; i < drawn.length; i++) {
      for (let j = i + 1; j < drawn.length; j++) {
        const a = drawn[i].r;
        const b = drawn[j].r;
        const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (x > 0.5 && y > 0.5) problems.push(`${drawn[i].id} overlaps ${drawn[j].id}`);
      }
    }
    // rows: items whose vertical middles are within half the shortest item's height share one
    const middles = drawn.map(({ r }) => r.top + r.height / 2).sort((a, b) => a - b);
    const half = Math.min(...drawn.map(({ r }) => r.height)) / 2;
    let lines = middles.length ? 1 : 0;
    for (let i = 1; i < middles.length; i++) if (middles[i] - middles[i - 1] > half) lines += 1;
    if (lines > 1) problems.push(`on ${lines} lines`);
    return { evaluated: true, ok: problems.length === 0, detail: problems.join('; ') || `8 items on ${lines} line` };
  });
}

/** The masthead: brand, areas, Find and tools apart, and every area link on screen. */
async function mastheadGate(page: Page): Promise<Gate> {
  return page.evaluate(() => {
    const mast = document.querySelector('[data-frame="masthead"]');
    if (!mast) return { evaluated: false, ok: true, detail: 'no masthead on this page' };
    const problems: string[] = [];
    const parts = ['brand', 'areas', 'find', 'tools']
      .map((name) => ({ name, el: mast.querySelector<HTMLElement>(`.n-masthead__${name}`) }))
      .map(({ name, el }) => ({ name, r: el ? el.getBoundingClientRect() : null }))
      .filter((p): p is { name: string; r: DOMRect } => !!p.r && p.r.width > 0 && p.r.height > 0);
    for (let i = 0; i < parts.length; i++) {
      for (let j = i + 1; j < parts.length; j++) {
        const a = parts[i].r;
        const b = parts[j].r;
        const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (x > 0.5 && y > 0.5) problems.push(`${parts[i].name} overlaps ${parts[j].name}`);
      }
    }
    const width = document.documentElement.clientWidth;
    for (const link of Array.from(mast.querySelectorAll<HTMLElement>('.n-masthead__areas .n-areas__link'))) {
      const r = link.getBoundingClientRect();
      if (!r.width) continue;
      if (r.left < -0.5 || r.right > width + 0.5) problems.push(`area link "${(link.textContent || '').trim()}" is cut by the viewport`);
    }
    return { evaluated: true, ok: problems.length === 0, detail: problems.join('; ') || 'apart and on screen' };
  });
}

function preferences(look: Look, lang: 'en' | 'ro' = 'en', settings: Settings = { id: 'default' }) {
  return { look: look.look, scheme: look.scheme, lang, density: settings.density ?? 'normal', motion: 'calm', font: settings.font ?? 'theme',
    accent: 'cyan', scanline: 'off', dotgrid: 'off' };
}

/** The appearance cache and the hub's appearance answer pinned to one choice, the first run passed. */
async function pinAppearance(page: Page, prefs: ReturnType<typeof preferences>) {
  await page.addInitScript(({ cache }) => {
    localStorage.setItem('hud.appearance.v1:/', JSON.stringify({ version: 2, preferences: cache }));
    localStorage.setItem('hud.seen', '1');
    localStorage.setItem('hud.firstrun.dismissed', '1');
  }, { cache: prefs });
  await page.route('**/api/preferences/appearance', (route) => route.fulfill({
    status: 200, contentType: 'application/json', json: { revision: 'shots', configured: true, preferences: prefs },
  }));
}

async function prepare(page: Page, look: Look, shot: Shot) {
  const prefs = preferences(look);
  await page.addInitScript(({ cache }) => {
    localStorage.setItem('hud.appearance.v1:/', JSON.stringify({ version: 2, preferences: cache }));
    localStorage.setItem('hud.seen', '1');
    // the first-run gate (onboarding-state.ts FIRST_RUN_DISMISS_KEY) would otherwise cover a live
    // shot whenever the fixture hub's command center says the install is not ready
    localStorage.setItem('hud.firstrun.dismissed', '1');
  }, { cache: prefs });
  await page.route('**/api/preferences/appearance', (route) => route.fulfill({
    status: 200, contentType: 'application/json', json: { revision: 'shots', configured: true, preferences: prefs },
  }));
  if (shot.safeMode) {
    // the fixture hub runs without its lifespan, so its own /status may not answer: the notice
    // needs an answered /status that reports safe mode
    await page.route((url) => url.pathname === '/status', async (route) => {
      const response = await route.fetch().catch(() => null);
      const json = response && response.ok() ? await response.json().catch(() => ({})) : {};
      await route.fulfill({ status: 200, contentType: 'application/json',
        json: { ...json, safe_mode: { enabled: true, skipped: ['plugins', 'owner_jobs'] } } });
    });
  }
}

/** What the page measures of itself (CSS px). */
async function measure(page: Page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const main = document.querySelector('[data-frame="page"]') as HTMLElement | null;
    let min = Infinity;
    let where = '';
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.textContent || !node.textContent.trim()) continue;
      const el = node.parentElement;
      if (!el || el.closest('[data-visually-hidden], [hidden]')) continue;
      const rect = el.getBoundingClientRect();
      if (!rect.width || !rect.height) continue;
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) continue;
      const size = parseFloat(style.fontSize);
      if (size < min) { min = size; where = `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? `.${el.className.trim().split(/\s+/).join('.')}` : ''}`; }
    }
    return {
      overflowX: Math.max(root.scrollWidth, document.body.scrollWidth) - window.innerWidth,
      pageScroll: Math.max(root.scrollHeight - window.innerHeight, main ? main.scrollHeight - main.clientHeight : 0),
      minFont: Number.isFinite(min) ? min : null,
      minFontAt: where,
      frame: !!document.querySelector('[data-frame="masthead"]'),
    };
  });
}

/** The open docket entry's signature as the docket shows it now (its SignLine where the request takes a typed
 *  phrase, its row with Sign where it takes one or two steps): how much of it lies outside the window and
 *  outside the view of the scrolling body that holds it (the register's body), each side. The body clips what
 *  it holds: a line inside the window but below the body's view is not visible. Not evaluated where no entry
 *  is open, or the open one signs elsewhere (a payment or a skill change: a link to its page). */
type SignView = Gate & { hidden?: { below: number; above: number; left: number; right: number }; titleAbove?: number; entryAbove?: number; firstAbove?: number; firstText?: string; scrolled?: number; height?: number; friction?: string };
async function docketSignView(page: Page): Promise<SignView> {
  return page.evaluate(() => {
    const sign = document.querySelector<HTMLElement>('[data-register="docket"] .n-entry--open :is(.n-signline, .n-entry__signrow)');
    if (!sign || !sign.getClientRects().length) return { evaluated: false, ok: true, detail: 'no open entry with a signature drawn' };
    const r = sign.getBoundingClientRect();
    const root = document.documentElement;
    const view = { left: 0, top: 0, right: root.clientWidth, bottom: root.clientHeight };
    // every box around it that clips what it holds (the docket's scrolling body first of all)
    for (let el = sign.parentElement; el && el !== root; el = el.parentElement) {
      const cs = getComputedStyle(el);
      if (cs.display === 'inline' || cs.display === 'contents') continue;
      const b = el.getBoundingClientRect();
      const left = b.left + el.clientLeft;
      const top = b.top + el.clientTop;
      if (cs.overflowX !== 'visible') { view.left = Math.max(view.left, left); view.right = Math.min(view.right, left + el.clientWidth); }
      if (cs.overflowY !== 'visible') { view.top = Math.max(view.top, top); view.bottom = Math.min(view.bottom, top + el.clientHeight); }
    }
    const round = (n: number) => Math.max(0, Math.round(n * 10) / 10);
    const hidden = { below: round(r.bottom - view.bottom), above: round(view.top - r.top), left: round(view.left - r.left), right: round(r.right - view.right) };
    const out = Object.entries(hidden).filter(([, px]) => px > 0.5);
    const friction = sign.getAttribute('data-friction') || '';
    const what = sign.classList.contains('n-signline') ? 'SignLine' : `signature (${friction || 'Sign'})`;
    // the decision it signs stays in view with it: the open entry's title is not above the view (where the docket
    // scrolls its body to show the signature, it stops at the title)
    const title = sign.closest('.n-entry--open')?.querySelector<HTMLElement>('.n-entry__title');
    const titleAbove = title ? round(view.top - title.getBoundingClientRect().top) : 0;
    // and so does the entry's first line (its tier word, who asked, when): the final gate found the docket
    // scrolling it out of view to reach the signature (Classic, Romanian, 1100px; every phone)
    const entry = sign.closest<HTMLElement>('.n-entry--open');
    const entryAbove = entry ? round(view.top - entry.getBoundingClientRect().top) : 0;
    // and so does everything the docket's body draws above the entry: its state line ("Demo sample — signing is
    // disabled.", "Unknown — …"), an outcome, the column heads. The body's first drawn text, measured by its own
    // line box (a Range over the text, not the element's padding): the final round's verifier found the docket
    // scrolling 21-22px in Classic, English, at 1100×800 and the demo's state line cut under the head's rule,
    // which the entry's first line alone did not see
    const body = sign.closest<HTMLElement>('.n-register__body');
    let firstAbove = 0;
    let firstText = '';
    if (body) {
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.textContent || !node.textContent.trim()) continue;
        const el = node.parentElement;
        if (!el || el.closest('[data-visually-hidden], [hidden]')) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        const box = Array.from(range.getClientRects()).find((b) => b.width > 0 && b.height > 0);
        if (!box) continue;
        firstAbove = round(view.top - box.top);
        firstText = node.textContent.trim().slice(0, 48);
        break;
      }
    }
    const problems = out.map(([side, px]) => `${px}px of its ${Math.round(r.height)}px ${side === 'below' ? 'below' : side === 'above' ? 'above' : `past the ${side} edge of`} what the docket's body and the window show`);
    if (titleAbove > 0.5) problems.push(`the open entry's title starts ${titleAbove}px above the body's view`);
    if (entryAbove > 0.5) problems.push(`the open entry's first line (its tier word) starts ${entryAbove}px above the body's view`);
    if (firstAbove > 0.5) problems.push(`the docket body's first line ("${firstText}") starts ${firstAbove}px above the body's view, cut under the head's rule`);
    return {
      evaluated: true, ok: problems.length === 0, hidden, titleAbove, entryAbove, firstAbove, firstText, scrolled: Math.round((title?.closest('.n-register__body')?.scrollTop ?? 0) * 10) / 10, height: Math.round(r.height * 10) / 10, friction,
      detail: problems.length
        ? `the open entry's ${what} is not fully visible with its title: ${problems.join(', ')}`
        : `the open entry's ${what} is whole inside the docket body's view and the window, its title in view`,
    };
  });
}

/** §9.5 docket-1280: only when the docket draws entries (they carry data-docket-entry). */
async function docketGate(page: Page): Promise<Gate> {
  const entries = page.locator('[data-register="docket"] [data-docket-entry]');
  const count = await entries.count();
  if (!count) return { evaluated: false, ok: true, detail: 'no docket entries on screen (empty, refused or unanswered feed)' };
  // as the docket first draws it, before anything below scrolls its body
  const sign = await docketSignView(page);
  if (sign.evaluated && !sign.ok) return { evaluated: true, ok: false, detail: sign.detail };
  for (let i = 0; i < count; i++) {
    // the entry's own hand: Sign (or "Open to sign"); the open entry signs on its SignLine
    const control = entries.nth(i).locator('[data-verb="sign"], [data-verb="open"]').first();
    if (!(await control.count())) continue;
    await control.scrollIntoViewIfNeeded();
    // a trial click needs an enabled control; demo disables every decision control, so check
    // what a click would reach instead: nothing may cover the control's centre
    const reached = await control.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !!at && (at === el || el.contains(at));
    });
    if (!reached) return { evaluated: true, ok: false, detail: `entry ${i + 1}'s sign control is covered or off screen` };
  }
  return { evaluated: true, ok: true, detail: `${count} entries checked; ${sign.evaluated ? sign.detail : 'no entry open'}` };
}

/** What sec-heads counts: the rows it measured, by kind (section heads, register heads, totals), and the
 *  rows of register heads side by side it compared (`beside`: two or more heads, level, apart). */
type HeadsCounts = { sec: number; head: number; total: number; beside: number };
type HeadsGate = Gate & { counts: HeadsCounts; problems: string[] };

/** sec-heads: every section head (.n-sec: its title and aside), register head (.n-register__head: its
 *  title and meta) and total (.n-total: its sentence and aside) drawn now, in `within` (a popover) or
 *  the whole page. Each is a row of a title and a flow beside it (frame/kit/Register.tsx), and
 *  (a) the title takes no more lines than it would alone in the row, and is not cut where alone it
 *      would be whole (measured by giving it the whole row for a moment: its style, set and put back
 *      in the same task, so nothing is painted and nothing observes it);
 *  (b) the flow's box and the title's lie inside the row's box, no text of the row is drawn past it,
 *      and none of the flow's text is drawn over the title's;
 *  (c) a text that is cut (its laid-out extent past a box that clips it, by more than fit.ts
 *      CUT_EPSILON, in fractions of a pixel as Chromium cuts) is cut by a box inside its row that draws
 *      an ellipsis for it (text-overflow: ellipsis, the text its inline content), and keeps its whole
 *      text in a title or an accessible name (aria-label, or a heading's, button's or link's own words)
 *      of that box or a box around it up to the row. A text cut by a box outside its row (a register's
 *      body, the page around a popover that reaches past it) is cut without an ellipsis, and has run
 *      past its row.
 *  The heads of the registers drawn side by side (level with each other and apart across the row):
 *  (d) the rules under them lie on one line: the tops of their bottom rules within 0.5px, whichever head
 *      wraps;
 *  (e) where none of them wraps (each title on one line; each meta, if drawn, on its title's line and on
 *      one line), each is as tall as a register head is (its --register-head-h), within 0.5px: their one
 *      height adds no space in the usual case.
 *  A popover (`within`) lies inside the window itself; one that reaches past it is a problem too. */
async function secHeadsGate(page: Page, within: string | null = null): Promise<HeadsGate> {
  return page.evaluate(({ within, CUT }) => {
    type X = { left: number; right: number };
    const KINDS = [
      { kind: 'sec', row: '.n-sec', title: 'n-sec__title', flow: 'n-sec__aside', flowName: 'aside' },
      { kind: 'head', row: '.n-register__head', title: 'n-register__title', flow: 'n-register__meta', flowName: 'meta' },
      { kind: 'total', row: '.n-total', title: 'n-total__main', flow: 'n-total__aside', flowName: 'aside' },
    ] as const;
    const counts = { sec: 0, head: 0, total: 0, beside: 0 };
    const root = within ? document.querySelector(within) : document.body;
    if (!root) return { evaluated: false, ok: true, detail: `no ${within}`, counts, problems: [] };
    const problems: string[] = [];
    if (within) {
      const sb = root.getBoundingClientRect();
      const vw = document.documentElement.clientWidth;
      if (sb.left < -0.5) problems.push(`the popover begins ${(-sb.left).toFixed(1)}px left of the window`);
      if (sb.right > vw + 0.5) problems.push(`the popover ends ${(sb.right - vw).toFixed(1)}px right of the window`);
    }
    const norm = (s: string | null | undefined) => (s || '').replace(/\s+/g, ' ').trim();
    const css = (el: Element) => getComputedStyle(el);
    const unseen = (el: Element | null): boolean => {
      for (let a = el; a && a !== document.documentElement; a = a.parentElement) {
        if (a.hasAttribute('data-visually-hidden') || a.hasAttribute('hidden')) return true;
        const cs = css(a);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse' || cs.opacity === '0' || /^inset\(50%/.test(cs.clipPath || '')) return true;
      }
      return false;
    };
    const texts = (el: Element): Text[] => {
      const out: Text[] = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
        if (norm(node.textContent) && !unseen(node.parentElement)) out.push(node);
      }
      return out;
    };
    const rectsOf = (node: Text): DOMRect[] => {
      const range = document.createRange();
      range.selectNodeContents(node);
      return Array.from(range.getClientRects()).filter((q) => q.width > 0.25 && q.height > 0.25);
    };
    /** A box's inner edges (inside its border and padding): where its lines end. */
    const inner = (el: Element): X => {
      const b = el.getBoundingClientRect();
      const cs = css(el);
      return { left: b.left + (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.paddingLeft) || 0), right: b.right - (parseFloat(cs.borderRightWidth) || 0) - (parseFloat(cs.paddingRight) || 0) };
    };
    /** What a box lets its contents draw: its padding box. */
    const shown = (el: Element): X => {
      const b = el.getBoundingClientRect();
      return { left: b.left + el.clientLeft, right: b.left + el.clientLeft + el.clientWidth };
    };
    const clips = (el: Element) => { const cs = css(el); return cs.overflowX !== 'visible' && cs.display !== 'inline' && cs.display !== 'contents'; };
    /** How far rects run past a box's inner edges, sideways (0 when inside). */
    const past = (rects: DOMRect[], box: X) => Math.max(0, ...rects.map((q) => Math.max(q.right - box.right, box.left - q.left)));
    /** The lines a box's text takes: its text's rects, one line where their middles are within half
     *  the shorter's height of each other (a large figure and its words on one line are one line). */
    const lines = (el: Element): number => {
      const items = texts(el).flatMap(rectsOf).map((q) => ({ c: (q.top + q.bottom) / 2, h: q.height })).sort((a, b) => a.c - b.c);
      let count = 0;
      let c = 0;
      let h = 0;
      for (const q of items) {
        if (count && Math.abs(q.c - c) < Math.min(q.h, h) / 2) continue;
        count += 1;
        c = q.c;
        h = q.h;
      }
      return count;
    };
    /** Whether a box cuts its own text: it clips, and its text runs past its inner edges. */
    const cutsItself = (el: Element) => clips(el) && past(texts(el).flatMap(rectsOf), inner(el)) > CUT;
    const ownName = (el: Element) => /^H[1-6]$|^BUTTON$/.test(el.tagName) || (el.tagName === 'A' && el.hasAttribute('href'))
      || /^(?:heading|button|link|tab|menuitem)$/.test(el.getAttribute('role') || '');
    /** The whole of a cut text kept for the reader: in a title or an accessible name of `from` or a box
     *  around it, up to the row. */
    const kept = (whole: string, from: Element, row: Element) => {
      for (let a: Element | null = from; a; a = a.parentElement) {
        if (norm(a.getAttribute('title')).includes(whole) || norm(a.getAttribute('aria-label')).includes(whole)) return true;
        if (ownName(a) && !a.hasAttribute('aria-label') && !a.hasAttribute('aria-labelledby') && norm(a.textContent).includes(whole)) return true;
        if (a === row) break;
      }
      return false;
    };
    const named = (el: Element) => (typeof el.className === 'string' && el.className.trim() ? `.${el.className.trim().split(/\s+/)[0]}` : el.tagName.toLowerCase());
    for (const spec of KINDS) {
      for (const row of Array.from(root.querySelectorAll<HTMLElement>(spec.row))) {
        if (!row.getClientRects().length || unseen(row)) continue;
        const rb = row.getBoundingClientRect();
        if (rb.width < 1) continue;
        counts[spec.kind] += 1;
        const title = Array.from(row.children).find((c) => c.classList.contains(spec.title)) as HTMLElement | undefined;
        const flow = Array.from(row.children).find((c) => c.classList.contains(spec.flow)) as HTMLElement | undefined;
        const reg = row.closest('[data-register]')?.getAttribute('data-register');
        const where = `${spec.kind} "${norm(title?.textContent).slice(0, 32)}"${reg ? ` (${reg})` : ''}`;
        const own: string[] = [];
        // (a) the title as it is, then alone in the row. Without a transition while its style is set and
        // put back: calm motion transitions every property for 0.01ms (reduced motion), and a
        // transition's start value outranks even an inline !important one, so the title would be
        // measured as it was; the style put back is computed before the transition is let go
        if (title && texts(title).length) {
          const now = { lines: lines(title), cut: cutsItself(title) };
          const style = title.getAttribute('style');
          const still = (extra: string) => title.setAttribute('style', `${style ? `${style};` : ''}transition: none !important;${extra}`);
          still('flex: 0 0 100% !important; max-width: 100% !important; min-width: 0 !important;');
          const alone = { lines: lines(title), cut: cutsItself(title) };
          still('');
          void title.getBoundingClientRect();
          if (style === null) title.removeAttribute('style'); else title.setAttribute('style', style);
          if (now.lines > alone.lines) own.push(`(a) the title takes ${now.lines} lines; alone in the row it takes ${alone.lines}`);
          if (now.cut && !alone.cut) own.push('(a) the title is cut; alone in the row it is whole');
        }
        // (b) the boxes inside the row
        for (const [name, el] of [[spec.flowName, flow], ['title', title]] as const) {
          if (!el || !el.getClientRects().length) continue;
          const b = el.getBoundingClientRect();
          const out = Math.max(rb.left - b.left, b.right - rb.right);
          if (out > 0.5) own.push(`(b) the ${name} ends ${out.toFixed(1)}px past the row`);
        }
        // (b) and (c): every text of the row, where it is drawn and what cuts it
        const drawn: Record<'title' | 'flow', Array<{ left: number; right: number; top: number; bottom: number }>> = { title: [], flow: [] };
        for (const node of texts(row)) {
          const rects = rectsOf(node);
          if (!rects.length) continue;
          const words = norm(node.textContent).slice(0, 40);
          let seen: X = { left: Math.min(...rects.map((q) => q.left)), right: Math.max(...rects.map((q) => q.right)) };
          let cutter: Element | null = null;
          for (let a = node.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
            if (!clips(a)) continue;
            if (!cutter && past(rects, inner(a)) > CUT) cutter = a;
            const s = shown(a);
            seen = { left: Math.max(seen.left, s.left), right: Math.min(seen.right, s.right) };
          }
          if (seen.right - seen.left > 0.5) {
            if (seen.left < rb.left - 0.5 || seen.right > rb.right + 0.5) own.push(`(b) "${words}" is drawn past the row (${Math.round(seen.left)}..${Math.round(seen.right)} of ${Math.round(rb.left)}..${Math.round(rb.right)})`);
            const part = title?.contains(node) ? 'title' : flow?.contains(node) ? 'flow' : null;
            if (part) for (const q of rects) drawn[part].push({ left: Math.max(q.left, seen.left), right: Math.min(q.right, seen.right), top: q.top, bottom: q.bottom });
          }
          if (!cutter) continue;
          const by = named(cutter);
          const amount = past(rects, inner(cutter)).toFixed(2);
          if (cutter !== row && !row.contains(cutter)) {
            own.push(`(c) "${words}" is cut by ${by}${within && !root.contains(cutter) ? ' around the popover' : ''}, outside the row, without an ellipsis (${amount}px)`);
            continue;
          }
          let inline = true;
          for (let a = node.parentElement; a && a !== cutter; a = a.parentElement) if (css(a).display !== 'inline') inline = false;
          const cs = css(cutter);
          if (cs.textOverflow !== 'ellipsis' || !inline || /flex|grid/.test(cs.display)) own.push(`(c) "${words}" is cut by ${by} without an ellipsis (${amount}px)`);
          const whole = norm(cutter.textContent);
          if (!kept(whole, cutter, row)) own.push(`(c) "${whole.slice(0, 48)}" is cut, its whole text in no title or accessible name`);
        }
        const meets = (p: { left: number; right: number; top: number; bottom: number }, q: typeof p) => Math.min(p.right, q.right) - Math.max(p.left, q.left) > 0.5 && Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top) > 0.5;
        if (drawn.flow.some((f) => drawn.title.some((t) => meets(f, t)))) own.push(`(b) the ${spec.flowName}'s words are drawn over the title's`);
        for (const p of own) problems.push(`${where}: ${p}`);
      }
    }
    // (d) and (e): the heads of the registers side by side. A head wraps where its title takes more than
    // one line, or its meta is drawn under the title (on the head's next line: below the title's box, which
    // a meta beside it, on the title's baseline, always overlaps, however tall a figure makes the title) or
    // on more than one line; its own height is --register-head-h, a register head's with nothing wrapping
    type Head = { name: string; r: DOMRect; rule: number; own: number; wraps: boolean };
    const heads: Head[] = Array.from(root.querySelectorAll<HTMLElement>('.n-register > .n-register__head'))
      .filter((h) => h.getClientRects().length > 0 && !unseen(h) && h.getBoundingClientRect().width >= 1)
      .map((h) => {
        const r = h.getBoundingClientRect();
        const cs = css(h);
        const title = Array.from(h.children).find((c) => c.classList.contains('n-register__title')) as HTMLElement | undefined;
        const meta = Array.from(h.children).find((c) => c.classList.contains('n-register__meta')) as HTMLElement | undefined;
        const tr = title ? title.getBoundingClientRect() : null;
        const mr = meta && meta.getClientRects().length > 0 && texts(meta).length > 0 ? meta.getBoundingClientRect() : null;
        const wraps = (!!title && lines(title) > 1) || (!!mr && !!tr && (mr.top >= tr.bottom - 0.5 || lines(meta as HTMLElement) > 1));
        const reg = h.parentElement?.getAttribute('data-register');
        return { name: reg || `"${norm(title?.textContent).slice(0, 24)}"`, r, rule: r.bottom - (parseFloat(cs.borderBottomWidth) || 0),
          own: parseFloat(cs.getPropertyValue('--register-head-h')) || 0, wraps };
      });
    const beside = (a: Head, b: Head) => (a.r.right <= b.r.left + 0.5 || b.r.right <= a.r.left + 0.5) && Math.min(a.rule, b.rule) - Math.max(a.r.top, b.r.top) > 0;
    const rowsOf: Head[][] = [];
    for (const h of heads) {
      const group = rowsOf.find((g) => g.some((o) => beside(o, h)));
      if (group) group.push(h); else rowsOf.push([h]);
    }
    for (const group of rowsOf) {
      if (group.length < 2) continue;
      counts.beside += 1;
      const said = (h: Head) => `${h.name} ${h.r.height.toFixed(1)}px${h.wraps ? ', wraps' : ''}`;
      for (let i = 0; i < group.length; i += 1) {
        for (let j = i + 1; j < group.length; j += 1) {
          const [a, b] = [group[i], group[j]];
          if (Math.abs(a.rule - b.rule) > 0.5) problems.push(`(d) the rules under the ${a.name} and ${b.name} heads are ${Math.abs(a.rule - b.rule).toFixed(1)}px apart (${said(a)}; ${said(b)})`);
        }
      }
      if (!group.some((h) => h.wraps)) {
        for (const h of group) {
          if (h.own > 0 && Math.abs(h.r.height - h.own) > 0.5) problems.push(`(e) the ${h.name} head is ${h.r.height.toFixed(1)}px tall with nothing beside it wrapping; a register head is ${h.own}px`);
        }
      }
    }
    const unique = [...new Set(problems)];
    const total = counts.sec + counts.head + counts.total;
    return {
      evaluated: true, ok: unique.length === 0, counts, problems: unique,
      detail: unique.join('; ') || (total ? `${counts.sec} section heads, ${counts.head} register heads and ${counts.total} totals whole and inside their rows; ${counts.beside} rows of register heads side by side level` : 'no section head, register head or total drawn'),
    };
  }, { within, CUT: 0.003 });
}

/** What register-inset counts: the top-level registers it measured (`framed`: drawn as a card, `ruled`:
 *  drawn with rules), and the texts, controls and totals of the framed ones it held to their margin. */
type InsetCounts = { registers: number; framed: number; ruled: number; texts: number; controls: number; totals: number };
/** The nearest any text or control of a framed register came to the inner edge of its frame (px), and what. */
type InsetNearest = Record<'left' | 'right' | 'bottom', { px: number; what: string } | null>;
type InsetGate = Gate & { counts: InsetCounts; nearest: InsetNearest; problems: string[] };

/** register-inset: every top-level register drawn now (an .n-register inside no other). A register whose
 *  frame is drawn (a side border wider than 0, or a ground that is not transparent: Atlas, Console,
 *  Threshold and Workbench, light and dark, and Classic · Obsidian and Graphite, from 760px) keeps what it
 *  holds off that frame by its margin m, its own side padding (the look's --n-register-pad,
 *  frame/kit/kit.css):
 *  (a) m is more than 0, the same on the left and the right; and the bottom keeps it: a register with no
 *      foot pads its bottom by m, and a register with a foot has its foot's last box end m or more above
 *      the frame (the foot keeps the margin there, collapsed with a margin that box keeps of its own);
 *  (b) no visible text (each text node's client rects, via Range, cut to every box inside the register
 *      that clips it: a scrolling body shows only what is in its view), no control's box (button, input,
 *      textarea, select, a, [role=button]) and no total's box (.n-total: its double rule), each cut the
 *      same way, lies closer to the inner edge of its border than m, less 0.5px, on the left, the right or
 *      the bottom.
 *  A register drawn with rules (Ledger, Briefing, Presence: no side border, no ground) has no padding on
 *  those edges at all (c): its column is as it was. And below 760px (a phone) no register is framed, in
 *  any look (d): its column is as wide as the rule looks draw it (a margin there cut words that had been
 *  whole). The top is not measured: the head's strut sets the title under the top edge, and the margin
 *  leaves the top as it was. The edges are straight lines: a rounded corner's curve is not measured. */
async function registerInsetGate(page: Page): Promise<InsetGate> {
  return page.evaluate(() => {
    type Box = { left: number; top: number; right: number; bottom: number };
    type Side = 'left' | 'right' | 'bottom';
    const SIDES: Side[] = ['left', 'right', 'bottom'];
    const counts = { registers: 0, framed: 0, ruled: 0, texts: 0, controls: 0, totals: 0 };
    const nearest: Record<Side, { px: number; what: string } | null> = { left: null, right: null, bottom: null };
    const problems: string[] = [];
    // a phone: no register is framed there (d); the window's width, as the stylesheets' media queries read it
    const phone = window.matchMedia('(max-width: 759px)').matches;
    const norm = (s: string | null | undefined) => (s || '').replace(/\s+/g, ' ').trim();
    const css = (el: Element) => getComputedStyle(el);
    const px = (value: string) => parseFloat(value) || 0;
    const fixed = (value: number) => (Number.isFinite(value) ? value.toFixed(1) : 'n/a');
    /** A computed colour that paints nothing: transparent, or a colour at alpha 0 (rgba(…, 0), or … / 0)). */
    const clear = (colour: string) => /^transparent$|^rgba\((?:[^,()]+,){3}\s*0\)$|\/\s*0\)$/.test(colour.trim());
    const hiddenMemo = new Map<Element, boolean>();
    const hidden = (el: Element | null): boolean => {
      if (!el || el === document.documentElement) return false;
      const memo = hiddenMemo.get(el);
      if (memo !== undefined) return memo;
      const cs = css(el);
      const out = el.hasAttribute('data-visually-hidden') || el.hasAttribute('hidden') || cs.display === 'none'
        || cs.visibility === 'hidden' || cs.visibility === 'collapse' || cs.opacity === '0' || /^inset\(50%/.test(cs.clipPath || '')
        || hidden(el.parentElement);
      hiddenMemo.set(el, out);
      return out;
    };
    const ALL: Box = { left: -Infinity, top: -Infinity, right: Infinity, bottom: Infinity };
    const registers = Array.from(document.querySelectorAll<HTMLElement>('.n-register'))
      .filter((reg) => !reg.parentElement?.closest('.n-register'));
    for (const reg of registers) {
      if (!reg.getClientRects().length || hidden(reg)) continue;
      const rb = reg.getBoundingClientRect();
      if (rb.width < 1 || rb.height < 1) continue;
      counts.registers += 1;
      const cs = css(reg);
      const border = { left: px(cs.borderLeftWidth), right: px(cs.borderRightWidth), bottom: px(cs.borderBottomWidth) };
      const pad: Record<Side, number> = { left: px(cs.paddingLeft), right: px(cs.paddingRight), bottom: px(cs.paddingBottom) };
      const framed = border.left > 0 || border.right > 0 || !clear(cs.backgroundColor);
      const name = reg.getAttribute('data-register') || `"${norm(reg.querySelector('.n-register__title')?.textContent).slice(0, 32)}"`;
      const padding = `left ${pad.left}px, right ${pad.right}px, bottom ${pad.bottom}px`;
      if (!framed) {
        counts.ruled += 1;
        if (SIDES.some((side) => pad[side] > 0.01)) problems.push(`(c) ${name}: drawn with rules, yet padded (${padding})`);
        continue;
      }
      counts.framed += 1;
      if (phone) problems.push(`(d) ${name}: framed at ${window.innerWidth}px, below 760px (its column ${fixed(rb.width - border.left - border.right - pad.left - pad.right)}px of the ${fixed(rb.width)}px the rule looks give it; ${padding})`);
      // its margin: its own side padding, one value on both sides
      const m = pad.left;
      const foot = reg.querySelector(':scope > .n-register__main > .n-register__foot');
      const edge: Record<Side, number> = { left: rb.left + border.left, right: rb.right - border.right, bottom: rb.bottom - border.bottom };
      // the boxes inside the register that clip what they hold (a scrolling body, an ellipsis), per element
      const clipMemo = new Map<Element, Box>();
      const clipOf = (el: Element | null): Box => {
        if (!el || el === reg || !reg.contains(el)) return ALL;
        const memo = clipMemo.get(el);
        if (memo) return memo;
        const up = clipOf(el.parentElement);
        const ecs = css(el);
        let out = up;
        if (ecs.display !== 'inline' && ecs.display !== 'contents' && (ecs.overflowX !== 'visible' || ecs.overflowY !== 'visible')) {
          const b = el.getBoundingClientRect();
          const left = b.left + el.clientLeft;
          const top = b.top + el.clientTop;
          out = {
            left: ecs.overflowX !== 'visible' ? Math.max(up.left, left) : up.left,
            right: ecs.overflowX !== 'visible' ? Math.min(up.right, left + el.clientWidth) : up.right,
            top: ecs.overflowY !== 'visible' ? Math.max(up.top, top) : up.top,
            bottom: ecs.overflowY !== 'visible' ? Math.min(up.bottom, top + el.clientHeight) : up.bottom,
          };
        }
        clipMemo.set(el, out);
        return out;
      };
      const worst: Record<Side, { px: number; what: string }> = { left: { px: Infinity, what: '' }, right: { px: Infinity, what: '' }, bottom: { px: Infinity, what: '' } };
      const close: Record<Side, number> = { left: 0, right: 0, bottom: 0 };
      /** One visible box (a text's line, a control, a total): how near it comes to each edge. True if any of it shows. */
      const take = (rects: DOMRectList | DOMRect[], clip: Box, what: string): boolean => {
        let shows = false;
        for (const q of Array.from(rects)) {
          const v = { left: Math.max(q.left, clip.left), right: Math.min(q.right, clip.right), top: Math.max(q.top, clip.top), bottom: Math.min(q.bottom, clip.bottom) };
          if (v.right - v.left <= 0.25 || v.bottom - v.top <= 0.25) continue;
          shows = true;
          const d: Record<Side, number> = { left: v.left - edge.left, right: edge.right - v.right, bottom: edge.bottom - v.bottom };
          for (const side of SIDES) {
            if (d[side] < worst[side].px) worst[side] = { px: d[side], what };
            if (d[side] < m - 0.5) close[side] += 1;
          }
        }
        return shows;
      };
      const walker = document.createTreeWalker(reg, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
        const parent = node.parentElement;
        if (!norm(node.textContent) || !parent || hidden(parent) || parent.closest('select, textarea')) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        if (take(range.getClientRects(), clipOf(parent), `"${norm(node.textContent).slice(0, 32)}"`)) counts.texts += 1;
      }
      for (const control of Array.from(reg.querySelectorAll('button, input, textarea, select, a, [role="button"]'))) {
        if (hidden(control)) continue;
        const what = `${control.tagName.toLowerCase()} "${norm(control.getAttribute('aria-label') || control.textContent || control.getAttribute('placeholder')).slice(0, 32)}"`;
        if (take(control.getClientRects(), clipOf(control.parentElement), what)) counts.controls += 1;
      }
      // a total's box, to its double rule
      for (const total of Array.from(reg.querySelectorAll('.n-total'))) {
        if (hidden(total)) continue;
        if (take(total.getClientRects(), clipOf(total.parentElement), `total "${norm(total.textContent).slice(0, 32)}"`)) counts.totals += 1;
      }
      for (const side of SIDES) {
        if (Number.isFinite(worst[side].px) && (!nearest[side] || worst[side].px < (nearest[side]?.px ?? Infinity))) {
          nearest[side] = { px: Number(worst[side].px.toFixed(2)), what: `${name}: ${worst[side].what}` };
        }
      }
      const said = (side: Side) => `${fixed(worst[side].px)}px from the ${side} edge (${worst[side].what || 'nothing'})`;
      if (m < 0.5 || Math.abs(pad.right - m) > 0.01) {
        problems.push(`(a) ${name}: its frame is drawn and it keeps no margin inside it, or not the same on both sides (${padding}); nearest ${SIDES.map(said).join(', ')}`);
      } else if (!foot && Math.abs(pad.bottom - m) > 0.01) {
        problems.push(`(a) ${name}: no foot, and its bottom padding is not its ${m}px margin (${padding})`);
      } else if (foot) {
        // the foot keeps the margin: its last box ends m or more above the frame
        const last = Array.from(foot.children).filter((child) => !hidden(child) && child.getClientRects().length).pop();
        const gap = last ? edge.bottom - last.getBoundingClientRect().bottom : Infinity;
        if (gap < m - 0.5) problems.push(`(a) ${name}: its foot's last box (${last?.tagName.toLowerCase()}.${(last?.className || '').toString().trim().split(/\s+/).join('.')}) ends ${fixed(gap)}px above the frame, inside its ${m}px margin`);
      }
      for (const side of SIDES) {
        if (close[side]) problems.push(`(b) ${name}: ${close[side]} text, control or total boxes closer to the ${side} edge than its ${m}px margin, nearest ${said(side)}`);
      }
    }
    const near = SIDES.map((side) => `${side} ${nearest[side] ? `${nearest[side]?.px}px` : 'n/a'}`).join(', ');
    return {
      evaluated: true, ok: problems.length === 0, counts, nearest, problems,
      detail: problems.join('; ') || (counts.registers
        ? `${counts.framed} framed registers keep ${counts.texts} texts, ${counts.controls} controls and ${counts.totals} totals inside their margin (nearest: ${near}); ${counts.ruled} drawn with rules, unpadded`
        : 'no register drawn'),
    };
  });
}

/** What area-frame counts: the area pages' columns it measured (`mains`), and the registers inside them it
 *  held to (b): every register drawn, and those drawn as cards (`framed`). */
type AreaCounts = { mains: number; registers: number; framed: number };
type AreaGate = Gate & { counts: AreaCounts; problems: string[] };

/** area-frame: the column an area page draws (.n-areapage__main: Trust, Work, Timeline, the conversation page,
 *  every mode page drawn through PageSection and every panel page) is not a card (frame/frame.css):
 *  (a) it draws no fill (its ground is transparent, no image), no side or bottom border and no shadow: only
 *      the look's top rule opens it, in every look;
 *  (b) no register drawn as a card (a side border wider than 0, or a ground that is not transparent) has a
 *      framed ancestor (by the same measure) up to and including that column: no card inside a card.
 *  Found after the register-inset round: in every card look the column drew the look's panel treatment, the
 *  page's title 0px from its frame at every width and every register a card whose frame lay on the area
 *  frame's edge. Not evaluated on a page with no area column (Home, Glance). */
async function areaFrameGate(page: Page): Promise<AreaGate> {
  return page.evaluate(() => {
    const px = (value: string) => parseFloat(value) || 0;
    /** A computed colour that paints nothing: transparent, or a colour at alpha 0 (rgba(…, 0), or … / 0)). */
    const clear = (colour: string) => /^transparent$|^rgba\((?:[^,()]+,){3}\s*0\)$|\/\s*0\)$/.test(colour.trim());
    const framed = (el: Element) => {
      const cs = getComputedStyle(el);
      return px(cs.borderLeftWidth) > 0 || px(cs.borderRightWidth) > 0 || !clear(cs.backgroundColor);
    };
    const norm = (s: string | null | undefined) => (s || '').replace(/\s+/g, ' ').trim();
    const named = (el: Element) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${typeof el.className === 'string' && el.className.trim() ? `.${el.className.trim().split(/\s+/).slice(0, 3).join('.')}` : ''}`;
    const counts = { mains: 0, registers: 0, framed: 0 };
    const problems: string[] = [];
    for (const main of Array.from(document.querySelectorAll<HTMLElement>('.n-areapage__main'))) {
      if (!main.getClientRects().length) continue;
      counts.mains += 1;
      const cs = getComputedStyle(main);
      if (!clear(cs.backgroundColor) || cs.backgroundImage !== 'none') problems.push(`(a) the page's column draws a fill (${cs.backgroundColor}${cs.backgroundImage !== 'none' ? `, ${cs.backgroundImage}` : ''})`);
      for (const side of ['left', 'right', 'bottom'] as const) {
        const width = px(cs.getPropertyValue(`border-${side}-width`));
        if (width > 0 && cs.getPropertyValue(`border-${side}-style`) !== 'none') problems.push(`(a) the page's column draws a ${side} border (${width}px ${cs.getPropertyValue(`border-${side}-style`)} ${cs.getPropertyValue(`border-${side}-color`)})`);
      }
      if (cs.boxShadow !== 'none') problems.push(`(a) the page's column draws a shadow (${cs.boxShadow})`);
      for (const reg of Array.from(main.querySelectorAll<HTMLElement>('.n-register'))) {
        if (!reg.getClientRects().length || getComputedStyle(reg).visibility === 'hidden') continue;
        counts.registers += 1;
        if (!framed(reg)) continue;
        counts.framed += 1;
        for (let up = reg.parentElement; up; up = up.parentElement) {
          if (framed(up)) {
            const ucs = getComputedStyle(up);
            problems.push(`(b) the register "${norm(reg.querySelector('.n-register__title')?.textContent).slice(0, 40)}" is a card inside a card: ${up === main ? 'the page\'s column' : named(up)} around it is framed (border ${ucs.borderLeftWidth} / ${ucs.borderRightWidth}, ground ${ucs.backgroundColor})`);
            break;
          }
          if (up === main) break;
        }
      }
    }
    return {
      evaluated: counts.mains > 0, ok: problems.length === 0, counts, problems,
      detail: problems.join('; ') || (counts.mains
        ? `the page's column draws its top rule only; ${counts.framed} of ${counts.registers} registers drawn as cards, none inside another`
        : 'no area page column on this page'),
    };
  });
}

function shoot(size: Size, look: Look, shot: Shot, demo: boolean) {
  const name = `${shot.id}${demo ? '-demo' : ''}-${size.name}-${look.look}-${look.scheme}`;
  test(name, async ({ page, baseURL }) => {
    const origin = new URL(baseURL!).origin;
    const errors: string[] = [];
    const http: string[] = [];
    const external: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() !== 'error') return;
      const text = msg.text();
      const failed = FAILED_RESOURCE.exec(text);
      // an HTTP answer the page draws as refused or unavailable: reported, not a console error
      if (failed) { http.push(`${failed[1] ?? failed[2]} ${msg.location().url || ''}`.trim()); return; }
      errors.push(text);
    });
    page.on('pageerror', (error) => errors.push(`uncaught: ${error.message}`));
    page.on('request', (req) => {
      const url = new URL(req.url());
      if ((url.protocol === 'http:' || url.protocol === 'https:') && url.origin !== origin) external.push(url.href);
    });
    await page.route((url) => url.origin !== origin && (url.protocol === 'http:' || url.protocol === 'https:'), (route) => route.abort());
    await prepare(page, look, shot);
    await page.goto(`${shot.path}${demo ? '?demo=1' : ''}`);
    await page.waitForLoadState('networkidle');
    // the page drawn before it is measured: the frame's masthead, or Glance's running head (Glance
    // has no masthead; without a wait, a slow start was shot blank once the network went idle)
    if (shot.id !== 'glance') await expect(page.locator('[data-frame="masthead"]')).toBeVisible();
    else await expect(page.locator('[data-frame="runhead"]')).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    const m = await measure(page);
    const axe = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze();
    const contrast = axe.violations.flatMap((v) => v.nodes.map((n) => `${n.target.join(' ')}: ${n.failureSummary?.split('\n')[1]?.trim() || v.id}`));
    const docket = size.name === '1280' && shot.id === 'home' ? await docketGate(page) : null;
    const runhead = await runheadGate(page);
    const masthead = await mastheadGate(page);
    const secHeads = await secHeadsGate(page);
    const registerInset = await registerInsetGate(page);
    const areaFrame = await areaFrameGate(page);
    mkdirSync(OUT, { recursive: true });
    await page.screenshot({ path: join(OUT, `${name}.png`) });
    const gates = {
      'overflow-x': m.overflowX <= 0,
      'page-scroll': !shot.fixedPage || m.pageScroll <= 1,
      'min-font': !look.nerva || (m.minFont !== null && m.minFont >= 12),
      contrast: contrast.length === 0,
      console: errors.length === 0,
      external: external.length === 0,
      ...(runhead.evaluated ? { runhead: runhead.ok } : {}),
      ...(masthead.evaluated ? { masthead: masthead.ok } : {}),
      ...(docket && docket.evaluated ? { 'docket-1280': docket.ok } : {}),
      'sec-heads': secHeads.ok,
      'register-inset': registerInset.ok,
      ...(areaFrame.evaluated ? { 'area-frame': areaFrame.ok } : {}),
    };
    const result = {
      name, page: shot.id, path: shot.path, demo, width: size.width, height: size.height, scale: size.scale,
      look: look.look, scheme: look.scheme, frame: m.frame, gates,
      measured: { overflowX: m.overflowX, pageScroll: m.pageScroll, minFont: m.minFont, minFontAt: m.minFontAt },
      contrast, errors, http, external, runhead, masthead, ...(docket ? { docket } : {}), secHeads, registerInset, areaFrame,
    };
    REPORT.push(result);
    mkdirSync(RUN_DIR, { recursive: true });
    writeFileSync(join(RUN_DIR, `${name}.json`), JSON.stringify(result, null, 2));
    for (const [gate, ok] of Object.entries(gates)) expect.soft(ok, `${name}: ${gate}`).toBe(true);
  });
}

// A manual lane: the ordinary e2e lane (playwright.config.ts) finds this file too, and skips it.
test.beforeEach(async ({}, testInfo) => {
  test.skip(testInfo.project.name !== 'ledger-shots', 'manual lane: npx playwright test -c playwright.ledger-shots.config.ts');
});

for (const size of SIZES) {
  test.describe(`${size.width}×${size.height}`, () => {
    test.use({ viewport: { width: size.width, height: size.height }, deviceScaleFactor: size.scale });
    for (const look of LOOKS) {
      for (const shot of PAGES) for (const sample of SAMPLES) shoot(size, look, shot, sample.demo);
      if (size.name === '1920') shoot(size, look, NOTICES, true);
    }
  });
}

/* ---- the geometry gates (see the header): the masthead's one row, the running head's line and
   marks, the running foot at phone widths, the marks of the floating window and Glance ---------- */

const GATE_LOOKS: Look[] = [LOOKS[0], LOOKS[2]];   // Ledger dark, Classic · Obsidian
const GATE_LANGS = ['en', 'ro'] as const;
type GateLang = typeof GATE_LANGS[number];
const FIT_WIDTHS = [1100, 1180, 1280, 1340, 1440, 1680, 1920, 2560];
/** The masthead's extra cases (the stop halted, Presence, comfy density) at fewer widths. */
const FIT_EXTRA_WIDTHS = [1100, 1180, 1280, 1340, 1680, 2560];
/** The masthead's window height for a width: 1280 × 820 is the owner's default shell. */
const mastHeight = (width: number) => (width >= 2560 ? 1353 : width === 1280 ? 820 : 900);
const MARK_WIDTHS = [320, 390, 600, 740];
const PRESENCE: Look = { look: 'presence', scheme: 'dark', nerva: true };
const ATLAS_LIGHT: Look = { look: 'atlas', scheme: 'light', nerva: true };
const PLAIN: Settings = { id: 'default' };
const COMFY: Settings = { id: 'comfy', density: 'comfy' };
const MONO: Settings = { id: 'mono', font: 'jetbrains-mono' };
/** A light area page (Trust is the current area, so the link with the widest note is also bold). */
const GATE_PATH = '/v2/trust';

const answer = (body: unknown) => (route: Route) => route.fulfill({ status: 200, contentType: 'application/json', json: body });
const refuse = (route: Route) => route.fulfill({ status: 403, contentType: 'application/json', json: { detail: 'admin token required' } });
/** Two frames: whatever a resize or an answer changed is laid out and fitted. */
const settle = (page: Page) => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
/** No transition running. Calm motion (theme/overrides.css) gives every element a 0.01ms transition on every
 *  property, and a computed value read before the frame that ends it is still the last width's: right after the
 *  window crossed 760px, under load, register-inset once read a register framed with the 8px margin it has at
 *  760px. A walk that measures what a width draws waits for them (5s at most). */
const quiet = (page: Page) => page.waitForFunction(() => !document.getAnimations().some((a) => a.playState === 'running'), null, { timeout: 5_000 }).catch(() => undefined);
const caseName = (look: Look, settings: Settings = PLAIN) => `${look.look}-${look.scheme}${settings.id === 'default' ? '' : `-${settings.id}`}`;
/** A window height for a width (the shapes of the owner's screens). */
const heightFor = (width: number) => (width >= 2560 ? 1353 : width >= 1920 ? 1080 : width >= 1440 ? 900 : 800);

/** All three notes drawn beside their areas (each lands with its own poll). */
async function notesLanded(page: Page) {
  for (const key of ['docket', 'services', 'record']) {
    await expect(page.locator(`[data-frame="masthead"] .n-masthead__areas [data-note="${key}"]`)).toHaveCount(1);
  }
}

/** A docket of 128 entries waiting on the owner (four agents): the docket's note, and the foot's
 *  "waiting on you". */
async function widestDocket(page: Page) {
  const now = new Date().toISOString();
  const agents = ['pepper', 'stark', 'friday', 'jarvis'];
  await page.route((url) => url.pathname === '/autonomy/tasks' && url.searchParams.get('status') === 'blocked', answer({
    tasks: Array.from({ length: 128 }, (_, i) => ({ id: 9000 + i, kind: 'send_email', title: `Request ${i + 1}`, agent: agents[i % 4], created_at: now, risk_tier: 1 })),
    groups: [],
  }));
}

/** Every attention note at its widest: a docket of 128 entries, 12 services down, the record broken
 *  at a six-figure entry; the stop armed (or halted: "Halted · resume in Trust"). */
async function widestNotes(page: Page, { halted = false }: { halted?: boolean } = {}) {
  await widestDocket(page);
  await page.route((url) => url.pathname === '/autonomy/observer', answer({
    enabled: true, probes: 20, tracked: 20,
    unhealthy: Array.from({ length: 12 }, (_, i) => ({ key: `service.probe${i + 1}`, detail: `probe ${i + 1} is not answering`, severity: 'WARN', since: null })),
  }));
  await page.route((url) => url.pathname === '/api/security/audit/verify', answer({ valid: false, entries: 992144, first_invalid_id: 412907, tamper_evident: true }));
  await page.route((url) => url.pathname === '/api/security/kill-switch', answer(halted
    ? { global: true, any_halted: true, halted_count: 1 } : { global: false, any_halted: false, halted_count: 0 }));
}

type Box = { id: string; left: number; right: number; top: number; bottom: number; width: number; height: number; onTop: boolean };

/** The masthead's row: one row tall; every area link and every tool drawn whole inside it and the
 *  viewport, the links inside their strip (not scrolling), none overlapping, each on top at its
 *  centre; Find's words, when drawn, not cut. */
async function mastheadFitGate(page: Page, { halted = false }: { halted?: boolean } = {}) {
  return page.evaluate(({ halted }) => {
    const mast = document.querySelector('[data-frame="masthead"]') as HTMLElement | null;
    if (!mast) return { ok: false, detail: 'no masthead', fit: '', height: 0, boxes: [] as Box[] };
    const vw = document.documentElement.clientWidth;
    const row = mast.getBoundingClientRect();
    const box = (id: string, el: Element): Box => {
      const r = el.getBoundingClientRect();
      const hit = r.width > 0 && r.height > 0 ? document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) : null;
      return { id, left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height, onTop: !!hit && (hit === el || el.contains(hit)) };
    };
    const problems: string[] = [];
    const strip = mast.querySelector('.n-masthead__areas') as HTMLElement | null;
    const links = Array.from(mast.querySelectorAll('.n-masthead__areas a[data-area]')).map((el) => box(`area:${el.getAttribute('data-area')}`, el));
    if (links.length !== 9) problems.push(`${links.length} of 9 area links`);
    const TOOLS: Array<[string, string]> = [
      ['brand', '.n-masthead__brand'], ['find', '.n-masthead__find'], ['language', '.n-masthead__lang'],
      ['scheme', '[data-scheme-toggle]'], ['glance', '[data-anchor="glance"]'], ['stop', '.n-masthead__stop, .n-masthead__halted'],
    ];
    const tools = TOOLS.map(([id, selector]) => {
      const el = mast.querySelector(selector);
      if (!el) problems.push(`${id} is missing`);
      return el ? box(id, el) : null;
    }).filter((b): b is Box => !!b);
    const all = [...links, ...tools];
    for (const b of all) {
      if (!(b.width > 0 && b.height > 0)) { problems.push(`${b.id} is not drawn`); continue; }
      if (b.left < row.left - 0.5 || b.right > row.right + 0.5 || b.top < row.top - 0.5 || b.bottom > row.bottom + 0.5) {
        problems.push(`${b.id} is outside the masthead row (${Math.round(b.left)}..${Math.round(b.right)} of ${Math.round(row.left)}..${Math.round(row.right)})`);
      }
      if (b.left < -0.5 || b.right > vw + 0.5) problems.push(`${b.id} is cut by the viewport (${Math.round(b.left)}..${Math.round(b.right)} of ${vw})`);
      if (!b.onTop) problems.push(`${b.id} is covered at its centre`);
    }
    if (strip) {
      const s = strip.getBoundingClientRect();
      if (strip.scrollWidth - strip.clientWidth > 1) problems.push(`the areas strip holds ${strip.scrollWidth}px in ${strip.clientWidth}px`);
      for (const b of links) if (b.left < s.left - 0.5 || b.right > s.right + 0.5) problems.push(`${b.id} spills out of its strip`);
    } else problems.push('no areas strip');
    for (let i = 0; i < all.length; i++) {
      for (let j = i + 1; j < all.length; j++) {
        const a = all[i];
        const b = all[j];
        const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (x > 0.5 && y > 0.5) problems.push(`${a.id} overlaps ${b.id} by ${Math.round(x)}px`);
      }
    }
    // one row tall: what the row draws sits on one line, and the header is no taller than the
    // tallest of it (or its own minimum height)
    const leaves = Array.from(mast.querySelectorAll<HTMLElement>(
      '.n-masthead__mark, .n-masthead__areas .n-areas__label, .n-masthead__find, .n-masthead__lang, [data-scheme-toggle], [data-anchor="glance"], .n-masthead__stop, .n-masthead__halted',
    )).map((el) => el.getBoundingClientRect()).filter((r) => r.width > 0 && r.height > 0);
    const middles = leaves.map((r) => r.top + r.height / 2);
    const half = Math.min(...leaves.map((r) => r.height)) / 2;
    if (middles.length && Math.max(...middles) - Math.min(...middles) > half) problems.push('the masthead draws more than one row');
    const tallest = Math.max(0, ...leaves.map((r) => r.height));
    const minimum = parseFloat(getComputedStyle(mast).minHeight) || 0;
    if (mast.clientHeight > Math.max(minimum, tallest) + 1) problems.push(`the header is ${mast.clientHeight}px tall for one row of ${Math.round(Math.max(minimum, tallest))}px`);
    // Find's words, when drawn, whole (a placeholder gives way at its steps, it is never cut). In
    // fractions of a pixel: Chromium draws the ellipsis for any overflow of a layout unit (1/64px),
    // which whole-pixel scrollWidth and clientWidth cannot see (0.44px read as 44 in 43, or as equal)
    // (fit.ts textOverflow: the text's extent from a Range against the box's inner edges, or the
    // whole pixels where they say more; cut beyond 0.003px, under a layout unit at up to 4×)
    const past = (el: HTMLElement): number => {
      const range = document.createRange();
      range.selectNodeContents(el);
      const rects = Array.from(range.getClientRects()).filter((q) => q.width > 0 && q.height > 0);
      if (!rects.length) return 0;
      const cs = getComputedStyle(el);
      const b = el.getBoundingClientRect();
      const inner = { left: b.left + (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.paddingLeft) || 0), right: b.right - (parseFloat(cs.borderRightWidth) || 0) - (parseFloat(cs.paddingRight) || 0) };
      return Math.max(Math.max(...rects.map((q) => q.right)) - inner.right, inner.left - Math.min(...rects.map((q) => q.left)), 0);
    };
    const words = mast.querySelector<HTMLElement>('.n-masthead__find-words');
    const findPast = words ? past(words) : 0;
    const findWhole = words ? Math.max(0, words.scrollWidth - words.clientWidth) : 0;
    if (words && Math.max(findPast, findWhole) > 0.003) {
      problems.push(`Find's words are cut: their text runs ${findPast.toFixed(2)}px past their box (${words.scrollWidth}px in ${words.clientWidth}px in whole pixels), and an ellipsis is drawn`);
    }
    // the notes are the widest the gate meant (the stubs landed)
    const notes = Array.from(mast.querySelectorAll('.n-masthead__areas a[data-area] [data-note]')).map((el) => el.getAttribute('data-note'));
    for (const key of ['docket', 'services', 'record']) if (!notes.includes(key)) problems.push(`no ${key} note: the stub did not land`);
    const stop = mast.querySelector('.n-masthead__stop, .n-masthead__halted');
    if (halted && stop?.getAttribute('data-stop') !== 'halted') problems.push('the stop is not halted: the stub did not land');
    if (halted && !stop?.getAttribute('title')) problems.push('the halted stop has no title');
    return {
      ok: problems.length === 0, detail: problems.join('; ') || 'one row: nine areas and six tools whole, apart and in it',
      fit: mast.getAttribute('data-fit') || '', height: mast.clientHeight, boxes: all,
    };
  }, { halted });
}

/* What is drawn, measured in the page: the gates below call `window.__nervaRow` and
   `window.__nervaPaint` (installed by installGates). A text node's drawn part is its client rects
   clipped by every ancestor up to its item that scrolls or clips (an ellipsis-cut value, a visually
   hidden label: nothing drawn outside its box); an item is "on top" when elementFromPoint at its
   centre finds it or a child.

   __nervaPaint(scope, { around, margin }) looks at everything painted in `scope` (or, with `around`,
   only what involves that element: its own paints, or a collision on its box, among the paints within
   `margin` px of it): every text node's drawn part, every mark (an svg), every element's fill (a
   background colour or image; decoration with no content and no pointer events, such as Classic's
   texture layers, is the page's ground and is left out) and its rules (each border side). A text or a mark
   that meets a paint of an element that is neither its ancestor nor its descendant is drawn over or
   under it: text over text, a rule through a word, a fill over a sentence, a figure under a mark.
   A text is compared by its core, the middle half of its line box, so a tight line height (two lines
   of a large figure, a label over its value) is not a collision; a rule is compared whole. A text
   whose box reaches past what its clipping ancestors let it draw is cut: a scrolling ancestor is taken
   at its whole scrollable extent, so what lies below the fold is not cut, but what lies above or left
   of where scrolling starts can never be reached; an ellipsis that cuts a value on purpose is not.
   A positioned ::before / ::after is measured from its computed offsets and size within its
   containing block, and paints its fill and rules as its element's; an underlined text paints its
   underline as a rule of the element that decorates it, at the baseline the font's metrics give
   (canvas measureText) plus its offset. An in-flow pseudo-element, a box shadow and an outline are
   not seen (the header lists the limits).

   __nervaTakeBack(kind) answers, for the masthead or the running head as fitted, which of the steps
   written could be taken back with the row still fitting by the row's own measure (the replica of
   Masthead.tsx rowSpills and RunningHead.tsx runheadSpills / runheadLoss below): none, when the fit
   keeps nothing a later step made unneeded. It writes each try on the row and puts the steps back
   before it returns, in the same task: no frame is painted, and neither row observes its data-fit. */
type RowItem = { id: string; left: number; right: number; top: number; bottom: number; width: number; drawn: string; scroll: number; client: number };
type RowGate = { ok: boolean; detail: string; steps: string; lines: number; items: RowItem[] };
type PaintGate = { ok: boolean; detail: string; problems: string[]; checked: { texts: number; marks: number; fills: number; rules: number } };

async function installGates(page: Page) {
  await page.evaluate(() => {
    type R = { left: number; right: number; top: number; bottom: number };
    /** How far an element's text runs past its own content box, in fractions of a pixel: the text's
     *  extent (a Range over its contents) against the box's inner edges, or the whole pixels
     *  scrollWidth and clientWidth give where they say more. Chromium draws an ellipsis
     *  (text-overflow) for any overflow of one layout unit (1/64px), which the whole pixels alone
     *  cannot see (fit.ts textOverflow measures the same way). */
    /** The text's own extent past the box (a Range), in px; 0 where it has none drawn. */
    const textPast = (el: Element | null): number => {
      if (!(el instanceof HTMLElement)) return 0;
      const range = document.createRange();
      range.selectNodeContents(el);
      const rects = Array.from(range.getClientRects()).filter((q) => q.width > 0 && q.height > 0);
      if (!rects.length) return 0;
      const cs = getComputedStyle(el);
      const b = el.getBoundingClientRect();
      const innerLeft = b.left + (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.paddingLeft) || 0);
      const innerRight = b.right - (parseFloat(cs.borderRightWidth) || 0) - (parseFloat(cs.paddingRight) || 0);
      return Math.max(Math.max(...rects.map((q) => q.right)) - innerRight, innerLeft - Math.min(...rects.map((q) => q.left)), 0);
    };
    const cutPx = (el: Element | null): number => (el instanceof HTMLElement ? Math.max(textPast(el), el.scrollWidth - el.clientWidth, 0) : 0);
    /** Cut: by more than this (fit.ts CUT_EPSILON: under a layout unit, 1/64 of a device pixel, up to 4×). */
    const CUT = 0.003;
    (window as unknown as { __nervaCutPx: unknown }).__nervaCutPx = cutPx;
    (window as unknown as { __nervaTextPast: unknown }).__nervaTextPast = textPast;
    const meet = (a: R, b: R): R | null => {
      const r = { left: Math.max(a.left, b.left), right: Math.min(a.right, b.right), top: Math.max(a.top, b.top), bottom: Math.min(a.bottom, b.bottom) };
      return r.right - r.left > 0.5 && r.bottom - r.top > 0.5 ? r : null;
    };
    /** The drawn part of a text node: its rects, clipped by the clipping ancestors up to `stop`. */
    const drawnRects = (node: Text, stop: Element): R[] => {
      let clip: R | null = null;
      for (let el = node.parentElement; el; el = el.parentElement) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return [];
        if (cs.clipPath && cs.clipPath !== 'none') return [];   // the visually hidden pattern (inset 50%)
        if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
          const r = el.getBoundingClientRect();
          clip = clip ? meet(clip, r) : { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
          if (!clip) return [];
        }
        if (el === stop) break;
      }
      const range = document.createRange();
      range.selectNodeContents(node);
      return Array.from(range.getClientRects()).map((r) => (clip ? meet(r, clip) : r)).filter((r): r is R => !!r && r.right - r.left > 0.5 && r.bottom - r.top > 0.5);
    };
    (window as unknown as { __nervaRow: unknown }).__nervaRow = (rowSelector: string, itemSelector: string, opts: { count?: number; oneLine?: boolean }) => {
      const row = document.querySelector(rowSelector) as HTMLElement | null;
      if (!row) return { ok: false, detail: `no ${rowSelector}`, steps: '', lines: 0, items: [] };
      const vw = document.documentElement.clientWidth;
      const steps = row.getAttribute('data-fit') || '';
      const problems: string[] = [];
      const els = Array.from(row.querySelectorAll<HTMLElement>(itemSelector)).filter((el) => {
        const r = el.getBoundingClientRect();
        return opts.count !== undefined || (r.width > 0 && r.height > 0);
      });
      if (opts.count !== undefined && els.length !== opts.count) problems.push(`${els.length} of ${opts.count} items`);
      const items = els.map((el, i) => {
        const r = el.getBoundingClientRect();
        const id = el.getAttribute('data-signal') || el.getAttribute('data-runhead') || el.getAttribute('data-machine')
          || el.getAttribute('data-chrome') || el.getAttribute('data-activity') || el.getAttribute('data-runfoot') || `#${i + 1}`;
        let drawn = '';
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
          const text = (node.textContent || '').trim();
          if (!text) continue;
          const rects = drawnRects(node, el);
          if (!rects.length) continue;
          drawn += `${drawn ? ' ' : ''}${text}`;
          for (const t of rects) {
            if (t.left < r.left - 1 || t.right > r.right + 1 || t.top < r.top - 1 || t.bottom > r.bottom + 1) {
              problems.push(`${id}: "${text}" is drawn outside its item (${Math.round(t.left)}..${Math.round(t.right)} of ${Math.round(r.left)}..${Math.round(r.right)})`);
            }
            if (t.left < -0.5 || t.right > vw + 0.5) problems.push(`${id}: "${text}" is cut by the viewport`);
          }
        }
        // a value cut with an ellipsis: only where the row's fit has taken its "cut" step (the running
        // head's egress statement and model id), never before it, and never in a row with no such step
        if (!steps.split(' ').includes('cut')) {
          for (const part of Array.from(el.querySelectorAll<HTMLElement>('*'))) {
            if (getComputedStyle(part).textOverflow !== 'ellipsis') continue;
            if (cutPx(part) > CUT) {
              problems.push(`${id}: "${(part.textContent || '').trim().slice(0, 40)}" is cut with an ellipsis before the fit's "cut" step (its text ${textPast(part).toFixed(2)}px past its box; ${part.scrollWidth}px in ${part.clientWidth}px in whole pixels)`);
            }
          }
        }
        if (!(r.width > 0 && r.height > 0)) problems.push(`${id} is not drawn`);
        else {
          if (el.scrollWidth - el.clientWidth > 1) problems.push(`${id} holds ${el.scrollWidth}px in ${el.clientWidth}px`);
          if (r.left < -0.5 || r.right > vw + 0.5) problems.push(`${id} is cut by the viewport (${Math.round(r.left)}..${Math.round(r.right)} of ${vw})`);
          const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          if (!hit || !(hit === el || el.contains(hit))) problems.push(`${id} is covered at its centre`);
        }
        return { id, left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, drawn, scroll: el.scrollWidth, client: el.clientWidth };
      });
      for (let i = 0; i < items.length; i += 1) {
        for (let j = i + 1; j < items.length; j += 1) {
          const a = items[i];
          const b = items[j];
          const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (x > 0.5 && y > 0.5) problems.push(`${a.id} overlaps ${b.id} by ${Math.round(x)}px`);
        }
      }
      const drawnItems = items.filter((it) => it.width > 0);
      const middles = drawnItems.map((it) => (it.top + it.bottom) / 2).sort((a, b) => a - b);
      const half = Math.min(...drawnItems.map((it) => it.bottom - it.top)) / 2;
      let lines = middles.length ? 1 : 0;
      for (let i = 1; i < middles.length; i += 1) if (middles[i] - middles[i - 1] > half) lines += 1;
      if (opts.oneLine && lines > 1 && !steps.split(' ').includes('lines')) problems.push(`on ${lines} lines without the last-resort step`);
      return { ok: problems.length === 0, detail: problems.join('; ') || `${items.length} items whole, apart and on top, on ${lines} line${lines === 1 ? '' : 's'}`, steps, lines, items };
    };

    const EVERYWHERE: R = { left: -Infinity, top: -Infinity, right: Infinity, bottom: Infinity };
    const style = new Map<Element, CSSStyleDeclaration>();
    const css = (el: Element) => { let s = style.get(el); if (!s) { s = getComputedStyle(el); style.set(el, s); } return s; };
    /** Not painted: not displayed, invisible, transparent, or the visually hidden pattern. */
    const unpainted = new Map<Element, boolean>();
    const hidden = (el: Element | null): boolean => {
      if (!el) return false;
      const known = unpainted.get(el);
      if (known !== undefined) return known;
      const cs = css(el);
      const own = cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse' || cs.opacity === '0'
        || /^inset\(50%/.test(cs.clipPath || '');
      const result = own || hidden(el.parentElement);
      unpainted.set(el, result);
      return result;
    };
    const meetAll = (a: R, b: R): R => ({ left: Math.max(a.left, b.left), top: Math.max(a.top, b.top), right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom) });
    /** What an element's ancestors (and, for its own text, the element itself: `inclusive`) let it
     *  draw. `seen`: what is on screen now — every box that clips (overflow other than visible; an
     *  inline box or display: contents clips nothing) and the window. `reach`: what scrolling can
     *  bring on screen — the clipping boxes up to the nearest scroller, which counts at its whole
     *  scrollable extent from where its scrolling starts (what lies above it limits its window, not
     *  what it can bring into view), else the document when the window scrolls, the window when not. */
    const clipsOf = (el: Element, inclusive = false): { seen: R; reach: R } => {
      const html = document.documentElement;
      let seen: R = { left: 0, top: 0, right: html.clientWidth, bottom: html.clientHeight };
      let reach = EVERYWHERE;
      let scroller = false;
      for (let a = inclusive ? el : el.parentElement; a && a !== html && a !== document.body; a = a.parentElement) {
        const cs = css(a);
        if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
        if (cs.display === 'inline' || cs.display === 'contents') continue;
        const r = a.getBoundingClientRect();
        const pad: R = { left: r.left + a.clientLeft, top: r.top + a.clientTop, right: r.left + a.clientLeft + a.clientWidth, bottom: r.top + a.clientTop + a.clientHeight };
        seen = meetAll(seen, pad);
        if (scroller) continue;
        const scrollsX = cs.overflowX === 'auto' || cs.overflowX === 'scroll';
        const scrollsY = cs.overflowY === 'auto' || cs.overflowY === 'scroll';
        const left = pad.left - a.scrollLeft;
        const top = pad.top - a.scrollTop;
        reach = meetAll(reach, {
          left: scrollsX ? left : pad.left, top: scrollsY ? top : pad.top,
          right: scrollsX ? left + Math.max(a.scrollWidth, a.clientWidth) : pad.right,
          bottom: scrollsY ? top + Math.max(a.scrollHeight, a.clientHeight) : pad.bottom,
        });
        scroller = scrollsX || scrollsY;
      }
      if (!scroller) {
        const page = css(html).overflowY !== 'visible' ? css(html) : css(document.body);
        const scrollsX = page.overflowX !== 'hidden' && page.overflowX !== 'clip';
        const scrollsY = page.overflowY !== 'hidden' && page.overflowY !== 'clip';
        reach = meetAll(reach, { left: -window.scrollX, top: -window.scrollY,
          right: -window.scrollX + (scrollsX ? Math.max(html.scrollWidth, html.clientWidth) : html.clientWidth),
          bottom: -window.scrollY + (scrollsY ? Math.max(html.scrollHeight, html.clientHeight) : html.clientHeight) });
      }
      return { seen, reach };
    };
    const inter = (a: R, b: R): R | null => {
      const r = { left: Math.max(a.left, b.left), right: Math.min(a.right, b.right), top: Math.max(a.top, b.top), bottom: Math.min(a.bottom, b.bottom) };
      return r.right - r.left > 0.5 && r.bottom - r.top > 0.5 ? r : null;
    };
    /** Whether a computed colour paints at all: rgba(…, a), and any colour function with "/ a"
     *  (the themes' oklch() roles, a color-mix() resolved to color(srgb …)), read for its alpha. */
    const opaque = (color: string): boolean => {
      if (!color || color === 'transparent') return false;
      const slash = /\/\s*([\d.]+)(%?)\s*\)\s*$/.exec(color);
      if (slash) return parseFloat(slash[1]) / (slash[2] ? 100 : 1) > 0.02;
      const legacy = /^rgba\(([^)]+)\)$/.exec(color.trim());
      if (legacy) {
        const parts = legacy[1].split(/[\s,]+/).filter(Boolean);
        return parts.length < 4 || parseFloat(parts[3]) > 0.02;
      }
      return true;
    };
    const tag = (el: Element): string => {
      const cls = typeof el.className === 'string' && el.className.trim() ? `.${el.className.trim().split(/\s+/)[0]}` : '';
      const data = ['data-signal', 'data-runhead', 'data-cell', 'data-frame', 'data-mark', 'data-machine', 'data-activity', 'data-chrome']
        .map((name) => (el.hasAttribute(name) ? `[${name}="${el.getAttribute(name)}"]` : '')).join('');
      return `${el.tagName.toLowerCase()}${cls}${data}`;
    };
    const ellipsis = (el: Element | null, upto: Element): boolean => {
      for (let a = el; a && a !== upto.parentElement; a = a.parentElement) if (css(a).textOverflow === 'ellipsis') return true;
      return false;
    };
    const round = (r: R) => `${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.right - r.left)}×${Math.round(r.bottom - r.top)}`;
    const px = (v: string) => parseFloat(v) || 0;
    /** An element's positioned ::before / ::after (absolute or fixed): its border box, from its
     *  computed offsets and size within its containing block (the nearest positioned or transformed
     *  ancestor, the element itself included). An in-flow one has no box the DOM gives: not seen. */
    const pseudoBoxes = (el: Element): Array<{ which: string; box: R; ps: CSSStyleDeclaration }> => {
      const out: Array<{ which: string; box: R; ps: CSSStyleDeclaration }> = [];
      for (const which of ['::before', '::after']) {
        const ps = getComputedStyle(el, which);
        if (!ps.content || ps.content === 'none' || ps.content === 'normal') continue;
        if (ps.display === 'none' || ps.visibility === 'hidden' || ps.opacity === '0') continue;
        if (ps.position !== 'absolute' && ps.position !== 'fixed') continue;
        let origin = { left: 0, top: 0 };
        if (ps.position === 'absolute') {
          let block: Element | null = el;
          while (block && block !== document.documentElement && css(block).position === 'static' && css(block).transform === 'none') block = block.parentElement;
          if (block && block !== document.documentElement) {
            const r = block.getBoundingClientRect();
            origin = { left: r.left + block.clientLeft - block.scrollLeft, top: r.top + block.clientTop - block.scrollTop };
          } else origin = { left: -window.scrollX, top: -window.scrollY };
        }
        const [left, top, width, height] = [ps.left, ps.top, ps.width, ps.height].map((v) => parseFloat(v));
        if (![left, top, width, height].every(Number.isFinite)) continue;
        const borderBox = ps.boxSizing === 'border-box';
        const w = borderBox ? width : width + px(ps.paddingLeft) + px(ps.paddingRight) + px(ps.borderLeftWidth) + px(ps.borderRightWidth);
        const h = borderBox ? height : height + px(ps.paddingTop) + px(ps.paddingBottom) + px(ps.borderTopWidth) + px(ps.borderBottomWidth);
        const x = origin.left + left + px(ps.marginLeft);
        const y = origin.top + top + px(ps.marginTop);
        out.push({ which, box: { left: x, top: y, right: x + w, bottom: y + h }, ps });
      }
      return out;
    };
    const ascents = new Map<string, number>();
    const pen = document.createElement('canvas').getContext('2d');
    /** The element whose text-decoration underlines a text (its owner, or an inline ancestor up to
     *  the first one that is not inline, whose decoration reaches its inline content), with the
     *  owner font's ascent (from the baseline to the top of the line box a text rect spans) and the
     *  underline's offset below the baseline and thickness ("auto": the usual font proportions). */
    const underlinedBy = (owner: Element): { by: Element; ascent: number; offset: number; thickness: number } | null => {
      for (let a: Element | null = owner; a && a !== document.body; a = a.parentElement) {
        const cs = css(a);
        if ((cs.textDecorationLine || '').includes('underline')) {
          const own = css(owner);
          const size = px(own.fontSize) || 16;
          const font = `${own.fontStyle} ${own.fontWeight} ${own.fontSize} ${own.fontFamily}`;
          let ascent = ascents.get(font);
          if (ascent === undefined) {
            ascent = size * 0.8;
            if (pen) {
              pen.font = font;
              const m = pen.measureText('Hg');
              if (Number.isFinite(m.fontBoundingBoxAscent) && m.fontBoundingBoxAscent > 0) ascent = m.fontBoundingBoxAscent;
            }
            ascents.set(font, ascent);
          }
          const offset = parseFloat(cs.textUnderlineOffset);
          const thickness = parseFloat(cs.textDecorationThickness);
          return { by: a, ascent, offset: Number.isFinite(offset) ? offset : Math.max(1, size * 0.08), thickness: Number.isFinite(thickness) ? thickness : Math.max(1, size / 14) };
        }
        if (cs.display !== 'inline') break;
      }
      return null;
    };

    (window as unknown as { __nervaPaint: unknown }).__nervaPaint = (scopeSelector: string, opts: { around?: string; margin?: number } = {}) => {
      style.clear();
      unpainted.clear();
      const scope = document.querySelector(scopeSelector);
      const none = { texts: 0, marks: 0, fills: 0, rules: 0 };
      if (!scope) return { ok: false, detail: `no ${scopeSelector}`, problems: [`no ${scopeSelector}`], checked: none };
      // around one element: only what involves it — a paint of its own, or a collision on its box —
      // among the paints within `margin` of it (what two other regions do to each other is theirs)
      let region = EVERYWHERE;
      let anchor: Element | null = null;
      let anchorBox = EVERYWHERE;
      if (opts.around) {
        anchor = document.querySelector(opts.around);
        if (!anchor) return { ok: false, detail: `no ${opts.around}`, problems: [`no ${opts.around}`], checked: none };
        const r = anchor.getBoundingClientRect();
        const m = opts.margin ?? 0;
        anchorBox = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
        region = { left: r.left - m, top: r.top - m, right: r.right + m, bottom: r.bottom + m };
      }
      const involves = (els: Element[], at: R) => !anchor || els.some((el) => anchor!.contains(el)) || !!inter(at, anchorBox);
      type Paint = { kind: 'text' | 'mark' | 'fill' | 'rule'; el: Element; r: R; what: string };
      const solids: Paint[] = [];
      const others: Paint[] = [];
      const problems: string[] = [];
      // the marks, the fills and the rules
      for (const el of [scope, ...Array.from(scope.querySelectorAll('*'))]) {
        const inSvg = el.closest('svg');
        if (inSvg && inSvg !== el) continue;
        if (hidden(el)) continue;
        const cs = css(el);
        if (cs.display === 'contents') continue;
        const clip = clipsOf(el).seen;
        for (const rect of Array.from(el.getClientRects())) {
          // a plain box: a DOMRect's sides are getters, which a spread ({ ...rect }) does not copy
          const box: R = { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
          const drawn = inter(box, clip);
          if (!drawn) continue;
          if (/^(svg|img|canvas|video)$/i.test(el.tagName)) {
            const inset = { left: drawn.left + 1, top: drawn.top + 1, right: drawn.right - 1, bottom: drawn.bottom - 1 };
            if (inset.right > inset.left && inset.bottom > inset.top) solids.push({ kind: 'mark', el, r: inset, what: `the mark ${tag(el)}` });
            continue;
          }
          // decoration (Classic's texture and glow layers: no content, no pointer events) is the
          // page's ground, under everything, not a paint that can be drawn over a word
          if (cs.pointerEvents === 'none' && !(el.textContent || '').trim()) continue;
          if (opaque(cs.backgroundColor) || (cs.backgroundImage && cs.backgroundImage !== 'none')) others.push({ kind: 'fill', el, r: drawn, what: `the fill of ${tag(el)}` });
          const sides: Array<[string, R]> = [
            ['top', { ...box, bottom: box.top + parseFloat(cs.borderTopWidth) }],
            ['bottom', { ...box, top: box.bottom - parseFloat(cs.borderBottomWidth) }],
            ['left', { ...box, right: box.left + parseFloat(cs.borderLeftWidth) }],
            ['right', { ...box, left: box.right - parseFloat(cs.borderRightWidth) }],
          ];
          for (const [side, rule] of sides) {
            const across = side === 'top' || side === 'bottom';
            const width = across ? rule.bottom - rule.top : rule.right - rule.left;
            const lineStyle = cs.getPropertyValue(`border-${side}-style`);
            if (!(width >= 0.5) || lineStyle === 'none' || lineStyle === 'hidden' || !opaque(cs.getPropertyValue(`border-${side}-color`))) continue;
            // a hairline under 1px is given its whole device pixel, so a rule through a word is seen
            const line = width < 1 ? { ...rule, ...(across ? { bottom: rule.top + 1 } : { right: rule.left + 1 }) } : rule;
            const seen = inter(line, clip);
            if (seen) others.push({ kind: 'rule', el, r: seen, what: `the ${side} rule of ${tag(el)}` });
          }
        }
        // its positioned ::before / ::after: a fill or a rule of its own (an area's underline bar,
        // a gutter's rule), clipped as the element's content is
        for (const { which, box, ps } of pseudoBoxes(el)) {
          const own = clipsOf(el, true).seen;
          const drawn = inter(box, own);
          if (!drawn) continue;
          const what = `${tag(el)}${which}`;
          if (opaque(ps.backgroundColor) || (ps.backgroundImage && ps.backgroundImage !== 'none')) others.push({ kind: 'fill', el, r: drawn, what: `the fill of ${what}` });
          const sides: Array<[string, R]> = [
            ['top', { ...box, bottom: box.top + (parseFloat(ps.borderTopWidth) || 0) }],
            ['bottom', { ...box, top: box.bottom - (parseFloat(ps.borderBottomWidth) || 0) }],
            ['left', { ...box, right: box.left + (parseFloat(ps.borderLeftWidth) || 0) }],
            ['right', { ...box, left: box.right - (parseFloat(ps.borderRightWidth) || 0) }],
          ];
          for (const [side, rule] of sides) {
            const across = side === 'top' || side === 'bottom';
            const width = across ? rule.bottom - rule.top : rule.right - rule.left;
            const lineStyle = ps.getPropertyValue(`border-${side}-style`);
            if (!(width >= 0.5) || lineStyle === 'none' || lineStyle === 'hidden' || !opaque(ps.getPropertyValue(`border-${side}-color`))) continue;
            const line = width < 1 ? { ...rule, ...(across ? { bottom: rule.top + 1 } : { right: rule.left + 1 }) } : rule;
            const seen = inter(line, own);
            if (seen) others.push({ kind: 'rule', el, r: seen, what: `the ${side} rule of ${what}` });
          }
        }
      }
      // the text: each node's drawn part, and whether its ancestors cut it
      const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
        const words = (node.textContent || '').replace(/\s+/g, ' ').trim();
        const owner = node.parentElement;
        if (!words || !owner || owner.closest('svg') || hidden(owner)) continue;
        const { seen, reach } = clipsOf(owner, true);
        const range = document.createRange();
        range.selectNodeContents(node);
        const underline = underlinedBy(owner);
        for (const full of Array.from(range.getClientRects())) {
          if (full.width < 0.5 || full.height < 0.5) continue;
          const drawn = inter(full, seen);
          const excerpt = words.length > 40 ? `${words.slice(0, 38)}…` : words;
          if (inter(full, region) && involves([owner], full) && (full.left < reach.left - 1 || full.top < reach.top - 1 || full.right > reach.right + 1 || full.bottom > reach.bottom + 1) && !ellipsis(owner, scope)) {
            problems.push(`"${excerpt}" (${tag(owner)}) is cut: ${round(full)} reaches past what scrolling can show (${round(reach)})`);
          }
          if (!drawn) continue;
          const quarter = (full.bottom - full.top) / 4;
          const core = { left: drawn.left + 1, right: drawn.right - 1, top: Math.max(drawn.top, full.top + quarter), bottom: Math.min(drawn.bottom, full.bottom - quarter) };
          if (core.right - core.left > 0.5 && core.bottom - core.top > 0.5) solids.push({ kind: 'text', el: owner, r: core, what: `"${excerpt}" (${tag(owner)})` });
          // its underline, below the baseline the font's metrics give, as a rule of the element
          // that decorates it
          if (underline) {
            const at = full.top + underline.ascent + underline.offset;
            const line = inter({ left: full.left, right: full.right, top: at, bottom: at + Math.max(1, underline.thickness) }, seen);
            if (line) others.push({ kind: 'rule', el: underline.by, r: line, what: `the underline of "${excerpt}" (${tag(owner)})` });
          }
        }
      }
      const related = (a: Element, b: Element) => a === b || a.contains(b) || b.contains(a);
      const seenPairs = new Set<string>();
      const report = (a: Paint, b: Paint, at: R) => {
        const key = `${a.what}|${b.what}`;
        if (seenPairs.has(key)) return;
        seenPairs.add(key);
        problems.push(`${a.what} meets ${b.what} at ${round(at)}`);
      };
      // a collision lies inside both paints, so only paints that meet the region can make one there
      const near = (p: Paint) => !!inter(p.r, region);
      const solidsNear = solids.filter(near);
      const othersNear = others.filter(near);
      for (let i = 0; i < solidsNear.length; i += 1) {
        const a = solidsNear[i];
        for (let j = i + 1; j < solidsNear.length; j += 1) {
          const b = solidsNear[j];
          const at = inter(a.r, b.r);
          if (at && inter(at, region) && involves([a.el, b.el], at) && !related(a.el, b.el)) report(a, b, at);
        }
        for (const b of othersNear) {
          const at = inter(a.r, b.r);
          if (at && inter(at, region) && involves([a.el, b.el], at) && !related(a.el, b.el)) report(a, b, at);
        }
      }
      const checked = {
        texts: solids.filter((p) => p.kind === 'text').length, marks: solids.filter((p) => p.kind === 'mark').length,
        fills: others.filter((p) => p.kind === 'fill').length, rules: others.filter((p) => p.kind === 'rule').length,
      };
      return {
        ok: problems.length === 0,
        detail: problems.length ? `${problems.length} problem${problems.length === 1 ? '' : 's'}: ${problems.slice(0, 12).join('; ')}${problems.length > 12 ? '; …' : ''}`
          : `nothing drawn over anything else and nothing cut (${checked.texts} text runs, ${checked.marks} marks, ${checked.fills} fills, ${checked.rules} rules)`,
        problems, checked,
      };
    };

    (window as unknown as { __nervaTakeBack: unknown }).__nervaTakeBack = (kind: 'masthead' | 'runhead') => {
      const ORDER = kind === 'runhead'
        ? ['source', 'short', 'egress', 'values', 'tight', 'labels', 'mode', 'cut', 'lines']
        : ['search', 'notes', 'glance', 'hand', 'tight', 'brand', 'stop', 'find', 'tighter', 'scroll'];
      const row = document.querySelector<HTMLElement>(`[data-frame="${kind}"]`);
      if (!row) return { back: [] as string[], steps: '', spills: false };
      const written = row.getAttribute('data-fit');
      const taken = ORDER.filter((step) => (written || '').split(' ').includes(step));
      const write = (steps: string[]) => { if (steps.length) row.setAttribute('data-fit', steps.join(' ')); else row.removeAttribute('data-fit'); };
      // fit.ts spillsOver (a box holding more than it shows: whole pixels, as the rows measure it)
      // and textCut (a text cut with an ellipsis: in fractions of a pixel)
      const over = (el: Element | null) => !!el && el.scrollWidth - el.clientWidth > 1;
      const cut = (el: Element | null) => cutPx(el) > CUT;
      // RunningHead.tsx runheadSpills and runheadLoss, as they measure
      const ITEMS = '[data-signal], [data-runhead="mode"], [data-runhead="interrupts"]';
      const PARTS = ':scope > dt, :scope > dd, .n-signals__button, .n-runhead__key, .n-runhead__seg, .n-runhead__fold, .n-runhead__said, .n-runhead__figure';
      const POPOVERS = '.n-disclosure__panel, .n-runhead__pop';
      const hit = (a: DOMRect, b: DOMRect) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.5 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5;
      const runheadSpills = (steps: string[]) => {
        const folded = steps.includes('mode');
        const style = getComputedStyle(row);
        const line = row.getBoundingClientRect();
        const left = line.left + (parseFloat(style.paddingLeft) || 0) - 1;
        const right = line.right - (parseFloat(style.paddingRight) || 0) + 1;
        const items = Array.from(row.querySelectorAll<HTMLElement>(ITEMS));
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
          for (let j = 0; j < i; j += 1) if (boxes[j].width > 0 && hit(box, boxes[j])) return true;
        }
        return !steps.includes('cut') && Array.from(row.querySelectorAll('.n-signals__ident, .n-signals__text')).some((el) => !el.closest(POPOVERS) && cut(el));
      };
      const loss = () => {
        let cutBy = 0;
        for (const el of Array.from(row.querySelectorAll<HTMLElement>('.n-signals__ident, .n-signals__text'))) if (!el.closest(POPOVERS)) cutBy += cutPx(el);
        const boxes = Array.from(row.querySelectorAll<HTMLElement>(ITEMS)).map((item) => item.getBoundingClientRect()).filter((r) => r.width > 0 && r.height > 0);
        const middles = boxes.map((r) => r.top + r.height / 2).sort((a, b) => a - b);
        const half = boxes.length ? Math.min(...boxes.map((r) => r.height)) / 2 : 0;
        let lines = middles.length ? 1 : 0;
        for (let i = 1; i < middles.length; i += 1) if (middles[i] - middles[i - 1] > half) lines += 1;
        return { cut: cutBy, lines };
      };
      // Masthead.tsx rowSpills
      const spills = (steps: string[]) => (kind === 'runhead' ? runheadSpills(steps)
        : over(row) || over(row.querySelector('.n-masthead__areas')) || over(row.querySelector('.n-masthead__tools')) || cut(row.querySelector('.n-masthead__find-words')));
      const back: string[] = [];
      try {
        // a row that spills as fitted (its last resort) has nothing to take back
        if (spills(taken)) return { back, steps: taken.join(' '), spills: true };
        const bar = kind === 'runhead' ? loss() : null;
        for (const step of taken) {
          const without = taken.filter((s) => s !== step);
          write(without);
          if (spills(without)) continue;
          if (bar) {
            const now = loss();
            if (now.cut > bar.cut + CUT || now.lines > bar.lines) continue;
          }
          back.push(step);
        }
      } finally {
        if (written === null) row.removeAttribute('data-fit'); else row.setAttribute('data-fit', written);
      }
      return { back, steps: taken.join(' '), spills: false };
    };

    /** A colour's alpha as computed: rgba(…, a), any colour function with "/ a", 0 for transparent. */
    const alpha = (color: string): number => {
      if (!color || color === 'transparent') return 0;
      const slash = /\/\s*([\d.]+)(%?)\s*\)\s*$/.exec(color);
      if (slash) return parseFloat(slash[1]) / (slash[2] ? 100 : 1);
      const legacy = /^rgba\(([^)]+)\)$/.exec(color.trim());
      if (legacy) {
        const parts = legacy[1].split(/[\s,]+/).filter(Boolean);
        return parts.length < 4 ? 1 : parseFloat(parts[3]);
      }
      return 1;
    };
    /** A surface drawn over the page (a popover, the approval mode's confirmation): inside the window,
     *  on top at its centre and at four points 6px inside its corners, and opaque — its own ground a
     *  colour with no transparency (a translucent one lets the page's words through: Classic's
     *  --surface), and nothing on it or above it fading it (opacity). Its problems, in words. */
    (window as unknown as { __nervaSurface: unknown }).__nervaSurface = (el: Element | null): string[] => {
      if (!(el instanceof HTMLElement)) return ['not in the page'];
      const r = el.getBoundingClientRect();
      if (!(r.width > 0 && r.height > 0)) return ['not drawn'];
      const out: string[] = [];
      const vw = document.documentElement.clientWidth;
      const vh = document.documentElement.clientHeight;
      if (r.left < -0.5 || r.top < -0.5 || r.right > vw + 0.5 || r.bottom > vh + 0.5) {
        out.push(`leaves the window (${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}×${Math.round(r.height)} in ${vw}×${vh})`);
      }
      const inset = Math.min(6, r.width / 4, r.height / 4);
      const points: Array<[string, number, number]> = [
        ['its centre', r.left + r.width / 2, r.top + r.height / 2],
        ['its top left', r.left + inset, r.top + inset], ['its top right', r.right - inset, r.top + inset],
        ['its bottom left', r.left + inset, r.bottom - inset], ['its bottom right', r.right - inset, r.bottom - inset],
      ];
      for (const [where, x, y] of points) {
        if (x < 0 || y < 0 || x >= vw || y >= vh) continue;
        const at = document.elementFromPoint(x, y);
        if (!at || !(at === el || el.contains(at))) out.push(`covered at ${where}${at ? ` by ${at.tagName.toLowerCase()}${typeof at.className === 'string' && at.className ? `.${at.className.trim().split(/\s+/)[0]}` : ''}` : ''}`);
      }
      const ground = getComputedStyle(el).backgroundColor;
      if (alpha(ground) < 0.99) out.push(`see-through: its ground is ${ground}, so what lies under it is drawn through it`);
      for (let a: Element | null = el; a && a !== document.documentElement; a = a.parentElement) {
        const o = parseFloat(getComputedStyle(a).opacity);
        if (Number.isFinite(o) && o < 0.99) { out.push(`faded: opacity ${o} on ${a.tagName.toLowerCase()}`); break; }
      }
      return out;
    };
  });
}

/** A surface's problems (installGates' __nervaSurface): [] when it is inside the window, on top and opaque. */
const surfaceProblems = (page: Page, selector: string): Promise<string[]> =>
  page.evaluate((selector) => (window as unknown as { __nervaSurface: (el: Element | null) => string[] })
    .__nervaSurface(Array.from(document.querySelectorAll(selector)).find((el) => (el as HTMLElement).getClientRects().length > 0) ?? null), selector);

type TakeBack = { back: string[]; steps: string; spills: boolean };
/** Which of the steps a row has written could be taken back with the row still fitting by its own
 *  measure (installGates' __nervaTakeBack): none, when no step is lossier than needed. */
const takeBack = (page: Page, kind: 'masthead' | 'runhead'): Promise<TakeBack> =>
  page.evaluate((kind) => (window as unknown as { __nervaTakeBack: (k: string) => TakeBack }).__nervaTakeBack(kind), kind);
/** A row's steps now and three frames later: a fit that flips back and forth shows as two answers. */
const steadySteps = (page: Page, selector: string): Promise<{ now: string; later: string }> => page.evaluate((selector) => new Promise((resolve) => {
  const read = () => document.querySelector(selector)?.getAttribute('data-fit') || '';
  const now = read();
  requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(() => resolve({ now, later: read() }))));
}), selector);
/** A take-back's words for a gate's detail ("" when no step could be taken back). */
const lossier = (t: TakeBack) => (t.back.length ? `lossier than needed: ${t.back.map((s) => `"${s}"`).join(', ')} could be taken back from "${t.steps}"` : '');

/** Every popover of the running head, opened one at a time (each button clicked, then Escape): the
 *  signals' and the interrupts' disclosures, and the approval mode's own popover (its fold, or its
 *  mark below 760px) where it is drawn as a button. Each must open inside the window, on top at its
 *  centre and inside its corners, and opaque (installGates' __nervaSurface). */
async function popoversGate(page: Page): Promise<{ ok: boolean; problems: string[]; opened: number }> {
  const buttons = page.locator('[data-frame="runhead"] :is(.n-disclosure__button, .n-runhead__fold)');
  const count = await buttons.count();
  const problems: string[] = [];
  let opened = 0;
  for (let i = 0; i < count; i += 1) {
    const button = buttons.nth(i);
    if (!(await button.isVisible())) continue;
    await button.scrollIntoViewIfNeeded();
    await button.click();
    await settle(page);
    const result = await button.evaluate((el) => {
      const name = el.getAttribute('aria-label') || (el.textContent || '').trim();
      if (el.getAttribute('aria-expanded') !== 'true') return { name, problem: 'did not open' };
      const panel = document.getElementById(el.getAttribute('aria-controls') || '');
      if (!panel) return { name, problem: 'no popover' };
      const out = (window as unknown as { __nervaSurface: (el: Element | null) => string[] }).__nervaSurface(panel);
      return { name, problem: out.map((p) => `its popover ${p}`).join('; ') };
    });
    opened += 1;
    if (result.problem) problems.push(`${result.name}: ${result.problem}`);
    await page.keyboard.press('Escape');
    await settle(page);
  }
  return { ok: problems.length === 0, problems, opened };
}

/** What is painted in `scope` (or within `margin` px of `around`): no text or mark drawn over or
 *  under another element's paint, nothing cut or out of reach (see __nervaPaint above). */
const paintGate = (page: Page, scope: string, opts: { around?: string; margin?: number } = {}): Promise<PaintGate> =>
  page.evaluate(({ scope, opts }) => (window as unknown as { __nervaPaint: (s: string, o: object) => PaintGate }).__nervaPaint(scope, opts), { scope, opts });

const RUNHEAD_ITEMS = '[data-signal], [data-runhead="mode"], [data-runhead="interrupts"]';
/** The running head's eight items: whole, apart, on top, on one line (unless the fit's last resort;
 *  `oneLine: false` where the head wraps by design, 760–1099px). */
const runheadRowGate = (page: Page, { oneLine = true }: { oneLine?: boolean } = {}): Promise<RowGate> => page.evaluate(({ items, oneLine }) =>
  (window as unknown as { __nervaRow: (row: string, items: string, opts: object) => RowGate }).__nervaRow('[data-frame="runhead"]', items, { count: 8, oneLine }),
{ items: RUNHEAD_ITEMS, oneLine });

/** The running head below 760px: one line, every item whole inside the viewport and the head, none
 *  overlapping, each on top at its centre, each a named button that opens its popover. */
async function runheadMarksGate(page: Page) {
  return page.evaluate(() => {
    const head = document.querySelector('[data-frame="runhead"]') as HTMLElement | null;
    if (!head) return { ok: false, detail: 'no running head', names: [] as string[] };
    const vw = document.documentElement.clientWidth;
    const hb = head.getBoundingClientRect();
    const problems: string[] = [];
    if (!head.classList.contains('n-runhead--compact')) problems.push('not drawn as marks (n-runhead--compact)');
    const items = Array.from(head.querySelectorAll<HTMLElement>('[data-signal], [data-runhead="mode"], [data-runhead="interrupts"]')).map((el) => {
      const r = el.getBoundingClientRect();
      const hit = r.width > 0 ? document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) : null;
      const button = el.querySelector('button[aria-expanded]');
      return { id: el.getAttribute('data-signal') || el.getAttribute('data-runhead') || '?', r, onTop: !!hit && el.contains(hit), name: button?.getAttribute('aria-label') || '' };
    });
    if (items.length !== 8) problems.push(`${items.length} of 8 items`);
    for (const { id, r, onTop, name } of items) {
      if (!(r.width > 0 && r.height > 0)) { problems.push(`${id} is not drawn`); continue; }
      if (r.left < -0.5 || r.right > vw + 0.5) problems.push(`${id} is cut by the viewport (${Math.round(r.left)}..${Math.round(r.right)} of ${vw})`);
      if (r.left < hb.left - 0.5 || r.right > hb.right + 0.5 || r.top < hb.top - 0.5 || r.bottom > hb.bottom + 0.5) problems.push(`${id} is outside the running head`);
      if (!onTop) problems.push(`${id} is covered at its centre`);
      if (!/^[^:]+: .+/.test(name)) problems.push(`${id} has no button named "Label: value" (${JSON.stringify(name)})`);
    }
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i].r;
        const b = items[j].r;
        if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.5 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5) problems.push(`${items[i].id} overlaps ${items[j].id}`);
      }
    }
    const middles = items.map(({ r }) => r.top + r.height / 2).sort((a, b) => a - b);
    const half = Math.min(...items.map(({ r }) => r.height)) / 2;
    let lines = middles.length ? 1 : 0;
    for (let i = 1; i < middles.length; i++) if (middles[i] - middles[i - 1] > half) lines += 1;
    if (lines !== 1) problems.push(`on ${lines} lines`);
    if (head.scrollWidth - head.clientWidth > 1) problems.push(`the head holds ${head.scrollWidth}px in ${head.clientWidth}px`);
    return { ok: problems.length === 0, detail: problems.join('; ') || `8 items as marks on 1 line in ${Math.round(hb.width)}px`, names: items.map((i) => i.name) };
  });
}

function recordGate(name: string, gate: string, ok: boolean, extra: Record<string, unknown>) {
  recordGates(name, { [gate]: ok }, extra);
}

/** One record with several gates (a case whose own gate and its surroundings are judged apart). */
function recordGates(name: string, gates: Record<string, boolean>, extra: Record<string, unknown>) {
  const result = { name, gates, ...extra };
  REPORT.push(result);
  mkdirSync(RUN_DIR, { recursive: true });
  writeFileSync(join(RUN_DIR, `${name}.json`), JSON.stringify(result, null, 2));
}

test.describe('masthead-fit', () => {
  for (const look of GATE_LOOKS) {
    for (const lang of GATE_LANGS) {
      for (const width of FIT_WIDTHS) {
        test(`masthead-fit-${width}-${look.look}-${look.scheme}-${lang}`, async ({ page }) => {
          await page.setViewportSize({ width, height: mastHeight(width) });
          await pinAppearance(page, preferences(look, lang));
          await widestNotes(page);
          await page.goto(GATE_PATH);
          await page.waitForLoadState('networkidle');
          await page.evaluate(() => document.fonts.ready);
          await notesLanded(page);
          await installGates(page);
          const gate = await mastheadFitGate(page);
          const back = await takeBack(page, 'masthead');
          const ok = gate.ok && !back.back.length;
          const detail = [gate.ok ? '' : gate.detail, lossier(back)].filter(Boolean).join('; ') || gate.detail;
          const name = `masthead-fit-${width}-${look.look}-${look.scheme}-${lang}`;
          recordGate(name, 'masthead-fit', ok, { width, height: mastHeight(width), look: look.look, scheme: look.scheme, lang, detail, fit: gate.fit, takeBack: back.back, rowHeight: gate.height });
          expect.soft(ok, `${name}: ${detail} (fit: "${gate.fit}")`).toBe(true);
        });
      }
      test(`masthead-fit-resize-${look.look}-${look.scheme}-${lang}`, async ({ page }) => {
        await page.setViewportSize({ width: 2560, height: 1353 });
        await pinAppearance(page, preferences(look, lang));
        await widestNotes(page);
        await page.goto(GATE_PATH);
        await page.waitForLoadState('networkidle');
        await page.evaluate(() => document.fonts.ready);
        await notesLanded(page);
        await installGates(page);
        const failures: string[] = [];
        const down: Record<number, string> = {};
        const up: Record<number, string> = {};
        // down through the widths, then back up: the steps come off again as the room returns, so
        // each width takes the same steps whichever way the window reached it, none it could take
        // back, and the same three frames later
        const pass = async (widths: number[], into: Record<number, string>) => {
          for (const width of widths) {
            await page.setViewportSize({ width, height: mastHeight(width) });
            await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
            const gate = await mastheadFitGate(page);
            into[width] = gate.fit;
            if (!gate.ok) failures.push(`${width}px: ${gate.detail}`);
            const back = await takeBack(page, 'masthead');
            if (back.back.length) failures.push(`${width}px: ${lossier(back)}`);
            const steady = await steadySteps(page, '[data-frame="masthead"]');
            if (steady.now !== steady.later) failures.push(`${width}px: the steps flip from "${steady.now}" to "${steady.later}"`);
          }
        };
        await pass([...FIT_WIDTHS].reverse(), down);
        await pass(FIT_WIDTHS.slice(1), up);
        for (const width of FIT_WIDTHS.slice(1)) {
          if (down[width] !== up[width]) failures.push(`${width}px takes "${down[width]}" on the way down and "${up[width]}" on the way up`);
        }
        const name = `masthead-fit-resize-${look.look}-${look.scheme}-${lang}`;
        recordGate(name, 'masthead-fit', failures.length === 0, { look: look.look, scheme: look.scheme, lang, detail: failures.join('; ') || 'fits at every width, down and up', down, up });
        expect.soft(failures, `${name}`).toEqual([]);
      });
    }
  }
  // the extra cases, a fresh load at each of fewer widths: the stop halted ("Halted · resume in
  // Trust", whose "stop" step keeps "Halted" and its title the rest), the largest UI type, comfy
  const EXTRAS: Array<{ id: string; look: Look; settings: Settings; halted: boolean }> = [
    { id: 'halted', look: LOOKS[0], settings: PLAIN, halted: true },
    { id: 'presence', look: PRESENCE, settings: PLAIN, halted: false },
    { id: 'comfy', look: LOOKS[0], settings: COMFY, halted: false },
  ];
  for (const extra of EXTRAS) {
    for (const lang of GATE_LANGS) {
      test(`masthead-fit-${extra.id}-${lang}`, async ({ page }) => {
        await pinAppearance(page, preferences(extra.look, lang, extra.settings));
        await widestNotes(page, { halted: extra.halted });
        const fits: Record<number, string> = {};
        const failures: string[] = [];
        for (const width of FIT_EXTRA_WIDTHS) {
          await page.setViewportSize({ width, height: mastHeight(width) });
          await page.goto(GATE_PATH);
          await page.waitForLoadState('networkidle');
          await page.evaluate(() => document.fonts.ready);
          await notesLanded(page);
          if (extra.halted) await expect(page.locator('[data-frame="masthead"] [data-stop="halted"]')).toHaveCount(1);
          await settle(page);
          await installGates(page);
          const gate = await mastheadFitGate(page, { halted: extra.halted });
          fits[width] = gate.fit;
          if (!gate.ok) failures.push(`${width}px: ${gate.detail} (fit: "${gate.fit}")`);
          const back = await takeBack(page, 'masthead');
          if (back.back.length) failures.push(`${width}px: ${lossier(back)}`);
        }
        const name = `masthead-fit-${extra.id}-${lang}`;
        recordGate(name, 'masthead-fit', failures.length === 0, { look: extra.look.look, scheme: extra.look.scheme, settings: extra.settings.id, lang, detail: failures.join('; ') || 'one row, whole and apart at every width', fits });
        expect.soft(failures, name).toEqual([]);
      });
    }
  }
});

/* ---- the running head from 1100px -------------------------------------------------------------- */

const RUNHEAD_LOOKS: Look[] = [LOOKS[0], LOOKS[2], PRESENCE, ATLAS_LIGHT];
const RUNHEAD_WIDTHS = [1100, 1180, 1280, 1340, 1366, 1440, 1536, 1600, 1680, 1920, 2200, 2560];
/** The extra settings (comfy density, the mono typeface override) at fewer widths. */
const RUNHEAD_EXTRA_WIDTHS = [1100, 1340, 1680, 2200];
/** A long model id as a local runner names it, quantisation and all. */
const LONG_MODEL = 'deepseek-r1-distill-qwen-32b-abliterated@q4_k_m';

/** The widest real values the running head draws: a cloud model configured (both providers, the
 *  strict-local flag set too) with the readable network ledger's count since yesterday, a long model
 *  id with its backend, the local-route figure, the chain broken at a six-figure entry, the approval
 *  mode refused, a two-figure interrupt budget. `offline` makes the hub stop answering /status from
 *  its next poll (its first answer is the last good reading). */
async function widestRunhead(page: Page) {
  const hub = { offline: false };
  const since = new Date(Date.now() - 26 * 3600_000).toISOString();
  await page.route((url) => url.pathname === '/api/trust/status', answer({ mic: 'on', strict_local: true, cloud_available: true, claude_available: true }));
  await page.route((url) => url.pathname === '/api/admin/network/calls', answer({ external_egress_total: 12345, model_egress_total: 678, ledger: { persistent: true, since } }));
  await page.route((url) => url.pathname === '/api/analytics/locality', answer({ local: 11523, cloud: 494, unknown: 0, total: 12017, local_pct: 95.9 }));
  await page.route((url) => url.pathname === '/api/security/audit/verify', answer({ valid: false, entries: 992144, first_invalid_id: 412907, tamper_evident: true }));
  await page.route((url) => url.pathname === '/autonomy/mode', refuse);
  await page.route((url) => url.pathname === '/autonomy/interrupts', answer({ used: 12, per_day: 24, remaining: 12 }));
  await page.route((url) => url.pathname === '/status', async (route) => {
    if (hub.offline) { await route.abort('connectionrefused'); return; }
    const response = await route.fetch().catch(() => null);
    const json = response && response.ok() ? await response.json().catch(() => ({})) : {};
    await route.fulfill({ status: 200, contentType: 'application/json', json: { ...json, model_state: 'ready', loaded_model: LONG_MODEL, llm_backend: 'lmstudio' } });
  });
  return hub;
}

/** The running head drawn: late in a long run the app can take more than the default 5 s to start
 *  after the network went idle (the full matrix once timed out here; the case passed alone). */
const headDrawn = (page: Page) => expect(page.locator('[data-frame="runhead"]').first()).toBeVisible({ timeout: 20_000 });

/** A page just loaded, drawn: once, a load that never mounts is loaded again, and the record says so.
 *  On Windows the fixture hub's proxy can run out of socket addresses in a long run (WinError 10048
 *  in its log), and the one page load that meets it stays empty; a second miss fails the case. */
async function mounted(page: Page, reloads: string[]): Promise<void> {
  try {
    await headDrawn(page);
    return;
  } catch { /* loaded again below */ }
  reloads.push(new URL(page.url()).pathname);
  await page.reload();
  await page.waitForLoadState('networkidle');
  await headDrawn(page);
}

/** The widest values drawn (each lands with its own poll). */
async function widestLanded(page: Page, { offline = false }: { offline?: boolean } = {}) {
  const head = page.locator('[data-frame="runhead"]');
  await headDrawn(page);
  await expect(head.locator('[data-signal="egress"]')).toContainText('12345');
  await expect(head.locator('[data-signal="localRoute"]')).toContainText('11523');
  await expect(head.locator('[data-signal="chain"]')).toContainText('412907');
  await expect(head.locator('[data-runhead="mode"] [data-source-state="refused"]')).toHaveCount(1);
  await expect(head.locator('[data-runhead="interrupts"]')).toContainText('12');
  if (offline) await expect(head.locator('[data-signal="data"]')).toHaveAttribute('data-state', 'offline');
  else await expect(head.locator('[data-signal="model"]')).toContainText(LONG_MODEL);
}

type RunheadSource = 'widest' | 'fixture';

/** One case: a fresh load at each width, the gate measured there; with the widest values, the hub
 *  then stops answering and the gate is measured again — "Offline · last good reading" from 2200px,
 *  "Offline" below it (wider than "Live", and in Romanian "Deconectat" than "În direct"). At each,
 *  no step may be lossier than needed (fit-takeback). */
async function runheadCase(page: Page, look: Look, lang: GateLang, settings: Settings, source: RunheadSource, widths: number[]) {
  const widest = source === 'widest';
  // the loader polls every 30 s: the clock is moved on to the next poll instead of waiting for it
  if (widest) await page.clock.install();
  await pinAppearance(page, preferences(look, lang, settings));
  const hub = widest ? await widestRunhead(page) : null;
  const results: Array<Record<string, unknown>> = [];
  const failures: string[] = [];
  const reloads: string[] = [];
  for (const width of widths) {
    if (hub) hub.offline = false;
    await page.setViewportSize({ width, height: heightFor(width) });
    await page.goto(GATE_PATH);
    await page.waitForLoadState('networkidle');
    await mounted(page, reloads);
    await page.evaluate(() => document.fonts.ready);
    if (widest) await widestLanded(page);
    else {
      await headDrawn(page);
      await expect(page.locator('[data-frame="runhead"] [data-signal="data"]')).not.toHaveAttribute('data-state', 'unknown');
    }
    await settle(page);
    await installGates(page);
    const gate = await runheadRowGate(page);
    const back = await takeBack(page, 'runhead');
    results.push({ width, steps: gate.steps, lines: gate.lines, ok: gate.ok && !back.back.length, detail: gate.detail, takeBack: back.back, drawn: gate.items.map((i) => `${i.id}: ${i.drawn}`) });
    if (!gate.ok) failures.push(`${width}px: ${gate.detail} (fit: "${gate.steps}")`);
    if (back.back.length) failures.push(`${width}px: ${lossier(back)}`);
    if (hub) {
      hub.offline = true;
      await page.clock.fastForward(31_000);
      await widestLanded(page, { offline: true });
      await settle(page);
      const offline = await runheadRowGate(page);
      const offlineBack = await takeBack(page, 'runhead');
      results.push({ width, offline: true, steps: offline.steps, lines: offline.lines, ok: offline.ok && !offlineBack.back.length, detail: offline.detail,
        takeBack: offlineBack.back, drawn: offline.items.map((i) => `${i.id}: ${i.drawn}`) });
      if (!offline.ok) failures.push(`${width}px, offline: ${offline.detail} (fit: "${offline.steps}")`);
      if (offlineBack.back.length) failures.push(`${width}px, offline: ${lossier(offlineBack)}`);
    }
  }
  return { results, failures, reloads };
}

test.describe('runhead-fit', () => {
  const cases: Array<{ look: Look; settings: Settings; source: RunheadSource; widths: number[] }> = [
    ...RUNHEAD_LOOKS.flatMap((look) => (['widest', 'fixture'] as const).map((source) => ({ look, settings: PLAIN, source, widths: RUNHEAD_WIDTHS }))),
    { look: LOOKS[0], settings: COMFY, source: 'widest', widths: RUNHEAD_EXTRA_WIDTHS },
    { look: LOOKS[0], settings: MONO, source: 'widest', widths: RUNHEAD_EXTRA_WIDTHS },
  ];
  for (const c of cases) {
    for (const lang of GATE_LANGS) {
      const name = `runhead-fit-${caseName(c.look, c.settings)}-${c.source}-${lang}`;
      test(name, async ({ page }) => {
        // a fresh load at each width, and with the widest values a second, offline measurement
        test.setTimeout(300_000);
        const { results, failures, reloads } = await runheadCase(page, c.look, lang, c.settings, c.source, c.widths);
        const lastResort = results.filter((r) => String(r.steps).split(' ').includes('lines')).map((r) => r.width);
        recordGate(name, 'runhead-fit', failures.length === 0, {
          look: c.look.look, scheme: c.look.scheme, settings: c.settings.id, source: c.source, lang,
          detail: failures.join('; ') || `eight items whole, apart, on top at ${c.widths.length} widths`,
          steps: Object.fromEntries(results.map((r) => [`${r.width}${r.offline ? ' offline' : ''}`, r.steps])),
          twoLines: lastResort, reloads, results,
        });
        mkdirSync(OUT, { recursive: true });
        await page.screenshot({ path: join(OUT, `${name}-last.png`), clip: { x: 0, y: 0, width: page.viewportSize()!.width, height: 160 } });
        expect.soft(failures, name).toEqual([]);
      });
    }
  }
  // down through the widths and back up, the widest values: each width takes the same steps
  // whichever way the window reached it, and passes the gate each time
  for (const look of RUNHEAD_LOOKS) {
    for (const lang of GATE_LANGS) {
      const name = `runhead-fit-resize-${caseName(look)}-${lang}`;
      test(name, async ({ page }) => {
        await page.setViewportSize({ width: 2560, height: 1353 });
        await pinAppearance(page, preferences(look, lang));
        await widestRunhead(page);
        await page.goto(GATE_PATH);
        await page.waitForLoadState('networkidle');
        await page.evaluate(() => document.fonts.ready);
        await widestLanded(page);
        await installGates(page);
        const failures: string[] = [];
        const down: Record<number, string> = {};
        const up: Record<number, string> = {};
        const pass = async (widths: number[], into: Record<number, string>) => {
          for (const width of widths) {
            await page.setViewportSize({ width, height: heightFor(width) });
            await settle(page);
            const gate = await runheadRowGate(page);
            into[width] = gate.steps;
            if (!gate.ok) failures.push(`${width}px: ${gate.detail} (fit: "${gate.steps}")`);
            const back = await takeBack(page, 'runhead');
            if (back.back.length) failures.push(`${width}px: ${lossier(back)}`);
            const steady = await steadySteps(page, '[data-frame="runhead"]');
            if (steady.now !== steady.later) failures.push(`${width}px: the steps flip from "${steady.now}" to "${steady.later}"`);
          }
        };
        await pass([...RUNHEAD_WIDTHS].reverse(), down);
        await pass(RUNHEAD_WIDTHS.slice(1), up);
        for (const width of RUNHEAD_WIDTHS.slice(1)) {
          if (down[width] !== up[width]) failures.push(`${width}px takes "${down[width]}" on the way down and "${up[width]}" on the way up`);
        }
        recordGate(name, 'runhead-fit', failures.length === 0, { look: look.look, scheme: look.scheme, lang, detail: failures.join('; ') || 'fits at every width, down and up', down, up });
        expect.soft(failures, name).toEqual([]);
      });
    }
  }
});

/* ---- the marks of the floating window (420 × 620) and Glance --------------------------------- */

/** Glance's windows: the six widths at their usual heights, and two short ones (a laptop's browser
 *  with its bars, a window snapped to half a 1920×1200 screen). */
const GLANCE_SIZES: ReadonlyArray<{ width: number; height: number }> = [
  { width: 420, height: 800 }, { width: 760, height: 800 }, { width: 760, height: 560 }, { width: 1100, height: 800 }, { width: 1280, height: 800 },
  { width: 1280, height: 560 }, { width: 1920, height: 1080 }, { width: 1920, height: 600 }, { width: 2560, height: 1353 },
];

/** Scrolls every scroller on the page to its end (the document, and each box that scrolls its
 *  overflow): how many there were. */
const scrollAllToEnd = (page: Page): Promise<number> => page.evaluate(() => {
  const scrollers = [document.scrollingElement, ...Array.from(document.querySelectorAll<HTMLElement>('*')).filter((el) => {
    const cs = getComputedStyle(el);
    return /(auto|scroll)/.test(cs.overflowY) && el.scrollHeight - el.clientHeight > 1;
  })].filter((el): el is Element => !!el && el.scrollHeight - el.clientHeight > 1);
  for (const el of scrollers) el.scrollTop = el.scrollHeight;
  return scrollers.length;
});
const sizeName = (size: { width: number; height: number }) => (size.height === heightFor(size.width) ? `${size.width}` : `${size.width}x${size.height}`);
/** Ledger dark, Classic · Obsidian and Atlas light (the round card look, light). */
const WINDOW_LOOKS: Look[] = [LOOKS[0], LOOKS[2], ATLAS_LIGHT];

/** Glance's middle, where the sheet does not scroll: centred in its room (the gaps above and below
 *  what it holds within 2px of each other). */
async function glanceCentred(page: Page): Promise<{ ok: boolean; detail: string }> {
  return page.evaluate(() => {
    const main = document.querySelector('.n-glance__main') as HTMLElement | null;
    if (!main) return { ok: false, detail: 'no middle' };
    const kids = Array.from(main.children).map((el) => el.getBoundingClientRect()).filter((r) => r.height > 0);
    if (!kids.length) return { ok: false, detail: 'an empty middle' };
    const box = main.getBoundingClientRect();
    const cs = getComputedStyle(main);
    const above = Math.min(...kids.map((r) => r.top)) - (box.top + (parseFloat(cs.paddingTop) || 0));
    const below = box.bottom - (parseFloat(cs.paddingBottom) || 0) - Math.max(...kids.map((r) => r.bottom));
    return { ok: Math.abs(above - below) <= 2 && above >= -0.5, detail: `${Math.round(above)}px above and ${Math.round(below)}px below what it holds` };
  });
}

test.describe('runhead-window', () => {
  for (const look of WINDOW_LOOKS) {
    for (const lang of GATE_LANGS) {
      const floating = `runhead-window-floating-${caseName(look)}-${lang}`;
      test(floating, async ({ page }) => {
        await page.setViewportSize({ width: 420, height: 620 });
        // a mock desktop bridge selects the floating window's UI (as base-path.spec does); no native call is made
        await page.addInitScript(() => { (window as unknown as { __TAURI__: unknown }).__TAURI__ = { core: { invoke: async () => ({}) } }; });
        await pinAppearance(page, preferences(look, lang));
        await widestRunhead(page);
        // the floating window keeps a stream open, so the network is never idle: wait for its head
        await page.goto('/v2/chat?desktop=floating');
        await expect(page.locator('[data-chatpage="floating"] [data-frame="runhead"]')).toHaveCount(1);
        await page.evaluate(() => document.fonts.ready);
        await widestLanded(page);
        await settle(page);
        await installGates(page);
        const gate = await runheadRowGate(page);
        // what is drawn under and around the marks: the whole window, as first shown and with every
        // scroller in it scrolled to its end
        const around = [await paintGate(page, 'body')];
        mkdirSync(OUT, { recursive: true });
        await page.screenshot({ path: join(OUT, `${floating}.png`) });
        const scrollers = await scrollAllToEnd(page);
        if (scrollers) {
          await settle(page);
          around.push(await paintGate(page, 'body'));
        }
        // every mark's popover opens inside the window, on top
        await page.locator('[data-frame="runhead"]').scrollIntoViewIfNeeded();
        const pops = await popoversGate(page);
        const ok = gate.ok && pops.ok;
        const detail = [gate.ok ? '' : gate.detail, ...pops.problems.map((p) => `popover: ${p}`)].filter(Boolean).join('; ') || `${gate.detail}; ${pops.opened} popovers inside the window`;
        const problems = around.flatMap((a, i) => a.problems.map((p) => (i ? `scrolled to the end: ${p}` : p)));
        recordGates(floating, { 'runhead-window': ok, 'runhead-surroundings': problems.length === 0 }, {
          look: look.look, scheme: look.scheme, lang, width: 420, detail, surroundings: problems.length ? problems : around[0].detail, checked: around[0].checked,
          scrollers, steps: gate.steps, lines: gate.lines, popovers: pops.opened, drawn: gate.items.map((i) => `${i.id}: ${i.drawn}`),
        });
        expect.soft(ok, `${floating}: ${detail}`).toBe(true);
        expect.soft(problems, `${floating}, under and around the marks`).toEqual([]);
      });
      const glance = `runhead-window-glance-${caseName(look)}-${lang}`;
      test(glance, async ({ page }) => {
        test.setTimeout(240_000);
        await pinAppearance(page, preferences(look, lang));
        await widestRunhead(page);
        const results: Array<Record<string, unknown>> = [];
        const failures: string[] = [];
        const surroundings: string[] = [];
        const reloads: string[] = [];
        for (const size of GLANCE_SIZES) {
          const { width } = size;
          await page.setViewportSize(size);
          await page.goto('/v2/glance');
          await page.waitForLoadState('networkidle');
          await mounted(page, reloads);
          await page.evaluate(() => document.fonts.ready);
          await widestLanded(page);
          await settle(page);
          await installGates(page);
          // what is drawn under and around the marks: the whole Glance sheet (its foot holds them), as
          // it first shows and, when the sheet scrolls (a short window), scrolled to its end too
          const sheet = page.locator('[data-glance]');
          const scrolls = await sheet.evaluate((el) => el.scrollHeight - el.clientHeight);
          const around = [await paintGate(page, '[data-glance]')];
          // where the sheet holds it all, its middle is centred, as designed
          const centred = scrolls > 0 ? null : await glanceCentred(page);
          if (centred && !centred.ok) failures.push(`${sizeName(size)}: the middle is not centred (${centred.detail})`);
          mkdirSync(OUT, { recursive: true });
          if (scrolls > 0) {
            await page.screenshot({ path: join(OUT, `${glance}-${sizeName(size)}-top.png`) });
            await sheet.evaluate((el) => { el.scrollTop = el.scrollHeight; });
            await settle(page);
            around.push(await paintGate(page, '[data-glance]'));
          }
          // the marks measured where they can be seen (on a scrolling sheet, scrolled to)
          await page.locator('[data-frame="runhead"]').scrollIntoViewIfNeeded();
          await settle(page);
          // one line of marks below 760px and from 1100px; between, the head wraps by design (§4.2)
          const gate = await runheadRowGate(page, { oneLine: width < 760 || width >= 1100 });
          const back = width >= 1100 ? await takeBack(page, 'runhead') : { back: [], steps: gate.steps, spills: false };
          await page.screenshot({ path: join(OUT, `${glance}-${sizeName(size)}.png`) });
          // every popover of the foot's marks opens inside the window (above them, at its bottom), on top
          const pops = await popoversGate(page);
          const problems = around.flatMap((a, i) => a.problems.map((p) => (i ? `scrolled to the end: ${p}` : p)));
          results.push({ width, height: size.height, steps: gate.steps, lines: gate.lines, ok: gate.ok && pops.ok && !back.back.length, detail: gate.detail,
            takeBack: back.back, popovers: pops.opened, popoverProblems: pops.problems, centred: centred?.detail ?? null, drawn: gate.items.map((i) => `${i.id}: ${i.drawn}`),
            sheetScrolls: scrolls, surroundings: problems.length ? problems : around[0].detail, checked: around[0].checked });
          if (!gate.ok) failures.push(`${sizeName(size)}: ${gate.detail} (fit: "${gate.steps}")`);
          if (back.back.length) failures.push(`${sizeName(size)}: ${lossier(back)}`);
          for (const p of pops.problems) failures.push(`${sizeName(size)}: popover: ${p}`);
          if (problems.length) surroundings.push(`${sizeName(size)}: ${problems.length} problem${problems.length === 1 ? '' : 's'}: ${problems.slice(0, 12).join('; ')}${problems.length > 12 ? '; …' : ''}`);
        }
        recordGates(glance, { 'runhead-window': failures.length === 0, 'runhead-surroundings': surroundings.length === 0 }, {
          look: look.look, scheme: look.scheme, lang,
          detail: failures.join('; ') || 'whole, apart and on top, its popovers inside the window, in every window',
          surroundings: surroundings.join('; ') || 'nothing drawn over anything else and nothing cut, in every window, as first shown and scrolled to the end',
          reloads, results,
        });
        expect.soft(failures, glance).toEqual([]);
        expect.soft(surroundings, `${glance}, under and around the marks`).toEqual([]);
      });
    }
  }
});

/* ---- the frame's rows in every look: no word cut that the spec keeps whole ---------------------- */

/** Every look and scheme the theme registry offers (Classic is dark only). */
const ALL_LOOKS: Look[] = [
  ...(['ledger', 'presence', 'briefing', 'workbench', 'threshold', 'console', 'atlas'] as const)
    .flatMap((look) => (['dark', 'light'] as const).map((scheme) => ({ look, scheme, nerva: true }))),
  { look: 'obsidian', scheme: 'dark', nerva: false }, { look: 'graphite', scheme: 'dark', nerva: false },
];

test.describe('frame-ellipsis', () => {
  for (const look of ALL_LOOKS) {
    for (const lang of GATE_LANGS) {
      const name = `frame-ellipsis-${caseName(look)}-${lang}`;
      test(name, async ({ page }) => {
        test.setTimeout(180_000);
        await pinAppearance(page, preferences(look, lang));
        await widestRunhead(page);
        await widestDocket(page);
        await page.setViewportSize({ width: 2560, height: 1353 });
        await page.goto('/v2/cockpit');
        await page.waitForLoadState('networkidle');
        const reloads: string[] = [];
        await mounted(page, reloads);
        await page.evaluate(() => document.fonts.ready);
        await widestLanded(page);
        await expect(page.locator('[data-frame="masthead"] [data-note="docket"]')).toHaveCount(1);
        await installGates(page);
        const failures: string[] = [];
        const steps: Record<string, string> = {};
        // down through the fit widths (each fit starts afresh, so the way the window came is no matter)
        for (const width of [...RUNHEAD_WIDTHS].reverse()) {
          await page.setViewportSize({ width, height: heightFor(width) });
          await settle(page);
          const r = await page.evaluate(() => {
            const w = window as unknown as { __nervaCutPx: (el: Element | null) => number; __nervaTextPast: (el: Element | null) => number };
            // cut beyond 0.003px (fit.ts CUT_EPSILON); the figure said is the text's own extent past its box
            const how = (el: HTMLElement) => `its text ${w.__nervaTextPast(el).toFixed(2)}px past its box; ${el.scrollWidth}px in ${el.clientWidth}px in whole pixels`;
            const problems: string[] = [];
            const mast = document.querySelector('[data-frame="masthead"]');
            const words = mast?.querySelector<HTMLElement>('.n-masthead__find-words') ?? null;
            // the form of Find's words drawn now (the long and the short one are both in the page)
            const drawn = words ? Array.from(words.children).filter((c) => c.getClientRects().length).map((c) => (c.textContent || '').trim()).join(' ') : '';
            if (words && w.__nervaCutPx(words) > 0.003) problems.push(`Find's words "${drawn}" are cut with an ellipsis (${how(words)})`);
            const head = document.querySelector('[data-frame="runhead"]');
            const run = head?.getAttribute('data-fit') || '';
            if (head && !run.split(' ').includes('cut')) {
              for (const el of Array.from(head.querySelectorAll<HTMLElement>('.n-signals__ident, .n-signals__text'))) {
                if (el.closest('.n-disclosure__panel, .n-runhead__pop')) continue;
                if (w.__nervaCutPx(el) > 0.003) problems.push(`the ${el.closest('[data-signal]')?.getAttribute('data-signal')} value "${(el.textContent || '').trim()}" is cut with an ellipsis before the "cut" step (${how(el)})`);
              }
            }
            return { problems, masthead: mast?.getAttribute('data-fit') || '', runhead: run };
          });
          steps[width] = `masthead "${r.masthead}" · running head "${r.runhead}"`;
          for (const p of r.problems) failures.push(`${width}px [${steps[width]}]: ${p}`);
          if (r.problems.length) {
            mkdirSync(OUT, { recursive: true });
            await page.screenshot({ path: join(OUT, `${name}-${width}.png`), clip: { x: 0, y: 0, width, height: 140 } });
          }
        }
        recordGate(name, 'frame-ellipsis', failures.length === 0, {
          look: look.look, scheme: look.scheme, lang, detail: failures.join('; ') || `nothing cut that is kept whole, at ${RUNHEAD_WIDTHS.length} widths`, steps, reloads,
        });
        expect.soft(failures, name).toEqual([]);
      });
    }
  }
});

/* ---- sec-heads: the section heads, register heads and totals at every width --------------------- */

/** The widths sec-heads walks: phones, the drawer's edge, one column, the two registers, the day
 *  register (1680–2199px) and the owner's four registers (from 2200px). */
const HEADS_WIDTHS = [320, 390, 600, 760, 1100, 1280, 1340, 1440, 1680, 1920, 2200, 2560];
/** Home (the day, the conversation, the docket and, from 2200px, the agents and the record's tail) and
 *  Trust (the record, payments, capabilities, where work ran). */
const HEADS_PAGES: ReadonlyArray<{ id: string; path: string }> = [{ id: 'home', path: '/v2/cockpit' }, { id: 'trust', path: '/v2/trust' }];
const headsHeight = (width: number) => (width >= 2560 ? 1353 : width >= 1920 ? 1080 : width >= 1440 ? 900 : width >= 1100 ? 800 : 844);
/** Where the plan promises the open docket entry whole, as the docket first shows it: 1280×800 (§9.5, "the
 *  open entry's SignLine is fully visible") and 1440×900 (§5.1, "the open docket entry is shown in full"). */
const SIGN_SIZES: ReadonlyArray<{ width: number; height: number }> = [{ width: 1280, height: 800 }, { width: 1440, height: 900 }];
/** The same promise measured on a fresh load at each size (the docket's first paint there), 1340×900 with them:
 *  the walk reaches 1340px at 800px tall. */
const FRESH_SIGN_SIZES: ReadonlyArray<{ width: number; height: number }> = [{ width: 1280, height: 800 }, { width: 1340, height: 900 }, { width: 1440, height: 900 }];
/** Where the plan promises no whole signature (one column, a phone: the open entry is taller than the body's
 *  view), a fresh load must still not scroll the body past the open entry's first line (its tier word, who
 *  asked, when) or the docket's state line above it: the docket scrolls only to show the signature whole. */
const FRESH_FIRST_LINE_SIZES: ReadonlyArray<{ width: number; height: number }> = [{ width: 390, height: 844 }, { width: 1100, height: 800 }];

/** Until no source label in a head says it is still checking (a feed the width mounts, such as the
 *  record's from 2200px, has answered), at most `ms`; what still checks then is returned and recorded. */
async function headsSettled(page: Page, ms = 8_000): Promise<string[]> {
  const deadline = Date.now() + ms;
  for (;;) {
    const checking = await page.evaluate(() => Array.from(document.querySelectorAll(':is(.n-sec, .n-register__head, .n-total) .n-src'))
      .filter((el) => el.getClientRects().length > 0 && /^(?:Checking…|Se verifică…)$/.test((el.textContent || '').trim()))
      .map((el) => el.closest('[data-register]')?.getAttribute('data-register') || '?'));
    if (!checking.length || Date.now() > deadline) return checking;
    await page.waitForTimeout(250);
  }
}

/** Below 1680px the day is a band: each of its popovers (the verdict, Today, While you were away) holds
 *  what the register held, its section heads and totals with it. Each is opened (its button clicked),
 *  measured inside the popover, and closed (Escape); a popover with a problem is shot while open. */
async function bandHeads(page: Page, shotPath: string | null): Promise<Array<{ id: string; gate: HeadsGate }>> {
  const buttons = page.locator('[data-frame="dayband"] .n-dayband__button');
  const out: Array<{ id: string; gate: HeadsGate }> = [];
  let shot = shotPath;
  const count = await buttons.count();
  for (let i = 0; i < count; i += 1) {
    const button = buttons.nth(i);
    if (!(await button.isVisible())) continue;
    await button.click();
    await expect(button).toHaveAttribute('aria-expanded', 'true');
    const panel = `[id="${await button.getAttribute('aria-controls')}"]`;
    await settle(page);
    const gate = await secHeadsGate(page, panel);
    out.push({ id: `band ${i + 1}`, gate });
    if (!gate.ok && shot) {
      await page.locator(panel).screenshot({ path: shot }).catch(() => {});
      shot = null;
    }
    await page.keyboard.press('Escape');
    await expect(button).toHaveAttribute('aria-expanded', 'false');
  }
  return out;
}

test.describe('sec-heads', () => {
  for (const shot of HEADS_PAGES) {
    for (const look of ALL_LOOKS) {
      for (const lang of GATE_LANGS) {
        const name = `sec-heads-${shot.id}-${caseName(look)}-${lang}`;
        test(name, async ({ page }) => {
          test.setTimeout(360_000);
          await pinAppearance(page, preferences(look, lang));
          const reloads: string[] = [];
          const failures: string[] = [];
          // register-inset, measured at the same widths and passes (the page, not the band's popovers)
          const insetFailures: string[] = [];
          const insetCounts: InsetCounts = { registers: 0, framed: 0, ruled: 0, texts: 0, controls: 0, totals: 0 };
          const insetNearest: InsetNearest = { left: null, right: null, bottom: null };
          // docket-sign, on Home where the docket draws entries, at the viewports the plan names
          const signFailures: string[] = [];
          const signs: Array<Record<string, unknown>> = [];
          const results: Array<Record<string, unknown>> = [];
          const counts: HeadsCounts = { sec: 0, head: 0, total: 0, beside: 0 };
          let shotTaken = false;
          mkdirSync(OUT, { recursive: true });
          // the fixture hub's own answers, then the demo sample (it draws the docket's, the record's and
          // the payments' totals, which the fixture's refused feeds do not), each walked down the widths;
          // on Home then a live docket of 128 entries (widestDocket), whose large figure ("128", in the
          // accent) heads the docket beside the others, from 1100px, where the registers stand side by side
          const passes = shot.id === 'home' ? (['live', 'demo', 'docket'] as const) : (['live', 'demo'] as const);
          for (const pass of passes) {
            const demo = pass === 'demo';
            if (pass === 'docket') await widestDocket(page);
            await page.setViewportSize({ width: 2560, height: headsHeight(2560) });
            await page.goto(`${shot.path}${demo ? '?demo=1' : ''}`);
            await page.waitForLoadState('networkidle');
            await mounted(page, reloads);
            if (pass === 'docket') await expect(page.locator('[data-register="docket"] .n-docket__figure[data-figure-state="live"]')).toHaveText('128', { timeout: 20_000 });
            await page.evaluate(() => document.fonts.ready);
            const widths = pass === 'docket' ? HEADS_WIDTHS.filter((w) => w >= 1100) : HEADS_WIDTHS;
            for (const width of [...widths].reverse()) {
              await page.setViewportSize({ width, height: headsHeight(width) });
              await settle(page);
              await quiet(page);
              const checking = await headsSettled(page);
              const views: Array<{ id: string; gate: HeadsGate }> = [{ id: 'page', gate: await secHeadsGate(page) }];
              const inset = await registerInsetGate(page);
              for (const kind of ['registers', 'framed', 'ruled', 'texts', 'controls', 'totals'] as const) insetCounts[kind] += inset.counts[kind];
              for (const side of ['left', 'right', 'bottom'] as const) {
                const near = inset.nearest[side];
                if (near && (!insetNearest[side] || near.px < (insetNearest[side]?.px ?? Infinity))) insetNearest[side] = { px: near.px, what: `${pass} ${width}px: ${near.what}` };
              }
              for (const p of inset.problems) insetFailures.push(`${pass} ${width}px: ${p}`);
              // the open entry's sign line as the docket first shows it (nothing in this walk scrolls its body),
              // at 1280×800 (§9.5) and 1440×900 (§5.1: the open entry shown in full), before the band's popovers
              const sign = shot.id === 'home' && pass !== 'live' && SIGN_SIZES.some((s) => s.width === width && s.height === headsHeight(width))
                ? await docketSignView(page) : null;
              if (sign) {
                signs.push({ pass, width, height: headsHeight(width), load: 'walk', ok: sign.ok, evaluated: sign.evaluated, hidden: sign.hidden, titleAbove: sign.titleAbove, entryAbove: sign.entryAbove, firstAbove: sign.firstAbove, firstText: sign.firstText, scrolled: sign.scrolled, detail: sign.detail });
                if (!sign.evaluated) signFailures.push(`${pass} ${width}×${headsHeight(width)}: the docket drew no open entry to measure`);
                else if (!sign.ok) signFailures.push(`${pass} ${width}×${headsHeight(width)}: ${sign.detail}`);
              }
              const file = `${name}-${pass === 'live' ? '' : `${pass}-`}${width}`;
              if ((!views[0].gate.ok || !inset.ok || (sign && !sign.ok)) && !shotTaken) {
                shotTaken = true;
                await page.screenshot({ path: join(OUT, `${file}.png`) });
              }
              if (shot.id === 'home' && width < 1680) {
                views.push(...await bandHeads(page, shotTaken ? null : join(OUT, `${file}-band.png`)));
                if (views.some((v) => !v.gate.ok)) shotTaken = true;
              }
              for (const view of views) {
                const at = `${pass} ${width}px${view.id === 'page' ? '' : ` [${view.id}]`}`;
                for (const kind of ['sec', 'head', 'total', 'beside'] as const) counts[kind] += view.gate.counts[kind];
                for (const p of view.gate.problems) failures.push(`${at}: ${p}`);
              }
              results.push({
                pass, demo, width, checking, views: views.map((v) => ({ id: v.id, counts: v.gate.counts, ok: v.gate.ok, problems: v.gate.problems })),
                inset: { ok: inset.ok, counts: inset.counts, nearest: inset.nearest, problems: inset.problems },
              });
            }
            // and as the docket first draws it in a window of that size: a fresh load at each viewport the plan
            // names (1280×800, §9.5; 1340×900 and 1440×900, §5.1), not a window resized down from 2560px
            if (shot.id === 'home' && pass !== 'live') {
              for (const size of FRESH_SIGN_SIZES) {
                await page.setViewportSize(size);
                await page.goto(`${shot.path}${demo ? '?demo=1' : ''}`);
                await page.waitForLoadState('networkidle');
                await mounted(page, reloads);
                if (pass === 'docket') await expect(page.locator('[data-register="docket"] .n-docket__figure[data-figure-state="live"]')).toHaveText('128', { timeout: 20_000 });
                await page.evaluate(() => document.fonts.ready);
                await settle(page);
                await quiet(page);
                const sign = await docketSignView(page);
                signs.push({ pass, width: size.width, height: size.height, load: 'fresh', ok: sign.ok, evaluated: sign.evaluated, hidden: sign.hidden, titleAbove: sign.titleAbove, entryAbove: sign.entryAbove, firstAbove: sign.firstAbove, firstText: sign.firstText, scrolled: sign.scrolled, detail: sign.detail });
                if (!sign.evaluated) signFailures.push(`${pass} ${size.width}×${size.height} (fresh load): the docket drew no open entry to measure`);
                else if (!sign.ok) signFailures.push(`${pass} ${size.width}×${size.height} (fresh load): ${sign.detail}`);
                if (!sign.ok && !shotTaken) {
                  shotTaken = true;
                  await page.screenshot({ path: join(OUT, `${name}-${pass}-fresh-${size.width}x${size.height}.png`) });
                }
              }
              for (const size of FRESH_FIRST_LINE_SIZES) {
                await page.setViewportSize(size);
                await page.goto(`${shot.path}${demo ? '?demo=1' : ''}`);
                await page.waitForLoadState('networkidle');
                await mounted(page, reloads);
                await page.evaluate(() => document.fonts.ready);
                await settle(page);
                await quiet(page);
                const sign = await docketSignView(page);
                // nothing above the open entry cut either: the docket's state line (the body's first line)
                const ok = sign.evaluated && (sign.entryAbove ?? 0) <= 0.5 && (sign.firstAbove ?? 0) <= 0.5 && (sign.scrolled === 0 || sign.ok);
                signs.push({ pass, width: size.width, height: size.height, load: 'fresh, first line', ok, evaluated: sign.evaluated, hidden: sign.hidden, titleAbove: sign.titleAbove, entryAbove: sign.entryAbove, firstAbove: sign.firstAbove, firstText: sign.firstText, scrolled: sign.scrolled, detail: sign.detail });
                if (!sign.evaluated) signFailures.push(`${pass} ${size.width}×${size.height} (fresh load): the docket drew no open entry to measure`);
                else if (!ok) signFailures.push(`${pass} ${size.width}×${size.height} (fresh load): the docket's body was scrolled ${sign.scrolled}px at first paint, the open entry's first line ${sign.entryAbove}px and the body's first line ("${sign.firstText}") ${sign.firstAbove}px above its view, without showing the signature whole`);
                if (!ok && !shotTaken) {
                  shotTaken = true;
                  await page.screenshot({ path: join(OUT, `${name}-${pass}-fresh-${size.width}x${size.height}.png`) });
                }
              }
            }
          }
          const insetNear = (['left', 'right', 'bottom'] as const).map((side) => `${side} ${insetNearest[side] ? `${insetNearest[side]?.px}px` : 'n/a'}`).join(', ');
          recordGates(name, {
            'sec-heads': failures.length === 0, 'register-inset': insetFailures.length === 0,
            ...(shot.id === 'home' ? { 'docket-sign': signFailures.length === 0 } : {}),
          }, {
            page: shot.id, path: shot.path, look: look.look, scheme: look.scheme, lang, counts, reloads,
            detail: failures.join('; ') || `${counts.sec} section heads, ${counts.head} register heads and ${counts.total} totals whole and inside their rows, and ${counts.beside} rows of register heads side by side level, at ${HEADS_WIDTHS.length} widths, ${passes.join(', ')}`,
            registerInset: {
              counts: insetCounts, nearest: insetNearest,
              detail: insetFailures.join('; ') || `${insetCounts.framed} framed registers kept ${insetCounts.texts} texts, ${insetCounts.controls} controls and ${insetCounts.totals} totals inside their margin (nearest: ${insetNear}); ${insetCounts.ruled} drawn with rules, unpadded; at ${HEADS_WIDTHS.length} widths, ${passes.join(', ')}`,
            },
            ...(shot.id === 'home' ? {
              docketSign: { detail: signFailures.join('; ') || `the open entry's sign line whole inside the docket body's view and the window, ${signs.length} measures (in the walk ${SIGN_SIZES.map((s) => `${s.width}×${s.height}`).join(', ')}; on a fresh load ${FRESH_SIGN_SIZES.map((s) => `${s.width}×${s.height}`).join(', ')}; the state line and the entry's first line never scrolled out of view, also on a fresh load at ${FRESH_FIRST_LINE_SIZES.map((s) => `${s.width}×${s.height}`).join(', ')}; demo and 128 entries)`, results: signs },
            } : {}),
            results,
          });
          expect.soft(failures, name).toEqual([]);
          expect.soft(insetFailures, `${name}: register-inset`).toEqual([]);
          if (shot.id === 'home') expect.soft(signFailures, `${name}: docket-sign`).toEqual([]);
        });
      }
    }
  }
});

/* ---- area-frame: the column of an area page is not a card -------------------------------------- */

/** Trust, Work, Timeline, the conversation page, and four mode pages drawn through PageSection (Agents,
 *  Memory, Settings, Connect). */
const AREA_PAGES: ReadonlyArray<{ id: string; path: string }> = [
  { id: 'trust', path: '/v2/trust' }, { id: 'work', path: '/v2/work' }, { id: 'timeline', path: '/v2/timeline' }, { id: 'chat', path: '/v2/chat' },
  { id: 'agents', path: '/v2/agents' }, { id: 'memory', path: '/v2/memory' }, { id: 'settings', path: '/v2/admin' }, { id: 'connect', path: '/v2/interop' },
];
/** A phone, the one-column page, the two registers and the three, walked down from a load at 1920px. */
const AREA_WIDTHS = [1920, 1280, 760, 390];

test.describe('area-frame', () => {
  for (const look of ALL_LOOKS) {
    for (const lang of GATE_LANGS) {
      const name = `area-frame-${caseName(look)}-${lang}`;
      test(name, async ({ page }) => {
        test.setTimeout(480_000);
        await pinAppearance(page, preferences(look, lang));
        const reloads: string[] = [];
        const failures: string[] = [];
        const counts: AreaCounts = { mains: 0, registers: 0, framed: 0 };
        const results: Array<Record<string, unknown>> = [];
        let shotTaken = false;
        mkdirSync(OUT, { recursive: true });
        // the fixture hub's own answers, then the demo sample; each page loaded at 1920px and walked down the widths
        for (const sample of SAMPLES) {
          for (const area of AREA_PAGES) {
            await page.setViewportSize({ width: AREA_WIDTHS[0], height: headsHeight(AREA_WIDTHS[0]) });
            await page.goto(`${area.path}${sample.demo ? '?demo=1' : ''}`);
            await page.waitForLoadState('networkidle');
            await mounted(page, reloads);
            // the page's own registers drawn before the column is measured around them
            await expect(page.locator('.n-areapage__main .n-register').first()).toBeVisible({ timeout: 20_000 }).catch(() => undefined);
            await page.evaluate(() => document.fonts.ready);
            for (const width of AREA_WIDTHS) {
              await page.setViewportSize({ width, height: headsHeight(width) });
              await settle(page);
              await quiet(page);
              const gate = await areaFrameGate(page);
              for (const kind of ['mains', 'registers', 'framed'] as const) counts[kind] += gate.counts[kind];
              const at = `${area.id}${sample.demo ? ' demo' : ''} ${width}px`;
              if (!gate.evaluated) failures.push(`${at}: the page drew no area column`);
              for (const p of gate.problems) failures.push(`${at}: ${p}`);
              if ((!gate.ok || !gate.evaluated) && !shotTaken) {
                shotTaken = true;
                await page.screenshot({ path: join(OUT, `${name}-${area.id}${sample.demo ? '-demo' : ''}-${width}.png`) });
              }
              results.push({ page: area.id, path: area.path, demo: sample.demo, width, height: headsHeight(width), ok: gate.evaluated && gate.ok, counts: gate.counts, problems: gate.problems });
            }
          }
        }
        recordGate(name, 'area-frame', failures.length === 0, {
          look: look.look, scheme: look.scheme, lang, counts, reloads, pages: AREA_PAGES.map((p) => p.path), widths: AREA_WIDTHS,
          detail: failures.join('; ') || `the page's column draws its top rule only on ${AREA_PAGES.length} pages at ${AREA_WIDTHS.length} widths, live and demo (${counts.mains} columns); ${counts.framed} of ${counts.registers} registers drawn as cards, none inside another`,
          results,
        });
        expect.soft(failures, name).toEqual([]);
      });
    }
  }
});

/* ---- the main window's running-head popovers: inside the window, on top, opaque ----------------- */

const POPOVER_LOOKS: Look[] = [LOOKS[0], LOOKS[2], { look: 'graphite', scheme: 'dark', nerva: false }];
const POPOVER_SIZES: ReadonlyArray<{ width: number; height: number }> = [{ width: 1280, height: 820 }, { width: 1920, height: 1080 }, { width: 390, height: 844 }];

test.describe('runhead-popovers', () => {
  for (const look of POPOVER_LOOKS) {
    for (const lang of GATE_LANGS) {
      const name = `runhead-popovers-${caseName(look)}-${lang}`;
      test(name, async ({ page }) => {
        test.setTimeout(180_000);
        await pinAppearance(page, preferences(look, lang));
        await widestRunhead(page);
        await widestDocket(page);
        const results: Array<Record<string, unknown>> = [];
        const failures: string[] = [];
        const reloads: string[] = [];
        for (const size of POPOVER_SIZES) {
          await page.setViewportSize(size);
          await page.goto('/v2/cockpit');
          await page.waitForLoadState('networkidle');
          await mounted(page, reloads);
          await page.evaluate(() => document.fonts.ready);
          await widestLanded(page);
          await settle(page);
          await installGates(page);
          const pops = await popoversGate(page);
          results.push({ width: size.width, height: size.height, opened: pops.opened, problems: pops.problems });
          // the six signals and the interrupts at least (the approval mode too where it is a button)
          if (pops.opened < 7) failures.push(`${size.width}x${size.height}: only ${pops.opened} popovers opened`);
          for (const p of pops.problems) failures.push(`${size.width}x${size.height}: ${p}`);
        }
        recordGate(name, 'runhead-popovers', failures.length === 0, {
          look: look.look, scheme: look.scheme, lang, detail: failures.join('; ') || 'every popover inside the window, on top and opaque', reloads, results,
        });
        expect.soft(failures, name).toEqual([]);
      });
    }
  }
});

/* ---- the approval mode while its looser choice waits for the second step ------------------------- */

const HELD_LOOKS: Look[] = [LOOKS[0], LOOKS[2]];
/** Where the looser choice is asked (the window's width), and the widths the window then takes. */
const HELD_CASES: ReadonlyArray<{ id: string; start: number; widths: number[] }> = [
  { id: 'line', start: 1600, widths: [1180, 900, 600, 430, 390, 360, 900, 2200] },
  { id: 'fold', start: 1180, widths: [1100, 900, 600, 390, 1180, 1600] },
  { id: 'marks', start: 600, widths: [740, 900, 1280, 1920, 390] },
];

/** The approval mode readable (Ask), so a looser choice can be asked; a write is answered by `post`
 *  (nothing reaches the fixture hub) and counted. */
async function modeReadable(page: Page, post: { status: number; json: unknown } = { status: 500, json: { detail: 'not in this test' } }) {
  const posts: unknown[] = [];
  await page.route((url) => url.pathname === '/autonomy/mode', async (route) => {
    if (route.request().method() !== 'GET') {
      posts.push(route.request().postDataJSON());
      await route.fulfill({ status: post.status, contentType: 'application/json', json: post.json });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', json: { mode: 'ask' } });
  });
  return posts;
}

/** The running head as the window has it, with what waits in its approval mode: the head follows the
 *  window (the marks below 760px), every item inside it, no sideways scroll; and `waiting` (the
 *  confirmation, or the hub's refusal) drawn, inside the window on an opaque surface on top, each of
 *  its buttons whole and on top. With `focused`, the focus is still on the control the page stored
 *  as window.__nervaHeld (the confirming button it took when the choice was asked). */
async function heldGate(page: Page, waiting: string, { focused = false }: { focused?: boolean } = {}) {
  return page.evaluate(({ waiting, focused, items }) => {
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const head = document.querySelector('[data-frame="runhead"]') as HTMLElement;
    const mode = head.querySelector('[data-runhead="mode"]') as HTMLElement | null;
    const problems: string[] = [];
    if (document.documentElement.scrollWidth > vw + 0.5) problems.push(`the page scrolls sideways (${document.documentElement.scrollWidth}px in ${vw})`);
    const compact = head.classList.contains('n-runhead--compact');
    if (compact !== (vw < 760)) problems.push(compact ? 'the head is still the marks from 760px' : 'the head keeps its line below 760px (§4.2: one line of marks)');
    for (const item of Array.from(head.querySelectorAll<HTMLElement>(items))) {
      const r = item.getBoundingClientRect();
      if (r.width > 0 && (r.left < -0.5 || r.right > vw + 0.5)) problems.push(`${item.getAttribute('data-signal') || item.getAttribute('data-runhead')} leaves the window (${Math.round(r.left)}..${Math.round(r.right)} of ${vw})`);
    }
    const shown = document.querySelector<HTMLElement>(waiting);
    if (!shown) problems.push(`${waiting} is gone`);
    else if (!shown.getClientRects().length || !(shown.getBoundingClientRect().width > 0)) problems.push(`${waiting} is not drawn`);
    else {
      const c = shown.getBoundingClientRect();
      if (c.left < -0.5 || c.right > vw + 0.5 || c.top < -0.5 || c.bottom > vh + 0.5) problems.push(`${waiting} leaves the window (${Math.round(c.left)}..${Math.round(c.right)} × ${Math.round(c.top)}..${Math.round(c.bottom)} in ${vw}×${vh})`);
      for (const b of Array.from(shown.querySelectorAll<HTMLElement>('button'))) {
        const br = b.getBoundingClientRect();
        const words = (b.textContent || '').trim();
        if (br.left < -0.5 || br.right > vw + 0.5) problems.push(`"${words}" is cut by the window (${Math.round(br.left)}..${Math.round(br.right)})`);
        const at = document.elementFromPoint(Math.min(vw - 1, Math.max(0, br.left + br.width / 2)), br.top + br.height / 2);
        if (!at || !b.contains(at)) problems.push(`"${words}" is covered at its centre`);
      }
      // the surface it is drawn on: the nearest box laid over the page (its own popover, the mode's
      // popover, or the marks' popover)
      let surface: HTMLElement | null = shown;
      while (surface && !['absolute', 'fixed'].includes(getComputedStyle(surface).position)) surface = surface.parentElement;
      const on = (window as unknown as { __nervaSurface: (el: Element | null) => string[] }).__nervaSurface(surface);
      for (const p of on) problems.push(`the surface under ${waiting} ${p}`);
    }
    const held = (window as unknown as { __nervaHeld?: Element }).__nervaHeld;
    if (focused && held) {
      if (!document.contains(held)) problems.push('the confirming button the focus was on is gone (drawn again elsewhere)');
      else if (document.activeElement !== held) problems.push(`the focus left the confirmation (now on ${document.activeElement === document.body ? 'the page' : (document.activeElement as HTMLElement | null)?.tagName.toLowerCase()})`);
    }
    return { problems, compact, fit: head.getAttribute('data-fit') || '', hold: mode?.getAttribute('data-hold') ?? null, vw };
  }, { waiting, focused, items: RUNHEAD_ITEMS });
}

test.describe('runhead-held', () => {
  for (const look of HELD_LOOKS) {
    for (const lang of GATE_LANGS) {
      for (const c of HELD_CASES) {
        const name = `runhead-held-${c.id}-${caseName(look)}-${lang}`;
        test(name, async ({ page }) => {
          test.setTimeout(180_000);
          await pinAppearance(page, preferences(look, lang));
          await widestRunhead(page);
          const posts = await modeReadable(page);
          await page.setViewportSize({ width: c.start, height: 900 });
          await page.goto(GATE_PATH);
          await page.waitForLoadState('networkidle');
          const reloads: string[] = [];
          await mounted(page, reloads);
          await page.evaluate(() => document.fonts.ready);
          const head = page.locator('[data-frame="runhead"]');
          await expect(head.locator('[data-signal="chain"]')).toContainText('412907');
          // the mode read (Ask checked in the line, or Ask as the fold's or the mark's word)
          await expect(head.locator('[data-runhead="mode"] :is([role="radio"][data-mode="ask"][aria-checked="true"], b[data-mode="ask"])').first()).toBeAttached();
          await settle(page);
          await installGates(page);
          // the looser choice asked where the mode is drawn at this width: in the line, or in the popover
          // of its fold or its mark
          const opener = head.locator('[data-runhead="mode"] :is(.n-runhead__fold, .n-disclosure__button)');
          const asked = await opener.isVisible() ? 'popover' : 'line';
          if (asked === 'popover') await opener.click();
          await head.locator('[role="radio"][data-mode="auto"]').click();
          const confirm = page.locator('[data-runhead="confirm"]');
          await expect(confirm).toHaveCount(1);
          const switchTo = confirm.locator('button').first();
          await expect(switchTo).toBeFocused();
          await switchTo.evaluate((el) => { (window as unknown as { __nervaHeld: Element }).__nervaHeld = el; });
          const results: Array<Record<string, unknown>> = [];
          const failures: string[] = [];
          for (const width of [c.start, ...c.widths]) {
            await page.setViewportSize({ width, height: 900 });
            await settle(page);
            const r = await heldGate(page, '[data-runhead="confirm"]', { focused: true });
            results.push({ width, ...r });
            for (const p of r.problems) failures.push(`${width}px [${r.compact ? 'marks' : `line, fit "${r.fit}"`}]: ${p}`);
            if (r.problems.length) {
              mkdirSync(OUT, { recursive: true });
              await page.screenshot({ path: join(OUT, `${name}-${width}.png`), clip: { x: 0, y: 0, width, height: 440 } });
            }
          }
          if (posts.length) failures.push(`${posts.length} write(s) reached the hub: the looser mode was never confirmed`);
          recordGate(name, 'runhead-held', failures.length === 0, {
            look: look.look, scheme: look.scheme, lang, asked, start: c.start, detail: failures.join('; ') || 'the confirmation whole, inside the window and focused at every width', reloads, results,
          });
          expect.soft(failures, name).toEqual([]);
        });
      }
      // the hub's refusal on screen: it holds nothing, the head follows the window, the refusal is seen
      const noteName = `runhead-held-note-${caseName(look)}-${lang}`;
      test(noteName, async ({ page }) => {
        test.setTimeout(180_000);
        await pinAppearance(page, preferences(look, lang));
        await widestRunhead(page);
        await modeReadable(page, { status: 503, json: { error: 'mode_not_saved', mode: 'ask' } });
        await page.setViewportSize({ width: 1700, height: 900 });
        await page.goto(GATE_PATH);
        await page.waitForLoadState('networkidle');
        const reloads: string[] = [];
        await mounted(page, reloads);
        await page.evaluate(() => document.fonts.ready);
        const head = page.locator('[data-frame="runhead"]');
        await expect(head.locator('[data-runhead="mode"] :is([role="radio"][data-mode="ask"][aria-checked="true"], b[data-mode="ask"])').first()).toBeAttached();
        await settle(page);
        await installGates(page);
        const opener = head.locator('[data-runhead="mode"] :is(.n-runhead__fold, .n-disclosure__button)');
        if (await opener.isVisible()) await opener.click();
        // a stricter mode is one press: written, and refused by the hub
        await head.locator('[role="radio"][data-mode="off"]').click();
        await expect(page.locator('[data-runhead="mode-note"]')).toHaveCount(1);
        const results: Array<Record<string, unknown>> = [];
        const failures: string[] = [];
        for (const width of [1700, 600, 390]) {
          await page.setViewportSize({ width, height: 900 });
          await settle(page);
          const r = await heldGate(page, '[data-runhead="mode-note"]');
          results.push({ width, ...r });
          for (const p of r.problems) failures.push(`${width}px [${r.compact ? 'marks' : `line, fit "${r.fit}"`}]: ${p}`);
          if (r.hold !== null) failures.push(`${width}px: the refusal holds the approval mode (data-hold="${r.hold}")`);
          if (r.problems.length) {
            mkdirSync(OUT, { recursive: true });
            await page.screenshot({ path: join(OUT, `${noteName}-${width}.png`), clip: { x: 0, y: 0, width, height: 440 } });
          }
        }
        recordGate(noteName, 'runhead-held', failures.length === 0, {
          look: look.look, scheme: look.scheme, lang, detail: failures.join('; ') || 'the refusal seen inside the window, nothing held, at every width', reloads, results,
        });
        expect.soft(failures, noteName).toEqual([]);
      });
    }
  }
});

/* ---- the running foot at phone widths ------------------------------------------------------------ */

/** The running foot's widest real form (§4.3), every count over 19 so Romanian takes its longest
 *  plurals ("23 de răspunsuri rulează în altă parte", "21 de sesiuni"): a served roster of 96 agents —
 *  32 waiting on you (64 requests on the docket, two each), 24 working (a running task each), 21
 *  finished today (an action each in the day's feed), Athena unavailable (cloud-only, and no cloud
 *  model is configured), 18 with no activity reported — 23 replies running elsewhere (the hub's turn
 *  slots, none of them this tab's), RAM 99%, VRAM 100% and GPU load 100% known, 10 of 12 channels
 *  running, 21 sessions in the last 15 minutes, and a pre-release version. */
const FOOT = {
  roster: 96, waiting: 32, working: 24, finished: 21, elsewhere: 23, sessions: 21, version: '1.12.0-rc.3',
  channels: ['discord', 'telegram', 'slack', 'whatsapp', 'signal', 'matrix', 'email', 'sms', 'webchat', 'voice', 'teams', 'irc'], running: 10,
} as const;

async function widestFoot(page: Page) {
  const ids = Array.from({ length: FOOT.roster - 1 }, (_, i) => `agent-${String(i + 1).padStart(2, '0')}`).concat('athena');
  const waiting = ids.slice(0, FOOT.waiting);
  const working = ids.slice(FOOT.waiting, FOOT.waiting + FOOT.working);
  const finished = ids.slice(FOOT.waiting + FOOT.working, FOOT.waiting + FOOT.working + FOOT.finished);
  const now = Date.now();
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  const today = Math.floor(Math.max(midnight.getTime() + 1000, now - 5000) / 1000);
  const created = new Date(now).toISOString();
  await page.route((url) => url.pathname === '/api/agents', answer({
    agents: ids.map((id) => ({ id, name: id === 'athena' ? 'Athena' : `Agent ${id.slice(6)}`, role: 'Specialist' })),
  }));
  await page.route((url) => url.pathname === '/autonomy/tasks' && url.searchParams.get('status') === 'blocked', answer({
    tasks: waiting.flatMap((agent, i) => [0, 1].map((k) => ({ id: 9000 + i * 2 + k, kind: 'send_email', title: `Request ${i * 2 + k + 1}`, agent, created_at: created, risk_tier: 1 }))),
    groups: [],
  }));
  await page.route((url) => url.pathname === '/autonomy/tasks' && url.searchParams.get('status') === 'running', answer({
    tasks: working.map((agent, i) => ({ id: 8000 + i, kind: 'research', title: `Running ${i + 1}`, agent, created_at: created })),
  }));
  await page.route((url) => url.pathname === '/api/dashboard/today', answer({
    items: finished.map((agent, i) => ({ entry_id: `action:${i + 1}`, epoch: today, kind: 'action', title: `Finished ${i + 1}`, agent })),
  }));
  await page.route((url) => url.pathname === '/api/subagents', answer({ spawns: [], stats: { active: 0, cap: 4 } }));
  await page.route((url) => url.pathname === '/api/security/kill-switch', answer({ global: false, any_halted: false, halted_count: 0 }));
  await page.route((url) => url.pathname === '/api/trust/status', answer({ mic: 'on', strict_local: false, cloud_available: false, claude_available: false }));
  await page.route((url) => url.pathname === '/status', async (route) => {
    const response = await route.fetch().catch(() => null);
    const json = response && response.ok() ? await response.json().catch(() => ({})) : {};
    await route.fulfill({ status: 200, contentType: 'application/json', json: {
      ...json,
      sys: { ram_used: 63.2, ram_total: 64, vram_used: 24, vram_total: 24, gpu_load: 100, gpu: 'NVIDIA GeForce RTX 4090' },
      gateway: { state: 'running', running: FOOT.channels.slice(0, FOOT.running), running_count: FOOT.running, total: FOOT.channels.length },
      sessions: { active: FOOT.sessions, window_s: 900, state: 'known' },
      version: FOOT.version,
      slots: { turns: { running: FOOT.elsewhere, per_session: 2, cap: 32 }, lanes: [], subagents: { running: 0, cap: 4 } },
    } });
  });
}

/** The widest foot drawn: each source lands with its own poll, and the gate measures nothing before
 *  every one has (the fixture hub serves no roster, so without its stub the foot says "Agents: not
 *  reported" and draws no state at all). */
async function footLanded(page: Page, lang: GateLang) {
  const foot = page.locator('[data-frame="runfoot"]');
  await expect(foot.locator('.n-runfoot__lead')).toHaveText(`${lang === 'ro' ? 'Agenți' : 'Agents'} ${FOOT.roster}`, { timeout: 15_000 });
  const counts: Array<[string, number]> = [['working', FOOT.working], ['waitingOnYou', FOOT.waiting], ['finishedToday', FOOT.finished], ['unavailable', 1]];
  for (const [activity, n] of counts) await expect(foot.locator(`[data-activity="${activity}"]`)).toHaveText(new RegExp(`^${n} `));
  await expect(foot.locator('[data-runfoot="elsewhere"]')).toHaveText(new RegExp(`^${FOOT.elsewhere} `));
  for (const key of ['ram', 'vram', 'gpu']) await expect(foot.locator(`[data-machine="${key}"]`)).toHaveAttribute('data-state', 'live');
  await expect(foot.locator('[data-chrome="gateway"]')).toContainText(`${FOOT.running} ${lang === 'ro' ? 'din' : 'of'} ${FOOT.channels.length}`);
  await expect(foot.locator('[data-chrome="sessions"]')).toContainText(`${FOOT.sessions} `);
  await expect(foot.locator('[data-chrome="version"]')).toHaveText(`Nerva ${FOOT.version}`);
}

type FootPart = readonly [string, string];
/** What a phone width keeps drawn in the foot, with the widest real values. */
const FOOT_DRAWN: readonly FootPart[] = [
  ['the agents', '[data-runfoot="agents"] .n-runfoot__lead'], ['working', '[data-activity="working"]'],
  ['waiting on you', '[data-activity="waitingOnYou"]'], ['finished today', '[data-activity="finishedToday"]'],
  ['unavailable', '[data-activity="unavailable"]'], ['the replies running elsewhere', '[data-runfoot="elsewhere"]'],
  ['RAM', '[data-machine="ram"]'], ['VRAM', '[data-machine="vram"]'], ['GPU load', '[data-machine="gpu"]'],
  ['the channels', '[data-chrome="gateway"]'], ['the sessions', '[data-chrome="sessions"]'], ['the version', '[data-chrome="version"]'],
];
/** …and with the fixture hub's own answers: the roster not reported, the machine and channels unknown. */
const FOOT_DRAWN_UNKNOWN: readonly FootPart[] = [
  ['the agents', '[data-runfoot="agents"] .n-runfoot__lead'],
  ['RAM', '[data-machine="ram"]'], ['VRAM', '[data-machine="vram"]'], ['GPU load', '[data-machine="gpu"]'],
  ['the channels', '[data-chrome="gateway"]'], ['the sessions', '[data-chrome="sessions"]'], ['the name', '.n-runfoot__ver'],
];
/** What §4.3 leaves out of the foot below 1680px (and the key hint, below 2200px). */
const FOOT_LEFT_OUT: readonly FootPart[] = [
  ['the agents with no activity reported', '[data-activity="noActivity"]'], ['the latency', '[data-machine="latency"]'],
  ['the meters', '.n-runfoot__meter'], ['the unread sources', '[data-runfoot="agents"] .n-runfoot__detail'], ['the key hint', '[data-runfoot="keys"]'],
];

type FootGate = RowGate & { parts: string[]; surroundings: PaintGate };

/** The running foot at phone widths: every part the width keeps drawn, whole, inside the viewport;
 *  what §4.3 leaves out not drawn; every text node's drawn part inside its item and the viewport, no
 *  two items overlapping; nothing drawn into the foot from around it (the paint gate within 24px of
 *  it); and an unknown machine reading drawn as its label and mark (its words read, not drawn, and in
 *  its title). */
async function runfootPhoneGate(page: Page, drawn: readonly FootPart[]): Promise<FootGate> {
  await installGates(page);
  const row = await page.evaluate(() =>
    (window as unknown as { __nervaRow: (row: string, items: string, opts: object) => RowGate }).__nervaRow(
      '[data-frame="runfoot"]', '.n-runfoot__item, .n-runfoot__ver', {}));
  const extra = await page.evaluate(({ drawn, leftOut }) => {
    const foot = document.querySelector('[data-frame="runfoot"]') as HTMLElement | null;
    if (!foot) return { problems: ['no running foot'], parts: [] as string[] };
    const problems: string[] = [];
    const parts: string[] = [];
    const vw = document.documentElement.clientWidth;
    const box = foot.getBoundingClientRect();
    if (box.left < -0.5 || box.right > vw + 0.5) problems.push('the foot is cut by the viewport');
    if (foot.scrollWidth - foot.clientWidth > 1) problems.push(`the foot holds ${foot.scrollWidth}px in ${foot.clientWidth}px`);
    for (const [name, selector] of drawn) {
      const el = foot.querySelector<HTMLElement>(selector);
      if (!el) { problems.push(`${name}: not in the foot`); continue; }
      const r = el.getBoundingClientRect();
      if (!el.getClientRects().length || r.width < 1 || r.height < 1) { problems.push(`${name} is not drawn`); continue; }
      if (r.left < -0.5 || r.right > vw + 0.5) problems.push(`${name} is cut by the viewport`);
      parts.push(`${name}: ${(el.innerText || '').replace(/\s+/g, ' ').trim()}`);
    }
    for (const [name, selector] of leftOut) {
      for (const el of Array.from(foot.querySelectorAll(selector))) {
        if (el.getClientRects().length && el.getBoundingClientRect().width >= 1) { problems.push(`${name} is drawn (§4.3 leaves it out below 1680px)`); break; }
      }
    }
    for (const el of Array.from(foot.querySelectorAll<HTMLElement>('[data-machine][data-state="unknown"]'))) {
      if (!el.getClientRects().length) continue;   // left out at this width (the latency)
      const key = el.getAttribute('data-machine');
      const words = el.querySelector<HTMLElement>('.n-runfoot__words');
      if (!words || !(words.textContent || '').trim()) problems.push(`${key} reads no words`);
      else if (getComputedStyle(words).clipPath === 'none' && words.getBoundingClientRect().width > 1) problems.push(`${key}'s words ("${words.textContent}") are drawn at phone width`);
      if (!el.getAttribute('title')) problems.push(`${key} has no title for its words`);
      if (!el.querySelector('[data-mark="unknown"]')) problems.push(`${key} draws no unknown mark`);
    }
    return { problems, parts };
  }, { drawn, leftOut: FOOT_LEFT_OUT });
  const surroundings = await paintGate(page, 'body', { around: '[data-frame="runfoot"]', margin: 24 });
  const problems = [...(row.ok ? [] : [row.detail]), ...extra.problems, ...(surroundings.ok ? [] : [`around the foot: ${surroundings.detail}`])];
  return { ...row, ok: problems.length === 0, detail: problems.join('; ') || row.detail, parts: extra.parts, surroundings };
}

test.describe('runhead-marks', () => {
  for (const look of GATE_LOOKS) {
    for (const lang of GATE_LANGS) {
      for (const width of MARK_WIDTHS) {
        test(`runhead-marks-${width}-${look.look}-${look.scheme}-${lang}`, async ({ page }) => {
          await page.setViewportSize({ width, height: 844 });
          await pinAppearance(page, preferences(look, lang));
          // the widest words the marks keep: the mode Ask ("Întreabă") and a two-figure budget
          await page.route((url) => url.pathname === '/autonomy/mode', answer({ mode: 'ask' }));
          await page.route((url) => url.pathname === '/autonomy/interrupts', answer({ used: 12, per_day: 24, remaining: 12 }));
          // the foot's widest real form (FOOT)
          await widestFoot(page);
          await page.goto('/v2/cockpit');
          await page.waitForLoadState('networkidle');
          await page.evaluate(() => document.fonts.ready);
          await expect(page.locator('[data-frame="runhead"] [data-runhead="mode"] b[data-mode="ask"]')).toHaveCount(1);
          await expect(page.locator('[data-frame="runhead"] [data-runhead="interrupts"] button')).toHaveText(lang === 'ro' ? '12 din 24' : '12 of 24');
          await footLanded(page, lang);
          await settle(page);
          const gate = await runheadMarksGate(page);
          // what is drawn under and around the marks: anything within 32px of the head
          await installGates(page);
          const around = await paintGate(page, 'body', { around: '[data-frame="runhead"]', margin: 32 });
          const name = `runhead-marks-${width}-${look.look}-${look.scheme}-${lang}`;
          recordGates(name, { 'runhead-marks': gate.ok, 'runhead-surroundings': around.ok }, {
            width, look: look.look, scheme: look.scheme, lang, detail: gate.detail, surroundings: around.detail, names: gate.names,
          });
          mkdirSync(OUT, { recursive: true });
          await page.screenshot({ path: join(OUT, `${name}.png`) });
          expect.soft(gate.ok, `${name}: ${gate.detail}`).toBe(true);
          expect.soft(around.problems, `${name}, under and around the marks`).toEqual([]);
          // the foot at the same width, at its widest: every part it keeps drawn and nothing cut
          const foot = await runfootPhoneGate(page, FOOT_DRAWN);
          const footName = `runfoot-phone-${width}-${look.look}-${look.scheme}-${lang}`;
          recordGate(footName, 'runfoot-phone', foot.ok, {
            width, look: look.look, scheme: look.scheme, lang, source: 'widest', detail: foot.detail, lines: foot.lines, parts: foot.parts,
            surroundings: foot.surroundings.detail, drawn: foot.items.map((i) => `${i.id}: ${i.drawn}`),
          });
          await page.locator('[data-frame="runfoot"]').screenshot({ path: join(OUT, `${footName}.png`) });
          expect.soft(foot.ok, `${footName}: ${foot.detail}`).toBe(true);
          // a mark opens its popover, inside the window
          const model = page.locator('[data-frame="runhead"] [data-signal="model"] button[aria-expanded]');
          await model.click();
          await expect(model).toHaveAttribute('aria-expanded', 'true');
          const pop = await page.locator('[data-frame="runhead"] [data-signal="model"] .n-disclosure__panel').boundingBox();
          expect.soft(!!pop && pop.x >= -0.5 && pop.x + pop.width <= width + 0.5, `${name}: the popover is cut by the window ${JSON.stringify(pop)}`).toBe(true);
        });
      }
    }
  }
});

// the foot with the fixture hub's own answers (no roster, the machine and channels unknown): an
// unknown reading is its label and mark at phone width, never its sentence; a fresh load per width
test.describe('runfoot-phone', () => {
  for (const look of GATE_LOOKS) {
    for (const lang of GATE_LANGS) {
      const name = `runfoot-phone-unknown-${caseName(look)}-${lang}`;
      test(name, async ({ page }) => {
        await pinAppearance(page, preferences(look, lang));
        const results: Array<Record<string, unknown>> = [];
        const failures: string[] = [];
        for (const width of MARK_WIDTHS) {
          await page.setViewportSize({ width, height: 844 });
          await page.goto('/v2/cockpit');
          await page.waitForLoadState('networkidle');
          await page.evaluate(() => document.fonts.ready);
          // the fixture's /status has answered (the data on screen is no longer "Checking…"), and this
          // case still measures what it means to: a machine the hub could not read
          await expect(page.locator('[data-frame="runhead"] [data-signal="data"]')).not.toHaveAttribute('data-state', 'unknown', { timeout: 15_000 });
          await expect(page.locator('[data-frame="runfoot"] [data-machine="ram"]')).toHaveAttribute('data-state', 'unknown');
          await expect(page.locator('[data-frame="runfoot"] [data-machine="ram"]')).not.toHaveAttribute('title', /Checking|Se verifică/);
          await settle(page);
          const foot = await runfootPhoneGate(page, FOOT_DRAWN_UNKNOWN);
          results.push({ width, ok: foot.ok, detail: foot.detail, parts: foot.parts, surroundings: foot.surroundings.detail, drawn: foot.items.map((i) => `${i.id}: ${i.drawn}`) });
          if (!foot.ok) failures.push(`${width}px: ${foot.detail}`);
          mkdirSync(OUT, { recursive: true });
          await page.locator('[data-frame="runfoot"]').screenshot({ path: join(OUT, `${name}-${width}.png`) });
        }
        recordGate(name, 'runfoot-phone', failures.length === 0, {
          look: look.look, scheme: look.scheme, lang, source: 'fixture', detail: failures.join('; ') || 'nothing cut, unknown readings as their marks, at every width', results,
        });
        expect.soft(failures, name).toEqual([]);
      });
    }
  }
});

test.afterAll(() => {
  if (!REPORT.length) return;   // skipped (another lane), or nothing ran
  mkdirSync(OUT, { recursive: true });
  // every shot of this run so far, whichever worker took it (see RUN above)
  const all = readdirSync(RUN_DIR).filter((f) => f.endsWith('.json'))
    .map((f) => JSON.parse(readFileSync(join(RUN_DIR, f), 'utf8')) as Record<string, unknown>)
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const failed = all.filter((r) => Object.values(r.gates as Record<string, boolean>).includes(false)).map((r) => r.name);
  writeFileSync(join(OUT, 'report.json'), JSON.stringify({
    generated: new Date().toISOString(),
    run: RUN,
    frame: 'ledger (the only frame since the stage 5 cleanup)',
    shots: all.length,
    failed,
    nonClaims: [
      'Chromium only; the owner\'s Windows machine at 2560 and 1.5x is the final review render.',
      'Every region is wired in; live-empty shots draw each feed as the fixture hub answers it (often refused, unknown or empty), not a populated day.',
      'min-font is reported but not gated for Classic · Obsidian.',
      'Chromium\'s "Failed to load resource" lines (the fixture hub\'s 503 / 401 / 403 answers) are listed under http and not gated; page errors and every other console error are.',
      'sec-heads draws the docket\'s large figure from the demo sample and, on Home from 1100px, from a stubbed live docket of 128 entries (the fixture hub refuses the docket feed, so its own live state draws none); it opens the day band\'s popovers only on Home below 1680px.',
      'register-inset measures text, control and total boxes against the straight inner edges of a register\'s frame (left, right, bottom), not a rounded corner\'s curve and not the top (the head\'s strut keeps the title under it); it measures the page as each shot or width first shows it, scrolling boxes at their first position, not the day band\'s popovers. It measures registers only; an area page\'s own column is area-frame\'s.',
      'area-frame measures the column\'s own fill, side and bottom borders and shadow (not its radius, which draws nothing without them), and nesting among registers only: a framed box that is not a register (a legacy panel inside a register\'s body) is not counted. Its walk covers eight area pages; the matrix\'s page shots add Build, Logs, the emergency stop, Model setup and All pages in Ledger and Classic · Obsidian.',
      'docket-1280 and docket-sign measure the open entry\'s sign line as the docket first draws it, at 1280×800 and, in the sec-heads walks, 1440×900 (a window resized down from 2560px) and, on a fresh load, 1280×800, 1340×900 and 1440×900; not after a decision, a refresh or the owner\'s own scrolling. Where the layout leaves part of the line below the body\'s view the docket scrolls its body by that much, never past the open entry\'s title (docket/Docket.tsx useSignatureInView): the gates measure what the owner sees, that scroll included.',
    ],
    results: all,
  }, null, 2));
});
