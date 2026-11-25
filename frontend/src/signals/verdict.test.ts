import { describe, expect, it } from 'vitest';
import { stringProblems } from '../frame/strings';
import { initialHubSnapshot } from '../frame/types';
import { SAFE_MODE_OFF } from '../safe-mode-banner';
import { T0, at, checking, empty, healthyInput, hubOf, intactChain, live, offlineReading, refused, stale, unknown, NO_PRESSURE } from './test-support';
import type { PressureEntry } from './types';
import { VERDICT_STRINGS, consequenceOf, verdict } from './verdict';
import type { ObserverStatus, TaskLite } from './wire';

const disk = (over: Partial<PressureEntry> = {}): PressureEntry => ({ condition: 'disk_critical', level: 'critical', dismissed: false, percent: 97, paths: [{ path: 'C:\\', percent: 97 }], ...over });
const memory = (over: Partial<PressureEntry> = {}): PressureEntry => ({ condition: 'memory_elevated', level: 'elevated', dismissed: false, percent: 88, paths: [], ...over });
const pressureOf = (...conditions: PressureEntry[]) => live({ bootId: 'b', conditions, worst: conditions.find((c) => !c.dismissed) ?? null });
const down = (...keys: string[]): ObserverStatus => ({
  enabled: true, probes: 2, tracked: 7,
  unhealthy: keys.map((k, i) => ({ key: `service.${k}`, detail: `${k} not responding on 127.0.0.1:${1000 + i}`, severity: 'CRITICAL' as const, since: at(8, 14 + i) })),
});

describe('the verdict strings', () => {
  it('are complete in English and Romanian', () => expect(stringProblems(VERDICT_STRINGS)).toEqual([]));
});

describe('verdict: each rule', () => {
  it('1 · demo says so and invents no time', () => {
    const v = verdict(healthyInput({ demo: true }));
    expect([v.rule, v.state, v.checkedAt, v.since]).toEqual([1, 'demo', null, null]);
    expect(verdict(healthyInput({ hub: hubOf({ demo: true, state: 'demo' }) })).rule).toBe(1);
  });

  it('2 · the first poll not yet answered is Checking, never normal', () => {
    const v = verdict(healthyInput({ hub: initialHubSnapshot(false) }));
    expect([v.rule, v.state, v.headline]).toEqual([2, 'checking', 'Checking…']);
  });

  it('3 · a hub that stopped answering says when it last did', () => {
    const v = verdict(healthyInput({ hub: hubOf({ state: 'offline', reason: 'network', serverUp: false, lastGoodAt: at(10, 44) }) }));
    expect([v.rule, v.state]).toEqual([3, 'offline']);
    expect(v.headline).toBe('The hub is not answering · last good reading 10:44');
    expect(verdict(healthyInput({ hub: hubOf({ state: 'offline', serverUp: false, lastGoodAt: null }) })).headline).toBe('The hub is not answering');
  });

  it('3 · a loader that committed nothing for 2.5 intervals is offline too, not live', () => {
    const v = verdict(healthyInput({ now: T0 + 100_000 }));
    expect(v.rule).toBe(3);
  });

  it('4 · a global halt', () => {
    const v = verdict(healthyInput({ killSwitch: live({ halted: true }) }));
    expect([v.rule, v.state, v.mark, v.headline]).toEqual([4, 'halted', 'held', 'All agents are stopped']);
    expect(v.link?.href).toBe('/v2/console/kill-switch');
  });

  it('5 · safe mode names what it left out', () => {
    const v = verdict(healthyInput({ hub: hubOf({ safeMode: { enabled: true, skipped: ['owner_skills', 'plugins'] } }) }));
    expect([v.rule, v.state, v.headline]).toEqual([5, 'degraded', 'Running in safe mode · left out: owner_skills, plugins']);
    expect(v.causes.map((c) => c.key)).toEqual(['owner_skills', 'plugins']);
    expect(verdict(healthyInput({ hub: hubOf({ safeMode: { enabled: true, skipped: [] } }) })).headline).toBe('Running in safe mode');
  });

  it('6 · no backend, or no model, is a problem with a link to Model setup', () => {
    const off = verdict(healthyInput({ hub: hubOf({ llm: { state: 'offline', model: null, residents: [] } }) }));
    expect([off.rule, off.state, off.headline]).toEqual([6, 'problem', 'No local backend is reachable']);
    expect(off.link?.href).toBe('/v2/console/model-setup');
    const none = verdict(healthyInput({ hub: hubOf({ llm: { state: 'no_model', model: null, residents: [] } }) }));
    expect(none.headline).toBe('No model is loaded — replies cannot be written');
  });

  it('7 · critical pressure is a problem, and says which disk', () => {
    const v = verdict(healthyInput({ pressure: pressureOf(disk()) }));
    expect([v.rule, v.state, v.headline]).toEqual([7, 'problem', 'Disk C:\\ is 97% full']);
    const oom = verdict(healthyInput({ pressure: pressureOf({ condition: 'oom_restart_suspected', level: 'suspected', dismissed: false, percent: null, paths: [] }) }));
    expect([oom.rule, oom.state]).toEqual([7, 'problem']);
  });

  it('7 and 8 · a dismissed banner does not make a full disk normal', () => {
    expect(verdict(healthyInput({ pressure: pressureOf(disk({ dismissed: true })) })).rule).toBe(7);
    expect(verdict(healthyInput({ pressure: pressureOf(memory({ dismissed: true })) })).rule).toBe(8);
  });

  it('8 · elevated pressure is degraded', () => {
    const v = verdict(healthyInput({ pressure: pressureOf(memory()) }));
    expect([v.rule, v.state, v.headline]).toEqual([8, 'degraded', 'Memory is 88% in use']);
  });

  it('9 · a broken audit chain names the entry', () => {
    const v = verdict(healthyInput({ audit: live({ ...intactChain, valid: false, firstInvalidId: 412 }) }));
    expect([v.rule, v.state, v.headline]).toEqual([9, 'problem', 'The record is broken at entry 412']);
    expect(verdict(healthyInput({ audit: live({ ...intactChain, valid: false, firstInvalidId: null }) })).headline).toBe('The record is broken');
  });

  it('10 · unhealthy probes: the count, the probes\' own words, and the earliest since', () => {
    const v = verdict(healthyInput({ observer: live(down('lmstudio', 'qdrant', 'neo4j', 'n8n')) }));
    expect([v.rule, v.state, v.headline]).toEqual([10, 'degraded', 'Working, with 4 local services not responding']);
    expect(v.causes.map((c) => c.key)).toEqual(['service.lmstudio', 'service.qdrant', 'service.neo4j', 'service.n8n']);
    expect(v.causes[0].detail).toBe('lmstudio not responding on 127.0.0.1:1000');
    expect(v.since).toBe(at(8, 14));
    expect(verdict(healthyInput({ observer: live(down('qdrant')) })).headline).toBe('Working, with 1 local service not responding');
  });

  it('10 · "since" is claimed only when every cause reports one', () => {
    const o: ObserverStatus = { ...down('qdrant', 'n8n'), unhealthy: [{ key: 'service.qdrant', detail: 'q', severity: 'WARN', since: at(9) }, { key: 'service.n8n', detail: 'n', severity: 'WARN', since: null }] };
    expect(verdict(healthyInput({ observer: live(o) })).since).toBeNull();
  });

  it('10 · a probe that is not a service counts as a check, not a service', () => {
    const o: ObserverStatus = { enabled: true, probes: 2, tracked: 3, unhealthy: [{ key: 'resource.ram', detail: 'RAM at 91.0% (≥85.0%)', severity: 'WARN', since: null }] };
    expect(verdict(healthyInput({ observer: live(o) })).headline).toBe('Working, with 1 check not passing');
  });

  it('10 · a restart_service entry naming a down key becomes the remedy (the oldest first)', () => {
    const blocked: TaskLite[] = [
      { id: 9, kind: 'restart_service', title: 'Restart qdrant?', agent: 'steve', createdAt: null, service: 'qdrant' },
      { id: 4, kind: 'restart_service', title: 'Restart qdrant?', agent: 'steve', createdAt: null, service: 'qdrant' },
      { id: 2, kind: 'restart_service', title: 'Restart docker?', agent: 'steve', createdAt: null, service: 'docker' },
      { id: 1, kind: 'send_email', title: 'x', agent: null, createdAt: null, service: null },
    ];
    const v = verdict(healthyInput({ observer: live(down('qdrant')), blocked: live(blocked) }));
    expect(v.remedy).toEqual({ taskId: 4, href: '/v2/cockpit#docket-entry-4', text: 'the first of 2 entries on the docket' });
    const single = verdict(healthyInput({ observer: live(down('qdrant')), blocked: live(blocked.slice(1, 3)) }));
    expect(single.remedy?.text).toBe('its entry on the docket');
    expect(verdict(healthyInput({ observer: live(down('neo4j')), blocked: live(blocked) })).remedy).toBeNull();
    expect(verdict(healthyInput({ observer: live(down('qdrant')), blocked: refused() })).remedy).toBeNull();
  });

  it('10 · without the observer (refused), the ticker\'s WARNING and ALERT items stand in', () => {
    const hub = hubOf({ ticker: [{ agent: 'STEVE', verb: 'WARNING', text: 'docker not responding on 127.0.0.1:2375' }, { agent: 'JARVIS', verb: 'MONITORING', text: 'all quiet' }] });
    const v = verdict(healthyInput({ hub, observer: refused() }));
    expect([v.rule, v.causes.length, v.causes[0].source, v.causes[0].key]).toEqual([10, 1, 'ticker', 'ticker.1']);
    expect(v.missing).toEqual(['the service probes']);
  });

  it('11 · components that did not start', () => {
    const v = verdict(healthyInput({ components: live({ failed: ['kg', 'vision'] }) }));
    expect([v.rule, v.state, v.headline]).toEqual([11, 'degraded', 'Working, with 2 optional components that did not start']);
    expect(v.causes.map((c) => c.key)).toEqual(['kg', 'vision']);
  });

  it('12 · everything current and nothing wrong is normal', () => {
    const v = verdict(healthyInput());
    expect([v.rule, v.state, v.mark, v.headline, v.missing]).toEqual([12, 'normal', 'ok', 'Working normally', undefined]);
    expect(v.checkedAt).toBe(T0);
  });

  it('13 · otherwise unknown, naming what did not answer', () => {
    const v = verdict(healthyInput({ audit: refused(), observer: refused() }));
    expect([v.rule, v.state, v.mark]).toEqual([13, 'unknown', 'unknown']);
    expect(v.headline).toBe('Unknown — the audit chain and the service probes did not answer');
    expect(v.missing).toEqual(['the audit chain', 'the service probes']);
  });
});

describe('verdict: "Working normally" is never claimed on a reading that did not answer', () => {
  const readings: [string, Parameters<typeof healthyInput>[0]][] = [
    ['kill switch', { killSwitch: unknown() }],
    ['pressure', { pressure: refused() }],
    ['audit chain', { audit: offlineReading() }],
    ['observer', { observer: refused() }],
    ['observer switched off', { observer: live({ enabled: false, probes: null, tracked: null, unhealthy: null }) }],
    ['components', { components: unknown() }],
    ['components registry', { components: live({ failed: null }) }],
    ['stale reading', { audit: stale(intactChain) }],
    ['model state', { hub: hubOf({ llm: { state: 'unknown', model: null, residents: [] } }) }],
  ];
  it.each(readings)('%s', (_name, overrides) => {
    const v = verdict(healthyInput(overrides));
    expect(v.state).toBe('unknown');
    expect(v.rule).toBe(13);
  });

  it('a pressure reading that is merely empty is an answer (nothing raised), not a gap', () => {
    expect(verdict(healthyInput({ pressure: empty(NO_PRESSURE) })).rule).toBe(12);
  });
});

describe('verdict: precedence (the first matching rule wins)', () => {
  const everythingWrong = () => healthyInput({
    hub: hubOf({ safeMode: { enabled: true, skipped: [] }, llm: { state: 'offline', model: null, residents: [] } }),
    killSwitch: live({ halted: true }),
    pressure: pressureOf(disk(), memory()),
    audit: live({ ...intactChain, valid: false, firstInvalidId: 7 }),
    observer: live(down('qdrant')),
    components: live({ failed: ['kg'] }),
  });

  it('with safe mode off, each rule gives way to the next', () => {
    let input = { ...everythingWrong(), hub: hubOf({ llm: { state: 'offline', model: null, residents: [] } }) };
    const order: number[] = [];
    order.push(verdict(input).rule);                                              // 4 halted
    input = { ...input, killSwitch: live({ halted: false }) }; order.push(verdict(input).rule);   // 6 no backend
    input = { ...input, hub: hubOf() }; order.push(verdict(input).rule);          // 7 critical pressure
    input = { ...input, pressure: pressureOf(memory()) }; order.push(verdict(input).rule);        // 8 elevated
    input = { ...input, pressure: empty(NO_PRESSURE) }; order.push(verdict(input).rule);          // 9 audit
    input = { ...input, audit: live(intactChain) }; order.push(verdict(input).rule);              // 10 probes
    input = { ...input, observer: live({ enabled: true, probes: 1, tracked: 1, unhealthy: [] }) }; order.push(verdict(input).rule);   // 11 components
    input = { ...input, components: live({ failed: [] }) }; order.push(verdict(input).rule);      // 12 normal
    expect(order).toEqual([4, 6, 7, 8, 9, 10, 11, 12]);
  });

  it('safe mode (5) beats no backend (6), and the ticker keys are unique even when every warning names the same agent', () => {
    expect(verdict({ ...everythingWrong(), killSwitch: live({ halted: false }) }).rule).toBe(5);
    const hub = hubOf({ ticker: [{ agent: 'STEVE', verb: 'WARNING', text: 'a' }, { agent: 'STEVE', verb: 'ALERT', text: 'b' }] });
    const keys = verdict(healthyInput({ hub, observer: refused() })).causes.map((c) => c.key);
    expect(new Set(keys).size).toBe(2);
  });

  it('readings still on their first request are Checking, not "did not answer"', () => {
    const v = verdict(healthyInput({ observer: checking(), components: checking() }));
    expect([v.rule, v.state, v.headline]).toEqual([13, 'checking', 'Checking…']);
    // one that did fail is still named, and the one still checking is not
    const mixed = verdict(healthyInput({ audit: refused(), observer: checking() }));
    expect([mixed.state, mixed.headline]).toEqual(['unknown', 'Unknown — the audit chain did not answer']);
  });

  it('demo beats everything, checking beats offline, offline beats the halt', () => {
    expect(verdict({ ...everythingWrong(), demo: true }).rule).toBe(1);
    expect(verdict({ ...everythingWrong(), hub: initialHubSnapshot(false) }).rule).toBe(2);
    expect(verdict({ ...everythingWrong(), hub: hubOf({ state: 'offline', serverUp: false }) }).rule).toBe(3);
  });

  it('a problem that fired still lists the readings that did not answer', () => {
    const v = verdict(healthyInput({ pressure: pressureOf(disk()), audit: refused() }));
    expect(v.rule).toBe(7);
    expect(v.missing).toEqual(['the audit chain']);
  });
});

describe('verdict: causes and their consequences', () => {
  it('lmstudio down is "not blocking" only when Ollama serves the replies, and the reverse', () => {
    expect(consequenceOf('service.lmstudio', 'ollama')).toBe('Not blocking: replies are served by ollama.');
    expect(consequenceOf('service.ollama', 'lmstudio')).toBe('Not blocking: replies are served by lmstudio.');
    expect(consequenceOf('service.ollama', 'ollama')).toBeNull();     // the one serving the replies is down
    expect(consequenceOf('service.lmstudio', 'lmstudio')).toBeNull();
    expect(consequenceOf('service.lmstudio', null)).toBeNull();
    expect(consequenceOf('service.lmstudio', 'none')).toBeNull();
  });

  it('claims no consequence for qdrant, neo4j or n8n', () => {
    for (const k of ['qdrant', 'neo4j', 'n8n', 'docker']) expect(consequenceOf(`service.${k}`, 'ollama'), k).toBeNull();
    const v = verdict(healthyInput({ observer: live(down('lmstudio', 'qdrant')) }));
    expect(v.causes[0].consequence).toBe('Not blocking: replies are served by ollama.');
    expect(v.causes[1].consequence).toBeNull();
  });
});

describe('verdict: Romanian', () => {
  it('speaks Romanian with correct plurals and diacritics', () => {
    expect(verdict(healthyInput(), 'ro').headline).toBe('Funcționează normal');
    expect(verdict(healthyInput({ observer: live(down('qdrant')) }), 'ro').headline).toBe('Funcționează, cu 1 serviciu local care nu răspunde');
    expect(verdict(healthyInput({ observer: live(down('a', 'b')) }), 'ro').headline).toBe('Funcționează, cu 2 servicii locale care nu răspund');
    expect(verdict(healthyInput({ observer: live(down(...Array.from({ length: 20 }, (_, i) => `s${i}`))) }), 'ro').headline).toContain('20 de servicii locale');
    expect(verdict(healthyInput({ audit: refused() }), 'ro').headline).toBe('Necunoscut — lanțul de audit nu a răspuns');
    expect(verdict(healthyInput({ audit: refused(), observer: refused() }), 'ro').headline).toBe('Necunoscut — lanțul de audit și sondele de servicii nu au răspuns');
  });
});

describe('verdict: the offline hub is not a "normal" one in disguise', () => {
  it('keeps SAFE_MODE_OFF out of rule 5', () => {
    expect(verdict(healthyInput({ hub: hubOf({ safeMode: SAFE_MODE_OFF }) })).rule).toBe(12);
  });
});
