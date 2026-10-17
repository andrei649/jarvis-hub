/* Menu (WAI-ARIA menu button) and Popover (a non-modal disclosure panel).

   Menu: the trigger opens with click, Enter, Space or ArrowDown; arrows, Home and End move
   between items; Escape closes and returns focus to the trigger; Tab closes and lets focus move
   on; choosing an item closes the menu. Radio items (language, theme) announce their checked
   state. Popover hosts richer content (the notifications list, the model status): focus moves
   into it on open and back to the trigger on Escape; clicking outside closes both. */
import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Icon, type IconName } from './icons';
import { focusableWithin } from './focus';

export interface TriggerProps {
  ref: React.Ref<HTMLButtonElement>;
  'aria-haspopup': 'menu' | 'dialog';
  'aria-expanded': boolean;
  'aria-controls': string;
  onClick: () => void;
  onKeyDown: (event: React.KeyboardEvent) => void;
}

export interface MenuAction {
  kind?: 'item';
  id: string;
  label: string;
  icon?: IconName;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

export interface MenuRadio { kind: 'radio'; id: string; label: string; checked: boolean; onSelect: () => void }
export interface MenuGroup { kind: 'group'; id: string; label: string; items: MenuRadio[] }
export interface MenuSeparator { kind: 'separator'; id: string }
export type MenuEntry = MenuAction | MenuGroup | MenuSeparator;

function useOutsideClose(open: boolean, wrapper: React.RefObject<HTMLElement | null>, close: () => void): void {
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event: MouseEvent) => {
      if (wrapper.current && !wrapper.current.contains(event.target as Node)) close();
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open, wrapper, close]);
}

export interface MenuProps {
  /** Accessible name of the menu itself. */
  label: string;
  trigger: (props: TriggerProps) => React.ReactNode;
  items: MenuEntry[];
  align?: 'start' | 'end';
  className?: string;
}

export function Menu({ label, trigger, items, align = 'end', className }: MenuProps) {
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = `m${useId().replace(/:/g, '')}`;
  const focusOnOpen = useRef<'first' | 'last'>('first');

  const close = useCallback((returnFocus = true) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }, []);
  const closeQuietly = useCallback(() => setOpen(false), []);
  useOutsideClose(open, wrapper, closeQuietly);

  const menuItems = () => Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not([disabled])') ?? []);

  useEffect(() => {
    if (!open) return;
    const list = menuItems();
    (focusOnOpen.current === 'last' ? list[list.length - 1] : list[0])?.focus();
  }, [open]);

  const onTriggerKey = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      focusOnOpen.current = event.key === 'ArrowUp' ? 'last' : 'first';
      setOpen(true);
    }
  };

  const onMenuKey = (event: React.KeyboardEvent) => {
    const list = menuItems();
    const index = list.indexOf(document.activeElement as HTMLElement);
    const move = (next: number) => { event.preventDefault(); list[(next + list.length) % list.length]?.focus(); };
    if (event.key === 'ArrowDown') move(index + 1);
    else if (event.key === 'ArrowUp') move(index - 1);
    else if (event.key === 'Home') move(0);
    else if (event.key === 'End') move(list.length - 1);
    else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
    else if (event.key === 'Tab') close(false);
  };

  const choose = (onSelect: () => void) => { close(); onSelect(); };

  const renderEntry = (entry: MenuEntry) => {
    if (entry.kind === 'separator') return <div key={entry.id} role="separator" className="ws-menu__sep" />;
    if (entry.kind === 'group') {
      return (
        <div key={entry.id} role="group" aria-labelledby={`${menuId}-${entry.id}`} className="ws-menu__group">
          <div id={`${menuId}-${entry.id}`} className="ws-menu__group-label">{entry.label}</div>
          {entry.items.map((radio) => (
            <button
              key={radio.id} type="button" role="menuitemradio" aria-checked={radio.checked} tabIndex={-1}
              className="ws-menu__item" onClick={() => choose(radio.onSelect)}
            >
              <span className="ws-menu__check" aria-hidden="true">{radio.checked && <Icon name="check" size={16} />}</span>
              <span>{radio.label}</span>
            </button>
          ))}
        </div>
      );
    }
    return (
      <button
        key={entry.id} type="button" role="menuitem" tabIndex={-1} disabled={entry.disabled}
        className={['ws-menu__item', entry.danger && 'is-danger'].filter(Boolean).join(' ')}
        onClick={() => choose(entry.onSelect)}
      >
        {entry.icon ? <Icon name={entry.icon} size={16} /> : <span className="ws-menu__check" aria-hidden="true" />}
        <span>{entry.label}</span>
      </button>
    );
  };

  return (
    <div ref={wrapper} className={['ws-menu-wrap', className].filter(Boolean).join(' ')}>
      {trigger({
        ref: triggerRef,
        'aria-haspopup': 'menu',
        'aria-expanded': open,
        'aria-controls': menuId,
        onClick: () => { focusOnOpen.current = 'first'; setOpen((v) => !v); },
        onKeyDown: onTriggerKey,
      })}
      {open && (
        <div ref={menuRef} id={menuId} role="menu" aria-label={label} className={`ws-menu ws-menu--${align}`} onKeyDown={onMenuKey}>
          {items.map(renderEntry)}
        </div>
      )}
    </div>
  );
}

export interface PopoverProps {
  label: string;
  trigger: (props: TriggerProps) => React.ReactNode;
  children: (close: () => void) => React.ReactNode;
  align?: 'start' | 'end';
  className?: string;
  onOpenChange?: (open: boolean) => void;
}

export function Popover({ label, trigger, children, align = 'end', className, onOpenChange }: PopoverProps) {
  const [open, setOpenState] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = `p${useId().replace(/:/g, '')}`;
  const changeRef = useRef(onOpenChange);
  changeRef.current = onOpenChange;

  const setOpen = useCallback((next: boolean) => {
    setOpenState(next);
    changeRef.current?.(next);
  }, []);
  const close = useCallback(() => { setOpen(false); triggerRef.current?.focus(); }, [setOpen]);
  const closeQuietly = useCallback(() => setOpen(false), [setOpen]);
  useOutsideClose(open, wrapper, closeQuietly);

  useEffect(() => {
    if (!open || !panelRef.current) return;
    (focusableWithin(panelRef.current)[0] ?? panelRef.current).focus();
  }, [open]);

  return (
    <div
      ref={wrapper}
      className={['ws-menu-wrap', className].filter(Boolean).join(' ')}
      onBlur={(event) => { if (open && !wrapper.current?.contains(event.relatedTarget as Node | null) && event.relatedTarget) closeQuietly(); }}
    >
      {trigger({
        ref: triggerRef,
        'aria-haspopup': 'dialog',
        'aria-expanded': open,
        'aria-controls': panelId,
        onClick: () => setOpen(!open),
        onKeyDown: () => undefined,
      })}
      {open && (
        <div
          ref={panelRef} id={panelId} role="dialog" aria-label={label} tabIndex={-1}
          className={`ws-popover ws-popover--${align}`}
          onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); } }}
        >
          {children(close)}
        </div>
      )}
    </div>
  );
}
