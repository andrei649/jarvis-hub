import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
jest.mock('expo/fetch', () => ({ fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args) }));
import { ApiError } from '../client';
import { ChatNoteTitleConflict, fetchChatNoteTarget, projectSavedChatNote, readSavedChatNote, saveChatNote,
  type ChatNoteDraft, type ChatNoteReceipt, type ChatNoteTarget } from '../chatNote';

const config = { baseUrl: 'hub.local', token: ' user ', adminToken: ' owner ' };
const target: ChatNoteTarget = { id: `v1-${'a'.repeat(64)}`, vault: 'Sample Vault', inbox: 'Journal/Inbox' };
const receipt: ChatNoteReceipt = { relPath: 'Journal/Inbox/Reviewed note.md',
  source: { vault: 'Sample Vault', file: 'Journal/Inbox/Reviewed note.md', readable: true } };
const draft: ChatNoteDraft = { target, requestId: '123e4567-e89b-42d3-a456-426614174000',
  title: 'Reviewed note', content: '\n  exact edited body\n' };
const oldFetch = globalThis.fetch;
const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;

function reply(status: number, data: unknown) {
  mockFetch.mockResolvedValueOnce({ status, json: async () => data } as Response);
}

beforeEach(() => { mockFetch.mockReset(); globalThis.fetch = mockFetch; });
afterEach(() => { globalThis.fetch = oldFetch; jest.useRealTimers(); });

describe('chat note API', () => {
  it('projects only a validated saved link for the chat cache', () => {
    expect(projectSavedChatNote({ target: { ...target, secret: 'omit' },
      receipt: { ...receipt, content: 'omit', source: { ...receipt.source, extra: 'omit' } },
      requestId: draft.requestId })).toEqual({ target, receipt });
    expect(projectSavedChatNote({ target, receipt: { ...receipt, relPath: 'Other/secret.md' } })).toBeNull();
  });

  it('checks the live target and writes exactly the reviewed draft once with owner credentials', async () => {
    reply(200, { ok: true, captureTarget: { ...target, ignored: 'secret' } });
    await expect(fetchChatNoteTarget(config)).resolves.toEqual(target);
    expect(mockFetch).toHaveBeenCalledWith('http://hub.local/api/os/status', expect.objectContaining({
      method: 'GET', redirect: 'error', credentials: 'omit',
      headers: { Accept: 'application/json', 'Cache-Control': 'no-store',
        'X-User-Token': 'user', 'X-Admin-Token': 'owner' },
    }));
    reply(200, { ok: true, ...receipt, ignored: 'secret' });
    await expect(saveChatNote(config, draft)).resolves.toEqual(receipt);
    expect(mockFetch).toHaveBeenLastCalledWith('http://hub.local/api/os/brain/chat-note', expect.objectContaining({
      method: 'POST', redirect: 'error', credentials: 'omit',
      body: JSON.stringify({ targetId: target.id, requestId: draft.requestId,
        title: draft.title, content: draft.content }),
    }));
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('accepts an unavailable target and rejects malformed targets', async () => {
    reply(200, { ok: true, captureTarget: null });
    await expect(fetchChatNoteTarget(config)).resolves.toBeNull();
    for (const bad of [{ ok: true }, { ok: false, captureTarget: null },
      { ok: true, captureTarget: { ...target, inbox: '../Elsewhere' } },
      { ok: true, captureTarget: { ...target, vault: 'Bad\u0000Vault' } }]) {
      reply(200, bad);
      await expect(fetchChatNoteTarget(config)).rejects.toThrow('Invalid vault status');
    }
  });

  it('uses a typed title collision only for the exact 409 code and never retries', async () => {
    reply(409, { ok: false, code: 'title_conflict' });
    await expect(saveChatNote(config, draft)).rejects.toBeInstanceOf(ChatNoteTitleConflict);
    reply(409, { ok: false, code: 'note_changed' });
    await expect(saveChatNote(config, draft)).rejects.toMatchObject({ status: 409, name: 'ApiError' });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('rejects invalid drafts before network and receipts outside the pinned inbox', async () => {
    for (const bad of [{ ...draft, requestId: 'not-uuid' }, { ...draft, content: '  ' },
      { ...draft, title: '\ud800' }, { ...draft, target: { ...target, inbox: 'Other/../Inbox' } }]) {
      await expect(saveChatNote(config, bad)).rejects.toBeInstanceOf(ApiError);
    }
    expect(mockFetch).not.toHaveBeenCalled();
    for (const bad of [{ ok: true, ...receipt, relPath: 'Journal/Inbox/../evil.md' },
      { ok: true, ...receipt, relPath: 'Journal/Inbox/Nested/evil.md' },
      { ok: true, ...receipt, source: { ...receipt.source, vault: 'Elsewhere' } },
      { ok: true, ...receipt, source: { ...receipt.source, readable: false } },
      { ok: true, ...receipt, relPath: 'Journal/Inbox/evil.txt' }]) {
      reply(200, bad);
      await expect(saveChatNote(config, draft)).rejects.toThrow('Invalid save receipt');
    }
  });

  it('saves and reads a legal path with no native Obsidian source', async () => {
    const localTarget = { ...target, vault: 'Notes #1', inbox: 'Journal/Inbox %' };
    const localReceipt = { relPath: 'Journal/Inbox %/Reviewed note.md', source: null };
    reply(200, { ok: true, captureTarget: localTarget });
    await expect(fetchChatNoteTarget(config)).resolves.toEqual(localTarget);
    reply(200, { ok: true, ...localReceipt });
    await expect(saveChatNote(config, { ...draft, target: localTarget })).resolves.toEqual(localReceipt);
    reply(200, { ok: true, targetId: localTarget.id, relPath: localReceipt.relPath, body: 'edited' });
    await expect(readSavedChatNote(config, localTarget, localReceipt)).resolves.toBe('edited');
    expect(mockFetch).toHaveBeenLastCalledWith(
      `http://hub.local/api/os/brain/note?relPath=Journal%2FInbox%20%25%2FReviewed%20note.md&targetId=${target.id}`,
      expect.objectContaining({ method: 'GET' }),
    );
    reply(200, { ok: true, relPath: localReceipt.relPath,
      source: { vault: localTarget.vault, file: localReceipt.relPath, readable: true } });
    await expect(saveChatNote(config, { ...draft, target: localTarget })).rejects.toThrow('Invalid save receipt');
  });

  it('reads the exact bound note body, including an empty body, without a retry', async () => {
    reply(200, { ok: true, targetId: target.id, relPath: receipt.relPath, body: '' });
    await expect(readSavedChatNote(config, target, receipt)).resolves.toBe('');
    expect(mockFetch).toHaveBeenCalledWith(
      `http://hub.local/api/os/brain/note?relPath=Journal%2FInbox%2FReviewed%20note.md&targetId=${target.id}`,
      expect.objectContaining({ method: 'GET', redirect: 'error', credentials: 'omit' }),
    );
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('refuses unbound or malformed reads and unsafe paths before network', async () => {
    await expect(readSavedChatNote(config, target, { ...receipt, relPath: 'Journal/Inbox/../secret.md' }))
      .rejects.toThrow('Invalid saved note path');
    expect(mockFetch).not.toHaveBeenCalled();
    for (const bad of [
      { ok: true, relPath: receipt.relPath, body: 'text' },
      { ok: true, targetId: 'wrong', relPath: receipt.relPath, body: 'text' },
      { ok: true, targetId: target.id, relPath: 'Other/file.md', body: 'text' },
      { ok: true, targetId: target.id, relPath: receipt.relPath, body: 'x'.repeat(100_001) },
    ]) {
      reply(200, bad);
      await expect(readSavedChatNote(config, target, receipt)).rejects.toThrow('Invalid saved note response');
    }
  });

  it('rejects credential-bearing URLs and times out one attempt', async () => {
    await expect(fetchChatNoteTarget({ ...config, baseUrl: 'https://user:pass@evil.test' }))
      .rejects.toThrow('Invalid server URL');
    expect(mockFetch).not.toHaveBeenCalled();
    jest.useFakeTimers();
    mockFetch.mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    const pending = saveChatNote(config, draft);
    const expected = expect(pending).rejects.toThrow('timed out');
    await jest.advanceTimersByTimeAsync(15_000);
    await expected;
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
