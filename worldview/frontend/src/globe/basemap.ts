import { env } from "@/lib/env";

// Which basemap this session draws — and the honest sentence the HUD prints about it.
//
// Cesium-free on purpose: this is the decision, not the rendering, so it stays unit-testable in
// a node environment and the status line can never disagree with what the viewer actually loads.

/** Colour grading applied to whichever basemap loads, so the HUD palette stays dominant. */
export const BASEMAP_GRADE = {
  brightness: 0.62,
  saturation: 0.45,
  contrast: 1.15,
  gamma: 1.1,
} as const;

export type BasemapKind = "ion" | "natural-earth";

export interface BasemapChoice {
  kind: BasemapKind;
  /** Short label for the basemap status line. */
  label: string;
  /** The honest one-liner: where the pixels come from and what it costs. */
  detail: string;
  /** Whether world terrain (3D relief) is available with this choice. */
  terrain: boolean;
}

/** The Cesium ion access token, or "" when the app is running credential-free. */
export function ionToken(): string {
  return env("VITE_CESIUM_ION_TOKEN").trim();
}

/**
 * The basemap for this session. With no token the globe still shows a real Earth: Cesium ships
 * Natural Earth II raster tiles inside the package, so coastlines and bathymetry render with no
 * account, no key and no network fetch. A token upgrades the same slot to ion world imagery plus
 * world terrain.
 */
export function basemapChoice(token = ionToken()): BasemapChoice {
  if (token.length > 0) {
    return {
      kind: "ion",
      label: "CESIUM ION · WORLD IMAGERY + TERRAIN",
      detail: "photographic basemap and 3D terrain, served from your Cesium ion account",
      terrain: true,
    };
  }
  return {
    kind: "natural-earth",
    label: "NATURAL EARTH II · BUNDLED, NO ACCOUNT",
    detail:
      "real coastlines and bathymetry from tiles bundled with Cesium — no token, no network fetch; add VITE_CESIUM_ION_TOKEN for imagery + terrain",
    terrain: false,
  };
}
