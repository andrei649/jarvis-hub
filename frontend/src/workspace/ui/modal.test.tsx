import React, { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { I18nProvider } from '../i18n';
import { Dialog } from './modal';
import { Menu } from './Menu';

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <I18nProvider>
      <button type="button" onClick={() => setOpen(true)}>Deschide</button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Titlu" footer={<button type="button">Ultimul</button>}>
        <input aria-label="Primul" />
      </Dialog>
    </I18nProvider>
  );
}

describe('Dialog', () => {
  it('moves focus in, traps Tab both ways, closes on Escape and returns focus to the opener', () => {
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Deschide' });
    opener.focus();
    fireEvent.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'Titlu' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(screen.getByLabelText('Primul'));

    screen.getByRole('button', { name: 'Ultimul' }).focus();
    fireEvent.keyDown(document.activeElement as Element, { key: 'Tab' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Închide' }));
    fireEvent.keyDown(document.activeElement as Element, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Ultimul' }));

    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});

describe('Menu', () => {
  it('opens from the keyboard, moves with arrows and returns focus on Escape', () => {
    const chosen: string[] = [];
    render(
      <Menu
        label="Cont"
        items={[{ id: 'a', label: 'Profil', onSelect: () => chosen.push('a') }, { id: 'b', label: 'Ieșire', onSelect: () => chosen.push('b') }]}
        trigger={(props) => <button type="button" {...props}>Meniu</button>}
      />,
    );
    const trigger = screen.getByRole('button', { name: 'Meniu' });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: 'Profil' }));
    fireEvent.keyDown(document.activeElement as Element, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: 'Ieșire' }));
    fireEvent.keyDown(document.activeElement as Element, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: 'Profil' }));
    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('menuitem', { name: 'Ieșire' }));
    expect(chosen).toEqual(['b']);
    expect(document.activeElement).toBe(trigger);
  });
});
