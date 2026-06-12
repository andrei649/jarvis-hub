"use client";

import { MARK_HEX, type MarkKind } from "@/lib/markStyle";

// The legend/stats glyphs (spec §3.2): the SAME shapes the map renders, as inline SVG, so the
// legend is decode-by-construction. Shapes mirror lib/markAtlas.ts / the mock's Mark component.

function shape(kind: MarkKind | "hex" | "ghost") {
  const c = kind === "hex" ? MARK_HEX.jam : kind === "ghost" ? MARK_HEX.dark : MARK_HEX[kind];
  switch (kind) {
    case "civil":
      return <path d="M0,-5 L4,4 L0,1.6 L-4,4 Z" fill={c} />;
    case "mil":
      return <path d="M0,-5 L4,4 L0,1.6 L-4,4 Z" fill="none" stroke={c} strokeWidth="1.5" />;
    case "vessel":
      return <rect x="-3.6" y="-3.6" width="7.2" height="7.2" transform="rotate(45)" fill={c} />;
    case "dark":
      return (
        <g>
          <circle r="5" fill="none" stroke={c} strokeWidth="1.8" />
          <circle r="1.6" fill={c} />
        </g>
      );
    case "sat":
      return (
        <g>
          <circle r="3" fill={c} />
          <circle r="6" fill="none" stroke={c} strokeWidth=".8" opacity=".6" />
        </g>
      );
    case "intel":
      return <rect x="-3.4" y="-3.4" width="6.8" height="6.8" fill={c} opacity=".9" />;
    case "hex": {
      // A small H3 hexagon for the jamming layer.
      const pts = Array.from({ length: 6 }, (_, k) => {
        const a = (Math.PI / 3) * k + Math.PI / 6;
        return `${(5.4 * Math.cos(a)).toFixed(1)},${(5.4 * Math.sin(a)).toFixed(1)}`;
      }).join(" ");
      return <polygon points={pts} fill={c} opacity=".55" stroke={c} strokeWidth=".8" />;
    }
    case "ghost":
      return (
        <g opacity=".8">
          <circle r="5" fill="none" stroke={c} strokeWidth="1.1" strokeDasharray="2 2" />
          <path d="M-2,-2 L2,2 M2,-2 L-2,2" stroke={c} strokeWidth="1.1" />
        </g>
      );
  }
}

export function MarkGlyph({ kind, size = 18 }: { kind: MarkKind | "hex" | "ghost"; size?: number }) {
  return (
    <svg
      width={size}
      height={(size * 14) / 18}
      viewBox="-8 -7 16 14"
      aria-hidden
      className="shrink-0"
    >
      {shape(kind)}
    </svg>
  );
}
