import { beforeEach, expect, jest, test } from '@jest/globals';
import { Conversation } from '../conversation';
import { resumeSession, streamChat, type StreamHandlers } from '../../api/client';
import { loadConversation, saveConversation } from '../../storage/chat';

jest.mock('../../api/client', () => ({
  ...jest.requireActual<typeof import('../../api/client')>('../../api/client'),
  streamChat: jest.fn(), resumeSession: jest.fn(),
}));
jest.mock('../../storage/chat', () => ({ loadConversation: jest.fn(), saveConversation: jest.fn() }));

const config = { baseUrl: 'http://hub', token: 'owner', adminToken: '' };
const turns = [{ role: 'user', content: 'Earlier question' },
  { role: 'assistant', content: 'Earlier answer', agent_id: 'howard' }];
let handlers: StreamHandlers;
let cancel: jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  cancel = jest.fn();
  jest.mocked(loadConversation).mockResolvedValue({ sessionId: null, messages: [] });
  jest.mocked(saveConversation).mockResolvedValue();
  jest.mocked(streamChat).mockImplementation((_c, _m, _a, h) => { handlers = h; return cancel; });
});

async function opened(serverConfig = config) {
  const chat = new Conversation(serverConfig, 'connection-1', jest.fn());
  await chat.hydrate();
  return chat;
}

test('resumed history sends the exact selected session on every subsequent turn', async () => {
  const chat = await opened();
  chat.resume('archived-session', turns);
  expect(chat.state.messages[1].agent).toBe('howard');
  chat.send('Continue', 'jarvis');
  expect(streamChat).toHaveBeenLastCalledWith(config, 'Continue', 'jarvis', expect.any(Object), 'archived-session', undefined);
  handlers.onDone('Next answer', 'archived-session');
  chat.send('And then?', 'jarvis');
  expect(streamChat).toHaveBeenLastCalledWith(config, 'And then?', 'jarvis', expect.any(Object), 'archived-session', undefined);
});

test('keeps measured activity on its own reply across turns and native history restore', async () => {
  const chat = await opened();
  const tools = { proposed: 0, queued: 0, executed: 0, failures: 0, basis: 'observed' as const };
  const text = '[Invitation sent via WhatsApp bridge]';
  chat.send('Draft an invitation', 'frigga');
  handlers.onDone(text, 'thread', { tools });
  chat.send('Another draft', 'frigga');
  handlers.onDone('Second draft', 'thread');
  expect(chat.state.messages.map(m => m.toolActivity)).toEqual([undefined, tools, undefined, undefined]);
  expect(chat.state.messages[1].text).toBe(text);
  const unknown = { proposed: 2, queued: 1, executed: null, failures: null, basis: 'unknown' as const };
  chat.resume('thread', [
    { role: 'user', content: text, tool_activity: tools },
    { role: 'assistant', content: text, agent_id: 'frigga', tool_activity: unknown },
    { role: 'assistant', content: text, foreign_origin: 'codex', tool_activity: tools },
    { role: 'assistant', content: text, tainted: true, tool_activity: tools },
    { role: 'assistant', content: text },
  ]);
  expect(chat.state.messages.map(m => m.toolActivity)).toEqual([undefined, unknown, undefined, undefined, undefined]);
});

test('first response binds and persists the actual server session', async () => {
  const chat = await opened();
  chat.send('Hello', 'jarvis');
  handlers.onDone('Hello back', 'server-session');
  expect(chat.state.sessionId).toBe('server-session');
  expect(saveConversation).toHaveBeenLastCalledWith('connection-1', expect.objectContaining({ sessionId: 'server-session' }));
  expect(chat.state.messages.at(-1)?.pending).toBe(false);
  expect(chat.state.messages.at(-1)?.completed).toBe(true);
});

test('an incomplete EOF cannot make a partial answer note eligible', async () => {
  const chat = await opened();
  chat.send('Question', 'jarvis');
  handlers.onToken('Partial');
  handlers.onDone('', undefined);
  expect(chat.state.messages.at(-1)?.completed).toBeUndefined();
  chat.send('Another question', 'jarvis');
  handlers.onToken('Real answer');
  handlers.onDone('', 'session');
  expect(chat.state.messages.at(-1)?.completed).toBe(true);
});

test('explicit answer end without session ID remains note eligible, but commands and system do not', async () => {
  const chat = await opened();
  chat.send('Question', 'jarvis');
  handlers.onDone('Answer', undefined);
  expect(chat.state.messages.at(-1)?.completed).toBe(true);
  chat.send('  /help', 'jarvis');
  handlers.onDone('Help text', undefined);
  expect(chat.state.messages.at(-1)?.completed).toBeUndefined();
  chat.send('Question', 'jarvis');
  handlers.onStart?.('system');
  handlers.onDone('System response', undefined);
  expect(chat.state.messages.at(-1)?.completed).toBeUndefined();
});

test('selected vault excerpts travel beside the message and never enter conversation state', async () => {
  const chat = await opened();
  const excerpts = [{ name: 'note.md', text: 'private excerpt' }];
  expect(chat.send('Question', 'jarvis', undefined, excerpts)).toBe(true);
  expect(streamChat).toHaveBeenLastCalledWith(config, 'Question', 'jarvis', expect.any(Object), null,
    undefined, excerpts);
  expect(chat.state.messages[0].text).toBe('Question');
  handlers.onDone('Answer', 'session');
  expect(JSON.stringify(chat.state)).not.toContain('private excerpt');
  expect(JSON.stringify(jest.mocked(saveConversation).mock.calls)).not.toContain('private excerpt');
});

const history = { reference: { session_id: 'source', turn: 2, revision: 'a'.repeat(64),
  excerpt: 'private source excerpt', allow_cloud: false }, role: 'assistant' as const };
const historyConfig = { ...config, adminToken: 'owner-secret' };

test('selected history accepts only an explicit ACK for the current destination', async () => {
  const chat = await opened(historyConfig);
  chat.resume('destination', turns);
  const result = jest.fn();
  expect(chat.send('Follow up', 'frigga', undefined, undefined, history, result)).toBe(true);
  expect(streamChat).toHaveBeenLastCalledWith(historyConfig, 'Follow up', 'frigga', expect.any(Object),
    'destination', undefined, undefined, history.reference);
  expect(JSON.stringify(chat.state)).not.toContain(history.reference.excerpt);
  handlers.onDone('Answer', 'destination', undefined, undefined, undefined, true);
  expect(result).toHaveBeenCalledWith(true);
  expect(chat.state.messages.at(-2)?.historySource).toEqual({ session_id: 'source', turn: 2,
    revision: 'a'.repeat(64), role: 'assistant' });
  expect(JSON.stringify(jest.mocked(saveConversation).mock.calls)).not.toContain(history.reference.excerpt);
});

test('native session resume projects source receipts only from trusted user turns', async () => {
  const chat = await opened();
  const source = { session_id: 'source', turn: 2, revision: 'a'.repeat(64), role: 'assistant' };
  chat.resume('destination', [
    { role: 'user', content: 'Follow up', history_source: { ...source, excerpt: 'private' } },
    { role: 'assistant', content: 'Answer', history_source: source },
    { role: 'user', content: 'Imported', history_source: source, foreign_origin: 'other' },
    { role: 'user', content: 'Malformed', history_source: { ...source, revision: 'bad' } },
  ]);
  expect(chat.state.messages.map(m => m.historySource)).toEqual([source, undefined, undefined, undefined]);
  expect(JSON.stringify(jest.mocked(saveConversation).mock.calls)).not.toContain('private');
});

test.each([
  [undefined, undefined], [false, 'destination'], [true, 'other-destination'], [true, undefined],
] as const)('unconfirmed history ACK %s / %s restores the draft without a saved bubble', async (used, id) => {
  const chat = await opened(historyConfig);
  chat.resume('destination', turns);
  const before = chat.state.messages;
  const result = jest.fn();
  expect(chat.send('Keep draft', 'frigga', undefined, undefined, history, result)).toBe(true);
  handlers.onToken('Partial');
  handlers.onDone('Answer', id, undefined, undefined, undefined, used);
  expect(result).toHaveBeenCalledTimes(1);
  expect(result).toHaveBeenCalledWith(false);
  expect(chat.state.messages).toEqual(before);
  expect(chat.state.sessionId).toBe('destination');
  expect(jest.mocked(saveConversation).mock.calls.at(-1)?.[1].messages).toEqual(before);
});

test('history validation, busy turns, transport failure and stop preserve unsent text', async () => {
  const chat = await opened(historyConfig);
  const result = jest.fn();
  expect(chat.send('/new', 'frigga', undefined, undefined, history, result)).toBe(false);
  expect(chat.send('Follow up', 'jarvis', undefined, undefined, history, result)).toBe(false);
  expect(chat.send('Follow up', 'frigga', undefined, [{ name: 'a', text: 'b' }], history, result)).toBe(false);
  expect(result).toHaveBeenCalledTimes(3);
  expect(streamChat).not.toHaveBeenCalled();
  expect(chat.send('Follow up', 'frigga', undefined, undefined, history, result)).toBe(true);
  expect(chat.send('Busy', 'frigga', undefined, undefined, history, result)).toBe(false);
  handlers.onError('Network failed');
  expect(chat.state.messages).toEqual([]);
  expect(result).toHaveBeenCalledTimes(5);
  expect(result).toHaveBeenLastCalledWith(false);
  chat.send('Follow up', 'frigga', undefined, undefined, history, result);
  chat.stop();
  expect(chat.state.messages).toEqual([]);
  expect(result).toHaveBeenCalledTimes(6);
});

test('invalid selected excerpts and slash commands leave the unsent draft untouched', async () => {
  const chat = await opened();
  const before = chat.state.messages;
  expect(chat.send('Question', 'jarvis', undefined, [])).toBe(false);
  expect(chat.send('Question', 'jarvis', undefined, [{ name: 'note.md', text: '' }])).toBe(false);
  expect(chat.send('/new', 'jarvis', undefined, [{ name: 'note.md', text: 'excerpt' }])).toBe(false);
  expect(chat.state.messages).toBe(before);
  expect(streamChat).not.toHaveBeenCalled();
});

test('completed receipt stays on its reply through the next turn, without inferring location', async () => {
  const chat = await opened();
  const calls = [{ provider: 'ollama', model: 'qwen3/8b' }];
  chat.send('First', 'jarvis');
  handlers.onDone('First reply', 'session', undefined, undefined, calls);
  expect(chat.state.messages.at(-1)?.modelCalls).toEqual(calls);
  chat.send('Second', 'jarvis');
  expect(chat.state.messages.at(-1)?.modelCalls).toBeUndefined();
  handlers.onDone('Second reply', 'session');
  expect(chat.state.messages.at(-3)?.modelCalls).toEqual(calls);
  expect(chat.state.messages.at(-1)?.modelCalls).toBeUndefined();
});

test('resumed assistant receipts are projected, while foreign, tainted, user and malformed rows are omitted', async () => {
  const chat = await opened();
  const calls = [{ provider: 'openai', model: 'gpt-5.1' }];
  chat.resume('saved', [
    { role: 'user', content: 'question', model_calls: calls },
    { role: 'assistant', content: 'measured', model_calls: calls },
    { role: 'assistant', content: 'foreign', foreign_origin: 'codex', model_calls: calls },
    { role: 'assistant', content: 'tainted', tainted: true, model_calls: calls },
    { role: 'assistant', content: 'malformed', model_calls: [{ ...calls[0], location: 'unknown' }] },
  ]);
  expect(chat.state.messages.map(m => m.modelCalls)).toEqual([undefined, calls, undefined, undefined, undefined]);
});

test('restored real answers are note eligible, while commands, foreign and system replies are not', async () => {
  const chat = await opened();
  chat.resume('saved', [
    { role: 'user', content: 'Question' },
    { role: 'assistant', content: 'Answer', agent_id: 'jarvis' },
    { role: 'user', content: '/new' },
    { role: 'assistant', content: 'Created', agent_id: 'jarvis' },
    { role: 'user', content: 'Other question' },
    { role: 'assistant', content: 'Foreign', agent_id: 'jarvis', foreign_origin: 'codex' },
    { role: 'assistant', content: 'System', agent_id: 'system' },
  ]);
  expect(chat.state.messages.filter(m => m.completed).map(m => m.text)).toEqual(['Answer']);
});

test('stopped or reselected stream cannot attach a late receipt to another session', async () => {
  const chat = await opened();
  chat.send('First', 'jarvis');
  const stale = handlers;
  chat.resume('chosen', turns);
  stale.onDone('late', 'old', undefined, undefined, [{ provider: 'ollama', model: 'late' }]);
  expect(chat.state.messages.every(m => !m.modelCalls)).toBe(true);
});

test('unconfirmed missing-session recovery does not attribute receipt to the local notice', async () => {
  const chat = await opened();
  chat.resume('gone', turns);
  chat.send('Question', 'jarvis');
  handlers.onError('missing', { kind: 'session_missing', sessionId: 'gone' });
  chat.recoverWithNewSession('jarvis');
  handlers.onDone('Hub answer', 'other', undefined, undefined, [{ provider: 'ollama', model: 'qwen3/8b' }]);
  expect(chat.state.messages.at(-1)?.text).toContain('did not confirm a new conversation');
  expect(chat.state.messages.at(-1)?.modelCalls).toBeUndefined();
});

test('current duration is ephemeral, projected only after a measured end and excluded from persistence', async () => {
  const chat = await opened();
  expect((chat.state as any).turnOutcome).toBeNull();
  chat.send('Hello', 'jarvis');
  handlers.onDone('Hello back', 'server-session', { latency_ms: 0 });
  expect(chat.state.sessionId).toBe('server-session');
  expect((chat.state as any).turnOutcome).toEqual({ latency_ms: 0 });
  expect(saveConversation).toHaveBeenLastCalledWith('connection-1', {
    sessionId: 'server-session', messages: chat.state.messages,
  });
  expect(JSON.stringify(jest.mocked(saveConversation).mock.calls.at(-1)![1])).not.toContain('latency_ms');
  chat.send('Next', 'jarvis');
  expect((chat.state as any).turnOutcome).toBeNull();
  handlers.onDone('Reply', 'server-session', { latency_ms: 154 });
  expect((chat.state as any).turnOutcome).toEqual({ latency_ms: 154 });
});

test('absent duration, stop, error, resume, selected-image start and disposal clear current metric', async () => {
  const chat = await opened();
  chat.send('First', 'jarvis');
  handlers.onDone('First reply', 'one', { latency_ms: 7 });
  chat.send('No metric', 'jarvis');
  handlers.onDone('Second reply', 'one');
  expect((chat.state as any).turnOutcome).toBeNull();
  chat.send('Third', 'jarvis');
  handlers.onDone('Third reply', 'one', { latency_ms: 8 });
  chat.send('Stop this', 'jarvis');
  chat.stop();
  expect((chat.state as any).turnOutcome).toBeNull();
  chat.send('Error', 'jarvis');
  handlers.onError('offline');
  expect((chat.state as any).turnOutcome).toBeNull();
  chat.send('Measured', 'jarvis');
  handlers.onDone('Answer', 'one', { latency_ms: 9 });
  chat.resume('two', turns);
  expect((chat.state as any).turnOutcome).toBeNull();
  chat.send('Measured again', 'jarvis');
  handlers.onDone('Answer', 'two', { latency_ms: 10 });
  const selected = chat.beginSelectedImage('two', chat.revision);
  expect(selected).not.toBeNull();
  expect((chat.state as any).turnOutcome).toBeNull();
  selected!.release();
  chat.send('Final', 'jarvis');
  handlers.onDone('Final answer', 'two', { latency_ms: 11 });
  chat.dispose();
  expect((chat.state as any).turnOutcome).toBeNull();
});

test('agent change clears only duration while old stream reply still settles, even after A-to-B-to-A', async () => {
  const chat = await opened();
  chat.send('From A', 'agent_a');
  const old = handlers;
  (chat as any).clearTurnOutcome();
  (chat as any).clearTurnOutcome();
  old.onDone('A completed reply', 'session_a', { latency_ms: 44 });
  expect(chat.state.messages.at(-1)?.text).toBe('A completed reply');
  expect(chat.state.sessionId).toBe('session_a');
  expect((chat.state as any).turnOutcome).toBeNull();
  expect(cancel).not.toHaveBeenCalled();
  chat.send('From A again', 'agent_a');
  handlers.onDone('Current reply', 'session_a', { latency_ms: 55 });
  expect((chat.state as any).turnOutcome).toEqual({ latency_ms: 55 });
});

test.each(['/new', '/reset', '/undo'])
('%s rollover hides its timing but a refused command in place may keep it', async command => {
  const chat = await opened();
  chat.resume('old', turns);
  jest.mocked(resumeSession).mockResolvedValue({ ok: false, session: '', turns: [] });
  chat.send(command, 'jarvis');
  handlers.onDone('Created', 'fresh', { latency_ms: 13 });
  expect(chat.state.sessionId).toBe('fresh');
  expect((chat.state as any).turnOutcome).toBeNull();
  chat.send(command, 'jarvis');
  handlers.onDone('Denied', 'fresh', { latency_ms: 14 });
  expect((chat.state as any).turnOutcome).toEqual({ latency_ms: 14 });
});

test('startup restores the session together with its messages before sending', async () => {
  let resolve!: (value: any) => void;
  jest.mocked(loadConversation).mockReturnValueOnce(new Promise(r => { resolve = r; }));
  const chat = new Conversation(config, 'connection-1', jest.fn());
  const hydration = chat.hydrate();
  expect(chat.send('Too soon', 'jarvis')).toBe(false);
  expect(saveConversation).not.toHaveBeenCalled();
  resolve({ sessionId: 'saved', messages: [{ id: 'old', role: 'user', text: 'Saved' }] });
  await hydration;
  chat.send('Continue', 'jarvis');
  expect(streamChat).toHaveBeenLastCalledWith(config, 'Continue', 'jarvis', expect.any(Object), 'saved', undefined);
});

test('late hydration cannot replace an explicitly resumed conversation', async () => {
  let resolve!: (value: any) => void;
  jest.mocked(loadConversation).mockReturnValueOnce(new Promise(r => { resolve = r; }));
  const chat = new Conversation(config, 'connection-1', jest.fn());
  const hydration = chat.hydrate();
  chat.resume('chosen', turns);
  resolve({ sessionId: 'old', messages: [] });
  await hydration;
  expect(chat.state.sessionId).toBe('chosen');
  expect(chat.state.messages).toHaveLength(2);
});

test('new chat goes through the governed command and clears history only after rollover', async () => {
  const chat = await opened();
  chat.resume('old', turns);
  chat.send('/new', 'jarvis');
  expect(chat.state.messages[0].text).toBe('Earlier question');
  expect(streamChat).toHaveBeenLastCalledWith(config, '/new', 'jarvis', expect.any(Object), 'old', undefined);
  handlers.onDone('New conversation created', 'fresh');
  expect(chat.state.sessionId).toBe('fresh');
  expect(chat.state.messages.map(m => m.text)).toEqual(['New conversation created']);
});

test('a refused new command retains the previous conversation', async () => {
  const chat = await opened();
  chat.resume('old', turns);
  chat.send('/new', 'jarvis');
  handlers.onDone('Permission denied', 'old');
  expect(chat.state.sessionId).toBe('old');
  expect(chat.state.messages[0].text).toBe('Earlier question');
});

test('stopped callbacks cannot modify the next selected conversation', async () => {
  const chat = await opened();
  chat.send('First', 'jarvis');
  const stale = handlers;
  chat.resume('chosen', turns);
  stale.onToken('Late token');
  stale.onDone('Late answer', 'wrong');
  stale.onError('Late error');
  expect(cancel).toHaveBeenCalled();
  expect(chat.state.sessionId).toBe('chosen');
  expect(chat.state.messages.map(m => m.text)).toEqual(turns.map(t => t.content));
});

test('stop settles the partial bubble and ignores late completion', async () => {
  const chat = await opened();
  chat.send('First', 'jarvis');
  handlers.onToken('Partial');
  chat.stop();
  handlers.onDone('Late answer', 'wrong');
  expect(chat.state.sending).toBe(false);
  expect(chat.state.messages.at(-1)).toMatchObject({ text: 'Partial', pending: false });
  expect(chat.state.messages.at(-1)?.completed).toBeUndefined();
  expect(chat.state.sessionId).toBeNull();
});

test('disposing on a hub change stops callbacks and does not persist a stale thread', async () => {
  const chat = await opened();
  chat.send('First', 'jarvis');
  chat.dispose();
  handlers.onDone('Stale answer', 'wrong-hub');
  expect(cancel).toHaveBeenCalled();
  expect(saveConversation).not.toHaveBeenCalled();
});

test('undo reloads the exact returned transcript and filters non-chat roles', async () => {
  const chat = await opened();
  chat.resume('old', turns);
  jest.mocked(resumeSession).mockResolvedValueOnce({ ok: true, session: 'undone', turns: [
    { role: 'system', content: 'Hidden' }, { role: 'user', content: 'Kept' },
  ] });
  chat.send('/undo', 'jarvis');
  handlers.onDone('Undone', 'undone');
  await Promise.resolve();
  expect(resumeSession).toHaveBeenCalledWith(config, 'undone');
  expect(chat.state.messages.map(m => m.text)).toEqual(['Kept']);
});

test('an undo reload cannot overwrite a newer turn', async () => {
  const chat = await opened();
  chat.resume('old', turns);
  let resolve!: (value: any) => void;
  jest.mocked(resumeSession).mockReturnValueOnce(new Promise(r => { resolve = r; }));
  chat.send('/undo', 'jarvis');
  handlers.onDone('Undone', 'undone');
  chat.send('New question', 'jarvis');
  resolve({ ok: true, session: 'undone', turns: [] });
  await Promise.resolve();
  expect(chat.state.messages.some(m => m.text === 'New question')).toBe(true);
});

test('a synchronous transport error does not leave the conversation busy', async () => {
  jest.mocked(streamChat).mockImplementationOnce((_c, _m, _a, h) => { h.onError('offline'); return cancel; });
  const chat = await opened();
  chat.send('Hello', 'jarvis');
  expect(chat.state.sending).toBe(false);
  expect(chat.state.messages.at(-1)).toMatchObject({ error: true, pending: false });
  expect(chat.state.messages.at(-1)?.completed).toBeUndefined();
});

test('exact missing-session failure retains prompt and blocks normal sends until explicit recovery', async () => {
  const chat = await opened();
  chat.resume('gone', turns);
  chat.send('Keep this draft', 'jarvis');
  const failed = handlers;
  failed.onError('Server returned HTTP 404', { kind: 'session_missing', sessionId: 'gone' });

  expect(chat.state.sessionId).toBe('gone');
  expect(chat.state.missingSessionId).toBe('gone');
  expect(chat.state.recoveryPrompt).toBe('Keep this draft');
  expect(chat.state.sending).toBe(false);
  expect(saveConversation).toHaveBeenLastCalledWith('connection-1', expect.objectContaining({
    sessionId: 'gone', recoveryPrompt: 'Keep this draft',
  }));
  expect(chat.send('Another doomed request', 'jarvis')).toBe(false);
  expect(streamChat).toHaveBeenCalledTimes(1);
});

test('explicit recovery omits the missing ID and preserves transcript/prompt until distinct ID confirms', async () => {
  const chat = await opened();
  chat.resume('gone', turns);
  chat.send('Retain this question', 'jarvis');
  handlers.onError('Server returned HTTP 404', { kind: 'session_missing', sessionId: 'gone' });
  const oldTranscript = chat.state.messages.map(message => message.text);

  expect(chat.recoverWithNewSession('jarvis')).toBe(true);
  expect(streamChat).toHaveBeenLastCalledWith(config, '/new', 'jarvis', expect.any(Object), null, undefined);
  expect(chat.state.sessionId).toBe('gone');
  expect(chat.state.messages.map(message => message.text).slice(0, oldTranscript.length)).toEqual(oldTranscript);
  expect(chat.state.messages.slice(oldTranscript.length).map(message => message.text)).toEqual(['/new', '']);
  handlers.onDone('No new session', 'gone');
  expect(chat.state.sessionId).toBe('gone');
  expect(chat.state.missingSessionId).toBe('gone');
  expect(chat.state.recoveryPrompt).toBe('Retain this question');
  expect(chat.state.messages[0].text).toBe('Earlier question');
  expect(chat.recoverWithNewSession('jarvis')).toBe(true);
  handlers.onDone('New chat ready', 'new-session', undefined,
    { command: 'new', sessionId: 'new-session' });

  expect(chat.state.sessionId).toBe('new-session');
  expect(chat.state.missingSessionId).toBeNull();
  expect(chat.state.recoveryPrompt).toBe('Retain this question');
  expect(chat.state.messages.map(message => message.text)).toEqual(['New chat ready']);
  expect(saveConversation).toHaveBeenLastCalledWith('connection-1', expect.objectContaining({
    sessionId: 'new-session', recoveryPrompt: 'Retain this question',
  }));
  expect(streamChat).toHaveBeenCalledTimes(3); // failed turn and two explicit /new attempts; no prompt replay.
});

test('a different default ID without explicit session transition cannot recover or replace history', async () => {
  const chat = await opened();
  chat.resume('gone', turns);
  chat.send('Keep prompt', 'jarvis');
  handlers.onError('Server returned HTTP 404', { kind: 'session_missing', sessionId: 'gone' });
  const before = chat.state.messages.map(message => message.text);
  expect(chat.recoverWithNewSession('jarvis')).toBe(true);
  handlers.onDone('Unbound command result', 'default-session');

  expect(chat.state.sessionId).toBe('gone');
  expect(chat.state.missingSessionId).toBe('gone');
  expect(chat.state.recoveryPrompt).toBe('Keep prompt');
  expect(chat.state.messages.map(message => message.text).slice(0, before.length)).toEqual(before);
  expect(chat.state.messages.at(-1)?.text).toContain('did not confirm a new conversation');
  expect(chat.state.messages.at(-1)?.text).toContain('update the hub');
  expect(chat.send('Blocked until confirmed recovery', 'jarvis')).toBe(false);
});

test('dismissing the retained prompt does not revoke explicit missing-session recovery', async () => {
  const chat = await opened();
  chat.resume('gone', turns);
  chat.send('Save as draft', 'jarvis');
  handlers.onError('Server returned HTTP 404', { kind: 'session_missing', sessionId: 'gone' });
  chat.dismissRecoveryPrompt();
  expect(chat.state.recoveryPrompt).toBeNull();
  expect(chat.state.missingSessionId).toBe('gone');

  expect(chat.recoverWithNewSession('jarvis')).toBe(true);
  expect(streamChat).toHaveBeenLastCalledWith(config, '/new', 'jarvis', expect.any(Object), null, undefined);
});

test('stale missing-session callback cannot mark a newly resumed selection', async () => {
  const chat = await opened();
  chat.resume('gone', turns);
  chat.send('Old question', 'jarvis');
  const stale = handlers;
  chat.resume('selected', turns);
  stale.onError('Server returned HTTP 404', { kind: 'session_missing', sessionId: 'gone' });

  expect(chat.state.sessionId).toBe('selected');
  expect(chat.state.missingSessionId).toBeNull();
  expect(chat.state.recoveryPrompt).toBeNull();
});

test('same-scope history selection clears missing authority but retains the unsent prompt', async () => {
  const chat = await opened();
  chat.resume('gone', turns);
  chat.send('Save this draft', 'jarvis');
  handlers.onError('Server returned HTTP 404', { kind: 'session_missing', sessionId: 'gone' });
  chat.resume('history-selection', turns);

  expect(chat.state.sessionId).toBe('history-selection');
  expect(chat.state.missingSessionId).toBeNull();
  expect(chat.state.recoveryPrompt).toBe('Save this draft');
});

test('selected image turn takes the same gate as streaming text and commits only scoped text', async () => {
  const chat = await opened();
  chat.resume('selected', turns);
  const revision = chat.revision;
  const turn = chat.beginSelectedImage('selected', revision);
  expect(turn).not.toBeNull();
  expect(chat.send('Interleaving text', 'jarvis')).toBe(false);
  expect(chat.beginSelectedImage('selected', revision)).toBeNull();
  expect(turn!.commit('Exact prompt', 'jarvis', 2, 'llava', 'Answer')).toBe(true);
  expect(chat.state.sending).toBe(false);
  expect(chat.state.messages.slice(-2).map(m => m.text)).toEqual(['Exact prompt\n[2 images attached]', 'Answer']);
  expect(saveConversation).toHaveBeenLastCalledWith('connection-1', expect.objectContaining({ sessionId: 'selected' }));
});

test('stop or history selection revokes a selected image callback and aborts its request', async () => {
  const chat = await opened();
  chat.resume('one', turns);
  const first = chat.beginSelectedImage('one', chat.revision)!;
  chat.stop();
  expect(first.signal.aborted).toBe(true);
  expect(first.commit('Question', 'jarvis', 1, 'llava', 'Too late')).toBe(false);
  const second = chat.beginSelectedImage('one', chat.revision)!;
  chat.resume('two', turns);
  expect(second.signal.aborted).toBe(true);
  expect(second.commit('Question', 'jarvis', 1, 'llava', 'Too late')).toBe(false);
  expect(chat.state.sessionId).toBe('two');
  expect(chat.state.messages).toHaveLength(2);
});

test('a retained unsent prompt must be used or dismissed before another text send can replace it', async () => {
  const chat = await opened();
  chat.resume('gone', turns);
  chat.send('Original unsent message', 'jarvis');
  handlers.onError('missing', { kind: 'session_missing', sessionId: 'gone' });
  chat.resume('second', turns);
  const calls = jest.mocked(streamChat).mock.calls.length;
  expect(chat.send('Second unsent message', 'jarvis')).toBe(false);
  expect(jest.mocked(streamChat).mock.calls).toHaveLength(calls);
  expect(chat.state.recoveryPrompt).toBe('Original unsent message');
  chat.dismissRecoveryPrompt();
  expect(chat.send('Second unsent message', 'jarvis')).toBe(true);
  handlers.onError('missing', { kind: 'session_missing', sessionId: 'second' });
  expect(chat.state.recoveryPrompt).toBe('Second unsent message');
});
