// The five WorldView data layers (design doc §1). Shared by the store and the map.
export const LAYER_IDS = [
  "adsb", // A — Aerospace
  "ais", // B — Maritime (+ dark vessels)
  "tle", // C — Space (satellites + footprints)
  "ew", // D — Cyber & EW (H3 jamming / blackouts)
  "context", // E — Contextual intel (NOTAMs, zones, events)
] as const;

export type LayerId = (typeof LAYER_IDS)[number];

export function isLayer(value: string): value is LayerId {
  return (LAYER_IDS as readonly string[]).includes(value);
}
