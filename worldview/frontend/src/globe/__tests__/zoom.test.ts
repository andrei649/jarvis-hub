import { describe, expect, it } from "vitest";
import { cameraHeightForZoom, zoomFromCamera, EQUATOR_RESOLUTION } from "../zoom";

// The LOD contract is written in slippy-map zoom levels; Cesium only knows camera heights. These
// guard the conversion, because getting it wrong silently changes when the API is asked for
// minute rollups and when the tile overlay takes over.

const VIEWPORT = 900;
const FOV = Math.PI / 3;

describe("zoomFromCamera", () => {
  it("round-trips against cameraHeightForZoom", () => {
    for (const zoom of [0, 1, 3.5, 6, 12, 18]) {
      const height = cameraHeightForZoom(zoom, {
        viewportHeightPx: VIEWPORT,
        fovY: FOV,
        latitudeDeg: 26.6,
      });
      const back = zoomFromCamera({
        heightMeters: height,
        viewportHeightPx: VIEWPORT,
        fovY: FOV,
        latitudeDeg: 26.6,
      });
      expect(back).toBeCloseTo(zoom, 6);
    }
  });

  it("increases as the camera descends", () => {
    const high = zoomFromCamera({ heightMeters: 20_000_000, viewportHeightPx: VIEWPORT, fovY: FOV, latitudeDeg: 0 });
    const low = zoomFromCamera({ heightMeters: 5_000, viewportHeightPx: VIEWPORT, fovY: FOV, latitudeDeg: 0 });
    expect(low).toBeGreaterThan(high);
  });

  it("matches the tile-resolution definition at the equator", () => {
    // At zoom 0 the whole world is one 256 px tile: metres/pixel = EQUATOR_RESOLUTION.
    const height = (EQUATOR_RESOLUTION * VIEWPORT) / (2 * Math.tan(FOV / 2));
    expect(
      zoomFromCamera({ heightMeters: height, viewportHeightPx: VIEWPORT, fovY: FOV, latitudeDeg: 0 }),
    ).toBeCloseTo(0, 6);
  });

  it("clamps to [0, 22] and never returns NaN", () => {
    const bad = [Number.NaN, 0, -1, Number.POSITIVE_INFINITY];
    for (const heightMeters of bad) {
      const zoom = zoomFromCamera({ heightMeters, viewportHeightPx: VIEWPORT, fovY: FOV, latitudeDeg: 0 });
      expect(Number.isFinite(zoom)).toBe(true);
      expect(zoom).toBeGreaterThanOrEqual(0);
      expect(zoom).toBeLessThanOrEqual(22);
    }
    expect(
      zoomFromCamera({ heightMeters: 1, viewportHeightPx: 0, fovY: FOV, latitudeDeg: 0 }),
    ).toBe(0);
    expect(
      zoomFromCamera({ heightMeters: 0.000001, viewportHeightPx: VIEWPORT, fovY: FOV, latitudeDeg: 0 }),
    ).toBeLessThanOrEqual(22);
  });

  it("accounts for latitude — the same height reads as a higher zoom near the poles", () => {
    const equator = zoomFromCamera({ heightMeters: 500_000, viewportHeightPx: VIEWPORT, fovY: FOV, latitudeDeg: 0 });
    const north = zoomFromCamera({ heightMeters: 500_000, viewportHeightPx: VIEWPORT, fovY: FOV, latitudeDeg: 70 });
    expect(equator).toBeGreaterThan(north);
  });
});
