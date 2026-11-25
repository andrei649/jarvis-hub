// @ts-nocheck
/* H132 — a page puts its toolbar in the page header, which is cleared when the page changes.
   The frame's AreaPage draws the header (frame/AreaPage.tsx: PageHeaderBar beside the page title,
   keyed on the page); Jobs is the page that uses it. Moved here from the rail tests when the HUD v2
   rail was deleted (PHASE_B_PLAN.md §8.2 row 17). */
import { describe, expect, it } from 'vitest';
import React, { useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { PageHeaderBar, PageHeaderProvider, usePageHeader } from '../page-header';

describe('page-header slot', () => {
  function PageA() { usePageHeader(<button>action A</button>); return <div>page A</div>; }
  function PageB() { return <div>page B</div>; }
  function PageC() { usePageHeader(<button>action C</button>); return <div>page C</div>; }
  function Shell() {
    const [page, setPage] = useState('a');
    return (
      <>
        <button onClick={() => setPage('a')}>go a</button>
        <button onClick={() => setPage('b')}>go b</button>
        <button onClick={() => setPage('c')}>go c</button>
        <PageHeaderProvider routeKey={page}>
          <PageHeaderBar title={`title ${page}`} />
          {page === 'a' ? <PageA /> : page === 'b' ? <PageB /> : <PageC />}
        </PageHeaderProvider>
      </>
    );
  }

  it('shows the page toolbar beside the title and clears it on a page change', () => {
    render(<Shell />);
    expect(screen.getByText('action A')).toBeTruthy();
    expect(screen.getByText('title a')).toBeTruthy();
    expect(screen.getByRole('toolbar', { name: 'page actions' })).toBeTruthy();
    act(() => { fireEvent.click(screen.getByText('go b')); });
    expect(screen.queryByText('action A')).toBeNull();
    expect(screen.queryByRole('toolbar')).toBeNull();     // a page without actions: no bar
    act(() => { fireEvent.click(screen.getByText('go c')); });
    expect(screen.getByText('action C')).toBeTruthy();
    expect(screen.getByText('title c')).toBeTruthy();
    act(() => { fireEvent.click(screen.getByText('go a')); });
    expect(screen.queryByText('action C')).toBeNull();
    expect(screen.getByText('action A')).toBeTruthy();
  });

  it('does nothing outside a provider (a panel drawn outside a page)', () => {
    render(<PageA />);
    expect(screen.getByText('page A')).toBeTruthy();
    expect(screen.queryByText('action A')).toBeNull();
  });
});
