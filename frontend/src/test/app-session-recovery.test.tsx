import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';

vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {} }) }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../api/loaders', () => ({ loadJarvisData: async () => ({}),
  createLatestRefreshRunner: () => ({ refresh: () => {}, stop: () => {} }) }));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../gap', () => ({ FirstRunGate: () => null }));

const event = (payload: unknown) => `data: ${JSON.stringify(payload)}\n\n`;
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
let requests: Array<{ path: string; body?: any }> = [];

beforeEach(() => {
  cleanup();
  localStorage.clear(); sessionStorage.clear();
  localStorage.setItem('hud.seen', '1');
  history.replaceState(null, '', '/v2/chat');
  requests = [];
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function mount() {
  render(<App />);
  await screen.findByLabelText('Attach images');
}

it('rehydrates exact missing-session 404 to current memory and sends the next turn there', async () => {
  sessionStorage.setItem('nerva.chat.session_id', 'old');
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: { body?: string }) => {
    requests.push({ path, body: init?.body ? JSON.parse(init.body) : undefined });
    if (path === '/sessions/resume') return json(404, { error: "session 'old' not found" });
    if (path === '/memory') return json(200, { session: 'current', turns: [
      { role: 'assistant', content: 'Recovered current transcript' },
    ] });
    if (path === '/chat/stream') return new Response(
      event({ type: 'start', agent: 'jarvis' }) + event({ type: 'end', agent: 'jarvis', text: 'New reply' }),
      { headers: { 'Content-Type': 'text/event-stream' } });
    return json(200, {});
  }));

  await mount();
  expect(await screen.findByText('Recovered current transcript')).toBeTruthy();
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('current');
  const input = document.querySelector('[data-composer]') as HTMLInputElement;
  fireEvent.change(input, { target: { value: 'continue here' } });
  fireEvent.click(document.querySelector('.inputbar .transmit') as HTMLElement);
  await screen.findByText('New reply');
  const chat = requests.find((request) => request.path === '/chat/stream');
  expect(chat?.body).toMatchObject({ session_id: 'current' });
});

it.each([
  ['403', () => json(403, { error: "session 'old' not found" })],
  ['503', () => json(503, { error: "session 'old' not found" })],
  ['proxy 404', () => json(404, { detail: "session 'old' not found" })],
  ['mismatched 404', () => json(404, { error: "session 'other' not found" })],
  ['network failure', () => new TypeError('offline')],
])('startup %s preserves the selected id and does not read fallback memory', async (_label, reply) => {
  sessionStorage.setItem('nerva.chat.session_id', 'old');
  let releaseResume!: (response: Response) => void;
  let rejectResume!: (error: unknown) => void;
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: { body?: string }) => {
    requests.push({ path, body: init?.body ? JSON.parse(init.body) : undefined });
    if (path === '/sessions/resume') return new Promise<Response>((resolve, reject) => {
      releaseResume = resolve; rejectResume = reject;
    });
    return json(200, {});
  }));
  await mount();
  await waitFor(() => expect(releaseResume).toBeTruthy());
  await act(async () => {
    const result = reply();
    if (result instanceof Response) releaseResume(result);
    else rejectResume(result);
  });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('old');
  expect(requests.some((request) => request.path === '/memory')).toBe(false);
  expect(screen.queryByText('Should not load fallback transcript')).toBeNull();
});

it('a terminal-looking 503 after an existing transcript does not replace the message', async () => {
  sessionStorage.setItem('nerva.chat.session_id', 'old');
  let releaseResume!: (response: Response) => void;
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: { body?: string }) => {
    requests.push({ path, body: init?.body ? JSON.parse(init.body) : undefined });
    if (path === '/sessions/resume') return new Promise<Response>((resolve) => { releaseResume = resolve; });
    return json(200, {});
  }));
  await mount();
  await waitFor(() => expect(releaseResume).toBeTruthy());
  act(() => window.dispatchEvent(new CustomEvent('nerva:session-selected', { detail: {
    sessionId: 'old', turns: [{ role: 'assistant', content: 'Existing old transcript' }],
  } })));
  expect(screen.getByText('Existing old transcript')).toBeTruthy();
  await act(async () => releaseResume(json(503, { error: "session 'old' not found" })));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('old');
  expect(screen.getByText('Existing old transcript')).toBeTruthy();
  expect(requests.some((request) => request.path === '/memory')).toBe(false);
});

it('a completed text turn fences a late fallback snapshot even though busy has cleared', async () => {
  sessionStorage.setItem('nerva.chat.session_id', 'old');
  let releaseMemory!: (response: Response) => void;
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: { body?: string }) => {
    requests.push({ path, body: init?.body ? JSON.parse(init.body) : undefined });
    if (path === '/sessions/resume') return json(404, { error: "session 'old' not found" });
    if (path === '/memory') return new Promise<Response>((resolve) => { releaseMemory = resolve; });
    if (path === '/chat/stream') return new Response(
      event({ type: 'start', agent: 'jarvis' }) + event({ type: 'end', agent: 'jarvis', text: 'Completed during recovery' }),
      { headers: { 'Content-Type': 'text/event-stream' } });
    return json(200, {});
  }));

  await mount();
  await waitFor(() => expect(releaseMemory).toBeTruthy());
  const input = document.querySelector('[data-composer]') as HTMLInputElement;
  fireEvent.change(input, { target: { value: 'new work' } });
  fireEvent.click(document.querySelector('.inputbar .transmit') as HTMLElement);
  await screen.findByText('Completed during recovery');
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('old');

  await act(async () => releaseMemory(json(200, { session: 'current', turns: [
    { role: 'assistant', content: 'Late obsolete transcript' },
  ] })));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('old');
  expect(screen.getByText('Completed during recovery')).toBeTruthy();
  expect(screen.queryByText('Late obsolete transcript')).toBeNull();
});
