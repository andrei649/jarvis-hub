import { expect, test } from '@playwright/test';

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
  await expect(page).toHaveTitle('Cockpit · Nerva');
  await expect(page.getByTitle('console (`)')).toBeVisible();
  expect(loaded.some(url => /\/gap-/.test(url))).toBe(false);
  await page.getByTitle('console (`)').click();
  await page.getByRole('link', { name: 'Decision Inbox', exact: true }).click();
  await expect(page).toHaveURL(/\/v2\/console\/decision-inbox\?demo=1#anchor$/);
  await expect(page).toHaveTitle('Decision Inbox · Console · Nerva');
  await expect(page.getByRole('heading', { name: 'Decision Inbox', exact: true })).toBeFocused();
  expect(loaded.some(url => /\/gap-/.test(url))).toBe(true);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Decision Inbox', exact: true })).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath('console-bookmark.png') });
  await page.getByRole('link', { name: 'All console panels' }).click();
  await page.goBack();
  await expect(page).toHaveTitle('Decision Inbox · Console · Nerva');
  await page.goForward();
  await expect(page).toHaveTitle('Console · Nerva');
  await page.goto('/v2/does-not-exist?demo=1');
  await expect(page).toHaveURL(/\/v2\/cockpit\?demo=1$/);
  await expect(page.getByRole('alert').filter({ hasText: 'Page not found' })).toBeVisible();
  expect(errors).toEqual([]);
  expect(writes).toEqual([]);
});

for (const width of [1101, 1280, 1440]) {
  test(`HUD grid fits ${width}px without clipping its context column`, async ({page, baseURL}, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'Explicit desktop grid widths');
    await page.setViewportSize({width, height:900});
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      return url.origin === new URL(baseURL!).origin && url.pathname.startsWith('/v2/')
        ? route.continue() : route.fulfill({json:{}});
    });
    for (const path of ['/v2/cockpit', '/v2/console/media-gallery']) {
      await page.goto(path);
      await expect(page.locator('.workzone.cockpit')).toBeVisible();
      if (path.includes('/console/')) await expect(page).toHaveTitle(/Media Gallery.*Console/);
      else {
        const bar = page.locator('.workzone.cockpit .inputbar');
        const bounds = await bar.boundingBox();
        for (const control of await bar.locator('button,input').all()) {
          const box = await control.boundingBox();
          expect(box!.x + box!.width).toBeLessThanOrEqual(bounds!.x + bounds!.width);
        }
        expect((await bar.locator('input').boundingBox())!.width).toBeGreaterThanOrEqual(100);
        await page.screenshot({path:testInfo.outputPath('cockpit-width.png')});
      }
      await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      const geometry = await page.locator('.workzone.cockpit .scrollcol').boundingBox();
      expect(geometry).not.toBeNull();
      expect(geometry!.x + geometry!.width).toBeLessThanOrEqual(width);
      expect(geometry!.width).toBeGreaterThan(300);
    }
    await page.screenshot({path:testInfo.outputPath('grid-width.png')});
  });
}
