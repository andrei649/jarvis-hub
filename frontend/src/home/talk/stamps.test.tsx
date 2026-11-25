/* The three reply stamps runTurn writes (home/talk/types.ts ReplyStamps): _askedAt when the
   reply bubble is reserved, _startedAt on the first `start` frame, _firstTokenAt on the first
   `token` frame — each set once, kept through the end of the turn, never on the owner's turn. */
import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../../app';
import { REPLY_STAMPS } from './types';
import { composerSend } from './test-support';

const seen: { messages: any[] } = { messages: [] };
vi.mock('../../cockpit', async (importOriginal) => {
  const real: any = await importOriginal();
  return { ...real, Conversation: (props: any) => { seen.messages = props.messages; return React.createElement(real.Conversation, props); } };
});
vi.mock('../../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {} }) }));
vi.mock('../../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../../api/loaders', () => ({ loadJarvisData: async () => ({}), createLatestRefreshRunner: () => ({ refresh: () => {}, stop: () => {} }) }));
vi.mock('../../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../../gap', () => ({ FirstRunGate: () => null }));

let streams: Array<(response: Response) => void> = [];
const encoder = new TextEncoder();
const frame = (payload: unknown) => encoder.encode(`data: ${JSON.stringify(payload)}\n\n`);
const reply = () => { const turns = seen.messages.filter((m) => m.role === 'agent' && m._turnId); return turns[turns.length - 1]; };

beforeEach(() => {
  cleanup();
  localStorage.clear(); sessionStorage.clear();
  localStorage.setItem('hud.seen', '1');
  history.replaceState(null, '', '/v2');
  streams = []; seen.messages = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string) => {
    if (path === '/chat/stream') return new Promise<Response>((resolve) => streams.push(resolve));
    return new Response(JSON.stringify({ configured: false, revision: '0', preferences: {} }));
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('stamps the reply bubble when it is reserved, on the first start and on the first token', async () => {
  expect(REPLY_STAMPS).toEqual(['_askedAt', '_startedAt', '_firstTokenAt']);
  render(<App />);
  await screen.findByLabelText('Attach images');
  const before = Date.now();
  fireEvent.change(document.querySelector('[data-composer]') as HTMLInputElement, { target: { value: 'hello' } });
  fireEvent.click(composerSend());
  await waitFor(() => expect(streams.length).toBe(1));

  await waitFor(() => expect(typeof reply()?._askedAt).toBe('number'));
  expect(reply()._askedAt).toBeGreaterThanOrEqual(before);
  expect(reply()._startedAt).toBeUndefined();
  expect(reply()._firstTokenAt).toBeUndefined();
  const owner = seen.messages.find((m) => m.role === 'user');
  for (const stamp of REPLY_STAMPS) expect(owner, stamp).not.toHaveProperty(stamp);

  let body!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start(controller) { body = controller; } });
  await act(async () => streams[0](new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })));

  await act(async () => { body.enqueue(frame({ type: 'start', agent: 'jarvis' })); });
  await waitFor(() => expect(typeof reply()._startedAt).toBe('number'));
  expect(reply()._firstTokenAt).toBeUndefined();
  const started = reply()._startedAt;
  expect(started).toBeGreaterThanOrEqual(reply()._askedAt);

  await act(async () => { body.enqueue(frame({ type: 'token', text: 'Hel' })); });
  await waitFor(() => expect(typeof reply()._firstTokenAt).toBe('number'));
  const first = reply()._firstTokenAt;
  expect(first).toBeGreaterThanOrEqual(started);

  await new Promise((resolve) => setTimeout(resolve, 5));
  await act(async () => { body.enqueue(frame({ type: 'start', agent: 'jarvis' })); body.enqueue(frame({ type: 'token', text: 'lo' })); });
  await waitFor(() => expect(reply().text).toBe('Hello'));
  expect(reply()._startedAt).toBe(started);
  expect(reply()._firstTokenAt).toBe(first);

  await act(async () => { body.enqueue(frame({ type: 'end', agent: 'jarvis', text: 'Hello' })); body.close(); });
  await waitFor(() => expect(reply()._complete).toBe(true));
  expect(reply()).toMatchObject({ _startedAt: started, _firstTokenAt: first });
});
