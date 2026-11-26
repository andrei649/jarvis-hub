import { expect, test } from '@playwright/test';

test('two genuine manager children appear while batch POST is held; stop one and inspect the other', async ({ page, request }, info) => {
  test.skip(info.project.name !== 'subagents-live' || Boolean(process.env.NERVA_FINISH_PARALLEL_MODEL), 'controlled manual lane');
  await page.addInitScript(() => {
    localStorage.setItem('hud.user_token', 'parallel-hud-user-fixture');
    localStorage.setItem('hud.admin_token', 'parallel-hud-admin-fixture');
    localStorage.setItem('hud.firstrun.dismissed', '1');
  });
  await page.goto('/v2/console/sub-agents');
  const initialCapacity = page.getByText(/^0\/\d+ active$/);
  await expect(initialCapacity).toBeVisible();
  const cap = Number((await initialCapacity.textContent())?.match(/\/(\d+) active/)?.[1]);
  expect(cap).toBeGreaterThanOrEqual(2);

  await page.getByPlaceholder('batch: one task per line (up to 16)').fill('write backup guidance\ncheck a bicycle tire');
  await page.getByTitle('run these tasks as a batch of sub-agents').click();
  await expect(page.getByText('spawning… the connection is held for the whole turn')).toBeVisible();

  const first = page.locator('.n-row').filter({ hasText: 'write backup guidance' }).first();
  const second = page.locator('.n-row').filter({ hasText: 'check a bicycle tire' }).first();
  await expect(first.getByTitle('cancel this running sub-agent')).toBeVisible();
  await expect(second.getByTitle('cancel this running sub-agent')).toBeVisible();
  await expect(page.getByText(`2/${cap} active`)).toBeVisible();

  await first.getByTitle('cancel this running sub-agent').click();
  await expect(first).toContainText('stopped');
  await expect(second.getByTitle('cancel this running sub-agent')).toBeVisible();

  const released = await request.post('/__test/release-b', {
    headers: { 'X-Admin-Token': 'parallel-hud-admin-fixture' },
  });
  expect(released.ok()).toBeTruthy();
  await expect(page.getByText(`0/${cap} active`)).toBeVisible();
  await second.getByTitle('read durable result without claiming delivery').click();
  await expect(second.locator('xpath=following-sibling::*[1]')).toContainText('B genuine bicycle response');
  await expect(first.locator('xpath=following-sibling::*[1]')).not.toContainText('B genuine bicycle response');
});

test('physical Ollama children run in parallel; stopping one leaves the sibling answer durable', async ({ page, request }, info) => {
  const model = process.env.NERVA_FINISH_PARALLEL_MODEL;
  test.skip(info.project.name !== 'subagents-live' || !model, 'opt-in physical Ollama lane');
  const escaped: string[] = [];
  await page.context().route('**/*', async (route) => {
    if (new URL(route.request().url()).origin !== 'http://127.0.0.1:45178') {
      escaped.push(route.request().url());
      await route.abort();
      return;
    }
    await route.continue();
  });
  await page.addInitScript(() => {
    localStorage.setItem('hud.user_token', 'parallel-hud-user-fixture');
    localStorage.setItem('hud.admin_token', 'parallel-hud-admin-fixture');
    localStorage.setItem('hud.firstrun.dismissed', '1');
  });
  await page.goto('/v2/console/sub-agents');
  const capacity = page.getByText(/^0\/\d+ active$/);
  await expect(capacity).toBeVisible();
  const cap = Number((await capacity.textContent())?.match(/\/(\d+) active/)?.[1]);
  expect(cap).toBeGreaterThanOrEqual(2);
  await page.getByPlaceholder('model (optional)').fill(model!);
  const packing = 'Create a detailed numbered packing checklist with 100 distinct items for a synthetic bicycle-parts shipment. Continue until all items are written.';
  const wheels = 'Calculate the number of wheels needed for 17 boxes with 14 wheels in each box. State the exact total and its unit, then give 20 numbered arithmetic checks.';
  expect(packing + wheels).not.toContain('238');
  await page.getByPlaceholder('batch: one task per line (up to 16)').fill(`${packing}\n${wheels}`);
  await page.getByTitle('run these tasks as a batch of sub-agents').click();
  await expect(page.getByText('spawning… the connection is held for the whole turn')).toBeVisible();

  const first = page.locator('.n-row').filter({ hasText: packing.slice(0, 40) }).first();
  const second = page.locator('.n-row').filter({ hasText: wheels.slice(0, 40) }).first();
  await expect(first.getByTitle('cancel this running sub-agent')).toBeVisible();
  await expect(second.getByTitle('cancel this running sub-agent')).toBeVisible();
  await expect(page.getByText(`2/${cap} active`)).toBeVisible();
  const firstId = await first.getByText(/^sub-[\w-]+$/).textContent();
  const secondId = await second.getByText(/^sub-[\w-]+$/).textContent();
  expect(firstId).toBeTruthy();
  expect(secondId).toBeTruthy();
  expect(firstId).not.toBe(secondId);

  await first.getByTitle('cancel this running sub-agent').click();
  await expect(first).toContainText('stopped');
  await expect(second.getByTitle('cancel this running sub-agent')).toBeVisible();
  await expect(page.getByText(`1/${cap} active`)).toBeVisible();
  await expect(second).toContainText('done', { timeout: 240_000 });
  await expect(page.getByText(`0/${cap} active`)).toBeVisible();
  await second.getByTitle('read durable result without claiming delivery').click();
  const shown = second.locator('xpath=following-sibling::*[1]');
  await expect(shown).toContainText('238');
  await expect(shown).toContainText(/wheels?/i);
  await expect(first.locator('xpath=following-sibling::*[1]')).not.toContainText('238');

  const durable = await request.get(`/api/subagents/${secondId}/result`, {
    headers: { 'X-Admin-Token': 'parallel-hud-admin-fixture' },
  });
  expect(durable.ok()).toBeTruthy();
  const row = await durable.json();
  expect(row.spawn_id).toBe(secondId);
  expect(row.status).toBe('done');
  expect(row.result.output).toMatch(/\b238\b/);
  expect(row.result.output).toMatch(/wheels?/i);
  const stopped = await request.get(`/api/subagents/${firstId}/result`, {
    headers: { 'X-Admin-Token': 'parallel-hud-admin-fixture' },
  });
  expect(stopped.ok()).toBeTruthy();
  const stoppedRow = await stopped.json();
  expect(stoppedRow.spawn_id).toBe(firstId);
  expect(stoppedRow.status).toBe('stopped');
  expect(JSON.stringify(stoppedRow.result)).not.toContain('238');
  const physical = await request.get('/__test/physical-generations', {
    headers: { 'X-Admin-Token': 'parallel-hud-admin-fixture' },
  });
  expect(physical.ok()).toBeTruthy();
  expect((await physical.json()).models).toContainEqual({ spawn_id: secondId, model });
  expect(escaped).toEqual([]);
});
