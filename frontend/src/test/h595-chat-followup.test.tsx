import React from 'react';
import { webcrypto } from 'node:crypto';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
vi.mock('../modes3', async () => {
  const { Conversation, InputBar } = await import('../cockpit');
  return { ChatMode: (props: any) => <><Conversation {...props} /><InputBar onSubmit={props.onSubmit} t={props.t} /></> };
});
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
  let releaseOld!: (value: any) => void;
  cognition.mockImplementationOnce(() => new Promise(resolve => { releaseOld = resolve; }));
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
  expect(screen.getByRole('button', { name: 'Stop generating' })).toBeTruthy();
  act(() => streams[1].event({ type: 'end', text: 'Second final', agent: 'jarvis', model_calls: [{provider:'openai',model:'second-model'}] }));
  await act(async () => releaseOld({ decision: { agents_selected: ['jarvis'], local: true }, plugins: ['old-plugin'] }));
  expect(screen.getByText('First final').closest('.msg.agent')?.querySelector('.prov-chip')?.textContent).toContain('ollama / first-model');
  expect(screen.getByText('Second final').closest('.msg.agent')?.querySelector('.prov-chip')?.textContent).toContain('openai / second-model');
  expect(screen.getByText('First final').closest('.msg.agent')?.textContent).not.toContain('old-plugin');
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
  const mixed = screen.getByText('Mixed final').closest('.msg.agent')!;
  expect(mixed.querySelector('.prov-chip')?.textContent).toContain('ollama / local-model · openai / remote-model');
  expect(screen.getByText('No receipt final').closest('.msg.agent')?.querySelector('.prov-chip')).toBeNull();
  fireEvent.click(mixed.querySelector('.prov-chip')!);
  expect(screen.getByRole('dialog', { name: 'MODELS CALLED' })).toBeTruthy();
  expect(screen.getByText(/Physical execution location was not reported/)).toBeTruthy();
  fireEvent.keyDown(screen.getByRole('dialog', { name: 'MODELS CALLED' }), {key:'Escape'});
  expect(screen.queryByRole('dialog', { name: 'MODELS CALLED' })).toBeNull();
});

it('does not render the legacy demo provenance as measured model calls', async () => {
  render(<Conversation messages={[{role:'agent',who:'jarvis',text:'Sample reply',prov:{
    agents:['jarvis'],plugins:['gmail'],local:true,conf:0.9,
  }}]} thinking={null} onProv={vi.fn()} />);
  expect(screen.getByText('Sample reply')).toBeTruthy();
  expect(document.querySelector('.prov-chip')).toBeNull();
});

it('Stop aborts every pending stream and settles the voice turn', async () => {
  render(<App />);
  await waitFor(() => expect(voiceTurn).toBeTruthy());
  let voiceReply!: Promise<string>;
  act(() => { voiceReply = voiceTurn!('Spoken request'); });
  await send('Typed follow-up');
  await waitFor(() => expect(streams).toHaveLength(2));
  expect(await voiceTurn!('Unexpected voice overlap')).toBe('');
  fireEvent.click(screen.getByRole('button', { name: 'Stop generating' }));
  expect(streams.every(stream => stream.signal.aborted)).toBe(true);
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
  await act(async () => streams[0].resolve());
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Stop generating' })).toBeNull());
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
  act(() => streams[0].event({ type: 'end', agent: 'jarvis', ...(final === undefined ? {} : { text: final }) }));
  if (keepsDraft) {
    expect(screen.getByText('Draft answer')).toBeTruthy();
  } else {
    expect(screen.queryByText('Draft answer')).toBeNull();
  }
  if (expected) expect(screen.getByText(expected)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Stop generating' })).toBeNull();
});
