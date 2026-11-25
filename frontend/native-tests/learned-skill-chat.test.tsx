import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';

const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
const skill = { kind: 'skill', name: 'my-procedure', command: '/my-procedure',
  usage: '/my-procedure [instruction]', description: 'Owner procedure', tier: 'admin' };
const reply = (data: unknown) => ({ ok: true, status: 200, json: async () => data });

class ChatXHR {
  static latest: ChatXHR | null;
  static sent: ChatXHR[] = [];
  body: any;
  status = 200;
  readyState = 3;
  responseText = '';
  onreadystatechange?: () => void;
  constructor() { ChatXHR.latest = this; }
  open() {}
  setRequestHeader() {}
  abort() {}
  send(body: string) { this.body = JSON.parse(body); ChatXHR.sent.push(this); }
  end(session: string) {
    this.responseText += `data: ${JSON.stringify({ type: 'end', text: 'Done', session_id: session })}\n\n`;
    this.onreadystatechange?.();
  }
}

const mount = () => render(<ServerProvider><ChatScreen onGoToSettings={() => {}} /></ServerProvider>);
const draft = () => screen.getByPlaceholderText(/Message/) as HTMLTextAreaElement;
const chooseSkill = async () => {
  fireEvent.click(screen.getByText('Commands'));
  fireEvent.click(await screen.findByLabelText('Insert /my-procedure in message'));
};

beforeEach(() => {
  records.clear();
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'one', sessionId: 'saved',
    messages: [{ id: 'earlier', role: 'user', text: 'Earlier task' }] }));
  ChatXHR.latest = null;
  ChatXHR.sent = [];
  vi.stubGlobal('XMLHttpRequest', ChatXHR);
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/sessions/page?')) return reply({ sessions: [{ id: 'another', title: 'Another conversation' }], next_cursor: null });
    if (url.includes('/api/commands')) return reply({ ok: true, commands: [],
      shortcuts: url.includes('agent=frigga') || url.includes('agent=jarvis') ? [skill] : [] });
    return reply({ agents: [{ id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }] });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('preserves a picked skill and its instructions when inspecting another conversation', async () => {
  mount();
  await screen.findByText('Earlier task');
  fireEvent.change(draft(), { target: { value: 'Keep my instructions' } });
  await chooseSkill();
  fireEvent.click(screen.getByText('History'));
  fireEvent.click(await screen.findByText('Another conversation'));
  await screen.findByText('Send or remove the selected skill before switching conversations.');
  expect(draft().value).toBe('/my-procedure Keep my instructions');
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/sessions/resume'))).toBe(false);
});

it('discovers Frigga’s procedure, keeps the multiline task, and sends only on Send to the selected session', async () => {
  mount();
  await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByLabelText(/^Choose agent, current recipient jarvis$/i));
  fireEvent.click(await screen.findByText('Frigga'));
  fireEvent.change(draft(), { target: { value: 'Check reports\nKeep the original wording' } });
  await chooseSkill();
  expect(fetch).toHaveBeenCalledWith('https://hub.test/api/commands?agent=frigga', expect.anything());
  expect(draft().value).toBe('/my-procedure Check reports\nKeep the original wording');
  expect(ChatXHR.sent).toHaveLength(0);
  fireEvent.click(screen.getByText('Send'));
  expect(ChatXHR.sent).toHaveLength(1);
  expect(ChatXHR.latest?.body).toMatchObject({ message: '/my-procedure Check reports\nKeep the original wording',
    agent: 'frigga', session_id: 'saved' });
});

it('keeps a manually entered slash command and refuses a task that exceeds the skill limit', async () => {
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.change(draft(), { target: { value: '/status original' } });
  await chooseSkill();
  expect(draft().value).toBe('/status original');
  expect(screen.getByText(/draft already contains a slash command/i)).toBeTruthy();
  expect(screen.getByLabelText('Insert /my-procedure in message')).toBeTruthy();
  expect(ChatXHR.sent).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('Close commands'));
  fireEvent.change(draft(), { target: { value: 'x'.repeat(2001) } });
  await chooseSkill();
  expect(draft().value).toBe('x'.repeat(2001));
  expect(screen.getByText(/2,000 characters/)).toBeTruthy();
  expect(ChatXHR.sent).toHaveLength(0);
});

it('names the selected recipient in an empty conversation', async () => {
  records.delete('jarvis.chat.conversation.v2');
  mount();
  await screen.findByText('Say hello to Jarvis.');
  fireEvent.click(screen.getByLabelText(/^Choose agent, current recipient jarvis$/i));
  fireEvent.click(await screen.findByText('Frigga'));
  expect(screen.getByText('Say hello to @frigga.')).toBeTruthy();
});

it('strips only the picker prefix when the agent changes, even when both agents expose the same slug', async () => {
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByLabelText(/^Choose agent, current recipient jarvis$/i));
  fireEvent.click(await screen.findByText('Frigga'));
  fireEvent.change(draft(), { target: { value: 'Private task\nSecond line' } });
  await chooseSkill();
  fireEvent.change(draft(), { target: { value: '  /my-procedure Private task\nEdited line' } });
  fireEvent.click(screen.getByText('Frigga'));
  fireEvent.click(await screen.findByText('Jarvis'));
  await waitFor(() => expect(draft().value).toBe('  Private task\nEdited line'));
  fireEvent.click(screen.getByText('Send'));
  expect(ChatXHR.latest?.body).toMatchObject({ message: 'Private task\nEdited line', agent: 'jarvis', session_id: 'saved' });
});

it('strips the picker prefix after a session transition and keeps later edits bounded', async () => {
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.change(draft(), { target: { value: 'Task for this chat' } });
  await chooseSkill();
  fireEvent.click(screen.getByText('New'));
  expect(ChatXHR.latest?.body.message).toBe('/new');
  await act(async () => ChatXHR.latest!.end('new-session'));
  expect(draft().value).toBe('Task for this chat');
  await chooseSkill();
  fireEvent.change(draft(), { target: { value: `/my-procedure ${'a'.repeat(2001)}` } });
  expect(screen.getByLabelText('Skill draft too long')).toBeTruthy();
  expect((screen.getByText('Send').closest('button') as HTMLButtonElement).disabled).toBe(true);
  expect(ChatXHR.sent).toHaveLength(1);
});
