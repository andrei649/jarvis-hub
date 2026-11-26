import { expect, test } from '@playwright/test';

test('Projects opens a read-only sample and only loads the real board on exiting demo', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/kanban/') || path === '/api/missions') requests.push(path);
  });
  await page.route('**/api/missions', route => route.fulfill({
    json: { missions: [{ id: 'synthetic-1', title: 'Fixture venue booking', status: 'active' }] },
  }));
  await page.addInitScript(() => localStorage.setItem('hud.firstrun.dismissed', '1'));
  await page.goto('/v2/projects?demo=1', { waitUntil: 'domcontentloaded' });
  const projects = page.locator('[data-mode="projects"]');
  await expect(projects.getByRole('note')).toHaveText('Demo sample · read-only projects');
  await expect(projects.getByText('Exhibition planning')).toBeVisible();
  await expect(projects.getByRole('button')).toHaveCount(0);
  await expect(projects.getByText('Fixture venue booking')).toHaveCount(0);
  expect(requests).toEqual([]);

  await page.getByRole('button', { name: 'Exit demo' }).click();
  await expect(projects.getByText('Fixture venue booking')).toBeVisible();
  await expect(projects.getByRole('button', { name: '+ room' })).toBeVisible();
  expect(requests).toContain('/api/kanban/boards');
});
