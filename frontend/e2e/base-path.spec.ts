import { expect, test } from '@playwright/test';

for (const prefix of ['', '/one', '/two/nerva']) {
  test(`same built HUD through proxy at ${prefix || '/'}`, async ({ page, context, baseURL }) => {
    const origin = new URL(baseURL!).origin;
    const leaks: string[] = [];
    const errors: string[] = [];
    const assets = new Set<string>();
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', req => {
      const url = new URL(req.url());
      if (url.origin === origin && prefix && !url.pathname.startsWith(prefix + '/')) leaks.push(url.pathname);
      if (url.pathname.includes('/v2/assets/')) assets.add(url.pathname);
    });
    await page.goto(prefix + '/v2/cockpit?demo=1#anchor');
    await expect(page).toHaveTitle('Cockpit · Nerva');
    await page.keyboard.press('`');
    await expect(page).toHaveTitle('Console · Nerva');
    await page.keyboard.press('`');
    await expect(page).toHaveTitle('Cockpit · Nerva');
    await page.route('http://localhost:8787/**', route => route.abort());
    await page.keyboard.press('w');
    await expect(page).toHaveTitle('World · Nerva');
    await page.keyboard.press('Escape');
    await expect(page).toHaveTitle('Cockpit · Nerva');
    await page.getByTitle('console (`)').click();
    await page.getByRole('link', {name:'Decision Inbox', exact:true}).click();
    await expect(page).toHaveURL(origin + prefix + '/v2/console/decision-inbox?demo=1#anchor');
    await expect(page.getByRole('heading', {name:'Decision Inbox', exact:true})).toBeFocused();
    await page.reload();
    await expect(page).toHaveTitle('Decision Inbox · Console · Nerva');
    await page.getByRole('link', {name:'All console panels'}).click();
    await page.goBack();
    await expect(page).toHaveTitle('Decision Inbox · Console · Nerva');
    await page.goForward();
    await expect(page).toHaveTitle('Console · Nerva');
    expect([...assets].some(path => /\/gap-/.test(path))).toBe(true);
    expect([...assets].some(path => path.endsWith('.woff2'))).toBe(true);
    const entry = [...assets].find(path => /\/index-[^/]+\.js$/.test(path))!;
    const logicalEntry = entry.slice(prefix.length);
    expect(await (await page.request.get(entry)).body()).toEqual(await (await page.request.get(logicalEntry)).body());
    const manifest = await page.request.get(prefix + '/manifest.webmanifest');
    expect((await manifest.json()).scope).toBe(prefix + '/');
    const index = await page.request.get(prefix + '/v2/chat', {headers:{'X-Forwarded-Prefix':'/forged'}});
    expect(await index.text()).toContain(`window.__NERVA_BASE_PATH__=${JSON.stringify(prefix)}`);
    expect((await page.request.get(prefix + '/v2/assets/absent.js')).status()).toBe(404);
    const redirect = await page.request.get(prefix + '/static', {maxRedirects:0});
    expect(redirect.headers().location).toBe(origin + prefix + '/static/');
    // Production transport code has unit coverage; here the actual proxy carries
    // GET, SSE and streaming POST bodies with fixture-only service responses.
    const refused = await page.request.post(prefix + '/api/schedule/parse', {headers:{'X-User-Token':''}, data:{text:'every 5 minutes'}});
    expect(refused.status()).toBe(401);
    const parsed = await page.request.post(prefix + '/api/schedule/parse', {data:{text:'every 5 minutes'}});
    expect(parsed.status()).toBe(200);
    expect(await parsed.json()).toEqual({ok:true, cron:'*/5 * * * *', description:'every 5 minute(s)'});
    const transport = await page.evaluate(async p => {
      const status = await fetch(p + '/api/system-map').then(r => r.json());
      const frame = await new Promise<string>((resolve, reject) => {
        const es = new EventSource(p + '/api/cognition/stream');
        es.onmessage = e => {es.close(); resolve(e.data);}; es.onerror = () => {es.close(); reject(new Error('SSE failed'));};
      });
      const stream = await fetch(p + '/chat/stream', {method:'POST', body:JSON.stringify({text:'fixture'})}).then(r => r.text());
      return {status, frame, stream};
    }, prefix);
    expect(transport.status).toHaveProperty('topology');
    expect(transport.frame).toContain('ready');
    expect(transport.stream).toContain('fixture reply');
    await page.goto(prefix + '/map');
    await expect.poll(() => page.evaluate(() => document.querySelectorAll('svg .node').length)).toBeGreaterThan(0);
    await page.goto(prefix + '/mission-control');
    await expect(page).toHaveTitle(/Mission Control/);
    // Mock bridge tests existing floating UI selection, not native GUI authority.
    await page.addInitScript(() => {(window as any).__TAURI__ = {core:{invoke:async () => ({})}};});
    await page.goto(prefix + '/v2/unknown?desktop=floating&demo=1');
    await expect(page).toHaveURL(origin + prefix + '/v2/chat?desktop=floating&demo=1');
    await expect(page).toHaveTitle('Chat · Nerva');
    await page.goto(prefix + '/v2/cockpit?demo=1');
    await page.evaluate(async () => {await navigator.serviceWorker.ready;});
    await page.reload();
    await page.evaluate(async () => {await caches.open('unrelated-application');});
    const cacheKeys = await page.evaluate(() => caches.keys());
    expect(cacheKeys).toContain('unrelated-application');
    expect(cacheKeys.some(key => key.startsWith('nerva-hud-v2:' + encodeURIComponent(prefix + '/') + ':'))).toBe(true);
    const cached = await page.evaluate(async () => (await Promise.all((await caches.keys()).map(async key => (await (await caches.open(key)).keys()).map(r => r.url)))).flat());
    expect(cached.some(url => url.includes('/api/'))).toBe(false);
    await context.setOffline(true);
    await page.goto(prefix + '/v2/chat?demo=1');
    await expect(page).toHaveTitle('Chat · Nerva');
    await context.setOffline(false);
    expect(leaks).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('cohosted workers keep separate shells and preserve unrelated caches', async ({page}) => {
  await page.goto('/one/v2/chat?demo=1');
  await page.evaluate(async () => {await navigator.serviceWorker.ready; await caches.open('other-app-cache');});
  await page.goto('/two/nerva/v2/chat?demo=1');
  await page.evaluate(async () => {await navigator.serviceWorker.ready;});
  const keys = await page.evaluate(() => caches.keys());
  expect(keys).toContain('other-app-cache');
  expect(keys.some(k => k.startsWith('nerva-hud-v2:%2Fone%2F:'))).toBe(true);
  expect(keys.some(k => k.startsWith('nerva-hud-v2:%2Ftwo%2Fnerva%2F:'))).toBe(true);
});
