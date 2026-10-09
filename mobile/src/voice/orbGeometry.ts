/** Small, deterministic native projection; no browser surface or per-frame topology work. */
export type OrbPoint = { x: number; y: number; z: number; phase: number };
export type OrbGeometry = { points: OrbPoint[]; links: [number, number][] };
export type OrbProjection = { x: number; y: number; depth: number };

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

export function clampOrbSize(size: number | undefined): number {
  return Number.isFinite(size) ? Math.max(80, Math.min(360, size as number)) : 180;
}

export function buildOrbGeometry(requested = 72): OrbGeometry {
  const count = Number.isFinite(requested) ? Math.max(8, Math.min(72, Math.floor(requested))) : 72;
  const points: OrbPoint[] = [];
  const links: [number, number][] = [];
  for (let index = 0; index < count; index++) {
    const y = 1 - (index / (count - 1)) * 2;
    const radius = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = index * GOLDEN_ANGLE;
    points.push({ x: Math.cos(angle) * radius, y, z: Math.sin(angle) * radius, phase: angle });
  }
  for (let index = 0; index < count; index += 3) links.push([index, (index + 7) % count]);
  return { points, links };
}

export function projectOrb(geometry: OrbGeometry, requestedSize: number, requestedYaw: number, requestedEnergy: number): OrbProjection[] {
  const size = clampOrbSize(requestedSize);
  const yaw = Number.isFinite(requestedYaw) ? requestedYaw : 0;
  const energy = Number.isFinite(requestedEnergy) ? Math.max(0, Math.min(1, requestedEnergy)) : 0;
  const radius = size * 0.3 * (1 + energy * 0.16);
  const cosine = Math.cos(yaw), sine = Math.sin(yaw);
  const tiltCosine = Math.cos(0.42), tiltSine = Math.sin(0.42);
  return geometry.points.map(point => {
    const x = point.x * cosine - point.z * sine;
    const z = point.x * sine + point.z * cosine;
    const y = point.y * tiltCosine - z * tiltSine;
    const depth = Math.max(0, Math.min(1, (point.y * tiltSine + z * tiltCosine + 1) / 2));
    const scale = 1 / (1.9 - (depth * 2 - 1) * 0.55);
    return { x: size / 2 + x * radius * scale * 1.35, y: size / 2 + y * radius * scale * 1.35, depth };
  });
}
