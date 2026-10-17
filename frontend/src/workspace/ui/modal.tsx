/* Modal surfaces: Dialog, ConfirmDialog and Drawer share one ModalLayer.

   What the layer guarantees (spec §10 quality bar): focus moves into the surface when it opens,
   Tab and Shift+Tab cycle inside it, Escape closes the topmost surface only, the page behind is
   made inert and stops scrolling, and focus returns to the control that opened it. Surfaces
   stack (a confirm dialog over a drawer), so a module-level stack decides who owns the keys. */
import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '../i18n';
import { useErrorText } from '../app/errors';
import { Button, IconButton } from './Button';
import { focusableWithin } from './focus';

const stack: symbol[] = [];

function setBackgroundInert(inert: boolean): void {
  const root = document.getElementById('root');
  if (!root) return;
  if (inert) root.setAttribute('inert', '');
  else root.removeAttribute('inert');
  document.body.classList.toggle('ws-modal-open', inert);
}

interface ModalLayerProps {
  open: boolean;
  onClose: () => void;
  /** When false, Escape and the backdrop do nothing (e.g. while a save is in flight). */
  dismissible?: boolean;
  labelledBy: string;
  describedBy?: string;
  initialFocus?: React.RefObject<HTMLElement | null>;
  variant: 'dialog' | 'drawer-left' | 'drawer-right';
  size?: 'sm' | 'md' | 'lg';
  role?: 'dialog' | 'alertdialog';
  children: React.ReactNode;
}

function ModalLayer({ open, onClose, dismissible = true, labelledBy, describedBy, initialFocus, variant, size = 'md', role = 'dialog', children }: ModalLayerProps) {
  const surface = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  const dismissRef = useRef(dismissible);
  closeRef.current = onClose;
  dismissRef.current = dismissible;

  useEffect(() => {
    if (!open) return undefined;
    const token = Symbol('modal');
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    stack.push(token);
    setBackgroundInert(true);
    const node = surface.current;
    const target = initialFocus?.current
      ?? node?.querySelector<HTMLElement>('[data-autofocus]')
      ?? (node ? focusableWithin(node).find((el) => !el.dataset.modalClose) : undefined)
      ?? node;
    target?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (stack[stack.length - 1] !== token || !node) return;
      if (event.key === 'Escape') {
        event.stopPropagation();
        if (dismissRef.current) closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusableWithin(node);
      if (items.length === 0) { event.preventDefault(); node.focus(); return; }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !node.contains(active))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (active === last || !node.contains(active))) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      const index = stack.indexOf(token);
      if (index >= 0) stack.splice(index, 1);
      if (stack.length === 0) setBackgroundInert(false);
      if (opener && opener.isConnected) opener.focus();
    };
  }, [open, initialFocus]);

  if (!open) return null;
  return createPortal(
    <div className={`ws-layer ws-layer--${variant}`}>
      <div className="ws-layer__backdrop" aria-hidden="true" onMouseDown={() => { if (dismissRef.current) closeRef.current(); }} />
      <div
        ref={surface}
        className={`ws-surface ws-surface--${variant} ws-surface--${size}`}
        role={role}
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        tabIndex={-1}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  size?: 'sm' | 'md' | 'lg';
  busy?: boolean;
  initialFocus?: React.RefObject<HTMLElement | null>;
  role?: 'dialog' | 'alertdialog';
}

export function Dialog({ open, onClose, title, description, children, footer, size = 'md', busy = false, initialFocus, role }: DialogProps) {
  const { t } = useI18n();
  const id = useId().replace(/:/g, '');
  return (
    <ModalLayer
      open={open} onClose={onClose} dismissible={!busy} labelledBy={`${id}-title`}
      describedBy={description ? `${id}-desc` : undefined} initialFocus={initialFocus} variant="dialog" size={size} role={role}
    >
      <header className="ws-surface__header">
        <div>
          <h2 id={`${id}-title`} className="ws-surface__title">{title}</h2>
          {description && <p id={`${id}-desc`} className="ws-surface__desc">{description}</p>}
        </div>
        <IconButton icon="close" label={t('common.close')} onClick={onClose} disabled={busy} data-modal-close="true" />
      </header>
      {children && <div className="ws-surface__body">{children}</div>}
      {footer && <footer className="ws-surface__footer">{footer}</footer>}
    </ModalLayer>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  body: React.ReactNode;
  confirmLabel: string;
  tone?: 'danger' | 'primary';
  /** May reject with a WorkspaceApiError; the translated reason is shown inside the dialog. */
  onConfirm: () => Promise<void> | void;
}

export function ConfirmDialog({ open, onClose, title, body, confirmLabel, tone = 'danger', onConfirm }: ConfirmDialogProps) {
  const { t } = useI18n();
  const errorText = useErrorText();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => { if (open) { setError(null); setBusy(false); } }, [open]);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      setBusy(false);
      onClose();
    } catch (err) {
      setBusy(false);
      setError(errorText(err));
    }
  };

  return (
    <Dialog
      open={open} onClose={onClose} title={title} size="sm" busy={busy} role="alertdialog" initialFocus={cancelRef}
      footer={(
        <>
          <Button ref={cancelRef} onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant={tone === 'danger' ? 'danger' : 'primary'} busy={busy} onClick={confirm}>{confirmLabel}</Button>
        </>
      )}
    >
      <div className="ws-confirm__body">{body}</div>
      {error && <p className="ws-inline-error" role="alert">{error}</p>}
    </Dialog>
  );
}

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  side?: 'left' | 'right';
  children: React.ReactNode;
  footer?: React.ReactNode;
  busy?: boolean;
  /** Hide the visible header (the title stays as the accessible name). */
  bare?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

export function Drawer({ open, onClose, title, side = 'right', children, footer, busy = false, bare = false, size = 'md' }: DrawerProps) {
  const { t } = useI18n();
  const id = useId().replace(/:/g, '');
  return (
    <ModalLayer open={open} onClose={onClose} dismissible={!busy} labelledBy={`${id}-title`} variant={side === 'left' ? 'drawer-left' : 'drawer-right'} size={size}>
      <header className={['ws-surface__header', bare && 'ws-sr-only'].filter(Boolean).join(' ')}>
        <h2 id={`${id}-title`} className="ws-surface__title">{title}</h2>
        {!bare && <IconButton icon="close" label={t('common.close')} onClick={onClose} disabled={busy} data-modal-close="true" />}
      </header>
      <div className="ws-surface__body ws-surface__body--scroll">{children}</div>
      {footer && <footer className="ws-surface__footer">{footer}</footer>}
    </ModalLayer>
  );
}
