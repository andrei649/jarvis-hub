/* HUD v2 · content reachability at laptop widths. Proves the chat input bar can actually
   be reached — the thing jsdom/vitest cannot check, because it needs real grid row sizing
   against a real viewport.

   Why this exists. `@media (max-width:1100px)` (styles.css) collapses `.workzone.cockpit`
   to a single column, so its `.col` children stack vertically. The workzone is a grid with
   auto rows inside a `height:100%` shell that cannot grow, so the FIRST column takes its
   whole content height and the chat column gets whatever is left: measured
   `grid-template-rows: 577px 18px` at 1000x800. An 18px row cannot hold a 77px input bar,
   so it painted at y=931 in an 800px-tall viewport — below the fold, with nothing
   scrollable to reach it. The cockpit was unusable at 1100, 1000, 900 and 800px: ordinary
   laptop and split-screen widths.

   What is asserted, and what deliberately is not. The contract here is REACHABILITY: the
   input bar is either inside the viewport, or inside an ancestor that genuinely scrolls to
   it. It is not "the transcript is a comfortable height" — how tall a stacked transcript
   should be is a layout-design question that belongs with the still-open owner call on the
   sub-760px phone surface (BACKLOG.md, "The phone surface"), not with a reachability fix.
   Asserting a height here would be inventing that answer.

   Scope. Every width is >= 761px. Nothing below 760px is asserted, for the same reason. */
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
  });
});

/** 1280 is above the collapse breakpoint; the rest are inside the broken band. */
const WIDTHS = [1280, 1100, 1000, 900, 800] as const;

for (const width of WIDTHS) {
  test(`the chat input bar is reachable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/v2', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
    await page.waitForTimeout(600);

    const m = await page.evaluate(() => {
      const bar = document.querySelector('.inputbar') as HTMLElement | null;
      if (!bar) return null;
      const r = bar.getBoundingClientRect();
      const inViewport = r.bottom <= window.innerHeight + 1 && r.top >= -1;
      // …or reachable by scrolling: an ancestor that both overflows AND is allowed to scroll
      let scrollableAncestor: string | null = null;
      for (let e = bar.parentElement; e; e = e.parentElement) {
        const cs = getComputedStyle(e);
        if (/auto|scroll/.test(cs.overflowY) && e.scrollHeight > e.clientHeight + 1) {
          scrollableAncestor = `${e.tagName.toLowerCase()}.${(e.className || '').toString().trim().split(/\s+/)[0] || ''}`;
          break;
        }
      }
      const wz = document.querySelector('.workzone');
      return {
        inViewport,
        scrollableAncestor,
        barBottom: Math.round(r.bottom),
        innerHeight: window.innerHeight,
        workzoneRows: wz ? getComputedStyle(wz).gridTemplateRows : 'n/a',
      };
    });

    expect(m, 'the chat input bar should exist').not.toBeNull();
    expect(
      m!.inViewport || m!.scrollableAncestor !== null,
      `the input bar is unreachable at ${width}px: it ends at y=${m!.barBottom} in a ` +
      `${m!.innerHeight}px viewport and no ancestor scrolls to it ` +
      `(workzone rows: ${m!.workzoneRows}) — the collapsed single-column workzone crushed ` +
      'the chat row instead of letting the stack scroll',
    ).toBe(true);
  });
}
