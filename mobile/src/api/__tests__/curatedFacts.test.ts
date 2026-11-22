import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { ApiError, listChatFacts, saveChatFact } from '../client';

const config = { baseUrl: 'hub.local', token: ' user-token ', adminToken: ' admin-token ' };
const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const oldId = 'memory:user:0123456789abcdef';
const newId = 'memory:user:fedcba9876543210';

function reply(changed: boolean, entryId = oldId, value = 'București') {
  mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
    ok: true, changed, ...(entryId === newId ? { previous_id: oldId } : {}),
    entry: { entry_id: entryId, store: 'user', value },
  }) } as Response);
}

beforeEach(() => {
  mockFetch.mockReset();
  globalThis.fetch = mockFetch;
});

describe('listChatFacts', () => {
  it('reads only the selected store with owner credentials and private no-cache transport', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      entries: [{ entry_id: oldId, store: 'user', value: 'București' }],
    }) } as Response);
    expect(await listChatFacts(config, 'user')).toEqual([{ entry_id: oldId, store: 'user', value: 'București' }]);
    expect(mockFetch).toHaveBeenCalledWith('http://hub.local/api/memory/core/facts?store=user',
      expect.objectContaining({ method: 'GET', cache: 'no-store', redirect: 'error', credentials: 'omit',
        headers: expect.objectContaining({ 'X-User-Token': 'user-token', 'X-Admin-Token': 'admin-token' }) }));
    expect(mockFetch.mock.calls[0][1]?.body).toBeUndefined();
  });

  it('lists an older overlong fact so the owner can select it for shortening', async () => {
    const value = 'Legacy '.repeat(300);
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      entries: [{ entry_id: oldId, store: 'user', value }],
    }) } as Response);
    expect(await listChatFacts(config, 'user')).toEqual([{ entry_id: oldId, store: 'user', value }]);
  });

  it('rejects a foreign or malformed entry without exposing it to selection', async () => {
    for (const entries of [[{ entry_id: oldId, store: 'memory', value: 'Private' }],
      [{ entry_id: oldId, store: 'user', value: 'One' }, { entry_id: oldId, store: 'user', value: 'Two' }],
      [{ entry_id: 'learning:7', store: 'user', value: 'Wrong kind' }]]) {
      mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ entries }) } as Response);
      await expect(listChatFacts(config, 'user')).rejects.toMatchObject({ message: 'Invalid saved facts response' });
    }
  });

  it('does not retry an owner refusal or infer a store from untrusted input', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 401 } as Response);
    await expect(listChatFacts(config, 'memory')).rejects.toMatchObject({ status: 401 });
    await expect(listChatFacts(config, 'facts' as never)).rejects.toBeInstanceOf(ApiError);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});

describe('saveChatFact', () => {
  it('posts a trimmed Unicode fact with the configured chat credentials', async () => {
    reply(true);
    expect(await saveChatFact(config, 'user', '  București  ')).toEqual({
      changed: true, entry: { entry_id: oldId, store: 'user', value: 'București' },
    });
    expect(mockFetch).toHaveBeenCalledWith('http://hub.local/api/dashboard/today/entries', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'X-User-Token': 'user-token', 'X-Admin-Token': 'admin-token' }),
      body: JSON.stringify({ store: 'user', value: 'București' }),
      redirect: 'error', credentials: 'omit',
    }));
  });

  it('reports a normalized duplicate without claiming a new write', async () => {
    reply(false, oldId, 'București este acasă');
    expect(await saveChatFact(config, 'user', 'București   este acasă')).toEqual({
      changed: false, entry: { entry_id: oldId, store: 'user', value: 'București este acasă' },
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('lets the hub decide owner eligibility when no admin token is configured', async () => {
    reply(true);
    await saveChatFact({ baseUrl: config.baseUrl, token: '', adminToken: '' }, 'user', 'București');
    const [, options] = mockFetch.mock.calls[0];
    expect(options?.headers).not.toHaveProperty('X-Admin-Token');
    expect(options?.headers).not.toHaveProperty('X-User-Token');
  });

  it('patches a returned ring ID and accepts its replacement ID', async () => {
    reply(true, newId, 'Locuiesc în București');
    expect(await saveChatFact(config, 'user', '  Locuiesc în București  ', oldId)).toEqual({
      changed: true, entry: { entry_id: newId, store: 'user', value: 'Locuiesc în București' },
    });
    expect(mockFetch).toHaveBeenCalledWith(`http://hub.local/api/dashboard/today/entries/${oldId}`,
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ value: 'Locuiesc în București' }),
        redirect: 'error', credentials: 'omit' }));
  });

  it('accepts the server-normalized replacement and checks its previous ID', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      ok: true, changed: true, previous_id: oldId,
      entry: { entry_id: newId, store: 'user', value: 'Locuiesc în București' },
    }) } as Response);
    await expect(saveChatFact(config, 'user', '  Locuiesc   în\nBucurești  ', oldId)).resolves.toMatchObject({
      changed: true, entry: { entry_id: newId, value: 'Locuiesc în București' },
    });
  });

  it('accepts Python whitespace normalization of a pasted NEXT LINE character', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      ok: true, changed: true, previous_id: oldId,
      entry: { entry_id: newId, store: 'user', value: 'A B' },
    }) } as Response);
    await expect(saveChatFact(config, 'user', 'A\u0085B', oldId)).resolves.toMatchObject({
      entry: { entry_id: newId, value: 'A B' },
    });
    expect(JSON.parse(mockFetch.mock.calls[0][1]?.body as string)).toEqual({ value: 'A\u0085B' });
  });

  it.each([
    { entry_id: oldId, value: 'Changed', previous_id: oldId },
    { entry_id: newId, value: 'Unexpected', previous_id: oldId },
    { entry_id: newId, value: 'Changed', previous_id: newId },
    { entry_id: newId, value: 'Changed', previous_id: undefined },
  ])('rejects a correction receipt that cannot confirm the selected old fact', async (entry) => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      ok: true, changed: true, previous_id: entry.previous_id,
      entry: { entry_id: entry.entry_id, store: 'user', value: entry.value },
    }) } as Response);
    await expect(saveChatFact(config, 'user', 'Changed', oldId)).rejects.toMatchObject({
      message: 'Invalid saved fact response',
    });
  });

  it.each(['learning:7', 'memory:user:abc', 'memory:user:0123456789ABCDEf',
    'memory:memory:0123456789abcdef', 'memory:user:0123456789abcdef/extra'])
  ('rejects a malformed or foreign correction ID: %s', async (entryId) => {
    await expect(saveChatFact(config, 'user', 'Updated', entryId)).rejects.toBeInstanceOf(ApiError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it.each(['', '  ', 'x'.repeat(301)])('rejects an invalid fact before the request', async (value) => {
    await expect(saveChatFact(config, 'memory', value)).rejects.toBeInstanceOf(ApiError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('accepts 300 Unicode code points', async () => {
    const value = '😀'.repeat(300);
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      ok: true, changed: true, entry: { entry_id: 'memory:memory:0123456789abcdef', store: 'memory', value },
    }) } as Response);
    await expect(saveChatFact(config, 'memory', value)).resolves.toMatchObject({ changed: true });
  });

  it.each([403, 503])('does not retry an HTTP %i refusal', async (status) => {
    mockFetch.mockResolvedValueOnce({ ok: false, status } as Response);
    await expect(saveChatFact(config, 'user', 'București')).rejects.toMatchObject({ status });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    [400, 'memory_disabled', 'Automatic memory is off on this hub.'],
    [400, 'memory_full', 'Saved facts are full. Remove a fact before saving another.'],
    [409, 'memory_over_budget', 'Saved facts are over the space limit. Shorten or remove a fact.'],
    [404, 'memory_no_match', 'This saved fact changed or is no longer available. Review it before correcting.'],
    [409, 'memory_duplicate', 'That fact is already saved.'],
    [409, 'memory_changed_meanwhile', 'Saved facts changed while saving. Review them and try again.'],
  ])('maps HTTP %i reason %s without echoing server text', async (status, reason, message) => {
    mockFetch.mockResolvedValueOnce({ ok: false, status, json: async () => ({ reason, error: 'private server text' }) } as Response);
    await expect(saveChatFact(config, 'user', 'București')).rejects.toMatchObject({ status, message });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('keeps generic fallback for unknown reasons and authorization refusals', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({
      reason: 'future_reason', error: 'private server text',
    }) } as Response);
    await expect(saveChatFact(config, 'user', 'București')).rejects.toMatchObject({
      status: 409, message: 'Server returned HTTP 409',
    });
    mockFetch.mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ reason: 'constructor' }) } as Response);
    await expect(saveChatFact(config, 'user', 'București')).rejects.toMatchObject({
      status: 409, message: 'Server returned HTTP 409',
    });
    mockFetch.mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({
      reason: 'memory_disabled', error: 'private server text',
    }) } as Response);
    await expect(saveChatFact(config, 'user', 'București')).rejects.toMatchObject({
      status: 403, message: 'Server returned HTTP 403',
    });
  });

  it('rejects an unconfirmed or wrong-store response', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      ok: false, changed: true, entry: { entry_id: oldId, store: 'user', value: 'București' },
    }) } as Response);
    await expect(saveChatFact(config, 'user', 'București')).rejects.toBeInstanceOf(ApiError);
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      ok: true, changed: true, entry: { entry_id: 'memory:memory:0123456789abcdef', store: 'memory', value: 'București' },
    }) } as Response);
    await expect(saveChatFact(config, 'user', 'București')).rejects.toBeInstanceOf(ApiError);
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      ok: true, changed: true, entry: { entry_id: oldId, store: 'user', value: '   ' },
    }) } as Response);
    await expect(saveChatFact(config, 'user', 'București')).rejects.toMatchObject({
      message: 'Invalid saved fact response',
    });
  });
});
