/* HUD v2 · H133 status-chrome geometry, in the Ledger frame since the cutover (PHASE_B_PLAN.md
   §8.2 rows 27 and 28). The live status chrome — the running head's eight items, and the gateway,
   session and version readings the running foot keeps (`data-chrome`) — only counts as delivered
   if the owner can SEE it on an ordinary screen, and a DOM-presence check in jsdom cannot tell,
   because jsdom has no layout. This spec measures painted rects in a real Chromium.

   What went wrong first (the classic shell). `.brand .badges` was `justify-content:flex-end;
   overflow:hidden`, so every badge added to the strip pushed the LEFTMOST ones out of the clip
   box: adding three badges hid AGENTS + LLM at 1680x1050 and AGENTS + LLM + DATA + GATEWAY at
   1366x768 — the model and data-provenance badges vanished at exactly the laptop widths owners
   use. And the rail's gateway dot sat below the fold of a 768px-tall screen, in a body with
   `overflow:hidden`. Any strip that grows can do the same, so the frame's are measured.

   The contract asserted here:
   1) at 2560x1353, 1920x1080, 1536x864, 1440x900, 1366x768 and 1280x800 all eight running-head
      items — the six trust signals, the approval mode and the interrupts — are painted fully
      inside the viewport and inside the running head's own box, each on top at its centre and
      none on another: no item may evict another (§4.2: the running head is visible at every width);
   2) the version (stubbed 1.1.0) is painted in the running foot at every one of those widths;
   3) the gateway and the active-session count are painted in the foot at every one of those
      widths too (§8.2 row 27; H133's own claim, that no laptop width may lose them): whole from
      2200px ("12 sessions in the last 15 min"), compact below it ("12 sessions", the window in its
      title), never half-clipped — and the gateway also at 1024x768, where the rail's dot used to be;
   4) (since the Ledger cutover, the rail and its gateway dot being gone) the masthead's nine
      areas are painted inside the viewport, on top, at 1366x768, 1280x800 and 1024x768, and
      below 760px the Areas drawer holds all nine — see the comment above those tests.

   `/status` is stubbed so the strip carries the gateway, session and version fields whatever
   the backend under test happens to report — the geometry is what is under test here. */
import { test, expect, type Page } from '@playwright/test';

const STATUS = {
  status: 'ok',
  version: '1.1.0',
  model_state: 'ready',
  loaded_model: 'qwen2.5-7b-instruct',
  gateway: { state: 'running', running: ['telegram', 'voice'], running_count: 2, total: 3 },
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

/* 1)–3) The running head and the running foot (PHASE_B_PLAN.md §8.2 row 27). This half boots on
   the stubbed /status having landed: the foot's version is the hub's own. */
async function bootChrome(page: Page, width: number, height: number) {
  await page.setViewportSize({ width, height });
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
  await expect(page.locator('[data-frame="runhead"]')).toBeVisible({ timeout: 20_000 });
  // the foot re-renders once the stubbed /status poll lands
  await expect(page.locator('[data-frame="runfoot"] [data-chrome="version"]')).toHaveText('Nerva 1.1.0');
  await page.waitForTimeout(300);
}

/** The eight running-head items (signals/types.ts SIGNAL_IDS, then the mode and the interrupts). */
const RUNHEAD_ITEMS = ['egress', 'localRoute', 'microphone', 'model', 'data', 'chain', 'mode', 'interrupts'];
const CHROME_SCREENS = [[2560, 1353], [1920, 1080], [1536, 864], [1440, 900], [1366, 768], [1280, 800]] as const;

for (const [width, height] of CHROME_SCREENS) {
  test(`the running head's eight items and the foot's readings stay fully visible at ${width}x${height}`, async ({ page }) => {
    await bootChrome(page, width, height);

    // 1) the eight running-head items: painted, whole, on top, and apart
    const items = await page.evaluate(() => {
      const head = document.querySelector('[data-frame="runhead"]') as HTMLElement;
      const box = head.getBoundingClientRect();
      const vw = document.documentElement.clientWidth;
      const vh = window.innerHeight;
      return Array.from(head.querySelectorAll<HTMLElement>('[data-signal], [data-runhead="mode"], [data-runhead="interrupts"]')).map((el) => {
        const r = el.getBoundingClientRect();
        const shown = getComputedStyle(el).display !== 'none' && r.width > 0 && r.height > 0;
        const hit = shown ? document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) : null;
        return {
          id: el.getAttribute('data-signal') || el.getAttribute('data-runhead') || '?',
          shown,
          inViewport: shown && r.left >= -0.5 && r.top >= -0.5 && r.right <= vw + 0.5 && r.bottom <= vh + 0.5,
          inHead: shown && r.left >= box.left - 0.5 && r.right <= box.right + 0.5 && r.top >= box.top - 0.5 && r.bottom <= box.bottom + 0.5,
          // the topmost element at the item's centre is the item (or a part of it)
          onTop: !!hit && el.contains(hit),
          rect: [r.left, r.top, r.right, r.bottom],
        };
      });
    });
    expect(items.map((i) => i.id).sort(), 'the running head holds its eight items').toEqual([...RUNHEAD_ITEMS].sort());
    const unseen = items.filter((i) => !(i.shown && i.inViewport && i.inHead && i.onTop)).map((i) => i.id);
    expect(unseen, `running-head items clipped, hidden or covered at ${width}x${height}: ${JSON.stringify(items)}`).toEqual([]);
    const stacked: string[] = [];
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const [al, at, ar, ab] = items[i].rect;
        const [bl, bt, br, bb] = items[j].rect;
        if (Math.min(ar, br) - Math.max(al, bl) > 0.5 && Math.min(ab, bb) - Math.max(at, bt) > 0.5) stacked.push(`${items[i].id}/${items[j].id}`);
      }
    }
    expect(stacked, `running-head items on top of each other at ${width}x${height}`).toEqual([]);

    // 2) and 3) the foot's readings: painted whole where the foot carries them, else hidden whole
    const foot = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const vh = window.innerHeight;
      const read = (hook: string) => {
        const el = document.querySelector<HTMLElement>(`[data-frame="runfoot"] [data-chrome="${hook}"]`);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const painted = r.width > 0 && r.height > 0 && el.offsetParent !== null;
        const hit = painted ? document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) : null;
        return {
          // what is drawn (the long and the short forms are both in the DOM; CSS shows one)
          text: (el.innerText || '').replace(/\s+/g, ' ').trim(),
          title: el.getAttribute('title') || '',
          painted,
          inside: painted && r.left >= -0.5 && r.top >= -0.5 && r.right <= vw + 0.5 && r.bottom <= vh + 0.5,
          onTop: !!hit && el.contains(hit),
          // half-clipped: painted, but crossing the viewport's edge
          partial: painted && (r.left < -0.5 || r.right > vw + 0.5 || r.bottom > vh + 0.5),
        };
      };
      return { version: read('version'), gateway: read('gateway'), sessions: read('sessions') };
    });
    expect(foot.version, 'the foot carries the version the hub reported').not.toBeNull();
    expect(foot.version!.text).toBe('Nerva 1.1.0');
    expect(foot.version!.painted && foot.version!.inside && foot.version!.onTop,
      `the version is not visible at ${width}x${height}: ${JSON.stringify(foot.version)}`).toBe(true);
    expect(foot.gateway, 'the foot keeps the gateway reading (data-chrome="gateway")').not.toBeNull();
    expect(foot.sessions, 'the foot keeps the session count (data-chrome="sessions")').not.toBeNull();
    for (const [name, reading] of [['gateway', foot.gateway!], ['sessions', foot.sessions!]] as const) {
      expect(reading.partial, `the ${name} reading is half-clipped at ${width}x${height}: ${JSON.stringify(reading)}`).toBe(false);
    }
    // the stubbed hub: 2 of 3 channels running, 12 sessions over 900 s — painted at every width
    expect(foot.gateway!.painted && foot.gateway!.inside && foot.gateway!.onTop,
      `the gateway is not visible at ${width}x${height}: ${JSON.stringify(foot.gateway)}`).toBe(true);
    expect(foot.gateway!.text).toContain('2 of 3 running');
    expect(foot.gateway!.title).toBe('telegram, voice');
    expect(foot.sessions!.painted && foot.sessions!.inside && foot.sessions!.onTop,
      `the session count is not visible at ${width}x${height}: ${JSON.stringify(foot.sessions)}`).toBe(true);
    if (width >= 2200) {
      expect(foot.sessions!.text).toBe('12 sessions in the last 15 min');
    } else {
      // compact below 2200px: the count is drawn, its window is in the title
      expect(foot.sessions!.text).toBe('12 sessions');
      expect(foot.sessions!.title).toBe('12 sessions in the last 15 min');
    }
  });
}

/* 4) The nine areas, rewritten at the Ledger cutover (PHASE_B_PLAN.md §8.2 row 28). The rail and
      its gateway dot are gone: the gateway rides in the running foot now (the half above), and
      what the owner must reach on an ordinary screen instead is the masthead's nine areas. At
      1366x768, 1280x800 and 1024x768 every area link is painted inside the viewport and is the
      topmost element at its centre (a link scrolled out of a clipped row, or under another layer,
      fails); below 760px the docked list gives way to the "Areas" drawer, which holds all nine.
      The wheel test went with the rail: nothing scrolls the masthead.

   This half boots on the masthead itself (`bootFrame`), not on the half above's readiness. */
const AREA_ORDER = ['home', 'work', 'agents', 'memory', 'trust', 'build', 'connect', 'observe', 'settings'];

async function bootFrame(page: Page, width: number, height: number) {
  await page.setViewportSize({ width, height });
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
  await expect(page.locator('[data-frame="masthead"]')).toBeVisible({ timeout: 20_000 });
}

/** Every link of an area list: painted, inside the viewport, and on top at its centre. */
function measureAreas(nav: ReturnType<Page['locator']>) {
  return nav.locator('a[data-area]').evaluateAll((links) => links.map((a) => {
    const r = a.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return {
      area: a.getAttribute('data-area'),
      painted: r.width > 0 && r.height > 0 && getComputedStyle(a).visibility !== 'hidden',
      inside: r.left >= -0.5 && r.top >= -0.5 && r.right <= window.innerWidth + 0.5 && r.bottom <= window.innerHeight + 0.5,
      onTop: !!hit && a.contains(hit),
      box: [r.left, r.top, r.right, r.bottom].map(Math.round),
    };
  }));
}

const AREA_SCREENS = [[1366, 768], [1280, 800], [1024, 768]] as const;

for (const [width, height] of AREA_SCREENS) {
  test(`the nine areas are on screen in the masthead at ${width}x${height}`, async ({ page }) => {
    await bootFrame(page, width, height);
    // the rail's gateway dot used to answer "is the gateway up?" at these sizes: the foot does now
    const gateway = page.locator('[data-frame="runfoot"] [data-chrome="gateway"]');
    await expect(gateway).toHaveAttribute('data-state', 'running');
    const g = await gateway.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return { inside: r.width > 0 && r.top >= 0 && r.bottom <= window.innerHeight && r.left >= 0 && r.right <= window.innerWidth, onTop: !!hit && el.contains(hit) };
    });
    expect(g.inside && g.onTop, `the gateway is not on screen at ${width}x${height}: ${JSON.stringify(g)}`).toBe(true);
    const nav = page.locator('[data-frame="masthead"]').getByRole('navigation', { name: 'Areas' });
    await expect(nav).toBeVisible();
    const m = await measureAreas(nav);
    expect(m.map((a) => a.area), 'the masthead lists the nine areas in order').toEqual(AREA_ORDER);
    const off = m.filter((a) => !(a.painted && a.inside && a.onTop)).map((a) => a.area);
    expect(off, `areas not fully on screen at ${width}x${height}: ${JSON.stringify(m)}`).toEqual([]);
    // docked, so the drawer's opener is not drawn beside them
    await expect(page.getByRole('button', { name: 'Open the areas menu' })).toBeHidden();
  });
}

test('below 760px the nine areas are one button away, in the Areas drawer', async ({ page }) => {
  await bootFrame(page, 740, 800);
  // the docked list is not drawn at this width; its opener is
  await expect(page.locator('[data-frame="masthead"]').getByRole('navigation', { name: 'Areas' })).toHaveCount(0);
  const opener = page.getByRole('button', { name: 'Open the areas menu' });
  await expect(opener).toBeVisible();
  await opener.click();
  const drawer = page.getByRole('dialog', { name: 'Areas' });
  await expect(drawer).toBeVisible();
  const m = await measureAreas(drawer.getByRole('navigation', { name: 'Areas' }));
  expect(m.map((a) => a.area), 'the drawer lists the nine areas in order').toEqual(AREA_ORDER);
  const off = m.filter((a) => !(a.painted && a.inside && a.onTop)).map((a) => a.area);
  expect(off, `areas not fully on screen in the drawer: ${JSON.stringify(m)}`).toEqual([]);
  // Escape closes it and gives the focus back to its opener
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect(opener).toBeFocused();
});
