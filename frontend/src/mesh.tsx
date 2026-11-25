/* HUD v3 · NEURAL MESH — native cinematic live brain (replaces the /brain?embed=1 iframe).
   Faithful TS port of docs/design/hud-v3/v3-mesh.jsx: arc-reactor core · decorative model
   shell · tier-coloured agent constellation that slowly rotates · comet token-flow on
   attribution edges · auto-choreographed cascades so it's alive on camera.

   Differences from the prototype, all behaviour-preserving:
   - defensive guards (null 2D context, missing ResizeObserver) so it degrades cleanly in
     headless/JSDOM and never throws if the canvas isn't drawable;
   - the mock `window.JarvisMock.streamSub` pulse hook is dropped (production has no mock) —
     live mode reacts only to current task/agent evidence. Demo mode keeps the cinematic
     choreography because it is explicitly URL-owned and visibly badged.

   Honesty contract: what is drawn is only what the hub reports. Agent nodes come from the
   roster, model shells from the current residents and this load's trust evidence
   (deriveMeshModels), task marks from the running-task list; activity (particles, rings) follows
   agents the hub reports busy or active and tasks it reports running. Only the visibly badged
   demo mode adds the cinematic cascades. A theme changes how a mark is drawn, never which marks
   exist.

   Themes (src/theme/CONTRACT.md): in a Nerva look the mesh draws flat marks in the theme's roles,
   read from the element the canvas sits in (theme/canvas-colours.ts): no bloom, no halo, no
   additive blending and no starfield (decoration, not data); labels take the theme's label voice
   at 12px or more, model names the mono face. A mark is drawn in the role its legend swatch
   (styles.css, .nm-dot) is keyed in, so a mark and its key agree. Classic (obsidian, graphite)
   keeps every literal below exactly as HUD v2 drew it, and so does an environment that cannot
   resolve the roles (no readable 2D context). */
import React, { useRef, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { runningTasks } from './task-state';
import { isNervaLook, readRole, readRoleColours, rgb, themeOf, watchLook } from './theme/canvas-colours';

// A fixed-size arc can only label so many tasks legibly regardless of focus —
// this bounds the per-owner task fan (see the byOwner.forEach draw below).
const MAX_FAN_TASKS = 5;
const MAX_FAN_LABELS = 3;
// The cinematic default constellation is allowed only in visibly badged demo mode.
const DEMO_MESH_MODELS = [
  { key: 'demo:gemma', label: 'gemma-4-26b', cloud: false, size: 0.66, detail: 'demo model' },
  { key: 'demo:claude', label: 'claude', cloud: true, size: 0.22, detail: 'demo cloud lane' },
  { key: 'demo:gemini', label: 'gemini', cloud: true, size: 0.13, detail: 'demo cloud lane' },
];

// "minimax/minimax-m2.7" → "minimax-m2.7"; keep the mesh label legible.
function shortModelName(raw) {
  const s = String(raw || '').trim();
  if (!s) return '';
  const base = s.includes('/') ? s.split('/').pop() : s;
  return base.length > 18 ? base.slice(0, 17) + '…' : base;
}

// Live model shells are derived only from the current status residents and a
// successful trust response from this exact load cycle.
export function deriveMeshModels({ demo, residents = [], trustEvidence = false, trust = null }: any) {
  if (demo) return DEMO_MESH_MODELS;
  const models: any[] = [];
  const seen = new Set<string>();
  (Array.isArray(residents) ? residents : []).forEach((resident) => {
    const provider = typeof resident?.provider === 'string' ? resident.provider.trim() : '';
    const id = typeof resident?.id === 'string' ? resident.id.trim() : '';
    if (!provider || !id) return;
    const key = `${provider}:${id}`;
    if (seen.has(key)) return;
    seen.add(key);
    models.push({ key, label: shortModelName(id), cloud: false, size: 0.66, detail: 'local model · loaded' });
  });
  if (trustEvidence === true && trust?.claude_available === true) {
    models.push({ key: 'cloud:claude', label: 'claude', cloud: true, size: 0.22, detail: 'cloud lane' });
  } else if (trustEvidence === true && trust?.cloud_available === true) {
    models.push({ key: 'cloud:generic', label: 'cloud', cloud: true, size: 0.18, detail: 'cloud lane' });
  }
  return models;
}
const TIER_COLOR: Record<string, string> = {
  CNS: '#2bb8f0', command: '#2bb8f0', BUS: '#ffb23f', business: '#ffb23f',
  TEC: '#a78bfa', tech: '#a78bfa', FND: '#41f59b', foundation: '#41f59b',
};
const agentColor = (a) => (a && (TIER_COLOR[a.tier] || TIER_COLOR[String((a && a.tier) || '').toLowerCase()])) || '#5fa8d8';

export function isExecutingAgent(agent): boolean {
  const status = String(agent?.status || '').trim().toLowerCase();
  return status === 'busy' || status === 'active';
}

function taskOwner(t) {
  return String((t && (t.owner || t.agent_id || t.agent)) || 'jarvis').toLowerCase();
}
function taskTitle(t) {
  return String((t && (t.title || t.label || t.kind || t.id)) || 'task');
}
function taskColor(t) {
  const s = String((t && (t.state || t.status)) || '').trim().toLowerCase();
  return s === 'running' ? '#41f59b' : '#8aa8be';
}

/* ---- Nerva looks: the mesh in the theme's roles ------------------------------------------ */

// The roles a Nerva look draws the mesh with (contract §3). The legend's swatches (styles.css,
// .nm-dot) key the same marks in the same roles: the core --n-text, a local model --n-ok, a cloud
// lane --n-cloud, a running task --n-warn.
const MESH_ROLES = [
  'n-bg', 'n-panel-bg', 'n-sheet', 'n-text', 'n-text-2', 'n-text-3', 'n-rule', 'n-rule-2',
  'n-emph', 'n-ok', 'n-warn', 'n-info', 'n-cloud',
] as const;
// --n-panel-bg is transparent in a theme that draws registers without a box; the rest must resolve.
const MESH_ROLES_REQUIRED = MESH_ROLES.filter((role) => role !== 'n-panel-bg');

type MeshPalette = {
  ground: string;      // what the canvas paints each frame: the ground it sits on
  sheet: string; text: string; text2: string; text3: string; rule: string; rule2: string;
  emph: string; ok: string; warn: string; info: string; cloud: string;
  size: number;        // label size, px: --n-fs-meta, never below 12
  labelFont: string;   // ctx.font in the theme's label voice
  identFont: string;   // ctx.font for identifiers (model names): mono, never re-cased
  labelCase: string;   // --n-label-case
  track: string;       // --n-label-track as a canvas letterSpacing, px
};

// --n-label-track (0, .02em, 1px) as px for ctx.letterSpacing.
function trackPx(raw: string, size: number): string {
  const value = String(raw || '').trim().toLowerCase();
  const n = parseFloat(value);
  if (!Number.isFinite(n) || n === 0) return '0px';
  if (value.endsWith('rem')) return (n * 16).toFixed(2) + 'px';
  if (value.endsWith('em')) return (n * size).toFixed(2) + 'px';
  if (value.endsWith('px')) return n + 'px';
  return '0px';
}

// A Nerva look's mesh palette, read from the element the canvas sits in. Null in Classic and
// wherever the roles cannot be resolved (no readable 2D context): the legacy palette is drawn.
function readMeshPalette(el: Element | null): MeshPalette | null {
  if (!el || !isNervaLook(themeOf(el).look)) return null;
  const c = readRoleColours(el, MESH_ROLES);
  if (!c || MESH_ROLES_REQUIRED.some((role) => !c[role])) return null;
  // The canvas sits on the page ground, or on its panel's when the theme fills panels (a card
  // theme): it paints that ground, so it never cuts a page-coloured hole in a card.
  const panel = typeof el.closest === 'function' ? el.closest('.panel') : null;
  const ground = panel && c['n-panel-bg'] ? c['n-panel-bg'] : c['n-bg'];
  const size = Math.max(12, parseFloat(readRole(el, 'n-fs-meta')) || 12);
  const labelFace = readRole(el, 'n-font-label') || readRole(el, 'n-font-ui') || 'sans-serif';
  const monoFace = readRole(el, 'n-font-mono') || 'monospace';
  return {
    ground: rgb(ground), sheet: rgb(c['n-sheet']),
    text: rgb(c['n-text']), text2: rgb(c['n-text-2']), text3: rgb(c['n-text-3']),
    rule: rgb(c['n-rule']), rule2: rgb(c['n-rule-2']),
    emph: rgb(c['n-emph']), ok: rgb(c['n-ok']), warn: rgb(c['n-warn']), info: rgb(c['n-info']), cloud: rgb(c['n-cloud']),
    size,
    labelFont: `${readRole(el, 'n-label-weight') || '400'} ${size}px ${labelFace}`,
    identFont: `${readRole(el, 'n-w-reg') || '400'} ${size}px ${monoFace}`,
    labelCase: readRole(el, 'n-label-case') || 'none',
    track: trackPx(readRole(el, 'n-label-track'), size),
  };
}

// The label voice's case (--n-label-case), as text-transform would draw it.
function voiceCase(text: string, labelCase: string): string {
  if (labelCase === 'uppercase') return text.toUpperCase();
  if (labelCase === 'lowercase') return text.toLowerCase();
  if (labelCase === 'capitalize') return text.replace(/(^|\s)(\S)/g, (_m, space, ch) => space + ch.toUpperCase());
  return text;
}

// Tracking for canvas text where the engine supports it; only written when it changes.
function setTracking(ctx, value: string) {
  if (ctx && 'letterSpacing' in ctx && ctx.letterSpacing !== value) ctx.letterSpacing = value;
}

// The tier hues of HUD v2 as roles: command info · business warn · tech cloud · foundation ok.
const TIER_ROLE: Record<string, 'info' | 'warn' | 'cloud' | 'ok'> = {
  CNS: 'info', command: 'info', BUS: 'warn', business: 'warn',
  TEC: 'cloud', tech: 'cloud', FND: 'ok', foundation: 'ok',
};
function tierRole(tier): 'info' | 'warn' | 'cloud' | 'ok' | 'text3' {
  const key = String(tier || '');
  if (Object.prototype.hasOwnProperty.call(TIER_ROLE, key)) return TIER_ROLE[key];
  const lower = key.toLowerCase();
  if (Object.prototype.hasOwnProperty.call(TIER_ROLE, lower)) return TIER_ROLE[lower];
  return 'text3';
}
// A node's mark in a Nerva look; mirrors colorFor() below, role for literal.
function roleColorFor(n, pal: MeshPalette): string {
  if (n.kind === 'core') return pal.text;
  if (n.kind === 'model') return n.model.cloud ? pal.cloud : pal.ok;
  const s = n.agent && n.agent.status;
  if (s === 'active') return pal.emph;
  if (s === 'busy') return pal.warn;
  return pal[tierRole(n.agent && n.agent.tier)];
}
// A running task is ringed in --n-warn, the role its legend key (.nm-dot.task in styles.css) and
// a busy agent are drawn in: work in progress reads as one colour on the canvas and in the key.
// HUD v2 drew it green under an amber key; a theme keeps the mark and its key in step instead.
function taskRoleColor(t, pal: MeshPalette): string {
  const s = String((t && (t.state || t.status)) || '').trim().toLowerCase();
  return s === 'running' ? pal.warn : pal.text3;
}

export function NeuralMesh({ agents = [], tasks = [], activeId, onSelect, motion, cinema = false, llm, trust, sources, demo = false, t }: any) {
  const wrapRef = useRef<any>(null), canvasRef = useRef<any>(null);
  const S = useRef<any>({
    nodes: [], edges: [], particles: [], rings: [], stars: [], hover: null, tasks: [], models: [], agents: [],
    demo: false, calm: false, cinema: false,
    w: 640, h: 460, cx: 320, cy: 230, dpr: 1, raf: 0, tick: 0, lastPulse: 0, lastCascade: 0, cascadeI: -1, focus: null,
    nodeMap: new Map(),
    pal: null,   // MeshPalette in a Nerva look; null draws the legacy (Classic) palette
  });
  const [tip, setTip] = useState<any>(null);
  const taskList = useMemo(() => runningTasks(Array.isArray(tasks) ? tasks : []), [tasks]);
  const models = useMemo(() => deriveMeshModels({
    demo,
    residents: llm?.residents,
    trustEvidence: sources?.trust === true,
    trust,
  }), [demo, llm?.residents, sources?.trust, trust]);
  S.current.models = models;
  S.current.agents = Array.isArray(agents) ? agents : [];
  S.current.demo = demo;
  S.current.calm = motion === 'calm';
  S.current.cinema = cinema;
  const visibleTaskCount = useMemo(() => {
    const known = new Set(['jarvis', ...agents.map((a) => String(a.id).toLowerCase())]);
    return taskList.filter((tk) => known.has(taskOwner(tk))).length;
  }, [agents, taskList]);
  const evidenceState = demo
    ? 'demo'
    : Object.values(sources || {}).some(Boolean) ? 'live telemetry' : 'no live activity';

  function colorFor(n) {
    if (n.kind === 'core') return '#7fd6ff';
    if (n.kind === 'model') return n.model.cloud ? '#a78bfa' : '#41f59b';
    const s = n.agent && n.agent.status;
    if (s === 'active') return '#8fe0ff';
    if (s === 'busy') return '#ffce7a';
    return agentColor(n.agent);
  }
  // O(1) hash lookup via nodeMap instead of O(N) array search on every animation frame (60FPS loop)
  const node = (id) => S.current.nodeMap.get(id);

  function build() {
    const st = S.current, W = st.w, H = st.h, cx = W / 2, cy = H / 2; st.cx = cx; st.cy = cy;
    const nodes: any[] = [], edges: any[] = []; const R = Math.min(W, H);
    const edgesByA = new Map<string, any[]>();
    const agentModelEdgeMap = new Map<string, any>();
    const addEdge = (e: any) => {
      edges.push(e);
      const list = edgesByA.get(e.a) || [];
      list.push(e);
      edgesByA.set(e.a, list);
      if (e.kind === 'am') {
        agentModelEdgeMap.set(e.a, e);
      }
    };

    const liveAgents = Array.isArray(st.agents) ? st.agents : [];
    nodes.push({ id: 'jarvis', kind: 'core', baseAng: 0, baseRad: 0, r: Math.max(15, R * (st.cinema ? 0.058 : 0.05)), label: 'JARVIS', agent: liveAgents.find((a) => a.id === 'jarvis'), i: 0 });
    const meshModels = Array.isArray(st.models) ? st.models : [];
    const mR = R * 0.20;
    meshModels.forEach((m, i) => {
      const ang = -Math.PI / 2 + i * (2 * Math.PI / meshModels.length);
      nodes.push({ id: 'model:' + m.key, kind: 'model', baseAng: ang, baseRad: mR, r: 6 + m.size * 10, model: m, label: m.label, i });
      addEdge({ a: 'jarvis', b: 'model:' + m.key, kind: 'mc' });
    });
    // Pick edge targets from whatever models actually exist, so agent→model
    // wiring survives a live roster of just one local model (or a cloud lane).
    const localModel = meshModels.find((m) => !m.cloud) || meshModels[0];
    const cloudModels = meshModels.filter((m) => m.cloud);
    const list = liveAgents.filter((a) => a.id !== 'jarvis'); const aR = R * 0.44;
    list.forEach((a, i) => {
      const ang = -Math.PI / 2 + i * (2 * Math.PI / Math.max(1, list.length));
      nodes.push({ id: a.id, kind: 'agent', baseAng: ang, baseRad: aR, r: st.cinema ? 7 : 5.5, agent: a, label: a.name, i });
      const preferLocal = a.tier === 'FND' || a.id === 'frigga' || a.id === 'ultron' || a.id === 'hephaestus';
      const target = (preferLocal || !cloudModels.length) ? localModel : cloudModels[i % cloudModels.length];
      if (target) addEdge({ a: a.id, b: 'model:' + target.key, kind: 'am' });
      addEdge({ a: a.id, b: 'jarvis', kind: 'ac' });
    });
    st.nodes = nodes; st.edges = edges;
    st.edgesByA = edgesByA;
    st.agentModelEdgeMap = agentModelEdgeMap;
    st.nodeMap = new Map(nodes.map((n) => [n.id, n]));
    st.agentNodes = nodes.filter((n) => n.kind === 'agent');
    st.agentNodesSorted = [...st.agentNodes].sort((p, q) => p.baseAng - q.baseAng);
    st.stars = Array.from({ length: 46 }, () => ({ x: Math.random() * W, y: Math.random() * H, r: Math.random() * 1.1 + 0.2, a: Math.random() * 0.4 + 0.1 }));
  }

  function fire(id, big?) {
    const st = S.current, n = node(id); if (!n) return; const c = colorFor(n);
    st.rings.push({ x: n.x, y: n.y, life: 0, c, big });
    // Bolt Optimization: O(1) Map lookup via edgesByA and indexed for loop to avoid array closures
    const outgoing = st.edgesByA ? st.edgesByA.get(id) : st.edges.filter((e) => e.a === id);
    if (outgoing) {
      const numOutgoing = outgoing.length;
      for (let i = 0; i < numOutgoing; i++) {
        const e = outgoing[i];
        for (let k = 0; k < (big ? 4 : 3); k++) {
          st.particles.push({ e, life: -k * 0.12, sp: 0.017 + ((n.i + k) % 3) * 0.005, c, big });
        }
      }
    }
  }
  function corePulse() {
    const st = S.current, c = node('jarvis'); if (!c) return;
    st.rings.push({ x: c.x, y: c.y, life: 0, c: '#8fe0ff', big: true });
    // Bolt Optimization: O(1) Map lookup via edgesByA and indexed for loop to avoid array closures
    const outgoing = st.edgesByA ? st.edgesByA.get('jarvis') : st.edges.filter((e) => e.a === 'jarvis');
    if (outgoing) {
      const numOutgoing = outgoing.length;
      for (let i = 0; i < numOutgoing; i++) {
        const e = outgoing[i];
        for (let k = 0; k < 2; k++) {
          st.particles.push({ e, life: -k * 0.1, sp: 0.022, c: '#8fe0ff', big: true });
        }
      }
    }
  }

  function resize() {
    const st = S.current, wrap = wrapRef.current, cv = canvasRef.current; if (!wrap || !cv) return;
    const r = wrap.getBoundingClientRect(); st.w = Math.max(220, r.width || 640); st.h = Math.max(160, r.height || 460);
    st.dpr = Math.min(2, (typeof window !== 'undefined' && window.devicePixelRatio) || 1);
    cv.width = st.w * st.dpr; cv.height = st.h * st.dpr; cv.style.width = st.w + 'px'; cv.style.height = st.h + 'px';
    build();
    // A theme's type scale can step at a breakpoint (Ledger reads larger at >= 2200px).
    if (st.pal) refreshPalette();
  }

  // The theme's roles for the canvas: read before the first frame, again whenever <html>'s look,
  // scheme or typeface changes (watchLook also drops the colour cache), and on resize.
  function refreshPalette() {
    S.current.pal = readMeshPalette(wrapRef.current);
  }
  useLayoutEffect(() => {
    refreshPalette();
    return watchLook(refreshPalette);
    // eslint-disable-next-line
  }, []);

  useEffect(() => {
    resize();
    let ro: any = null;
    if (typeof ResizeObserver !== 'undefined') { ro = new ResizeObserver(resize); if (wrapRef.current) ro.observe(wrapRef.current); }
    const loop = () => { draw(); S.current.raf = requestAnimationFrame(loop); };
    S.current.raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(S.current.raf); if (ro) ro.disconnect(); };
    // eslint-disable-next-line
  }, []);
  useEffect(() => { build(); /* eslint-disable-next-line */ }, [agents, models, cinema]);
  useEffect(() => { S.current.focus = activeId; }, [activeId]);
  useEffect(() => {
    S.current.tasks = taskList;
    // Bolt Optimization: Group task fan by owner and precompute uniqueTaskOwners on state ref when taskList updates
    // to eliminate Map and Set allocations, string operations, and array scans inside the 60 FPS animation loop.
    const byOwner = new Map<string, any[]>();
    const uniqueOwners: string[] = [];
    for (let i = 0; i < taskList.length; i++) {
      const tk = taskList[i];
      const owner = taskOwner(tk);
      let list = byOwner.get(owner);
      if (!list) {
        list = [];
        byOwner.set(owner, list);
        uniqueOwners.push(owner);
      }
      list.push(tk);
    }
    S.current.tasksByOwner = byOwner;
    S.current.tasksByOwnerList = Array.from(byOwner.entries());
    S.current.uniqueTaskOwners = uniqueOwners;
  }, [taskList]);

  function draw() {
    const st = S.current, cv = canvasRef.current; if (!cv) return; const ctx = cv.getContext('2d'); if (!ctx) return;
    ctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0); st.tick++;
    const calm = st.calm;
    const cinema = st.cinema;
    const W = st.w, H = st.h, cx = st.cx, cy = st.cy;
    // A Nerva look's role palette; null draws the legacy (Classic) palette below, literal for literal.
    const pal: MeshPalette | null = st.pal;
    ctx.globalCompositeOperation = 'source-over';
    if (pal) {
      // Flat marks on the ground the canvas sits on, painted opaque each frame (no trails); no
      // additive blending, no starfield, no bloom.
      ctx.globalAlpha = 1;
      ctx.fillStyle = pal.ground; ctx.fillRect(0, 0, W, H);
    } else {
      ctx.fillStyle = 'rgba(4,7,13,' + (calm ? 0.4 : 0.26) + ')'; ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = 'lighter';
      // Bolt Optimization: Replace .forEach() array closures with indexed for loops across stars, nodes, and edges
      // in the 60 FPS animation loop to avoid allocating function closures on every frame.
      const stars = st.stars;
      const numStars = stars.length;
      for (let i = 0; i < numStars; i++) {
        const s = stars[i];
        const tw = 0.6 + 0.4 * Math.sin(st.tick * 0.03 + s.x);
        ctx.globalAlpha = s.a * tw;
        ctx.fillStyle = '#6fb8e0';
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, 7);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      const bloom = ctx.createRadialGradient(cx, cy, 4, cx, cy, Math.min(W, H) * 0.5);
      bloom.addColorStop(0, 'rgba(43,140,210,0.10)'); bloom.addColorStop(1, 'rgba(43,140,210,0)');
      ctx.fillStyle = bloom; ctx.fillRect(0, 0, W, H);
    }
    const rot = calm ? 0 : st.tick * (cinema ? 0.0011 : 0.0016);
    const nodes = st.nodes;
    const numNodes = nodes.length;
    for (let i = 0; i < numNodes; i++) {
      const n = nodes[i];
      if (n.kind === 'core') { n.x = cx; n.y = cy; n._r = n.r; continue; }
      const rad = n.baseRad + (calm ? 0 : Math.sin(st.tick * 0.04 + n.i) * 2.2);
      n.x = cx + Math.cos(n.baseAng + rot) * rad; n.y = cy + Math.sin(n.baseAng + rot) * rad; n._r = n.r;
    }
    const hov = st.hover, foc = st.focus;
    const edges = st.edges;
    const numEdges = edges.length;
    // Bolt Optimization: Cache strokeStyle and lineWidth to eliminate redundant Canvas 2D
    // state setter calls across edges on every 60 FPS animation frame (~5,000+ fewer setter calls/sec).
    let curStroke = '';
    let curLineWidth = -1;
    for (let i = 0; i < numEdges; i++) {
      const e = edges[i];
      const a = node(e.a), b = node(e.b); if (!a || !b) continue;
      const act = isExecutingAgent(a.agent) || isExecutingAgent(b.agent) || foc === e.a;
      const dim = (hov && hov !== e.a && hov !== e.b) || (foc && foc !== e.a && foc !== e.b && e.a !== 'jarvis');
      const stroke = pal
        ? (dim ? pal.rule : act ? pal.text3 : pal.rule2)
        : (dim ? 'rgba(90,120,150,0.05)' : act ? 'rgba(80,190,255,0.22)' : 'rgba(110,140,170,0.09)');
      const lw = e.kind === 'mc' ? 1.2 : 0.7;
      if (curStroke !== stroke) {
        ctx.strokeStyle = stroke;
        curStroke = stroke;
      }
      if (curLineWidth !== lw) {
        ctx.lineWidth = lw;
        curLineWidth = lw;
      }
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    drawTaskFan(ctx, st, foc);
    ctx.globalCompositeOperation = pal ? 'source-over' : 'lighter';
    if (!calm && st.demo) {
      if (st.tick % 46 === 0) { const ags = st.agentNodes || []; const n = ags[Math.floor(Math.random() * ags.length)]; if (n) fire(n.id); }
      if (st.tick - st.lastPulse > (cinema ? 150 : 185)) { st.lastPulse = st.tick; corePulse(); }
      if (st.tick - st.lastCascade > (cinema ? 300 : 430)) { st.lastCascade = st.tick; st.cascadeI = 0; }
      if (st.cascadeI >= 0 && st.tick % 2 === 0) { const ags = st.agentNodesSorted || []; const n = ags[st.cascadeI]; if (n) fire(n.id, true); st.cascadeI++; if (st.cascadeI >= ags.length) { st.cascadeI = -1; corePulse(); } }
    }
    if (!calm && !st.demo && st.tick % 8 === 0) {
      // Bolt Optimization: Use indexed for loop instead of .forEach closure allocation
      for (let i = 0; i < numNodes; i++) {
        const n = nodes[i];
        if (n.kind === 'agent' && isExecutingAgent(n.agent)) {
          // Bolt Optimization: O(1) Map lookup via agentModelEdgeMap instead of O(E) array scan per executing agent frame
          const e = st.agentModelEdgeMap ? st.agentModelEdgeMap.get(n.id) : st.edges.find((x) => x.a === n.id && x.kind === 'am');
          if (e) st.particles.push({ e, life: 0, sp: 0.015 + (n.i % 3) * 0.004, c: colorFor(n) });
        }
      }
    }
    if (!calm && !st.demo && st.tick % 30 === 0 && st.tasks.length) {
      // Bolt Optimization: Iterate over precomputed uniqueTaskOwners instead of allocating a
      // new Set<string>() and repeatedly resolving taskOwner() on every 30th frame (~120 Set allocations/min).
      const owners = st.uniqueTaskOwners;
      if (owners) {
        const numOwners = owners.length;
        for (let i = 0; i < numOwners; i++) {
          fire(owners[i]);
        }
      }
    }
    if (!calm && !st.demo && st.tick % 60 === 0) {
      // Bolt Optimization: Avoid st.nodes.some callback closure allocation
      if (st.tasks.length) {
        corePulse();
      } else {
        for (let i = 0; i < numNodes; i++) {
          const n = nodes[i];
          if (n.kind === 'agent' && isExecutingAgent(n.agent)) {
            corePulse();
            break;
          }
        }
      }
    }
    // Bolt Optimization: Prune particles in-place during iteration instead of filter() + forEach()
    // to prevent array allocations and GC pressure every 60 FPS frame (~3,600 allocations/min).
    const particles = st.particles;
    let particleWriteIdx = 0;
    const numParticles = particles.length;
    for (let i = 0; i < numParticles; i++) {
      const p = particles[i];
      p.life += calm ? p.sp * 0.4 : p.sp;
      if (p.life >= 1) continue;
      particles[particleWriteIdx++] = p;
      if (p.life < 0) continue;
      const a = node(p.e.a), b = node(p.e.b); if (!a || !b) continue;
      const x = a.x + (b.x - a.x) * p.life, y = a.y + (b.y - a.y) * p.life; const sz = p.big ? 2.4 : 1.7;
      if (pal) {
        // a flat dot in the secondary ink, fading as it travels: no halo
        ctx.globalAlpha = 1 - p.life * 0.35; ctx.fillStyle = pal.text2; ctx.beginPath(); ctx.arc(x, y, sz, 0, 7); ctx.fill();
      } else {
        ctx.globalAlpha = (1 - p.life) * 0.22; ctx.fillStyle = p.c; ctx.beginPath(); ctx.arc(x, y, sz * 3, 0, 7); ctx.fill();
        ctx.globalAlpha = 1 - p.life * 0.35; ctx.beginPath(); ctx.arc(x, y, sz, 0, 7); ctx.fillStyle = '#eaf6ff'; ctx.fill();
      }
    }
    particles.length = particleWriteIdx;

    ctx.globalAlpha = 1;

    // Bolt Optimization: Prune rings in-place during iteration instead of filter() + forEach()
    // to prevent array allocations and GC pressure every 60 FPS frame.
    const rings = st.rings;
    let ringWriteIdx = 0;
    const numRings = rings.length;
    for (let i = 0; i < numRings; i++) {
      const r = rings[i];
      r.life += r.big ? 0.028 : 0.04;
      if (r.life >= 1) continue;
      rings[ringWriteIdx++] = r;
      ctx.globalAlpha = (1 - r.life) * 0.55; ctx.strokeStyle = pal ? pal.text2 : r.c; ctx.lineWidth = r.big ? 2 : 1.2; ctx.beginPath(); ctx.arc(r.x, r.y, 4 + r.life * (r.big ? 40 : 22), 0, 7); ctx.stroke();
    }
    rings.length = ringWriteIdx;

    ctx.globalAlpha = 1;
    // Node halos are HUD v2 glow: Classic only.
    if (!pal) {
      for (let i = 0; i < numNodes; i++) {
        const n = nodes[i];
        const active = isExecutingAgent(n.agent); const isHov = hov === n.id || foc === n.id;
        if (n.kind === 'core' || active || isHov || n.kind === 'model') {
          const c = colorFor(n); const g = ctx.createRadialGradient(n.x, n.y, 1, n.x, n.y, n._r + (n.kind === 'core' ? 16 : 9));
          g.addColorStop(0, c + '88'); g.addColorStop(1, c + '00'); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(n.x, n.y, n._r + (n.kind === 'core' ? 16 : 9), 0, 7); ctx.fill();
        }
      }
    }
    ctx.globalCompositeOperation = 'source-over';
    // Bolt Optimization: Set font and textAlign once before the node label loop
    // to avoid ~900 redundant Canvas 2D font property assignments per second during 60 FPS animation.
    // A Nerva look switches between its label voice and the mono face (model names) only on change.
    let voice = '';
    if (!pal) {
      ctx.font = '800 8px "JetBrains Mono",monospace';
      setTracking(ctx, '0px');
    }
    ctx.textAlign = 'center';
    for (let i = 0; i < numNodes; i++) {
      const n = nodes[i];
      const c = pal ? roleColorFor(n, pal) : colorFor(n); const isHov = hov === n.id; const dim = (hov && !isHov && n.kind !== 'core') || (foc && foc !== n.id && n.kind === 'agent');
      const active = isExecutingAgent(n.agent); ctx.globalAlpha = dim ? 0.3 : 1;
      if (n.kind === 'core' && pal) {
        // the core in ink: its ring, two arcs (still under calm motion) and a solid centre
        ctx.strokeStyle = pal.text; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(n.x, n.y, n._r, 0, 7); ctx.stroke();
        const a1 = calm ? 0 : st.tick * 0.03, a2 = calm ? 0 : -st.tick * 0.045;
        ctx.lineWidth = 1.4; ctx.strokeStyle = pal.text2;
        ctx.beginPath(); ctx.arc(n.x, n.y, n._r - 4, a1, a1 + 2.1); ctx.stroke();
        ctx.beginPath(); ctx.arc(n.x, n.y, n._r - 4, a1 + Math.PI, a1 + Math.PI + 2.1); ctx.stroke();
        ctx.beginPath(); ctx.arc(n.x, n.y, n._r - 8, a2, a2 + 1.7); ctx.stroke();
        const pr = n._r * 0.34 + (calm ? 0 : Math.sin(st.tick * 0.09) * 2);
        ctx.fillStyle = pal.text; ctx.beginPath(); ctx.arc(n.x, n.y, Math.max(2, pr), 0, 7); ctx.fill();
      } else if (n.kind === 'core') {
        ctx.strokeStyle = '#bfeaff'; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(n.x, n.y, n._r, 0, 7); ctx.stroke();
        const a1 = st.tick * 0.03, a2 = -st.tick * 0.045;
        ctx.lineWidth = 1.4; ctx.strokeStyle = 'rgba(143,224,255,0.8)';
        ctx.beginPath(); ctx.arc(n.x, n.y, n._r - 4, a1, a1 + 2.1); ctx.stroke();
        ctx.beginPath(); ctx.arc(n.x, n.y, n._r - 4, a1 + Math.PI, a1 + Math.PI + 2.1); ctx.stroke();
        ctx.strokeStyle = 'rgba(43,184,240,0.7)';
        ctx.beginPath(); ctx.arc(n.x, n.y, n._r - 8, a2, a2 + 1.7); ctx.stroke();
        const pr = n._r * 0.34 + (calm ? 0 : Math.sin(st.tick * 0.09) * 2);
        ctx.fillStyle = '#dff4ff'; ctx.beginPath(); ctx.arc(n.x, n.y, Math.max(2, pr), 0, 7); ctx.fill();
      } else {
        // an idle agent is a ring on the ground (it hides the edges beneath it); models and busy/active agents are solid
        ctx.beginPath(); ctx.arc(n.x, n.y, n._r, 0, 7); ctx.fillStyle = (n.kind === 'model' || active) ? c : (pal ? pal.ground : '#0a1219'); ctx.fill();
        ctx.lineWidth = n.kind === 'model' ? 1.5 : 1.2; ctx.strokeStyle = c; ctx.stroke();
      }
      ctx.globalAlpha = 1;
      if (n.kind !== 'agent' || active || isHov || foc === n.id) {
        if (pal) {
          // names in the label voice and its case; a model name is an identifier: mono, as written
          const ident = n.kind === 'model';
          if (voice !== (ident ? 'ident' : 'label')) {
            ctx.font = ident ? pal.identFont : pal.labelFont; setTracking(ctx, ident ? '0px' : pal.track);
            voice = ident ? 'ident' : 'label';
          }
          ctx.fillStyle = (isHov || n.kind === 'core') ? pal.text : pal.text2;
          ctx.fillText(ident ? String(n.label) : voiceCase(String(n.label), pal.labelCase), n.x, n.y + n._r + pal.size + 1);
        } else { ctx.fillStyle = isHov ? '#eaf6ff' : 'rgba(165,190,210,0.75)'; ctx.fillText(String(n.label).toUpperCase(), n.x, n.y + n._r + 10); }
      }
    }
  }

  function drawTaskFan(ctx, st, foc) {
    const tasksByOwnerList = st.tasksByOwnerList;
    if (!tasksByOwnerList || !tasksByOwnerList.length) return;
    const W = st.w, H = st.h, cx = st.cx, cy = st.cy;
    const outer = Math.min(W, H) * (st.cinema ? 0.48 : 0.46);
    // Nerva: a task is a mark on the sheet ringed by its state, joined to its owner by a quiet
    // rule, its title in the label voice; Classic keeps the HUD v2 literals.
    const pal: MeshPalette | null = st.pal;
    ctx.globalCompositeOperation = 'source-over';
    // Bolt Optimization: Set font and textAlign once before the task fan loop
    // to avoid redundant Canvas 2D font property assignments per task at 60 FPS.
    if (pal) {
      ctx.font = pal.labelFont;
      setTracking(ctx, pal.track);
    } else {
      ctx.font = '800 8px "JetBrains Mono",monospace';
      setTracking(ctx, '0px');
    }
    ctx.textAlign = 'center';
    // Bounded fan (real-world finding, 2026-07-08): an owner can accumulate far
    // more tasks than a fixed-size arc can label legibly — cap what's drawn so
    // the fan never degrades into an unreadable overlapping block, no matter
    // how many tasks pile up under one owner.
    // Bolt Optimization: Use indexed for loop over tasksByOwnerList array to avoid MapIterator allocations per frame
    const numOwners = tasksByOwnerList.length;
    for (let ownerIdx = 0; ownerIdx < numOwners; ownerIdx++) {
      const [owner, fullList] = tasksByOwnerList[ownerIdx];
      const origin = node(owner);
      if (!origin) continue;
      const focused = foc === owner;
      const count = Math.min(fullList.length, MAX_FAN_TASKS);
      const base = Math.atan2(origin.y - cy, origin.x - cx);
      const span = focused ? Math.PI * 0.42 : Math.min(0.5, count * 0.13);
      for (let i = 0; i < count; i++) {
        const tk = fullList[i];
        const frac = count === 1 ? 0.5 : i / (count - 1);
        const ang = base + (frac - 0.5) * span;
        const r = focused ? origin._r + 44 : outer;
        const x = focused ? origin.x + Math.cos(ang) * r : cx + Math.cos(ang) * r;
        const y = focused ? origin.y + Math.sin(ang) * r : cy + Math.sin(ang) * r;
        const dim = foc && !focused && owner !== 'jarvis';
        ctx.globalAlpha = dim ? 0.25 : 0.92;
        ctx.strokeStyle = pal ? pal.rule2 : 'rgba(130,170,200,0.18)';
        ctx.lineWidth = focused ? 0.9 : 0.6;
        ctx.beginPath(); ctx.moveTo(origin.x, origin.y); ctx.lineTo(x, y); ctx.stroke();
        ctx.fillStyle = pal ? pal.sheet : 'rgba(4,7,13,0.92)';
        ctx.strokeStyle = pal ? taskRoleColor(tk, pal) : taskColor(tk);
        ctx.lineWidth = focused ? 1.7 : 1.2;
        ctx.beginPath(); ctx.arc(x, y, focused ? 4.6 : 3.1, 0, 7); ctx.fill(); ctx.stroke();
        if (focused) {
          ctx.fillStyle = pal ? pal.text : 'rgba(225,240,255,0.82)';
          if (i < MAX_FAN_LABELS) {
            if (pal) ctx.fillText(voiceCase(taskTitle(tk).slice(0, 18), pal.labelCase), x, y - 9);
            else ctx.fillText(taskTitle(tk).slice(0, 18).toUpperCase(), x, y - 8);
          } else if (i === MAX_FAN_LABELS && fullList.length > MAX_FAN_LABELS) {
            if (pal) ctx.fillText(voiceCase(`+${fullList.length - MAX_FAN_LABELS} more`, pal.labelCase), x, y - 9);
            else ctx.fillText(`+${fullList.length - MAX_FAN_LABELS} MORE`, x, y - 8);
          }
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  function onMove(e) {
    const st = S.current, r = canvasRef.current.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    let hit: any = null, hd = 15;
    // Bolt Optimization: Use indexed loop on mouse movement handler to eliminate callback closures
    const nodes = st.nodes;
    const numNodes = nodes.length;
    for (let i = 0; i < numNodes; i++) {
      const n = nodes[i];
      const d = Math.hypot(n.x - mx, n.y - my);
      if (d < hd) { hd = d; hit = n; }
    }
    st.hover = hit ? hit.id : null;
    if (hit && hit.kind === 'agent' && hit.agent) setTip({ x: mx, y: my, name: hit.agent.name || hit.label, role: (hit.agent.role || '') + (isExecutingAgent(hit.agent) ? ' · ' + hit.agent.status : '') });
    else if (hit && hit.kind === 'model') setTip({ x: mx, y: my, name: hit.label, role: hit.model.detail });
    else if (hit && hit.kind === 'core') setTip({ x: mx, y: my, name: 'Jarvis', role: 'Prime Orchestrator · routes every turn' });
    else setTip(null);
  }
  function onLeave() { S.current.hover = null; setTip(null); }
  function onClick() {
    const h = S.current.hover, n = h && node(h);
    if (n && n.kind === 'agent' && onSelect) {
      onSelect(h);
      if (S.current.demo || isExecutingAgent(n.agent)) fire(h, true);
    }
  }

  return (
    <div className="nmesh" ref={wrapRef} onMouseMove={onMove} onMouseLeave={onLeave} onClick={onClick}>
      <canvas ref={canvasRef}></canvas>
      {tip && <div className="nmesh-tip" style={{ left: tip.x, top: tip.y }}><div className="nm-name">{tip.name}</div><div className="nm-role">{tip.role}</div></div>}
      <div className="nmesh-legend"><span><i className="nm-dot core"></i>orchestrator</span><span><i className="nm-dot local"></i>local model</span><span><i className="nm-dot cloud"></i>cloud lane</span>{visibleTaskCount > 0 && <span><i className="nm-dot task"></i>{visibleTaskCount} running task{visibleTaskCount === 1 ? '' : 's'}</span>}<span className="nm-hint">{evidenceState} · click an agent</span></div>
    </div>
  );
}
