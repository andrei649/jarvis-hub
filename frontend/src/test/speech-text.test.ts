/* H526 — the HUD reads a reply as speech, exactly as the hub does.
 *
 * `speech-text-cases.json` is shared with tests/test_h526_speech_text.py: the browser's
 * own voice and the hub's /tts must never read the same reply differently.
 */
import { describe, it, expect } from 'vitest';
import cases from './speech-text-cases.json';
import { speechText, speechLang, SpeechStreamFilter, WORDS } from '../speech-text';
import { SentenceAggregator } from '../sentences';

describe('speechText — the shared cases', () => {
  for (const c of cases as { name: string; lang: string; text: string; spoken: string }[]) {
    it(c.name, () => {
      expect(speechText(c.text, c.lang)).toBe(c.spoken);
      expect(speechText(speechText(c.text, c.lang), c.lang)).toBe(c.spoken);   // a fixed point
    });
  }

  it('reads the symbol words of the reply language', () => {
    expect(speechText('a & b', 'ro-RO')).toBe('a și b');
    expect(speechText('a & b', 'fr')).toBe('a and b');
    expect(speechText('a & b')).toBe('a and b');
    expect(WORDS.ro.percent).toBe('la sută');
  });

  it('nothing in is nothing out', () => {
    for (const v of [null, undefined, '', '   ', '```\n```']) expect(speechText(v)).toBe('');
  });

  it('speechLang follows the request, then the voice, then the default', () => {
    expect(speechLang('ro', 'en-GB-RyanNeural')).toBe('ro');
    expect(speechLang(null, 'ro-RO-EmilNeural')).toBe('ro');
    expect(speechLang('', 'en-US-GuyNeural')).toBe('en');
    expect(speechLang(null, 'xtts', 'ro')).toBe('ro');
    expect(speechLang(undefined, undefined)).toBe('en');
    expect(speechLang(undefined, undefined, '')).toBe('en');
  });

  it('keeps ordinary letters and signs', () => {
    expect(speechText('Preț: 5 € — „bine” … ™ © ° ș ț ă î â ñ ü 中文 😀', 'ro'))
      .toBe('Preț: 5 € — „bine”… ™ © grade ș ț ă î â ñ ü 中文');
    expect(speechText('și_cu _italic_ ș_x', 'ro')).toBe('și_cu italic ș_x');
  });
});

/** Feed deltas through the filter and the aggregator, as the HUD's live voice does. */
function spokenFrom(deltas: string[]): string[] {
  const filter = new SpeechStreamFilter();
  const agg = new SentenceAggregator();
  const out: string[] = [];
  for (const d of deltas) out.push(...agg.push(filter.push(d)));
  out.push(...agg.push(filter.flush()), ...agg.flush());
  return out.map((s) => speechText(s, 'en')).filter(Boolean);
}

describe('SpeechStreamFilter — code and reasoning split across deltas', () => {
  const footer = '⚠️ File-mutation verifier: 1 file edit(s) FAILED this turn despite any wording above that may suggest otherwise. Run `git status` or `read_file` to confirm what actually landed.\n  • `/tmp/a.md` — [patch] Could not find old_string';

  it('withholds a split verifier footer before it reaches sentence synthesis', () => {
    const source = `Ready.\r\n\r\n${footer.replace(/\n/g, '\r\n')}\r\nNext.`;
    const cuts = [8, 10, 14, 15, 19, 38, 90, 158, 184, 185, 190, source.length - 5];
    let at = 0;
    const deltas = cuts.map((end) => { const chunk = source.slice(at, end); at = end; return chunk; });
    deltas.push(source.slice(at));
    expect(spokenFrom(deltas)).toEqual(['Ready.', 'Next.']);
    expect(source).toContain('Could not find old_string');
  });

  it('keeps an incomplete footer header and ordinary warning text audible', () => {
    const header = footer.split('\n')[0];
    expect(spokenFrom(['Start.\n\n⚠', '️ File-mutation verifier:', header.slice('⚠️ File-mutation verifier:'.length)]).join(' '))
      .toBe(`Start. ${speechText(header)}`);
    expect(spokenFrom(['Warning: this file-', 'mutation verifier is useful.']))
      .toEqual(['Warning: this file-mutation verifier is useful.']);
  });

  it('bounds an invalid footer candidate instead of holding the reply', () => {
    const filter = new SpeechStreamFilter();
    const out = filter.push('⚠️ File-mutation verifier: ' + '9'.repeat(100_000));
    expect(out.length).toBeGreaterThan(99_000);
    expect((filter as any).pending.length).toBeLessThan(256);
    expect(filter.flush()).toBe('');
  });

  it('resets footer suppression after flush so the next stream is audible', () => {
    const filter = new SpeechStreamFilter();
    expect(filter.push(footer)).toBe('');
    expect(filter.flush()).toBe('');
    expect(filter.push('Hello again.')).toBe('Hello again.');
    expect(filter.flush()).toBe('');
  });

  it('drops a fence whose markers arrive in pieces', () => {
    expect(spokenFrom(['Intro. ', '``', '`py\nprint(1)\nx = 2. y = 3.\n`', '``\nAfter it.']))
      .toEqual(['Intro.', 'After it.']);
  });

  it('drops a tilde fence', () => {
    expect(spokenFrom(['~', '~~\ncode. more.\n~~', '~\nDone.'])).toEqual(['Done.']);
  });

  it('drops a reasoning block whose tags arrive in pieces', () => {
    expect(spokenFrom(['<thi', 'nk>secret. plan.</th', 'ink>Visible.'])).toEqual(['Visible.']);
    expect(spokenFrom(['<THINKING>x.</thinking >', 'Ok.'])).toEqual(['Ok.']);
    expect(spokenFrom(['<Thinking>a. b. c.</THINKING>', 'Yes.'])).toEqual(['Yes.']);
    expect(spokenFrom(['<reasoning effort="high">', 'a. b.', '</reasoning>', 'Yes.'])).toEqual(['Yes.']);
  });

  it('holds a reasoning tag split inside its attributes', () => {
    // three sentences inside: a per-sentence clean-up alone would let the middle one out
    expect(spokenFrom(['Hi. <reasoning effort="hi', 'gh">one. two. three.</reasoning>', 'Ok.'])).toEqual(['Hi.', 'Ok.']);
  });

  it('starts clean after a flush', () => {
    const f = new SpeechStreamFilter();
    f.push('```js\nconst a = 1;');
    expect(f.flush()).toBe('');
    expect(f.push('Hello there.')).toBe('Hello there.');
  });

  it('never speaks an unclosed block at the end', () => {
    expect(spokenFrom(['Start. ```js\nconst a', ' = 1;'])).toEqual(['Start.']);
    expect(spokenFrom(['Sure. <think>still going'])).toEqual(['Sure.']);
  });

  it('lets ordinary text through, holding back only what could become a marker', () => {
    const f = new SpeechStreamFilter();
    expect(f.push('Use `x')).toBe('Use `x');
    expect(f.push('` now ``')).toBe('` now ');
    expect(f.push(' and')).toBe('`` and');
    expect(f.push(' a < b <t')).toBe(' a < b ');
    expect(f.push('able> ok')).toBe('<table> ok');
    expect(f.push(' ~')).toBe(' ');
    expect(f.flush()).toBe('~');
    expect(f.flush()).toBe('');
  });

  it('keeps a long code block from growing the held buffer', () => {
    const f = new SpeechStreamFilter();
    f.push('```\n');
    for (let i = 0; i < 200; i += 1) expect(f.push(`line ${i} of code\n`)).toBe('');
    expect((f as any).pending.length).toBeLessThanOrEqual(2);
    f.push('<think>');
    const g = new SpeechStreamFilter();
    g.push('<think>');
    for (let i = 0; i < 200; i += 1) g.push(`thought ${i}. `);
    expect((g as any).pending.length).toBeLessThanOrEqual(16);
    expect(g.push('</think>after')).toBe('\nafter');
  });

  it('a reply with no markers passes through whole, in any chunking', () => {
    const reply = 'One thing. Then **two** things! Finally, 50% done -> ship.';
    const chunks = [reply.slice(0, 7), reply.slice(7, 19), reply.slice(19, 40), reply.slice(40)];
    expect(spokenFrom(chunks)).toEqual(['One thing.', 'Then two things!', 'Finally, 50 percent done to ship.']);
  });
});
