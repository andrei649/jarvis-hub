import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '../../test/render';
import { ADMIN_DEPARTMENTS, apiError, makeAdminUser, makeUser, mockFetch, shellRoutes, signedIn } from '../../test/mockApi';

const SMTP_OK = { host: 'smtp.acme.ro', port: 587, security: 'starttls', username: 'nerva', from_address: 'nerva@acme.ro', from_name: 'Nerva', allowed_domains: [], has_password: true };
const SMTP_NONE = { host: '', port: 0, security: 'starttls', username: '', from_address: '', from_name: '', allowed_domains: [], has_password: false };

function setup(over: { smtp?: object; users?: object[] } = {}) {
  const me = makeUser();
  const colleague = makeAdminUser({ id: 2, email: 'ion@acme.ro', name: 'Ion Ionescu', role: 'member', department_ids: [2], last_login_at: 1_700_000_000 });
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(me),
    ...shellRoutes(),
    'GET /api/workspace/admin/users': { users: over.users ?? [makeAdminUser(), colleague] },
    'GET /api/workspace/admin/departments': { departments: ADMIN_DEPARTMENTS },
    'GET /api/workspace/admin/smtp': over.smtp ?? SMTP_OK,
  });
  renderApp('/workspace/admin/users');
  return { mock, colleague };
}

/** The invite button stays disabled until the department list has arrived. */
async function inviteButton() {
  const button = await screen.findByRole('button', { name: 'Invită utilizator' }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  return button;
}

async function openRowMenu(name: string) {
  fireEvent.click(await screen.findByRole('button', { name: `Acțiuni pentru ${name}` }));
  return screen.getByRole('menu', { name: `Acțiuni pentru ${name}` });
}

describe('Admin → Users', () => {
  it('lists users with role, departments and status', async () => {
    setup();
    await screen.findByText('Ion Ionescu');
    const table = screen.getByRole('table', { name: 'Utilizatori' });
    const row = within(table).getByText('Ion Ionescu').closest('tr') as HTMLElement;
    expect(within(row).getByText('Membru')).toBeTruthy();
    expect(within(row).getByText('Juridic')).toBeTruthy();
    expect(within(row).getByText('Activ')).toBeTruthy();
    expect(within(table).getByText('(tu)')).toBeTruthy();
  });

  it('invites a user with role, departments and email delivery, then shows the copyable link', async () => {
    const { mock } = setup();
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    mock.on('POST /api/workspace/admin/users', {
      status: 201,
      body: { user: makeAdminUser({ id: 9, email: 'maria@acme.ro', name: 'Maria', role: 'approver', status: 'invited', department_ids: [2] }), invite_url: 'https://hub/workspace/invite#t=abc', emailed: true },
    });
    fireEvent.click(await inviteButton());
    const dialog = await screen.findByRole('dialog', { name: 'Invită un utilizator' });

    fireEvent.click(within(dialog).getByRole('button', { name: 'Trimite invitația' }));
    expect(await within(dialog).findByText('Alege cel puțin un departament.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/admin/users')).toHaveLength(0);

    fireEvent.change(within(dialog).getByLabelText(/^Email/), { target: { value: 'maria@acme.ro' } });
    fireEvent.change(within(dialog).getByLabelText(/^Nume/), { target: { value: 'Maria' } });
    fireEvent.change(within(dialog).getByLabelText(/^Rol/), { target: { value: 'approver' } });
    fireEvent.click(within(dialog).getByLabelText('Juridic'));
    expect((within(dialog).getByLabelText('Trimite linkul pe email') as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Trimite invitația' }));

    const done = await screen.findByRole('dialog', { name: 'Invitație creată' });
    expect(mock.find('POST', '/api/workspace/admin/users')[0].body).toEqual({
      email: 'maria@acme.ro', name: 'Maria', role: 'approver', department_ids: [2], send_email: true,
    });
    expect(mock.find('POST', '/api/workspace/admin/users')[0].headers['X-CSRF-Token']).toBe('csrf-1');
    expect((within(done).getByLabelText('Link personal') as HTMLInputElement).value).toBe('https://hub/workspace/invite#t=abc');
    expect(within(done).getByText('Linkul a fost trimis pe email la maria@acme.ro.')).toBeTruthy();
    fireEvent.click(within(done).getByRole('button', { name: 'Copiază' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://hub/workspace/invite#t=abc'));
    expect(await screen.findByText('Linkul a fost copiat.')).toBeTruthy();
  });

  it('turns off email delivery when SMTP is not configured and maps a duplicate email to the field', async () => {
    const { mock } = setup({ smtp: SMTP_NONE });
    mock.on('POST /api/workspace/admin/users', apiError(409, 'email_taken', { field: 'email' }));
    expect(await screen.findByText(/Emailul nu este configurat/)).toBeTruthy();
    fireEvent.click(await inviteButton());
    const dialog = await screen.findByRole('dialog', { name: 'Invită un utilizator' });
    const sendEmail = within(dialog).getByLabelText('Trimite linkul pe email') as HTMLInputElement;
    expect(sendEmail.disabled).toBe(true);
    expect(sendEmail.checked).toBe(false);
    fireEvent.change(within(dialog).getByLabelText(/^Email/), { target: { value: 'ion@acme.ro' } });
    fireEvent.change(within(dialog).getByLabelText(/^Nume/), { target: { value: 'Ion' } });
    fireEvent.click(within(dialog).getByLabelText('General'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Creează invitația' }));
    expect(await within(dialog).findByText('Există deja un utilizator cu acest email.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/admin/users')[0].body).toMatchObject({ send_email: false });
  });

  it('disables a user after confirmation and reloads the list', async () => {
    const { mock, colleague } = setup();
    mock.on('PATCH /api/workspace/admin/users/2', { user: { ...colleague, status: 'disabled' } });
    const menu = await openRowMenu('Ion Ionescu');
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Dezactivează' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Dezactivezi contul?' });
    expect(within(confirm).getByText(/Ion Ionescu nu se va mai putea conecta/)).toBeTruthy();
    const listCalls = mock.find('GET', '/api/workspace/admin/users').length;
    fireEvent.click(within(confirm).getByRole('button', { name: 'Dezactivează' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(mock.find('PATCH', '/api/workspace/admin/users/2')[0].body).toEqual({ status: 'disabled' });
    expect(await screen.findByText('Cont dezactivat: Ion Ionescu.')).toBeTruthy();
    expect(mock.find('GET', '/api/workspace/admin/users').length).toBeGreaterThan(listCalls);
  });

  it('keeps the confirm dialog open with the reason when the server refuses (last admin)', async () => {
    const other = makeAdminUser({ id: 3, email: 'boss@acme.ro', name: 'Boss', role: 'admin' });
    const { mock } = setup({ users: [makeAdminUser(), other] });
    mock.on('PATCH /api/workspace/admin/users/3', apiError(409, 'last_admin'));
    const menu = await openRowMenu('Boss');
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Dezactivează' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Dezactivezi contul?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Dezactivează' }));
    expect(await within(confirm).findByText('Spațiul de lucru are nevoie de cel puțin un administrator activ.')).toBeTruthy();
  });

  it('cannot disable your own account from the menu', async () => {
    setup();
    const menu = await openRowMenu('Ana Pop');
    expect((within(menu).getByRole('menuitem', { name: 'Dezactivează' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('issues a reset link for an active user and enables a disabled one', async () => {
    const disabled = makeAdminUser({ id: 4, email: 'dan@acme.ro', name: 'Dan', role: 'member', status: 'disabled' });
    const { mock } = setup({ users: [makeAdminUser(), disabled, makeAdminUser({ id: 5, email: 'eva@acme.ro', name: 'Eva', role: 'member' })] });
    mock.on('POST /api/workspace/admin/users/5/invite', { invite_url: 'https://hub/workspace/invite#t=r', purpose: 'reset', emailed: false, email_error: 'smtp_failed' });
    mock.on('PATCH /api/workspace/admin/users/4', { user: { ...disabled, status: 'active' } });

    let menu = await openRowMenu('Eva');
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Link de resetare a parolei' }));
    const dialog = await screen.findByRole('dialog', { name: 'Link de resetare a parolei' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Generează linkul' }));
    expect(await within(dialog).findByText('Serverul de email a refuzat mesajul sau nu a putut fi contactat.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/admin/users/5/invite')[0].body).toEqual({ send_email: true });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Gata' }));

    menu = await openRowMenu('Dan');
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Activează' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Activezi contul?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Activează' }));
    await waitFor(() => expect(mock.find('PATCH', '/api/workspace/admin/users/4')[0]?.body).toEqual({ status: 'active' }));
  });

  it('is not reachable for a non-admin', async () => {
    mockFetch({ 'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })), ...shellRoutes() });
    renderApp('/workspace/admin/users');
    expect(await screen.findByRole('heading', { level: 1, name: 'Pagina nu există' })).toBeTruthy();
  });
});
