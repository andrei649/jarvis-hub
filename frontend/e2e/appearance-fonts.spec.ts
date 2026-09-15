import { expect, test } from '@playwright/test';
const headers={'X-User-Token':'h130-isolated-test-token'};
for(const prefix of ['', '/one']) {
  test(`local font choices persist without changing mono at ${prefix || '/'}`,async({page,browser,baseURL,request})=>{
    await request.put(prefix+'/api/preferences/appearance',{data:{font:'theme',look:'obsidian'}});
    await page.goto(prefix+'/v2/chat?demo=1');
    const root=page.locator('.hud-root');
    await expect(root).toHaveAttribute('data-font','theme');
    const mono=await root.evaluate(el=>getComputedStyle(el).getPropertyValue('--font-mono'));
    // Exercise the shipped code rule, independently of body font inheritance.
    await root.evaluate(el=>{const block=document.createElement('div');block.className='art-md';block.id='font-code-probe';const code=document.createElement('code');code.textContent='const value = 1';block.append(code);el.append(block);});
    const code=page.locator('#font-code-probe code');
    const codeFont=await code.evaluate(el=>getComputedStyle(el).fontFamily);
    for(const [id, label, family] of [['system-sans','System Sans','system-ui'],['system-serif','System Serif','Georgia'],['system-mono','System Mono','ui-monospace'],['jetbrains-mono','JetBrains Mono','JetBrains Mono'],['theme','Theme Default','Space Grotesk']]) {
      await page.getByTitle('command palette',{exact:true}).click();
      const saved=page.waitForResponse(r=>r.url().endsWith('/api/preferences/appearance')&&r.request().method()==='PUT');
      await page.getByText('Font · '+label,{exact:true}).click();
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
      await second.getByTitle('command palette',{exact:true}).click();
      await second.getByText('Look · Graphite',{exact:true}).click();
      await expect(second.locator('.hud-root')).toHaveAttribute('data-look','graphite');
      expect(await second.locator('.hud-root').evaluate(el=>getComputedStyle(el).fontFamily)).toContain('Georgia');
      await fresh.setOffline(true);
      await second.getByTitle('command palette',{exact:true}).click();
      await second.getByText('Font · System Mono',{exact:true}).click();
      await expect(second.getByText('Appearance saved on this browser only. Sync failed.')).toBeVisible();
      await fresh.setOffline(false);
      await second.evaluate(()=>window.dispatchEvent(new Event('online')));
      await expect.poll(async()=>(await (await request.get(prefix+'/api/preferences/appearance')).json()).preferences.font).toBe('system-mono');
      await second.evaluate(()=>localStorage.clear());await second.reload();
      await expect(second.locator('.hud-root')).toHaveAttribute('data-font','system-mono');
    } finally {await fresh.close();}
  });
}
