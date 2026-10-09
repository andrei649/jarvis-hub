import { beforeEach, expect, jest, test } from '@jest/globals';
import { Conversation } from '../conversation';
import { resumeSession, streamChat, type StreamHandlers } from '../../api/client';
import { loadConversation, saveConversation } from '../../storage/chat';

jest.mock('../../api/client', () => ({ streamChat: jest.fn(), resumeSession: jest.fn() }));
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

async function opened() {
  const chat = new Conversation(config, 'connection-1', jest.fn());
  await chat.hydrate();
  return chat;
}

test('resumed history sends the exact selected session on every subsequent turn', async () => {
  const chat = await opened();
  chat.resume('archived-session', turns);
  expect(chat.state.messages[1].agent).toBe('howard');
  chat.send('Continue', 'jarvis');
  expect(streamChat).toHaveBeenLastCalledWith(config, 'Continue', 'jarvis', expect.any(Object), 'archived-session');
  handlers.onDone('Next answer', 'archived-session');
  chat.send('And then?', 'jarvis');
  expect(streamChat).toHaveBeenLastCalledWith(config, 'And then?', 'jarvis', expect.any(Object), 'archived-session');
});

test('first response binds and persists the actual server session', async () => {
  const chat = await opened();
  chat.send('Hello', 'jarvis');
  handlers.onDone('Hello back', 'server-session');
  expect(chat.state.sessionId).toBe('server-session');
  expect(saveConversation).toHaveBeenLastCalledWith('connection-1', expect.objectContaining({ sessionId: 'server-session' }));
  expect(chat.state.messages.at(-1)?.pending).toBe(false);
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
  expect(streamChat).toHaveBeenLastCalledWith(config, 'Continue', 'jarvis', expect.any(Object), 'saved');
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
  expect(streamChat).toHaveBeenLastCalledWith(config, '/new', 'jarvis', expect.any(Object), 'old');
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
