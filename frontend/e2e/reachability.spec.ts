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
    // Since the cutover (PHASE_B_PLAN.md §8.2 row 24) the input bar is the Ledger composer's:
    // [data-composer-bar] with its Send, [data-composer-send]. Home keeps the conversation beside
    // the docket down to 1100px; at 1099px and below it is one column and the page scrolls. So
    // REACHABLE is asserted as the owner meets it: scrolled to (as focus or a wheel would bring it,
    // through whatever ancestors really scroll), the bar and Send sit wholly inside the viewport and
    // a press at Send's centre lands on Send. A bar no scrolling can bring into view fails here.
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/v2', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
    const bar = page.locator('[data-composer-bar]').first();
    await expect(bar, 'the composer bar should exist').toBeAttached({ timeout: 20_000 });
    await page.waitForTimeout(600);
    await bar.scrollIntoViewIfNeeded();

    const m = await page.evaluate(() => {
      const bar = document.querySelector('[data-composer-bar]') as HTMLElement | null;
      const send = document.querySelector('[data-composer-send]') as HTMLElement | null;
      if (!bar || !send) return null;
      const inside = (r: DOMRect) => r.width > 0 && r.height > 0 && r.top >= -1 && r.left >= -1
        && r.bottom <= window.innerHeight + 1 && r.right <= window.innerWidth + 1;
      const b = bar.getBoundingClientRect();
      const s = send.getBoundingClientRect();
      const hit = document.elementFromPoint(s.left + s.width / 2, s.top + s.height / 2);
      const name = (el: Element | null) => el ? `${el.tagName.toLowerCase()}.${(el.className || '').toString().trim().split(/\s+/)[0] || ''}` : 'nothing';
      return {
        barInside: inside(b), sendInside: inside(s), sendHit: !!hit && send.contains(hit), hit: name(hit),
        bar: [b.left, b.top, b.right, b.bottom].map(Math.round), send: [s.left, s.top, s.right, s.bottom].map(Math.round),
        innerWidth: window.innerWidth, innerHeight: window.innerHeight,
      };
    });

    expect(m, 'the composer bar and its Send should exist').not.toBeNull();
    const where = `in a ${m!.innerWidth}x${m!.innerHeight} viewport (bar ${m!.bar.join(',')}, Send ${m!.send.join(',')})`;
    expect(m!.barInside, `the composer bar is unreachable at ${width}px: scrolled to, it is still not inside the viewport ${where}`).toBe(true);
    expect(m!.sendInside, `Send is unreachable at ${width}px: scrolled to, it is still not inside the viewport ${where}`).toBe(true);
    expect(m!.sendHit, `a press at Send's centre at ${width}px lands on ${m!.hit}, not on Send ${where}`).toBe(true);
  });

  test(`the focus ring is not clipped at ${width}px`, async ({ page }) => {
    // Companion to the test above, and it exists because the fix for that one once caused this
    // bug: `overflow-y:auto` promotes the used `overflow-x` to `auto` per spec, so a region that
    // scrolls starts clipping horizontally and eats the `:focus-visible` outline — which is drawn
    // at outline-offset:2px, i.e. 4px OUTSIDE the border box. axe cannot see a clipped outline,
    // so a11y.spec.ts passes either way; only geometry catches it.
    // Since the cutover (PHASE_B_PLAN.md §8.2 row 23) the region is the frame's page,
    // `[data-frame="page"]` (Home scrolls inside it below 1100px), still with a 4px ring. The
    // registers that scroll inside the page are their own clip boxes and are not measured here.
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/v2', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
    await expect(page.locator('[data-frame="page"]')).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(600);

    const m = await page.evaluate(() => {
      const region = document.querySelector('[data-frame="page"]') as HTMLElement | null;
      if (!region) return null;
      const clips = getComputedStyle(region).overflowX !== 'visible';
      const box = region.getBoundingClientRect();
      const shown = (el: HTMLElement) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !el.matches(':disabled'); };
      const focusables = Array.from(region.querySelectorAll<HTMLElement>('[tabindex="0"], button, a[href], input, textarea, select'))
        .filter(shown);
      const name = (el: HTMLElement) => el.tagName.toLowerCase() + '.' + ((el.className || '').toString().trim().split(/\s+/)[0] || '');
      // The probe is the page's first control (a button or a link): the ring every control
      // takes. A scrolling region focused as a whole (the transcript's role="log") may draw its
      // ring inside itself, so it is measured below but never chosen as the probe.
      const probe = focusables.find((el) => el.matches('button, a[href]'));
      if (!probe) return { clips, worstOverhang: 0, who: 'none', ring: 0, probe: 'none' };

      // Read the ring geometry from a FOCUSED element. Unfocused ones report
      // outline-width/offset as 0px — measuring those makes this assertion always pass,
      // which is exactly how the first version of it failed its own red-proof.
      const active = document.activeElement as HTMLElement | null;
      probe.focus();
      const pcs = getComputedStyle(probe);
      const ring = parseFloat(pcs.outlineWidth || '0') + parseFloat(pcs.outlineOffset || '0');
      if (active && active !== probe) active.focus(); else probe.blur();

      let worst = 0; let who = '';
      for (const el of focusables) {
        const r = el.getBoundingClientRect();
        const overhang = Math.round(Math.max(box.left - (r.left - ring), (r.right + ring) - box.right));
        if (overhang > worst) { worst = overhang; who = name(el); }
      }
      return { clips, worstOverhang: worst, who, ring, probe: name(probe) };
    });

    expect(m, 'the frame\'s page region should exist').not.toBeNull();
    // Pin the probe's ring geometry. Without this the assertion below can pass VACUOUSLY:
    // if the probe ever stops matching :focus-visible, or picks up an `outline:0` override
    // (as the classic `.inputbar .field input` did), `ring` silently becomes 0 and nothing can
    // overhang. That is exactly how the first version of this test self-passed against a broken build.
    expect(
      m!.ring,
      `the focus-ring probe (${m!.probe}) reported a ${m!.ring}px ring; ` +
      'it should be 4px (outline 2px + offset 2px). A 0px ring makes the check below vacuous.',
    ).toBe(4);
    if (m!.clips) {
      expect(
        m!.worstOverhang,
        `at ${width}px the page region clips horizontally and ${m!.who}'s focus ring overhangs ` +
        `its clip box by ${m!.worstOverhang}px — the ring will be cut off. Give the page ` +
        'enough horizontal padding to hold a 4px outline.',
      ).toBeLessThanOrEqual(0);
    }
  });
}
