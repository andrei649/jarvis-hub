// @ts-nocheck
/* H5.16 — the browser-side sentence segmenter that lets TTS start while the chat
   is still streaming. These cases mirror the Python `sentence_stream.py` contract
   (tests/test_sentence_stream.py) so the two implementations can't diverge, plus
   the property that matters most for a live stream: feeding text in ARBITRARY
   chunk boundaries must reproduce the whole text exactly — never duplicated,
   never dropped. */
import { describe, it, expect } from 'vitest';
import { splitSentences, SentenceAggregator } from '../sentences';

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
