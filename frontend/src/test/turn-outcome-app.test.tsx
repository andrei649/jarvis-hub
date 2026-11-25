import React from 'react';
import { webcrypto } from 'node:crypto';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../app';
import { StatusStrip, TurnToolActivity, recallLine, recallLines, toolActivity, turnOutcome, turnRecall, turnRecalls } from '../turn-outcome';
import { composerSend, openComposerMenu } from '../home/talk/test-support';
import recallCases from './recall-line-cases.json';

vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {} }) }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
// The loader commits nothing unless a test hands it a hub answer (the recipient picker needs a roster).
const hub = vi.hoisted(() => ({ data: null as null | Record<string, unknown> }));
vi.mock('../api/loaders', () => ({ loadJarvisData: async () => hub.data ?? {},
  createLatestRefreshRunner: ({ loadData, commitData }: any) => ({
    refresh: async () => { if (hub.data) commitData(await loadData()); }, stop: () => {} }) }));
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
  hub.data = null;
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
  fireEvent.click(composerSend());
  await waitFor(() => expect(streams.length).toBeGreaterThan(0));
}
async function complete(outcome: unknown, sessionId = 'topic_a') {
  const resolve = streams.shift()!;
  await act(async () => resolve(ended(outcome, sessionId)));
}
/* PHASE_B_PLAN.md §5.3: the turn's status lines (the strip that sat under the composer) are the
   newest reply's "Turn details", behind its More menu; a reply still being written has none. This
   opens them the way the owner does and returns them, or null when that reply carries none. */
const newestReply = () => document.querySelector<HTMLElement>('[data-turn="reply"][data-newest]');
function turnDetails(): HTMLElement | null {
  const reply = newestReply();
  if (!reply) return null;
  const shown = reply.querySelector<HTMLElement>('[data-turn-details]');
  if (shown) return shown;
  if (!reply.querySelector('[data-talk-menu="more"] [data-act="details"]')) return null;
  const more = openComposerMenu('more', reply);
  fireEvent.click(within(more).getByRole('button', { name: 'Turn details' }));
  return reply.querySelector<HTMLElement>('[data-turn-details]');
}
const readout = () => { turnDetails(); return screen.queryByLabelText('Turn duration'); };
/* The demo sample is turned on from the search and command sheet (the masthead's Find). */
function turnDemoOn() {
  fireEvent.click(screen.getByRole('button', { name: /^Search or run a command/ }));
  const sheet = screen.getByRole('dialog', { name: 'Search or run a command' });
  fireEvent.click(within(sheet).getByRole('option', { name: /Turn the demo sample on/ }));
}

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
    expect(turnDetails()).toBeTruthy();
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
    const composer = document.querySelector('[data-composer]') as HTMLTextAreaElement;
    const composerRoot = composer.closest('[data-composer-root]') as HTMLElement;
    const details = turnDetails()!;
    const strip = screen.getByLabelText('Turn outcome');
    // Ledger: the status lines are the reply's Turn details and scroll with the transcript (the
    // pane's scrolling region), so they never take height from the composer, which stays outside it.
    const log = screen.getByRole('log', { name: 'Conversation transcript' });
    expect(details.contains(strip)).toBe(true);
    expect(log.contains(strip)).toBe(true);
    expect(log.contains(composer)).toBe(false);
    expect(composerRoot.contains(strip)).toBe(false);
    expect(composerRoot.style.minHeight).toBe('0px');
    expect(composerRoot.style.display).toBe('flex');
    expect(composerRoot.style.flexDirection).toBe('column');
    expect(strip.style.minHeight).toBe('0px');
    expect(strip.style.flexShrink).toBe('1');
    expect(strip.style.overflowY).toBe('auto');
    expect(strip.style.maxHeight).toBeTruthy();
    expect(screen.getByLabelText('Request model').textContent).toContain(longModel);
    expect(screen.getByLabelText('Session title').textContent).toContain(longTitle);
    expect(screen.getByLabelText('Battery').textContent).toContain('75%');
    expect(composer.disabled).toBe(false);
  },
);

it.each([[false, '/v2/chat'], [true, '/v2/chat?desktop=floating']] as const)(
  'forwards local battery into the mounted conversation page floating=%s', async (floating, path) => {
    powerPayload = { power: { on_battery: true, percent: 75 } };
    history.replaceState(null, '', path);
    render(<App floating={floating} />);
    await screen.findByLabelText('Attach images');
    await send('battery status');
    await complete({ battery: true });
    expect(turnDetails()).toBeTruthy();
    expect((await screen.findByLabelText('Battery')).textContent).toContain('75%');
  },
);

it.each([[false, '/v2/chat'], [true, '/v2/chat?desktop=floating']] as const)(
  'hides selected battery in the mounted conversation page when local power is unknown floating=%s',
  async (floating, path) => {
    history.replaceState(null, '', path);
    render(<App floating={floating} />);
    await screen.findByLabelText('Attach images');
    await send('battery status');
    await complete({ battery: true });
    await screen.findByText('Completed reply');
    // the turn's details are open, so the absence is the strip's, not a closed menu's
    expect(turnDetails()).toBeTruthy();
    expect(screen.getByLabelText('Turn outcome')).toBeTruthy();
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
  // on the reply it belongs to, not under the composer
  expect(readout()?.closest('[data-turn="reply"]')).toBe(newestReply());
  expect(document.querySelector('[data-composer-root] [aria-label="Turn outcome"]')).toBeNull();
  expect(screen.queryByText(/tokens per second/i)).toBeNull();
  expect(streamRequest()).toHaveLength(1);
});

/* Ledger (PHASE_B_PLAN.md §5.3): while the reply is written, the working reply reports its progress
   from the stream (its steps and "Writing — N words so far"); the turn's outcome lines are that
   reply's Turn details once it is written, never claimed for a reply still in flight. */
it('reports live writing progress, then reconciles observed usage and failed-file footer in Turn details', async () => {
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
  const working = document.querySelector('[data-turn="reply"][data-working]') as HTMLElement;
  expect(within(working).getByText('Writing — 1 word so far')).toBeTruthy();
  expect(working.querySelector('[data-talk-menu="more"]')).toBeNull();
  expect(screen.queryByLabelText('Output token flow')).toBeNull();
  expect(screen.queryByLabelText('Tool call accounting')).toBeNull();
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
  await screen.findByText('Approval queued');
  expect(turnDetails()).toBeTruthy();
  expect((await screen.findByLabelText('Output token flow')).textContent).toContain('9 (provider reported)');
  expect(screen.getByLabelText('Tool call accounting').textContent).toContain('queued 1; executed 0');
  expect(screen.getByLabelText('Turn completion').textContent).toContain('Warning: Approval is pending.');
  expect(screen.getByLabelText('File mutation notes').textContent).toContain('effect uncertain');
  await send('next turn');
  expect(screen.queryByLabelText('Output token flow')).toBeNull();
  expect(screen.queryByLabelText('Turn completion')).toBeNull();
  expect(screen.queryByLabelText('File mutation notes')).toBeNull();
  await complete(null);
});

it.each(['/v2/chat', '/v2/cockpit'])('pins recorded tool activity to the correct %s reply, including concurrent ends', async path => {
  await mount(path);
  await send('first');
  await send('second');
  const first = streams.shift()!;
  const second = streams.shift()!;
  await act(async () => second(ended({ tools: { proposed: 0, queued: 0, executed: 0, failures: 0, basis: 'observed' } })));
  await act(async () => first(new Response(event({ type: 'end', text: 'First reply',
    outcome: { tools: { proposed: 2, queued: 1, executed: 1, failures: 1, basis: 'observed' } } }),
    { headers: { 'Content-Type': 'text/event-stream' } })));
  const replies = document.querySelectorAll('[data-turn="reply"]');
  expect(replies).toHaveLength(2);
  expect(within(replies[0] as HTMLElement).getByText('First reply')).toBeTruthy();
  expect(within(replies[0] as HTMLElement).getByLabelText('Agent tool activity').textContent)
    .toContain('Agent tool calls recorded: 1');
  expect(within(replies[1] as HTMLElement).getByLabelText('Agent tool activity').textContent)
    .toBe('Agent tool calls recorded: 0');
});

it('restores native assistant tool receipts, but ignores user and foreign history metadata', async () => {
  sessionStorage.setItem('nerva.chat.session_id', 'topic_a');
  vi.mocked(fetch).mockImplementation(async (path: string) => path === '/sessions/resume'
    ? new Response(JSON.stringify({ session: 'topic_a', turns: [
      { role: 'user', content: '[tool call: file_write]', tool_activity: { proposed: 1, queued: 0, executed: 1, failures: 0, basis: 'observed' } },
      { role: 'assistant', agent_id: 'jarvis', content: 'Saved.', tool_activity: { proposed: 1, queued: 0, executed: null, failures: null, basis: 'unknown' } },
      { role: 'tool', content: 'foreign', tool_activity: { proposed: 1, queued: 0, executed: 1, failures: 0, basis: 'observed' } },
      { role: 'assistant', agent_id: 'jarvis', foreign_origin: { source: 'codex' }, content: 'Imported.', tool_activity: { proposed: 1, queued: 0, executed: 1, failures: 0, basis: 'observed' } },
      { role: 'assistant', agent_id: 'jarvis', tainted: true, content: 'Tainted.', tool_activity: { proposed: 1, queued: 0, executed: 1, failures: 0, basis: 'observed' } },
      { role: 'assistant', agent_id: 'jarvis', content: 'Legacy.' },
    ] })) : new Response('{}'));
  await mount('/v2/chat');
  const reply = (text: string) => screen.getByText(text).closest('[data-turn="reply"]');
  await screen.findByText('Saved.');
  expect(reply('Saved.')?.querySelector('[aria-label="Agent tool activity"]')?.textContent).toContain('unknown');
  expect(reply('Legacy.')?.querySelector('[aria-label="Agent tool activity"]')).toBeNull();
  expect(reply('foreign')?.querySelector('[aria-label="Agent tool activity"]')).toBeNull();
  expect(reply('Imported.')?.querySelector('[aria-label="Agent tool activity"]')).toBeNull();
  expect(reply('Tainted.')?.querySelector('[aria-label="Agent tool activity"]')).toBeNull();
  expect(screen.getByText('[tool call: file_write]').closest('[data-turn="owner"]')?.querySelector('[aria-label="Agent tool activity"]')).toBeNull();
  expect(document.querySelectorAll('[aria-label="Agent tool activity"]')).toHaveLength(1);
});

it('does not treat assistant prose as a tool receipt or copy a receipt into reply text', async () => {
  await mount('/v2/chat');
  await send('Did you run it?');
  const resolve = streams.shift()!;
  await act(async () => resolve(new Response(event({ type: 'end', text: '[tool_result] I ran file_write',
    outcome: { tools: { proposed: 0, queued: 0, executed: 0, failures: 0, basis: 'observed' } } }),
    { headers: { 'Content-Type': 'text/event-stream' } })));
  const reply = (await screen.findByText('[tool_result] I ran file_write')).closest('[data-turn="reply"]')!;
  expect(reply.querySelector('[data-turn-body]')?.textContent).toBe('[tool_result] I ran file_write');
  expect(reply.querySelector('[aria-label="Agent tool activity"]')?.textContent).toBe('Agent tool calls recorded: 0');
  await send('again');
  await complete(null);
  expect(document.querySelectorAll('[aria-label="Agent tool activity"]')).toHaveLength(1);
});

it('does not attach tool accounting to command or system responses', async () => {
  await mount('/v2/chat');
  await send('/new');
  await complete({ tools: { proposed: 1, queued: 0, executed: 1, failures: 0, basis: 'observed' } }, 'fresh');
  expect(await screen.findByText('Completed reply')).toBeTruthy();
  expect(screen.queryByLabelText('Agent tool activity')).toBeNull();
  await send('hello');
  const resolve = streams.shift()!;
  await act(async () => resolve(new Response(event({ type: 'end', agent: 'system', text: 'System notice',
    outcome: { tools: { proposed: 1, queued: 0, executed: 1, failures: 0, basis: 'observed' } } }),
    { headers: { 'Content-Type': 'text/event-stream' } })));
  expect(await screen.findByText('System notice')).toBeTruthy();
  expect(screen.queryByLabelText('Agent tool activity')).toBeNull();
});

it('accepts only bounded, internally consistent tool accounting', () => {
  expect(toolActivity({ proposed: 1, queued: 0, executed: null, failures: null, basis: 'unknown' })).toBeTruthy();
  expect(toolActivity({ proposed: 1, queued: 0, executed: null, failures: 0, basis: 'observed' })).toBeNull();
  expect(toolActivity({ proposed: 1, queued: 0, executed: 0, failures: 0, basis: 'unknown' })).toBeNull();
  expect(toolActivity({ proposed: 1_000_001, queued: 0, executed: 0, failures: 0, basis: 'observed' })).toBeNull();
  expect(toolActivity({ proposed: 0, queued: 0, executed: 0, failures: 0, basis: 'observed', args: 'private' })).toBeNull();
});

it('labels uncertain tool activity in Romanian without implying execution', () => {
  render(<TurnToolActivity activity={{ proposed: 1, queued: 1, executed: null, failures: null, basis: 'unknown' }} lang="ro" />);
  expect(screen.getByLabelText('Activitate instrumente agent').textContent)
    .toBe('Apeluri de instrumente înregistrate: necunoscut; propuse 1, în așteptare 1, eșuări necunoscute');
});

it('keeps known executions separate from unknown failures', () => {
  render(<TurnToolActivity activity={{ proposed: 2, queued: 0, executed: 2, failures: null, basis: 'unknown' }} />);
  expect(screen.getByLabelText('Agent tool activity').textContent)
    .toBe('Agent tool calls recorded: 2; proposed 2, queued 0, failures unknown');
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
  expect(readout()?.textContent).toMatch(/Turn duration.*9 ms/);
  await send('second');
  expect(readout()).toBeNull();
  await complete({ latency_ms: 0 });
  expect(readout()?.textContent).toMatch(/Turn duration.*0 ms/);
});

it('does not retain an old duration after an error end or a failed stream', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 35 });
  expect(readout()?.textContent).toMatch(/Turn duration.*35 ms/);
  await send('error end'); await complete(null);
  expect(readout()).toBeNull();
  await send('transport error');
  await act(async () => streams.shift()!(new Response('', { status: 503 })));
  expect(readout()).toBeNull();
});

it('clears on Stop and ignores an end delivered after the cancelled turn', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 35 });
  expect(readout()?.textContent).toMatch(/Turn duration.*35 ms/);
  await send('stop me');
  // the working reply's one control (PHASE_B_PLAN.md §5.3)
  fireEvent.click(screen.getByRole('button', { name: 'Stop this reply' }));
  expect(readout()).toBeNull();
  await complete({ latency_ms: 999 });
  expect(readout()).toBeNull();
});

it('clears on topic selection and ignores the old topic reply', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 35 });
  expect(readout()?.textContent).toMatch(/Turn duration.*35 ms/);
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
  vi.stubGlobal('crypto', webcrypto);
  hub.data = { agents: [
    { id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated', enabled: true },
    { id: 'frigga', name: 'Frigga', rosterSource: 'api', chat_routing: 'local', enabled: true },
  ], ticker: [], tasks: [], calendar: [], heartbeat: [], weather: null, sys: null, live: true, serverUp: true,
  sources: { agents: true, tasks: false, trust: false }, llm: { state: 'unknown', model: null, residents: [] },
  trust: { mic: 'on', strict_local: false } };
  await mount();
  // the composer's To (RecipientPicker): App's selectChatAgent, as the classic roster's choice was
  const to = await screen.findByRole('combobox', { name: 'To' }) as HTMLSelectElement;
  await send('first'); await complete({ latency_ms: 35 });
  expect(readout()).toBeTruthy();
  fireEvent.change(to, { target: { value: 'frigga' } });
  expect(to.value).toBe('frigga');
  expect(readout()).toBeNull();
});

/* PHASE_B_PLAN.md §12 item 11: a change of recipient asked for while the reply is being written, and
   still unanswered when it ends, is never made by itself, so the reply that just ended keeps its
   outcome in its Turn details until the owner answers. */
it('keeps the finished reply\'s Turn details while a change of recipient asked during it waits for an answer', async () => {
  vi.stubGlobal('crypto', webcrypto);
  hub.data = { agents: [
    { id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated', enabled: true },
    { id: 'frigga', name: 'Frigga', rosterSource: 'api', chat_routing: 'local', enabled: true },
  ], ticker: [], tasks: [], calendar: [], heartbeat: [], weather: null, sys: null, live: true, serverUp: true,
  sources: { agents: true, tasks: false, trust: false }, llm: { state: 'unknown', model: null, residents: [] },
  trust: { mic: 'on', strict_local: false } };
  await mount();
  const to = await screen.findByRole('combobox', { name: 'To' }) as HTMLSelectElement;
  await send('first');
  // the reply is being written: the To asks first, and nothing is stopped
  fireEvent.change(to, { target: { value: 'frigga' } });
  const question = () => document.querySelector('[data-recipient-switch]');
  expect(question()?.textContent).toContain('Writing to Frigga stops the reply in progress.');
  expect(streamRequest()[0].signal?.aborted).toBe(false);
  await complete({ latency_ms: 35 });
  await screen.findByText('Completed reply');
  // the reply ended with the question open: the recipient is unchanged, the outcome kept
  expect(to.value).toBe('jarvis');
  expect(question()?.getAttribute('data-recipient-switch-state')).toBe('ended');
  expect(readout()?.textContent).toMatch(/Turn duration.*35 ms/);
  // only the owner's answer changes who is written to
  fireEvent.click(screen.getByRole('button', { name: 'Write to Frigga' }));
  expect(to.value).toBe('frigga');
  expect(question()).toBeNull();
});

it('clears when entering demo mode and never presents an old live duration as demo evidence', async () => {
  await mount();
  await send('first'); await complete({ latency_ms: 35 });
  expect(readout()).toBeTruthy();
  turnDemoOn();
  expect(await screen.findByText(/Demo sample on screen/)).toBeTruthy();
  expect(readout()).toBeNull();
});

it('ignores a late live end after the user switches into demo mode', async () => {
  await mount();
  await send('pending live turn');
  turnDemoOn();
  expect(await screen.findByText(/Demo sample on screen/)).toBeTruthy();
  expect(readout()).toBeNull();
  await complete({ latency_ms: 810 });
  expect(readout()).toBeNull();
  expect(screen.queryByText('Completed reply')).toBeNull();
});

// H430 — the turn's recall indicator: one line per memory provider (long-term recall and
// Howard's message archive). recall-line-cases.json is shared with
// tests/test_h430_recall_indicator.py, which runs the same statuses and turns through
// recall_admission.describe_recall / describe_recalls: the two renderers cannot drift apart.
describe('recall indicator', () => {
  const status = (over: Record<string, unknown> = {}) => ({ schema: 'nerva.recall-status.v1',
    provider: 'long_term_memory', basis: 'this_turn', recalled: 2, withheld: {}, untrusted: 0, ...over });
  const archive = (over: Record<string, unknown> = {}) => status({ provider: 'message_archive', recalled: 5, ...over });
  const lines = () => Array.from(screen.getByLabelText('Memory recall').querySelectorAll('output'))
    .map(node => node.textContent);

  it.each(recallCases.statuses.map(c => [c.why, c] as const))('%s', (_why, c) => {
    const parsed = turnRecall(c.status);
    expect(parsed === null).toBe(c.why.startsWith('malformed'));
    expect(parsed ? recallLine(parsed) : '').toBe(c.line);
  });

  it.each(recallCases.turns.map(c => [c.why, c] as const))('turn: %s', (_why, c) => {
    const parsed = turnRecalls(c.recall);
    expect(parsed ? recallLines(parsed) : []).toEqual(c.lines);
  });

  it('shows each provider\'s last prefetch beside the turn, and nothing for a prefetch with nothing to say', () => {
    const { unmount } = render(<StatusStrip outcome={turnOutcome({ latency_ms: 5, recall: [archive(), status()] })} />);
    expect(lines()).toEqual(['🧠 Long-term memory — recalled 2 memories', '🧠 Message archive — recalled 5 memories']);
    unmount();
    render(<StatusStrip outcome={turnOutcome({ latency_ms: 5, recall: [status({ recalled: 0 })] })} />);
    expect(screen.queryByLabelText('Memory recall')).toBeNull();
  });

  it('drops a status that could carry memory text instead of rendering part of it', () => {
    expect(turnOutcome({ latency_ms: 5, recall: [{ ...status(), text: 'the dentist is on Tuesday' }] }))
      .toEqual({ latency_ms: 5 });
    expect(turnOutcome({ latency_ms: 5, recall: status() })).toEqual({ latency_ms: 5 });   // not a list
  });

  it('renders the stream end outcome in the mounted HUD turn', async () => {
    await mount('/v2/chat');
    await send('ce ai ales?');
    await complete({ latency_ms: 40, recall: [status({ withheld: { rejected_taint: 1 }, untrusted: 1 }),
      archive({ recalled: 2 })] });
    await screen.findByText('Completed reply');
    expect(turnDetails()).toBeTruthy();
    await screen.findByLabelText('Memory recall');
    expect(lines()).toEqual(['🧠 Long-term memory — recalled 2 memories (1 from an untrusted source), 1 withheld (taint: 1)',
      '🧠 Message archive — recalled 2 memories']);
  });

  /* Ledger (PHASE_B_PLAN.md §5.3): before any token arrives the working reply says the agent has
     started and names the model the progress event reported; the recall line belongs to the
     reply's Turn details, drawn once that reply is written (a reply in flight claims no outcome). */
  it('reports the live progress event before any token arrives, and the recall line in Turn details once written', async () => {
    await mount('/v2/chat');
    await send('ce ai ales?');
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
    await act(async () => streams.shift()!(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })));
    await act(async () => {
      controller.enqueue(new TextEncoder().encode(event({ type: 'start', agent: 'howard' })
        + event({ type: 'outcome_progress', outcome: { model: 'archive-model', recall: [archive({ recalled: 2 })] } })));
    });
    const working = document.querySelector('[data-turn="reply"][data-working]') as HTMLElement;
    expect(within(working).getByText('Started — waiting for the first words…')).toBeTruthy();
    expect(working.querySelector('[data-working-where]')?.textContent).toBe('model archive-model (reported)');
    expect(screen.queryByLabelText('Memory recall')).toBeNull();
    await act(async () => {
      controller.enqueue(new TextEncoder().encode(event({ type: 'end', text: 'Am ales.', session_id: 'topic_a',
        outcome: { latency_ms: 20, recall: [archive({ recalled: 2 })] } })));
      controller.close();
    });
    await screen.findByText('Am ales.');
    expect(turnDetails()).toBeTruthy();
    expect(lines()).toEqual(['🧠 Message archive — recalled 2 memories']);
  });
});
