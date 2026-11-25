/* The day's verdict: one honest sentence about the hub (PHASE_B_PLAN.md §5.2).

   Pure: readings in, a Verdict out, for one language. The first matching rule wins:

     1  demo                          Demo sample (labelled; invents no time)
     2  first poll not yet answered   Checking
     3  hub stopped answering         Offline    "The hub is not answering · last good reading 10:44"
     4  global halt                   Halted     "All agents are stopped"
     5  safe mode                     Degraded   "Running in safe mode · left out: …"
     6  no backend / no model         Problem
     7  pressure critical             Problem    (disk or memory, or a suspected out-of-memory restart)
     8  pressure elevated             Degraded
     9  audit chain invalid           Problem    "The record is broken at entry N"
    10  unhealthy probes              Degraded   "Working, with N local services not responding"
    11  failed optional components    Degraded
    12  every required reading live   Normal     "Working normally"
    13  otherwise                     Unknown    "Unknown — <which readings> did not answer"

   "Working normally" is claimed only when every reading it rests on is current: the hub, the stop,
   memory and disk, the audit chain, the service probes, the component check and the model state.
   A reading that did not answer never counts as "no problem": it is named in rule 13, and listed
   in `missing` beside a problem that did fire. Dismissing the pressure banner does not clear rule
   7 or 8 (the conditions are read, dismissed or not).

   Causes come from the probes' own words. A consequence line exists only where backend code
   supports it: LM Studio and Ollama are interchangeable local backends, so one being down is "not
   blocking" when the other serves the replies. For qdrant, neo4j and n8n no consequence is
   claimed: Neo4j falls back to an in-memory graph only if it was unreachable when the hub
   started, and Qdrant and n8n have no fallback the HUD can vouch for. */
import { defineStrings, fmt, plural, pick, type Lang } from '../frame/strings';
import { clockTime } from '../frame/kit/strings';
import { hubReading } from '../frame/types';
import { isCurrent } from './types';
import type { Cause, HubSnapshot, KillSwitchState, PressureEntry, PressureReading, Reading, Verdict } from './types';
import type { AuditVerify, ComponentsHealth, ObserverProbe, ObserverStatus, TaskLite } from './wire';

export const VERDICT_STRINGS = defineStrings({
  en: {
    stateDemo: 'Demo sample',
    stateChecking: 'Checking',
    stateOffline: 'Offline',
    stateHalted: 'Halted',
    stateDegraded: 'Degraded',
    stateProblem: 'Problem',
    stateNormal: 'Normal',
    stateUnknown: 'Unknown',
    headlineDemo: 'Working, with 4 local services not responding',
    headlineChecking: 'Checking…',
    headlineOffline: 'The hub is not answering · last good reading {time}',
    headlineOfflineNoTime: 'The hub is not answering',
    headlineHalted: 'All agents are stopped',
    linkHalted: 'Resume in Trust › Emergency stop',
    headlineSafe: 'Running in safe mode',
    headlineSafeLeft: 'Running in safe mode · left out: {list}',
    headlineNoBackend: 'No local backend is reachable',
    headlineNoModel: 'No model is loaded — replies cannot be written',
    linkModel: 'Open Model setup',
    diskNamed: 'Disk {path} is {pct}% full',
    diskPct: 'Disk is {pct}% full',
    diskLow: 'Disk space is running low',
    memoryPct: 'Memory is {pct}% in use',
    memoryLow: 'Memory is running low',
    oomSuspected: 'The hub restarted after running out of memory (suspected)',
    headlineAudit: 'The record is broken at entry {n}',
    headlineAuditNoId: 'The record is broken',
    linkTrust: 'Open Trust',
    headlineServices: { one: 'Working, with {n} local service not responding', few: 'Working, with {n} local services not responding', other: 'Working, with {n} local services not responding' },
    headlineChecks: { one: 'Working, with {n} check not passing', few: 'Working, with {n} checks not passing', other: 'Working, with {n} checks not passing' },
    headlineComponents: { one: 'Working, with {n} optional component that did not start', few: 'Working, with {n} optional components that did not start', other: 'Working, with {n} optional components that did not start' },
    headlineNormal: 'Working normally',
    headlineUnknown: { one: 'Unknown — {list} did not answer', few: 'Unknown — {list} did not answer', other: 'Unknown — {list} did not answer' },
    missingHub: 'the hub status',
    missingStop: 'the emergency stop',
    missingAudit: 'the audit chain',
    missingProbes: 'the service probes',
    missingComponents: 'the component check',
    missingPressure: 'the memory and disk readings',
    missingModel: 'the model state',
    causeHalt: 'The global halt is on',
    causeBroken: 'Chain broken at entry {n}',
    causeBrokenNoId: 'Chain broken',
    causeNotStarted: 'Did not start',
    causeSafe: 'Left out in safe mode',
    causeNoBackend: 'No local backend answered',
    causeNoModel: 'The backend holds no model',
    consequenceBackend: 'Not blocking: replies are served by {backend}.',
    remedyLink: { one: 'its entry on the docket', few: 'the first of {n} entries on the docket', other: 'the first of {n} entries on the docket' },
    demoCauseDetail: 'Not responding (demo sample)',
    and: 'and',
  },
  ro: {
    stateDemo: 'Mostră demo',
    stateChecking: 'Se verifică',
    stateOffline: 'Deconectat',
    stateHalted: 'Oprit',
    stateDegraded: 'Degradat',
    stateProblem: 'Problemă',
    stateNormal: 'Normal',
    stateUnknown: 'Necunoscut',
    headlineDemo: 'Funcționează, cu 4 servicii locale care nu răspund',
    headlineChecking: 'Se verifică…',
    headlineOffline: 'Hubul nu răspunde · ultima citire bună la {time}',
    headlineOfflineNoTime: 'Hubul nu răspunde',
    headlineHalted: 'Toți agenții sunt opriți',
    linkHalted: 'Reia din Încredere › Oprire de urgență',
    headlineSafe: 'Rulează în mod sigur',
    headlineSafeLeft: 'Rulează în mod sigur · lăsate deoparte: {list}',
    headlineNoBackend: 'Niciun backend local nu este accesibil',
    headlineNoModel: 'Niciun model nu este încărcat — răspunsurile nu pot fi scrise',
    linkModel: 'Deschide configurarea modelului',
    diskNamed: 'Discul {path} este plin în proporție de {pct}%',
    diskPct: 'Discul este plin în proporție de {pct}%',
    diskLow: 'Spațiul de pe disc se împuținează',
    memoryPct: 'Memoria este folosită în proporție de {pct}%',
    memoryLow: 'Memoria se împuținează',
    oomSuspected: 'Hubul a repornit după ce a rămas fără memorie (suspectat)',
    headlineAudit: 'Registrul este rupt la intrarea {n}',
    headlineAuditNoId: 'Registrul este rupt',
    linkTrust: 'Deschide Încredere',
    headlineServices: { one: 'Funcționează, cu {n} serviciu local care nu răspunde', few: 'Funcționează, cu {n} servicii locale care nu răspund', other: 'Funcționează, cu {n} de servicii locale care nu răspund' },
    headlineChecks: { one: 'Funcționează, cu {n} verificare care nu trece', few: 'Funcționează, cu {n} verificări care nu trec', other: 'Funcționează, cu {n} de verificări care nu trec' },
    headlineComponents: { one: 'Funcționează, cu {n} componentă opțională care nu a pornit', few: 'Funcționează, cu {n} componente opționale care nu au pornit', other: 'Funcționează, cu {n} de componente opționale care nu au pornit' },
    headlineNormal: 'Funcționează normal',
    headlineUnknown: { one: 'Necunoscut — {list} nu a răspuns', few: 'Necunoscut — {list} nu au răspuns', other: 'Necunoscut — {list} nu au răspuns' },
    missingHub: 'starea hubului',
    missingStop: 'oprirea de urgență',
    missingAudit: 'lanțul de audit',
    missingProbes: 'sondele de servicii',
    missingComponents: 'verificarea componentelor',
    missingPressure: 'citirile de memorie și disc',
    missingModel: 'starea modelului',
    causeHalt: 'Oprirea globală este activă',
    causeBroken: 'Lanț rupt la intrarea {n}',
    causeBrokenNoId: 'Lanț rupt',
    causeNotStarted: 'Nu a pornit',
    causeSafe: 'Lăsat deoparte în modul sigur',
    causeNoBackend: 'Niciun backend local nu a răspuns',
    causeNoModel: 'Backendul nu ține niciun model',
    consequenceBackend: 'Nu blochează: răspunsurile sunt servite de {backend}.',
    remedyLink: { one: 'intrarea sa din registrul de semnături', few: 'prima dintre cele {n} intrări din registrul de semnături', other: 'prima dintre cele {n} de intrări din registrul de semnături' },
    demoCauseDetail: 'Nu răspunde (mostră demo)',
    and: 'și',
  },
});

export interface VerdictInput {
  readonly hub: HubSnapshot;
  /** Epoch ms for staleness (default Date.now()). */
  readonly now?: number;
  readonly demo?: boolean;
  readonly killSwitch: Reading<KillSwitchState>;
  readonly audit: Reading<AuditVerify>;
  readonly observer: Reading<ObserverStatus>;
  readonly components: Reading<ComponentsHealth>;
  readonly pressure: Reading<PressureReading>;
  /** The blocked tasks (the docket's feed), for the remedy link to a restart_service entry. */
  readonly blocked?: Reading<readonly TaskLite[]> | null;
  /** A ready href for a docket entry (docket/links.ts docketHref). */
  readonly docketHref?: (taskId: number) => string;
}

const TRUST_PATH = '/v2/trust';
const KILL_SWITCH_PATH = '/v2/console/kill-switch';
const MODEL_SETUP_PATH = '/v2/console/model-setup';

/** The local backends that stand in for each other. */
const BACKEND_PEERS: Readonly<Record<string, string>> = { lmstudio: 'ollama', ollama: 'lmstudio' };
const SERVICE_PREFIX = 'service.';

/** A reading's value when it holds one worth warning about (live, stale or last-known). */
function held<T>(r: Reading<T>): T | null {
  return r.state === 'demo' || r.state === 'disabled' ? null : r.value;
}

/** The consequence of a down service, from the fixed map (never generated copy). */
export function consequenceOf(key: string, backend: string | null, lang: Lang | string = 'en'): string | null {
  if (!key.startsWith(SERVICE_PREFIX) || !backend || backend === 'none') return null;
  const name = key.slice(SERVICE_PREFIX.length);
  const peer = BACKEND_PEERS[name];
  if (!peer || backend !== peer) return null;
  return fmt(pick(VERDICT_STRINGS, lang).consequenceBackend, { backend });
}

function pressureDetail(entry: PressureEntry, lang: Lang): string {
  const s = pick(VERDICT_STRINGS, lang);
  if (entry.condition === 'oom_restart_suspected') return s.oomSuspected;
  if (entry.condition.startsWith('disk')) {
    const top = entry.paths[0];
    if (top) return fmt(s.diskNamed, { path: top.path, pct: top.percent });
    return entry.percent !== null ? fmt(s.diskPct, { pct: entry.percent }) : s.diskLow;
  }
  return entry.percent !== null ? fmt(s.memoryPct, { pct: entry.percent }) : s.memoryLow;
}

function probeCause(p: ObserverProbe, backend: string | null, lang: Lang): Cause {
  return {
    key: p.key, detail: p.detail, mark: 'problem', severity: p.severity, consequence: consequenceOf(p.key, backend, lang),
    since: p.since, source: 'observer',
  };
}

/** WARNING and ALERT items of the situation ticker: the fallback when the observer (admin) cannot be read. */
function tickerCauses(hub: HubSnapshot): Cause[] {
  // Keyed by position: /ticker labels every observer warning with the same agent, and the agent is
  // not a probe key. The key must be unique (it is a React key and a problem id).
  let n = 0;
  return hub.ticker.flatMap((item): Cause[] => {
    const verb = String(item?.verb ?? '').toUpperCase();
    const detail = typeof item?.text === 'string' ? item.text.trim() : '';
    if ((verb !== 'WARNING' && verb !== 'ALERT') || !detail) return [];
    n += 1;
    return [{ key: `ticker.${n}`, detail, mark: 'problem', severity: verb, consequence: null, since: null, source: 'ticker' }];
  });
}

const earliest = (causes: readonly Cause[]): number | null => {
  if (!causes.length || causes.some((c) => c.since == null)) return null;
  return Math.min(...causes.map((c) => c.since as number));
};

function listOf(and: string, items: readonly string[]): string {
  if (items.length < 2) return items.join('');
  return `${items.slice(0, -1).join(', ')} ${and} ${items[items.length - 1]}`;
}

/** The verdict for one language. */
export function verdict(input: VerdictInput, langIn: Lang | string = 'en'): Verdict {
  const lang: Lang = langIn === 'ro' ? 'ro' : 'en';
  const s = pick(VERDICT_STRINGS, lang);
  const { hub, killSwitch, audit, observer, components, pressure } = input;
  const now = input.now ?? Date.now();
  const checkedAt = hub.checkedAt;
  const make = (v: Omit<Verdict, 'checkedAt' | 'since'> & { since?: number | null; checkedAt?: number | null }): Verdict => ({ checkedAt, since: null, ...v });

  // 1 · demo
  if (input.demo || hub.demo) {
    const keys = ['lmstudio', 'qdrant', 'neo4j', 'n8n'];
    return make({
      state: 'demo', rule: 1, mark: 'attn', headline: s.headlineDemo,
      causes: keys.map((k) => ({ key: `${SERVICE_PREFIX}${k}`, detail: s.demoCauseDetail, mark: 'problem' as const, severity: null, consequence: null, since: null, source: 'observer' as const })),
      checkedAt: null,
    });
  }

  const hr = hubReading(hub, now);
  // 2 · first poll
  if (hr.state === 'unknown' && hr.reason === 'checking') {
    return make({ state: 'checking', rule: 2, mark: 'unknown', headline: s.headlineChecking, causes: [] });
  }
  // 3 · the hub stopped answering (no answer, or none good for 2.5 loader intervals)
  if (hr.state === 'offline' || hr.state === 'stale') {
    const headline = hub.lastGoodAt !== null ? fmt(s.headlineOffline, { time: clockTime(hub.lastGoodAt) }) : s.headlineOfflineNoTime;
    return make({ state: 'offline', rule: 3, mark: 'unknown', headline, causes: [] });
  }

  const backend = hub.backend && hub.backend !== 'none' ? hub.backend : null;

  // readings that did not answer, by their name (used by rules 5–11 as a note, and by 12 and 13)
  const missingKeys: string[] = [];
  // A reading that is still on its first request is Checking, not "did not answer" (rule 13).
  const stillChecking = new Set<string>();
  const note = (key: string, reading?: Reading<unknown>) => {
    missingKeys.push(key);
    if (reading && reading.state === 'unknown' && reading.reason === 'checking') stillChecking.add(key);
  };
  if (hr.state !== 'live') note('missingHub');
  if (!isCurrent(killSwitch)) note('missingStop', killSwitch);
  if (!isCurrent(pressure)) note('missingPressure', pressure);
  if (!isCurrent(audit)) note('missingAudit', audit);
  const observerValue = held(observer);
  const probesKnown = isCurrent(observer) && !!observerValue && observerValue.enabled && observerValue.unhealthy !== null;
  if (!probesKnown) note('missingProbes', observer);
  if (!(isCurrent(components) && components.value && components.value.failed !== null)) note('missingComponents', components);
  if (hub.llm.state !== 'ready') note('missingModel');
  const missingWords = missingKeys.map((k) => s[k as 'missingHub']);
  const withMissing = (v: Verdict): Verdict => (missingWords.length ? { ...v, missing: missingWords, missingKeys } : v);

  // 4 · global halt
  if (held(killSwitch)?.halted === true) {
    return withMissing(make({
      state: 'halted', rule: 4, mark: 'held', headline: s.headlineHalted,
      causes: [{ key: 'kill-switch', detail: s.causeHalt, mark: 'held', consequence: null, since: null, source: 'kill-switch' }],
      link: { href: KILL_SWITCH_PATH, text: s.linkHalted },
    }));
  }

  // 5 · safe mode
  if (hub.safeMode.enabled) {
    const left = hub.safeMode.skipped;
    return withMissing(make({
      state: 'degraded', rule: 5, mark: 'attn',
      headline: left.length ? fmt(s.headlineSafeLeft, { list: left.join(', ') }) : s.headlineSafe,
      causes: left.map((key): Cause => ({ key, detail: s.causeSafe, mark: 'problem', consequence: null, since: null, source: 'status' })),
    }));
  }

  // 6 · no backend, no model
  if (hub.llm.state === 'offline' || hub.llm.state === 'no_model') {
    const offline = hub.llm.state === 'offline';
    return withMissing(make({
      state: 'problem', rule: 6, mark: 'problem', headline: offline ? s.headlineNoBackend : s.headlineNoModel,
      causes: [{ key: backend ?? 'model', detail: offline ? s.causeNoBackend : s.causeNoModel, mark: 'problem', consequence: null, since: null, source: 'status' }],
      link: { href: MODEL_SETUP_PATH, text: s.linkModel },
    }));
  }

  // 7 and 8 · pressure (every raised condition, dismissed or not)
  const conditions = held(pressure)?.conditions ?? [];
  const critical = conditions.filter((c) => c.level === 'critical' || c.level === 'suspected');
  if (critical.length) {
    return withMissing(make({
      state: 'problem', rule: 7, mark: 'problem', headline: pressureDetail(critical[0], lang),
      causes: critical.map((c): Cause => ({ key: c.condition, detail: pressureDetail(c, lang), mark: 'problem', consequence: null, since: null, source: 'pressure' })),
    }));
  }
  const elevated = conditions.filter((c) => c.level === 'elevated');
  if (elevated.length) {
    return withMissing(make({
      state: 'degraded', rule: 8, mark: 'attn', headline: pressureDetail(elevated[0], lang),
      causes: elevated.map((c): Cause => ({ key: c.condition, detail: pressureDetail(c, lang), mark: 'attn', consequence: null, since: null, source: 'pressure' })),
    }));
  }

  // 9 · the record is broken
  const auditValue = held(audit);
  if (auditValue && !auditValue.valid) {
    const id = auditValue.firstInvalidId;
    return withMissing(make({
      state: 'problem', rule: 9, mark: 'problem', headline: id !== null ? fmt(s.headlineAudit, { n: id }) : s.headlineAuditNoId,
      causes: [{ key: 'audit-chain', detail: id !== null ? fmt(s.causeBroken, { n: id }) : s.causeBrokenNoId, mark: 'problem', consequence: null, since: null, source: 'audit' }],
      link: { href: TRUST_PATH, text: s.linkTrust },
    }));
  }

  // 10 · unhealthy probes (the observer, else the ticker's warnings)
  const probeCauses = observerValue && observerValue.enabled && observerValue.unhealthy
    ? observerValue.unhealthy.map((p) => probeCause(p, backend, lang))
    : tickerCauses(hub);
  if (probeCauses.length) {
    const n = probeCauses.length;
    const services = probeCauses.filter((c) => c.key.startsWith(SERVICE_PREFIX)).length;
    const headline = services === n ? plural(lang, s.headlineServices, n) : plural(lang, s.headlineChecks, n);
    const down = new Set(probeCauses.filter((c) => c.key.startsWith(SERVICE_PREFIX)).map((c) => c.key.slice(SERVICE_PREFIX.length)));
    const fixes = ((input.blocked ? held(input.blocked) : null) ?? [])
      .filter((t) => t.kind === 'restart_service' && t.service !== null && down.has(t.service))
      .sort((a, b) => a.id - b.id);
    const remedy = fixes.length && input.docketHref
      ? { taskId: fixes[0].id, href: input.docketHref(fixes[0].id), text: plural(lang, s.remedyLink, fixes.length) }
      : null;
    return withMissing(make({ state: 'degraded', rule: 10, mark: 'attn', headline, causes: probeCauses, remedy, since: earliest(probeCauses) }));
  }

  // 11 · optional components that did not start
  const failed = held(components)?.failed ?? [];
  if (failed.length) {
    return withMissing(make({
      state: 'degraded', rule: 11, mark: 'attn', headline: plural(lang, s.headlineComponents, failed.length),
      causes: failed.map((key): Cause => ({ key, detail: s.causeNotStarted, mark: 'problem', consequence: null, since: null, source: 'components' })),
    }));
  }

  // 12 · everything it rests on is current, and nothing is wrong
  if (!missingKeys.length) {
    return make({ state: 'normal', rule: 12, mark: 'ok', headline: s.headlineNormal, causes: [] });
  }

  // 13 · otherwise. Readings still on their first request are not "unanswered": while every
  // missing one is checking, the verdict is Checking.
  const unanswered = missingKeys.filter((k) => !stillChecking.has(k));
  if (!unanswered.length) {
    return make({ state: 'checking', rule: 13, mark: 'unknown', headline: s.headlineChecking, causes: [], missingKeys });
  }
  const unansweredWords = unanswered.map((k) => s[k as 'missingHub']);
  return make({
    state: 'unknown', rule: 13, mark: 'unknown', headline: plural(lang, s.headlineUnknown, unansweredWords.length, { list: listOf(s.and, unansweredWords) }),
    causes: [], missing: unansweredWords, missingKeys,
  });
}
