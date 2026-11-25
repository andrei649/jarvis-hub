/* The kit's words: reading states and reasons (SourceLabel), bases, the key's title.
   Marks and risk tiers have their words in ./marks.ts. */
import { defineStrings, fmt, pick, type Lang } from '../strings';
import type { Basis, ReadingReason, ReadingState } from '../../signals/types';

export const KIT_STRINGS = defineStrings({
  en: {
    live: 'Live',
    stale: 'Stale',
    unknown: 'Unknown',
    refused: 'Refused',
    offline: 'Offline',
    demo: 'Demo sample',
    empty: 'Empty',
    disabled: 'Off',
    checking: 'Checking…',
    checkedAt: 'checked {time}',
    verifiedAt: 'verified {time}',
    lastGoodAt: 'last good reading {time}',
    reasonUnavailable: 'switched off on the hub',
    reasonHttp: 'the hub answered {status}',
    reasonError: 'the hub answered with an error',
    reasonMalformed: 'the answer could not be read',
    reasonNotMeasured: 'not measured',
    reasonNotReported: 'not reported',
    reasonCredential: 'needs the owner credential',
    reasonNetwork: 'no answer',
    basisMeasured: 'measured',
    basisDeclared: 'declared, not measured',
    basisDerived: 'derived',
    basisSeeded: 'demo sample',
    basisUnknown: 'basis unknown',
    key: 'Key',
  },
  ro: {
    live: 'În direct',
    stale: 'Învechit',
    unknown: 'Necunoscut',
    refused: 'Refuzat',
    offline: 'Deconectat',
    demo: 'Mostră demo',
    empty: 'Gol',
    disabled: 'Oprit',
    checking: 'Se verifică…',
    checkedAt: 'actualizat la {time}',
    verifiedAt: 'verificat la {time}',
    lastGoodAt: 'ultima citire bună la {time}',
    reasonUnavailable: 'oprit pe hub',
    reasonHttp: 'hubul a răspuns {status}',
    reasonError: 'hubul a răspuns cu o eroare',
    reasonMalformed: 'răspunsul nu a putut fi citit',
    reasonNotMeasured: 'nemăsurat',
    reasonNotReported: 'neraportat',
    reasonCredential: 'necesită credențialul proprietarului',
    reasonNetwork: 'niciun răspuns',
    basisMeasured: 'măsurat',
    basisDeclared: 'declarat, nu măsurat',
    basisDerived: 'dedus',
    basisSeeded: 'mostră demo',
    basisUnknown: 'bază necunoscută',
    key: 'Legendă',
  },
});

const pad = (n: number) => String(n).padStart(2, '0');

/** HH:MM in local time, 24-hour, the same in both languages ("checked 10:50"). */
export function clockTime(at: number | Date): string {
  const d = at instanceof Date ? at : new Date(at);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** The word for a reading state. */
export function stateWord(state: ReadingState, lang: Lang | string = 'en'): string {
  return pick(KIT_STRINGS, lang)[state];
}

/** The words for why a reading is not live (null when there is no reason to give). */
export function reasonWords(reason: ReadingReason | undefined, lang: Lang | string = 'en', status?: number | null): string | null {
  const s = pick(KIT_STRINGS, lang);
  switch (reason) {
    case 'checking': return s.checking;
    case 'unavailable': return s.reasonUnavailable;
    case 'http': return typeof status === 'number' ? fmt(s.reasonHttp, { status }) : s.reasonError;
    case 'malformed': return s.reasonMalformed;
    case 'not-measured': return s.reasonNotMeasured;
    case 'not-reported': return s.reasonNotReported;
    case 'credential': return s.reasonCredential;
    case 'network': return s.reasonNetwork;
    default: return null;
  }
}

/** The words for a locality basis (gap-5 §7). */
export function basisWords(basis: Basis, lang: Lang | string = 'en'): string {
  const s = pick(KIT_STRINGS, lang);
  switch (basis) {
    case 'measured': return s.basisMeasured;
    case 'declared': return s.basisDeclared;
    case 'derived': return s.basisDerived;
    case 'seeded': return s.basisSeeded;
    default: return s.basisUnknown;
  }
}
