/**
 * A small, dependency-free Markdown parser producing a typed AST.
 *
 * Scope is deliberately the subset an assistant actually emits: fenced code,
 * headings, ordered/unordered lists, blockquotes, paragraphs, and inline
 * bold / italic / code / links. Pure (no RN imports) → unit-testable; the
 * renderer in Markdown.tsx maps this AST to React Native nodes.
 */

export type Inline =
  | { type: 'text'; text: string }
  | { type: 'bold'; children: Inline[] }
  | { type: 'italic'; children: Inline[] }
  | { type: 'code'; text: string }
  | { type: 'link'; text: string; href: string };

export type Block =
  | { type: 'code'; lang: string; text: string }
  | { type: 'heading'; level: number; inline: Inline[] }
  | { type: 'list'; ordered: boolean; items: Inline[][] }
  | { type: 'quote'; inline: Inline[] }
  | { type: 'paragraph'; inline: Inline[] };

const LIST_RE = /^\s*([-*+]|\d+[.)])\s+/;
const ORDERED_RE = /^\s*\d+[.)]\s+/;
const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const QUOTE_RE = /^\s*>\s?/;
const FENCE_RE = /^```(.*)$/;

export function parseMarkdown(md: string): Block[] {
  const lines = md.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    const fence = line.match(FENCE_RE);
    if (fence) {
      const lang = fence[1].trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !FENCE_RE.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      i++; // consume closing fence (if present)
      blocks.push({ type: 'code', lang, text: buf.join('\n') });
      continue;
    }

    // Blank line
    if (line.trim() === '') {
      i++;
      continue;
    }

    // Heading
    const heading = line.match(HEADING_RE);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, inline: parseInline(heading[2].trim()) });
      i++;
      continue;
    }

    // List (gather consecutive items)
    if (LIST_RE.test(line)) {
      const ordered = ORDERED_RE.test(line);
      const items: Inline[][] = [];
      while (i < lines.length && LIST_RE.test(lines[i])) {
        items.push(parseInline(lines[i].replace(LIST_RE, '')));
        i++;
      }
      blocks.push({ type: 'list', ordered, items });
      continue;
    }

    // Blockquote
    if (QUOTE_RE.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && QUOTE_RE.test(lines[i])) {
        buf.push(lines[i].replace(QUOTE_RE, ''));
        i++;
      }
      blocks.push({ type: 'quote', inline: parseInline(buf.join(' ')) });
      continue;
    }

    // Paragraph (gather until a blank line or the start of another block)
    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !FENCE_RE.test(lines[i]) &&
      !HEADING_RE.test(lines[i]) &&
      !LIST_RE.test(lines[i]) &&
      !QUOTE_RE.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push({ type: 'paragraph', inline: parseInline(buf.join(' ')) });
  }

  return blocks;
}

export function parseInline(src: string): Inline[] {
  const nodes: Inline[] = [];
  let plain = '';
  let i = 0;

  const flush = () => {
    if (plain) {
      nodes.push({ type: 'text', text: plain });
      plain = '';
    }
  };

  while (i < src.length) {
    const c = src[i];

    // Inline code — no nested formatting
    if (c === '`') {
      const end = src.indexOf('`', i + 1);
      if (end > i) {
        flush();
        nodes.push({ type: 'code', text: src.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }

    // Link [text](href)
    if (c === '[') {
      const close = src.indexOf(']', i + 1);
      if (close > i && src[close + 1] === '(') {
        const paren = src.indexOf(')', close + 2);
        if (paren > close) {
          flush();
          nodes.push({ type: 'link', text: src.slice(i + 1, close), href: src.slice(close + 2, paren) });
          i = paren + 1;
          continue;
        }
      }
    }

    // Bold ** or __
    if ((c === '*' && src[i + 1] === '*') || (c === '_' && src[i + 1] === '_')) {
      const marker = src.slice(i, i + 2);
      const end = src.indexOf(marker, i + 2);
      if (end > i + 1) {
        flush();
        nodes.push({ type: 'bold', children: parseInline(src.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    }

    // Italic * or _
    if (c === '*' || c === '_') {
      const end = src.indexOf(c, i + 1);
      if (end > i + 1) {
        flush();
        nodes.push({ type: 'italic', children: parseInline(src.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }

    plain += c;
    i++;
  }

  flush();
  return nodes;
}
