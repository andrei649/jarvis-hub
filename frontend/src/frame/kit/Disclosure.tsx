/* Disclosure: a control that opens a small popover with the detail behind a reading — its
   basis, the time it was checked, a caveat (§4.2: every running-head item has one).
   The WAI-ARIA disclosure pattern: a button with aria-expanded / aria-controls; click or
   Enter / Space toggles; Escape closes and returns focus to the button; a press elsewhere
   closes. `title` gives the same hint on hover. Not modal: focus is never trapped.

   `contain` keeps the open popover inside the window (`placeInside`): it opens below its button,
   or above it where below would leave the window and above leaves less of it out (the running
   head in Glance's foot, at the bottom of the screen), and it moves in from a side edge it would
   cross. Measured when it opens and when the window is resized while it is open, before the paint. */
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import './kit.css';

export interface DisclosureProps {
  /** The button's content (a running-head item's mark and words). */
  label: React.ReactNode;
  /** The detail. */
  children: React.ReactNode;
  /** A hover hint (title attribute). */
  title?: string;
  /** The button's accessible name when its content is not enough. */
  ariaLabel?: string;
  /** Open the popover towards the start (default) or the end edge. */
  align?: 'start' | 'end';
  /** Keep the open popover inside the window (above the button, or moved in from an edge, as needed). */
  contain?: boolean;
  className?: string;
  buttonClassName?: string;
  panelClassName?: string;
  onOpenChange?: (open: boolean) => void;
}

/** The margin a contained popover keeps from the window's edges, in px. */
const EDGE = 4;

/** Places an open popover inside the window: below its button unless that leaves the window and
 *  above leaves less of it out (data-place="above"), then moved sideways by the least that keeps it
 *  inside (--n-disclosure-shift, a translation: nothing else moves). Where the window has no size
 *  (no layout), it leaves the popover as its stylesheet places it. */
export function placeInside(panel: HTMLElement): void {
  unplace(panel);
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  if (!(vw > 0 && vh > 0)) return;
  const below = panel.getBoundingClientRect();
  if (!(below.width > 0 && below.height > 0)) return;
  let r = below;
  if (below.bottom > vh - EDGE) {
    panel.setAttribute('data-place', 'above');
    const above = panel.getBoundingClientRect();
    if (EDGE - above.top > 0 && EDGE - above.top >= below.bottom - (vh - EDGE)) panel.removeAttribute('data-place');
    else r = above;
  }
  let shift = 0;
  if (r.right > vw - EDGE) shift = vw - EDGE - r.right;
  if (r.left + shift < EDGE) shift = EDGE - r.left;
  if (Math.abs(shift) >= 0.5) {
    panel.style.setProperty('--n-disclosure-shift', `${Math.round(shift)}px`);
    panel.setAttribute('data-shift', '');
  }
}

/** The popover as its stylesheet places it (below its button, at its own edge): what `placeInside`
 *  wrote, undone. The running head's approval mode places its own popover and confirmation with the
 *  pair (RunningHead.tsx), as the stylesheet then draws them (frame.css). */
export function unplace(panel: HTMLElement): void {
  panel.removeAttribute('data-place');
  panel.removeAttribute('data-shift');
  panel.style.removeProperty('--n-disclosure-shift');
}

export function Disclosure({ label, children, title, ariaLabel, align = 'start', contain = false, className, buttonClassName, panelClassName, onOpenChange }: DisclosureProps) {
  const [open, setOpen] = useState(false);
  const auto = useId();
  const panelId = `n-disclosure-${auto.replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const change = useRef(onOpenChange);
  change.current = onOpenChange;
  const set = (next: boolean) => { setOpen(next); change.current?.(next); };

  useEffect(() => {
    if (!open) return undefined;
    const away = (event: MouseEvent) => {
      if (root.current && event.target instanceof Node && !root.current.contains(event.target)) { setOpen(false); change.current?.(false); }
    };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);

  useLayoutEffect(() => {
    const el = panel.current;
    if (!open || !contain || !el) return undefined;
    const place = () => placeInside(el);
    place();
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('resize', place);
      unplace(el);
    };
  }, [open, contain]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== 'Escape' || !open) return;
    event.preventDefault();
    event.stopPropagation();   // the Escape is this popover's, not an overlay's beneath it
    set(false);
    button.current?.focus();
  };

  return (
    <div ref={root} className={['n-disclosure', align === 'end' ? 'n-disclosure--end' : '', className].filter(Boolean).join(' ')} onKeyDown={onKeyDown}>
      <button ref={button} type="button" className={['n-disclosure__button', buttonClassName].filter(Boolean).join(' ')}
        aria-expanded={open} aria-controls={panelId} title={title} aria-label={ariaLabel} onClick={() => set(!open)}>
        {label}
      </button>
      <div ref={panel} id={panelId} className={['n-disclosure__panel', panelClassName].filter(Boolean).join(' ')} hidden={!open}>
        {children}
      </div>
    </div>
  );
}
