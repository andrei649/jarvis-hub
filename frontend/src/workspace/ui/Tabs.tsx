/* In-page tabs (WAI-ARIA tabs with automatic activation): one tab stop for the whole list,
   arrows/Home/End move and select, the panel is labelled by its tab. Route-level sections (the
   admin area) use NavTabs instead — real links, so each section has a URL. */
import React, { useEffect, useId, useRef, useState } from 'react';
import { Link } from '../router';

export interface TabItem<V extends string> { value: V; label: React.ReactNode; badge?: React.ReactNode }

export interface TabsProps<V extends string> {
  label: string;
  items: TabItem<V>[];
  value: V;
  onChange: (value: V) => void;
  children: React.ReactNode;
}

export function Tabs<V extends string>({ label, items, value, onChange, children }: TabsProps<V>) {
  const base = useId().replace(/:/g, '');
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const index = Math.max(0, items.findIndex((item) => item.value === value));

  const onKey = (event: React.KeyboardEvent) => {
    const keys: Record<string, number> = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: items.length - 1 };
    if (!(event.key in keys)) return;
    event.preventDefault();
    const next = (keys[event.key] + items.length) % items.length;
    onChange(items[next].value);
    refs.current[next]?.focus();
  };

  return (
    <div className="ws-tabs">
      <div role="tablist" aria-label={label} className="ws-tabs__list" onKeyDown={onKey}>
        {items.map((item, i) => (
          <button
            key={item.value}
            ref={(el) => { refs.current[i] = el; }}
            type="button"
            role="tab"
            id={`${base}-tab-${item.value}`}
            aria-selected={i === index}
            aria-controls={`${base}-panel`}
            tabIndex={i === index ? 0 : -1}
            className="ws-tabs__tab"
            onClick={() => onChange(item.value)}
          >
            {item.label}
            {item.badge}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${base}-panel`} aria-labelledby={`${base}-tab-${items[index]?.value}`} className="ws-tabs__panel">
        {children}
      </div>
    </div>
  );
}

export interface NavTabItem { to: string; label: React.ReactNode; active: boolean }

/**
 * Section navigation styled as tabs; each entry is a link with `aria-current="page"`. On a
 * narrow screen the row scrolls sideways, so the current section is scrolled into view —
 * otherwise a phone opened on the last section shows only the first ones — and the edge with
 * more sections fades out, so a cut-off row reads as one that continues.
 */
export function NavTabs({ label, items }: { label: string; items: NavTabItem[] }) {
  const list = useRef<HTMLUListElement>(null);
  const activeTo = items.find((item) => item.active)?.to;
  const [more, setMore] = useState({ start: false, end: false });
  useEffect(() => {
    const row = list.current;
    if (!row) return undefined;
    const current = row.querySelector<HTMLElement>('[aria-current="page"]');
    if (current) {
      const rowBox = row.getBoundingClientRect();
      const box = current.getBoundingClientRect();
      row.scrollLeft += box.left - rowBox.left - (rowBox.width - box.width) / 2;
    }
    const measure = () => {
      const start = row.scrollLeft > 1;
      const end = row.scrollLeft + row.clientWidth < row.scrollWidth - 1;
      setMore((prev) => (prev.start === start && prev.end === end ? prev : { start, end }));
    };
    measure();
    row.addEventListener('scroll', measure, { passive: true });
    window.addEventListener('resize', measure);
    return () => { row.removeEventListener('scroll', measure); window.removeEventListener('resize', measure); };
  }, [activeTo]);
  return (
    <nav aria-label={label} className="ws-navtabs">
      <ul ref={list} className={['ws-navtabs__list', more.start && 'is-more-start', more.end && 'is-more-end'].filter(Boolean).join(' ')}>
        {items.map((item) => (
          <li key={item.to}>
            <Link to={item.to} className="ws-navtabs__tab" aria-current={item.active ? 'page' : undefined}>{item.label}</Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
