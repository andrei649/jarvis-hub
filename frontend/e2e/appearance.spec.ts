import { expect, test, type Page } from '@playwright/test';
const defaults={accent:'cyan',look:'obsidian',density:'normal',motion:'system',scanline:'on',dotgrid:'off'};
const headers={'X-User-Token':'h130-isolated-test-token'};

/* Since the Ledger cutover the palette is the search and command sheet (PHASE_B_PLAN.md §3.7,
   §8.2 row 35): it opens from the masthead's Find button and keeps the old palette's appearance
   rows word for word, listed once something is typed. The values asserted are unchanged. */
const SHEET = 'Search or run a command';
/** Opens the sheet from Find and types a row's own words; returns that row. */
async function sheetRow(page: Page, label: string) {
  await page.getByRole('button',{name:/^Search or run a command/}).click();
  const sheet=page.getByRole('dialog',{name:SHEET});
  await expect(sheet).toBeVisible();
  await sheet.getByRole('combobox').fill(label);
  const row=sheet.getByRole('option').filter({has:page.getByText(label,{exact:true})});
  await expect(row).toHaveCount(1);
  return row;
}

for (const prefix of ['', '/one']) {
  test(`appearance follows the owner across browsers at ${prefix || '/'}`, async ({page,browser,baseURL,request}) => {
    await request.put(prefix+'/api/preferences/appearance',{data:defaults});
    // A choice made before the first read lands is sent against no revision: the hub answers 409
    // and the client reads again and resends it (appearance.ts), so the first PUT below would not
    // be the save this test pins. Wait for that read, as an owner choosing after load does; a cold
    // fixture hub answers it after the sheet is already open.
    const hydrated=page.waitForResponse(r=>r.url().endsWith('/api/preferences/appearance') && r.request().method()==='GET');
    await page.goto(prefix+'/v2/chat?demo=1');
    expect((await hydrated).ok()).toBe(true);
    await expect(page.locator('.hud-root')).toHaveAttribute('data-accent','cyan');
    const violet=await sheetRow(page,'Accent · Violet');
    const saved=page.waitForResponse(r=>r.url().endsWith('/api/preferences/appearance') && r.request().method()==='PUT');
    await violet.click();
    expect((await saved).status()).toBe(200);
    await expect(page.getByRole('dialog',{name:SHEET})).toHaveCount(0);
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
      await (await sheetRow(second,'Look · Graphite')).click();
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
  await (await sheetRow(page,'Accent · Violet')).click();
  await expect(page.getByText('Appearance saved on this browser only. Sync failed.')).toBeVisible();
  await (await sheetRow(second,'Look · Graphite')).click();
  await expect(second.getByText('Appearance saved on this browser only. Sync failed.')).toBeVisible();
  await page.close();await second.close();await context.setOffline(false);
  const restored=await context.newPage();await restored.goto('/v2/chat?demo=1');
  await expect(restored.locator('.hud-root')).toHaveAttribute('data-accent','violet');
  await expect(restored.locator('.hud-root')).toHaveAttribute('data-look','graphite');
  await expect.poll(async()=> (await (await request.get('/api/preferences/appearance')).json()).preferences).toMatchObject({accent:'violet',look:'graphite'});
});
