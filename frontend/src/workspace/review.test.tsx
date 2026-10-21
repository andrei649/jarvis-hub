/* Review fixes outside the bigger screens (frontend fixer, QA round 2):
   - forms: a failed submit focuses the first invalid field (A11Y-04); an empty password says
     "choose a password" and an empty confirmation is asked for (UX-18 c);
   - the invalid-invite page is not a dead end (UX-18 d);
   - the password toggle keeps one label with aria-pressed (A11Y-19);
   - language names carry their own lang (A11Y-14);
   - members see where the model runs in words, not the engine and route ids (UX-13);
   - tables stack as labelled cards on phones and keep their table semantics (UX-03);
   - dialogs and drawers are not banner/contentinfo landmarks (A11Y-17);
   - withdrawn approvals say why, and "reject" is not a solid red twin of "approve" (F4, UX-18 e);
   - the company-wide collection shows members a note instead of an upload card, and the
     document preview renders tables (UX-10, UX-06);
   - Romanian copy: no "{count}" before a word outside plural keys, no "hub" jargon (UX-08, UX-15). */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Approval, WorkspaceDocument } from './api/types';
import { RO } from './i18n/messages';
import { I18nProvider } from './i18n';
import { renderApp } from './test/render';
import { makeUser, mockFetch, ORG, shellRoutes, signedIn, SIGNED_OUT, type RouteHandler } from './test/mockApi';
import { Dialog, Drawer, Table, ToastProvider } from './ui';

const NOW = Date.now() / 1000;
const field = (name: RegExp) => screen.getByLabelText(name, { selector: 'input' });

describe('Sign-in, setup and invite forms', () => {
  it('login focuses the first invalid field after a failed submit (A11Y-04)', async () => {
    mockFetch({ 'GET /api/workspace/session': SIGNED_OUT });
    renderApp('/workspace/');
    await screen.findByRole('heading', { name: 'Conectează-te' });
    const submit = screen.getByRole('button', { name: 'Conectează-te' });
    submit.focus();
    fireEvent.click(submit);
    await waitFor(() => expect(document.activeElement).toBe(field(/^Email/)));
  });

  it('setup focuses the first invalid field, asks for a password and its confirmation in words (A11Y-04, UX-18 c)', async () => {
    mockFetch({ 'GET /api/workspace/session': { enabled: true, setup_required: true, sso_available: false, authenticated: false } });
    renderApp('/workspace/');
    await screen.findByRole('heading', { name: 'Configurează Nerva Workspace' });
    const submit = screen.getByRole('button', { name: 'Creează spațiul de lucru' });
    submit.focus();
    fireEvent.click(submit);
    await waitFor(() => expect(document.activeElement).toBe(field(/^Cod de configurare/)));
    expect(screen.getByText('Alege o parolă.')).toBeTruthy();
    expect(screen.getByText('Scrie parola încă o dată, ca să o confirmi.')).toBeTruthy();
    expect(screen.queryByText('Parola trebuie să aibă cel puțin 12 caractere.')).toBeNull();
    expect(screen.getByText(/nerva-run -m agents\.core\.workspace setup-code/)).toBeTruthy();
  });

  it('an invalid invite link offers the way to sign in (UX-18 d)', async () => {
    mockFetch({ 'GET /api/workspace/session': SIGNED_OUT });
    renderApp('/workspace/invite');
    expect(await screen.findByRole('heading', { name: 'Linkul nu mai este valabil' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Mergi la conectare' }).getAttribute('href')).toBe('/workspace/');
  });

  it('the password toggle keeps one label and reports its state with aria-pressed (A11Y-19)', async () => {
    mockFetch({ 'GET /api/workspace/session': SIGNED_OUT });
    renderApp('/workspace/');
    await screen.findByRole('heading', { name: 'Conectează-te' });
    const toggle = screen.getByRole('button', { name: 'Arată parola' });
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(toggle);
    expect(screen.getByRole('button', { name: 'Arată parola' }).getAttribute('aria-pressed')).toBe('true');
  });
});

describe('Shell and profile', () => {
  it('marks language names with their own lang in the account menu and the profile (A11Y-14)', async () => {
    mockFetch({ 'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })), ...shellRoutes(), 'GET /api/workspace/me/sessions': { sessions: [] } });
    renderApp('/workspace/profile');
    fireEvent.click(await screen.findByRole('button', { name: /Contul tău: Ana Pop/ }));
    expect(screen.getByRole('menuitemradio', { name: 'English' }).getAttribute('lang')).toBe('en');
    expect(screen.getByRole('menuitemradio', { name: 'Română' }).getAttribute('lang')).toBe('ro');
    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    const option = screen.getByRole('option', { name: 'English' });
    expect(option.getAttribute('lang')).toBe('en');
  });

  it('the profile password form focuses its first invalid field (A11Y-04)', async () => {
    mockFetch({ 'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })), ...shellRoutes(), 'GET /api/workspace/me/sessions': { sessions: [] } });
    renderApp('/workspace/profile');
    const submit = await screen.findByRole('button', { name: 'Schimbă parola' });
    submit.focus();
    fireEvent.click(submit);
    await waitFor(() => expect(document.activeElement).toBe(field(/^Parola actuală/)));
  });

  it('tells a member where the model runs in words, without engine or route ids (UX-13)', async () => {
    mockFetch({ 'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })), ...shellRoutes() });
    renderApp('/workspace/assistant');
    fireEvent.click(await screen.findByRole('button', { name: 'Modelul AI: Local' }));
    const panel = await screen.findByRole('dialog', { name: 'Modelul AI' });
    expect(within(panel).getByText('Pe serverul companiei')).toBeTruthy();
    expect(within(panel).queryByText('lm-studio')).toBeNull();
    expect(within(panel).queryByText('Motor')).toBeNull();
    expect(within(panel).queryByText('Rută')).toBeNull();
  });
});

describe('UI kit', () => {
  it('tables keep explicit table roles and label every cell for the stacked phone layout (UX-03)', () => {
    render(
      <I18nProvider>
        <Table
          caption="Oameni" rowKey={(r: { id: number; name: string }) => r.id} rows={[{ id: 1, name: 'Ana' }]} empty={null}
          columns={[
            { key: 'name', header: 'Nume', render: (r) => r.name },
            { key: 'role', header: 'Rol', render: () => 'Membru', nowrap: true },
            { key: 'actions', header: '', srHeader: 'Acțiuni', render: () => <button type="button">…</button> },
          ]}
        />
      </I18nProvider>,
    );
    const table = screen.getByRole('table', { name: 'Oameni' });
    expect(table.getAttribute('role')).toBe('table');
    expect(table.classList.contains('ws-table--stack')).toBe(true);
    const cells = within(table).getAllByRole('cell');
    expect(cells.map((c) => c.getAttribute('data-label'))).toEqual([null, 'Rol', null]);
    expect(cells[0].classList.contains('is-primary')).toBe(true);
    expect(cells[1].classList.contains('is-nowrap')).toBe(true);
    expect(cells[2].classList.contains('is-actions')).toBe(true);
    expect(within(table).getAllByRole('columnheader')).toHaveLength(3);
  });

  it('dialogs and drawers add no banner or contentinfo landmark (A11Y-17)', () => {
    render(
      <I18nProvider>
        <ToastProvider>
          <Dialog open onClose={() => undefined} title="Un dialog" footer={<button type="button">OK</button>}>Text</Dialog>
          <Drawer open onClose={() => undefined} title="Un sertar" footer={<button type="button">Gata</button>}>Text</Drawer>
        </ToastProvider>
      </I18nProvider>,
    );
    expect(screen.queryAllByRole('banner')).toHaveLength(0);
    expect(screen.queryAllByRole('contentinfo')).toHaveLength(0);
    expect(document.querySelectorAll('.ws-surface header, .ws-surface footer')).toHaveLength(0);
  });
});

function approval(over: Partial<Approval> = {}): Approval {
  return {
    id: 5, kind: 'report.delivery', department_id: 1, summary: 'Livrarea raportului „Nord”',
    payload: { report_id: 3, emails: ['sef@client.ro'] }, status: 'cancelled', requester: { id: 1, name: 'Ana Pop' },
    decider: null, decided_at: NOW - 60, decision_note: null, result: null, error_code: null, created_at: NOW - 600,
    expires_at: NOW + 86_400, can_decide: false, can_cancel: false, ...over,
  };
}

function bootApprovals(routes: Record<string, RouteHandler>, role: 'approver' | 'member' = 'member') {
  mockFetch({
    'GET /api/workspace/session': signedIn(makeUser({ role })),
    ...shellRoutes(),
    'GET /api/workspace/approvals': { items: [], pending_inbox_count: 0 },
    'GET /api/workspace/reports/3': { id: 3, name: 'Nord' },
    ...routes,
  });
  renderApp('/workspace/approvals/5');
}

describe('Approvals', () => {
  it('a request withdrawn by a change says why; one the requester cancelled says so (F4)', async () => {
    bootApprovals({ 'GET /api/workspace/approvals/5': approval({ error_code: 'superseded' }) });
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    expect(await within(drawer).findByText(/Cererea a fost înlocuită de una nouă după o modificare a raportului/)).toBeTruthy();
    expect(within(drawer).queryByText('Solicitantul a anulat cererea.')).toBeNull();
  });

  it('a report deletion reads as such', async () => {
    bootApprovals({ 'GET /api/workspace/approvals/5': approval({ error_code: 'report_deleted' }) });
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    expect(await within(drawer).findByText('Cererea a fost retrasă: raportul la care se referea a fost șters.')).toBeTruthy();
  });

  it('"reject" is a quiet danger button next to the primary "approve" (UX-18 e)', async () => {
    bootApprovals({ 'GET /api/workspace/approvals/5': approval({ status: 'pending', decided_at: null, can_decide: true, requester: { id: 2, name: 'Ion' } }) }, 'approver');
    const drawer = await screen.findByRole('dialog', { name: 'Cererea #5' });
    const reject = await within(drawer).findByRole('button', { name: 'Respinge' });
    expect(reject.classList.contains('ws-btn--danger')).toBe(false);
    expect(reject.classList.contains('ws-btn--danger-ghost')).toBe(true);
    expect(within(drawer).getByRole('button', { name: 'Aprobă' }).classList.contains('ws-btn--primary')).toBe(true);
  });
});

function doc(over: Partial<WorkspaceDocument>): WorkspaceDocument {
  return {
    id: 5, title: 'Încasări', filename: 'incasari.xlsx', mime: 'application/vnd.ms-excel', size_bytes: 2000, department_id: 1,
    visibility: 'department', status: 'ready', error: null, page_count: null, chunk_count: 1, uploader: null, created_at: NOW,
    can_delete: false, can_reindex: false, can_publish: false, ...over,
  };
}

describe('Documents', () => {
  it('the document preview renders the extracted Markdown, tables included (UX-06)', async () => {
    mockFetch({
      'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })),
      ...shellRoutes(),
      'GET /api/workspace/documents': { documents: [doc({})] },
      'GET /api/workspace/documents/5': { ...doc({}), preview: '## Încasări\n\n| Lună | Încasări (lei) |\n| --- | --- |\n| Iulie | 41250 |' },
    });
    renderApp('/workspace/documents/5');
    const drawer = await screen.findByRole('dialog', { name: 'Încasări' });
    const region = await within(drawer).findByRole('region', { name: 'Previzualizare text' });
    expect(within(region).getByRole('table')).toBeTruthy();
    expect(within(region).getByRole('cell', { name: '41250' })).toBeTruthy();
    expect(within(region).getByRole('heading', { level: 5, name: 'Încasări' })).toBeTruthy();
    expect(within(region).queryByText(/\| --- \|/)).toBeNull();
  });

  it('a member in the company-wide collection gets a note, not an upload card (UX-10)', async () => {
    mockFetch({
      'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })),
      ...shellRoutes(),
      'GET /api/workspace/documents': { documents: [] },
    });
    renderApp('/workspace/documents');
    fireEvent.change(await screen.findByLabelText('Documentele din'), { target: { value: 'company' } });
    expect(await screen.findByText(/Documentele pentru toată compania sunt adăugate de administratori/)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Încarcă documente' })).toBeNull();
  });
});

describe('Romanian copy', () => {
  it('never puts {count} before a word outside a plural key (UX-08)', () => {
    const offenders = Object.entries(RO)
      .filter(([key]) => !/\.(one|few|other)$/.test(key))
      .filter(([, text]) => /\{count\}\s+\p{L}/u.test(text))
      .map(([key]) => key);
    expect(offenders).toEqual([]);
  });

  it('says "serverul Nerva", never "hub", to the people using it (UX-15)', () => {
    const offenders = Object.entries(RO).filter(([, text]) => /\bhub/i.test(text)).map(([key]) => key);
    expect(offenders).toEqual([]);
  });

  it('does not address women as "lui {name}" or with "(ă)" (UX-14)', () => {
    const offenders = Object.entries(RO).filter(([, text]) => /(^|\s)lui \{name\}|\(ă\)/.test(text)).map(([key]) => key);
    expect(offenders).toEqual([]);
  });
});

void ORG;
