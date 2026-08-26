import { describe, expect, it } from "vitest";
import { deriveUiMode, isDemoFeed, MODE_META, type UiMode } from "../uiMode";
import { emptyCollection, type FeatureCollection } from "../types";

function fc(sources: (string | undefined)[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: sources.map((source) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [0, 0] },
      properties: source === undefined ? {} : { source },
    })),
  };
}

describe("isDemoFeed", () => {
  it("is false with no data at all (an empty screen is OFFLINE/empty, not DEMO)", () => {
    expect(isDemoFeed({ adsb: emptyCollection() })).toBe(false);
  });

  it("is true when rows are tagged source='demo'", () => {
    expect(isDemoFeed({ ais: fc(["demo", "demo"]) })).toBe(true);
  });

  it("is true on a MIXED feed — honesty wins when demo rows blend with real ones", () => {
    expect(isDemoFeed({ ais: fc(["aisstream", "demo"]) })).toBe(true);
  });

  it("is false for a purely real feed", () => {
    expect(isDemoFeed({ ais: fc(["aisstream", undefined]) })).toBe(false);
  });
});

describe("deriveUiMode", () => {
  const base = {
    mode: "live" as const,
    liveConnection: "open" as const,
    replaying: false,
    replayArmed: false,
    demoFeed: false,
  };

  it("live feed, healthy socket → LIVE", () => {
    expect(deriveUiMode(base)).toBe("live");
  });

  it("demo rows on screen → DEMO (never silently LIVE)", () => {
    expect(deriveUiMode({ ...base, demoFeed: true })).toBe("demo");
  });

  it("closed socket in live mode → OFFLINE", () => {
    expect(deriveUiMode({ ...base, liveConnection: "closed" })).toBe("offline");
  });

  it("scrubbed into the past → HISTORICAL", () => {
    expect(deriveUiMode({ ...base, mode: "historical" })).toBe("historical");
  });

  it("an active replay wins over everything", () => {
    expect(deriveUiMode({ ...base, mode: "historical", replaying: true, demoFeed: true })).toBe(
      "replay",
    );
  });

  it("an armed arrival window in historical declares REPLAY from the first frame (§5.1)", () => {
    expect(deriveUiMode({ ...base, mode: "historical", replayArmed: true })).toBe("replay");
  });

  it("an armed window does NOT claim REPLAY while live (never fake state)", () => {
    expect(deriveUiMode({ ...base, replayArmed: true })).toBe("live");
  });

  it("every mode has display metadata", () => {
    const modes: UiMode[] = ["live", "demo", "historical", "replay", "offline"];
    for (const m of modes) {
      expect(MODE_META[m].label).toBeTruthy();
      expect(MODE_META[m].frame).toContain("border-");
    }
  });
});
