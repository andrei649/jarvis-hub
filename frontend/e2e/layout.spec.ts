/* HUD v2 · frame layout fit (H23.17 tail; rewritten for the Ledger frame at the cutover,
   PHASE_B_PLAN.md §8.2 row 25). Proves the frame neither overflows its viewport nor solves that
   by stacking its own content at ordinary widths — the thing jsdom/vitest cannot check, because
   it needs real layout and real painted geometry.

   What is asserted, at 2560 / 1920 / 1280 / 900 / 800px:
   1) no horizontal overflow: the document is no wider than the viewport. `body{overflow:hidden}`
      would clip the excess with no scrollbar — unreachable, which is worse than scrolling;
   2) the running head's eight items (six trust signals, the approval mode, the interrupts) are all
      painted, inside the viewport, and none sits on another. Between 760 and 1099px they may wrap
      to two lines (§4.2); from 1100px up they share one;
   3) the masthead's parts — the brand, the nine areas, Find and the tools — do not overlap, and
      every area link is painted inside both the viewport and its own strip. Below 1100px the
      areas take a second row that scrolls sideways when the nine do not fit (frame.css), so
      there a link past the row's edge is reachable by scrolling and is not counted as cut.

   Why the overlap assertions sit beside the fit assertion. The classic topbar taught it: the
   obvious fix for an overflow (a track allowed to shrink) passed `scrollWidth` while the track's
   flex content spilled over its neighbour — 109px at 1280, 274px at 900, the clock unreadable
   underneath. Overlap is exactly how an overflow disappears from a `scrollWidth` check, so a fit
   assertion alone goes green *because* of the regression; the overlap checks have the teeth.

   Scope, deliberately. Every width here is >= 760px, where the masthead docks its areas; below
   that they move into the drawer (frame/AreaDrawer, which has its own tests). The sub-760px phone
   surface is a separate, still-open owner call (BACKLOG.md, "The phone surface"). */
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); localStorage.setItem('hud.seen', '1'); } catch { /* ignore */ }
  });
});

/** The owner's 2560, the common desktop and laptop widths, and the old blow-out window (761–1080). */
const WIDTHS = [2560, 1920, 1280, 900, 800] as const;

for (const width of WIDTHS) {
  test(`the frame fits and does not stack at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width >= 2560 ? 1353 : 800 });
    await page.goto('/v2', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
    await expect(page.locator('[data-frame="masthead"]')).toBeVisible({ timeout: 20_000 });
    await expect(page.locator('[data-frame="runhead"]')).toBeVisible();
    // the running head's words change as each reading's first answer lands: let them settle
    await page.waitForTimeout(800);

    const m = await page.evaluate(() => {
      type Box = { id: string; left: number; right: number; top: number; bottom: number; width: number; height: number };
      const box = (id: string, el: Element): Box => {
        const r = el.getBoundingClientRect();
        return { id, left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
      };
      const drawn = (b: Box) => b.width > 0 && b.height > 0;
      const overlaps = (boxes: Box[]) => {
        const out: string[] = [];
        for (let i = 0; i < boxes.length; i++) {
          for (let j = i + 1; j < boxes.length; j++) {
            const a = boxes[i];
            const b = boxes[j];
            const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
            const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
            if (x > 0.5 && y > 0.5) out.push(`${a.id} overlaps ${b.id} by ${Math.round(x)}x${Math.round(y)}px`);
          }
        }
        return out;
      };
      const vw = document.documentElement.clientWidth;
      const outside = (b: Box) => b.left < -0.5 || b.right > vw + 0.5;

      // the running head's eight items
      const head = document.querySelector('[data-frame="runhead"]');
      const items = head
        ? Array.from(head.querySelectorAll('[data-signal], [data-runhead="mode"], [data-runhead="interrupts"]'))
          .map((el) => box(el.getAttribute('data-signal') || el.getAttribute('data-runhead') || '?', el))
        : [];
      const painted = items.filter(drawn);
      // lines: items whose vertical middles lie within half the shortest item's height share one
      const middles = painted.map((b) => b.top + b.height / 2).sort((a, b) => a - b);
      const half = painted.length ? Math.min(...painted.map((b) => b.height)) / 2 : 0;
      let lines = middles.length ? 1 : 0;
      for (let i = 1; i < middles.length; i++) if (middles[i] - middles[i - 1] > half) lines += 1;

      // the masthead: its four parts, and the area links inside their strip
      const mast = document.querySelector('[data-frame="masthead"]');
      const parts = mast
        ? ['brand', 'areas', 'find', 'tools']
          .map((name) => { const el = mast.querySelector(`.n-masthead__${name}`); return el ? box(name, el) : null; })
          .filter((b): b is Box => !!b && drawn(b))
        : [];
      const strip = parts.find((b) => b.id === 'areas') ?? null;
      const stripEl = mast?.querySelector<HTMLElement>('.n-masthead__areas') ?? null;
      // below 1100px the areas take the masthead's second row, which scrolls sideways when the
      // nine do not fit (frame.css): a link past its edge is then reached by scrolling the row
      const stripScrolls = !!stripEl && /auto|scroll/.test(getComputedStyle(stripEl).overflowX) && stripEl.scrollWidth > stripEl.clientWidth + 1;
      const links = mast ? Array.from(mast.querySelectorAll('.n-masthead__areas a[data-area]')).map((el) => box(el.getAttribute('data-area') || '?', el)) : [];

      return {
        scrollWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
        clientWidth: vw,
        items: items.length,
        undrawn: items.filter((b) => !drawn(b)).map((b) => b.id),
        cut: painted.filter(outside).map((b) => `${b.id} ${Math.round(b.left)}..${Math.round(b.right)} of ${vw}`),
        itemOverlaps: overlaps(painted),
        lines,
        parts: parts.map((b) => b.id),
        partOverlaps: overlaps(parts),
        links: links.length,
        linksUndrawn: links.filter((b) => !drawn(b)).map((b) => b.id),
        stripScrolls,
        linksCut: stripScrolls ? [] : links.filter((b) => drawn(b) && (outside(b)
          || (strip !== null && (b.left < strip.left - 0.5 || b.right > strip.right + 0.5)))).map((b) => b.id),
      };
    });

    // 1) the page must fit its viewport: no clipped, unreachable content
    expect(m.scrollWidth, `the document is wider than the viewport at ${width}px`).toBeLessThanOrEqual(m.clientWidth);

    // 2) the running head: all eight items painted, on screen, and none on top of another
    expect(m.items, 'the running head holds its eight items').toBe(8);
    expect(m.undrawn, `running-head items not painted at ${width}px`).toEqual([]);
    expect(m.cut, `running-head items cut by the viewport at ${width}px`).toEqual([]);
    expect(m.itemOverlaps, `running-head items stacked on each other at ${width}px`).toEqual([]);
    if (width >= 1100) expect(m.lines, `the running head wraps at ${width}px; it keeps one line from 1100px up`).toBe(1);

    // 3) the masthead: brand, areas, Find and tools apart; every area docked and painted, and
    //    whole on screen — from 1100px in its one row; narrower, in a second row that scrolls
    //    sideways when the nine do not fit, never clipped without a way to reach them
    expect(m.parts, 'the masthead draws its brand, its areas, Find and its tools').toEqual(['brand', 'areas', 'find', 'tools']);
    expect(m.partOverlaps, `masthead parts overlap at ${width}px`).toEqual([]);
    expect(m.links, 'the masthead docks the nine areas').toBe(9);
    expect(m.linksUndrawn, `area links not painted at ${width}px`).toEqual([]);
    if (width >= 1100) expect(m.stripScrolls, `the areas no longer fit their row at ${width}px`).toBe(false);
    expect(m.linksCut, `area links cut by the viewport or their strip at ${width}px`).toEqual([]);
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
    const input = page.locator('[data-composer]');
    await input.fill('For project PRJ-642, what is the Final calibration code?');
    // Vault notes is in the composer's Attach menu since the re-lay (PHASE_B_PLAN.md §5.3); choosing it closes the menu
    await page.locator('[data-talk-menu="attach"] > button').click();
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
    const send = page.locator('[data-composer-send]');
    // Below 1100px Home is one column and the page scrolls as a whole (home.css; PHASE_B_PLAN.md
    // §5.1): Send is no longer the classic bar pinned under the review. Where it sits after the
    // preview's own scroll depends on the scroll the passage chooser left behind, so measured as
    // it stood this was flaky (Send under the running foot on 2 of 6 runs at 320px). The owner
    // scrolls on until Send shows — a 'nearest' scroll, as reachability.spec.ts brings the bar into
    // view — and the passage must still be on screen beside it: the passage and its Send together.
    await send.evaluate((el) => el.scrollIntoView({ block: 'nearest', inline: 'nearest' }));
    const fit = await page.evaluate(() => {
      const send = document.querySelector('[data-composer-send]') as HTMLElement;
      const preview = document.querySelector('.vault-passage-preview') as HTMLElement;
      const review = document.querySelector('.vault-review') as HTMLElement;
      const body = document.querySelector('[data-frame="page"]') as HTMLElement;
      const s = send.getBoundingClientRect();
      const p = preview.getBoundingClientRect();
      const r = review.getBoundingClientRect();
      const b = body.getBoundingClientRect();
      const hit = document.elementFromPoint(s.x + s.width / 2, s.y + s.height / 2);
      return {
        sendRight: s.right, sendBottom: s.bottom, sendHit: hit === send || send.contains(hit),
        sendBox: [s.x, s.y, s.right, s.bottom], hitTitle: (hit as HTMLElement | null)?.title,
        previewInside: p.top >= r.top && p.bottom <= r.bottom,
        // the preview is in the page's visible area (under the running head, above the running foot)
        previewOnScreen: p.top >= b.top - 0.5 && p.bottom <= b.bottom + 0.5 && p.bottom <= window.innerHeight + 0.5,
        previewBox: [p.top, p.bottom], pageBox: [b.top, b.bottom],
        documentWidth: document.documentElement.scrollWidth,
      };
    });
    expect(fit.sendRight).toBeLessThanOrEqual(width);
    expect(fit.sendBottom).toBeLessThanOrEqual(844);
    expect(fit.sendHit, JSON.stringify(fit)).toBe(true);
    expect(fit.previewInside).toBe(true);
    expect(fit.previewOnScreen, JSON.stringify(fit)).toBe(true);
    expect(fit.documentWidth).toBeLessThanOrEqual(width);
    await send.click({ trial: true });
    await input.focus();
    for (let i = 0; i < 4 && !(await send.evaluate(el => el === document.activeElement)); i++) {
      await page.keyboard.press('Tab');
    }
    await expect(send).toBeFocused();
  });
}
