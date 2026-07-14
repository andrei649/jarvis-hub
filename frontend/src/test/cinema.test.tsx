// @ts-nocheck
/* HUD-v3 §4 — Cinema mode (CinemaMesh): a full-bleed Neural Mesh framed as a shareable
   demo. Reuses the canvas brain, so the 2D context is stubbed like mesh.test.tsx. Asserts
   the overlay chrome mounts, Esc/exit calls onExit, and — the honesty contract — that real
   figures are shown (live agent count, %-local) and the prototype's fabricated "87% /
   0 cloud leaks" are NOT present. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, fireEvent, act } from '@testing-library/react';
import { CinemaMesh } from '../shell';

let cinemaRafCb: any = null;
beforeEach(() => {
  cinemaRafCb = null;
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null);   // null-context: mesh draw-guard no-ops
  vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => { cinemaRafCb = cb; return 1; });
  vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); });

const AGENTS = [
  { id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'active' },
  { id: 'frigga', name: 'Frigga', tier: 'FND', status: 'idle' },
  { id: 'howard', name: 'Howard', tier: 'BUS', status: 'busy' },
  { id: 'pepper', name: 'Pepper', tier: 'BUS', status: 'ready' },
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
    // Only active/busy execute; ready means available, not live work.
    expect(container.textContent).toContain('2 agents live');
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

  it('passes the same current model, trust, source, and task truth into its mesh', () => {
    const grad = { addColorStop: vi.fn() };
    const ctx: any = {
      setTransform: vi.fn(), fillRect: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(),
      stroke: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), fillText: vi.fn(),
      createRadialGradient: vi.fn(() => grad),
      globalCompositeOperation: '', globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '',
    };
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    const { container } = render(<CinemaMesh
      agents={AGENTS}
      tasks={[
        { id: 'run', owner: 'howard', state: 'running' },
        { id: 'old', owner: 'howard', state: 'done' },
      ]}
      llm={{ state: 'ready', model: 'local-a', residents: [{ provider: 'ollama', id: 'local-a' }] }}
      trust={{ claude_available: true, cloud_available: true }}
      sources={{ tasks: true, trust: true }}
      demo={false}
      localPct={87}
      onExit={() => {}}
      t={{}}
    />);
    act(() => { cinemaRafCb(0); });
    const labels = ctx.fillText.mock.calls.map((call) => String(call[0]));
    expect(labels).toContain('LOCAL-A');
    expect(labels).toContain('CLAUDE');
    expect(container.querySelector('.nmesh-legend')?.textContent).toContain('1 running task');
    expect(container.querySelector('.nmesh-legend')?.textContent).toContain('live telemetry');
  });
});
