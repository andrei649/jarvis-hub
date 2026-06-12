// Runtime-generated icon atlas for the map marks (spec §1.2): the same shapes the legend's
// MarkGlyph renders, drawn once onto a canvas and handed to deck.gl's icon point type. Colors
// are baked per kind (mask:false). When no canvas exists (SSR, vitest's node env, a headless
// failure) `getMarkAtlas()` returns null and deckLayers falls back to the circle rendering, so
// the map never goes blank because of the atlas.

import { MARK_HEX, type MarkKind } from "./markStyle";

export type IconName = Exclude<MarkKind, "jam"> | "ghost";

const CELL = 64; // px per icon cell
const ICONS: IconName[] = ["civil", "mil", "vessel", "dark", "sat", "intel", "ghost"];

export const ICON_MAPPING: Record<
  IconName,
  { x: number; y: number; width: number; height: number; mask: false }
> = Object.fromEntries(
  ICONS.map((name, i) => [name, { x: i * CELL, y: 0, width: CELL, height: CELL, mask: false }]),
) as Record<IconName, { x: number; y: number; width: number; height: number; mask: false }>;

// Glyph coordinates live in the same -8..8 space as MarkGlyph; scale into the 64px cell.
const SCALE = 3.4;

function drawIcon(ctx: CanvasRenderingContext2D, name: IconName, cx: number, cy: number) {
  const c = name === "ghost" ? MARK_HEX.dark : MARK_HEX[name];
  const s = SCALE;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.fillStyle = c;
  ctx.strokeStyle = c;
  switch (name) {
    case "civil":
    case "mil": {
      ctx.beginPath();
      ctx.moveTo(0, -5 * s);
      ctx.lineTo(4 * s, 4 * s);
      ctx.lineTo(0, 1.6 * s);
      ctx.lineTo(-4 * s, 4 * s);
      ctx.closePath();
      if (name === "civil") ctx.fill();
      else {
        ctx.lineWidth = 1.5 * s;
        ctx.stroke();
      }
      break;
    }
    case "vessel": {
      ctx.rotate(Math.PI / 4);
      ctx.fillRect(-3.6 * s, -3.6 * s, 7.2 * s, 7.2 * s);
      break;
    }
    case "dark": {
      ctx.lineWidth = 1.8 * s;
      ctx.beginPath();
      ctx.arc(0, 0, 5 * s, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, 0, 1.6 * s, 0, Math.PI * 2);
      ctx.fill();
      break;
    }
    case "sat": {
      ctx.beginPath();
      ctx.arc(0, 0, 3 * s, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 0.6;
      ctx.lineWidth = 0.8 * s;
      ctx.beginPath();
      ctx.arc(0, 0, 6 * s, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
      break;
    }
    case "intel": {
      ctx.globalAlpha = 0.9;
      ctx.fillRect(-3.4 * s, -3.4 * s, 6.8 * s, 6.8 * s);
      ctx.globalAlpha = 1;
      break;
    }
    case "ghost": {
      // Signal-loss marker (spec §5.0): dashed ring + × at the exact last fix. Never animates.
      ctx.lineWidth = 1.2 * s;
      ctx.setLineDash([2 * s, 2 * s]);
      ctx.beginPath();
      ctx.arc(0, 0, 5 * s, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(-2.4 * s, -2.4 * s);
      ctx.lineTo(2.4 * s, 2.4 * s);
      ctx.moveTo(2.4 * s, -2.4 * s);
      ctx.lineTo(-2.4 * s, 2.4 * s);
      ctx.stroke();
      break;
    }
  }
  ctx.restore();
}

let cached: string | null | undefined;

/** The atlas as a data URL, or null when no canvas is available (caller falls back to circles). */
export function getMarkAtlas(): string | null {
  if (cached !== undefined) return cached;
  if (typeof document === "undefined") {
    cached = null;
    return cached;
  }
  try {
    const canvas = document.createElement("canvas");
    canvas.width = CELL * ICONS.length;
    canvas.height = CELL;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      cached = null;
      return cached;
    }
    ICONS.forEach((name, i) => drawIcon(ctx, name, i * CELL + CELL / 2, CELL / 2));
    cached = canvas.toDataURL("image/png");
  } catch {
    cached = null;
  }
  return cached;
}

/** Test seam: reset the cache (e.g. after swapping the document). */
export function resetMarkAtlasCache(): void {
  cached = undefined;
}
