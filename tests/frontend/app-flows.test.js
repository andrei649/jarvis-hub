// app.js critical flows: the chat send→stream→render pipeline (P1) and the
// background polling intervals (P2).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

const ALL_FILES = [
  'i18n', 'data', 'components', 'network', 'enhancements',
  'cognition', 'systems', 'workflows', 'observability', 'dossier-modal', 'app',
];

function bootStub(extra = {}) {
  const json = (body) => Promise.resolve({ json: async () => body, ok: true });
  return vi.fn((url, opts) => {
    if (extra[url]) return extra[url](url, opts);
    if (url === '/api/agents') return json({ agents: [{ id: 'jarvis', name: 'Jarvis', status: 'active', enabled: true, model: 'm' }] });
    if (url.startsWith('/status')) return json({ lm_online: true, sys: {}, agents: [] });
    if (url.startsWith('/dashboard')) return json({ weather: null, calendar: [], notifications: [] });
    if (url.startsWith('/tasks')) return json({ tasks: [] });
    if (url.startsWith('/ticker')) return json({ ticker: [] });
    return json({});
  });
}

// Build a fake SSE Response whose body.getReader() streams the given events.
function sseResponse(events) {
  const enc = new TextEncoder();
  const payload = events.map((e) => 'data: ' + JSON.stringify(e) + '\n').join('');
  let sent = false;
  return Promise.resolve({
    ok: true,
    body: {
      getReader: () => ({
        read: async () => {
          if (sent) return { done: true, value: undefined };
          sent = true;
          return { done: false, value: enc.encode(payload) };
        },
      }),
    },
  });
}

describe('chat flow (P1)', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('sends a message and renders the streamed agent reply', async () => {
    const fetch = bootStub({
      '/chat/stream': () => sseResponse([
        { type: 'start', agent: 'jarvis' },
        { type: 'token', text: 'Salut' },
        { type: 'token', text: ' lume' },
        { type: 'end', text: 'Salut lume', agent: 'jarvis' },
      ]),
    });
    env = loadHud({ files: ALL_FILES, fetch, lang: 'ro' });
    // app.js uses TextDecoder in the realm to decode the stream.
    env.window.TextDecoder = TextDecoder;
    await env.flush();

    const root = env.document.getElementById('root');
    const input = root.querySelector('.input-field');
    expect(input).not.toBeNull();

    env.type(input, 'salutare');
    env.click(root.querySelector('.input-send'));
    await env.flush();

    expect(fetch).toHaveBeenCalledWith('/chat/stream', expect.objectContaining({ method: 'POST' }));
    // User message + streamed agent reply are both in the conversation.
    expect(root.textContent).toContain('salutare');
    expect(root.textContent).toContain('Salut lume');
  });

  it('shows a connection error when the stream request fails', async () => {
    const fetch = bootStub({
      '/chat/stream': () => Promise.resolve({ ok: false, status: 500 }),
    });
    env = loadHud({ files: ALL_FILES, fetch, lang: 'ro' });
    env.window.TextDecoder = TextDecoder;
    await env.flush();

    const root = env.document.getElementById('root');
    env.type(root.querySelector('.input-field'), 'hello');
    env.click(root.querySelector('.input-send'));
    await env.flush();

    // app.connection_error string (ro) is rendered as an agent message.
    expect(root.textContent.toLowerCase()).toContain('conexiune');
  });
});

describe('background polling (P2)', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('re-fetches live data on the 30s interval tick', async () => {
    const fetch = bootStub();
    env = loadHud({ files: ALL_FILES, fetch, lang: 'ro' });

    // Capture intervals registered by app.js effects (which run during flush).
    const intervals = [];
    env.window.setInterval = (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; };
    await env.flush();

    const dataPoll = intervals.find((i) => i.ms === 30000);
    expect(dataPoll, 'a 30s data poll is registered').toBeTruthy();

    fetch.mockClear();
    await dataPoll.fn(); // simulate one tick
    await env.flush();
    expect(fetch).toHaveBeenCalledWith('/api/agents');
  });

  it('re-fetches /status on the status interval tick', async () => {
    const fetch = bootStub();
    env = loadHud({ files: ALL_FILES, fetch, lang: 'ro' });
    const intervals = [];
    env.window.setInterval = (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; };
    await env.flush();

    // The status poll runs on a 10s interval.
    const statusPoll = intervals.find((i) => i.ms === 10000);
    expect(statusPoll, 'a status poll is registered').toBeTruthy();
    fetch.mockClear();
    await statusPoll.fn();
    await env.flush();
    expect(env.window.fetch).toHaveBeenCalledWith('/status');
  });
});
