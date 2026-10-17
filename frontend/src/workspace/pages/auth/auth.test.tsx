import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { getCsrfToken } from '../../api/client';
import { renderApp } from '../../test/render';
import {
  ADMIN_DEPARTMENTS, apiError, makeUser, mockFetch, ORG, shellRoutes, signedIn, SIGNED_OUT,
} from '../../test/mockApi';

const field = (name: RegExp) => screen.getByLabelText(name, { selector: 'input' });

describe('Login', () => {
  it('signs in and opens the shell at the requested page', async () => {
    const user = makeUser({ role: 'member' });
    const mock = mockFetch({
      'GET /api/workspace/session': SIGNED_OUT,
      'POST /api/workspace/login': { user, org: ORG, csrf_token: 'csrf-login' },
      ...shellRoutes(),
    });
    renderApp('/workspace/documents');
    expect(await screen.findByRole('heading', { level: 1, name: 'Conectează-te' })).toBeTruthy();
    expect(screen.getByText('de Digitaholic')).toBeTruthy();

    fireEvent.change(field(/^Email/), { target: { value: ' ana@acme.ro ' } });
    fireEvent.change(field(/^Parolă/), { target: { value: 'Parola-Buna-2026!' } });
    fireEvent.click(screen.getByRole('button', { name: 'Conectează-te' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Documente' })).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/login')[0].body).toEqual({ email: 'ana@acme.ro', password: 'Parola-Buna-2026!' });
    expect(getCsrfToken()).toBe('csrf-login');
    expect(screen.queryByRole('link', { name: /Administrare/ })).toBeNull();
    expect(await screen.findByText('2 cereri în așteptare')).toBeTruthy();
  });

  it('validates locally before calling the server', async () => {
    const mock = mockFetch({ 'GET /api/workspace/session': SIGNED_OUT });
    renderApp('/workspace/');
    await screen.findByRole('heading', { name: 'Conectează-te' });
    fireEvent.click(screen.getByRole('button', { name: 'Conectează-te' }));
    expect(await screen.findByText('Introdu o adresă de email validă.')).toBeTruthy();
    expect(screen.getByText('Introdu parola.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/login')).toHaveLength(0);
  });

  it('shows the generic credentials error and clears the password', async () => {
    mockFetch({
      'GET /api/workspace/session': SIGNED_OUT,
      'POST /api/workspace/login': apiError(401, 'invalid_credentials'),
    });
    renderApp('/workspace/');
    await screen.findByRole('heading', { name: 'Conectează-te' });
    fireEvent.change(field(/^Email/), { target: { value: 'ana@acme.ro' } });
    fireEvent.change(field(/^Parolă/), { target: { value: 'gresit' } });
    fireEvent.click(screen.getByRole('button', { name: 'Conectează-te' }));
    expect(await screen.findByText('Emailul sau parola nu sunt corecte.')).toBeTruthy();
    expect((field(/^Parolă/) as HTMLInputElement).value).toBe('');
  });

  it('tells a throttled user when to retry', async () => {
    mockFetch({
      'GET /api/workspace/session': SIGNED_OUT,
      'POST /api/workspace/login': apiError(429, 'too_many_attempts', { retry_after_seconds: 840 }),
    });
    renderApp('/workspace/');
    await screen.findByRole('heading', { name: 'Conectează-te' });
    fireEvent.change(field(/^Email/), { target: { value: 'ana@acme.ro' } });
    fireEvent.change(field(/^Parolă/), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Conectează-te' }));
    expect(await screen.findByText('Prea multe încercări nereușite. Poți încerca din nou peste 14 minute.')).toBeTruthy();
  });

  it('returns to the login screen with an explanation when the session expires mid-use', async () => {
    let session = signedIn(makeUser({ role: 'member' }));
    mockFetch({
      'GET /api/workspace/session': () => session,
      ...shellRoutes(),
      'GET /api/workspace/me/sessions': () => { session = SIGNED_OUT; return apiError(401, 'auth_required'); },
    });
    renderApp('/workspace/profile');
    expect(await screen.findByText('Sesiunea ta s-a încheiat. Conectează-te din nou pentru a continua.')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1, name: 'Conectează-te' })).toBeTruthy();
  });

  it('offers proxy SSO when the server has it and signs in through it', async () => {
    const user = makeUser({ role: 'member' });
    const mock = mockFetch({
      'GET /api/workspace/session': { ...SIGNED_OUT, sso_available: true },
      'POST /api/workspace/login/sso': apiError(401, 'sso_no_identity'),
      ...shellRoutes(),
    });
    renderApp('/workspace/');
    const sso = await screen.findByRole('button', { name: 'Continuă cu contul companiei' });
    await waitFor(() => expect(mock.find('POST', '/api/workspace/login/sso')).toHaveLength(1));
    expect(screen.queryByText(/nu a transmis identitatea/)).toBeNull();
    mock.on('POST /api/workspace/login/sso', { user, org: ORG, csrf_token: 'c' });
    fireEvent.click(sso);
    expect(await screen.findByRole('heading', { level: 1, name: 'Asistent' })).toBeTruthy();
  });

  it('shows the disabled screen when the workspace flag is off', async () => {
    mockFetch({ 'GET /api/workspace/session': apiError(404, 'workspace_disabled') });
    renderApp('/workspace/');
    expect(await screen.findByRole('heading', { name: 'Nerva Workspace nu este activat' })).toBeTruthy();
  });
});

describe('First-run setup', () => {
  const fill = () => {
    fireEvent.change(field(/^Cod de configurare/), { target: { value: ' cod-123 ' } });
    fireEvent.change(field(/^Numele organizației/), { target: { value: 'Acme SRL' } });
    fireEvent.change(field(/^Nume$/), { target: { value: 'Ana Pop' } });
    fireEvent.change(field(/^Email/), { target: { value: 'ana@acme.ro' } });
    fireEvent.change(field(/^Parolă$/), { target: { value: 'Munte-Albastru-2026' } });
    fireEvent.change(field(/^Confirmă parola/), { target: { value: 'Munte-Albastru-2026' } });
  };

  it('creates the organisation and lands the new admin on Users', async () => {
    const admin = makeUser();
    const mock = mockFetch({
      'GET /api/workspace/session': { ...SIGNED_OUT, setup_required: true },
      'POST /api/workspace/setup': { status: 201, body: { user: admin, org: ORG, csrf_token: 'csrf-setup' } },
      ...shellRoutes(),
      'GET /api/workspace/admin/users': { users: [{ ...admin, last_login_at: null, pending_invite: null }] },
      'GET /api/workspace/admin/departments': { departments: ADMIN_DEPARTMENTS },
      'GET /api/workspace/admin/smtp': { host: '', port: 587, security: 'starttls', username: '', from_address: '', from_name: '', allowed_domains: [], has_password: false },
    });
    renderApp('/workspace/');
    expect(await screen.findByRole('heading', { name: 'Configurează Nerva Workspace' })).toBeTruthy();
    expect(screen.getByText(/setup-code\.txt/)).toBeTruthy();
    fill();
    fireEvent.click(screen.getByRole('button', { name: 'Creează spațiul de lucru' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Utilizatori' })).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/setup')[0].body).toEqual({
      setup_code: 'cod-123', org_name: 'Acme SRL', name: 'Ana Pop', email: 'ana@acme.ro', password: 'Munte-Albastru-2026', locale: 'ro',
    });
    expect(window.location.pathname).toBe('/workspace/admin/users');
  });

  it('marks a wrong setup code on its field', async () => {
    mockFetch({
      'GET /api/workspace/session': { ...SIGNED_OUT, setup_required: true },
      'POST /api/workspace/setup': apiError(403, 'invalid_setup_code'),
    });
    renderApp('/workspace/');
    await screen.findByRole('heading', { name: 'Configurează Nerva Workspace' });
    fill();
    fireEvent.click(screen.getByRole('button', { name: 'Creează spațiul de lucru' }));
    expect(await screen.findByText('Codul de configurare nu este corect.')).toBeTruthy();
    expect(field(/^Cod de configurare/).getAttribute('aria-invalid')).toBe('true');
  });

  it('applies the password policy before sending', async () => {
    const mock = mockFetch({ 'GET /api/workspace/session': { ...SIGNED_OUT, setup_required: true } });
    renderApp('/workspace/');
    await screen.findByRole('heading', { name: 'Configurează Nerva Workspace' });
    fill();
    fireEvent.change(field(/^Parolă$/), { target: { value: 'ana-are-mere-2026' } });
    fireEvent.change(field(/^Confirmă parola/), { target: { value: 'altceva' } });
    fireEvent.click(screen.getByRole('button', { name: 'Creează spațiul de lucru' }));
    expect(await screen.findByText('Parola nu poate conține partea dinaintea @ din adresa de email.')).toBeTruthy();
    expect(screen.getByText('Parolele nu coincid.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/setup')).toHaveLength(0);
  });
});

describe('Invite and reset', () => {
  const TOKEN = 'tok_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_abc';

  it('reads the token from the fragment, clears it, and activates the account', async () => {
    const user = makeUser({ id: 7, email: 'ion@acme.ro', name: 'Ion', role: 'member' });
    const replaceState = vi.spyOn(window.history, 'replaceState');
    const mock = mockFetch({
      'GET /api/workspace/session': SIGNED_OUT,
      'POST /api/workspace/invites/lookup': { email: 'ion@acme.ro', name: 'Ion', org_name: 'Acme', purpose: 'invite', expires_at: 1_800_000_000 },
      'POST /api/workspace/invites/accept': { user, org: ORG, csrf_token: 'csrf-inv' },
      ...shellRoutes(),
    });
    renderApp(`/workspace/invite#t=${TOKEN}`);
    expect(await screen.findByRole('heading', { name: 'Bine ai venit în Acme' })).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/invites/lookup')[0].body).toEqual({ token: TOKEN });
    expect(window.location.hash).toBe('');
    expect(replaceState).toHaveBeenCalled();
    expect((field(/^Nume$/) as HTMLInputElement).value).toBe('Ion');

    fireEvent.change(field(/^Nume$/), { target: { value: 'Ion Popescu' } });
    fireEvent.change(field(/^Parola nouă/), { target: { value: 'Munte-Albastru-2026' } });
    fireEvent.change(field(/^Confirmă parola/), { target: { value: 'Munte-Albastru-2026' } });
    fireEvent.click(screen.getByRole('button', { name: 'Activează contul' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Asistent' })).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/invites/accept')[0].body).toEqual({ token: TOKEN, password: 'Munte-Albastru-2026', name: 'Ion Popescu' });
  });

  it('resets a password without asking for a name and maps a server policy refusal', async () => {
    const mock = mockFetch({
      'GET /api/workspace/session': SIGNED_OUT,
      'POST /api/workspace/invites/lookup': { email: 'ion@acme.ro', name: 'Ion', org_name: 'Acme', purpose: 'reset', expires_at: 1_800_000_000 },
      'POST /api/workspace/invites/accept': apiError(422, 'weak_password', { reason: 'too_common' }),
    });
    renderApp(`/workspace/invite#t=${TOKEN}`);
    expect(await screen.findByRole('heading', { name: 'Alege o parolă nouă' })).toBeTruthy();
    expect(screen.queryByLabelText(/^Nume$/)).toBeNull();
    fireEvent.change(field(/^Parola nouă/), { target: { value: 'Password12345' } });
    fireEvent.change(field(/^Confirmă parola/), { target: { value: 'Password12345' } });
    fireEvent.click(screen.getByRole('button', { name: 'Salvează parola nouă' }));
    expect(await screen.findByText('Parola este prea des folosită. Alege una mai greu de ghicit.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/invites/accept')[0].body).toEqual({ token: TOKEN, password: 'Password12345' });
  });

  it('explains an expired or used link and drops the fragment', async () => {
    mockFetch({
      'GET /api/workspace/session': SIGNED_OUT,
      'POST /api/workspace/invites/lookup': apiError(404, 'invite_invalid'),
    });
    renderApp(`/workspace/invite#t=${TOKEN}`);
    expect(await screen.findByRole('heading', { name: 'Linkul nu mai este valabil' })).toBeTruthy();
    expect(window.location.hash).toBe('');
  });

  it('treats a link without a token as invalid without calling the server', async () => {
    const mock = mockFetch({ 'GET /api/workspace/session': SIGNED_OUT });
    renderApp('/workspace/invite');
    expect(await screen.findByRole('heading', { name: 'Linkul nu mai este valabil' })).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/invites/lookup')).toHaveLength(0);
  });

  it('keeps the fragment when the lookup fails on the network so a retry works', async () => {
    let fail = true;
    const mock = mockFetch({
      'GET /api/workspace/session': SIGNED_OUT,
      'POST /api/workspace/invites/lookup': () => {
        if (fail) throw new TypeError('offline');
        return { email: 'ion@acme.ro', name: 'Ion', org_name: 'Acme', purpose: 'invite', expires_at: 1_800_000_000 };
      },
    });
    renderApp(`/workspace/invite#t=${TOKEN}`);
    const alert = await screen.findByText(/Nu ne-am putut conecta la server/);
    expect(window.location.hash).toBe(`#t=${TOKEN}`);
    fail = false;
    fireEvent.click(within(alert.closest('.ws-auth__card') as HTMLElement).getByRole('button', { name: 'Încearcă din nou' }));
    expect(await screen.findByRole('heading', { name: 'Bine ai venit în Acme' })).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/invites/lookup')).toHaveLength(2);
  });
});
