// @ts-nocheck
/* H309 — the model points at the HUD: a tip rings one element and captions it; a tour pages. */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import React from 'react';
import { render, screen, cleanup, fireEvent, act } from '@testing-library/react';

vi.mock('../api/client', () => ({ apiGet: vi.fn() }));
import { apiGet } from '../api/client';
import {
  POINTER_ANCHORS, POINTER_TTL_SECONDS, POLL_MS, PointerOverlay, PointerView, anchorRect, currentPointer, readPointer,
} from '../pointer';

const NOW = 1_800_000_000;
const tip = (over = {}) => ({ id: 't1', type: 'tip', agent: 'jarvis', created_at: NOW - 5,
  payload: { target: 'console', caption: 'Open tools here', untrusted: false }, ...over });
const tour = (over = {}) => ({ id: 'r1', type: 'tour', agent: 'nerva', created_at: NOW - 5,
  payload: { title: 'Getting around', steps: [{ target: 'composer', caption: 'Type here' }, { target: 'mode.memory', caption: 'Memory' }] }, ...over });

function anchor(name, rect = { left: 100, top: 50, width: 80, height: 20, right: 180, bottom: 70 }) {
  const el = document.createElement('button');
  el.setAttribute('data-anchor', name);
  el.getBoundingClientRect = () => ({ ...rect, x: rect.left, y: rect.top, toJSON: () => rect });
  document.body.appendChild(el);
  return el;
}

beforeEach(() => { cleanup(); document.body.innerHTML = ''; sessionStorage.clear(); vi.mocked(apiGet).mockReset(); });

describe('reading pointers', () => {
  it('reads a tip and a tour and nothing else', () => {
    expect(readPointer(tip())).toEqual({ id: 't1', kind: 'tip', title: '', steps: [{ target: 'console', caption: 'Open tools here' }], untrusted: false, agent: 'jarvis' });
    expect(readPointer(tour()).steps.map((s) => s.target)).toEqual(['composer', 'mode.memory']);
    expect(readPointer(tip({ payload: { target: 'console', caption: 'x', untrusted: true } })).untrusted).toBe(true);
    expect(readPointer(tip({ agent: 5 })).agent).toBe('agent');
    for (const bad of [
      null, 'x', { type: 'tip' }, tip({ id: 3 }), tip({ type: 'text' }),
      tip({ payload: { target: 'approve', caption: 'x' } }), tip({ payload: { target: 'console', caption: '' } }),
      tip({ payload: null }), tour({ payload: { steps: [] } }), tour({ payload: { steps: 'x' } }),
      tour({ payload: { steps: [{ target: 'console', caption: 'ok' }, { target: 'nope', caption: 'x' }] } }),
    ]) expect(readPointer(bad)).toBeNull();
  });

  it('takes the newest live one the viewer has not closed', () => {
    const els = [tip({ id: 'new' }), tour({ id: 'old' })];
    expect(currentPointer(els, [], NOW).id).toBe('new');
    expect(currentPointer(els, ['new'], NOW).id).toBe('old');
    expect(currentPointer([tip({ created_at: NOW - POINTER_TTL_SECONDS - 1 })], [], NOW)).toBeNull();
    expect(currentPointer([tip({ created_at: NOW - POINTER_TTL_SECONDS })], [], NOW).id).toBe('t1');
    expect(currentPointer([tip({ created_at: 'x' })], [], NOW)).toBeNull();
    expect(currentPointer([{ id: 'x', type: 'text', created_at: NOW }, tip()], [], NOW).id).toBe('t1');
    expect(currentPointer(null, [], NOW)).toBeNull();
    expect(POINTER_TTL_SECONDS).toBe(600);
  });

  it('finds only named anchors that are on screen', () => {
    anchor('console');
    anchor('composer', { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 });
    expect(anchorRect('console').left).toBe(100);
    expect(anchorRect('composer')).toBeNull();       // hidden: no box
    expect(anchorRect('decisions')).toBeNull();      // not rendered
    anchor('approve');                               // on screen, with a box
    expect(anchorRect('approve')).toBeNull();        // not a named place
    expect(POINTER_ANCHORS).toContain('decisions');
  });
});

describe('the pointer', () => {
  it('rings the element and captions it', () => {
    anchor('console');
    const onClose = vi.fn();
    render(<PointerView pointer={readPointer(tip())} onClose={onClose} />);
    const ring = screen.getByTestId('pointer-ring');
    expect(ring.style.left).toBe('96px');
    expect(ring.style.width).toBe('88px');
    const dialog = screen.getByRole('dialog', { name: 'Tip' });
    expect(dialog.textContent).toContain('Open tools here');
    expect(dialog.textContent).toContain('from jarvis');
    expect(dialog.style.top).toBe('82px');
    expect(screen.queryByText(/not on this screen/)).toBeNull();
    expect(screen.queryByRole('note')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('says so when the target is not on this screen, and when an untrusted turn wrote it', () => {
    render(<PointerView pointer={readPointer(tip({ payload: { target: 'decisions', caption: 'Look', untrusted: true } }))} onClose={() => {}} />);
    expect(screen.queryByTestId('pointer-ring')).toBeNull();
    expect(screen.getByText('(not on this screen: decisions)')).toBeTruthy();
    expect(screen.getByRole('note').textContent).toContain('untrusted turn');
  });

  it('pages a tour with Back, Next and Done', () => {
    anchor('composer');
    const onClose = vi.fn();
    render(<PointerView pointer={readPointer(tour())} onClose={onClose} />);
    const dialog = screen.getByRole('dialog', { name: 'Tour: Getting around' });
    expect(dialog.textContent).toContain('GETTING AROUND · 1/2');
    expect(dialog.textContent).toContain('Type here');
    expect(screen.getByRole('button', { name: 'Back' }).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(dialog.textContent).toContain('2/2');
    expect(dialog.textContent).toContain('Memory');
    expect(screen.getByText('(not on this screen: mode.memory)')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(dialog.textContent).toContain('1/2');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('a new tour starts at its first step', () => {
    const view = render(<PointerView pointer={readPointer(tour())} onClose={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('dialog').textContent).toContain('2/2');
    view.rerender(<PointerView pointer={readPointer(tour({ id: 'r2' }))} onClose={() => {}} />);
    expect(screen.getByRole('dialog').textContent).toContain('1/2');
  });

  it('flips above an element near the bottom of the window', () => {
    anchor('console', { left: 900, top: window.innerHeight - 30, width: 80, height: 20, right: 980, bottom: window.innerHeight - 10 });
    render(<PointerView pointer={readPointer(tip())} onClose={() => {}} />);
    const dialog = screen.getByRole('dialog', { name: 'Tip' });
    expect(dialog.style.top).toBe(`${window.innerHeight - 30 - 132}px`);
    expect(Number.parseFloat(dialog.style.left)).toBeLessThanOrEqual(window.innerWidth - 328);
  });
});

describe('the overlay', () => {
  it('polls the canvas, shows the newest tip and remembers a close for this page', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW * 1000);
    try {
      vi.mocked(apiGet).mockResolvedValue({ elements: [tip()] });
      const view = render(<PointerOverlay />);
      await act(async () => { await Promise.resolve(); });
      expect(apiGet).toHaveBeenCalledWith('/api/canvas');
      expect(screen.getByRole('dialog', { name: 'Tip' })).toBeTruthy();
      fireEvent.click(screen.getByRole('button', { name: 'Close' }));
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(JSON.parse(sessionStorage.getItem('hud.pointer.closed'))).toEqual(['t1']);
      vi.mocked(apiGet).mockResolvedValue({ elements: [tip({ id: 't2', payload: { target: 'console', caption: 'Second' } }), tip()] });
      await act(async () => { vi.advanceTimersByTime(POLL_MS); await Promise.resolve(); });
      expect(screen.getByRole('dialog', { name: 'Tip' }).textContent).toContain('Second');
      view.unmount();
      render(<PointerOverlay />);
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByRole('dialog').textContent).toContain('Second');   // t1 stays closed
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows nothing when off, on a failed read, or with nothing live', async () => {
    vi.mocked(apiGet).mockResolvedValue({ elements: [tip()] });
    render(<PointerOverlay enabled={false} />);
    await act(async () => { await Promise.resolve(); });
    expect(apiGet).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();
    cleanup();
    vi.mocked(apiGet).mockRejectedValue(new Error('down'));
    render(<PointerOverlay />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByRole('dialog')).toBeNull();
    cleanup();
    vi.mocked(apiGet).mockResolvedValue({ nope: 1 });
    render(<PointerOverlay />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
