"use client";

import { useEffect, useState } from "react";
import type { LayerId } from "@/lib/layers";
import { fetchProvenance, formatTs, type Provenance } from "@/lib/provenance";

// Provenance / chain-of-custody block for the Inspector (ticket H19.4.3 frontend). Shows where the
// selected entity's datum came from and the bitemporal pair behind it: valid time (`ts`, when it
// was true) vs transaction time (`ingested_at`, when WorldView recorded it).
//
// Two sources of truth, in order of authority:
//  1. The selected feature already carries `properties.source` + `properties.ingested_at` — shown
//     immediately, no network needed.
//  2. We also resolve the authoritative last-known custody at the master time via
//     /provenance/:layer/:entityId?t=, bucketed (~60s) like ReconPanel so we don't refetch storms.

export function ProvenanceSection({
  layer,
  entityId,
  masterTime,
  featureSource,
  featureIngestedAt,
}: {
  layer: LayerId;
  entityId: string;
  masterTime: number;
  /** `properties.source` carried by the selected feature, if present. */
  featureSource?: unknown;
  /** `properties.ingested_at` carried by the selected feature (unix seconds), if present. */
  featureIngestedAt?: unknown;
}) {
  const [prov, setProv] = useState<Provenance | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchProvenance(layer, entityId, masterTime).then((p) => {
      if (!cancelled) setProv(p);
    });
    return () => {
      cancelled = true;
    };
    // Refetch only when the selection or a coarse (~60s) time bucket changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layer, entityId, Math.floor(masterTime / 60)]);

  // The feature-carried lineage (instant, no network). Authoritative custody (from the endpoint)
  // wins for source/valid-time/transaction-time when available.
  const featSource = typeof featureSource === "string" ? featureSource : undefined;
  const featIngested = typeof featureIngestedAt === "number" ? featureIngestedAt : undefined;

  const source = prov?.source ?? featSource;
  const validTime = prov?.ts ?? undefined;
  const txTime = prov?.ingestedAt ?? featIngested;

  const unknown = source == null && validTime == null && txTime == null;

  return (
    <div className="mt-2 border-t border-white/10 pt-2">
      <div className="mb-1 font-semibold text-signal/90">Provenance · chain-of-custody</div>
      {unknown ? (
        <div className="text-white/50">provenance unknown</div>
      ) : (
        <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5">
          <dt className="text-white/45">source</dt>
          <dd className="truncate text-right font-mono text-white/85">{source ?? "—"}</dd>
          <dt className="text-white/45">valid time</dt>
          <dd className="truncate text-right font-mono text-white/85">{formatTs(validTime)}</dd>
          <dt className="text-white/45">transaction time</dt>
          <dd className="truncate text-right font-mono text-white/85">{formatTs(txTime)}</dd>
        </dl>
      )}
    </div>
  );
}
