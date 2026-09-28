/* H526 — what a reply sounds like: speech, not read-out markdown (browser side).
 *
 * The twin of `agents/core/voice/speech_text.py`. The hub normalises everything it
 * synthesizes, but the HUD also speaks on its own (the browser's speechSynthesis voice)
 * and splits the live token stream into sentences before any of it reaches the hub — so
 * the same rules run here. `test/speech-text-cases.json` pins both implementations to the
 * same outputs; a change to one must land in the other.
 *
 * `SpeechStreamFilter` is the streaming half: a fenced code block or a reasoning block
 * whose markers arrive split across token deltas is never handed to the sentence
 * aggregator, so no line of it is spoken; an unclosed one at the end is dropped.
 */

const THINK_TAGS = 'think|thinking|reasoning';
const THINK_CLOSED = new RegExp(`<(${THINK_TAGS})\\b[^>]*>[\\s\\S]*?</\\1\\s*>`, 'gi');
const THINK_OPEN = new RegExp(`<(?:${THINK_TAGS})\\b[^>]*>[\\s\\S]*$`, 'i');
const THINK_STRAY_CLOSE = new RegExp(`^[\\s\\S]*</(?:${THINK_TAGS})\\s*>`, 'i');
const FENCE = /(```|~~~)[\s\S]*?(?:\1|$)/g;
const AUTOLINK = /<https?:\/\/[^<>\s]+>/g;
const HTML_TAG = /<\/?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?\/?>/g;
const IMAGE = /!\[([^\]\n]*)\]\([^)\n]*\)/g;
const LINK = /\[([^\]\n]+)\]\([^)\n]*\)/g;
const URL_RE = /https?:\/\/[^\s<>()[\]]+/g;
const URL_TRAIL = /[.,;:!?'"]+$/;

const RULE = /^([-*_])(?:\s*\1){2,}$/;
const TABLE_SEPARATOR = /^\|?(?:\s*:?-{2,}:?\s*\|)+\s*(?::?-{2,}:?)?\s*\|?$/;
const HEADING = /^#{1,6}\s+(.*?)(?:\s+#+)?$/;
const QUOTE = /^(?:>\s?)+/;
const LIST_MARKER = /^(?:[-*+•]|\d{1,3}[.)])\s+/;
const TASK_BOX = /^\[[ xX]\]\s+/;

// Bold, strikethrough and inline-code markers simply go (their words stay); single-
// character emphasis needs the word-boundary guards so "2*3*4" and "my_var" survive.
const PAIRED_MARKERS = /\*\*|__|~~|`/g;
// Python's \w is Unicode-aware; spell it out so "ș_" behaves the same here.
const ITALIC = /(^|[^\p{L}\p{N}_*])\*(\S(?:.*?\S)?)\*(?![\p{L}\p{N}_*])/gu;
const ITALIC_UNDERSCORE = /(^|[^\p{L}\p{N}_])_(\S(?:.*?\S)?)_(?![\p{L}\p{N}_])/gu;

const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2300}-\u{23FF}\u{FE00}-\u{FE0F}\u{200D}\u{20E3}\u{E0020}-\u{E007F}]+/gu;
const SPACE_BEFORE_PUNCT = /\s+([,.;:!?…])/g;
const SPACES = /\s+/g;
const ENDS_A_SENTENCE = /[.!?…:;,]$/;
const SAYABLE = /[\p{L}\p{N}]/u;          // a letter or a digit, in any script

type Words = { and: string; percent: string; to: string; degrees: string };

/** The words for each symbol, per language (anything not Romanian reads English). */
export const WORDS: Record<'en' | 'ro', Words> = {
  en: { and: 'and', percent: 'percent', to: 'to', degrees: 'degrees' },
  ro: { and: 'și', percent: 'la sută', to: 'spre', degrees: 'grade' },
};

/** "ro" or "en": the request's language, else the voice's ("ro-RO-…"), else the default. */
export function speechLang(lang?: unknown, voice?: unknown, fallback = 'en'): 'ro' | 'en' {
  const voiceHint = typeof voice === 'string' && /^[a-z]{2}-[A-Z]{2}-/.test(voice) ? voice : null;
  for (const hint of [lang, voiceHint, fallback]) {
    if (typeof hint === 'string' && hint.trim()) return hint.trim().toLowerCase().startsWith('ro') ? 'ro' : 'en';
  }
  return 'en';
}

function symbols(line: string, w: Words): string {
  return line
    .replace(/\s*&\s*/g, ` ${w.and} `)
    .replace(/\s*%/g, ` ${w.percent}`)
    .replace(/\s*(?:->|→|=>)\s*/g, ` ${w.to} `)
    .replace(/\s*°\s*C\b/g, ` ${w.degrees} Celsius`)
    .replace(/\s*°\s*F\b/g, ` ${w.degrees} Fahrenheit`)
    .replace(/\s*°/g, ` ${w.degrees}`);
}

function inline(line: string): string {
  return line.replace(PAIRED_MARKERS, '').replace(ITALIC, '$1$2').replace(ITALIC_UNDERSCORE, '$1$2');
}

function oneLine(raw: string, w: Words): string {
  let line = raw.trim();
  if (!line || RULE.test(line)) return '';
  let block = false;
  const heading = HEADING.exec(line);
  if (line.startsWith('|')) {
    if (TABLE_SEPARATOR.test(line)) return '';
    line = line.replace(/^\|+|\|+$/g, '').split('|').map((c) => c.trim()).filter(Boolean).join(', ');
    block = true;
  } else if (heading) {
    line = heading[1];
    block = true;
  } else {
    const quoted = line.replace(QUOTE, '');
    const listed = quoted.replace(LIST_MARKER, '').replace(TASK_BOX, '');
    block = quoted !== line || listed !== quoted;
    line = listed;
  }
  line = inline(line);
  line = line.replace(URL_RE, (m) => `link${(URL_TRAIL.exec(m) || [''])[0]}`);
  line = symbols(line, w);
  line = line.replace(EMOJI, ' ');
  line = line.replace(SPACES, ' ').replace(SPACE_BEFORE_PUNCT, '$1').trim();
  if (block && line && !ENDS_A_SENTENCE.test(line)) line += '.';
  return line;
}

/** `text` as it should be heard, or "" when nothing in it is worth saying. */
export function speechText(text: unknown, lang?: unknown): string {
  let raw = String(text ?? '').replace(/\r\n?/g, '\n');
  raw = raw.replace(THINK_CLOSED, ' ').replace(THINK_OPEN, '').replace(THINK_STRAY_CLOSE, '');
  raw = raw.replace(FENCE, '\n').replace(AUTOLINK, 'link').replace(HTML_TAG, ' ');
  raw = raw.replace(IMAGE, '$1').replace(LINK, '$1');
  const w = WORDS[speechLang(lang)];
  const spoken = raw.split('\n').map((l) => oneLine(l, w)).filter(Boolean).join(' ');
  return SAYABLE.test(spoken) ? spoken : '';   // a lone "." is nothing to say
}

const OPENERS = /```|~~~|<(think|thinking|reasoning)\b[^>]*>/i;
const THINK_CLOSERS: Record<string, RegExp> = {
  think: /<\/think\s*>/i,
  thinking: /<\/thinking\s*>/i,
  reasoning: /<\/reasoning\s*>/i,
};
// A tail that may still become an opener once the next delta arrives.
const MAYBE_OPENER = /(`{1,2}|~{1,2}|<[A-Za-z]{0,9}|<(?:think|thinking|reasoning)\b[^>]*)$/i;

/**
 * Drops fenced code and reasoning from a live token stream, however its markers are
 * split across deltas. `push()` returns the text that is safe to speak so far; a tail
 * that might still turn into a marker is held back until the next delta decides.
 */
export class SpeechStreamFilter {
  private pending = '';
  private closer: RegExp | string | null = null;   // what ends the block we are inside

  push(delta: string): string {
    this.pending += String(delta || '');
    let out = '';
    for (;;) {
      if (this.closer !== null) {
        if (typeof this.closer === 'string') {
          const at = this.pending.indexOf(this.closer);
          if (at < 0) { this.pending = this.pending.slice(-(this.closer.length - 1)); return out; }
          this.pending = this.pending.slice(at + this.closer.length);
        } else {
          const m = this.closer.exec(this.pending);
          if (!m) { this.pending = this.pending.slice(-16); return out; }
          this.pending = this.pending.slice(m.index + m[0].length);
        }
        this.closer = null;
        out += '\n';
        continue;
      }
      const m = OPENERS.exec(this.pending);
      if (m) {
        out += this.pending.slice(0, m.index);
        this.closer = m[1] ? THINK_CLOSERS[m[1].toLowerCase()] : m[0];
        this.pending = this.pending.slice(m.index + m[0].length);
        continue;
      }
      const hold = MAYBE_OPENER.exec(this.pending);
      const cut = hold ? hold.index : this.pending.length;
      out += this.pending.slice(0, cut);
      this.pending = this.pending.slice(cut);
      return out;
    }
  }

  /** The end of the stream: a held tail is text; an unclosed block is never spoken. */
  flush(): string {
    const rest = this.closer === null ? this.pending : '';
    this.pending = '';
    this.closer = null;
    return rest;
  }
}
