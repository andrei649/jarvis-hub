/* Buttons. A busy button keeps its width (the label stays, a spinner overlays it) so a pending
   save never shifts the layout, and it reports `aria-busy` while ignoring repeat clicks. */
import React, { forwardRef } from 'react';
import { Icon, type IconName } from './icons';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-ghost';
export type ButtonSize = 'sm' | 'md';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: IconName;
  iconAfter?: IconName;
  busy?: boolean;
  block?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon, iconAfter, busy = false, block = false, className, children, disabled, type, onClick, ...rest },
  ref,
) {
  const classes = ['ws-btn', `ws-btn--${variant}`, `ws-btn--${size}`, block && 'ws-btn--block', busy && 'is-busy', className]
    .filter(Boolean).join(' ');
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={classes}
      disabled={disabled}
      aria-busy={busy || undefined}
      aria-disabled={busy || undefined}
      onClick={(event) => { if (busy) { event.preventDefault(); return; } onClick?.(event); }}
      {...rest}
    >
      <span className="ws-btn__content">
        {icon && <Icon name={icon} size={size === 'sm' ? 16 : 18} />}
        {children && <span className="ws-btn__label">{children}</span>}
        {iconAfter && <Icon name={iconAfter} size={size === 'sm' ? 16 : 18} />}
      </span>
      {busy && <span className="ws-btn__spinner" aria-hidden="true" />}
    </button>
  );
});

export interface IconButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  icon: IconName;
  /** Required: an icon-only control must have an accessible name (also shown as a tooltip). */
  label: string;
  variant?: 'ghost' | 'secondary' | 'danger-ghost';
  size?: ButtonSize;
  badge?: React.ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, variant = 'ghost', size = 'md', badge, className, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={['ws-icon-btn', `ws-icon-btn--${variant}`, `ws-icon-btn--${size}`, className].filter(Boolean).join(' ')}
      aria-label={label}
      title={label}
      {...rest}
    >
      <Icon name={icon} size={size === 'sm' ? 16 : 18} />
      {badge}
    </button>
  );
});
