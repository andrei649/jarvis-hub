import { expect, test } from '@playwright/test';
const defaults={accent:'cyan',look:'obsidian',density:'normal',motion:'system',scanline:'on',dotgrid:'off'};
const headers={'X-User-Token':'h130-isolated-test-token'};

for (const prefix of ['', '/one']) {
  test(`appearance follows the owner across browsers at ${prefix || '/'}`, async ({page,browser,baseURL,request}) => {
    await request.put(prefix+'/api/preferences/appearance',{data:defaults});
    await page.goto(prefix+'/v2/chat?demo=1');
    await expect(page.locator('.hud-root')).toHaveAttribute('data-accent','cyan');
    await page.getByTitle('command palette',{exact:true}).click();
    const saved=page.waitForResponse(r=>r.url().endsWith('/api/preferences/appearance') && r.request().method()==='PUT');
    await page.getByText('Accent · Violet',{exact:true}).click();
    expect((await saved).status()).toBe(200);
    await expect(page.locator('.hud-root')).toHaveAttribute('data-accent','violet');
    const fresh=await browser.newContext({baseURL,extraHTTPHeaders:headers,reducedMotion:'reduce'});
    const second=await fresh.newPage();
    try {
      await second.goto(prefix+'/v2/chat?demo=1');
      await expect(second.locator('.hud-root')).toHaveAttribute('data-accent','violet');
      await expect(second.locator('.hud-root')).toHaveAttribute('data-motion','calm');
      await second.evaluate(()=>localStorage.clear());
      await second.reload();
      await expect(second.locator('.hud-root')).toHaveAttribute('data-accent','violet');
      await fresh.setOffline(true);
      await second.getByTitle('command palette',{exact:true}).click();
      await second.getByText('Look · Graphite',{exact:true}).click();
      await expect(second.getByText('Appearance saved on this browser only. Sync failed.')).toBeVisible();
      await expect(second.locator('.hud-root')).toHaveAttribute('data-look','graphite');
      await fresh.setOffline(false);
      // The browser online event retries the durable explicit edit automatically.
      await expect(second.getByText('Appearance saved on this browser only. Sync failed.')).toHaveCount(0);
      await expect.poll(async()=> (await (await request.get(prefix+'/api/preferences/appearance')).json()).preferences.look).toBe('graphite');
      await page.reload();
      await expect(page.locator('.hud-root')).toHaveAttribute('data-look','graphite');
    } finally {await fresh.close();}
  });
}

test('two offline tabs retain different edits after both tabs close, without Web Locks', async ({page,context,request}) => {
  await context.addInitScript(()=>Object.defineProperty(navigator,'locks',{value:undefined,configurable:true}));
  await request.put('/api/preferences/appearance',{data:defaults});
  const second=await context.newPage();
  await page.goto('/v2/chat?demo=1');await second.goto('/v2/chat?demo=1');
  await expect(page.locator('.hud-root')).toHaveAttribute('data-accent','cyan');
  await context.setOffline(true);
  await page.getByTitle('command palette',{exact:true}).click();
  await page.getByText('Accent · Violet',{exact:true}).click();
  await expect(page.getByText('Appearance saved on this browser only. Sync failed.')).toBeVisible();
  await second.getByTitle('command palette',{exact:true}).click();
  await second.getByText('Look · Graphite',{exact:true}).click();
  await expect(second.getByText('Appearance saved on this browser only. Sync failed.')).toBeVisible();
  await page.close();await second.close();await context.setOffline(false);
  const restored=await context.newPage();await restored.goto('/v2/chat?demo=1');
  await expect(restored.locator('.hud-root')).toHaveAttribute('data-accent','violet');
  await expect(restored.locator('.hud-root')).toHaveAttribute('data-look','graphite');
  await expect.poll(async()=> (await (await request.get('/api/preferences/appearance')).json()).preferences).toMatchObject({accent:'violet',look:'graphite'});
});
