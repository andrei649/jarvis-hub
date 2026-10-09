import { expect, test } from '@playwright/test';

const failure = 'Provider response failed; no usable image was verified. Check this task before proposing another.';
const uncertain = 'Result uncertain. Check the task before making another proposal; generation may have started.';

// Production assets/navigation with fixture API responses. Backend tests prove
// which persisted producer envelopes may yield failed, including ready recovery.
for (const width of [1280, 390]) {
  test(`failed image response remains distinct after reload at ${width}px`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem('hud.firstrun.dismissed', '1');
      localStorage.setItem('hud.admin_token', 'image-failure-browser-fixture');
    });
    const writes: string[] = [];
    const pngReads: string[] = [];
    const errors: string[] = [];
    const credentials: string[] = [];
    let state: 'failed' | 'uncertain' = 'failed';
    let reads = 0;
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin === new URL(baseURL!).origin && url.pathname.startsWith('/v2/')) {
        return route.continue();
      }
      if (request.method() !== 'GET' && !url.pathname.includes('analytics')) {
        writes.push(request.method() + ' ' + url.pathname);
      }
      if (url.pathname === '/api/media') {
        return route.fulfill({ json: { local_image: {
          configured: true, local: true, approval_required: true, reachable: null,
        } } });
      }
      if (url.pathname === '/api/media/generation-tasks/17') {
        reads++;
        credentials.push(request.headers()['x-admin-token']);
        return route.fulfill({ json: { task_id: 17, state, artifact: null } });
      }
      if (url.pathname.startsWith('/api/media/generated/')) pngReads.push(url.pathname);
      return route.fulfill({ json: {} });
    });

    await page.goto('/v2/console/images?demo=1&image_task=17');
    await expect(page.getByText(failure, { exact: true })).toBeVisible();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByText(failure, { exact: true })).toBeVisible();
    const panel = page.locator('.panel').filter({ has: page.getByText('IMAGES', { exact: true }) });
    await expect(panel.getByRole('img', { name: 'Generated image' })).toHaveCount(0);
    await expect(panel.getByRole('link', { name: 'Download PNG' })).toHaveCount(0);
    await expect(panel.getByText(uncertain, { exact: true })).toHaveCount(0);
    await panel.screenshot({ path: testInfo.outputPath('image-response-failed.png') });

    state = 'uncertain';
    await panel.getByRole('button', { name: 'Check status', exact: true }).click();
    await expect(panel.getByText(uncertain, { exact: true })).toBeVisible();
    await expect(panel.getByText(failure, { exact: true })).toHaveCount(0);
    state = 'failed';
    await panel.getByRole('button', { name: 'Check status', exact: true }).click();
    await expect(panel.getByText(failure, { exact: true })).toBeVisible();
    const manualReads = reads;
    // A terminal failed response must not retain the 1.5-second active-task poll.
    await page.waitForTimeout(1700);
    expect(reads).toBe(manualReads);
    expect(reads).toBe(4);
    expect(credentials.every(value => value === 'image-failure-browser-fixture')).toBe(true);
    expect(writes).toEqual([]);
    expect(pngReads).toEqual([]);
    expect(errors).toEqual([]);
    const bounds = await panel.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
  });
}
