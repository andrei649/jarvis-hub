import { describe, expect, it } from '@jest/globals';
import { buildOrbGeometry, clampOrbSize, projectOrb } from '../orbGeometry';

describe('bounded native orb geometry', () => {
  it('caps the Fibonacci sphere and fixed filaments for mobile', () => {
    const geometry = buildOrbGeometry(10000);
    expect(geometry.points).toHaveLength(72);
    expect(geometry.links.length).toBeLessThanOrEqual(24);
    expect(new Set(geometry.points.map(point => `${point.x},${point.y},${point.z}`)).size).toBe(72);
    for (const point of geometry.points) {
      expect(Math.hypot(point.x, point.y, point.z)).toBeCloseTo(1, 5);
      expect(Number.isFinite(point.phase)).toBe(true);
    }
    for (const [from, to] of geometry.links) {
      expect(from).toBeGreaterThanOrEqual(0);
      expect(to).toBeLessThan(geometry.points.length);
    }
  });

  it('clamps dimensions and produces finite in-view coordinates for invalid inputs', () => {
    expect(clampOrbSize(-100)).toBe(80);
    expect(clampOrbSize(Infinity)).toBe(180);
    expect(clampOrbSize(10000)).toBe(360);
    const projected = projectOrb(buildOrbGeometry(72), Infinity, NaN, Infinity);
    expect(projected).toHaveLength(72);
    for (const point of projected) {
      expect(Number.isFinite(point.x)).toBe(true);
      expect(Number.isFinite(point.y)).toBe(true);
      expect(point.x).toBeGreaterThanOrEqual(0);
      expect(point.x).toBeLessThanOrEqual(180);
      expect(point.y).toBeGreaterThanOrEqual(0);
      expect(point.y).toBeLessThanOrEqual(180);
      expect(point.depth).toBeGreaterThanOrEqual(0);
      expect(point.depth).toBeLessThanOrEqual(1);
    }
  });

  it('projects deterministically and lets explicit energy swell the orb without changing topology', () => {
    const geometry = buildOrbGeometry(42);
    const quiet = projectOrb(geometry, 180, 0, 0);
    expect(projectOrb(geometry, 180, 0, 0)).toEqual(quiet);
    const active = projectOrb(geometry, 180, 0, 1);
    expect(active).toHaveLength(quiet.length);
    expect(active.some((point, index) => point.x !== quiet[index].x || point.y !== quiet[index].y)).toBe(true);
  });
});
