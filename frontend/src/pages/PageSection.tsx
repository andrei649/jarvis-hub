/* PageSection: the one section wrapper of every mode page (PHASE_B_PLAN.md §2.3, §6).

   It replaced the five wrappers the modes used to carry (ModePanel, MP, Panel, and the
   hand-written .panel + corner-bracket blocks in AgentsMode, MemoryMode, CommsMode, AdminMode).
   It draws a register from the frame kit: the title strut, the source label and meta on the right,
   a scrolling body, all through the theme's panel roles. `headExtra` (a control in the head) and
   `lead` (a note between the head and the body) sit beside them. (The HUD v2 panel markup it also
   wrote while the classic shell lived was deleted with that shell, Phase B stage 5.) */
import React from 'react';
import { Register, SourceLabel } from '../frame/kit';
import type { Reading } from '../signals/types';
import './pages.css';

export interface PageSectionProps {
  title: React.ReactNode;
  /** Where the section's data comes from and how current it is; drawn in the head. */
  source?: Reading<unknown> | null;
  /** Right of the title (a short status). */
  meta?: React.ReactNode;
  /** Inline style of the meta (the Trust head turns it red when the chain is broken). */
  metaStyle?: React.CSSProperties;
  id?: string;
  className?: string;
  lang?: string;
  children?: React.ReactNode;
  /** A control that belongs in the head, after the meta. */
  headExtra?: React.ReactNode;
  /** Content between the head and the body. */
  lead?: React.ReactNode;
  /** Props for the scrolling body (role, aria-label, tabIndex, style). */
  bodyProps?: React.HTMLAttributes<HTMLDivElement>;
}

export function PageSection(props: PageSectionProps) {
  const { title, source, meta, metaStyle, id, className, lang, children, headExtra, lead, bodyProps } = props;
  const right = (source || (meta != null && meta !== false) || headExtra) ? (
    <>
      {source && <SourceLabel reading={source} lang={lang} />}
      {meta != null && meta !== false && <span className="n-pagesection__meta" style={metaStyle}>{meta}</span>}
      {headExtra}
    </>
  ) : undefined;
  return (
    <div className={['n-pagesection', className].filter(Boolean).join(' ')} id={id}>
      <Register title={title} meta={right} bodyProps={bodyProps}>
        {lead}
        {children}
      </Register>
    </div>
  );
}
