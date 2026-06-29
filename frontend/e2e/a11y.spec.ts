/* HUD v2 · accessibility gate (H23.17). Runs axe-core against the live cockpit
   (and the cinema overlay) in real Chromium — the WCAG checks jsdom/vitest can't
   do: real computed colour-contrast, ARIA/role correctness, focus-order, and
   landmark structure on the actually-painted DOM.

   Threshold is intentionally conservative: the cockpit is a dense, custom canvas
   HUD (not a form-heavy CRUD app), so we gate on the impact levels that are
   unambiguous bugs — `critical` and `serious` — rather than chasing every
   `moderate`/`minor` advisory. The full violation list (all impacts) is written
   to e2e/artifacts/a11y-*.json as the human-reviewable audit trail, so the
   moderate/minor backlog stays visible without blocking the lane. */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdirSync, writeFileSync } from 'node:fs';

type Impact = 'critical' | 'serious' | 'moderate' | 'minor' | null;
const BLOCKING: ReadonlyArray<Exclude<Impact, null>> = ['critical', 'serious'];

/** Compact summary line per violation for the failure message + artifact. */
function summarise(violations: { id: string; impact?: Impact; nodes: unknown[] }[]) {
  return violations.map((v) => `${v.impact ?? 'n/a'} · ${v.id} (${v.nodes.length} node${v.nodes.length === 1 ? '' : 's'})`);
}

test('HUD v2 cockpit has no critical/serious accessibility violations', async ({ page }) => {
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  // wait for the React app + mesh to actually mount before scanning the DOM
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
  await expect(page.locator('.nmesh canvas').first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(800); // let panels settle / async data degrade-or-fill

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  mkdirSync('e2e/artifacts', { recursive: true });
  writeFileSync(
    'e2e/artifacts/a11y-cockpit.json',
    JSON.stringify({ url: '/v2', counts: tally(results.violations), violations: results.violations }, null, 2),
  );

  const blocking = results.violations.filter((v) => BLOCKING.includes((v.impact ?? '') as never));
  expect(
    blocking,
    `axe found ${blocking.length} critical/serious violation(s) on /v2:\n` + summarise(blocking).join('\n'),
  ).toEqual([]);
});

test('Cinema mode overlay has no critical/serious accessibility violations', async ({ page }) => {
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.nmesh canvas').first()).toBeVisible({ timeout: 20_000 });

  await page.keyboard.press('m');
  await expect(page.locator('.cinema')).toBeVisible();
  await page.waitForTimeout(500);

  const results = await new AxeBuilder({ page })
    .include('.cinema')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  mkdirSync('e2e/artifacts', { recursive: true });
  writeFileSync(
    'e2e/artifacts/a11y-cinema.json',
    JSON.stringify({ scope: '.cinema', counts: tally(results.violations), violations: results.violations }, null, 2),
  );

  const blocking = results.violations.filter((v) => BLOCKING.includes((v.impact ?? '') as never));
  expect(
    blocking,
    `axe found ${blocking.length} critical/serious violation(s) in cinema mode:\n` + summarise(blocking).join('\n'),
  ).toEqual([]);
});

/** Count violations by impact level for the artifact header. */
function tally(violations: { impact?: Impact }[]) {
  const counts: Record<string, number> = { critical: 0, serious: 0, moderate: 0, minor: 0, 'n/a': 0 };
  for (const v of violations) counts[v.impact ?? 'n/a'] = (counts[v.impact ?? 'n/a'] ?? 0) + 1;
  return counts;
}
