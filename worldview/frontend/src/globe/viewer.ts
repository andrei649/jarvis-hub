import {
  Color,
  Ion,
  JulianDate,
  Terrain,
  Viewer,
  type ImageryLayer,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { basemapChoice, ionToken, type BasemapChoice } from "./basemap";
import { createBaseImagery } from "./imagery";

// Viewer construction: a Cesium globe with every stock widget off, because WorldView supplies
// its own HUD. Two things here are load-bearing beyond "make a viewer":
//
//  1. The basemap is chosen credential-free by default (see ./imagery.ts).
//  2. Globe lighting is ON and the scene clock is driven by the MASTER clock, so scrubbing time
//     moves the day/night terminator with the data. The 4D contract becomes visible on the
//     globe itself, not just in the panels.

export interface Globe {
  viewer: Viewer;
  choice: BasemapChoice;
  baseLayer: ImageryLayer;
  /** Point the scene's sun/terminator at a master-clock timestamp (UNIX seconds). */
  setSceneTime: (unixSeconds: number) => void;
  destroy: () => void;
}

const SPACE = Color.fromCssColorString("#04070E");
const OCEAN = Color.fromCssColorString("#0A121C");

/**
 * Build the globe. Throws when WebGL is unavailable — the caller renders the diagnosis card
 * rather than leaving a black screen (the failure mode the old error boundary existed for).
 */
export function createGlobe(container: HTMLElement, creditContainer: HTMLElement): Globe {
  const token = ionToken();
  if (token) Ion.defaultAccessToken = token;
  const choice = basemapChoice(token);
  const baseLayer = createBaseImagery(choice);

  const viewer = new Viewer(container, {
    baseLayer,
    // World terrain needs an ion account; without one the ellipsoid is the terrain.
    terrain: choice.terrain ? Terrain.fromWorldTerrain() : undefined,
    creditContainer,
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    shouldAnimate: false, // the master clock drives scene time; Cesium never animates on its own
  });

  const scene = viewer.scene;
  scene.backgroundColor = SPACE;
  scene.globe.baseColor = OCEAN;
  // Sunlight on the globe: the terminator is a function of scene time, which we bind to the
  // master clock below, so the lit hemisphere is always the one the current timestamp implies.
  scene.globe.enableLighting = true;
  scene.globe.showGroundAtmosphere = true;
  scene.highDynamicRange = false;
  scene.fog.enabled = true;
  // Cesium's default double-click "zoom to entity" fights our own selection handling.
  scene.screenSpaceCameraController.enableLook = true;

  return {
    viewer,
    choice,
    baseLayer,
    setSceneTime(unixSeconds: number) {
      if (!Number.isFinite(unixSeconds)) return;
      viewer.clock.currentTime = JulianDate.fromDate(new Date(unixSeconds * 1000));
    },
    destroy() {
      viewer.destroy();
    },
  };
}
