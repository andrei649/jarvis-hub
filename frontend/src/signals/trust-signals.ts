/* The six running-head signals, in words (PHASE_B_PLAN.md §4.2; gap-5 §7).

   Pure: the hub snapshot, the audit reading and (optionally) the egress ledger in, six
   SignalView out, for one language. What this module will not say:

     - "Sealed — nothing can leave this machine": the hub knows whether a cloud model is
       configured (a setting), not where bytes went. Egress says "No cloud model configured",
       basis declared, and adds the measured ledger count only when the admin ledger answered;
     - a bare percentage: the local route is a count of runs with its window and its basis
       ("115 of 121 runs · all time · by route"), never "100%";
     - 0 for unknown: a trust status, locality figure, model state or audit verdict that did not
       answer is "Unknown", "Checking…" or its refusal, never a default.

   The running head draws `label`/`value` at three widths (long ≥ 1680 px, short, marks) and
   a Disclosure with `detail`: what it means, its basis, when it was checked. */
import { defineStrings, fmt, plural, pick, type Lang } from '../frame/strings';
import { basisWords, clockTime } from '../frame/kit/strings';
import type { MarkKind } from '../frame/kit/marks';
import { hubReading } from '../frame/types';
import type { AuditVerify, EgressLedger } from './wire';
import type { Basis, HubSnapshot, Reading, ReadingState, SignalId, SignalView } from './types';

export const TRUST_SIGNAL_STRINGS = defineStrings({
  en: {
    demoSample: 'Demo sample',
    // the short form the running head draws below 2200px: the section says "Demo sample" beside it
    // (the approval mode's source label) and the notice under it, so six repeats add only width
    demoShort: 'Demo',
    checking: 'Checking…',
    basis: 'Basis: {basis}',
    checkedAt: 'Checked at {time}',
    notChecked: 'Not checked yet',
    // egress
    egressLabel: 'Egress',
    egressNoCloud: 'No cloud model configured',
    egressNoCloudShort: 'No cloud model',
    egressNoCloudMarks: 'No cloud model',
    egressCloud: 'Cloud model configured · {which}',
    egressCloudShort: 'Cloud model configured',
    egressCloudMarks: 'Cloud model',
    whichAnthropic: 'Anthropic',
    whichGemini: 'Gemini or compatible',
    whichBoth: 'Anthropic, Gemini or compatible',
    egressUnknown: 'Unknown — trust status did not answer',
    egressUnknownShort: 'Unknown',
    egressMeaningNoCloud: 'A setting, not a network measurement; plugins such as weather can still reach the internet.',
    egressMeaningCloud: 'A cloud model is set up, so a prompt can leave this machine when an agent is routed to it.',
    egressStrictAlso: 'The strict-local flag is also set; it is a setting, not proof that no cloud route is used.',
    ledgerSince: { one: '{n} request left this machine since {time}', few: '{n} requests left this machine since {time}', other: '{n} requests left this machine since {time}' },
    ledgerNoSince: { one: '{n} request left this machine', few: '{n} requests left this machine', other: '{n} requests left this machine' },
    ledgerModels: '{n} from models',
    ledgerBasis: 'The request count is measured by the hub\'s egress ledger.',
    // local route
    routeLabelLong: 'Sent to local runners',
    routeLabelShort: 'Local route',
    routeRuns: '{local} of {total} runs · all time · by route',
    routeRunsShort: '{local} of {total} · by route',
    routeRunsMarks: '{local}/{total}',
    routeNone: 'No runs recorded · derived from configuration',
    routeNoneShort: 'No runs recorded',
    routeNoneMarks: 'No runs',
    routeNoRoute: 'No run recorded a route · derived from configuration',
    routeNoRouteShort: 'No route recorded',
    routeNoRouteMarks: 'No route',
    routeUnknown: 'Unknown — locality did not answer',
    routeUnknownShort: 'Unknown',
    routeMeaning: 'Counted from each run\'s route label: where the hub sent the prompt, not where the model computed.',
    routeNoneMeaning: 'No run has been recorded yet, so there is nothing to count. This is read from the configuration, not measured.',
    routeUnrouted: { one: '{n} run recorded no route and is not counted as local.', few: '{n} runs recorded no route and are not counted as local.', other: '{n} runs recorded no route and are not counted as local.' },
    routeCloud: { one: '{n} run was routed to a cloud model.', few: '{n} runs were routed to a cloud model.', other: '{n} runs were routed to a cloud model.' },
    routeLan: 'Local includes runners on your home network.',
    // microphone
    micLabel: 'Microphone',
    micOn: 'On',
    micMuted: 'Muted',
    micUnknown: 'Unknown',
    micMeaning: 'The hub\'s microphone permission.',
    micListening: 'Listening now.',
    // model
    modelLabel: 'Model',
    modelVia: '· {backend}',
    modelLoadedNoId: 'Model loaded',
    modelNoModel: 'No model loaded',
    modelNoBackend: 'No local backend reachable',
    modelUnknown: 'Unknown',
    modelMeaningReady: 'The model the hub found loaded on its local backend.',
    modelMeaningNoModel: 'The backend answered but holds no model; replies cannot be written.',
    modelMeaningNoBackend: 'No local backend answered; replies cannot be written.',
    modelMeaningUnknown: 'The hub did not say whether a model is loaded.',
    modelConfigured: 'Configured model: {model} (a setting, not a measurement).',
    modelResidency: 'The local runners could not say which models they hold.',
    // data on screen
    dataLabelLong: 'Data on screen',
    dataLabelShort: 'Data',
    dataLive: 'Live · checked {time}',
    dataLiveShort: 'Live',
    dataStale: 'Stale · checked {time}',
    dataStaleShort: 'Stale',
    dataOffline: 'Offline · last good reading {time}',
    dataOfflineNoTime: 'Offline',
    dataOfflineShort: 'Offline',
    dataUnknown: 'Unknown',
    dataMeaning: 'How recently the hub\'s status was read; it is asked every 30 seconds.',
    // audit chain
    chainLabelLong: 'Audit chain',
    chainLabelShort: 'Chain',
    chainIntact: 'Intact · {n} sealed · verified {time}',
    chainIntactNoCount: 'Intact · verified {time}',
    chainIntactShort: 'Intact',
    chainBroken: 'Broken at entry {n}',
    chainBrokenNoId: 'Broken',
    chainUnknown: 'Unknown — could not verify',
    chainRefused: 'Unknown — needs the owner credential',
    chainUnknownShort: 'Unknown',
    chainMeaningKeyed: 'Each entry is sealed to the one before it, with a key: an edit cannot be recomputed without it.',
    chainMeaningUnkeyed: 'Each entry is sealed to the one before it, without a key: this catches accidental damage and is not tamper evidence.',
    chainMeaningBroken: 'An entry no longer matches its seal.',
  },
  ro: {
    demoSample: 'Mostră demo',
    demoShort: 'Demo',
    checking: 'Se verifică…',
    basis: 'Temei: {basis}',
    checkedAt: 'Verificat la {time}',
    notChecked: 'Încă neverificat',
    egressLabel: 'Ieșire',
    egressNoCloud: 'Niciun model cloud configurat',
    egressNoCloudShort: 'Fără model cloud',
    egressNoCloudMarks: 'Fără model cloud',
    egressCloud: 'Model cloud configurat · {which}',
    egressCloudShort: 'Model cloud configurat',
    egressCloudMarks: 'Model cloud',
    whichAnthropic: 'Anthropic',
    whichGemini: 'Gemini sau compatibil',
    whichBoth: 'Anthropic, Gemini sau compatibil',
    egressUnknown: 'Necunoscut — starea de încredere nu a răspuns',
    egressUnknownShort: 'Necunoscut',
    egressMeaningNoCloud: 'O setare, nu o măsurătoare de rețea; pluginuri precum vremea pot totuși accesa internetul.',
    egressMeaningCloud: 'Un model cloud este configurat, deci un prompt poate părăsi acest calculator când un agent este direcționat către el.',
    egressStrictAlso: 'Indicatorul strict-local este și el setat; este o setare, nu o dovadă că nu se folosește nicio rută cloud.',
    ledgerSince: { one: '{n} cerere a părăsit acest calculator din {time}', few: '{n} cereri au părăsit acest calculator din {time}', other: '{n} de cereri au părăsit acest calculator din {time}' },
    ledgerNoSince: { one: '{n} cerere a părăsit acest calculator', few: '{n} cereri au părăsit acest calculator', other: '{n} de cereri au părăsit acest calculator' },
    ledgerModels: '{n} de la modele',
    ledgerBasis: 'Numărul de cereri este măsurat de registrul de ieșiri al hubului.',
    routeLabelLong: 'Trimis către executoare locale',
    routeLabelShort: 'Rută locală',
    routeRuns: '{local} din {total} rulări · tot timpul · după rută',
    routeRunsShort: '{local} din {total} · după rută',
    routeRunsMarks: '{local}/{total}',
    routeNone: 'Nicio rulare înregistrată · dedus din configurare',
    routeNoneShort: 'Nicio rulare',
    routeNoneMarks: 'Nicio rulare',
    routeNoRoute: 'Nicio rulare nu are rută înregistrată · dedus din configurare',
    routeNoRouteShort: 'Nicio rută înregistrată',
    routeNoRouteMarks: 'Nicio rută',
    routeUnknown: 'Necunoscut — localitatea nu a răspuns',
    routeUnknownShort: 'Necunoscut',
    routeMeaning: 'Numărat după eticheta de rută a fiecărei rulări: unde a trimis hubul promptul, nu unde a calculat modelul.',
    routeNoneMeaning: 'Nu s-a înregistrat încă nicio rulare, deci nu e nimic de numărat. Se citește din configurare, nu e măsurat.',
    routeUnrouted: { one: '{n} rulare nu are rută înregistrată și nu e numărată ca locală.', few: '{n} rulări nu au rută înregistrată și nu sunt numărate ca locale.', other: '{n} de rulări nu au rută înregistrată și nu sunt numărate ca locale.' },
    routeCloud: { one: '{n} rulare a fost direcționată către un model cloud.', few: '{n} rulări au fost direcționate către un model cloud.', other: '{n} de rulări au fost direcționate către un model cloud.' },
    routeLan: 'Local include executoarele din rețeaua ta de acasă.',
    micLabel: 'Microfon',
    micOn: 'Pornit',
    micMuted: 'Oprit',
    micUnknown: 'Necunoscut',
    micMeaning: 'Permisiunea de microfon a hubului.',
    micListening: 'Ascultă acum.',
    modelLabel: 'Model',
    modelVia: '· {backend}',
    modelLoadedNoId: 'Model încărcat',
    modelNoModel: 'Niciun model încărcat',
    modelNoBackend: 'Niciun backend local accesibil',
    modelUnknown: 'Necunoscut',
    modelMeaningReady: 'Modelul pe care hubul l-a găsit încărcat pe backendul său local.',
    modelMeaningNoModel: 'Backendul a răspuns, dar nu ține niciun model; răspunsurile nu pot fi scrise.',
    modelMeaningNoBackend: 'Niciun backend local nu a răspuns; răspunsurile nu pot fi scrise.',
    modelMeaningUnknown: 'Hubul nu a spus dacă un model este încărcat.',
    modelConfigured: 'Model configurat: {model} (o setare, nu o măsurătoare).',
    modelResidency: 'Executoarele locale nu au putut spune ce modele țin încărcate.',
    dataLabelLong: 'Date pe ecran',
    dataLabelShort: 'Date',
    dataLive: 'În direct · actualizat la {time}',
    dataLiveShort: 'În direct',
    dataStale: 'Învechit · actualizat la {time}',
    dataStaleShort: 'Învechit',
    dataOffline: 'Deconectat · ultima citire bună la {time}',
    dataOfflineNoTime: 'Deconectat',
    dataOfflineShort: 'Deconectat',
    dataUnknown: 'Necunoscut',
    dataMeaning: 'Cât de recent a fost citită starea hubului; este întrebat la fiecare 30 de secunde.',
    chainLabelLong: 'Lanț de audit',
    chainLabelShort: 'Lanț',
    chainIntact: 'Intact · {n} sigilate · verificat la {time}',
    chainIntactNoCount: 'Intact · verificat la {time}',
    chainIntactShort: 'Intact',
    chainBroken: 'Rupt la intrarea {n}',
    chainBrokenNoId: 'Rupt',
    chainUnknown: 'Necunoscut — nu s-a putut verifica',
    chainRefused: 'Necunoscut — necesită credențialul proprietarului',
    chainUnknownShort: 'Necunoscut',
    chainMeaningKeyed: 'Fiecare intrare este sigilată de cea dinainte, cu o cheie: o modificare nu poate fi recalculată fără ea.',
    chainMeaningUnkeyed: 'Fiecare intrare este sigilată de cea dinainte, fără cheie: prinde stricăciunile accidentale și nu este dovadă de manipulare.',
    chainMeaningBroken: 'O intrare nu se mai potrivește cu sigiliul ei.',
  },
});

export interface TrustSignalsInput {
  readonly hub: HubSnapshot;
  /** Epoch ms for staleness (default Date.now()). */
  readonly now?: number;
  /** Demo mode: every signal says "Demo sample" and invents nothing. */
  readonly demo?: boolean;
  /** GET /api/security/audit/verify. */
  readonly audit: Reading<AuditVerify>;
  /** GET /api/admin/network/calls (admin). Optional: absent, refused or unreadable adds nothing. */
  readonly egress?: Reading<EgressLedger> | null;
  /** App's useVoice() status; 'listening' adds "Listening now". */
  readonly voiceStatus?: string | null;
}

type S = ReturnType<typeof pick<typeof TRUST_SIGNAL_STRINGS.en>>;

interface Parts {
  id: SignalId;
  state: ReadingState;
  mark: MarkKind;
  label: { long: string; short: string };
  value: { long: string; short: string; marks: string };
  ident?: string | null;
  basis?: Basis;
  meaning: string[];
  checkedAt: number | null;
  href?: string;
}

function view(p: Parts, s: S, lang: Lang): SignalView {
  const detail = [...p.meaning];
  if (p.basis) detail.push(fmt(s.basis, { basis: basisWords(p.basis, lang) }));
  detail.push(p.checkedAt !== null ? fmt(s.checkedAt, { time: clockTime(p.checkedAt) }) : s.notChecked);
  return {
    id: p.id, state: p.state, mark: p.mark, label: p.label, value: p.value,
    ...(p.ident ? { ident: p.ident } : {}), ...(p.basis ? { basis: p.basis } : {}),
    detail, checkedAt: p.checkedAt, ...(p.href ? { href: p.href } : {}),
  };
}

const same = (text: string) => ({ long: text, short: text, marks: text });
const checkingOf = (hub: HubSnapshot) => hub.state === 'unknown' && hub.reason === 'checking';

const MODEL_SETUP_PATH = '/v2/console/model-setup';

/** `at` as a clock time when it is today, else with its date: the ledger's tallies count from the
 *  first row ever stored, which can be weeks ago, and a bare "11:20" would read as today. */
export function sinceStamp(at: number, now: number, lang: Lang | string = 'en'): string {
  const a = new Date(at);
  const n = new Date(now);
  const sameDay = a.getFullYear() === n.getFullYear() && a.getMonth() === n.getMonth() && a.getDate() === n.getDate();
  if (sameDay) return clockTime(at);
  const date = a.toLocaleDateString(lang === 'ro' ? 'ro-RO' : 'en-GB', {
    day: 'numeric', month: 'short', ...(a.getFullYear() === n.getFullYear() ? {} : { year: 'numeric' }),
  });
  return `${date} ${clockTime(at)}`;
}

/** The six signals for one language, in running-head order. */
export function trustSignals(input: TrustSignalsInput, langIn: Lang | string = 'en'): SignalView[] {
  const lang: Lang = langIn === 'ro' ? 'ro' : 'en';
  const s = pick(TRUST_SIGNAL_STRINGS, lang);
  const { hub, audit } = input;
  const now = input.now ?? Date.now();
  const demo = !!input.demo || hub.demo;

  if (demo) {
    const demoView = (id: SignalId, label: { long: string; short: string }): SignalView => view({
      id, state: 'demo', mark: 'idle', label, value: { long: s.demoSample, short: s.demoShort, marks: s.demoShort },
      basis: 'seeded', meaning: [s.demoSample], checkedAt: null,
    }, s, lang);
    return [
      demoView('egress', same(s.egressLabel)),
      demoView('localRoute', { long: s.routeLabelLong, short: s.routeLabelShort }),
      demoView('microphone', same(s.micLabel)),
      demoView('model', same(s.modelLabel)),
      demoView('data', { long: s.dataLabelLong, short: s.dataLabelShort }),
      demoView('chain', { long: s.chainLabelLong, short: s.chainLabelShort }),
    ];
  }

  const checking = checkingOf(hub);
  const answered = hub.state === 'live';

  // ---- egress ------------------------------------------------------------------------------
  const egress = ((): SignalView => {
    const base = { id: 'egress' as const, label: same(s.egressLabel), checkedAt: hub.checkedAt };
    if (!hub.trust) {
      return checking
        ? view({ ...base, state: 'unknown', mark: 'unknown', value: same(s.checking), meaning: [] }, s, lang)
        : view({ ...base, state: 'unknown', mark: 'unknown', value: { long: s.egressUnknown, short: s.egressUnknownShort, marks: s.egressUnknownShort }, meaning: [] }, s, lang);
    }
    const cloud = hub.trust.cloudAvailable || hub.trust.claudeAvailable;
    const ledger = input.egress && input.egress.state === 'live' && input.egress.value ? input.egress.value : null;
    let ledgerText: string | null = null;
    const ledgerLines: string[] = [];
    if (ledger) {
      const count = ledger.since !== null
        ? plural(lang, s.ledgerSince, ledger.external, { time: sinceStamp(ledger.since, now, lang) })
        : plural(lang, s.ledgerNoSince, ledger.external);
      ledgerText = ledger.models !== null ? `${count}, ${fmt(s.ledgerModels, { n: ledger.models })}` : count;
      ledgerLines.push(ledgerText, s.ledgerBasis);
    }
    if (cloud) {
      const which = hub.trust.claudeAvailable && hub.trust.cloudAvailable ? s.whichBoth : hub.trust.claudeAvailable ? s.whichAnthropic : s.whichGemini;
      const meaning = [s.egressMeaningCloud, ...(hub.trust.strictLocal ? [s.egressStrictAlso] : []), ...ledgerLines];
      return view({
        ...base, state: 'live', mark: 'attn', basis: 'declared',
        value: { long: `${fmt(s.egressCloud, { which })}${ledgerText ? ` · ${ledgerText}` : ''}`, short: s.egressCloudShort, marks: s.egressCloudMarks },
        meaning,
      }, s, lang);
    }
    return view({
      ...base, state: 'live', mark: 'ok', basis: 'declared',
      value: { long: `${s.egressNoCloud}${ledgerText ? ` · ${ledgerText}` : ''}`, short: s.egressNoCloudShort, marks: s.egressNoCloudMarks },
      meaning: [s.egressMeaningNoCloud, ...ledgerLines],
    }, s, lang);
  })();

  // ---- local route -----------------------------------------------------------------------------
  const localRoute = ((): SignalView => {
    const base = { id: 'localRoute' as const, label: { long: s.routeLabelLong, short: s.routeLabelShort }, checkedAt: hub.checkedAt };
    const loc = hub.locality;
    if (!loc) {
      return checking
        ? view({ ...base, state: 'unknown', mark: 'unknown', basis: 'unknown', value: same(s.checking), meaning: [] }, s, lang)
        : view({ ...base, state: 'unknown', mark: 'unknown', basis: 'unknown', value: { long: s.routeUnknown, short: s.routeUnknownShort, marks: s.routeUnknownShort }, meaning: [] }, s, lang);
    }
    if (loc.local + loc.cloud === 0) {
      return view({
        ...base, state: 'live', mark: 'unknown', basis: 'derived',
        value: loc.unknown > 0
          ? { long: s.routeNoRoute, short: s.routeNoRouteShort, marks: s.routeNoRouteMarks }
          : { long: s.routeNone, short: s.routeNoneShort, marks: s.routeNoneMarks },
        meaning: loc.unknown > 0 ? [plural(lang, s.routeUnrouted, loc.unknown)] : [s.routeNoneMeaning],
      }, s, lang);
    }
    const vals = { local: loc.local, total: loc.total };
    return view({
      ...base, state: 'live', mark: loc.cloud > 0 ? 'attn' : 'ok', basis: 'declared',
      value: { long: fmt(s.routeRuns, vals), short: fmt(s.routeRunsShort, vals), marks: fmt(s.routeRunsMarks, vals) },
      meaning: [
        s.routeMeaning,
        ...(loc.cloud > 0 ? [plural(lang, s.routeCloud, loc.cloud)] : []),
        ...(loc.unknown > 0 ? [plural(lang, s.routeUnrouted, loc.unknown)] : []),
        s.routeLan,
      ],
    }, s, lang);
  })();

  // ---- microphone ---------------------------------------------------------------------------------
  const microphone = ((): SignalView => {
    const base = { id: 'microphone' as const, label: same(s.micLabel), checkedAt: hub.checkedAt };
    const listening = input.voiceStatus === 'listening' ? [s.micListening] : [];
    if (!hub.trust) {
      return checking
        ? view({ ...base, state: 'unknown', mark: 'unknown', value: same(s.checking), meaning: [] }, s, lang)
        : view({ ...base, state: 'unknown', mark: 'unknown', value: same(s.micUnknown), meaning: [s.micMeaning] }, s, lang);
    }
    const mic = hub.trust.mic;
    if (mic === 'unknown') return view({ ...base, state: 'unknown', mark: 'unknown', value: same(s.micUnknown), meaning: [s.micMeaning] }, s, lang);
    return view({
      ...base, state: 'live', mark: 'ok', value: same(mic === 'on' ? s.micOn : s.micMuted), meaning: [s.micMeaning, ...(mic === 'on' ? listening : [])],
    }, s, lang);
  })();

  // ---- model ------------------------------------------------------------------------------------------
  const model = ((): SignalView => {
    const base = { id: 'model' as const, label: same(s.modelLabel), checkedAt: hub.checkedAt, href: MODEL_SETUP_PATH };
    if (!answered) {
      return checking
        ? view({ ...base, state: 'unknown', mark: 'unknown', value: same(s.checking), meaning: [] }, s, lang)
        : view({ ...base, state: hub.state, mark: 'unknown', value: same(s.modelUnknown), meaning: [s.modelMeaningUnknown] }, s, lang);
    }
    const backend = hub.backend && hub.backend !== 'none' ? hub.backend : null;
    const configured = hub.configuredModel ? [fmt(s.modelConfigured, { model: hub.configuredModel })] : [];
    const residency = hub.residency && hub.residency !== 'known' ? [s.modelResidency] : [];
    switch (hub.llm.state) {
      case 'ready': {
        const id = hub.llm.model;
        const via = backend ? fmt(s.modelVia, { backend }) : '';
        return view({
          ...base, state: 'live', mark: 'ok', ident: id,
          value: { long: id ? via : [s.modelLoadedNoId, via].filter(Boolean).join(' '), short: id ? via : s.modelLoadedNoId, marks: id ? '' : s.modelLoadedNoId },
          meaning: [s.modelMeaningReady, ...configured, ...residency],
        }, s, lang);
      }
      case 'no_model':
        return view({ ...base, state: 'live', mark: 'problem', value: same(s.modelNoModel), meaning: [s.modelMeaningNoModel, ...configured] }, s, lang);
      case 'offline':
        return view({ ...base, state: 'live', mark: 'problem', value: same(s.modelNoBackend), meaning: [s.modelMeaningNoBackend, ...configured] }, s, lang);
      default:
        return view({ ...base, state: 'unknown', mark: 'unknown', value: same(s.modelUnknown), meaning: [s.modelMeaningUnknown, ...configured] }, s, lang);
    }
  })();

  // ---- data on screen -----------------------------------------------------------------------------------
  const data = ((): SignalView => {
    const r = hubReading(hub, now);
    const base = { id: 'data' as const, label: { long: s.dataLabelLong, short: s.dataLabelShort }, checkedAt: hub.checkedAt, meaning: [s.dataMeaning] };
    const t = (at: number | null) => (at !== null ? clockTime(at) : null);
    switch (r.state) {
      case 'live': {
        const time = t(r.lastGoodAt);
        return view({ ...base, state: 'live', mark: 'ok', value: { long: time ? fmt(s.dataLive, { time }) : s.dataLiveShort, short: s.dataLiveShort, marks: s.dataLiveShort } }, s, lang);
      }
      case 'stale': {
        const time = t(r.lastGoodAt);
        return view({ ...base, state: 'stale', mark: 'stale', value: { long: time ? fmt(s.dataStale, { time }) : s.dataStaleShort, short: s.dataStaleShort, marks: s.dataStaleShort } }, s, lang);
      }
      case 'offline': {
        const time = t(r.lastGoodAt);
        return view({ ...base, state: 'offline', mark: 'unknown', value: { long: time ? fmt(s.dataOffline, { time }) : s.dataOfflineNoTime, short: s.dataOfflineShort, marks: s.dataOfflineShort } }, s, lang);
      }
      case 'demo':
        return view({ ...base, state: 'demo', mark: 'idle', basis: 'seeded', value: same(s.demoSample) }, s, lang);
      default:
        return checking
          ? view({ ...base, state: 'unknown', mark: 'unknown', value: same(s.checking) }, s, lang)
          : view({ ...base, state: 'unknown', mark: 'unknown', value: same(s.dataUnknown) }, s, lang);
    }
  })();

  // ---- audit chain -----------------------------------------------------------------------------------------
  const chain = ((): SignalView => {
    const base = { id: 'chain' as const, label: { long: s.chainLabelLong, short: s.chainLabelShort }, checkedAt: audit.lastGoodAt };
    const v = audit.value;
    if (v && (audit.state === 'live' || audit.state === 'stale' || audit.state === 'offline' || audit.state === 'empty')) {
      if (!v.valid) {
        const text = v.firstInvalidId !== null ? fmt(s.chainBroken, { n: v.firstInvalidId }) : s.chainBrokenNoId;
        return view({ ...base, state: audit.state, mark: 'problem', value: { long: text, short: text, marks: text }, meaning: [s.chainMeaningBroken] }, s, lang);
      }
      const time = audit.lastGoodAt !== null ? clockTime(audit.lastGoodAt) : null;
      const long = time
        ? (v.entries !== null ? fmt(s.chainIntact, { n: v.entries, time }) : fmt(s.chainIntactNoCount, { time }))
        : s.chainIntactShort;
      const meaning = v.tamperEvident === false ? [s.chainMeaningUnkeyed] : v.tamperEvident === true ? [s.chainMeaningKeyed] : [];
      return view({
        ...base, state: audit.state, mark: audit.state === 'live' ? 'chain' : 'stale',
        value: { long, short: s.chainIntactShort, marks: s.chainIntactShort }, meaning,
      }, s, lang);
    }
    // the short forms say "Unknown"; the reason is in the long form and in the popover's first line
    if (audit.state === 'refused') return view({ ...base, state: 'refused', mark: 'unknown', value: { long: s.chainRefused, short: s.chainUnknownShort, marks: s.chainUnknownShort }, meaning: [s.chainRefused] }, s, lang);
    if (audit.state === 'unknown' && audit.reason === 'checking') return view({ ...base, state: 'unknown', mark: 'unknown', value: same(s.checking), meaning: [] }, s, lang);
    return view({ ...base, state: audit.state === 'offline' ? 'offline' : 'unknown', mark: 'unknown', value: { long: s.chainUnknown, short: s.chainUnknownShort, marks: s.chainUnknownShort }, meaning: [s.chainUnknown] }, s, lang);
  })();

  // Readings taken from a snapshot that has gone stale are stale, not live: only the audit chain
  // (its own request) and the data signal (which reads the clock itself) are left as they are.
  const gone = hubReading(hub, now).state === 'stale';
  const aged = (v: SignalView): SignalView => (gone && v.state === 'live' ? { ...v, state: 'stale', mark: 'stale' } : v);
  return [aged(egress), aged(localRoute), aged(microphone), aged(model), data, chain];
}
