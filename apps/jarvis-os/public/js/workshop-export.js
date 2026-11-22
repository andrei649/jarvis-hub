import { Matrix4 } from "three";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";

// GLTFExporter and TextureUtils are unmodified three.js r169 (MIT; vendor/three/LICENSE).
export async function workshopGLB(roots) {
  if (!Array.isArray(roots) || roots.some((root) => !root?.isObject3D || root.isScene)) {
    throw new TypeError("workshopGLB expects an array of object roots");
  }

  const copies = [];
  for (const root of roots) {
    const matrix = new Matrix4();
    let visible = true;
    for (let node = root; node; node = node.parent) {
      if (!node.visible) visible = false;
      matrix.premultiply(node.matrixAutoUpdate
        ? new Matrix4().compose(node.position, node.quaternion, node.scale)
        : node.matrix);
    }
    if (!visible) continue;

    const copy = root.clone(true);
    copy.matrix.copy(matrix);
    copy.matrixAutoUpdate = false;
    copies.push(copy);
  }

  const data = await new GLTFExporter().parseAsync(copies, { binary: true, onlyVisible: true });
  return new Blob([data], { type: "model/gltf-binary" });
}

function floorPlanGeometry(house) {
  const footprint = (mesh) => {
    const { width: w, depth: d } = mesh.geometry.parameters;
    return { name: mesh.name, x: mesh.position.x, z: mesh.position.z, w, d };
  };
  const floors = ["Interior tiled floor", "Garage floor", "Pool deck"]
    .map((name) => house.houseRoot.getObjectByName(name)).filter(Boolean).map(footprint);
  const pools = ["Swimming pool", "Spa pool"]
    .map((name) => house.houseRoot.getObjectByName(name)).filter(Boolean).map(footprint);
  const walls = house.stepGroups.walls.children
    .map((group) => group.userData.floorFootprint).filter(Boolean);
  if (floors.length !== 3 || pools.length !== 2 || !walls.length) throw new Error("house floor plan is unavailable");

  const all = [...floors, ...pools, ...walls];
  const x0 = Math.min(...all.map((p) => p.x - p.w / 2)) - 0.8;
  const z0 = Math.min(...all.map((p) => p.z - p.d / 2)) - 0.8;
  const x1 = Math.max(...all.map((p) => p.x + p.w / 2)) + 0.8;
  const z1 = Math.max(...all.map((p) => p.z + p.d / 2)) + 1.2;
  return { floors, pools, walls, labels: house.roomLabels(), x0, z0, x1, z1 };
}

/** Editable top-down geometry from the current house scene, at 1:100 on paper. */
export function houseFloorPlanSVG(house) {
  const { floors, pools, walls, labels: rooms, x0, z0, x1, z1 } = floorPlanGeometry(house);
  const n = (value) => String(Number(value.toFixed(3)));
  const esc = (value) => String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[ch]);
  const rects = (items) => items.map((p) => `<rect x="${n(p.x - p.w / 2)}" y="${n(p.z - p.d / 2)}" width="${n(p.w)}" height="${n(p.d)}"/>`).join("");
  const labels = rooms.map((r) => `<text x="${n(r.x)}" y="${n(r.z)}">${esc(r.name)}</text>`).join("");
  return `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<svg xmlns="http://www.w3.org/2000/svg" width="${n((x1 - x0) * 10)}mm" height="${n((z1 - z0) * 10)}mm" viewBox="${n(x0)} ${n(z0)} ${n(x1 - x0)} ${n(z1 - z0)}">` +
    `<title>Pool Home Plan</title><desc>Top-down scene footprints, metres; print scale 1:100.</desc>` +
    `<g id="floors" fill="#eee9dc" stroke="#b7aa92" stroke-width="0.05">${rects(floors.slice(0, 1))}</g>` +
    `<g id="garage" fill="#dddfe2" stroke="#9ca3af" stroke-width="0.05">${rects(floors.slice(1, 2))}</g>` +
    `<g id="deck" fill="#e7d6b9" stroke="#b69d77" stroke-width="0.05">${rects(floors.slice(2))}</g>` +
    `<g id="pools" fill="#7dd3fc" stroke="#0369a1" stroke-width="0.07">${rects(pools)}</g>` +
    `<g id="walls" fill="#334155" stroke="#0f172a" stroke-width="0.03">${rects(walls)}</g>` +
    `<g id="labels" fill="#0f172a" font-family="Arial,sans-serif" font-size="0.36" text-anchor="middle">${labels}</g>` +
    `<g id="scale" fill="#0f172a" font-family="Arial,sans-serif" font-size="0.28">` +
    `<path d="M ${n(x0 + 0.3)} ${n(z1 - 0.65)} h 5 m -5 -0.12 v 0.24 m 5 -0.24 v 0.24" fill="none" stroke="#0f172a" stroke-width="0.04"/>` +
    `<text x="${n(x0 + 0.3)}" y="${n(z1 - 0.25)}">0</text><text x="${n(x0 + 5.3)}" y="${n(z1 - 0.25)}">5 m · 1:100</text></g></svg>`;
}

/** Illustrator's native document API builds the editable plan when the owner runs this JSX. */
export function houseFloorPlanIllustratorScript(house) {
  const { floors, pools, walls, labels, x0, z0, x1, z1 } = floorPlanGeometry(house);
  const pt = 72 / 25.4 * 10; // one scene metre is 10 mm on paper (1:100)
  const width = (x1 - x0) * pt;
  const height = (z1 - z0) * pt;
  const n = (value) => {
    if (!Number.isFinite(value) || Math.abs(value) > 16383) throw new RangeError("floor plan exceeds Illustrator canvas");
    return Number(value.toFixed(4));
  };
  if (!(width > 0 && height > 0) || width > 16383 || height > 16383) {
    throw new RangeError("floor plan exceeds Illustrator canvas");
  }
  const xy = (x, z) => [n((x - x0) * pt), n((z1 - z) * pt)];
  const rect = (p) => {
    if (![p.x, p.z, p.w, p.d].every(Number.isFinite) || p.w <= 0 || p.d <= 0) {
      throw new RangeError("invalid floor plan rectangle");
    }
    return [...xy(p.x - p.w / 2, p.z - p.d / 2), n(p.w * pt), n(p.d * pt)];
  };
  const label = (name, x, z, size) => {
    if (typeof name !== "string" || name.length > 200) throw new RangeError("invalid room label");
    return [name, ...xy(x, z), n(size * pt)];
  };
  const data = {
    width: n(width), height: n(height),
    groups: [
      ["Floors", floors.slice(0, 1).map(rect), "eee9dc", "b7aa92", n(0.05 * pt)],
      ["Garage", floors.slice(1, 2).map(rect), "dddfe2", "9ca3af", n(0.05 * pt)],
      ["Deck", floors.slice(2).map(rect), "e7d6b9", "b69d77", n(0.05 * pt)],
      ["Pools", pools.map(rect), "7dd3fc", "0369a1", n(0.07 * pt)],
      ["Walls", walls.map(rect), "334155", "0f172a", n(0.03 * pt)],
    ],
    labels: labels.map((r) => label(r.name, r.x, r.z, 0.36)),
    scale: [
      [xy(x0 + 0.3, z1 - 0.65), xy(x0 + 5.3, z1 - 0.65)],
      [xy(x0 + 0.3, z1 - 0.53), xy(x0 + 0.3, z1 - 0.77)],
      [xy(x0 + 5.3, z1 - 0.53), xy(x0 + 5.3, z1 - 0.77)],
    ],
    scaleLabels: [
      label("0", x0 + 0.3, z1 - 0.25, 0.28),
      label("5 m · 1:100", x0 + 5.3, z1 - 0.25, 0.28),
    ],
  };
  // JSON is data-only; escape JavaScript line separators for older ExtendScript parsers.
  const literal = JSON.stringify(data).replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
  return [
    "(function () {",
    "  var data = " + literal + ";",
    "  var draft = null;",
    "  function color(hex) {",
    "    var rgb = new RGBColor();",
    "    rgb.red = parseInt(hex.substr(0, 2), 16);",
    "    rgb.green = parseInt(hex.substr(2, 2), 16);",
    "    rgb.blue = parseInt(hex.substr(4, 2), 16);",
    "    return rgb;",
    "  }",
    "  function addText(group, item, centered) {",
    "    var frame = group.textFrames.pointText([item[1], item[2]]);",
    "    frame.contents = item[0];",
    "    frame.textRange.characterAttributes.size = item[3];",
    "    frame.textRange.characterAttributes.fillColor = color('0f172a');",
    "    frame.paragraphs[0].paragraphAttributes.justification = centered ? Justification.CENTER : Justification.LEFT;",
    "  }",
    "  try {",
    "    draft = app.documents.add(DocumentColorSpace.RGB, data.width, data.height);",
    "    draft.artboards[0].artboardRect = [0, data.height, data.width, 0];",
    "    for (var i = 0; i < data.groups.length; i++) {",
    "      var spec = data.groups[i];",
    "      var group = draft.groupItems.add();",
    "      group.name = spec[0];",
    "      for (var j = 0; j < spec[1].length; j++) {",
    "        var r = spec[1][j];",
    "        var path = group.pathItems.rectangle(r[1], r[0], r[2], r[3]);",
    "        path.filled = true;",
    "        path.fillColor = color(spec[2]);",
    "        path.stroked = true;",
    "        path.strokeColor = color(spec[3]);",
    "        path.strokeWidth = spec[4];",
    "      }",
    "    }",
    "    var rooms = draft.groupItems.add();",
    "    rooms.name = 'Room labels';",
    "    for (var k = 0; k < data.labels.length; k++) addText(rooms, data.labels[k], true);",
    "    var scale = draft.groupItems.add();",
    "    scale.name = 'Scale';",
    "    for (var m = 0; m < data.scale.length; m++) {",
    "      var line = scale.pathItems.add();",
    "      line.setEntirePath(data.scale[m]);",
    "      line.filled = false;",
    "      line.stroked = true;",
    "      line.strokeColor = color('0f172a');",
    "      line.strokeWidth = " + n(0.04 * pt) + ";",
    "    }",
    "    for (var s = 0; s < data.scaleLabels.length; s++) addText(scale, data.scaleLabels[s], false);",
    "  } catch (error) {",
    "    if (draft) draft.close(SaveOptions.DONOTSAVECHANGES);",
    "    throw error;",
    "  }",
    "})();",
  ].join("\n");
}
