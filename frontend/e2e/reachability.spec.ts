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

  test(`the focus ring is not clipped at ${width}px`, async ({ page }) => {
    // Companion to the test above, and it exists because the fix for that one caused this
    // bug: `overflow-y:auto` promotes the used `overflow-x` to `auto` per spec, so the
    // workzone starts clipping horizontally and eats the `:focus-visible` outline — which
    // is drawn at outline-offset:2px, i.e. 4px OUTSIDE the border box. axe cannot see a
    // clipped outline, so a11y.spec.ts passes either way; only geometry catches it.
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/v2', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
    await page.waitForTimeout(600);

    const m = await page.evaluate(() => {
      const wz = document.querySelector('.workzone') as HTMLElement | null;
      if (!wz) return null;
      const clips = getComputedStyle(wz).overflowX !== 'visible';
      const box = wz.getBoundingClientRect();
      const focusables = Array.from(wz.querySelectorAll<HTMLElement>('[tabindex="0"], button, a[href], input'))
        .filter((el) => el.getBoundingClientRect().width > 0);
      if (!focusables.length) return { clips, worstOverhang: 0, who: 'none', ring: 0 };

      // Read the ring geometry from a FOCUSED element. Unfocused ones report
      // outline-width/offset as 0px — measuring those makes this assertion always pass,
      // which is exactly how the first version of it failed its own red-proof.
      const probe = focusables[0];
      const active = document.activeElement as HTMLElement | null;
      probe.focus();
      const pcs = getComputedStyle(probe);
      const ring = parseFloat(pcs.outlineWidth || '0') + parseFloat(pcs.outlineOffset || '0');
      if (active && active !== probe) active.focus(); else probe.blur();

      let worst = 0; let who = '';
      for (const el of focusables) {
        const r = el.getBoundingClientRect();
        const overhang = Math.round(Math.max(box.left - (r.left - ring), (r.right + ring) - box.right));
        if (overhang > worst) { worst = overhang; who = el.tagName.toLowerCase() + '.' + ((el.className || '').toString().trim().split(/\s+/)[0] || ''); }
      }
      return { clips, worstOverhang: worst, who, ring };
    });

    expect(m, 'the workzone should exist').not.toBeNull();
    // Pin the probe's ring geometry. Without this the assertion below can pass VACUOUSLY:
    // if the probe ever stops matching :focus-visible, or picks up an `outline:0` override
    // (as `.inputbar .field input` does), `ring` silently becomes 0 and nothing can overhang.
    // That is exactly how the first version of this test self-passed against a broken build.
    expect(
      m!.ring,
      `the focus-ring probe (${m!.who || 'first focusable'}) reported a ${m!.ring}px ring; ` +
      'it should be 4px (outline 2px + offset 2px). A 0px ring makes the check below vacuous.',
    ).toBe(4);
    if (m!.clips) {
      expect(
        m!.worstOverhang,
        `at ${width}px the workzone clips horizontally and ${m!.who}'s focus ring overhangs ` +
        `its clip box by ${m!.worstOverhang}px — the ring will be cut off. Give the ` +
        'collapsed workzone enough horizontal padding to hold a 4px outline.',
      ).toBeLessThanOrEqual(0);
    }
  });
}
