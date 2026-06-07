// Recon-window client (ticket H19.2.2 frontend): types + fetchers for upcoming predicted
// satellite overflights of an AOI, plus a compact ETA formatter for the live countdown.
// Mirrors the backend contract in backend-api/src/repositories/recon.ts — times are UNIX seconds.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:4000";

/** One predicted overflight window (matches recon_windows row projection; times in unix seconds). */
export interface ReconWindow {
  norad_id: number;
  aoi_id: string;
  sensor_type: string;
  t_ingress: number;
  t_peak: number;
  t_egress: number;
  min_distance_km: number;
  sunlit_at_peak: boolean;
  quality: number;
}

/**
 * Compact "time-to-ingress" string for the countdown.
 * "now" if the window is here/past, else "in 45s" | "in 12m" | "in 2h 5m".
 */
export function formatEta(tIngress: number, now: number): string {
  const secs = Math.floor(tIngress - now);
  if (secs <= 0) return "now";
  if (secs < 60) return `in ${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `in ${mins}m`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `in ${hours}h ${remMins}m` : `in ${hours}h`;
}

/**
 * REST: upcoming windows ingressing in [from, to], optionally filtered by AOI.
 * Gracefully returns [] on a non-ok response or a thrown fetch (backend not up yet).
 */
export async function fetchReconWindows(opts: {
  aoi?: string;
  from: number;
  to: number;
}): Promise<ReconWindow[]> {
  const url = new URL(`${API_URL}/recon/windows`);
  url.searchParams.set("from", String(Math.floor(opts.from)));
  url.searchParams.set("to", String(Math.floor(opts.to)));
  if (opts.aoi) url.searchParams.set("aoi", opts.aoi);
  try {
    const res = await fetch(url.toString());
    if (!res.ok) return [];
    const body = (await res.json()) as { windows?: ReconWindow[] };
    return body.windows ?? [];
  } catch {
    return [];
  }
}

/**
 * REST: windows whose ingress falls within `leadSeconds` of now — the alertable set.
 * Gracefully returns [] on a non-ok response or a thrown fetch.
 */
export async function fetchReconAlerts(leadSeconds: number): Promise<ReconWindow[]> {
  const url = new URL(`${API_URL}/recon/alerts`);
  url.searchParams.set("lead", String(Math.floor(leadSeconds)));
  try {
    const res = await fetch(url.toString());
    if (!res.ok) return [];
    const body = (await res.json()) as { alerts?: ReconWindow[] };
    return body.alerts ?? [];
  } catch {
    return [];
  }
}
