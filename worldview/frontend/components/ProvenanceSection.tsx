"use client";

import { useEffect, useState } from "react";
import type { LayerId } from "@/lib/layers";
import { fetchProvenance, type Provenance } from "@/lib/provenance";

// Provenance / chain-of-custody (H19.4.3 frontend, restyled per spec §4): the bitemporal pair
// in PLAIN WORDS — "Reported by {source} — true at {valid time}, recorded by WorldView at
// {transaction time}." — instead of unexplained "valid time / transaction time" jargon.
//
// Two sources of truth, in order of authority:
//  1. The selected feature already carries `properties.source` + `properties.ingested_at` —
//     shown immediately, no network needed.
//  2. The authoritative last-known custody at the master time via /provenance/:layer/:id?t=,
//     bucketed (~60s) like the recon panel so we don't refetch storms.

function utc(ts: number | undefined): string | null {
  if (ts == null || !Number.isFinite(ts) || ts <= 0) return null;
  return `${new Date(ts * 1000).toISOString().slice(11, 19)} UTC`;
}

export function ProvenanceSection({
  layer,
  entityId,
  masterTime,
  featureSource,
  featureIngestedAt,
  deadReckoned = false,
}: {
  layer: LayerId;
  entityId: string;
  masterTime: number;
  /** `properties.source` carried by the selected feature, if present. */
  featureSource?: unknown;
  /** `properties.ingested_at` carried by the selected feature (unix seconds), if present. */
  featureIngestedAt?: unknown;
  /** Dark vessels: append the dead-reckoning caveat to the custody sentence. */
  deadReckoned?: boolean;
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

  const featSource = typeof featureSource === "string" ? featureSource : undefined;
  const featIngested = typeof featureIngestedAt === "number" ? featureIngestedAt : undefined;

  const source = prov?.source ?? featSource;
  const validTime = utc(prov?.ts ?? undefined);
  const txTime = utc(prov?.ingestedAt ?? featIngested);

  const unknown = source == null && validTime == null && txTime == null;

  // Compose the plain-words custody sentence from whatever pieces exist.
  let sentence: string;
  if (unknown) {
    sentence = "Provenance unknown — this datum carries no source or custody record.";
  } else {
    const reporter = source ? `Reported by ${source}` : "Reported by an unrecorded source";
    const valid = validTime ? ` — true at ${validTime}` : "";
    const recorded = txTime ? `, recorded by WorldView at ${txTime}` : "";
    sentence = `${reporter}${valid}${recorded}.`;
    if (deadReckoned) sentence += " Position since then is estimated from last course and speed.";
  }

  return (
    <div className="mt-2.5 rounded-md border border-signal-dim bg-signal-faint px-2.5 py-2">
      <div className="font-mono text-[8px] tracking-[.14em] text-signal-light">
        PROVENANCE · CHAIN OF CUSTODY
      </div>
      <div className="mt-1 text-[10.5px] leading-relaxed text-ink/65">{sentence}</div>
    </div>
  );
}
