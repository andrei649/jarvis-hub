/* TalkMenu: the composer's Attach and Options menus and a reply's More (PHASE_B_PLAN.md §5.3).

   The WAI-ARIA disclosure pattern, as frame/kit Disclosure draws it, with what a composer needs
   on top: the panel opens above its button (the composer sits at the foot of the register), it
   can be opened and closed by its owner (an item that hands off to a dialog closes it), and it
   stays MOUNTED while closed (`hidden`), so the controls inside keep their state and their refs
   (the document input, the board-result trigger, the skills panel). Escape closes it and returns
   focus to its button; a press elsewhere closes it, except a press inside a dialog (a review
   opened from the menu) or while `hold` is set (a flow started from it is still running and will
   return focus to its trigger). Not modal: focus is never trapped. */
import React, { useEffect, useId, useRef, useState } from 'react';

export interface TalkMenuProps {
  /** The button's visible content. */
  label: React.ReactNode;
  /** The button's accessible name, when the visible content is not enough. */
  ariaLabel?: string;
  /** The panel's accessible name (a group of controls). */
  menuLabel: string;
  /** Controlled: the owner keeps the open state. Leave both out for a self-contained menu. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Ignore presses elsewhere while true. */
  hold?: boolean;
  /** Open towards the end edge (a menu at the right of a bar). */
  align?: 'start' | 'end';
  /** The test hook: data-talk-menu="attach" | "options" | "more". */
  hook: string;
  className?: string;
  buttonClassName?: string;
  title?: string;
  buttonRef?: React.MutableRefObject<HTMLButtonElement | null>;
  children: React.ReactNode;
}

export function TalkMenu({ label, ariaLabel, menuLabel, open: controlled, onOpenChange, hold = false, align = 'start', hook,
  className, buttonClassName, title, buttonRef, children }: TalkMenuProps) {
  const [own, setOwn] = useState(false);
  const open = controlled ?? own;
  const auto = useId();
  const panelId = `n-tmenu-${auto.replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement | null>(null);
  const change = useRef(onOpenChange);
  change.current = onOpenChange;
  const set = (next: boolean) => { if (controlled === undefined) setOwn(next); change.current?.(next); };
  const setRef = useRef(set);
  setRef.current = set;

  useEffect(() => {
    if (!open || hold) return undefined;
    const away = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node) || !root.current || root.current.contains(target)) return;
      // a review or dialog opened from the menu: pressing inside it does not close the menu
      if (target instanceof Element && target.closest('dialog, [role="dialog"], [aria-modal="true"]')) return;
      setRef.current(false);
    };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open, hold]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== 'Escape' || !open) return;
    event.preventDefault();
    event.stopPropagation();   // this menu's Escape, not an overlay's beneath it
    set(false);
    button.current?.focus();
  };

  return (
    <div ref={root} className={['n-tmenu', align === 'end' ? 'n-tmenu--end' : '', className].filter(Boolean).join(' ')}
      data-talk-menu={hook} onKeyDown={onKeyDown}>
      <button ref={(node) => { button.current = node; if (buttonRef) buttonRef.current = node; }} type="button"
        className={buttonClassName} aria-expanded={open} aria-controls={panelId} aria-label={ariaLabel} title={title}
        onClick={() => set(!open)}>
        {label}
      </button>
      <div id={panelId} role="group" aria-label={menuLabel} className="n-tmenu__panel" hidden={!open}>
        {children}
      </div>
    </div>
  );
}
