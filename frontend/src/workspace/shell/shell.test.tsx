import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../test/render';
import { json, makeUser, mockFetch, shellRoutes, signedIn, SIGNED_OUT } from '../test/mockApi';

const NOTE = { id: 5, kind: 'approval.requested', title: 'Cerere nouă de aprobare', body: 'Ion cere trimiterea unui raport.', link: '/workspace/approvals/5', created_at: Date.now() / 1000 - 60, read_at: null };

describe('Shell', () => {
  it('shows the unread count, marks an item read and follows its in-app link', async () => {
    const mock = mockFetch({
      'GET /api/workspace/session': signedIn(makeUser({ role: 'approver' })),
      ...shellRoutes(),
      'GET /api/workspace/notifications': { items: [NOTE], unread_count: 1 },
      'POST /api/workspace/notifications/read': { unread_count: 0 },
    });
    renderApp('/workspace/assistant');
    const bell = await screen.findByRole('button', { name: 'Notificări — 1 necitită' });
    fireEvent.click(bell);
    const panel = await screen.findByRole('dialog', { name: 'Notificări' });
    fireEvent.click(await within(panel).findByRole('button', { name: /Cerere nouă de aprobare/ }));
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/approvals/5'));
    expect(mock.find('POST', '/api/workspace/notifications/read')[0].body).toEqual({ ids: [5] });
    expect(await screen.findByRole('heading', { level: 1, name: 'Aprobări' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Notificări' })).toBeTruthy();
  });

  it('marks everything read in one call', async () => {
    const mock = mockFetch({
      'GET /api/workspace/session': signedIn(makeUser()),
      ...shellRoutes(),
      'GET /api/workspace/notifications': { items: [NOTE, { ...NOTE, id: 6, link: '' }], unread_count: 2 },
      'POST /api/workspace/notifications/read': { unread_count: 0 },
    });
    renderApp('/workspace/assistant');
    fireEvent.click(await screen.findByRole('button', { name: /Notificări — 2 necitite/ }));
    const panel = await screen.findByRole('dialog', { name: 'Notificări' });
    await within(panel).findAllByRole('button', { name: /Cerere nouă/ });
    fireEvent.click(within(panel).getByRole('button', { name: 'Marchează toate ca citite' }));
    await waitFor(() => expect(mock.find('POST', '/api/workspace/notifications/read')[0]?.body).toEqual({ all: true }));
    expect(await screen.findByRole('button', { name: 'Notificări' })).toBeTruthy();
  });

  it('labels an unavailable model and explains why', async () => {
    mockFetch({
      'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })),
      ...shellRoutes(),
      'GET /api/workspace/model': { available: false, backend: null, model: null, route: null, locality: null, policy: 'local_only', reason: 'hub_not_ready', guardrails_mode: null },
    });
    renderApp('/workspace/assistant');
    const chip = await screen.findByRole('button', { name: 'Modelul AI: Indisponibil' });
    fireEvent.click(chip);
    const panel = await screen.findByRole('dialog', { name: 'Modelul AI' });
    expect(within(panel).getByText('Serverul Nerva încă pornește. Încearcă din nou peste un minut.')).toBeTruthy();
    expect(within(panel).queryByRole('link', { name: 'Setările modelului' })).toBeNull();
  });

  it('signs out to the login screen and does not let SSO sign straight back in', async () => {
    let session = { ...signedIn(makeUser()), sso_available: true };
    const mock = mockFetch({
      'GET /api/workspace/session': () => session,
      ...shellRoutes(),
      'POST /api/workspace/logout': () => { session = { ...SIGNED_OUT, sso_available: true }; return json(204); },
      'POST /api/workspace/login/sso': { status: 401, body: { error: 'sso_no_identity' } },
    });
    renderApp('/workspace/assistant');
    fireEvent.click(await screen.findByRole('button', { name: 'Contul tău: Ana Pop' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Deconectare' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Conectează-te' })).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/logout')).toHaveLength(1);
    expect(mock.find('POST', '/api/workspace/login/sso')).toHaveLength(0);
  });

  it('opens the navigation drawer from the menu button and remembers the chosen department', async () => {
    mockFetch({ 'GET /api/workspace/session': signedIn(makeUser({ department_ids: [1, 2] })), ...shellRoutes() });
    renderApp('/workspace/assistant');
    const sidebar = await screen.findByRole('complementary', { name: 'Bara laterală' });
    const select = await within(sidebar).findByLabelText('Departament');
    await waitFor(() => expect((select as HTMLSelectElement).value).toBe('1'));
    fireEvent.change(select, { target: { value: '2' } });
    expect(window.localStorage.getItem('nerva.workspace.department.1')).toBe('2');

    fireEvent.click(screen.getByRole('button', { name: 'Deschide meniul' }));
    const drawer = await screen.findByRole('dialog', { name: 'Meniu' });
    expect((within(drawer).getByLabelText('Departament') as HTMLSelectElement).value).toBe('2');
    fireEvent.click(within(drawer).getByRole('link', { name: 'Documente' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Meniu' })).toBeNull());
    expect(window.location.pathname).toBe('/workspace/documents');
  });

  it('renders the 404 page for an unknown in-app path', async () => {
    mockFetch({ 'GET /api/workspace/session': signedIn(makeUser()), ...shellRoutes() });
    renderApp('/workspace/does-not-exist');
    expect(await screen.findByRole('heading', { level: 1, name: 'Pagina nu există' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Mergi la Asistent' }).getAttribute('href')).toBe('/workspace/assistant');
  });
});
