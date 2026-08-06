/* HUD v3 · NEURAL BURST — the cinematic "brain firing" field for the briefing wall.

   Reference: the owner-supplied wall-screen video (2026-08-06, see
   docs/design/JARVIS_PRESENCE_GAP.md). Its centrepiece is not a particle sphere — it is
   a firing field: coloured node clusters ("regions") webbed by thin edges, long sweeping
   axon trails, and a blown-out white core that flares when the assistant works.

   What makes this Nerva's and not a wallpaper: every region is a REAL tier of the live
   cabinet, its node count is the real number of agents in that tier, and it only fires
   when those agents are actually executing. The reference video labels its regions
   "MOTOR CORTEX · 148 neurons · firing 0.42"; we label ours with counts we can prove.

   HONESTY CONTRACT (same posture as mesh.tsx / orb.tsx):
   - An empty roster draws an empty field. No agents → no regions → a dim, quiet core.
   - Firing is driven by evidence: executing agents, running tasks, and — while the voice
     loop is LISTENING — the measured mic RMS. `burstEnergy()` reports which one, and the
     wall prints that source. Nothing animates itself into looking busy.
   - Demo mode is the ONLY place the choreography runs without live evidence, and it is
     visibly badged by the caller.

   Canvas 2D only, no dependencies, no external assets. Degrades to a non-throwing empty
   shell when the 2D context is null (JSDOM/headless), like the mesh. */
import React, { useRef, useEffect, useMemo } from 'react';
import { runningTasks } from './task-state';
import { isExecutingAgent } from './mesh';

// Tier palette — identical to the Neural Mesh, so the same agent is the same colour
// wherever the HUD draws it.
const TIER: Record<string, { color: string; label: string }> = {
  CNS: { color: '#2bb8f0', label: 'orchestration' },
  command: { color: '#2bb8f0', label: 'orchestration' },
  BUS: { color: '#ffb23f', label: 'business' },
  business: { color: '#ffb23f', label: 'business' },
  TEC: { color: '#a78bfa', label: 'engineering' },
  tech: { color: '#a78bfa', label: 'engineering' },
  FND: { color: '#41f59b', label: 'foundation' },
  foundation: { color: '#41f59b', label: 'foundation' },
};
const FALLBACK = { color: '#5fa8d8', label: 'cabinet' };
const tierOf = (a: any) => String((a && a.tier) || '').trim();
const lookOf = (tier: string) => TIER[tier] || TIER[tier.toLowerCase()] || FALLBACK;

function ownerOf(task: any) {
  return String((task && (task.owner || task.agent_id || task.agent)) || 'jarvis').toLowerCase();
}

/* Pure view-model: real roster + real queue → the regions the canvas draws.
   One region per tier present in the roster. `nodes` is the real agent count (that is
   what the chip reports), `firing` counts only agents actually executing. */
export function burstRegions({ agents = [], tasks = [] }: any = {}) {
  const list = Array.isArray(agents) ? agents : [];
  const running = runningTasks(Array.isArray(tasks) ? tasks : []);
  const byTier = new Map<string, any>();
  list.forEach((a) => {
    const tier = tierOf(a) || 'cabinet';
    const key = tier.toLowerCase();
    const look = lookOf(tier);
    const cur = byTier.get(key) || { key, label: look.label, color: look.color, nodes: 0, firing: 0, tasks: 0, ids: [] };
    cur.nodes += 1;
    if (isExecutingAgent(a)) cur.firing += 1;
    cur.ids.push(String(a.id || '').toLowerCase());
    byTier.set(key, cur);
  });
  running.forEach((tk) => {
    const owner = ownerOf(tk);
    byTier.forEach((r) => { if (r.ids.indexOf(owner) >= 0) r.tasks += 1; });
  });
  // stable order → the field doesn't reshuffle between renders
  return Array.from(byTier.values()).sort((a, b) => a.key.localeCompare(b.key));
}

/* Where the light comes from, and whether we can prove it.
   Priority: a measured mic level while listening > live cabinet work > idle. */
export function burstEnergy({ agents = [], tasks = [], voice = null, demo = false }: any = {}) {
  const list = Array.isArray(agents) ? agents : [];
  const firing = list.filter(isExecutingAgent).length;
  const running = runningTasks(Array.isArray(tasks) ? tasks : []).length;
  const status = String((voice && voice.status) || 'off');
  const listening = status === 'listening';
  const mic = listening ? Math.max(0, Math.min(1, (Number(voice && voice.level) || 0) / 0.25)) : 0;
  if (demo) return { level: 0.62, source: 'demo', detail: 'seeded choreography' };
  if (listening) {
    return { level: Math.min(1, 0.18 + mic * 0.8), source: 'mic', detail: 'measured mic level' };
  }
  if (status === 'speaking' || status === 'transcribing') {
    return { level: 0.42, source: 'voice', detail: 'voice loop ' + status };
  }
  if (firing || running) {
    const load = Math.min(1, (firing * 0.22) + (running * 0.12));
    return { level: 0.2 + load * 0.7, source: 'work', detail: `${firing} agent${firing === 1 ? '' : 's'} executing · ${running} task${running === 1 ? '' : 's'} running` };
  }
  return { level: 0.07, source: 'idle', detail: 'no live activity' };
}

/* Deterministic pseudo-random so the field is stable frame to frame (and identical
   between renders of the same roster) — a re-seeded field would flicker. */
function rng(seed: number) {
  let x = seed * 9301 + 49297;
  return () => { x = (x * 9301 + 49297) % 233280; return x / 233280; };
}

/* One region = one dendrite tree growing outward from the core. Segments branch and
   taper the way the reference's neuron bundles do, instead of forming a polygon. */
function growTree(seed: number, ang0: number, R: number, depthMax: number, rand: () => number) {
  const segs: any[] = [], nodes: any[] = [];
  const walk = (x: number, y: number, ang: number, len: number, depth: number, width: number) => {
    if (depth > depthMax) return;
    const steps = 4 + Math.floor(rand() * 4);
    let cx = x, cy = y, ca = ang;
    for (let i = 0; i < steps; i++) {
      ca += (rand() - 0.5) * 0.55;
      const l = len * (0.55 + rand() * 0.6);
      const nx = cx + Math.cos(ca) * l * 1.5, ny = cy + Math.sin(ca) * l;
      segs.push({ x1: cx, y1: cy, x2: nx, y2: ny, w: width, d: depth, ph: (segs.length * 7) % 23 });
      cx = nx; cy = ny;
      if (rand() < 0.55) nodes.push({ x: nx, y: ny, d: depth, ph: (nodes.length * 11) % 19 });
      if (depth < depthMax && rand() < 0.78) {
        walk(cx, cy, ca + (rand() < 0.5 ? 1 : -1) * (0.45 + rand() * 0.55), len * 0.66, depth + 1, width * 0.7);
      }
    }
  };
  // three fanned trunks per region: one bundle reads as a nerve, not a spider
  const r0 = R * 0.03;
  for (let k = -1; k <= 1; k++) {
    const a = ang0 + k * 0.34;
    walk(Math.cos(a) * r0 * 1.5, Math.sin(a) * r0, a, R * 0.05, 0, 1);
  }
  return { segs, nodes };
}

function buildField(regions: any[], W: number, H: number) {
  const cx = W / 2, cy = H / 2;
  const R = Math.min(W, H);
  const n = regions.length;
  const clusters = regions.map((region, i) => {
    const rand = rng(i * 977 + 13);
    // fan the trees around the core, biased to the horizontal like the reference
    const ang = -Math.PI / 2 + (i + 0.5) * (2 * Math.PI / Math.max(1, n));
    // more agents in a tier = a deeper, busier tree (bounded so it stays legible)
    const depth = Math.max(2, Math.min(4, Math.round(Math.log2(Math.max(1, region.nodes)) + 1.6)));
    const tree = growTree(i, ang, R, depth, rand);
    // label anchors on the tree's outer mass, not on a fixed ring
    const tip = tree.nodes.length ? tree.nodes[tree.nodes.length - 1] : { x: Math.cos(ang) * R * 0.3, y: Math.sin(ang) * R * 0.3 };
    return { ...region, ang, depth, segs: tree.segs, pts: tree.nodes, tipx: tip.x, tipy: tip.y };
  });
  return { cx, cy, R, clusters };
}

export function NeuralBurst({ agents = [], tasks = [], voice = null, motion = 'lively', demo = false, onEnergy }: any) {
  const wrapRef = useRef<any>(null), canvasRef = useRef<any>(null);
  const regions = useMemo(() => burstRegions({ agents, tasks }), [agents, tasks]);
  const energy = useMemo(() => burstEnergy({ agents, tasks, voice, demo }), [agents, tasks, voice, demo]);
  const S = useRef<any>({ w: 960, h: 540, dpr: 1, raf: 0, tick: 0, e: 0, field: null, regions: [], energy, calm: false });
  S.current.regions = regions;
  S.current.energy = energy;
  S.current.calm = motion === 'calm';

  // let the wall print the same energy source the canvas is drawing
  useEffect(() => { if (onEnergy) onEnergy(energy); }, [energy, onEnergy]);

  function resize() {
    const st = S.current, wrap = wrapRef.current, cv = canvasRef.current;
    if (!wrap || !cv) return;
    const r = wrap.getBoundingClientRect();
    st.w = Math.max(240, r.width || 960);
    st.h = Math.max(160, r.height || 540);
    st.dpr = Math.min(2, (typeof window !== 'undefined' && window.devicePixelRatio) || 1);
    cv.width = st.w * st.dpr; cv.height = st.h * st.dpr;
    cv.style.width = st.w + 'px'; cv.style.height = st.h + 'px';
    st.field = buildField(st.regions, st.w, st.h);
  }

  useEffect(() => {
    resize();
    let ro: any = null;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(resize);
      if (wrapRef.current) ro.observe(wrapRef.current);
    }
    const loop = () => { draw(); S.current.raf = requestAnimationFrame(loop); };
    S.current.raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(S.current.raf); if (ro) ro.disconnect(); };
    // eslint-disable-next-line
  }, []);
  useEffect(() => { S.current.field = buildField(regions, S.current.w, S.current.h); }, [regions]);

  function draw() {
    const st = S.current, cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext('2d');
    if (!ctx) return;                    // headless → no-op, never throws
    const field = st.field || buildField(st.regions, st.w, st.h);
    const calm = st.calm;
    ctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
    if (!calm) st.tick++;
    st.e += (st.energy.level - st.e) * 0.08;      // eased; the target is the real value
    const e = st.e, W = st.w, H = st.h, cx = field.cx, cy = field.cy, R = field.R;
    const t = st.tick;

    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = '#02040c';
    ctx.fillRect(0, 0, W, H);
    // blue haze — the reference's field is never pure black around the core
    const haze = ctx.createRadialGradient(cx, cy, R * 0.02, cx, cy, R * 0.72);
    haze.addColorStop(0, `rgba(30,90,190,${0.20 + e * 0.20})`);
    haze.addColorStop(0.5, 'rgba(16,48,110,0.13)');
    haze.addColorStop(1, 'rgba(4,10,30,0)');
    ctx.fillStyle = haze; ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'lighter';

    // ── region dendrite trees. Everything is drawn relative to the core, so the
    // whole field reads as one organism rather than separate constellations.
    ctx.save();
    ctx.translate(cx, cy);
    field.clusters.forEach((c: any, ci: number) => {
      const live = c.firing > 0 || c.tasks > 0;
      const sway = calm ? 0 : Math.sin(t * 0.008 + ci) * 0.02;
      ctx.rotate(sway);
      // branches: thinner and dimmer the deeper they go
      c.segs.forEach((sg: any) => {
        const pulse = live && !calm ? 0.5 + 0.5 * Math.sin(t * 0.05 - sg.ph * 0.4) : 0.4;
        ctx.globalAlpha = (live ? 0.20 + pulse * 0.34 : 0.12) * (1 - sg.d * 0.16) + e * 0.10;
        ctx.strokeStyle = c.color;
        ctx.lineWidth = Math.max(0.3, sg.w * (live ? 1.0 : 0.7));
        ctx.beginPath(); ctx.moveTo(sg.x1, sg.y1); ctx.lineTo(sg.x2, sg.y2); ctx.stroke();
      });
      // synapse nodes with a soft halo
      c.pts.forEach((p: any) => {
        const pulse = live && !calm ? 0.5 + 0.5 * Math.sin(t * 0.06 + p.ph) : 0.3;
        const r = 0.45 + (1 - p.d * 0.18) * (0.45 + pulse * 0.5);
        ctx.globalAlpha = 0.34 + pulse * 0.46;
        ctx.fillStyle = c.color;
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 7); ctx.fill();
        ctx.globalAlpha = (0.03 + pulse * 0.07) * (live ? 1 : 0.4);
        ctx.beginPath(); ctx.arc(p.x, p.y, r * 3.4, 0, 7); ctx.fill();
      });
      // firing signal: a bright head running the trunk outward — live tiers only
      if (live && !calm && c.segs.length) {
        for (let s2 = 0; s2 < 2; s2++) {
          const idx = Math.floor(((t * 0.02 + s2 * 0.5 + ci * 0.3) % 1) * c.segs.length);
          const sg = c.segs[idx];
          if (!sg) continue;
          ctx.globalAlpha = 0.9;
          ctx.fillStyle = '#eaf6ff';
          ctx.beginPath(); ctx.arc(sg.x2, sg.y2, 1.6, 0, 7); ctx.fill();
          ctx.globalAlpha = 0.3;
          ctx.fillStyle = c.color;
          ctx.beginPath(); ctx.arc(sg.x2, sg.y2, 8, 0, 7); ctx.fill();
        }
      }
      ctx.rotate(-sway);
    });
    ctx.restore();

    // ── long white axon sweeps that pass through the core and leave the frame.
    // Their count scales with energy, so an idle field is nearly bare.
    const sweeps = Math.round(4 + e * 16);
    for (let s2 = 0; s2 < sweeps; s2++) {
      const a0 = (s2 / sweeps) * Math.PI * 2 + (calm ? 0 : t * 0.0008) + s2 * 0.7;
      const len = R * (0.5 + ((s2 * 7) % 5) * 0.16);
      const bend = ((s2 % 3) - 1) * 0.8;
      const x1 = Math.cos(a0) * len * 1.6, y1 = Math.sin(a0) * len;
      const cxp = Math.cos(a0 + bend) * len * 0.55, cyp = Math.sin(a0 + bend) * len * 0.45;
      ctx.globalAlpha = 0.04 + e * 0.13;
      ctx.strokeStyle = s2 % 4 === 0 ? '#ffffff' : '#9fdcff';
      ctx.lineWidth = s2 % 4 === 0 ? 1.1 : 0.6;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.quadraticCurveTo(cx + cxp, cy + cyp, cx + x1, cy + y1);
      ctx.stroke();
    }

    // ── the hot core: small and blown out, with the bloom doing the work
    const coreR = R * (0.016 + e * 0.026);
    const bloom = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 14);
    bloom.addColorStop(0, `rgba(255,255,255,${0.5 + e * 0.45})`);
    bloom.addColorStop(0.10, `rgba(210,245,255,${0.26 + e * 0.34})`);
    bloom.addColorStop(0.32, `rgba(70,160,255,${0.10 + e * 0.16})`);
    bloom.addColorStop(1, 'rgba(20,60,160,0)');
    ctx.globalAlpha = 1;
    ctx.fillStyle = bloom;
    ctx.beginPath(); ctx.arc(cx, cy, coreR * 14, 0, 7); ctx.fill();
    // the hot lobe itself: stacked soft gradients, vertically elongated and never a
    // hard-edged shape — in the reference the core dissolves into its own bloom
    const wobble = calm ? 1 : 1 + Math.sin(t * 0.06) * 0.12;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.scale(0.62, 1.45 * wobble);
    for (let k = 3; k >= 1; k--) {
      const rr = coreR * k * 1.15;
      const g = ctx.createRadialGradient(0, 0, 0, 0, 0, rr);
      g.addColorStop(0, `rgba(255,255,255,${(0.42 + e * 0.4) / k})`);
      g.addColorStop(0.55, `rgba(226,246,255,${(0.16 + e * 0.2) / k})`);
      g.addColorStop(1, 'rgba(190,230,255,0)');
      ctx.globalAlpha = 1;
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(0, 0, rr, 0, 7); ctx.fill();
    }
    ctx.restore();

    // ── region chips: real name, real counts, anchored on the cluster
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    field.clusters.forEach((c: any) => {
      const label = String(c.label || c.key).toUpperCase();
      const sub = `${c.nodes} agent${c.nodes === 1 ? '' : 's'} · ${c.firing ? c.firing + ' executing' : 'idle'}${c.tasks ? ' · ' + c.tasks + ' task' + (c.tasks === 1 ? '' : 's') : ''}`;
      ctx.font = '700 8px "JetBrains Mono",monospace';
      const w = Math.max(ctx.measureText(label).width, ctx.measureText(sub).width) + 16;
      // Anchor part-way out along the tree, then clamp into a safe band: the wall's
      // stat cards own the outer fifths and the top/bottom bars own the edges, so a
      // chip pinned to the outermost tip would land on top of them.
      const ax = field.cx + c.tipx * 0.55, ay = field.cy + c.tipy * 0.55;
      const padX = W * 0.21, padTop = H * 0.12, padBot = H * 0.16;
      const x = Math.max(padX, Math.min(W - w - padX, ax - w / 2));
      const y = Math.max(padTop, Math.min(H - padBot, ay + 12));
      ctx.fillStyle = 'rgba(3,8,20,0.82)';
      ctx.fillRect(x, y, w, 22);
      ctx.fillStyle = c.color;
      ctx.fillRect(x, y, 2, 22);
      ctx.globalAlpha = 0.85;
      ctx.fillStyle = c.color;
      ctx.font = '700 8px "JetBrains Mono",monospace';
      ctx.textAlign = 'left';
      ctx.fillText(label, x + 7, y + 9);
      ctx.globalAlpha = 0.62;
      ctx.fillStyle = '#a8c4dd';
      ctx.font = '400 7px "JetBrains Mono",monospace';
      ctx.fillText(sub, x + 7, y + 18);
      ctx.globalAlpha = 1;
    });
  }

  return (
    <div className="nburst" ref={wrapRef} data-regions={regions.length} data-energy-source={energy.source}>
      <canvas ref={canvasRef}></canvas>
      {!regions.length && (
        <div className="nburst-empty">no agents reported · the field stays dark until the roster loads</div>
      )}
    </div>
  );
}
