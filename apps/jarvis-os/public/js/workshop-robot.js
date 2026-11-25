import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

function makeAcousticFabricTexture() {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 256;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#222733";
  ctx.fillRect(0, 0, 256, 256);

  for (let y = 0; y < 256; y += 4) {
    for (let x = 0; x < 256; x += 4) {
      const shade = ((x + y) % 8 === 0) ? "#2f3646" : "#181c26";
      ctx.fillStyle = shade;
      ctx.fillRect(x, y, 3, 3);
    }
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(18, 7);
  return tex;
}

function makePCBTexture() {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#0b3b24";
  ctx.fillRect(0, 0, 512, 512);

  ctx.strokeStyle = "#d4af37";
  ctx.lineWidth = 3;
  for (let r = 45; r < 235; r += 22) {
    ctx.beginPath();
    ctx.arc(256, 256, r, 0, Math.PI * 1.65);
    ctx.stroke();
  }
  ctx.fillStyle = "#eab308";
  for (let i = 0; i < 36; i++) {
    const a = (i / 36) * Math.PI * 2;
    ctx.beginPath();
    ctx.arc(256 + Math.cos(a) * 215, 256 + Math.sin(a) * 215, 5, 0, Math.PI * 2);
    ctx.fill();
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeBatteryTexture() {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 256;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#11141c";
  ctx.fillRect(0, 0, 512, 256);
  ctx.strokeStyle = "#334155";
  ctx.lineWidth = 4;
  ctx.strokeRect(14, 14, 484, 228);
  ctx.fillStyle = "#94a3b8";
  ctx.font = "600 22px JetBrains Mono, monospace";
  ctx.fillText("JARVIS CELL · 7.4V 3200mAh", 68, 136);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export class RobotWorkshop {
  constructor(containerEl, calloutSvg, calloutLabelsEl) {
    this.container = containerEl;
    this.calloutSvg = calloutSvg;
    this.calloutLabelsEl = calloutLabelsEl;

    this.active = false;
    this.explodeTarget = 0;
    this.explodeCurrent = 0;
    this.housingColorName = "silver";
    this.ringHex = "#10b981";
    this.phase = 0;
    this.voicePulse = 0;
    this.cameraGoal = null;
    this.parts = [];

    this._initScene();
    this._buildRobot();
  }

  _initScene() {
    const w = window.innerWidth;
    const h = window.innerHeight;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 120);
    this.camera.position.set(2.4, 1.35, 8.2);

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.18;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.target.set(0, 0.35, 0);
    this.controls.minDistance = 3.2;
    this.controls.maxDistance = 18;

    // Dramatic studio lighting
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.4);
    keyLight.position.set(5, 8, 6);
    keyLight.castShadow = true;
    this.scene.add(keyLight);

    const rimLeft = new THREE.DirectionalLight(0x7dd3fc, 1.65);
    rimLeft.position.set(-6, 4, -4);
    this.scene.add(rimLeft);

    const fillBottom = new THREE.DirectionalLight(0x94a3b8, 0.65);
    fillBottom.position.set(0, -4, 5);
    this.scene.add(fillBottom);

    this.reactorLight = new THREE.PointLight(0x10b981, 2.6, 8);
    this.reactorLight.position.set(0, 1.1, 1.85);
    this.scene.add(this.reactorLight);

    // Subtle dark studio shadow pedestal (no bright horizon line)
    const floorCanvas = document.createElement("canvas");
    floorCanvas.width = 256;
    floorCanvas.height = 256;
    const fctx = floorCanvas.getContext("2d");
    const fgrad = fctx.createRadialGradient(128, 128, 12, 128, 128, 124);
    fgrad.addColorStop(0, "rgba(22, 29, 45, 0.85)");
    fgrad.addColorStop(0.55, "rgba(10, 14, 24, 0.35)");
    fgrad.addColorStop(1, "rgba(5, 7, 12, 0)");
    fctx.fillStyle = fgrad;
    fctx.fillRect(0, 0, 256, 256);
    const floorAlphaTex = new THREE.CanvasTexture(floorCanvas);

    const floorGeo = new THREE.PlaneGeometry(7.5, 7.5);
    const floorMat = new THREE.MeshStandardMaterial({
      map: floorAlphaTex,
      transparent: true,
      roughness: 0.28,
      metalness: 0.55,
      depthWrite: false,
    });
    this.floorMesh = new THREE.Mesh(floorGeo, floorMat);
    this.floorMesh.rotation.x = -Math.PI / 2;
    this.floorMesh.position.y = -1.6;
    this.scene.add(this.floorMesh);

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

  _registerPart(group, config) {
    group.name = config.label;
    group.position.copy(config.basePos);
    this.robotRoot.add(group);
    this.parts.push({
      group,
      basePos: config.basePos.clone(),
      explodePos: config.explodePos.clone(),
      label: config.label,
      side: config.side || "left",
      showCallout: config.showCallout !== false,
      stepIndex: config.stepIndex ?? 0,
      anchorOffset: config.anchorOffset || new THREE.Vector3(0, 0, 0),
    });
  }

  _buildRobot() {
    this.robotRoot = new THREE.Group();
    this.robotRoot.name = "Jarvis Reactor Companion";
    // Slight rotation in exploded view aligns eye to front-left like the video
    this.scene.add(this.robotRoot);

    const alumMat = new THREE.MeshStandardMaterial({
      color: 0xd8dee9,
      metalness: 0.9,
      roughness: 0.22,
    });
    this.alumMat = alumMat;

    const darkMetalMat = new THREE.MeshStandardMaterial({
      color: 0x1e2430,
      metalness: 0.78,
      roughness: 0.32,
    });

    const fabricTex = makeAcousticFabricTexture();
    this.fabricMat = new THREE.MeshStandardMaterial({
      color: 0x2b3242,
      map: fabricTex,
      bumpMap: fabricTex,
      bumpScale: 0.035,
      roughness: 0.82,
      metalness: 0.08,
    });

    this.shellMat = new THREE.MeshStandardMaterial({
      color: 0x131720,
      roughness: 0.56,
      metalness: 0.14,
    });

    this.housingMat = new THREE.MeshStandardMaterial({
      color: 0xd8dee9,
      metalness: 0.88,
      roughness: 0.22,
    });

    this.reactorRingMat = new THREE.MeshStandardMaterial({
      color: 0x10b981,
      emissive: 0x00ff88,
      emissiveIntensity: 2.4,
      roughness: 0.15,
      metalness: 0.1,
    });

    this.waistLedMat = new THREE.MeshStandardMaterial({
      color: 0x10b981,
      emissive: 0x00ff88,
      emissiveIntensity: 2.2,
    });
    alumMat.name = "Brushed aluminium";
    darkMetalMat.name = "Dark metal";
    this.fabricMat.name = "Acoustic fabric";
    this.shellMat.name = "Soft-touch shell";
    this.housingMat.name = "Anodised housing";
    this.reactorRingMat.name = "Emerald reactor light";
    this.waistLedMat.name = "Emerald indicator light";

    // 1. Aluminium base (step 0)
    const baseGrp = new THREE.Group();
    const footDisc = new THREE.Mesh(new THREE.CylinderGeometry(1.18, 1.08, 0.16, 64), alumMat);
    const rubberPad = new THREE.Mesh(
      new THREE.CylinderGeometry(1.04, 1.04, 0.05, 64),
      new THREE.MeshStandardMaterial({ color: 0x0b0e14, roughness: 0.9 })
    );
    rubberPad.position.y = -0.09;
    baseGrp.add(footDisc, rubberPad);
    this._registerPart(baseGrp, {
      basePos: new THREE.Vector3(0, -1.48, 0),
      explodePos: new THREE.Vector3(0, -3.55, 0),
      label: "Aluminium base",
      side: "left",
      stepIndex: 0,
    });

    // 2. Lower acoustic band / woven cylinder (step 4)
    const acousticGrp = new THREE.Group();
    const grilleMesh = new THREE.Mesh(new THREE.CylinderGeometry(1.24, 1.19, 1.28, 64, 1, false), this.fabricMat);
    acousticGrp.add(grilleMesh);
    this._registerPart(acousticGrp, {
      basePos: new THREE.Vector3(0, -0.82, 0),
      explodePos: new THREE.Vector3(0, -3.05, 0),
      label: "Acoustic mesh shell",
      showCallout: false,
      stepIndex: 4,
    });

    // 3. Full-range speaker driver (step 1)
    const driverGrp = new THREE.Group();
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.68, 0.34, 48, 1, true), darkMetalMat);
    cone.rotation.x = Math.PI;
    const surround = new THREE.Mesh(
      new THREE.TorusGeometry(0.68, 0.06, 20, 48),
      new THREE.MeshStandardMaterial({ color: 0x111318, roughness: 0.75 })
    );
    surround.rotation.x = Math.PI / 2;
    surround.position.y = 0.16;
    const magnet = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.32, 0.18, 36), alumMat);
    magnet.position.y = -0.18;
    driverGrp.add(cone, surround, magnet);
    this._registerPart(driverGrp, {
      basePos: new THREE.Vector3(0, -1.08, 0),
      explodePos: new THREE.Vector3(0, -2.18, 0),
      label: "Full-range speaker driver",
      side: "left",
      stepIndex: 1,
    });

    // 4. Machined inner frame + 4 standoffs (step 1)
    const frameGrp = new THREE.Group();
    const frameRing = new THREE.Mesh(new THREE.TorusGeometry(0.76, 0.06, 20, 56), alumMat);
    frameRing.rotation.x = Math.PI / 2;
    frameGrp.add(frameRing);
    for (let i = 0; i < 4; i++) {
      const a = (i / 4) * Math.PI * 2 + Math.PI / 4;
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.42, 16), alumMat);
      post.position.set(Math.cos(a) * 0.72, -0.21, Math.sin(a) * 0.72);
      frameGrp.add(post);
    }
    this._registerPart(frameGrp, {
      basePos: new THREE.Vector3(0, -0.68, 0),
      explodePos: new THREE.Vector3(0, -1.42, 0),
      label: "Machined inner frame",
      side: "left",
      stepIndex: 1,
    });

    // 5. Battery pack (step 2)
    const battGrp = new THREE.Group();
    const battMat = new THREE.MeshStandardMaterial({ map: makeBatteryTexture(), roughness: 0.45, metalness: 0.2 });
    const battBox = new THREE.Mesh(new THREE.BoxGeometry(1.02, 0.36, 0.74), battMat);
    battGrp.add(battBox);
    this._registerPart(battGrp, {
      basePos: new THREE.Vector3(0, -0.36, 0),
      explodePos: new THREE.Vector3(0, -0.74, 0),
      label: "Battery pack",
      side: "left",
      stepIndex: 2,
    });

    // 6. Main logic board (step 2)
    const pcbGrp = new THREE.Group();
    const pcbDisc = new THREE.Mesh(
      new THREE.CylinderGeometry(0.84, 0.84, 0.045, 48),
      new THREE.MeshStandardMaterial({ map: makePCBTexture(), roughness: 0.35, metalness: 0.35 })
    );
    const soc = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.06, 0.36), darkMetalMat);
    soc.position.y = 0.045;
    pcbGrp.add(pcbDisc, soc);
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2;
      const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.09, 14), alumMat);
      cap.position.set(Math.cos(a) * 0.56, 0.055, Math.sin(a) * 0.56);
      pcbGrp.add(cap);
    }
    this._registerPart(pcbGrp, {
      basePos: new THREE.Vector3(0, -0.04, 0),
      explodePos: new THREE.Vector3(0, -0.1, 0),
      label: "Main logic board",
      side: "left",
      stepIndex: 2,
    });

    // 7. Finned heat sink (step 3)
    const sinkGrp = new THREE.Group();
    const sinkBase = new THREE.Mesh(new THREE.BoxGeometry(0.58, 0.05, 0.54), darkMetalMat);
    sinkGrp.add(sinkBase);
    for (let f = -5; f <= 5; f++) {
      const fin = new THREE.Mesh(new THREE.BoxGeometry(0.024, 0.34, 0.52), darkMetalMat);
      fin.position.set(f * 0.05, 0.18, 0);
      sinkGrp.add(fin);
    }
    this._registerPart(sinkGrp, {
      basePos: new THREE.Vector3(0, 0.14, 0),
      explodePos: new THREE.Vector3(0, 0.48, 0),
      label: "Finned heat sink",
      side: "left",
      stepIndex: 3,
    });

    // 8. Copper/Kapton Flex cables (step 3)
    const flexGrp = new THREE.Group();
    const copperMat = new THREE.MeshStandardMaterial({
      color: 0xd97706,
      metalness: 0.72,
      roughness: 0.28,
    });
    const curve1 = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0.45, -0.15, 0),
      new THREE.Vector3(0.88, 0.25, 0.12),
      new THREE.Vector3(0.84, 0.92, 0.08),
      new THREE.Vector3(0.52, 1.32, 0),
    ]);
    const curve2 = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0.38, -0.05, -0.18),
      new THREE.Vector3(0.78, 0.32, -0.22),
      new THREE.Vector3(0.72, 0.78, -0.15),
    ]);
    flexGrp.add(new THREE.Mesh(new THREE.TubeGeometry(curve1, 32, 0.028, 8, false), copperMat));
    flexGrp.add(new THREE.Mesh(new THREE.TubeGeometry(curve2, 24, 0.024, 8, false), copperMat));
    this._registerPart(flexGrp, {
      basePos: new THREE.Vector3(0, 0.1, 0),
      explodePos: new THREE.Vector3(1.18, 0.52, 0),
      label: "Flex cables",
      side: "right",
      anchorOffset: new THREE.Vector3(0.82, 0.52, 0),
      stepIndex: 3,
    });

    // 9. Aluminium waist ring + green LED dot (step 4)
    const waistGrp = new THREE.Group();
    const waistTorus = new THREE.Mesh(new THREE.CylinderGeometry(1.255, 1.255, 0.09, 64), alumMat);
    const tinyLed = new THREE.Mesh(new THREE.SphereGeometry(0.022, 12, 12), this.waistLedMat);
    tinyLed.position.set(0, -0.06, 1.245);
    waistGrp.add(waistTorus, tinyLed);
    this._registerPart(waistGrp, {
      basePos: new THREE.Vector3(0, -0.15, 0),
      explodePos: new THREE.Vector3(0, 1.08, 0),
      label: "Aluminium waist ring",
      side: "left",
      stepIndex: 4,
    });

    // 10. Soft-touch body shell (step 6)
    const shellGrp = new THREE.Group();
    const torsoCyl = new THREE.Mesh(new THREE.CylinderGeometry(1.16, 1.25, 1.72, 64), this.shellMat);
    const shoulderDome = new THREE.Mesh(
      new THREE.SphereGeometry(1.16, 64, 32, 0, Math.PI * 2, 0, Math.PI * 0.48),
      this.shellMat
    );
    shoulderDome.position.y = 0.85;
    shoulderDome.scale.set(1, 0.48, 1);
    shellGrp.add(torsoCyl, shoulderDome);
    this._registerPart(shellGrp, {
      basePos: new THREE.Vector3(0, 0.74, 0),
      explodePos: new THREE.Vector3(0, 1.72, 0),
      label: "Soft-touch body shell",
      side: "left",
      anchorOffset: new THREE.Vector3(-0.9, -0.35, 0),
      stepIndex: 6,
    });

    // 11. Reactor light ring (step 5)
    const lightRingGrp = new THREE.Group();
    const glowTorus = new THREE.Mesh(new THREE.TorusGeometry(0.56, 0.032, 24, 64), this.reactorRingMat);
    const ringBacking = new THREE.Mesh(new THREE.RingGeometry(0.49, 0.62, 64), darkMetalMat);
    ringBacking.position.z = -0.02;
    lightRingGrp.add(glowTorus, ringBacking);
    // Micro HUD ticks inside the emerald eye
    this.eyeTickGroup = new THREE.Group();
    for (let t = 0; t < 24; t++) {
      const ang = (t / 24) * Math.PI * 2;
      const tick = new THREE.Mesh(new THREE.BoxGeometry(0.015, 0.055, 0.01), this.reactorRingMat);
      tick.position.set(Math.cos(ang) * 0.46, Math.sin(ang) * 0.46, 0.01);
      tick.rotation.z = ang + Math.PI / 2;
      this.eyeTickGroup.add(tick);
    }
    lightRingGrp.add(this.eyeTickGroup);
    this._registerPart(lightRingGrp, {
      basePos: new THREE.Vector3(0, 0.92, 1.18),
      explodePos: new THREE.Vector3(-0.72, 1.85, 1.05),
      label: "Reactor light ring",
      side: "right",
      stepIndex: 5,
    });

    // 12. Dark glass eye (step 6)
    const eyeGrp = new THREE.Group();
    const glassMat = new THREE.MeshPhysicalMaterial({
      color: 0x050a0e,
      roughness: 0.06,
      metalness: 0.1,
      transmission: 0.55,
      thickness: 0.4,
      clearcoat: 1.0,
    });
    const lensDome = new THREE.Mesh(
      new THREE.SphereGeometry(0.52, 48, 24, 0, Math.PI * 2, 0, Math.PI * 0.35),
      glassMat
    );
    lensDome.rotation.x = Math.PI / 2;
    lensDome.position.z = -0.18;
    const innerPupil = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.22, 0.12, 32), darkMetalMat);
    innerPupil.rotation.x = Math.PI / 2;
    innerPupil.position.z = -0.06;
    eyeGrp.add(lensDome, innerPupil);
    this._registerPart(eyeGrp, {
      basePos: new THREE.Vector3(0, 0.92, 1.24),
      explodePos: new THREE.Vector3(-1.35, 1.85, 1.55),
      label: "Dark glass eye",
      side: "left",
      stepIndex: 6,
    });

    // 13. Anodised reactor housing bezel (step 6)
    const housingGrp = new THREE.Group();
    const outerBezel = new THREE.Mesh(new THREE.TorusGeometry(0.66, 0.11, 32, 64), this.housingMat);
    const sleeve = new THREE.Mesh(new THREE.CylinderGeometry(0.71, 0.74, 0.32, 64, 1, true), this.housingMat);
    sleeve.rotation.x = Math.PI / 2;
    sleeve.position.z = -0.14;
    housingGrp.add(outerBezel, sleeve);
    this.housingPartRef = {
      basePos: new THREE.Vector3(0, 0.92, 1.22),
      explodePos: new THREE.Vector3(-2.12, 1.85, 2.15),
      label: "Anodised reactor housing",
      side: "left",
      stepIndex: 6,
    };
    this._registerPart(housingGrp, this.housingPartRef);
    this.housingPartEntry = this.parts[this.parts.length - 1];

    // 14. Far-field microphone ring (step 7 — enclosed cleanly inside shell when assembled)
    const micGrp = new THREE.Group();
    const micRing = new THREE.Mesh(
      new THREE.TorusGeometry(0.76, 0.025, 16, 56),
      new THREE.MeshStandardMaterial({ color: 0x166534, metalness: 0.4, roughness: 0.35 })
    );
    micRing.rotation.x = Math.PI / 2;
    micGrp.add(micRing);
    for (let m = 0; m < 6; m++) {
      const a = (m / 6) * Math.PI * 2;
      const pad = new THREE.Mesh(
        new THREE.BoxGeometry(0.06, 0.03, 0.06),
        new THREE.MeshStandardMaterial({ color: 0xfacc15, metalness: 0.9, roughness: 0.2 })
      );
      pad.position.set(Math.cos(a) * 0.76, 0.02, Math.sin(a) * 0.76);
      micGrp.add(pad);
    }
    this._registerPart(micGrp, {
      basePos: new THREE.Vector3(0, 1.42, 0),
      explodePos: new THREE.Vector3(0, 2.75, 0),
      label: "Far-field microphone ring",
      side: "left",
      stepIndex: 7,
    });

    // 15. Brushed Touch top cap (step 7 — flush crown on shoulderDome)
    const capGrp = new THREE.Group();
    const topCap = new THREE.Mesh(
      new THREE.SphereGeometry(0.86, 64, 24, 0, Math.PI * 2, 0, Math.PI * 0.28),
      alumMat
    );
    topCap.scale.set(1, 0.4, 1);
    capGrp.add(topCap);
    this._registerPart(capGrp, {
      basePos: new THREE.Vector3(0, 1.84, 0),
      explodePos: new THREE.Vector3(0, 3.22, 0),
      label: "Touch top cap",
      side: "left",
      stepIndex: 7,
    });
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
    this.calloutSvg.innerHTML = "";
    this.calloutLabelsEl.innerHTML = "";
  }

  playProgressiveBuild(onStepProgress, onComplete) {
    const sequence = this.sequence = (this.sequence || 0) + 1;
    this.explodeTarget = 0;
    this.explodeCurrent = 0;
    this.robotRoot.rotation.y = 0.35;
    this.cameraGoal = {
      pos: new THREE.Vector3(2.2, 1.15, 7.6),
      target: new THREE.Vector3(0, 0.32, 0),
      alpha: 0,
    };

    const steps = [
      "Turning the aluminium foot",
      "Seating the speaker driver",
      "Populating the logic board",
      "Fitting the heat sink",
      "Wrapping the acoustic band",
      "Lighting the emerald reactor",
      "Closing the soft-touch shell",
      "Waking the reactor",
    ];

    // Hide parts initially
    this.parts.forEach((p) => {
      p.group.visible = false;
    });

    let currentStep = 0;
    const advance = () => {
      if (!this.active || sequence !== this.sequence) return;
      this.parts.forEach((p) => {
        if (p.stepIndex <= currentStep) p.group.visible = true;
      });
      if (onStepProgress) onStepProgress(steps, currentStep);
      currentStep++;
      if (currentStep < steps.length) {
        setTimeout(advance, 420);
      } else if (onComplete) {
        setTimeout(onComplete, 320);
      }
    };
    advance();
  }

  applyMaterialEdit(params = {}, onStepProgress, onComplete) {
    const sequence = this.sequence = (this.sequence || 0) + 1;
    const steps = [];

    if (params.housingColor) {
      const c = params.housingColor.toLowerCase();
      if (/^#[0-9a-f]{6}$/.test(c)) {
        this.housingMat.color.set(c);
        this.housingPartEntry.label = `Anodised reactor housing ${c}`;
        steps.push(`Setting housing color to ${c}`);
      } else if (c.includes("red")) {
        this.housingMat.color.set("#b91c1c");
        this.housingMat.metalness = 0.84;
        this.housingMat.roughness = 0.24;
        this.housingPartEntry.label = "Red anodised reactor housing";
        steps.push("Anodising the housing red");
      } else if (c.includes("gold")) {
        this.housingMat.color.set("#f59e0b");
        this.housingPartEntry.label = "Gold anodised reactor housing";
        steps.push("Anodising the housing gold");
      } else if (c.includes("blue")) {
        this.housingMat.color.set("#2563eb");
        this.housingPartEntry.label = "Cobalt anodised reactor housing";
        steps.push("Anodising the housing cobalt blue");
      } else {
        this.housingMat.color.set("#d8dee9");
        this.housingPartEntry.label = "Anodised reactor housing";
        steps.push("Machining brushed silver housing");
      }
      this.housingPartEntry.group.name = this.housingPartEntry.label;
      this.housingMat.name = this.housingPartEntry.label;
    }

    if (params.ringColor) {
      const col = new THREE.Color(params.ringColor);
      this.reactorRingMat.color.copy(col);
      this.reactorRingMat.emissive.copy(col);
      this.waistLedMat.color.copy(col);
      this.waistLedMat.emissive.copy(col);
      this.reactorLight.color.copy(col);
      steps.push(params.ringColor === "#10b981" ? "Restoring the emerald ring" : "Updating reactor light ring");
    }

    if (params.shellColor) {
      this.shellMat.color.set(params.shellColor);
      steps.push("Refinishing soft-touch body shell");
    }

    if (steps.length === 0) {
      if (onStepProgress) onStepProgress([], 0);
      if (onComplete) onComplete();
      return;
    }

    let idx = 0;
    const stepTimer = () => {
      if (sequence !== this.sequence || !this.active) return;
      if (onStepProgress) onStepProgress(steps, idx);
      idx++;
      if (idx < steps.length) setTimeout(stepTimer, 340);
      else if (onComplete) setTimeout(onComplete, 250);
    };
    stepTimer();
  }

  setExploded(exploded) {
    this.sequence = (this.sequence || 0) + 1;
    this.explodeTarget = exploded ? 1 : 0;
    this.parts.forEach((p) => (p.group.visible = true));

    if (exploded) {
      // Rotate robot so eye assembly explodes forward-left cleanly like 5:22 in the video
      this.targetRotY = -0.68;
      this.cameraGoal = {
        pos: new THREE.Vector3(0.25, -0.08, 13.8),
        target: new THREE.Vector3(-0.15, -0.1, 0),
        alpha: 0,
      };
    } else {
      this.targetRotY = 0.35;
      this.cameraGoal = {
        pos: new THREE.Vector3(2.2, 1.15, 7.6),
        target: new THREE.Vector3(0, 0.32, 0),
        alpha: 0,
      };
    }
  }

  setExplodeAmount(val01) {
    this.sequence = (this.sequence || 0) + 1;
    this.explodeTarget = THREE.MathUtils.clamp(val01, 0, 1);
    this.targetRotY = this.explodeTarget > 0.25 ? -0.68 : 0.35;
  }

  projectSnapshot() {
    return {
      version: 1,
      view: "robot",
      camera: { position: this.camera.position.toArray(), target: this.controls.target.toArray() },
      state: {
        housingColor: `#${this.housingMat.color.getHexString()}`,
        ringColor: `#${this.reactorRingMat.color.getHexString()}`,
        shellColor: `#${this.shellMat.color.getHexString()}`,
        metalness: this.housingMat.metalness,
        roughness: this.housingMat.roughness,
        explode: this.explodeTarget,
      },
    };
  }

  restoreProject(project) {
    this.sequence = (this.sequence || 0) + 1;
    this.cameraGoal = null;
    this.housingMat.color.set(project.state.housingColor);
    this.housingMat.metalness = project.state.metalness;
    this.housingMat.roughness = project.state.roughness;
    this.shellMat.color.set(project.state.shellColor);
    this.reactorRingMat.color.set(project.state.ringColor);
    this.reactorRingMat.emissive.set(project.state.ringColor);
    this.waistLedMat.color.set(project.state.ringColor);
    this.waistLedMat.emissive.set(project.state.ringColor);
    this.reactorLight.color.set(project.state.ringColor);
    this.housingPartEntry.label = `Anodised reactor housing ${project.state.housingColor}`;
    this.housingPartEntry.group.name = this.housingPartEntry.label;
    this.housingMat.name = this.housingPartEntry.label;
    this.explodeTarget = this.explodeCurrent = project.state.explode;
    this.targetRotY = this.explodeTarget > 0.25 ? -0.68 : 0.35;
    this.robotRoot.rotation.y = this.targetRotY;
    this.parts.forEach((part) => {
      part.group.visible = true;
      part.group.position.lerpVectors(part.basePos, part.explodePos, this.explodeCurrent);
    });
    this.floorMesh.visible = this.explodeCurrent < 0.35;
    this.camera.position.fromArray(project.camera.position);
    this.controls.target.fromArray(project.camera.target);
    this.controls.update();
  }

  capturePNG() {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }

  _updateCallouts() {
    const layer = document.getElementById("exploded-callout-layer");
    if (!this.active || this.explodeCurrent < 0.55) {
      layer.classList.add("hidden");
      return;
    }
    layer.classList.remove("hidden");

    const w = window.innerWidth;
    const h = window.innerHeight;
    const leftItems = [];
    const rightItems = [];

    for (const part of this.parts) {
      if (!part.showCallout || !part.group.visible) continue;
      const worldPos = new THREE.Vector3();
      part.group.getWorldPosition(worldPos);
      worldPos.add(part.anchorOffset.clone().applyQuaternion(this.robotRoot.quaternion));

      const ndc = worldPos.clone().project(this.camera);
      if (ndc.z > 1) continue;

      const sx = (ndc.x * 0.5 + 0.5) * w;
      const sy = (-ndc.y * 0.5 + 0.5) * h;

      const item = { part, sx, sy, labelY: sy };
      if (part.side === "right") rightItems.push(item);
      else leftItems.push(item);
    }

    // Sort vertically & keep pills strictly between top bar (88px) and bottom bar (h - 90px)
    const relax = (arr) => {
      if (!arr.length) return;
      arr.sort((a, b) => a.sy - b.sy);
      const minY = 92;
      const maxY = h - 92;
      const minGap = Math.min(29, (maxY - minY) / Math.max(1, arr.length));
      arr[0].labelY = Math.max(minY, arr[0].sy);
      for (let i = 1; i < arr.length; i++) {
        arr[i].labelY = Math.max(arr[i].sy, arr[i - 1].labelY + minGap);
      }
      if (arr[arr.length - 1].labelY > maxY) {
        arr[arr.length - 1].labelY = maxY;
        for (let i = arr.length - 2; i >= 0; i--) {
          arr[i].labelY = Math.min(arr[i].labelY, arr[i + 1].labelY - minGap);
        }
      }
    };
    relax(leftItems);
    relax(rightItems);

    const leftX = Math.max(210, w * 0.23);
    const rightX = Math.min(w - 260, w * 0.67);

    let svgHtml = "";
    let pillsHtml = "";

    for (const item of leftItems) {
      const elbowX = leftX + 26;
      svgHtml += `
        <circle cx="${item.sx.toFixed(1)}" cy="${item.sy.toFixed(1)}" r="3.2" fill="#ffffff" />
        <polyline points="${leftX},${item.labelY.toFixed(1)} ${elbowX},${item.labelY.toFixed(1)} ${item.sx.toFixed(1)},${item.sy.toFixed(1)}"
          fill="none" stroke="rgba(255,255,255,0.75)" stroke-width="1.3" />
      `;
      pillsHtml += `<div class="exploded-pill" style="left:${leftX - 6}px; top:${item.labelY.toFixed(1)}px; transform:translate(-100%, -50%);">${item.part.label}</div>`;
    }

    for (const item of rightItems) {
      const elbowX = rightX - 26;
      svgHtml += `
        <circle cx="${item.sx.toFixed(1)}" cy="${item.sy.toFixed(1)}" r="3.2" fill="#ffffff" />
        <polyline points="${item.sx.toFixed(1)},${item.sy.toFixed(1)} ${elbowX},${item.labelY.toFixed(1)} ${rightX},${item.labelY.toFixed(1)}"
          fill="none" stroke="rgba(255,255,255,0.75)" stroke-width="1.3" />
      `;
      pillsHtml += `<div class="exploded-pill" style="left:${rightX + 6}px; top:${item.labelY.toFixed(1)}px;">${item.part.label}</div>`;
    }

    this.calloutSvg.innerHTML = svgHtml;
    this.calloutLabelsEl.innerHTML = pillsHtml;
  }

  tick(dt, voiceLevel = 0) {
    if (!this.active) return;
    this.phase += dt;

    // Smoothly interpolate explode factor
    this.explodeCurrent = THREE.MathUtils.lerp(this.explodeCurrent, this.explodeTarget, Math.min(1, dt * 4.5));
    for (const p of this.parts) {
      p.group.position.lerpVectors(p.basePos, p.explodePos, this.explodeCurrent);
    }
    this.floorMesh.visible = this.explodeCurrent < 0.35;

    if (this.targetRotY !== undefined) {
      this.robotRoot.rotation.y = THREE.MathUtils.lerp(this.robotRoot.rotation.y, this.targetRotY, Math.min(1, dt * 3.5));
    }

    if (this.cameraGoal) {
      this.cameraGoal.alpha = Math.min(1, this.cameraGoal.alpha + dt * 2.2);
      this.camera.position.lerp(this.cameraGoal.pos, dt * 3.8);
      this.controls.target.lerp(this.cameraGoal.target, dt * 3.8);
      if (this.cameraGoal.alpha >= 0.99) this.cameraGoal = null;
    }

    // Pulse reactor glow & micro-ticks with JARVIS voice
    const pulse = 1.9 + Math.sin(this.phase * 4.2) * 0.35 + voiceLevel * 2.2;
    this.reactorRingMat.emissiveIntensity = pulse;
    this.reactorLight.intensity = 2.0 + voiceLevel * 2.8;
    if (this.eyeTickGroup) {
      this.eyeTickGroup.rotation.z = this.phase * 0.25;
      const s = 1 + voiceLevel * 0.08;
      this.eyeTickGroup.scale.set(s, s, 1);
    }

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this._updateCallouts();
  }
}
