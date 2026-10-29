import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';
import { StatusStrip, turnOutcome } from '../turn-outcome';

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
let powerPayload: unknown = {};
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
  powerPayload = {};
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: { body?: string; signal?: AbortSignal }) => {
    requests.push({ path, body: init?.body, signal: init?.signal });
    if (path === '/chat/stream') return new Promise<Response>(resolve => streams.push(resolve));
    if (path === '/api/power') return new Response(JSON.stringify(powerPayload));
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

it('parses source-backed H686 fields and drops malformed metrics independently', () => {
  const outcome = turnOutcome({ model: 'actual', context_detail: { prompt_tokens: 500, window_tokens: 1000 },
    context_pct: 50, cache_hit: 60, tps: 40, compressions: 2, duration_ms: 80,
    prompt_elapsed_ms: 25, total_tokens: 580, title: 'Current chat', battery: true,
    bg_processes: 99, goal: 'guessed' });
  expect(outcome).toMatchObject({ model: 'actual', context_pct: 50, cache_hit: 60,
    tps: 40, compressions: 2, duration_ms: 80, prompt_elapsed_ms: 25,
    total_tokens: 580, title: 'Current chat', battery: true });
  expect(outcome).not.toHaveProperty('bg_processes');
  expect(outcome).not.toHaveProperty('goal');
  expect(turnOutcome({ context_pct: 120, cache_hit: -1, tps: Infinity,
    duration_ms: '20', total_tokens: -1, model: '<script>' })).toBeNull();
});

it('renders selected metrics with cache thresholds and truthful local battery', () => {
  const outcome = turnOutcome({ model: 'actual', context_detail: { prompt_tokens: 500, window_tokens: 1000 },
    context_pct: 50, cache_hit: 60, tps: 40, compressions: 2, duration_ms: 80,
    prompt_elapsed_ms: 25, total_tokens: 580, title: 'Current chat', battery: true });
  render(<StatusStrip outcome={outcome} power={{ onBattery: true, percent: 75, deferred: false,
    resumedAt: null, keepAwake: { enabled: false, active: false, refused: null, error: null } }} />);
  expect(screen.getByLabelText('Request output tokens per second').textContent).toContain('40');
  expect(screen.getByLabelText('Prompt cache hit').getAttribute('data-band')).toBe('medium');
  expect(screen.getByLabelText('Prompt context').textContent).toContain('500 / 1000');
  expect(screen.getByLabelText('Battery').textContent).toContain('75%');
  expect(screen.getByLabelText('Accepted compressions').textContent).toContain('2');
  expect(screen.getByLabelText('Turn generation and settlement').textContent).toContain('80 ms');
  expect(screen.getByLabelText('Prompt elapsed to first visible chunk').textContent).toContain('25 ms');
});

const longModel = `model/${'x'.repeat(114)}`;
const longTitle = 'T'.repeat(200);

it('separates status rows and keeps full valid long values within a bounded scrollable strip', () => {
  render(<StatusStrip outcome={turnOutcome({ latency_ms: 1250, model: longModel,
    title: longTitle, completion: { kind: 'answered', explanation: 'Done',
      severity: 'info', unanswered_tool_results: 0 } })} />);
  const strip = screen.getByLabelText('Turn outcome');
  expect(strip.style.maxWidth).toBe('100%');
  expect(strip.style.overflowWrap).toBe('anywhere');
  expect(strip.style.overflowY).toBe('auto');
  expect(strip.style.maxHeight).toBeTruthy();
  expect(screen.getByLabelText('Turn duration').style.display).toBe('block');
  expect(screen.getByLabelText('Request model').style.display).toBe('block');
  expect(screen.getByLabelText('Request model').textContent).toContain(longModel);
  expect(screen.getByLabelText('Session title').textContent).toContain(longTitle);
  expect(screen.getByLabelText('Turn completion').textContent).toContain('Done');
});

it.each([[false, '/v2/chat'], [true, '/v2/chat?desktop=floating']] as const)(
  'mounts long status values beside a reachable composer floating=%s', async (floating, path) => {
    history.replaceState(null, '', path);
    render(<App floating={floating} />);
    await screen.findByLabelText('Attach images');
    await send('long status');
    await complete({ latency_ms: 1250, model: longModel, title: longTitle });
    expect((screen.getByLabelText('Request model').textContent || '').includes(longModel)).toBe(true);
    expect((screen.getByLabelText('Session title').textContent || '').includes(longTitle)).toBe(true);
    expect(document.querySelector('[data-composer]')).toBeTruthy();
    expect(screen.getByLabelText('Turn outcome').style.overflowY).toBe('auto');
  },
);

it.each([[false, '/v2/chat'], [true, '/v2/chat?desktop=floating']] as const)(
  'allocates remaining chat-pane height to scrollable status while preserving composer floating=%s',
  async (floating, path) => {
    powerPayload = { power: { on_battery: true, percent: 75 } };
    history.replaceState(null, '', path);
    render(<App floating={floating} />);
    await screen.findByLabelText('Attach images');
    await send('all selected metrics');
    await complete({ latency_ms: 1250, model: longModel,
      context_detail: { prompt_tokens: 8192, window_tokens: 16384 }, context_pct: 50,
      cache_hit: 72.5, tps: 47.2, compressions: 3, duration_ms: 1080,
      prompt_elapsed_ms: 115, total_tokens: 9472, title: longTitle, battery: true });
    const composer = document.querySelector('[data-composer]') as HTMLInputElement;
    const composerStatus = composer.closest('.inputbar')?.parentElement as HTMLElement;
    const chatPane = composer.closest('.chat-col') as HTMLElement;
    const strip = screen.getByLabelText('Turn outcome');
    expect(chatPane.style.maxHeight).toBe('100%');
    expect(composerStatus.style.minHeight).toBe('0px');
    expect(composerStatus.style.display).toBe('flex');
    expect(composerStatus.style.flexDirection).toBe('column');
    expect(strip.style.minHeight).toBe('0px');
    expect(strip.style.flexShrink).toBe('1');
    expect(strip.style.overflowY).toBe('auto');
    expect(screen.getByLabelText('Request model').textContent).toContain(longModel);
    expect(screen.getByLabelText('Session title').textContent).toContain(longTitle);
    expect(screen.getByLabelText('Battery').textContent).toContain('75%');
    expect(composer.disabled).toBe(false);
  },
);

it.each([[false, '/v2/chat'], [true, '/v2/chat?desktop=floating']] as const)(
  'forwards local battery into mounted ChatMode floating=%s', async (floating, path) => {
    powerPayload = { power: { on_battery: true, percent: 75 } };
    history.replaceState(null, '', path);
    render(<App floating={floating} />);
    await screen.findByLabelText('Attach images');
    await send('battery status');
    await complete({ battery: true });
    expect((await screen.findByLabelText('Battery')).textContent).toContain('75%');
  },
);

it.each([[false, '/v2/chat'], [true, '/v2/chat?desktop=floating']] as const)(
  'hides selected battery in mounted ChatMode when local power is unknown floating=%s',
  async (floating, path) => {
    history.replaceState(null, '', path);
    render(<App floating={floating} />);
    await screen.findByLabelText('Attach images');
    await send('battery status');
    await complete({ battery: true });
    await screen.findByText('Completed reply');
    expect(screen.queryByLabelText('Battery')).toBeNull();
  },
);

it.each([[70, 'high'], [40, 'medium'], [39.9, 'low']] as const)(
  'uses the frozen 70/40 cache bands for %s%%', (rate, band) => {
    const { unmount } = render(<StatusStrip outcome={turnOutcome({ cache_hit: rate })} />);
    expect(screen.getByLabelText('Prompt cache hit').getAttribute('data-band')).toBe(band);
    unmount();
  },
);

it('keeps every valid bounded file attempt from the owner outcome', () => {
  const attempts = Array.from({ length: 33 }, (_, index) => ({
    attempt: index + 1, operation: 'write', outcome: 'refused',
  }));
  expect(turnOutcome({ file_mutations: attempts })?.file_mutations).toHaveLength(33);
});

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

it('renders live visible-output estimate, then reconciles observed usage and failed-file footer', async () => {
  await mount('/v2/chat');
  await send('write the note');
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const encoded = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
  await act(async () => streams.shift()!(new Response(body, {
    headers: { 'Content-Type': 'text/event-stream' },
  })));
  await act(async () => {
    controller.enqueue(encoded.encode(event({ type: 'start', agent: 'jarvis' })
      + event({ type: 'token', text: 'Working' })
      + event({ type: 'outcome_progress', outcome: {
        output: { tokens: 2, basis: 'visible_estimate' },
        tools: { proposed: 1, queued: 1, executed: 0, failures: 0, basis: 'observed' },
      } })));
  });
  expect((await screen.findByLabelText('Output token flow')).textContent).toContain('~2 tokens (text estimate)');
  expect(screen.getByLabelText('Tool call accounting').textContent).toContain('queued 1; executed 0');
  await act(async () => {
    controller.enqueue(encoded.encode(event({ type: 'end', text: 'Approval queued', session_id: 'topic_a',
      outcome: {
        latency_ms: 20,
        completion: { kind: 'pending_approval', severity: 'warning',
          explanation: 'Approval is pending.', unanswered_tool_results: 1 },
        tools: { proposed: 1, queued: 1, executed: 0, failures: 0, basis: 'observed' },
        output: { tokens: 9, basis: 'provider_complete' },
        file_mutations: [{ attempt: 1, operation: 'write', outcome: 'unknown' }],
      } })));
    controller.close();
  });
  expect((await screen.findByLabelText('Output token flow')).textContent).toContain('9 (provider reported)');
  expect(screen.getByLabelText('Turn completion').textContent).toContain('Warning: Approval is pending.');
  expect(screen.getByLabelText('File mutation notes').textContent).toContain('effect uncertain');
  await send('next turn');
  expect(screen.queryByLabelText('Output token flow')).toBeNull();
  expect(screen.queryByLabelText('Turn completion')).toBeNull();
  expect(screen.queryByLabelText('File mutation notes')).toBeNull();
  await complete(null);
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
