import { expect, test } from '@playwright/test';

test('finds older retained media through an empty scan and exports the explicit selection', async ({ page }) => {
  await page.goto('/v2/console/media-gallery?demo=1');
  await expect(page.getByText('recent fixture 219', { exact: true })).toBeVisible();
  await expect(page.getByText(/220 retained/)).toBeVisible();
  await page.getByLabel('Search media', { exact: true }).fill('browser needle');
  await expect(page.getByText('No matches in the scanned range. Continue search to check older media.')).toBeVisible();
  await page.getByRole('button', { name: 'Continue search', exact: true }).click();
  await expect(page.getByText('oldest browser needle', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Continue search', exact: true })).toHaveCount(0);
  await page.getByLabel('Select md-000000000000', { exact: true }).check();
  const response = page.waitForResponse(r => r.url().endsWith('/api/media/export') && r.request().method() === 'POST');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export selected media (1)', exact: true }).click();
  const exported = await response;
  expect(exported.status()).toBe(200);
  expect(exported.request().postDataJSON()).toEqual({ ids: ['md-000000000000'] });
  expect(exported.headers()['content-type']).toContain('application/zip');
  await download;
  await page.getByLabel('Search media', { exact: true }).fill('recent fixture');
  await expect(page.getByRole('button', { name: 'Export selected media (0)', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
