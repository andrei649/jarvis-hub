// Provenance / chain-of-custody client (ticket H19.4.3 frontend): types + fetcher for the
// lineage of a selected entity's last-known datum, plus a compact UTC timestamp formatter.
// Mirrors the backend contract in backend-api/src/repositories/provenance.ts — times are UNIX
// seconds. The two-axis bitemporal pair: `ts` (valid time, when it was true in the world) vs
// `ingestedAt` (transaction time, when WorldView recorded it).

import type { LayerId } from "./layers";
import { apiUrl } from "./env";

/** Chain-of-custody of one entity's last-known datum at/<=T (times in unix seconds). */
export interface Provenance {
  layer: string;
  entityId: string;
  source: string;
  /** Valid time: the event's `ts` (when it was true in the world), UNIX seconds. */
  ts: number;
  /** Transaction time: when WorldView recorded the datum (`ingested_at`), UNIX seconds. */
  ingestedAt: number;
}

/**
 * Compact "YYYY-MM-DD HH:MM:SS UTC" for an epoch-seconds timestamp, matching the master-clock
 * readout in TimelineScrubber. Returns "—" for a missing/invalid value so callers can render it
 * inline without guarding.
 */
export function formatTs(epoch: number | null | undefined): string {
  if (epoch == null || !Number.isFinite(epoch)) return "—";
  return new Date(epoch * 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

/**
 * REST: chain-of-custody for `entityId` in `layer`, as-of optional T (unix seconds).
 * Returns the parsed provenance object, or null when the entity has no datum at/<=T, on a non-ok
 * response, or when fetch throws (backend not up yet). Never throws.
 */
export async function fetchProvenance(
  layer: LayerId,
  entityId: string,
  t?: number,
): Promise<Provenance | null> {
  const url = new URL(`${apiUrl()}/provenance/${layer}/${encodeURIComponent(entityId)}`);
  if (t != null) url.searchParams.set("t", String(Math.floor(t)));
  try {
    const res = await fetch(url.toString());
    if (!res.ok) return null;
    const body = (await res.json()) as { provenance?: Provenance | null };
    return body.provenance ?? null;
  } catch {
    return null;
  }
}
