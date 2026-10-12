import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  loadFacts, loadMemoryMap, loadSkills, removeEntity, saveEntity, switchSkill,
} from '../api/memory-graph';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const bounds = { count: 2, first_ingested: 100, last_ingested: 300, first_valid: 100, last_change: 400 };
beforeEach(() => { localStorage.clear(); vi.stubGlobal('fetch', vi.fn()); vi.spyOn(window, 'prompt').mockReturnValue(null); });

describe('memory graph reads', () => {
  it('reads the bounded whole-map and keeps names, types, edges and first-seen only', async () => {
    vi.mocked(fetch).mockResolvedValue(json({
      entities: [{ name: 'A', type: 'person', first_seen: 120, properties: { secret: 'PRIVATE' } }, { name: 'B', type: 'city', first_seen: null }],
      relations: [{ source: 'A', relation: 'lives_in', target: 'B', properties: { x: 1 } }], clipped: false, relations_clipped: true,
    }));
    const map = await loadMemoryMap();
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/kg/map?limit=500');
    expect(map).toEqual({
      entities: [{ name: 'A', type: 'person', firstSeen: 120 }, { name: 'B', type: 'city', firstSeen: null }],
      relations: [{ source: 'A', relation: 'lives_in', target: 'B' }], clipped: false, relationsClipped: true,
    });
    expect(JSON.stringify(map)).not.toContain('PRIVATE');
  });

  it.each([
    { entities: [{}], relations: [], clipped: false },
    { entities: [{ name: 'A', type: 'x' }], relations: [{ source: 'A', relation: 'r', target: 'GHOST' }], clipped: false },
    { entities: 'no', relations: [] },
    { error: 'graph not available', entities: [], relations: [] },
  ])('rejects a malformed map %#', async value => {
    vi.mocked(fetch).mockResolvedValue(json(value));
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('requests the facts for an axis and instant and validates the page', async () => {
    vi.mocked(fetch).mockResolvedValue(json({
      at: 250, axis: 'known', clipped: false, bounds,
      facts: [{ id: 1, subject: 'andrei', predicate: 'lives_in', object: 'Bucharest', valid_from: 100, valid_to: null, ingested_at: 100, invalidated_at: null }],
    }));
    const page = await loadFacts('known', 250.5);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/kg/facts/as-of?axis=known&at=250.5&limit=500');
    expect(page.facts[0]).toMatchObject({ subject: 'andrei', predicate: 'lives_in', object: 'Bucharest', ingestedAt: 100 });
    expect(page.bounds).toEqual({ count: 2, firstIngested: 100, lastIngested: 300, firstValid: 100, lastChange: 400 });
  });

  it('omits `at` for "now" and refuses a bad axis or a malformed fact', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ at: null, axis: 'valid', clipped: false, bounds, facts: [] }));
    await loadFacts('valid', null);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/kg/facts/as-of?axis=valid&limit=500');
    await expect(loadFacts('sideways' as any, null)).rejects.toMatchObject({ code: 'unavailable' });
    vi.mocked(fetch).mockResolvedValue(json({ axis: 'known', clipped: false, bounds, facts: [{ subject: 1 }] }));
    await expect(loadFacts('known', 1)).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('lists installed skills from GET /skills', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ skills: {
      'web-search': { name: 'web-search', category: 'research', essential: false, disabled: false, disabled_channels: [], description: 'long text' },
      core: { name: 'core', category: '', essential: true, disabled: false, disabled_channels: [] },
    } }));
    const skills = await loadSkills();
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/skills');
    expect(skills).toEqual([
      { name: 'core', category: '', essential: true, disabled: false },
      { name: 'web-search', category: 'research', essential: false, disabled: false },
    ]);
  });

  it('tells a kernel/contract denial from an authentication failure on 403', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ error: 'kernel denied: halted' }, 403));
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'denied', detail: 'kernel denied: halted' });
    vi.mocked(fetch).mockResolvedValue(json({ detail: 'forbidden' }, 403));
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'auth' });
    vi.mocked(fetch).mockResolvedValue(json({}, 401));
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'auth' });
  });
});

describe('memory graph writes use only the mediated routes', () => {
  it('saves an entity with a body of name/type/properties and no capability header', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ ok: true, entity: { name: 'Andrei', type: 'person', properties: {} } }));
    const saved = await saveEntity('Andrei', 'person', { city: 'Cluj' });
    const [path, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/kg/entities');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ name: 'Andrei', type: 'person', properties: { city: 'Cluj' } });
    expect(JSON.stringify(init.headers).toLowerCase()).not.toContain('capability');
    expect(saved).toMatchObject({ name: 'Andrei', type: 'person' });
  });

  it('refuses an unsafe type locally, mirroring the server, without a request', async () => {
    await expect(saveEntity('A', 'bad type!', {})).rejects.toMatchObject({ code: 'invalid' });
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([
    [400, { error: 'invalid entity type' }, 'invalid', 'invalid entity type'],
    [403, { error: 'kernel denied: halted' }, 'denied', 'kernel denied: halted'],
    [403, { error: 'contract denied: unknown_operation' }, 'denied', 'contract denied: unknown_operation'],
    [503, { error: 'graph not available' }, 'unavailable', 'graph not available'],
    [401, { detail: 'nope' }, 'auth', ''],
  ])('maps %s to %s keeping the server message', async (status, body, code, detail) => {
    vi.mocked(fetch).mockResolvedValue(json(body, status as number));
    await expect(saveEntity('A', 'person', {})).rejects.toMatchObject(detail ? { code, detail } : { code });
  });

  it('deletes one encoded path segment and returns the retracted-fact count', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ ok: true, deleted: 'A B ?', facts_retracted: 3 }));
    expect(await removeEntity('A B ?')).toEqual({ factsRetracted: 3 });
    const [path, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/kg/entities/' + encodeURIComponent('A B ?'));
    expect(init.method).toBe('DELETE');
  });

  it('never sends a name the path route cannot carry (slash, dot segments)', async () => {
    for (const name of ['a/b', '..', 'x\\y']) {
      await expect(removeEntity(name)).rejects.toMatchObject({ code: 'invalid' });
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it('shows a kernel refusal on delete and a 404 as not found', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ error: 'kernel denied: halted' }, 403));
    await expect(removeEntity('A')).rejects.toMatchObject({ code: 'denied', detail: 'kernel denied: halted' });
    vi.mocked(fetch).mockResolvedValue(json({ error: 'not found' }, 404));
    await expect(removeEntity('A')).rejects.toMatchObject({ code: 'notfound' });
  });

  it('switches a skill off through the admin-guarded switch route', async () => {
    localStorage.setItem('hud.admin_token', 'adm');
    vi.mocked(fetch).mockResolvedValue(json({ status: 'ok', changed: ['web-search'] }));
    const result = await switchSkill('web-search', false);
    const [path, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/skills/switch');
    expect(JSON.parse(init.body as string)).toEqual({ skill: 'web-search', enabled: false });
    expect(JSON.stringify(init.headers)).toContain('adm');
    expect(result.changed).toEqual(['web-search']);
    vi.mocked(fetch).mockResolvedValue(json({ error: 'admin required' }, 403));
    await expect(switchSkill('web-search', false)).rejects.toMatchObject({ code: 'admin' });
    vi.mocked(fetch).mockResolvedValue(json({ error: 'core is essential and cannot be switched off', reason: 'essential' }, 409));
    await expect(switchSkill('core', false)).rejects.toMatchObject({ code: 'invalid', detail: expect.stringContaining('essential') });
  });
});
