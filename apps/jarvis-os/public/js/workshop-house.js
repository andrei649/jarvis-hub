import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

function makeTileTexture(bgHex, lineHex, cells = 8) {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 256;
  const ctx = c.getContext("2d");
  ctx.fillStyle = bgHex;
  ctx.fillRect(0, 0, 256, 256);
  ctx.strokeStyle = lineHex;
  ctx.lineWidth = 2;
  const step = 256 / cells;
  for (let i = 0; i <= cells; i++) {
    const p = i * step;
    ctx.beginPath();
    ctx.moveTo(p, 0);
    ctx.lineTo(p, 256);
    ctx.moveTo(0, p);
    ctx.lineTo(256, p);
    ctx.stroke();
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeWaterCausticsTexture() {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 256;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#29a8df";
  ctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 70; i++) {
    ctx.strokeStyle = "rgba(186, 242, 255, 0.34)";
    ctx.lineWidth = 2 + (i % 3);
    ctx.beginPath();
    ctx.arc((i * 73) % 256, (i * 139) % 256, 14 + (i % 22), 0, Math.PI * 2);
    ctx.stroke();
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(3, 2);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeSandBumpTexture() {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 256;
  const ctx = c.getContext("2d");
  for (let y = 0; y < 256; y++) {
    const wave = Math.floor(128 + Math.sin((y / 256) * Math.PI * 18) * 55);
    ctx.fillStyle = `rgb(${wave},${wave},${wave})`;
    ctx.fillRect(0, y, 256, 1);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(8, 8);
  return tex;
}

export class HouseWorkshop {
  constructor(containerEl, calloutSvg, calloutLabelsEl) {
    this.container = containerEl;
    this.calloutSvg = calloutSvg;
    this.calloutLabelsEl = calloutLabelsEl;

    this.active = false;
    this.viewMode = "3d"; // '3d' | 'miniature'
    this.miniatureReady = false;
    this.phase = 0;
    this.cameraGoal = null;

    this.state = {
      centeredDoorNoStairs: false,
      garageCars: false,
      livingRoomExtraMeters: 0,
      kitchenExtraMeters: 0,
      poolBackPalmsAndFlowers: false,
      poolLoungeChairs: false,
      showRoof: false,
      roofVisibilityOverride: null,
      showRoomLabels: false,
      explodedLayers: false,
    };

    this._initScene();
    this._rebuildArchitecture();
  }

  _initScene() {
    const w = window.innerWidth;
    const h = window.innerHeight;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, w / h, 0.2, 240);
    this.camera.position.set(-11, 18.5, 21.5);

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.target.set(0, 0.5, 0);
    this.controls.minDistance = 8;
    this.controls.maxDistance = 58;
    this.controls.maxPolarAngle = Math.PI * 0.47;

    // Lights (dynamically tuned between 3D Studio mode and Golden-Hour Miniature mode)
    this.hemiLight = new THREE.HemisphereLight(0xf8fafc, 0x334155, 1.15);
    this.scene.add(this.hemiLight);

    this.sunLight = new THREE.DirectionalLight(0xffffff, 2.0);
    this.sunLight.position.set(16, 26, 14);
    this.sunLight.castShadow = true;
    this.sunLight.shadow.mapSize.set(2048, 2048);
    this.sunLight.shadow.camera.left = -28;
    this.sunLight.shadow.camera.right = 28;
    this.sunLight.shadow.camera.top = 28;
    this.sunLight.shadow.camera.bottom = -28;
    this.sunLight.shadow.bias = -0.0005;
    this.scene.add(this.sunLight);

    this.houseRoot = new THREE.Group();
    this.houseRoot.name = "Pool Home Plan";
    this.scene.add(this.houseRoot);

    this.miniatureEnvGroup = new THREE.Group();
    this.miniatureEnvGroup.name = "Desert diorama";
    this.scene.add(this.miniatureEnvGroup);
    this._buildMiniatureDesertEnvironment();
    this.miniatureEnvGroup.visible = false;

    window.addEventListener("resize", () => {
      if (!this.active) return;
      this.resize();
    });
  }

  resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  _createPalmTree(height = 3.2) {
    const g = new THREE.Group();
    const trunkCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, 0, 0),
      new THREE.Vector3(0.18, height * 0.45, 0.08),
      new THREE.Vector3(0.06, height, 0),
    ]);
    const trunkMat = new THREE.MeshStandardMaterial({ color: 0x7c5836, roughness: 0.88 });
    const trunk = new THREE.Mesh(new THREE.TubeGeometry(trunkCurve, 14, 0.14, 8, false), trunkMat);
    trunk.castShadow = true;
    g.add(trunk);

    const frondMat = new THREE.MeshStandardMaterial({
      color: 0x3da32d,
      roughness: 0.62,
      side: THREE.DoubleSide,
    });
    const top = new THREE.Vector3(0.06, height, 0);
    for (let i = 0; i < 9; i++) {
      const ang = (i / 9) * Math.PI * 2;
      const frondGeo = new THREE.ConeGeometry(0.42, 1.85, 5);
      frondGeo.translate(0, 0.9, 0);
      frondGeo.scale(0.55, 1, 0.12);
      const frond = new THREE.Mesh(frondGeo, frondMat);
      frond.position.copy(top);
      frond.rotation.y = ang;
      frond.rotation.z = 1.08 + (i % 2) * 0.16;
      frond.castShadow = true;
      g.add(frond);
    }
    return g;
  }

  _createPineTree(scale = 1.0) {
    const g = new THREE.Group();
    const trunk = new THREE.Mesh(
      new THREE.CylinderGeometry(0.16, 0.24, 1.1, 8),
      new THREE.MeshStandardMaterial({ color: 0x5c4028, roughness: 0.9 })
    );
    trunk.position.y = 0.55;
    g.add(trunk);

    const leafMat = new THREE.MeshStandardMaterial({ color: 0x2d5a27, roughness: 0.8 });
    for (let tier = 0; tier < 3; tier++) {
      const cone = new THREE.Mesh(new THREE.ConeGeometry(1.35 - tier * 0.3, 1.8, 9), leafMat);
      cone.position.y = 1.45 + tier * 0.95;
      cone.castShadow = true;
      cone.receiveShadow = true;
      g.add(cone);
    }
    g.scale.setScalar(scale);
    return g;
  }

  _createCar(bodyHex = 0x334e68, isSUV = true) {
    const car = new THREE.Group();
    const paint = new THREE.MeshStandardMaterial({ color: bodyHex, metalness: 0.65, roughness: 0.25 });
    const glass = new THREE.MeshStandardMaterial({ color: 0x0f172a, metalness: 0.85, roughness: 0.12 });
    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.8 });

    const chassis = new THREE.Mesh(new THREE.BoxGeometry(1.75, 0.52, 3.85), paint);
    chassis.position.y = 0.42;
    chassis.castShadow = true;
    car.add(chassis);

    const cabinLen = isSUV ? 2.45 : 1.95;
    const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.52, 0.46, cabinLen), paint);
    cabin.position.set(0, 0.86, isSUV ? -0.15 : -0.1);
    cabin.castShadow = true;
    car.add(cabin);

    const wind = new THREE.Mesh(new THREE.BoxGeometry(1.54, 0.36, cabinLen + 0.06), glass);
    wind.position.copy(cabin.position);
    car.add(wind);

    const wheelPositions = [
      [-0.86, 0.24, 1.22],
      [0.86, 0.24, 1.22],
      [-0.86, 0.24, -1.22],
      [0.86, 0.24, -1.22],
    ];
    for (const [wx, wy, wz] of wheelPositions) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.26, 0.18, 18), wheelMat);
      wheel.rotation.z = Math.PI / 2;
      wheel.position.set(wx, wy, wz);
      car.add(wheel);
    }
    return car;
  }

  _buildMiniatureDesertEnvironment() {
    // Sculpted Golden-Hour Desert Dunes + Stone Compound Wall + Warm Lanterns + Pine Trees (matching 11:16 in the video!)
    const sandGeo = new THREE.PlaneGeometry(110, 95, 96, 96);
    const pos = sandGeo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const y = pos.getY(i);
      const insideYard = Math.abs(x) < 13.6 && Math.abs(y) < 11.6;
      if (insideYard) {
        pos.setZ(i, -0.18);
      } else {
        const dune =
          Math.sin(x * 0.18 + y * 0.08) * 0.65 +
          Math.cos(y * 0.24 - x * 0.06) * 0.45 +
          0.15;
        pos.setZ(i, dune);
      }
    }
    sandGeo.computeVertexNormals();

    const sandMat = new THREE.MeshStandardMaterial({
      color: 0xc89566,
      bumpMap: makeSandBumpTexture(),
      bumpScale: 0.08,
      roughness: 0.88,
      metalness: 0.02,
    });
    sandMat.name = "Desert sand";
    const desertMesh = new THREE.Mesh(sandGeo, sandMat);
    desertMesh.name = "Sculpted desert terrain";
    desertMesh.rotation.x = -Math.PI / 2;
    desertMesh.position.y = -0.12;
    desertMesh.receiveShadow = true;
    this.miniatureEnvGroup.add(desertMesh);

    // Rustic Stone Perimeter Wall + Glowing Corner Lanterns
    const stoneMat = new THREE.MeshStandardMaterial({ color: 0xbba58b, roughness: 0.92 });
    stoneMat.name = "Perimeter stone";
    const wallSpecs = [
      [0, 0.55, -10.8, 25.8, 1.1, 0.45], // North back wall
      [-12.8, 0.55, 0, 0.45, 1.1, 22.0], // West wall
      [12.8, 0.55, 0, 0.45, 1.1, 22.0],  // East wall
      [-6.8, 0.55, 10.8, 12.4, 1.1, 0.45], // South-West front wall
    ];
    for (const [x, y, z, w, h, d] of wallSpecs) {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), stoneMat);
      m.name = "Perimeter stone wall";
      m.position.set(x, y, z);
      m.castShadow = true;
      m.receiveShadow = true;
      this.miniatureEnvGroup.add(m);
    }

    // Glowing Stone Pillar Lanterns
    const lanternMat = new THREE.MeshStandardMaterial({
      color: 0xffe4b5,
      emissive: 0xffa94d,
      emissiveIntensity: 3.0,
    });
    lanternMat.name = "Warm lantern glass";
    const pillarCoords = [
      [-12.8, -10.8],
      [12.8, -10.8],
      [-12.8, 2.2],
      [12.8, 2.2],
      [-12.8, 10.8],
      [-0.8, 10.8],
    ];
    for (const [px, pz] of pillarCoords) {
      const pillar = new THREE.Mesh(new THREE.BoxGeometry(0.72, 1.45, 0.72), stoneMat);
      pillar.name = "Stone lantern pillar";
      pillar.position.set(px, 0.72, pz);
      pillar.castShadow = true;
      this.miniatureEnvGroup.add(pillar);

      const lamp = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.36, 0.32), lanternMat);
      lamp.name = "Glowing lantern";
      lamp.position.set(px, 1.62, pz);
      this.miniatureEnvGroup.add(lamp);

      const pt = new THREE.PointLight(0xffab5e, 1.8, 8);
      pt.position.set(px, 1.9, pz);
      this.miniatureEnvGroup.add(pt);
    }

    // Exterior Conifer / Pine Trees on Dunes
    const pineSpots = [
      [-17.5, -8.5, 1.35],
      [-16.2, -1.2, 1.15],
      [16.8, -7.8, 1.3],
      [16.0, 0.5, 1.15],
      [-18.0, 8.2, 1.25],
      [18.2, 8.8, 1.2],
    ];
    for (const [tx, tz, sc] of pineSpots) {
      const pine = this._createPineTree(sc);
      pine.name = "Desert pine";
      pine.position.set(tx, 0, tz);
      this.miniatureEnvGroup.add(pine);
    }
  }

  _addWall(parent, x, z, w, d, h = 2.55, hasWindow = false) {
    const wallGroup = new THREE.Group();
    const wallMat = this.wallMat;
    const capMat = this.wallCapMat;

    if (hasWindow && Math.max(w, d) > 2.2) {
      // Sill + header + smoked glass pane
      const sill = new THREE.Mesh(new THREE.BoxGeometry(w, 0.55, d), wallMat);
      sill.position.y = 0.275;
      const header = new THREE.Mesh(new THREE.BoxGeometry(w, 0.42, d), wallMat);
      header.position.y = h - 0.21;
      const pane = new THREE.Mesh(
        new THREE.BoxGeometry(w > d ? w * 0.88 : 0.08, h - 0.97, d > w ? d * 0.88 : 0.08),
        this.windowGlassMat
      );
      pane.position.y = 0.55 + (h - 0.97) / 2;
      sill.castShadow = header.castShadow = true;
      sill.receiveShadow = header.receiveShadow = true;
      wallGroup.add(sill, header, pane);
    } else {
      const body = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), wallMat);
      body.position.y = h / 2;
      body.castShadow = true;
      body.receiveShadow = true;
      wallGroup.add(body);
    }

    // Crisp dark architectural top cap (signature look in the video!)
    const cap = new THREE.Mesh(new THREE.BoxGeometry(w + 0.03, 0.09, d + 0.03), capMat);
    cap.position.y = h + 0.045;
    wallGroup.add(cap);

    wallGroup.position.set(x, 0, z);
    wallGroup.userData.floorFootprint = { x, z, w, d };
    parent.add(wallGroup);
    return wallGroup;
  }

  _rebuildArchitecture() {
    const geometries = new Set();
    const materials = new Set();
    const textures = new Set();
    this.houseRoot.traverse((object) => {
      if (object.geometry) geometries.add(object.geometry);
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        if (!material) continue;
        materials.add(material);
        for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
      }
    });
    geometries.forEach((geometry) => geometry.dispose());
    textures.forEach((texture) => texture.dispose());
    materials.forEach((material) => material.dispose());
    this.houseRoot.clear();

    this.stepGroups = {
      grounds: new THREE.Group(),
      pool: new THREE.Group(),
      walls: new THREE.Group(),
      living: new THREE.Group(),
      bedrooms: new THREE.Group(),
      roof: new THREE.Group(),
      warmLights: new THREE.Group(),
    };
    Object.entries(this.stepGroups).forEach(([key, group]) => {
      group.name = ({ grounds: "Grounds and floors", pool: "Pool terrace", walls: "Walls and garage", living: "Living, dining and kitchen", bedrooms: "Bedroom and bath", roof: "Roof", warmLights: "Interior lights" })[key];
    });
    Object.values(this.stepGroups).forEach((g) => this.houseRoot.add(g));

    const isMini = this.viewMode === "miniature";
    const extLiving = this.state.livingRoomExtraMeters;
    const extKitchen = this.state.kitchenExtraMeters;

    this.wallMat = new THREE.MeshStandardMaterial({
      color: isMini ? 0xf3e7d3 : 0xf6f5f0,
      roughness: 0.78,
    });
    this.wallMat.name = "Plaster walls";
    this.wallCapMat = new THREE.MeshStandardMaterial({
      color: isMini ? 0x2b211a : 0x1e293b,
      roughness: 0.5,
    });
    this.wallCapMat.name = "Dark wall caps";
    this.windowGlassMat = new THREE.MeshStandardMaterial({
      color: 0x0f2922,
      roughness: 0.15,
      metalness: 0.6,
      transparent: true,
      opacity: 0.78,
    });
    this.windowGlassMat.name = "Window glass";

    // 1. GROUNDS & INTERIOR FLOOR SLAB
    const lawnMat = new THREE.MeshStandardMaterial({
      color: isMini ? 0x4f7f30 : 0x65b741,
      roughness: 0.88,
    });
    lawnMat.name = "Lawn grass";
    const lawnSlab = new THREE.Mesh(new THREE.BoxGeometry(24.8, 0.28, 21.0), lawnMat);
    lawnSlab.name = "Lawn slab";
    lawnSlab.position.set(0, -0.14, 0);
    lawnSlab.receiveShadow = true;
    this.stepGroups.grounds.add(lawnSlab);

    const floorTex = makeTileTexture(isMini ? "#ead9c1" : "#f3efe6", isMini ? "#d8c2a3" : "#e5dfd3", 12);
    floorTex.repeat.set(6, 5);
    const interiorFloor = new THREE.Mesh(
      new THREE.BoxGeometry(17.6 + extKitchen, 0.14, 11.6 + extLiving),
      new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.65 })
    );
    interiorFloor.name = "Interior tiled floor";
    interiorFloor.position.set(0.2 + extKitchen * 0.5, 0.07, 2.2 + extLiving * 0.5);
    interiorFloor.receiveShadow = true;
    this.stepGroups.grounds.add(interiorFloor);

    // Garage concrete apron & driveway
    const garageFloor = new THREE.Mesh(
      new THREE.BoxGeometry(6.4, 0.15, 6.6),
      new THREE.MeshStandardMaterial({ color: isMini ? 0xd6cfc4 : 0xe2e8f0, roughness: 0.8 })
    );
    garageFloor.name = "Garage floor";
    garageFloor.position.set(5.8, 0.075, 5.4);
    garageFloor.receiveShadow = true;
    this.stepGroups.grounds.add(garageFloor);

    // Corner Palms
    const basePalmSpots = [
      [-10.4, 2.6, 3.3],
      [10.4, 4.2, 3.2],
      [-2.8, 8.8, 3.0],
      [9.6, -5.2, 3.1],
    ];
    for (const [px, pz, ph] of basePalmSpots) {
      const palm = this._createPalmTree(ph);
      palm.position.set(px, 0, pz);
      this.stepGroups.grounds.add(palm);
    }

    // 2. POOL TERRACE & SWIMMING POOL
    const deckTex = makeTileTexture("#ece0cc", "#d8c7ae", 10);
    deckTex.repeat.set(5, 3);
    const poolDeck = new THREE.Mesh(
      new THREE.BoxGeometry(15.6, 0.16, 5.4),
      new THREE.MeshStandardMaterial({ map: deckTex, roughness: 0.72 })
    );
    poolDeck.name = "Pool deck";
    poolDeck.position.set(-0.2, 0.08, -6.2);
    poolDeck.receiveShadow = true;
    this.stepGroups.pool.add(poolDeck);

    this.waterTex = makeWaterCausticsTexture();
    const waterMat = new THREE.MeshStandardMaterial({
      map: this.waterTex,
      color: 0x38bdf8,
      roughness: 0.12,
      metalness: 0.15,
      transparent: true,
      opacity: 0.9,
    });
    waterMat.name = "Pool water";
    const mainPool = new THREE.Mesh(new THREE.BoxGeometry(9.6, 0.18, 2.8), waterMat);
    mainPool.name = "Swimming pool";
    mainPool.position.set(-1.2, 0.12, -6.8);
    const spaPool = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.24, 1.7), waterMat);
    spaPool.name = "Spa pool";
    spaPool.position.set(-6.9, 0.16, -6.2);
    this.stepGroups.pool.add(mainPool, spaPool);

    // Lanai Patio Dining Set & Columns
    const teakMat = new THREE.MeshStandardMaterial({ color: 0x925c2c, roughness: 0.65 });
    teakMat.name = "Teak furniture";
    const patioTable = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.55, 1.05), teakMat);
    patioTable.name = "Patio dining table";
    patioTable.position.set(3.2, 0.42, -5.2);
    patioTable.castShadow = true;
    this.stepGroups.pool.add(patioTable);

    const colMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.5 });
    colMat.name = "White columns";
    for (const cx of [1.2, 4.2, 6.8]) {
      const col = new THREE.Mesh(new THREE.BoxGeometry(0.28, 2.5, 0.28), colMat);
      col.position.set(cx, 1.25, -6.5);
      col.castShadow = true;
      this.stepGroups.pool.add(col);
    }

    // Optional Voice Edit: Palm Trees & Colorful Flower Border Behind Pool!
    if (this.state.poolBackPalmsAndFlowers) {
      for (const bx of [-5.8, 5.4]) {
        const backPalm = this._createPalmTree(3.9);
        backPalm.position.set(bx, 0, -9.35);
        this.stepGroups.pool.add(backPalm);
      }
      // Lush hedge strip + vibrant blossoms along back edge of pool terrace
      const soil = new THREE.Mesh(
        new THREE.BoxGeometry(14.8, 0.18, 0.72),
        new THREE.MeshStandardMaterial({ color: 0x422817, roughness: 0.95 })
      );
      soil.position.set(-0.2, 0.1, -9.15);
      this.stepGroups.pool.add(soil);

      const shrubMat = new THREE.MeshStandardMaterial({ color: 0x2e6f21, roughness: 0.8 });
      const flowerColors = [0xef4444, 0xf59e0b, 0xec4899, 0xf97316, 0xfef08a];
      for (let i = 0; i < 24; i++) {
        const sx = -7.1 + i * 0.6;
        const bush = new THREE.Mesh(new THREE.SphereGeometry(0.32, 12, 10), shrubMat);
        bush.position.set(sx, 0.32, -9.15 + (i % 2) * 0.12);
        bush.castShadow = true;
        this.stepGroups.pool.add(bush);

        const blossom = new THREE.Mesh(
          new THREE.SphereGeometry(0.13, 8, 8),
          new THREE.MeshStandardMaterial({ color: flowerColors[i % flowerColors.length], roughness: 0.5 })
        );
        blossom.position.set(sx + 0.06, 0.56, -9.1);
        this.stepGroups.pool.add(blossom);
      }
    }

    if (this.state.poolLoungeChairs) {
      const cushionMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.6 });
      for (const lx of [-4.2, -2.5]) {
        const lounger = new THREE.Mesh(new THREE.BoxGeometry(0.75, 0.28, 1.85), cushionMat);
        lounger.position.set(lx, 0.28, -4.5);
        lounger.castShadow = true;
        this.stepGroups.pool.add(lounger);
      }
    }

    // 3. ARCHITECTURAL WALLS (Cutaway Dollhouse with Dark Caps)
    const W = this.stepGroups.walls;
    const southLivingZ = 6.2 + extLiving;

    // Master Wing Perimeter & Partitions (Left: x from -8.6 to -3.6)
    this._addWall(W, -6.1, -3.5, 5.0, 0.22, 2.55, true); // Master North pool window
    this._addWall(W, -8.6, 2.15, 0.22, 11.3);            // West exterior wall
    this._addWall(W, -6.1, 7.8, 5.0, 0.22, 2.55, true);  // Master Bath South wall
    this._addWall(W, -3.6, 2.15, 0.22, 11.3);            // Master interior corridor wall
    this._addWall(W, -6.1, 0.6, 5.0, 0.18);              // Master Bed / WIC divider
    this._addWall(W, -6.1, 3.6, 5.0, 0.18);              // WIC / Master Bath divider
    this._addWall(W, -6.1, 2.1, 0.18, 3.0);              // Dual WIC split

    // Great Room & Dining/Kitchen North Glass Walls
    this._addWall(W, -0.8, -3.5, 5.6, 0.22, 2.55, true); // Great Room pool sliders
    this._addWall(W, 5.5 + extKitchen * 0.5, -3.5, 7.0 + extKitchen, 0.22, 2.55, true);

    // East Exterior & Guest/Utility Partitions
    const eastX = 9.0 + extKitchen;
    this._addWall(W, eastX, 2.6, 0.22, 12.2);
    this._addWall(W, 6.8 + extKitchen * 0.5, 2.1, 4.4 + extKitchen, 0.2); // Kitchen / Garage divider
    this._addWall(W, 2.6, 5.4, 0.22, 6.6); // Foyer / Garage West wall

    // South Living / Entry Porch Wall (dynamically moves with livingRoomExtraMeters!)
    this._addWall(W, -0.5, southLivingZ, 6.2, 0.22, 2.55, true);

    // Garage Front Portal (Bottom-Right)
    this._addWall(W, 3.2, 8.7, 1.2, 0.24);
    this._addWall(W, 8.4 + extKitchen, 8.7, 1.2 + extKitchen, 0.24);
    const garageHeader = new THREE.Mesh(new THREE.BoxGeometry(4.4, 0.55, 0.24), this.wallMat);
    garageHeader.position.set(5.8, 2.28, 8.7);
    W.add(garageHeader);

    // Entry Foyer Stairs vs Centered Front Porch Edit!
    if (!this.state.centeredDoorNoStairs) {
      // Initial Front Stairs & Offset Wooden Fence/Door (like 7:47 in the video)
      for (let s = 0; s < 3; s++) {
        const step = new THREE.Mesh(
          new THREE.BoxGeometry(1.8, 0.14, 0.45),
          new THREE.MeshStandardMaterial({ color: 0xe2dcd0, roughness: 0.8 })
        );
        step.position.set(-0.2, 0.08 + s * 0.1, southLivingZ + 0.8 + s * 0.35);
        W.add(step);
      }
      const woodFence = new THREE.Mesh(
        new THREE.BoxGeometry(4.2, 1.45, 0.16),
        new THREE.MeshStandardMaterial({ color: 0xd4b483, roughness: 0.75 })
      );
      woodFence.position.set(5.8, 0.75, 8.75);
      W.add(woodFence);
    } else {
      // Centered Front Door + Symmetrical Columns under Porch!
      const door = new THREE.Mesh(
        new THREE.BoxGeometry(1.15, 2.1, 0.3),
        new THREE.MeshStandardMaterial({ color: 0x7c4a24, roughness: 0.55 })
      );
      door.position.set(-0.5, 1.05, southLivingZ + 0.02);
      W.add(door);

      for (const pcx of [-1.75, 0.75]) {
        const pcol = new THREE.Mesh(new THREE.BoxGeometry(0.28, 2.45, 0.28), colMat);
        pcol.position.set(pcx, 1.22, southLivingZ + 1.15);
        pcol.castShadow = true;
        W.add(pcol);
      }
    }

    if (this.state.garageCars || this.state.centeredDoorNoStairs) {
      const suv = this._createCar(0x2c4a63, true);
      suv.name = "Garage SUV";
      suv.position.set(4.5, 0.14, 5.4);
      const sedan = this._createCar(0xf1efe9, false);
      sedan.name = "Garage sedan";
      sedan.position.set(7.1, 0.14, 5.4);
      W.add(suv, sedan);
    }

    // 4. LIVING, DINING & KITCHEN FURNITURE
    const L = this.stepGroups.living;
    const sofaMat = new THREE.MeshStandardMaterial({ color: 0x8eaec4, roughness: 0.75 });
    sofaMat.name = "Sofa upholstery";
    const rug = new THREE.Mesh(
      new THREE.BoxGeometry(3.6, 0.03, 4.2 + extLiving * 0.5),
      new THREE.MeshStandardMaterial({ color: 0xf5efe6, roughness: 0.92 })
    );
    rug.name = "Living room rug";
    rug.position.set(-1.1, 0.16, 0.8 + extLiving * 0.35);
    L.add(rug);

    const sofaMain = new THREE.Mesh(new THREE.BoxGeometry(0.95, 0.68, 2.9), sofaMat);
    sofaMain.name = "Living room sofa";
    sofaMain.position.set(0.15, 0.48, 0.8 + extLiving * 0.35);
    sofaMain.castShadow = true;
    const sofaBack = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.92, 2.9), sofaMat);
    sofaBack.position.set(0.52, 0.6, 0.8 + extLiving * 0.35);
    L.add(sofaMain, sofaBack);

    const coffeeTable = new THREE.Mesh(new THREE.BoxGeometry(0.75, 0.38, 1.45), teakMat);
    coffeeTable.name = "Coffee table";
    coffeeTable.position.set(-1.05, 0.34, 0.8 + extLiving * 0.35);
    coffeeTable.castShadow = true;
    L.add(coffeeTable);

    const chairMat = new THREE.MeshStandardMaterial({ color: 0xfef3c7, roughness: 0.7 });
    chairMat.name = "Armchair upholstery";
    for (const cz of [-1.1, 2.7 + extLiving * 0.65]) {
      const armchair = new THREE.Mesh(new THREE.BoxGeometry(0.88, 0.68, 0.88), chairMat);
      armchair.position.set(-1.1, 0.48, cz);
      armchair.castShadow = true;
      L.add(armchair);
    }

    // Dining Table + 6 Chairs
    const diningTable = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.74, 2.35), teakMat);
    diningTable.name = "Dining table";
    diningTable.position.set(2.5, 0.5, 0.4);
    diningTable.castShadow = true;
    L.add(diningTable);

    // Waterfall Kitchen Island + Cabinetry
    const marbleMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.25 });
    marbleMat.name = "White marble";
    const island = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.88, 3.1), marbleMat);
    island.name = "Kitchen island";
    island.position.set(5.1, 0.58, -0.2);
    island.castShadow = true;
    const backCounter = new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.88, 4.2), marbleMat);
    backCounter.name = "Kitchen counter";
    backCounter.position.set(6.9 + extKitchen * 0.4, 0.58, -0.4);
    backCounter.castShadow = true;
    L.add(island, backCounter);

    // 5. BEDROOM & MASTER BATH FIXTURES
    const B = this.stepGroups.bedrooms;
    const bedFrame = new THREE.Mesh(new THREE.BoxGeometry(2.35, 0.52, 2.15), marbleMat);
    bedFrame.name = "Bed frame";
    bedFrame.position.set(-7.1, 0.4, -1.4);
    bedFrame.castShadow = true;
    const blanket = new THREE.Mesh(
      new THREE.BoxGeometry(1.5, 0.56, 2.18),
      new THREE.MeshStandardMaterial({ color: 0x94a89a, roughness: 0.8 })
    );
    blanket.position.set(-6.68, 0.41, -1.4);
    B.add(bedFrame, blanket);

    // Soaking Tub & Dual Vanity
    const tub = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.48, 0.58, 24), marbleMat);
    tub.name = "Soaking tub";
    tub.scale.set(1, 1, 1.65);
    tub.position.set(-7.4, 0.42, 6.2);
    const vanity = new THREE.Mesh(new THREE.BoxGeometry(0.75, 0.82, 2.4), marbleMat);
    vanity.name = "Bathroom vanity";
    vanity.position.set(-4.2, 0.54, 5.6);
    B.add(tub, vanity);

    // 6. OPTIONAL ROOF OVERHANG
    const roofMesh = new THREE.Mesh(
      new THREE.BoxGeometry(18.6 + extKitchen, 0.24, 13.4 + extLiving),
      new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.65, transparent: true, opacity: 0.92 })
    );
    roofMesh.name = "Roof overhang";
    roofMesh.position.set(0.3 + extKitchen * 0.5, 2.75, 2.4 + extLiving * 0.5);
    this.stepGroups.roof.add(roofMesh);
    this.stepGroups.roof.visible = this.state.showRoof;

    // 7. WARM COZY INTERIOR 2700K LAMPS FOR MINIATURE DIORAMA MODE
    const roomLampCoords = [
      [-6.2, 2.1, -1.2], // Master Suite
      [-1.0, 2.2, 0.9],  // Great Room
      [3.8, 2.2, 0.2],   // Dining & Kitchen
      [-6.0, 2.0, 5.8],  // Master Bath
      [5.8, 2.1, 5.4],   // 2-Car Garage
    ];
    for (const [lx, ly, lz] of roomLampCoords) {
      const pt = new THREE.PointLight(0xffb469, 2.4, 9.5);
      pt.position.set(lx, ly, lz);
      this.stepGroups.warmLights.add(pt);
    }
    this.stepGroups.warmLights.visible = isMini;

    // Exploded Architectural Layers option
    if (this.state.explodedLayers) {
      this.stepGroups.walls.position.y = 2.2;
      this.stepGroups.living.position.y = 4.2;
      this.stepGroups.bedrooms.position.y = 4.2;
      this.stepGroups.roof.visible = this.state.roofVisibilityOverride ?? true;
      this.stepGroups.roof.position.y = 6.6;
    }

    this._applyLightingForMode();
  }

  _applyLightingForMode() {
    const isMini = this.viewMode === "miniature";
    this.miniatureEnvGroup.visible = isMini;
    if (this.stepGroups?.warmLights) {
      this.stepGroups.warmLights.visible = isMini;
    }

    if (isMini) {
      // Warm Golden-Hour Desert Tilt-Shift Diorama Lighting
      this.scene.background = new THREE.Color(0x9a6b42);
      this.hemiLight.color.set(0xffdcb5);
      this.hemiLight.groundColor.set(0x5c3d24);
      this.hemiLight.intensity = 0.72;

      this.sunLight.color.set(0xffb066);
      this.sunLight.intensity = 2.65;
      this.sunLight.position.set(-22, 16, 14);
      this.renderer.toneMappingExposure = 1.16;
    } else {
      // Crisp Obsidian 3D CAD Studio Lighting
      this.scene.background = null;
      this.hemiLight.color.set(0xf8fafc);
      this.hemiLight.groundColor.set(0x334155);
      this.hemiLight.intensity = 1.25;

      this.sunLight.color.set(0xffffff);
      this.sunLight.intensity = 2.0;
      this.sunLight.position.set(16, 26, 14);
      this.renderer.toneMappingExposure = 1.06;
    }
  }

  mount() {
    this.container.innerHTML = "";
    this.container.appendChild(this.renderer.domElement);
    this.active = true;
    this.resize();
  }

  unmount() {
    this.active = false;
    this.sequence = (this.sequence || 0) + 1;
    document.getElementById("exploded-callout-layer").classList.add("hidden");
  }

  playInitialBuild(onStepProgress, onComplete, onMiniatureReady) {
    const sequence = this.sequence = (this.sequence || 0) + 1;
    this.viewMode = "3d";
    this.miniatureReady = false;
    this._rebuildArchitecture();

    this.cameraGoal = {
      pos: new THREE.Vector3(-11.5, 17.5, 20.5),
      target: new THREE.Vector3(0.2, 0.4, 0.8),
      alpha: 0,
    };

    const order = [
      { key: "walls", label: "Raising the walls" },
      { key: "living", label: "Furnishing the living spaces" },
      { key: "bedrooms", label: "Fitting bedroom and baths" },
      { key: "pool", label: "Pouring the pool terrace" },
      { key: "grounds", label: "Laying out the grounds" },
      { key: "roof", label: "Setting the roof" },
    ];

    Object.values(this.stepGroups).forEach((g) => (g.visible = false));

    let idx = 0;
    const labels = order.map((o) => o.label);

    const stepFn = () => {
      if (!this.active || sequence !== this.sequence) return;
      const key = order[idx].key;
      if (key === "roof") {
        this.stepGroups.roof.visible = this.state.showRoof;
      } else {
        this.stepGroups[key].visible = true;
      }
      if (onStepProgress) onStepProgress(labels, idx);
      idx++;
      if (idx < order.length) {
        setTimeout(stepFn, 380);
      } else {
        if (onComplete) onComplete();
        // Background craft of the Photorealistic Miniature
        setTimeout(() => {
          if (!this.active || sequence !== this.sequence) return;
          this.miniatureReady = true;
          if (onMiniatureReady) onMiniatureReady();
        }, 2100);
      }
    };
    stepFn();
  }

  applyEdit(params = {}, onStepProgress, onComplete) {
    const sequence = this.sequence = (this.sequence || 0) + 1;
    const steps = [];

    if (params.centerDoorRemoveStairs) {
      this.state.centeredDoorNoStairs = true;
      this.state.garageCars = true;
      steps.push("Clearing the foyer stairs", "Centring the entry porch", "Parking vehicles in 2-car garage");
    }
    if (params.addGarageCars) {
      this.state.garageCars = true;
      steps.push("Parking SUV and sedan in garage");
    }
    if (typeof params.enlargeLivingRoom === "number") {
      this.state.livingRoomExtraMeters = Math.min(5, Math.max(0, (this.state.livingRoomExtraMeters || 0) + params.enlargeLivingRoom));
      steps.push("Extending the great room walls", "Rearranging the larger living space");
    }
    if (typeof params.enlargeKitchen === "number") {
      this.state.kitchenExtraMeters = Math.min(4, Math.max(0, (this.state.kitchenExtraMeters || 0) + params.enlargeKitchen));
      steps.push("Expanding the waterfall kitchen");
    }
    if (params.addPoolPalmsAndFlowers) {
      this.state.poolBackPalmsAndFlowers = true;
      steps.push("Planting tropical palms beyond the pool", "Arranging flowering border hedge");
    }
    if (params.addLoungeChairs) {
      this.state.poolLoungeChairs = true;
      steps.push("Placing poolside sun loungers");
    }
    if (params.toggleRoof && typeof params.showRoof !== "boolean") {
      this.state.showRoof = !this.stepGroups.roof.visible;
      this.state.roofVisibilityOverride = this.state.showRoof;
      steps.push(this.state.showRoof ? "Closing modern overhang roof" : "Opening architectural cutaway");
    }
    if (typeof params.showRoof === "boolean") {
      if (this.stepGroups.roof.visible !== params.showRoof) {
        steps.push(params.showRoof ? "Showing the roof" : "Hiding the roof");
      }
      this.state.showRoof = params.showRoof;
      this.state.roofVisibilityOverride = params.showRoof;
    }
    if (typeof params.showLabels === "boolean") {
      this.state.showRoomLabels = params.showLabels;
      steps.push("Updating architectural room callouts");
    }
    if (typeof params.explodedHouse === "boolean") {
      this.state.explodedLayers = params.explodedHouse;
      steps.push(params.explodedHouse ? "Separating architectural layers" : "Reassembling floor plan slab");
    }

    if (steps.length === 0) {
      if (onStepProgress) onStepProgress([], 0);
      if (onComplete) onComplete();
      return;
    }

    this._rebuildArchitecture();

    // Top-down / isometric view framing the edit cleanly like 10:59 in the video
    this.cameraGoal = {
      pos: new THREE.Vector3(0, 22.5, 16.2),
      target: new THREE.Vector3(0.2, 0.2, 0.2),
      alpha: 0,
    };

    let idx = 0;
    const next = () => {
      if (!this.active || sequence !== this.sequence) return;
      if (onStepProgress) onStepProgress(steps, idx);
      idx++;
      if (idx < steps.length) setTimeout(next, 320);
      else if (onComplete) setTimeout(onComplete, 220);
    };
    next();
  }

  setViewMode(mode) {
    this.sequence = (this.sequence || 0) + 1;
    this.viewMode = mode === "miniature" ? "miniature" : "3d";
    this._rebuildArchitecture();
    if (this.viewMode === "miniature") {
      this.cameraGoal = {
        pos: new THREE.Vector3(0, 29.5, 22.5),
        target: new THREE.Vector3(0, 0, -0.5),
        alpha: 0,
      };
    } else {
      this.cameraGoal = {
        pos: new THREE.Vector3(-10.5, 18.5, 20.5),
        target: new THREE.Vector3(0.2, 0.3, 0.6),
        alpha: 0,
      };
    }
  }

  projectSnapshot() {
    return {
      version: 1,
      view: "house",
      camera: { position: this.camera.position.toArray(), target: this.controls.target.toArray() },
      state: { mode: this.viewMode, ...this.state },
    };
  }

  restoreProject(project) {
    this.sequence = (this.sequence || 0) + 1;
    this.cameraGoal = null;
    this.viewMode = project.state.mode;
    this.state = { ...project.state };
    delete this.state.mode;
    this._rebuildArchitecture();
    this.miniatureReady = true;
    this.camera.position.fromArray(project.camera.position);
    this.controls.target.fromArray(project.camera.target);
    this.controls.update();
  }

  capturePNG() {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }

  roomLabels() {
    return [
      { name: "Master Suite", x: -6.2, z: -1.4, y: 1.4 },
      { name: "Great Room", x: -0.8, z: 1.0 + this.state.livingRoomExtraMeters * 0.5, y: 1.4 },
      { name: "Kitchen & Dining", x: 4.5 + this.state.kitchenExtraMeters * 0.5, z: 0, y: 1.4 },
      { name: "Swimming Pool", x: -1.2, z: -6.8, y: 0.6 },
      { name: "2-Car Garage", x: 5.8, z: 5.4, y: 1.4 },
    ];
  }

  _updateRoomCallouts() {
    const layer = document.getElementById("exploded-callout-layer");
    if (!this.active || !this.state.showRoomLabels) {
      layer.classList.add("hidden");
      return;
    }
    layer.classList.remove("hidden");
    this.calloutSvg.innerHTML = "";

    const w = window.innerWidth;
    const h = window.innerHeight;
    let html = "";
    for (const r of this.roomLabels()) {
      const ndc = new THREE.Vector3(r.x, r.y, r.z).project(this.camera);
      if (ndc.z > 1) continue;
      const sx = (ndc.x * 0.5 + 0.5) * w;
      const sy = (-ndc.y * 0.5 + 0.5) * h;
      html += `<div class="exploded-pill" style="left:${sx.toFixed(1)}px; top:${sy.toFixed(1)}px; transform:translate(-50%, -50%);">${r.name}</div>`;
    }
    this.calloutLabelsEl.innerHTML = html;
  }

  tick(dt) {
    if (!this.active) return;
    this.phase += dt;

    if (this.waterTex) {
      this.waterTex.offset.x = (this.phase * 0.04) % 1;
      this.waterTex.offset.y = Math.sin(this.phase * 0.6) * 0.03;
    }

    if (this.cameraGoal) {
      this.cameraGoal.alpha = Math.min(1, this.cameraGoal.alpha + dt * 2.2);
      this.camera.position.lerp(this.cameraGoal.pos, dt * 3.8);
      this.controls.target.lerp(this.cameraGoal.target, dt * 3.8);
      if (this.cameraGoal.alpha >= 0.99) this.cameraGoal = null;
    }

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this._updateRoomCallouts();
  }
}
