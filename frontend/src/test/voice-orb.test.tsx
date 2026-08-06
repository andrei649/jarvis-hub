// @ts-nocheck
/* HUD-v3 · VOICE ORB — the particle sphere bound to the useVoice state machine.
   Two contracts are pinned here:
   1. the pure state→visual mapping (`orbVisual`), including the honesty rule that
      only LISTENING may use the measured mic RMS — every other state is a labelled
      state animation and never a number;
   2. the component mounts, renders a canvas, and degrades without throwing when the
      2D context is null (headless) — same guard posture as the Neural Mesh. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, fireEvent } from '@testing-library/react';
import { VoiceOrb, orbVisual } from '../orb';
import { CinemaMesh } from '../shell';

let rafCb: any = null;
beforeEach(() => {
  rafCb = null;
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null);   // null-context → draw guard no-ops
  vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => { rafCb = cb; return 1; });
  vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); });

describe('orbVisual — state → visual contract', () => {
  it('uses the measured mic level ONLY while listening', () => {
    const listening = orbVisual({ status: 'listening', level: 0.25 });
    expect(listening.energySource).toBe('mic');
    expect(listening.energy).toBeGreaterThan(orbVisual({ status: 'listening', level: 0 }).energy);

    for (const s of ['off', 'idle', 'transcribing', 'speaking', 'error']) {
      const v = orbVisual({ status: s, level: 0.25 });
      expect(v.energySource).toBe('state');
      // a loud mic must not leak into a state the mic isn't measuring
      expect(v.energy).toBe(orbVisual({ status: s, level: 0 }).energy);
    }
  });

  it('keeps idle/off visibly quiet and never exceeds full energy', () => {
    expect(orbVisual({ status: 'off' }).energy).toBeLessThan(0.1);
    expect(orbVisual({ status: 'off' }).linked).toBe(false);
    expect(orbVisual({ status: 'idle' }).linked).toBe(false);
    expect(orbVisual({ status: 'listening', level: 99 }).energy).toBeLessThanOrEqual(1);
  });

  it('matches the voice-pill palette and falls back to off for unknown states', () => {
    expect(orbVisual({ status: 'listening' }).color).toBe('#41f59b');    // --green
    expect(orbVisual({ status: 'speaking' }).color).toBe('#8fe0ff');     // --accent-light
    expect(orbVisual({ status: 'error' }).color).toBe('#ff5a52');        // --red
    const unknown = orbVisual({ status: 'wat' });
    expect(unknown.status).toBe('off');
  });

  it('calm motion slows the spin without changing the reported state', () => {
    const lively = orbVisual({ status: 'speaking', motion: 'lively' });
    const calm = orbVisual({ status: 'speaking', motion: 'calm' });
    expect(calm.spin).toBeLessThan(lively.spin);
    expect(calm.calm).toBe(true);
    expect(calm.label).toBe(lively.label);
  });
});

describe('VoiceOrb — component', () => {
  it('mounts a canvas, exposes the state, and survives a null 2D context', () => {
    const { container } = render(<VoiceOrb status="listening" level={0.08} />);
    const orb = container.querySelector('.vorb');
    expect(orb).toBeTruthy();
    expect(container.querySelector('.vorb canvas')).toBeTruthy();
    expect(orb.getAttribute('data-status')).toBe('listening');
    expect(orb.getAttribute('data-energy-source')).toBe('mic');
    expect(() => rafCb && rafCb()).not.toThrow();      // one animation frame, null ctx
  });

  it('labels the energy source instead of printing a level number', () => {
    const { container } = render(<VoiceOrb status="speaking" level={0.2} />);
    expect(container.textContent).toContain('speaking');
    expect(container.textContent).toContain('state animation');
    expect(container.textContent).not.toMatch(/0\.\d/);
  });

  it('hides the caption when asked (inline pill use)', () => {
    const { container } = render(<VoiceOrb status="listening" showLabel={false} className="vorb-inline" />);
    expect(container.querySelector('.vorb-cap')).toBeNull();
    expect(container.querySelector('.vorb.vorb-inline')).toBeTruthy();
  });
});

/* The tests above stub a null 2D context (the degrade path). This block gives the
   canvas a recording stub instead, so the actual drawing reacts to real state: the
   sphere's particles are always drawn, and the neural filaments appear only when
   there is genuine energy — an idle orb must not paint itself busy. */
function recordingCtx() {
  const calls = { arc: 0, moveTo: 0, ellipse: 0 };
  const noop = () => {};
  return {
    calls,
    ctx: {
      setTransform: noop, clearRect: noop, beginPath: noop, closePath: noop,
      fill: noop, stroke: noop, fillRect: noop,
      arc: () => { calls.arc++; },
      ellipse: () => { calls.ellipse++; },
      moveTo: () => { calls.moveTo++; },
      lineTo: noop,
      createRadialGradient: () => ({ addColorStop: noop }),
      globalAlpha: 1, globalCompositeOperation: '', fillStyle: '', strokeStyle: '', lineWidth: 1,
    },
  };
}

describe('VoiceOrb — drawing reacts to state', () => {
  function drawOnce(props) {
    const rec = recordingCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => rec.ctx);
    const { unmount } = render(<VoiceOrb {...props} />);
    // the sphere sits at rest on mount; step frames so the eased energy reaches the target
    for (let i = 0; i < 40; i++) rafCb && rafCb();
    unmount();
    return rec.calls;
  }

  it('paints the particle sphere plus the reactor rings every frame', () => {
    const calls = drawOnce({ status: 'idle' });
    expect(calls.arc).toBeGreaterThan(600);     // 620 particles + bloom + centre
    expect(calls.ellipse).toBeGreaterThan(0);   // the two tilted rings
  });

  it('draws filaments while speaking but not while idle or off', () => {
    expect(drawOnce({ status: 'off' }).moveTo).toBe(0);
    expect(drawOnce({ status: 'idle' }).moveTo).toBe(0);
    expect(drawOnce({ status: 'speaking' }).moveTo).toBeGreaterThan(0);
  });

  it('a loud mic while listening lights the filaments up', () => {
    expect(drawOnce({ status: 'listening', level: 0 }).moveTo).toBe(0);
    expect(drawOnce({ status: 'listening', level: 0.2 }).moveTo).toBeGreaterThan(0);
  });
});

describe('CinemaMesh — orb stage', () => {
  const AGENTS = [{ id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'active' }];

  it('keeps the mesh as the default stage and switches to the orb on demand', () => {
    const { container, getByTitle } = render(
      <CinemaMesh agents={AGENTS} voice={{ status: 'listening', level: 0.1 }} onExit={() => {}} t={{}} />,
    );
    expect(container.querySelector('.cin-stage .nmesh')).toBeTruthy();
    expect(container.querySelector('.cin-stage .vorb')).toBeNull();

    fireEvent.click(getByTitle('voice orb (o)'));
    expect(container.querySelector('.cin-stage .vorb')).toBeTruthy();
    expect(container.querySelector('.cin-stage .nmesh')).toBeNull();
    expect(container.querySelector('.cin-stage .vorb').getAttribute('data-status')).toBe('listening');

    fireEvent.click(getByTitle('neural mesh (n)'));
    expect(container.querySelector('.cin-stage .nmesh')).toBeTruthy();
  });

  it('shows the orb as errored when the voice loop reports an error', () => {
    const { container, getByTitle } = render(
      <CinemaMesh agents={AGENTS} voice={{ status: 'idle', error: 'Microphone permission denied' }} onExit={() => {}} t={{}} />,
    );
    fireEvent.click(getByTitle('voice orb (o)'));
    expect(container.querySelector('.cin-stage .vorb').getAttribute('data-status')).toBe('error');
  });

  it('falls back to off with no voice loop wired', () => {
    const { container, getByTitle } = render(<CinemaMesh agents={AGENTS} onExit={() => {}} t={{}} />);
    fireEvent.click(getByTitle('voice orb (o)'));
    expect(container.querySelector('.cin-stage .vorb').getAttribute('data-status')).toBe('off');
  });

  it('Esc still exits from the orb stage', () => {
    const onExit = vi.fn();
    const { getByTitle } = render(<CinemaMesh agents={AGENTS} onExit={onExit} t={{}} />);
    fireEvent.click(getByTitle('voice orb (o)'));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onExit).toHaveBeenCalled();
  });
});
