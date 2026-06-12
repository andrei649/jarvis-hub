// The mode system's single derivation (spec §3.3): one UiMode drives the mode frame, the
// app-bar pill, and the timeline's restatement, so the three signals can never disagree.
// Honesty rules (brief §7): DEMO is bound to the FEED (source='demo' rows), never to an env
// flag; OFFLINE is never dressed up as live; REPLAY is declared from the first frame.

import type { LiveConnectionState, PlaybackMode } from "./store/useTimelineStore";
import type { FeatureCollection } from "./types";

export type UiMode = "live" | "demo" | "historical" | "replay" | "offline";

/** True when the data on screen is the synthetic demo feed (rows tagged source='demo'). */
export function isDemoFeed(layers: Record<string, FeatureCollection>): boolean {
  let total = 0;
  let demo = 0;
  for (const fc of Object.values(layers)) {
    for (const f of fc.features) {
      total += 1;
      if (f.properties?.source === "demo") demo += 1;
    }
  }
  // Any demo-tagged rows badge the screen as DEMO: when feeds mix, honesty wins over flattery.
  return total > 0 && demo > 0;
}

export function deriveUiMode(opts: {
  mode: PlaybackMode;
  liveConnection: LiveConnectionState;
  /** A replay is actively driving the master clock. */
  replaying: boolean;
  /** An arrival deep-link pre-armed a replay window (mode REPLAY from the first frame, §5.1). */
  replayArmed: boolean;
  demoFeed: boolean;
}): UiMode {
  if (opts.replaying || (opts.replayArmed && opts.mode === "historical")) return "replay";
  if (opts.mode === "historical") return "historical";
  if (opts.liveConnection === "closed") return "offline";
  if (opts.demoFeed) return "demo";
  return "live";
}

/** Display metadata per mode: label + the tint classes each surface reuses. */
export const MODE_META: Record<
  UiMode,
  { label: string; frame: string; pill: string; dot: string }
> = {
  live: {
    label: "LIVE",
    frame: "border-green/55",
    pill: "border-green/40 bg-green/10 text-green",
    dot: "bg-green",
  },
  demo: {
    label: "DEMO",
    frame: "border-amber/60",
    pill: "border-amber/45 bg-amber/10 text-amber",
    dot: "bg-amber",
  },
  historical: {
    label: "HISTORICAL",
    frame: "border-signal/60",
    pill: "border-signal-dim bg-signal-faint text-signal-light",
    dot: "bg-signal-light",
  },
  replay: {
    label: "REPLAY",
    frame: "border-violet/65",
    pill: "border-violet/45 bg-violet/10 text-violet",
    dot: "bg-violet",
  },
  offline: {
    label: "OFFLINE",
    frame: "border-red/60",
    pill: "border-red/45 bg-red/10 text-red",
    dot: "bg-red",
  },
};
