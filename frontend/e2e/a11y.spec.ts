/* HUD v2 · accessibility gate (H23.17). Runs axe-core against the live cockpit
   (and the cinema overlay) in real Chromium — the WCAG checks jsdom/vitest can't
   do: real computed colour-contrast, ARIA/role correctness, focus-order, and
   landmark structure on the actually-painted DOM.

   Threshold is intentionally conservative: the cockpit is a dense, custom canvas
   HUD (not a form-heavy CRUD app), so we gate on the impact levels that are
   unambiguous bugs — `critical` and `serious` — rather than chasing every
   `moderate`/`minor` advisory. The full violation list (all impacts) is written
   to e2e/artifacts/a11y-*.json as the human-reviewable audit trail, so the
   moderate/minor backlog stays visible without blocking the lane. */
import { test, expect } from '@playwright/test';

// The e2e backend boots with no model loaded, which (correctly) raises the
// first-run gate. These specs drive the cockpit as an already-onboarded user,
// so pre-seed the dismissal exactly as a returning user's browser carries it.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* ignore */ }
  });
});
import AxeBuilder from '@axe-core/playwright';
import { mkdirSync, writeFileSync } from 'node:fs';

type Impact = 'critical' | 'serious' | 'moderate' | 'minor' | null;
const BLOCKING: ReadonlyArray<Exclude<Impact, null>> = ['critical', 'serious'];

/** Compact summary line per violation for the failure message + artifact. */
function summarise(violations: { id: string; impact?: Impact; nodes: unknown[] }[]) {
  return violations.map((v) => `${v.impact ?? 'n/a'} · ${v.id} (${v.nodes.length} node${v.nodes.length === 1 ? '' : 's'})`);
}

test('HUD v2 cockpit has no critical/serious accessibility violations', async ({ page }) => {
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  // wait for the React app + mesh to actually mount before scanning the DOM
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
  await expect(page.locator('.nmesh canvas').first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(800); // let panels settle / async data degrade-or-fill

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  mkdirSync('e2e/artifacts', { recursive: true });
  writeFileSync(
    'e2e/artifacts/a11y-cockpit.json',
    JSON.stringify({ url: '/v2', counts: tally(results.violations), violations: results.violations }, null, 2),
  );

  const blocking = results.violations.filter((v) => BLOCKING.includes((v.impact ?? '') as never));
  expect(
    blocking,
    `axe found ${blocking.length} critical/serious violation(s) on /v2:\n` + summarise(blocking).join('\n'),
  ).toEqual([]);
});

test('Cinema mode overlay has no critical/serious accessibility violations', async ({ page }) => {
  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.nmesh canvas').first()).toBeVisible({ timeout: 20_000 });

  await page.keyboard.press('m');
  await expect(page.locator('.cinema')).toBeVisible();
  await page.waitForTimeout(500);

  const results = await new AxeBuilder({ page })
    .include('.cinema')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  mkdirSync('e2e/artifacts', { recursive: true });
  writeFileSync(
    'e2e/artifacts/a11y-cinema.json',
    JSON.stringify({ scope: '.cinema', counts: tally(results.violations), violations: results.violations }, null, 2),
  );

  const blocking = results.violations.filter((v) => BLOCKING.includes((v.impact ?? '') as never));
  expect(
    blocking,
    `axe found ${blocking.length} critical/serious violation(s) in cinema mode:\n` + summarise(blocking).join('\n'),
  ).toEqual([]);
});

/* ── The transcript region · WCAG 2.1.1 ──────────────────────────────────────────
   The two scans above run against the DEFAULT e2e state: a freshly booted backend
   with an empty session, so `.convo` holds nothing, does not overflow, and is not a
   scrollable region at all. That is why they stayed green for months while the
   scheduled matrix went red — the defect only exists once the transcript OVERFLOWS
   and holds NO focusable descendant, and the ⧉/🔊 controls that would supply one sit
   on AGENT bubbles only. A run of user turns whose replies never arrived (no model
   loaded, an aborted turn) rehydrates into exactly that shape.

   So this test seeds that shape instead of hoping to inherit it. The transcript is
   injected by shimming `window.fetch` for GET /memory before the app boots — not with
   `page.route`, which the webkit lane does not intercept reliably, and not by mutating
   the shared backend, which would leak into whatever spec runs next. What that buys is
   a DOM/keyboard contract proven against a known transcript; it does not prove the
   backend produces this transcript (the nightly already showed that it does).

   Why the assertions are shaped the way they are: Chromium makes overflow scrollers
   focusable on its own, so a tab-walk reaches `.convo` even with the defect present
   (measured: 39th Tab unfixed, 28th fixed) — a tab-reachability assertion here is
   VACUOUS and self-passes, and so is a PageDown-after-`.focus()` check. That masking is
   about FOCUS, not about axe: Chromium's axe reports the violation on an overflowing
   unfixed transcript exactly as webkit does. The portable facts are the axe rule
   (`scrollable-region-focusable`, serious, WCAG 2.1.1) and `tabIndex`.

   Scope, so a green run is not read as more than it is: this scans the cockpit route,
   like the two above it. Other HUD surfaces have their own scrollable regions and are
   not covered — see BACKLOG.md for the ones already measured and still open. */
test('the chat transcript stays keyboard-reachable when it holds only user turns', async ({ page }) => {
  await page.addInitScript(() => {
    const turns = Array.from({ length: 6 }, (_, i) => ({
      role: 'user',
      content: `user turn ${i + 1} — long enough to wrap and take vertical room in the column`,
      timestamp: new Date(1700000000000 + i * 60000).toISOString(),
    }));
    const orig = window.fetch;
    window.fetch = (input: any, init?: any) => {
      const raw = typeof input === 'string' ? input : (input && input.url) || '';
      // Compare the PATHNAME, exactly. A `/…memory(\?|$)/` shape reads like it excludes
      // the other memory routes and mostly does — but it also matches
      // `/api/cognition/memory`, which CognitionPanel polls (gap.tsx). Harmless on this
      // route today, silently wrong the moment this scan covers the mode that mounts it.
      let path = '';
      try { path = new URL(raw, window.location.origin).pathname; } catch { path = ''; }
      if (path === '/memory') {
        return Promise.resolve(new Response(JSON.stringify({ session: 'e2e-a11y', turns }), {
          status: 200, headers: { 'Content-Type': 'application/json' },
        }));
      }
      return orig(input, init);
    };
  });

  await page.goto('/v2', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });
  await expect(page.locator('.convo .msg.user')).toHaveCount(6, { timeout: 20_000 });
  await page.waitForTimeout(600);

  const state = await page.evaluate(() => {
    const c = document.querySelector('.convo') as HTMLElement | null;
    if (!c) return null;
    return {
      overflowY: getComputedStyle(c).overflowY,
      scrollHeight: c.scrollHeight,
      clientHeight: c.clientHeight,
      // `.convo` itself is not a descendant of `.convo`, so this counts children only.
      focusables: c.querySelectorAll('[tabindex], button, a[href], input, select, textarea').length,
      agentMsgs: c.querySelectorAll('.msg.agent').length,
      tabIndex: c.tabIndex,
      role: c.getAttribute('role'),
      name: c.getAttribute('aria-label'),
    };
  });

  expect(state, 'the transcript region should exist').not.toBeNull();
  // Non-vacuity pins. If either premise stops holding, there is no scrollable region
  // with no way in, the axe rule below cannot fire, and this test would self-pass.
  expect(state!.agentMsgs, 'the seeded transcript must contain no agent turns').toBe(0);
  expect(
    state!.focusables,
    'the seeded transcript must contain no focusable child — that is the whole premise: ' +
    'a scrollable region whose only keyboard route would be a control inside it',
  ).toBe(0);
  expect(
    state!.scrollHeight,
    `the transcript must actually overflow to be a scrollable region ` +
    `(overflow-y: ${state!.overflowY}, ${state!.scrollHeight}px of content in ${state!.clientHeight}px)`,
  ).toBeGreaterThan(state!.clientHeight + 1);

  // The WCAG assertion comes FIRST on purpose: it is the one that names the defect. With
  // the DOM-contract checks ahead of it, removing the fix failed on "tabIndex must be 0"
  // and the violation was never reported, so a red run said less than it knew.
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  mkdirSync('e2e/artifacts', { recursive: true });
  writeFileSync(
    'e2e/artifacts/a11y-transcript.json',
    JSON.stringify({ scope: '/v2 · user-only transcript', counts: tally(results.violations), violations: results.violations }, null, 2),
  );

  const blocking = results.violations.filter((v) => BLOCKING.includes((v.impact ?? '') as never));
  expect(
    blocking,
    `axe found ${blocking.length} critical/serious violation(s) on a user-only transcript:\n` + summarise(blocking).join('\n'),
  ).toEqual([]);

  expect(
    state!.tabIndex,
    'the transcript is a scrollable region with no focusable content, so it must itself be ' +
    'in the sequential focus order (tabindex="0") — otherwise a keyboard user cannot read ' +
    'past the fold. Chromium focuses overflow scrollers implicitly; webkit and firefox do not.',
  ).toBe(0);
  expect(state!.role, 'the transcript should carry the chat-log role').toBe('log');
  expect(state!.name, 'a focusable region needs an accessible name').toBeTruthy();

  // Deliberately NOT asserted here: that PageDown scrolls the focused region. Measured
  // both ways — programmatic `.focus()` succeeds on an overflow scroller in Chromium
  // with and without `tabindex`, so PageDown moves scrollTop to 94 either way and the
  // check cannot go red for the defect it would be placed after. It is the same trap as
  // the tab-walk, one layer down. Do not re-add it without a red-proof.
});

/** Count violations by impact level for the artifact header. */
function tally(violations: { impact?: Impact }[]) {
  const counts: Record<string, number> = { critical: 0, serious: 0, moderate: 0, minor: 0, 'n/a': 0 };
  for (const v of violations) counts[v.impact ?? 'n/a'] = (counts[v.impact ?? 'n/a'] ?? 0) + 1;
  return counts;
}
