import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render';
import { apiError, json, makeUser, mockFetch, shellRoutes, signedIn } from '../../test/mockApi';

const SESSIONS = {
  sessions: [
    { id: 'aaaaaaaaaaaa', current: true, created_at: 1_700_000_000, last_seen_at: 1_700_000_500, ip: '10.0.0.2', user_agent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36', via: 'password' },
    { id: 'bbbbbbbbbbbb', current: false, created_at: 1_699_000_000, last_seen_at: 1_699_000_500, ip: '10.0.0.9', user_agent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1', via: 'invite' },
  ],
};

function setup() {
  const user = makeUser({ role: 'member' });
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(user),
    ...shellRoutes(),
    'GET /api/workspace/me/sessions': SESSIONS,
  });
  renderApp('/workspace/profile');
  return { mock, user };
}

const passwordForm = async () => {
  const card = (await screen.findByRole('heading', { name: 'Parolă' })).closest('section') as HTMLElement;
  return {
    card,
    current: within(card).getByLabelText(/^Parola actuală/, { selector: 'input' }),
    next: within(card).getByLabelText(/^Parola nouă/, { selector: 'input' }),
    confirm: within(card).getByLabelText(/^Confirmă parola/, { selector: 'input' }),
    submit: within(card).getByRole('button', { name: 'Schimbă parola' }),
  };
};

describe('Profile → password', () => {
  it('shows live policy feedback and blocks a short password locally', async () => {
    const { mock } = setup();
    const form = await passwordForm();
    fireEvent.change(form.next, { target: { value: 'scurt' } });
    const rule = within(form.card).getByText('Între 12 și 256 de caractere').closest('li') as HTMLElement;
    expect(rule.className).toBe('is-bad');
    fireEvent.change(form.current, { target: { value: 'Vechea-Parola-1' } });
    fireEvent.change(form.confirm, { target: { value: 'scurt' } });
    fireEvent.click(form.submit);
    expect(await within(form.card).findByText('Parola trebuie să aibă cel puțin 12 caractere.')).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/me/password')).toHaveLength(0);
    fireEvent.change(form.next, { target: { value: 'Munte-Albastru-2026' } });
    expect(rule.className).toBe('is-ok');
  });

  it('changes the password, says other sessions closed, and reloads the session list', async () => {
    const { mock } = setup();
    mock.on('POST /api/workspace/me/password', json(204));
    const form = await passwordForm();
    await screen.findByText('Safari pe iOS');
    const before = mock.find('GET', '/api/workspace/me/sessions').length;
    fireEvent.change(form.current, { target: { value: 'Vechea-Parola-1' } });
    fireEvent.change(form.next, { target: { value: 'Munte-Albastru-2026' } });
    fireEvent.change(form.confirm, { target: { value: 'Munte-Albastru-2026' } });
    fireEvent.click(form.submit);
    expect(await screen.findByText('Parola a fost schimbată. Celelalte sesiuni au fost închise.')).toBeTruthy();
    const call = mock.find('POST', '/api/workspace/me/password')[0];
    // A fixture password the secret scan (gitleaks) would read as a credential: allowed on the line.
    expect(call.body).toEqual({ current_password: 'Vechea-Parola-1', new_password: 'Munte-Albastru-2026' }); // gitleaks:allow
    expect(call.headers['X-CSRF-Token']).toBe('csrf-1');
    expect((form.current as HTMLInputElement).value).toBe('');
    await waitFor(() => expect(mock.find('GET', '/api/workspace/me/sessions').length).toBeGreaterThan(before));
  });

  it('puts a wrong current password on its field and a common new password on the new field', async () => {
    const { mock } = setup();
    mock.on('POST /api/workspace/me/password', apiError(403, 'wrong_password'));
    const form = await passwordForm();
    fireEvent.change(form.current, { target: { value: 'gresit-dar-lung' } });
    fireEvent.change(form.next, { target: { value: 'Munte-Albastru-2026' } });
    fireEvent.change(form.confirm, { target: { value: 'Munte-Albastru-2026' } });
    fireEvent.click(form.submit);
    expect(await within(form.card).findByText('Parola actuală nu este corectă.')).toBeTruthy();
    expect(form.current.getAttribute('aria-invalid')).toBe('true');

    mock.on('POST /api/workspace/me/password', apiError(422, 'weak_password', { reason: 'too_common' }));
    fireEvent.click(form.submit);
    expect(await within(form.card).findByText('Parola este prea des folosită. Alege una mai greu de ghicit.')).toBeTruthy();
    expect(form.next.getAttribute('aria-invalid')).toBe('true');
  });
});

describe('Profile → sessions and preferences', () => {
  it('revokes another session after confirmation', async () => {
    const { mock } = setup();
    mock.on('DELETE /api/workspace/me/sessions/bbbbbbbbbbbb', json(204));
    const row = (await screen.findByText('Safari pe iOS')).closest('tr') as HTMLElement;
    expect(within((await screen.findByText('Chrome pe Windows')).closest('tr') as HTMLElement).queryByRole('button', { name: 'Închide sesiunea' })).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: 'Închide sesiunea' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Închizi această sesiune?' });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Închide sesiunea' }));
    expect(await screen.findByText('Sesiunea a fost închisă.')).toBeTruthy();
    expect(mock.find('DELETE', '/api/workspace/me/sessions/bbbbbbbbbbbb')).toHaveLength(1);
  });

  it('signs out every other session at once', async () => {
    const { mock } = setup();
    mock.on('POST /api/workspace/me/sessions/revoke-others', { revoked: 1 });
    await screen.findByText('Safari pe iOS');
    fireEvent.click(screen.getByRole('button', { name: 'Închide celelalte sesiuni' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Închizi celelalte sesiuni?' });
    expect(within(confirm).getByText(/1 alt dispozitiv va fi deconectat/)).toBeTruthy();
    fireEvent.click(within(confirm).getByRole('button', { name: 'Închide celelalte sesiuni' }));
    expect(await screen.findByText('1 sesiune a fost închisă.')).toBeTruthy();
  });

  it('switches the language at once and saves it to the account', async () => {
    const { mock, user } = setup();
    mock.on('PATCH /api/workspace/me', { user: { ...user, locale: 'en' } });
    const select = await screen.findByLabelText('Limbă', { selector: 'select' });
    fireEvent.change(select, { target: { value: 'en' } });
    expect(await screen.findByRole('heading', { level: 1, name: 'Profile' })).toBeTruthy();
    expect(mock.find('PATCH', '/api/workspace/me')[0].body).toEqual({ locale: 'en' });
    expect(document.documentElement.lang).toBe('en');
  });

  it('checks the chosen theme at once, while the save is still on its way', async () => {
    const { mock, user } = setup();
    let answer: (value: unknown) => void = () => undefined;
    mock.on('PATCH /api/workspace/me', () => new Promise((resolve) => { answer = resolve; }));
    const dark = await screen.findByLabelText(/^Întunecată/) as HTMLInputElement;
    fireEvent.click(dark);
    expect(dark.checked).toBe(true);
    expect((screen.getByLabelText(/^Luminoasă/) as HTMLInputElement).checked).toBe(false);
    expect(document.documentElement.dataset.theme).toBe('dark');
    answer({ user: { ...user, theme: 'dark' } });
    await waitFor(() => expect(mock.find('PATCH', '/api/workspace/me')).toHaveLength(1));
    expect(dark.checked).toBe(true);
  });

  it('shows the chosen language in its select at once, and reverts both when saving fails', async () => {
    const { mock } = setup();
    let fail: (value: unknown) => void = () => undefined;
    mock.on('PATCH /api/workspace/me', () => new Promise((resolve) => { fail = resolve; }));
    fireEvent.change(await screen.findByLabelText('Limbă', { selector: 'select' }), { target: { value: 'en' } });
    const select = await screen.findByLabelText('Language', { selector: 'select' }) as HTMLSelectElement;
    expect(select.value).toBe('en');
    fail(apiError(500, 'server_error'));
    expect(await screen.findByRole('heading', { level: 1, name: 'Profil' })).toBeTruthy();
    expect((screen.getByLabelText('Limbă', { selector: 'select' }) as HTMLSelectElement).value).toBe('ro');
    expect(document.documentElement.lang).toBe('ro');
  });

  it('applies the theme to <html> and reverts it when saving fails', async () => {
    const { mock } = setup();
    mock.on('PATCH /api/workspace/me', apiError(500, 'server_error'));
    fireEvent.click(await screen.findByLabelText(/^Întunecată/));
    await screen.findByText('Serverul a întâmpinat o problemă. Încearcă din nou peste câteva momente.');
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});
