/* HUD v2 · accessibility gate for the PAGES of the HUD, walked the way the owner walks them.

   Rewritten at the Ledger cutover (PHASE_B_PLAN.md §8.2 row 30). It used to walk the sixteen rail
   modes of the classic shell. The Ledger frame has no rail: its navigation is the masthead's nine
   areas (AreaNav), each area's contents column (ContentsColumn) and the number keys (1–9 the areas
   in masthead order, 0 the conversation). This walk goes through exactly those and scans every
   page it reaches with axe:
     - every id the router registers in `src/hud-modes.ts` — the nine landings, the other modes
       and the four Ledger views (Work, Timeline, Saved replies, Glance) — each reached once;
     - one panel page per area, the first panel of its contents column. All 138 panels would not
       fit the time budget; every panel page is the same PanelPage frame, so the sample covers the
       frame on a panel page in every area. The other panels' own content is NOT scanned here: a
       gap stated, not covered.

   Why this file exists. `a11y.spec.ts` scans Home and the Cinema overlay — two surfaces — and a
   green a11y lane was being read as "the HUD is accessible". Walking the modes with axe found
   blocking violations on surfaces no spec had ever visited, one of them the same rule
   (`scrollable-region-focusable`) that a11y.spec.ts covers on the transcript.

   Three ways a page walk lies, all of them caught the hard way by review of the classic walk, all
   still pinned below.

   1. IT SCANS THE SAME SURFACE TWICE. A navigation that does not land leaves the previous page
      mounted, and axe re-scans it under the new name. This walk fingerprints the PAGE ON SCREEN —
      its URL path, the masthead's current area and the contents column's current page — checks
      each against where the walk meant to go, and asserts it reached every registered id once.

   2. IT SCANS AN EMPTY STATE AND CALLS IT CLEAN. A mode whose backend source is not live is drawn
      as the area-page empty state ("Nothing to show yet — this page's source has not answered"),
      which replaced the classic `ModeEmpty` card. Against a backend with no data that is the case
      for several modes (on the isolated fixture hub: Build, Autonomy, the four agent homes and
      the Inbox), so scanning only the live app says nothing about their real surfaces. So the
      walk runs twice, live and `?demo=1`, and records `empty` per page so a green scan of an empty
      state can never be mistaken for coverage.

   3. IT SCANS AT ONE VIEWPORT. axe's contrast rule can only sample pixels inside the viewport,
      and layout breakpoints move content in and out of it: at 1440 (1340–1679px) Home's day is
      folded into a band and the contents column is 200px wide; at 1280 (≤ 1339px) the layout
      tightens, the column narrows to 176px and the docket shrinks. No single viewport sees
      everything, so this scans two.

   Threshold and artifact discipline match a11y.spec.ts: gate on `critical` and `serious`, write
   the full result — violations AND `incomplete`, which is where axe parks contrast it could not
   resolve — to e2e/artifacts/ for the human pass. */
import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { HUD_MODES } from '../src/hud-modes';

type Impact = 'critical' | 'serious' | 'moderate' | 'minor' | null;
const BLOCKING: ReadonlyArray<Exclude<Impact, null>> = ['critical', 'serious'];

/** The number keys of the areas (PHASE_B_PLAN.md §3.6): key N goes to the N-th area of the
 *  masthead. Read against the masthead itself below, never against a list kept in this file. */
const AREA_KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9'] as const;
/** 0 goes to the conversation, a page of Home; its contents column lists Home's pages (Today
 *  itself has none). */
const CONVERSATION = { key: '0', path: '/v2/chat', area: 'home' } as const;

/** The masthead's nine area links, the contents column, and what the page body is drawn in. */
const MASTHEAD_AREAS = '[data-frame="masthead"] nav[aria-label="Areas"] a[data-area]';
const CONTENTS = '[data-frame="contents"]';
const PAGE_BODY = '[data-frame="page"]';
const GLANCE_BODY = '[data-glance]';

/* How long the page body must hold still before axe runs. Was 450ms on the classic walk, which
   review demonstrated is short enough to release mid-build: these surfaces arrive in stages with
   multi-second gaps, and any gap longer than the window ends the wait early. Reproduced against a
   real backend — the cockpit sat at 147 nodes from t=101ms to t=2019ms before jumping to 306 (the
   entire agent roster missing), and `admin` settled at 34 of its ~442 on one run in three, because
   `api/live.ts` zeroes `V2.ADMIN` via `honestAdminSeed()` and refills it on a 30s interval. 1600ms
   clears the observed gaps with margin; it is a mitigation and not a proof, because no
   DOM-quiescence heuristic can see an outstanding fetch — `nodes` is recorded per scan so a short
   scan is visible in the artifact after the fact. Closing this across every page needs readiness
   signals for its async sources; the Admin EstopCard wait below covers only that card's request. */
const QUIET_MS = 1600;

/* The time budget. Each scan costs the navigation, the quiet window and an axe pass; 22 registered
   ids and 9 panel pages make 31 scans per lane, which took 1.3–1.6 minutes per lane against the
   isolated fixture hub (2026-11-24). A real backend answers more slowly, and the default test
   timeout cannot hold a lane either way. */
const LANE_TIMEOUT_MS = 420_000;

type AdminEstopOutcome = 'ready' | 'unavailable' | 'empty';

/** Admin's EstopCard has its own request lifecycle; DOM quiet alone cannot see it. Admin is the
 *  landing page of Settings: the only mode page of that area (its other pages are panels). */
async function waitForAdminEstopReadiness(page: Page, timeoutMs = 25_000): Promise<AdminEstopOutcome> {
  let observed = 'missing';
  await expect.poll(async () => {
    observed = await page.evaluate(() => {
      const area = document.querySelector('[data-frame="masthead"] [data-area][aria-current="page"]');
      const admin = document.querySelector('[data-frame="page"] [data-areapage="mode"][data-area="settings"]');
      if (area?.getAttribute('data-area') !== 'settings' || !admin) return 'wrong-page';
      const card = admin.querySelector('[data-estop-readiness]');
      if (card) {
        const state = card.getAttribute('data-estop-readiness');
        if (card.getAttribute('aria-busy') !== 'false') return 'pending';
        return state === 'ready' || state === 'unavailable' ? state : 'pending';
      }
      // The area-page empty state is a legitimate live Admin surface when ADMIN has no live mark
      // (frame/ModePage.tsx). Match its page head (Settings), its own copy and its demo offer; an
      // actual Admin page missing its Estop marker must never pass this wait.
      const empty = admin.querySelector('[data-empty]');
      const title = admin.querySelector('h1')?.textContent?.trim();
      const explicit = !!empty && title === 'Settings'
        && (empty.textContent || '').includes('Nothing to show yet')
        && Array.from(empty.querySelectorAll('button')).some((b) => (b.textContent || '').includes('Show a demo sample'));
      return explicit ? 'empty' : 'missing-marker';
    });
    return observed;
  }, {
    message: 'Admin must show the explicit area-page empty state or a settled EstopCard before axe',
    timeout: timeoutMs,
  }).toMatch(/^(ready|unavailable|empty)$/);
  return observed as AdminEstopOutcome;
}

/* One caveat that belongs next to the list rather than in a commit message. `projects` does not
   go through the demo path at all: app.tsx's `ledgerModeBody` renders `<ProjectsMode t={t} />`
   without `demo`, and ModePage has no live keys for it, so it is drawn the same way in both lanes.
   Its demo lane is not independent coverage of its live one: both run the same component against
   the same backend, whose four panels are their own "nothing yet" empty states (ROOMS 0, MISSIONS
   0, ACTIVITY "no activity yet"). That is NOT the area-page empty state, so `empty` is correctly
   false and the demo pin below cannot flag it. What a green lane proves for `projects` is that its
   frame and empty states are clean; a populated projects surface is still unscanned. */

/** The two viewports, and why each is here — see (3) above. */
const VIEWPORTS = [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
] as const;

type Via = 'hotkey' | 'contents' | 'glance';
/** Where a scan meant to be: the path, the masthead's current area and the contents column's
 *  current page (null where the page has none: Today, Glance). */
type Target = { name: string; via: Via; path: string; area: string | null; pageKey: string | null };
type Seen = { path: string; area: string | null; pageKey: string | null };
type PageScan = Target & {
  seen: Seen; empty: boolean; nodes: number; scrollY: number; pending: boolean;
  adminEstop: AdminEstopOutcome | null; blocking: string[]; incomplete: number; unreported: string[];
};

/** The second path segment: the mode of `/v2/<mode>`, or the panel of `/v2/console/<id>`. */
const idOf = (path: string) => (path.startsWith('/v2/console/') ? path.split('/')[3] : path.split('/')[2]) || '';

/* axe's `incomplete` is "I could not decide", not "this is fine" — and on this shell it is where
   the real findings hide. The lane gates on `violations` and once stored `incomplete` only as a
   COUNT, so a `serious` entry there was invisible unless a human opened the JSON. That is not
   hypothetical: #1022 fixed `scrollable-region-focusable` on the AGENTS roster by adding
   `aria-label` to a role-less <div>, which is `serious · aria-prohibited-attr` — axe filed it
   under `incomplete` while the roster had content, the walk stayed green, and the regression
   merged and went unnoticed for 8.5 hours, until a review pass read the JSON.

   So: SURFACE them, never gate on them. `incomplete` is not one thing — for some rules axe genuinely
   cannot decide, for others it declines for a specific resolvable reason — so a blanket gate would
   be wrong for the first kind and a blanket ignore is wrong for the second. Reporting is correct
   for both.

   `color-contrast` is exempted from the LISTING and counted beside it, because it runs to the
   hundreds of nodes per lane and would bury everything else. Stated honestly, because the
   exemption is broader than its reason: it filters by RULE ID, so it suppresses every
   color-contrast incomplete. The frame itself is what `contrast.spec.ts` measures from pixels; a
   page body's own color-contrast incompletes are covered by no lane at all. Real gap, recorded
   rather than papered over by the wording.

   Where this is visible: `e2e.yml` triggers on schedule, dispatch and push-to-main — it has **no**
   `pull_request` trigger — so this reaches a human on the nightly and in the uploaded
   `hud-e2e-artifacts` (where `surfacedIncomplete` sits at the top level of the JSON), NOT on the
   PR that introduces a regression. */
const SURFACE_EXEMPT = new Set(['color-contrast']);

test.describe('HUD pages', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
    });
  });

  for (const demo of [false, true]) {
    for (const vp of VIEWPORTS) {
      const lane = `${demo ? 'demo' : 'live'} · ${vp.width}x${vp.height}`;

      test(`no critical/serious accessibility violations on any HUD page (${lane})`, async ({ page }) => {
        test.setTimeout(LANE_TIMEOUT_MS);
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(demo ? '/v2/?demo=1' : '/v2', { waitUntil: 'domcontentloaded' });
        await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
        await expect(page.locator('[data-frame="masthead"]')).toBeVisible({ timeout: 20_000 });

        // Couple the walk to the MASTHEAD, not to a list kept in this file: the areas and their
        // landing paths are read from the page, and key N must land on the N-th of them. A tenth
        // area (or one fewer) fails here, loudly, instead of leaving a surface unscanned.
        const areas = await page.locator(MASTHEAD_AREAS).evaluateAll((links) => links.map((a) => ({
          id: a.getAttribute('data-area') || '',
          path: new URL((a as HTMLAnchorElement).href).pathname,
        })));
        expect(
          areas.map((a) => a.id),
          `the masthead draws ${areas.length} areas; the number keys 1–9 reach nine. An area was added `
          + 'or removed: give it its key in shortcuts.ts (§3.6) and walk it here, do not just bump a number.',
        ).toHaveLength(AREA_KEYS.length);

        const scans: PageScan[] = [];
        const all: unknown[] = [];

        /** Go somewhere, check the walk landed where it meant to, let the body settle, scan it. */
        const scan = async (target: Target, go: () => Promise<void>) => {
          // Clear the settle memo BEFORE switching. It lives on `window` and its `since` stamp is
          // reset only when the node count changes — so if a new page's first paint happens to
          // have the same node count as the previous page's last, the quiet window would already be
          // satisfied on entry and axe would scan a half-built DOM.
          await page.evaluate(() => { delete (window as unknown as { __a11ySettle?: unknown }).__a11ySettle; });
          await go();
          // A navigation that does not land is SILENT otherwise: the previous page stays mounted
          // and axe re-scans it under this name. Fail here, naming where the walk meant to go.
          await expect.poll(() => page.evaluate(() => location.pathname), {
            message: `${target.via} did not reach ${target.path} (${target.name})`, timeout: 15_000,
          }).toBe(target.path);

          // Every page is scanned at the same scroll offset: axe's contrast rule samples only inside
          // the viewport, so a scrolled scan is not comparable with the others. The frame does not
          // scroll the document (registers and page bodies scroll inside), and `scrollY` goes into
          // the artifact so that is checked rather than trusted.
          await page.evaluate(() => window.scrollTo(0, 0));
          const root = target.name === 'glance' ? GLANCE_BODY : PAGE_BODY;

          // This is a card-level completion proof, not a declaration that every Admin feed has
          // settled. Failure/unavailability is itself a rendered settled state; a pending request
          // must fail this wait before axe runs.
          let adminEstop = target.name === 'admin' ? await waitForAdminEstopReadiness(page) : null;

          // Not a bare sleep: wait for the DOM to stop changing. It proves the page stopped
          // changing for QUIET_MS, which is strictly better than a fixed wait and is not the same
          // as proving it finished.
          await page.waitForFunction(({ quietMs, selector }: { quietMs: number; selector: string }) => {
            const body = document.querySelector(selector);
            if (!body) return false;
            const w = window as unknown as { __a11ySettle?: { n: number; since: number } };
            const n = body.querySelectorAll('*').length;
            const now = Date.now();
            if (!w.__a11ySettle || w.__a11ySettle.n !== n) { w.__a11ySettle = { n, since: now }; return false; }
            return now - w.__a11ySettle.since > quietMs;
            // QUIET_MS is a Node-side constant and this predicate runs IN THE PAGE, so it has to
            // travel as an argument; referencing it directly throws ReferenceError at runtime.
          }, { quietMs: QUIET_MS, selector: root }, { timeout: 25_000 });
          // A live Admin empty state may acquire its backend mark during that quiet window and
          // mount EstopCard. Check again immediately before axe so a new pending request cannot
          // inherit the earlier empty outcome.
          if (target.name === 'admin') adminEstop = await waitForAdminEstopReadiness(page);

          const meta = await page.evaluate((selector: string) => {
            const body = document.querySelector(selector);
            const txt = body ? (body.textContent || '') : '';
            return {
              seen: {
                path: location.pathname,
                area: document.querySelector('[data-frame="masthead"] [data-area][aria-current="page"]')?.getAttribute('data-area') ?? null,
                pageKey: document.querySelector('[data-frame="contents"] [aria-current="page"]')?.getAttribute('data-page') ?? null,
              },
              scrollY: Math.round(window.scrollY),
              // Was an async section still resolving when axe ran? See the settle note above.
              pending: /checking|loading|connecting…|please wait/i.test(txt),
              nodes: body ? body.querySelectorAll('*').length : 0,
              // the area-page empty state (frame/AreaPage.tsx AreaEmpty), not a page's own "nothing yet"
              empty: !!body?.querySelector('[data-empty]'),
            };
          }, root);

          const results = await new AxeBuilder({ page })
            .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
            .analyze();
          all.push({ lane, ...target, adminEstop, ...meta, violations: results.violations, incomplete: results.incomplete });

          scans.push({
            ...target, ...meta, adminEstop,
            incomplete: results.incomplete.length,
            // `impact == null` is surfaced too, not dropped: axe leaves `impact` null when it cannot
            // even estimate severity, and an unknown severity is not a safe one.
            unreported: results.incomplete
              .filter((v) => v.impact == null || BLOCKING.includes(v.impact as never))
              .filter((v) => !SURFACE_EXEMPT.has(v.id))
              .map((v) => `${v.impact ?? 'unrated'} · ${v.id} (${v.nodes.length}) → ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`),
            blocking: results.violations
              .filter((v) => BLOCKING.includes((v.impact ?? '') as never))
              .map((v) => `${v.impact} · ${v.id} (${v.nodes.length}) → ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`),
          });
        };

        const pressKey = (key: string) => async () => {
          // Blur first: the hotkey handler correctly ignores keys typed in a field or in the
          // transcript's role="log" region, so a stray focus would silently keep us on one page.
          await page.evaluate(() => { const a = document.activeElement as HTMLElement | null; if (a && a.blur) a.blur(); });
          await page.keyboard.press(key);
        };
        /* DOM activation, not a mouse click: a real `click()` also tests pointer reachability, and
           a fixed layer over a link (the pointer bubble, the companion) would fail it for a reason
           this walk is not about. `el.click()` dispatches a real DOM click through React's own
           onClick, so the walk tests the PAGE, deterministically. That the nine areas are on screen
           and on top is status-chrome-layout.spec.ts's own test. */
        const activate = (selector: string) => async () => {
          const link = page.locator(selector);
          await expect(link, `nothing to click at ${selector}`).toHaveCount(1);
          await link.evaluate((el) => (el as HTMLElement).click());
        };

        // 1. The number keys: 1–9 the nine areas in masthead order, 0 the conversation (§3.6).
        //    Today (Home's landing) has no contents column; every other landing is listed first in
        //    its own.
        for (const [i, key] of AREA_KEYS.entries()) {
          const area = areas[i];
          const name = idOf(area.path);
          await scan({ name, via: 'hotkey', path: area.path, area: area.id, pageKey: area.id === 'home' ? null : `mode:${name}` }, pressKey(key));
        }
        await scan({ name: 'chat', via: 'hotkey', path: CONVERSATION.path, area: CONVERSATION.area, pageKey: 'mode:chat' }, pressKey(CONVERSATION.key));

        // 2. Each area through its masthead link, then its contents column: every mode page not yet
        //    scanned, and the first panel page.
        for (const area of areas) {
          await activate(`${MASTHEAD_AREAS}[data-area="${area.id}"]`)();
          await expect.poll(() => page.evaluate(() => location.pathname), { message: `the masthead link of ${area.id}` }).toBe(area.path);
          // Home's pages are listed beside the conversation, not on Today.
          if (area.id === 'home') {
            await pressKey(CONVERSATION.key)();
            await expect.poll(() => page.evaluate(() => location.pathname)).toBe(CONVERSATION.path);
          }
          const column = page.locator(`${CONTENTS}[data-area="${area.id}"]`);
          await expect(column, `the contents column of ${area.id}`).toHaveCount(1);
          // "N more pages": the rest of the area's listed pages are behind it.
          const more = column.locator('button[data-contents="more"][aria-expanded="false"]');
          if (await more.count()) await more.evaluate((el) => (el as HTMLElement).click());
          const listed = await column.locator('a[data-page]').evaluateAll((links) => links.map((a) => ({
            key: a.getAttribute('data-page') || '', path: new URL((a as HTMLAnchorElement).href).pathname,
          })));
          for (const link of listed.filter((l) => l.key.startsWith('mode:'))) {
            if (scans.some((s) => s.path === link.path)) continue;
            await scan({ name: idOf(link.path), via: 'contents', path: link.path, area: area.id, pageKey: link.key },
              activate(`${CONTENTS} a[data-page="${link.key}"]`));
            // A page reached from the column is drawn with its own column: open "more" again.
            const again = page.locator(`${CONTENTS} button[data-contents="more"][aria-expanded="false"]`);
            if (await again.count()) await again.evaluate((el) => (el as HTMLElement).click());
          }
          const firstPanel = listed.find((l) => l.key.startsWith('panel:'));
          expect(firstPanel, `the contents column of ${area.id} lists no panel page`).toBeTruthy();
          await scan({ name: idOf(firstPanel!.path), via: 'contents', path: firstPanel!.path, area: area.id, pageKey: firstPanel!.key },
            activate(`${CONTENTS} a[data-page="${firstPanel!.key}"]`));
        }

        // 3. Glance, the one view that is not listed: the masthead's own button, full screen, no
        //    frame. Escape returns to the page it was opened from.
        const before = await page.evaluate(() => location.pathname);
        await scan({ name: 'glance', via: 'glance', path: '/v2/glance', area: null, pageKey: null },
          activate('[data-frame="masthead"] [data-anchor="glance"]'));
        await page.keyboard.press('Escape');
        await expect.poll(() => page.evaluate(() => location.pathname), { message: 'Escape out of Glance' }).toBe(before);

        // Surfaced, not gated (see SURFACE_EXEMPT above). This is the only place a `serious`
        // `incomplete` finding becomes visible without opening the JSON, so it goes to the console
        // as well as the artifact — a lane that is green while hiding a serious finding is exactly
        // how the last one got in.
        const unreported = scans.filter((s) => s.unreported.length);
        // NODES, not entries: axe returns ONE `incomplete` entry per rule id with every unresolved
        // node inside its `nodes[]`, so counting entries would answer "how many pages had any
        // contrast incomplete" and not "how much is suppressed".
        const contrastExempt = (all as { incomplete: { id: string; nodes: unknown[] }[] }[])
          .flatMap((e) => e.incomplete.filter((v) => SURFACE_EXEMPT.has(v.id)));
        const contrastIncompleteNodes = contrastExempt.reduce((n, v) => n + v.nodes.length, 0);
        const contrastIncompletePages = contrastExempt.length;
        if (unreported.length) {
          console.log(`a11y ${lane} · findings this lane SURFACES but does not fail on:`);
          for (const s of unreported) for (const line of s.unreported) console.log(`    ${s.path}: ${line}`);
        }
        console.log(
          `a11y ${lane} · ${unreported.length} page(s) with a surfaced incomplete finding; `
          + `${contrastIncompleteNodes} color-contrast incomplete NODES across `
          + `${contrastIncompletePages} page(s), not listed — see the note above SURFACE_EXEMPT`,
        );

        mkdirSync('e2e/artifacts', { recursive: true });
        writeFileSync(
          `e2e/artifacts/a11y-modes-${demo ? 'demo' : 'live'}-${vp.width}x${vp.height}.json`,
          JSON.stringify({
            lane,
            counts: tally(all),
            // Header, so a reader sees this without walking `scans`: what axe declined to judge at
            // serious/critical or unrated impact, minus the color-contrast entries counted beside it.
            surfacedIncomplete: unreported.map((s) => ({ page: s.path, findings: s.unreported })),
            contrastIncompleteNodes,
            contrastIncompletePages,
            scans,
            detail: all,
          }, null, 2),
        );

        // Where each scan was, against where the walk meant it to be: the path, the masthead's
        // current area and the contents column's current page. A miss names the page and says what
        // was on screen instead.
        const misses = scans.filter((s) => s.seen.path !== s.path || s.seen.area !== s.area || s.seen.pageKey !== s.pageKey);
        expect(
          misses.map((s) => `${s.via} → ${s.path} (area ${s.area}, page ${s.pageKey}) saw ${JSON.stringify(s.seen)}`),
          'a scan was not on the page the walk meant to reach; it re-measured another surface',
        ).toEqual([]);

        const scrolled = scans.filter((s) => s.scrollY !== 0);
        expect(
          scrolled.map((s) => `${s.path} scanned at scrollY=${s.scrollY}`),
          'every page must be scanned at the same scroll offset; axe samples contrast only inside '
          + 'the viewport, so a scrolled scan is not comparable with the others',
        ).toEqual([]);

        // Non-vacuity pins. Every page scanned once, and the ids reached are exactly the router's
        // own registry (src/hud-modes.ts): a mode added there but not placed in a contents column,
        // or not drawn, fails here instead of going unscanned.
        expect(new Set(scans.map((s) => s.seen.path)).size, `the walk scanned a page twice: ${scans.map((s) => s.path).join(', ')}`)
          .toBe(scans.length);
        const reached = scans.filter((s) => !s.path.startsWith('/v2/console/')).map((s) => s.name);
        expect([...reached].sort(), 'the walk must reach every id the router registers').toEqual([...HUD_MODES].sort());
        const panelAreas = scans.filter((s) => s.path.startsWith('/v2/console/')).map((s) => s.area);
        expect(panelAreas, 'one panel page per area').toEqual(areas.map((a) => a.id));

        // In demo every page renders for real, so an empty state there means the walk did not
        // actually get in. Live is allowed to have empty states — that is the honest gate — and
        // the artifact records which, so a green live run is never read as covering them.
        if (demo) {
          expect(
            scans.filter((s) => s.empty).map((s) => s.path),
            'in demo every page should render; the area-page empty state means the scan saw nothing',
          ).toEqual([]);
        }

        const offenders = scans.filter((s) => s.blocking.length > 0);
        expect(
          offenders,
          `axe found critical/serious violations (${lane}):\n` +
            offenders.map((s) => `  ${s.path}${s.empty ? ' [EMPTY STATE]' : ''}:\n    ${s.blocking.join('\n    ')}`).join('\n'),
        ).toEqual([]);
      });
    }
  }
});

/** Synthetic Settings pages for the readiness helper: the masthead marks Settings, and the page
 *  body is Settings' landing (the Admin mode) unless `kind` says otherwise. */
function settingsPage(body: string, kind: 'mode' | 'panel' = 'mode') {
  return '<header data-frame="masthead"><nav aria-label="Areas">'
    + '<a data-area="home" href="/v2/cockpit">Home</a><a data-area="settings" aria-current="page" href="/v2/admin">Settings</a>'
    + `</nav></header><main data-frame="page"><div data-areapage="${kind}" data-area="settings">`
    + `<section><header><h1>${kind === 'mode' ? 'Settings' : 'Model setup'}</h1></header><div>${body}</div></section></div></main>`;
}

test('Admin readiness accepts only the explicit empty state, not a missing or pending marker', async ({ page }) => {
  const emptyState = '<div data-empty=""><p>Nothing to show yet — this page’s source has not answered. It fills in when it does.</p>'
    + '<button type="button">Show a demo sample</button></div>';
  await page.setContent(settingsPage(emptyState));
  expect(await waitForAdminEstopReadiness(page, 500)).toBe('empty');

  await page.setContent(settingsPage('<div data-mode="admin"><div class="admin-grid">Mounted Admin without EstopCard marker</div></div>'));
  await expect(waitForAdminEstopReadiness(page, 350)).rejects.toThrow(/Admin must show the explicit area-page empty state/);

  await page.setContent(settingsPage('<div data-mode="admin"><div data-estop-readiness="pending" aria-busy="true">checking estop</div></div>'));
  await expect(waitForAdminEstopReadiness(page, 350)).rejects.toThrow(/Admin must show the explicit area-page empty state/);

  // another page of Settings with an empty state is not Admin's
  await page.setContent(settingsPage(emptyState, 'panel'));
  await expect(waitForAdminEstopReadiness(page, 350)).rejects.toThrow(/Admin must show the explicit area-page empty state/);
});

test('Admin axe scan waits for EstopCard after the old quiet window', async ({ page }) => {
  test.slow();
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
  });
  let releaseResponse!: () => void;
  const heldResponse = new Promise<void>(resolve => { releaseResponse = resolve; });
  let requestSeen!: () => void;
  const intercepted = new Promise<void>(resolve => { requestSeen = resolve; });
  let requests = 0;
  await page.route(/\/api\/ops\/estop(?:\?.*)?$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    requests += 1;
    requestSeen();
    await heldResponse;
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ engaged: false, state: null }),
    });
  });

  await page.goto('/v2/?demo=1', { waitUntil: 'domcontentloaded' });
  // Settings, through its masthead link: its landing page is the Admin mode.
  const settings = page.locator(`${MASTHEAD_AREAS}[data-area="settings"]`);
  await expect(settings).toHaveCount(1);
  await settings.evaluate(el => (el as HTMLElement).click());
  await intercepted;
  const card = page.locator(`${PAGE_BODY} [data-estop-readiness]`);
  await expect(card).toHaveAttribute('data-estop-readiness', 'pending');
  await expect(card).toHaveAttribute('aria-busy', 'true');

  let axeScans = 0;
  let readyOutcome: AdminEstopOutcome | null = null;
  const scan = waitForAdminEstopReadiness(page).then(async outcome => {
    readyOutcome = outcome;
    axeScans += 1;
    return new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  });
  try {
    // This test-only controlled delay exceeds the previous DOM-quiet window.
    // The real walk has no sleep-based success path: its helper must remain blocked.
    await page.waitForTimeout(QUIET_MS + 150);
    expect(axeScans).toBe(0);
    await expect(card).toHaveAttribute('data-estop-readiness', 'pending');
  } finally {
    releaseResponse();
  }
  const result = await scan;
  expect(requests).toBe(1);
  expect(axeScans).toBe(1);
  expect(readyOutcome).toBe('ready');
  expect(Array.isArray(result.violations)).toBe(true);
  await expect(card).toHaveAttribute('data-estop-readiness', 'ready');
});

/** Count violations by impact across every page, for the artifact header. */
function tally(all: unknown[]) {
  const counts: Record<string, number> = { critical: 0, serious: 0, moderate: 0, minor: 0, 'n/a': 0, incomplete: 0 };
  for (const entry of all as { violations: { impact?: Impact }[]; incomplete: unknown[] }[]) {
    for (const v of entry.violations) counts[v.impact ?? 'n/a'] = (counts[v.impact ?? 'n/a'] ?? 0) + 1;
    counts.incomplete += entry.incomplete.length;
  }
  return counts;
}
