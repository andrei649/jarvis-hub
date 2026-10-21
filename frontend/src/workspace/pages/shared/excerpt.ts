/* A cited passage as readable Markdown.

   The server stores a citation's excerpt with its whitespace collapsed to single spaces, so a
   table the extractor wrote as Markdown (a DOCX table, an XLSX sheet, a CSV) arrives as one line:
   "… fișa clientului. | Categorie client | Discount | | --- | --- | | Client nou | 12% | …".
   Shown as is, that reads as noise at the exact moment someone checks a source. This rebuilds
   the line breaks such a table needs: the separator row names the column count, the cells just
   before it are the header, and each following run of that many cells is a row. A "## Sheet"
   heading right before a table gets its own line too. Text that is not a table is left alone,
   and the words are never changed — only line breaks are put back. */

const SEPARATOR = /\|(?:\s*:?-{3,}:?\s*\|)+/g;

function cells(segment: string): number {
  return (segment.match(/\|/g)?.length ?? 1) - 1;
}

/** The header cells before a separator: the last `count` cells of `before`, which ends in "|". */
function splitHeader(before: string, count: number): { prefix: string; header: string } | null {
  const text = before.trimEnd();
  if (!text.endsWith('|')) return null;
  let seen = 0;
  for (let i = text.length - 1; i >= 0; i -= 1) {
    if (text[i] !== '|') continue;
    seen += 1;
    if (seen === count + 1) return { prefix: text.slice(0, i).trimEnd(), header: text.slice(i) };
  }
  return null;
}

/** The body rows after a separator, `count` cells each, and whatever text follows them. */
function splitRows(after: string, count: number): { rows: string[]; rest: string } {
  const row = new RegExp(`^\\s*(\\|(?:[^|]*\\|){${count}})`);
  const rows: string[] = [];
  let rest = after;
  for (let match = row.exec(rest); match; match = row.exec(rest)) {
    rows.push(match[1].trim());
    rest = rest.slice(match[0].length);
  }
  return { rows, rest: rest.trim() };
}

/** "… intro ## Încasări" → intro and a heading on its own line. */
function splitHeading(prefix: string): string {
  // A heading opens the passage or follows a finished sentence; a lone "#" mid-sentence is text.
  const match = /(^|[.!?:…]\s+)(#{1,6}) ([^#|]+)$/.exec(prefix);
  if (!match) return prefix;
  const before = prefix.slice(0, match.index + match[1].length).trim();
  const heading = `${match[2]} ${match[3].trim()}`;
  return before ? `${before}\n\n${heading}` : heading;
}

export function excerptMarkdown(excerpt: string): string {
  const text = String(excerpt ?? '');
  if (text.includes('\n')) return text;  // line breaks kept: already readable Markdown
  SEPARATOR.lastIndex = 0;
  const separator = SEPARATOR.exec(text);
  if (!separator) return text;
  const count = cells(separator[0]);
  const head = splitHeader(text.slice(0, separator.index), count);
  if (!head || count < 1) return text;
  const { rows, rest } = splitRows(text.slice(separator.index + separator[0].length), count);
  const table = [head.header, separator[0].trim(), ...rows].join('\n');
  const parts = [head.prefix ? splitHeading(head.prefix) : '', table, rest ? excerptMarkdown(rest) : ''];
  return parts.filter(Boolean).join('\n\n');
}
