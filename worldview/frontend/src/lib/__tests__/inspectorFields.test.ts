import { describe, expect, it } from "vitest";
import { buildInspectorView, formatDuration } from "../inspectorFields";

describe("formatDuration", () => {
  it("formats seconds, minutes and hours", () => {
    expect(formatDuration(30)).toBe("30s");
    expect(formatDuration(45 * 60)).toBe("45m");
    expect(formatDuration(3600)).toBe("1h 00m");
    expect(formatDuration(3840)).toBe("1h 04m");
  });
});

describe("buildInspectorView (spec §4 — humanized labels, never raw keys)", () => {
  it("aircraft: units on rows, military flagged in the kind tag", () => {
    const v = buildInspectorView(
      "adsb",
      { callsign: "UAE12", icao24: "ab1234", alt_m: 10670, gs_kt: 480, track_deg: 270, is_military: false },
      0,
    );
    expect(v.name).toBe("UAE12");
    expect(v.kind).toBe("AIRCRAFT");
    expect(v.glyph).toBe("civil");
    expect(v.rows.find((r) => r.label === "Altitude")?.value).toBe("10,670 m");
    expect(v.rows.find((r) => r.label === "Ground speed / track")?.value).toBe("480 kt · 270°");
    // No raw telemetry keys leak into labels.
    for (const r of v.rows) expect(r.label).not.toMatch(/_kt|_deg|_m$/);
  });

  it("military aircraft uses the hollow-chevron glyph", () => {
    const v = buildInspectorView("adsb", { icao24: "x", is_military: true }, 0);
    expect(v.kind).toContain("MILITARY");
    expect(v.glyph).toBe("mil");
  });

  it("dark vessel: ALERT CONTEXT leads — last fix, silence (red), dead-reckoned (amber)", () => {
    const v = buildInspectorView(
      "context",
      { kind: "dark_vessel", mmsi: "244660000", ts: 1765538463, gap_seconds: 3600, entity_id: "dv1" },
      1765542063,
    );
    expect(v.alert).toBe(true);
    expect(v.kind).toBe("DARK VESSEL · ALERT CONTEXT");
    expect(v.glyph).toBe("dark");
    expect(v.rows[0]?.label).toBe("Last AIS fix");
    const silent = v.rows.find((r) => r.label === "Silent for");
    expect(silent?.value).toBe("1h 00m");
    expect(silent?.tone).toBe("bad");
    const pos = v.rows.find((r) => r.label === "Position now");
    expect(pos?.value).toBe("dead-reckoned");
    expect(pos?.tone).toBe("warn");
  });

  it("satellite: sensor in the kind tag, lighting as words", () => {
    const v = buildInspectorView(
      "tle",
      { norad_id: 43437, sensor_type: "sar", velocity_kms: 7.61, is_sunlit: false },
      0,
    );
    expect(v.name).toBe("NORAD 43437");
    expect(v.kind).toBe("SATELLITE · SAR");
    expect(v.rows.find((r) => r.label === "Target lighting")?.value).toBe("☾ night");
  });

  it("unknown props surface as raw leftovers (transparency), hidden ones don't", () => {
    const v = buildInspectorView(
      "ais",
      { mmsi: "1", sog_kt: 10, cog_deg: 90, weird_field: 7, source: "demo", ingested_at: 123 },
      0,
    );
    const rawKeys = v.raw.map(([k]) => k);
    expect(rawKeys).toContain("weird_field");
    expect(rawKeys).not.toContain("source");
    expect(rawKeys).not.toContain("ingested_at");
  });
});
