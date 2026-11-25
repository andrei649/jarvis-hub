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
import { toHexColor } from '../theme/apply';
import { invalidateRoleColours } from '../theme/canvas-colours';

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
  invalidateRoleColours();   // the role cache and its probe are module state: start each test clean
  HTMLCanvasElement.prototype.getContext = vi.fn(() => stubCtx());
  // capture (don't auto-invoke) — the loop re-schedules itself, so auto-invoke would recurse
  vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => { rafCb = cb; return 1; });
  vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  for (const name of ['data-look', 'data-scheme', 'style']) document.documentElement.removeAttribute(name);
  invalidateRoleColours();
});

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

  it('mount-captured resize callbacks rebuild from the latest roster and model inputs', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    const originalResizeObserver = globalThis.ResizeObserver;
    let resizeCb: any = null;
    globalThis.ResizeObserver = class {
      constructor(cb) { resizeCb = cb; }
      observe() {}
      unobserve() {}
      disconnect() {}
    } as any;
    const initialAgents = [{ id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'idle' }];
    const currentAgents = [...initialAgents, { id: 'new-agent', name: 'New Agent', tier: 'BUS', status: 'busy' }];
    const view = render(<NeuralMesh agents={initialAgents} activeId="jarvis" onSelect={() => {}} motion="lively"
      llm={EMPTY_LLM} sources={NO_SOURCES} demo={false} t={{}} />);
    try {
      view.rerender(<NeuralMesh agents={currentAgents} activeId="jarvis" onSelect={() => {}} motion="lively"
        llm={{ state: 'ready', model: 'live-model', residents: [{ provider: 'ollama', id: 'live-model' }] }}
        sources={NO_SOURCES} demo={false} t={{}} />);
      expect(resizeCb).toBeTypeOf('function');
      act(() => { resizeCb([], null); });
      ctx.fillText.mockClear();
      act(() => { rafCb(0); });
      const labels = ctx.fillText.mock.calls.map((call) => String(call[0]));
      expect(labels).toContain('NEW AGENT');
      expect(labels).toContain('LIVE-MODEL');
    } finally {
      view.unmount();
      if (originalResizeObserver) globalThis.ResizeObserver = originalResizeObserver;
      else delete (globalThis as any).ResizeObserver;
    }
  });

  it('mount-captured RAF callbacks honor a later reduced-motion change', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    const random = vi.spyOn(Math, 'random');
    const view = render(<NeuralMesh agents={AGENTS} activeId="jarvis" onSelect={() => {}} motion="lively"
      llm={EMPTY_LLM} sources={NO_SOURCES} demo={true} t={{}} />);
    view.rerender(<NeuralMesh agents={AGENTS} activeId="jarvis" onSelect={() => {}} motion="calm"
      llm={EMPTY_LLM} sources={NO_SOURCES} demo={true} t={{}} />);
    random.mockClear();

    act(() => {
      for (let i = 0; i < 500; i += 1) rafCb(i);
    });

    expect(random).not.toHaveBeenCalled();
  });

  it('uses only owner, agent_id, then agent before the Jarvis owner fallback', () => {
    const ctx = stubCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    const task = [{ id: 't1', assignee: 'howard', title: 'assignee only', state: 'running' }];
    const view = render(<NeuralMesh agents={AGENTS} tasks={task} activeId="howard" onSelect={() => {}} motion="calm"
      llm={EMPTY_LLM} sources={{ tasks: true, trust: false }} demo={false} t={{}} />);
    act(() => { rafCb(0); });
    expect(ctx.fillText.mock.calls.map((call) => String(call[0]))).not.toContain('ASSIGNEE ONLY');

    ctx.fillText.mockClear();
    view.rerender(<NeuralMesh agents={AGENTS} tasks={task} activeId="jarvis" onSelect={() => {}} motion="calm"
      llm={EMPTY_LLM} sources={{ tasks: true, trust: false }} demo={false} t={{}} />);
    act(() => { rafCb(1); });
    expect(ctx.fillText.mock.calls.map((call) => String(call[0]))).toContain('ASSIGNEE ONLY');
  });
});

/* ---- themes: the seven Nerva looks draw in roles, Classic exactly as HUD v2 ----------------
   jsdom has no canvas, so the roles are resolved through a one-pixel probe stub that paints like
   a browser (apply.ts's converter stands in for the browser's colour parser), and the mesh draws
   into a recording context that keeps every colour, font and composite operation it was given. */

// Role values as a theme file would declare them; --n-emph points at the ink, as in Ledger.
const ROLES = {
  '--n-bg': '#0e1210', '--n-panel-bg': 'transparent', '--n-sheet': '#151a17',
  '--n-text': '#e0e6dc', '--n-text-2': '#b4bcb0', '--n-text-3': '#929a8e',
  '--n-rule': '#262c28', '--n-rule-2': '#373e3a', '--n-emph': 'var(--n-text)',
  '--n-ok': '#88b894', '--n-warn': '#d6b679', '--n-info': '#93acc1', '--n-cloud': '#b1a3d6',
  '--n-fs-meta': '12px', '--n-font-label': '"Barlow", sans-serif', '--n-font-mono': '"JetBrains Mono", monospace',
  '--n-label-case': 'none', '--n-label-track': '0', '--n-label-weight': '400', '--n-w-reg': '400',
};
const hexRgb = (hex) => `rgb(${parseInt(hex.slice(1, 3), 16)}, ${parseInt(hex.slice(3, 5), 16)}, ${parseInt(hex.slice(5, 7), 16)})`;
const role = (name) => hexRgb(ROLES[name === '--n-emph' ? '--n-text' : name]);
const ROLE_COLOURS = new Set(['--n-bg', '--n-sheet', '--n-text', '--n-text-2', '--n-text-3', '--n-rule', '--n-rule-2',
  '--n-ok', '--n-warn', '--n-info', '--n-cloud'].map(role));

function setLook(look, scheme = 'dark', roles = ROLES) {
  const html = document.documentElement;
  html.setAttribute('data-look', look);
  html.setAttribute('data-scheme', scheme);
  for (const [name, value] of Object.entries(roles)) html.style.setProperty(name, value);
}

/** The probe: one pixel that parses and paints a colour as a browser would. */
function pixelContext() {
  let style = '#000000';
  let pixel = [0, 0, 0, 0];
  const ctx = {
    reads: 0,
    get fillStyle() { return style; },
    set fillStyle(value) {
      const text = String(value).trim();
      if (text === 'transparent') { style = 'rgba(0, 0, 0, 0)'; return; }
      const hex = toHexColor(text);
      if (hex) style = hex;
    },
    clearRect() { pixel = [0, 0, 0, 0]; },
    fillRect() {
      pixel = style.startsWith('#')
        ? [parseInt(style.slice(1, 3), 16), parseInt(style.slice(3, 5), 16), parseInt(style.slice(5, 7), 16), 255]
        : [0, 0, 0, 0];
    },
    getImageData() { ctx.reads += 1; return { data: Uint8ClampedArray.from(pixel) }; },
  };
  return ctx;
}

/** The drawing context, recording what every mark was drawn with. */
function recordingCtx() {
  const ctx: any = stubCtx();
  const log = { fillStyle: [], strokeStyle: [], font: [], globalCompositeOperation: [], letterSpacing: [] };
  for (const prop of Object.keys(log)) {
    let value = prop === 'letterSpacing' ? '0px' : ctx[prop];
    Object.defineProperty(ctx, prop, { get: () => value, set: (v) => { value = v; log[prop].push(v); }, enumerable: true });
  }
  ctx.log = log;
  ctx.texts = [];
  ctx.fills = [];
  ctx.strokes = [];
  ctx.marks = [];   // every fill and stroke with the radius of the arc it painted (null: a line)
  let radius = null;
  ctx.beginPath = vi.fn(() => { radius = null; });
  ctx.arc = vi.fn((_x, _y, r) => { radius = r; });
  ctx.fillText = vi.fn((text) => { ctx.texts.push({ text: String(text), fill: ctx.fillStyle, font: ctx.font, track: ctx.letterSpacing }); });
  ctx.fill = vi.fn(() => { ctx.fills.push(ctx.fillStyle); ctx.marks.push({ op: 'fill', style: ctx.fillStyle, r: radius }); });
  ctx.stroke = vi.fn(() => { ctx.strokes.push(ctx.strokeStyle); ctx.marks.push({ op: 'stroke', style: ctx.strokeStyle, r: radius }); });
  return ctx;
}

/** getContext: the 1×1 probe canvas gets the probe, the mesh canvas the recording context. */
function installCanvas() {
  const probe = pixelContext();
  const draw = recordingCtx();
  HTMLCanvasElement.prototype.getContext = function getContext(this: HTMLCanvasElement) {
    return this.width === 1 && this.height === 1 ? probe : draw;
  } as any;
  return { probe, draw };
}

const LIVE_MODEL = { state: 'ready', model: 'qwen:7b', residents: [{ provider: 'ollama', id: 'qwen:7b' }] };
const TRUST_CLOUD = { claude_available: true };
const LIVE_SOURCES = { tasks: true, trust: true };
function mesh(props: any = {}) {
  return <NeuralMesh agents={AGENTS} tasks={TASKS} activeId="frigga" onSelect={() => {}} motion="lively"
    llm={LIVE_MODEL} trust={TRUST_CLOUD} sources={LIVE_SOURCES} demo={false} t={{}} {...props} />;
}

describe('NeuralMesh — theme roles in the Nerva looks, HUD v2 literals in Classic', () => {
  it('draws a Nerva look in its roles: flat marks on the ground, no bloom, halo, starfield or additive glow', () => {
    setLook('ledger');
    const { probe, draw } = installCanvas();
    render(mesh());
    act(() => { rafCb(0); });

    expect(probe.reads).toBeGreaterThan(0);                              // the roles were resolved
    expect(draw.createRadialGradient).not.toHaveBeenCalled();            // no bloom, no node halos
    expect(draw.log.globalCompositeOperation).not.toContain('lighter');  // no additive blending
    expect(draw.log.fillStyle[0]).toBe(role('--n-bg'));                 // the ground, opaque, first
    expect(draw.fillRect).toHaveBeenCalledTimes(1);                      // no starfield, no bloom fill
    // every colour the frame drew with is a role colour: not one HUD v2 literal
    for (const colour of [...draw.log.fillStyle, ...draw.log.strokeStyle]) expect(ROLE_COLOURS.has(colour)).toBe(true);

    // core, ring and label in the ink; a busy agent in warn; a local model in ok, a cloud lane in cloud
    expect(draw.strokes).toContain(role('--n-text'));
    expect(draw.fills).toEqual(expect.arrayContaining([role('--n-text'), role('--n-warn'), role('--n-ok'), role('--n-cloud')]));
    expect(draw.texts).toContainEqual(expect.objectContaining({ text: 'JARVIS', fill: role('--n-text') }));
    // edges: active in the meta ink, dimmed (another agent focused) in the hairline
    expect(draw.strokes).toEqual(expect.arrayContaining([role('--n-text-3'), role('--n-rule')]));
  });

  it('sets Nerva labels in the label voice at 12px or more, and model names as identifiers', () => {
    setLook('ledger');
    const { draw } = installCanvas();
    render(mesh());
    act(() => { rafCb(0); });
    const labels = draw.texts.map((entry) => entry.text);
    expect(labels).toEqual(expect.arrayContaining(['JARVIS', 'Frigga', 'Howard', 'qwen:7b', 'claude']));
    expect(labels).not.toContain('FRIGGA');
    expect(draw.texts.find((entry) => entry.text === 'Frigga')).toMatchObject({ font: '400 12px "Barlow", sans-serif', fill: role('--n-text-2') });
    expect(draw.texts.find((entry) => entry.text === 'qwen:7b')).toMatchObject({ font: '400 12px "JetBrains Mono", monospace' });
    for (const font of draw.log.font) expect(Number(/(\d+(?:\.\d+)?)px/.exec(font)?.[1])).toBeGreaterThanOrEqual(12);
  });

  it('follows a theme that cases and tracks its labels, never an identifier', () => {
    setLook('presence', 'light', { ...ROLES, '--n-label-case': 'uppercase', '--n-label-track': '0.1em', '--n-fs-meta': '13px' });
    const { draw } = installCanvas();
    render(mesh());
    act(() => { rafCb(0); });
    expect(draw.texts.find((entry) => entry.text === 'FRIGGA')).toMatchObject({ font: '400 13px "Barlow", sans-serif', track: '1.30px' });
    expect(draw.texts.find((entry) => entry.text === 'qwen:7b')).toMatchObject({ track: '0px' });
  });

  it('draws the Nerva task fan as sheet marks ringed in their legend key, a quiet rule and titles in the voice', () => {
    setLook('ledger');
    const { draw } = installCanvas();
    const manyTasks = Array.from({ length: 10 }, (_, i) => ({ id: i, owner: 'howard', title: `retry attempt ${i}`, status: 'running' }));
    render(mesh({ tasks: manyTasks, activeId: 'howard' }));
    act(() => { rafCb(0); });
    const labels = draw.texts.map((entry) => entry.text);
    expect(labels.filter((label) => label.startsWith('retry attempt'))).toEqual(['retry attempt 0', 'retry attempt 1', 'retry attempt 2']);
    expect(labels).toContain('+7 more');
    expect(draw.texts.find((entry) => entry.text === 'retry attempt 0')).toMatchObject({ fill: role('--n-text') });
    expect(draw.arc.mock.calls.filter((call) => call[2] === 4.6)).toHaveLength(5);   // the same five marks
    // each task mark: a sheet fill ringed in --n-warn, the role .nm-dot.task keys "running task" in
    const taskMarks = draw.marks.filter((mark) => mark.r === 4.6);
    expect(taskMarks.filter((mark) => mark.op === 'fill').map((mark) => mark.style)).toEqual(Array(5).fill(role('--n-sheet')));
    expect(taskMarks.filter((mark) => mark.op === 'stroke').map((mark) => mark.style)).toEqual(Array(5).fill(role('--n-warn')));
    expect(draw.strokes).toContain(role('--n-rule-2'));                     // the fan's rule to its owner
  });

  it('keeps every HUD v2 literal in Classic, and never consults the theme roles', () => {
    setLook('obsidian');
    const { probe, draw } = installCanvas();
    const { container } = render(mesh());
    act(() => { rafCb(0); });
    expect(probe.reads).toBe(0);
    expect(draw.log.fillStyle[0]).toBe('rgba(4,7,13,0.26)');            // the trail fill
    expect(draw.log.fillStyle).toContain('#6fb8e0');                     // the starfield
    expect(draw.createRadialGradient).toHaveBeenCalled();                // bloom and halos
    expect(draw.log.globalCompositeOperation).toContain('lighter');
    expect(draw.strokes).toContain('#bfeaff');                           // the reactor ring
    expect(draw.log.font).toContain('800 8px "JetBrains Mono",monospace');
    expect(draw.texts.map((entry) => entry.text)).toEqual(expect.arrayContaining(['JARVIS', 'FRIGGA', 'HOWARD', 'QWEN:7B']));
    for (const colour of [...draw.log.fillStyle, ...draw.log.strokeStyle]) expect(ROLE_COLOURS.has(colour)).toBe(false);
    container.querySelectorAll('.nm-dot').forEach((dot) => expect(dot.getAttribute('style')).toBeNull());
  });

  it('draws each keyed mark in its legend swatch role, and leaves the swatches themselves to styles.css', () => {
    setLook('ledger');
    const { draw } = installCanvas();
    const { container } = render(mesh({ tasks: [{ id: 1, owner: 'frigga', title: 'sync', state: 'running' }] }));
    act(() => { rafCb(0); });
    // .nm-dot.core --n-text · .local --n-ok · .cloud --n-cloud · .task --n-warn (styles.css)
    const solid = (r) => draw.marks.filter((mark) => mark.op === 'fill' && mark.r === r).map((mark) => mark.style);
    expect(draw.marks).toContainEqual({ op: 'stroke', style: role('--n-text'), r: 23 });   // the core's ring
    expect(solid(6 + 0.66 * 10)).toContain(role('--n-ok'));                              // the local model
    expect(solid(6 + 0.22 * 10)).toContain(role('--n-cloud'));                           // the cloud lane
    expect(draw.marks.filter((mark) => mark.op === 'stroke' && mark.r === 4.6).map((mark) => mark.style)).toEqual([role('--n-warn')]);
    // no inline colour on the swatches: the markup the tests and styles.css select on is unchanged
    container.querySelectorAll('.nm-dot').forEach((dot) => expect(dot.getAttribute('style')).toBeNull());
    expect(container.querySelector('.nmesh-legend')?.textContent).toContain('1 running task');
  });

  it('re-reads the palette when the look changes: Nerva, Classic, Nerva again', async () => {
    setLook('ledger');
    const { draw } = installCanvas();
    render(mesh());
    act(() => { rafCb(0); });
    expect(draw.createRadialGradient).not.toHaveBeenCalled();
    expect(draw.log.fillStyle[0]).toBe(role('--n-bg'));

    // the MutationObserver on <html> reports after the change: let it run inside act()
    const switchLook = (look) => act(async () => {
      document.documentElement.setAttribute('data-look', look);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await switchLook('graphite');
    draw.log.fillStyle.length = 0;
    act(() => { rafCb(1); });
    expect(draw.createRadialGradient).toHaveBeenCalled();
    expect(draw.log.fillStyle[0]).toBe('rgba(4,7,13,0.26)');

    draw.createRadialGradient.mockClear();
    draw.log.fillStyle.length = 0;
    await switchLook('atlas');
    act(() => { rafCb(2); });
    expect(draw.createRadialGradient).not.toHaveBeenCalled();
    expect(draw.log.fillStyle[0]).toBe(role('--n-bg'));
  });

  it('paints the panel ground when it sits in a filled panel (a card theme)', () => {
    setLook('atlas', 'dark', { ...ROLES, '--n-panel-bg': '#1c2220' });
    const { draw } = installCanvas();
    render(<div className="panel">{mesh()}</div>);
    act(() => { rafCb(0); });
    expect(draw.log.fillStyle[0]).toBe(hexRgb('#1c2220'));
  });

  it('holds the Nerva core still under calm motion', () => {
    setLook('ledger');
    const { draw } = installCanvas();
    render(mesh({ motion: 'calm' }));
    act(() => { rafCb(0); rafCb(1); rafCb(2); });
    // the core's arcs are the arcs drawn with an explicit sweep (rings and nodes sweep 0..7)
    const sweeps = draw.arc.mock.calls.filter((call) => call[4] !== 7).map((call) => call[3]);
    expect(sweeps.length).toBeGreaterThan(0);
    expect(new Set(sweeps)).toEqual(new Set([0, Math.PI]));
  });

  it('keeps the legacy palette in a Nerva look when no 2D context can resolve the roles', () => {
    setLook('ledger');
    const ctx = stubCtx();   // no getImageData: the probe cannot read a pixel back
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    render(mesh());
    expect(() => act(() => { rafCb(0); })).not.toThrow();
    expect(ctx.createRadialGradient).toHaveBeenCalled();
    expect(ctx.font).toBe('800 8px "JetBrains Mono",monospace');
  });
});
