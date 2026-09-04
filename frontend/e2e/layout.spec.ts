/* HUD v2 · layout fit (H23.17 tail). Proves the cockpit does not scroll sideways at
   ordinary laptop widths — the thing jsdom/vitest cannot check, because it needs real
   grid track sizing against a real viewport.

   Why this exists. `.topbar` and the collapsed `.workzone` used a BARE `1fr` track.
   `1fr` means `minmax(auto, 1fr)`, and that `auto` minimum is the item's min-content
   width, so the track physically cannot shrink below it: at a 900px viewport the topbar
   still demanded 1082px and the whole document scrolled sideways. The window where it
   bit — roughly 760px to 1080px — is a normal laptop window or a half-screen split, not
   an exotic size.

   Scope, deliberately. Every width asserted here is >= 760px. The sub-760px phone
   surface is a separate, still-open owner call (BACKLOG.md, "The phone surface"): the
   HUD has no stacked-layout breakpoint below 760px and this spec does not pretend it
   does. Asserting a phone width here would be asserting a contract the product has not
   decided to offer. */
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
  });
});

/** Laptop widths that sit inside, above and below the old blow-out window. */
const WIDTHS = [1280, 1000, 900, 800] as const;

for (const width of WIDTHS) {
  test(`cockpit fits its viewport at ${width}px — no horizontal scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/v2', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
    // let the roster/panels settle: the overflow came from content-driven track sizing
    await page.waitForTimeout(600);

    const fit = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      topbarTracks: getComputedStyle(document.querySelector('.topbar') as Element).gridTemplateColumns,
    }));

    expect(
      fit.scrollWidth,
      `the document scrolls sideways at ${width}px (topbar tracks: ${fit.topbarTracks}) — ` +
      'a flexible grid track is refusing to shrink below its min-content width',
    ).toBeLessThanOrEqual(fit.clientWidth);
  });
}
