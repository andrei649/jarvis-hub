/* HUD v3 · NEURAL MESH — native cinematic live brain (replaces the /brain?embed=1 iframe).
   Faithful TS port of docs/design/hud-v3/v3-mesh.jsx: arc-reactor core · decorative model
   shell · tier-coloured agent constellation that slowly rotates · comet token-flow on
   attribution edges · auto-choreographed cascades so it's alive on camera.

   Differences from the prototype, all behaviour-preserving:
   - defensive guards (null 2D context, missing ResizeObserver) so it degrades cleanly in
     headless/JSDOM and never throws if the canvas isn't drawable;
   - the mock `window.JarvisMock.streamSub` pulse hook is dropped (production has no mock) —
     live mode reacts only to current task/agent evidence. Demo mode keeps the cinematic
     choreography because it is explicitly URL-owned and visibly badged. */
import React, { useRef, useEffect, useMemo, useState } from 'react';
import { runningTasks } from './task-state';

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
  return runningTasks([t]).length ? '#41f59b' : '#8aa8be';
}

export function NeuralMesh({ agents = [], tasks = [], activeId, onSelect, motion, cinema = false, llm, trust, sources, demo = false, t }: any) {
  const wrapRef = useRef<any>(null), canvasRef = useRef<any>(null);
  const S = useRef<any>({
    nodes: [], edges: [], particles: [], rings: [], stars: [], hover: null, tasks: [], models: [], agents: [],
    demo: false, calm: false, cinema: false,
    w: 640, h: 460, cx: 320, cy: 230, dpr: 1, raf: 0, tick: 0, lastPulse: 0, lastCascade: 0, cascadeI: -1, focus: null,
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
  const node = (id) => S.current.nodes.find((n) => n.id === id);

  function build() {
    const st = S.current, W = st.w, H = st.h, cx = W / 2, cy = H / 2; st.cx = cx; st.cy = cy;
    const nodes: any[] = [], edges: any[] = []; const R = Math.min(W, H);
    const liveAgents = Array.isArray(st.agents) ? st.agents : [];
    nodes.push({ id: 'jarvis', kind: 'core', baseAng: 0, baseRad: 0, r: Math.max(15, R * (st.cinema ? 0.058 : 0.05)), label: 'JARVIS', agent: liveAgents.find((a) => a.id === 'jarvis'), i: 0 });
    const meshModels = Array.isArray(st.models) ? st.models : [];
    const mR = R * 0.20;
    meshModels.forEach((m, i) => {
      const ang = -Math.PI / 2 + i * (2 * Math.PI / meshModels.length);
      nodes.push({ id: 'model:' + m.key, kind: 'model', baseAng: ang, baseRad: mR, r: 6 + m.size * 10, model: m, label: m.label, i });
      edges.push({ a: 'jarvis', b: 'model:' + m.key, kind: 'mc' });
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
      if (target) edges.push({ a: a.id, b: 'model:' + target.key, kind: 'am' });
      edges.push({ a: a.id, b: 'jarvis', kind: 'ac' });
    });
    st.nodes = nodes; st.edges = edges;
    st.stars = Array.from({ length: 46 }, () => ({ x: Math.random() * W, y: Math.random() * H, r: Math.random() * 1.1 + 0.2, a: Math.random() * 0.4 + 0.1 }));
  }

  function fire(id, big?) {
    const st = S.current, n = node(id); if (!n) return; const c = colorFor(n);
    st.rings.push({ x: n.x, y: n.y, life: 0, c, big });
    st.edges.filter((e) => e.a === id).forEach((e) => {
      for (let k = 0; k < (big ? 4 : 3); k++) {
        st.particles.push({ e, life: -k * 0.12, sp: 0.017 + ((n.i + k) % 3) * 0.005, c, big });
      }
    });
  }
  function corePulse() {
    const st = S.current, c = node('jarvis'); if (!c) return;
    st.rings.push({ x: c.x, y: c.y, life: 0, c: '#8fe0ff', big: true });
    st.edges.filter((e) => e.a === 'jarvis').forEach((e) => { for (let k = 0; k < 2; k++) st.particles.push({ e, life: -k * 0.1, sp: 0.022, c: '#8fe0ff', big: true }); });
  }

  function resize() {
    const st = S.current, wrap = wrapRef.current, cv = canvasRef.current; if (!wrap || !cv) return;
    const r = wrap.getBoundingClientRect(); st.w = Math.max(220, r.width || 640); st.h = Math.max(160, r.height || 460);
    st.dpr = Math.min(2, (typeof window !== 'undefined' && window.devicePixelRatio) || 1);
    cv.width = st.w * st.dpr; cv.height = st.h * st.dpr; cv.style.width = st.w + 'px'; cv.style.height = st.h + 'px';
    build();
  }

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
  useEffect(() => { S.current.tasks = taskList; }, [taskList]);

  function draw() {
    const st = S.current, cv = canvasRef.current; if (!cv) return; const ctx = cv.getContext('2d'); if (!ctx) return;
    ctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0); st.tick++;
    const calm = st.calm;
    const cinema = st.cinema;
    const W = st.w, H = st.h, cx = st.cx, cy = st.cy;
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = 'rgba(4,7,13,' + (calm ? 0.4 : 0.26) + ')'; ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'lighter';
    st.stars.forEach((s) => { const tw = 0.6 + 0.4 * Math.sin(st.tick * 0.03 + s.x); ctx.globalAlpha = s.a * tw; ctx.fillStyle = '#6fb8e0'; ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, 7); ctx.fill(); });
    ctx.globalAlpha = 1;
    const bloom = ctx.createRadialGradient(cx, cy, 4, cx, cy, Math.min(W, H) * 0.5);
    bloom.addColorStop(0, 'rgba(43,140,210,0.10)'); bloom.addColorStop(1, 'rgba(43,140,210,0)');
    ctx.fillStyle = bloom; ctx.fillRect(0, 0, W, H);
    const rot = calm ? 0 : st.tick * (cinema ? 0.0011 : 0.0016);
    st.nodes.forEach((n) => {
      if (n.kind === 'core') { n.x = cx; n.y = cy; n._r = n.r; return; }
      const rad = n.baseRad + (calm ? 0 : Math.sin(st.tick * 0.04 + n.i) * 2.2);
      n.x = cx + Math.cos(n.baseAng + rot) * rad; n.y = cy + Math.sin(n.baseAng + rot) * rad; n._r = n.r;
    });
    const hov = st.hover, foc = st.focus;
    st.edges.forEach((e) => {
      const a = node(e.a), b = node(e.b); if (!a || !b) return;
      const act = isExecutingAgent(a.agent) || isExecutingAgent(b.agent) || foc === e.a;
      const dim = (hov && hov !== e.a && hov !== e.b) || (foc && foc !== e.a && foc !== e.b && e.a !== 'jarvis');
      ctx.strokeStyle = dim ? 'rgba(90,120,150,0.05)' : act ? 'rgba(80,190,255,0.22)' : 'rgba(110,140,170,0.09)';
      ctx.lineWidth = e.kind === 'mc' ? 1.2 : 0.7; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    });
    drawTaskFan(ctx, st, foc);
    ctx.globalCompositeOperation = 'lighter';
    if (!calm && st.demo) {
      if (st.tick % 46 === 0) { const ags = st.nodes.filter((n) => n.kind === 'agent'); const n = ags[Math.floor(Math.random() * ags.length)]; if (n) fire(n.id); }
      if (st.tick - st.lastPulse > (cinema ? 150 : 185)) { st.lastPulse = st.tick; corePulse(); }
      if (st.tick - st.lastCascade > (cinema ? 300 : 430)) { st.lastCascade = st.tick; st.cascadeI = 0; }
      if (st.cascadeI >= 0 && st.tick % 2 === 0) { const ags = st.nodes.filter((n) => n.kind === 'agent').sort((p, q) => p.baseAng - q.baseAng); const n = ags[st.cascadeI]; if (n) fire(n.id, true); st.cascadeI++; if (st.cascadeI >= ags.length) { st.cascadeI = -1; corePulse(); } }
    }
    if (!calm && !st.demo && st.tick % 8 === 0) {
      st.nodes.forEach((n) => {
        if (n.kind === 'agent' && isExecutingAgent(n.agent)) {
          const e = st.edges.find((x) => x.a === n.id && x.kind === 'am');
          if (e) st.particles.push({ e, life: 0, sp: 0.015 + (n.i % 3) * 0.004, c: colorFor(n) });
        }
      });
    }
    if (!calm && !st.demo && st.tick % 30 === 0 && st.tasks.length) {
      const owners = new Set(st.tasks.map(taskOwner));
      owners.forEach((owner) => fire(owner));
    }
    if (!calm && !st.demo && st.tick % 60 === 0
      && (st.tasks.length || st.nodes.some((n) => n.kind === 'agent' && isExecutingAgent(n.agent)))) {
      corePulse();
    }
    st.particles = st.particles.filter((p) => p.life < 1);
    st.particles.forEach((p) => {
      p.life += calm ? p.sp * 0.4 : p.sp; if (p.life < 0) return; const a = node(p.e.a), b = node(p.e.b); if (!a || !b) return;
      const x = a.x + (b.x - a.x) * p.life, y = a.y + (b.y - a.y) * p.life; const sz = p.big ? 2.4 : 1.7;
      ctx.globalAlpha = (1 - p.life) * 0.22; ctx.fillStyle = p.c; ctx.beginPath(); ctx.arc(x, y, sz * 3, 0, 7); ctx.fill();
      ctx.globalAlpha = 1 - p.life * 0.35; ctx.beginPath(); ctx.arc(x, y, sz, 0, 7); ctx.fillStyle = '#eaf6ff'; ctx.fill();
    });
    ctx.globalAlpha = 1;
    st.rings = st.rings.filter((r) => r.life < 1); st.rings.forEach((r) => { r.life += r.big ? 0.028 : 0.04; ctx.globalAlpha = (1 - r.life) * 0.55; ctx.strokeStyle = r.c; ctx.lineWidth = r.big ? 2 : 1.2; ctx.beginPath(); ctx.arc(r.x, r.y, 4 + r.life * (r.big ? 40 : 22), 0, 7); ctx.stroke(); });
    ctx.globalAlpha = 1;
    st.nodes.forEach((n) => {
      const active = isExecutingAgent(n.agent); const isHov = hov === n.id || foc === n.id;
      if (n.kind === 'core' || active || isHov || n.kind === 'model') {
        const c = colorFor(n); const g = ctx.createRadialGradient(n.x, n.y, 1, n.x, n.y, n._r + (n.kind === 'core' ? 16 : 9));
        g.addColorStop(0, c + '88'); g.addColorStop(1, c + '00'); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(n.x, n.y, n._r + (n.kind === 'core' ? 16 : 9), 0, 7); ctx.fill();
      }
    });
    ctx.globalCompositeOperation = 'source-over';
    st.nodes.forEach((n) => {
      const c = colorFor(n); const isHov = hov === n.id; const dim = (hov && !isHov && n.kind !== 'core') || (foc && foc !== n.id && n.kind === 'agent');
      const active = isExecutingAgent(n.agent); ctx.globalAlpha = dim ? 0.3 : 1;
      if (n.kind === 'core') {
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
        ctx.beginPath(); ctx.arc(n.x, n.y, n._r, 0, 7); ctx.fillStyle = (n.kind === 'model' || active) ? c : '#0a1219'; ctx.fill();
        ctx.lineWidth = n.kind === 'model' ? 1.5 : 1.2; ctx.strokeStyle = c; ctx.stroke();
      }
      ctx.globalAlpha = 1;
      if (n.kind !== 'agent' || active || isHov || foc === n.id) { ctx.fillStyle = isHov ? '#eaf6ff' : 'rgba(165,190,210,0.75)'; ctx.font = '800 8px "JetBrains Mono",monospace'; ctx.textAlign = 'center'; ctx.fillText(String(n.label).toUpperCase(), n.x, n.y + n._r + 10); }
    });
  }

  function drawTaskFan(ctx, st, foc) {
    const raw = Array.isArray(st.tasks) ? st.tasks : [];
    if (!raw.length) return;
    const byOwner = new Map();
    raw.forEach((tk) => {
      const owner = taskOwner(tk);
      if (!node(owner)) return;
      const list = byOwner.get(owner) || [];
      list.push(tk);
      byOwner.set(owner, list);
    });
    if (!byOwner.size) return;
    const W = st.w, H = st.h, cx = st.cx, cy = st.cy;
    const outer = Math.min(W, H) * (st.cinema ? 0.48 : 0.46);
    ctx.globalCompositeOperation = 'source-over';
    // Bounded fan (real-world finding, 2026-07-08): an owner can accumulate far
    // more tasks than a fixed-size arc can label legibly — cap what's drawn so
    // the fan never degrades into an unreadable overlapping block, no matter
    // how many tasks pile up under one owner.
    byOwner.forEach((fullList, owner) => {
      const origin = node(owner);
      if (!origin) return;
      const focused = foc === owner;
      const list = fullList.slice(0, MAX_FAN_TASKS);
      const base = Math.atan2(origin.y - cy, origin.x - cx);
      const span = focused ? Math.PI * 0.42 : Math.min(0.5, list.length * 0.13);
      list.forEach((tk, i) => {
        const frac = list.length === 1 ? 0.5 : i / (list.length - 1);
        const ang = base + (frac - 0.5) * span;
        const r = focused ? origin._r + 44 : outer;
        const x = focused ? origin.x + Math.cos(ang) * r : cx + Math.cos(ang) * r;
        const y = focused ? origin.y + Math.sin(ang) * r : cy + Math.sin(ang) * r;
        const dim = foc && !focused && owner !== 'jarvis';
        ctx.globalAlpha = dim ? 0.25 : 0.92;
        ctx.strokeStyle = 'rgba(130,170,200,0.18)';
        ctx.lineWidth = focused ? 0.9 : 0.6;
        ctx.beginPath(); ctx.moveTo(origin.x, origin.y); ctx.lineTo(x, y); ctx.stroke();
        ctx.fillStyle = 'rgba(4,7,13,0.92)';
        ctx.strokeStyle = taskColor(tk);
        ctx.lineWidth = focused ? 1.7 : 1.2;
        ctx.beginPath(); ctx.arc(x, y, focused ? 4.6 : 3.1, 0, 7); ctx.fill(); ctx.stroke();
        if (focused) {
          ctx.fillStyle = 'rgba(225,240,255,0.82)';
          ctx.font = '800 8px "JetBrains Mono",monospace';
          ctx.textAlign = 'center';
          if (i < MAX_FAN_LABELS) {
            ctx.fillText(taskTitle(tk).slice(0, 18).toUpperCase(), x, y - 8);
          } else if (i === MAX_FAN_LABELS && fullList.length > MAX_FAN_LABELS) {
            ctx.fillText(`+${fullList.length - MAX_FAN_LABELS} MORE`, x, y - 8);
          }
        }
      });
    });
    ctx.globalAlpha = 1;
  }

  function onMove(e) {
    const st = S.current, r = canvasRef.current.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    let hit: any = null, hd = 15; st.nodes.forEach((n) => { const d = Math.hypot(n.x - mx, n.y - my); if (d < hd) { hd = d; hit = n; } });
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
