import { describe, expect, it } from '@jest/globals';
import { parseSseLine, SseDecoder } from '../sse';

describe('parseSseLine', () => {
  it('parses a data frame into an event', () => {
    expect(parseSseLine('data: {"type":"token","text":"hi"}')).toEqual({ type: 'token', text: 'hi' });
  });

  it('ignores non-data lines and blanks', () => {
    expect(parseSseLine('')).toBeNull();
    expect(parseSseLine(': keep-alive')).toBeNull();
    expect(parseSseLine('event: ping')).toBeNull();
  });

  it('ignores malformed json and objects without a type', () => {
    expect(parseSseLine('data: not json')).toBeNull();
    expect(parseSseLine('data: {"text":"no type"}')).toBeNull();
  });
});

describe('SseDecoder', () => {
  it('decodes whole frames', () => {
    const d = new SseDecoder();
    const events = d.push('data: {"type":"start","agent":"jarvis"}\n\ndata: {"type":"token","text":"a"}\n\n');
    expect(events).toEqual([
      { type: 'start', agent: 'jarvis' },
      { type: 'token', text: 'a' },
    ]);
  });

  it('buffers a frame split across chunks', () => {
    const d = new SseDecoder();
    expect(d.push('data: {"type":"to')).toEqual([]);
    expect(d.push('ken","text":"hello"}\n')).toEqual([{ type: 'token', text: 'hello' }]);
  });

  it('streams tokens then an end event in order', () => {
    const d = new SseDecoder();
    const out = [
      ...d.push('data: {"type":"token","text":"He"}\n'),
      ...d.push('data: {"type":"token","text":"llo"}\n'),
      ...d.push('data: {"type":"end","text":"Hello"}\n'),
    ];
    expect(out).toEqual([
      { type: 'token', text: 'He' },
      { type: 'token', text: 'llo' },
      { type: 'end', text: 'Hello' },
    ]);
  });

  it('flush() drains an unterminated trailing line', () => {
    const d = new SseDecoder();
    expect(d.push('data: {"type":"end","text":"done"}')).toEqual([]);
    expect(d.flush()).toEqual([{ type: 'end', text: 'done' }]);
  });
});
