/* HUD v2 · E2E smoke (H23.17). Drives the served /v2 bundle in real Chromium and
   proves what jsdom can't: the HUD mounts, the native Neural Mesh canvas actually
   PAINTS pixels (the v3 port that replaced the /brain iframe), and nothing throws an
   uncaught exception. A screenshot is captured as the human-reviewable artifact. */
import { test, expect } from '@playwright/test';

// The e2e backend boots with no model loaded, which (correctly) raises the
// first-run gate. These specs drive the cockpit as an already-onboarded user,
// so pre-seed the dismissal exactly as a returning user's browser carries it.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
  });
});
import { mkdirSync } from 'node:fs';

function sse(events: object[]): string {
  return events.map((evt) => `data: ${JSON.stringify(evt)}\n\n`).join('');
}

// Since the cutover (PHASE_B_PLAN.md §8.2 row 31) /v2 is Home in the Ledger frame: the day, the
// conversation and the docket. The Neural Mesh is drawn only in Cinema (`m`), so its paint proof
// moved into the Cinema test below.
test('HUD v2 boots into Home — the day, the conversation and the docket — with no uncaught errors', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (e) => pageErrors.push(String(e?.stack || e)));

  await page.goto('/v2', { waitUntil: 'domcontentloaded' });

  // 1) the React app mounted into #root, inside the Ledger frame
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
  await expect(page.locator('[data-frame="masthead"]')).toBeVisible({ timeout: 20_000 });

  // 2) Home's three registers are painted, the composer in the conversation's. The day is its
  //    register from 1680px and folds into the band below that (the browser matrix runs phone
  //    and laptop sizes), so whichever this width draws is the one that must be visible.
  for (const register of ['talk', 'docket']) {
    await expect(page.locator(`[data-home] [data-register="${register}"]`), `Home's ${register} register`).toBeVisible();
  }
  await expect(page.locator('[data-home] [data-register="day"]:visible, [data-home] [data-frame="dayband"]:visible').first(),
    'Home\'s day, as its register or its band').toBeVisible();
  await expect(page.locator('[data-home] [data-register="talk"] [data-composer]')).toBeVisible();
  // the mesh is Cinema's now, not Home's
  await expect(page.locator('[data-home] .nmesh')).toHaveCount(0);

  // 3) let the registers' first readings land (a failed API fetch degrades, it does not throw)
  await page.waitForTimeout(1200);

  // 4) artifact: a screenshot of Home for the human review pass
  mkdirSync('e2e/artifacts', { recursive: true });
  await page.screenshot({ path: 'e2e/artifacts/hud-cockpit.png' });

  // 5) the app must not have thrown an uncaught exception (failed API fetches are
  //    expected to degrade gracefully — those are console-level, not page errors)
  expect(pageErrors, `uncaught page errors:\n${pageErrors.join('\n')}`).toEqual([]);
});

test('Cinema mode (m) opens the full-bleed mesh, the mesh paints, and Esc closes it', async ({ page }) => {
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('[data-frame="masthead"]')).toBeVisible({ timeout: 20_000 });

  await page.keyboard.press('m');                       // hotkey → cinema overlay
  await expect(page.locator('.cinema')).toBeVisible();
  const meshCanvas = page.locator('.cinema .nmesh canvas').first();
  await expect(meshCanvas).toBeVisible();               // mesh embedded full-bleed

  // give the requestAnimationFrame loop a moment to draw several frames
  await page.waitForTimeout(1800);

  // THE proof jsdom can't give: the canvas backing store has non-blank pixels.
  // The mesh draws only its own shapes (no cross-origin images) so getImageData
  // is not tainted. Count pixels with any alpha — a blank/broken canvas → 0.
  const litPixels = await meshCanvas.evaluate((cv: HTMLCanvasElement) => {
    const ctx = cv.getContext('2d');
    if (!ctx || !cv.width || !cv.height) return -1;
    const { data } = ctx.getImageData(0, 0, cv.width, cv.height);
    let lit = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] > 8) lit++;
    return lit;
  });
  expect(litPixels, 'the Neural Mesh canvas should paint pixels in Cinema, not be blank').toBeGreaterThan(100);

  mkdirSync('e2e/artifacts', { recursive: true });
  await page.screenshot({ path: 'e2e/artifacts/hud-cinema.png' });

  await page.keyboard.press('Escape');                  // Esc → exit
  await expect(page.locator('.cinema')).toHaveCount(0);
  await expect(page.locator('[data-frame="masthead"]')).toBeVisible();
});

test('golden-signals /metrics stays available during the HUD soak', async ({ request }) => {
  const resp = await request.get('/metrics');
  expect(resp.status()).toBe(200);
  const body = await resp.text();
  for (const family of [
    'jarvis_http_requests_total',
    'jarvis_http_request_duration_seconds',
    'jarvis_http_errors_total',
    'jarvis_http_requests_in_flight',
  ]) {
    expect(body).toContain(family);
  }
});

test('chat flow renders SSE tokens and the final reply', async ({ page }) => {
  await page.route('**/chat/stream', async (route) => {
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
      body: sse([
        { type: 'start', agent: 'jarvis' },
        { type: 'token', text: 'hello ' },
        { type: 'token', text: 'from e2e' },
        { type: 'end', agent: 'jarvis', text: 'hello from e2e' },
      ]),
    });
  });
  await page.route('**/api/cognition', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        decision: { agents_selected: ['jarvis'], confidence: 0.9, source: 'e2e', timing: { total: 1 } },
        scoring: [],
        plugins: [],
        local: true,
      }),
    });
  });

  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });

  // The Ledger composer and transcript (PHASE_B_PLAN.md §8.2 row 32): data-composer is the field,
  // data-composer-send its Send; each turn carries data-turn and its words data-turn-body.
  await page.locator('[data-composer]').first().fill('hello jarvis');
  await page.locator('[data-composer-send]').first().click();

  await expect(page.locator('[data-turn="owner"] [data-turn-body]').filter({ hasText: 'hello jarvis' })).toBeVisible();
  await expect(page.locator('[data-turn="reply"] [data-turn-body]').filter({ hasText: 'hello from e2e' })).toBeVisible();
});

test('stop button aborts an in-flight chat stream', async ({ page }) => {
  await page.route('**/chat/stream', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    try {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
        body: sse([
          { type: 'start', agent: 'jarvis' },
          { type: 'token', text: 'late token' },
          { type: 'end', agent: 'jarvis', text: 'late token' },
        ]),
      });
    } catch {
      // The page intentionally aborts this request; route.fulfill can race that abort.
    }
  });

  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });

  await page.locator('[data-composer]').first().fill('please stop');
  await page.locator('[data-composer-send]').first().click();

  // the working reply's one control (§5.3): "Stop this reply", or "Stop the replies" with more in flight
  const stop = page.getByRole('button', { name: /^Stop (this reply|the replies)$/ });
  await expect(stop).toBeVisible();
  await stop.click();
  await expect(stop).toHaveCount(0);
});

test('voice push-to-talk captures STT text and drives a chat turn', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('hud.voice', JSON.stringify({
      mode: 'ptt',
      tts: 'off',
      lang: 'en',
      barge: 'off',
    }));

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => ({
          getTracks: () => [{ stop: () => undefined }],
        }),
      },
    });

    class FakeMediaRecorder {
      state = 'inactive';
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      static isTypeSupported() { return true; }
      start() {
        this.state = 'recording';
        setTimeout(() => {
          this.ondataavailable?.({ data: new Blob([new Uint8Array(4096)], { type: 'audio/webm' }) });
          this.stop();
        }, 120);
      }
      stop() {
        if (this.state === 'inactive') return;
        this.state = 'inactive';
        this.onstop?.();
      }
    }

    class FakeAudioContext {
      createMediaStreamSource() { return { connect: () => undefined }; }
      createAnalyser() {
        return {
          fftSize: 1024,
          getByteTimeDomainData: (buf: Uint8Array) => buf.fill(128),
        };
      }
      resume() { return Promise.resolve(); }
      close() { return Promise.resolve(); }
    }

    // @ts-expect-error test shim for browser APIs
    window.MediaRecorder = FakeMediaRecorder;
    // @ts-expect-error test shim for browser APIs
    window.AudioContext = FakeAudioContext;
  });

  await page.route('**/api/voice/capabilities', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ stt: true, tts: true }) });
  });
  await page.route('**/api/voice/stt?**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ text: 'voice hello' }) });
  });
  await page.route('**/chat/stream', async (route) => {
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
      body: sse([
        { type: 'start', agent: 'jarvis' },
        { type: 'token', text: 'voice reply' },
        { type: 'end', agent: 'jarvis', text: 'voice reply from e2e' },
      ]),
    });
  });
  await page.route('**/api/cognition', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ decision: { agents_selected: ['jarvis'], confidence: 0.9 }, scoring: [] }),
    });
  });

  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });

  // the composer bar's Voice control keeps its "push-to-talk" title (§8.2 row 32)
  await page.locator('[data-composer-bar] button[title*="push-to-talk"]').first().click();

  await expect(page.locator('[data-turn="owner"] [data-turn-body]').filter({ hasText: 'voice hello' })).toBeVisible();
  await expect(page.locator('[data-turn="reply"] [data-turn-body]').filter({ hasText: 'voice reply from e2e' })).toBeVisible();
});
