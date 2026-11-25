import { expect, test, type Page } from '@playwright/test';
const headers={'X-User-Token':'h130-isolated-test-token'};

/* Since the Ledger cutover the palette is the search and command sheet (PHASE_B_PLAN.md §3.7,
   §8.2 row 35): it opens from the masthead's Find button and keeps the old palette's appearance
   rows word for word, listed once something is typed. The computed-font assertions (row 34) are
   unchanged. */
/** Opens the sheet from Find and types a row's own words; returns that row. */
async function sheetRow(page: Page, label: string) {
  await page.getByRole('button',{name:/^Search or run a command/}).click();
  const sheet=page.getByRole('dialog',{name:'Search or run a command'});
  await expect(sheet).toBeVisible();
  await sheet.getByRole('combobox').fill(label);
  const row=sheet.getByRole('option').filter({has:page.getByText(label,{exact:true})});
  await expect(row).toHaveCount(1);
  return row;
}

for(const prefix of ['', '/one']) {
  test(`local font choices persist without changing mono at ${prefix || '/'}`,async({page,browser,baseURL,request})=>{
    await request.put(prefix+'/api/preferences/appearance',{data:{font:'theme',look:'obsidian'}});
    // A choice made before the first read lands is sent against no revision: the hub answers 409
    // and the client reads again and resends it (appearance.ts), so the first PUT below would not
    // be the save this test pins. Wait for that read, as an owner choosing after load does.
    const hydrated=page.waitForResponse(r=>r.url().endsWith('/api/preferences/appearance')&&r.request().method()==='GET');
    await page.goto(prefix+'/v2/chat?demo=1');
    expect((await hydrated).ok()).toBe(true);
    const root=page.locator('.hud-root');
    await expect(root).toHaveAttribute('data-font','theme');
    const mono=await root.evaluate(el=>getComputedStyle(el).getPropertyValue('--font-mono'));
    // Exercise the shipped code rule, independently of body font inheritance.
    await root.evaluate(el=>{const block=document.createElement('div');block.className='art-md';block.id='font-code-probe';const code=document.createElement('code');code.textContent='const value = 1';block.append(code);el.append(block);});
    const code=page.locator('#font-code-probe code');
    const codeFont=await code.evaluate(el=>getComputedStyle(el).fontFamily);
    for(const [id, label, family] of [['system-sans','System Sans','system-ui'],['system-serif','System Serif','Georgia'],['system-mono','System Mono','ui-monospace'],['jetbrains-mono','JetBrains Mono','JetBrains Mono'],['theme','Theme Default','Space Grotesk']]) {
      const row=await sheetRow(page,'Font · '+label);
      const saved=page.waitForResponse(r=>r.url().endsWith('/api/preferences/appearance')&&r.request().method()==='PUT');
      await row.click();
      expect((await saved).status()).toBe(200);
      await expect(root).toHaveAttribute('data-font',id);
      expect(await root.evaluate(el=>getComputedStyle(el).fontFamily)).toContain(family);
      expect(await root.evaluate(el=>getComputedStyle(el).getPropertyValue('--font-mono'))).toBe(mono);
      expect(await code.evaluate(el=>getComputedStyle(el).fontFamily)).toBe(codeFont);
    }
    await request.put(prefix+'/api/preferences/appearance',{data:{font:'system-serif'}});
    const fresh=await browser.newContext({baseURL,extraHTTPHeaders:headers});
    try {
      const second=await fresh.newPage();await second.goto(prefix+'/v2/chat?demo=1');
      await expect(second.locator('.hud-root')).toHaveAttribute('data-font','system-serif');
      await (await sheetRow(second,'Look · Graphite')).click();
      await expect(second.locator('.hud-root')).toHaveAttribute('data-look','graphite');
      expect(await second.locator('.hud-root').evaluate(el=>getComputedStyle(el).fontFamily)).toContain('Georgia');
      await fresh.setOffline(true);
      await (await sheetRow(second,'Font · System Mono')).click();
      await expect(second.getByText('Appearance saved on this browser only. Sync failed.')).toBeVisible();
      await fresh.setOffline(false);
      await second.evaluate(()=>window.dispatchEvent(new Event('online')));
      await expect.poll(async()=>(await (await request.get(prefix+'/api/preferences/appearance')).json()).preferences.font).toBe('system-mono');
      await second.evaluate(()=>localStorage.clear());await second.reload();
      await expect(second.locator('.hud-root')).toHaveAttribute('data-font','system-mono');
    } finally {await fresh.close();}
  });
}
