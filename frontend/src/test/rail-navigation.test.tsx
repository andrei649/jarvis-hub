// @ts-nocheck
/* H132 — the mode rail and tabs navigate and mark the active mode; the owner can collapse or
   expand the rail (remembered); at phone width the rail is a drawer over a backdrop; a page
   puts its toolbar in the page header, which is cleared when the mode changes. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import React, { useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MODES, Rail, RailDrawer, Tabs, RAIL_PREF_KEY, useRailCollapsed } from '../shell';
import { PageHeaderBar, PageHeaderProvider, usePageHeader } from '../page-header';

const T = Object.fromEntries(MODES.filter((m) => !m.sep).map((m) => [m.tkey, `L-${m.id}`]));

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('Rail navigation', () => {
  it('navigates on click and marks only the active mode', () => {
    const setMode = vi.fn();
    const { container } = render(<Rail mode="memory" setMode={setMode} t={T} />);
    const active = container.querySelectorAll('.rail-btn.active');
    expect(active).toHaveLength(1);
    expect(active[0].getAttribute('data-anchor')).toBe('mode.memory');
    expect(active[0].getAttribute('aria-current')).toBe('page');
    expect(container.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    fireEvent.click(container.querySelector('[data-anchor="mode.trust"]'));
    expect(setMode).toHaveBeenCalledWith('trust');
    // one button per mode, separators are not buttons
    expect(container.querySelectorAll('.rail-btn')).toHaveLength(MODES.filter((m) => !m.sep).length);
  });

  it('collapses and expands, and remembers the choice', () => {
    function Harness() {
      const [collapsed, toggle] = useRailCollapsed();
      return <Rail mode="cockpit" setMode={() => {}} t={T} collapsed={collapsed} onToggle={toggle} />;
    }
    const { container, unmount } = render(<Harness />);
    const rail = () => container.querySelector('.rail');
    expect(rail().getAttribute('data-collapsed')).toBe('true');
    fireEvent.click(screen.getByLabelText('expand the rail'));
    expect(rail().getAttribute('data-collapsed')).toBe('false');
    expect(screen.getByLabelText('collapse the rail').getAttribute('aria-expanded')).toBe('true');
    expect(localStorage.getItem(RAIL_PREF_KEY)).toBe('expanded');
    unmount();
    const again = render(<Harness />);
    expect(again.container.querySelector('.rail').getAttribute('data-collapsed')).toBe('false');
  });

  it('has no toggle when the caller gives none (the drawer)', () => {
    render(<Rail mode="cockpit" setMode={() => {}} t={T} />);
    expect(screen.queryByLabelText('expand the rail')).toBeNull();
  });
});

describe('Tabs navigation', () => {
  it('navigates and marks the active tab', () => {
    const setMode = vi.fn();
    const { container } = render(<Tabs mode="chat" setMode={setMode} t={T} />);
    const active = container.querySelectorAll('.tab-btn.active');
    expect(active).toHaveLength(1);
    expect(active[0].textContent).toContain('L-chat');
    fireEvent.click(screen.getByText('L-agents'));
    expect(setMode).toHaveBeenCalledWith('agents');
  });
});

describe('RailDrawer (phone width)', () => {
  it('opens over a backdrop and closes on a choice, the backdrop or Escape', () => {
    const setMode = vi.fn();
    render(<RailDrawer mode="cockpit" setMode={setMode} t={T} />);
    const menu = screen.getByLabelText('open the modes menu');
    expect(screen.queryByRole('dialog')).toBeNull();

    fireEvent.click(menu);
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(menu.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(screen.getByText('L-memory'));
    expect(setMode).toHaveBeenCalledWith('memory');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(menu);

    fireEvent.click(menu);
    fireEvent.click(screen.getByTestId('rail-backdrop'));
    expect(screen.queryByRole('dialog')).toBeNull();

    fireEvent.click(menu);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();

    fireEvent.click(menu);
    fireEvent.click(screen.getByLabelText('close the modes menu'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows the drawer rail expanded (labels beside icons)', () => {
    const { container } = render(<RailDrawer mode="cockpit" setMode={() => {}} t={T} />);
    fireEvent.click(screen.getByLabelText('open the modes menu'));
    expect(container.querySelector('.rail-drawer .rail').getAttribute('data-collapsed')).toBe('false');
  });
});

describe('page-header slot', () => {
  function PageA() { usePageHeader(<button>action A</button>); return <div>page A</div>; }
  function PageB() { return <div>page B</div>; }
  function PageC() { usePageHeader(<button>action C</button>); return <div>page C</div>; }
  function Shell() {
    const [mode, setMode] = useState('a');
    return (
      <>
        <button onClick={() => setMode('a')}>go a</button>
        <button onClick={() => setMode('b')}>go b</button>
        <button onClick={() => setMode('c')}>go c</button>
        <PageHeaderProvider routeKey={mode}>
          <PageHeaderBar title={`title ${mode}`} />
          {mode === 'a' ? <PageA /> : mode === 'b' ? <PageB /> : <PageC />}
        </PageHeaderProvider>
      </>
    );
  }

  it('shows the page toolbar beside the title and clears it on a mode change', () => {
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

  it('does nothing outside a provider (a panel in the Console overlay)', () => {
    render(<PageA />);
    expect(screen.getByText('page A')).toBeTruthy();
    expect(screen.queryByText('action A')).toBeNull();
  });
});
