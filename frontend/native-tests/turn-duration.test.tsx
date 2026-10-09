import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';

vi.mock('../../mobile/src/components/PushToTalk', () => ({
  PushToTalk: () => <button disabled>Dictation control</button>,
}));
vi.mock('../../mobile/src/voice/pushToTalk', () => ({ waitForMicrophoneIdle: async () => {} }));
const speech = vi.hoisted(() => ({ state: { status: 'off' } }));
const restoredPrefs = vi.hoisted(() => ({ load: null as null | (() => Promise<{ agent: string }>) }));
vi.mock('../../mobile/src/storage/prefs', async importOriginal => {
  const actual = await importOriginal<typeof import('../../mobile/src/storage/prefs')>();
  return { ...actual, loadPrefs: () => restoredPrefs.load ? restoredPrefs.load() : actual.loadPrefs() };
});
vi.mock('../../mobile/src/audio/tts', () => ({
  getSpeechState: () => speech.state, subscribeSpeech: () => () => {},
  speak: vi.fn(), stopSpeaking: vi.fn(),
}));
vi.mock('../../mobile/src/components/VoiceOrb', () => ({ VoiceOrb: () => <div /> }));
vi.mock('../../mobile/src/components/SelectedImages', () => ({
  SelectedImages: ({ chat, sessionId }: any) => <button onClick={() => chat.beginSelectedImage(sessionId, chat.revision)}>
    Begin selected image
  </button>,
}));

const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
let server: ReturnType<typeof useServer>;
let onEpochCommit: (() => void) | null = null;
function Probe() {
  server = useServer();
  const epoch = server.connectionEpoch;
  React.useLayoutEffect(() => { onEpochCommit?.(); }, [epoch]);
  return <ChatScreen onGoToSettings={() => {}} />;
}
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);

class ChatXHR {
  static created: ChatXHR[] = [];
  status = 200;
  readyState = 3;
  responseText = '';
  body: any;
  aborted = false;
  onreadystatechange?: () => void;
  onerror?: () => void;
  constructor() { ChatXHR.created.push(this); }
  open() {}
  setRequestHeader() {}
  abort() { this.aborted = true; this.status = 0; this.readyState = 4; this.onreadystatechange?.(); }
  send(body: string) { this.body = JSON.parse(body); }
  frame(frame: unknown) {
    this.status = 200;
    this.readyState = 3;
    this.responseText += `data: ${JSON.stringify(frame)}\n\n`;
    this.onreadystatechange?.();
  }
  end(text = 'Fresh reply', session = 'saved', outcome?: unknown) {
    this.frame({ type: 'end', text, session_id: session, ...(outcome === undefined ? {} : { outcome }) });
  }
  fail() { this.onerror?.(); }
}

const duration = () => screen.queryByLabelText(/^Turn duration/);
async function send(text: string): Promise<ChatXHR> {
  const input = await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.change(input, { target: { value: text } });
  fireEvent.click(screen.getByText('Send'));
  const xhr = ChatXHR.created.at(-1);
  expect(xhr?.body).toMatchObject({ message: text, session_id: 'saved' });
  return xhr!;
}
async function complete(text = 'Fresh reply', outcome: unknown = { latency_ms: 123 }, session = 'saved') {
  const xhr = await send(text);
  await act(async () => xhr.end(`${text} answer`, session, outcome));
  expect(screen.getByText(`${text} answer`)).toBeTruthy();
  return xhr;
}

beforeEach(() => {
  records.clear();
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'one', sessionId: 'saved',
    messages: [{ id: 'answer', role: 'assistant', text: 'Saved reply' }] }));
  ChatXHR.created = [];
  onEpochCommit = null;
  restoredPrefs.load = null;
  vi.stubGlobal('XMLHttpRequest', ChatXHR);
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () =>
    url.endsWith('/sessions/resume') ? { ok: true, session: 'older', turns: [{ role: 'assistant', content: 'Older answer' }] }
      : url.endsWith('/sessions') ? { sessions: [{ id: 'older', title: 'Older session' }] } : { agents: [
      { id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' },
    ] },
  })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows a current whole-turn duration from a real end frame, including zero', async () => {
  mount();
  await complete('Timed reply');
  expect(duration()?.textContent).toMatch(/123\s*ms/);
  expect(duration()?.getAttribute('aria-label')).toMatch(/Turn duration:\s*123\s*ms/);
  await complete('Zero reply', { latency_ms: 0 });
  expect(duration()?.textContent).toMatch(/0\s*ms/);
});

it('never shows a duration for absent or malformed outcome data', async () => {
  mount();
  const absent = await send('No outcome');
  await act(async () => absent.end('Untimed reply'));
  expect(screen.getByText('Untimed reply')).toBeTruthy();
  expect(duration()).toBeNull();
  for (const outcome of [null, { latency_ms: -1 }, { latency_ms: '12' }, { latency_ms: 1.5 }]) {
    const xhr = await send(`Bad ${JSON.stringify(outcome)}`);
    await act(async () => xhr.end('Untimed result', 'saved', outcome));
    expect(duration()).toBeNull();
  }
});

it('clears duration on the next send, stop and error, ignoring late frames', async () => {
  mount();
  await complete('First reply');
  expect(duration()).toBeTruthy();
  const stopped = await send('Stop me');
  expect(duration()).toBeNull();
  fireEvent.click(screen.getByText('Stop'));
  await act(async () => stopped.end('Late reply', 'saved', { latency_ms: 999 }));
  expect(duration()).toBeNull();
  const errored = await send('Fail me');
  await act(async () => errored.fail());
  expect(screen.getByText(/Could not reach/)).toBeTruthy();
  expect(duration()).toBeNull();
});

it('clears a duration when an actual new session rolls over', async () => {
  mount();
  await complete('Before new');
  expect(duration()).toBeTruthy();
  fireEvent.click(screen.getByText('New'));
  const xhr = ChatXHR.created.at(-1)!;
  expect(xhr.body).toMatchObject({ message: '/new', session_id: 'saved' });
  await act(async () => xhr.end('New session', 'fresh', { latency_ms: 50 }));
  expect(screen.getByText('New session')).toBeTruthy();
  expect(duration()).toBeNull();
});

it('clears a duration when history selects another session', async () => {
  mount();
  await complete('Before history');
  expect(duration()).toBeTruthy();
  fireEvent.click(screen.getByText('History'));
  fireEvent.click(await screen.findByText('Older session'));
  expect(await screen.findByText('Older answer')).toBeTruthy();
  expect(duration()).toBeNull();
});

it('clears a duration when an image turn starts without putting it on the image transcript', async () => {
  mount();
  await complete('Before image');
  expect(duration()).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Selected images'));
  fireEvent.click(screen.getByText('Begin selected image'));
  expect(duration()).toBeNull();
});

it('preserves an old reply but suppresses its duration after agent A to B to A', async () => {
  mount();
  const old = await send('Agent pending');
  fireEvent.click(screen.getByText('jarvis'));
  fireEvent.click(await screen.findByText('Frigga'));
  fireEvent.click(screen.getByText('Frigga'));
  fireEvent.click(await screen.findByText('Jarvis'));
  await act(async () => old.end('Old agent reply', 'saved', { latency_ms: 600 }));
  expect(screen.getByText('Old agent reply')).toBeTruthy();
  expect(duration()).toBeNull();
});

it('clears an idle completed duration as soon as the selected agent changes', async () => {
  mount();
  await complete('Before agent');
  expect(duration()).toBeTruthy();
  fireEvent.click(screen.getByText('jarvis'));
  fireEvent.click(await screen.findByText('Frigga'));
  expect(duration()).toBeNull();
});

it('suppresses an in-flight duration when stored agent preference resolves later', async () => {
  let resolvePrefs!: (prefs: { agent: string }) => void;
  restoredPrefs.load = () => new Promise(resolve => { resolvePrefs = resolve; });
  mount();
  const old = await send('Before preference');
  await act(async () => resolvePrefs({ agent: 'frigga' }));
  expect(screen.getByText('frigga')).toBeTruthy();
  await act(async () => old.end('Preselection reply', 'saved', { latency_ms: 777 }));
  expect(screen.getByText('Preselection reply')).toBeTruthy();
  expect(duration()).toBeNull();
});

it('hides a prior connection duration immediately and rejects its late reply', async () => {
  mount();
  await complete('First connection');
  expect(duration()).toBeTruthy();
  const old = await send('In flight');
  await act(async () => server.updateConfig({ ...config, token: 'different' }));
  expect(duration()).toBeNull();
  await act(async () => old.end('Old connection reply', 'saved', { latency_ms: 400 }));
  expect(screen.queryByText('Old connection reply')).toBeNull();
  expect(duration()).toBeNull();
});

it('clears a duration for a new connection epoch even when the saved config is identical', async () => {
  mount();
  await complete('Same hub');
  expect(duration()).toBeTruthy();
  let committedDuration: Element | null | undefined;
  onEpochCommit = () => { committedDuration = duration(); };
  await act(async () => server.updateConfig(config));
  expect(committedDuration).toBeNull();
  expect(duration()).toBeNull();
  const old = await send('Before reconnect');
  await act(async () => server.updateConfig(config));
  await act(async () => old.end('Revoked epoch reply', 'saved', { latency_ms: 900 }));
  expect(screen.queryByText('Revoked epoch reply')).toBeNull();
});

it('stores no duration bytes and never restores a prior duration after remount', async () => {
  const view = mount();
  await complete('Persisted reply');
  expect(duration()).toBeTruthy();
  await waitFor(() => expect(records.get('jarvis.chat.conversation.v2')).toContain('Persisted reply answer'));
  expect(records.get('jarvis.chat.conversation.v2')).not.toMatch(/"(?:latency_ms|turnOutcome)"/);
  view.unmount();
  mount();
  expect(await screen.findByText('Persisted reply answer')).toBeTruthy();
  expect(duration()).toBeNull();
});
