/* HUD v2 · marketing footage capture (T-0.52). One .webm per shot in the
 * `docs/marketing/TEASER_PACK.md` §6 shot list, recorded off the REAL running HUD.
 *
 * This is a capture tool that happens to be a test, and it is a test on purpose:
 * the shot list's own rule is
 *
 *     "never stage fake data for a shot. Demo mode is clearly badged; use it, or
 *      use real data. The honesty *is* the marketing."
 *
 * A rule like that survives exactly as long as something checks it. So the two
 * sources are the only two this file can be run with — `FOOTAGE_SOURCE=live`
 * (default) drives the real backend and ASSERTS the demo banner is absent;
 * `FOOTAGE_SOURCE=demo` appends the `?demo=1` the HUD itself uses and ASSERTS the
 * banner is visible. Anything else fails at collection with a message naming both.
 * There is no third mode, and in particular there is no seam here for injecting a
 * prettier corpus: the specs never write app state, they only navigate and wait.
 *
 * What that means for whoever produces the visuals: a surface with nothing in it
 * films as an empty state. That is not a bug in this script, it is the product
 * telling the truth about the machine it was filmed on. Fill the surface with real
 * work, or film it in demo mode with the banner in frame. Both are honest; a
 * hand-fed screenshot is not. `docs/marketing/FOOTAGE_RUNBOOK.md` carries the rest.
 *
 * Gated behind FOOTAGE=1 — `playwright.config.ts` registers the `footage` project
 * only when that is set, and every other project ignores this file. It is never
 * part of `npm run e2e`, the PR lane, or the nightly soak: recording video for six
 * shots is minutes of wall clock and tens of MB of artifacts, and it gates nothing.
 */
import { test, expect, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const OUT = 'e2e/artifacts/footage';

/* Two sources, and only two — see the header. Read once, at module scope, so an
   unknown value fails the whole file loudly instead of per-test. */
const SOURCE = (() => {
  const raw = (process.env.FOOTAGE_SOURCE || 'live').trim().toLowerCase();
  if (raw !== 'live' && raw !== 'demo') {
    throw new Error(
      `FOOTAGE_SOURCE must be "live" (real data, no banner) or "demo" (seeded corpus, `
      + `banner in frame) — got "${raw}". TEASER_PACK.md §6 allows no third source.`,
    );
  }
  return raw as 'live' | 'demo';
})();

/* How long each shot rolls. Long enough that the Neural Mesh and the ticker are
   visibly moving; short enough that six shots are a coffee, not a lunch. */
const SECONDS = (() => {
  const n = Number(process.env.FOOTAGE_SECONDS);
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 6;
})();

const URL_FOR = SOURCE === 'demo' ? '/v2?demo=1' : '/v2';

/** The §6 list. `command` is the exact palette entry — palette command names are
 *  hardcoded English in shell.tsx, so this survives a language toggle; `null` means
 *  the shot is the boot surface and needs no navigation. */
const SHOTS: Array<{ id: string; command: string | null; title: string; teaser: string }> = [
  { id: 'hero', command: null, title: 'Cockpit at rest',
    teaser: '§6.1 Hero — the cockpit at rest, agent network brain alive, void/cyan.' },
  { id: 'trust-center', command: 'Trust Center', title: 'Trust Center',
    teaser: '§6.2 audit chain "chain verified · no tampering detected" + the %-local meter.' },
  { id: 'governed-autonomy', command: 'Autonomy', title: 'Autonomy · approval queue',
    teaser: '§6.3 a governed-autonomy moment — the HUD half; the Telegram card is a device capture.' },
  { id: 'morning-brief', command: 'Knowledge', title: 'Knowledge · research queue + daily digest',
    teaser: '§6.4 the morning brief — a prioritized digest, to sell proactivity.' },
  { id: 'strict-local', command: 'Family · local', title: 'Family · local-only',
    teaser: '§6.5 the strict-local / Frigga badge — the privacy proof point.' },
  // §6.6 (WorldView globe, "optional") is deliberately absent: WorldView is a
  // separate surface with its own server, not something this backend serves, so a
  // clip of it cannot come from this lane. FOOTAGE_RUNBOOK.md says where it comes
  // from instead. Adding a stub here would produce a file named worldview.webm
  // containing something that is not WorldView, which is the exact failure mode the
  // reuse rule exists to prevent.
];

/** Open the command palette and run one entry by its exact name. */
async function palette(page: Page, command: string): Promise<void> {
  await page.keyboard.press('Control+k');
  const input = page.locator('.pal .pal-input input');
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill(command);
  const item = page.locator('.pal-item', { has: page.locator('.pi-name', { hasText: command }) }).first();
  await expect(item, `no palette entry matched "${command}"`).toBeVisible({ timeout: 10_000 });
  await item.click();
  await expect(page.locator('.pal-scrim')).toHaveCount(0, { timeout: 10_000 });
}

/** Title of the currently active rail button — the HUD's own record of which mode
 *  is on screen. Used to prove navigation happened without pinning MODES' order. */
async function activeMode(page: Page): Promise<string> {
  return (await page.locator('.rail-btn.active').first().getAttribute('title')) || '';
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
  });
});

for (const shot of SHOTS) {
  test(`footage · ${shot.id}`, async ({ page }, testInfo) => {
    const video = page.video();
    expect(video, 'no video recorder — run this through the `footage` project (FOOTAGE=1)')
      .not.toBeNull();

    const pageErrors: string[] = [];
    page.on('pageerror', (e) => pageErrors.push(String(e?.stack || e)));

    await page.goto(URL_FOR, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });

    /* The honesty assertion. The demo banner is what tells a viewer the data on
       screen is seeded — so in demo it must be ON SCREEN (it will be in the frame,
       which is the point), and in live it must be absent (footage of real data must
       not be quietly demo footage). If the banner is ever made subtler, dismissable
       or conditional, this goes red and someone gets to make that call deliberately. */
    // Matched by the words a VIEWER reads, not by a class: the banner is inline-styled
    // with no hook, and the contract being defended is legibility on screen, which a
    // class name would not have proved anyway.
    const banner = page.getByText(/DEMO DATA .*seeded sample, not your live backend/);
    if (SOURCE === 'demo') {
      await expect(banner.first(), 'demo footage must carry the demo badge in frame')
        .toBeVisible({ timeout: 10_000 });
    } else {
      await expect(banner, 'live footage must not secretly be demo footage').toHaveCount(0);
    }

    const bootMode = await activeMode(page);
    if (shot.command) {
      await palette(page, shot.command);
      await expect
        .poll(async () => await activeMode(page), { timeout: 10_000, message: 'the mode never changed' })
        .not.toBe(bootMode);
    } else {
      // The hero shot is the boot surface; its content proof is the same one
      // hud.spec.ts makes — the Neural Mesh canvas is there and visible.
      await expect(page.locator('.nmesh canvas').first()).toBeVisible({ timeout: 20_000 });
    }

    // Roll. Nothing is driven during this window — whatever moves, moves on its own.
    await page.waitForTimeout(SECONDS * 1000);

    expect(pageErrors, `uncaught page errors during the shot:\n${pageErrors.join('\n')}`).toEqual([]);

    /* Save the clip under a stable, human-meaningful name. Playwright finalises the
       video when the page closes, so close first and save after — otherwise saveAs
       races the encoder and can land a truncated file. */
    mkdirSync(OUT, { recursive: true });
    const webm = join(OUT, `${shot.id}.webm`);
    await page.close();
    await video!.saveAs(webm);

    const bytes = statSync(webm).size;
    expect(bytes, `${webm} is empty — the recorder produced no frames`).toBeGreaterThan(1024);

    writeFileSync(join(OUT, `${shot.id}.json`), JSON.stringify({
      id: shot.id,
      title: shot.title,
      teaser: shot.teaser,
      source: SOURCE,
      seconds: SECONDS,
      viewport: testInfo.project.use.viewport || null,
      file: `${shot.id}.webm`,
      bytes,
    }, null, 2) + '\n');
  });
}
