/* A rendered report has to fit the phone viewport even when its table needs
   its own sideways scroll. The run is a fixed report fixture, not a model stream. */
import { expect, test } from '@playwright/test';

test('a finished report stays within the 320 px phone viewport', async ({ page }) => {
  const run = {
    id: 40, report_id: 3, status: 'succeeded', trigger: 'manual', triggered_by: 1,
    model: 'synthetic-local-model', route: 'local', locality: 'local', error_code: null,
    error: null, shared_company: false, delivered_to: [], started_at: 1770000000,
    finished_at: 1770000010, created_at: 1770000000, delivery_state: null,
    content_md: '# Raport: Situația zilnică a vânzărilor\n\n## Rezumat executiv\n\nDiscountul maxim pentru clienții noi din Țara Bârsei este de 12% din valoarea comenzii. [1]\n\n## Constatări\n\n- Discountul maxim pentru clienții noi din Țara Bârsei este de 12% din valoarea comenzii. [1]\n- Lună: Iulie — Județ: Sibiu — Încasări (lei): 41250 [2]\n- Comisionul agenților de vânzări este de 3% din încasările lunare. [3]\n\n## Date cheie\n\n| Nr. | Document | Extras |\n| --- | --- | --- |\n| [1] | politica-discount-vanzari | Discountul maxim pentru clienții noi din Țara Bârsei este de 12% din valoarea comenzii. |\n| [2] | incasari-trimestrul-3 | Lună: Iulie — Județ: Sibiu — Încasări (lei): 41250 |\n| [3] | regulament-comisioane | Comisionul agenților de vânzări este de 3% din încasările lunare. |\n\n## Surse\n\n1. [1] politica-discount-vanzari\n2. [2] incasari-trimestrul-3\n3. [3] regulament-comisioane',
    citations: [
      { n: 1, document_id: 5, title: 'politica-discount-vanzari', chunk_id: 2, page: null, excerpt: 'Discountul maxim pentru clienții noi din Țara Bârsei este de 12% din valoarea comenzii.' },
      { n: 2, document_id: 6, title: 'incasari-trimestrul-3', chunk_id: 3, page: null, excerpt: 'Lună: Iulie — Județ: Sibiu — Încasări (lei): 41250' },
      { n: 3, document_id: 7, title: 'regulament-comisioane', chunk_id: 4, page: 1, excerpt: 'Comisionul agenților de vânzări este de 3% din încasările lunare.' },
    ],
    can_share: true, can_email: true, report: { id: 3, name: 'Situația zilnică a vânzărilor', department_id: 1 },
    department_name: 'General',
  };
  // The real Workspace shell and renderer run against an isolated hub. Only their GET
  // fixtures are supplied here, so this layout check works before or after setup.
  const department = { id: 1, slug: 'general', name: 'General', description: '' };
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
    '/api/workspace/approvals/eligible': { count: 1, smtp_configured: true },
    '/api/workspace/model': { available: true, backend: 'lm-studio', model: 'synthetic-local-model', route: 'local', locality: 'local', policy: 'local_only', reason: null, guardrails_mode: 'monitor' },
    '/api/workspace/report-runs/40': { run },
  };
  const unexpected: string[] = [];
  await page.route('**/api/workspace/**', route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET' && Object.prototype.hasOwnProperty.call(reads, path)) return route.fulfill({ json: reads[path] });
    unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 500, json: { error: 'unexpected_layout_fixture_request' } });
  });
  await page.goto('/workspace/report-runs/40');
  const article = page.locator('article.ws-report');
  await expect(page.getByRole('heading', { level: 1, name: 'Situația zilnică a vânzărilor' })).toBeVisible();
  await expect(article.getByRole('table')).toBeVisible();
  await expect(article).toContainText('politica-discount-vanzari');
  await expect(page.getByRole('button', { name: 'Partajează în companie' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Trimite pe email' })).toBeVisible();
  for (const width of [320, 390, 1024]) {
    await page.setViewportSize({ width, height: 640 });
    const measure = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
      offenders: Array.from(document.querySelectorAll<HTMLElement>('.ws-run *'))
        .filter(element => element.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
        .slice(0, 5).map(element => `${element.tagName.toLowerCase()}.${element.className}`),
      tableScroll: (() => {
        const frame = document.querySelector<HTMLElement>('.ws-report .ws-md__table');
        return frame ? frame.scrollWidth - frame.clientWidth : -1;
      })(),
    }));
    expect(measure.page, `${width}px report overflow; ${measure.offenders.join(', ')}`).toBeLessThanOrEqual(measure.viewport + 1);
    await expect(article.getByRole('table')).toBeVisible();
    if (width === 320) expect(measure.tableScroll, 'the full report table remains in its own scrollable frame').toBeGreaterThan(0);
  }
  expect(unexpected, 'the layout fixture only performs the expected Workspace GETs').toEqual([]);
});
