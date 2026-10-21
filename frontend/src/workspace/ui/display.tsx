/* Presentational building blocks: Badge, Avatar, Card, PageHeader, EmptyState, Spinner,
   Skeleton, Notice. Kept dumb on purpose — they take copy from the caller, so every string on
   screen comes from the typed dictionaries. */
import React from 'react';
import { Icon, type IconName } from './icons';

export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export function Badge({ tone = 'neutral', children, dot = false, className }: { tone?: Tone; children: React.ReactNode; dot?: boolean; className?: string }) {
  return (
    <span className={['ws-badge', `ws-badge--${tone}`, className].filter(Boolean).join(' ')}>
      {dot && <span className="ws-badge__dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

/** A small count pill (unread notifications, pending approvals); hidden when zero. The digits
    are decorative; `label` ("3 pending") is read instead, as part of the parent control's name. */
export function CountBadge({ count, label }: { count: number; label: string }) {
  if (count <= 0) return null;
  return (
    <>
      <span className="ws-count" aria-hidden="true">{count > 99 ? '99+' : count}</span>
      <span className="ws-sr-only">{label}</span>
    </>
  );
}

const AVATAR_TONES = 6;

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] ?? '?').slice(0, 2);
  return letters.toLocaleUpperCase();
}

/** Initials on a tone picked deterministically from the name, so a person keeps their colour. */
export function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return (
    <span
      className={`ws-avatar ws-avatar--t${hash % AVATAR_TONES}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
      aria-hidden="true"
    >
      {initials(name || '?')}
    </span>
  );
}

export function Card({ title, description, actions, children, className, as = 'section' }: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  as?: 'section' | 'div';
}) {
  const Tag = as;
  return (
    <Tag className={['ws-card', className].filter(Boolean).join(' ')}>
      {(title || actions) && (
        <header className="ws-card__header">
          <div>
            {title && <h2 className="ws-card__title">{title}</h2>}
            {description && <p className="ws-card__desc">{description}</p>}
          </div>
          {actions && <div className="ws-card__actions">{actions}</div>}
        </header>
      )}
      {children}
    </Tag>
  );
}

/** The page's single h1. It takes focus after navigation (see router.tsx) so screen readers
    announce the new page; the outline is suppressed for that programmatic focus only. */
export function PageHeader({ title, description, actions, eyebrow, compact = false }: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: React.ReactNode;
  /** Below 768 px the description is dropped (a page whose content needs the height, the chat). */
  compact?: boolean;
}) {
  return (
    <header className={['ws-page-header', compact && 'ws-page-header--compact'].filter(Boolean).join(' ')}>
      <div className="ws-page-header__text">
        {eyebrow && <p className="ws-page-header__eyebrow">{eyebrow}</p>}
        <h1 className="ws-page-header__title" tabIndex={-1} data-page-heading="true">{title}</h1>
        {description && <p className="ws-page-header__desc">{description}</p>}
      </div>
      {actions && <div className="ws-page-header__actions">{actions}</div>}
    </header>
  );
}

export function EmptyState({ icon = 'info', title, body, action, compact = false }: {
  icon?: IconName;
  title: React.ReactNode;
  body?: React.ReactNode;
  action?: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={['ws-empty', compact && 'ws-empty--compact'].filter(Boolean).join(' ')}>
      <span className="ws-empty__icon"><Icon name={icon} size={22} /></span>
      <p className="ws-empty__title">{title}</p>
      {body && <p className="ws-empty__body">{body}</p>}
      {action && <div className="ws-empty__action">{action}</div>}
    </div>
  );
}

export function Spinner({ label, size = 20 }: { label?: string; size?: number }) {
  return (
    <span className="ws-spinner-wrap" role={label ? 'status' : undefined}>
      <span className="ws-spinner" style={{ width: size, height: size }} aria-hidden="true" />
      {label && <span className="ws-sr-only">{label}</span>}
    </span>
  );
}

export function Skeleton({ width = '100%', height = 14, radius, className }: { width?: number | string; height?: number; radius?: number; className?: string }) {
  return <span className={['ws-skeleton', className].filter(Boolean).join(' ')} style={{ width, height, borderRadius: radius }} aria-hidden="true" />;
}

/** Placeholder for a loading section: skeleton lines plus a screen-reader status. */
export function LoadingBlock({ label, lines = 3 }: { label: string; lines?: number }) {
  return (
    <div className="ws-loading-block" role="status" aria-live="polite">
      <span className="ws-sr-only">{label}</span>
      {Array.from({ length: lines }, (_, i) => <Skeleton key={i} width={`${90 - i * 15}%`} />)}
    </div>
  );
}

const NOTICE_ICON: Record<Exclude<Tone, 'neutral'>, IconName> = { accent: 'info', success: 'checkCircle', warning: 'alert', danger: 'xCircle' };

/** An inline banner for honest states: "SMTP is not configured", "chain intact", errors. */
export function Notice({ tone = 'accent', title, children, action, live }: {
  tone?: Exclude<Tone, 'neutral'>;
  title?: React.ReactNode;
  children?: React.ReactNode;
  action?: React.ReactNode;
  /** 'polite' for results that appear after a user action, 'assertive' for errors. */
  live?: 'polite' | 'assertive';
}) {
  const role = live === 'assertive' ? 'alert' : live === 'polite' ? 'status' : undefined;
  return (
    <div className={`ws-notice ws-notice--${tone}`} role={role}>
      <Icon name={NOTICE_ICON[tone]} size={18} className="ws-notice__icon" />
      <div className="ws-notice__text">
        {title && <p className="ws-notice__title">{title}</p>}
        {children && <div className="ws-notice__body">{children}</div>}
      </div>
      {action && <div className="ws-notice__action">{action}</div>}
    </div>
  );
}
