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
    url.endsWith('/sessions') ? { sessions: [{ id: 'chosen', title: 'Earlier topic' }] } :
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
  await act(async () => xhr.emit({ type: 'end', text: 'New conversation created', session_id: 'fresh-session' }));
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
    String(url).endsWith('/sessions') ? { sessions: [{ id: 'chosen', title: 'Earlier topic' }] } :
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
