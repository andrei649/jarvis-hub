import React from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Attention } from '../signals/types';
import { AreaNav, noteCount } from './AreaNav';

afterEach(() => { history.replaceState(null, '', '/'); });

/* The notes' three forms (long, short, the count alone) are switched by frame.css: by width, and
   by the masthead's fit steps "notes" and "hand" (Masthead.tsx). Whatever form is drawn, the
   link's name and its tooltip keep the words. */
describe('AreaNav — a note shortened keeps its words', () => {
  const attention: Attention = {
    docket: { key: 'docket', count: 12 },
    services: { key: 'services', count: 4 },
    record: { key: 'record', brokenAt: 412 },
  };

  it('draws a problem note as its mark and count, a broken record as its mark alone, the words in the name and the tooltip', () => {
    render(<AreaNav current={null} lang="en" attention={attention} navigate={vi.fn()} />);
    const observe = screen.getByRole('link', { name: 'Observe — 4 services down' });
    expect(observe.getAttribute('title')).toBe('Observe — 4 services down');
    const services = observe.querySelector('[data-note="services"]') as HTMLElement;
    expect(services.querySelector('[data-mark="problem"]')?.getAttribute('aria-hidden')).toBe('true');
    expect(services.querySelector('.n-areas__count')?.textContent).toBe('4');

    const trust = screen.getByRole('link', { name: 'Trust — record broken at entry 412' });
    expect(trust.getAttribute('title')).toBe('Trust — record broken at entry 412');
    const record = trust.querySelector('[data-note="record"]') as HTMLElement;
    expect([...record.querySelectorAll('.n-areas__words')].map((el) => el.textContent)).toEqual(['record broken at entry 412', 'record broken']);
    // no count to draw: shortened, the note is its mark alone
    expect(record.querySelector('.n-areas__count')).toBeNull();
    expect(record.querySelector('[data-mark="problem"]')).not.toBeNull();

    // the owner's hand keeps the accent in every form
    const work = screen.getByRole('link', { name: 'Work — 12 need you' });
    const docket = work.querySelector('[data-note="docket"]') as HTMLElement;
    expect(docket.classList.contains('n-areas__note--hand')).toBe(true);
    expect(docket.querySelector('.n-areas__count')?.textContent).toBe('12');
  });

  it('shortens payments waiting to their count, in Romanian too', () => {
    render(<AreaNav current={null} lang="ro" attention={{ payments: { key: 'payments', count: 3 } }} navigate={vi.fn()} />);
    const trust = screen.getByRole('link', { name: 'Încredere — 3 așteaptă' });
    expect(trust.getAttribute('title')).toBe('Încredere — 3 așteaptă');
    const note = trust.querySelector('[data-note="payments"]') as HTMLElement;
    expect(note.classList.contains('n-areas__note--hand')).toBe(true);
    expect([...note.querySelectorAll('.n-areas__words')].map((el) => el.textContent)).toEqual(['3 așteaptă', '3 așteaptă']);
    expect(note.querySelector('.n-areas__count')?.textContent).toBe('3');
  });

  it('draws no note, no count and no tooltip where the attention model has nothing to say', () => {
    render(<AreaNav current={null} lang="en" attention={{}} navigate={vi.fn()} />);
    for (const link of screen.getAllByRole('link')) {
      expect(link.querySelector('[data-note], .n-areas__count')).toBeNull();
      expect(link.hasAttribute('title')).toBe(false);
      expect(link.hasAttribute('aria-label')).toBe(false);
    }
  });

  it('counts only what a note counts', () => {
    expect(noteCount({ key: 'docket', count: 9 })).toBe('9');
    expect(noteCount({ key: 'payments', count: 1 })).toBe('1');
    expect(noteCount({ key: 'services', count: 12 })).toBe('12');
    expect(noteCount({ key: 'record', brokenAt: 412 })).toBeNull();
    expect(noteCount({ key: 'record', brokenAt: null })).toBeNull();
    expect(noteCount({ key: 'killSwitch', state: 'armed' })).toBeNull();
  });
});
