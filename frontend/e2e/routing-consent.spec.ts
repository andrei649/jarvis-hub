/* Two real turns in one Ledger conversation. The fixture confines both model
   transports to loopback; this spec never replaces the roster or chat stream. */
import { expect, test, type Page, type Response } from '@playwright/test';

type ModelCall = { provider: string; model: string };
type End = { type: 'end'; agent: string; text: string; session_id: string | null; model_calls?: ModelCall[] };
type Routing = { local: { count: number; model: string | null }; cloud: { count: number; model: string | null; paths: string[]; current_turn_seen: boolean; prior_user_seen: boolean; prior_reply_seen: boolean } };

const adminHeaders = { 'X-User-Token': 'route-proof-user', 'X-Admin-Token': 'route-proof-admin' };
const to = (page: Page) => page.getByRole('combobox', { name: 'To', exact: true });
const field = (page: Page) => page.locator('[data-composer]');
const send = (page: Page) => page.locator('[data-composer-send]');
const visibleWords = (text: string) => text.replace(/[^\p{L}\p{N}]/gu, '').toLowerCase();

async function routing(page: Page): Promise<Routing> {
  const response = await page.request.get('/__test/routing', { headers: adminHeaders });
  expect(response.status()).toBe(200);
  return await response.json() as Routing;
}

async function ask(page: Page, prompt: string): Promise<{ request: { agent: string; session_id?: string }; end: End }> {
  const incoming = page.waitForResponse((response: Response) =>
    response.request().method() === 'POST' && new URL(response.url()).pathname === '/chat/stream');
  await field(page).fill(prompt);
  await send(page).click();
  const response = await incoming;
  expect(response.status()).toBe(200);
  const request = response.request().postDataJSON() as { agent: string; session_id?: string };
  const frames = (await response.text()).split(/\r?\n/)
    .filter(line => line.startsWith('data: '))
    .map(line => JSON.parse(line.slice(6)) as { type: string });
  expect(frames.some(frame => frame.type === 'error')).toBe(false);
  const end = frames.find(frame => frame.type === 'end') as End | undefined;
  expect(end, 'the real stream ends with a receipt').toBeDefined();
  return { request, end: end! };
}

test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'routing-consent', 'isolated routing-consent lane only');
  await page.addInitScript(() => {
    localStorage.setItem('hud.firstrun.dismissed', '1');
    localStorage.setItem('hud.seen', '1');
  });
});

test('a local Frigga turn and a consented cloud Athena turn keep one chat with distinct receipts', async ({ page }, testInfo) => {
  const initial = await routing(page);
  expect(initial.local.count).toBe(0);
  expect(initial.cloud.count).toBe(0);

  await page.goto('/v2/chat');
  await expect(to(page)).toBeVisible();
  await to(page).selectOption('frigga');
  await expect(to(page)).toHaveValue('frigga');
  const first = await ask(page, 'Synthetic local route proof, first turn.');
  expect(first.request.agent).toBe('frigga');
  expect(first.request.session_id).toEqual(expect.any(String));
  expect(first.end.agent).toBe('frigga');
  expect(first.end.session_id).toEqual(expect.any(String));
  expect(first.end.session_id).toBe(first.request.session_id);
  expect(first.end.text.trim()).not.toBe('');
  const localWire = await routing(page);
  expect(localWire.local.count).toBeGreaterThan(0);
  expect(localWire.cloud.count).toBe(0);
  expect(first.end.model_calls).toContainEqual({ provider: 'lm-studio', model: localWire.local.model });
  const localReply = page.locator('[data-turn="reply"]').first();
  await expect.poll(async () => visibleWords(await localReply.locator('[data-turn-body]').textContent() || '')).toBe(visibleWords(first.end.text));
  await expect(localReply.locator('[data-footnote]')).toHaveAttribute('data-marker', 'localRunner');
  await expect(localReply.locator('[data-footnote]')).toContainText(localWire.local.model!);

  // The real administrator route first refuses the key without data-policy
  // acknowledgement; no cloud generation can occur during that refusal.
  const refused = await page.request.put('/api/admin/integrations/model.gemini/key', {
    headers: adminHeaders, data: { value: 'fixture-synthetic-key' },
  });
  expect(refused.status()).toBe(409);
  expect(await refused.json()).toMatchObject({ error: 'selection_guard', needs: ['acknowledge_training'] });
  expect((await routing(page)).cloud.count).toBe(0);

  // The same shipped route audits explicit consent before storing the synthetic
  // key or updating the live router.
  const consent = await page.request.put('/api/admin/integrations/model.gemini/key', {
    headers: adminHeaders,
    data: { value: 'fixture-synthetic-key', acknowledge_training: true },
  });
  expect(consent.status(), await consent.text()).toBe(200);
  expect((await routing(page)).cloud.count).toBe(0);

  await to(page).selectOption('athena');
  await expect(to(page)).toHaveValue('athena');
  const second = await ask(page, 'Synthetic consented cloud route proof, second turn.');
  expect(second.request.agent).toBe('athena');
  expect(second.request.session_id).toBe(first.end.session_id);
  expect(second.end.agent).toBe('athena');
  expect(second.end.session_id).toBe(first.end.session_id);
  expect(second.end.text.trim()).not.toBe('');
  const cloudWire = await routing(page);
  expect(cloudWire.cloud.count).toBeGreaterThan(0);
  expect(cloudWire.cloud.current_turn_seen, 'the real cloud protocol request contains the consented turn').toBe(true);
  testInfo.annotations.push({ type: 'observed prior local user turn in cloud request', description: String(cloudWire.cloud.prior_user_seen) });
  testInfo.annotations.push({ type: 'observed prior local reply in cloud request', description: String(cloudWire.cloud.prior_reply_seen) });
  console.info(`Observed prior local user/reply in cloud request: ${cloudWire.cloud.prior_user_seen}/${cloudWire.cloud.prior_reply_seen}`);
  expect(second.end.model_calls).toContainEqual({ provider: 'gemini', model: cloudWire.cloud.model });
  await expect(page.locator('[data-turn="owner"]')).toHaveCount(2);
  await expect(page.locator('[data-turn="reply"]')).toHaveCount(2);
  const cloudReply = page.locator('[data-turn="reply"]').nth(1);
  await expect.poll(async () => visibleWords(await cloudReply.locator('[data-turn-body]').textContent() || '')).toBe(visibleWords(second.end.text));
  await expect(cloudReply.locator('[data-footnote]')).toHaveAttribute('data-marker', 'cloud');
  await expect(cloudReply.locator('[data-footnote]')).toContainText(cloudWire.cloud.model!);
  await expect(localReply.locator('[data-footnote]')).toHaveAttribute('data-marker', 'localRunner');
});
