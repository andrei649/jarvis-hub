import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';
import { picker } from './support/picker';

const voice = vi.hoisted(() => ({ props: null as any }));
vi.mock('../../mobile/src/components/PushToTalk', () => ({
  PushToTalk: (props: any) => { voice.props = props; return <button disabled={props.disabled}>Dictation control</button>; },
}));
vi.mock('../../mobile/src/components/VoiceOrb', () => ({ VoiceOrb: () => <div>Voice orb</div> }));
vi.mock('../../mobile/src/screens/BriefingWall', () => ({
  BriefingWall: (props: any) => <div><span>Briefing view</span><button onClick={props.onExit}>Review draft</button>{props.children}</div>,
}));
const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB';
const review = { configured: true, reachable: null, review_token: 'r'.repeat(24), session_id: 'selected',
  destination: 'http://127.0.0.1:11434', model: 'llava', backend: 'ollama', local: true, active_image_count: 0 };
const command = { name: 'status', command: '/status', description: 'Show status', usage: '/status', tier: 'user' };
const reply = (data: unknown) => ({ ok: true, status: 200, headers: { get: () => null },
  json: async () => data, text: async () => JSON.stringify(data) });
class ChatXHR { static sent: string[] = []; open() {} setRequestHeader() {} abort() {}
  send(body: string) { ChatXHR.sent.push(body); }
}
const mount = () => render(<ServerProvider><ChatScreen onGoToSettings={() => {}} /></ServerProvider>);
beforeEach(() => {
  records.clear(); ChatXHR.sent = []; voice.props = null;
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'scope' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'scope', sessionId: 'selected',
    messages: [{ id: 'old', role: 'user', text: 'Earlier' }] }));
  picker.launchImageLibraryAsync = vi.fn(async () => ({ canceled: false,
    assets: [{ type: 'image', base64: png, width: 1, height: 1 }] }));
  vi.stubGlobal('XMLHttpRequest', ChatXHR);
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).includes('/active-images')
    ? reply({ session_id: 'selected', images: [] }) : String(url).endsWith('/selected-prepare') ? reply(review)
      : String(url).endsWith('/api/commands') ? reply({ ok: true, commands: [command] }) : reply({ agents: [] })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('cancels the old microphone context for Commands and never overwrites a command with late STT', async () => {
  mount(); const input = await screen.findByPlaceholderText('Message Jarvis…');
  const old = voice.props;
  await act(async () => { old.onStart(); old.onState({ status: 'listening', level: 0.5 }); });
  fireEvent.click(screen.getByLabelText('Browse chat commands'));
  expect(voice.props.disabled).toBe(true);
  expect(voice.props.contextKey).not.toBe(old.contextKey);
  await act(async () => old.onTranscript('Late mic text'));
  fireEvent.click(await screen.findByLabelText('Insert /status in message'));
  await act(async () => old.onTranscript('Even later mic text'));
  expect((input as HTMLTextAreaElement).value).toBe('/status');
  expect(ChatXHR.sent).toHaveLength(0);
  expect(voice.props.disabled).toBe(false);
});

it('cancels old dictation for Images, including a callback after the image panel closes', async () => {
  mount(); const input = await screen.findByPlaceholderText('Message Jarvis…');
  const old = voice.props;
  await act(async () => { old.onStart(); old.onState({ status: 'listening', level: 0.5 }); });
  fireEvent.click(screen.getByLabelText('Selected images'));
  expect(voice.props.disabled).toBe(true);
  expect(voice.props.contextKey).not.toBe(old.contextKey);
  await act(async () => old.onTranscript('Stale during image selection'));
  fireEvent.click(screen.getByLabelText('Close selected images'));
  await act(async () => old.onTranscript('Stale after image selection'));
  expect((input as HTMLTextAreaElement).value).toBe('');
  expect(ChatXHR.sent).toHaveLength(0);
  expect(voice.props.disabled).toBe(false);
});

it('invalidates a reviewed image selection when switching to Commands or Briefing', async () => {
  mount(); await screen.findByText('Earlier');
  fireEvent.click(screen.getByLabelText('Selected images'));
  await screen.findByText(/Current session selected/);
  fireEvent.click(screen.getByLabelText('Add selected image'));
  await screen.findByText(/image\/png/);
  fireEvent.change(screen.getByLabelText('Image question'), { target: { value: 'What is this?' } });
  fireEvent.click(screen.getByLabelText('Review selected Ollama destination'));
  await screen.findByText(/Model: llava/);
  fireEvent.click(screen.getByLabelText('Browse chat commands'));
  expect(screen.queryByText(/Model: llava/)).toBeNull();
  fireEvent.click(screen.getByLabelText('Close commands'));
  fireEvent.click(screen.getByLabelText('Selected images'));
  expect(screen.queryByText(/Model: llava/)).toBeNull();
  fireEvent.click(screen.getByText('Briefing'));
  expect(screen.queryByLabelText('Selected images')).toBeNull();
  fireEvent.click(screen.getByText('Review draft'));
  expect(screen.queryByText(/Model: llava/)).toBeNull();
  expect(ChatXHR.sent).toHaveLength(0);
  await waitFor(() => expect(voice.props.disabled).toBe(false));
});

it('uses the one Conversation turn gate for a selected image send and leaves abort delivery unknown', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).includes('/active-images')
    ? reply({ session_id: 'selected', images: [] }) : String(url).endsWith('/selected-prepare') ? reply(review)
      : String(url).endsWith('/selected-chat') ? new Promise(() => {}) : reply({ agents: [] })));
  mount(); await screen.findByText('Earlier');
  fireEvent.click(screen.getByLabelText('Selected images'));
  await screen.findByText(/Current session selected/);
  await waitFor(() => expect((screen.getByLabelText('Add selected image') as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByLabelText('Add selected image'));
  await screen.findByText(/image\/png/);
  fireEvent.change(screen.getByLabelText('Image question'), { target: { value: 'Inspect this' } });
  fireEvent.click(screen.getByLabelText('Review selected Ollama destination'));
  await screen.findByText(/Model: llava/);
  fireEvent.change(screen.getByPlaceholderText('Message Jarvis…'), { target: { value: 'Unsent text' } });
  fireEvent.click(screen.getByLabelText('Submit reviewed selected images'));
  await screen.findByText(/Sending reviewed images/);
  expect(screen.getByText('Stop')).toBeTruthy();
  expect(screen.queryByText('Send')).toBeNull();
  expect(ChatXHR.sent).toHaveLength(0);
  fireEvent.click(screen.getByText('Stop'));
  await screen.findByText(/Outcome unknown\. Inspect History before trying again/);
  expect(ChatXHR.sent).toHaveLength(0);
});
