/* H5.16 — sentence segmentation for LIVE token streams (browser side).
 *
 * `agents/core/voice/sentence_stream.py` does this server-side for an
 * already-complete reply (`/tts/stream` chunks a finished string). What was
 * still missing is the half that actually earns the item's name: starting
 * synthesis while the chat is *still generating*. That has to happen in the
 * browser, because the token deltas arrive there over SSE.
 *
 * This is a deliberate, contract-matching port of the Python splitter's rules,
 * not a re-invention — same terminators, same hard-terminator handling, same
 * abbreviation guard, same decimal guard, same merge-forward-if-too-short
 * behaviour, same push()/flush() aggregator contract. `sentences.test.ts` pins
 * the shared cases so the two implementations can't silently diverge.
 */

// Sentence-final punctuation (Latin + common CJK/Arabic marks). A run collapses
// into one boundary so "Really?!" / "Wait..." stay together.
const TERMINATORS = '.!?…。！？؟';

// Fullwidth/CJK terminators end a sentence with no following whitespace (CJK
// text isn't space-separated). ASCII terminators need whitespace/end after them
// so "U.S." style tokens don't split.
const HARD_TERMINATORS = '…。！？';

// Abbreviations whose trailing period is not a boundary (bilingual RO/EN subset,
// mirroring the Python set exactly).
const ABBREVIATIONS = new Set([
  'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'vs', 'etc', 'e.g', 'i.e',
  'inc', 'ltd', 'co', 'no', 'vol', 'fig', 'approx', 'dept', 'univ', 'gov',
  'dl', 'dna', 'dra', 'nr', 'str', 'bd', 'art', 'alin', 'ex', 'ed', 'pag',
]);

export const DEFAULT_MIN_CHARS = 1;

const ABBREV_RE = /([A-Za-zÀ-ɏ.]+)\.\s*$/;

function endsWithAbbreviation(text: string): boolean {
  const m = ABBREV_RE.exec(text);
  if (!m) return false;
  return ABBREVIATIONS.has(m[1].replace(/\.+$/, '').toLowerCase());
}

/** "3.14" — a period between digits is a decimal point, never a boundary. */
function isDecimalSplit(current: string, rest: string): boolean {
  return /\d$/.test(current.replace(/\.$/, '')) && /^\d/.test(rest);
}

/** Segment a finished string into sentences (mirrors Python `split_sentences`). */
export function splitSentences(text: string, minChars: number = DEFAULT_MIN_CHARS): string[] {
  const src = text || '';
  const out: string[] = [];
  let buf: string[] = [];
  let i = 0;
  const n = src.length;

  while (i < n) {
    const ch = src[i];
    buf.push(ch);
    if (TERMINATORS.includes(ch)) {
      // Collapse a run of terminators into one boundary.
      let j = i + 1;
      let run = ch;
      while (j < n && TERMINATORS.includes(src[j])) { run += src[j]; buf.push(src[j]); j += 1; }
      const current = buf.join('');
      const rest = src.slice(j);
      let hard = false;
      for (const c of run) if (HARD_TERMINATORS.includes(c)) { hard = true; break; }
      const boundary = j >= n || /\s/.test(src[j]) || hard;
      if (boundary && !isDecimalSplit(current, rest) && !endsWithAbbreviation(current)) {
        const candidate = current.trim();
        if (candidate && candidate.length >= minChars) { out.push(candidate); buf = []; }
        // else: too short → keep accumulating (merge forward)
      }
      i = j;
      continue;
    }
    i += 1;
  }

  const tail = buf.join('').trim();
  if (tail) {
    if (out.length && tail.length < minChars) out[out.length - 1] = `${out[out.length - 1]} ${tail}`;
    else out.push(tail);
  }
  return out;
}

/**
 * Incremental sentence segmenter for a token/delta stream — the browser twin of
 * Python's `SentenceAggregator`. Feed it deltas as they arrive; it returns any
 * sentences that just *closed*. `flush()` once at the end for the remainder.
 */
export class SentenceAggregator {
  private buffer = '';
  private emitted = 0;
  constructor(private readonly minChars: number = DEFAULT_MIN_CHARS) {}

  /** Add a delta; return sentences that became complete (possibly empty). */
  push(delta: string): string[] {
    if (!delta) return [];
    this.buffer += delta;
    const parts = splitSentences(this.buffer, this.minChars);
    if (!parts.length) return [];

    // The final part is only safe to speak when BOTH hold:
    //   1. it actually ends in a terminator — otherwise it's a fragment still
    //      being typed ("A. B. C" must not speak a bare "C"); and
    //   2. the buffer does NOT end in a terminator — otherwise the run may still
    //      grow ("Really?" + "!" must speak "Really?!" once, not "Really?" then "!").
    // Both directions are pinned by the arbitrary-chunk round-trip property test
    // in sentences.test.ts, which fails loudly if either guard is dropped.
    const last = parts[parts.length - 1];
    const lastIsTerminated = TERMINATORS.includes(last[last.length - 1]);
    const bufferMayGrow = TERMINATORS.includes(this.buffer[this.buffer.length - 1]);
    const emit = (lastIsTerminated && !bufferMayGrow) ? parts : parts.slice(0, -1);
    if (!emit.length) return [];

    // Advance the buffer past exactly what we emitted. Locating each part in
    // order (rather than doing arithmetic on a joined string) keeps the offset
    // correct regardless of the original whitespace between sentences.
    let idx = 0;
    for (const p of emit) {
      const found = this.buffer.indexOf(p, idx);
      if (found < 0) break;          // defensive: never re-emit on a drift
      idx = found + p.length;
    }
    this.buffer = this.buffer.slice(idx);
    this.emitted += emit.length;
    return emit;
  }

  /** Emit any remaining buffered text as a final chunk. Idempotent. */
  flush(): string[] {
    const rest = this.buffer.trim();
    this.buffer = '';
    if (!rest) return [];
    const parts = splitSentences(rest, this.minChars);
    this.emitted += parts.length;
    return parts;
  }

  get emittedCount(): number { return this.emitted; }
}

/**
 * The part of `reply` that was NOT covered by `spoken` (sentences that already
 * played, in order). Used by the streaming-TTS fallback: when synthesis fails
 * mid-stream after some sentences played, only the remainder may be re-spoken —
 * replaying the whole reply would read the opening twice.
 *
 * Sentences are trimmed in-order slices of the reply, so each is located with
 * a forward scan. If one cannot be found (a drift that should not happen), the
 * conservative answer is '' — the reply is on screen, and double audio is the
 * one failure mode this function exists to prevent.
 */
export function unspokenRemainder(reply: string, spoken: string[]): string {
  const text = reply || '';
  if (!spoken.length) return text.trim();
  let cursor = 0;
  for (const sentence of spoken) {
    const probe = sentence.trim();
    if (!probe) continue;
    const found = text.indexOf(probe, cursor);
    if (found < 0) return '';
    cursor = found + probe.length;
  }
  return text.slice(cursor).trim();
}
