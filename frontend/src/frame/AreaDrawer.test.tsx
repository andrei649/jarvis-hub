/* The areas below 760px (PHASE_B_PLAN.md §4.1): a modal sheet of the nine areas that keeps the
   focus inside it, closes on Escape, its backdrop or its close button, and gives the focus back
   to the button that opened it (the legacy RailDrawer's behaviour). */
import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { areaById } from '../nav/areas';
import { AreaDrawer } from './AreaDrawer';

beforeEach(() => { history.replaceState(null, '', '/v2/trust?frame=ledger'); });

function openDrawer(lang: 'en' | 'ro' = 'en') {
  const navigate = vi.fn();
  render(<AreaDrawer current={areaById('trust') ?? null} lang={lang} attention={{}} navigate={navigate} />);
  const opener = screen.getByRole('button', { name: lang === 'en' ? 'Open the areas menu' : 'Deschide meniul zonelor' });
  opener.focus();
  fireEvent.click(opener);
  return { opener, dialog: screen.getByRole('dialog'), navigate };
}

describe('AreaDrawer', () => {
  it('opens a modal sheet of the nine areas, the focus inside it and the current area marked', () => {
    const { opener, dialog } = openDrawer();
    expect(opener.getAttribute('aria-expanded')).toBe('true');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(dialog.getAttribute('aria-label')).toBe('Areas');
    const links = within(dialog).getAllByRole('link');
    expect(links).toHaveLength(9);
    expect(links.filter((a) => a.getAttribute('aria-current') === 'page').map((a) => a.textContent)).toEqual(['Trust']);
    expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: 'Close the areas menu' }));
  });

  it('keeps Tab inside: past the last control to the first, before the first to the last', () => {
    const { dialog } = openDrawer();
    const close = within(dialog).getByRole('button', { name: 'Close the areas menu' });
    const links = within(dialog).getAllByRole('link');
    const last = links[links.length - 1];
    last.focus();
    fireEvent.keyDown(last, { key: 'Tab' });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it('closes on Escape and gives the focus back to its opener', () => {
    const { opener } = openDrawer();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(opener.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(opener);
  });

  it('closes from its backdrop and from its close button, the focus back on the opener each time', () => {
    const { opener } = openDrawer();
    fireEvent.click(screen.getByTestId('area-drawer-backdrop'));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
    fireEvent.click(opener);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close the areas menu' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('goes to the chosen area and closes', () => {
    const { dialog, navigate } = openDrawer();
    fireEvent.click(within(dialog).getByRole('link', { name: 'Build' }));
    expect(navigate).toHaveBeenCalledWith('/v2/build');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('speaks Romanian', () => {
    const { dialog } = openDrawer('ro');
    expect(dialog.getAttribute('aria-label')).toBe('Zone');
    expect(within(dialog).getByRole('button', { name: 'Închide meniul zonelor' })).toBeTruthy();
    expect(within(dialog).getAllByRole('link').map((a) => a.textContent)).toContain('Încredere');
  });
});
