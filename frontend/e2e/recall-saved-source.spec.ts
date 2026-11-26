/* Opt-in native acceptance: a reviewed chat fact is recalled in a later real local
   reply, and the reply's source finder opens the exact retained owner turn. Run
   only against a dedicated, synthetic, loopback hub with a real local model. */
import { randomBytes } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';

const enabled = process.env.NERVA_RUN_RECALL_SOURCE_ACCEPTANCE === '1';
const streamPath = '/chat/stream';
const entriesPath = '/api/dashboard/today/entries';
const sessionKey = 'nerva.chat.session_id';

type StreamEnd = {
  type: string;
  text?: string;
  session_id?: string;
  model_calls?: Array<{ provider?: string; model?: string }>;
};
type Source = { session_id: string; turn: number; role: string; revision: string };

function endFrame(response: string): StreamEnd {
  const frames = response.split(/\r?\n/).filter(line => line.startsWith('data: '))
    .map(line => JSON.parse(line.slice(6)) as StreamEnd);
  const end = frames.reverse().find(frame => frame.type === 'end');
  expect(end, 'the real chat stream must finish with an end frame').toBeDefined();
  return end!;
}

async function send(page: Page, message: string, model?: string): Promise<StreamEnd> {
  const pending = page.waitForResponse(response =>
    new URL(response.url()).pathname === streamPath && response.request().method() === 'POST');
  await page.locator('[data-composer]').fill(message);
  await page.locator('[data-composer-send]').click();
  const response = await pending;
  expect(response.status(), `chat request for ${message.slice(0, 30)}`).toBe(200);
  expect(response.request().headers()['x-admin-token']).toBeUndefined();
  expect(response.request().headers()['x-csrf-token'], 'ordinary chat uses the real owner session').toBeTruthy();
  const posted = response.request().postDataJSON() as Record<string, unknown>;
  expect(posted.message).toBe(message);
  expect(posted.attachments).toBeUndefined();
  expect(posted.history_reference).toBeUndefined();
  expect(posted.board_references).toBeUndefined();
  const end = endFrame(await response.text());
  expect(end.session_id).toMatch(/^[A-Za-z0-9_-]{1,128}$/);
  if (model) {
    expect(end.model_calls, 'a local generation receipt is required').toEqual(
      [{ provider: 'ollama', model }]);
    expect(end.text?.trim()).toBeTruthy();
    await expect(page.locator('[data-turn="reply"] [data-turn-body]').last()).toBeVisible();
  }
  return end;
}

test('real local recall opens its saved owner source and forgets for a fresh chat', async ({ page }, testInfo) => {
  test.skip(!enabled, 'run only in the isolated native memory acceptance lane');
  test.setTimeout(420_000);

  const base = testInfo.project.use.baseURL;
  const token = process.env.NERVA_MEMORY_ADMIN_TOKEN;
  const model = process.env.NERVA_MEMORY_MODEL;
  const vaultMarker = process.env.NERVA_MEMORY_VAULT_MARKER;
  expect(typeof base).toBe('string');
  const origin = new URL(base!);
  // 127.0.0.2 stays on loopback, while the HUD treats it as a networked owner
  // browser and uses its regular signed-in cookie and CSRF path.
  expect(origin.protocol).toBe('https:');
  expect(origin.hostname).toBe('127.0.0.2');
  expect(origin.port).not.toBe('8080');
  expect(Number(origin.port)).toBeGreaterThan(1024);
  expect(token).toBeTruthy();
  expect(model).toBeTruthy();
  expect(vaultMarker).toMatch(/^[A-Za-z0-9_-]{8,80}$/);

  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.origin === origin.origin ? route.continue() : route.abort();
  });
  await page.addInitScript(() => {
    localStorage.setItem('hud.firstrun.dismissed', '1');
    localStorage.setItem('hud.lang', 'en');
  });

  // The real cookie is shared with this browser context. The HUD then hydrates
  // owner-session.ts itself and sends the server-issued CSRF on ordinary turns.
  const login = await page.request.post('/api/auth/login', {
    headers: { Origin: origin.origin, 'Content-Type': 'application/json' },
    data: { secret: token },
  });
  expect(login.status()).toBe(200);
  const loginBody = await login.json() as { signed_in?: boolean; csrf?: string };
  expect(loginBody.signed_in).toBe(true);
  expect(loginBody.csrf).toMatch(/^[A-Za-z0-9_-]{16,}$/);
  const session = await page.request.get('/api/auth/session', { headers: { Origin: origin.origin } });
  expect(session.status()).toBe(200);
  expect((await session.json()).signed_in).toBe(true);

  await page.goto('/v2/chat');
  await expect(page.getByTestId('owner-session-chip')).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('[data-composer]')).toBeVisible({ timeout: 20_000 });
  const memory = await page.request.get('/api/memory', { headers: { 'X-Admin-Token': token! } });
  expect(memory.status()).toBe(200);
  expect((await memory.json()).injected, 'automatic memory must be enabled on this isolated hub').toBe(true);

  const code = `HERON${randomBytes(5).toString('hex').toUpperCase()}`;
  const ownerWords = `For this temporary sample project, the codename I chose is ${code}. Please acknowledge it.`;
  const fact = `My project codename is ${code}.`;
  const question = 'What is the project codename I told you?';
  expect(question).not.toContain(code);

  // Chat A: the owner says the fact in ordinary chat, then saves it from that exact turn.
  const first = await send(page, ownerWords, model);
  const sessionA = first.session_id!;
  const ownerTurn = page.locator('[data-turn="owner"]').filter({ hasText: ownerWords }).first();
  await expect(ownerTurn).toBeVisible();
  await ownerTurn.getByRole('button', { name: 'More actions for your message' }).click();
  await ownerTurn.getByRole('button', { name: 'Remember message' }).click();
  const remember = page.getByRole('dialog', { name: 'Remember message' });
  await remember.getByLabel('Save in').selectOption('user');
  await remember.getByLabel('Fact to save').fill(fact);
  const transcriptRead = page.waitForResponse(response => new URL(response.url()).pathname ===
    `/sessions/${sessionA}/transcript` && response.url().includes('references=true'));
  const saved = page.waitForResponse(response => new URL(response.url()).pathname === entriesPath
    && response.request().method() === 'POST');
  await remember.getByRole('button', { name: 'Save fact', exact: true }).click();
  const sourceResponse = await transcriptRead;
  expect(sourceResponse.status()).toBe(200);
  const transcript = await sourceResponse.json() as { session_id: string; turns: Array<{ turn: number; role: string; content: string; reference_revision: string }> };
  expect(transcript.session_id).toBe(sessionA);
  const original = transcript.turns.filter(turn => turn.role === 'user' && turn.content === ownerWords);
  expect(original).toHaveLength(1);
  const saveResponse = await saved;
  expect(saveResponse.status()).toBe(200);
  const saveBody = await saveResponse.json() as { ok: boolean; changed: boolean; entry: { entry_id: string; store: string; value: string; source: Source } };
  expect(saveBody).toMatchObject({ ok: true, changed: true, entry: { store: 'user', value: fact } });
  const entry = saveBody.entry;
  expect(entry.entry_id).toMatch(/^memory:user:[0-9a-f]{16}$/);
  expect(entry.source).toEqual({ session_id: sessionA, turn: original[0].turn,
    role: 'user', revision: original[0].reference_revision });
  expect(entry.source.revision).toMatch(/^[0-9a-f]{64}$/);
  await remember.getByRole('button', { name: 'Close' }).click();

  // Chat B begins through the real command. Its plain question contains no code or source hint.
  const resetB = await send(page, '/new');
  const sessionB = resetB.session_id!;
  expect(sessionB).not.toBe(sessionA);
  await expect.poll(() => page.evaluate(key => sessionStorage.getItem(key), sessionKey)).toBe(sessionB);
  const second = await send(page, question, model);
  expect(second.session_id).toBe(sessionB);
  const returnedCode = second.text?.match(/HERON[0-9A-F]{10}/)?.[0];
  expect(returnedCode, 'the later real model reply must recall the randomized code').toBe(code);

  const reply = page.locator('[data-turn="reply"]').filter({ hasText: code }).last();
  await reply.getByRole('button', { name: 'More actions for this reply' }).click();
  const lookupRequests: Array<{ method: string; path: string }> = [];
  const recordLookup = (req: { method(): string; url(): string }) => {
    const url = new URL(req.url());
    if (url.origin === origin.origin) lookupRequests.push({ method: req.method(), path: url.pathname });
  };
  page.on('request', recordLookup);
  await reply.getByRole('button', { name: 'Find saved source' }).click();
  const finder = page.getByRole('dialog', { name: 'Find saved source' });
  await expect(finder).toBeVisible();
  await finder.getByRole('textbox', { name: 'Exact phrase from this reply' }).fill(returnedCode!);
  await expect(finder.getByText('Matching saved facts')).toBeVisible();
  await expect(finder.getByText(fact, { exact: true })).toHaveCount(1);
  await expect(finder.getByRole('button', { name: 'Open original' })).toHaveCount(1);
  const originalRead = page.waitForResponse(response => new URL(response.url()).pathname ===
    `/sessions/${sessionA}/transcript` && response.url().includes('references=true'));
  await finder.getByRole('button', { name: 'Open original' }).click();
  const opened = await originalRead;
  expect(opened.status()).toBe(200);
  const reopened = await opened.json() as typeof transcript;
  expect(reopened.session_id).toBe(sessionA);
  expect(reopened.turns.find(turn => turn.turn === entry.source.turn)).toMatchObject({
    role: 'user', content: ownerWords, reference_revision: entry.source.revision,
  });
  await expect(finder.getByText(ownerWords, { exact: true })).toBeVisible();
  page.off('request', recordLookup);
  expect(lookupRequests.some(req => req.path === streamPath), 'source lookup must not call a model').toBe(false);
  expect(lookupRequests.filter(req => req.path.startsWith('/api/dashboard/today/entries')
    || req.path.startsWith('/sessions/')).every(req => req.method === 'GET'),
  'source lookup must only read saved facts and retained chat').toBe(true);
  await finder.getByRole('button', { name: 'Close' }).click();

  // The same synthetic profile has an actual indexed Obsidian note, found by the composer.
  await page.locator('[data-composer]').fill('Where is the glass heron calibration code recorded?');
  await page.locator('[data-talk-menu="attach"] button').first().click();
  const vaultRead = page.waitForResponse(response => new URL(response.url()).pathname === '/api/os/brain/retrieve');
  await page.getByRole('button', { name: 'Find vault notes' }).click();
  const vaultResponse = await vaultRead;
  expect(vaultResponse.status()).toBe(200);
  const vault = await vaultResponse.json() as { ok: boolean; attachments: Array<{ name: string; text: string }> };
  expect(vault.ok).toBe(true);
  expect(vault.attachments.some(note => note.name.endsWith('Calibration.md') && note.text.includes(vaultMarker!))).toBe(true);
  await expect(page.getByRole('region', { name: 'Obsidian note excerpts' }).getByText(vaultMarker!, { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Close vault notes' }).click();
  await page.locator('[data-composer]').fill('');

  // Forget only the fact this test created. A third real chat must start without it.
  const forgotten = await page.request.delete(`${entriesPath}/${encodeURIComponent(entry.entry_id)}`, {
    headers: { 'X-Admin-Token': token! },
  });
  expect(forgotten.status()).toBe(200);
  expect(await forgotten.json()).toMatchObject({ ok: true, deleted: entry.entry_id, store: 'user' });
  const facts = await page.request.get(`${entriesPath}?store=user&references=true`, { headers: { 'X-Admin-Token': token! } });
  expect(facts.status()).toBe(200);
  expect((await facts.json() as { entries: Array<{ entry_id: string }> }).entries.some(item => item.entry_id === entry.entry_id)).toBe(false);
  const resetC = await send(page, '/new');
  const sessionC = resetC.session_id!;
  expect(sessionC).not.toBe(sessionB);
  expect(sessionC).not.toBe(sessionA);
  const third = await send(page, question, model);
  expect(third.session_id).toBe(sessionC);
  expect(third.text).not.toContain(code);
  await expect(page.locator('[data-turn="reply"] [data-turn-body]').last()).not.toContainText(code);
});
