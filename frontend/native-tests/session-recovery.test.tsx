import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records, storage } from './support/storage';

const SERVER_KEY = 'jarvis.server.config.v1';
const CHAT_KEY = 'jarvis.chat.conversation.v2';
const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
let server: ReturnType<typeof useServer>;
function Probe() { server = useServer(); return <ChatScreen onGoToSettings={() => {}} />; }
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);

class ChatXHR {
  static latest: ChatXHR;
  status = 200;
  readyState = 3;
  responseText = '';
  body: any;
  aborted = false;
  headers: Record<string, string> = {};
  onreadystatechange?: () => void;
  constructor() { ChatXHR.latest = this; }
  open() {}
  setRequestHeader(key: string, value: string) { this.headers[key] = value; }
  send(body: string) { this.body = JSON.parse(body); }
  abort() { this.aborted = true; }
  emit(event: object) {
    this.responseText += `data: ${JSON.stringify(event)}\n\n`;
    this.onreadystatechange?.();
  }
  fail(status: number, body = '') {
    this.status = status;
    this.readyState = 4;
    this.responseText = body;
    this.onreadystatechange?.();
  }
}

const seedChat = (scope = 'connection-one') => records.set(CHAT_KEY, JSON.stringify({
  version: 2, scope, sessionId: 'saved-session', messages: [{ id: 'previous', role: 'user', text: 'Saved topic' }],
}));
const send = (text: string) => {
  fireEvent.change(screen.getByPlaceholderText('Message Jarvis…'), { target: { value: text } });
  fireEvent.click(screen.getByText('Send'));
  return ChatXHR.latest;
};

beforeEach(() => {
  records.clear();
  records.set(SERVER_KEY, JSON.stringify({ version: 2, config, appearance: null, chatScope: 'connection-one' }));
  vi.stubGlobal('XMLHttpRequest', ChatXHR);
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () =>
    (url.endsWith('/sessions') || url.includes('/sessions/page?')) ? { sessions: [{ id: 'chosen', title: 'Earlier topic' }], next_cursor: null } :
      url.endsWith('/sessions/resume') ? { ok: true, session: 'chosen', turns: [{ role: 'user', content: 'Resumed question' }] } :
        { agents: [] },
  })));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('rehydrates the mounted screen and continues the same ID after an app restart', async () => {
  seedChat();
  const first = mount();
  await screen.findByText('Saved topic');
  const xhr = send('Continue here');
  expect(xhr.body.session_id).toBe('saved-session');
  await act(async () => xhr.emit({ type: 'end', text: 'Answer', session_id: 'saved-session' }));
  await waitFor(() => expect(JSON.parse(records.get(CHAT_KEY)!).messages.at(-1).text).toBe('Answer'));
  first.unmount();
  mount();
  await screen.findByText('Answer');
  expect(send('Continue after restart').body.session_id).toBe('saved-session');
});

it('New keeps the old transcript until the server acknowledges a distinct session', async () => {
  seedChat(); mount();
  await screen.findByText('Saved topic');
  fireEvent.click(screen.getByText('New'));
  const xhr = ChatXHR.latest;
  expect(xhr.body).toMatchObject({ message: '/new', session_id: 'saved-session' });
  expect(screen.queryByText('Saved topic')).not.toBeNull();
  await act(async () => xhr.emit({ type: 'end', text: 'New conversation created', session_id: 'fresh-session',
    session_transition: { command: 'new', session_id: 'fresh-session' } }));
  expect(screen.queryByText('Saved topic')).toBeNull();
  expect(send('First question').body.session_id).toBe('fresh-session');
});

it('a token change clears the rendered thread, aborts streaming and ignores late completion', async () => {
  seedChat(); mount();
  await screen.findByText('Saved topic');
  const old = send('Old owner question');
  await act(async () => server.updateConfig({ ...config, token: 'different-user' }));
  expect(old.aborted).toBe(true);
  expect(screen.queryByText('Saved topic')).toBeNull();
  await act(async () => old.emit({ type: 'end', text: 'Private late answer', session_id: 'old-owner' }));
  expect(screen.queryByText('Private late answer')).toBeNull();
  await screen.findByPlaceholderText('Message Jarvis…');
  expect(send('Different owner').body.session_id).toBeUndefined();
});

it('does not overwrite cached history while its initial read is delayed', async () => {
  seedChat();
  const original = storage.getItem;
  let release!: (value: string | null) => void;
  vi.spyOn(storage, 'getItem').mockImplementation(key => key === CHAT_KEY
    ? new Promise(resolve => { release = resolve; }) : original(key));
  mount();
  await screen.findByPlaceholderText('Restoring conversation…');
  expect((screen.getByText('Send').closest('button') as HTMLButtonElement).disabled).toBe(true);
  await waitFor(() => expect(release).toBeDefined());
  const cached = records.get(CHAT_KEY)!;
  await act(async () => release(cached));
  await screen.findByText('Saved topic');
  expect(JSON.parse(records.get(CHAT_KEY)!).sessionId).toBe('saved-session');
});

it('History selects the server transcript and the next typed message uses that session', async () => {
  mount();
  await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('History'));
  await screen.findByText('Earlier topic');
  fireEvent.click(screen.getByText('Earlier topic'));
  await screen.findByText('Resumed question');
  expect(send('Continue the chosen topic').body.session_id).toBe('chosen');
});

it('a pending History resume cannot install its transcript after changing hubs', async () => {
  let release!: (value: unknown) => void;
  vi.mocked(fetch).mockImplementation(async url => ({ ok: true, status: 200, json: async () =>
    (String(url).endsWith('/sessions') || String(url).includes('/sessions/page?')) ? { sessions: [{ id: 'chosen', title: 'Earlier topic' }], next_cursor: null } :
      String(url).endsWith('/sessions/resume') ? new Promise(resolve => { release = resolve; }) : { agents: [] },
  }) as Response);
  mount();
  await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('History'));
  await screen.findByText('Earlier topic');
  fireEvent.click(screen.getByText('Earlier topic'));
  await waitFor(() => expect(release).toBeDefined());
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://different-hub.test' }));
  await act(async () => release({ ok: true, session: 'chosen', turns: [{ role: 'user', content: 'Old hub private topic' }] }));
  expect(screen.queryByText('Old hub private topic')).toBeNull();
  await screen.findByPlaceholderText('Message Jarvis…');
  expect(send('New hub question').body.session_id).toBeUndefined();
});

it('recovers an exact missing session explicitly and appends the saved prompt without sending it', async () => {
  seedChat(); mount();
  await screen.findByText('Saved topic');

  const failed = send('Keep this question');
  expect(failed.body.session_id).toBe('saved-session');
  await act(async () => failed.fail(404, JSON.stringify({ error: 'session_not_found' })));

  await screen.findByText('This chat session is unavailable.');
  expect(screen.getAllByText('Keep this question')).toHaveLength(2);
  expect((screen.getByText('Send').closest('button') as HTMLButtonElement).disabled).toBe(true);

  fireEvent.click(screen.getByLabelText('Start new chat'));
  const recovery = ChatXHR.latest;
  expect(recovery).not.toBe(failed);
  expect(recovery.body.message).toBe('/new');
  expect(recovery.body).not.toHaveProperty('session_id');
  expect(screen.queryByText('Saved topic')).not.toBeNull();
  await act(async () => recovery.emit({ type: 'end', text: 'New conversation created', session_id: 'fresh-session',
    session_transition: { command: 'new', session_id: 'fresh-session' } }));

  await screen.findByText('Your unsent message is saved.');
  await screen.findByText('Keep this question');
  expect(screen.queryByText('Saved topic')).toBeNull();
  const composer = screen.getByPlaceholderText('Message Jarvis…');
  fireEvent.change(composer, { target: { value: 'Newer draft' } });
  const latestBeforeAdd = ChatXHR.latest;
  fireEvent.click(screen.getByLabelText('Add unsent message to draft'));
  expect((composer as HTMLTextAreaElement).value).toBe('Newer draft\nKeep this question');
  expect(ChatXHR.latest).toBe(latestBeforeAdd);
  expect(screen.queryByLabelText('Unsent message recovery')).toBeNull();

  fireEvent.click(screen.getByText('Send'));
  expect(ChatXHR.latest.body).toMatchObject({ message: 'Newer draft\nKeep this question', session_id: 'fresh-session' });
});

it('keeps the recovery card and saved prompt when starting a new chat fails', async () => {
  seedChat(); mount();
  await screen.findByText('Saved topic');
  const failed = send('Please preserve me');
  await act(async () => failed.fail(404, JSON.stringify({ error: 'session_not_found' })));
  await screen.findByLabelText('Start new chat');

  fireEvent.click(screen.getByLabelText('Start new chat'));
  const recovery = ChatXHR.latest;
  await act(async () => recovery.fail(503, JSON.stringify({ error: 'temporarily_unavailable' })));

  await screen.findByLabelText('Start new chat');
  expect(screen.getAllByText('Please preserve me')).toHaveLength(2);
  expect((screen.getByText('Send').closest('button') as HTMLButtonElement).disabled).toBe(true);
  expect(recovery.body).not.toHaveProperty('session_id');
});

it('does not treat a distinct default session ID as proof that /new was accepted', async () => {
  seedChat(); mount();
  await screen.findByText('Saved topic');
  const failed = send('Keep pending without proof');
  await act(async () => failed.fail(404, JSON.stringify({ error: 'session_not_found' })));
  await screen.findByLabelText('Start new chat');

  fireEvent.click(screen.getByLabelText('Start new chat'));
  const recovery = ChatXHR.latest;
  await act(async () => recovery.emit({ type: 'end', text: 'New conversation refused', session_id: 'existing-default' }));

  await screen.findByLabelText('Start new chat');
  expect(screen.getAllByText('Keep pending without proof')).toHaveLength(2);
  expect((screen.getByText('Send').closest('button') as HTMLButtonElement).disabled).toBe(true);
  const composer = screen.getByPlaceholderText('Message Jarvis…');
  fireEvent.change(composer, { target: { value: 'Must remain unsent' } });
  fireEvent.click(screen.getByText('Send'));
  expect(ChatXHR.latest).toBe(recovery);
  expect((composer as HTMLTextAreaElement).value).toBe('Must remain unsent');
});

it.each([
  ['unrelated 404', 404, { error: 'route_not_found' }],
  ['temporary refusal', 503, { error: 'temporarily_unavailable' }],
])('does not offer deleted-session recovery for %s', async (_label, status, body) => {
  seedChat(); mount();
  await screen.findByText('Saved topic');
  const request = send('Do not classify this as deletion');
  await act(async () => request.fail(status, JSON.stringify(body)));

  expect(screen.queryByLabelText('Unsent message recovery')).toBeNull();
  expect(screen.queryByLabelText('Start new chat')).toBeNull();
});

it('keeps the Start new chat action after the user moves the saved prompt to the composer', async () => {
  seedChat(); mount();
  await screen.findByText('Saved topic');
  const failed = send('Keep this question available');
  await act(async () => failed.fail(404, JSON.stringify({ error: 'session_not_found' })));
  await screen.findByLabelText('Start new chat');

  fireEvent.click(screen.getByLabelText('Add unsent message to draft'));
  expect((screen.getByPlaceholderText('Message Jarvis…') as HTMLTextAreaElement).value)
    .toBe('Keep this question available');
  expect(screen.getByLabelText('Start new chat')).not.toBeNull();
  expect((screen.getByText('Send').closest('button') as HTMLButtonElement).disabled).toBe(true);

  expect(screen.getByLabelText('Start new chat')).not.toBeNull();
  fireEvent.click(screen.getByLabelText('Start new chat'));
  expect(ChatXHR.latest.body).toMatchObject({ message: '/new' });
  expect(ChatXHR.latest.body).not.toHaveProperty('session_id');
});

it('keeps the Start new chat action after the user dismisses the saved prompt', async () => {
  seedChat(); mount();
  await screen.findByText('Saved topic');
  const failed = send('Discard this saved prompt');
  await act(async () => failed.fail(404, JSON.stringify({ error: 'session_not_found' })));
  await screen.findByLabelText('Start new chat');

  fireEvent.click(screen.getByLabelText('Dismiss saved message'));
  expect(screen.queryByLabelText('Add unsent message to draft')).toBeNull();
  expect(screen.getByLabelText('Start new chat')).not.toBeNull();
  fireEvent.click(screen.getByLabelText('Start new chat'));
  expect(ChatXHR.latest.body).toMatchObject({ message: '/new' });
  expect(ChatXHR.latest.body).not.toHaveProperty('session_id');
});

it('clears missing-session authority after History selection but keeps the unsent prompt as an explicit draft option', async () => {
  seedChat(); mount();
  await screen.findByText('Saved topic');
  const failed = send('Old-topic question');
  await act(async () => failed.fail(404, JSON.stringify({ error: 'session_not_found' })));
  await screen.findByText('This chat session is unavailable.');

  fireEvent.click(screen.getByText('History'));
  await screen.findByText('Earlier topic');
  fireEvent.click(screen.getByText('Earlier topic'));
  await screen.findByText('Resumed question');
  await screen.findByText('Your unsent message is saved.');
  expect(screen.queryByLabelText('Start new chat')).toBeNull();
  const previousRequest = ChatXHR.latest;
  send('Continue chosen history');
  expect(ChatXHR.latest).toBe(previousRequest);
  expect((screen.getByPlaceholderText('Message Jarvis…') as HTMLTextAreaElement).value).toBe('Continue chosen history');
  fireEvent.click(screen.getByLabelText('Dismiss saved message'));
  fireEvent.click(screen.getByText('Send'));
  expect(ChatXHR.latest.body.session_id).toBe('chosen');
});
