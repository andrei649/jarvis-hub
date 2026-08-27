import {
  Billboard,
  BillboardCollection,
  Cartesian2,
  Cartesian3,
  Color,
  ColorMaterialProperty,
  ConstantProperty,
  Entity,
  HeightReference,
  HorizontalOrigin,
  Label,
  LabelCollection,
  LabelStyle,
  Material,
  PointPrimitive,
  PointPrimitiveCollection,
  PolygonHierarchy,
  Polyline,
  PolylineCollection,
  VerticalOrigin,
  Math as CesiumMath,
  type ImageryLayer,
  type Viewer,
} from "cesium";
import type { LayerId } from "@/lib/layers";
import { markIcon } from "@/lib/markIcons";
import { createTileOverlay } from "./imagery";
import type { LabelDraw, PointDraw, PolygonDraw, PolylineDraw, Rgba, Scene } from "./scene";

// Applies a scene spec (src/globe/scene.ts) to Cesium. The ONLY module that knows how the marks
// reach the GPU; everything about what to draw was decided upstream, in plain data.
//
// Frames are diffed by id rather than rebuilt: at 4 Hz with tens of thousands of marks, clearing
// and repopulating the collections drops frames and makes every billboard re-request its image.
// Updating in place keeps the globe smooth while the master clock runs.

/** What a picked primitive carries back to the HUD (tooltip + selection). */
export interface PickPayload {
  layer: LayerId;
  props: Record<string, unknown>;
  trackId: string | null;
}

function color([r, g, b, a]: Rgba): Color {
  return new Color(r / 255, g / 255, b / 255, a / 255);
}

/** Ground-level marks clamp to terrain; airborne/orbital ones keep their true altitude. */
function heightReferenceFor(alt: number): HeightReference {
  return alt > 0 ? HeightReference.NONE : HeightReference.CLAMP_TO_GROUND;
}

class Marks {
  private readonly billboards = new Map<string, Billboard>();
  private readonly points = new Map<string, PointPrimitive>();

  constructor(
    private readonly billboardCollection: BillboardCollection,
    private readonly pointCollection: PointPrimitiveCollection,
  ) {}

  sync(draws: PointDraw[]): void {
    const seenBillboards = new Set<string>();
    const seenPoints = new Set<string>();

    for (const draw of draws) {
      const position = Cartesian3.fromDegrees(draw.lon, draw.lat, draw.alt);
      const id: PickPayload = { layer: draw.layer, props: draw.props, trackId: draw.trackId };
      const image = markIcon(draw.icon);

      if (image) {
        seenBillboards.add(draw.id);
        const existing = this.billboards.get(draw.id);
        const rotation = -CesiumMath.toRadians(draw.rotationDeg);
        if (existing) {
          existing.position = position;
          existing.image = image;
          existing.rotation = rotation;
          existing.id = id;
          existing.heightReference = heightReferenceFor(draw.alt);
        } else {
          this.billboards.set(
            draw.id,
            this.billboardCollection.add({
              position,
              image,
              id,
              rotation,
              width: draw.sizePx,
              height: draw.sizePx,
              alignedAxis: Cartesian3.ZERO, // screen-facing, so headings read as on a map
              heightReference: heightReferenceFor(draw.alt),
            }),
          );
        }
        continue;
      }

      // No canvas (headless / icon failure): a plain coloured point still shows the entity.
      seenPoints.add(draw.id);
      const existing = this.points.get(draw.id);
      if (existing) {
        existing.position = position;
        existing.color = color(draw.color);
        existing.id = id;
      } else {
        this.points.set(
          draw.id,
          this.pointCollection.add({
            position,
            id,
            color: color(draw.color),
            pixelSize: draw.sizePx / 2,
            heightReference: heightReferenceFor(draw.alt),
          }),
        );
      }
    }

    for (const [id, billboard] of this.billboards) {
      if (seenBillboards.has(id)) continue;
      this.billboardCollection.remove(billboard);
      this.billboards.delete(id);
    }
    for (const [id, point] of this.points) {
      if (seenPoints.has(id)) continue;
      this.pointCollection.remove(point);
      this.points.delete(id);
    }
  }
}

class Labels {
  private readonly labels = new Map<string, Label>();

  constructor(private readonly collection: LabelCollection) {}

  sync(draws: LabelDraw[]): void {
    const seen = new Set<string>();
    for (const draw of draws) {
      seen.add(draw.id);
      const position = Cartesian3.fromDegrees(draw.lon, draw.lat, 0);
      const fillColor = color(draw.color);
      const existing = this.labels.get(draw.id);
      if (existing) {
        existing.position = position;
        existing.text = draw.text;
        existing.fillColor = fillColor;
        continue;
      }
      this.labels.set(
        draw.id,
        this.collection.add({
          position,
          text: draw.text,
          font: `${draw.sizePx}px "JetBrains Mono", ui-monospace, monospace`,
          fillColor,
          style: LabelStyle.FILL_AND_OUTLINE,
          outlineColor: new Color(4 / 255, 7 / 255, 14 / 255, 0.86),
          outlineWidth: 2,
          horizontalOrigin: HorizontalOrigin.LEFT,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(9, -9),
          heightReference: HeightReference.CLAMP_TO_GROUND,
        }),
      );
    }
    for (const [id, label] of this.labels) {
      if (seen.has(id)) continue;
      this.collection.remove(label);
      this.labels.delete(id);
    }
  }
}

class Lines {
  private readonly lines = new Map<string, Polyline>();

  constructor(private readonly collection: PolylineCollection) {}

  sync(draws: PolylineDraw[]): void {
    const seen = new Set<string>();
    for (const draw of draws) {
      seen.add(draw.id);
      const positions = draw.positions.map(([lon, lat, alt]) =>
        Cartesian3.fromDegrees(lon, lat, alt),
      );
      const existing = this.lines.get(draw.id);
      if (existing) {
        existing.positions = positions;
        continue;
      }
      const stroke = color(draw.color);
      this.lines.set(
        draw.id,
        this.collection.add({
          positions,
          width: draw.width,
          material: draw.dashed
            ? Material.fromType("PolylineDash", { color: stroke, dashLength: 10 })
            : Material.fromType("Color", { color: stroke }),
        }),
      );
    }
    for (const [id, line] of this.lines) {
      if (seen.has(id)) continue;
      this.collection.remove(line);
      this.lines.delete(id);
    }
  }
}

class Polygons {
  private readonly entities = new Map<string, Entity>();

  constructor(
    private readonly viewer: Viewer,
    private readonly clampToGround: boolean,
  ) {}

  sync(draws: PolygonDraw[]): void {
    const seen = new Set<string>();
    for (const draw of draws) {
      const outer = draw.rings[0];
      if (!outer || outer.length < 3) continue;
      seen.add(draw.id);
      const positions = Cartesian3.fromDegreesArray(outer.flat());
      const existing = this.entities.get(draw.id);
      if (existing?.polygon) {
        existing.polygon.hierarchy = new ConstantProperty(new PolygonHierarchy(positions));
        if (draw.fill) existing.polygon.material = new ColorMaterialProperty(color(draw.fill));
        continue;
      }
      const entity = this.viewer.entities.add({
        id: `wv-poly-${draw.id}`,
        polygon: draw.fill
          ? {
              hierarchy: new PolygonHierarchy(positions),
              material: color(draw.fill),
              // Ground clamping needs terrain to clamp to; on the ellipsoid it's a flat draw.
              heightReference: this.clampToGround
                ? HeightReference.CLAMP_TO_GROUND
                : HeightReference.NONE,
              height: this.clampToGround ? undefined : 0,
            }
          : undefined,
        polyline: draw.outline
          ? {
              // The outline is its own polyline: Cesium's polygon `outline` is unreliable on
              // most platforms, and zone boundaries are load-bearing here (voided zones).
              positions: Cartesian3.fromDegreesArray([...outer, outer[0]!].flat()),
              width: draw.outlineWidth,
              material: color(draw.outline),
              clampToGround: this.clampToGround,
            }
          : undefined,
      });
      this.entities.set(draw.id, entity);
    }
    for (const [id, entity] of this.entities) {
      if (seen.has(id)) continue;
      this.viewer.entities.remove(entity);
      this.entities.delete(id);
    }
  }
}

/** Owns every Cesium collection the data layers draw into, and applies scene specs to them. */
export function createRenderer(viewer: Viewer, opts: { clampToGround: boolean }) {
  const scene = viewer.scene;
  const billboardCollection = scene.primitives.add(new BillboardCollection({ scene }));
  const pointCollection = scene.primitives.add(new PointPrimitiveCollection());
  const labelCollection = scene.primitives.add(new LabelCollection({ scene }));
  const polylineCollection = scene.primitives.add(new PolylineCollection());

  const marks = new Marks(billboardCollection, pointCollection);
  const labels = new Labels(labelCollection);
  const lines = new Lines(polylineCollection);
  const polygons = new Polygons(viewer, opts.clampToGround);

  let overlay: ImageryLayer | null = null;
  let overlayUrl: string | null = null;

  function syncOverlay(spec: Scene) {
    const wanted = spec.tileOverlay;
    if (wanted && wanted.data === overlayUrl) return;
    if (overlay) {
      viewer.imageryLayers.remove(overlay, true);
      overlay = null;
      overlayUrl = null;
    }
    if (!wanted) return;
    overlay = createTileOverlay(wanted);
    viewer.imageryLayers.add(overlay);
    overlayUrl = wanted.data;
  }

  return {
    apply(spec: Scene): void {
      marks.sync(spec.points);
      labels.sync(spec.labels);
      lines.sync(spec.polylines);
      polygons.sync(spec.polygons);
      syncOverlay(spec);
    },
  };
}
