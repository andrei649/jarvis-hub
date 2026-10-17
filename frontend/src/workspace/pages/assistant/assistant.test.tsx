import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ChatMessage, Citation } from '../../api/types';
import { renderApp } from '../../test/render';
import { apiError, json, makeUser, mockFetch, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';
import { sseChannel } from '../../test/streams';

const NOW = Date.now() / 1000;
const CONVERSATION = { id: 7, title: 'Termene de plată', department_id: 1, created_at: NOW - 600, updated_at: NOW - 60 };
const CITATION: Citation = { n: 1, document_id: 5, title: 'Contract cadru.pdf', chunk_id: 31, page: 2, excerpt: 'Plata se face în 30 de zile de la factură.' };

function message(over: Partial<ChatMessage>): ChatMessage {
  return {
    id: 1, role: 'assistant', content: '', citations: [], status: 'complete', error_code: null, model: 'qwen2.5', locality: 'local',
    latency_ms: 1400, feedback: null, created_at: NOW - 30, ...over,
  };
}

const QUESTION = message({ id: 11, role: 'user', content: 'Care e termenul de plată?', model: null, locality: null, latency_ms: null });
const ANSWER = message({ id: 12, content: 'Termenul este de **30 de zile** [1].', citations: [CITATION] });

function boot(path: string, routes: Record<string, RouteHandler> = {}) {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })),
    ...shellRoutes(),
    'GET /api/workspace/conversations': { conversations: [{ ...CONVERSATION, message_count: 2 }] },
    'GET /api/workspace/conversations/7': { conversation: CONVERSATION, messages: [] },
    'GET /api/workspace/approvals/eligible': { count: 1, smtp_configured: true },
    ...routes,
  });
  renderApp(path);
  return mock;
}

async function ask(text: string) {
  const box = await screen.findByLabelText('Întrebarea ta');
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: 'Enter' });
}

describe('Assistant → streaming chat', () => {
  it('streams tokens and sources, then shows the stored answer whose citation opens the source drawer', async () => {
    const channel = sseChannel();
    const mock = boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => channel.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    await ask('Care e termenul de plată?');

    await waitFor(() => expect(mock.find('POST', '/api/workspace/conversations/7/messages')).toHaveLength(1));
    const call = mock.find('POST', '/api/workspace/conversations/7/messages')[0];
    expect(call.body).toEqual({ content: 'Care e termenul de plată?' });
    expect(call.headers.Accept).toBe('text/event-stream');
    expect(call.headers['X-CSRF-Token']).toBe('csrf-1');
    expect(await screen.findByText('Caută în documente…')).toBeTruthy();

    channel.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    channel.ping();
    channel.send('sources', { citations: [CITATION] });
    channel.send('token', { t: 'Termenul este de 30 de zile' });
    expect(await screen.findByText(/Termenul este de 30 de zile/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Oprește' })).toBeTruthy();

    channel.send('done', { assistant_message: ANSWER });
    channel.close();
    expect(await screen.findByText('30 de zile')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Trimite' })).toBeTruthy();
    expect(screen.getByText('local')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Sursa 1: Contract cadru.pdf' }));
    const drawer = await screen.findByRole('dialog', { name: 'Sursa [1]' });
    expect(within(drawer).getByText('Plata se face în 30 de zile de la factură.')).toBeTruthy();
    expect(within(drawer).getByText('· pagina 2')).toBeTruthy();
    expect(within(drawer).getByRole('link', { name: 'Deschide documentul' }).getAttribute('href')).toBe('/workspace/documents/5');
    expect(within(drawer).getByRole('link', { name: 'Descarcă originalul' }).getAttribute('href')).toBe('/api/workspace/documents/5/file');
  });

  it('drops the partial answer on an error event, explains it, and asks again', async () => {
    const first = sseChannel();
    const second = sseChannel();
    const replies = [first, second];
    const mock = boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => replies.shift()!.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    await ask('Care e termenul de plată?');
    await waitFor(() => expect(mock.find('POST', '/api/workspace/conversations/7/messages')).toHaveLength(1));

    first.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    first.send('token', { t: 'Un început de răspuns care' });
    expect(await screen.findByText('Un început de răspuns care')).toBeTruthy();
    first.send('error', { error: 'model_timeout', message: 'timed out' });
    first.close();

    expect(await screen.findByText('Modelul AI nu a răspuns la timp.')).toBeTruthy();
    expect(screen.getByText('Încearcă o întrebare mai scurtă sau mai precisă, apoi trimite din nou.')).toBeTruthy();
    expect(screen.queryByText('Un început de răspuns care')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Întreabă din nou' }));
    await waitFor(() => expect(mock.find('POST', '/api/workspace/conversations/7/messages')).toHaveLength(2));
    expect(mock.find('POST', '/api/workspace/conversations/7/messages')[1].body).toEqual({ content: 'Care e termenul de plată?' });
    second.send('done', { assistant_message: ANSWER });
    second.close();
    expect(await screen.findByText('30 de zile')).toBeTruthy();
  });

  it('names why the model is unavailable when the stream says so', async () => {
    const channel = sseChannel();
    const mock = boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => channel.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    await ask('Care e termenul de plată?');
    await waitFor(() => expect(mock.find('POST', '/api/workspace/conversations/7/messages')).toHaveLength(1));
    channel.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    channel.send('error', { error: 'model_unavailable', reason: 'no_local_model', message: 'no local model', assistant_message: null });
    channel.close();
    expect(await screen.findByText('Modelul AI nu este disponibil acum. Niciun model local nu este configurat sau pornit pe serverul hubului.')).toBeTruthy();
  });

  it('stops a streaming answer: the request is aborted and the stop is explained', async () => {
    const channel = sseChannel();
    boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': () => channel.response() });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    await ask('Care e termenul de plată?');
    channel.send('start', { user_message: QUESTION, assistant_message_id: 12 });
    channel.send('token', { t: 'Răspunsul începe' });
    fireEvent.click(await screen.findByRole('button', { name: 'Oprește' }));

    const log = screen.getByRole('list', { name: 'Mesajele conversației' });
    expect(await within(log).findByText('Ai oprit răspunsul')).toBeTruthy();
    await waitFor(() => expect(channel.cancelled).toBe(true));
    expect(screen.queryByText('Răspunsul începe')).toBeNull();
    expect(screen.getByRole('button', { name: 'Întreabă din nou' })).toBeTruthy();
  });

  it('puts the question back when the server refuses it before streaming (conversation busy)', async () => {
    boot('/workspace/assistant/7', { 'POST /api/workspace/conversations/7/messages': apiError(409, 'conversation_busy') });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    await ask('Încă o întrebare');
    expect(await screen.findByText('Asistentul încă răspunde în această conversație.')).toBeTruthy();
    expect((screen.getByLabelText('Întrebarea ta') as HTMLTextAreaElement).value).toBe('Încă o întrebare');
    expect(screen.queryByText('Caută în documente…')).toBeNull();
  });

  it('refreshes a rotated CSRF token and re-sends the question once', async () => {
    const channel = sseChannel();
    let attempts = 0;
    const mock = boot('/workspace/assistant/7', {
      'POST /api/workspace/conversations/7/messages': () => {
        attempts += 1;
        return attempts === 1 ? apiError(403, 'csrf_failed') : channel.response();
      },
    });
    await screen.findByRole('heading', { level: 2, name: 'Termene de plată' });
    const sessionReads = mock.find('GET', '/api/workspace/session').length;
    await ask('Care e termenul de plată?');
    await waitFor(() => expect(mock.find('POST', '/api/workspace/conversations/7/messages')).toHaveLength(2));
    expect(mock.find('GET', '/api/workspace/session').length).toBeGreaterThan(sessionReads);
    channel.send('done', { assistant_message: ANSWER });
    channel.close();
    expect(await screen.findByText('30 de zile')).toBeTruthy();
    expect(screen.queryByText(/refuzată din motive de securitate/)).toBeNull();
  });

  it('creates the conversation on the first question from a suggested prompt and gives it its URL', async () => {
    const channel = sseChannel();
    const mock = boot('/workspace/assistant', {
      'GET /api/workspace/conversations': { conversations: [] },
      'POST /api/workspace/conversations': json(201, { ...CONVERSATION, id: 9, title: 'Conversație nouă' }),
      'POST /api/workspace/conversations/9/messages': () => channel.response(),
    });
    expect(await screen.findByText('Nicio conversație încă')).toBeTruthy();
    const prompt = await screen.findByRole('button', { name: 'Care sunt cele mai importante proceduri pe care ar trebui să le cunoască un coleg nou?' });
    fireEvent.click(prompt);
    await waitFor(() => expect(mock.find('POST', '/api/workspace/conversations')[0]?.body).toEqual({ department_id: 1 }));
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/assistant/9'));
    await waitFor(() => expect(mock.find('POST', '/api/workspace/conversations/9/messages')).toHaveLength(1));
    channel.send('done', { assistant_message: ANSWER });
    channel.close();
    expect(await screen.findByText('30 de zile')).toBeTruthy();
    expect(mock.find('GET', '/api/workspace/conversations/9')).toHaveLength(0);
  });

  it('explains an unavailable model and REDACT guardrails before anyone asks', async () => {
    boot('/workspace/assistant', {
      'GET /api/workspace/model': { available: false, backend: null, model: null, route: null, locality: null, policy: 'local_only', reason: 'no_local_model', guardrails_mode: 'redact' },
    });
    expect(await screen.findByText('Modelul AI nu este disponibil acum: Niciun model local nu este configurat sau pornit pe serverul hubului.')).toBeTruthy();
  });

  it('says answers arrive in one piece when guardrails run in BLOCK mode', async () => {
    boot('/workspace/assistant', {
      'GET /api/workspace/model': { available: true, backend: 'lm-studio', model: 'qwen', route: 'local', locality: 'local', policy: 'local_only', reason: null, guardrails_mode: 'BLOCK' },
    });
    expect(await screen.findByText(/răspunsurile apar dintr-odată/)).toBeTruthy();
  });
});

describe('Assistant → conversations', () => {
  it('filters, renames and deletes (after confirmation) a conversation', async () => {
    const mock = boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations': { conversations: [{ ...CONVERSATION, message_count: 2 }, { ...CONVERSATION, id: 8, title: 'Concedii', message_count: 4 }] },
      'PATCH /api/workspace/conversations/8': { ...CONVERSATION, id: 8, title: 'Concedii 2026' },
      'DELETE /api/workspace/conversations/7': json(204),
    });
    const list = await screen.findByRole('navigation', { name: 'Conversații' });
    await within(list).findByRole('link', { name: /Concedii/ });
    fireEvent.change(within(list).getByLabelText('Caută în conversații'), { target: { value: 'conc' } });
    expect(within(list).queryByRole('link', { name: /Termene de plată/ })).toBeNull();
    fireEvent.change(within(list).getByLabelText('Caută în conversații'), { target: { value: '' } });

    fireEvent.click(within(list).getByRole('button', { name: 'Acțiuni pentru „Concedii”' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Redenumește' }));
    const rename = await screen.findByRole('dialog', { name: 'Redenumește conversația' });
    fireEvent.change(within(rename).getByLabelText('Titlu'), { target: { value: 'Concedii 2026' } });
    fireEvent.click(within(rename).getByRole('button', { name: 'Salvează' }));
    expect(await within(list).findByRole('link', { name: /Concedii 2026/ })).toBeTruthy();
    expect(mock.find('PATCH', '/api/workspace/conversations/8')[0].body).toEqual({ title: 'Concedii 2026' });

    fireEvent.click(within(list).getByRole('button', { name: 'Acțiuni pentru „Termene de plată”' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Șterge' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Ștergi conversația?' });
    expect(mock.find('DELETE', '/api/workspace/conversations/7')).toHaveLength(0);
    fireEvent.click(within(confirm).getByRole('button', { name: 'Șterge' }));
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/assistant'));
    expect(mock.find('DELETE', '/api/workspace/conversations/7')).toHaveLength(1);
    expect(within(list).queryByRole('link', { name: /Termene de plată/ })).toBeNull();
  });

  it('shows a clear page for a conversation that no longer exists', async () => {
    boot('/workspace/assistant/7', { 'GET /api/workspace/conversations/7': apiError(404, 'not_found') });
    expect(await screen.findByText('Conversația nu mai există')).toBeTruthy();
  });
});

describe('Assistant → answer actions', () => {
  const history = { conversation: CONVERSATION, messages: [QUESTION, ANSWER] };

  it('rates an answer, adds a note and copies it', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const mock = boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': history,
      'POST /api/workspace/messages/12/feedback': (call) => ({ message: { ...ANSWER, feedback: (call.body as { value: number }).value } }),
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Răspuns util' }));
    await waitFor(() => expect(mock.find('POST', '/api/workspace/messages/12/feedback')[0]?.body).toEqual({ value: 1 }));
    expect(screen.getByRole('button', { name: 'Răspuns util' }).getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: 'Adaugă o notă' }));
    const dialog = await screen.findByRole('dialog', { name: 'Spune-ne mai multe' });
    fireEvent.change(within(dialog).getByLabelText(/^Notă/), { target: { value: 'Exact ce căutam.' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Salvează' }));
    await waitFor(() => expect(mock.find('POST', '/api/workspace/messages/12/feedback')[1]?.body).toEqual({ value: 1, note: 'Exact ce căutam.' }));
    expect(await screen.findByText('Nota a fost salvată.')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Copiază răspunsul' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('Termenul este de **30 de zile** [1].'));
    Reflect.deleteProperty(navigator, 'clipboard');
  });

  it('keeps the excerpt of a source the reader may no longer open, says why, and offers no link to it', async () => {
    const gone: Citation = { ...CITATION, can_open: false };
    const kept: Citation = { n: 2, document_id: 6, title: 'Regulament intern', chunk_id: 32, page: null, excerpt: 'Regula comună.', can_open: true };
    const answer = { ...ANSWER, content: 'Termenul este de **30 de zile** [1], conform regulamentului [2].', citations: [gone, kept] };
    const mock = boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': { conversation: CONVERSATION, messages: [QUESTION, answer] },
      'POST /api/workspace/messages/12/feedback': (call) => ({ message: { ...answer, feedback: (call.body as { value: number }).value } }),
    });

    fireEvent.click(await screen.findByRole('button', { name: 'Sursa 1: Contract cadru.pdf' }));
    let drawer = await screen.findByRole('dialog', { name: 'Sursa [1]' });
    expect(within(drawer).getByText('Plata se face în 30 de zile de la factură.')).toBeTruthy();
    expect(within(drawer).getByText(/Documentul sursă nu îți mai este accesibil: a fost șters sau mutat între timp/)).toBeTruthy();
    expect(within(drawer).getByText(/asistentul l-a folosit în răspuns/)).toBeTruthy();
    expect(within(drawer).queryByText(/folosit în raport/)).toBeNull();
    expect(within(drawer).queryByRole('link', { name: 'Deschide documentul' })).toBeNull();
    expect(within(drawer).queryByRole('link', { name: 'Descarcă originalul' })).toBeNull();
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Închide' })[0]);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Sursa [1]' })).toBeNull());

    // The rating's answer replaces the message: the flags it carries still decide the links.
    fireEvent.click(screen.getByRole('button', { name: 'Răspuns util' }));
    await waitFor(() => expect(mock.find('POST', '/api/workspace/messages/12/feedback')).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Răspuns util' }).getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(screen.getByRole('button', { name: 'Sursa 1: Contract cadru.pdf' }));
    drawer = await screen.findByRole('dialog', { name: 'Sursa [1]' });
    expect(within(drawer).queryByRole('link', { name: 'Deschide documentul' })).toBeNull();
    fireEvent.click(within(drawer).getAllByRole('button', { name: 'Închide' })[0]);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Sursa [1]' })).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: 'Sursa 2: Regulament intern' }));
    drawer = await screen.findByRole('dialog', { name: 'Sursa [2]' });
    expect(within(drawer).queryByText(/nu îți mai este accesibil/)).toBeNull();
    expect(within(drawer).getByRole('link', { name: 'Deschide documentul' }).getAttribute('href')).toBe('/workspace/documents/6');
    expect(within(drawer).getByRole('link', { name: 'Descarcă originalul' }).getAttribute('href')).toBe('/api/workspace/documents/6/file');
  });

  it('requests an email approval with the answer and its sources prefilled', async () => {
    const mock = boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': history,
      'POST /api/workspace/approvals': json(201, { id: 31, kind: 'email.send', status: 'pending' }),
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Trimite pe email' }));
    const dialog = await screen.findByRole('dialog', { name: 'Trimite pe email' });
    expect(await within(dialog).findByText('1 persoană poate aproba această cerere.')).toBeTruthy();
    expect(mock.find('GET', '/api/workspace/approvals/eligible')[0].search).toBe('?kind=email.send&department_id=1');
    expect((within(dialog).getByLabelText(/^Subiect/) as HTMLInputElement).value).toBe('Răspuns Nerva: Care e termenul de plată?');

    fireEvent.click(within(dialog).getByRole('button', { name: 'Cere aprobarea' }));
    expect(await within(dialog).findByText('Introdu cel puțin o adresă de email.')).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Destinatari/), { target: { value: 'ion@client.ro; nu-e-adresa' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cere aprobarea' }));
    expect(await within(dialog).findByText('Adresa „nu-e-adresa” nu este validă.')).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Destinatari/), { target: { value: 'ion@client.ro, Ion@Client.ro, ana@client.ro' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cere aprobarea' }));

    expect(await screen.findByRole('dialog', { name: 'Cererea a fost trimisă' })).toBeTruthy();
    expect(mock.find('POST', '/api/workspace/approvals')[0].body).toEqual({
      kind: 'email.send',
      payload: {
        to: ['ion@client.ro', 'ana@client.ro'],
        subject: 'Răspuns Nerva: Care e termenul de plată?',
        body_markdown: 'Termenul este de **30 de zile** [1].\n\n**Surse**\n\n1. Contract cadru.pdf, pagina 2',
        source: { type: 'message', id: 12 },
      },
    });
    expect(screen.getByRole('link', { name: 'Vezi cererea' }).getAttribute('href')).toBe('/workspace/approvals/31');
  });

  it('links to the identical request already waiting instead of sending it twice', async () => {
    boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': history,
      'POST /api/workspace/approvals': apiError(409, 'already_requested', { approval_id: 30 }),
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Trimite pe email' }));
    const dialog = await screen.findByRole('dialog', { name: 'Trimite pe email' });
    await within(dialog).findByText('1 persoană poate aproba această cerere.');
    fireEvent.change(within(dialog).getByLabelText(/^Destinatari/), { target: { value: 'ion@client.ro' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cere aprobarea' }));
    expect(await within(dialog).findByText('O cerere identică așteaptă deja o decizie.')).toBeTruthy();
    expect(within(dialog).getByRole('link', { name: 'Vezi cererea' }).getAttribute('href')).toBe('/workspace/approvals/30');
  });

  it('brings a refused recipient into view and focus', async () => {
    boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': history,
      'POST /api/workspace/approvals': apiError(422, 'recipient_not_allowed', { recipients: ['ion@client.ro'], allowed_domains: ['acme.ro'] }),
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Trimite pe email' }));
    const dialog = await screen.findByRole('dialog', { name: 'Trimite pe email' });
    await within(dialog).findByText('1 persoană poate aproba această cerere.');
    const to = within(dialog).getByLabelText(/^Destinatari/);
    fireEvent.change(to, { target: { value: 'ion@client.ro' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cere aprobarea' }));
    expect(await within(dialog).findByText('Adresa destinatarului nu face parte dintr-un domeniu permis.')).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(to));
  });

  it('explains that nobody can approve, and offers nothing to send', async () => {
    const mock = boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': history,
      'GET /api/workspace/approvals/eligible': { count: 0, smtp_configured: true },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Trimite pe email' }));
    const dialog = await screen.findByRole('dialog', { name: 'Trimite pe email' });
    expect(await within(dialog).findByText('Nimeni nu poate aproba acum')).toBeTruthy();
    expect(within(dialog).getByText(/aprobator din departamentul General/)).toBeTruthy();
    expect((within(dialog).getByRole('button', { name: 'Cere aprobarea' }) as HTMLButtonElement).disabled).toBe(true);
    expect(mock.find('POST', '/api/workspace/approvals')).toHaveLength(0);
  });

  it('hides the email action when outgoing email is not configured', async () => {
    const mock = boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations/7': history,
      'GET /api/workspace/approvals/eligible': { count: 2, smtp_configured: false },
    });
    expect(await screen.findByRole('button', { name: 'Răspuns util' })).toBeTruthy();
    await waitFor(() => expect(mock.find('GET', '/api/workspace/approvals/eligible')).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Trimite pe email' })).toBeNull());
  });
});
