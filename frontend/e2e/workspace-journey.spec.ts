/* Nerva Workspace · the pilot journey against the REAL hub (spec §1, definition of done 3).

   One serial story, one step per test, every step asserting the real effect (a row the server
   stored, a message in the SMTP sink, a downloaded file) and not just that a control is visible.
   The cast — an admin, a Vânzări member, a Vânzări approver and a Financiar member — each in
   their own browser context, signed in through the real invite links. Every main page gets an
   axe scan and two screenshots (support/workspace-helpers.ts → checkPage); every step fails on
   a console error or an uncaught page error unless it declared that HTTP failure itself.

   Runs only under playwright.workspace.config.ts (the HUD lanes ignore workspace*.spec.ts). */
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import {
  assertNoPageProblems, buildDocuments, checkPage, controlsUnderTopBar, DESKTOP, focusRing, guard, guardFor, holdSmtpGreeting, hubLog, pageGet, PHONE, readMail,
  RUN_DIR, screenDir, setModelServer, setSmtpSink, SETUP_CODE, SMTP_PORT, tableScrollsSideways, waitForMail, waitForSmtpConnection, type SampleDoc, type SampleKey,
} from './support/workspace-helpers';

test.describe.configure({ mode: 'serial' });

interface Person { name: string; email: string; password: string }

const ORG = 'Acme Distribuție SRL';
// The cast's passwords exist only in the throwaway hub of each run (a fresh JARVIS_HOME). The
// secret-scan gate (security.yml, gitleaks) reads them as credentials, so each line carries the
// scanner's inline allow marker; it has to sit on the line itself.
const ADMIN: Person = { name: 'Ana Popescu', email: 'ana.popescu@acme.ro', password: 'Cer-albastru-peste-Carpati-42' }; // gitleaks:allow
const SALES_MEMBER: Person = { name: 'Mihai Ionescu', email: 'mihai.ionescu@acme.ro', password: 'Lumina-de-toamna-la-Sibiu-7' }; // gitleaks:allow
const SALES_APPROVER: Person = { name: 'Elena Dumitrescu', email: 'elena.dumitrescu@acme.ro', password: 'Podul-de-piatra-din-Iasi-19' }; // gitleaks:allow
const FIN_MEMBER: Person = { name: 'Radu Georgescu', email: 'radu.georgescu@acme.ro', password: 'Marea-Neagra-in-august-83' }; // gitleaks:allow
/** The Vânzări member's password after the profile step changes it. */
const NEW_MEMBER_PASSWORD = 'Frunze-ruginii-pe-Tampa-2026'; // gitleaks:allow
const SALES = 'Vânzări';
const FINANCE = 'Financiar';

/** Shared across the serial steps. */
const state: {
  contexts: BrowserContext[];
  admin?: Page;
  member?: Page;
  approver?: Page;
  finance?: Page;
  invites: Partial<Record<'member' | 'approver' | 'finance', string>>;
  departments: Record<string, number>;
  docs?: Record<SampleKey, SampleDoc>;
  documentIds: Partial<Record<SampleKey, number>>;
  conversationId?: number;
  reportId?: number;
  runId?: number;
} = { contexts: [], invites: {}, departments: {}, documentIds: {} };

async function newPage(browser: Browser, who: string): Promise<Page> {
  const use = test.info().project.use;
  const context = await browser.newContext({
    baseURL: use.baseURL, viewport: use.viewport, locale: use.locale, timezoneId: use.timezoneId,
    serviceWorkers: 'block', acceptDownloads: true,
  });
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: use.baseURL });
  state.contexts.push(context);
  const page = await context.newPage();
  guard(page, who);
  return page;
}

function need<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new Error(`${what} is not set: an earlier step failed`);
  return value;
}

/** The newest toast with *text* (earlier toasts from the same step may still be showing). */
function toast(page: Page, text: string, region: 'status' | 'alert' = 'status') {
  return page.getByRole(region).getByText(text, { exact: true }).last();
}

function userMenu(page: Page, name: string) {
  return page.getByRole('button', { name: new RegExp(`(Contul tău|Your account): ${name}`) });
}

/** Toasts drawn over a dialog's or drawer's controls (they move aside while one is open). */
async function toastsOverControls(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const hits: string[] = [];
    const toasts = Array.from(document.querySelectorAll<HTMLElement>('.ws-toast')).map((t) => t.getBoundingClientRect());
    for (const control of Array.from(document.querySelectorAll<HTMLElement>('.ws-surface button, .ws-surface a[href]'))) {
      const r = control.getBoundingClientRect();
      if (r.width === 0) continue;
      if (toasts.some((t) => t.left < r.right && t.right > r.left && t.top < r.bottom && t.bottom > r.top)) hits.push((control.textContent || '').trim());
    }
    return hits;
  });
}

test.afterEach(() => assertNoPageProblems());

test.afterAll(async () => {
  for (const context of state.contexts) await context.close().catch(() => undefined);
});

test('first run: the setup code creates the organisation and its administrator', async ({ browser }) => {
  const page = await newPage(browser, 'admin');
  state.admin = page;
  await page.goto('/workspace/');
  await expect(page.getByRole('heading', { name: 'Configurează Nerva Workspace' })).toBeVisible();
  await checkPage(page, 'setup');

  // A wrong code is refused on the field, and nothing is created.
  guardFor(page).expectHttp(/\/api\/workspace\/setup$/, 403);
  await page.getByLabel('Cod de configurare').fill('cod-gresit-123456');
  await page.getByLabel('Numele organizației').fill(ORG);
  await page.getByLabel('Nume', { exact: true }).fill(ADMIN.name);
  await page.getByLabel('Email', { exact: true }).fill(ADMIN.email);
  await page.getByLabel('Parolă', { exact: true }).fill(ADMIN.password);
  await page.getByLabel('Confirmă parola').fill(ADMIN.password);
  await page.getByRole('button', { name: 'Creează spațiul de lucru' }).click();
  await expect(page.getByLabel('Cod de configurare')).toHaveAttribute('aria-invalid', 'true');
  expect((await pageGet<{ setup_required: boolean }>(page, '/api/workspace/session')).body.setup_required).toBe(true);

  await page.getByLabel('Cod de configurare').fill(SETUP_CODE);
  await page.getByRole('button', { name: 'Creează spațiul de lucru' }).click();
  await expect(page).toHaveURL(/\/workspace\/admin\/users$/);
  await expect(userMenu(page, ADMIN.name)).toBeVisible();

  const me = await pageGet<{ user: { role: string; email: string }; org: { name: string }; departments: { name: string }[] }>(page, '/api/workspace/me');
  expect(me.status).toBe(200);
  expect(me.body.user).toMatchObject({ role: 'admin', email: ADMIN.email });
  expect(me.body.org.name).toBe(ORG);
  expect(me.body.departments.map((d) => d.name)).toEqual(['General']);
  // The admin row is in the users table, marked as the signed-in user.
  await expect(page.getByRole('table', { name: 'Utilizatori' }).getByText(ADMIN.email)).toBeVisible();
  await checkPage(page, 'admin-users');
});

test('the admin creates the Vânzări and Financiar departments', async () => {
  const page = need(state.admin, 'admin page');
  await page.getByRole('navigation', { name: 'Secțiunile administrării' }).getByRole('link', { name: 'Departamente' }).click();
  await expect(page).toHaveURL(/\/workspace\/admin\/departments$/);
  for (const [name, description] of [[SALES, 'Echipa comercială și agenții de teren.'], [FINANCE, 'Contabilitate, facturare și bugete.']]) {
    await page.getByRole('button', { name: 'Departament nou' }).first().click();
    const drawer = page.getByRole('dialog', { name: 'Departament nou' });
    // The previous department's confirmation may still show: it must not cover this drawer's buttons.
    expect(await toastsOverControls(page)).toEqual([]);
    await drawer.getByLabel('Nume', { exact: true }).fill(name);
    await drawer.getByLabel(/^Descriere/).fill(description);
    await drawer.getByRole('button', { name: 'Creează departamentul' }).click();
    await expect(drawer).toBeHidden();
    await expect(toast(page, `Departamentul „${name}” a fost creat.`)).toBeVisible();
    await expect(page.getByRole('table', { name: 'Departamente' }).getByText(name, { exact: true })).toBeVisible();
  }
  const listed = await pageGet<{ departments: { id: number; name: string; slug: string; description: string }[] }>(page, '/api/workspace/admin/departments');
  for (const d of listed.body.departments) state.departments[d.name] = d.id;
  expect(Object.keys(state.departments).sort()).toEqual(['Financiar', 'General', 'Vânzări']);
  expect(listed.body.departments.find((d) => d.name === SALES)).toMatchObject({ slug: 'vanzari', description: 'Echipa comercială și agenții de teren.' });
  // The sidebar's department switcher offers them at once.
  await expect(page.getByLabel('Departament', { exact: true }).locator('option')).toHaveText(['Financiar', 'General', 'Vânzări']);
  await checkPage(page, 'admin-departments');
});

async function invite(page: Page, person: Person, roleLabel: string, department: string): Promise<string> {
  await page.getByRole('button', { name: 'Invită utilizator' }).click();
  const dialog = page.getByRole('dialog', { name: 'Invită un utilizator' });
  await dialog.getByLabel('Email', { exact: true }).fill(person.email);
  await dialog.getByLabel('Nume', { exact: true }).fill(person.name);
  await dialog.getByLabel('Rol').selectOption({ label: roleLabel });
  await dialog.getByRole('checkbox', { name: department, exact: true }).check();
  // Email is not configured yet: nothing is sent, so the button says it creates the invitation.
  await dialog.getByRole('button', { name: 'Creează invitația' }).click();
  const done = page.getByRole('dialog', { name: 'Invitație creată' });
  await expect(done).toBeVisible();
  const field = done.getByLabel('Link personal');
  const shown = await field.inputValue();
  expect(shown).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/workspace\/invite#t=[A-Za-z0-9_-]{16,128}$/);
  await done.getByRole('button', { name: 'Copiază' }).click();
  await expect(toast(page, 'Linkul a fost copiat.')).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toBe(shown);
  await done.getByRole('button', { name: 'Gata' }).click();
  await expect(done).toBeHidden();
  return copied;
}

test('the admin invites a member and an approver to Vânzări and a member to Financiar', async () => {
  const page = need(state.admin, 'admin page');
  await page.getByRole('navigation', { name: 'Secțiunile administrării' }).getByRole('link', { name: 'Utilizatori' }).click();
  state.invites.member = await invite(page, SALES_MEMBER, 'Membru', SALES);
  state.invites.approver = await invite(page, SALES_APPROVER, 'Aprobator', SALES);
  state.invites.finance = await invite(page, FIN_MEMBER, 'Membru', FINANCE);

  const users = await pageGet<{ users: { email: string; role: string; status: string; department_ids: number[] }[] }>(page, '/api/workspace/admin/users');
  const byEmail = new Map(users.body.users.map((u) => [u.email, u]));
  expect(byEmail.get(SALES_MEMBER.email)).toMatchObject({ role: 'member', status: 'invited', department_ids: [state.departments[SALES]] });
  expect(byEmail.get(SALES_APPROVER.email)).toMatchObject({ role: 'approver', status: 'invited', department_ids: [state.departments[SALES]] });
  expect(byEmail.get(FIN_MEMBER.email)).toMatchObject({ role: 'member', status: 'invited', department_ids: [state.departments[FINANCE]] });
  await expect(page.getByRole('table', { name: 'Utilizatori' }).getByText('Invitat')).toHaveCount(3);
});

async function acceptInvite(browser: Browser, link: string, person: Person, who: string, scan: boolean): Promise<Page> {
  const page = await newPage(browser, who);
  await page.goto(link);
  await expect(page.getByRole('heading', { name: `Bine ai venit în ${ORG}` })).toBeVisible();
  await expect(page.getByText(`Invitația este pentru adresa ${person.email}.`)).toBeVisible();
  // The token left the address bar as soon as it was read (spec §6).
  await expect.poll(() => new URL(page.url()).hash).toBe('');
  await expect(page.getByLabel('Nume', { exact: true })).toHaveValue(person.name);
  if (scan) await checkPage(page, 'invite');
  await page.getByLabel('Parola nouă').fill(person.password);
  await page.getByLabel('Confirmă parola').fill(person.password);
  await page.getByRole('button', { name: 'Activează contul' }).click();
  await expect(userMenu(page, person.name)).toBeVisible();
  const me = await pageGet<{ user: { status: string; email: string } }>(page, '/api/workspace/me');
  expect(me.body.user).toMatchObject({ status: 'active', email: person.email });
  return page;
}

test('each invitee opens their link in a fresh browser, chooses a password and is signed in', async ({ browser }) => {
  state.member = await acceptInvite(browser, need(state.invites.member, 'member invite'), SALES_MEMBER, 'vanzari-member', true);
  state.approver = await acceptInvite(browser, need(state.invites.approver, 'approver invite'), SALES_APPROVER, 'vanzari-approver', false);
  state.finance = await acceptInvite(browser, need(state.invites.finance, 'finance invite'), FIN_MEMBER, 'financiar-member', false);

  // Each sees exactly their department, and no admin area.
  await expect(state.member.getByLabel('Departament', { exact: true })).toHaveValue(String(state.departments[SALES]));
  await expect(state.finance.getByLabel('Departament', { exact: true }).locator('option')).toHaveText([FINANCE]);
  await expect(state.member.getByRole('navigation', { name: 'Navigare principală' }).getByRole('link', { name: 'Administrare' })).toHaveCount(0);

  // A used link does not work twice.
  const again = await newPage(browser, 'reused-link');
  guardFor(again).expectHttp(/\/api\/workspace\/invites\/lookup$/, 404);
  await again.goto(need(state.invites.member, 'member invite'));
  await expect(again.getByRole('heading', { name: 'Linkul nu mai este valabil' })).toBeVisible();
  await again.close();

  // The admin's list now shows three active accounts besides their own.
  const users = await pageGet<{ users: { status: string }[] }>(need(state.admin, 'admin'), '/api/workspace/admin/users');
  expect(users.body.users.filter((u) => u.status === 'active')).toHaveLength(4);
});

async function nav(page: Page, label: string): Promise<void> {
  await page.getByRole('navigation', { name: 'Navigare principală' }).getByRole('link', { name: label, exact: true }).click();
}

interface ApiDocument {
  id: number; title: string; filename: string; status: string; chunk_count: number; department_id: number | null;
  visibility: string; uploader: { name: string } | null; error: string | null;
}

test('the Vânzări member uploads a DOCX, a PDF, an XLSX and a CSV, and each is extracted and indexed', async () => {
  const page = need(state.member, 'member page');
  const docs = buildDocuments();
  state.docs = docs;
  await nav(page, 'Documente');
  await expect(page).toHaveURL(/\/workspace\/documents$/);
  await expect(page.getByText('Se adaugă în: Vânzări')).toBeVisible();
  await expect(page.getByText('Niciun document încă')).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(Object.values(docs).map((d) => d.path));
  // Once every upload has finished, the ready ones fold into one line (they are table rows now);
  // their per-file detail is a click away.
  await expect(page.getByText('4 fișiere încărcate și indexate; le găsești în listă.')).toBeVisible({ timeout: 60_000 });
  await page.getByRole('button', { name: 'Arată detaliile' }).click();
  const queue = page.locator('.ws-upload__list');
  for (const doc of Object.values(docs)) {
    await expect(queue.getByRole('listitem').filter({ hasText: doc.file }))
      .toContainText(/Gata · \d+ (de )?fragment(e)? indexat(e)?/, { timeout: 60_000 });
  }

  const listed = await pageGet<{ documents: ApiDocument[] }>(page, `/api/workspace/documents?department_id=${state.departments[SALES]}`);
  expect(listed.status).toBe(200);
  for (const [key, doc] of Object.entries(docs) as [SampleKey, SampleDoc][]) {
    const row = listed.body.documents.find((d) => d.filename === doc.file);
    expect(row, `${doc.file} is listed`).toBeTruthy();
    expect(row).toMatchObject({ title: doc.title, status: 'ready', error: null, department_id: state.departments[SALES], visibility: 'department' });
    expect(row?.chunk_count).toBeGreaterThan(0);
    expect(row?.uploader?.name).toBe(SALES_MEMBER.name);
    state.documentIds[key] = row?.id;
  }
  const table = page.getByRole('table', { name: 'Documente' });
  await expect(table.getByRole('row')).toHaveCount(1 + 4);
  await expect(table.getByText('Gata', { exact: true })).toHaveCount(4);

  // Each preview shows the extracted Romanian text, diacritics intact.
  for (const doc of Object.values(docs)) {
    await table.getByRole('button', { name: doc.title, exact: true }).click();
    const drawer = page.getByRole('dialog', { name: doc.title });
    await expect(drawer.getByRole('region', { name: 'Previzualizare text' })).toContainText(doc.fact);
    if (doc.file.endsWith('.docx')) {
      // The original comes back byte for byte.
      const [download] = await Promise.all([page.waitForEvent('download'), drawer.getByRole('link', { name: 'Descarcă' }).click()]);
      expect(download.suggestedFilename()).toBe(doc.file);
      expect(readFileSync(await download.path())).toEqual(readFileSync(doc.path));
      await expect(page).toHaveURL(new RegExp(`/workspace/documents/${state.documentIds.docx}$`));
      await checkPage(page, 'document-drawer');
    }
    await drawer.getByRole('button', { name: 'Închide' }).first().click();
    await expect(drawer).toBeHidden();
  }
  await checkPage(page, 'documents');
});

interface ApiMessage {
  id: number; role: string; content: string; status: string; feedback: number | null; feedback_note: string | null;
  citations: { n: number; document_id: number; title: string; excerpt: string; can_open?: boolean }[]; model: string | null; locality: string | null;
}

const QUESTION = 'Care este discountul maxim pentru clienții noi din Țara Bârsei?';

test('the member asks a question the DOCX answers: tokens stream, the answer cites it, the source drawer opens, feedback is saved', async () => {
  const page = need(state.member, 'member page');
  const docs = need(state.docs, 'documents');
  await nav(page, 'Asistent');
  // A first visit (no conversation yet) is greeted by name.
  await expect(page.getByText('Bine ai venit, Mihai!')).toBeVisible();
  await expect(page.getByText('Nicio conversație încă')).toBeVisible();

  // Record the answer's text length on every DOM change while it is still streaming.
  await page.evaluate(() => {
    const w = window as unknown as { __lengths: number[] };
    w.__lengths = [];
    new MutationObserver(() => {
      const answer = document.querySelector('.ws-msg--assistant .ws-msg__answer[aria-busy="true"]');
      if (answer) w.__lengths.push((answer.textContent || '').length);
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  const streamed = page.waitForResponse((r) => /\/api\/workspace\/conversations\/\d+\/messages$/.test(r.url()) && r.request().method() === 'POST');
  await page.getByLabel('Întrebarea ta').fill(QUESTION);
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  const response = await streamed;
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('text/event-stream');

  const answer = page.locator('.ws-msg--assistant').last();
  await expect(answer).toContainText(`Conform documentelor companiei: ${docs.docx.fact}`);
  await expect(answer.locator('.ws-msg__answer')).not.toHaveAttribute('aria-busy', 'true');
  const lengths = await page.evaluate(() => (window as unknown as { __lengths: number[] }).__lengths);
  expect(new Set(lengths.filter((n) => n > 0)).size, 'the answer grew piece by piece in the page').toBeGreaterThan(3);

  await expect(page).toHaveURL(/\/workspace\/assistant\/\d+$/);
  state.conversationId = Number(/\/assistant\/(\d+)$/.exec(page.url())?.[1]);
  // The conversation is listed under the first question, as its title.
  await expect(page.getByRole('navigation', { name: 'Conversații' }).getByRole('link', { name: /Care este discountul maxim/ })).toBeVisible();

  // The stored answer: complete, local, one citation pointing at the DOCX.
  const detail = await pageGet<{ messages: ApiMessage[] }>(page, `/api/workspace/conversations/${state.conversationId}`);
  const answers = detail.body.messages.filter((m) => m.role === 'assistant');
  const stored = answers[answers.length - 1];
  expect(stored).toMatchObject({ status: 'complete', locality: 'local', model: 'nerva-fake-model' });
  expect(stored?.content).toContain(docs.docx.fact);
  // Under the answer, where it was produced in words; the model id is for admins only (UX-13).
  await expect(answer.locator('.ws-msg__meta')).toContainText('Pe serverul companiei');
  await expect(answer.locator('.ws-msg__meta')).not.toContainText('nerva-fake-model');
  expect(stored?.citations.map((c) => [c.n, c.document_id, c.can_open])).toEqual([[1, state.documentIds.docx, true]]);

  // The inline chip opens the source drawer with the exact passage.
  await answer.getByRole('button', { name: `Sursa 1: ${docs.docx.title}` }).click();
  const source = page.getByRole('dialog', { name: 'Sursa [1]' });
  await expect(source.getByText(docs.docx.title, { exact: true })).toBeVisible();
  await expect(source.locator('blockquote')).toContainText(docs.docx.fact);
  await checkPage(page, 'source-drawer');
  await source.getByRole('link', { name: 'Deschide documentul' }).click();
  await expect(page).toHaveURL(new RegExp(`/workspace/documents/${state.documentIds.docx}$`));
  await expect(page.getByRole('dialog', { name: docs.docx.title })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/workspace/assistant/${state.conversationId}$`));

  // Feedback: thumbs up, then a note; both stored.
  const reloaded = page.locator('.ws-msg--assistant').last();
  await reloaded.getByRole('button', { name: 'Răspuns util' }).click();
  await expect(toast(page, 'Mulțumim! Evaluarea ta a fost salvată.')).toBeVisible();
  await expect(reloaded.getByRole('button', { name: 'Răspuns util' })).toHaveAttribute('aria-pressed', 'true');
  await reloaded.getByRole('button', { name: 'Adaugă o notă' }).click();
  const noteDialog = page.getByRole('dialog', { name: 'Spune-ne mai multe' });
  await noteDialog.getByLabel('Notă').fill('Exact procentul de care aveam nevoie pentru ofertă.');
  await noteDialog.getByRole('button', { name: 'Salvează' }).click();
  await expect(toast(page, 'Nota a fost salvată.')).toBeVisible();
  const rated = await pageGet<{ messages: ApiMessage[] }>(page, `/api/workspace/conversations/${state.conversationId}`);
  expect(rated.body.messages.find((m) => m.id === stored?.id)).toMatchObject({ feedback: 1, feedback_note: 'Exact procentul de care aveam nevoie pentru ofertă.' });
  await checkPage(page, 'assistant');
});

test('through the real hub stack answers stream token by token, and Stop stores the answer as cancelled', async () => {
  const page = need(state.member, 'member page');
  // HTTP level: read the stream from inside the page and time each token event.
  const probe = await page.evaluate(async ({ departmentId, question }) => {
    const session = await (await fetch('/api/workspace/session', { cache: 'no-store' })).json() as { csrf_token: string };
    const headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token };
    const created = await fetch('/api/workspace/conversations', { method: 'POST', headers, body: JSON.stringify({ department_id: departmentId, title: 'Probă de streaming' }) });
    const conversation = await created.json() as { id: number };
    const started = performance.now();
    const response = await fetch(`/api/workspace/conversations/${conversation.id}/messages`, {
      method: 'POST', headers: { ...headers, Accept: 'text/event-stream' }, body: JSON.stringify({ content: question }),
    });
    const reader = (response.body as ReadableStream<Uint8Array>).getReader();
    const decoder = new TextDecoder();
    const tokenTimes: number[] = [];
    let reads = 0;
    let text = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      reads += 1;
      const piece = decoder.decode(value, { stream: true });
      text += piece;
      for (const _ of piece.matchAll(/^event: token$/gm)) tokenTimes.push(performance.now() - started);
    }
    return { id: conversation.id, created: created.status, status: response.status, type: response.headers.get('content-type'), reads, tokenTimes, text };
  }, { departmentId: state.departments[SALES], question: 'Cât este comisionul agenților de vânzări?' });
  expect(probe.created).toBe(201);
  expect(probe.status).toBe(200);
  expect(probe.type).toContain('text/event-stream');
  expect(probe.text).toMatch(/^event: start$/m);
  expect(probe.text).toMatch(/^event: sources$/m);
  expect(probe.text).toMatch(/^event: done$/m);
  expect(probe.text).toContain('Comisionul agenților de vânzări este de 3%');
  expect(probe.tokenTimes.length).toBeGreaterThan(5);
  // The model sends a word every 20 ms; unbuffered, they arrive spread out, in many reads.
  expect(probe.reads).toBeGreaterThan(5);
  expect(probe.tokenTimes[probe.tokenTimes.length - 1] - probe.tokenTimes[0]).toBeGreaterThan(100);

  // UI level: a slow answer, stopped from the composer, is recorded by the server as cancelled.
  await page.goto('/workspace/assistant');
  await page.getByLabel('Întrebarea ta').fill('Ce termene avem săptămâna aceasta? nerva-fake-slow');
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await page.getByRole('button', { name: 'Oprește' }).click();
  await expect(page.locator('.ws-msg--assistant').last()).toContainText('Ai oprit răspunsul');
  await expect(page.getByLabel('Întrebarea ta')).toBeEnabled();
  // The Stop button went away under the pointer: focus is in the question box, not on <body>.
  await expect(page.getByLabel('Întrebarea ta')).toBeFocused();
  await expect(page).toHaveURL(/\/workspace\/assistant\/\d+$/);
  const stoppedId = Number(/\/assistant\/(\d+)$/.exec(page.url())?.[1]);
  await expect.poll(async () => {
    const detail = await pageGet<{ messages: ApiMessage[] }>(page, `/api/workspace/conversations/${stoppedId}`);
    const reply = detail.body.messages.find((m) => m.role === 'assistant');
    return reply ? `${reply.status}:${(reply as ApiMessage & { error_code: string | null }).error_code}` : 'none';
  }, { message: 'the stopped answer is stored as cancelled' }).toBe('error:cancelled');

  // Both probe conversations are deleted from the list's menu, and are gone on the server.
  await page.reload();
  const list = page.getByRole('navigation', { name: 'Conversații' });
  for (const id of [probe.id, stoppedId]) {
    const summary = await pageGet<{ conversation: { title: string } }>(page, `/api/workspace/conversations/${id}`);
    const title = summary.body.conversation.title;
    await list.getByRole('button', { name: `Acțiuni pentru „${title}”` }).click();
    await page.getByRole('menuitem', { name: 'Șterge' }).click();
    const confirm = page.getByRole('alertdialog', { name: 'Ștergi conversația?' });
    await confirm.getByRole('button', { name: 'Șterge' }).click();
    await expect(toast(page, 'Conversația a fost ștearsă.')).toBeVisible();
    await expect(list.getByRole('link', { name: new RegExp(title.slice(0, 20).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })).toHaveCount(0);
    guardFor(page).expectHttp(new RegExp(`/api/workspace/conversations/${id}$`), 404);
    expect((await pageGet(page, `/api/workspace/conversations/${id}`)).status).toBe(404);
  }
  await expect(list.getByRole('link', { name: /Care este discountul maxim/ })).toBeVisible();
});

test('isolation: the Financiar member sees none of Vânzări, and direct requests for its ids answer 404', async () => {
  const page = need(state.finance, 'finance page');
  const docs = need(state.docs, 'documents');
  await page.reload();
  await nav(page, 'Documente');
  await expect(page.getByText('Se adaugă în: Financiar')).toBeVisible();
  await expect(page.getByText('Niciun document încă')).toBeVisible();
  await expect(page.getByLabel('Documentele din').locator('option')).toHaveText([FINANCE, 'Toată compania']);
  for (const doc of Object.values(docs)) await expect(page.getByText(doc.title)).toHaveCount(0);
  await nav(page, 'Asistent');
  await expect(page.getByText('Nicio conversație încă')).toBeVisible();
  await expect(page.getByText(/discountul maxim/i)).toHaveCount(0);

  const g = guardFor(page);
  const ids = Object.values(state.documentIds) as number[];
  for (const id of ids) {
    g.expectHttp(new RegExp(`/api/workspace/documents/${id}$`), 404);
    g.expectHttp(new RegExp(`/api/workspace/documents/${id}/file$`), 404);
  }
  g.expectHttp(new RegExp(`/api/workspace/conversations/${state.conversationId}$`), 404);
  g.expectHttp(new RegExp(`/api/workspace/documents\\?department_id=${state.departments[SALES]}$`), 404);
  for (const id of ids) {
    expect((await pageGet(page, `/api/workspace/documents/${id}`)).status, `document ${id}`).toBe(404);
    expect((await pageGet(page, `/api/workspace/documents/${id}/file`)).status, `file ${id}`).toBe(404);
  }
  const conversation = await pageGet<{ error: string }>(page, `/api/workspace/conversations/${state.conversationId}`);
  expect(conversation.status).toBe(404);
  expect(conversation.body.error).toBe('not_found');
  expect((await pageGet(page, `/api/workspace/documents?department_id=${state.departments[SALES]}`)).status).toBe(404);
  const own = await pageGet<{ documents: unknown[] }>(page, '/api/workspace/documents');
  expect(own.body.documents).toEqual([]);
  const conversations = await pageGet<{ conversations: unknown[] }>(page, `/api/workspace/conversations?department_id=${state.departments[FINANCE]}`);
  expect(conversations.body.conversations).toEqual([]);
});

test('the admin points email at the SMTP sink and a test message arrives', async () => {
  const page = need(state.admin, 'admin page');
  await nav(page, 'Administrare');
  await page.getByRole('navigation', { name: 'Secțiunile administrării' }).getByRole('link', { name: 'Email' }).click();
  await expect(page).toHaveURL(/\/workspace\/admin\/email$/);
  await expect(page.getByText('Neconfigurat')).toBeVisible();
  await page.getByLabel('Securitatea conexiunii').selectOption('none');
  await page.getByLabel('Server SMTP').fill('127.0.0.1');
  await page.getByLabel('Port', { exact: true }).fill(String(SMTP_PORT));
  await page.getByLabel('Adresa expeditorului').fill('nerva@acme.ro');
  await page.getByLabel(/^Numele expeditorului/).fill('Nerva Acme');
  await page.getByLabel(/^Domenii permise/).fill('acme.ro');
  await page.getByRole('button', { name: 'Salvează' }).click();
  await expect(toast(page, 'Setările de email au fost salvate.')).toBeVisible();
  await expect(page.getByText('Configurat', { exact: true })).toBeVisible();
  const saved = await pageGet<Record<string, unknown>>(page, '/api/workspace/admin/smtp');
  expect(saved.body).toMatchObject({ host: '127.0.0.1', port: SMTP_PORT, security: 'none', from_address: 'nerva@acme.ro', from_name: 'Nerva Acme', allowed_domains: ['acme.ro'], configured: true, has_password: false });

  await expect(page.getByLabel('Trimite la')).toHaveValue(ADMIN.email);
  await page.getByRole('button', { name: 'Trimite testul' }).click();
  await expect(page.locator('.ws-notice').getByText(`Mesajul de test a fost acceptat de server pentru ${ADMIN.email}.`)).toBeVisible();
  // …and said by a status region that was on the page before the result (A11Y-09).
  await expect(page.locator('p.ws-sr-only[role="status"]').filter({ hasText: `Mesajul de test a fost acceptat de server pentru ${ADMIN.email}.` })).toHaveCount(1);
  const mail = await waitForMail((m) => m.subject === 'Nerva Workspace — test de email', 'the SMTP test message');
  expect(mail.rcpt_tos).toEqual([ADMIN.email]);
  expect(mail.mail_from).toBe('nerva@acme.ro');
  expect(mail.from).toContain('Nerva Acme');
  expect(mail.text).toContain('trimiterea emailurilor funcționează');
  await checkPage(page, 'admin-email');
});

test('"Trimite pe email": the member asks, the approver approves under "De aprobat", the mail reaches the sink', async () => {
  const member = need(state.member, 'member page');
  const approver = need(state.approver, 'approver page');
  const docs = need(state.docs, 'documents');
  const subject = 'Discount clienți noi — Țara Bârsei';
  const recipient = 'client.nou@acme.ro';
  // SMTP was off when this page loaded; a fresh read of the conversation offers email now.
  await member.goto(`/workspace/assistant/${state.conversationId}`);
  const answer = member.locator('.ws-msg--assistant').last();
  await answer.getByRole('button', { name: 'Trimite pe email' }).click();
  const dialog = member.getByRole('dialog', { name: 'Trimite pe email' });
  await expect(dialog.getByText('2 persoane pot aproba această cerere.')).toBeVisible();
  await expect(dialog.getByLabel('Mesaj')).toHaveValue(new RegExp(docs.docx.fact.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  await expect(dialog.getByLabel('Subiect')).toHaveValue(`Răspuns Nerva: ${QUESTION}`);
  await dialog.getByLabel('Destinatari').fill(recipient);
  await dialog.getByLabel('Subiect').fill(subject);
  await dialog.getByRole('button', { name: 'Cere aprobarea' }).click();
  const done = member.getByRole('dialog', { name: 'Cererea a fost trimisă' });
  await expect(done).toContainText(recipient);
  await done.getByRole('link', { name: 'Vezi cererea' }).click();
  await expect(member).toHaveURL(/\/workspace\/approvals\/\d+$/);
  const approvalId = Number(/\/approvals\/(\d+)$/.exec(member.url())?.[1]);
  const requestDrawer = member.getByRole('dialog', { name: `Cererea #${approvalId}` });
  await expect(requestDrawer.getByText('În așteptare')).toBeVisible();
  await expect(requestDrawer.getByText(`${SALES_APPROVER.name}, ${ADMIN.name}`).or(requestDrawer.getByText(`${ADMIN.name}, ${SALES_APPROVER.name}`))).toBeVisible();
  expect(readMail().some((m) => m.subject === subject), 'nothing is sent before the approval').toBe(false);
  await checkPage(member, 'approvals-member');

  // The approver's inbox ("De aprobat") lists it; approving executes it.
  await approver.reload();
  await nav(approver, 'Aprobări');
  await expect(approver.getByRole('tab', { name: /De aprobat/ })).toHaveAttribute('aria-selected', 'true');
  const inbox = approver.getByRole('table', { name: 'De aprobat' });
  await expect(inbox.getByRole('row')).toHaveCount(2);
  await expect(inbox).toContainText(SALES_MEMBER.name);
  await checkPage(approver, 'approvals');
  await inbox.getByRole('button').first().click();
  const drawer = approver.getByRole('dialog', { name: `Cererea #${approvalId}` });
  await expect(drawer).toContainText(recipient);
  await expect(drawer).toContainText(subject);
  await drawer.getByRole('button', { name: 'Aprobă' }).click();
  const confirm = approver.getByRole('alertdialog', { name: 'Aprobi cererea?' });
  await confirm.getByLabel(/^Notă pentru solicitant/).fill('Trimis clientului, mulțumesc.');
  await confirm.getByRole('button', { name: 'Aprobă' }).click();
  await expect(toast(approver, 'Cererea a fost aprobată și executată.')).toBeVisible();
  await expect(drawer.getByText('Aprobată și executată')).toBeVisible();
  await expect(drawer.getByText(`Trimis către: ${recipient}`)).toBeVisible();
  // Once decided, the preview is the action that was asked for, not what approving „will" do (UX-20).
  await expect(drawer.getByRole('heading', { name: 'Acțiunea cerută' })).toBeVisible();

  const mail = await waitForMail((m) => m.subject === subject, 'the approved answer email');
  expect(mail.rcpt_tos).toEqual([recipient]);
  expect(mail.mail_from).toBe('nerva@acme.ro');
  expect(mail.text).toContain(docs.docx.fact);
  const stored = await pageGet<{ status: string; decider: { name: string }; decision_note: string; result: { sent_to: string[] } }>(approver, `/api/workspace/approvals/${approvalId}`);
  expect(stored.body).toMatchObject({ status: 'approved', decider: { name: SALES_APPROVER.name }, decision_note: 'Trimis clientului, mulțumesc.', result: { sent_to: [recipient] } });

  // The member is told: the bell counts it, and the notification opens the request.
  await member.goto('/workspace/assistant');
  const bell = member.getByRole('button', { name: /^Notificări — \d+ necitit/ });
  await expect(bell).toBeVisible();
  await bell.click();
  const panel = member.getByRole('dialog', { name: 'Notificări' });
  await panel.getByRole('button', { name: /Cerere aprobată/ }).first().click();
  await expect(member).toHaveURL(new RegExp(`/workspace/approvals/${approvalId}$`));
  const opened = member.getByRole('dialog', { name: `Cererea #${approvalId}` });
  await expect(opened.getByText('Aprobată și executată')).toBeVisible();
  await opened.getByRole('button', { name: 'Închide' }).first().click();
  await expect(opened).toBeHidden();
  await expect(member).toHaveURL(/\/workspace\/approvals$/);
});

const REPORT_NAME = 'Situația zilnică a vânzărilor';

interface ApiRun {
  id: number; status: string; content_md: string | null; citations: { n: number; document_id: number; title: string; can_open?: boolean }[];
  shared_company: boolean; error: string | null; report_name: string; department_name: string; locality: string | null;
}

test('the member creates a daily report and runs it now: it succeeds as Markdown with sources, and the HTML and Markdown exports download', async () => {
  const page = need(state.member, 'member page');
  const docs = need(state.docs, 'documents');
  await nav(page, 'Rapoarte');
  await expect(page.getByText('Niciun raport încă')).toBeVisible();
  await page.getByRole('button', { name: 'Raport nou' }).first().click();
  const form = page.getByRole('dialog', { name: 'Raport nou' });
  await expect(form.getByLabel('Departament', { exact: true })).toHaveValue(String(state.departments[SALES]));
  await form.getByLabel('Nume', { exact: true }).fill(REPORT_NAME);
  await form.getByLabel('Ce trebuie să conțină raportul').fill(
    'Rezumă politica de discount, comisioanele agenților și încasările pe județe. Încheie cu un tabel al cifrelor cheie.');
  for (const key of ['docx', 'pdf', 'xlsx'] as const) await form.getByRole('checkbox', { name: docs[key].title, exact: true }).check();
  await expect(form.getByText('3 documente alese')).toBeVisible();
  await form.getByRole('radio', { name: /^Zilnic/ }).check();
  await form.getByLabel('Ora', { exact: true }).fill('08:15');
  await expect(form.getByLabel('Fus orar')).toHaveValue('Europe/Bucharest');
  await form.getByRole('button', { name: 'Creează raportul' }).click();
  await expect(toast(page, `Raportul „${REPORT_NAME}” a fost creat.`)).toBeVisible();
  await expect(page).toHaveURL(/\/workspace\/reports\/\d+$/);
  const reportId = Number(/\/reports\/(\d+)$/.exec(page.url())?.[1]);
  state.reportId = reportId;
  await expect(page.getByRole('heading', { level: 1, name: REPORT_NAME })).toBeVisible();
  await expect(page.getByText('Zilnic, la 08:15')).toBeVisible();

  const report = await pageGet<Record<string, unknown>>(page, `/api/workspace/reports/${reportId}`);
  expect(report.body).toMatchObject({ name: REPORT_NAME, department_id: state.departments[SALES], schedule_kind: 'daily', schedule_time: '08:15', timezone: 'Europe/Bucharest', delivery_status: 'none' });
  expect((report.body.document_ids as number[]).sort()).toEqual([state.documentIds.docx, state.documentIds.pdf, state.documentIds.xlsx].sort());
  expect(report.body.next_run_at as number).toBeGreaterThan(Date.now() / 1000);
  await checkPage(page, 'report-detail');

  await page.getByRole('button', { name: 'Rulează acum' }).click();
  await expect(page).toHaveURL(/\/workspace\/report-runs\/\d+$/);
  state.runId = Number(/\/report-runs\/(\d+)$/.exec(page.url())?.[1]);
  // The run page's h1 is the report's name, and it holds the focus the navigation gave it even
  // though a loading heading came first (A11Y-03).
  await expect(page.getByRole('heading', { level: 1, name: REPORT_NAME })).toBeFocused();
  const meta = page.locator('.ws-run-meta');
  await expect(meta.getByText('Gata', { exact: true })).toBeVisible({ timeout: 60_000 });
  const article = page.locator('article.ws-report');
  // The report's own title sits one level under the page's h1.
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
  await expect(article.getByRole('heading', { level: 2 }).first()).toHaveText(`Raport: ${REPORT_NAME}`);
  await expect(article.getByRole('heading', { name: 'Surse' })).toBeVisible();
  await expect(article.getByRole('table')).toBeVisible();
  await expect(article.getByRole('button', { name: /^Sursa 1: / }).first()).toBeVisible();
  // How it was produced: where, in words; the model id is for admins only (UX-13).
  await expect(meta).toContainText('Unde a fost generat');
  await expect(meta).toContainText('Pe serverul companiei');
  await expect(meta).not.toContainText('nerva-fake-model');
  // The "Nr." column's chips stand alone in their cell: full 24 px targets (A11Y-15).
  const leadChip = await article.locator('td > .ws-cite').first().boundingBox();
  expect(leadChip && leadChip.width >= 24 && leadChip.height >= 24, 'a chip alone in its cell is 24 × 24 px').toBe(true);

  const run = await pageGet<ApiRun>(page, `/api/workspace/report-runs/${state.runId}`);
  expect(run.body).toMatchObject({ status: 'succeeded', error: null, shared_company: false, report_name: REPORT_NAME, department_name: SALES, locality: 'local' });
  const markdown = run.body.content_md ?? '';
  expect(markdown.split('\n')[0]).toBe(`# Raport: ${REPORT_NAME}`);
  expect(markdown).not.toContain('Raport: Raport');
  expect(markdown).toMatch(/^## Surse$/m);
  const cited = new Set(run.body.citations.map((c) => c.document_id));
  expect(cited.size).toBeGreaterThan(0);
  for (const id of cited) expect([state.documentIds.docx, state.documentIds.pdf, state.documentIds.xlsx]).toContain(id);

  // Exports: the Markdown is the report itself; the HTML is a standalone page with no script.
  const [md] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Exportă Markdown' }).click()]);
  expect(md.suggestedFilename()).toMatch(/\.md$/);
  const mdText = readFileSync(await md.path(), 'utf8');
  expect(mdText).toContain(markdown.split('\n')[0]);
  expect(mdText).toMatch(/^## Surse$/m);
  const [html] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Exportă HTML' }).click()]);
  expect(html.suggestedFilename()).toMatch(/\.html$/);
  const htmlText = readFileSync(await html.path(), 'utf8');
  expect(htmlText.toLowerCase()).toContain('<!doctype html>');
  expect(htmlText).toContain(REPORT_NAME);
  expect(htmlText).toContain('Surse');
  expect(htmlText.toLowerCase()).not.toContain('<script');
  await checkPage(page, 'run-view');
  // The three ways out are one group named by its caption; on a phone the caption shows over the
  // short labels („Markdown", „HTML"), and each download keeps its full name (UX-21; that no label
  // wraps at 390 or 320 px is checkPage's layout check).
  const exportGroup = page.getByRole('group', { name: 'Exportă' });
  await expect(page.locator('.ws-export__caption')).toBeHidden();
  await page.setViewportSize(PHONE);
  await expect(page.locator('.ws-export__caption')).toHaveText('Exportă');
  await expect(page.locator('.ws-export__caption')).toBeVisible();
  await expect(exportGroup.getByText('Markdown', { exact: true })).toBeVisible();
  for (const name of ['Exportă Markdown', 'Exportă HTML']) await expect(exportGroup.getByRole('link', { name, exact: true })).toBeVisible();
  await expect(exportGroup.getByRole('button', { name: 'Tipărește', exact: true })).toBeVisible();
  await page.setViewportSize(DESKTOP);

  await page.getByRole('link', { name: 'Înapoi la raport' }).click();
  await page.getByRole('link', { name: 'Toate rapoartele' }).click();
  const list = page.getByRole('table', { name: 'Rapoarte' });
  await expect(list.getByRole('link', { name: REPORT_NAME })).toBeVisible();
  await expect(list.getByText('Gata', { exact: true })).toBeVisible();
  await expect(list.getByText('Zilnic, la 08:15')).toBeVisible();
  await checkPage(page, 'reports');
  for (const width of [768, 1024, 1180]) {
    await page.setViewportSize({ width, height: 800 });
    expect(await tableScrollsSideways(page, 'Rapoarte'), `reports list scrolls sideways at ${width} px`).toBe(0);
    await expect(list.getByRole('button', { name: `Rulează acum „${REPORT_NAME}”` })).toBeVisible();
  }
  await page.setViewportSize(DESKTOP);

  // A fresh deep link whose deferred reports chunk fails keeps the shell usable; reloading
  // after the network recovers fetches the chunk and reaches the report list.
  const retryPage = await page.context().newPage();
  const reportsChunk = '**/assets/reports-*.js';
  await retryPage.route(reportsChunk, (route) => route.abort('failed'));
  try {
    await retryPage.goto('/workspace/reports');
    await expect(retryPage.getByRole('alert').getByText('Pagina nu s-a putut încărca')).toBeVisible();
    await retryPage.unroute(reportsChunk);
    await retryPage.getByRole('button', { name: 'Încearcă din nou' }).click();
    await expect(retryPage.getByRole('table', { name: 'Rapoarte' })).toBeVisible();
  } finally {
    await retryPage.close();
  }

  // A member may see reports they cannot run. Their table still needs the same compact layout.
  const readonlyPage = await page.context().newPage();
  guard(readonlyPage, 'read-only reports');
  await readonlyPage.route('**/api/workspace/reports**', async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() !== 'GET' || url.pathname !== '/api/workspace/reports') return route.continue();
    const response = await route.fetch();
    const body = await response.json() as { reports: Record<string, unknown>[] };
    await route.fulfill({ response, json: { ...body, reports: body.reports.map((report) => ({ ...report, can_run: false })) } });
  });
  try {
    await readonlyPage.goto('/workspace/reports');
    const readonlyTable = readonlyPage.getByRole('table', { name: 'Rapoarte' });
    await expect(readonlyTable.getByRole('row')).toHaveCount(2);
    await expect(readonlyTable.getByRole('button', { name: /Rulează acum/ })).toHaveCount(0);
    for (const width of [768, 1024, 1180]) {
      await readonlyPage.setViewportSize({ width, height: 800 });
      expect(await tableScrollsSideways(readonlyPage, 'Rapoarte'), `read-only reports scroll at ${width}px`).toBe(0);
      const padding = await readonlyTable.locator('th').first().evaluate((th) => parseFloat(getComputedStyle(th).paddingLeft));
      expect(padding, `read-only reports have compact cells at ${width}px`).toBe(8);
    }
  } finally {
    await readonlyPage.close();
  }
});

test('a company-wide share request is approved by the admin, and the Financiar member reads the shared report', async () => {
  const docs = need(state.docs, 'documents');
  const member = need(state.member, 'member page');
  const admin = need(state.admin, 'admin page');
  const finance = need(state.finance, 'finance page');
  const runId = need(state.runId, 'run id');

  // Before: nothing is shared, and the run itself is out of the Financiar member's reach.
  await nav(finance, 'Rapoarte partajate');
  await expect(finance.getByText('Niciun raport partajat încă')).toBeVisible();
  guardFor(finance).expectHttp(new RegExp(`/api/workspace/report-runs/${runId}$`), 404);
  expect((await pageGet(finance, `/api/workspace/report-runs/${runId}`)).status).toBe(404);

  await member.goto(`/workspace/report-runs/${runId}`);
  await member.getByRole('button', { name: 'Partajează în companie' }).click();
  const dialog = member.getByRole('dialog', { name: 'Partajezi raportul cu toată compania?' });
  await expect(dialog.getByText('1 persoană poate aproba această cerere.')).toBeVisible();
  await dialog.getByRole('button', { name: 'Trimite cererea' }).click();
  await expect(toast(member, 'Cererea a fost trimisă spre aprobare. O urmărești în Aprobări → Cererile mele.')).toBeVisible();
  const mine = await pageGet<{ items: { id: number; kind: string; status: string }[] }>(member, '/api/workspace/approvals?box=mine');
  const request = mine.body.items.find((a) => a.kind === 'report.share_company');
  expect(request?.status).toBe('pending');

  // While it waits, the run says so and does not offer a second request (F8).
  await member.reload();
  await expect(member.getByText('Partajarea în companie așteaptă aprobarea')).toBeVisible();
  await expect(member.getByRole('button', { name: 'Partajează în companie' })).toHaveCount(0);

  // The admin decides it from "De aprobat".
  await admin.reload();
  await nav(admin, 'Aprobări');
  const inbox = admin.getByRole('table', { name: 'De aprobat' });
  await expect(inbox.getByRole('row')).toHaveCount(2);
  await inbox.getByRole('button').first().click();
  const drawer = admin.getByRole('dialog', { name: `Cererea #${request?.id}` });
  await expect(drawer).toContainText('Rularea raportului va deveni vizibilă pentru toată compania');
  await drawer.getByRole('button', { name: 'Aprobă' }).click();
  await admin.getByRole('alertdialog', { name: 'Aprobi cererea?' }).getByRole('button', { name: 'Aprobă' }).click();
  await expect(toast(admin, 'Cererea a fost aprobată și executată.')).toBeVisible();
  await expect(drawer.getByText('Aprobată și executată')).toBeVisible();
  await drawer.getByRole('button', { name: 'Închide' }).first().click();

  // After: the run is marked shared, and the Financiar member finds and opens it.
  await member.reload();
  await expect(member.locator('.ws-run-meta').getByText('Partajat în companie')).toBeVisible();
  await member.setViewportSize({ width: 320, height: 640 });
  const visibilityBadge = member.locator('.ws-run-meta').getByText('Partajat în companie');
  const badgeHeight = await visibilityBadge.evaluate((badge) => badge.getBoundingClientRect().height);
  expect(badgeHeight, 'shared visibility badge wraps at 320 px').toBeLessThanOrEqual(24);
  await member.setViewportSize(DESKTOP);
  await finance.reload();
  const shared = finance.getByRole('table', { name: 'Rapoarte partajate' });
  const row = shared.getByRole('row').filter({ hasText: REPORT_NAME });
  await expect(row).toBeVisible();
  await expect(row).toContainText(SALES);
  await checkPage(finance, 'shared-reports');
  await row.getByRole('link', { name: REPORT_NAME }).click();
  await expect(finance).toHaveURL(new RegExp(`/workspace/shared-reports/${runId}$`));
  await expect(finance.locator('article.ws-report').getByRole('heading', { name: 'Surse' })).toBeVisible();
  const seen = await pageGet<ApiRun>(finance, `/api/workspace/report-runs/${runId}`);
  expect(seen.status).toBe(200);
  expect(seen.body).toMatchObject({ status: 'succeeded', shared_company: true });
  // Its sources are Vânzări documents: the excerpt is shared, the document is not.
  expect(seen.body.citations.length).toBeGreaterThan(0);
  expect(seen.body.citations.every((c) => c.can_open === false)).toBe(true);
  await finance.locator('article.ws-report').getByRole('button', { name: new RegExp(`^Sursa \\d+: ${docs.docx.title}$`) }).first().click();
  const source = finance.getByRole('dialog', { name: /^Sursa \[\d+\]$/ });
  await expect(source.locator('blockquote')).toContainText(docs.docx.fact);
  await expect(source.getByText(/Documentul sursă nu îți este accesibil/)).toBeVisible();
  await expect(source.getByRole('link')).toHaveCount(0);
  await checkPage(finance, 'shared-report-source');
  await source.getByRole('button', { name: 'Închide' }).first().click();
  await expect(source).toBeHidden();
  await checkPage(finance, 'shared-report-run');
});

test('the admin publishes a Vânzări document company-wide at once, and the Financiar member can read it', async () => {
  const admin = need(state.admin, 'admin page');
  const finance = need(state.finance, 'finance page');
  const docs = need(state.docs, 'documents');
  const pdfId = need(state.documentIds.pdf, 'pdf id');
  await nav(admin, 'Documente');
  await admin.getByLabel('Departament', { exact: true }).selectOption({ label: SALES });
  const table = admin.getByRole('table', { name: 'Documente' });
  await expect(table.getByRole('row')).toHaveCount(5);
  await table.getByRole('button', { name: `Acțiuni pentru „${docs.pdf.title}”` }).click();
  await admin.getByRole('menuitem', { name: 'Publică în toată compania' }).click();
  const dialog = admin.getByRole('dialog', { name: 'Publici documentul în toată compania?' });
  await expect(dialog.getByText('Ca administrator, publicarea se aplică imediat')).toBeVisible();
  await dialog.getByRole('button', { name: 'Publică acum' }).click();
  await expect(toast(admin, `„${docs.pdf.title}” este acum disponibil în toată compania.`)).toBeVisible();
  await expect(table.getByRole('row').filter({ hasText: docs.pdf.title })).toContainText('Toată compania');
  const published = await pageGet<{ visibility: string }>(admin, `/api/workspace/documents/${pdfId}`);
  expect(published.body.visibility).toBe('company');
  const approvals = await pageGet<{ items: { kind: string; status: string; decision_note: string | null; requester: { name: string } }[] }>(admin, '/api/workspace/approvals?box=all');
  expect(approvals.body.items.find((a) => a.kind === 'document.company_publish')).toMatchObject({ status: 'approved', decision_note: null, requester: { name: ADMIN.name } });

  await finance.goto('/workspace/documents');
  await finance.getByLabel('Documentele din').selectOption({ label: 'Toată compania' });
  const visible = finance.getByRole('table', { name: 'Documente' });
  await expect(visible.getByRole('row')).toHaveCount(2);
  await expect(visible.getByRole('button', { name: docs.pdf.title, exact: true })).toBeVisible();
  expect((await pageGet(finance, `/api/workspace/documents/${pdfId}`)).status).toBe(200);
  const others = (Object.entries(state.documentIds) as [SampleKey, number][]).filter(([key]) => key !== 'pdf');
  for (const [, id] of others) {
    guardFor(finance).expectHttp(new RegExp(`/api/workspace/documents/${id}$`), 404);
    expect((await pageGet(finance, `/api/workspace/documents/${id}`)).status).toBe(404);
  }

  // In the shared report, that source now leads to the document and its original file.
  const runId = need(state.runId, 'run id');
  await finance.goto(`/workspace/shared-reports/${runId}`);
  await finance.locator('article.ws-report').getByRole('button', { name: new RegExp(`^Sursa \\d+: ${docs.pdf.title}$`) }).first().click();
  const source = finance.getByRole('dialog', { name: /^Sursa \[\d+\]$/ });
  await expect(source.getByText(/Documentul sursă nu îți este accesibil/)).toHaveCount(0);
  const [original] = await Promise.all([finance.waitForEvent('download'), source.getByRole('link', { name: 'Descarcă originalul' }).click()]);
  expect(readFileSync(await original.path())).toEqual(readFileSync(docs.pdf.path));
  await source.getByRole('link', { name: 'Deschide documentul' }).click();
  await expect(finance).toHaveURL(new RegExp(`/workspace/documents/${pdfId}$`));
  await expect(finance.getByRole('dialog', { name: docs.pdf.title }).getByRole('region', { name: 'Previzualizare text' })).toContainText(docs.pdf.fact);
});

interface ApiAudit { id: number; action: string; actor_name: string | null; actor_email: string | null; details: Record<string, unknown> }

test('audit names the person behind every action, the chain verifies, and the CSV export downloads', async () => {
  const page = need(state.admin, 'admin page');
  await nav(page, 'Administrare');
  await page.getByRole('navigation', { name: 'Secțiunile administrării' }).getByRole('link', { name: 'Audit' }).click();
  await expect(page).toHaveURL(/\/workspace\/admin\/audit$/);
  const all = await pageGet<{ items: ApiAudit[] }>(page, '/api/workspace/admin/audit?limit=200');
  const did = (action: string, actor: Person) => all.body.items.some((e) => e.action === action && e.actor_name === actor.name && e.actor_email === actor.email);
  expect(did('auth.setup', ADMIN)).toBe(true);
  expect(did('department.created', ADMIN)).toBe(true);
  expect(did('user.created', ADMIN)).toBe(true);
  expect(did('auth.invite_accepted', SALES_MEMBER)).toBe(true);
  expect(did('document.uploaded', SALES_MEMBER)).toBe(true);
  expect(did('chat.asked', SALES_MEMBER)).toBe(true);
  expect(did('message.feedback', SALES_MEMBER)).toBe(true);
  expect(did('smtp.updated', ADMIN)).toBe(true);
  expect(did('smtp.tested', ADMIN)).toBe(true);
  expect(did('approval.requested', SALES_MEMBER)).toBe(true);
  expect(did('approval.approved', SALES_APPROVER)).toBe(true);
  expect(did('report.created', SALES_MEMBER)).toBe(true);
  expect(did('report.run_started', SALES_MEMBER)).toBe(true);
  expect(did('document.published', ADMIN)).toBe(true);
  expect(all.body.items.filter((e) => e.action === 'document.uploaded')).toHaveLength(4);

  // The table shows them with names and translated actions; the actor filter narrows to one person.
  const table = page.getByRole('table', { name: 'Audit' });
  await expect(table.getByRole('row').filter({ hasText: 'Document publicat în toată compania' }).first()).toContainText(ADMIN.name);
  const users = await pageGet<{ users: { id: number; email: string }[] }>(page, '/api/workspace/admin/users');
  const memberId = users.body.users.find((u) => u.email === SALES_MEMBER.email)?.id;
  await page.getByLabel('Persoana').selectOption(String(memberId));
  const filteredResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === '/api/workspace/admin/audit' && url.searchParams.get('actor_id') === String(memberId);
  });
  await page.getByRole('button', { name: 'Aplică filtrele' }).click();
  const filtered = await (await filteredResponse).json() as { items: ApiAudit[] };
  const rows = table.getByRole('row');
  await expect(rows).toHaveCount(filtered.items.length + 1);
  await expect(table.getByRole('row').filter({ hasText: 'Document încărcat' })).toHaveCount(4);
  const count = await rows.count();
  expect(count).toBeGreaterThan(5);
  for (let i = 1; i < count; i += 1) await expect(rows.nth(i)).toContainText(SALES_MEMBER.name);
  await page.getByRole('button', { name: 'Resetează' }).click();

  // An entry's drawer reads the codes it recorded as words, never raw (UX-13): the email settings'
  // security and password change, as the admin saved them.
  await table.getByRole('row').filter({ hasText: 'Setări de email modificate' }).first().getByRole('button', { name: /^Detalii: Detaliile intrării/ }).click();
  const entry = page.getByRole('dialog', { name: /^Intrarea #\d+ din jurnal$/ });
  await expect(entry.getByText('Fără criptare', { exact: true })).toBeVisible();
  await expect(entry.getByText('Parola a rămas neschimbată', { exact: true })).toBeVisible();
  await expect(entry.getByText('kept', { exact: true })).toHaveCount(0);
  await entry.getByRole('button', { name: 'Închide' }).first().click();
  await expect(entry).toBeHidden();

  await page.getByRole('button', { name: 'Verifică lanțul' }).click();
  const notice = page.locator('.ws-notice').filter({ hasText: 'Lanțul de audit este intact' });
  await expect(notice).toBeVisible();
  const verify = await pageGet<{ ok: boolean; checked: number }>(page, '/api/workspace/admin/audit/verify');
  expect(verify.body.ok).toBe(true);
  // Romanian plural, by the count (UX-08): „1 intrare", „3 intrări", „20 de intrări".
  const n = verify.body.checked;
  const shown = new Intl.NumberFormat('ro-RO').format(n);
  const form = new Intl.PluralRules('ro-RO').select(n);
  const counted = form === 'one' ? `${shown} intrare; nu a fost modificată.` : form === 'few' ? `${shown} intrări; niciuna nu a fost modificată.` : `${shown} de intrări; niciuna nu a fost modificată.`;
  await expect(notice).toContainText(`Am verificat ${counted}`);

  const [csv] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Exportă CSV' }).click()]);
  expect(csv.suggestedFilename()).toMatch(/\.csv$/);
  const text = readFileSync(await csv.path(), 'utf8');
  const lines = text.trim().split(/\r?\n/);
  expect(lines.length).toBeGreaterThan(all.body.items.length);
  expect(lines[0]).toMatch(/action/);
  expect(text).toContain(SALES_MEMBER.email);
  expect(lines.some((l) => l.includes('document.uploaded') && l.includes(SALES_MEMBER.name))).toBe(true);
  await checkPage(page, 'admin-audit');
});

test('usage shows the real activity, and the organisation page tests the model', async () => {
  const page = need(state.admin, 'admin page');
  const sections = page.getByRole('navigation', { name: 'Secțiunile administrării' });
  await sections.getByRole('link', { name: 'Utilizare' }).click();
  await expect(page).toHaveURL(/\/workspace\/admin\/usage$/);
  const stats = await pageGet<{ totals: Record<string, number>; daily: { questions: number; report_runs: number }[] }>(page, '/api/workspace/admin/stats?days=30');
  // Three questions were asked (two of their conversations were deleted since: still counted)
  // and one report ran; one answer was rated helpful.
  expect(stats.body.totals).toMatchObject({
    users: 4, active_users_7d: 4, documents: 4, conversations: 1, questions: 3, reports: 1, report_runs: 1,
    feedback_up: 1, feedback_down: 0, approvals_pending: 0,
  });
  expect(stats.body.daily.reduce((n, d) => n + d.questions, 0)).toBe(3);
  expect(stats.body.daily.reduce((n, d) => n + d.report_runs, 0)).toBe(1);
  const kpi = (label: string) => page.locator('.ws-kpi').filter({ has: page.locator('.ws-kpi__label', { hasText: new RegExp(`^${label}$`) }) }).locator('.ws-kpi__value');
  await expect(kpi('Utilizatori')).toHaveText('4');
  await expect(kpi('Documente')).toHaveText('4');
  await expect(kpi('Rapoarte')).toHaveText('1');
  await expect(kpi('Întrebări în perioadă')).toHaveText('3');
  await expect(kpi('Răspunsuri apreciate')).toHaveText(/^100\s?%$/);
  await expect(page.getByRole('table', { name: 'Pe departamente' }).getByRole('row').filter({ hasText: SALES })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.setViewportSize({ width: 320, height: 640 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth), 'usage chart widens the page during narrow resize').toBeLessThanOrEqual(321);
  const plot = page.locator('.ws-chart__plot').first();
  await page.setViewportSize({ width: 390, height: 844 });
  await plot.focus();
  await expect(page.locator('.ws-chart__tip').first()).toBeVisible();
  await page.setViewportSize({ width: 320, height: 640 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth), 'focused usage tooltip widens the page').toBeLessThanOrEqual(321);
  await page.setViewportSize({ width: 390, height: 844 });
  await plot.locator('.ws-chart__hit').last().hover();
  await expect(page.locator('.ws-chart__tip').first()).toBeVisible();
  await page.setViewportSize({ width: 320, height: 640 });
  const hovered = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, tipRight: document.querySelector('.ws-chart__tip')?.getBoundingClientRect().right ?? 0 }));
  expect(hovered.scroll, 'hovered usage tooltip widens the page').toBeLessThanOrEqual(321);
  expect(hovered.tipRight, 'hovered usage tooltip leaves the viewport').toBeLessThanOrEqual(321);
  await page.mouse.move(0, 0);
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.setViewportSize(DESKTOP);
  await checkPage(page, 'admin-usage');

  await sections.getByRole('link', { name: 'Organizație' }).click();
  await expect(page).toHaveURL(/\/workspace\/admin\/organisation$/);
  await expect(page.getByLabel('Numele organizației')).toHaveValue(ORG);
  await expect(page.getByRole('radio', { name: /^Doar model local/ })).toBeChecked();
  await page.getByRole('button', { name: 'Testează modelul' }).click();
  await expect(page.locator('.ws-notice').getByText(/^Modelul a răspuns în /)).toBeVisible();
  await expect(page.locator('.ws-notice').getByText('nerva-fake-model · Pe serverul companiei')).toBeVisible();
  await checkPage(page, 'admin-organisation');
});

async function signIn(page: Page, person: Person, password: string): Promise<void> {
  await page.goto('/workspace/');
  await expect(page.getByRole('heading', { name: 'Conectează-te' })).toBeVisible();
  await page.getByLabel('Email', { exact: true }).fill(person.email);
  await page.getByLabel('Parolă', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Conectează-te' }).click();
  await expect(userMenu(page, person.name)).toBeVisible();
}

async function me(page: Page): Promise<{ status: number; user?: { locale: string; theme: string } }> {
  const response = await pageGet<{ user: { locale: string; theme: string } }>(page, '/api/workspace/me');
  return { status: response.status, user: response.body?.user };
}

test('profile: English and back, the dark theme, closing the other sessions, and a password change', async ({ browser }) => {
  const page = need(state.member, 'member page');
  await userMenu(page, SALES_MEMBER.name).click();
  await page.getByRole('menuitem', { name: 'Profil' }).click();
  await expect(page).toHaveURL(/\/workspace\/profile$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Profil' })).toBeVisible();
  await checkPage(page, 'profile');

  // Language: English from the profile, Romanian again from the account menu; both stored.
  await page.getByLabel('Limbă').selectOption('en');
  await expect(page.getByRole('heading', { level: 1, name: 'Profile' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Assistant' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect.poll(async () => (await me(page)).user?.locale).toBe('en');
  await checkPage(page, 'profile-en');
  await page.getByRole('button', { name: `Your account: ${SALES_MEMBER.name}` }).click();
  await page.getByRole('menuitemradio', { name: 'Română' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Profil' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ro');
  await expect.poll(async () => (await me(page)).user?.locale).toBe('ro');

  // Theme: dark applies at once, is stored, survives a reload, and passes the same bar.
  await page.getByRole('radio', { name: /^Întunecată/ }).check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect.poll(async () => (await me(page)).user?.theme).toBe('dark');
  await checkPage(page, 'profile-dark');
  await page.goto(`/workspace/assistant/${state.conversationId}`);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('.ws-msg--assistant').last()).toContainText('Conform documentelor companiei');
  await checkPage(page, 'assistant-dark');
  await page.goto('/workspace/profile');
  await page.getByRole('radio', { name: /^Luminoasă/ }).check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect.poll(async () => (await me(page)).user?.theme).toBe('light');

  // "Close the other sessions" signs a second browser out at once.
  const second = await newPage(browser, 'member-second-browser');
  await signIn(second, SALES_MEMBER, SALES_MEMBER.password);
  await page.reload();
  const sessions = page.getByRole('table', { name: 'Sesiuni active' });
  await expect(sessions.getByRole('row')).toHaveCount(1 + 2);
  await expect(sessions.getByText('Sesiunea curentă')).toHaveCount(1);
  await page.getByRole('button', { name: 'Închide celelalte sesiuni' }).click();
  await page.getByRole('alertdialog', { name: 'Închizi celelalte sesiuni?' }).getByRole('button', { name: 'Închide celelalte sesiuni' }).click();
  await expect(toast(page, '1 sesiune a fost închisă.')).toBeVisible();
  await expect(sessions.getByRole('row')).toHaveCount(1 + 1);
  guardFor(second).allowHttp(/\/api\/workspace\//, 401);
  guardFor(second).expectHttp(/\/api\/workspace\/me$/, 401);
  expect((await me(second)).status).toBe(401);
  await second.reload();
  await expect(second.getByRole('heading', { name: 'Conectează-te' })).toBeVisible();

  // A password change keeps this session, closes the others, and only the new password works.
  await signIn(second, SALES_MEMBER, SALES_MEMBER.password);
  await page.reload();
  await expect(sessions.getByRole('row')).toHaveCount(1 + 2);
  await page.getByLabel('Parola actuală').fill(SALES_MEMBER.password);
  await page.getByLabel('Parola nouă').fill(NEW_MEMBER_PASSWORD);
  await page.getByLabel('Confirmă parola').fill(NEW_MEMBER_PASSWORD);
  await page.getByRole('button', { name: 'Schimbă parola' }).click();
  await expect(toast(page, 'Parola a fost schimbată. Celelalte sesiuni au fost închise.')).toBeVisible();
  await expect(sessions.getByRole('row')).toHaveCount(1 + 1);
  expect((await me(page)).status).toBe(200);
  guardFor(second).allowHttp(/\/api\/workspace\//, 401);
  guardFor(second).expectHttp(/\/api\/workspace\/me$/, 401);
  expect((await me(second)).status).toBe(401);
  await second.close();
});

test('logout ends the session; the old password is refused and the new one signs in', async () => {
  const page = need(state.member, 'member page');
  await userMenu(page, SALES_MEMBER.name).click();
  await page.getByRole('menuitem', { name: 'Deconectare' }).click();
  await expect(page.getByRole('heading', { name: 'Conectează-te' })).toBeVisible();
  await expect(page.getByText('Folosește emailul și parola contului tău de serviciu.')).toBeVisible();
  guardFor(page).expectHttp(/\/api\/workspace\/me$/, 401);
  expect((await me(page)).status).toBe(401);
  await checkPage(page, 'login');

  guardFor(page).expectHttp(/\/api\/workspace\/login$/, 401);
  await page.getByLabel('Email', { exact: true }).fill(SALES_MEMBER.email);
  await page.getByLabel('Parolă', { exact: true }).fill(SALES_MEMBER.password);
  await page.getByRole('button', { name: 'Conectează-te' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Emailul sau parola nu sunt corecte.' })).toBeVisible();
  await page.getByLabel('Parolă', { exact: true }).fill(NEW_MEMBER_PASSWORD);
  await page.getByRole('button', { name: 'Conectează-te' }).click();
  await expect(userMenu(page, SALES_MEMBER.name)).toBeVisible();
  expect((await me(page)).status).toBe(200);
});

test('an admin disables the Financiar member mid-question: the open page lands on sign-in, and the question waits in the composer', async () => {
  const admin = need(state.admin, 'admin page');
  const finance = need(state.finance, 'finance page');
  const question = 'Care sunt termenele de raportare financiară din luna aceasta?';
  await finance.goto('/workspace/assistant');
  await finance.getByLabel('Întrebarea ta').fill(question);

  await admin.goto('/workspace/admin/users');
  await admin.getByRole('button', { name: `Acțiuni pentru ${FIN_MEMBER.name}` }).click();
  await admin.getByRole('menuitem', { name: 'Dezactivează' }).click();
  await admin.getByRole('alertdialog', { name: 'Dezactivezi contul?' }).getByRole('button', { name: 'Dezactivează' }).click();
  await expect(toast(admin, `Cont dezactivat: ${FIN_MEMBER.name}.`)).toBeVisible();
  const row = admin.getByRole('table', { name: 'Utilizatori' }).getByRole('row').filter({ hasText: FIN_MEMBER.email });
  await expect(row).toContainText('Dezactivat');

  // The disabled member's next action answers 401: the app shows sign-in, honestly.
  guardFor(finance).allowHttp(/\/api\/workspace\//, 401);
  await finance.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(finance.getByRole('heading', { name: 'Conectează-te' })).toBeVisible();
  await expect(finance.getByText('Sesiunea ta s-a încheiat. Conectează-te din nou pentru a continua.')).toBeVisible();
  expect((await me(finance)).status).toBe(401);

  // Enabled again, they sign in: the question they had typed is still in the composer (F3).
  await admin.getByRole('button', { name: `Acțiuni pentru ${FIN_MEMBER.name}` }).click();
  await admin.getByRole('menuitem', { name: 'Activează' }).click();
  await admin.getByRole('alertdialog', { name: 'Activezi contul?' }).getByRole('button', { name: 'Activează' }).click();
  await expect(toast(admin, `Cont activat: ${FIN_MEMBER.name}.`)).toBeVisible();
  await finance.getByLabel('Email', { exact: true }).fill(FIN_MEMBER.email);
  await finance.getByLabel('Parolă', { exact: true }).fill(FIN_MEMBER.password);
  await finance.getByRole('button', { name: 'Conectează-te' }).click();
  await expect(userMenu(finance, FIN_MEMBER.name)).toBeVisible();
  await expect(finance.getByLabel('Întrebarea ta')).toHaveValue(question);
  await finance.getByLabel('Întrebarea ta').fill('');
});

test('repeated wrong passwords end in the same generic throttle message for a real and an unknown account', async ({ browser }) => {
  const page = await newPage(browser, 'anonymous');
  await page.goto('/workspace/');
  await expect(page.getByRole('heading', { name: 'Conectează-te' })).toBeVisible();
  const g = guardFor(page);
  g.expectHttp(/\/api\/workspace\/login$/, 401);
  g.expectHttp(/\/api\/workspace\/login$/, 429);

  const attempt = async (email: string, password: string): Promise<{ status: number; error: string; message: string }> => {
    await page.getByLabel('Email', { exact: true }).fill(email);
    await page.getByLabel('Parolă', { exact: true }).fill(password);
    const answered = page.waitForResponse((r) => r.url().endsWith('/api/workspace/login') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Conectează-te' }).click();
    const response = await answered;
    const body = await response.json() as { error: string };
    const notice = page.locator('.ws-notice--danger');
    await expect(notice).toBeVisible();
    await expect(page.getByRole('button', { name: 'Conectează-te' })).toBeEnabled();
    return { status: response.status(), error: body.error, message: (await notice.innerText()).trim() };
  };

  const outcomes: Record<string, { status: number; error: string; message: string }[]> = {};
  for (const email of [FIN_MEMBER.email, 'nimeni.altcineva@acme.ro']) {
    outcomes[email] = [];
    for (let i = 1; i <= 6; i += 1) outcomes[email].push(await attempt(email, `Parola-gresita-numarul-${i}`));
  }
  const [real, unknown] = Object.values(outcomes);
  for (const list of [real, unknown]) {
    expect(list.slice(0, 5).map((o) => [o.status, o.error, o.message]))
      .toEqual(Array(5).fill([401, 'invalid_credentials', 'Emailul sau parola nu sunt corecte.']));
    expect(list[5]).toMatchObject({ status: 429, error: 'too_many_attempts' });
    expect(list[5].message).toMatch(/^Prea multe încercări nereușite\. \S/);
  }
  // Same words for both: nothing tells an existing account from a made-up one.
  const strip = (text: string) => text.replace(/\d+/g, 'N');
  expect(strip(real[5].message)).toBe(strip(unknown[5].message));
  await checkPage(page, 'login-throttled');
});

test('a cited document deleted since: the answer keeps its excerpt, and the source drawer says why it offers no link', async () => {
  const page = need(state.member, 'member page');
  const docs = need(state.docs, 'documents');
  const conversationId = need(state.conversationId, 'conversation id');
  const docxId = need(state.documentIds.docx, 'DOCX id');
  await page.goto(`/workspace/documents/${docxId}`);
  await page.getByRole('dialog', { name: docs.docx.title }).getByRole('button', { name: 'Șterge' }).click();
  await page.getByRole('alertdialog', { name: 'Ștergi documentul?' }).getByRole('button', { name: 'Șterge' }).click();
  await expect(toast(page, 'Documentul a fost șters.')).toBeVisible();
  guardFor(page).expectHttp(new RegExp(`/api/workspace/documents/${docxId}$`), 404);
  expect((await pageGet(page, `/api/workspace/documents/${docxId}`)).status).toBe(404);

  // Judged when read: the stored answer still quotes the DOCX, but may no longer link to it.
  const detail = await pageGet<{ messages: ApiMessage[] }>(page, `/api/workspace/conversations/${conversationId}`);
  const first = detail.body.messages.filter((m) => m.role === 'assistant')[0];
  expect(first?.citations.map((c) => [c.document_id, c.can_open])).toEqual([[docxId, false]]);

  await page.goto(`/workspace/assistant/${conversationId}`);
  await page.locator('.ws-msg--assistant').first().getByRole('button', { name: `Sursa 1: ${docs.docx.title}` }).click();
  const source = page.getByRole('dialog', { name: 'Sursa [1]' });
  await expect(source.locator('blockquote')).toContainText(docs.docx.fact);
  await expect(source.getByText(/Documentul sursă nu îți mai este accesibil: a fost șters sau mutat între timp/)).toBeVisible();
  await expect(source.getByRole('link', { name: 'Deschide documentul' })).toHaveCount(0);
  await expect(source.getByRole('link', { name: 'Descarcă originalul' })).toHaveCount(0);
  await checkPage(page, 'source-drawer-deleted');
});

test('a rejected email request reaches its requester with the approver\'s note, and nothing is sent', async () => {
  const member = need(state.member, 'member page');
  const approver = need(state.approver, 'approver page');
  const subject = 'Comision agenți — de verificat';
  await member.goto(`/workspace/assistant/${need(state.conversationId, 'conversation id')}`);
  await member.locator('.ws-msg--assistant').last().getByRole('button', { name: 'Trimite pe email' }).click();
  let dialog = member.getByRole('dialog', { name: 'Trimite pe email' });
  await dialog.getByLabel('Destinatari').fill('auditor@acme.ro');
  await dialog.getByLabel('Subiect').fill(subject);

  // The session ends under the member before the request is sent (an admin disables the account,
  // then enables it again): signed in again, the reopened dialog has what was typed (F3).
  const admin = need(state.admin, 'admin page');
  const toggleMember = async (menuItem: 'Dezactivează' | 'Activează', title: string, done: string) => {
    await admin.goto('/workspace/admin/users');
    await admin.getByRole('button', { name: `Acțiuni pentru ${SALES_MEMBER.name}` }).click();
    await admin.getByRole('menuitem', { name: menuItem }).click();
    await admin.getByRole('alertdialog', { name: title }).getByRole('button', { name: menuItem }).click();
    await expect(toast(admin, `${done}: ${SALES_MEMBER.name}.`)).toBeVisible();
  };
  await toggleMember('Dezactivează', 'Dezactivezi contul?', 'Cont dezactivat');
  guardFor(member).allowHttp(/\/api\/workspace\//, 401);
  await dialog.getByRole('button', { name: 'Cere aprobarea' }).click();
  await expect(member.getByRole('heading', { name: 'Conectează-te' })).toBeVisible();
  await toggleMember('Activează', 'Activezi contul?', 'Cont activat');
  await member.getByLabel('Email', { exact: true }).fill(SALES_MEMBER.email);
  await member.getByLabel('Parolă', { exact: true }).fill(NEW_MEMBER_PASSWORD);
  await member.getByRole('button', { name: 'Conectează-te' }).click();
  await expect(userMenu(member, SALES_MEMBER.name)).toBeVisible();
  await member.locator('.ws-msg--assistant').last().getByRole('button', { name: 'Trimite pe email' }).click();
  dialog = member.getByRole('dialog', { name: 'Trimite pe email' });
  await expect(dialog.getByText(/Am păstrat ce scriseseși și nu trimiseseși/)).toBeVisible();
  await expect(dialog.getByLabel('Destinatari')).toHaveValue('auditor@acme.ro');
  await expect(dialog.getByLabel('Subiect')).toHaveValue(subject);
  // The message can be previewed as the recipient will read it.
  await dialog.getByRole('button', { name: 'Previzualizare' }).click();
  await expect(dialog.getByRole('region', { name: 'Așa vede destinatarul mesajul' })).toBeVisible();
  await dialog.getByRole('button', { name: 'Previzualizare' }).click();
  await dialog.getByRole('button', { name: 'Cere aprobarea' }).click();
  const done = member.getByRole('dialog', { name: 'Cererea a fost trimisă' });
  await done.getByRole('link', { name: 'Vezi cererea' }).click();
  const approvalId = Number(/\/approvals\/(\d+)$/.exec(member.url())?.[1]);

  await approver.goto(`/workspace/approvals/${approvalId}`);
  const drawer = approver.getByRole('dialog', { name: `Cererea #${approvalId}` });
  await drawer.getByRole('button', { name: 'Respinge' }).click();
  const confirm = approver.getByRole('alertdialog', { name: 'Respingi cererea?' });
  await confirm.getByLabel(/^Notă pentru solicitant/).fill('Cifrele nu sunt încă finale; revino după închiderea lunii.');
  await confirm.getByRole('button', { name: 'Respinge' }).click();
  await expect(toast(approver, 'Cererea a fost respinsă.')).toBeVisible();
  await expect(drawer.getByText('Cererea a fost respinsă.')).toBeVisible();

  await member.reload();
  const mine = member.getByRole('dialog', { name: `Cererea #${approvalId}` });
  await expect(mine.getByText('Respinsă', { exact: true })).toBeVisible();
  await expect(mine.getByText('Cifrele nu sunt încă finale; revino după închiderea lunii.')).toBeVisible();
  await expect(mine.getByText(SALES_APPROVER.name, { exact: true })).toBeVisible();
  // A rejected request says what approving would have done, the recipient aligned with the subject (UX-20).
  await expect(mine.getByRole('heading', { name: 'Ce s-ar fi întâmplat la aprobare' })).toBeVisible();
  const head = mine.locator('.ws-email-preview__head');
  const [toBox, subjectBox] = await Promise.all([head.getByText('auditor@acme.ro', { exact: true }).boundingBox(), head.getByText(subject, { exact: true }).boundingBox()]);
  expect(toBox && subjectBox && Math.abs(toBox.x - subjectBox.x) < 1, 'the recipient starts where the subject starts').toBe(true);
  const stored = await pageGet<{ status: string; decision_note: string; decider: { name: string } }>(member, `/api/workspace/approvals/${approvalId}`);
  expect(stored.body).toMatchObject({ status: 'rejected', decision_note: 'Cifrele nu sunt încă finale; revino după închiderea lunii.', decider: { name: SALES_APPROVER.name } });
  expect(readMail().some((m) => m.subject === subject), 'a rejected request sends nothing').toBe(false);
  await checkPage(member, 'approval-rejected');
});

/** The mail failure in words (error.smtp_failed); never the code or the socket error behind it. */
const SMTP_DOWN_REASON = 'Serverul de email a refuzat mesajul sau nu a putut fi contactat.';
const RAW_MAIL_ERROR = /smtp_failed|connection_failed|delivery_failed|Connection ?Refused|Errno|Traceback/;

test('with the mail server down, an approved email fails honestly: the approver and the requester read why in Romanian, and nothing is sent', async () => {
  const member = need(state.member, 'member page');
  const approver = need(state.approver, 'approver page');
  const runId = need(state.runId, 'run id');
  const subject = 'Situația vânzărilor — pentru conducere';
  const recipient = 'conducere@acme.ro';
  // The member asks while mail works, from the report run.
  await member.goto(`/workspace/report-runs/${runId}`);
  await member.getByRole('button', { name: 'Trimite pe email' }).click();
  const dialog = member.getByRole('dialog', { name: 'Trimite pe email' });
  await dialog.getByLabel('Destinatari').fill(recipient);
  await dialog.getByLabel('Subiect').fill(subject);
  await dialog.getByRole('button', { name: 'Cere aprobarea' }).click();
  await member.getByRole('dialog', { name: 'Cererea a fost trimisă' }).getByRole('link', { name: 'Vezi cererea' }).click();
  await expect(member).toHaveURL(/\/workspace\/approvals\/\d+$/);
  const approvalId = Number(/\/approvals\/(\d+)$/.exec(member.url())?.[1]);

  // Then the mail server goes away for real (its port refuses connections; the settings stay as
  // the admin saved them), and the approver approves.
  await setSmtpSink('down');
  try {
    await approver.goto(`/workspace/approvals/${approvalId}`);
    const drawer = approver.getByRole('dialog', { name: `Cererea #${approvalId}` });
    await expect(drawer).toContainText(recipient);
    await drawer.getByRole('button', { name: 'Aprobă' }).click();
    await approver.getByRole('alertdialog', { name: 'Aprobi cererea?' }).getByRole('button', { name: 'Aprobă' }).click();
    await expect(toast(approver, `Cererea a fost aprobată, dar execuția nu a reușit: ${SMTP_DOWN_REASON}`, 'alert')).toBeVisible();
    await expect(drawer.getByText('Eșuată', { exact: true })).toBeVisible();
    await expect(drawer.locator('.ws-notice').filter({ hasText: 'Aprobată, dar execuția nu a reușit' })).toContainText(SMTP_DOWN_REASON);
    await expect(drawer.getByRole('heading', { name: 'Acțiunea cerută' })).toBeVisible();
    await expect(approver.getByText(RAW_MAIL_ERROR)).toHaveCount(0);
    await checkPage(approver, 'approval-failed');
    const stored = await pageGet<{ status: string; error_code: string | null; result: unknown; decider: { name: string } }>(approver, `/api/workspace/approvals/${approvalId}`);
    expect(stored.body).toMatchObject({ status: 'failed', error_code: 'smtp_failed', result: null, decider: { name: SALES_APPROVER.name } });

    // The requester is told by the bell, and their drawer says the same, in the same words.
    await member.goto('/workspace/assistant');
    await member.getByRole('button', { name: /^Notificări — \d+ necitit/ }).click();
    await member.getByRole('dialog', { name: 'Notificări' }).getByRole('button', { name: /Cerere aprobată, dar neexecutată/ }).first().click();
    await expect(member).toHaveURL(new RegExp(`/workspace/approvals/${approvalId}$`));
    const mine = member.getByRole('dialog', { name: `Cererea #${approvalId}` });
    await expect(mine.getByText('Eșuată', { exact: true })).toBeVisible();
    await expect(mine.locator('.ws-notice').filter({ hasText: 'Aprobată, dar execuția nu a reușit' })).toContainText(SMTP_DOWN_REASON);
    await expect(member.getByText(RAW_MAIL_ERROR)).toHaveCount(0);
  } finally {
    await setSmtpSink('up');
  }
  // Mail is back; the failed request is not sent behind anyone's back.
  expect(readMail().some((m) => m.subject === subject), 'a failed request sends nothing').toBe(false);
});

/** The report's approved delivery address, from the step that approves it on. */
const DELIVERY_RECIPIENT = 'directiune@acme.ro';
type RunDelivery = ApiRun & { error_code: string | null; error_reason: string | null; delivered_to: string[]; delivery_state: string | null };

test('an approved report delivery that cannot reach the mail server: the run is ready and says its email was not sent; with mail back, the next run arrives', async () => {
  const member = need(state.member, 'member page');
  const approver = need(state.approver, 'approver page');
  const reportId = need(state.reportId, 'report id');
  const recipient = DELIVERY_RECIPIENT;
  const readRun = async (id: number) => (await pageGet<RunDelivery>(member, `/api/workspace/report-runs/${id}`)).body;

  // Delivery to a recipient needs a department approver's yes (spec §9), given while mail works.
  await member.goto(`/workspace/reports/${reportId}`);
  await member.getByRole('button', { name: `Acțiuni pentru „${REPORT_NAME}”` }).click();
  await member.getByRole('menuitem', { name: 'Editează' }).click();
  const form = member.getByRole('dialog', { name: 'Editează raportul' });
  await form.getByLabel(/^Trimite rezultatul pe email/).fill(recipient);
  await expect(form.getByText('Destinatarii modificați au nevoie de o nouă aprobare înainte de livrare.')).toBeVisible();
  await form.getByRole('button', { name: 'Salvează' }).click();
  await expect(toast(member, 'Raportul a fost salvat.')).toBeVisible();
  await expect(member.getByText(/^Livrarea așteaptă aprobarea unui aprobator din departament/)).toBeVisible();
  const pending = await pageGet<{ delivery_status: string; delivery_approval_id: number }>(member, `/api/workspace/reports/${reportId}`);
  expect(pending.body.delivery_status).toBe('pending');
  const deliveryApproval = pending.body.delivery_approval_id;
  await approver.goto(`/workspace/approvals/${deliveryApproval}`);
  const drawer = approver.getByRole('dialog', { name: `Cererea #${deliveryApproval}` });
  await expect(drawer).toContainText(recipient);
  await drawer.getByRole('button', { name: 'Aprobă' }).click();
  await approver.getByRole('alertdialog', { name: 'Aprobi cererea?' }).getByRole('button', { name: 'Aprobă' }).click();
  await expect(toast(approver, 'Cererea a fost aprobată și executată.')).toBeVisible();
  const approved = await pageGet<{ delivery_status: string; delivery_approved: string[] }>(member, `/api/workspace/reports/${reportId}`);
  expect(approved.body).toMatchObject({ delivery_status: 'approved', delivery_approved: [recipient] });

  // The mail server is down when the report runs: the report is made, its email is not.
  await setSmtpSink('down');
  try {
    await member.reload();
    await member.getByRole('button', { name: 'Rulează acum' }).click();
    await expect(member).toHaveURL(/\/workspace\/report-runs\/\d+$/);
    const failedRun = Number(/\/report-runs\/(\d+)$/.exec(member.url())?.[1]);
    // The email goes out after the run is stored, so its outcome is read once the server has it.
    await expect.poll(async () => (await readRun(failedRun)).error, { message: 'the delivery failure is recorded', timeout: 60_000 }).toBe('delivery_failed');
    expect(await readRun(failedRun)).toMatchObject({ status: 'succeeded', error_code: 'smtp_failed', error_reason: 'connection_failed', delivery_state: 'failed', delivered_to: [] });
    // The live page, never reloaded, already says so: it kept polling while the email was on its
    // way, instead of stopping at "ready" (NWS-20).
    await expect(member.locator('.ws-notice').filter({ hasText: 'Raportul este gata, dar emailul nu a fost trimis' })).toContainText(SMTP_DOWN_REASON);
    await member.reload();
    await expect(member.locator('.ws-run-meta').getByText('Gata', { exact: true })).toBeVisible();
    await expect(member.locator('article.ws-report').getByRole('heading', { name: 'Surse' })).toBeVisible();
    const notice = member.locator('.ws-notice').filter({ hasText: 'Raportul este gata, dar emailul nu a fost trimis' });
    await expect(notice).toContainText(SMTP_DOWN_REASON);
    await expect(notice).toContainText('Destinatarii nu au primit această rulare.');
    await expect(member.getByText(RAW_MAIL_ERROR)).toHaveCount(0);
    await checkPage(member, 'run-view-delivery-failed');
  } finally {
    await setSmtpSink('up');
  }
  // The report's history flags that run.
  await member.getByRole('link', { name: 'Înapoi la raport' }).click();
  const history = member.getByRole('table', { name: 'Istoricul rulărilor' });
  await expect(history.getByRole('row').filter({ hasText: 'Email netrimis' })).toHaveCount(1);

  // Mail is back: the next run reaches the recipient, and its page says to whom it went.
  await member.getByRole('button', { name: 'Rulează acum' }).click();
  await expect(member).toHaveURL(/\/workspace\/report-runs\/\d+$/);
  const deliveredRun = Number(/\/report-runs\/(\d+)$/.exec(member.url())?.[1]);
  const mail = await waitForMail((m) => m.rcpt_tos.includes(recipient), 'the delivered report');
  expect(mail.subject.startsWith(`${REPORT_NAME} — `), mail.subject).toBe(true);
  expect(mail.text).toContain(`# Raport: ${REPORT_NAME}`);
  await expect.poll(async () => (await readRun(deliveredRun)).delivered_to, { message: 'the delivery is recorded' }).toEqual([recipient]);
  expect(await readRun(deliveredRun)).toMatchObject({ status: 'succeeded', error: null, error_code: null, delivery_state: 'sent' });
  // Shown live first (NWS-20), then again after a reload.
  await expect(member.locator('.ws-run-meta').getByText(recipient, { exact: true })).toBeVisible();
  await member.reload();
  const meta = member.locator('.ws-run-meta');
  await expect(meta.getByText('Trimis pe email către', { exact: true })).toBeVisible();
  await expect(meta.getByText(recipient, { exact: true })).toBeVisible();
  await expect(member.locator('.ws-notice').filter({ hasText: 'emailul nu a fost trimis' })).toHaveCount(0);
});

/** The run page's own status region, holding *text* (it is always on the page; each change is said once). */
function runStatus(page: Page, text: string) {
  return page.locator('p.ws-sr-only[role="status"]').filter({ hasText: text });
}

test('while a run\'s email is still on its way the live page says so, then shows to whom it went — with no reload (NWS-20)', async () => {
  const member = need(state.member, 'member page');
  const reportId = need(state.reportId, 'report id');
  const recipient = DELIVERY_RECIPIENT;
  const readRun = async (id: number) => (await pageGet<RunDelivery>(member, `/api/workspace/report-runs/${id}`)).body;
  const mailsBefore = readMail().filter((m) => m.rcpt_tos.includes(recipient)).length;
  await member.goto(`/workspace/reports/${reportId}`);

  // A slow mail relay: every greeting waits until the journey lets it go (the hub stores the run
  // "ready" first and only then talks to the mail server; each SMTP step may take up to 15 s).
  const connections = await holdSmtpGreeting(true);
  let runId = 0;
  try {
    await member.getByRole('button', { name: 'Rulează acum' }).click();
    await expect(member).toHaveURL(/\/workspace\/report-runs\/\d+$/);
    runId = Number(/\/report-runs\/(\d+)$/.exec(member.url())?.[1]);
    // Wiped out by any reload: proves the outcome below arrives on this very page.
    await member.evaluate(() => { (window as unknown as { __sameDocument?: boolean }).__sameDocument = true; });
    await waitForSmtpConnection(connections);
    // The hub is waiting for the mail server: the run is stored ready, its email still pending.
    expect(await readRun(runId)).toMatchObject({ status: 'succeeded', delivery_state: 'pending', delivered_to: [], error: null });
    await expect(member.locator('.ws-notice').filter({ hasText: 'Raportul se trimite pe email…' })).toBeVisible();
    await expect(member.locator('.ws-run-meta').getByText('Gata', { exact: true })).toBeVisible();
    await expect(member.locator('article.ws-report').getByRole('heading', { name: 'Surse' })).toBeVisible();
    await expect(runStatus(member, 'Raportul este gata și se trimite pe email…')).toHaveCount(1);
    await expect(member.locator('.ws-run-meta').getByText('Trimis pe email către', { exact: true })).toHaveCount(0);
  } finally {
    await holdSmtpGreeting(false);
  }

  // The mail server answers: the same page shows to whom the report went, and says it once.
  const meta = member.locator('.ws-run-meta');
  await expect(meta.getByText('Trimis pe email către', { exact: true })).toBeVisible();
  await expect(meta.getByText(recipient, { exact: true })).toBeVisible();
  await expect(member.locator('.ws-notice').filter({ hasText: 'Raportul se trimite pe email…' })).toHaveCount(0);
  await expect(runStatus(member, `Raportul a fost trimis pe email către ${recipient}.`)).toHaveCount(1);
  expect(await member.evaluate(() => (window as unknown as { __sameDocument?: boolean }).__sameDocument), 'the page was never reloaded').toBe(true);
  expect(await readRun(runId)).toMatchObject({ status: 'succeeded', delivery_state: 'sent', delivered_to: [recipient], error: null, error_code: null });
  await expect.poll(() => readMail().filter((m) => m.rcpt_tos.includes(recipient)).length, { message: 'the report reached the sink' }).toBe(mailsBefore + 1);
});

test('the run history fits a 1024 px screen without sideways scrolling, and no locality chip wraps (UX-22)', async () => {
  const member = need(state.member, 'member page');
  const reportId = need(state.reportId, 'report id');
  await member.goto(`/workspace/reports/${reportId}`);
  const history = member.getByRole('table', { name: 'Istoricul rulărilor' });
  // Every kind of row by now: shared with the company, an email not sent, emails sent.
  await expect(history.getByRole('row').filter({ hasText: 'Partajat în companie' })).toHaveCount(1);
  await expect(history.getByRole('row').filter({ hasText: 'Email netrimis' })).toHaveCount(1);
  for (const viewport of [{ width: 1024, height: 768 }, { width: 1100, height: 800 }, { width: 800, height: 900 }, DESKTOP]) {
    await member.setViewportSize(viewport);
    expect(await tableScrollsSideways(member, 'Istoricul rulărilor'), `the run history scrolls sideways at ${viewport.width} px`).toBe(0);
  }
  await member.setViewportSize({ width: 1024, height: 768 });
  await member.evaluate(() => window.scrollTo(0, 0));
  await member.screenshot({ path: path.join(screenDir(), 'report-detail-history-1024x768.png'), fullPage: true });
  await member.setViewportSize(DESKTOP);
  // The axe scan and the layout faults (chips that wrap included) at every size, 1024 among them.
  await checkPage(member, 'report-detail-history');
  // The run page's side card: the words „Pe serverul companiei" on one line beside nothing.
  await history.getByRole('link').first().click();
  await expect(member.locator('.ws-run-meta')).toContainText('Pe serverul companiei');
  for (const viewport of [{ width: 1100, height: 800 }, { width: 1180, height: 800 }]) {
    await member.setViewportSize(viewport);
    const lines = await member.locator('.ws-run-meta .ws-locality').evaluate((chip) => Math.round(chip.getBoundingClientRect().height));
    expect(lines, `the locality chip is one line at ${viewport.width} px`).toBeLessThanOrEqual(22);
    // …and the source pills under it stay inside their card (a long title ends in an ellipsis).
    const outside = await member.locator('.ws-sources .ws-source').evaluateAll((pills) => pills
      .filter((pill) => pill.getBoundingClientRect().right > (pill.closest('.ws-card')?.getBoundingClientRect().right ?? Infinity) + 1)
      .map((pill) => (pill.textContent || '').trim()));
    expect(outside, `source pills outside their card at ${viewport.width} px`).toEqual([]);
  }
  await member.setViewportSize(DESKTOP);
});

test('the model\'s failures are honest: an error and an empty answer are explained, stored as errors, and Retry keeps the keyboard in place', async () => {
  const page = need(state.member, 'member page');
  for (const [marker, reason] of [['nerva-fake-error', 'Serverul modelului a întors o eroare.'], ['nerva-fake-empty', 'Modelul a trimis un răspuns gol.']] as const) {
    await page.goto('/workspace/assistant');
    await page.getByLabel('Întrebarea ta').fill(`Ce prevede regulamentul comisioanelor? ${marker}`);
    await page.getByRole('button', { name: 'Trimite', exact: true }).click();
    const failed = page.locator('.ws-msg--assistant').last();
    await expect(failed.getByText('Răspunsul nu a putut fi generat')).toBeVisible({ timeout: 30_000 });
    await expect(failed.getByText(`Modelul AI nu este disponibil acum. ${reason}`)).toBeVisible();
    await expect(failed.getByText(/simulated|model_error|empty_answer/)).toHaveCount(0);
    await expect(page).toHaveURL(/\/workspace\/assistant\/\d+$/);
    const id = Number(/\/assistant\/(\d+)$/.exec(page.url())?.[1]);
    const detail = await pageGet<{ messages: (ApiMessage & { error_code: string | null })[] }>(page, `/api/workspace/conversations/${id}`);
    expect(detail.body.messages.map((m) => [m.role, m.status, m.error_code])).toEqual([['user', 'complete', null], ['assistant', 'error', 'model_unavailable']]);
    // The server answered (with an error, or with nothing): the model is still reachable.
    await expect(page.getByRole('button', { name: 'Modelul AI: Local' })).toBeVisible();
    // Retry from the keyboard: its button goes away with the failed answer, focus does not drop.
    await failed.getByRole('button', { name: 'Întreabă din nou' }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByLabel('Întrebarea ta')).toBeFocused();
    await expect(page.locator('.ws-msg--assistant').last().getByText('Răspunsul nu a putut fi generat')).toBeVisible({ timeout: 30_000 });
    if (marker === 'nerva-fake-empty') await checkPage(page, 'assistant-failed-answer');
  }
});

/** A stopped model server in the chat's words (error.model_unavailable + model.reason.model_unreachable),
    and the chat's next step for it (chat.hint.model_unavailable): a report run says the same. */
const MODEL_DOWN = 'Modelul AI nu este disponibil acum. Serverul modelului nu poate fi contactat (este oprit sau conexiunea s-a întrerupt).';
const MODEL_DOWN_HINT = 'Încearcă din nou peste câteva minute. Dacă problema continuă, anunță un administrator.';
const RAW_MODEL_ERROR = /model_unreachable|model_unavailable|ConnectError|Connection ?refused|Errno|Traceback/i;

test('with the model server stopped, the chat and a report run say why in Romanian and the chip reads "Indisponibil"; started again, the next question answers and the chip recovers (T-GAP-2)', async () => {
  const page = need(state.member, 'member page');
  const reportId = need(state.reportId, 'report id');
  const question = 'Cât este comisionul agenților de vânzări?';
  await page.goto('/workspace/assistant');
  await expect(page.getByRole('button', { name: 'Modelul AI: Local' })).toBeVisible();

  await setModelServer('down');
  try {
    // The chat: the reason in words, the next step, the chip and the notice above the composer.
    await page.getByLabel('Întrebarea ta').fill(question);
    await page.getByRole('button', { name: 'Trimite', exact: true }).click();
    const failed = page.locator('.ws-msg--assistant').last();
    await expect(failed.getByText('Răspunsul nu a putut fi generat')).toBeVisible({ timeout: 30_000 });
    await expect(failed.getByText(MODEL_DOWN)).toBeVisible();
    await expect(failed.getByText(MODEL_DOWN_HINT)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Modelul AI: Indisponibil' })).toBeVisible();
    await expect(page.locator('.ws-chat__foot .ws-notice')).toContainText('Serverul modelului nu poate fi contactat');
    await expect(page.getByText(RAW_MODEL_ERROR)).toHaveCount(0);
    await expect(page).toHaveURL(/\/workspace\/assistant\/\d+$/);
    const conversationId = Number(/\/assistant\/(\d+)$/.exec(page.url())?.[1]);
    const detail = await pageGet<{ messages: (ApiMessage & { error_code: string | null })[] }>(page, `/api/workspace/conversations/${conversationId}`);
    expect(detail.body.messages.map((m) => [m.role, m.status, m.error_code])).toEqual([['user', 'complete', null], ['assistant', 'error', 'model_unavailable']]);
    await checkPage(page, 'assistant-model-down');

    // A report run: it fails with the same reason and the same next step, live on its page.
    await page.goto(`/workspace/reports/${reportId}`);
    await page.getByRole('button', { name: 'Rulează acum' }).click();
    await expect(page).toHaveURL(/\/workspace\/report-runs\/\d+$/);
    const runId = Number(/\/report-runs\/(\d+)$/.exec(page.url())?.[1]);
    const notice = page.locator('.ws-notice').filter({ hasText: 'Raportul nu a putut fi generat' });
    await expect(notice).toContainText(MODEL_DOWN, { timeout: 60_000 });
    await expect(notice).toContainText(MODEL_DOWN_HINT);
    await expect(notice.getByRole('button', { name: 'Rulează din nou' })).toBeVisible();
    await expect(page.locator('.ws-run-meta').getByText('Eșuat', { exact: true })).toBeVisible();
    await expect(page.locator('p.ws-sr-only[role="status"]')).toContainText('Raportul nu a putut fi generat');
    await expect(page.getByRole('button', { name: 'Modelul AI: Indisponibil' })).toBeVisible();
    await expect(page.getByText(RAW_MODEL_ERROR)).toHaveCount(0);
    const run = await pageGet<RunDelivery>(page, `/api/workspace/report-runs/${runId}`);
    expect(run.body).toMatchObject({ status: 'failed', error_code: 'model_unavailable', error_reason: 'model_unreachable', content_md: null, delivery_state: null });
    await checkPage(page, 'run-view-model-down');
  } finally {
    await setModelServer('up');
  }

  // Started again: the next question answers, and the chip and the composer's notice recover
  // with that answer (the server marked the model up again), without a reload.
  await page.goto('/workspace/assistant');
  await page.evaluate(() => { (window as unknown as { __sameDocument?: boolean }).__sameDocument = true; });
  await page.getByLabel('Întrebarea ta').fill(question);
  await page.getByRole('button', { name: 'Trimite', exact: true }).click();
  await expect(page.locator('.ws-msg--assistant').last()).toContainText('Comisionul agenților de vânzări este de 3%', { timeout: 30_000 });
  await expect(page.getByRole('button', { name: 'Modelul AI: Local' })).toBeVisible();
  await expect(page.locator('.ws-chat__foot .ws-notice')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __sameDocument?: boolean }).__sameDocument), 'the page was never reloaded').toBe(true);
  const posture = await pageGet<{ available: boolean }>(page, '/api/workspace/model');
  expect(posture.body.available, 'the server reports the model available again').toBe(true);
});

test('an archived department takes no uploads, and the toggle that shows it appears only then', async () => {
  const admin = need(state.admin, 'admin page');
  await admin.goto('/workspace/admin/departments');
  await expect(admin.getByRole('switch', { name: /Arată și arhivate/ })).toHaveCount(0);
  await admin.getByRole('button', { name: 'Departament nou' }).first().click();
  const drawer = admin.getByRole('dialog', { name: 'Departament nou' });
  await drawer.getByLabel('Nume', { exact: true }).fill('Proiecte închise');
  await drawer.getByRole('button', { name: 'Creează departamentul' }).click();
  await expect(toast(admin, 'Departamentul „Proiecte închise” a fost creat.')).toBeVisible();
  await admin.getByRole('button', { name: 'Acțiuni pentru Proiecte închise' }).click();
  await admin.getByRole('menuitem', { name: 'Arhivează' }).click();
  await admin.getByRole('alertdialog', { name: 'Arhivezi departamentul?' }).getByRole('button', { name: 'Arhivează' }).click();
  await expect(toast(admin, 'Departamentul „Proiecte închise” a fost arhivat.')).toBeVisible();
  await expect(admin.getByRole('switch', { name: 'Arată și arhivate (1)' })).toBeVisible();
  const listed = await pageGet<{ departments: { id: number; name: string; archived: boolean }[] }>(admin, '/api/workspace/admin/departments');
  const archived = listed.body.departments.find((d) => d.name === 'Proiecte închise');
  expect(archived?.archived).toBe(true);

  guardFor(admin).expectHttp(/\/api\/workspace\/documents\?/, 409);
  const upload = await admin.evaluate(async (departmentId) => {
    const session = await (await fetch('/api/workspace/session', { cache: 'no-store' })).json() as { csrf_token: string };
    const response = await fetch(`/api/workspace/documents?department_id=${departmentId}&filename=nota.txt`, {
      method: 'POST', headers: { 'Content-Type': 'text/plain', 'X-CSRF-Token': session.csrf_token }, body: 'O notă.',
    });
    return { status: response.status, body: await response.json() as { error: string } };
  }, archived?.id);
  expect(upload).toMatchObject({ status: 409, body: { error: 'department_archived' } });
  // And the sidebar never offers it as a place to work in.
  await expect(admin.getByLabel('Departament', { exact: true }).locator('option', { hasText: 'Proiecte închise' })).toHaveCount(0);
});

test('keyboard focus stays visible in forced colours and never hides under the sticky top bar', async () => {
  const admin = need(state.admin, 'admin page');
  await admin.emulateMedia({ forcedColors: 'active' });
  try {
    await admin.goto('/workspace/admin/email');
    expect(await focusRing(admin, 'main input.ws-input')).toMatchObject({ style: 'solid' });
    expect((await focusRing(admin, 'main input.ws-input')).width).toBeGreaterThanOrEqual(2);
    await admin.goto('/workspace/assistant');
    expect(await focusRing(admin, '.ws-composer__input')).toMatchObject({ style: 'solid' });
    await admin.goto('/workspace/admin/users');
    await admin.getByRole('button', { name: `Acțiuni pentru ${SALES_APPROVER.name}` }).click();
    await admin.keyboard.press('ArrowDown');
    const item = await admin.evaluate(() => {
      const style = getComputedStyle(document.activeElement as Element);
      return { role: (document.activeElement as Element).getAttribute('role'), style: style.outlineStyle, width: parseFloat(style.outlineWidth) };
    });
    expect(item.role).toBe('menuitem');
    expect(item.style).toBe('solid');
    expect(item.width).toBeGreaterThanOrEqual(2);
    await admin.keyboard.press('Escape');
  } finally {
    await admin.emulateMedia({ forcedColors: 'none' });
  }
  for (const [url, size] of [['/workspace/admin/audit', { width: 1280, height: 600 }], ['/workspace/admin/email', { width: 1280, height: 600 }], [`/workspace/report-runs/${need(state.runId, 'run id')}`, { width: 390, height: 700 }]] as const) {
    await admin.setViewportSize(size);
    await admin.goto(url);
    await admin.waitForLoadState('networkidle');
    expect(await controlsUnderTopBar(admin), `focus hidden under the top bar on ${url}`).toEqual([]);
  }
  await admin.setViewportSize({ width: 1280, height: 800 });
});

test('the company data lives in its own directory, never in the owner\'s file-tool root', async () => {
  // Spec §3: <data>/business. <data>/workspace is the hub's default root of the owner's file
  // tools, local terminal and tool-result spills, so nothing of the company's may land there.
  const home = path.join(RUN_DIR, 'home');
  const business = path.join(home, 'business');
  expect(existsSync(path.join(business, 'workspace.db')), 'the database is in business/').toBe(true);
  expect(readdirSync(path.join(business, 'files')).filter((name) => name.endsWith('.bin')).length).toBeGreaterThan(0);
  const shared = path.join(home, 'workspace');
  const company = existsSync(shared)
    ? readdirSync(shared, { recursive: true }).map(String).filter((name) => /workspace\.db|\.bin$|secrets\.enc|setup-code/.test(name))
    : [];
  expect(company, 'company files in the owner\'s workspace/ directory').toEqual([]);
});

test('the hub log holds no traceback or error from the whole journey', async () => {
  const log = hubLog();
  expect(log.length, 'the hub log was captured').toBeGreaterThan(0);
  const lines = log.split('\n');
  // The one failure the journey causes on purpose: the fake model answering 500 to the
  // "nerva-fake-error" question (and its retry). The hub logs that provider failure; it must
  // have happened, and it is the only error allowed.
  const SIMULATED = /LM Studio request failed .*simulated model failure/;
  expect(lines.filter((line) => SIMULATED.test(line)).length, 'the simulated model failure was logged').toBeGreaterThan(0);
  // The stopped model server (T-GAP-2) was noticed by the hub — as a warning, not an error.
  expect(lines.filter((line) => /\bWARNING\b.*LM Studio unreachable/.test(line)).length, 'the stopped model server was noticed').toBeGreaterThan(0);
  const bad = lines.filter((line) => /Traceback \(most recent call last\)|\bERROR\b|\bCRITICAL\b/.test(line) && !SIMULATED.test(line));
  expect(bad, `the hub logged:\n${bad.join('\n')}`).toEqual([]);
});
