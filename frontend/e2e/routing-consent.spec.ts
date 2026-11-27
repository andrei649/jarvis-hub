/* Two real turns in one Ledger conversation. The fixture confines both model
   transports to loopback; this spec never replaces the roster or chat stream. */
import { expect, test, type Page, type Response } from '@playwright/test';

type ModelCall = { provider: string; model: string };
type End = { type: 'end'; agent: string; text: string; session_id: string | null; model_calls?: ModelCall[] };
type CloudObservation = { current_turn_seen: boolean; prior_user_seen: boolean; prior_reply_seen: boolean; unrelated_session_seen: boolean };
type Routing = { local: { count: number; model: string | null }; cloud: { count: number; model: string | null; paths: string[]; requests: CloudObservation[] } };

const adminHeaders = { 'X-User-Token': 'route-proof-user', 'X-Admin-Token': 'route-proof-admin' };
const to = (page: Page) => page.getByRole('combobox', { name: 'To', exact: true });
const field = (page: Page) => page.locator('[data-composer]');
const send = (page: Page) => page.locator('[data-composer-send]');
const visibleWords = (text: string) => text.replace(/[^\p{L}\p{N}]/gu, '').toLowerCase();

async function routing(page: Page, expectedReply = ''): Promise<Routing> {
  const response = await page.request.get(`/__test/routing?expected_reply=${encodeURIComponent(expectedReply)}`, { headers: adminHeaders });
  expect(response.status()).toBe(200);
  return await response.json() as Routing;
}

async function streamAfter(page: Page, action: () => Promise<void>): Promise<{ request: { agent: string; session_id?: string; cloud_history?: unknown }; end: End }> {
  const incoming = page.waitForResponse((response: Response) =>
    response.request().method() === 'POST' && new URL(response.url()).pathname === '/chat/stream');
  await action();
  const response = await incoming;
  expect(response.status()).toBe(200);
  const request = response.request().postDataJSON() as { agent: string; session_id?: string; cloud_history?: unknown };
  const frames = (await response.text()).split(/\r?\n/)
    .filter(line => line.startsWith('data: '))
    .map(line => JSON.parse(line.slice(6)) as { type: string });
  expect(frames.some(frame => frame.type === 'error')).toBe(false);
  const end = frames.find(frame => frame.type === 'end') as End | undefined;
  expect(end, 'the real stream ends with a receipt').toBeDefined();
  return { request, end: end! };
}
const ask = (page: Page, prompt: string) => streamAfter(page, async () => {
  await field(page).fill(prompt);
  await send(page).click();
});

test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'routing-consent', 'isolated routing-consent lane only');
  await page.addInitScript(() => {
    localStorage.setItem('hud.firstrun.dismissed', '1');
    localStorage.setItem('hud.seen', '1');
  });
});

test('cloud history is current-only by default, then includes the reviewed session only', async ({ page }) => {
  const initial = await routing(page);
  expect(initial.local.count).toBe(0);
  expect(initial.cloud.count).toBe(0);

  await page.goto('/v2/chat');
  await expect(to(page)).toBeVisible();
  await to(page).selectOption('frigga');
  await expect(to(page)).toHaveValue('frigga');
  const unrelated = await ask(page, 'UNRELATED SESSION SENTINEL');
  expect(unrelated.end.session_id).toEqual(expect.any(String));
  const fresh = await ask(page, '/new');
  expect(fresh.end.session_id).toEqual(expect.any(String));
  expect(fresh.end.session_id).not.toBe(unrelated.end.session_id);
  // A new chat drops the chosen recipient by design; choose Frigga again before its first turn.
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
  const localReply = page.locator('[data-turn="reply"]').filter({ has: page.locator('[data-footnote][data-marker="localRunner"]') });
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
  expect(second.request.cloud_history).toBeUndefined();
  expect(second.end.agent).toBe('athena');
  expect(second.end.session_id).toBe(first.end.session_id);
  expect(second.end.text.trim()).not.toBe('');
  const cloudWire = await routing(page, first.end.text);
  expect(cloudWire.cloud.count).toBeGreaterThan(0);
  expect(cloudWire.cloud.requests).toHaveLength(1);
  expect(cloudWire.cloud.requests[0]).toEqual({ current_turn_seen: true, prior_user_seen: false,
    prior_reply_seen: false, unrelated_session_seen: false });
  expect(second.end.model_calls).toContainEqual({ provider: 'gemini', model: cloudWire.cloud.model });
  await expect(page.locator('[data-turn="owner"]')).toHaveCount(2);
  await expect(page.locator('[data-turn="reply"]')).toHaveCount(3); // /new leaves its command receipt in the fresh chat
  const cloudReply = page.locator('[data-turn="reply"]').filter({ has: page.locator('[data-footnote][data-marker="cloud"]') });
  await expect.poll(async () => visibleWords(await cloudReply.locator('[data-turn-body]').textContent() || '')).toBe(visibleWords(second.end.text));
  await expect(cloudReply.locator('[data-footnote]')).toHaveAttribute('data-marker', 'cloud');
  await expect(cloudReply.locator('[data-footnote]')).toContainText(cloudWire.cloud.model!);
  await expect(localReply.locator('[data-footnote]')).toHaveAttribute('data-marker', 'localRunner');

  const thirdPrompt = 'Include earlier turns for this question.';
  await field(page).fill(thirdPrompt);
  const previewResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/chat/cloud-history/preview');
  await page.getByRole('button', { name: 'Review earlier turns' }).click();
  const preview = await previewResponse;
  expect(preview.status()).toBe(200);
  expect(preview.request().postDataJSON()).toEqual({ session_id: first.end.session_id, agent: 'athena', message: thirdPrompt });
  const review = page.getByRole('dialog', { name: 'Send earlier turns' });
  await expect(review).toContainText(`${cloudWire.cloud.model}`);
  expect((await routing(page)).cloud.count).toBe(1);
  await review.getByRole('button', { name: 'Cancel' }).click();
  await expect(field(page)).toHaveValue(thirdPrompt);
  expect((await routing(page)).cloud.count).toBe(1);

  const nextPreviewResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/chat/cloud-history/preview');
  await page.getByRole('button', { name: 'Review earlier turns' }).click();
  const nextPreview = await nextPreviewResponse;
  expect(nextPreview.status()).toBe(200);
  const grant = await nextPreview.json() as { session_id: string; agent: string; provider: string; model: string; revision: string };
  await expect(review).toContainText(`${grant.provider} / ${grant.model}`);
  expect((await routing(page)).cloud.count).toBe(1);
  const third = await streamAfter(page, () => review.getByRole('button', { name: 'Include and send' }).click());
  expect(third.request.cloud_history).toEqual(grant);
  expect(third.request.session_id).toBe(first.end.session_id);
  expect(third.end.session_id).toBe(first.end.session_id);
  expect(third.end.model_calls).toContainEqual({ provider: 'gemini', model: grant.model });
  const after = await routing(page, first.end.text);
  expect(after.cloud.requests).toHaveLength(2);
  expect(after.cloud.requests[1].prior_user_seen).toBe(true);
  expect(after.cloud.requests[1].prior_reply_seen).toBe(true);
  expect(after.cloud.requests[1].unrelated_session_seen).toBe(false);
});
