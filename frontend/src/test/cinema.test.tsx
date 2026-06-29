// @ts-nocheck
/* HUD-v3 §4 — Cinema mode (CinemaMesh): a full-bleed Neural Mesh framed as a shareable
   demo. Reuses the canvas brain, so the 2D context is stubbed like mesh.test.tsx. Asserts
   the overlay chrome mounts, Esc/exit calls onExit, and — the honesty contract — that real
   figures are shown (live agent count, %-local) and the prototype's fabricated "87% /
   0 cloud leaks" are NOT present. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, fireEvent } from '@testing-library/react';
import { CinemaMesh } from '../shell';

beforeEach(() => {
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null);   // null-context: mesh draw-guard no-ops
  vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(() => 1);
  vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); });

const AGENTS = [
  { id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'active' },
  { id: 'frigga', name: 'Frigga', tier: 'FND', status: 'idle' },
  { id: 'howard', name: 'Howard', tier: 'BUS', status: 'busy' },
];

describe('CinemaMesh — full-bleed mesh demo overlay', () => {
  it('mounts the cinema chrome + the embedded mesh', () => {
    const { container } = render(<CinemaMesh agents={AGENTS} localPct={87} onExit={() => {}} t={{}} />);
    expect(container.querySelector('.cinema')).toBeTruthy();
    expect(container.querySelector('.cin-stage .nmesh')).toBeTruthy();   // the mesh is embedded
    expect(container.querySelector('.cin-exit')).toBeTruthy();
  });

  it('shows ONLY real figures (live count + %-local), never fabricated metrics', () => {
    const { container, queryByText } = render(<CinemaMesh agents={AGENTS} localPct={87} onExit={() => {}} t={{}} />);
    // 2 of 3 agents are non-idle → "2 agents live"; %-local is the real prop value
    expect(container.textContent).toContain('2');
    expect(container.textContent).toContain('87');
    // the prototype's fabricated lines must not appear
    expect(queryByText(/0 cloud leaks/i)).toBeNull();
    expect(queryByText(/EGRESS SEALED/i)).toBeNull();
  });

  it('omits %-local entirely when it is unknown (no fabricated split)', () => {
    const { container } = render(<CinemaMesh agents={AGENTS} localPct={null} onExit={() => {}} t={{}} />);
    expect(container.textContent).not.toContain('on-device');
  });

  it('Esc and the exit button both call onExit', () => {
    const onExit = vi.fn();
    const { container } = render(<CinemaMesh agents={AGENTS} localPct={50} onExit={onExit} t={{}} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(container.querySelector('.cin-exit'));
    expect(onExit).toHaveBeenCalledTimes(2);
  });
});
