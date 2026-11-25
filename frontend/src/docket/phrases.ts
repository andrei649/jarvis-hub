/* The phrase a typed signature asks for (PHASE_B_PLAN.md §5.4), a fixed map:

     restart_service                 restart
     money (tier 3 with an amount)   the amount in digits ("4200")
     any delete                      delete
     send, post or message kinds     send   (the words send, post, message — not a draft:
                                            draft_email or draft_message sends nothing)
     deploy                          deploy
     book                            book
     anything else                   sign

   Only tiers 2–3 (and an unknown tier, which counts as the strictest) sign by typing; tiers 0–1
   have no phrase. The words are the same in both languages on purpose, like the HUD's other
   typed confirmations (DISENGAGE, FORGET): a short plain word anyone can type on any keyboard,
   with the instruction around it in the owner's language. The table is still declared in both
   languages so the strings check covers it. */
import { defineStrings, pick, type Lang } from '../frame/strings';
import type { TierKey } from '../frame/kit/marks';
import { amountDigits, kindTokens } from './kinds';
import type { DocketTask, Friction } from './types';

export const PHRASE_STRINGS = defineStrings({
  en: { restart: 'restart', delete: 'delete', send: 'send', deploy: 'deploy', book: 'book', sign: 'sign' },
  ro: { restart: 'restart', delete: 'delete', send: 'send', deploy: 'deploy', book: 'book', sign: 'sign' },
});

export type PhraseWord = keyof typeof PHRASE_STRINGS.en;

/** The send, post and message kinds (§5.4), by the words of the kind: no wider. */
const SEND_WORDS = new Set(['send', 'post', 'message', 'messages']);

/** Which fixed word a request's kind takes (the money amount is not a word; see phraseFor). */
export function phraseWord(kind: unknown): PhraseWord {
  if (kind === 'restart_service') return 'restart';
  const words = kindTokens(kind);
  if (words.includes('delete')) return 'delete';
  if (!words.includes('draft') && words.some((word) => SEND_WORDS.has(word))) return 'send';
  if (words.includes('deploy')) return 'deploy';
  if (words.includes('book') || words.includes('booking')) return 'book';
  return 'sign';
}

/** The phrase a typed signature of this request needs, or null when its friction is not typed.
 *  `payload` overrides the request's own (an edited payload is signed with its own amount). */
export function phraseFor(task: DocketTask, tier: TierKey, friction: Friction, lang: Lang | string = 'en',
  payload: unknown = task.payload): string | null {
  if (friction !== 'typed') return null;
  if (task.kind === 'restart_service') return pick(PHRASE_STRINGS, lang).restart;
  if (tier === 'money') {
    const amount = payload && typeof payload === 'object' ? amountDigits((payload as { amount?: unknown }).amount) : null;
    if (amount) return amount;
  }
  return pick(PHRASE_STRINGS, lang)[phraseWord(task.kind)];
}
