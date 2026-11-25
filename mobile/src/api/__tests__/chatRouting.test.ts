import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { chatRoutingLabel, fetchAgents, selectableChatAgents } from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const config = { baseUrl: 'hub.local', token: 'user-token', adminToken: 'admin-token' };

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

describe('native chat routing disclosure', () => {
  it('reads the authenticated roster and filters disabled or invalid choices', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ agents: [
      { id: 'jarvis', name: 'Jarvis', enabled: true, chat_routing: 'orchestrated' },
      { id: 'frigga', name: 'Frigga', enabled: false, chat_routing: 'local' },
      { id: 'howard', name: 'Howard', chat_routing: 'cloud_only' },
      { id: '', name: 'Invalid' },
    ] }) } as Response);

    const roster = await fetchAgents(config);
    expect(mockFetch).toHaveBeenCalledWith('http://hub.local/api/agents', expect.objectContaining({
      method: 'GET', headers: expect.objectContaining({ 'X-User-Token': 'user-token' }),
    }));
    expect(selectableChatAgents(roster).map(agent => agent.id)).toEqual(['jarvis', 'howard']);
    expect(roster[0].chat_routing).toBe('orchestrated');
  });

  it('labels configured policies without claiming the backend that ran', () => {
    expect(['orchestrated', 'local', 'cloud_only', 'cloud_preferred', 'claude_preferred', 'auto']
      .map(policy => chatRoutingLabel(policy as Parameters<typeof chatRoutingLabel>[0])))
      .toEqual(['Orchestrated', 'Local preference (hub setting)', 'Cloud only',
        'Cloud preferred', 'Claude preferred', 'Auto']);
    expect(chatRoutingLabel(null)).toBe('Unknown');
    expect(chatRoutingLabel(undefined)).toBe('Unknown');
    expect(chatRoutingLabel('new_server_policy' as any)).toBe('Unknown');
  });

  it('treats malformed roster payloads as no selectable agents', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ agents: {} }) } as Response);
    expect(await fetchAgents(config)).toEqual([]);
  });
});
