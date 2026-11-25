/* The areas as a drawer, below 760px (PHASE_B_PLAN.md §4.1). An "Areas" button opens a modal
   dialog with the nine areas; choosing one, the backdrop, Escape or the close button shuts it,
   and focus returns to the button (the behaviour of the legacy RailDrawer). The button is shown
   only at the narrowest width (frame.css), where the docked AreaNav is hidden. */
import React, { useEffect, useRef, useState } from 'react';
import type { Area } from '../nav/areas';
import type { Attention } from '../signals/types';
import { AreaNav } from './AreaNav';
import { MASTHEAD_STRINGS } from './frame-strings';
import { pick, type Lang } from './strings';

/** A modal sheet keeps Tab inside itself: past the last control it wraps to the first. */
function keepFocusInside(event: React.KeyboardEvent<HTMLElement>) {
  if (event.key !== 'Tab') return;
  const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not([disabled])'));
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

export interface AreaDrawerProps {
  current: Area | null;
  lang: Lang;
  attention: Attention;
  navigate: (path: string) => void;
}

export function AreaDrawer({ current, lang, attention, navigate }: AreaDrawerProps) {
  const s = pick(MASTHEAD_STRINGS, lang);
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const closer = useRef<HTMLButtonElement>(null);
  const close = () => { setOpen(false); opener.current?.focus(); };
  useEffect(() => {
    if (!open) return undefined;
    closer.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpen(false);
      opener.current?.focus();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);
  return (
    <div className="n-areadrawer" data-show-upto="xxs">
      <button ref={opener} type="button" className="n-masthead__tool n-areadrawer__open" aria-haspopup="dialog" aria-expanded={open}
        aria-label={s.drawerOpen} onClick={() => setOpen(true)}>
        <svg className="n-masthead__icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M2.5 4h11M2.5 8h11M2.5 12h11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <span>{s.drawerButton}</span>
      </button>
      {open && (
        <div className="n-areadrawer__root">
          <div className="n-areadrawer__backdrop" data-testid="area-drawer-backdrop" onClick={close} />
          <div className="n-areadrawer__sheet" role="dialog" aria-modal="true" aria-label={s.areas} onKeyDown={keepFocusInside}>
            <button ref={closer} type="button" className="n-masthead__tool n-areadrawer__close" aria-label={s.drawerClose} onClick={close}>
              <svg className="n-masthead__icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
            <AreaNav current={current} lang={lang} attention={attention} navigate={navigate} onNavigate={() => setOpen(false)}
              className="n-areas--drawer" />
          </div>
        </div>
      )}
    </div>
  );
}
