// @ts-nocheck
/* HUD-v3 Phase D — the native Neural Mesh canvas (mesh.tsx, the v3-mesh.jsx port that
   replaces the /brain iframe). This proves the WIRING: it mounts without throwing, renders
   the .nmesh wrapper + canvas + legend, builds its node graph from the agents prop, and
   runs a draw frame against a stubbed 2D context. Visual fidelity is owner-verified (CDX-9);
   this is the headless safety net (no crash, lifecycle clean, data-driven build). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, act, fireEvent } from '@testing-library/react';
import { deriveMeshModels, NeuralMesh } from '../mesh';

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

const EMPTY_LLM = { state: 'no_model', model: null, residents: [] };
const NO_SOURCES = { tasks: false, trust: false };

describe('NeuralMesh — the native canvas brain mounts + draws without throwing', () => {
  it('renders the wrapper, canvas and legend', () => {
    const { container } = render(<NeuralMesh agents={AGENTS} activeId="jarvis" onSelect={() => {}} motion="lively" t={{}} />);
    expect(container.querySelector('.nmesh')).toBeTruthy();
    expect(container.querySelector('.nmesh canvas')).toBeTruthy();
    expect(container.querySelector('.nmesh-legend')).toBeTruthy();
  });

  it('defensively surfaces only running tasks in the active mesh legend', () => {
    const { container } = render(<NeuralMesh agents={AGENTS} tasks={TASKS} sources={{ tasks: true, trust: false }} activeId="jarvis" onSelect={() => {}} motion="lively" t={{}} />);
    expect(container.querySelector('.nmesh-legend')?.textContent).toContain('1 running task');
    expect(container.querySelector('.nmesh-legend')?.textContent).toContain('live telemetry');
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

  it('derives zero live models without evidence and stable provider/id nodes with current trust', () => {
    expect(deriveMeshModels({
      demo: false, residents: [], trustEvidence: false, trust: null,
    })).toEqual([]);
    expect(deriveMeshModels({
      demo: false,
      residents: [
        { provider: 'lm-studio', id: 'a' },
        { provider: 'ollama', id: 'b' },
      ],
      trustEvidence: true,
      trust: { claude_available: true, cloud_available: true },
    }).map((model) => model.key)).toEqual(['lm-studio:a', 'ollama:b', 'cloud:claude']);
    expect(deriveMeshModels({
      demo: false,
      residents: [{ provider: 'lm-studio', id: 'same' }, { provider: 'ollama', id: 'same' }],
      trustEvidence: false,
      trust: { claude_available: true },
    }).map((model) => model.key)).toEqual(['lm-studio:same', 'ollama:same']);
  });

  it('labels every proven resident model and no demo model in live mode', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    render(<NeuralMesh agents={AGENTS} activeId="jarvis" onSelect={() => {}} motion="lively"
      llm={{ state: 'ready', model: 'minimax/minimax-m2.7', residents: [
        { provider: 'lm-studio', id: 'minimax/minimax-m2.7' },
        { provider: 'ollama', id: 'qwen:7b' },
      ] }} trust={{}} sources={NO_SOURCES} demo={false} t={{}} />);
    act(() => { rafCb(0); });
    const labels = ctx.fillText.mock.calls.map((c) => String(c[0]));
    expect(labels.some((l) => l.includes('MINIMAX-M2.7'))).toBe(true);
    expect(labels.some((l) => l.includes('QWEN:7B'))).toBe(true);
    expect(labels.some((l) => l.includes('GEMMA-4-26B'))).toBe(false);
  });

  it('keeps the cinematic default model constellation in demo mode (badged)', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    render(<NeuralMesh agents={AGENTS} activeId="jarvis" onSelect={() => {}} motion="lively"
      llm={{ state: 'ready', model: 'minimax/minimax-m2.7' }} trust={{}} demo={true} t={{}} />);
    act(() => { rafCb(0); });
    const labels = ctx.fillText.mock.calls.map((c) => String(c[0]));
    expect(labels.some((l) => l.includes('GEMMA-4-26B'))).toBe(true);    // demo constellation intact
  });

  it('draws five task dots per owner and at most three labels plus a +N summary', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    const manyTasks = Array.from({ length: 10 }, (_, i) => ({
      id: i, owner: 'howard', title: `retry attempt ${i}`, status: 'running',
    }));
    render(<NeuralMesh agents={AGENTS} tasks={manyTasks} sources={{ tasks: true, trust: false }} activeId="howard" onSelect={() => {}} motion="lively" llm={EMPTY_LLM} t={{}} />);
    act(() => { rafCb(0); });
    const taskDots = ctx.arc.mock.calls.filter((call) => call[2] === 4.6);
    const labels = ctx.fillText.mock.calls.map((call) => String(call[0]));
    expect(taskDots).toHaveLength(5);
    expect(labels.filter((label) => label.startsWith('RETRY ATTEMPT'))).toEqual([
      'RETRY ATTEMPT 0', 'RETRY ATTEMPT 1', 'RETRY ATTEMPT 2',
    ]);
    expect(labels).toContain('+7 MORE');
  });

  it('treats only busy/active agents as executing and removes live random cascades', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    const random = vi.spyOn(Math, 'random');
    const agents = [
      { id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'ready' },
      { id: 'ready-agent', name: 'Ready Agent', tier: 'FND', status: 'ready' },
      { id: 'busy-agent', name: 'Busy Agent', tier: 'BUS', status: 'busy' },
    ];
    render(<NeuralMesh agents={agents} activeId="jarvis" onSelect={() => {}} motion="lively" llm={EMPTY_LLM} sources={NO_SOURCES} demo={false} t={{}} />);
    random.mockClear();
    act(() => {
      for (let i = 0; i < 500; i += 1) rafCb(i);
    });
    const labels = ctx.fillText.mock.calls.map((call) => String(call[0]));
    expect(labels).toContain('BUSY AGENT');
    expect(labels).not.toContain('READY AGENT');
    expect(random).not.toHaveBeenCalled();
  });

  it('uses truthful model tooltips and explicit legend provenance', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    const { container, rerender } = render(<NeuralMesh agents={[AGENTS[0]]} activeId="jarvis" onSelect={() => {}} motion="calm"
      llm={{ state: 'ready', model: 'alpha', residents: [{ provider: 'lm-studio', id: 'alpha' }] }}
      trust={{}} sources={NO_SOURCES} demo={false} t={{}} />);
    act(() => { rafCb(0); });
    fireEvent.mouseMove(container.querySelector('.nmesh'), { clientX: 320, clientY: 138 });
    expect(container.querySelector('.nmesh-tip')?.textContent).toContain('local model · loaded');
    expect(container.querySelector('.nmesh-legend')?.textContent).toContain('no live activity');

    rerender(<NeuralMesh agents={[AGENTS[0]]} activeId="jarvis" onSelect={() => {}} motion="calm"
      llm={EMPTY_LLM} trust={{}} sources={NO_SOURCES} demo={true} t={{}} />);
    expect(container.querySelector('.nmesh-legend')?.textContent).toContain('demo');
  });
});
