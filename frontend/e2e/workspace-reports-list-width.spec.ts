/* The packaged Workspace reports list must fit its desktop table at split-window widths. */
import { expect, test } from '@playwright/test';

test('reports list fits at split desktop widths', async ({ page }) => {
  const department = { id: 1, slug: 'general', name: 'General', description: '' };
  const report = {
    id: 3, department_id: 1, name: 'Situația zilnică a vânzărilor',
    instructions: 'Rezumă politica de discount, comisioanele agenților și încasările pe județe. Încheie cu un tabel al cifrelor cheie.', document_ids: [5, 6, 7],
    schedule_kind: 'daily', schedule_time: '08:15', schedule_weekday: null,
    timezone: 'Europe/Bucharest', delivery_emails: [], delivery_status: 'none',
    owner_id: 1, active: true, next_run_at: Date.now() / 1000 + 86_400, last_run_at: 1770000000,
    created_at: 1770000000, updated_at: 1770000000,
    last_run: { id: 40, status: 'succeeded', finished_at: 1770000000 },
    can_edit: true, can_run: true,
  };
  const reads: Record<string, unknown> = {
    '/api/workspace/session': {
      enabled: true, setup_required: false, sso_available: false, authenticated: true,
      user: { id: 1, email: 'member@example.test', name: 'Mihai Test', role: 'member', status: 'active', locale: 'ro', theme: 'light', department_ids: [1] },
      org: { name: 'Atelier sintetic', default_locale: 'ro', model_policy: 'local_only' },
      csrf_token: 'layout-only', departments: [department],
    },
    '/api/workspace/departments': { departments: [department] },
    '/api/workspace/notifications': { items: [], unread_count: 0 },
    '/api/workspace/approvals': { items: [], pending_inbox_count: 0 },
    '/api/workspace/model': { available: true, backend: 'lm-studio', model: 'synthetic-local-model', route: 'local', locality: 'local', policy: 'local_only', reason: null, guardrails_mode: 'monitor' },
    '/api/workspace/reports': { reports: [report] },
    '/api/workspace/reports/3': report,
    '/api/workspace/reports/3/runs': { runs: [] },
    '/api/workspace/documents': { documents: [] },
  };
  const unexpected: string[] = [];
  await page.route('**/api/workspace/**', route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET' && Object.prototype.hasOwnProperty.call(reads, path)) return route.fulfill({ json: reads[path] });
    unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 500, json: { error: 'unexpected_layout_fixture_request' } });
  });
  await page.goto('/workspace/reports');
  const table = page.getByRole('table', { name: 'Rapoarte' });
  const title = table.getByRole('link', { name: report.name });
  await expect(title).toBeVisible();
  await expect(table.getByText('Zilnic, la 08:15')).toBeVisible();
  await expect(table.getByText('Fără livrare')).toBeVisible();
  for (const width of [768, 1024, 1180]) {
    await page.setViewportSize({ width, height: 800 });
    const measure = await table.evaluate(node => {
      const frame = node.closest<HTMLElement>('.ws-table-scroll')!;
      return { tableOverflow: frame.scrollWidth - frame.clientWidth, pageWidth: document.documentElement.scrollWidth };
    });
    expect(measure.tableOverflow, `reports list table scrolls at ${width}px`).toBe(0);
    expect(measure.pageWidth, `reports list document overflows at ${width}px`).toBeLessThanOrEqual(width);
    await expect(title).toBeVisible();
    await expect(table.getByRole('button', { name: `Rulează acum „${report.name}”` })).toBeVisible();
  }
  await title.click();
  await expect(page).toHaveURL(/\/workspace\/reports\/3$/);
  expect(unexpected).toEqual([]);
});
