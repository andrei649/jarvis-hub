import { expect, test } from '@playwright/test';

// Real production assets and browser navigation; status responses are fixtures.
// Queue verification and authentication are exercised by backend HTTP tests.
for (const width of [1280, 390]) {
  test(`mediation state survives hard reload and hides unavailable counts at ${width}px`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem('hud.firstrun.dismissed', '1');
      localStorage.setItem('hud.admin_token', 'mediation-browser-fixture');
    });
    const writes: string[] = [];
    const errors: string[] = [];
    const credentials: string[] = [];
    let mode = 'off';
    let valid = true;
    let status = 200;
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
      if (url.pathname === '/autonomy/mediation') {
        credentials.push(request.headers()['x-admin-token']);
        return route.fulfill({ status, json: status === 200 ? {
          mode, valid, stats: valid ? {
            authorized_enqueue: 12, governed: 7, refused_unmediated: 3, ungoverned_detected: 1,
          } : null,
        } : { error: 'mediation status unavailable' } });
      }
      return route.fulfill({ json: {} });
    });

    await page.goto('/v2/console/autonomy-control?demo=1');
    const section = page.getByRole('region', { name: 'Task mediation', exact: true });
    const panel = page.locator('.panel').filter({ has: section });
    for (mode of ['off', 'hold', 'enforce']) {
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(section.getByText(`Effective mode: ${mode}`, { exact: true })).toBeVisible();
      await expect(section.getByText('Evidence: verified', { exact: true })).toBeVisible();
      await expect(section.getByText('Authorized enqueue events: 12', { exact: true })).toBeVisible();
      await expect(section.getByText('Governed events: 7', { exact: true })).toBeVisible();
      await expect(section.getByText('Refused unmediated events: 3', { exact: true })).toBeVisible();
      await expect(section.getByText('Ungoverned events detected: 1', { exact: true })).toBeVisible();
    }
    await section.screenshot({ path: testInfo.outputPath('mediation-verified.png') });

    valid = false;
    await panel.getByRole('button', { name: 'Reload', exact: true }).click();
    await expect(section.getByText('Evidence: unavailable or invalid', { exact: true })).toBeVisible();
    await expect(section.getByText(/events:/)).toHaveCount(0);
    await expect(section.getByText(/events detected:/)).toHaveCount(0);
    status = 503;
    await panel.getByRole('button', { name: 'Reload', exact: true }).click();
    await expect(section.getByText('Mediation status unavailable', { exact: true })).toBeVisible();
    await expect(section.getByText(/Effective mode:|Evidence:|events:/)).toHaveCount(0);
    await section.screenshot({ path: testInfo.outputPath('mediation-unavailable.png') });

    expect(credentials.length).toBeGreaterThanOrEqual(5);
    expect(credentials.every(value => value === 'mediation-browser-fixture')).toBe(true);
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
    await expect(section.getByRole('button')).toHaveCount(0);
    const bounds = await section.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
  });
}
