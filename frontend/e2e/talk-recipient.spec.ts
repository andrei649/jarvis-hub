/* The conversation's recipient, end to end (PHASE_B_PLAN.md §5.3, §12 item 11): the served bundle
   in a real Chromium, with a real streaming fetch held open, then released or aborted.

   (a) A refused recipient. The agent written to leaves the hub's roster: the composer says which
       agent and that nothing is sent until the owner chooses again, Send is held and nothing is
       sent, and the register head names no recipient. When the roster is then not served at all,
       it still says what is true (never "Checking the selected agent…" with no agent selected),
       and the To offers Jarvis, App's own default, so the owner can choose.
   (b) "Write to <Agent>" from the search sheet while a reply is held open: the To asks first in
       its own words, Send is held and points at the question, and nothing is stopped until the
       owner confirms. Left unanswered when the reply ends, the question stays, without "stops the
       reply", also after leaving Home and coming back; the reply that ended keeps its Turn
       details; only the owner's answer changes who is written to.
   (c) The same question through a reading of the roster that fails (GET /api/agents refused once:
       the page's loader falls back to rows from /status, which are not the hub's roster). The
       question stays, Send stays held, and only its switch waits, saying why, naming the agent as
       the hub's roster last named it; once the roster is served again the owner's answer is taken.
   (d) A question dropped because a served roster no longer offers the agent says why, on one line,
       until the next send.
   (e) A saved recipient the hub never serves the roster for after a reload is never left at
       "Checking the selected agent…": the composer says what is true, the To offers Jarvis, nothing
       switches by itself, and a served roster that offers the agent confirms the saved choice.

   Two routes are stubbed with page.route: the hub's roster (GET /api/agents: served, changed, or
   not served) and the chat stream (POST /chat/stream, held until the test releases it). Nothing
   reaches a model; every other request goes to the lane's own server.

   A manual lane: playwright.home-registers.config.ts (the fixture hub on its own port). The main
   lane (playwright.config.ts, which boots serve.py) ignores this file, and it skips itself outside
   its own project. */
import { expect, test, type Locator, type Page } from '@playwright/test';

type Agent = { id: string; name: string; chat_routing: string; enabled: boolean };
const JARVIS: Agent = { id: 'jarvis', name: 'Jarvis', chat_routing: 'orchestrated', enabled: true };
const FRIGGA: Agent = { id: 'frigga', name: 'Frigga', chat_routing: 'local', enabled: true };

/** The hub's roster as the test serves it: these agents, or (null) not served at all. */
async function serveRoster(page: Page): Promise<{ agents: Agent[] | null }> {
  const roster: { agents: Agent[] | null } = { agents: [JARVIS, FRIGGA] };
  await page.route((url) => url.pathname === '/api/agents', (route) => roster.agents
    ? route.fulfill({ status: 200, contentType: 'application/json', json: { agents: roster.agents } })
    : route.fulfill({ status: 503, contentType: 'application/json', json: { detail: 'not served in this test' } }));
  return roster;
}

type Held = { asked: Array<{ agent: string; message: string }>; aborted: number; delivered: number; release(): void };
/** POST /chat/stream, held open until `release()`; `aborted` counts the replies the page stopped. */
async function holdStream(page: Page): Promise<Held> {
  const gates: Array<() => void> = [];
  const held: Held = { asked: [], aborted: 0, delivered: 0, release: () => { gates.splice(0).forEach((open) => open()); } };
  page.on('requestfailed', (request) => { if (new URL(request.url()).pathname === '/chat/stream') held.aborted += 1; });
  await page.route((url) => url.pathname === '/chat/stream', async (route) => {
    const body = route.request().postDataJSON() as { agent: string; message: string };
    held.asked.push({ agent: body.agent, message: body.message });
    await new Promise<void>((open) => gates.push(open));
    const frames = [
      { type: 'start', agent: body.agent },
      { type: 'end', agent: body.agent, text: `Reply to ${body.message}.`, outcome: { latency_ms: 1250 } },
    ];
    try {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('') });
      held.delivered += 1;
    } catch { /* the page stopped this reply before it was released */ }
  });
  return held;
}

const to = (page: Page) => page.getByRole('combobox', { name: 'To', exact: true });
const field = (page: Page) => page.locator('[data-composer]');
const send = (page: Page) => page.locator('[data-composer-send]');
const head = (page: Page) => page.locator('[data-register="talk"] .n-talk__with');
/** The register head names the recipient and its declared policy (the role between them shows from
 *  1340px, and comes from the seed for a known agent, so it is not asserted here). */
async function expectWith(page: Page, name: string, policy: string) {
  await expect(head(page).locator('b')).toHaveText(name);
  await expect(head(page).locator('.n-talk__policy')).toHaveText(policy);
}
const stopReply = (page: Page) => page.getByRole('button', { name: 'Stop this reply', exact: true });
/** What Send's description points at while it is held. */
const sendWhy = (page: Page) => send(page).evaluate((button) =>
  document.getElementById(button.getAttribute('aria-describedby') || '')?.textContent ?? null);

/** The masthead's Find opens the search and command sheet; `id` is the command run. */
async function runCommand(page: Page, query: string, id: string) {
  await page.getByRole('button', { name: /^Search or run a command/ }).click();
  const sheet = page.getByRole('dialog', { name: 'Search or run a command' });
  await expect(sheet).toBeVisible();
  await sheet.getByRole('combobox').fill(query);
  await sheet.locator(`[data-command="${id}"]`).click();
  await expect(sheet).toBeHidden();
}

async function sendMessage(page: Page, text: string) {
  await field(page).fill(text);
  await field(page).press('Enter');
}

test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'home-registers', 'manual lane: npx playwright test -c playwright.home-registers.config.ts');
  await page.addInitScript(() => {
    try { localStorage.setItem('hud.firstrun.dismissed', '1'); localStorage.setItem('hud.seen', '1'); } catch { /* ignore */ }
  });
  await page.setViewportSize({ width: 1440, height: 900 });
});

test('a refused recipient: says why, holds Send and sends nothing, and still lets the owner choose', async ({ page }) => {
  const roster = await serveRoster(page);
  const stream = await holdStream(page);
  await page.goto('/v2/chat');
  await expect(to(page)).toBeVisible({ timeout: 20_000 });
  await to(page).selectOption('frigga');
  await expectWith(page, 'Frigga', 'Local');

  // Frigga leaves the hub's roster; the next reading of it says so
  roster.agents = [JARVIS];
  await runCommand(page, 'refresh live data', 'action:refresh');
  const UNAVAILABLE = 'Frigga is not available now. Nothing is sent until you choose who to write to.';
  const line = page.locator('.n-composer__recipient');
  await expect(line).toHaveText(UNAVAILABLE);
  await expect(line).toHaveAttribute('data-recipient-reason', 'unavailable');
  await expect(head(page)).toHaveText('no agent chosen');
  await expect(to(page).locator('option:checked')).toHaveText('Choose an agent');
  await expect(send(page)).toBeDisabled();
  expect(await sendWhy(page)).toBe(UNAVAILABLE);
  // the message goes to no one: not Frigga, and no substitute
  await sendMessage(page, 'Hold this draft');
  await page.waitForTimeout(400);
  expect(stream.asked).toEqual([]);
  await expect(field(page)).toHaveValue('Hold this draft');

  // the roster is then not served at all: still no agent chosen, never "Checking the selected agent…"
  roster.agents = null;
  await runCommand(page, 'refresh live data', 'action:refresh');
  await expect(page.locator('[data-recipient-choices="not-served"]')).toBeVisible();
  await expect(page.getByText('Checking the selected agent…')).toHaveCount(0);
  await expect(line).toHaveText(UNAVAILABLE);
  await expect(head(page)).toHaveText('no agent chosen');
  await expect(send(page)).toBeDisabled();
  // …and the owner can choose: Jarvis, App's default, needs no roster
  await expect(to(page).locator('option')).toHaveText(['Choose an agent', 'Jarvis · Routing policy unknown']);
  await to(page).selectOption('jarvis');
  await expect(head(page)).toHaveText('with Jarvis · Routing policy unknown');
  await expect(field(page)).toBeFocused();
  await expect(send(page)).toBeEnabled();
  await field(page).press('Enter');
  await expect.poll(() => stream.asked).toEqual([{ agent: 'jarvis', message: 'Hold this draft' }]);
  stream.release();
  await expect(page.getByText('Reply to Hold this draft.')).toBeVisible();
});

test('"Write to" while a reply is held: asks first, holds Send, and stops nothing until confirmed', async ({ page }) => {
  await serveRoster(page);
  const stream = await holdStream(page);
  await page.goto('/v2/chat');
  await expect(to(page)).toBeVisible({ timeout: 20_000 });
  await sendMessage(page, 'Think this through');
  await expect(stopReply(page)).toBeVisible();
  expect(stream.asked).toEqual([{ agent: 'jarvis', message: 'Think this through' }]);

  await runCommand(page, 'write to frigga', 'agent:write:frigga');
  const question = page.locator('[data-recipient-switch="frigga"]');
  await expect(question).toHaveAttribute('role', 'alert');
  await expect(question).toContainText('Writing to Frigga stops the reply in progress.');
  // nothing is stopped and the recipient has not changed
  await expect(stopReply(page)).toBeVisible();
  await expect(to(page)).toHaveValue('jarvis');
  expect(stream.aborted).toBe(0);
  // Send waits for the answer and points at it: a message now would still go to Jarvis
  await field(page).fill('For Frigga');
  await expect(send(page)).toBeDisabled();
  expect(await sendWhy(page)).toBe('Writing to Frigga stops the reply in progress.');
  await field(page).press('Enter');
  await page.waitForTimeout(300);
  expect(stream.asked).toHaveLength(1);
  expect(stream.aborted).toBe(0);

  // confirmed: only now is the reply stopped and the recipient changed
  await question.getByRole('button', { name: 'Stop it and write to Frigga', exact: true }).click();
  await expect.poll(() => stream.aborted).toBe(1);
  await expect(to(page)).toHaveValue('frigga');
  await expect(question).toHaveCount(0);
  await expect(stopReply(page)).toHaveCount(0);
  await expectWith(page, 'Frigga', 'Local');
  await expect(send(page)).toBeEnabled();
  await send(page).click();
  await expect.poll(() => stream.asked.length).toBe(2);
  expect(stream.asked[1]).toEqual({ agent: 'frigga', message: 'For Frigga' });
  stream.release();
  await expect(page.getByText('Reply to For Frigga.')).toBeVisible();
});

test('a "Write to" left unanswered stays when the reply ends, after leaving Home and coming back too', async ({ page }) => {
  await serveRoster(page);
  const stream = await holdStream(page);
  await page.goto('/v2/cockpit');
  await expect(to(page)).toBeVisible({ timeout: 20_000 });
  await sendMessage(page, 'Finish first');
  await expect(stopReply(page)).toBeVisible();
  await runCommand(page, 'write to frigga', 'agent:write:frigga');
  const question: Locator = page.locator('[data-recipient-switch="frigga"]');
  await expect(question).toContainText('Writing to Frigga stops the reply in progress.');

  // the owner leaves Home with the question open, and the reply ends meanwhile
  await page.locator('[data-area="trust"]').click();
  await expect(field(page)).toHaveCount(0);
  stream.release();
  await expect.poll(() => stream.delivered).toBe(1);
  await page.locator('[data-area="home"]').click();
  await expect(page.getByText('Reply to Finish first.')).toBeVisible();

  // nothing switched by itself: the same question, reworded without "stops the reply"
  await expect(question).toHaveAttribute('data-recipient-switch-state', 'ended');
  await expect(question).toContainText('The reply from Jarvis has ended. Write to Frigga?');
  await expect(question).not.toContainText('stops the reply');
  await expect(to(page)).toHaveValue('jarvis');
  expect(stream.aborted).toBe(0);
  // Send still waits for the answer, and points at it
  await field(page).fill('Now for Frigga');
  await expect(send(page)).toBeDisabled();
  expect(await sendWhy(page)).toBe('The reply from Jarvis has ended. Write to Frigga?');
  // the reply that ended keeps its Turn details
  const reply = page.locator('[data-turn="reply"]').filter({ hasText: 'Reply to Finish first.' });
  await reply.getByRole('button', { name: 'More actions for this reply', exact: true }).click();
  await reply.getByRole('button', { name: 'Turn details', exact: true }).click();
  await expect(reply.getByLabel('Turn duration', { exact: true })).toContainText('1.25');

  // only the owner's answer changes who is written to
  await question.getByRole('button', { name: 'Write to Frigga', exact: true }).click();
  await expect(to(page)).toHaveValue('frigga');
  await expect(question).toHaveCount(0);
  await expectWith(page, 'Frigga', 'Local');
  await expect(send(page)).toBeEnabled();
  expect(stream.asked).toEqual([{ agent: 'jarvis', message: 'Finish first' }]);
});

test('a reading of the roster that fails keeps the "Write to" question: Send stays held, and only its switch waits', async ({ page }) => {
  const roster = await serveRoster(page);
  const stream = await holdStream(page);
  await page.goto('/v2/chat');
  await expect(to(page)).toBeVisible({ timeout: 20_000 });
  await sendMessage(page, 'Think this through');
  await expect(stopReply(page)).toBeVisible();
  await runCommand(page, 'write to frigga', 'agent:write:frigga');
  const question = page.locator('[data-recipient-switch="frigga"]');
  await expect(question).toContainText('Writing to Frigga stops the reply in progress.');

  // one reading of the roster is refused: the page builds its rows from /status instead
  roster.agents = null;
  await runCommand(page, 'refresh live data', 'action:refresh');
  await expect(head(page).locator('.n-talk__policy[data-policy="not-served"]')).toHaveText('Routing policy unknown');
  // the question stays; its switch waits and says why; nothing is stopped
  await expect(question).toHaveAttribute('data-recipient-switch-held', '');
  const take = question.getByRole('button', { name: 'Stop it and write to Frigga', exact: true });
  await expect(take).toBeDisabled();
  await expect(question.locator('.n-composer__held'))
    .toHaveText('The hub did not serve the agent roster, so Frigga cannot be chosen until it does.');
  await expect(stopReply(page)).toBeVisible();
  // Send stays held and points at the question: a message now would go to Jarvis, whom the owner asked to replace
  await field(page).fill('For Frigga');
  await expect(send(page)).toBeDisabled();
  expect(await sendWhy(page)).toBe('Writing to Frigga stops the reply in progress.');
  await field(page).press('Enter');
  await page.waitForTimeout(300);
  expect(stream.asked).toEqual([{ agent: 'jarvis', message: 'Think this through' }]);
  expect(stream.aborted).toBe(0);

  // the roster is served again, Frigga in it: the owner's answer is taken
  roster.agents = [JARVIS, FRIGGA];
  await runCommand(page, 'refresh live data', 'action:refresh');
  await expect(take).toBeEnabled();
  await expect(question).not.toHaveAttribute('data-recipient-switch-held');
  await expect(question.locator('.n-composer__held')).toHaveCount(0);
  await take.click();
  await expect.poll(() => stream.aborted).toBe(1);
  await expect(to(page)).toHaveValue('frigga');
  await expect(question).toHaveCount(0);
  await expectWith(page, 'Frigga', 'Local');
  await expect(send(page)).toBeEnabled();
  await send(page).click();
  await expect.poll(() => stream.asked.length).toBe(2);
  expect(stream.asked[1]).toEqual({ agent: 'frigga', message: 'For Frigga' });
  stream.release();
  await expect(page.getByText('Reply to For Frigga.')).toBeVisible();
});

test('a question held for the roster names the agent as the hub\'s roster last named it', async ({ page }) => {
  const roster = await serveRoster(page);
  roster.agents = [JARVIS, { ...FRIGGA, name: 'Frigga Allmother' }];
  await holdStream(page);
  await page.goto('/v2/chat');
  await expect(to(page)).toBeVisible({ timeout: 20_000 });
  await sendMessage(page, 'Think this through');
  await expect(stopReply(page)).toBeVisible();
  await runCommand(page, 'write to frigga', 'agent:write:frigga');
  const question = page.locator('[data-recipient-switch="frigga"]');
  await expect(question).toContainText('Writing to Frigga Allmother stops the reply in progress.');
  // a reading of the roster that fails: the rows the page falls back to do not carry the hub's name
  roster.agents = null;
  await runCommand(page, 'refresh live data', 'action:refresh');
  await expect(question).toHaveAttribute('data-recipient-switch-held', '');
  await expect(question.locator('.n-composer__held'))
    .toHaveText('The hub did not serve the agent roster, so Frigga Allmother cannot be chosen until it does.');
  await expect(question).toContainText('Writing to Frigga Allmother stops the reply in progress.');
  await expect(question.getByRole('button', { name: 'Stop it and write to Frigga Allmother', exact: true })).toBeDisabled();
  expect(await sendWhy(page)).toBe('Writing to Frigga Allmother stops the reply in progress.');
});

test('a question dropped because the served roster no longer offers the agent says why, until the next send', async ({ page }) => {
  const roster = await serveRoster(page);
  const stream = await holdStream(page);
  await page.goto('/v2/chat');
  await expect(to(page)).toBeVisible({ timeout: 20_000 });
  await sendMessage(page, 'Think this through');
  await expect(stopReply(page)).toBeVisible();
  await runCommand(page, 'write to frigga', 'agent:write:frigga');
  const question = page.locator('[data-recipient-switch="frigga"]');
  await expect(question).toContainText('Writing to Frigga stops the reply in progress.');
  // Frigga leaves the roster the hub serves: the question goes, and a line says why
  roster.agents = [JARVIS];
  await runCommand(page, 'refresh live data', 'action:refresh');
  await expect(question).toHaveCount(0);
  const dropped = page.locator('[data-recipient-dropped="frigga"]');
  await expect(dropped).toHaveAttribute('role', 'status');
  await expect(dropped).toContainText('Frigga is not available now, so the change to Frigga was dropped. Messages still go to Jarvis.');
  // nothing was stopped or switched, and Send is free once the reply ends: the next send ends the line
  expect(stream.aborted).toBe(0);
  await expect(to(page)).toHaveValue('jarvis');
  stream.release();
  await expect(page.getByText('Reply to Think this through.')).toBeVisible();
  await field(page).fill('Still Jarvis');
  await expect(send(page)).toBeEnabled();
  await field(page).press('Enter');
  await expect.poll(() => stream.asked.length).toBe(2);
  expect(stream.asked[1]).toEqual({ agent: 'jarvis', message: 'Still Jarvis' });
  await expect(dropped).toHaveCount(0);
  stream.release();
});

test('a saved recipient the hub never serves the roster for: says why, offers Jarvis, and is confirmed once served', async ({ page }) => {
  const roster = await serveRoster(page);
  const stream = await holdStream(page);
  await page.goto('/v2/chat');
  await expect(to(page)).toBeVisible({ timeout: 20_000 });
  await to(page).selectOption('frigga');
  await expectWith(page, 'Frigga', 'Local');
  // the choice is kept for this tab (with the credential that made it); the tab is reloaded while the
  // hub does not serve the roster, and it never does until the end of the test
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem('nerva.chat.recipient') || 'null')?.credential?.length ?? 0)).toBe(64);
  roster.agents = null;
  await page.reload();
  const HELD = 'The hub did not serve the agent roster, so Frigga cannot be confirmed until it does. Nothing is sent until then, unless you choose Jarvis.';
  const line = page.locator('.n-composer__recipient');
  await expect(line).toHaveText(HELD, { timeout: 20_000 });
  await expect(line).toHaveAttribute('data-recipient-state', 'unconfirmed');
  await expect(page.getByText('Checking the selected agent…')).toHaveCount(0);
  await expect(head(page)).toHaveText('with Frigga · not confirmed');
  await expect(to(page).locator('option')).toHaveText(['Frigga · not confirmed', 'Jarvis · Routing policy unknown']);
  await expect(send(page)).toBeDisabled();
  expect(await sendWhy(page)).toBe(HELD);
  await sendMessage(page, 'Wait for Frigga');
  await page.waitForTimeout(400);
  expect(stream.asked).toEqual([]);
  // another reading without the roster: nothing switches by itself, and the choice is kept
  await runCommand(page, 'refresh live data', 'action:refresh');
  await expect(line).toHaveText(HELD);
  await expect(to(page)).toHaveValue('');
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('nerva.chat.recipient') || 'null')?.agent)).toBe('frigga');
  // the hub serves the roster again, Frigga in it: the saved choice is confirmed
  roster.agents = [JARVIS, FRIGGA];
  await runCommand(page, 'refresh live data', 'action:refresh');
  await expect(to(page)).toHaveValue('frigga');
  await expectWith(page, 'Frigga', 'Local');
  await expect(line).toHaveCount(0);
  await expect(send(page)).toBeEnabled();
  await field(page).press('Enter');
  await expect.poll(() => stream.asked).toEqual([{ agent: 'frigga', message: 'Wait for Frigga' }]);
  stream.release();
  await expect(page.getByText('Reply to Wait for Frigga.')).toBeVisible();
});
