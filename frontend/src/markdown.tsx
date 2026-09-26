/* H165 / H168 — the shared, safe Markdown renderer.

   A line-based block parser and an inline tokenizer that emit React elements only.
   Nothing here uses dangerouslySetInnerHTML, so raw HTML in a document (<script>,
   <iframe>, an onerror attribute) is shown as the literal text it is.

   Blocks: headings, ``` / ~~~ fences (as <pre><code>), pipe tables, bullet and
   ordered lists, blockquotes, horizontal rules and paragraphs. Inline: code, bold,
   italic and [label](url) links. A link renders only for an http(s) URL or a
   same-origin path, and opens in a new tab with rel="noopener noreferrer". Anything
   else (javascript:, data:, a protocol-relative //host, a bare file name) stays
   text. Unrecognised syntax is left as text too. */
import React from 'react';
import { internalLink } from './base-path';

/* One inline token at a time, leftmost first: code, bold, italic, link. No regex
   lookbehind (older Safari cannot parse it and the whole bundle would fail): an
   italic candidate is checked in code instead, and must hug its words with no
   word character outside it, so MEMORY_EMBED_TURNS and "2 * 3 * 4" stay text. */
const INLINE = /`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\s][^*\n]*?\*|_[^_\s][^_\n]*?_|\[[^\]\n]+\]\([^)\s]+\)/g;
const LINK = /^\[([^\]]+)\]\(([^)\s]+)\)$/;
const WORD = /[\p{L}\p{N}_]/u;

/** The href a link may carry, or null when it must stay text. */
export function safeHref(url: string): string | null {
  // Browsers drop TAB/LF/CR inside a URL before parsing it: "/<TAB>/host" would
  // become protocol-relative, so classify what the browser will actually see.
  const u = String(url || '').replace(/[\t\n\r]/g, '').trim();
  if (/^https?:\/\/[^/\\]/i.test(u)) return u;
  if (u.startsWith('/') && !u.startsWith('//') && !u.startsWith('/\\')) return internalLink(u);
  return null;
}

function renderToken(token: string, key: string): React.ReactNode {
  if (token.startsWith('`')) return <code key={key}>{token.slice(1, -1)}</code>;
  if (token.startsWith('**') || token.startsWith('__')) {
    return <strong key={key}>{renderInline(token.slice(2, -2), `${key}-`)}</strong>;
  }
  if (token.startsWith('*') || token.startsWith('_')) return <em key={key}>{token.slice(1, -1)}</em>;
  const link = token.match(LINK)!;
  const href = safeHref(link[2]);
  return href
    ? <a key={key} href={href} target="_blank" rel="noopener noreferrer">{link[1]}</a>
    : <span key={key}>{link[1]}</span>;
}

export function renderInline(text: string, keyPrefix = ''): React.ReactNode[] {
  const source = String(text ?? '');
  const out: React.ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const match of source.matchAll(INLINE)) {
    const token = match[0];
    const start = match.index ?? 0;
    const end = start + token.length;
    const italic = (token[0] === '*' || token[0] === '_') && token[1] !== token[0];
    if (italic && (WORD.test(source[start - 1] || '') || WORD.test(source[end] || '')
        || /\s/.test(token[token.length - 2]))) {
      continue;  // not emphasis: it stays part of the surrounding text
    }
    if (start > last) out.push(source.slice(last, start));
    out.push(renderToken(token, `${keyPrefix}${n}`));
    n += 1;
    last = end;
  }
  if (last < source.length) out.push(source.slice(last));
  return out;
}

const FENCE = /^\s*(```|~~~)/;
const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const QUOTE = /^\s*>\s?(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const ORDERED = /^\s*\d{1,9}[.)]\s+(.*)$/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;

function tableCells(line: string): string[] {
  let row = line.trim();
  if (row.startsWith('|')) row = row.slice(1);
  if (row.endsWith('|')) row = row.slice(0, -1);
  return row.split('|').map((cell) => cell.trim());
}

function startsBlock(lines: string[], i: number): boolean {
  const line = lines[i];
  return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || QUOTE.test(line)
    || BULLET.test(line) || ORDERED.test(line)
    || (line.includes('|') && i + 1 < lines.length && TABLE_SEPARATOR.test(lines[i + 1]));
}

/** A heading's anchor: lower case, backticks dropped, every other run of characters
    outside [a-z0-9_.] one '-'. agents/core/routers/help_docs.py computes the same. */
export function headingAnchor(text: string): string {
  return String(text ?? '').replace(/`/g, '').toLowerCase().replace(/[^a-z0-9_.]+/g, '-').replace(/^-+|-+$/g, '');
}

/** *breaks*: a single newline inside a paragraph is a line break (GitHub's comment
    flavour), for chat replies and notes written line by line; without it the lines of
    a paragraph join, as in a document. */
export function Markdown({ text, className, breaks = false }: { text: string; className?: string; breaks?: boolean }) {
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  const anchors = new Map<string, number>();  // a repeated anchor gets -2, -3 … like GitHub's
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const key = blocks.length;
    const fence = line.match(FENCE);
    if (fence) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) { body.push(lines[i]); i += 1; }
      i += 1;  // the closing fence (or the end of the document)
      blocks.push(<pre key={key}><code>{body.join('\n')}</code></pre>);
      continue;
    }
    const heading = line.match(HEADING);
    if (heading) {
      const base = headingAnchor(heading[2]);
      const seen = anchors.get(base) || 0;
      anchors.set(base, seen + 1);
      const id = seen ? `${base}-${seen + 1}` : base;
      blocks.push(React.createElement(`h${heading[1].length}`, { key, id: id || undefined, className: 'md-h' },
        renderInline(heading[2], `h${key}-`)));
      i += 1;
      continue;
    }
    if (line.includes('|') && i + 1 < lines.length && TABLE_SEPARATOR.test(lines[i + 1])) {
      const head = tableCells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) { rows.push(tableCells(lines[i])); i += 1; }
      blocks.push(
        <table key={key}>
          <thead><tr>{head.map((cell, c) => <th key={c}>{renderInline(cell, `t${key}-${c}-`)}</th>)}</tr></thead>
          <tbody>{rows.map((row, r) => (
            <tr key={r}>{row.map((cell, c) => <td key={c}>{renderInline(cell, `t${key}-${r}-${c}-`)}</td>)}</tr>
          ))}</tbody>
        </table>);
      continue;
    }
    if (RULE.test(line)) { blocks.push(<hr key={key} />); i += 1; continue; }
    if (QUOTE.test(line)) {
      const quoted: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i])) { quoted.push(lines[i].match(QUOTE)![1]); i += 1; }
      blocks.push(<blockquote key={key}>{renderInline(quoted.join(' '), `q${key}-`)}</blockquote>);
      continue;
    }
    if (BULLET.test(line) || ORDERED.test(line)) {
      const ordered = !BULLET.test(line);
      const marker = ordered ? ORDERED : BULLET;
      const items: string[] = [];
      while (i < lines.length && marker.test(lines[i])) {
        items.push(lines[i].match(marker)![1]);
        i += 1;
        // An indented continuation line belongs to the item above it.
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !BULLET.test(lines[i]) && !ORDERED.test(lines[i])) {
          items[items.length - 1] += ` ${lines[i].trim()}`;
          i += 1;
        }
      }
      const children = items.map((item, n) => <li key={n}>{renderInline(item, `l${key}-${n}-`)}</li>);
      blocks.push(ordered ? <ol key={key}>{children}</ol> : <ul key={key}>{children}</ul>);
      continue;
    }
    if (!line.trim()) { i += 1; continue; }
    const paragraph = [line.trim()];
    i += 1;
    while (i < lines.length && lines[i].trim() && !startsBlock(lines, i)) { paragraph.push(lines[i].trim()); i += 1; }
    blocks.push(<p key={key}>{breaks
      ? paragraph.flatMap((part, n) => [
        ...(n ? [<br key={`b${n}`} />] : []),
        <React.Fragment key={`f${n}`}>{renderInline(part, `p${key}-${n}-`)}</React.Fragment>])
      : renderInline(paragraph.join(' '), `p${key}-`)}</p>);
  }
  return <div className={className || 'md'}>{blocks}</div>;
}
