// @ts-nocheck
/* HUD-v3 Phase D — the native Neural Mesh canvas (mesh.tsx, the v3-mesh.jsx port that
   replaces the /brain iframe). This proves the WIRING: it mounts without throwing, renders
   the .nmesh wrapper + canvas + legend, builds its node graph from the agents prop, and
   runs a draw frame against a stubbed 2D context. Visual fidelity is owner-verified (CDX-9);
   this is the headless safety net (no crash, lifecycle clean, data-driven build). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, act } from '@testing-library/react';
import { NeuralMesh } from '../mesh';

// jsdom has no 2D canvas — stub getContext with the methods the mesh draws with, so the
// RAF draw loop exercises real code instead of being skipped by the null-context guard.
function stubCtx() {
  const grad = { addColorStop: vi.fn() };
  return {
    setTransform: vi.fn(), fillRect: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(),
    stroke: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), fillText: vi.fn(),
    createRadialGradient: vi.fn(() => grad),
    globalCompositeOperation: '', globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '',
  };
}

let rafCb;   // capture the RAF callback so a test can run exactly ONE frame by hand
beforeEach(() => {
  rafCb = null;
  HTMLCanvasElement.prototype.getContext = vi.fn(() => stubCtx());
  // capture (don't auto-invoke) — the loop re-schedules itself, so auto-invoke would recurse
  vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => { rafCb = cb; return 1; });
  vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); });

const AGENTS = [
  { id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'active' },
  { id: 'frigga', name: 'Frigga', tier: 'FND', status: 'idle' },
  { id: 'howard', name: 'Howard', tier: 'BUS', status: 'busy' },
];
const TASKS = [
  { id: 1, owner: 'howard', title: 'draft payment plan', status: 'blocked' },
  { id: 2, agent_id: 'frigga', title: 'sync family digest', state: 'running' },
];

describe('NeuralMesh — the native canvas brain mounts + draws without throwing', () => {
  it('renders the wrapper, canvas and legend', () => {
    const { container } = render(<NeuralMesh agents={AGENTS} activeId="jarvis" onSelect={() => {}} motion="lively" t={{}} />);
    expect(container.querySelector('.nmesh')).toBeTruthy();
    expect(container.querySelector('.nmesh canvas')).toBeTruthy();
    expect(container.querySelector('.nmesh-legend')).toBeTruthy();
  });

  it('surfaces live /tasks in the active mesh legend', () => {
    const { container } = render(<NeuralMesh agents={AGENTS} tasks={TASKS} activeId="jarvis" onSelect={() => {}} motion="lively" t={{}} />);
    expect(container.querySelector('.nmesh-legend')?.textContent).toContain('2 tasks');
  });

  it('acquires a 2D context and runs a draw frame (drives the stub)', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    render(<NeuralMesh agents={AGENTS} activeId="howard" onSelect={() => {}} motion="lively" t={{}} />);
    expect(rafCb).toBeTypeOf('function');          // the loop scheduled a frame
    act(() => { rafCb(0); });                       // run exactly one frame
    expect(ctx.setTransform).toHaveBeenCalled();   // draw() ran against the context
    expect(ctx.arc).toHaveBeenCalled();            // nodes/edges were drawn
  });

  it('degrades cleanly when the canvas has no 2D context (null-context guard)', () => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => null);
    render(<NeuralMesh agents={AGENTS} activeId="jarvis" onSelect={() => {}} motion="calm" t={{}} />);
    // running a frame must not throw even though getContext returns null
    expect(() => act(() => { rafCb && rafCb(0); })).not.toThrow();
  });

  // Real-world finding (2026-07-08 test-drive): a focused agent's task fan had no
  // render cap. Every task under the focused owner draws into a fixed-size arc
  // (44px radius, ~24deg span) regardless of count — with dozens of tasks (a
  // realistic outcome after hours of autonomy/heartbeat activity) the labels
  // overlap into an unreadable dense block. The fan must stay bounded no matter
  // how many tasks a single owner accumulates.
  it('caps the focused task fan so label count never grows unbounded', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    const manyTasks = Array.from({ length: 40 }, (_, i) => ({
      id: i, owner: 'howard', title: `retry attempt ${i}`, status: 'blocked',
    }));
    render(<NeuralMesh agents={AGENTS} tasks={manyTasks} activeId="howard" onSelect={() => {}} motion="lively" t={{}} />);
    act(() => { rafCb(0); });
    // one fillText per agent label (howard is focused) + up to the fan cap for
    // its tasks — never anywhere close to the full 40.
    expect(ctx.fillText.mock.calls.length).toBeLessThan(20);
  });
});
