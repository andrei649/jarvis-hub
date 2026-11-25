/* Where a reply ran: the per-message marker (PHASE_B_PLAN.md §5.3; gap-5 §7.1).

   The hub can say where it SENT the prompt (the adapter and the model id on the wire, per
   reply), not where the model computed. So the footnote says "Sent to …", never "Ran on …", and
   never draws a solid "this machine" mark: that needs an explicit enforced-scope flag the receipt
   does not carry yet (the strict-local scope's `THIS MACHINE · enforced` row of gap-5 §7.1 is
   deliberately not produced here, and the model suffix is never parsed to fake it).

   The rows of §7.1 that exist in Phase B:

     cloud         the receipt's provider is a cloud adapter          measured (first hop)
     localRunner   Ollama or LM Studio, nothing more known            measured (first hop), not verified
     cloudName     a local runner whose model id says cloud (:cloud, -cloud): a warning, derived by name
     noModelCall   the turn's usage basis is `measured_zero`          measured
     notReported   no receipt                                         unknown

   A reply can carry up to eight pairs: the marker shows the least private one (cloud, then a
   cloud name, then a local runner) and counts the others ("+2 more", which opens the provenance
   modal). `verified` is always false. Pure; the words come from replyMarkerWords(). */
import { defineStrings, fmt, pick, type Lang } from '../frame/strings';
import type { Basis, ReplyMarker, ReplyMarkerKind } from './types';

export const PROVENANCE_STRINGS = defineStrings({
  en: {
    cloud: 'Sent to {provider} (cloud) · {model}',
    localRunner: 'Sent to {provider} on this computer · {model} · where it ran is not verified',
    cloudNameLine: 'Sent to {provider} on this computer · {model}',
    cloudNameWarning: '⚠ {model} names a cloud model',
    cloudNameWhy: 'The model id says cloud, so the local runner may have forwarded the prompt off this machine. The hub cannot see that.',
    noModelCall: 'No model call',
    notReported: 'Where it ran: not reported',
    more: '+{n} more',
  },
  ro: {
    cloud: 'Trimis către {provider} (cloud) · {model}',
    localRunner: 'Trimis către {provider} pe acest calculator · {model} · unde a rulat nu este verificat',
    cloudNameLine: 'Trimis către {provider} pe acest calculator · {model}',
    cloudNameWarning: '⚠ {model} este un model cloud după nume',
    cloudNameWhy: 'Identificatorul modelului spune cloud, deci executorul local poate să fi trimis promptul în afara acestui calculator. Hubul nu poate vedea asta.',
    noModelCall: 'Niciun apel de model',
    notReported: 'Unde a rulat: neraportat',
    more: '+{n} în plus',
  },
});

/** The adapters that talk to a runner on this computer or this network (turn_usage.py's local set). */
export const LOCAL_RUNNER_PROVIDERS: readonly string[] = ['ollama', 'lm-studio', 'lmstudio', 'lm_studio'];

const DISPLAY: Readonly<Record<string, string>> = {
  ollama: 'Ollama', 'lm-studio': 'LM Studio', lmstudio: 'LM Studio', lm_studio: 'LM Studio',
  anthropic: 'Anthropic', claude: 'Anthropic', gemini: 'Gemini', openai: 'OpenAI',
};

/** A provider id as a name ("lm-studio" → "LM Studio"); an id the table does not know is kept as sent. */
export function providerName(provider: string): string {
  return DISPLAY[provider.trim().toLowerCase()] ?? provider;
}

/** A model id that names a cloud model: `…:cloud` or `…-cloud` (not "cloudflare"). */
export function namesCloudModel(model: string): boolean {
  return /[:-]cloud(?![a-z0-9])/i.test(model);
}

export interface ReplyReceiptInput {
  /** The reply's measured {provider, model} pairs (m.prov.models, at most eight); absent without a receipt. */
  readonly models?: readonly { readonly provider: string; readonly model: string }[] | null;
  /** The turn's usage basis (`outcome.usage_detail`'s `usage_basis`): `measured_zero` means no model call. */
  readonly usageBasis?: string | null;
}

const RANK: Readonly<Record<'cloud' | 'cloudName' | 'localRunner', number>> = { cloud: 0, cloudName: 1, localRunner: 2 };
const BASIS: Readonly<Record<ReplyMarkerKind, Basis>> = {
  cloud: 'measured', localRunner: 'measured', cloudName: 'derived', noModelCall: 'measured', notReported: 'unknown',
};

function kindOfPair(provider: string, model: string): 'cloud' | 'cloudName' | 'localRunner' {
  if (!LOCAL_RUNNER_PROVIDERS.includes(provider.trim().toLowerCase())) return 'cloud';
  return namesCloudModel(model) ? 'cloudName' : 'localRunner';
}

/** The marker for a reply: the least private pair, or no model call, or not reported. */
export function replyMarker(input: ReplyReceiptInput | null | undefined): ReplyMarker {
  const pairs = (Array.isArray(input?.models) ? input.models : [])
    .filter((p) => !!p && typeof p.provider === 'string' && p.provider.trim() !== '' && typeof p.model === 'string' && p.model.trim() !== '')
    .slice(0, 8);
  if (!pairs.length) {
    const none = input?.usageBasis === 'measured_zero';
    const kind: ReplyMarkerKind = none ? 'noModelCall' : 'notReported';
    return { kind, basis: BASIS[kind], provider: null, model: null, more: 0, verified: false };
  }
  let best = 0;
  let bestKind = kindOfPair(pairs[0].provider, pairs[0].model);
  pairs.forEach((p, i) => {
    const k = kindOfPair(p.provider, p.model);
    if (RANK[k] < RANK[bestKind]) { best = i; bestKind = k; }
  });
  return {
    kind: bestKind, basis: BASIS[bestKind], provider: pairs[best].provider.trim(), model: pairs[best].model.trim(),
    more: pairs.length - 1, verified: false,
  };
}

export interface ReplyMarkerWords {
  /** The footnote line. */
  readonly text: string;
  /** "⚠ <model> names a cloud model"; null for every other kind. */
  readonly warning: string | null;
  /** Why the warning matters (the disclosure's line). */
  readonly warningWhy: string | null;
  /** "+2 more" when the reply carried other pairs; opens the provenance modal. */
  readonly more: string | null;
}

/** The marker in one language. */
export function replyMarkerWords(marker: ReplyMarker, langIn: Lang | string = 'en'): ReplyMarkerWords {
  const s = pick(PROVENANCE_STRINGS, langIn);
  const more = marker.more > 0 ? fmt(s.more, { n: marker.more }) : null;
  const values = { provider: marker.provider ? providerName(marker.provider) : '', model: marker.model ?? '' };
  switch (marker.kind) {
    case 'cloud': return { text: fmt(s.cloud, values), warning: null, warningWhy: null, more };
    case 'localRunner': return { text: fmt(s.localRunner, values), warning: null, warningWhy: null, more };
    case 'cloudName':
      return { text: fmt(s.cloudNameLine, values), warning: fmt(s.cloudNameWarning, values), warningWhy: s.cloudNameWhy, more };
    case 'noModelCall': return { text: s.noModelCall, warning: null, warningWhy: null, more: null };
    default: return { text: s.notReported, warning: null, warningWhy: null, more: null };
  }
}
