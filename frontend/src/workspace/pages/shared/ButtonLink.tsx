/* Links that look like buttons. Navigation and downloads stay real anchors (open in a new
   tab, "save link as", a visible URL on hover) instead of buttons that call navigate(). */
import React from 'react';
import { Link } from '../../router';
import { Icon, type IconName } from '../../ui';

interface LinkLook {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md';
  icon?: IconName;
  className?: string;
  children: React.ReactNode;
}

function classes({ variant = 'secondary', size = 'md', className }: LinkLook): string {
  return ['ws-btn', `ws-btn--${variant}`, `ws-btn--${size}`, className].filter(Boolean).join(' ');
}

function Content({ icon, size = 'md', children }: Pick<LinkLook, 'icon' | 'size' | 'children'>) {
  return (
    <span className="ws-btn__content">
      {icon && <Icon name={icon} size={size === 'sm' ? 16 : 18} />}
      <span className="ws-btn__label">{children}</span>
    </span>
  );
}

/** An in-app link (see router.tsx Link) styled as a button. */
export function ButtonLink({ to, onClick, ...look }: LinkLook & { to: string; onClick?: () => void }) {
  return <Link to={to} className={classes(look)} onClick={onClick}><Content {...look} /></Link>;
}

/** A download of a server attachment (the session cookie rides along) styled as a button. */
export function DownloadLink({ href, ...look }: LinkLook & { href: string }) {
  return <a href={href} download className={classes(look)}><Content {...look} /></a>;
}
