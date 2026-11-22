/* HUD v2 · topbar layout fit (H23.17 tail). Proves the cockpit neither overflows its
   viewport nor solves that by stacking its own content at ordinary laptop widths — the
   thing jsdom/vitest cannot check, because it needs real grid track sizing and real
   painted geometry.

   Why this exists. `.topbar` used a BARE `1fr` track. `1fr` means `minmax(auto, 1fr)`,
   and that `auto` minimum is the item's min-content width, so the track physically could
   not shrink below `.brand` — which nests the 6-badge status strip (`shell.tsx:52`).
   At a 900px viewport the topbar still demanded 1082px. `body{overflow:hidden}`
   (styles.css) propagates to the viewport, so there was no scrollbar: the excess was
   simply CLIPPED and unreachable, which is worse than scrolling, not better.

   Why there are TWO assertions. The obvious fix — `minmax(0,1fr)` alone — makes the
   first assertion pass while making the page worse: the track shrinks but `.brand` (a
   flex item with no `min-width:0`) does not, so its content spills over the centred
   clock. Measured 109px of overlap at 1280 and 274px at 900, with the clock digits
   unreadable underneath. Overlap is exactly how you make an overflow disappear from a
   `scrollWidth` check, so a fit assertion alone is not just incomplete — it goes green
   *because* of the regression. The second assertion is the one that has teeth.

   Scope, deliberately. Every width here is >= 760px. The sub-760px phone surface is a
   separate, still-open owner call (BACKLOG.md, "The phone surface"): the HUD has no
   stacked-layout breakpoint below 760px and this spec does not pretend it does. */
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
  });
});

/** Laptop widths spanning the old blow-out window (761–1080) and both sides of it. */
const WIDTHS = [1920, 1280, 900, 800] as const;

for (const width of WIDTHS) {
  test(`topbar fits and does not stack at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/v2', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
    // the overflow came from content-driven track sizing, so let the roster settle
    await page.waitForTimeout(600);

    const m = await page.evaluate(() => {
      const badges = document.querySelector('.brand .badges') as HTMLElement | null;
      const clock = document.querySelector('.clock') as HTMLElement | null;
      const cr = clock?.getBoundingClientRect();
      // Measure the PAINTED badges, not `.brand`: `.brand` is the grid item, so its rect
      // is the track box — which does shrink. What lands on the clock is the content
      // inside it, so an assertion on `.brand.right` silently passes the very regression
      // this exists to catch (verified: it did).
      let overlapPx: number | null = null;
      if (badges && cr && getComputedStyle(badges).display !== 'none') {
        overlapPx = -Infinity;
        for (const kid of Array.from(badges.children)) {
          const r = kid.getBoundingClientRect();
          if (r.width > 0) overlapPx = Math.max(overlapPx, Math.round(r.right - cr.left));
        }
        if (overlapPx === -Infinity) overlapPx = null;
      }
      return {
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        topbarTracks: getComputedStyle(document.querySelector('.topbar') as Element).gridTemplateColumns,
        // null when the clock or the strip is hidden — then there is nothing to overlap
        overlapPx,
      };
    });

    // 1) the page must fit its viewport: no clipped, unreachable content
    expect(
      m.scrollWidth,
      `the document is wider than the viewport at ${width}px (topbar tracks: ${m.topbarTracks}) — ` +
      'a flexible grid track is refusing to shrink below its min-content width',
    ).toBeLessThanOrEqual(m.clientWidth);

    // 2) …and it must not achieve that by putting the brand block on top of the clock
    if (m.overlapPx !== null) {
      expect(
        m.overlapPx,
        `the status badges overlap the clock by ${m.overlapPx}px at ${width}px — the topbar track ` +
        'shrank but its flex content did not reflow (needs min-width:0 + overflow on .badges)',
      ).toBeLessThanOrEqual(0);
    }
  });
}

for (const width of [320, 390]) {
  test(`vault passage and Send fit after resizing to ${width}px`, async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Chrome phone-width layout');
    const name = 'Project index summary #PRJ-642';
    const passage = 'The verification code is IRIS-9C0C-C28D.';
    await page.route('**/api/os/brain/retrieve*', route => route.fulfill({ json: {
      ok: true, attachments: [{ name, text: 'Compact project summary.' }],
      sources: { [name]: { vault: 'Test Vault', file: 'Projects/Lumen Passage.md', readable: true } },
    } }));
    await page.route('**/api/os/brain/note*', route => route.fulfill({ json: {
      ok: true, title: 'Lumen Passage', body: 'Orientation notes.\r\n'.repeat(100) + passage,
    } }));
    await page.route('**/memory', route => route.fulfill({ json: {
      session: 'layout-vault-session', turns: [],
    } }));
    await page.setViewportSize({ width: 1460, height: 1020 });
    await page.goto('/v2/');
    await page.waitForFunction(() => sessionStorage.getItem('nerva.chat.session_id') === 'layout-vault-session');
    const input = page.locator('.inputbar [data-composer]');
    await input.fill('For project PRJ-642, what is the Final calibration code?');
    await page.getByRole('button', { name: 'Find vault notes' }).click();
    const row = page.locator('.vault-review-note').filter({ hasText: name });
    await expect(row.getByRole('button', { name: 'Choose passage' })).toBeVisible();
    await page.setViewportSize({ width, height: 844 });
    await row.getByRole('button', { name: 'Choose passage' }).click();
    await row.getByRole('textbox', { name: /Select text from this note/ }).evaluate((field, text) => {
      const box = field as HTMLTextAreaElement;
      const start = box.value.indexOf(text);
      box.focus();
      box.setSelectionRange(start, start + text.length);
    }, passage);
    await row.getByRole('button', { name: 'Use selected passage' }).click();
    const preview = row.locator('.vault-passage-preview');
    await expect(preview).toContainText(passage);
    await preview.scrollIntoViewIfNeeded();
    const send = page.locator('.inputbar .transmit');
    const fit = await page.evaluate(() => {
      const send = document.querySelector('.inputbar .transmit') as HTMLElement;
      const preview = document.querySelector('.vault-passage-preview') as HTMLElement;
      const review = document.querySelector('.vault-review') as HTMLElement;
      const s = send.getBoundingClientRect();
      const p = preview.getBoundingClientRect();
      const r = review.getBoundingClientRect();
      const hit = document.elementFromPoint(s.x + s.width / 2, s.y + s.height / 2);
      return {
        sendRight: s.right, sendBottom: s.bottom, sendHit: hit === send || send.contains(hit),
        sendBox: [s.x, s.y, s.right, s.bottom], hitTitle: (hit as HTMLElement | null)?.title,
        previewInside: p.top >= r.top && p.bottom <= r.bottom,
        documentWidth: document.documentElement.scrollWidth,
      };
    });
    expect(fit.sendRight).toBeLessThanOrEqual(width);
    expect(fit.sendBottom).toBeLessThanOrEqual(844);
    expect(fit.sendHit, JSON.stringify(fit)).toBe(true);
    expect(fit.previewInside).toBe(true);
    expect(fit.documentWidth).toBeLessThanOrEqual(width);
    await send.click({ trial: true });
    await input.focus();
    for (let i = 0; i < 4 && !(await send.evaluate(el => el === document.activeElement)); i++) {
      await page.keyboard.press('Tab');
    }
    await expect(send).toBeFocused();
  });
}
