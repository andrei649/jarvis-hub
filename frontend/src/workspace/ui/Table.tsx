/* Data table with a caption, loading rows and an empty state.

   The table scrolls horizontally inside its own frame on narrow screens (the page itself never
   scrolls sideways), and the caption names the table for screen readers even when it is
   visually hidden. While loading, skeleton rows keep the final height so nothing jumps. */
import React from 'react';
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
}

export function Table<Row>({ caption, captionVisible = false, columns, rows, rowKey, loading = false, empty, footer, rowClassName }: TableProps<Row>) {
  const showSkeleton = loading && (!rows || rows.length === 0);
  const showEmpty = !loading && rows !== null && rows.length === 0;
  return (
    <div className="ws-table-frame">
      <div className="ws-table-scroll">
        <table className="ws-table" aria-busy={loading || undefined}>
          <caption className={captionVisible ? 'ws-table__caption' : 'ws-sr-only'}>{caption}</caption>
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key} scope="col" style={col.width ? { width: col.width } : undefined}
                  className={[col.align === 'end' && 'is-end', col.secondary && 'is-secondary'].filter(Boolean).join(' ') || undefined}
                >
                  {col.header}
                  {col.srHeader && <span className="ws-sr-only">{col.srHeader}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {showSkeleton && Array.from({ length: 4 }, (_, i) => (
              <tr key={`sk${i}`} aria-hidden="true">
                {columns.map((col) => (
                  <td key={col.key} className={col.secondary ? 'is-secondary' : undefined}><Skeleton width={col.align === 'end' ? 48 : '70%'} /></td>
                ))}
              </tr>
            ))}
            {!showSkeleton && rows?.map((row) => (
              <tr key={rowKey(row)} className={rowClassName?.(row)}>
                {columns.map((col) => (
                  <td key={col.key} className={[col.align === 'end' && 'is-end', col.secondary && 'is-secondary'].filter(Boolean).join(' ') || undefined}>
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
