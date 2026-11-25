/* The frame's attention notes (PHASE_B_PLAN.md §3.9): the masthead's and the contents column's.

   The signals engineer's useAttention() (signals/hooks.ts) derives them: "N need you" from the
   docket, "N wait" for payments, "■ N services down" from the observer (the ticker's warnings
   when the observer cannot be read), "■ record broken" from the audit chain, and the stop's word
   (Armed · Halted · Unknown). A note exists only for a live positive value or the stop's word;
   unknown is no note at all, never a 0. Demo reads nothing. This wrapper is the frame's one call
   site, so the Frame and the page body ask the same shared readings. */
import { useAttention } from '../signals/hooks';
import type { Attention, HubSnapshot } from '../signals/types';

export function useFrameAttention(opts: { demo?: boolean; hub?: HubSnapshot | null } = {}): Attention {
  return useAttention(opts);
}
