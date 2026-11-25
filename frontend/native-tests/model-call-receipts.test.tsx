import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';

vi.mock('../../mobile/src/components/PushToTalk', () => ({ PushToTalk: () => <div /> }));
vi.mock('../../mobile/src/components/VoiceOrb', () => ({ VoiceOrb: () => <div /> }));
const speech = vi.hoisted(() => ({ state: { status: 'off' } }));
vi.mock('../../mobile/src/audio/tts', () => ({
  getSpeechState: () => speech.state, subscribeSpeech: () => () => {},
  speak: vi.fn(), stopSpeaking: vi.fn(),
}));

class ChatXHR {
  static latest: ChatXHR;
  status = 200;
  readyState = 3;
  responseText = '';
  onreadystatechange?: () => void;
  constructor() { ChatXHR.latest = this; }
  open() {}
  setRequestHeader() {}
  send() {}
  abort() {}
  emit(frame: object) {
    this.responseText += `data: ${JSON.stringify(frame)}\n\n`;
    this.onreadystatechange?.();
  }
}

const mount = () => render(<ServerProvider><ChatScreen onGoToSettings={() => {}} /></ServerProvider>);
const calls = () => screen.queryAllByLabelText(/^Provider /);

beforeEach(() => {
  records.clear();
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2,
    config: { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' },
    appearance: null, chatScope: 'one' }));
  vi.stubGlobal('XMLHttpRequest', ChatXHR);
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () =>
    url.endsWith('/sessions/resume') ? { ok: true, session: 'older', turns: [
      { role: 'user', content: 'Earlier question' },
      { role: 'assistant', content: 'Earlier answer', model_calls: [
        { provider: 'ollama', model: 'long/local/model:name/with/many/segments' },
      ] },
    ] } : (url.endsWith('/sessions') || url.includes('/sessions/page?'))
      ? { sessions: [{ id: 'older', title: 'Older session' }], next_cursor: null }
      : { agents: [] },
  })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows each measured call only after a live assistant text reply completes', async () => {
  mount();
  fireEvent.change(await screen.findByPlaceholderText('Message Jarvis…'), { target: { value: 'Question' } });
  fireEvent.click(screen.getByText('Send'));
  expect(calls()).toHaveLength(0);
  await act(async () => ChatXHR.latest.emit({ type: 'end', text: 'Answer', session_id: 'saved', model_calls: [
    { provider: 'ollama', model: 'qwen3' },
    { provider: 'lmstudio', model: 'deep/reasoning/model-with-a-very-long-name' },
  ] }));
  expect(screen.getByText('Answer')).toBeTruthy();
  expect(screen.getByText('Models called')).toBeTruthy();
  expect(calls()).toHaveLength(2);
  expect(calls()[0].getAttribute('aria-label')).toBe('Provider ollama, model qwen3');
  expect(calls()[1].textContent).toContain('deep/reasoning/model-with-a-very-long-name');
  expect(calls()[1].getAttribute('data-native-style')).toContain('"flexShrink":1');
});

it('restores a receipt with its historical reply and leaves unannotated turns bare', async () => {
  mount();
  expect(calls()).toHaveLength(0);
  fireEvent.click(await screen.findByText('History'));
  fireEvent.click(await screen.findByText('Older session'));
  expect(await screen.findByText('Earlier answer')).toBeTruthy();
  expect(calls()).toHaveLength(1);
  expect(calls()[0].getAttribute('aria-label')).toContain('long/local/model:name/with/many/segments');
});

it('keeps the measured agent activity beside the mobile reply across a remount', async () => {
  const first = mount();
  fireEvent.change(await screen.findByPlaceholderText('Message Jarvis…'), { target: { value: 'Draft an invitation.' } });
  fireEvent.click(screen.getByText('Send'));
  const draft = '[Invitation sent via WhatsApp bridge]';
  await act(async () => ChatXHR.latest.emit({ type: 'token', text: draft }));
  expect(screen.queryByText(/Agent tool calls recorded/)).toBeNull();
  await act(async () => ChatXHR.latest.emit({ type: 'end', text: draft, session_id: 'saved',
    outcome: { tools: { proposed: 0, queued: 0, executed: 0, failures: 0, basis: 'observed' } } }));
  expect(await screen.findByText('Agent tool calls recorded: 0')).toBeTruthy();
  first.unmount();
  mount();
  expect(await screen.findByText('Agent tool calls recorded: 0')).toBeTruthy();
  expect(screen.getByText(/Invitation sent via WhatsApp bridge/)).toBeTruthy();
});
