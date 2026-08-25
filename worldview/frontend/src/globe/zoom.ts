// Camera height ⇄ slippy-map zoom.
//
// WorldView's level-of-detail contract is expressed in web-map zoom levels (the API asks for
// `lod=minute` below zoom 5; the tile switch fires at/below zoom 6). Cesium has no zoom level —
// it has a camera at a height in metres — so the two are related through ground resolution:
//
//   metres-per-pixel at zoom z, latitude φ  =  156543.03392 · cos φ / 2^z
//   metres-per-pixel from the camera        =  2 · h · tan(fovY / 2) / viewportHeightPx
//
// Equating them and solving for z gives the conversion below. Pure and unit-tested, so the LOD
// thresholds keep meaning exactly what they meant on the previous renderer.

/** Ground resolution in metres/pixel at zoom 0 on the equator (256 px tiles). */
export const EQUATOR_RESOLUTION = 156543.03392;

const MIN_ZOOM = 0;
const MAX_ZOOM = 22;

export interface ZoomFromCameraOpts {
  /** Camera height above the ellipsoid, in metres. */
  heightMeters: number;
  /** Canvas height in CSS pixels. */
  viewportHeightPx: number;
  /** Vertical field of view, radians. Cesium's default is π/3. */
  fovY: number;
  /** Camera latitude in degrees (resolution shrinks with cos φ). */
  latitudeDeg: number;
}

/**
 * The slippy-map zoom level equivalent to a Cesium camera pose. Clamped to [0, 22]; a
 * non-finite or non-positive height yields 0 (fully zoomed out), never NaN.
 */
export function zoomFromCamera(opts: ZoomFromCameraOpts): number {
  const { heightMeters, viewportHeightPx, fovY, latitudeDeg } = opts;
  if (!Number.isFinite(heightMeters) || heightMeters <= 0) return MIN_ZOOM;
  if (!Number.isFinite(viewportHeightPx) || viewportHeightPx <= 0) return MIN_ZOOM;
  const metresPerPixel = (2 * heightMeters * Math.tan(fovY / 2)) / viewportHeightPx;
  if (!Number.isFinite(metresPerPixel) || metresPerPixel <= 0) return MAX_ZOOM;
  const cosLat = Math.cos((Math.min(85, Math.abs(latitudeDeg)) * Math.PI) / 180);
  const zoom = Math.log2((EQUATOR_RESOLUTION * cosLat) / metresPerPixel);
  if (!Number.isFinite(zoom)) return MIN_ZOOM;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

/**
 * The inverse: the camera height that renders a given zoom level. Used to honour the camera
 * poses in the tour/arrival specs, which are authored in zoom levels.
 */
export function cameraHeightForZoom(
  zoom: number,
  opts: { viewportHeightPx: number; fovY: number; latitudeDeg: number },
): number {
  const { viewportHeightPx, fovY, latitudeDeg } = opts;
  const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number.isFinite(zoom) ? zoom : 0));
  const cosLat = Math.cos((Math.min(85, Math.abs(latitudeDeg)) * Math.PI) / 180);
  const metresPerPixel = (EQUATOR_RESOLUTION * cosLat) / 2 ** clamped;
  return (metresPerPixel * viewportHeightPx) / (2 * Math.tan(fovY / 2));
}
