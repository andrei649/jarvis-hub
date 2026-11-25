import React, { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SessionsModal } from '../../mobile/src/components/SessionsModal';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { records } from './support/storage';

const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
const other = { ...config, baseUrl: 'https://other.test', token: 'other' };
const hit = { session_id: 'source-7', turn: 4, role: 'assistant', timestamp: '2026-11-22T10:00:00Z', agent_id: 'frigga', snippet: 'redacted answer' };
const transcript = (content = 'The redacted answer is here') => ({ schema_version: 1, session_id: 'source-7', scope: 'retained_current_history', redacted: true,
  turn_count: 2, turns: [
    { turn: 3, role: 'user', content: 'Private question', timestamp: '2026-11-22T09:59:00Z', agent_id: null },
    { turn: 4, role: 'assistant', content, timestamp: hit.timestamp, agent_id: hit.agent_id, reference_revision: 'a'.repeat(64) },
  ] });
const response = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) });
const deferred = () => { let resolve!: (value: any) => void; const promise = new Promise<any>(r => { resolve = r; }); return { promise, resolve }; };
let fetchMock: ReturnType<typeof vi.fn>;
let resumed: ReturnType<typeof vi.fn>;
let closed: ReturnType<typeof vi.fn>;
let server: ReturnType<typeof useServer>;
let blockReason: string | null;
let sourceReason: string | null;
let stage: ReturnType<typeof vi.fn>;
let sourceEnabled = false;
let initialRecipient = 'frigga';
let startInMessages = false;
let setRecipient!: (value: string) => void;
function Probe() {
  server = useServer();
  const [visible, setVisible] = useState(true);
  const [recipient, chooseRecipient] = useState(initialRecipient);
  setRecipient = chooseRecipient;
  return <><button onClick={() => setVisible(false)}>Hide modal</button><button onClick={() => setVisible(true)}>Show modal</button>
    {server.ready && <SessionsModal visible={visible} onClose={() => { closed(); setVisible(false); }} onResumed={resumed}
      resumeBlockReason={() => blockReason} hasDraft recipient={recipient}
      onUseSource={sourceEnabled ? stage : undefined} sourceBlockReason={() => sourceReason}
      startInMessages={startInMessages} />}</>;
}
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);
const calls = (suffix: string) => fetchMock.mock.calls.filter(([url]) => String(url).includes(suffix));
const enterMessages = async () => { mount(); await screen.findByText('Recent chat'); fireEvent.click(screen.getByLabelText('Search messages')); };
const submit = (value: string) => { fireEvent.change(screen.getByLabelText('Search saved message text'), { target: { value } }); fireEvent.click(screen.getByLabelText('Submit message search')); };

beforeEach(() => {
  records.clear(); records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'message-search' }));
  resumed = vi.fn(); closed = vi.fn(); stage = vi.fn(() => true); blockReason = null; sourceReason = null;
  sourceEnabled = false; initialRecipient = 'frigga'; startInMessages = false;
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/sessions/search')) return response({ hits: [hit], truncated: false, stopped_by: null });
    if (url.includes('/transcript')) return response(transcript());
    if (url.endsWith('/sessions/resume')) return response({ ok: true, session: JSON.parse(String(init?.body)).session_id, turns: [] });
    return response({ sessions: [{ id: 'recent', title: 'Recent chat' },
      { id: 'source-7', title: 'Source conversation' }], next_cursor: null });
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('finds saved messages only on submit, reviews the exact redacted turn, then re-verifies before explicit resume', async () => {
  await enterMessages();
  expect(screen.getByLabelText('Browse sessions')).toBeTruthy();
  expect(screen.queryByText('Recent chat')).toBeNull();
  fireEvent.change(screen.getByLabelText('Search saved message text'), { target: { value: '  redacted  ' } });
  expect(calls('/sessions/search')).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('Submit message search'));
  await screen.findByText('redacted answer');
  expect(screen.getByText('Source conversation')).toBeTruthy();
  expect(JSON.parse(String(calls('/sessions/search')[0][1]?.body))).toEqual({ query: 'redacted', limit: 20 });
  expect(calls('/sessions/resume')).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  expect(screen.getByText('Source conversation')).toBeTruthy();
  expect(screen.getByText('Session source-7')).toBeTruthy();
  expect(screen.queryByLabelText('Search saved message text')).toBeNull();
  expect(JSON.parse(screen.getByLabelText('Back to message results').getAttribute('data-native-style') || '{}').minHeight).toBeGreaterThanOrEqual(44);
  expect(JSON.parse(screen.getByLabelText('Continue session source-7').getAttribute('data-native-style') || '{}').minHeight).toBeGreaterThanOrEqual(44);
  expect(screen.queryByText('Private question')).toBeNull();
  expect(screen.getByText(/typed message will stay/)).toBeTruthy();
  expect(calls('/sessions/resume')).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('Continue session source-7'));
  await waitFor(() => expect(resumed).toHaveBeenCalledWith('source-7', []));
  expect(calls('/transcript')).toHaveLength(2);
  expect(JSON.parse(String(calls('/sessions/resume')[0][1]?.body))).toEqual({ session_id: 'source-7' });
  expect(closed).toHaveBeenCalledOnce();
});

it('rejects a changed suffix after the search snippet at Continue and keeps search available', async () => {
  let reads = 0;
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/sessions/search') ? response({ hits: [hit], truncated: false, stopped_by: null })
    : url.includes('/transcript') ? response(transcript(++reads === 1 ? 'The redacted answer is here' : 'The redacted answer is here, but the ending changed'))
      : response({ sessions: [{ id: 'recent', title: 'Recent chat' }], next_cursor: null }));
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  fireEvent.click(screen.getByLabelText('Continue session source-7'));
  await screen.findByText(/saved turn changed or cannot be verified/i);
  expect(calls('/sessions/resume')).toHaveLength(0);
  expect(screen.getByLabelText('Submit message search')).toBeTruthy();
});

it('fences old search responses after query edits and connection changes', async () => {
  const pending = deferred();
  fetchMock.mockImplementation(async (url: string) => url.startsWith('https://hub.test/') && url.endsWith('/sessions/search') ? pending.promise
    : url.endsWith('/sessions/search') ? response({ hits: [], truncated: false, stopped_by: null })
      : response({ sessions: [{ id: 'recent', title: 'Recent chat' }], next_cursor: null }));
  await enterMessages(); submit('first');
  fireEvent.change(screen.getByLabelText('Search saved message text'), { target: { value: 'second' } });
  await act(async () => pending.resolve(response({ hits: [hit], truncated: false, stopped_by: null })));
  expect(screen.queryByText('redacted answer')).toBeNull();
  await act(async () => server.updateConfig(other));
  expect(screen.queryByLabelText('Search saved message text')).toBeNull();
  fireEvent.click(screen.getByLabelText('Search messages'));
  expect((screen.getByLabelText('Search saved message text') as HTMLInputElement).value).toBe('');
  expect(screen.queryByText('redacted answer')).toBeNull();
});

it('blocks continuation before and after the read, and ignores duplicate taps', async () => {
  const pending = deferred();
  let reads = 0;
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/sessions/search') ? response({ hits: [hit], truncated: false, stopped_by: null })
    : url.includes('/transcript') ? ++reads === 1 ? response(transcript()) : pending.promise
      : url.endsWith('/sessions/resume') ? response({ ok: true, session: 'source-7', turns: [] })
        : response({ sessions: [{ id: 'recent', title: 'Recent chat' }], next_cursor: null }));
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  blockReason = 'Finish the active reply first.';
  fireEvent.click(screen.getByLabelText('Continue session source-7'));
  await screen.findByText('Finish the active reply first.');
  expect(reads).toBe(1);
  blockReason = null;
  const button = screen.getByLabelText('Continue session source-7');
  act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  expect(reads).toBe(2);
  blockReason = 'Reply started during verification.';
  await act(async () => pending.resolve(response(transcript())));
  await screen.findByText('Reply started during verification.');
  expect(calls('/sessions/resume')).toHaveLength(0);
});

it('shows the reviewed source in place of results and clears search on Close history', async () => {
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  expect(screen.queryByText('redacted answer')).toBeNull();
  fireEvent.click(screen.getByLabelText('Back to message results'));
  expect(screen.getByLabelText('Search saved message text')).toBeTruthy();
  expect(screen.getByText('redacted answer')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Close history'));
  expect(closed).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByText('Show modal'));
  await screen.findByText('Recent chat');
  fireEvent.click(screen.getByLabelText('Search messages'));
  expect((screen.getByLabelText('Search saved message text') as HTMLInputElement).value).toBe('');
  expect(screen.queryByText('redacted answer')).toBeNull();
});

it('distinguishes same-agent conversations and gives new controls full touch targets', async () => {
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/sessions/search')
    ? response({ hits: [hit, { ...hit, session_id: 'other-8', snippet: 'another answer' }], truncated: false, stopped_by: null })
    : response({ sessions: [{ id: 'recent', title: 'Recent chat' }, { id: 'source-7', title: 'Source conversation' },
      { id: 'other-8', title: 'Other conversation' }], next_cursor: null }));
  await enterMessages();
  const touchHeight = (label: string) => JSON.parse(screen.getByLabelText(label).getAttribute('data-native-style') || '{}').minHeight;
  expect(touchHeight('Close history')).toBeGreaterThanOrEqual(44);
  expect(touchHeight('Search messages')).toBeGreaterThanOrEqual(44);
  submit('answer');
  await screen.findByText('another answer');
  expect(screen.getByText('Source conversation')).toBeTruthy();
  expect(screen.getByText('Other conversation')).toBeTruthy();
  expect(touchHeight('Submit message search')).toBeGreaterThanOrEqual(44);
  expect(touchHeight('Review saved turn 5 in session source-7')).toBeGreaterThanOrEqual(44);
});

it('leaves the reviewed source and search available when the hub refuses resume', async () => {
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/sessions/search') ? response({ hits: [hit], truncated: false, stopped_by: null })
    : url.includes('/transcript') ? response(transcript())
      : url.endsWith('/sessions/resume') ? response({ ok: false, session: 'source-7', turns: [] })
        : response({ sessions: [{ id: 'recent', title: 'Recent chat' }], next_cursor: null }));
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  fireEvent.click(screen.getByLabelText('Continue session source-7'));
  await screen.findByText('Could not reopen this conversation. Try again.');
  expect(resumed).not.toHaveBeenCalled(); expect(closed).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Back to message results')).toBeTruthy();
});

it('stages only an exact passage after a fresh source read, without resuming or sending', async () => {
  sourceEnabled = true;
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  expect(screen.getByText(/next message to frigga/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Exact passage'), { target: { value: 'redacted answer' } });
  fireEvent.click(screen.getByLabelText('Use passage in next message'));
  await waitFor(() => expect(stage).toHaveBeenCalledWith({ reference: {
    session_id: 'source-7', turn: 4, revision: 'a'.repeat(64), excerpt: 'redacted answer', allow_cloud: false,
  }, role: 'assistant' }));
  expect(calls('/transcript')).toHaveLength(2);
  expect(calls('/sessions/resume')).toHaveLength(0);
  expect(closed).toHaveBeenCalledOnce();
});

it('requires explicit cloud consent and retains review when a source changes', async () => {
  sourceEnabled = true;
  initialRecipient = 'athena';
  let reads = 0;
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/sessions/search') ? response({ hits: [hit], truncated: false, stopped_by: null })
    : url.includes('/transcript') ? response(transcript(++reads === 1 ? 'The redacted answer is here' : 'The redacted answer changed'))
      : response({ sessions: [{ id: 'recent', title: 'Recent chat' }], next_cursor: null }));
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  fireEvent.click(screen.getByLabelText('Use entire message'));
  fireEvent.click(screen.getByLabelText('Use passage in next message'));
  await screen.findByText(/Allow this passage for athena before using it/);
  expect(reads).toBe(1);
  expect(screen.getByLabelText('Allow this passage for athena').getAttribute('aria-checked')).toBe('false');
  fireEvent.click(screen.getByLabelText('Allow this passage for athena'));
  expect(screen.getByLabelText('Allow this passage for athena').getAttribute('aria-checked')).toBe('true');
  fireEvent.click(screen.getByLabelText('Use passage in next message'));
  await screen.findByText(/saved turn changed or cannot be verified/i);
  expect(stage).not.toHaveBeenCalled();
  expect(calls('/sessions/resume')).toHaveLength(0);
});

it('invalidates the reviewed passage when the recipient changes during verification', async () => {
  sourceEnabled = true;
  const pending = deferred(); let reads = 0;
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/sessions/search') ? response({ hits: [hit], truncated: false, stopped_by: null })
    : url.includes('/transcript') ? ++reads === 1 ? response(transcript()) : pending.promise
      : response({ sessions: [{ id: 'recent', title: 'Recent chat' }], next_cursor: null }));
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  fireEvent.click(screen.getByLabelText('Use entire message'));
  fireEvent.click(screen.getByLabelText('Use passage in next message'));
  act(() => setRecipient('athena'));
  await act(async () => pending.resolve(response(transcript())));
  expect(stage).not.toHaveBeenCalled();
  expect(screen.queryByLabelText('Use passage in next message')).toBeNull();
});

it('blocks invalid passages and busy staging, and ignores an old response after account change', async () => {
  sourceEnabled = true;
  const pending = deferred(); let reads = 0;
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/sessions/search') ? response({ hits: [hit], truncated: false, stopped_by: null })
    : url.includes('/transcript') ? ++reads === 1 ? response(transcript()) : pending.promise
      : response({ sessions: [{ id: 'recent', title: 'Recent chat' }], next_cursor: null }));
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  fireEvent.change(screen.getByLabelText('Exact passage'), { target: { value: 'not in the source' } });
  fireEvent.click(screen.getByLabelText('Use passage in next message'));
  await screen.findByText(/Choose an exact passage/);
  expect(reads).toBe(1);
  fireEvent.change(screen.getByLabelText('Exact passage'), { target: { value: 'redacted answer' } });
  sourceReason = 'Finish the active reply first.';
  fireEvent.click(screen.getByLabelText('Use passage in next message'));
  await screen.findByText('Finish the active reply first.');
  expect(reads).toBe(1);
  sourceReason = null;
  fireEvent.click(screen.getByLabelText('Use passage in next message'));
  expect(reads).toBe(2);
  await act(async () => server.updateConfig(other));
  await act(async () => pending.resolve(response(transcript())));
  expect(stage).not.toHaveBeenCalled();
  expect(closed).not.toHaveBeenCalled();
});

it('rechecks source availability after the transcript read before staging', async () => {
  sourceEnabled = true;
  const pending = deferred(); let reads = 0;
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/sessions/search') ? response({ hits: [hit], truncated: false, stopped_by: null })
    : url.includes('/transcript') ? ++reads === 1 ? response(transcript()) : pending.promise
      : response({ sessions: [{ id: 'recent', title: 'Recent chat' }], next_cursor: null }));
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByText('The redacted answer is here');
  fireEvent.change(screen.getByLabelText('Exact passage'), { target: { value: 'redacted answer' } });
  fireEvent.click(screen.getByLabelText('Use passage in next message'));
  sourceReason = 'Reply started during verification.';
  await act(async () => pending.resolve(response(transcript())));
  await screen.findByText('Reply started during verification.');
  expect(stage).not.toHaveBeenCalled();
  expect(closed).not.toHaveBeenCalled();
});

it('opens directly on message search for review again without searching or resuming', async () => {
  startInMessages = true;
  mount();
  await screen.findByLabelText('Search saved message text');
  expect(calls('/sessions/search')).toHaveLength(0);
  expect(calls('/sessions/resume')).toHaveLength(0);
  expect(screen.queryByText('Recent chat')).toBeNull();
});

it('keeps oversized whole messages visible without loading an unsendable passage', async () => {
  sourceEnabled = true;
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/sessions/search') ? response({ hits: [hit], truncated: false, stopped_by: null })
    : url.includes('/transcript') ? response(transcript('The redacted answer ' + 'x'.repeat(8100)))
      : response({ sessions: [{ id: 'recent', title: 'Recent chat' }], next_cursor: null }));
  await enterMessages(); submit('redacted'); await screen.findByText('redacted answer');
  fireEvent.click(screen.getByLabelText('Review saved turn 5 in session source-7'));
  await screen.findByLabelText('Use entire message');
  fireEvent.click(screen.getByLabelText('Use entire message'));
  await screen.findByText(/Whole message exceeds 8,000 UTF-8 bytes/);
  expect((screen.getByLabelText('Exact passage') as HTMLInputElement).value).toBe('');
  expect(screen.getByText(/^The redacted answer x/)).toBeTruthy();
  expect(stage).not.toHaveBeenCalled();
});

