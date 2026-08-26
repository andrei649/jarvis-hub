import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import type { Plugin } from "vite";

// Cesium's static assets, without a third-party plugin.
//
// The `cesium` npm package ships its runtime assets — the Web Workers, the widget CSS/images,
// the ThirdParty bundles, and Assets/Textures (which is where the bundled Natural Earth II
// basemap lives) — as plain files that must be reachable at a known URL. Cesium looks for them
// under `window.CESIUM_BASE_URL`, set in index.html.
//
// This plugin mirrors those directories into `public/<base>` once per Cesium version, so Vite
// serves them in dev and copies them into `dist/` on build like any other public asset. The
// mirror is content-addressed by a stamp file: it re-copies only after a Cesium upgrade, and
// `public/` is gitignored so the copies never enter the repository.

const ASSET_DIRS = ["Assets", "Workers", "ThirdParty", "Widgets"];

export function cesiumAssets(baseDir = "cesium"): Plugin {
  return {
    name: "worldview:cesium-assets",
    // `config` runs before dev-server startup and before build, so the mirror always exists by
    // the time Vite resolves the first request.
    config() {
      const require = createRequire(import.meta.url);
      const packageJson = require.resolve("cesium/package.json");
      const cesiumRoot = path.join(path.dirname(packageJson), "Build", "Cesium");
      const version = JSON.parse(fs.readFileSync(packageJson, "utf8")).version as string;

      const target = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "public", baseDir);
      const stamp = path.join(target, ".cesium-version");

      if (fs.existsSync(stamp) && fs.readFileSync(stamp, "utf8") === version) return;

      fs.rmSync(target, { recursive: true, force: true });
      fs.mkdirSync(target, { recursive: true });
      for (const dir of ASSET_DIRS) {
        const from = path.join(cesiumRoot, dir);
        if (!fs.existsSync(from)) continue;
        fs.cpSync(from, path.join(target, dir), { recursive: true });
      }
      fs.writeFileSync(stamp, version);
    },
  };
}
