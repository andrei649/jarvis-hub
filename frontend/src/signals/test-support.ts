/* Shared fixtures for the signal tests (not imported by any shipped module). A healthy hub and
   readings in every state, so each test changes only what it is about. */
import { initialHubSnapshot } from '../frame/types';
import { liveReading, unknownReading, checkingReading, type HubSnapshot, type KillSwitchState, type PressureReading, type Reading } from './types';
import type { AuditVerify, ComponentsHealth, ObserverStatus } from './wire';
import type { VerdictInput } from './verdict';

/** Monday 23 November 2026, 10:50 local. */
export const T0 = new Date(2026, 10, 23, 10, 50).getTime();
export const at = (h: number, m = 0, d = 23): number => new Date(2026, 10, d, h, m).getTime();

/** A hub that answered at T0: a model loaded on Ollama, no cloud model, a locality count. */
export function hubOf(overrides: Partial<HubSnapshot> = {}): HubSnapshot {
  return {
    ...initialHubSnapshot(false),
    state: 'live',
    reason: undefined,
    serverUp: true,
    checkedAt: T0,
    lastGoodAt: T0,
    llm: { state: 'ready', model: 'gemma-4-31b', residents: [] },
    backend: 'ollama',
    configuredModel: 'gemma-4-31b',
    residency: 'known',
    trust: { mic: 'on', strictLocal: true, cloudAvailable: false, claudeAvailable: false },
    locality: { local_pct: 95, local: 115, cloud: 0, unknown: 6, total: 121 },
    ...overrides,
  };
}

export const live = <T>(value: T, when: number = T0): Reading<T> => liveReading(value, when);
export const empty = <T>(value: T, when: number = T0): Reading<T> => ({ ...liveReading(value, when), state: 'empty' });
export const refused = <T>(): Reading<T> => ({ state: 'refused', value: null, checkedAt: T0, lastGoodAt: null, reason: 'credential', status: 401 });
export const offlineReading = <T>(value: T | null = null): Reading<T> => ({ state: 'offline', value, checkedAt: T0, lastGoodAt: value ? T0 - 60_000 : null, reason: 'network' });
export const checking = <T>(): Reading<T> => checkingReading<T>();
export const unknown = <T>(): Reading<T> => unknownReading<T>('http');
export const stale = <T>(value: T): Reading<T> => ({ state: 'stale', value, checkedAt: T0, lastGoodAt: T0 - 600_000 });

export const NO_PRESSURE: PressureReading = { bootId: 'b', conditions: [], worst: null };
export const intactChain: AuditVerify = { valid: true, firstInvalidId: null, entries: 921, tamperEvident: true };
export const calmObserver: ObserverStatus = { enabled: true, probes: 2, tracked: 7, unhealthy: [] };
export const allStarted: ComponentsHealth = { failed: [] };

/** Everything current and healthy: the verdict is rule 12. */
export function healthyInput(overrides: Partial<VerdictInput> = {}): VerdictInput {
  return {
    hub: hubOf(),
    now: T0,
    killSwitch: live<KillSwitchState>({ halted: false }),
    audit: live(intactChain),
    observer: live(calmObserver),
    components: live(allStarted),
    pressure: empty(NO_PRESSURE),
    blocked: empty([]),
    docketHref: (id) => `/v2/cockpit#docket-entry-${id}`,
    ...overrides,
  };
}
