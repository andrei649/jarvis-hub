import {expect,test} from '@playwright/test';

test('real manual request is accepted before offline dispatch and recorded through HUD', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('hud.admin_token','dispatch-fixture-admin'));
  await page.goto('/v2/?demo=1');
  await page.getByRole('button',{name:'Automations',exact:true}).click();
  await expect(page.getByText('Browser receipt reminder',{exact:true})).toBeVisible();
  const accepted = page.waitForResponse(r => r.url().endsWith('/run') && r.request().method() === 'POST');
  await page.getByTitle('run now').click();
  const response = await accepted;
  expect(response.status()).toBe(202);
  const body = await response.json();
  expect(body.request.status).toBe('queued');
  expect(body.run).toBeUndefined();
  await expect(page.getByText(/accepted · queued/)).toBeVisible();
  const before = await page.request.get(`/api/jobs/${body.request.job_id}/runs`,{headers:{'X-Admin-Token':'dispatch-fixture-admin'}});
  expect((await before.json()).runs).toEqual([]);
  await page.getByRole('button',{name:/tick due jobs/}).click();
  await expect(page.getByText('ok · isolated receipt completed',{exact:true})).toBeVisible();
  const history = page.waitForResponse(r => r.url().includes('/runs?limit=5'));
  await page.getByTitle('attempts').click();
  expect((await (await history).json()).runs[0]).toMatchObject({status:'ok',summary:'isolated receipt completed'});
  await expect(page.getByText(/^ok · .* · isolated receipt completed$/)).toBeVisible();
});
