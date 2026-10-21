/* Data table with a caption, loading rows and an empty state.

   Below 768 px every row becomes a stacked card (`ws-table--stack`): the first column is the
   card's title, the other cells follow one per line with their column name before them (the
   `data-label` attribute, drawn by CSS), and the row's actions column is pinned to the card's
   top-right corner, so nothing hides behind sideways scrolling on a phone. The explicit table
   roles keep the table semantics that `display: block` would otherwise strip.

   From 768 px the table scrolls horizontally inside its own frame when it is wider than the page
   (the page itself never scrolls sideways), with the actions column sticky on the right so the
   row menu stays reachable. The caption names the table for screen readers even when it is
   visually hidden. When the frame really overflows it becomes a focusable, labelled region so
   keyboard users can scroll it too (WCAG 2.1.1); otherwise it adds no extra tab stop. While
   loading, skeleton rows keep the final height so nothing jumps. */
import React, { useEffect, useId, useRef, useState } from 'react';
import { Skeleton } from './display';

export interface Column<Row> {
  key: string;
  header: React.ReactNode;
  render: (row: Row) => React.ReactNode;
  align?: 'start' | 'end';
  /** Hidden below 720 px (secondary detail columns). */
  secondary?: boolean;
  width?: string;
  /** Header text for screen readers when the visible header is empty (an actions column). */
  srHeader?: string;
  /** Short values (a name, a date, a status) that must not wrap inside their cell. */
  nowrap?: boolean;
}

export interface TableProps<Row> {
  caption: string;
  captionVisible?: boolean;
  columns: Column<Row>[];
  rows: Row[] | null;
  rowKey: (row: Row) => string | number;
  loading?: boolean;
  empty: React.ReactNode;
  footer?: React.ReactNode;
  rowClassName?: (row: Row) => string | undefined;
  /** Stack rows as cards below 768 px (default); false keeps a scrolling table (dense numbers). */
  stack?: boolean;
}

/** The actions column (empty visible header, row menu) is recognised by its key. */
function isActions<Row>(col: Column<Row>): boolean {
  return col.key === 'actions';
}

function cellClass<Row>(col: Column<Row>, index: number): string | undefined {
  return [
    col.align === 'end' && 'is-end', col.secondary && 'is-secondary', col.nowrap && 'is-nowrap',
    isActions(col) && 'is-actions', index === 0 && 'is-primary',
  ].filter(Boolean).join(' ') || undefined;
}

/** The column name a stacked card shows before a cell's value (none for the title and actions). */
function cellLabel<Row>(col: Column<Row>, index: number): string | undefined {
  if (index === 0 || isActions(col)) return undefined;
  return typeof col.header === 'string' && col.header ? col.header : undefined;
}

/** True while the element is wider inside than outside; re-measured on resize and content change. */
function useOverflowX(ref: React.RefObject<HTMLElement | null>, deps: unknown[]): boolean {
  const [overflowing, setOverflowing] = useState(false);
  useEffect(() => {
    const measure = () => {
      const node = ref.current;
      setOverflowing(Boolean(node && node.scrollWidth > node.clientWidth + 1));
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
    // `deps` are the table contents: a new row set can change the width.
  }, deps);
  return overflowing;
}

export function Table<Row>({ caption, captionVisible = false, columns, rows, rowKey, loading = false, empty, footer, rowClassName, stack = true }: TableProps<Row>) {
  const showSkeleton = loading && (!rows || rows.length === 0);
  const showEmpty = !loading && rows !== null && rows.length === 0;
  const scroller = useRef<HTMLDivElement>(null);
  const captionId = `t${useId().replace(/:/g, '')}`;
  const scrollable = useOverflowX(scroller, [rows, loading, columns.length]);
  return (
    <div className="ws-table-frame">
      <div
        ref={scroller}
        className="ws-table-scroll"
        {...(scrollable ? { tabIndex: 0, role: 'region', 'aria-labelledby': captionId } : {})}
      >
        <table className={['ws-table', stack && 'ws-table--stack'].filter(Boolean).join(' ')} role="table" aria-busy={loading || undefined}>
          <caption id={captionId} className={captionVisible ? 'ws-table__caption' : 'ws-sr-only'}>{caption}</caption>
          <thead role="rowgroup">
            <tr role="row">
              {columns.map((col, index) => (
                <th
                  key={col.key} scope="col" role="columnheader" style={col.width ? { width: col.width } : undefined}
                  className={cellClass(col, index)}
                >
                  {col.header}
                  {col.srHeader && <span className="ws-sr-only">{col.srHeader}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody role="rowgroup">
            {showSkeleton && Array.from({ length: 4 }, (_, i) => (
              <tr key={`sk${i}`} role="row" aria-hidden="true">
                {columns.map((col, index) => (
                  <td key={col.key} role="cell" className={cellClass(col, index)}><Skeleton width={col.align === 'end' ? 48 : '70%'} /></td>
                ))}
              </tr>
            ))}
            {!showSkeleton && rows?.map((row) => (
              <tr key={rowKey(row)} role="row" className={rowClassName?.(row)}>
                {columns.map((col, index) => (
                  <td key={col.key} role="cell" className={cellClass(col, index)} data-label={cellLabel(col, index)}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {showEmpty && <div className="ws-table__empty">{empty}</div>}
      {footer && <div className="ws-table__footer">{footer}</div>}
    </div>
  );
}
