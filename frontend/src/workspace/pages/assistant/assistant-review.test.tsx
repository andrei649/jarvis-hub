/* Review fixes on the Assistant (frontend fixer, QA round 2): focus never falls to <body> after
   Send, Stop, Retry or a suggested question (A11Y-02); message bodies are not live regions and
   one status region says when the answer is ready (A11Y-08); a cancelled answer says "you
   stopped it" only when this page saw Stop (F5); a failed answer re-reads the model posture
   (F2); a typed question survives the session ending (F3); the policy-blocked hint is precise
   and not repeated (F6); the "no documents" guidance reads ready documents (F10).
   Round 3: the email request keeps its recipients and edited text when the session ends (F3),
   and the line under an answer says where it was produced in words, with the model id for
   admins only (UX-13). */
import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '../../api/types';
import { renderApp } from '../../test/render';
import { DEPARTMENTS, json, makeUser, mockFetch, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';
import { sseChannel } from '../../test/streams';

const NOW = Date.now() / 1000;
const CONVERSATION = { id: 7, title: 'Termene de plată', department_id: 1, created_at: NOW - 600, updated_at: NOW - 60 };

function message(over: Partial<ChatMessage>): ChatMessage {
  return {
    id: 1, role: 'assistant', content: '', citations: [], status: 'complete', error_code: null, model: 'qwen2.5', locality: 'local',
    latency_ms: 1400, feedback: null, created_at: NOW - 30, ...over,
  };
}

const QUESTION = message({ id: 11, role: 'user', content: 'Care e termenul?', model: null, locality: null, latency_ms: null });
const ANSWER = message({ id: 12, content: 'Termenul este de 30 de zile.' });

function boot(path: string, routes: Record<string, RouteHandler> = {}, user = makeUser({ role: 'member' })) {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(user),
    ...shellRoutes(),
    'GET /api/workspace/conversations': { conversations: [{ ...CONVERSATION, message_count: 2 }] },
    'GET /api/workspace/conversations/7': { conversation: CONVERSATION, messages: [] },
    'GET /api/workspace/approvals/eligible': { count: 1, smtp_configured: true },
    ...routes,
  });
  renderApp(path);
  return mock;
}

async function composer(): Promise<HTMLTextAreaElement> {
  return (await screen.findByLabelText('Întrebarea ta')) as HTMLTextAreaElement;
}

describe('Assistant → focus after the control in use goes away (A11Y-02)', () => {
  it('Send: focus sits on Stop while streaming, then returns to the question box, never to <body>', async () => {
    const channel = sseChannel();
    boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => channel.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    fireEvent.change(await composer(), { target: { value: 'Care e termenul?' } });
    const send = screen.getByRole('button', { name: 'Trimite' });
    send.focus();
    fireEvent.click(send);
    await screen.findByRole('button', { name: 'Oprește' });
    expect(document.activeElement).not.toBe(document.body);
    channel.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    channel.send('done', { assistant_message: ANSWER });
    channel.close();
    await screen.findByText('Termenul este de 30 de zile.');
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('Întrebarea ta')));
  });

  it('Stop: focus moves to the question box, and the answer says the person stopped it', async () => {
    const channel = sseChannel();
    boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => channel.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    fireEvent.change(await composer(), { target: { value: 'Care e termenul?' } });
    fireEvent.keyDown(screen.getByLabelText('Întrebarea ta'), { key: 'Enter' });
    const stop = await screen.findByRole('button', { name: 'Oprește' });
    channel.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    stop.focus();
    fireEvent.click(stop);
    expect(await screen.findByText('Ai oprit răspunsul', { selector: '.ws-notice__title' })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('Întrebarea ta')));
    expect(channel.cancelled).toBe(true);
  });

  it('Retry: the button disappears with the failed answer, focus goes to the question box', async () => {
    const first = sseChannel();
    const second = sseChannel();
    const replies = [first, second];
    boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => replies.shift()!.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    fireEvent.change(await composer(), { target: { value: 'Care e termenul?' } });
    fireEvent.keyDown(screen.getByLabelText('Întrebarea ta'), { key: 'Enter' });
    await screen.findByRole('button', { name: 'Oprește' });
    first.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    first.send('error', { error: 'model_timeout', message: 'timed out' });
    first.close();
    const retry = await screen.findByRole('button', { name: 'Întreabă din nou' });
    retry.focus();
    fireEvent.click(retry);
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Întreabă din nou' })).toBeNull());
    expect(document.activeElement).toBe(screen.getByLabelText('Întrebarea ta'));
    second.send('done', { assistant_message: ANSWER });
    second.close();
    await screen.findByText('Termenul este de 30 de zile.');
    expect(document.activeElement).toBe(screen.getByLabelText('Întrebarea ta'));
  });

  it('a suggested question: the empty state goes away, focus goes to the question box', async () => {
    const channel = sseChannel();
    boot('/workspace/assistant', {
      'POST /api/workspace/conversations': { status: 201, body: { ...CONVERSATION, id: 8, title: 'Conversație nouă' } },
      'POST /api/workspace/conversations/8/messages': () => channel.response(),
    });
    const prompt = (await screen.findAllByRole('button', { name: /proceduri|Rezumă|termene/ }))[0];
    prompt.focus();
    fireEvent.click(prompt);
    await waitFor(() => expect(screen.queryByText('Întrebări sugerate')).toBeNull());
    expect(document.activeElement).toBe(screen.getByLabelText('Întrebarea ta'));
    channel.send('done', { assistant_message: ANSWER });
    channel.close();
    await screen.findByText('Termenul este de 30 de zile.');
  });
});

describe('Assistant → announcements and states', () => {
  it('message bodies are not live regions; the status region says when the answer is ready (A11Y-08)', async () => {
    const channel = sseChannel();
    boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => channel.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    fireEvent.change(await composer(), { target: { value: 'Care e termenul?' } });
    fireEvent.keyDown(screen.getByLabelText('Întrebarea ta'), { key: 'Enter' });
    await screen.findByRole('button', { name: 'Oprește' });
    const status = screen.getAllByRole('status').find((el) => el.textContent === 'Asistentul scrie un răspuns…') as HTMLElement;
    expect(status).toBeTruthy();
    channel.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    channel.send('token', { t: 'Termenul este' });
    await screen.findByText('Termenul este');
    expect(document.querySelectorAll('.ws-msg__answer[aria-live]')).toHaveLength(0);
    expect(document.querySelector('.ws-msg__answer')?.getAttribute('aria-busy')).toBe('true');
    channel.send('done', { assistant_message: ANSWER });
    channel.close();
    await waitFor(() => expect(status.textContent).toBe('Răspunsul este gata.'));
    expect(document.querySelectorAll('[aria-live]').length).toBeLessThanOrEqual(3); // the chat status + the two toast regions
  });

  it('a stored "cancelled" answer (a reload, leaving the page) reads as interrupted, not as stopped (F5)', async () => {
    boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': { conversation: CONVERSATION, messages: [QUESTION, message({ id: 12, status: 'error', error_code: 'cancelled' })] },
    });
    expect(await screen.findByText('Răspunsul a fost întrerupt', { selector: '.ws-notice__title' })).toBeTruthy();
    expect(screen.queryByText('Ai oprit răspunsul')).toBeNull();
    expect(screen.getByText(/de exemplu pentru că ai reîncărcat pagina sau ai părăsit conversația/)).toBeTruthy();
  });

  it('a failed answer re-reads the model posture at once, so the chip shows the outage (F2)', async () => {
    const channel = sseChannel();
    let down = false;
    boot('/workspace/assistant/7', {
      'POST /api/workspace/conversations/7/messages': () => channel.response(),
      'GET /api/workspace/model': () => (down
        ? { available: false, backend: 'lm-studio', model: 'qwen', route: 'local', locality: 'local', policy: 'local_only', reason: 'model_unreachable', guardrails_mode: null }
        : { available: true, backend: 'lm-studio', model: 'qwen', route: 'local', locality: 'local', policy: 'local_only', reason: null, guardrails_mode: null }),
    });
    expect(await screen.findByRole('button', { name: 'Modelul AI: Local' })).toBeTruthy();
    fireEvent.change(await composer(), { target: { value: 'Care e termenul?' } });
    fireEvent.keyDown(screen.getByLabelText('Întrebarea ta'), { key: 'Enter' });
    await screen.findByRole('button', { name: 'Oprește' });
    down = true;
    channel.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    channel.send('error', { error: 'model_unavailable', reason: 'model_unreachable', message: 'unreachable' });
    channel.close();
    expect(await screen.findByText('Modelul AI nu este disponibil acum. Serverul modelului nu poate fi contactat (este oprit sau conexiunea s-a întrerupt).')).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Modelul AI: Indisponibil' })).toBeTruthy();
  });

  it('the policy-blocked failure names the real fix once, not the same sentence twice (F6)', async () => {
    const channel = sseChannel();
    boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => channel.response() }, makeUser({ role: 'admin' }));
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    fireEvent.change(await composer(), { target: { value: 'Care e termenul?' } });
    fireEvent.keyDown(screen.getByLabelText('Întrebarea ta'), { key: 'Enter' });
    await screen.findByRole('button', { name: 'Oprește' });
    channel.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    channel.send('error', { error: 'model_policy_blocked', reason: 'data_policy_unacknowledged', message: 'blocked' });
    channel.close();
    const answer = await screen.findByText(/Proprietarul serverului Nerva nu a confirmat încă/, { selector: '.ws-notice p' });
    const notice = answer.closest('.ws-notice') as HTMLElement;
    const text = notice.textContent ?? '';
    expect(text.split('Politica organizației nu permite modelul disponibil acum.').length - 1).toBe(1);
    expect(within(notice).getAllByText(/ghidul pilotului, §3\.3/, { selector: 'p' }).length).toBeGreaterThan(0);
    expect(text).toContain('Schimbarea politicii de model nu ajută.');
    expect(text).not.toContain('poate schimba politica');
  });

  it('a department whose uploads all failed still says the assistant has nothing to cite (F10)', async () => {
    mockFetch({
      'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })),
      ...shellRoutes(),
      'GET /api/workspace/departments': { departments: [{ ...DEPARTMENTS[0], document_count: 3, ready_document_count: 0 }] },
      'GET /api/workspace/conversations': { conversations: [] },
    });
    renderApp('/workspace/assistant');
    expect(await screen.findByText(/nu are încă documente gata de folosit/)).toBeTruthy();
  });

  it('greets a first-time user by name until the first question, not someone with conversations (UX-07)', async () => {
    boot('/workspace/assistant', { 'GET /api/workspace/conversations': { conversations: [] } }, makeUser({ role: 'member', name: 'Mihai Ionescu' }));
    expect(await screen.findByText('Bine ai venit, Mihai!')).toBeTruthy();
    expect(screen.getByText(/Rapoartele programate le găsești în Rapoarte/)).toBeTruthy();
    cleanup();
    boot('/workspace/assistant', {}, makeUser({ role: 'member', name: 'Mihai Ionescu' }));
    expect(await screen.findByText('Cu ce te pot ajuta?')).toBeTruthy();
    expect(screen.queryByText('Bine ai venit, Mihai!')).toBeNull();
  });
});

describe('Assistant → drafts survive the session ending (F3)', () => {
  it('a question typed when the session ends is back in the composer after signing in again', async () => {
    boot('/workspace/assistant/7');
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    fireEvent.change(await composer(), { target: { value: 'O întrebare lungă despre termenele de plată din contracte' } });
    // The session ends: the shell unmounts (as the login screen replaces it), then comes back.
    cleanup();
    boot('/workspace/assistant/7');
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    await waitFor(() => expect((screen.getByLabelText('Întrebarea ta') as HTMLTextAreaElement).value)
      .toBe('O întrebare lungă despre termenele de plată din contracte'));
  });

  it('a sent question leaves no draft behind, and another user in the tab never sees it', async () => {
    const channel = sseChannel();
    boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => channel.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    fireEvent.change(await composer(), { target: { value: 'Ciornă a altcuiva' } });
    cleanup();
    boot('/workspace/assistant/7', {}, makeUser({ id: 2, role: 'member', name: 'Altcineva' }));
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    expect((screen.getByLabelText('Întrebarea ta') as HTMLTextAreaElement).value).toBe('');
    cleanup();
    boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => channel.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    await waitFor(() => expect((screen.getByLabelText('Întrebarea ta') as HTMLTextAreaElement).value).toBe('Ciornă a altcuiva'));
    fireEvent.keyDown(screen.getByLabelText('Întrebarea ta'), { key: 'Enter' });
    await act(async () => { channel.send('done', { assistant_message: ANSWER }); channel.close(); });
    await screen.findByText('Termenul este de 30 de zile.');
    cleanup();
    boot('/workspace/assistant/7');
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    expect((screen.getByLabelText('Întrebarea ta') as HTMLTextAreaElement).value).toBe('');
  });
});

describe('Assistant → the email request keeps its draft (F3)', () => {
  const history = { conversation: CONVERSATION, messages: [QUESTION, ANSWER] };

  async function openEmail() {
    fireEvent.click(await screen.findByRole('button', { name: 'Trimite pe email' }));
    const dialog = await screen.findByRole('dialog', { name: 'Trimite pe email' });
    await within(dialog).findByText('1 persoană poate aproba această cerere.');
    return dialog;
  }
  const to = (dialog: HTMLElement) => within(dialog).getByLabelText(/^Destinatari/) as HTMLInputElement;
  const body = (dialog: HTMLElement) => within(dialog).getByLabelText(/^Mesaj/) as HTMLTextAreaElement;

  it('recipients and an edited message come back after signing in again, until the request is cancelled', async () => {
    boot('/workspace/assistant/7', { 'GET /api/workspace/conversations/7': history });
    let dialog = await openEmail();
    expect(within(dialog).queryByText(/Am păstrat ce scriseseși/)).toBeNull();
    const prefilled = body(dialog).value;
    expect(prefilled).toContain('Termenul este de 30 de zile.');
    fireEvent.change(to(dialog), { target: { value: 'ion@client.ro' } });
    fireEvent.change(body(dialog), { target: { value: 'Bună ziua, vă trimit termenul: 30 de zile.' } });

    cleanup();
    boot('/workspace/assistant/7', { 'GET /api/workspace/conversations/7': history });
    dialog = await openEmail();
    expect(within(dialog).getByText(/Am păstrat ce scriseseși și nu trimiseseși/)).toBeTruthy();
    expect(to(dialog).value).toBe('ion@client.ro');
    expect(body(dialog).value).toBe('Bună ziua, vă trimit termenul: 30 de zile.');

    fireEvent.click(within(dialog).getByRole('button', { name: 'Renunță' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Trimite pe email' })).toBeNull());
    dialog = await openEmail();
    expect(within(dialog).queryByText(/Am păstrat ce scriseseși/)).toBeNull();
    expect(to(dialog).value).toBe('');
    expect(body(dialog).value).toBe(prefilled);
  });

  it('a sent request leaves no draft behind, and another user in the tab never sees one', async () => {
    boot('/workspace/assistant/7', { 'GET /api/workspace/conversations/7': history });
    let dialog = await openEmail();
    fireEvent.change(to(dialog), { target: { value: 'ion@client.ro' } });

    cleanup();
    boot('/workspace/assistant/7', { 'GET /api/workspace/conversations/7': history }, makeUser({ id: 2, role: 'member', name: 'Altcineva' }));
    dialog = await openEmail();
    expect(to(dialog).value).toBe('');

    cleanup();
    const mock = boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': history,
      'POST /api/workspace/approvals': json(201, { id: 31, kind: 'email.send', status: 'pending' }),
    });
    dialog = await openEmail();
    expect(to(dialog).value).toBe('ion@client.ro');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cere aprobarea' }));
    expect(await screen.findByRole('dialog', { name: 'Cererea a fost trimisă' })).toBeTruthy();
    expect((mock.find('POST', '/api/workspace/approvals')[0].body as { payload: { to: string[] } }).payload.to).toEqual(['ion@client.ro']);
    fireEvent.click(screen.getByRole('button', { name: 'Gata' }));

    cleanup();
    boot('/workspace/assistant/7', { 'GET /api/workspace/conversations/7': history });
    dialog = await openEmail();
    expect(to(dialog).value).toBe('');
    expect(within(dialog).queryByText(/Am păstrat ce scriseseși/)).toBeNull();
  });
});

describe('Assistant → the answer meta speaks plainly (UX-13)', () => {
  const history = { conversation: CONVERSATION, messages: [QUESTION, ANSWER] };

  it('tells a member where the answer was produced in words, without the model id', async () => {
    boot('/workspace/assistant/7', { 'GET /api/workspace/conversations/7': history });
    expect(await screen.findByText('Pe serverul companiei')).toBeTruthy();
    expect(screen.queryByText('qwen2.5')).toBeNull();
    expect(screen.queryByText('local')).toBeNull();
  });

  it('shows an admin the model id next to the same words', async () => {
    boot('/workspace/assistant/7', { 'GET /api/workspace/conversations/7': history }, makeUser({ role: 'admin' }));
    expect(await screen.findByText('Pe serverul companiei')).toBeTruthy();
    expect(screen.getByText('qwen2.5')).toBeTruthy();
  });

  it('says so plainly for a cloud answer and an unconfirmed location', async () => {
    boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': { conversation: CONVERSATION, messages: [QUESTION, ANSWER, message({ id: 14, content: 'Alt răspuns.', locality: 'cloud' }), message({ id: 15, content: 'Încă unul.', locality: 'unknown' })] },
    });
    expect(await screen.findByText('La un furnizor cloud aprobat')).toBeTruthy();
    expect(screen.getByText('Locație neconfirmată')).toBeTruthy();
  });
});
