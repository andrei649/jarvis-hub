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
      await page.locator('[data-composer]').first().fill(text);
      await page.getByRole('button', { name: 'Send', exact: true }).click();
    };
    await send('Measure this turn');
    await expect(page.getByText('Reply 1.', { exact: true })).toBeVisible();
    // The Ledger reply (PHASE_B_PLAN.md §5.3): the turn's status lines, the duration among them,
    // are that reply's "Turn details", behind its More menu, not a strip under the composer.
    const reply = (text: string) => page.locator('[data-turn="reply"]').filter({ hasText: text });
    await expect(strip).toHaveCount(0);
    await reply('Reply 1.').getByRole('button', { name: 'More actions for this reply', exact: true }).click();
    await reply('Reply 1.').getByRole('button', { name: 'Turn details', exact: true }).click();
    await expect(strip).toBeVisible();
    await expect(strip).toContainText('1.25');
    await expect(reply('Reply 1.').getByLabel('Turn duration', { exact: true })).toBeVisible();
    const box = await strip.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
    await page.screenshot({ path: testInfo.outputPath('turn-duration.png') });
    await send('No timing data');
    await expect(page.getByText('Reply 2.', { exact: true })).toBeVisible();
    await expect(strip).toHaveCount(0);
    // the new turn reported no timing, so its reply offers no Turn details at all
    await expect(reply('Reply 2.').locator('[data-act="details"]')).toHaveCount(0);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-composer-bar]')).toBeVisible();
    await expect(strip).toHaveCount(0);
    await expect(page.locator('[data-act="details"]')).toHaveCount(0);
    expect(calls).toBe(2);
    expect(errors).toEqual([]);
  });
}
