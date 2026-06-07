import { describe, expect, it } from '@jest/globals';
import { parseInline, parseMarkdown, type Block } from '../parse';

describe('parseInline', () => {
  it('returns plain text untouched', () => {
    expect(parseInline('hello world')).toEqual([{ type: 'text', text: 'hello world' }]);
  });

  it('parses bold, italic and inline code', () => {
    expect(parseInline('**b**')).toEqual([{ type: 'bold', children: [{ type: 'text', text: 'b' }] }]);
    expect(parseInline('_i_')).toEqual([{ type: 'italic', children: [{ type: 'text', text: 'i' }] }]);
    expect(parseInline('`c`')).toEqual([{ type: 'code', text: 'c' }]);
  });

  it('parses links', () => {
    expect(parseInline('see [docs](https://x.dev)')).toEqual([
      { type: 'text', text: 'see ' },
      { type: 'link', text: 'docs', href: 'https://x.dev' },
    ]);
  });

  it('nests italic inside bold', () => {
    expect(parseInline('**a _b_**')).toEqual([
      {
        type: 'bold',
        children: [
          { type: 'text', text: 'a ' },
          { type: 'italic', children: [{ type: 'text', text: 'b' }] },
        ],
      },
    ]);
  });

  it('leaves a lone asterisk as text', () => {
    expect(parseInline('2 * 3 = 6')).toEqual([{ type: 'text', text: '2 * 3 = 6' }]);
  });
});

describe('parseMarkdown', () => {
  it('parses a heading', () => {
    expect(parseMarkdown('# Title')).toEqual([
      { type: 'heading', level: 1, inline: [{ type: 'text', text: 'Title' }] },
    ]);
  });

  it('parses a fenced code block with a language', () => {
    const blocks = parseMarkdown('```ts\nconst x = 1;\n```');
    expect(blocks).toEqual([{ type: 'code', lang: 'ts', text: 'const x = 1;' }]);
  });

  it('groups consecutive list items', () => {
    const blocks = parseMarkdown('- one\n- two\n- three');
    expect(blocks).toHaveLength(1);
    const list = blocks[0] as Extract<Block, { type: 'list' }>;
    expect(list.type).toBe('list');
    expect(list.ordered).toBe(false);
    expect(list.items).toHaveLength(3);
  });

  it('detects ordered lists', () => {
    const blocks = parseMarkdown('1. first\n2. second');
    const list = blocks[0] as Extract<Block, { type: 'list' }>;
    expect(list.ordered).toBe(true);
    expect(list.items).toHaveLength(2);
  });

  it('parses a blockquote', () => {
    expect(parseMarkdown('> quoted')).toEqual([
      { type: 'quote', inline: [{ type: 'text', text: 'quoted' }] },
    ]);
  });

  it('separates paragraphs on blank lines and joins wrapped lines', () => {
    const blocks = parseMarkdown('para one\nstill one\n\npara two');
    expect(blocks).toEqual([
      { type: 'paragraph', inline: [{ type: 'text', text: 'para one still one' }] },
      { type: 'paragraph', inline: [{ type: 'text', text: 'para two' }] },
    ]);
  });

  it('handles a mixed document', () => {
    const types = parseMarkdown('# H\n\ntext **b**\n\n- a\n- b\n\n```\ncode\n```').map((b) => b.type);
    expect(types).toEqual(['heading', 'paragraph', 'list', 'code']);
  });
});
