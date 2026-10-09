import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';

const voice = vi.hoisted(() => ({ props: null as any, speak: vi.fn(), stop: vi.fn(), idle: vi.fn() }));
vi.mock('../../mobile/src/components/PushToTalk', () => ({
  PushToTalk: (props: any) => { voice.props = props; return <button disabled={props.disabled}>Dictation control</button>; },
}));
vi.mock('../../mobile/src/voice/pushToTalk', () => ({ waitForMicrophoneIdle: voice.idle }));
vi.mock('../../mobile/src/audio/tts', () => {
  const state = { status: 'off' };
  return { getSpeechState: () => state, subscribeSpeech: () => () => {}, speak: voice.speak, stopSpeaking: voice.stop };
});
vi.mock('../../mobile/src/components/VoiceOrb', () => ({
  VoiceOrb: ({ status, level }: any) => <div data-testid="dictation-orb" data-status={status} data-level={level} />,
}));
const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
let server: ReturnType<typeof useServer>;
function Probe() { server = useServer(); return <ChatScreen onGoToSettings={() => {}} />; }
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);
class ChatXHR {
  static latest: ChatXHR | null;
  status = 200; readyState = 3; responseText = ''; body: any;
  onreadystatechange?: () => void;
  constructor() { ChatXHR.latest = this; }
  open() {} setRequestHeader() {} abort() {}
  send(body: string) { this.body = JSON.parse(body); }
  end(session: string) {
    this.responseText += `data: ${JSON.stringify({ type: 'end', text: 'Reply', session_id: session })}\n\n`;
    this.onreadystatechange?.();
  }
}
beforeEach(() => {
  records.clear();
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'one', sessionId: 'saved',
    messages: [{ id: 'answer', role: 'assistant', text: 'Saved reply' }] }));
  voice.props = null; voice.speak.mockReset().mockResolvedValue(undefined); voice.stop.mockReset();
  voice.idle.mockReset().mockResolvedValue(undefined); ChatXHR.latest = null;
  vi.stubGlobal('XMLHttpRequest', ChatXHR);
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () =>
    url.endsWith('/sessions') ? { sessions: [] } : { agents: [{ id: 'frigga', name: 'Frigga' }] },
  })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('appends a transcript to the latest typed draft without sending a chat turn', async () => {
  mount(); const input = await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.change(input, { target: { value: 'Already typed' } });
  expect(voice.props).not.toBeNull();
  await act(async () => { voice.props.onStart(); voice.props.onState({ status: 'transcribing' }); });
  fireEvent.change(input, { target: { value: 'Edited while waiting' } });
  await act(async () => { voice.props.onState({ status: 'idle' }); voice.props.onTranscript('Spoken words'); });
  expect((input as HTMLInputElement).value).toBe('Edited while waiting\nSpoken words');
  expect(ChatXHR.latest).toBeNull();
  fireEvent.click(screen.getByText('Send'));
  expect(ChatXHR.latest?.body).toMatchObject({ message: 'Edited while waiting\nSpoken words', session_id: 'saved' });
  expect((screen.getByText('Dictation control') as HTMLButtonElement).disabled).toBe(true);
});

it('uses measured listening only and blocks speech while dictation is active', async () => {
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  expect(voice.props).not.toBeNull();
  await act(async () => { voice.props.onStart(); voice.props.onState({ status: 'listening', level: 0.25 }); });
  expect(screen.getByTestId('dictation-orb').getAttribute('data-status')).toBe('listening');
  expect(screen.getByTestId('dictation-orb').getAttribute('data-level')).toBe('0.25');
  expect(screen.queryByLabelText('Speak message')).toBeNull();
  await act(async () => voice.props.onState({ status: 'transcribing' }));
  expect(screen.getByTestId('dictation-orb').hasAttribute('data-level')).toBe(false);
  await act(async () => voice.props.onState({ status: 'idle' }));
  expect(screen.getByLabelText('Speak message')).toBeTruthy();
});

it('ignores old hub, session and agent callbacks and disables capture while history is open', async () => {
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  expect(voice.props).not.toBeNull();
  let old = voice.props;
  fireEvent.click(screen.getByText('History'));
  expect(voice.props.disabled).toBe(true);
  await act(async () => old.onTranscript('History late result'));
  expect((screen.getByPlaceholderText('Message Jarvis…') as HTMLInputElement).value).toBe('');
  fireEvent.click(screen.getByText('Resume session').closest('button')!.parentElement!);
  fireEvent.click(screen.getByText('New'));
  await act(async () => ChatXHR.latest!.end('fresh'));
  expect(voice.props.contextKey).not.toBe(old.contextKey);
  await act(async () => old.onTranscript('Old session result'));
  old = voice.props;
  fireEvent.click(screen.getByText('jarvis'));
  fireEvent.click(await screen.findByText('Frigga'));
  expect(voice.props.contextKey).not.toBe(old.contextKey);
  await act(async () => old.onTranscript('Old agent result'));
  old = voice.props;
  await act(async () => server.updateConfig({ ...config, token: 'different' }));
  await act(async () => { old.onTranscript('Old hub result'); old.onState({ status: 'listening', level: 1 }); });
  expect((await screen.findByPlaceholderText('Message Jarvis…') as HTMLInputElement).value).toBe('');
  expect(screen.getByTestId('dictation-orb').getAttribute('data-status')).not.toBe('listening');
});

it('waits for confirmed microphone cleanup before speaking and drops a cancelled playback request', async () => {
  let release!: () => void;
  voice.idle.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve; }));
  mount(); fireEvent.click(await screen.findByLabelText('Speak message'));
  await waitFor(() => expect(release).toBeDefined());
  expect(voice.speak).not.toHaveBeenCalled();
  expect(voice.props.disabled).toBe(true);
  fireEvent.click(screen.getByLabelText('Stop speaking'));
  await act(async () => release());
  expect(voice.speak).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText('Speak message'));
  await waitFor(() => expect(voice.speak).toHaveBeenCalledOnce());
});

it('changing agent cancels queued or playing speech and releases the dictation control', async () => {
  let release!: () => void;
  voice.idle.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve; }));
  mount(); fireEvent.click(await screen.findByLabelText('Speak message'));
  await waitFor(() => expect(release).toBeDefined());
  fireEvent.click(screen.getByText('jarvis'));
  fireEvent.click(await screen.findByText('Frigga'));
  await act(async () => release());
  expect(voice.speak).not.toHaveBeenCalled();
  expect(voice.props.disabled).toBe(false);
  expect(screen.queryByLabelText('Stop speaking')).toBeNull();
});

it('saving the same connection resets active dictation without accepting an old callback', async () => {
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  const old = voice.props;
  await act(async () => { old.onStart(); old.onState({ status: 'listening', level: 0.5 }); });
  await act(async () => server.updateConfig(config));
  expect(voice.props.contextKey).not.toBe(old.contextKey);
  await act(async () => old.onTranscript('stale result'));
  expect((screen.getByPlaceholderText('Message Jarvis…') as HTMLTextAreaElement).value).toBe('');
  expect(screen.getByTestId('dictation-orb').getAttribute('data-status')).not.toBe('listening');
  expect(screen.getByLabelText('Speak message')).toBeTruthy();
});
