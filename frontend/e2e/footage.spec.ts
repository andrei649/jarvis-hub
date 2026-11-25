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
 * (default) drives the real backend and ASSERTS the demo notice is absent;
 * `FOOTAGE_SOURCE=demo` appends the `?demo=1` the HUD itself uses and ASSERTS the
 * notice is on screen. Anything else fails at collection with a message naming both.
 * There is no third mode, and in particular there is no seam here for injecting a
 * prettier corpus: the specs never write app state, they only navigate and wait.
 * (The search sheet keeps its five recent rows in the test browser's own storage,
 * which dies with the test's browser context; nothing reaches the hub.)
 *
 * What that means for whoever produces the visuals: a surface with nothing in it
 * films as an empty state. That is not a bug in this script, it is the product
 * telling the truth about the machine it was filmed on. Fill the surface with real
 * work, or film it in demo mode with the notice in frame. Both are honest; a
 * hand-fed screenshot is not. `docs/marketing/FOOTAGE_RUNBOOK.md` carries the rest.
 *
 * Since the Phase B cutover (PHASE_B_PLAN.md §9.3 stage 4) the HUD is the Ledger frame:
 * a shot is reached through the search sheet (the masthead's Find, Ctrl K), the badge is
 * the frame's demo notice ("Demo sample on screen — seeded data, not your live hub."), and
 * the Neural Mesh lives only in Cinema (§2.4), so the hero films Today's registers.
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
      `FOOTAGE_SOURCE must be "live" (real data, no demo notice) or "demo" (seeded corpus, `
      + `notice in frame) — got "${raw}". TEASER_PACK.md §6 allows no third source.`,
    );
  }
  return raw as 'live' | 'demo';
})();

/* How long each shot rolls. Long enough for an editor to cut a usable take; short
   enough that the shots are a coffee, not a lunch. The Ledger frame animates nothing
   by itself (no mesh, no ticker on Home): what changes on screen is the hub's own. */
const SECONDS = (() => {
  const n = Number(process.env.FOOTAGE_SECONDS);
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 6;
})();

const URL_FOR = SOURCE === 'demo' ? '/v2?demo=1' : '/v2';

/** The shot's way in through the search sheet: the words typed, and the row run, named by
 *  its command id (nav/commands.ts: 'area:<id>', 'page:mode:<id>'). Ids are the same in
 *  every language and search reads both languages' labels and the old names, so this
 *  survives a language toggle. `path`, `area` and `mode` are where that row must land. */
type Way = { query: string; command: string; path: string; area: string; mode: string };

/** The §6 list. `find: null` means the shot is the boot surface (Today) and needs no
 *  navigation. */
const SHOTS: Array<{ id: string; find: Way | null; title: string; teaser: string }> = [
  { id: 'hero', find: null, title: 'Today at rest',
    teaser: '§6.1 Hero — Today at rest: the day, the conversation and the docket side by side. '
      + '(The agent network brain is Cinema\'s alone since the Ledger cutover.)' },
  { id: 'trust-center', find: { query: 'Trust', command: 'area:trust', path: '/v2/trust', area: 'trust', mode: 'trust' },
    title: 'Trust Center',
    teaser: '§6.2 the record\'s verdict + how many runs went to local runners, a count with its basis '
      + '(the Ledger retired the "no tampering detected" line and the %-local meter).' },
  { id: 'governed-autonomy', find: { query: 'Autonomy', command: 'page:mode:autonomy', path: '/v2/autonomy', area: 'work', mode: 'autonomy' },
    title: 'Autonomy · approval queue',
    teaser: '§6.3 a governed-autonomy moment — the HUD half; the Telegram card is a device capture.' },
  { id: 'morning-brief', find: { query: 'Knowledge', command: 'page:mode:knowledge', path: '/v2/knowledge', area: 'agents', mode: 'knowledge' },
    title: 'Knowledge · research queue + daily digest',
    teaser: '§6.4 the morning brief — a prioritized digest, to sell proactivity.' },
  { id: 'strict-local', find: { query: 'Family', command: 'page:mode:family', path: '/v2/family', area: 'agents', mode: 'family' },
    title: 'Family · local-only',
    teaser: '§6.5 the strict-local / Frigga badge — the privacy proof point.' },
  // §6.6 (WorldView globe, "optional") is deliberately absent: WorldView is a
  // separate surface with its own server, not something this backend serves, so a
  // clip of it cannot come from this lane. FOOTAGE_RUNBOOK.md says where it comes
  // from instead. Adding a stub here would produce a file named worldview.webm
  // containing something that is not WorldView, which is the exact failure mode the
  // reuse rule exists to prevent.
];

/* Both languages: in `live` the owner's synced appearance may say Romanian. */
const FIND_NAME = /^(?:Search or run a command|Caută sau rulează o comandă)/;
const DEMO_WORDS = /Demo sample on screen|Mostră demo pe ecran/;

/** Open the search sheet from the masthead's Find button and run one row by its id. */
async function find(page: Page, way: Way): Promise<void> {
  await page.locator('[data-frame="masthead"]').getByRole('button', { name: FIND_NAME }).click();
  const sheet = page.getByRole('dialog', { name: FIND_NAME });
  await expect(sheet).toBeVisible({ timeout: 10_000 });
  await sheet.getByRole('combobox').fill(way.query);
  const row = sheet.locator(`[role="option"][data-command="${way.command}"]`);
  await expect(row, `no sheet row "${way.command}" for "${way.query}"`).toBeVisible({ timeout: 10_000 });
  await row.click();
  await expect(sheet).toHaveCount(0, { timeout: 10_000 });
}

/** The page a shot is filming, drawn: the area page of its area with that mode's body in it,
 *  or the area page's honest empty state when the mode's source has not answered (a live
 *  machine with nothing in that surface films as that). An error page in its place is not it. */
async function expectDrawn(page: Page, way: Way, message: string, timeout = 20_000): Promise<void> {
  const areaPage = page.locator(`main[data-frame="page"] [data-areapage][data-area="${way.area}"]`);
  await expect(areaPage, message).toBeVisible({ timeout });
  await expect(areaPage.locator(`[data-mode="${way.mode}"], [data-empty]`).first(), message).toBeVisible({ timeout });
}

/** Today's registers at this width (1920: the day, the conversation, the docket; the fourth
 *  starts at 2200px). */
const HOME_REGISTERS = ['day', 'talk', 'docket'] as const;

/* The honesty assertion. The demo notice is what tells a viewer the data on screen is
   seeded — so in demo it must be ON SCREEN, in words, inside the frame (it will be in the
   clip, which is the point), and in live it must be absent (footage of real data must not
   be quietly demo footage). If the notice is ever made subtler, dismissable or
   conditional, this goes red and someone gets to make that call deliberately.
   The contract being defended is legibility, so demo is matched by the words a VIEWER
   reads. Live is matched twice, by the words and by the notice's own hook, and only once
   the frame that draws the notices is on screen: rewording the notice, or a page that never
   mounted, cannot make "absent" pass by matching nothing. It is checked when the shot
   starts and again after it rolled, because the clip is the whole window, not its first
   frame. */
async function demoBadge(page: Page, when: string): Promise<void> {
  await expect(page.locator('[data-frame="masthead"]'), `the HUD frame is not on screen ${when}`).toBeVisible({ timeout: 20_000 });
  const notices = page.locator('[data-frame="notices"]');
  await expect(notices, `the frame draws no notices region ${when}`).toBeAttached();
  const notice = notices.locator('[data-notice="demo"]');
  if (SOURCE === 'demo') {
    await expect(notice, `demo footage must carry the demo notice in frame ${when}`).toBeVisible({ timeout: 10_000 });
    await expect(notice, `the demo notice must say so in words ${when}`).toContainText(DEMO_WORDS);
    await expect(notice.getByText(DEMO_WORDS), `the demo notice must be inside the frame ${when}`).toBeInViewport();
  } else {
    await expect(notice, `live footage must not secretly be demo footage ${when}`).toHaveCount(0);
    await expect(page.getByText(DEMO_WORDS), `live footage must not secretly be demo footage ${when}`).toHaveCount(0);
  }
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

    await demoBadge(page, 'when the shot starts');

    if (shot.find) {
      const way = shot.find;
      await find(page, way);
      // Proof that the right page is on screen, without pinning the masthead's order: the
      // address the row opens, and that page drawn in its area.
      await expect
        .poll(() => new URL(page.url()).pathname, { timeout: 10_000, message: 'the page never changed' })
        .toBe(way.path);
      await expectDrawn(page, way, `${way.path} is not drawn in ${way.area}`);
    } else {
      // The hero is the boot surface: Today with its registers side by side. Its content
      // proof used to be the Neural Mesh canvas; the mesh is Cinema's alone now, and /v2 is
      // proved by Today's registers instead (PHASE_B_PLAN.md §8.2 row 31).
      for (const register of HOME_REGISTERS) {
        await expect(page.locator(`main[data-frame="page"] [data-register="${register}"]`), `Today shows no ${register} register`)
          .toBeVisible({ timeout: 20_000 });
      }
    }

    // Roll. Nothing is driven during this window — whatever moves, moves on its own.
    await page.waitForTimeout(SECONDS * 1000);

    // What the clip ends on is still the shot: the same page, and the same honesty.
    if (shot.find) {
      expect(new URL(page.url()).pathname, 'the page changed during the take').toBe(shot.find.path);
      await expectDrawn(page, shot.find, 'the filmed page did not last the take', 5_000);
    } else {
      for (const register of HOME_REGISTERS) {
        await expect(page.locator(`main[data-frame="page"] [data-register="${register}"]`), `Today lost its ${register} register during the take`)
          .toBeVisible();
      }
    }
    await demoBadge(page, 'after the shot rolled');

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
