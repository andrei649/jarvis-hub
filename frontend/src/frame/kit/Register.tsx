/* Register, SecHead, Total: the ruled structure of a page (ledger README §2 "Shape, rules").
   A register is a column opened by the heavy rule, with a title strut so every title sits on
   the same line, and a body that scrolls by itself. It is drawn with the theme's panel
   treatment (--n-panel-*), so card themes give it their frame and Ledger keeps rules, not boxes.
   A section head is the label voice over a quiet rule. A total is a single rule above and a
   double rule below, the accountant's convention, for every summary line.

   Each of the three is a row of a title (the register's title, the section's title, the total's
   sentence) and a flow beside it (the meta, the aside, the total's aside), drawn by kit.css with one
   rule at every width: the flow takes the line under the title where the two do not fit, so the
   title is never squeezed, and a flow wider than the row wraps between its parts. A part wider than
   the row alone is cut with an ellipsis; `useCutTitles` gives it its whole text in a tooltip.

   A register's body and foot are in one box after the head (.n-register__main), so a page that lines
   registers up side by side can give their heads one shared row (home/home.css). A page whose registers
   keep their own heights (Trust's columns, each as tall as what it holds) gives their heads one height
   with `useHeadRow` instead. */
import React, { useEffect, useId, useLayoutEffect, useRef } from 'react';
import { textCut } from '../fit';
import './kit.css';

type HeadingLevel = 2 | 3 | 4;
const Heading = ({ level, ...props }: { level: HeadingLevel } & React.HTMLAttributes<HTMLHeadingElement>) =>
  React.createElement(`h${level}`, props);

/** Marks a title `useCutTitles` wrote, so it never removes a title it did not write. */
export const CUT_TITLE_ATTRIBUTE = 'data-cut-title';

/** The words of a part, as one line (its title when it is cut). */
const wholeText = (el: Element): string => (el.textContent || '').replace(/\s+/g, ' ').trim();

/** Each part of a flow (a child of `ref`: an aside's, a meta's, a total half's) that is cut with an
 *  ellipsis keeps its whole text in a tooltip: its `title`, written while it is cut and taken away
 *  once it is whole. A part's own title (one the page gave it) is left as it is. Its accessible name is
 *  its text, which an ellipsis does not shorten. It measures (`textCut`, frame/fit.ts: in fractions of
 *  a pixel, as Chromium cuts) when the flow is first laid out and whenever the flow or a part changes
 *  size (the window, a font arriving, the look, the language: a ResizeObserver, which reports a new
 *  observation once, after layout, so nothing is measured while React commits), and when its words
 *  change; never on a render that changes none of these. Writing a title changes no size, so it cannot
 *  call itself again. Where there is no ResizeObserver (a test DOM) it measures once when drawn. */
export function useCutTitles(ref: React.RefObject<HTMLElement | null>, on = true): void {
  useEffect(() => {
    const flow = ref.current;
    if (!on || !flow) return undefined;
    const mark = () => {
      for (const part of Array.from(flow.children)) {
        const ours = part.hasAttribute(CUT_TITLE_ATTRIBUTE);
        const whole = wholeText(part);
        if (whole && textCut(part)) {
          if (ours || !part.hasAttribute('title')) {
            if (part.getAttribute('title') !== whole) part.setAttribute('title', whole);
            if (!ours) part.setAttribute(CUT_TITLE_ATTRIBUTE, '');
          }
        } else if (ours) {
          part.removeAttribute('title');
          part.removeAttribute(CUT_TITLE_ATTRIBUTE);
        }
      }
    };
    const sizes = typeof ResizeObserver === 'function' ? new ResizeObserver(mark) : null;
    const watch = () => {
      if (!sizes) return;
      sizes.disconnect();
      sizes.observe(flow);
      for (const part of Array.from(flow.children)) sizes.observe(part);
    };
    const words = typeof MutationObserver === 'function' ? new MutationObserver(() => { watch(); mark(); }) : null;
    if (sizes) watch(); else mark();
    words?.observe(flow, { childList: true, subtree: true, characterData: true });
    return () => {
      sizes?.disconnect();
      words?.disconnect();
    };
  }, [ref, on]);
}

/** The custom property `useHeadRow` sets on a register head: the height of the tallest head beside it
 *  (kit.css: a head's minimum height is the larger of its own and this). */
export const HEAD_ROW_PROPERTY = '--register-head-row';

/** The heads of the registers drawn side by side in `ref` (their tops level, apart across the row) take
 *  one height, the tallest's, so the rules under them lie on one line whatever wraps (a meta that drops
 *  under its title in one register and not in the other). Nothing changes while they are level, which is
 *  the usual case: a head is held up (HEAD_ROW_PROPERTY) only while a head beside it is taller, and never
 *  past what that head needs. Registers one under another keep their own heads.
 *
 *  For a page whose registers keep their own heights (Trust's columns): Home's spread, whose cells fill
 *  the page anyway, shares a grid row instead (home/home.css), which would stretch every register to the
 *  tallest one's height here, a card look's frame with it.
 *
 *  It measures before the first paint, then when a title or a meta changes size (a ResizeObserver: the
 *  window, the words, the language, the look, a font arriving) and when a head gains or loses a part
 *  (a meta drawn once its reading answers). Each measure takes the property away, reads every head's own
 *  height and sets it again where one is taller: it observes the titles and metas, which a head's height
 *  never resizes, and not the heads, so its own writes call it back for nothing. Without a
 *  ResizeObserver (a test DOM) it measures when drawn and when a head's parts change. */
export function useHeadRow(ref: React.RefObject<HTMLElement | null>, on = true): void {
  useLayoutEffect(() => {
    const row = ref.current;
    if (!on || !row) return undefined;
    /** The heads of the registers in the row that are not inside another register of it. */
    const heads = () => Array.from(row.querySelectorAll<HTMLElement>('.n-register > .n-register__head'))
      .filter((head) => {
        const outer = head.parentElement?.parentElement?.closest('.n-register');
        return !outer || !row.contains(outer);
      });
    let watched: Element[] = [];
    const sizes = typeof ResizeObserver === 'function' ? new ResizeObserver(() => fit()) : null;
    const fit = () => {
      const all = heads();
      for (const head of all) head.style.removeProperty(HEAD_ROW_PROPERTY);
      const boxes = all.map((head) => ({ head, r: head.getBoundingClientRect() })).filter(({ r }) => r.width > 0 && r.height > 0);
      const rows: Array<typeof boxes> = [];
      for (const box of boxes) {
        const beside = rows.find((group) => group.some(({ r }) => Math.abs(r.top - box.r.top) < 1
          && (r.right <= box.r.left + 0.5 || box.r.right <= r.left + 0.5)));
        if (beside) beside.push(box); else rows.push([box]);
      }
      for (const group of rows) {
        const tallest = Math.max(...group.map(({ r }) => r.height));
        if (group.length < 2 || group.every(({ r }) => tallest - r.height < 0.5)) continue;
        for (const { head } of group) head.style.setProperty(HEAD_ROW_PROPERTY, `${tallest}px`);
      }
      // what to watch: every title and meta of these heads (re-read, so a meta drawn later is watched too)
      const parts = all.flatMap((head) => Array.from(head.children));
      if (sizes && (parts.length !== watched.length || parts.some((part, i) => part !== watched[i]))) {
        sizes.disconnect();
        for (const part of parts) sizes.observe(part);
      }
      watched = parts;
    };
    // a head that gains or loses a part (its meta), or a register drawn or taken away
    const shapes = (node: Node) => node instanceof Element && (node.matches('.n-register, .n-register__head, .n-register__head > *') || !!node.querySelector('.n-register'));
    const changes = typeof MutationObserver === 'function' ? new MutationObserver((records) => {
      if (records.some((m) => (m.target instanceof Element && m.target.classList.contains('n-register__head'))
        || Array.from(m.addedNodes).some(shapes) || Array.from(m.removedNodes).some(shapes))) fit();
    }) : null;
    fit();
    changes?.observe(row, { childList: true, subtree: true });
    return () => {
      sizes?.disconnect();
      changes?.disconnect();
      for (const head of heads()) head.style.removeProperty(HEAD_ROW_PROPERTY);
    };
  }, [ref, on]);
}

export interface RegisterProps {
  title: React.ReactNode;
  /** Right of the title: a SourceLabel, a count, a link. */
  meta?: React.ReactNode;
  /** The test hook: data-register="day" | "talk" | "docket" | "record" | … */
  register?: string;
  /** Base for the heading id (default: a generated one). */
  id?: string;
  as?: 'section' | 'nav' | 'aside' | 'div';
  headingLevel?: HeadingLevel;
  className?: string;
  /** Props for the scrolling body (role="log", tabIndex, a ref through bodyRef). */
  bodyProps?: React.HTMLAttributes<HTMLDivElement>;
  bodyRef?: React.Ref<HTMLDivElement>;
  /** Pinned under the body, outside the scroll (a Total, the composer). */
  foot?: React.ReactNode;
  children?: React.ReactNode;
}

export function Register({ title, meta, register, id, as = 'section', headingLevel = 2, className, bodyProps, bodyRef, foot, children }: RegisterProps) {
  const auto = useId();
  const headingId = `${id || `n-register-${auto.replace(/[^a-zA-Z0-9_-]/g, '')}`}-title`;
  const Tag = as;
  const metaRef = useRef<HTMLDivElement>(null);
  const hasMeta = meta != null && meta !== false;
  useCutTitles(metaRef, hasMeta);
  return (
    <Tag className={['n-register', className].filter(Boolean).join(' ')} aria-labelledby={headingId}
      {...(register ? { 'data-register': register } : {})}>
      <header className="n-register__head">
        <Heading level={headingLevel} className="n-register__title" id={headingId}>{title}</Heading>
        {hasMeta && <div className="n-register__meta" ref={metaRef}>{meta}</div>}
      </header>
      <div className="n-register__main">
        <div {...bodyProps} ref={bodyRef} className={['n-register__body', bodyProps?.className].filter(Boolean).join(' ')}>
          {children}
        </div>
        {foot != null && foot !== false && <div className="n-register__foot">{foot}</div>}
      </div>
    </Tag>
  );
}

export interface SecHeadProps {
  title: React.ReactNode;
  /** Beside the title, in the meta size: a source label, a count, a link. It takes the line under the
   *  title where the two do not fit (kit.css). */
  aside?: React.ReactNode;
  level?: HeadingLevel;
  id?: string;
  className?: string;
}

/** A section head inside a register. */
export function SecHead({ title, aside, level = 3, id, className }: SecHeadProps) {
  const asideRef = useRef<HTMLElement>(null);
  const hasAside = aside != null && aside !== false;
  useCutTitles(asideRef, hasAside);
  return (
    <div className={['n-sec', className].filter(Boolean).join(' ')}>
      <Heading level={level} className="n-sec__title" id={id}>{title}</Heading>
      {hasAside && <small className="n-sec__aside" ref={asideRef}>{aside}</small>}
    </div>
  );
}

export interface TotalProps {
  /** The total's sentence: "7 entries · 2 held or blocked". Wrap figures in <b>. */
  children: React.ReactNode;
  /** Right-aligned part, e.g. a link. It takes the line under the sentence where the two do not fit. */
  aside?: React.ReactNode;
  className?: string;
}

/** A total line: a single rule above, a double rule below. */
export function Total({ children, aside, className }: TotalProps) {
  const mainRef = useRef<HTMLSpanElement>(null);
  const asideRef = useRef<HTMLSpanElement>(null);
  const hasAside = aside != null && aside !== false;
  useCutTitles(mainRef);
  useCutTitles(asideRef, hasAside);
  return (
    <div className={['n-total', className].filter(Boolean).join(' ')} data-total="">
      <span className="n-total__main" ref={mainRef}>{children}</span>
      {hasAside && <span className="n-total__aside" ref={asideRef}>{aside}</span>}
    </div>
  );
}
