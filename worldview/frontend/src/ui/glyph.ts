import { MARK_HEX, type MarkKind } from "@/lib/markStyle";

// The legend/stats glyphs (spec §3.2): the SAME shapes the globe renders, as inline SVG, so the
// legend is decode-by-construction. Shapes mirror lib/markIcons.ts.

export type GlyphKind = MarkKind | "hex" | "ghost";

function shape(kind: GlyphKind): string {
  const c = kind === "hex" ? MARK_HEX.jam : kind === "ghost" ? MARK_HEX.dark : MARK_HEX[kind];
  switch (kind) {
    case "civil":
      return `<path d="M0,-5 L4,4 L0,1.6 L-4,4 Z" fill="${c}" />`;
    case "mil":
      return `<path d="M0,-5 L4,4 L0,1.6 L-4,4 Z" fill="none" stroke="${c}" stroke-width="1.5" />`;
    case "vessel":
      return `<rect x="-3.6" y="-3.6" width="7.2" height="7.2" transform="rotate(45)" fill="${c}" />`;
    case "dark":
      return `<g><circle r="5" fill="none" stroke="${c}" stroke-width="1.8" /><circle r="1.6" fill="${c}" /></g>`;
    case "sat":
      return `<g><circle r="3" fill="${c}" /><circle r="6" fill="none" stroke="${c}" stroke-width=".8" opacity=".6" /></g>`;
    case "intel":
      return `<rect x="-3.4" y="-3.4" width="6.8" height="6.8" fill="${c}" opacity=".9" />`;
    case "jam":
    case "hex": {
      // A small H3 hexagon for the jamming layer.
      const points = Array.from({ length: 6 }, (_, k) => {
        const a = (Math.PI / 3) * k + Math.PI / 6;
        return `${(5.4 * Math.cos(a)).toFixed(1)},${(5.4 * Math.sin(a)).toFixed(1)}`;
      }).join(" ");
      return `<polygon points="${points}" fill="${c}" opacity=".55" stroke="${c}" stroke-width=".8" />`;
    }
    case "ghost":
      return `<g opacity=".8"><circle r="5" fill="none" stroke="${c}" stroke-width="1.1" stroke-dasharray="2 2" /><path d="M-2,-2 L2,2 M2,-2 L-2,2" stroke="${c}" stroke-width="1.1" /></g>`;
  }
}

export function glyph(kind: GlyphKind, size = 18): string {
  return `<svg width="${size}" height="${(size * 14) / 18}" viewBox="-8 -7 16 14" aria-hidden="true" class="shrink-0">${shape(kind)}</svg>`;
}

/** The WorldView wordmark globe icon. */
export function brandMark(size = 20): string {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" class="text-signal" aria-hidden="true"><circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="9" ry="3.6" /><path d="M12 3v18" /></svg>`;
}
