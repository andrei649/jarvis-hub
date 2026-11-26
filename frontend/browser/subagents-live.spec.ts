import { expect, test } from '@playwright/test';

test('two genuine manager children appear while batch POST is held; stop one and inspect the other', async ({ page, request }, info) => {
  test.skip(info.project.name !== 'subagents-live', 'manual lane: playwright.subagents-live.config.ts');
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
