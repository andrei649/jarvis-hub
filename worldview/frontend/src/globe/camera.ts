import {
  Cartesian3,
  HeadingPitchRange,
  Matrix4,
  PerspectiveFrustum,
  SceneMode,
  Math as CesiumMath,
  type Viewer,
} from "cesium";
import type { TourViewState } from "@/lib/cameraTour";
import type { ViewMode } from "@/lib/store/timelineStore";
import { cameraHeightForZoom, zoomFromCamera } from "./zoom";

// The camera driver: everything that moves the eye — arrival fly-tos, the AOI tour, the follow
// lock on a selected entity, the 2.5D ⇄ 3D morph — plus the zoom feedback the level-of-detail
// system reads. Camera poses arrive in the same {longitude, latitude, zoom, pitch} shape the
// tour model has always produced; the conversion to a Cesium height lives in ./zoom.ts.

/** Pitch convention conversion: 0 = straight down in the tour model, -90° in Cesium. */
function cesiumPitchDegrees(tourPitch: number | undefined): number {
  return -(90 - (tourPitch ?? 0));
}

/**
 * The opening pose: the platform's reference choke point, framed. Zoom is in the tour model's
 * units — ~3 frames the globe, ~6 is a regional view — and the projection picks which one, so
 * 3D opens on the whole sphere and 2.5D opens on the AOI.
 */
export const AOI_VIEW = { longitude: 56.4, latitude: 26.6, globeZoom: 3, mapZoom: 6 } as const;

export interface CameraTarget {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch?: number;
  bearing?: number;
  /** Flight time in ms; 0 flies instantly. */
  transitionDuration?: number;
}

export function createCameraDriver(viewer: Viewer, onZoomChange: (zoom: number) => void) {
  const camera = viewer.camera;
  let following = false;

  function viewportHeight(): number {
    return viewer.canvas.clientHeight || viewer.canvas.height || 1;
  }

  /** Vertical field of view; the 2D/Columbus frustum is orthographic and has none. */
  function fovY(): number {
    const frustum = viewer.scene.camera.frustum;
    const fov = frustum instanceof PerspectiveFrustum ? frustum.fov : undefined;
    return typeof fov === "number" && Number.isFinite(fov) ? fov : Math.PI / 3;
  }

  function currentZoom(): number {
    const carto = camera.positionCartographic;
    return zoomFromCamera({
      heightMeters: carto.height,
      viewportHeightPx: viewportHeight(),
      fovY: fovY(),
      latitudeDeg: CesiumMath.toDegrees(carto.latitude),
    });
  }

  function heightFor(zoom: number, latitudeDeg: number): number {
    return cameraHeightForZoom(zoom, {
      viewportHeightPx: viewportHeight(),
      fovY: fovY(),
      latitudeDeg,
    });
  }

  // Report zoom whenever the camera settles, so the LOD selector and the tile switch follow the
  // real view rather than a stored guess.
  camera.changed.addEventListener(() => onZoomChange(currentZoom()));
  // Cesium only fires `changed` past a percentage of movement; a small threshold keeps the LOD
  // responsive during a slow zoom without firing on every frame of a pan.
  camera.percentageChanged = 0.2;

  return {
    currentZoom,

    /** Fly to a pose expressed in the tour model's units. */
    flyTo(target: CameraTarget): void {
      this.stopFollowing();
      viewer.camera.flyTo({
        destination: Cartesian3.fromDegrees(
          target.longitude,
          target.latitude,
          heightFor(target.zoom, target.latitude),
        ),
        orientation: {
          heading: CesiumMath.toRadians(target.bearing ?? 0),
          pitch: CesiumMath.toRadians(cesiumPitchDegrees(target.pitch)),
          roll: 0,
        },
        duration: Math.max(0, (target.transitionDuration ?? 1200) / 1000),
      });
    },

    /** Fly to a tour step's pose (same shape the tour model has always emitted). */
    flyToTourStep(viewState: TourViewState): void {
      this.flyTo(viewState);
    },

    /**
     * Lock the camera onto a position and hold the current heading/pitch/range. Called on every
     * data frame while follow is on, so the eye tracks a moving entity.
     */
    follow(lon: number, lat: number, alt: number): void {
      const center = Cartesian3.fromDegrees(lon, lat, alt);
      const range = following
        ? camera.positionCartographic.height
        : Math.max(2000, camera.positionCartographic.height * 0.6);
      following = true;
      camera.lookAt(center, new HeadingPitchRange(camera.heading, camera.pitch, range));
    },

    /** Release the follow lock and hand the camera back to the user. */
    stopFollowing(): void {
      if (!following) return;
      following = false;
      camera.lookAtTransform(Matrix4.IDENTITY);
    },

    get isFollowing(): boolean {
      return following;
    },

    /**
     * Frame the AOI on startup. Without this the session opens wherever Cesium's default camera
     * happens to point — which at most times of day is the unlit half of the planet.
     */
    openOnAoi(mode: ViewMode): void {
      this.flyTo({
        longitude: AOI_VIEW.longitude,
        latitude: AOI_VIEW.latitude,
        zoom: mode === "globe" ? AOI_VIEW.globeZoom : AOI_VIEW.mapZoom,
        pitch: 0,
        transitionDuration: 0,
      });
      onZoomChange(currentZoom());
    },

    /** 2.5D flattened map ⇄ 3D globe. */
    setViewMode(mode: ViewMode): void {
      const wanted = mode === "globe" ? SceneMode.SCENE3D : SceneMode.COLUMBUS_VIEW;
      if (viewer.scene.mode === wanted) return;
      this.stopFollowing();
      if (wanted === SceneMode.SCENE3D) viewer.scene.morphTo3D(1.0);
      else viewer.scene.morphToColumbusView(1.0);
    },
  };
}

export type CameraDriver = ReturnType<typeof createCameraDriver>;
