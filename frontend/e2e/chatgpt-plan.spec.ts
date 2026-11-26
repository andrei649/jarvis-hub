import { expect, test } from '@playwright/test';

test.beforeEach(({}, testInfo) => {
  test.skip(testInfo.project.name !== 'chatgpt-plan', 'requires the isolated signed-provider hub');
});

test('owner connects, sees signed catalog in order, and disconnects through the packaged HUD', async ({ page, context, request, baseURL }) => {
  const origin = baseURL!;
  const callback = `${origin}/api/oauth/chatgpt/callback`;
  let authorizationRequests = 0;
  await context.addInitScript(() => localStorage.setItem('hud.admin_token', 'synthetic-plan-owner'));
  await context.route('https://auth.openai.com/api/accounts/authorize**', async route => {
    authorizationRequests++;
    const authorize = new URL(route.request().url());
    expect(authorize.origin + authorize.pathname).toBe('https://auth.openai.com/api/accounts/authorize');
    expect(authorize.searchParams.get('redirect_uri')).toBe(callback);
    expect(authorize.searchParams.get('code_challenge_method')).toBe('S256');
    const state = authorize.searchParams.get('state');
    expect(state).toBeTruthy();
    const returned = new URL(callback);
    returned.searchParams.set('state', state!);
    returned.searchParams.set('code', 'signed-synthetic-owner-code');
    returned.searchParams.set('client_id', 'oaiapp_synthetic');
    await route.fulfill({ status: 302, headers: { Location: returned.toString() }, body: '' });
  });

  await page.goto(`${origin}/v2/console/integrations`);
  const card = page.getByRole('listitem', { name: 'ChatGPT plan account connection' });
  await expect(card).toBeVisible();
  await expect(card.getByText('not connected', { exact: true })).toBeVisible();
  await expect(card.getByLabel(/API key/)).toHaveCount(0);
  await card.getByRole('button', { name: 'Continue with ChatGPT' }).click();
  const link = card.getByRole('link', { name: 'Open ChatGPT sign-in' });
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(link).toHaveAttribute('rel', /noopener noreferrer/);
  await expect(link).toHaveAttribute('href', /^https:\/\/auth\.openai\.com\/api\/accounts\/authorize\?/);

  const [returnTab] = await Promise.all([page.waitForEvent('popup'), link.click()]);
  await expect(returnTab.getByText('ChatGPT is connected. Return to Nerva')).toBeVisible();
  expect(new URL(returnTab.url()).origin).toBe(origin);
  expect(authorizationRequests).toBe(1);

  await card.getByRole('button', { name: 'Refresh connection' }).click();
  await expect(card.getByText('connected', { exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Show available models' }).click();
  const models = card.getByRole('list', { name: 'available models' });
  await expect(models.getByRole('listitem')).toHaveText(['Second (second)', 'First (first)']);

  await card.getByRole('button', { name: 'Disconnect' }).click();
  await expect(card.getByText('not connected', { exact: true })).toBeVisible();
  await expect(card.getByRole('status')).toContainText('removed from this hub locally');
  await expect(models).toHaveCount(0);
  const state = await (await request.get(`${origin}/_test/state`)).json();
  expect(state.provider_calls).toEqual([
    ['POST', 'auth.openai.com', '/api/accounts/oauth/token'],
    ['GET', 'auth.openai.com', '/.well-known/jwks.json'],
    ['GET', 'api.openai.com', '/v1/models'],
  ]);
  expect(state.generation_requests).toEqual([]);
});
