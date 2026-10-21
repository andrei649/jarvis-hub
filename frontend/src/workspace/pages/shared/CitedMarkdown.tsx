/* Model and report text rendered through the shared safe Markdown renderer, with every
   inline citation "[n]" that matches a known source turned into a chip that opens it.

   The renderer emits plain React elements (no HTML strings), so the chips are added by walking
   that element tree and splitting text nodes; code spans and code blocks are left untouched so
   an array index such as "items[1]" in a snippet stays text. A "[n]" without a matching source
   stays text too: numbering is exactly what the server streamed (spec §8). Tables are wrapped in
   a focusable, labelled frame so a wide one can be scrolled sideways from the keyboard.

   `headingOffset` moves the text's headings down the page outline: a report's "# Title" or an
   answer's "## Section" sits under the page's own h1 (and the chat's h2), never beside it.

   A chip inside running text keeps the compact size of the line it sits in (WCAG 2.5.8's
   inline exception). A chip that starts its block — the "Nr." cell of a report's table, the
   head of a "Surse" list item — is a target on its own, so it gets the full 24 × 24 px
   (`ws-cite--lead`, review A11Y-15). */
import React, { useMemo } from 'react';
import { Markdown } from '../../../markdown';
import type { Citation } from '../../api/types';
import { useI18n } from '../../i18n';

const MARKER = /\[(\d{1,3})\]/g;
const LITERAL_TAGS = new Set(['code', 'pre']);
const HEADING = /^h([1-6])$/;
/** Elements whose content starts a new line of its own; inline ones (strong, a…) continue it. */
const BLOCK_TAGS = new Set(['p', 'li', 'td', 'th', 'blockquote', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'table', 'thead', 'tbody', 'tr']);

/** *lead*: nothing but other chips (or spaces) comes before this one in its block. */
type ChipRenderer = (citation: Citation, key: string, lead: boolean) => React.ReactNode;

function decorateText(text: string, byNumber: Map<number, Citation>, chip: ChipRenderer, keyBase: string, atStart: boolean): React.ReactNode {
  if (!text.includes('[')) return text;
  const parts: React.ReactNode[] = [];
  let last = 0;
  let lead = atStart;
  for (const match of text.matchAll(MARKER)) {
    const citation = byNumber.get(Number(match[1]));
    if (!citation) continue;
    const start = match.index ?? 0;
    const before = text.slice(last, start);
    if (before.trim()) lead = false;
    if (start > last) parts.push(before);
    parts.push(chip(citation, `${keyBase}c${parts.length}`, lead));
    last = start + match[0].length;
  }
  if (parts.length === 0) return text;
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

interface DecorateContext {
  byNumber: Map<number, Citation>;
  chip: ChipRenderer;
  headingOffset: number;
  tableLabel: string;
}

function decorate(node: React.ReactNode, ctx: DecorateContext, keyBase: string, atStart = true): React.ReactNode {
  if (typeof node === 'string') return decorateText(node, ctx.byNumber, ctx.chip, keyBase, atStart);
  if (Array.isArray(node)) {
    return node.map((child, i) => {
      const out = decorate(child, ctx, `${keyBase}${i}-`, atStart && i === 0);
      return Array.isArray(out) ? <React.Fragment key={`${keyBase}f${i}`}>{out}</React.Fragment> : out;
    });
  }
  if (React.isValidElement(node)) {
    if (typeof node.type === 'string' && LITERAL_TAGS.has(node.type)) return node;
    const children = (node.props as { children?: React.ReactNode }).children;
    if (children === undefined || children === null) return node;
    const block = typeof node.type === 'string' && BLOCK_TAGS.has(node.type);
    const inner = decorate(children, ctx, `${keyBase}e-`, block || atStart);
    const level = typeof node.type === 'string' ? HEADING.exec(node.type) : null;
    if (level && ctx.headingOffset > 0) {
      const props = node.props as Record<string, unknown>;
      const demoted = Math.min(6, Number(level[1]) + ctx.headingOffset);
      return React.createElement(`h${demoted}`, { key: node.key ?? undefined, id: props.id, className: props.className }, inner);
    }
    const decorated = React.cloneElement(node, undefined, inner);
    if (node.type !== 'table') return decorated;
    return <div key={node.key ?? undefined} className="ws-md__table" tabIndex={0} role="group" aria-label={ctx.tableLabel}>{decorated}</div>;
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
  /** Levels added to every heading (1: "#" renders as h2), so the text nests under the page's. */
  headingOffset?: number;
  className?: string;
}

export function CitedMarkdown({ text, citations, onCite, breaks = false, headingOffset = 0, className }: CitedMarkdownProps) {
  const { t } = useI18n();
  const byNumber = useMemo(() => new Map(citations.map((c) => [c.n, c])), [citations]);
  const chip: ChipRenderer = (citation, key, lead) => (
    <button
      key={key} type="button" className={lead ? 'ws-cite ws-cite--lead' : 'ws-cite'} title={citation.title}
      aria-label={t('source.chip', { n: String(citation.n), title: citation.title })}
      onClick={() => onCite(citation)}
    >
      {citation.n}
    </button>
  );
  // Markdown is a pure function of its props (no hooks), so its element tree can be decorated.
  const ctx: DecorateContext = { byNumber, chip, headingOffset, tableLabel: t('common.tableScroll') };
  return <>{decorate(Markdown({ text, breaks, className: ['md ws-md', className].filter(Boolean).join(' ') }), ctx, 'm')}</>;
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
