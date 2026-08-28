/* H18.24 — the voice orb's state→visual contract, ported to native.
 *
 * `frontend/src/orb.tsx` splits the orb into two halves: a **pure view-model**
 * (`orbVisual`) and a Canvas-2D particle renderer. Only the first half is
 * portable — React Native has no canvas, and the browser renderer's particle
 * sphere needs a graphics surface (react-native-svg / Skia) that this app
 * deliberately does not depend on.
 *
 * This is that pure half, byte-for-byte equivalent to the browser's. Both
 * implementations are asserted against the SAME vector file
 * (`tests/_fixtures/orb_visual_vectors.json`) by their own test suites, so they
 * cannot silently diverge — the pattern this repo already uses for the
 * cross-language WorldView capability vectors.
 *
 * Honest scope note: native cannot currently reach `listening`/`transcribing`,
 * because the mobile app has no mic-capture pipeline (only TTS playback, H18.5).
 * The contract still models those states so the port stays faithful and so a
 * future native mic surface needs no second implementation.
 */

export type OrbStatus = 'off' | 'idle' | 'listening' | 'transcribing' | 'speaking' | 'error';

export interface OrbVisual {
  status: string;
  color: string;
  label: string;
  energy: number;
  /** 'mic' = amplitude is a measured mic RMS; 'state' = fixed breathing animation. */
  energySource: 'mic' | 'state';
  spin: number;
  linked: boolean;
  calm: boolean;
}

// Mirrors frontend/src/orb.tsx ORB_LOOK exactly. Any edit here without the same
// edit there breaks the shared-vector test in both suites, which is the point.
const ORB_LOOK: Record<string, { color: string; label: string; spin: number; base: number }> = {
  off: { color: '#5fa8d8', label: 'voice off', spin: 0.1, base: 0.06 },
  idle: { color: '#7fd6ff', label: 'standing by', spin: 0.35, base: 0.14 },
  listening: { color: '#41f59b', label: 'listening', spin: 0.85, base: 0.16 },
  transcribing: { color: '#ffc24d', label: 'transcribing', spin: 1.25, base: 0.34 },
  speaking: { color: '#8fe0ff', label: 'speaking', spin: 1.05, base: 0.4 },
  error: { color: '#ff5a52', label: 'voice error', spin: 0.14, base: 0.05 },
};

export function orbVisual(
  { status, level = 0, motion = 'lively' }:
  { status?: string | null; level?: number; motion?: string } = {},
): OrbVisual {
  const key = Object.prototype.hasOwnProperty.call(ORB_LOOK, String(status)) ? String(status) : 'off';
  const look = ORB_LOOK[key];
  const calm = motion === 'calm';
  const measured = key === 'listening';
  // RMS ~0.025 is the speech threshold in voice.ts; ~0.25 is a loud speaker.
  // Map that band onto 0..1 so normal talking fills most of the range.
  const mic = measured ? Math.max(0, Math.min(1, (Number(level) || 0) / 0.25)) : 0;
  const energy = Math.max(0, Math.min(1, look.base + mic * 0.72));
  return {
    status: key,
    color: look.color,
    label: look.label,
    energy,
    energySource: measured ? 'mic' : 'state',
    spin: calm ? look.spin * 0.25 : look.spin,
    linked: energy > 0.3,
    calm,
  };
}
