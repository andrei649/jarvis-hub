// @ts-nocheck
/* H5.16 — the browser-side sentence segmenter that lets TTS start while the chat
   is still streaming. These cases mirror the Python `sentence_stream.py` contract
   (tests/test_sentence_stream.py) so the two implementations can't diverge, plus
   the property that matters most for a live stream: feeding text in ARBITRARY
   chunk boundaries must reproduce the whole text exactly — never duplicated,
   never dropped. */
import { describe, it, expect } from 'vitest';
import { splitSentences, SentenceAggregator, unspokenRemainder } from '../sentences';

describe('splitSentences — matches the Python splitter contract', () => {
  it('splits on sentence-final punctuation', () => {
    expect(splitSentences('Hello there. How are you? Fine!')).toEqual(
      ['Hello there.', 'How are you?', 'Fine!'],
    );
  });

  it('keeps a run of terminators together', () => {
    expect(splitSentences('Really?! Yes... ok.')).toEqual(['Really?!', 'Yes...', 'ok.']);
  });

  it('does not split decimals', () => {
    expect(splitSentences('Pi is 3.14 exactly.')).toEqual(['Pi is 3.14 exactly.']);
  });

  it('does not split known abbreviations', () => {
    expect(splitSentences('Dr. Smith arrived.')).toEqual(['Dr. Smith arrived.']);
    expect(splitSentences('Vezi art. 5 din lege.')).toEqual(['Vezi art. 5 din lege.']);
  });

  it('splits CJK hard terminators without following whitespace', () => {
    expect(splitSentences('你好。再见。')).toEqual(['你好。', '再见。']);
  });

  it('returns an empty list for empty input', () => {
    expect(splitSentences('')).toEqual([]);
    expect(splitSentences('   ')).toEqual([]);
  });

  it('keeps an unterminated tail', () => {
    expect(splitSentences('Done. Still typing')).toEqual(['Done.', 'Still typing']);
  });
});

describe('SentenceAggregator — live token-stream segmentation', () => {
  it('emits a sentence as soon as it closes, not before', () => {
    const agg = new SentenceAggregator();
    expect(agg.push('Hello ')).toEqual([]);
    expect(agg.push('there')).toEqual([]);
    expect(agg.push('. ')).toEqual(['Hello there.']);
    expect(agg.push('Next one')).toEqual([]);
    expect(agg.flush()).toEqual(['Next one']);
  });

  it('flush is idempotent and empty after draining', () => {
    const agg = new SentenceAggregator();
    agg.push('One.');
    expect(agg.flush()).toEqual(['One.']);
    expect(agg.flush()).toEqual([]);
  });

  it('emits nothing at all for an empty stream', () => {
    const agg = new SentenceAggregator();
    expect(agg.push('')).toEqual([]);
    expect(agg.flush()).toEqual([]);
  });

  it('counts what it emitted', () => {
    const agg = new SentenceAggregator();
    agg.push('A. B. ');
    agg.flush();
    expect(agg.emittedCount).toBeGreaterThanOrEqual(2);
  });

  // The property that actually protects the user: whatever chunk boundaries the
  // model happens to produce, the spoken text must equal the written text.
  const TEXTS = [
    'Hello there. How are you? Fine!',
    'Pi is 3.14 exactly. Dr. Smith agrees.',
    'One sentence only',
    'Really?! Yes... ok.',
    'A. B. C. D.',
  ];
  const CHUNKINGS = [1, 2, 3, 5, 7, 999];

  for (const text of TEXTS) {
    for (const size of CHUNKINGS) {
      it(`reproduces ${JSON.stringify(text.slice(0, 24))}… at chunk size ${size}`, () => {
        const agg = new SentenceAggregator();
        const spoken: string[] = [];
        for (let i = 0; i < text.length; i += size) {
          spoken.push(...agg.push(text.slice(i, i + size)));
        }
        spoken.push(...agg.flush());
        // Normalising whitespace: the aggregator trims chunk edges, so compare
        // on collapsed whitespace — content and ORDER must be identical.
        const rebuilt = spoken.join(' ').replace(/\s+/g, ' ').trim();
        const expected = text.replace(/\s+/g, ' ').trim();
        expect(rebuilt).toBe(expected);
      });
    }
  }
});

describe('unspokenRemainder — the partial-failure TTS fallback', () => {
  const reply = 'First sentence. Second sentence. Third sentence.';

  it('returns the whole reply when nothing played', () => {
    expect(unspokenRemainder(reply, [])).toBe(reply);
  });

  it('returns only what comes after the sentences that played', () => {
    expect(unspokenRemainder(reply, ['First sentence.']))
      .toBe('Second sentence. Third sentence.');
    expect(unspokenRemainder(reply, ['First sentence.', 'Second sentence.']))
      .toBe('Third sentence.');
  });

  it('returns empty when everything played', () => {
    expect(unspokenRemainder(reply,
      ['First sentence.', 'Second sentence.', 'Third sentence.'])).toBe('');
  });

  it('never re-speaks on drift: an unlocatable sentence yields empty', () => {
    // Double audio is the failure mode this function exists to prevent, so the
    // conservative answer to "I cannot line the transcript up" is silence.
    expect(unspokenRemainder(reply, ['Not in the reply at all.'])).toBe('');
  });

  it('round-trips with the aggregator over arbitrary chunking', () => {
    const agg = new SentenceAggregator();
    const spoken: string[] = [];
    for (const chunk of ['First sen', 'tence. Second sent', 'ence. Thi']) {
      spoken.push(...agg.push(chunk));
    }
    // Stream "failed" here — flush never speaks. The remainder must be exactly
    // the un-played tail, so fallback + played audio reads the reply once.
    expect(unspokenRemainder('First sentence. Second sentence. Third.', spoken))
      .toBe('Third.');
  });
});
