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

/** app.tsx's own hotkey map, in its order. */
const MODES: ReadonlyArray<readonly [string, string]> = [
  ['1', 'cockpit'], ['2', 'agents'], ['3', 'trust'], ['4', 'memory'], ['5', 'autonomy'],
  ['6', 'build'], ['7', 'observe'], ['8', 'interop'], ['9', 'chat'], ['0', 'comms'],
];

/** The two viewports, and why each is here — see (3) above. */
const VIEWPORTS = [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
] as const;

type ModeScan = {
  mode: string; rail: string | null; empty: boolean; nodes: number;
  blocking: string[]; incomplete: number;
};

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

        const scans: ModeScan[] = [];
        const all: unknown[] = [];

        for (const [key, name] of MODES) {
          // Blur first: the hotkey handler correctly ignores keys typed in a field or in the
          // transcript's role="log" region, so a stray focus would silently keep us on one mode.
          await page.evaluate(() => { const a = document.activeElement as HTMLElement | null; if (a && a.blur) a.blur(); });
          await page.keyboard.press(key);

          // Not a bare sleep. Measured: with 1.5s of added API latency the AGENTS surface is
          // still at 64 of its final 318 nodes at 900ms, and a fixed wait silently scanned the
          // half-built DOM — two of three red-proof findings vanished. Wait for the DOM to stop
          // changing instead, so a slow runner scans the same thing a fast one does.
          await page.waitForFunction(() => {
            const wz = document.querySelector('.workzone');
            if (!wz) return false;
            const w = window as unknown as { __a11ySettle?: { n: number; since: number } };
            const n = wz.querySelectorAll('*').length;
            const now = Date.now();
            if (!w.__a11ySettle || w.__a11ySettle.n !== n) { w.__a11ySettle = { n, since: now }; return false; }
            return now - w.__a11ySettle.since > 450;
          }, undefined, { timeout: 25_000 });

          const meta = await page.evaluate(() => {
            const wz = document.querySelector('.workzone');
            const rail = document.querySelector('.rail-btn.active .rl');
            return {
              rail: rail ? (rail.textContent || '').trim() : null,
              nodes: wz ? wz.querySelectorAll('*').length : 0,
              // ModeEmpty's own copy — app.tsx renders one of these two strings.
              empty: !!(wz && /Not connected|Design preview/.test(wz.textContent || '')),
            };
          });

          const results = await new AxeBuilder({ page })
            .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
            .analyze();
          all.push({ lane, mode: name, ...meta, violations: results.violations, incomplete: results.incomplete });

          scans.push({
            mode: name, rail: meta.rail, empty: meta.empty, nodes: meta.nodes,
            incomplete: results.incomplete.length,
            blocking: results.violations
              .filter((v) => BLOCKING.includes((v.impact ?? '') as never))
              .map((v) => `${v.impact} · ${v.id} (${v.nodes.length}) → ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`),
          });
        }

        mkdirSync('e2e/artifacts', { recursive: true });
        writeFileSync(
          `e2e/artifacts/a11y-modes-${demo ? 'demo' : 'live'}-${vp.width}x${vp.height}.json`,
          JSON.stringify({ lane, counts: tally(all), scans, detail: all }, null, 2),
        );

        // Non-vacuity pin. The rail label is distinct per mode; `.workzone`'s className is NOT
        // (eight modes share `workzone full`), so a "did it change" check on the class passes
        // while eight of ten scans look at the same surface — demonstrated, not theorised.
        const rails = scans.map((s) => s.rail);
        expect(
          new Set(rails.filter(Boolean)).size,
          `the number hotkeys must reach ${MODES.length} distinct surfaces; saw: ${rails.join(', ')}`,
        ).toBe(MODES.length);

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
