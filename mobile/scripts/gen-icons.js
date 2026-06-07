/**
 * Generate Jarvis-branded app icons deterministically (no design tools needed).
 *
 * Motif: a cyan "core" — concentric rings + center disc — on the HUD background
 * (#030810), echoing the web HUD. Run with: `node scripts/gen-icons.js`.
 */
const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');

const BG = [0x03, 0x08, 0x10];
const CYAN = [0x00, 0xae, 0xef];
const CYAN_DIM = [0x0a, 0x6b, 0x8f];
const WHITE = [0xff, 0xff, 0xff];

const smoothstep = (e0, e1, x) => {
  const t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
};
const ring = (dist, r, half, aa) => 1 - smoothstep(half - aa, half + aa, Math.abs(dist - r));
const disc = (dist, r, aa) => 1 - smoothstep(r - aa, r + aa, dist);

/**
 * @param size       output dimension (square)
 * @param opts.bg    background rgb, or null for transparent
 * @param opts.fg    glyph rgb (rings/core)
 * @param opts.scale fraction of the half-size the glyph envelope occupies
 */
function render(size, { bg = BG, fg = CYAN, scale = 0.92 } = {}) {
  const png = new PNG({ width: size, height: size });
  const c = size / 2;
  const R = c * scale;
  const aa = size * 0.0045;
  const outerR = 0.92 * R;
  const midR = 0.6 * R;
  const coreR = 0.26 * R;
  const half = 0.05 * R;

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = x + 0.5 - c;
      const dy = y + 0.5 - c;
      const dist = Math.hypot(dx, dy);

      const aOuter = ring(dist, outerR, half, aa);
      const aMid = ring(dist, midR, half * 0.9, aa);
      const aCore = disc(dist, coreR, aa);
      const aGlyph = Math.max(aOuter, aCore);

      // Mid ring is slightly dimmer for depth (white glyphs stay white).
      const dim = fg === WHITE ? WHITE : CYAN_DIM;
      const [r, g, b] = aMid > aGlyph ? dim : fg;
      const alpha = Math.max(aGlyph, aMid);

      const i = (y * size + x) * 4;
      if (bg) {
        png.data[i] = Math.round(bg[0] * (1 - alpha) + r * alpha);
        png.data[i + 1] = Math.round(bg[1] * (1 - alpha) + g * alpha);
        png.data[i + 2] = Math.round(bg[2] * (1 - alpha) + b * alpha);
        png.data[i + 3] = 255;
      } else {
        png.data[i] = r;
        png.data[i + 1] = g;
        png.data[i + 2] = b;
        png.data[i + 3] = Math.round(255 * alpha);
      }
    }
  }
  return png;
}

function solid(size, color) {
  const png = new PNG({ width: size, height: size });
  for (let i = 0; i < png.data.length; i += 4) {
    png.data[i] = color[0];
    png.data[i + 1] = color[1];
    png.data[i + 2] = color[2];
    png.data[i + 3] = 255;
  }
  return png;
}

const ASSETS = path.join(__dirname, '..', 'assets');
const write = (name, png) => {
  fs.writeFileSync(path.join(ASSETS, name), PNG.sync.write(png));
  console.log('wrote', name, `${png.width}x${png.height}`);
};

// App icon (opaque) and splash glyph (transparent, smaller envelope).
write('icon.png', render(1024, { scale: 0.86 }));
write('splash-icon.png', render(1024, { bg: null, scale: 0.5 }));
write('favicon.png', render(48, { scale: 0.86 }));

// Android adaptive icon: foreground glyph sits inside the mask safe-zone (~0.62),
// background is a solid HUD-dark plate, monochrome is white-on-alpha for theming.
write('android-icon-foreground.png', render(512, { bg: null, scale: 0.62 }));
write('android-icon-background.png', solid(512, BG));
write('android-icon-monochrome.png', render(432, { bg: null, fg: WHITE, scale: 0.62 }));
