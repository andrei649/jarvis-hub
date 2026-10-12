import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  isAddressable, isEditable, loadEntity, loadFacts, loadMemoryMap, loadSkills, removeEntity, saveEntity, switchSkill,
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
      relations: [{ source: 'A', relation: 'lives_in', target: 'B' }], clipped: false, relationsClipped: true, skipped: 0,
    });
    expect(JSON.stringify(map)).not.toContain('PRIVATE');
  });

  it.each([
    { entities: 'no', relations: [] },
    { error: 'graph not available', entities: [], relations: [] },
  ])('rejects a malformed map %#', async value => {
    vi.mocked(fetch).mockResolvedValue(json(value));
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('leaves one odd entry out and counts it, instead of failing the whole map', async () => {
    vi.mocked(fetch).mockResolvedValue(json({
      entities: [
        { name: 'Andrei', type: 'person', first_seen: 1 },
        { name: 'Berlin\nParis', type: 'city', first_seen: 2 },      // a line break the ingester can produce
        { name: 'x'.repeat(300), type: 'city' },
        { name: 'Odd', type: 'T'.repeat(90) },                          // over-long type: drawn as unknown
        {},
      ],
      relations: [
        { source: 'Andrei', relation: 'knows', target: 'Odd' },
        { source: 'Andrei', relation: 'knows', target: 'Berlin\nParis' },   // endpoint left out
        { source: 'Andrei', relation: 'knows', target: 'GHOST' },
      ],
      clipped: false,
    }));
    const map = await loadMemoryMap();
    expect(map.entities.map(e => [e.name, e.type])).toEqual([['Andrei', 'person'], ['Odd', 'unknown']]);
    expect(map.relations).toEqual([{ source: 'Andrei', relation: 'knows', target: 'Odd' }]);
    expect(map.skipped).toBe(3);
  });

  it('leaves a fact with a control character out of the page and counts it', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ axis: 'known', clipped: false, bounds, facts: [
      { id: 1, subject: 'a', predicate: 'p', object: 'b', valid_from: 1, valid_to: null, ingested_at: 1 },
      { id: 2, subject: 'a\nb', predicate: 'p', object: 'b', valid_from: 1, valid_to: null, ingested_at: 1 },
    ] }));
    const page = await loadFacts('known', 5);
    expect(page.facts.map(f => f.id)).toEqual([1]);
    expect(page.skipped).toBe(1);
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
    vi.mocked(fetch).mockResolvedValue(json({ axis: 'known', clipped: false, bounds, facts: 'no' }));
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
    expect(await removeEntity('A B ?')).toEqual({ factsRetracted: 3, graphDeleted: true });
    const [path, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/kg/entities/' + encodeURIComponent('A B ?'));
    expect(init.method).toBe('DELETE');
  });

  it('does not call a lost reply or a 500 "nothing changed": the result is unknown', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('network'));
    await expect(removeEntity('A')).rejects.toMatchObject({ code: 'unknown' });
    await expect(saveEntity('A', 'person', {})).rejects.toMatchObject({ code: 'unknown' });
    vi.mocked(fetch).mockResolvedValue(json({ error: 'boom' }, 500));
    await expect(removeEntity('A')).rejects.toMatchObject({ code: 'unknown' });
    vi.mocked(fetch).mockResolvedValue(json({ error: 'graph not available' }, 503));
    await expect(removeEntity('A')).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('never sends a dot segment, which a URL path cannot carry', async () => {
    for (const name of ['..', '.']) {
      await expect(removeEntity(name)).rejects.toMatchObject({ code: 'unaddressable' });
      await expect(loadEntity(name)).rejects.toMatchObject({ code: 'unaddressable' });
      await expect(saveEntity(name, 'person', {})).rejects.toMatchObject({ code: 'unaddressable' });
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it('carries a name with a slash or a backslash as one percent-encoded segment', async () => {
    for (const name of ['AC/DC', 'x\\y', '/lead', 'trail/']) {
      vi.mocked(fetch).mockClear();
      vi.mocked(fetch).mockResolvedValue(json({ ok: true, deleted: name, graph_deleted: true, facts_retracted: 0 }));
      await removeEntity(name);
      const [path] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
      expect(path).toBe('/api/kg/entities/' + encodeURIComponent(name));
      expect(path.slice('/api/kg/entities/'.length)).not.toMatch(/[/\\]/);
    }
    vi.mocked(fetch).mockClear();
    vi.mocked(fetch).mockResolvedValue(json({ entity: { name: 'AC/DC', type: 'band', properties: { k: 'v' } } }));
    expect(await loadEntity('AC/DC')).toMatchObject({ name: 'AC/DC', type: 'band' });
  });

  it('refuses to edit a name with surrounding whitespace, because the server stores the exact name', async () => {
    for (const name of ['Foo ', ' Foo', 'Foo\u00a0']) {
      await expect(saveEntity(name, 'person', {})).rejects.toMatchObject({ code: 'padded' });
    }
    expect(fetch).not.toHaveBeenCalled();
    expect(isEditable('Foo ')).toBe(false);
    expect(isEditable('Foo')).toBe(true);
    expect(isAddressable('Foo ')).toBe(true);                 // Delete still works by path
  });

  it('leaves out a name that the map code would clean to nothing', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ entities: [{ name: '\u202e', type: 'x', first_seen: 1 }, { name: '\u0085', type: 'x', first_seen: 1 }, { name: 'Ok', type: 'x', first_seen: 1 }], relations: [] }));
    const data = await loadMemoryMap();
    expect(data.entities.map(e => e.name)).toEqual(['Ok']);
    expect(data.skipped).toBe(2);
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


describe('fix round 2: times a calendar cannot hold', () => {
  it('leaves out an entity or fact whose time Date cannot show, and counts it', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({
      entities: [{ name: 'Ok', type: 'x', first_seen: 100 }, { name: 'Huge', type: 'x', first_seen: 1e13 }], relations: [], clipped: false,
    }));
    const map = await loadMemoryMap();
    expect(map.entities.map(e => e.name)).toEqual(['Ok']);
    expect(map.skipped).toBe(1);
    const f = (id: number, over = {}) => ({ id, subject: 'A', predicate: 'p', object: 'B', valid_from: 100, valid_to: null, ingested_at: 100, ...over });
    vi.mocked(fetch).mockResolvedValueOnce(json({
      axis: 'known', clipped: false, facts: [f(1), f(2, { ingested_at: 1e13 }), f(3, { valid_from: -1e13 }), f(4, { valid_to: 1e13 })],
      bounds: { count: 4, first_ingested: 100, last_ingested: 1e13, first_valid: 100, last_change: 1e13 },
    }));
    const page = await loadFacts('known', null);
    expect(page.facts.map(x => x.id)).toEqual([1]);
    expect(page.skipped).toBe(3);
    expect(page.bounds).toMatchObject({ firstIngested: 100, lastIngested: null, lastChange: null });
  });

  it('reports whether the delete reached the live graph', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ ok: true, deleted: 'A', graph_deleted: false, facts_retracted: 2 }));
    expect(await removeEntity('A')).toEqual({ factsRetracted: 2, graphDeleted: false });
    vi.mocked(fetch).mockResolvedValueOnce(json({ ok: true, deleted: 'A', facts_retracted: 0 }));
    expect(await removeEntity('A')).toEqual({ factsRetracted: 0, graphDeleted: true });
  });

  it('says a dot segment cannot be addressed, with its own code', async () => {
    await expect(removeEntity('..')).rejects.toMatchObject({ code: 'unaddressable' });
    await expect(loadEntity('.')).rejects.toMatchObject({ code: 'unaddressable' });
  });
});

describe('mutation hardening: bounds and gates of the client', () => {
  const hugeBody = (bytes: number) => ({ entities: [], relations: [], pad: 'x'.repeat(bytes) });

  it('maps a 401 on the admin-guarded skill switch to the admin code, not auth', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ detail: 'nope' }, 401));
    await expect(switchSkill('web-search', false)).rejects.toMatchObject({ code: 'admin' });
  });

  it('refuses a reply that declares or streams more than the read limit', async () => {
    const tooLongDeclared = new Response(JSON.stringify({ entities: [], relations: [] }),
      { status: 200, headers: { 'Content-Type': 'application/json', 'Content-Length': String(3 * 1024 * 1024) } });
    vi.mocked(fetch).mockResolvedValueOnce(tooLongDeclared);
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'unavailable' });
    const badLength = new Response(JSON.stringify({ entities: [], relations: [] }),
      { status: 200, headers: { 'Content-Type': 'application/json', 'Content-Length': 'abc' } });
    vi.mocked(fetch).mockResolvedValueOnce(badLength);
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'unavailable' });
    // No Content-Length: the streamed size is what is bounded (2 MiB for the map).
    vi.mocked(fetch).mockResolvedValueOnce(json(hugeBody(2.5 * 1024 * 1024)));
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'unavailable' });
    vi.mocked(fetch).mockResolvedValueOnce(json(hugeBody(1024)));
    await expect(loadMemoryMap()).resolves.toMatchObject({ entities: [] });
  });

  it('refuses a map with more than 1000 entities or 4000 relations', async () => {
    const entities = Array.from({ length: 1001 }, (_, i) => ({ name: 'E' + i, type: 't' }));
    vi.mocked(fetch).mockResolvedValueOnce(json({ entities, relations: [] }));
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'unavailable' });
    const relations = Array.from({ length: 4001 }, () => ({ source: 'E0', relation: 'r', target: 'E0' }));
    vi.mocked(fetch).mockResolvedValueOnce(json({ entities: [{ name: 'E0', type: 't' }], relations }));
    await expect(loadMemoryMap()).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('refuses a facts page that answers another axis, and a non-finite instant', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ at: 1, axis: 'valid', clipped: false, bounds, facts: [] }));
    await expect(loadFacts('known', 1)).rejects.toMatchObject({ code: 'unavailable' });
    for (const at of [Number.NaN, Number.POSITIVE_INFINITY]) {
      vi.mocked(fetch).mockClear();
      await expect(loadFacts('known', at)).rejects.toMatchObject({ code: 'unavailable' });
      expect(fetch).not.toHaveBeenCalled();
    }
  });

  it('accepts a 64 character type and refuses a 65 character one', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ ok: true, entity: { name: 'A', type: 'T', properties: {} } }));
    await expect(saveEntity('A', 'T' + 'a'.repeat(63), {})).resolves.toMatchObject({ name: 'A' });
    await expect(saveEntity('A', 'T' + 'a'.repeat(64), {})).rejects.toMatchObject({ code: 'invalid' });
  });

  it('refuses an entity reply that names another entity', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ entity: { name: 'Other', type: 'person', properties: {} }, relations: [] }));
    await expect(loadEntity('Andrei')).rejects.toMatchObject({ code: 'unavailable' });
    vi.mocked(fetch).mockResolvedValue(json({ entity: { name: 'Andrei', type: 'person', properties: { a: 1 } }, relations: [] }));
    await expect(loadEntity('Andrei')).resolves.toMatchObject({ properties: { a: 1 } });
  });

  it('maps 409 to invalid and a 5xx other than 503 to unknown on writes', async () => {
    vi.mocked(fetch).mockResolvedValue(json({ error: 'conflict' }, 409));
    await expect(removeEntity('A')).rejects.toMatchObject({ code: 'invalid', detail: 'conflict' });
    vi.mocked(fetch).mockResolvedValue(json({ error: 'bad gateway' }, 502));
    await expect(removeEntity('A')).rejects.toMatchObject({ code: 'unknown' });
  });
});
