import { afterEach, describe, expect, jest, test } from '@jest/globals';
import {
  createRosterAgent,
  deleteLearnedEntry,
  deleteSkillBundle,
  editLearnedEntry,
  fetchAgentRoster,
  fetchLearnedEntries,
  fetchMemoryGovernance,
  fetchOsStatus,
  fetchOsWorkshopProject,
  fetchOsWorkshopProjects,
  fetchSkillBundles,
  reindexOsVault,
  renameRosterAgent,
  resetCuratedMemory,
  restoreRosterAgent,
  retireRosterAgent,
  saveSkillBundle,
  setMemorySwitch,
  switchSkillBundle,
} from '../ownerControls';
import type { ServerConfig } from '../../storage/settings';

const cfg: ServerConfig = {
  baseUrl: 'https://hub.example',
  token: 'user-tok',
  adminToken: 'admin-tok',
};

function jsonRes(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe('H18.35 / H18.37 / H18.38 native owner controls and ANDREI OS parity', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('H422 memory governance reads ring budgets, toggles switch, and enforces literal RESET confirmation', async () => {
    const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
    mockFetch
      .mockResolvedValueOnce(
        jsonRes({
          available: true,
          enabled: true,
          switch: true,
          block_max_chars: 4000,
          stores: {
            memory: { chars: 420, max_chars: 2200, entries: 5 },
            user: { chars: 180, max_chars: 1375, entries: 2 },
          },
        }),
      )
      .mockResolvedValueOnce(jsonRes({ ok: true, enabled: false }))
      .mockResolvedValueOnce(jsonRes({ ok: true, cleared: ['memory', 'user'] }));
    (globalThis as any).fetch = mockFetch;

    const status = await fetchMemoryGovernance(cfg);
    expect(status.memory).toEqual({ chars: 420, max_chars: 2200, entries: 5 });
    expect(status.user).toEqual({ chars: 180, max_chars: 1375, entries: 2 });

    const toggled = await setMemorySwitch(cfg, false);
    expect(toggled.enabled).toBe(false);

    await expect(resetCuratedMemory(cfg, 'all', 'reset')).rejects.toThrow(/Type RESET in capitals/);
    const cleared = await resetCuratedMemory(cfg, 'all', 'RESET');
    expect(cleared.cleared).toEqual(['memory', 'user']);
  });

  test('H026 skill bundles list, save, switch (202 pending approval), and delete', async () => {
    const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
    mockFetch
      .mockResolvedValueOnce(
        jsonRes({
          bundles: [
            { name: 'Morning Ops', slug: 'morning-ops', description: 'Daily checks', skills: ['brief'], installed: ['brief'], missing: [] },
          ],
          problems: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonRes({
          ok: true,
          replaced: false,
          bundle: { name: 'Evening', slug: 'evening', description: '', skills: ['notes'], installed: ['notes'], missing: [] },
        }),
      )
      .mockResolvedValueOnce(jsonRes({ ok: true, status: 'pending', task_id: 'appr_12', bundle: 'evening', missing: [] }, 202))
      .mockResolvedValueOnce(jsonRes({ ok: true }));
    (globalThis as any).fetch = mockFetch;

    const listed = await fetchSkillBundles(cfg);
    expect(listed.bundles[0].slug).toBe('morning-ops');

    const saved = await saveSkillBundle(cfg, { name: 'Evening', skills: ['notes'] });
    expect(saved.slug).toBe('evening');

    const switched = await switchSkillBundle(cfg, 'Evening', true);
    expect(switched).toEqual({ status: 'pending', taskId: 'appr_12', bundle: 'evening', missing: [] });

    await expect(deleteSkillBundle(cfg, 'Evening')).resolves.toBeUndefined();
  });

  test('H202 agent roster lists, creates, renames, enforces typed-id retirement, and restores', async () => {
    const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
    mockFetch
      .mockResolvedValueOnce(
        jsonRes({
          agents: [{ id: 'jarvis', name: 'Jarvis', status: 'active', live: true, protected: true, revision: 0 }],
          templates: [{ key: 'blank', name: 'Blank', description: 'Empty persona' }],
          tiers: ['foundation'],
          safe_mode: false,
        }),
      )
      .mockResolvedValueOnce(
        jsonRes({ ok: true, agent: { id: 'scout', name: 'Scout', status: 'active', live: true, created: true, revision: 1 } }, 201),
      )
      .mockResolvedValueOnce(
        jsonRes({ ok: true, agent: { id: 'scout', name: 'Scout Prime', status: 'active', live: true, created: true, revision: 2 } }),
      )
      .mockResolvedValueOnce(
        jsonRes({ ok: true, agent: { id: 'scout', name: 'Scout Prime', status: 'retired', live: false, created: true, revision: 3 } }),
      )
      .mockResolvedValueOnce(
        jsonRes({ ok: true, agent: { id: 'scout', name: 'Scout Prime', status: 'active', live: true, created: true, revision: 4 } }),
      );
    (globalThis as any).fetch = mockFetch;

    const view = await fetchAgentRoster(cfg);
    expect(view.agents[0].protected).toBe(true);

    const created = await createRosterAgent(cfg, { name: 'Scout', template: 'blank' });
    expect(created.id).toBe('scout');

    const renamed = await renameRosterAgent(cfg, 'scout', 'Scout Prime');
    expect(renamed.name).toBe('Scout Prime');

    await expect(retireRosterAgent(cfg, 'scout', 'wrong')).rejects.toThrow(/Type "scout" to confirm/);
    const retired = await retireRosterAgent(cfg, 'scout', 'scout', 'pause');
    expect(retired.status).toBe('retired');

    const restored = await restoreRosterAgent(cfg, 'scout');
    expect(restored.status).toBe('active');
  });

  test('H046 today learned entries list, edit, and forget', async () => {
    const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
    mockFetch
      .mockResolvedValueOnce(
        jsonRes({
          entries: [{ id: 'memory:abc123', store: 'memory', value: 'Prefers concise status reports' }],
          total: 1,
          counts: { memory: 1 },
        }),
      )
      .mockResolvedValueOnce(
        jsonRes({
          ok: true,
          changed: true,
          entry: { id: 'memory:def456', store: 'memory', value: 'Prefers concise Romanian reports' },
        }),
      )
      .mockResolvedValueOnce(jsonRes({ ok: true, deleted: 'memory:def456' }));
    (globalThis as any).fetch = mockFetch;

    const list = await fetchLearnedEntries(cfg);
    expect(list.entries).toHaveLength(1);

    const edited = await editLearnedEntry(cfg, 'memory:abc123', 'Prefers concise Romanian reports');
    expect(edited.changed).toBe(true);
    expect(edited.entry?.id).toBe('memory:def456');

    const removed = await deleteLearnedEntry(cfg, 'memory:def456');
    expect(removed.deleted).toBe('memory:def456');
  });

  test('H18.38 ANDREI OS status, vault reindex, and workshop project inspection', async () => {
    const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
    mockFetch
      .mockResolvedValueOnce(
        jsonRes({
          ok: true,
          vaultMode: 'andrei_plus_nerva',
          vaultPath: 'Vault',
          vaultAvailable: true,
          indexReady: true,
          indexedNotes: 142,
          lastIndexedAt: '2026-11-28T10:00:00Z',
          copilotConnected: true,
          inboxFolder: '00_Inbox',
        }),
      )
      .mockResolvedValueOnce(jsonRes({ ok: true, indexedNotes: 145, lastIndexedAt: '2026-11-28T10:05:00Z' }))
      .mockResolvedValueOnce(
        jsonRes({
          ok: true,
          projects: [{ path: 'workshop/robot-arm.json', title: 'Robot Arm', view: 'robot', updatedAt: '2026-11-28' }],
        }),
      )
      .mockResolvedValueOnce(
        jsonRes({
          ok: true,
          path: 'workshop/robot-arm.json',
          title: 'Robot Arm',
          project: { view: 'robot', params: { shoulderDeg: 35, gripOpen: true } },
        }),
      );
    (globalThis as any).fetch = mockFetch;

    const st = await fetchOsStatus(cfg);
    expect(st.indexedNotes).toBe(142);
    expect(st.copilotConnected).toBe(true);

    const reindexed = await reindexOsVault(cfg);
    expect(reindexed.indexedNotes).toBe(145);

    const projects = await fetchOsWorkshopProjects(cfg);
    expect(projects[0].title).toBe('Robot Arm');

    const detail = await fetchOsWorkshopProject(cfg, 'workshop/robot-arm.json');
    expect(detail.paramCount).toBe(2);
    expect(detail.summary).toContain('shoulderDeg');
  });
});
