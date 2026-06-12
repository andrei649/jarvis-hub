import { describe, expect, it } from "vitest";
import { parseArrival } from "../arrival";

describe("parseArrival (spec §5.1 — the deep-link contract)", () => {
  it("returns null without a from/to window", () => {
    expect(parseArrival("")).toBeNull();
    expect(parseArrival("?agent=argus")).toBeNull();
    expect(parseArrival("?from=100")).toBeNull();
  });

  it("a bare ?from&to is a silent window restore, NOT an arrival (no invented story)", () => {
    const p = parseArrival("?from=100&to=200");
    expect(p).not.toBeNull();
    expect(p!.window).toMatchObject({ from: 100, to: 200 });
    expect(p!.isArrival).toBe(false);
    expect(p!.entity).toBeNull();
    expect(p!.agent).toBeNull();
    // Absent lon/lat must not become a (0,0) camera target.
    expect(p!.view).toBeNull();
  });

  it("agent + entity + camera make a full arrival", () => {
    const p = parseArrival("?from=100&to=200&layer=ais&id=244660000&lon=56.4&lat=26.3&zoom=8&agent=argus");
    expect(p!.isArrival).toBe(true);
    expect(p!.agent).toBe("ARGUS");
    expect(p!.entity).toEqual({ layer: "ais", id: "244660000" });
    expect(p!.view).toEqual({ longitude: 56.4, latitude: 26.3, zoom: 8 });
  });

  it("an entity alone is enough to be an arrival; an invalid layer is rejected", () => {
    expect(parseArrival("?from=1&to=2&layer=ais&id=7")!.isArrival).toBe(true);
    expect(parseArrival("?from=1&to=2&layer=bogus&id=7")!.entity).toBeNull();
    expect(parseArrival("?from=1&to=2&layer=bogus&id=7")!.isArrival).toBe(false);
  });

  it("camera defaults zoom to 8 when omitted; non-finite coords are dropped", () => {
    expect(parseArrival("?from=1&to=2&lon=56&lat=26")!.view).toEqual({
      longitude: 56,
      latitude: 26,
      zoom: 8,
    });
    expect(parseArrival("?from=1&to=2&lon=abc&lat=26")!.view).toBeNull();
  });
});
