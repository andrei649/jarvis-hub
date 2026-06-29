/* HUD v2 · E2E smoke (H23.17). Drives the served /v2 bundle in real Chromium and
   proves what jsdom can't: the HUD mounts, the native Neural Mesh canvas actually
   PAINTS pixels (the v3 port that replaced the /brain iframe), and nothing throws an
   uncaught exception. A screenshot is captured as the human-reviewable artifact. */
import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';

test('HUD v2 boots, mounts, and the Neural Mesh paints — no uncaught errors', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (e) => pageErrors.push(String(e?.stack || e)));

  await page.goto('/v2', { waitUntil: 'domcontentloaded' });

  // 1) the React app mounted into #root
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });

  // 2) the cockpit's Neural Mesh canvas is present + visible (it replaced the iframe)
  const meshCanvas = page.locator('.nmesh canvas').first();
  await expect(meshCanvas).toBeVisible();

  // 3) give the requestAnimationFrame loop a moment to draw several frames
  await page.waitForTimeout(1800);

  // 4) THE proof jsdom can't give: the canvas backing store has non-blank pixels.
  //    The mesh draws only its own shapes (no cross-origin images) so getImageData
  //    is not tainted. Count pixels with any alpha — a blank/broken canvas → 0.
  const litPixels = await meshCanvas.evaluate((cv: HTMLCanvasElement) => {
    const ctx = cv.getContext('2d');
    if (!ctx || !cv.width || !cv.height) return -1;
    const { data } = ctx.getImageData(0, 0, cv.width, cv.height);
    let lit = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] > 8) lit++;
    return lit;
  });
  expect(litPixels, 'the Neural Mesh canvas should paint pixels, not be blank').toBeGreaterThan(100);

  // 5) artifact: a screenshot of the live cockpit for the human review pass
  mkdirSync('e2e/artifacts', { recursive: true });
  await page.screenshot({ path: 'e2e/artifacts/hud-cockpit.png' });

  // 6) the app must not have thrown an uncaught exception (failed API fetches are
  //    expected to degrade gracefully — those are console-level, not page errors)
  expect(pageErrors, `uncaught page errors:\n${pageErrors.join('\n')}`).toEqual([]);
});

test('Cinema mode (m) opens the full-bleed mesh and Esc closes it', async ({ page }) => {
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.nmesh canvas').first()).toBeVisible({ timeout: 20_000 });

  await page.keyboard.press('m');                       // hotkey → cinema overlay
  await expect(page.locator('.cinema')).toBeVisible();
  await expect(page.locator('.cinema .nmesh canvas')).toBeVisible();   // mesh embedded full-bleed
  await page.waitForTimeout(600);
  await page.screenshot({ path: 'e2e/artifacts/hud-cinema.png' });

  await page.keyboard.press('Escape');                  // Esc → exit
  await expect(page.locator('.cinema')).toHaveCount(0);
});
