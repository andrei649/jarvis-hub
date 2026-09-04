/* HUD v2 · accessibility gate for the MODE surfaces (the other nine).

   Why this file exists. `a11y.spec.ts` scans the cockpit route and the cinema overlay.
   That is two of eleven surfaces, and a green a11y lane was being read as "the HUD is
   accessible". Walking all ten modes with axe found three blocking violations on
   surfaces no spec had ever visited — one of them the SAME rule
   (`scrollable-region-focusable`) that a11y.spec.ts had just been extended to cover on
   `.convo`, sitting one keypress away on `.panel-body`.

   Same threshold as a11y.spec.ts, for the same reason: gate on `critical` and `serious`
   (unambiguous bugs) and write the full list, all impacts, to e2e/artifacts/ as the
   reviewable audit trail. The moderate/minor backlog stays visible without blocking.

   The modes are reached by their number hotkeys (app.tsx), which is how a user reaches
   them; `blur()` first because the hotkey handler correctly ignores keys typed inside an
   input, a textarea or the transcript's `role="log"` region. */
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

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
  });
});

test('every HUD mode is free of critical/serious accessibility violations', async ({ page }) => {
  // 1440x900, not the project default. axe's colour-contrast rule can only sample pixels
  // that are actually in the viewport, so a scan is only as wide as the window: measured,
  // BUILD's `.sb-in > span:nth-child(2)` (2.8:1, needs 4.5:1) sits below the fold at
  // 1280x720 and axe skips it entirely, then reports it at 1440x900 and 1920x1080. A
  // taller window is a bigger scan, not a friendlier one.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
  await page.waitForTimeout(800);

  const report: Record<string, string[]> = {};
  const all: unknown[] = [];

  for (const [key, name] of MODES) {
    // The mode hotkeys are ignored while focus is in a field or the transcript, which is
    // correct behaviour and would otherwise leave this test scanning the same mode ten
    // times — a way for it to pass while proving almost nothing.
    await page.evaluate(() => { const a = document.activeElement as HTMLElement | null; if (a && a.blur) a.blur(); });
    await page.keyboard.press(key);
    await page.waitForTimeout(900);   // let the mode's panels mount and their fetches settle

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    all.push({ mode: name, violations: results.violations });

    report[name] = results.violations
      .filter((v) => BLOCKING.includes((v.impact ?? '') as never))
      .map((v) => `${v.impact} · ${v.id} (${v.nodes.length}) → ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`);
  }

  mkdirSync('e2e/artifacts', { recursive: true });
  writeFileSync('e2e/artifacts/a11y-modes.json', JSON.stringify(all, null, 2));

  // Non-vacuity pin. If the hotkeys stop switching modes — a focus trap, a renamed
  // handler — every scan above runs against the cockpit and the loop proves nothing.
  // The mode surfaces are distinguishable by their workzone class.
  const seen = new Set<string>();
  for (const [key] of MODES) {
    await page.evaluate(() => { const a = document.activeElement as HTMLElement | null; if (a && a.blur) a.blur(); });
    await page.keyboard.press(key);
    await page.waitForTimeout(400);
    seen.add(await page.evaluate(() => (document.querySelector('.workzone')?.className ?? 'none')));
  }
  expect(seen.size, `the number hotkeys should reach visibly different surfaces, got ${[...seen].join(', ')}`).toBeGreaterThan(1);

  const offenders = Object.entries(report).filter(([, v]) => v.length > 0);
  expect(
    offenders,
    'axe found critical/serious violations in these HUD modes:\n' +
      offenders.map(([m, v]) => `  ${m}:\n    ${v.join('\n    ')}`).join('\n'),
  ).toEqual([]);
});
