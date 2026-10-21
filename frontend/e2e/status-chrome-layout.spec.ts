/* HUD v2 · H133 status-chrome geometry. The live status chrome (GATEWAY / SESSIONS badges in
   the top bar, the gateway dot in the rail) only counts as delivered if the owner can SEE it
   on an ordinary screen — and a DOM-presence check in jsdom cannot tell, because jsdom has no
   layout. This spec measures painted rects in a real Chromium.

   What went wrong first. `.brand .badges` is `justify-content:flex-end; overflow:hidden`, so
   every badge added to the strip pushed the LEFTMOST ones out of the clip box. Adding three
   badges hid AGENTS + LLM at 1680x1050 and AGENTS + LLM + DATA + GATEWAY at 1366x768 — the
   model and data-provenance badges vanished at exactly the laptop widths owners use. And the
   rail's gateway dot sat after `.rail-spacer` at the bottom of 17 rail buttons, at y~870 —
   below the fold of a 768px-tall screen, in a body with `overflow:hidden`.

   The contract asserted here:
   1) at 1920x1080, 1536x864, 1440x900 and 1366x768 the LLM, DATA and GATEWAY badges — and the EGRESS /
      MIC trust pair the strip already showed there — are painted fully inside the
      `.brand .badges` clip box: no low-priority badge may evict them;
   2) a badge that does not fit is HIDDEN whole (display:none), never half-clipped;
   3) the active-session count is painted inside the strip at every one of those widths;
   4) the rail gateway dot is inside the viewport at 1366x768 and with the collapsed rail at
      1024x768 — and inside the rail's own visible box, not scrolled away under it.

   `/status` is stubbed so the strip carries the gateway, session and version fields whatever
   the backend under test happens to report — the geometry is what is under test here. */
import { test, expect, type Page } from '@playwright/test';

const STATUS = {
  status: 'ok',
  version: '1.1.0',
  model_state: 'ready',
  loaded_model: 'qwen2.5-7b-instruct',
  gateway: { state: 'running', running: ['telegram', 'discord'], running_count: 2, total: 3 },
  sessions: { active: 12, window_s: 900, state: 'known' },
  agents: [],
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); localStorage.setItem('hud.seen', '1'); } catch { /* ignore */ }
  });
  await page.route(/\/status(\?.*)?$/, (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(STATUS),
  }));
});

async function boot(page: Page, width: number, height: number) {
  await page.setViewportSize({ width, height });
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
  // the badges re-render once the stubbed /status poll lands
  await expect(page.locator('.brand [data-chrome="gateway"]')).toHaveAttribute('data-state', 'running');
  await page.waitForTimeout(300);
}

const TOPBAR = [[1920, 1080], [1536, 864], [1440, 900], [1366, 768]] as const;

for (const [width, height] of TOPBAR) {
  test(`LLM, DATA and GATEWAY stay fully visible in the top bar at ${width}x${height}`, async ({ page }) => {
    await boot(page, width, height);
    const m = await page.evaluate(() => {
      const strip = document.querySelector('.brand .badges') as HTMLElement;
      const box = strip.getBoundingClientRect();
      return Array.from(strip.children).map((el) => {
        const r = el.getBoundingClientRect();
        const key = (el.querySelector('.k')?.textContent || '').trim();
        const shown = getComputedStyle(el).display !== 'none' && r.width > 0;
        return {
          key,
          shown,
          inside: shown && r.left >= box.left - 0.5 && r.right <= box.right + 0.5,
          partial: shown && (r.right > box.left + 0.5 && r.left < box.left - 0.5 || r.left < box.right - 0.5 && r.right > box.right + 0.5),
        };
      });
    });
    const by = Object.fromEntries(m.map((b) => [b.key, b]));
    // EGRESS and MIC are what this strip showed at 1366px before GATEWAY joined it: the new
    // badge must not buy its slot with the trust pair either.
    for (const key of ['LLM', 'DATA', 'GATEWAY', 'EGRESS', 'MIC']) {
      expect(by[key], `${key} badge missing from the strip`).toBeTruthy();
      expect(by[key].inside, `${key} badge is clipped or hidden at ${width}x${height}: ${JSON.stringify(m)}`).toBe(true);
    }
    const halfCut = m.filter((b) => b.partial).map((b) => b.key);
    expect(halfCut, `half-clipped badges at ${width}x${height}`).toEqual([]);
    // 3) the active-session count (stubbed: 12) is PAINTED in the strip at every width here.
    //    It used to be a badge of its own with the lowest keep, shed at every width from 1600
    //    down — and the badge was the only place the count appeared. It now rides inside the
    //    GATEWAY badge, which is never shed, so it lives exactly as long as GATEWAY does.
    const sess = await page.evaluate(() => {
      const strip = document.querySelector('.brand .badges') as HTMLElement;
      const el = strip.querySelector('[data-chrome="sessions"]') as HTMLElement | null;
      if (!el) return null;
      const box = strip.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return {
        text: (el.textContent || '').trim(),
        title: el.closest('[title]')?.getAttribute('title') || '',
        painted: r.width > 0 && r.height > 0 && el.offsetParent !== null,
        inside: r.left >= box.left - 0.5 && r.right <= box.right + 0.5,
        // the topmost element at the count's centre must be the count itself (or a child of
        // it), or its own badge's value line — never the page behind a display:none box
        hit: !!hit && (el.contains(hit) || (hit.contains(el) && !!el.closest('.badge')?.contains(hit))),
      };
    });
    expect(sess, `no session count in the strip at ${width}x${height}`).not.toBeNull();
    expect(sess!.text).toContain('12');
    expect(sess!.painted && sess!.inside && sess!.hit, `session count not visible at ${width}x${height}: ${JSON.stringify(sess)}`).toBe(true);
    expect(sess!.title).toContain('12 sessions active in the last 15 min');
    // the strip lost its VER badge; the version rides on the brand line instead
    await expect(page.locator('.brand [data-chrome="version"]')).toContainText('v1.1.0');
  });
}

const RAIL = [[1366, 768], [1280, 800], [1024, 768]] as const;

for (const [width, height] of RAIL) {
  test(`the rail gateway dot is on screen at ${width}x${height}`, async ({ page }) => {
    await boot(page, width, height);
    const m = await page.evaluate(() => {
      const gw = document.querySelector('[data-chrome="rail-gateway"]') as HTMLElement;
      const dot = gw.querySelector('.rail-gw-dot') as HTMLElement;
      const rail = document.querySelector('.rail') as HTMLElement;
      const d = dot.getBoundingClientRect();
      const r = rail.getBoundingClientRect();
      // the topmost painted element at the dot's centre must be the dot (or its row)
      const hit = document.elementFromPoint(d.left + d.width / 2, d.top + d.height / 2);
      return {
        dot: { top: d.top, bottom: d.bottom, w: d.width },
        rail: { top: r.top, bottom: r.bottom },
        vh: window.innerHeight,
        hitsDot: !!hit && gw.contains(hit),
      };
    });
    expect(m.dot.w, 'the gateway dot is not painted').toBeGreaterThan(0);
    expect(m.dot.top, `dot above the viewport: ${JSON.stringify(m)}`).toBeGreaterThanOrEqual(0);
    expect(m.dot.bottom, `dot below the fold: ${JSON.stringify(m)}`).toBeLessThanOrEqual(m.vh);
    expect(m.dot.bottom, `dot outside the rail box: ${JSON.stringify(m)}`).toBeLessThanOrEqual(m.rail.bottom + 0.5);
    expect(m.hitsDot, `the dot is covered at ${width}x${height}: ${JSON.stringify(m)}`).toBe(true);
  });
}

test('the rail wheel-scrolls to its last mode button on a 768px-tall screen', async ({ page }) => {
  await boot(page, 1366, 768);
  // A wheel over the rail, as the owner would scroll — not scrollIntoView, which also moves
  // `overflow:hidden` boxes and would pass even when nothing a user can do reaches the button.
  const rail = await page.locator('.rail').boundingBox();
  await page.mouse.move(rail!.x + rail!.width / 2, rail!.y + rail!.height / 2);
  await page.mouse.wheel(0, 2000);
  await page.waitForTimeout(300);
  const m = await page.locator('.rail .rail-btn').last().evaluate((el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { bottom: r.bottom, vh: window.innerHeight, hit: !!hit && el.contains(hit) };
  });
  expect(m.bottom).toBeLessThanOrEqual(m.vh);
  expect(m.hit, 'the last mode button is covered (by the pinned gateway footer?)').toBe(true);
  // and the gateway dot is still on screen after the scroll
  const dot = await page.locator('[data-chrome="rail-gateway"] .rail-gw-dot').boundingBox();
  expect(dot && dot.y + dot.height).toBeLessThanOrEqual(768);
});
