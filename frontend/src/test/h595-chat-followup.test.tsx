import React from 'react';
import { webcrypto } from 'node:crypto';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';
import { Conversation } from '../cockpit';

type Stream = { body: { message: string; agent: string }; event: (frame: any) => void; signal: AbortSignal; resolve: () => void };
const streams: Stream[] = [];
let voiceTurn: ((text: string) => Promise<string>) | undefined;
const cognition = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock('../voice', () => ({ useVoice: ({ onTurn }: any) => { voiceTurn = onTurn; return { active: false, toggle: () => {} }; } }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../api/loaders', () => ({ loadJarvisData: async () => ({}), createLatestRefreshRunner: () => ({ refresh: () => {}, stop: () => {} }) }));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../gap', () => ({ FirstRunGate: () => null }));
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiGet: (path: string) => path === '/api/cognition' ? cognition() : Promise.resolve({}), postStream: (_path: string, body: Stream['body'], event: Stream['event'], opts: { signal: AbortSignal }) => new Promise<void>(resolve => {
    streams.push({ body, event, signal: opts.signal, resolve });
  }) };
});

beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto);
  localStorage.clear();
  history.replaceState(null, '', '/v2/chat?demo=1');
  streams.length = 0;
  cognition.mockReset();
  cognition.mockResolvedValue({});
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

/* The Ledger conversation (PHASE_B_PLAN.md §5.3): turns carry data-turn, a finished reply's
   footnote says where it was sent, and the working reply's one control stops the turn ("Stop the
   replies" when more than one is in flight, because the stop ends them all). */
const STOP = /^Stop (this reply|the replies)$/;
const reply = (text: string) => screen.getByText(text).closest('[data-turn="reply"]') as HTMLElement;
const footnote = (text: string) => reply(text).querySelector('[data-footnote]') as HTMLElement | null;

async function send(text: string) {
  const input = await waitFor(() => {
    const el = document.querySelector<HTMLInputElement>('[data-composer="1"]');
    expect(el).toBeTruthy();
    return el!;
  });
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: 'Enter' });
}

it('sends a typed follow-up from the actual composer while the first stream is pending', async () => {
  render(<App />);
  await send('Run the sample');
  await waitFor(() => expect(streams).toHaveLength(1));
  act(() => {
    streams[0].event({ type: 'start', agent: 'jarvis' });
    streams[0].event({ type: 'token', text: 'Running' });
  });
  await send('Pause and inspect');
  await waitFor(() => expect(streams).toHaveLength(2));
  expect(streams.map(stream => stream.body.message)).toEqual(['Run the sample', 'Pause and inspect']);
  expect(screen.getByText('Running')).toBeTruthy();
  expect(screen.getByText('Pause and inspect')).toBeTruthy();
});

it('keeps both replies in their own bubbles when the older stream finishes later', async () => {
  render(<App />);
  await send('First task');
  await send('Second task');
  await waitFor(() => expect(streams).toHaveLength(2));
  act(() => {
    streams[1].event({ type: 'start', agent: 'jarvis' });
    streams[1].event({ type: 'token', text: 'Second partial' });
    streams[0].event({ type: 'start', agent: 'jarvis' });
    streams[0].event({ type: 'token', text: 'First partial' });
    streams[0].event({ type: 'end', text: 'First final', agent: 'jarvis', model_calls: [{provider:'ollama',model:'first-model'}] });
  });
  expect(screen.getByText('First final')).toBeTruthy();
  expect(screen.getByText('Second partial')).toBeTruthy();
  // the second reply is still being written, in its own turn, with the one stop control
  expect(reply('Second partial').hasAttribute('data-working')).toBe(true);
  expect(reply('First final').hasAttribute('data-working')).toBe(false);
  expect(screen.getByRole('button', { name: 'Stop this reply' })).toBeTruthy();
  act(() => streams[1].event({ type: 'end', text: 'Second final', agent: 'jarvis', model_calls: [{provider:'openai',model:'second-model'}] }));
  // A finished turn asks no cognition snapshot: the cockpit trace it fed was retired (PHASE_B_PLAN.md
  // §2.4), so a late snapshot from the older turn has nothing to land on.
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(cognition).not.toHaveBeenCalled();
  expect(reply('First final')).not.toBe(reply('Second final'));
  expect(footnote('First final')?.textContent).toContain('Sent to Ollama on this computer · first-model');
  expect(footnote('First final')?.textContent).not.toContain('second-model');
  expect(footnote('Second final')?.textContent).toContain('Sent to OpenAI (cloud) · second-model');
  expect(footnote('Second final')?.textContent).not.toContain('first-model');
  expect(reply('First final').textContent).not.toContain('old-plugin');
});

it('shows only a validated receipt, even when usage is mixed or incomplete', async () => {
  render(<App />);
  await send('Mixed call');
  await send('No receipt');
  await waitFor(() => expect(streams).toHaveLength(2));
  act(() => {
    streams[0].event({ type:'end', text:'Mixed final', model_calls:[
      {provider:'ollama',model:'local-model'}, {provider:'openai',model:'remote-model'},
    ], usage:{api_calls:2,breakdown:[{provider:'ollama',model:'local-model',input_tokens:null},
      {provider:'openai',model:'remote-model',input_tokens:10}]} });
    streams[1].event({ type:'end', text:'No receipt final', usage:{api_calls:1,breakdown:[{provider:'openai',model:'unattributed'}]} });
  });
  // the footnote names the least private pair and counts the rest; the rest open the provenance modal
  const mixed = footnote('Mixed final')!;
  expect(mixed.getAttribute('data-marker')).toBe('cloud');
  expect(mixed.textContent).toContain('Sent to OpenAI (cloud) · remote-model');
  const none = footnote('No receipt final')!;
  expect(none.getAttribute('data-marker')).toBe('notReported');
  expect(none.textContent).toContain('Where it ran: not reported');
  expect(within(none).queryByRole('button')).toBeNull();
  fireEvent.click(within(mixed).getByRole('button', { name: 'Show all 2 model calls' }));
  const dialog = screen.getByRole('dialog', { name: 'MODELS CALLED' });
  expect(within(dialog).getAllByRole('listitem').map(item => item.textContent)).toEqual(['ollama / local-model', 'openai / remote-model']);
  expect(screen.getByText(/Physical execution location was not reported/)).toBeTruthy();
  fireEvent.keyDown(dialog, {key:'Escape'});
  expect(screen.queryByRole('dialog', { name: 'MODELS CALLED' })).toBeNull();
});

it('does not render the legacy demo provenance as measured model calls', async () => {
  const message = {role:'agent',who:'jarvis',text:'Sample reply',prov:{
    agents:['jarvis'],plugins:['gmail'],local:true,conf:0.9,
  }};
  const view = render(<Conversation messages={[message]} thinking={null} onProv={vi.fn()} />);
  expect(screen.getByText('Sample reply')).toBeTruthy();
  expect(document.querySelector('.prov-chip')).toBeNull();
  view.unmount();
  // the Ledger reply's footnote: no measured pair, so "not reported", never a model or a local claim
  render(<Conversation messages={[message]} thinking={null} onProv={vi.fn()} variant="chat" turns={[]} />);
  const note = footnote('Sample reply')!;
  expect(note.getAttribute('data-marker')).toBe('notReported');
  expect(note.textContent).toContain('Where it ran: not reported');
  expect(within(note).queryByRole('button')).toBeNull();
});

it('Stop aborts every pending stream and settles the voice turn', async () => {
  render(<App />);
  await waitFor(() => expect(voiceTurn).toBeTruthy());
  let voiceReply!: Promise<string>;
  act(() => { voiceReply = voiceTurn!('Spoken request'); });
  await send('Typed follow-up');
  await waitFor(() => expect(streams).toHaveLength(2));
  expect(await voiceTurn!('Unexpected voice overlap')).toBe('');
  // two replies in flight: the one control says it stops them all
  expect(screen.getAllByRole('button', { name: STOP })).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Stop the replies' }));
  expect(streams.every(stream => stream.signal.aborted)).toBe(true);
  expect(screen.queryByRole('button', { name: STOP })).toBeNull();
  await expect(voiceReply).resolves.toBe('');
  act(() => {
    streams[0].event({ type: 'end', text: 'Stale voice reply' });
    streams[1].event({ type: 'end', text: 'Stale typed reply' });
  });
  expect(screen.queryByText('Stale voice reply')).toBeNull();
  expect(screen.queryByText('Stale typed reply')).toBeNull();
  await send('Fresh request');
  await waitFor(() => expect(streams).toHaveLength(3));
});

it('rejects rapid identical submissions and aborts both streams on unmount', async () => {
  const view = render(<App />);
  await send('Same request');
  await send('Same request');
  expect(streams).toHaveLength(1);
  await send('Distinct follow-up');
  await waitFor(() => expect(streams).toHaveLength(2));
  view.unmount();
  expect(streams.every(stream => stream.signal.aborted)).toBe(true);
});

it('keeps a pending answer attached to its original stream after a follow-up', async () => {
  const answers: Array<{ path: string; signal: AbortSignal }> = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: any) => {
    if (path.includes('/chat/pending/')) answers.push({ path, signal: options.signal });
    return new Response(JSON.stringify({ ok: true, status: 'resolved' }));
  }));
  render(<App />);
  await send('Ask a question');
  const id = 'a'.repeat(32);
  act(() => streams[0].event({ type: 'clarify', id, question: 'Select the workspace', choices: ['Local', 'Remote'], multi_select: false }));
  await screen.findByRole('dialog', { name: 'Select the workspace' });
  await send('Follow-up while waiting');
  await waitFor(() => expect(streams).toHaveLength(2));
  fireEvent.click(screen.getByRole('button', { name: 'Local' }));
  await waitFor(() => expect(answers).toHaveLength(1));
  expect(answers[0].path).toContain(id);
  expect(answers[0].signal).toBe(streams[0].signal);
});

it('releases a stream whose transport closes without an end event', async () => {
  render(<App />);
  await send('First request');
  act(() => streams[0].event({ type: 'token', text: 'Partial reply' }));
  expect(screen.getByRole('button', { name: STOP })).toBeTruthy();
  await act(async () => streams[0].resolve());
  await waitFor(() => expect(screen.queryByRole('button', { name: STOP })).toBeNull());
  expect(screen.getByText('Partial reply')).toBeTruthy();
  await send('Next request');
  await waitFor(() => expect(streams).toHaveLength(2));
});

it.each([
  { final: 'Final answer', expected: 'Final answer', keepsDraft: false },
  { final: '', expected: '', keepsDraft: false },
  { final: undefined, expected: 'Draft answer', keepsDraft: true },
])('uses the authoritative end text even when it is empty: $final', async ({ final, expected, keepsDraft }) => {
  render(<App />);
  await send('Explain this');
  await waitFor(() => expect(streams).toHaveLength(1));
  act(() => {
    streams[0].event({ type: 'start', agent: 'jarvis' });
    streams[0].event({ type: 'token', text: 'Draft answer' });
  });
  expect(screen.getByText('Draft answer')).toBeTruthy();
  expect(screen.getByRole('button', { name: STOP })).toBeTruthy();
  act(() => streams[0].event({ type: 'end', agent: 'jarvis', ...(final === undefined ? {} : { text: final }) }));
  if (keepsDraft) {
    expect(screen.getByText('Draft answer')).toBeTruthy();
  } else {
    expect(screen.queryByText('Draft answer')).toBeNull();
  }
  if (expected) expect(screen.getByText(expected)).toBeTruthy();
  expect(screen.queryByRole('button', { name: STOP })).toBeNull();
});
