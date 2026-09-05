/* HUD v2 · accessibility gate for the MODE surfaces.

   Why this file exists. `a11y.spec.ts` scans the cockpit route and the cinema overlay —
   two surfaces — and a green a11y lane was being read as "the HUD is accessible". Walking
   the modes with axe found blocking violations on surfaces no spec had ever visited, one of
   them the same rule (`scrollable-region-focusable`) that a11y.spec.ts covers on `.convo`,
   sitting one keypress away on `.panel-body`.

   Three ways a mode walk lies, all of them caught the hard way by review, all pinned below.

   1. IT SCANS THE SAME SURFACE TEN TIMES. `app.tsx` emits only three distinct `.workzone`
      classNames across ten modes (`cockpit`, `wide`, and `full` for the other eight), so a
      "did the surface change" check on that class is satisfied by two of ten modes. This
      walk fingerprints the ACTIVE RAIL LABEL, which is distinct per mode, and asserts it
      saw all ten.

   2. IT SCANS AN EMPTY STATE AND CALLS IT CLEAN. `app.tsx`'s honest gate renders `ModeEmpty`
      — an 11-node "Not connected" card — for any capability mode whose backend source is not
      live. Against the e2e backend that is AUTONOMY and COMMS, so scanning only the live app
      says nothing about them. Measured: their real surfaces carry five more `serious`
      contrast violations, four of them on interactive channel-filter buttons. So the walk
      runs twice, live and `?demo=1`, and records `empty` per mode so a green scan of a
      "Not connected" card can never be mistaken for coverage.

   3. IT SCANS AT ONE VIEWPORT. axe's contrast rule can only sample pixels inside the
      viewport, and layout breakpoints move content in and out of it. Measured on the unfixed
      build: BUILD's contrast violation is invisible at 1280x720 and reported at 1440x900 —
      and the cause is WIDTH, not the fold (`styles.css` `@media (max-width:1300px)` collapses
      `.build-grid` to one column, pushing the node to y=1122). In the other direction, AGENTS'
      `scrollable-region-focusable` disappears at 1920x1080 because the panel stops
      overflowing. No single viewport sees everything, so this scans two.

   Threshold and artifact discipline match a11y.spec.ts: gate on `critical` and `serious`,
   write the full result — violations AND `incomplete`, which is where axe parks contrast it
   could not resolve over a gradient — to e2e/artifacts/ for the human pass. */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdirSync, writeFileSync } from 'node:fs';

type Impact = 'critical' | 'serious' | 'moderate' | 'minor' | null;
const BLOCKING: ReadonlyArray<Exclude<Impact, null>> = ['critical', 'serious'];

/** app.tsx's own hotkey map, in its order. Ten of the sixteen rail modes. */
const MODES: ReadonlyArray<readonly [string, string]> = [
  ['1', 'cockpit'], ['2', 'agents'], ['3', 'trust'], ['4', 'memory'], ['5', 'autonomy'],
  ['6', 'build'], ['7', 'observe'], ['8', 'interop'], ['9', 'chat'], ['0', 'comms'],
];

/* The other six. `shell.tsx` MODES has sixteen entries; `app.tsx` binds number keys to ten of
   them, so `projects`, `finance`, `health`, `knowledge`, `family` and `admin` were reachable
   only by clicking the rail — which no spec did. They were walked by hand once and reported
   clean, but a hand-walk is not a gate and cannot regress-guard anything; six of sixteen HUD
   surfaces had never been scanned by axe at all. `admin` is the largest surface in the HUD
   (482 nodes in demo at 1440x900) and was one of them.

   Reached by their rail LABEL rather than by index. Index would be shorter and is what the
   pixel-contrast lane uses, but a rail index is a positional accident: `shell.tsx` interleaves
   `{sep:true}` rows, so inserting one silently renumbers every mode after it and this walk
   would keep passing while scanning the wrong surfaces. The label is the same string a user
   clicks, and the assertions below fail loudly if any of them stops matching. */
const RAIL_ONLY: ReadonlyArray<readonly [string, string]> = [
  ['Projects', 'projects'], ['Finance', 'finance'], ['Health', 'health'],
  ['Knowledge', 'knowledge'], ['Family', 'family'], ['Admin', 'admin'],
];
const ALL_MODE_COUNT = MODES.length + RAIL_ONLY.length;

/* How long `.workzone` must hold still before axe runs. Was 450ms, which review demonstrated is
   short enough to release mid-build: these surfaces arrive in stages with multi-second gaps, and
   any gap longer than the window ends the wait early. Reproduced against a real backend — the
   cockpit workzone sat at 147 nodes from t=101ms to t=2019ms before jumping to 306 (the entire
   agent roster missing), and `admin` settled at 34 of its ~442 on one run in three, because
   `api/live.ts` zeroes `V2.ADMIN` via `honestAdminSeed()` and refills it on a 30s interval.
   Every assertion in this file stayed green through both. 1600ms clears the observed gaps with
   margin; it is a mitigation and not a proof, because no DOM-quiescence heuristic can see an
   outstanding fetch — `nodes` is recorded per scan so a short scan is visible in the artifact
   after the fact. Closing this properly means a readiness signal per surface, which is its own
   slice and is written up in BACKLOG.md. */
const QUIET_MS = 1600;

/* One caveat that belongs next to the list rather than in a commit message. `projects` does not
   go through the demo path at all: `app.tsx:604` returns `<ProjectsMode t={t} />` BEFORE the
   `isLive` gate at 607-608, and never passes `demo`. So its demo lane is not independent coverage
   of its live one: both lanes run the same component against the same backend. On an isolated
   load both render 68 nodes with the same four panels; inside the walk the counts differ (85 demo
   vs 68 live on one run) purely because the walk itself accrues backend state — a session row —
   so do not read a node-count difference here as demo rendering something extra. Against this e2e
   backend those four panels are their own "nothing yet" empty states (ROOMS 0, MISSIONS 0,
   ACTIVITY "no activity yet"). That is NOT `ModeEmpty`, so `empty` is correctly false and the
   demo pin below cannot flag it. What a green lane proves for `projects` is that its CHROME and
   empty states are clean; a populated projects surface is still unscanned. */

/** The two viewports, and why each is here — see (3) above. */
const VIEWPORTS = [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
] as const;

type ModeScan = {
  mode: string; via: 'hotkey' | 'rail'; rail: string | null; empty: boolean; nodes: number;
  scrollY: number; pending: boolean; blocking: string[]; incomplete: number;
  unreported: string[];
};

/* axe's `incomplete` is "I could not decide", not "this is fine" — and on this shell it is where
   the real findings hide. The lane gates on `violations` and has only ever stored `incomplete` as
   a COUNT, so a `serious` entry there is invisible unless a human opens the JSON. That is not
   hypothetical: #1022 fixed `scrollable-region-focusable` on the AGENTS roster by adding
   `aria-label` to a role-less <div>, which is `serious · aria-prohibited-attr` — axe filed it
   under `incomplete` while the roster had content, the walk stayed green, and the regression
   merged and went unnoticed for 8.5 hours, until a review pass read the JSON. (It is a hard
   `violations` entry when the roster is
   empty, which the e2e backend never is.)

   So: SURFACE them, never gate on them. `incomplete` is not one thing — for some rules axe genuinely
   cannot decide, for others it declines for a specific resolvable reason — so a blanket gate would
   be wrong for the first kind and a blanket ignore is wrong for the second. Reporting is correct
   for both, and it is what this lane was missing entirely.

   `color-contrast` is exempted from the LISTING and counted beside it, because roughly 1,100-1,800
   nodes per lane would bury everything else. That figure is run-variable — backend state and how
   much of each surface has rendered move it — so it is a scale, not a bracket. Stated honestly,
   because the exemption is broader than its reason: it filters by RULE ID, so it suppresses every
   color-contrast incomplete, not only the ones this shell cannot resolve over a gradient. The
   gradient backlog is what `contrast.spec.ts` measures from pixels — but only for the HUD
   **chrome** (its `CHROME_PARTS`; its own NON_CLAIMS says the 16 mode surfaces are not measured).
   So EVERY color-contrast node on a mode surface is suppressed here and covered by no lane at all,
   gradient or not — measured, that is most of the suppressed total, not a non-gradient sliver.
   Real gap, recorded in BACKLOG.md rather than papered over by the wording.

   Where this is visible: `e2e.yml` triggers on schedule, dispatch and push-to-main — it has **no**
   `pull_request` trigger — so this reaches a human on the nightly and in the uploaded
   `hud-e2e-artifacts` (where `surfacedIncomplete` sits at the top level of the JSON, not buried in
   `detail`), NOT on the PR that introduces a regression. It shortens the next one from unread to
   one line in a place someone looks; it does not stop it landing. */
const SURFACE_EXEMPT = new Set(['color-contrast']);

test.describe('HUD mode surfaces', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
    });
  });

  for (const demo of [false, true]) {
    for (const vp of VIEWPORTS) {
      const lane = `${demo ? 'demo' : 'live'} · ${vp.width}x${vp.height}`;

      test(`no critical/serious accessibility violations in any HUD mode (${lane})`, async ({ page }) => {
        test.slow();   // ten modes x settle x an axe pass each
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(demo ? '/v2/?demo=1' : '/v2', { waitUntil: 'domcontentloaded' });
        await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
        await expect(page.locator('.rail-btn.active')).toBeVisible({ timeout: 20_000 });

        // Couple the walk to the RAIL, not to this file's own two lists. Without this,
        // ALL_MODE_COUNT is just MODES.length + RAIL_ONLY.length and every non-vacuity pin below
        // is satisfied by walking 16 of N buttons — so adding a 17th mode to shell.tsx would leave
        // all four lanes green while the new surface was never scanned, which is precisely the
        // hole this walk was extended to close. The rail is the app's own list; compare to it.
        expect(
          await page.locator('.rail-btn').count(),
          `shell.tsx renders a different number of rail modes than this walk knows about `
          + `(${MODES.length} hotkey + ${RAIL_ONLY.length} rail-only). A mode was added or removed: `
          + 'add it to MODES or RAIL_ONLY, do not just bump the number.',
        ).toBe(ALL_MODE_COUNT);

        const scans: ModeScan[] = [];
        const all: unknown[] = [];

        // Ten modes reached by their hotkey, then the six that have none, reached by the rail.
        const walk: ReadonlyArray<{ name: string; via: 'hotkey' | 'rail'; go: () => Promise<void> }> = [
          ...MODES.map(([key, name]) => ({
            name, via: 'hotkey' as const,
            go: async () => {
              // Blur first: the hotkey handler correctly ignores keys typed in a field or in the
              // transcript's role="log" region, so a stray focus would silently keep us on one mode.
              await page.evaluate(() => { const a = document.activeElement as HTMLElement | null; if (a && a.blur) a.blur(); });
              await page.keyboard.press(key);
            },
          })),
          ...RAIL_ONLY.map(([label, name]) => ({
            name, via: 'rail' as const,
            go: async () => {
              // Exact-match the label: `hasText: 'Health'` alone is a substring test, and a future
              // rail row like "Health history" would make this click a different mode while every
              // assertion here still passed.
              const btn = page.locator('.rail-btn').filter({ hasText: new RegExp(`^\\s*${label}\\s*$`) });
              await expect(
                btn,
                `no rail button labelled "${label}" — shell.tsx MODES and this list have drifted`,
              ).toHaveCount(1);
              // DOM activation, not a mouse click, and the reason is a real defect this walk must
              // not depend on: `world_app.tsx` paints a `button.tool-btn` at
              // `position:fixed; left:16; bottom:16; zIndex:60`, directly over the bottom of the
              // rail. At 1440x900 the ADMIN button is 847.8-885.9 and that overlay covers its
              // action point, so `btn.click()` fails Playwright's actionability check and retries
              // — landing only when `.tex-scanbar`'s 9s animation transiently grows the document
              // enough for `scrollIntoViewIfNeeded` to shift the rail clear. A surface gate whose
              // reachability rides on a decorative animation is a flake with a countdown on it.
              // `el.click()` dispatches a real DOM click through React's own onClick, so this
              // walk tests the MODE, deterministically, and does not pretend to test pointer
              // reachability. That the overlay covers a control is a genuine finding and is
              // recorded in BACKLOG.md as its own row rather than absorbed here.
              await btn.evaluate((el) => (el as HTMLElement).click());
            },
          })),
        ];

        for (const { name, via, go } of walk) {
          // Clear the settle memo BEFORE switching. It lives on `window` and its `since` stamp is
          // reset only when the node count changes — so if a new surface's first paint happens to
          // have the same `.workzone` descendant count as the previous surface's last, the 450ms
          // quiet window is already satisfied on entry and axe scans a half-built DOM. With ten
          // modes that collision was unlikely; with sixteen, six of them small, it is not.
          await page.evaluate(() => { delete (window as unknown as { __a11ySettle?: unknown }).__a11ySettle; });
          await go();

          // Put every mode on the same viewport before scanning. A hotkey never moves the page,
          // but `click()` scrolls its target into view — and at 1280x720 the HUD is 831px tall, so
          // the Family, Comms and Admin rail buttons are below the fold and clicking Admin scrolls
          // the document to y=240 (measured). Since axe's contrast rule can only sample pixels
          // inside the viewport — point (3) at the top of this file — that would scan the six
          // rail modes in a scrolled state no hotkey mode is ever scanned in, making the lanes
          // silently non-comparable. `scrollY` goes into the artifact so this is checkable rather
          // than trusted.
          await page.evaluate(() => window.scrollTo(0, 0));

          // Not a bare sleep: wait for the DOM to stop changing. What that buys, stated exactly,
          // because the previous wording ("so a slow runner scans the same thing a fast one
          // does") claimed more than the predicate delivers — under enough latency a slow runner
          // scans strictly LESS. It proves the surface stopped changing for QUIET_MS, which is
          // strictly better than a fixed wait and is not the same as proving it finished.
          await page.waitForFunction((quietMs: number) => {
            const wz = document.querySelector('.workzone');
            if (!wz) return false;
            const w = window as unknown as { __a11ySettle?: { n: number; since: number } };
            const n = wz.querySelectorAll('*').length;
            const now = Date.now();
            if (!w.__a11ySettle || w.__a11ySettle.n !== n) { w.__a11ySettle = { n, since: now }; return false; }
            return now - w.__a11ySettle.since > quietMs;
            // QUIET_MS is a Node-side constant and this predicate runs IN THE PAGE, so it has to
            // travel as an argument; referencing it directly throws ReferenceError at runtime.
          }, QUIET_MS, { timeout: 25_000 });
          // What this still cannot see, stated rather than left for the next reader to discover.
          // The predicate proves the DOM STOPPED changing, not that it FINISHED: a surface whose
          // async section holds a same-shape placeholder is genuinely flat while its request is in
          // flight, so a stall longer than 450ms ends the wait early and axe scans a partial tree.
          // The known instance is ADMIN — EstopCard (src/modes3.tsx) shows a one-node "checking
          // estop..." placeholder until /api/ops/estop answers. Each scan therefore records
          // `pending`, so the artifact says whether a placeholder was on screen instead of leaving
          // a green scan to imply the surface was complete. This is NOT gated on: `ModeEmpty`'s
          // own copy is a legitimate resting state in the live lane, so blocking on "no
          // placeholder" would turn a correct live surface into a 25s timeout.

          const meta = await page.evaluate(() => {
            const wz = document.querySelector('.workzone');
            const rail = document.querySelector('.rail-btn.active .rl');
            const txt = wz ? (wz.textContent || '') : '';
            return {
              rail: rail ? (rail.textContent || '').trim() : null,
              scrollY: Math.round(window.scrollY),
              // Was an async section still resolving when axe ran? See the settle note above.
              pending: /checking|loading|connecting\u2026|please wait/i.test(txt),
              nodes: wz ? wz.querySelectorAll('*').length : 0,
              // ModeEmpty's own copy — app.tsx renders one of these two strings.
              empty: !!(wz && /Not connected|Design preview/.test(wz.textContent || '')),
            };
          });

          const results = await new AxeBuilder({ page })
            .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
            .analyze();
          all.push({ lane, mode: name, via, ...meta, violations: results.violations, incomplete: results.incomplete });

          scans.push({
            mode: name, via, rail: meta.rail, empty: meta.empty, nodes: meta.nodes,
            scrollY: meta.scrollY, pending: meta.pending,
            incomplete: results.incomplete.length,
            // `impact == null` is surfaced too, not dropped. Every `incomplete` entry this shell
            // produces today carries one (measured across the four lanes: 64 color-contrast + 4
            // aria-prohibited-attr entries, all `serious`), but axe leaves `impact` null when it cannot
            // even estimate severity — and silently discarding an unrated finding is the same bug
            // this block exists to close, one level down. An unknown severity is not a safe one.
            unreported: results.incomplete
              .filter((v) => v.impact == null || BLOCKING.includes(v.impact as never))
              .filter((v) => !SURFACE_EXEMPT.has(v.id))
              .map((v) => `${v.impact ?? 'unrated'} · ${v.id} (${v.nodes.length}) → ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`),
            blocking: results.violations
              .filter((v) => BLOCKING.includes((v.impact ?? '') as never))
              .map((v) => `${v.impact} · ${v.id} (${v.nodes.length}) → ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`),
          });
        }

        // Surfaced, not gated (see SURFACE_EXEMPT above). This is the only place a `serious`
        // `incomplete` finding becomes visible without opening the JSON, so it goes to the console
        // as well as the artifact — a lane that is green while hiding a serious finding is exactly
        // how the last one got in.
        const unreported = scans.filter((s) => s.unreported.length);
        // NODES, not entries. axe returns ONE `incomplete` entry per rule id with every unresolved
        // node inside its `nodes[]`, so counting entries answers "how many of the 16 modes had any
        // contrast incomplete" (always ~16) and not "how much is suppressed" (order of a thousand per lane).
        // The first version of this line reported 16 and read as a node count — a number labelled
        // as one thing that measured another, which is the failure this whole block is about.
        const contrastExempt = (all as { incomplete: { id: string; nodes: unknown[] }[] }[])
          .flatMap((e) => e.incomplete.filter((v) => SURFACE_EXEMPT.has(v.id)));
        const contrastIncompleteNodes = contrastExempt.reduce((n, v) => n + v.nodes.length, 0);
        const contrastIncompleteModes = contrastExempt.length;
        if (unreported.length) {
          console.log(`a11y ${lane} · findings this lane SURFACES but does not fail on:`);
          for (const s of unreported) for (const line of s.unreported) console.log(`    ${s.mode}: ${line}`);
        }
        console.log(
          `a11y ${lane} · ${unreported.length} mode(s) with a surfaced incomplete finding; `
          + `${contrastIncompleteNodes} color-contrast incomplete NODES across `
          + `${contrastIncompleteModes} mode(s), not listed — see the note above SURFACE_EXEMPT`,
        );

        mkdirSync('e2e/artifacts', { recursive: true });
        writeFileSync(
          `e2e/artifacts/a11y-modes-${demo ? 'demo' : 'live'}-${vp.width}x${vp.height}.json`,
          JSON.stringify({
            lane,
            counts: tally(all),
            // Header, so a reader sees this without walking `scans`: what axe declined to judge at
            // serious/critical or unrated impact, minus the color-contrast entries counted beside it.
            surfacedIncomplete: unreported.map((s) => ({ mode: s.mode, findings: s.unreported })),
            contrastIncompleteNodes,
            contrastIncompleteModes,
            scans,
            detail: all,
          }, null, 2),
        );

        // A rail click that does not land is SILENT: `setMode` is skipped for a locked entry
        // (shell.tsx:107), the previous surface stays mounted, and axe re-scans it and reports it
        // clean under the new mode's name. This runs BEFORE the distinct-count pin below, and the
        // ordering is the whole point rather than an accident: a miss always duplicates the
        // PREVIOUS mode's label, so the count pin does catch it — red-proofed by making the Family
        // button deaf to clicks, which produced `..., Knowledge, Knowledge, Admin` and failed the
        // count at 15 of 16. But it fails with a list of sixteen labels to eyeball. This one names
        // the mode and says what was actually on screen instead.
        const railMisses = scans
          .filter((s) => s.via === 'rail')
          .filter((s) => (s.rail || '').toLowerCase() !== s.mode.toLowerCase());
        expect(
          railMisses.map((s) => `${s.mode} -> active rail was "${s.rail}"`),
          'a rail click did not change the active mode; that scan re-measured the previous surface',
        ).toEqual([]);

        const scrolled = scans.filter((s) => s.scrollY !== 0);
        expect(
          scrolled.map((s) => `${s.mode} scanned at scrollY=${s.scrollY}`),
          'every mode must be scanned at the same scroll offset; axe samples contrast only inside '
          + 'the viewport, so a scrolled scan is not comparable with the others',
        ).toEqual([]);

        // Non-vacuity pin. The rail label is distinct per mode; `.workzone`'s className is NOT
        // (eight modes share `workzone full`), so a "did it change" check on the class passes
        // while eight of ten scans look at the same surface — demonstrated, not theorised.
        const rails = scans.map((s) => s.rail);
        expect(
          new Set(rails.filter(Boolean)).size,
          `the walk must reach ${ALL_MODE_COUNT} distinct surfaces; saw: ${rails.join(', ')}`,
        ).toBe(ALL_MODE_COUNT);

        // In demo every mode renders for real, so an empty card there means the walk did not
        // actually get in. Live is allowed to have empty states — that is the honest gate — and
        // the artifact records which, so a green live run is never read as covering them.
        if (demo) {
          expect(
            scans.filter((s) => s.empty).map((s) => s.mode),
            'in demo mode every surface should render; an empty "Not connected" card means the scan saw nothing',
          ).toEqual([]);
        }

        const offenders = scans.filter((s) => s.blocking.length > 0);
        expect(
          offenders,
          `axe found critical/serious violations (${lane}):\n` +
            offenders.map((s) => `  ${s.mode}${s.empty ? ' [EMPTY STATE]' : ''}:\n    ${s.blocking.join('\n    ')}`).join('\n'),
        ).toEqual([]);
      });
    }
  }
});

/** Count violations by impact across every mode, for the artifact header. */
function tally(all: unknown[]) {
  const counts: Record<string, number> = { critical: 0, serious: 0, moderate: 0, minor: 0, 'n/a': 0, incomplete: 0 };
  for (const entry of all as { violations: { impact?: Impact }[]; incomplete: unknown[] }[]) {
    for (const v of entry.violations) counts[v.impact ?? 'n/a'] = (counts[v.impact ?? 'n/a'] ?? 0) + 1;
    counts.incomplete += entry.incomplete.length;
  }
  return counts;
}
