import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const THEME_PALETTES = {
  emerald: { primary: "#10b981", secondary: "#f43f5e", edge: "#1e3a5f", particle: "#34d399" },
  violet: { primary: "#a855f7", secondary: "#06b6d4", edge: "#312e81", particle: "#22d3ee" },
  lime: { primary: "#4ade80", secondary: "#6366f1", edge: "#1e3a3a", particle: "#86efac" },
  cyber: { primary: "#38bdf8", secondary: "#2563eb", edge: "#172554", particle: "#7dd3fc" },
};

export class KnowledgeGalaxy {
  constructor(canvas, dataset, callbacks = {}) {
    this.canvas = canvas;
    this.dataset = dataset;
    this.callbacks = callbacks;

    this.repelScale = 1.0;
    this.linkScale = 1.0;
    this.flatFactor = 0.0;
    this.targetFlatFactor = 0.0;
    this.autoRotate = true;
    this.showHubLabels = true;
    this.showParticles = true;
    this.showStarfield = true;
    this.isolateMode = false;
    this.crownHighlight = false;
    this.theme = "emerald";

    this.focusedIndex = null;
    this.pathIndices = null;
    this.mutedCategories = new Set();
    this.searchMatches = null;

    this.cameraFly = null;
    this.currentPositions = new Float32Array(dataset.nodes.length * 3);

    this._initScene();
    this._buildStarfield();
    this._buildGraph();
    this._buildParticles();
    this._bindEvents();
    this.updatePositions(true);
    this.refreshVisualHighlights();
  }

  _initScene() {
    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.FogExp2(0x05070c, 0.0022);

    const w = window.innerWidth;
    const h = window.innerHeight;
    this.camera = new THREE.PerspectiveCamera(52, w / h, 0.5, 900);
    this.camera.position.set(0, 18, 148);

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    this.renderer.setClearColor(0x05070c, 1);

    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.rotateSpeed = 0.65;
    this.controls.minDistance = 16;
    this.controls.maxDistance = 340;
    this.controls.autoRotate = true;
    this.controls.autoRotateSpeed = 0.42;

    const ambient = new THREE.AmbientLight(0xffffff, 0.9);
    const dir1 = new THREE.DirectionalLight(0xffffff, 1.1);
    dir1.position.set(60, 90, 80);
    this.scene.add(ambient, dir1);

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
  }

  _buildStarfield() {
    const count = 1400;
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 180 + Math.random() * 280;
      const t = Math.random() * Math.PI * 2;
      const p = Math.acos(2 * Math.random() - 1);
      pos[i * 3] = r * Math.sin(p) * Math.cos(t);
      pos[i * 3 + 1] = r * Math.sin(p) * Math.sin(t);
      pos[i * 3 + 2] = r * Math.cos(p);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({
      color: 0x94a3b8,
      size: 1.05,
      transparent: true,
      opacity: 0.48,
      sizeAttenuation: true,
    });
    this.starfield = new THREE.Points(geo, mat);
    this.scene.add(this.starfield);
  }

  _createLabelSprite(text, colorHex) {
    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = 96;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, 512, 96);

    ctx.font = "600 28px Inter, -apple-system, sans-serif";
    const metrics = ctx.measureText(text);
    const pillW = Math.min(490, metrics.width + 44);
    const x = (512 - pillW) / 2;

    ctx.fillStyle = "rgba(7, 10, 18, 0.78)";
    ctx.strokeStyle = colorHex;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(x, 20, pillW, 52, 26);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#f8fafc";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 256, 47);

    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(17, 3.2, 1);
    return sprite;
  }

  _buildGraph() {
    this.graphGroup = new THREE.Group();
    this.scene.add(this.graphGroup);

    const sphereGeo = new THREE.SphereGeometry(1, 18, 18);
    this.nodeMeshes = [];
    this.hubSprites = [];

    for (const node of this.dataset.nodes) {
      const baseColor = new THREE.Color(node.color);
      const mat = new THREE.MeshStandardMaterial({
        color: baseColor,
        emissive: baseColor,
        emissiveIntensity: node.isHub ? 0.85 : 0.48,
        roughness: 0.25,
        metalness: 0.15,
        transparent: true,
        opacity: 0.96,
      });
      const mesh = new THREE.Mesh(sphereGeo, mat);
      mesh.scale.setScalar(node.radius);
      mesh.userData = { nodeIndex: node.index };
      this.graphGroup.add(mesh);
      this.nodeMeshes.push(mesh);

      if (node.isHub && node.hubLabel) {
        const sprite = this._createLabelSprite(node.hubLabel, node.color);
        sprite.userData = { nodeIndex: node.index };
        this.graphGroup.add(sprite);
        this.hubSprites.push(sprite);
      }
    }

    // Edges LineSegments
    const edgeCount = this.dataset.edges.length;
    this.edgePositions = new Float32Array(edgeCount * 6);
    this.edgeColors = new Float32Array(edgeCount * 6);
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute("position", new THREE.BufferAttribute(this.edgePositions, 3));
    edgeGeo.setAttribute("color", new THREE.BufferAttribute(this.edgeColors, 3));

    this.edgeMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.34,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.edgeLines = new THREE.LineSegments(edgeGeo, this.edgeMaterial);
    this.graphGroup.add(this.edgeLines);
  }

  _buildParticles() {
    const count = 420;
    this.flowSeeds = [];
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      this.flowSeeds.push({
        edgeIndex: Math.floor(Math.random() * this.dataset.edges.length),
        t: Math.random(),
        speed: 0.18 + Math.random() * 0.38,
      });
    }
    const dotCanvas = document.createElement("canvas");
    dotCanvas.width = 32;
    dotCanvas.height = 32;
    const dctx = dotCanvas.getContext("2d");
    const grad = dctx.createRadialGradient(16, 16, 1, 16, 16, 15);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.45, "rgba(255,255,255,0.75)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    dctx.fillStyle = grad;
    dctx.fillRect(0, 0, 32, 32);
    const dotTex = new THREE.CanvasTexture(dotCanvas);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.particleMat = new THREE.PointsMaterial({
      color: 0x34d399,
      map: dotTex,
      size: 1.9,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.flowPoints = new THREE.Points(geo, this.particleMat);
    this.graphGroup.add(this.flowPoints);
  }

  updatePositions(immediate = false) {
    if (immediate) this.flatFactor = this.targetFlatFactor;
    const nodes = this.dataset.nodes;

    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      let x3, y3, z3, x2, y2;

      if (n.parentHubIndex !== undefined) {
        const hub = nodes[n.parentHubIndex];
        const hx = hub.base3d[0] * this.repelScale;
        const hy = hub.base3d[1] * this.repelScale;
        const hz = hub.base3d[2] * this.repelScale;
        x3 = hx + n.offset3d[0] * this.linkScale;
        y3 = hy + n.offset3d[1] * this.linkScale;
        z3 = hz + n.offset3d[2] * this.linkScale;

        const hx2 = hub.base2d[0] * this.repelScale;
        const hy2 = hub.base2d[1] * this.repelScale;
        x2 = hx2 + (n.base2d[0] - hub.base2d[0]) * this.linkScale;
        y2 = hy2 + (n.base2d[1] - hub.base2d[1]) * this.linkScale;
      } else {
        x3 = n.base3d[0] * this.repelScale;
        y3 = n.base3d[1] * this.repelScale;
        z3 = n.base3d[2] * this.repelScale;
        x2 = n.base2d[0] * this.repelScale;
        y2 = n.base2d[1] * this.repelScale;
      }

      const x = THREE.MathUtils.lerp(x3, x2, this.flatFactor);
      const y = THREE.MathUtils.lerp(y3, y2, this.flatFactor);
      const z = THREE.MathUtils.lerp(z3, 0, this.flatFactor);

      this.currentPositions[i * 3] = x;
      this.currentPositions[i * 3 + 1] = y;
      this.currentPositions[i * 3 + 2] = z;

      this.nodeMeshes[i].position.set(x, y, z);
    }

    for (const sprite of this.hubSprites) {
      const idx = sprite.userData.nodeIndex;
      const r = nodes[idx].radius;
      sprite.position.set(
        this.currentPositions[idx * 3],
        this.currentPositions[idx * 3 + 1] - r - 2.4,
        this.currentPositions[idx * 3 + 2]
      );
    }

    // Update edge vertices
    const edges = this.dataset.edges;
    for (let e = 0; e < edges.length; e++) {
      const [u, v] = edges[e];
      const base = e * 6;
      this.edgePositions[base] = this.currentPositions[u * 3];
      this.edgePositions[base + 1] = this.currentPositions[u * 3 + 1];
      this.edgePositions[base + 2] = this.currentPositions[u * 3 + 2];
      this.edgePositions[base + 3] = this.currentPositions[v * 3];
      this.edgePositions[base + 4] = this.currentPositions[v * 3 + 1];
      this.edgePositions[base + 5] = this.currentPositions[v * 3 + 2];
    }
    this.edgeLines.geometry.attributes.position.needsUpdate = true;
  }

  refreshVisualHighlights() {
    const nodes = this.dataset.nodes;
    const edges = this.dataset.edges;
    const palette = THEME_PALETTES[this.theme] || THEME_PALETTES.emerald;
    const baseEdgeColor = new THREE.Color(palette.edge);
    const activeEdgeColor = new THREE.Color(palette.primary);
    const pathEdgeColor = new THREE.Color("#fbbf24");

    const activeNeighbors = new Set();
    const pathSet = new Set(this.pathIndices || []);
    const pathPairs = new Set();

    if (this.pathIndices && this.pathIndices.length > 1) {
      for (let i = 0; i < this.pathIndices.length - 1; i++) {
        const a = Math.min(this.pathIndices[i], this.pathIndices[i + 1]);
        const b = Math.max(this.pathIndices[i], this.pathIndices[i + 1]);
        pathPairs.add(`${a}:${b}`);
      }
    }

    if (this.focusedIndex !== null) {
      activeNeighbors.add(this.focusedIndex);
      for (const nb of this.dataset.adjacency[this.focusedIndex]) {
        activeNeighbors.add(nb);
      }
    }

    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      const mesh = this.nodeMeshes[i];
      const catMuted = this.mutedCategories.has(n.category);
      const searchMiss = this.searchMatches && !this.searchMatches.has(i);

      let highlighted = true;
      if (this.pathIndices) {
        highlighted = pathSet.has(i);
      } else if (this.focusedIndex !== null) {
        highlighted = activeNeighbors.has(i);
      }

      if (catMuted || (this.isolateMode && this.focusedIndex !== null && !highlighted)) {
        mesh.visible = false;
        continue;
      }
      mesh.visible = true;

      const c = new THREE.Color(n.color);
      mesh.material.color.copy(c);
      mesh.material.emissive.copy(c);

      if (pathSet.has(i)) {
        mesh.material.opacity = 1.0;
        mesh.material.emissiveIntensity = 1.35;
        mesh.scale.setScalar(n.radius * 1.35);
      } else if (i === this.focusedIndex) {
        mesh.material.opacity = 1.0;
        mesh.material.emissiveIntensity = 1.4;
        mesh.scale.setScalar(n.radius * 1.45);
      } else if (!highlighted || searchMiss) {
        mesh.material.opacity = 0.12;
        mesh.material.emissiveIntensity = 0.1;
        mesh.scale.setScalar(n.radius * 0.88);
      } else {
        mesh.material.opacity = 0.95;
        mesh.material.emissiveIntensity = n.isHub ? (this.crownHighlight ? 1.4 : 0.85) : 0.48;
        mesh.scale.setScalar(n.isHub && this.crownHighlight ? n.radius * 1.3 : n.radius);
      }
    }

    for (const sprite of this.hubSprites) {
      const idx = sprite.userData.nodeIndex;
      sprite.visible = this.showHubLabels && this.nodeMeshes[idx].visible;
      sprite.material.opacity =
        this.focusedIndex !== null && !activeNeighbors.has(idx) && !pathSet.has(idx) ? 0.18 : 0.95;
    }

    // Color edges
    for (let e = 0; e < edges.length; e++) {
      const [u, v] = edges[e];
      const key = `${u}:${v}`;
      let col = baseEdgeColor;

      if (pathPairs.has(key)) {
        col = pathEdgeColor;
      } else if (this.focusedIndex !== null) {
        if (u === this.focusedIndex || v === this.focusedIndex) {
          col = activeEdgeColor;
        } else {
          col = new THREE.Color(0x070b14);
        }
      }

      const base = e * 6;
      this.edgeColors[base] = col.r;
      this.edgeColors[base + 1] = col.g;
      this.edgeColors[base + 2] = col.b;
      this.edgeColors[base + 3] = col.r;
      this.edgeColors[base + 4] = col.g;
      this.edgeColors[base + 5] = col.b;
    }

    this.edgeMaterial.opacity = this.pathIndices || this.focusedIndex !== null ? 0.72 : 0.32;
    this.edgeLines.geometry.attributes.color.needsUpdate = true;
    if (this.particleMat) {
      this.particleMat.color.set(palette.particle);
    }
  }

  focusNode(index, fly = true) {
    if (index === null || index === undefined || index < 0) {
      this.clearSelection();
      return;
    }
    this.focusedIndex = index;
    this.pathIndices = null;
    this.refreshVisualHighlights();

    if (fly) {
      const tx = this.currentPositions[index * 3];
      const ty = this.currentPositions[index * 3 + 1];
      const tz = this.currentPositions[index * 3 + 2];
      const target = new THREE.Vector3(tx, ty, tz);
      const dir = this.camera.position.clone().sub(this.controls.target).normalize();
      const desiredCam = target.clone().add(dir.multiplyScalar(38));
      this.cameraFly = { target, desiredCam, alpha: 0 };
    }

    if (this.callbacks.onSelectNode) {
      this.callbacks.onSelectNode(this.dataset.nodes[index], this.dataset.adjacency[index]);
    }
  }

  tracePathBetween(startIdx, endIdx) {
    const path = this.dataset.findShortestPath(startIdx, endIdx);
    if (!path) return null;
    this.pathIndices = path;
    this.focusedIndex = startIdx;
    this.refreshVisualHighlights();

    // Frame midpoint
    const midIdx = path[Math.floor(path.length / 2)];
    const target = new THREE.Vector3(
      this.currentPositions[midIdx * 3],
      this.currentPositions[midIdx * 3 + 1],
      this.currentPositions[midIdx * 3 + 2]
    );
    this.cameraFly = {
      target,
      desiredCam: target.clone().add(new THREE.Vector3(0, 14, 78)),
      alpha: 0,
    };

    if (this.callbacks.onPathTraced) {
      this.callbacks.onPathTraced(path.map((i) => this.dataset.nodes[i]));
    }
    return path;
  }

  clearSelection() {
    this.focusedIndex = null;
    this.pathIndices = null;
    this.isolateMode = false;
    this.refreshVisualHighlights();
    if (this.callbacks.onClearSelection) this.callbacks.onClearSelection();
  }

  fitView() {
    this.cameraFly = {
      target: new THREE.Vector3(0, 0, 0),
      desiredCam: new THREE.Vector3(0, this.targetFlatFactor > 0.5 ? 0 : 18, 148),
      alpha: 0,
    };
  }

  setFlatMode(isFlat) {
    this.targetFlatFactor = isFlat ? 1.0 : 0.0;
    this.controls.autoRotate = isFlat ? false : this.autoRotate;
    this.cameraFly = {
      target: new THREE.Vector3(0, 0, 0),
      desiredCam: new THREE.Vector3(0, isFlat ? 0 : 18, isFlat ? 165 : 148),
      alpha: 0,
    };
  }

  setDataset(newDataset) {
    if (this.graphGroup) {
      this.scene.remove(this.graphGroup);
      this.graphGroup.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (obj.material.map) obj.material.map.dispose();
          obj.material.dispose();
        }
      });
    }
    this.dataset = newDataset;
    this.focusedIndex = null;
    this.pathIndices = null;
    this.mutedCategories.clear();
    this.searchMatches = null;
    this.currentPositions = new Float32Array(newDataset.nodes.length * 3);

    this._buildGraph();
    this._buildParticles();
    this.updatePositions(true);
    this.refreshVisualHighlights();
    if (this.callbacks.onClearSelection) this.callbacks.onClearSelection();
  }

  search(query) {
    const q = (query || "").trim().toLowerCase();
    if (!q) {
      this.searchMatches = null;
      this.refreshVisualHighlights();
      return [];
    }
    const exactMatches = [];
    const bodyMatches = [];
    this.searchMatches = new Set();
    for (const n of this.dataset.nodes) {
      const inTitle = n.title.toLowerCase().includes(q);
      const inCat = n.category.toLowerCase().includes(q);
      const inPath = (n.relPath || "").toLowerCase().includes(q);
      const inBody = (n.body || "").toLowerCase().includes(q);
      if (inTitle || inCat || inPath) {
        this.searchMatches.add(n.index);
        exactMatches.push(n);
      } else if (inBody) {
        this.searchMatches.add(n.index);
        bodyMatches.push(n);
      }
    }
    this.refreshVisualHighlights();
    return [...exactMatches, ...bodyMatches];
  }

  setTheme(themeName) {
    this.theme = themeName;
    this.refreshVisualHighlights();
  }

  _bindEvents() {
    let downX = 0;
    let downY = 0;

    this.canvas.addEventListener("pointerdown", (e) => {
      downX = e.clientX;
      downY = e.clientY;
    });

    this.canvas.addEventListener("pointerup", (e) => {
      if (Math.hypot(e.clientX - downX, e.clientY - downY) > 5) return;

      const rect = this.canvas.getBoundingClientRect();
      this.pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      this.pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      this.raycaster.setFromCamera(this.pointer, this.camera);
      const visibleMeshes = this.nodeMeshes.filter((m) => m.visible);
      const hits = this.raycaster.intersectObjects(visibleMeshes, false);

      if (hits.length > 0) {
        const hitIdx = hits[0].object.userData.nodeIndex;
        if (e.shiftKey && this.focusedIndex !== null && this.focusedIndex !== hitIdx) {
          this.tracePathBetween(this.focusedIndex, hitIdx);
        } else {
          this.focusNode(hitIdx, true);
        }
      } else if (this.focusedIndex !== null || this.pathIndices !== null) {
        this.clearSelection();
        this.fitView();
      }
    });

    window.addEventListener("resize", () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(w, h);
    });
  }

  tick(dt) {
    if (Math.abs(this.flatFactor - this.targetFlatFactor) > 0.002) {
      this.flatFactor = THREE.MathUtils.lerp(this.flatFactor, this.targetFlatFactor, Math.min(1, dt * 4.5));
      this.updatePositions(false);
    }

    if (this.cameraFly) {
      this.cameraFly.alpha = Math.min(1, this.cameraFly.alpha + dt * 2.4);
      const ease = 1 - Math.pow(1 - this.cameraFly.alpha, 3);
      this.controls.target.lerp(this.cameraFly.target, ease * 0.22);
      this.camera.position.lerp(this.cameraFly.desiredCam, ease * 0.16);
      if (this.cameraFly.alpha >= 0.99) this.cameraFly = null;
    }

    // Update flowing particles along edges
    this.flowPoints.visible = this.showParticles && this.dataset.edges.length > 0;
    if (this.showParticles && this.dataset.edges.length > 0) {
      const attr = this.flowPoints.geometry.attributes.position;
      const arr = attr.array;
      const edges = this.dataset.edges;
      for (let i = 0; i < this.flowSeeds.length; i++) {
        const seed = this.flowSeeds[i];
        seed.t += dt * seed.speed;
        if (seed.t > 1) {
          seed.t -= 1;
          seed.edgeIndex = Math.floor(Math.random() * edges.length);
        }
        const [u, v] = edges[seed.edgeIndex];
        const ux = this.currentPositions[u * 3];
        const uy = this.currentPositions[u * 3 + 1];
        const uz = this.currentPositions[u * 3 + 2];
        const vx = this.currentPositions[v * 3];
        const vy = this.currentPositions[v * 3 + 1];
        const vz = this.currentPositions[v * 3 + 2];

        arr[i * 3] = ux + (vx - ux) * seed.t;
        arr[i * 3 + 1] = uy + (vy - uy) * seed.t;
        arr[i * 3 + 2] = uz + (vz - uz) * seed.t;
      }
      attr.needsUpdate = true;
    }

    this.starfield.visible = this.showStarfield;
    this.controls.autoRotate = this.autoRotate && this.targetFlatFactor < 0.2 && !this.cameraFly;
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
