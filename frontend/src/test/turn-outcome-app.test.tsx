import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';

vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {} }) }));
vi.mock('../mesh', () => ({
  NeuralMesh: ({ onSelect }: { onSelect?: (id: string) => void }) =>
    <button onClick={() => onSelect?.('frigga')}>Select Frigga</button>,
  isExecutingAgent: () => false,
}));
vi.mock('../api/loaders', () => ({ loadJarvisData: async () => ({}),
  createLatestRefreshRunner: () => ({ refresh: () => {}, stop: () => {} }) }));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../gap', () => ({ FirstRunGate: () => null }));

let streams: Array<(response: Response) => void> = [];
let requests: Array<{ path: string; body?: string; signal?: AbortSignal }> = [];
const event = (payload: unknown) => `data: ${JSON.stringify(payload)}\n\n`;
const ended = (outcome: unknown, sessionId = 'topic_a') => new Response(
  event({ type: 'start', agent: 'jarvis' }) + event({ type: 'end', agent: 'jarvis',
    text: 'Completed reply', session_id: sessionId, outcome }),
  { headers: { 'Content-Type': 'text/event-stream' } },
);
const streamRequest = () => requests.filter(request => request.path === '/chat/stream');

beforeEach(() => {
  cleanup();
  localStorage.clear(); sessionStorage.clear();
  localStorage.setItem('hud.seen', '1');
  history.replaceState(null, '', '/v2');
  streams = []; requests = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: { body?: string; signal?: AbortSignal }) => {
    requests.push({ path, body: init?.body, signal: init?.signal });
    if (path === '/chat/stream') return new Promise<Response>(resolve => streams.push(resolve));
    return new Response(JSON.stringify({ configured: false, revision: '0', preferences: {} }));
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function mount(path = '/v2') {
  history.replaceState(null, '', path);
  render(<App />);
  await screen.findByLabelText('Attach images');
}
async function send(text: string) {
  const input = document.querySelector('[data-composer]') as HTMLInputElement;
  fireEvent.change(input, { target: { value: text } });
  fireEvent.click(document.querySelector('.inputbar .transmit') as HTMLElement);
  await waitFor(() => expect(streams.length).toBeGreaterThan(0));
}
async function complete(outcome: unknown, sessionId = 'topic_a') {
  const resolve = streams.shift()!;
  await act(async () => resolve(ended(outcome, sessionId)));
}
const readout = () => screen.queryByLabelText('Turn duration');

it.each(['/v2', '/v2/chat'])('shows only measured whole-turn duration in %s after the current end', async path => {
  await mount(path);
  expect(readout()).toBeNull();
  await send('time this turn');
  expect(readout()).toBeNull();
  await complete({ latency_ms: 1250 });
  expect(await screen.findByText('Completed reply')).toBeTruthy();
  expect(readout()?.textContent).toMatch(/Turn duration.*1\.25 s/);
  expect(screen.queryByText(/tokens per second/i)).toBeNull();
  expect(streamRequest()).toHaveLength(1);
});

it.each([null, {}, { latency_ms: -1 }, { latency_ms: '19' }, { latency_ms: true }, { latency_ms: null },
  { latency_ms: 1e999 }])('omits absent, hidden or invalid duration %#', async outcome => {
  await mount();
  await send('first turn');
  await complete(outcome);
  await screen.findByText('Completed reply');
  expect(readout()).toBeNull();
});

it('omits a parsed nonfinite JSON number', async () => {
  await mount();
  await send('nonfinite');
  await act(async () => streams.shift()!(new Response(
    event({ type: 'start', agent: 'jarvis' })
      + 'data: {"type":"end","text":"Completed reply","session_id":"topic_a","outcome":{"latency_ms":1e999}}\n\n',
  )));
  await screen.findByText('Completed reply');
  expect(readout()).toBeNull();
});

it('omits a command duration when the command replaces the selected session', async () => {
  await mount();
  await send('/new');
  await complete({ latency_ms: 29 }, 'topic_b');
  await screen.findByText('Completed reply');
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('topic_b');
  expect(readout()).toBeNull();
});

it('shows exact zero and clears a prior duration synchronously when another turn starts', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 9 });
  await screen.findByLabelText('Turn duration');
  await send('second');
  expect(readout()).toBeNull();
  await complete({ latency_ms: 0 });
  expect(readout()?.textContent).toMatch(/Turn duration.*0 ms/);
});

it('does not retain an old duration after an error end or a failed stream', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 35 });
  await screen.findByLabelText('Turn duration');
  await send('error end'); await complete(null);
  expect(readout()).toBeNull();
  await send('transport error');
  await act(async () => streams.shift()!(new Response('', { status: 503 })));
  expect(readout()).toBeNull();
});

it('clears on Stop and ignores an end delivered after the cancelled turn', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 35 });
  await screen.findByLabelText('Turn duration');
  await send('stop me');
  fireEvent.click(screen.getByRole('button', { name: 'Stop generating' }));
  expect(readout()).toBeNull();
  await complete({ latency_ms: 999 });
  expect(readout()).toBeNull();
});

it('clears on topic selection and ignores the old topic reply', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 35 });
  await screen.findByLabelText('Turn duration');
  await send('old topic pending');
  act(() => window.dispatchEvent(new CustomEvent('nerva:session-selected', {
    detail: { sessionId: 'topic_b', turns: [{ role: 'assistant', content: 'B answer' }] },
  })));
  expect(readout()).toBeNull();
  await complete({ latency_ms: 999 }, 'topic_a');
  expect(readout()).toBeNull();
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('topic_b');
});

it('clears on agent selection, even when a prior turn completed', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 35 });
  await screen.findByLabelText('Turn duration');
  fireEvent.click(screen.getByText('Select Frigga'));
  expect(readout()).toBeNull();
});

it('clears when entering demo mode and never presents an old live duration as demo evidence', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 35 });
  await screen.findByLabelText('Turn duration');
  const demo = screen.getAllByText(/demo/i).find(node => node.tagName === 'BUTTON');
  expect(demo).toBeTruthy();
  fireEvent.click(demo!);
  expect(readout()).toBeNull();
});

it('ignores a late live end after the user switches into demo mode', async () => {
  await mount();
  await send('pending live turn');
  fireEvent.click(screen.getByTitle('toggle demo data (seeded sample vs live-only)'));
  expect(readout()).toBeNull();
  await complete({ latency_ms: 810 });
  expect(readout()).toBeNull();
  expect(screen.queryByText('Completed reply')).toBeNull();
});
