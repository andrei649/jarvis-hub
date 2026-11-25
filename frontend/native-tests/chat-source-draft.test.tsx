import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { Conversation } from '../../mobile/src/chat/conversation';
import { ServerProvider } from '../../mobile/src/context/ServerContext';
import { records } from './support/storage';

const selection = { reference: { session_id: 'older', turn: 3, revision: 'a'.repeat(64),
  excerpt: 'The blue notebook.', allow_cloud: true }, role: 'assistant' as const };

vi.mock('../../mobile/src/components/SessionsModal', () => ({
  SessionsModal: ({ visible, onUseSource, onClose }: any) => visible
    ? <><button onClick={() => { if (onUseSource?.(selection)) onClose(); }}>Choose reviewed passage</button>
      <button onClick={onClose}>Cancel review</button></> : null,
}));

const draft = () => screen.getByPlaceholderText(/Message /) as HTMLTextAreaElement;
async function stage() {
  render(<ServerProvider><ChatScreen onGoToSettings={() => {}} /></ServerProvider>);
  await screen.findByText('Earlier task');
  fireEvent.change(draft(), { target: { value: 'My question' } });
  fireEvent.click(screen.getByText('History'));
  fireEvent.click(await screen.findByText('Choose reviewed passage'));
  await screen.findByText(selection.reference.excerpt);
}

beforeEach(() => {
  records.clear();
  const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'one', sessionId: 'destination',
    messages: [{ id: 'old', role: 'user', text: 'Earlier task' }] }));
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({
    agents: [{ id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }],
  }) })));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('requires a confirmed write before clearing the sourced draft and allows review after refusal', async () => {
  const send = vi.spyOn(Conversation.prototype, 'send').mockReturnValue(true);
  await stage();
  expect(send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Send'));
  expect(send.mock.calls[0].slice(0, 5)).toEqual(['My question', 'jarvis', undefined, undefined, selection]);
  expect(draft().value).toBe('My question');
  act(() => send.mock.calls[0][5]!(false));
  expect(screen.getByText(selection.reference.excerpt)).toBeTruthy();
  expect(draft().value).toBe('My question');
  fireEvent.click(screen.getByText('Review again'));
  fireEvent.click(await screen.findByText('Cancel review'));
  expect(screen.getByText(selection.reference.excerpt)).toBeTruthy();
  fireEvent.click(screen.getByText('Review again'));
  fireEvent.click(await screen.findByText('Choose reviewed passage'));
  fireEvent.click(screen.getByText('Send'));
  act(() => send.mock.calls[1][5]!(true));
  expect(draft().value).toBe('');
  expect(screen.queryByText(selection.reference.excerpt)).toBeNull();
});

it('drops the staged passage on a change of recipient and preserves the plain question', async () => {
  const send = vi.spyOn(Conversation.prototype, 'send').mockReturnValue(true);
  await stage();
  fireEvent.click(screen.getByLabelText(/^Choose agent, current recipient jarvis$/i));
  fireEvent.click(await screen.findByText('Frigga'));
  expect(draft().value).toBe('My question');
  expect(screen.queryByText(selection.reference.excerpt)).toBeNull();
  fireEvent.click(screen.getByText('Send'));
  expect(send.mock.calls[0]).toEqual(['My question', 'frigga', undefined]);
});

it('clears the confirmed first question when the hub assigns a new conversation ID', async () => {
  const key = 'jarvis.chat.conversation.v2';
  records.set(key, JSON.stringify({ ...JSON.parse(records.get(key)!), sessionId: null }));
  const send = vi.spyOn(Conversation.prototype, 'send').mockReturnValue(true);
  await stage();
  fireEvent.click(screen.getByText('Send'));
  act(() => send.mock.contexts[0].resume('new-destination', []));
  act(() => send.mock.calls[0][5]!(true));
  expect(draft().value).toBe('');
});
