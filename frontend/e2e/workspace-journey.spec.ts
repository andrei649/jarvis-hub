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
  assertNoPageProblems, buildDocuments, checkPage, guard, guardFor, hubLog, pageGet, readMail,
  RUN_DIR, SETUP_CODE, SMTP_PORT, waitForMail, type SampleDoc, type SampleKey,
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
  await dialog.getByRole('button', { name: 'Trimite invitația' }).click();
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
  await expect(page.getByText(`Ai fost invitat(ă) cu adresa ${person.email}.`)).toBeVisible();
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
  citations: { n: number; document_id: number; title: string; excerpt: string }[]; model: string | null; locality: string | null;
}

const QUESTION = 'Care este discountul maxim pentru clienții noi din Țara Bârsei?';

test('the member asks a question the DOCX answers: tokens stream, the answer cites it, the source drawer opens, feedback is saved', async () => {
  const page = need(state.member, 'member page');
  const docs = need(state.docs, 'documents');
  await nav(page, 'Asistent');
  await expect(page.getByText('Cu ce te pot ajuta?')).toBeVisible();
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
  expect(stored?.citations.map((c) => [c.n, c.document_id])).toEqual([[1, state.documentIds.docx]]);

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
  await expect(page.getByText(`Mesajul de test a fost acceptat de server pentru ${ADMIN.email}.`)).toBeVisible();
  const mail = await waitForMail((m) => m.subject === 'Nerva Workspace — test de email', 'the SMTP test message');
  expect(mail.rcpt_tos).toEqual([ADMIN.email]);
  expect(mail.mail_from).toBe('nerva@acme.ro');
  expect(mail.from).toContain('Nerva Acme');
  expect(mail.text).toContain('trimiterea emailurilor funcționează');
  await checkPage(page, 'admin-email');
});

test('"Trimite pe email": the member asks, the approver approves under "De decis", the mail reaches the sink', async () => {
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

  // The approver's inbox ("De decis") lists it; approving executes it.
  await approver.reload();
  await nav(approver, 'Aprobări');
  await expect(approver.getByRole('tab', { name: /De decis/ })).toHaveAttribute('aria-selected', 'true');
  const inbox = approver.getByRole('table', { name: 'De decis' });
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
  const meta = page.locator('.ws-run-meta');
  await expect(meta.getByText('Gata', { exact: true })).toBeVisible({ timeout: 60_000 });
  const article = page.locator('article.ws-report');
  await expect(article.getByRole('heading', { level: 1 })).toContainText('Raport');
  await expect(article.getByRole('heading', { name: 'Surse' })).toBeVisible();
  await expect(article.getByRole('table')).toBeVisible();
  await expect(article.getByRole('button', { name: /^Sursa 1: / }).first()).toBeVisible();

  const run = await pageGet<ApiRun>(page, `/api/workspace/report-runs/${state.runId}`);
  expect(run.body).toMatchObject({ status: 'succeeded', error: null, shared_company: false, report_name: REPORT_NAME, department_name: SALES, locality: 'local' });
  const markdown = run.body.content_md ?? '';
  expect(markdown).toMatch(/^# Raport/m);
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

  await page.getByRole('link', { name: 'Înapoi la raport' }).click();
  await page.getByRole('link', { name: 'Toate rapoartele' }).click();
  const list = page.getByRole('table', { name: 'Rapoarte' });
  await expect(list.getByRole('link', { name: REPORT_NAME })).toBeVisible();
  await expect(list.getByText('Gata', { exact: true })).toBeVisible();
  await expect(list.getByText('Zilnic, la 08:15')).toBeVisible();
  await checkPage(page, 'reports');
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

  // The admin decides it from "De decis".
  await admin.reload();
  await nav(admin, 'Aprobări');
  const inbox = admin.getByRole('table', { name: 'De decis' });
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
  await page.getByRole('button', { name: 'Aplică filtrele' }).click();
  await expect(table.getByRole('row').filter({ hasText: 'Document încărcat' })).toHaveCount(4);
  const rows = table.getByRole('row');
  const count = await rows.count();
  expect(count).toBeGreaterThan(5);
  for (let i = 1; i < count; i += 1) await expect(rows.nth(i)).toContainText(SALES_MEMBER.name);
  await page.getByRole('button', { name: 'Resetează' }).click();

  await page.getByRole('button', { name: 'Verifică lanțul' }).click();
  await expect(page.getByText('Lanțul de audit este intact')).toBeVisible();
  const verify = await pageGet<{ ok: boolean; checked: number }>(page, '/api/workspace/admin/audit/verify');
  expect(verify.body.ok).toBe(true);
  await expect(page.getByText(/Am verificat \d+ intrări; niciuna nu a fost modificată\./)).toBeVisible();

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
  await checkPage(page, 'admin-usage');

  await sections.getByRole('link', { name: 'Organizație' }).click();
  await expect(page).toHaveURL(/\/workspace\/admin\/organisation$/);
  await expect(page.getByLabel('Numele organizației')).toHaveValue(ORG);
  await expect(page.getByRole('radio', { name: /^Doar model local/ })).toBeChecked();
  await page.getByRole('button', { name: 'Testează modelul' }).click();
  await expect(page.getByText(/^Modelul a răspuns în /)).toBeVisible();
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
  const bad = log.split('\n').filter((line) => /Traceback \(most recent call last\)|\bERROR\b|\bCRITICAL\b/.test(line));
  expect(bad, `the hub logged:\n${bad.join('\n')}`).toEqual([]);
});
