import { describe, expect, it } from "vitest";
import { hexToRgb, MARK_HEX, MARK_RGB, type MarkKind } from "../markStyle";

describe("markStyle (spec §1.2 — the de-collided encodings)", () => {
  it("hexToRgb parses correctly", () => {
    expect(hexToRgb("#FF5A52")).toEqual([255, 90, 82]);
    expect(hexToRgb("#04070E")).toEqual([4, 7, 14]);
  });

  it("RGB table mirrors the hex table for every kind", () => {
    for (const kind of Object.keys(MARK_HEX) as MarkKind[]) {
      expect(MARK_RGB[kind]).toEqual(hexToRgb(MARK_HEX[kind]));
    }
  });

  it("red is reserved: only the dark-vessel mark uses the alert red", () => {
    const red = MARK_HEX.dark;
    const others = (Object.keys(MARK_HEX) as MarkKind[]).filter((k) => k !== "dark");
    for (const kind of others) expect(MARK_HEX[kind]).not.toBe(red);
  });

  it("military no longer collides with the alert color (amber, not red)", () => {
    expect(MARK_HEX.mil).toBe("#FFB23F");
    expect(MARK_HEX.mil).not.toBe(MARK_HEX.dark);
  });

  it("no mark uses the UI accent cyan", () => {
    for (const hex of Object.values(MARK_HEX)) {
      expect(hex.toLowerCase()).not.toBe("#2bb8f0");
      expect(hex.toLowerCase()).not.toBe("#8fe0ff");
    }
  });
});
