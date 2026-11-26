import { expect, test } from '@playwright/test';

test('chat creates and edits Word and Excel copies and reopens each download', async ({ page }, testInfo) => {
  const realModel = process.env.NERVA_OFFICE_REAL_MODEL === '1';
  if (realModel) {
    test.setTimeout(180_000);
    const hub = new URL(testInfo.project.use.baseURL!);
    expect(hub.hostname).toBe('127.0.0.1');
    expect(Number(hub.port)).toBeGreaterThan(1024);
    expect(hub.port).not.toBe('8080');
    await page.route('**/*', route => {
      return new URL(route.request().url()).origin === hub.origin ? route.continue() : route.abort();
    });
  }
  await page.addInitScript(fixtureReply => {
    localStorage.setItem('hud.firstrun.dismissed', '1');
    localStorage.setItem('hud.lang', 'en');
    if (fixtureReply) sessionStorage.setItem('nerva.chat.session_id', 'office-copy-acceptance');
  }, !realModel);
  // The ordinary lane fixtures only the reply; the opt-in local lane uses the real stream.
  const answer = 'Delivery in May.\n\nKeep this paragraph.\n\n| Item | Month |\n| --- | --- |\n| Apples | May |';
  if (!realModel) await page.route('**/chat/stream', route => route.fulfill({
    contentType: 'text/event-stream',
    body: [{ type: 'start', agent: 'jarvis' }, { type: 'token', text: answer },
      { type: 'end', agent: 'jarvis', text: answer }].map(e => 'data: ' + JSON.stringify(e) + '\n\n').join(''),
  }));
  await page.goto('/v2/chat');
  const prompt = realModel
    ? `Reply with exactly the text below. Keep the Markdown table syntax and add nothing else:\n\n${answer}`
    : 'Prepare the sample delivery note and table.';
  await page.locator('[data-composer]').fill(prompt);
  const stream = realModel ? page.waitForResponse(response => new URL(response.url()).pathname === '/chat/stream') : null;
  await page.locator('[data-composer-send]').click();
  if (stream) {
    const response = await stream;
    expect(response.status()).toBe(200);
    const events = (await response.text()).split('\n').filter(line => line.startsWith('data: '))
      .map(line => JSON.parse(line.slice(6)) as { type: string; session_id?: string; model_calls?: { provider: string; model: string }[] });
    const end = events.find(event => event.type === 'end');
    expect(end?.session_id).toBeTruthy();
    expect(end?.model_calls).toEqual([{ provider: 'ollama', model: process.env.NERVA_OFFICE_MODEL }]);
  }
  const reply = page.locator('[data-turn="reply"]').filter({ hasText: 'Delivery in May.' }).last();
  const attach = page.getByRole('button', { name: 'Attach', exact: true });
  const preview = page.getByRole('dialog', { name: 'Attach document' });
  async function openFile(path: string) {
    if (await attach.getAttribute('aria-expanded') !== 'true') await attach.click();
    const chosen = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: 'Attach document' }).click();
    await (await chosen).setFiles(path);
    await expect(preview.getByLabel('Select a passage')).toBeVisible();
  }
  async function closeFile() {
    await preview.getByRole('button', { name: 'Close document preview' }).click();
    if (await attach.getAttribute('aria-expanded') === 'true') await attach.click();
  }
  for (const item of [
    { kind: 'docx', action: 'Download Word', targetLabel: 'Text to replace', target: 'Delivery in May.',
      valueLabel: 'Replacement text', original: 'Delivery in May.', revision: 'Delivery in June.', keep: 'Keep this paragraph.' },
    { kind: 'xlsx', action: 'Download Excel', targetLabel: 'Cell (A1)', target: 'B2',
      valueLabel: 'New value', original: 'May', revision: 'June', keep: 'Apples' },
  ]) {
    if (item.kind === 'docx') await reply.locator('[data-talk-menu="more"] button').first().click();
    const download = page.waitForEvent('download');
    await reply.getByRole('button', { name: item.action }).click();
    const original = testInfo.outputPath('original.' + item.kind);
    await (await download).saveAs(original);
    if (item.kind === 'docx') await page.keyboard.press('Escape');
    await openFile(original);
    await expect(preview.getByLabel('Select a passage')).toHaveValue(new RegExp(item.original));
    await preview.getByRole('button', { name: 'Edit a copy' }).click();
    await preview.getByRole('textbox', { name: item.targetLabel, exact: true }).fill(item.target);
    await preview.getByRole('textbox', { name: item.valueLabel, exact: true }).fill(item.revision);
    const edited = page.waitForEvent('download');
    await preview.getByRole('button', { name: 'Download edited copy' }).click();
    const result = testInfo.outputPath('revised.' + item.kind);
    await (await edited).saveAs(result);
    await closeFile();
    for (const [path, expected, absent] of [[result, item.revision, item.original], [original, item.original, item.revision]]) {
      await openFile(path);
      const text = await preview.getByLabel('Select a passage').inputValue();
      expect(text).toContain(expected);
      expect(text).toContain(item.keep);
      expect(text).not.toContain(absent);
      await closeFile();
    }
  }
});
