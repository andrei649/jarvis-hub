/* Toasts: short confirmations ("Saved", "Link copied") and non-blocking failures.

   Two live regions exist from the first render (a region injected later is often not
   announced): a polite one for success/info and an assertive one for errors. Toasts dismiss
   themselves after a few seconds — errors stay longer — and pause while hovered or focused so a
   slow reader is not cut off. The regions are portalled to <body>, outside the app root, so
   they stay announced and clickable while a modal dialog makes the page behind it inert. */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '../i18n';
import { Icon, type IconName } from './icons';

export type ToastTone = 'success' | 'info' | 'error';

interface ToastItem { id: number; tone: ToastTone; text: string }

export interface ToastApi {
  success(text: string): void;
  info(text: string): void;
  error(text: string): void;
}

const ToastContext = createContext<ToastApi | null>(null);
const DURATION: Record<ToastTone, number> = { success: 4000, info: 5000, error: 8000 };
const ICON: Record<ToastTone, IconName> = { success: 'checkCircle', info: 'info', error: 'alert' };

function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  const { t } = useI18n();
  const [paused, setPaused] = useState(false);
  const remaining = useRef(DURATION[item.tone]);
  useEffect(() => {
    if (paused) return undefined;
    const started = Date.now();
    const timer = window.setTimeout(() => onDismiss(item.id), remaining.current);
    return () => { window.clearTimeout(timer); remaining.current -= Date.now() - started; };
  }, [paused, item.id, onDismiss]);
  return (
    <div
      className={`ws-toast ws-toast--${item.tone}`}
      onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}
    >
      <Icon name={ICON[item.tone]} size={18} />
      <p className="ws-toast__text">{item.text}</p>
      <button type="button" className="ws-toast__close" onClick={() => onDismiss(item.id)} aria-label={t('common.dismiss')}>
        <Icon name="close" size={16} />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const dismiss = useCallback((id: number) => setItems((list) => list.filter((x) => x.id !== id)), []);
  const push = useCallback((tone: ToastTone, text: string) => {
    if (!text) return;
    const id = nextId.current++;
    setItems((list) => [...list.slice(-3), { id, tone, text }]);
  }, []);
  const api = useMemo<ToastApi>(() => ({
    success: (text) => push('success', text),
    info: (text) => push('info', text),
    error: (text) => push('error', text),
  }), [push]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(<div className="ws-toasts">
        <div role="status" aria-live="polite" className="ws-toasts__region">
          {items.filter((x) => x.tone !== 'error').map((x) => <Toast key={x.id} item={x} onDismiss={dismiss} />)}
        </div>
        <div role="alert" aria-live="assertive" className="ws-toasts__region">
          {items.filter((x) => x.tone === 'error').map((x) => <Toast key={x.id} item={x} onDismiss={dismiss} />)}
        </div>
      </div>, document.body)}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast outside ToastProvider');
  return ctx;
}
