/* HUD v3 · VOICE ORB — the particle sphere that reacts to the live voice loop.

   The Neural Mesh (mesh.tsx) draws WHO is working: agents, models, task fans. This
   is the other half of the "assistant is present in the room" picture — a single
   particle sphere whose motion is bound to the `useVoice()` state machine, so a
   glance from across the room tells you whether Jarvis is listening, transcribing,
   speaking, off, or broken.

   HONESTY CONTRACT (same posture as the mesh, and it matters more here because a
   pulsing sphere *looks* like data):
   - While the loop is LISTENING the pulse amplitude is the real measured mic RMS
     (`voice.level`, produced by the AnalyserNode in voice.ts) — energySource 'mic'.
   - In every other state there is no measured signal to show, so the sphere runs a
     fixed breathing animation and reports energySource 'state'. It is labelled as
     such and NO numeric level is ever rendered: an animation is a state indicator,
     never a metric.
   - Idle/off is visibly quiet. The orb never invents activity to look alive.

   Canvas 2D only — no WebGL, no three.js, no external assets (the HUD ships as a
   committed local bundle). Degrades cleanly: a null 2D context or a missing
   ResizeObserver leaves an empty, non-throwing shell in JSDOM/headless. */
import React, { useRef, useEffect, useMemo, useState } from 'react';

export type OrbStatus = 'off' | 'idle' | 'listening' | 'transcribing' | 'speaking' | 'error';

// Palette mirrors the voice pill in cockpit.tsx (listening = --green, speaking =
// --accent-light) so the orb and the text pill can never disagree about state.
const ORB_LOOK: Record<string, { color: string; label: string; spin: number; base: number }> = {
  off:          { color: '#5fa8d8', label: 'voice off',      spin: 0.10, base: 0.06 },
  idle:         { color: '#7fd6ff', label: 'standing by',    spin: 0.35, base: 0.14 },
  listening:    { color: '#41f59b', label: 'listening',      spin: 0.85, base: 0.16 },
  transcribing: { color: '#ffc24d', label: 'transcribing',   spin: 1.25, base: 0.34 },
  speaking:     { color: '#8fe0ff', label: 'speaking',       spin: 1.05, base: 0.40 },
  error:        { color: '#ff5a52', label: 'voice error',    spin: 0.14, base: 0.05 },
};

/* Pure view-model: everything the renderer needs, derived without a canvas so the
   state→visual contract is unit-testable on its own. `level` is the raw mic RMS
   (0..~0.3 in practice); it is only allowed to drive the sphere while listening. */
export function orbVisual({ status, level = 0, motion = 'lively' }: { status?: string; level?: number; motion?: string } = {}) {
  const key = Object.prototype.hasOwnProperty.call(ORB_LOOK, String(status)) ? String(status) : 'off';
  const look = ORB_LOOK[key];
  const calm = motion === 'calm';
  const measured = key === 'listening';
  // RMS ~0.025 is the speech threshold in voice.ts; ~0.25 is a loud speaker. Map
  // that band onto 0..1 so normal talking fills most of the range.
  const mic = measured ? Math.max(0, Math.min(1, (Number(level) || 0) / 0.25)) : 0;
  const energy = Math.max(0, Math.min(1, look.base + mic * 0.72));
  return {
    status: key,
    color: look.color,
    label: look.label,
    energy,
    // 'mic' = amplitude is the measured mic RMS; 'state' = fixed breathing animation.
    energySource: measured ? 'mic' : 'state',
    spin: calm ? look.spin * 0.25 : look.spin,
    linked: energy > 0.3,        // neural filaments only appear with real activity
    calm,
  };
}

function prefersReducedMotion() {
  try {
    return typeof window !== 'undefined' && !!window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch { return false; }
}

// Fibonacci sphere — even point distribution without clumping at the poles.
function sphereParticles(count: number) {
  const pts: any[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / Math.max(1, count - 1)) * 2;
    const rad = Math.sqrt(Math.max(0, 1 - y * y));
    const th = golden * i;
    pts.push({ x: Math.cos(th) * rad, y, z: Math.sin(th) * rad, phase: (i % 17) * 0.37, i });
  }
  return pts;
}

/* Fixed filament pairs (i → i+step) wrap the sphere in a wireframe lattice. Chosen
   once per particle set so the "neural" links are stable frame to frame instead of
   flickering random noise. */
function filaments(count: number) {
  const links: any[] = [];
  for (let i = 0; i < count; i += 3) {
    const j = (i + 7) % count;
    links.push([i, j]);
  }
  return links;
}

export function VoiceOrb({ status = 'off', level = 0, motion = 'lively', density = 'normal', showLabel = true, className = '' }: any) {
  const wrapRef = useRef<any>(null);
  const canvasRef = useRef<any>(null);
  const vis = useMemo(() => orbVisual({ status, level, motion }), [status, level, motion]);
  const [reduced] = useState(prefersReducedMotion);
  const count = density === 'compact' ? 220 : 620;
  const S = useRef<any>({
    pts: sphereParticles(count), links: filaments(count),
    w: 300, h: 300, dpr: 1, raf: 0, tick: 0, yaw: 0, energy: 0, vis,
  });
  S.current.vis = vis;
  // A hard reduced-motion preference wins over the HUD's own motion setting.
  S.current.frozen = reduced;

  function resize() {
    const st = S.current, wrap = wrapRef.current, cv = canvasRef.current;
    if (!wrap || !cv) return;
    const r = wrap.getBoundingClientRect();
    st.w = Math.max(80, r.width || 300);
    st.h = Math.max(80, r.height || 300);
    st.dpr = Math.min(2, (typeof window !== 'undefined' && window.devicePixelRatio) || 1);
    cv.width = st.w * st.dpr; cv.height = st.h * st.dpr;
    cv.style.width = st.w + 'px'; cv.style.height = st.h + 'px';
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

  function draw() {
    const st = S.current, cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext('2d');
    if (!ctx) return;                       // headless / unsupported → no-op, never throws
    const v = st.vis;
    ctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
    if (!st.frozen) st.tick++;
    // Ease toward the target energy so a mic spike swells the sphere instead of
    // snapping it — the smoothing is visual only, the target is the real value.
    st.energy += (v.energy - st.energy) * 0.12;
    const e = st.energy;
    const W = st.w, H = st.h, cx = W / 2, cy = H / 2;
    const R = Math.min(W, H) * 0.34;

    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'lighter';

    // core bloom
    const glow = ctx.createRadialGradient(cx, cy, 1, cx, cy, R * (1.5 + e * 0.5));
    glow.addColorStop(0, v.color + (v.status === 'off' ? '30' : '66'));
    glow.addColorStop(0.45, v.color + '18');
    glow.addColorStop(1, v.color + '00');
    ctx.fillStyle = glow;
    ctx.beginPath(); ctx.arc(cx, cy, R * (1.5 + e * 0.5), 0, 7); ctx.fill();

    if (!st.frozen) st.yaw += 0.004 * v.spin;
    const yaw = st.yaw, tilt = 0.42;
    const cosY = Math.cos(yaw), sinY = Math.sin(yaw);
    const cosT = Math.cos(tilt), sinT = Math.sin(tilt);
    const breathe = st.frozen ? 0 : Math.sin(st.tick * 0.035) * 0.5 + 0.5;

    // project every particle once; the lattice reuses the same screen positions
    const proj: any[] = [];
    st.pts.forEach((p) => {
      // radial displacement: steady breathing + per-particle turbulence scaled by energy
      const wob = st.frozen ? 0
        : Math.sin(st.tick * 0.05 + p.phase) * 0.035 + Math.sin(st.tick * 0.11 + p.i) * 0.02 * e;
      const rr = R * (1 + wob + e * 0.16 * breathe);
      let x = p.x, y = p.y, z = p.z;
      const x1 = x * cosY - z * sinY, z1 = x * sinY + z * cosY;          // yaw
      const y2 = y * cosT - z1 * sinT, z2 = y * sinT + z1 * cosT;         // tilt
      const depth = (z2 + 1) / 2;                                        // 0 back … 1 front
      const persp = 1 / (1.9 - z2 * 0.55);
      proj.push({
        x: cx + x1 * rr * persp * 1.55,
        y: cy + y2 * rr * persp * 1.55,
        d: depth,
      });
    });

    if (v.linked) {
      ctx.lineWidth = 0.6;
      st.links.forEach(([a, b]) => {
        const pa = proj[a], pb = proj[b];
        if (!pa || !pb) return;
        const alpha = Math.min(pa.d, pb.d) * 0.22 * e;
        if (alpha <= 0.01) return;
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = v.color;
        ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke();
      });
    }

    proj.forEach((p) => {
      const size = 0.5 + p.d * (density === 'compact' ? 1.1 : 1.6) + e * 0.7;
      ctx.globalAlpha = 0.12 + p.d * 0.72;
      ctx.fillStyle = p.d > 0.78 ? '#eaf6ff' : v.color;
      ctx.beginPath(); ctx.arc(p.x, p.y, size, 0, 7); ctx.fill();
    });

    // arc-reactor rings — the "it is a machine" cue, tilted with the sphere
    ctx.globalAlpha = 0.30 + e * 0.35;
    ctx.strokeStyle = v.color;
    ctx.lineWidth = density === 'compact' ? 0.8 : 1.2;
    for (let k = 0; k < 2; k++) {
      const rr = R * (1.12 + k * 0.22);
      ctx.beginPath();
      ctx.ellipse(cx, cy, rr, rr * (0.26 + k * 0.1), yaw * (k ? -0.6 : 0.8), 0, Math.PI * 2);
      ctx.stroke();
    }

    // hot centre
    ctx.globalAlpha = 0.55 + e * 0.45;
    ctx.fillStyle = '#eaf6ff';
    ctx.beginPath(); ctx.arc(cx, cy, Math.max(1.2, R * (0.06 + e * 0.05)), 0, 7); ctx.fill();

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  return (
    <div className={('vorb' + (className ? ' ' + className : '')).trim()} ref={wrapRef} data-status={vis.status} data-energy-source={vis.energySource}>
      <canvas ref={canvasRef}></canvas>
      {showLabel && (
        <div className="vorb-cap">
          <span className="vorb-state" style={{ color: vis.color }}>{vis.label}</span>
          <span className="vorb-src">{vis.energySource === 'mic' ? 'mic level' : 'state animation'}</span>
        </div>
      )}
    </div>
  );
}
