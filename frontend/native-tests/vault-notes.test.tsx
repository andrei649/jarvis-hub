import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';

const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
const original = [{ name: 'note.md', text: 'The full actual excerpt.' },
  { name: 'other.md', text: 'A second private excerpt.' }];
let server: ReturnType<typeof useServer>;
function Probe() { server = useServer(); return <ChatScreen onGoToSettings={() => {}} />; }
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);
const response = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
};
class ChatXHR {
  static instances: ChatXHR[] = [];
  status = 200; readyState = 3; responseText = ''; body: any;
  onreadystatechange?: () => void;
  constructor() { ChatXHR.instances.push(this); }
  open() {} setRequestHeader() {} abort() {}
  send(body: string) { this.body = JSON.parse(body); }
  end() {
    this.responseText += `data: ${JSON.stringify({ type: 'end', text: 'Answer', session_id: 'saved' })}\n\n`;
    this.onreadystatechange?.();
  }
}
let fetchMock: ReturnType<typeof vi.fn>;
let found = original;

beforeEach(() => {
  records.clear(); ChatXHR.instances = []; found = original;
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'one', sessionId: 'saved', messages: [] }));
  fetchMock = vi.fn(async (url: string) => response(url.includes('/api/os/brain/retrieve?')
    ? { ok: true, attachments: found } : url.includes('/sessions/page?')
      ? { sessions: [{ id: 'older', title: 'Older chat' }], next_cursor: null }
      : url.endsWith('/sessions/resume')
        ? { ok: true, session: 'older', turns: [{ role: 'user', content: 'Older question' }] }
        : { agents: [{ id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }] }));
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('XMLHttpRequest', ChatXHR);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function review(question = 'What does my vault say?') {
  const input = await screen.findByPlaceholderText('Message Jarvis…') as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: question } });
  fireEvent.click(screen.getByLabelText('Obsidian notes'));
  await screen.findByText('The full actual excerpt.');
  return input;
}
const selected = () => screen.getByLabelText('Select note note.md') as HTMLButtonElement;
const sendNotes = () => screen.getByLabelText('Send with notes') as HTMLButtonElement;

it('requires review, sends selected exact excerpts for one turn, and omits them from the next turn', async () => {
  mount(); const input = await review();
  expect(selected().textContent).toContain('☐');
  expect(sendNotes().disabled).toBe(true);
  expect(screen.getByText('A second private excerpt.')).toBeTruthy();
  fireEvent.click(selected());
  expect(selected().textContent).toContain('☑');
  fireEvent.click(screen.getByLabelText('Select note other.md'));
  expect(screen.getByText('2 selected')).toBeTruthy();
  fireEvent.click(sendNotes());
  await waitFor(() => expect(ChatXHR.instances).toHaveLength(1));
  expect(ChatXHR.instances[0].body).toMatchObject({ message: 'What does my vault say?', agent: 'jarvis',
    attachments: original });
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/os/brain/retrieve?'))).toHaveLength(2);
  await act(async () => ChatXHR.instances[0].end());
  fireEvent.change(input, { target: { value: 'Ordinary next question' } });
  fireEvent.click(screen.getByText('Send'));
  await waitFor(() => expect(ChatXHR.instances).toHaveLength(2));
  expect(ChatXHR.instances[1].body.message).toBe('Ordinary next question');
  expect(ChatXHR.instances[1].body).not.toHaveProperty('attachments');
});

it.each(['changed', 'removed'])('refuses a %s selected excerpt and requires a new selection', async variant => {
  mount(); const input = await review();
  fireEvent.click(selected());
  found = variant === 'changed' ? [{ name: 'note.md', text: 'Updated text' }] : [original[1]];
  fireEvent.click(sendNotes());
  await screen.findByText('A selected note changed or disappeared. Review the results again.');
  expect(ChatXHR.instances).toHaveLength(0);
  expect(input.value).toBe('What does my vault say?');
  expect(sendNotes().disabled).toBe(true);
});

it('refuses a refresh failure and clears selection', async () => {
  mount(); await review(); fireEvent.click(selected());
  fetchMock.mockRejectedValueOnce(new Error('offline'));
  fireEvent.click(sendNotes());
  await screen.findByText('The notes could not be checked. Review and select them again.');
  expect(sendNotes().disabled).toBe(true);
  expect(ChatXHR.instances).toHaveLength(0);
});

it('shows an empty result without enabling notes send', async () => {
  found = [];
  mount();
  const input = await screen.findByPlaceholderText('Message Jarvis…') as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: 'Is this in my notes?' } });
  fireEvent.click(screen.getByLabelText('Obsidian notes'));
  await screen.findByText('No matching notes. Try different words.');
  expect(sendNotes().disabled).toBe(true);
  expect(ChatXHR.instances).toHaveLength(0);
});

it('revokes a pending send when the hub identity changes during recheck', async () => {
  mount(); const input = await review(); fireEvent.click(selected());
  const pending = deferred<ReturnType<typeof response>>();
  fetchMock.mockImplementationOnce(() => pending.promise);
  fireEvent.click(sendNotes());
  await act(async () => server.updateConfig({ ...config, token: 'different-user' }));
  await act(async () => pending.resolve(response({ ok: true, attachments: original })));
  expect(ChatXHR.instances).toHaveLength(0);
  expect(input.value).toBe('What does my vault say?');
  expect(screen.queryByLabelText('Send with notes')).toBeNull();
});

it('revokes selection after an edit away and back to the same question', async () => {
  mount(); const input = await review(); fireEvent.click(selected());
  fireEvent.change(input, { target: { value: 'Different question' } });
  fireEvent.change(input, { target: { value: 'What does my vault say?' } });
  expect(screen.queryByLabelText('Send with notes')).toBeNull();
  expect(ChatXHR.instances).toHaveLength(0);
});

it.each(['close', 'agent', 'session'])('drops a late recheck after %s changes', async change => {
  mount(); const input = await review(); fireEvent.click(selected());
  const pending = deferred<ReturnType<typeof response>>();
  fetchMock.mockImplementationOnce(() => pending.promise);
  fireEvent.click(sendNotes());
  if (change === 'close') fireEvent.click(screen.getByLabelText('Close Obsidian notes'));
  if (change === 'agent') {
    fireEvent.click(screen.getByLabelText('Choose agent, current recipient Jarvis'));
    fireEvent.click(await screen.findByText('Frigga'));
  }
  if (change === 'session') {
    fireEvent.click(screen.getByText('History'));
    fireEvent.click(await screen.findByLabelText('Resume session older'));
  }
  await act(async () => pending.resolve(response({ ok: true, attachments: original })));
  expect(ChatXHR.instances).toHaveLength(0);
  expect(input.value).toBe('What does my vault say?');
  expect(screen.queryByLabelText('Send with notes')).toBeNull();
});
