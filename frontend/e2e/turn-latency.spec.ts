import { expect, test } from '@playwright/test';

// Real compiled HUD with a fixture SSE server response; backend tests separately
// verify the orchestrator clock and wire projection. No inference or credentials.
for (const width of [1280, 390]) {
  test(`current turn duration survives layout but not reload at ${width}px`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem('hud.firstrun.dismissed', '1'));
    const errors: string[] = [];
    let calls = 0;
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin === new URL(baseURL!).origin && url.pathname.startsWith('/v2/')) {
        return route.continue();
      }
      if (url.pathname === '/chat/stream') {
        calls++;
        const end = { type: 'end', agent: 'jarvis', text: `Reply ${calls}.`,
          outcome: calls === 1 ? { latency_ms: 1250 } : null };
        return route.fulfill({ contentType: 'text/event-stream', body:
          'data: {"type":"start","agent":"jarvis"}\n\n' + `data: ${JSON.stringify(end)}\n\n` });
      }
      return route.fulfill({ json: {} });
    });
    await page.goto('/v2/chat?demo=1');
    const strip = page.getByLabel('Turn duration', { exact: true });
    await expect(strip).toHaveCount(0);
    const send = async (text: string) => {
      await page.locator('.inputbar input').first().fill(text);
      await page.getByRole('button', { name: 'TRANSMIT', exact: true }).click();
    };
    await send('Measure this turn');
    await expect(page.getByText('Reply 1.', { exact: true })).toBeVisible();
    await expect(strip).toBeVisible();
    await expect(strip).toContainText('1.25');
    const box = await strip.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
    await page.screenshot({ path: testInfo.outputPath('turn-duration.png') });
    await send('No timing data');
    await expect(page.getByText('Reply 2.', { exact: true })).toBeVisible();
    await expect(strip).toHaveCount(0);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.inputbar')).toBeVisible();
    await expect(strip).toHaveCount(0);
    expect(calls).toBe(2);
    expect(errors).toEqual([]);
  });
}
