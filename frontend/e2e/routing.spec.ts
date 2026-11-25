/* The served HUD's routes, in the Ledger frame since the cutover (PHASE_B_PLAN.md §8.3 app-routing,
   §8.2 rows 36–37). Every API answer is stubbed: the bundle's own routing, history and lazy chunks
   are under test, and nothing is written to the hub.

   1) Bookmarks, reload, history, focus and lazy chunks: Home is Today; a Console panel opens as a
      page of its area (from the search sheet, which works at every width) and moves the focus to
      its heading, on load and on reload; the `gap` chunk is fetched only when a panel page needs
      it; All pages is an ordinary page Back and Forward walk through; an unknown URL returns to
      Today with an alert.
   2) Home at 1280/1440/1680/1920 (row 37): the docket is at least 480px wide and inside the
      viewport, every entry's sign control can be reached (scrolled to inside the docket, nothing
      covers its centre) and the open entry's signature line is fully visible; the composer's
      textarea is at least 320px wide and its five visible controls (To, Attach, Voice, Options,
      Send) sit inside the composer; a panel page lays its contents column and its body inside
      the viewport. */
import { expect, test, type Page } from '@playwright/test';

/** The masthead's Find opens the search and command sheet; its name begins with the words it shows. */
async function runFromSheet(page: Page, query: string, command: string) {
  await page.getByRole('button', { name: /^Search or run a command/ }).click();
  const sheet = page.getByRole('dialog', { name: 'Search or run a command' });
  await expect(sheet).toBeVisible();
  await sheet.getByRole('combobox').fill(query);
  await sheet.locator(`[data-command="${command}"]`).click();
  await expect(sheet).toHaveCount(0);
}

test('bookmarks, reload, history, focus and lazy chunks on the served HUD', async ({ page, baseURL }, testInfo) => {
  const errors: string[] = [];
  const writes: string[] = [];
  const loaded: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.url().includes('/v2/assets/')) loaded.push(request.url()); });
  await page.route('**/*', route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === new URL(baseURL!).origin && url.pathname.startsWith('/v2/')) return route.continue();
    // Analytics is a pageview beacon, never a business mutation.
    if (request.method() !== 'GET' && !url.pathname.includes('analytics')) writes.push(request.method() + ' ' + url.pathname);
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  await page.goto('/v2/cockpit?demo=1#anchor');
  await expect(page).toHaveTitle('Today · Nerva');
  await expect(page.locator('[data-frame="masthead"]')).toBeVisible();
  // the retired CONSOLE button's place: Find, which opens every panel
  await expect(page.getByRole('button', { name: /^Search or run a command/ })).toBeVisible();
  expect(loaded.some(url => /\/gap-/.test(url))).toBe(false);

  await runFromSheet(page, 'decisions', 'page:panel:decision-inbox');
  await expect(page).toHaveURL(/\/v2\/console\/decision-inbox\?demo=1(#anchor)?$/);
  await expect(page).toHaveTitle('Decisions · Work · Nerva');
  const heading = page.locator('[data-frame="page"]').getByRole('heading', { level: 1, name: 'Decisions', exact: true });
  await expect(heading).toBeFocused();
  // the masthead marks the panel's area, the contents column the panel
  await expect(page.locator('[data-frame="masthead"] a[data-area="work"]')).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('[data-frame="contents"] a[data-page="panel:decision-inbox"]')).toHaveAttribute('aria-current', 'page');
  expect(loaded.some(url => /\/gap-/.test(url))).toBe(true);
  await page.reload();
  await expect(heading).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath('console-bookmark.png') });

  await runFromSheet(page, 'all pages', 'page:allPages');
  await expect(page).toHaveURL(/\/v2\/console\?demo=1(#anchor)?$/);
  await expect(page).toHaveTitle('All pages · Nerva');
  await expect(page.locator('[data-frame="allpages"]')).toBeVisible();
  await page.goBack();
  await expect(page).toHaveTitle('Decisions · Work · Nerva');
  await page.goForward();
  await expect(page).toHaveTitle('All pages · Nerva');
  await page.goto('/v2/does-not-exist?demo=1');
  await expect(page).toHaveURL(/\/v2\/cockpit\?demo=1$/);
  await expect(page.getByRole('alert').filter({ hasText: 'Page not found' })).toBeVisible();
  expect(errors).toEqual([]);
  expect(writes).toEqual([]);
});

/** A box inside the viewport (CSS px), with a little tolerance for subpixel edges. */
function within(box: { x: number; y: number; width: number; height: number }, width: number, height: number) {
  return box.width > 0 && box.height > 0 && box.x >= -0.5 && box.y >= -0.5 && box.x + box.width <= width + 0.5 && box.y + box.height <= height + 0.5;
}

for (const width of [1280, 1440, 1680, 1920]) {
  test(`Home fits ${width}px: the docket signable, the composer whole, a panel page in its area`, async ({ page, baseURL }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'Explicit desktop grid widths');
    const height = 900;
    await page.setViewportSize({ width, height });
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      return url.origin === new URL(baseURL!).origin && url.pathname.startsWith('/v2/')
        ? route.continue() : route.fulfill({ json: {} });
    });

    // demo: the docket holds the sample's entries (every decision control disabled, as demo requires)
    await page.goto('/v2/cockpit?demo=1');
    const docket = page.locator('[data-register="docket"]');
    await expect(docket).toBeVisible();
    const entries = docket.locator('[data-docket-entry]');
    await expect(entries.first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);

    // the docket: at least 480px wide, inside the viewport
    const d = (await docket.boundingBox())!;
    expect(d.width, `the docket is ${Math.round(d.width)}px wide at ${width}px`).toBeGreaterThanOrEqual(480);
    expect(within(d, width, height), `the docket leaves the viewport at ${width}px: ${JSON.stringify(d)}`).toBe(true);

    // the open entry's signature line, fully visible
    const signLine = docket.locator('[data-phrase]').first();
    if (await signLine.count()) {
      const box = await signLine.boundingBox();
      expect(box && within(box, width, height), `the open entry's signature line is not fully visible at ${width}px`).toBe(true);
    }
    // every other entry's own sign control: scrolled to inside the docket, nothing covers its centre
    // (a click needs an enabled control, and demo disables them, so the check is what a click would reach)
    const count = await entries.count();
    let checked = 0;
    for (let i = 0; i < count; i++) {
      const control = entries.nth(i).locator('[data-verb="sign"], [data-verb="open"], [data-verb="openInDecisions"]').first();
      if (!(await control.count())) continue;
      await control.scrollIntoViewIfNeeded();
      const reached = await control.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        const inView = r.width > 0 && r.height > 0 && r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight;
        return inView && !!at && (at === el || el.contains(at));
      });
      expect(reached, `entry ${i + 1}'s sign control is covered or off screen at ${width}px`).toBe(true);
      checked++;
    }
    expect(checked + (await signLine.count()), 'the docket draws a way to sign its entries').toBeGreaterThan(0);

    // the composer: the textarea at least 320px wide, and its five visible controls inside it
    const composer = page.locator('[data-register="talk"] [data-composer-frame]');
    await expect(composer).toBeVisible();
    const c = (await composer.boundingBox())!;
    expect(within(c, width, height), `the composer leaves the viewport at ${width}px`).toBe(true);
    const field = (await page.locator('[data-register="talk"] [data-composer]').boundingBox())!;
    expect(field.width, `the message box is ${Math.round(field.width)}px wide at ${width}px`).toBeGreaterThanOrEqual(320);
    const controls: Record<string, string> = {
      to: '[data-recipient]',
      attach: '[data-composer-bar] [data-talk-menu="attach"] > button',
      voice: '[data-composer-bar] > button[aria-pressed]',
      options: '[data-composer-bar] [data-talk-menu="options"] > button',
      send: '[data-composer-send]',
    };
    for (const [name, selector] of Object.entries(controls)) {
      const control = composer.locator(selector).first();
      await expect(control, `the composer's ${name}`).toBeVisible();
      const box = (await control.boundingBox())!;
      expect(box.x >= c.x - 0.5 && box.x + box.width <= c.x + c.width + 0.5 && box.y >= c.y - 0.5 && box.y + box.height <= c.y + c.height + 0.5,
        `the composer's ${name} sits outside the composer at ${width}px: ${JSON.stringify({ box, composer: c })}`).toBe(true);
    }
    await page.screenshot({ path: testInfo.outputPath('cockpit-width.png') });

    // a panel page: its area's contents column and its body, inside the viewport
    await page.goto('/v2/console/media-gallery?demo=1');
    await expect(page).toHaveTitle('Media gallery · Build · Nerva');
    const contents = page.locator('[data-frame="contents"]');
    await expect(contents).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const cc = (await contents.boundingBox())!;
    expect(cc.x).toBeGreaterThanOrEqual(0);
    expect(cc.x + cc.width).toBeLessThanOrEqual(width);
    const body = (await page.locator('[data-frame="page"] [data-panel="media-gallery"]').boundingBox())!;
    expect(body.width, `the panel's body is ${Math.round(body.width)}px wide at ${width}px`).toBeGreaterThan(300);
    expect(body.x + body.width).toBeLessThanOrEqual(width);
    await page.screenshot({ path: testInfo.outputPath('grid-width.png') });
  });
}
