// Single source of truth for the map's mark encodings (spec §1.2): every mark pairs a SHAPE
// with a color so no state is communicated by color alone, and the legend/stats glyphs render
// from the same table the globe's marks do. Red means exactly one thing — something is wrong
// (dark vessel, alert, offline); military is amber caution; no mark uses the UI accent cyan.

export type MarkKind = "civil" | "mil" | "vessel" | "dark" | "sat" | "intel" | "jam";

/** Hex per mark kind — mirrors the mock's --mk-* tokens 1:1. */
export const MARK_HEX: Record<MarkKind, string> = {
  civil: "#7FB4E8", // filled chevron — steel blue (was dot ≈ accent collision)
  mil: "#FFB23F", //   hollow chevron — amber caution (was red ≈ alert collision)
  vessel: "#5FE0B0", // filled diamond — seafoam
  dark: "#FF5A52", //  hollow ring — red, the alert color
  sat: "#E8D27A", //   ringed dot — gold
  intel: "#A78BFA", // filled square / dashed zone — violet
  jam: "#FF8C28", //   H3 hex ramp endpoint — orange
};

/** Parse #RRGGBB to an RGB triple. */
export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

export const MARK_RGB: Record<MarkKind, [number, number, number]> = {
  civil: hexToRgb(MARK_HEX.civil),
  mil: hexToRgb(MARK_HEX.mil),
  vessel: hexToRgb(MARK_HEX.vessel),
  dark: hexToRgb(MARK_HEX.dark),
  sat: hexToRgb(MARK_HEX.sat),
  intel: hexToRgb(MARK_HEX.intel),
  jam: hexToRgb(MARK_HEX.jam),
};
