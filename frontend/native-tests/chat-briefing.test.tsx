import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';

const wall = vi.hoisted(() => ({ props: null as any, mic: null as any }));
vi.mock('../../mobile/src/screens/BriefingWall', () => ({
  BriefingWall: (props: any) => { wall.props = props; return <div>
    <span>Briefing view</span><button onClick={props.onExit}>Review draft</button>{props.children}
  </div>; },
}));
vi.mock('../../mobile/src/components/PushToTalk', () => ({
  PushToTalk: (props: any) => { wall.mic = props; return <button disabled={props.disabled}>Dictation control</button>; },
}));
const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
let server: ReturnType<typeof useServer>;
function Probe() { server = useServer(); return <ChatScreen onGoToSettings={() => {}} />; }
beforeEach(() => {
  records.clear(); wall.props = wall.mic = null;
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'room-one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'room-one', sessionId: 'chosen',
    messages: [{ id: 'reply', role: 'assistant', text: 'Private conversation history' }] }));
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ agents: [] }) })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('switches microphone context and hides the conversation while the briefing view is open', async () => {
  render(<ServerProvider><Probe /></ServerProvider>);
  await screen.findByText('Private conversation history');
  const old = wall.mic;
  fireEvent.click(screen.getByText('Briefing'));
  expect(screen.getByText('Briefing view')).toBeTruthy();
  expect(screen.queryByText('Private conversation history')).toBeNull();
  expect(wall.mic.contextKey).not.toBe(old.contextKey);
  await act(async () => old.onTranscript('late old-context transcript'));
  expect(wall.props.transcript).toBeNull();
  fireEvent.click(screen.getByText('Review draft'));
  expect((screen.getByPlaceholderText('Message Jarvis…') as HTMLTextAreaElement).value).toBe('');
});

it('keeps dictated text as a draft and clears the room transcript on the next visit', async () => {
  render(<ServerProvider><Probe /></ServerProvider>);
  const input = await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.change(input, { target: { value: 'Typed first' } });
  fireEvent.click(screen.getByText('Briefing'));
  await act(async () => wall.mic.onTranscript('A private spoken line'));
  expect(wall.props.transcript).toBe('A private spoken line');
  expect(screen.queryByText('Send')).toBeNull();
  fireEvent.click(screen.getByText('Review draft'));
  expect((screen.getByPlaceholderText('Message Jarvis…') as HTMLTextAreaElement).value).toBe('Typed first\nA private spoken line');
  fireEvent.click(screen.getByText('Briefing'));
  expect(wall.props.transcript).toBeNull();
});

it('closes the room on a connection save and rejects old room results', async () => {
  render(<ServerProvider><Probe /></ServerProvider>);
  await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('Briefing'));
  const old = wall.mic;
  await act(async () => server.updateConfig({ ...config, token: 'new-principal' }));
  expect(screen.queryByText('Briefing view')).toBeNull();
  await act(async () => old.onTranscript('Old private text'));
  expect((await screen.findByPlaceholderText('Message Jarvis…') as HTMLTextAreaElement).value).toBe('');
});
