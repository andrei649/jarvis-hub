/* Model and report text rendered through the shared safe Markdown renderer, with every
   inline citation "[n]" that matches a known source turned into a chip that opens it.

   The renderer emits plain React elements (no HTML strings), so the chips are added by walking
   that element tree and splitting text nodes; code spans and code blocks are left untouched so
   an array index such as "items[1]" in a snippet stays text. A "[n]" without a matching source
   stays text too: numbering is exactly what the server streamed (spec §8). Tables are wrapped in
   a focusable frame so a wide one can be scrolled sideways from the keyboard. */
import React, { useMemo } from 'react';
import { Markdown } from '../../../markdown';
import type { Citation } from '../../api/types';
import { useI18n } from '../../i18n';

const MARKER = /\[(\d{1,3})\]/g;
const LITERAL_TAGS = new Set(['code', 'pre']);

type ChipRenderer = (citation: Citation, key: string) => React.ReactNode;

function decorateText(text: string, byNumber: Map<number, Citation>, chip: ChipRenderer, keyBase: string): React.ReactNode {
  if (!text.includes('[')) return text;
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    const citation = byNumber.get(Number(match[1]));
    if (!citation) continue;
    const start = match.index ?? 0;
    if (start > last) parts.push(text.slice(last, start));
    parts.push(chip(citation, `${keyBase}c${parts.length}`));
    last = start + match[0].length;
  }
  if (parts.length === 0) return text;
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function decorate(node: React.ReactNode, byNumber: Map<number, Citation>, chip: ChipRenderer, keyBase: string): React.ReactNode {
  if (typeof node === 'string') return decorateText(node, byNumber, chip, keyBase);
  if (Array.isArray(node)) {
    return node.map((child, i) => {
      const out = decorate(child, byNumber, chip, `${keyBase}${i}-`);
      return Array.isArray(out) ? <React.Fragment key={`${keyBase}f${i}`}>{out}</React.Fragment> : out;
    });
  }
  if (React.isValidElement(node)) {
    if (typeof node.type === 'string' && LITERAL_TAGS.has(node.type)) return node;
    const children = (node.props as { children?: React.ReactNode }).children;
    if (children === undefined || children === null) return node;
    const decorated = React.cloneElement(node, undefined, decorate(children, byNumber, chip, `${keyBase}e-`));
    if (node.type !== 'table') return decorated;
    return <div key={node.key ?? undefined} className="ws-md__table" tabIndex={0}>{decorated}</div>;
  }
  return node;
}

export interface CitedMarkdownProps {
  text: string;
  /** Empty for text without sources (an email preview): it still gets the table frames. */
  citations: Citation[];
  onCite: (citation: Citation) => void;
  /** Chat replies keep single line breaks; reports read as documents. */
  breaks?: boolean;
}

export function CitedMarkdown({ text, citations, onCite, breaks = false }: CitedMarkdownProps) {
  const { t } = useI18n();
  const byNumber = useMemo(() => new Map(citations.map((c) => [c.n, c])), [citations]);
  const chip: ChipRenderer = (citation, key) => (
    <button
      key={key} type="button" className="ws-cite" title={citation.title}
      aria-label={t('source.chip', { n: String(citation.n), title: citation.title })}
      onClick={() => onCite(citation)}
    >
      {citation.n}
    </button>
  );
  // Markdown is a pure function of its props (no hooks), so its element tree can be decorated.
  return <>{decorate(Markdown({ text, breaks, className: 'md ws-md' }), byNumber, chip, 'm')}</>;
}

/** The numbered list of sources under an answer or a report; each opens the source drawer. */
export function SourcesList({ citations, onCite }: { citations: Citation[]; onCite: (citation: Citation) => void }) {
  const { t } = useI18n();
  if (citations.length === 0) return null;
  return (
    <div className="ws-sources">
      <p className="ws-sources__title">{t('chat.sources')}</p>
      <ol className="ws-sources__list">
        {citations.map((c) => (
          <li key={c.n}>
            <button type="button" className="ws-source" onClick={() => onCite(c)}>
              <span className="ws-cite ws-cite--static" aria-hidden="true">{c.n}</span>
              <span className="ws-source__title">{c.title}</span>
              {c.page !== null && c.page !== undefined && <span className="ws-source__page">{t('source.page', { page: String(c.page) })}</span>}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
