import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { CompareAgentsDialog } from '../compare-agents';
import { apiFetchOnce } from '../api/client';
import { isNetworkedOrigin, loadOwnerSession } from '../api/owner-session';

const sessionListeners = vi.hoisted(() => new Set<() => void>());
const sessionState = vi.hoisted(() => ({ value: null as null | { signed_in: boolean; csrf?: string } }));
vi.mock('../api/client', () => ({ apiFetchOnce: vi.fn(), getToken: () => localStorage.getItem('hud.user_token') || '',
  getAdminToken: () => localStorage.getItem('hud.admin_token') || '' }));
vi.mock('../api/owner-session', () => ({
  isNetworkedOrigin: vi.fn(() => false), loadOwnerSession: vi.fn(),
  onOwnerSession: (listener: () => void) => { sessionListeners.add(listener); return () => sessionListeners.delete(listener); },
  ownerSession: () => sessionState.value, requireSignIn: vi.fn(),
}));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => { cleanup(); vi.resetAllMocks(); localStorage.clear(); sessionListeners.clear(); sessionState.value = null; });

const agents = [
  { id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }, { id: 'howard', name: 'Howard' },
];
function open(lang = 'en') {
  const opener = document.createElement('button');
  document.body.append(opener);
  opener.focus();
  const onClose = vi.fn();
  const view = render(<CompareAgentsDialog question="Original question" agent="jarvis" agents={agents}
    lang={lang} opener={opener} onClose={onClose} />);
  return { ...view, opener, onClose };
}

it('reviews an editable text-only question and sends exactly once only after Compare', async () => {
  vi.mocked(apiFetchOnce).mockResolvedValue(new Response(JSON.stringify({ opinions: [
    { agent: 'jarvis', ok: true, text: 'First answer', model: 'm1', route: 'local' },
    { agent: 'frigga', ok: false, reason: 'model_unavailable' },
  ] }), { status: 200 }));
  const view = open();
  expect(apiFetchOnce).not.toHaveBeenCalled();
  const question = screen.getByRole('textbox', { name: 'Question' });
  expect(question).toHaveProperty('value', 'Original question');
  const first = screen.getByRole('combobox', { name: 'First agent' }) as HTMLSelectElement;
  const second = screen.getByRole('combobox', { name: 'Second agent' }) as HTMLSelectElement;
  expect(first.value).toBe('jarvis');
  expect(second.value).toBe('frigga');
  expect(second.querySelector('option[value="jarvis"]')?.hasAttribute('disabled')).toBe(true);
  fireEvent.change(question, { target: { value: 'Edited plain question' } });
  expect(apiFetchOnce).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await waitFor(() => expect(screen.getByText('First answer')).toBeTruthy());
  expect(apiFetchOnce).toHaveBeenCalledOnce();
  expect(vi.mocked(apiFetchOnce).mock.calls[0][0]).toBe('/api/agents/opinions');
  expect(vi.mocked(apiFetchOnce).mock.calls[0][1]).toMatchObject({ method: 'POST', admin: true,
    body: { question: 'Edited plain question', agents: ['jarvis', 'frigga'], allow_cloud: false },
    signal: expect.any(AbortSignal),
  });
  expect(screen.getByText('No eligible model is available.')).toBeTruthy();
  expect(screen.getByText(/m1 · local/)).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Frigga (frigga)' })).toBeTruthy();
  view.unmount();
  expect(document.activeElement).toBe(view.opener);
  view.opener.remove();
});

it('requires fresh cloud consent per changed question and never sends on a choice change', async () => {
  vi.mocked(apiFetchOnce).mockResolvedValue(new Response(JSON.stringify({ opinions: [] }), { status: 200 }));
  const view = open('ro');
  const consent = screen.getByRole('checkbox', { name: /cloud/i }) as HTMLInputElement;
  fireEvent.click(consent);
  expect(consent.checked).toBe(true);
  fireEvent.change(screen.getByRole('textbox', { name: 'Întrebare' }), { target: { value: 'Altă întrebare' } });
  expect(consent.checked).toBe(false);
  const first = screen.getByRole('combobox', { name: 'Primul agent' }) as HTMLSelectElement;
  fireEvent.change(first, { target: { value: 'howard' } });
  expect(apiFetchOnce).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Compară răspunsurile' }).hasAttribute('disabled')).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Compară răspunsurile' }));
  await waitFor(() => expect(apiFetchOnce).toHaveBeenCalledOnce());
  expect(vi.mocked(apiFetchOnce).mock.calls[0][1]).toMatchObject({ body: {
    question: 'Altă întrebare', agents: ['howard', 'frigga'], allow_cloud: false,
  } });
  view.unmount(); view.opener.remove();
});

it('blocks duplicate clicks, aborts on unmount, and ignores a late response', async () => {
  let finish!: (value: Response) => void;
  vi.mocked(apiFetchOnce).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = open();
  const submit = screen.getByRole('button', { name: 'Compare answers' });
  fireEvent.click(submit);
  fireEvent.click(submit);
  expect(apiFetchOnce).toHaveBeenCalledOnce();
  expect(screen.getByRole('status').textContent).toContain('Waiting for both agents');
  const signal = vi.mocked(apiFetchOnce).mock.calls[0][1]?.signal;
  expect(signal?.aborted).toBe(false);
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(new Response(JSON.stringify({ opinions: [{ agent: 'jarvis', ok: true, text: 'Late' }] }))));
  expect(screen.queryByText('Late')).toBeNull();
  view.opener.remove();
});

it('keeps the draft after a refused request and lets Escape close with focus restored', async () => {
  vi.mocked(apiFetchOnce).mockResolvedValue(new Response('{}', { status: 503 }));
  const view = open();
  fireEvent.change(screen.getByRole('textbox', { name: 'Question' }), { target: { value: 'Still mine' } });
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
  expect(screen.getByRole('textbox', { name: 'Question' })).toHaveProperty('value', 'Still mine');
  expect(apiFetchOnce).toHaveBeenCalledOnce();
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(view.onClose).toHaveBeenCalledOnce();
  view.unmount();
  expect(document.activeElement).toBe(view.opener);
  view.opener.remove();
});

it('sends cloud consent only after an explicit click, then clears old answers on edits', async () => {
  vi.mocked(apiFetchOnce).mockResolvedValue(new Response(JSON.stringify({ opinions: [
    { agent: 'jarvis', ok: true, text: 'A' }, { agent: 'frigga', ok: false, reason: 'cloud_disabled' },
  ] }), { status: 200 }));
  const view = open();
  fireEvent.click(screen.getByRole('checkbox', { name: /cloud/i }));
  expect(apiFetchOnce).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await waitFor(() => expect(screen.getByText('Cloud use is off for this question.')).toBeTruthy());
  expect(vi.mocked(apiFetchOnce).mock.calls[0][1]).toMatchObject({ body: { allow_cloud: true } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Question' }), { target: { value: 'New question' } });
  expect(screen.queryByText('Cloud use is off for this question.')).toBeNull();
  expect((screen.getByRole('checkbox', { name: /cloud/i }) as HTMLInputElement).checked).toBe(false);
  expect(apiFetchOnce).toHaveBeenCalledOnce();
  view.unmount(); view.opener.remove();
});

it('does not start a POST after close or principal rotation during owner preflight', async () => {
  vi.mocked(isNetworkedOrigin).mockReturnValue(true);
  let finish!: () => void;
  vi.mocked(loadOwnerSession).mockImplementation(() => new Promise(resolve => { finish = () => resolve({ signed_in: true }); }));
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  expect(loadOwnerSession).toHaveBeenCalledOnce();
  view.unmount();
  await act(async () => finish());
  expect(apiFetchOnce).not.toHaveBeenCalled();
  view.opener.remove();

  const other = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  localStorage.setItem('hud.admin_token', 'rotated');
  fireEvent.focus(window);
  await act(async () => finish());
  expect(apiFetchOnce).not.toHaveBeenCalled();
  expect(screen.getByRole('textbox', { name: 'Question' })).toHaveProperty('value', '');
  other.unmount(); other.opener.remove();
});

it('retains the reviewed draft when network owner access is first established', async () => {
  vi.mocked(isNetworkedOrigin).mockReturnValue(true);
  vi.mocked(loadOwnerSession).mockImplementation(async () => {
    sessionState.value = { signed_in: true, csrf: 'first-session' };
    sessionListeners.forEach(listener => listener());
    return sessionState.value;
  });
  vi.mocked(apiFetchOnce).mockResolvedValue(new Response(JSON.stringify({ opinions: [] }), { status: 200 }));
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await waitFor(() => expect(screen.getByText('Owner access is ready. Review the question and submit again.')).toBeTruthy());
  expect(apiFetchOnce).not.toHaveBeenCalled();
  expect(screen.getByRole('textbox', { name: 'Question' })).toHaveProperty('value', 'Original question');
  fireEvent.click(await screen.findByRole('button', { name: 'Compare answers' }));
  await waitFor(() => expect(apiFetchOnce).toHaveBeenCalledOnce());
  view.unmount(); view.opener.remove();
});

it('dismisses results when same-tab header credentials change or storage is cleared', async () => {
  vi.mocked(apiFetchOnce).mockImplementation(async () => new Response(JSON.stringify({ opinions: [
    { agent: 'jarvis', ok: true, text: 'Private answer' }, { agent: 'frigga', ok: false, reason: 'cloud_disabled' },
  ] }), { status: 200 }));
  localStorage.setItem('hud.admin_token', 'owner-a');
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await waitFor(() => expect(screen.getByText('Private answer')).toBeTruthy());
  localStorage.setItem('hud.admin_token', 'owner-b');
  fireEvent.focus(window);
  expect(screen.queryByText('Private answer')).toBeNull();
  expect(screen.getByRole('textbox', { name: 'Question' })).toHaveProperty('value', '');
  view.unmount(); view.opener.remove();

  const other = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await waitFor(() => expect(screen.getByText('Private answer')).toBeTruthy());
  localStorage.clear();
  fireEvent(window, new StorageEvent('storage', { key: null }));
  expect(screen.queryByText('Private answer')).toBeNull();
  other.unmount(); other.opener.remove();
});

it('handles malformed optional opinion fields without trying to render an object', async () => {
  vi.mocked(apiFetchOnce).mockResolvedValue(new Response(JSON.stringify({ opinions: [
    { agent: 'jarvis', ok: true, text: { hidden: 'bad' }, route: { bad: true } },
    { agent: 'frigga', ok: false, reason: { bad: true } },
  ] }), { status: 200 }));
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await waitFor(() => expect(screen.getAllByText('No answer returned.')).toHaveLength(2));
  expect([...document.querySelectorAll('.compare-agents-route')].every(node =>
    node.textContent?.includes('Model and route were not reported.'))).toBe(true);
  view.unmount(); view.opener.remove();
});

it('retains an answer when the owner session refreshes without changing credentials', async () => {
  vi.mocked(apiFetchOnce).mockResolvedValue(new Response(JSON.stringify({ opinions: [
    { agent: 'jarvis', ok: true, text: 'Still current' }, { agent: 'frigga', ok: false },
  ] }), { status: 200 }));
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await waitFor(() => expect(screen.getByText('Still current')).toBeTruthy());
  act(() => sessionListeners.forEach(listener => listener()));
  expect(screen.getByText('Still current')).toBeTruthy();
  expect(screen.getByRole('textbox', { name: 'Question' })).toHaveProperty('value', 'Original question');
  view.unmount(); view.opener.remove();
});

it('chooses two live agents if the previous agent vanished and shows their roles', () => {
  const opener = document.createElement('button');
  document.body.append(opener);
  const view = render(<CompareAgentsDialog question="Question" agent="vanished"
    agents={[{ id: 'frigga', name: 'Frigga', role: 'Local specialist' }, { id: 'howard', name: 'Howard', role: 'Researcher' }]}
    lang="en" opener={opener} onClose={vi.fn()} />);
  expect(screen.getByRole('combobox', { name: 'First agent' })).toHaveProperty('value', 'frigga');
  expect(screen.getByRole('combobox', { name: 'Second agent' })).toHaveProperty('value', 'howard');
  expect(screen.getByRole('button', { name: 'Compare answers' }).hasAttribute('disabled')).toBe(false);
  expect(screen.getAllByRole('option', { name: 'Frigga — Local specialist' })).toHaveLength(2);
  view.unmount(); opener.remove();
});

it('keeps an over-limit pasted draft visible and uses Unicode code points at the limit', () => {
  const view = open();
  const question = screen.getByRole('textbox', { name: 'Question' });
  fireEvent.change(question, { target: { value: '😀'.repeat(4096) } });
  expect(screen.getByRole('button', { name: 'Compare answers' }).hasAttribute('disabled')).toBe(false);
  fireEvent.change(question, { target: { value: '😀'.repeat(4097) } });
  expect(question).toHaveProperty('value', '😀'.repeat(4097));
  expect(screen.getByText('Shorten the question to 4,096 characters.')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Compare answers' }).hasAttribute('disabled')).toBe(true);
  expect(apiFetchOnce).not.toHaveBeenCalled();
  view.unmount(); view.opener.remove();
});

it('explains a busy server without automatically retrying', async () => {
  vi.mocked(apiFetchOnce).mockResolvedValue(new Response('{}', { status: 429 }));
  const view = open('ro');
  fireEvent.click(screen.getByRole('button', { name: 'Compară răspunsurile' }));
  await waitFor(() => expect(screen.getByText('O comparație este deja în curs. Așteaptă să se termine, apoi trimite din nou.')).toBeTruthy());
  expect(apiFetchOnce).toHaveBeenCalledOnce();
  view.unmount(); view.opener.remove();
});

it.each([
  ['timed_out', 'This agent ran out of time.', 'Acest agent a depășit timpul disponibil.'],
  ['generation_failed', 'This agent could not return an answer.', 'Acest agent nu a putut returna un răspuns.'],
  ['route_unavailable', 'No eligible route is available.', 'Nu există o rută eligibilă disponibilă.'],
])('shows %s as a localized refusal', async (reason, en, ro) => {
  vi.mocked(apiFetchOnce).mockImplementation(async () => new Response(JSON.stringify({ opinions: [
    { agent: 'jarvis', ok: false, reason }, { agent: 'frigga', ok: false, reason },
  ] }), { status: 200 }));
  for (const [lang, expected] of [['en', en], ['ro', ro]]) {
    const view = open(lang);
    fireEvent.click(screen.getByRole('button', { name: lang === 'ro' ? 'Compară răspunsurile' : 'Compare answers' }));
    await waitFor(() => expect(screen.getAllByText(expected)).toHaveLength(2));
    expect(screen.getByText(lang === 'ro' ? /Modelelor locale compatibile/ : /Supported local models receive a direct-answer request/)).toBeTruthy();
    view.unmount(); view.opener.remove();
  }
});
