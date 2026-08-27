import {
  ImageryLayer,
  IonWorldImageryStyle,
  TileMapServiceImageryProvider,
  UrlTemplateImageryProvider,
  buildModuleUrl,
  createWorldImageryAsync,
} from "cesium";
import type { TileLayerProps } from "@/lib/tiles";
import { BASEMAP_GRADE, basemapChoice, type BasemapChoice } from "./basemap";

// Turning the basemap decision (./basemap.ts) into actual Cesium imagery layers.
//
// The token-less path is the interesting one: `buildModuleUrl("Assets/Textures/NaturalEarthII")`
// resolves inside the Cesium assets mirrored into public/ by plugins/cesium.ts, so the globe
// renders real continents from local files — no key, no account, no network fetch. That is what
// replaced the hand-drawn 110 m coastline TopoJSON the previous renderer bundled.

export { BASEMAP_GRADE, basemapChoice, ionToken } from "./basemap";
export type { BasemapChoice, BasemapKind } from "./basemap";

/** Apply the WorldView grade to an imagery layer (safe to call on any layer). */
export function gradeLayer(layer: ImageryLayer): ImageryLayer {
  layer.brightness = BASEMAP_GRADE.brightness;
  layer.saturation = BASEMAP_GRADE.saturation;
  layer.contrast = BASEMAP_GRADE.contrast;
  layer.gamma = BASEMAP_GRADE.gamma;
  return layer;
}

/** Cesium's bundled Natural Earth II tiles — the keyless basemap. */
export function naturalEarthProvider(): Promise<TileMapServiceImageryProvider> {
  return TileMapServiceImageryProvider.fromUrl(buildModuleUrl("Assets/Textures/NaturalEarthII"));
}

/**
 * The base imagery layer for this session: ion world imagery when a token is configured,
 * Cesium's bundled Natural Earth II otherwise. If ion imagery fails to load (bad token, offline)
 * it falls back to the bundled tiles, because a blank blue ball is the one outcome the basemap
 * must never produce.
 */
export function createBaseImagery(choice: BasemapChoice = basemapChoice()): ImageryLayer {
  const provider =
    choice.kind === "ion"
      ? createWorldImageryAsync({ style: IonWorldImageryStyle.AERIAL }).catch(() =>
          naturalEarthProvider(),
        )
      : naturalEarthProvider();
  return gradeLayer(ImageryLayer.fromProviderAsync(provider, {}));
}

/**
 * The pre-aggregated raster overlay (H19.5.1) drawn over the basemap when the globe is zoomed
 * out. Only raster templates reach here — `lib/tiles.ts` refuses vector ones, which Cesium's
 * imagery pipeline cannot decode.
 */
export function createTileOverlay(props: TileLayerProps): ImageryLayer {
  return new ImageryLayer(
    new UrlTemplateImageryProvider({
      url: props.data,
      minimumLevel: Math.max(0, Math.floor(props.minZoom)),
      maximumLevel: Math.max(0, Math.floor(props.maxZoom)),
    }),
    { alpha: 0.85 },
  );
}
