import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { JSDOM } from 'jsdom';
import * as THREE from '../../apps/jarvis-os/public/vendor/three/three.module.js';

const appRoot = path.resolve(import.meta.dirname, '../../apps/jarvis-os/public');
let dom, app, exported, downloaded, revoked;

beforeEach(() => {
  dom = new JSDOM(fs.readFileSync(path.join(appRoot, 'index.html'), 'utf8'),
    { runScripts: 'outside-only', url: 'http://localhost:4719' });
  dom.window.HUB = true;
  const source = fs.readFileSync(path.join(appRoot, 'js/main.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '')
    .replaceAll('await import("./workshop-export.js")', 'await window.importWorkshopExport()')
    .replace(/window.addEventListener\("DOMContentLoaded",[\s\S]*$/, 'window.App = JarvisOSApp;');
  dom.window.eval(source);
  app = Object.create(dom.window.App.prototype);
  app.activeView = 'robot';
  app.robotWorkshop = { robotRoot: { name: 'Robot' }, explodeTarget: 0, capturePNG: () => 'data:image/png;base64,AA==' };
  app.houseWorkshop = { houseRoot: { name: 'House' }, miniatureEnvGroup: { name: 'Diorama' }, viewMode: '3d', capturePNG: () => 'data:image/png;base64,AA==' };
  app.hud = { showSubtitle: vi.fn() };
  exported = [];
  downloaded = [];
  revoked = [];
  dom.window.URL.createObjectURL = () => 'blob:workshop';
  dom.window.URL.revokeObjectURL = url => revoked.push(url);
  dom.window.HTMLAnchorElement.prototype.click = function () { downloaded.push([this.download, this.href]); };
  dom.window.importWorkshopExport = async () => ({ workshopGLB: async roots => {
    exported.push(roots);
    return new dom.window.Blob(['glb']);
  }, houseFloorPlanSVG: () => '<svg xmlns="http://www.w3.org/2000/svg"/>' });
});

afterEach(() => dom.window.close());

it('exports only the active model, including the visible miniature diorama', async () => {
  app._renderRobotTopBar();
  expect(await app.exportWorkshopModel()).toBe(true);
  expect(exported[0]).toEqual([app.robotWorkshop.robotRoot]);
  expect(downloaded[0][0]).toBe('jarvis-reactor-companion.glb');
  app.activeView = 'house';
  app.houseWorkshop.viewMode = 'miniature';
  app._renderHouseTopBar();
  expect(await app.exportWorkshopModel()).toBe(true);
  expect(exported[1]).toEqual([app.houseWorkshop.houseRoot, app.houseWorkshop.miniatureEnvGroup]);
  expect(downloaded[1][0]).toBe('pool-home-miniature.glb');
  expect(dom.window.document.getElementById('hs-save-btn')).not.toBeNull();
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(revoked).toEqual(['blob:workshop', 'blob:workshop']);
});

it('rejects duplicate requests and drops a completed export after leaving the view', async () => {
  let finish;
  dom.window.importWorkshopExport = async () => ({ workshopGLB: () => new Promise(resolve => { finish = resolve; }) });
  app._renderRobotTopBar();
  const first = app.exportWorkshopModel();
  expect(await app.exportWorkshopModel()).toBe(false);
  await Promise.resolve();
  expect(dom.window.document.getElementById('rb-export-btn').disabled).toBe(true);
  expect(dom.window.document.getElementById('workshop-export-status').textContent).toMatch(/Exporting/);
  app._cancelWorkshopExport();
  app.activeView = 'galaxy';
  finish(new dom.window.Blob(['glb']));
  expect(await first).toBe(false);
  expect(downloaded).toHaveLength(0);
  expect(dom.window.document.getElementById('rb-export-btn').disabled).toBe(false);
});

it('reports failures, allows retry, and never downloads outside a workshop', async () => {
  app.activeView = 'computer';
  expect(await app.exportWorkshopModel()).toBe(false);
  expect(downloaded).toHaveLength(0);
  app.activeView = 'house';
  app._renderHouseTopBar();
  dom.window.importWorkshopExport = async () => ({ workshopGLB: async () => { throw new Error('synthetic failure'); } });
  expect(await app.exportWorkshopModel()).toBe(false);
  expect(dom.window.document.getElementById('workshop-export-status').textContent).toMatch(/Could not export/);
  expect(dom.window.document.getElementById('hs-export-btn').disabled).toBe(false);
  dom.window.importWorkshopExport = async () => ({ workshopGLB: async roots => {
    exported.push(roots);
    return new dom.window.Blob(['glb']);
  } });
  expect(await app.exportWorkshopModel()).toBe(true);
  expect(downloaded).toHaveLength(1);
});

it('downloads the house floor plan only from the house workshop', async () => {
  expect(await app.exportHouseFloorPlan()).toBe(false);
  app.activeView = 'house';
  app._renderHouseTopBar();
  expect(dom.window.document.getElementById('hs-svg-btn').textContent).toMatch(/Illustrator/);
  expect(await app.exportHouseFloorPlan()).toBe(true);
  expect(downloaded[0][0]).toBe('pool-home-floor-plan.svg');
  expect(dom.window.document.getElementById('workshop-export-status').textContent).toMatch(/Downloaded/);
});

it('cancels a pending floor plan export when the house view is left', async () => {
  let release;
  app.activeView = 'house';
  app._renderHouseTopBar();
  dom.window.importWorkshopExport = () => new Promise(resolve => { release = resolve; });
  const pending = app.exportHouseFloorPlan();
  expect(await app.exportHouseFloorPlan()).toBe(false);
  expect(dom.window.document.getElementById('hs-svg-btn').disabled).toBe(true);
  expect(dom.window.document.getElementById('hs-export-btn').disabled).toBe(true);
  expect(dom.window.document.getElementById('workshop-export-status').textContent).toMatch(/Exporting floor plan/);
  app._cancelWorkshopExport();
  app.activeView = 'galaxy';
  release({ houseFloorPlanSVG: () => '<svg/>' });
  expect(await pending).toBe(false);
  expect(downloaded).toHaveLength(0);
});

it('keeps a prompt draft and seeds an empty Hub prompt for model edits', () => {
  app._renderRobotTopBar();
  const input = dom.window.document.getElementById('jarvis-prompt-input');
  dom.window.document.getElementById('rb-ai-edit-btn').click();
  expect(input.value).toBe('Edit model: ');
  expect(dom.window.document.activeElement).toBe(input);
  input.value = 'my draft';
  dom.window.document.getElementById('rb-ai-edit-btn').click();
  expect(input.value).toBe('Edit model: my draft');
  dom.window.document.getElementById('rb-ai-edit-btn').click();
  expect(input.value).toBe('Edit model: my draft');
});

it('loads an uploaded plan only as a reference beside the example model', () => {
  const title = dom.window.document.getElementById('workshop-title').textContent;
  const opened = vi.fn();
  app.openHouseWorkshop = opened;
  app.hud.speak = vi.fn();
  dom.window.FileReader = class {
    readAsDataURL() { this.result = 'data:image/png;base64,AA=='; this.onload(); }
  };
  app._loadCustomFloorplanFile({ name: 'my-house.png' });
  expect(opened).toHaveBeenCalledWith(false);
  expect(dom.window.document.getElementById('your-picture-img').src).toContain('data:image/png');
  expect(dom.window.document.getElementById('workshop-title').textContent).toBe(title);
  expect(app.hud.speak.mock.calls[0][0]).toMatch(/reference image.*example model/i);
});

it('applies every hex housing color exactly while retaining named preset colors', () => {
  const source = fs.readFileSync(path.join(appRoot, 'js/workshop-robot.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '')
    .replace('export class RobotWorkshop', 'class RobotWorkshop');
  dom.window.eval(`${source}\nwindow.RobotWorkshop = RobotWorkshop;`);
  const robot = Object.create(dom.window.RobotWorkshop.prototype);
  const colors = [];
  robot.housingMat = { color: { set: color => colors.push(color) } };
  robot.housingPartEntry = { label: '', group: {} };
  robot.applyMaterialEdit({ housingColor: '#c81e2b' });
  expect(colors.at(-1)).toBe('#c81e2b');
  expect(robot.housingPartEntry.group.name).toContain('#c81e2b');
  expect(robot.housingMat.name).toContain('#c81e2b');
  robot.applyMaterialEdit({ housingColor: 'red' });
  expect(colors.at(-1)).toBe('#b91c1c');
  robot.applyMaterialEdit({ housingColor: 'silver' });
  expect(colors.at(-1)).toBe('#d8dee9');
});

it('opens only known workshop deep links without a staged build', () => {
  const source = fs.readFileSync(path.join(appRoot, 'js/main.js'), 'utf8');
  const boot = source.slice(source.lastIndexOf('window.addEventListener("DOMContentLoaded"'))
    .replace('window.addEventListener("DOMContentLoaded", () => {', '(() => {')
    .replace('new JarvisOSApp()', 'window.fakeApp')
    .replace(/\}\);\s*$/, '})();');
  const opened = [];
  dom.window.fakeApp = {
    openRobotWorkshop: animate => opened.push(['robot', animate]),
    openHouseWorkshop: animate => opened.push(['house', animate]),
  };
  for (const studio of ['robot', 'house', 'other']) {
    dom.window.history.replaceState({}, '', `/?studio=${studio}`);
    dom.window.eval(boot);
  }
  expect(opened).toEqual([['robot', false], ['house', false]]);
});

it('measures requested house room extensions in actual scene meters', () => {
  dom.window.THREE = THREE;
  dom.window.HTMLCanvasElement.prototype.getContext = () => ({
    fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, arc() {},
  });
  const source = fs.readFileSync(path.join(appRoot, 'js/workshop-house.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '')
    .replace('export class HouseWorkshop', 'class HouseWorkshop');
  dom.window.eval(`${source}\nwindow.HouseWorkshop = HouseWorkshop;`);
  const house = Object.create(dom.window.HouseWorkshop.prototype);
  house.houseRoot = new THREE.Group();
  house.miniatureEnvGroup = new THREE.Group();
  house.hemiLight = new THREE.HemisphereLight();
  house.sunLight = new THREE.DirectionalLight();
  house.renderer = { toneMappingExposure: 1 };
  house.scene = { background: null };
  house.viewMode = '3d';
  house.state = { livingRoomExtraMeters: 0, kitchenExtraMeters: 0,
    showRoof: false, centeredDoorNoStairs: false, garageCars: false,
    poolBackPalmsAndFlowers: false, poolLoungeChairs: false, explodedLayers: false };
  const size = () => house.houseRoot.getObjectByName('Interior tiled floor').geometry.parameters;
  house._rebuildArchitecture();
  const initial = size();
  const exportSource = fs.readFileSync(path.join(appRoot, 'js/workshop-export.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '')
    .replace('export async function workshopGLB', 'async function workshopGLB')
    .replace('export function houseFloorPlanSVG', 'function houseFloorPlanSVG')
    .replace('export function houseFloorPlanIllustratorScript', 'function houseFloorPlanIllustratorScript');
  dom.window.eval(`${exportSource}\nwindow.houseFloorPlanSVG = houseFloorPlanSVG; window.houseFloorPlanIllustratorScript = houseFloorPlanIllustratorScript;`);
  const plan = () => new dom.window.DOMParser().parseFromString(dom.window.houseFloorPlanSVG(house), 'image/svg+xml');
  const originalPlan = plan();
  const originalFloor = originalPlan.querySelector('#floors rect');
  expect(originalPlan.querySelectorAll('#walls rect').length).toBeGreaterThan(10);
  expect(originalPlan.querySelectorAll('#pools rect')).toHaveLength(2);
  expect(originalPlan.documentElement.getAttribute('width')).toMatch(/mm$/);
  expect(originalPlan.querySelector('#labels').textContent).toContain('Great Room');
  expect(originalPlan.querySelector('#scale').hasAttribute('stroke')).toBe(false);
  expect(originalPlan.querySelector('#scale path').getAttribute('stroke')).toBe('#0f172a');
  const originalScript = dom.window.houseFloorPlanIllustratorScript(house);
  const scriptData = (source) => JSON.parse(source.match(/var data = (.*);/)[1]);
  const originalData = scriptData(originalScript);
  expect(originalData.groups.map((group) => group[0])).toEqual(['Floors', 'Garage', 'Deck', 'Pools', 'Walls']);
  expect(originalData.groups.reduce((count, group) => count + group[1].length, 0))
    .toBe(originalPlan.querySelectorAll('rect').length);
  expect(originalData.labels.map((label) => label[0])).toEqual([...originalPlan.querySelectorAll('#labels text')].map((node) => node.textContent));
  expect(originalData.scaleLabels.map((label) => label[0])).toEqual(['0', '5 m · 1:100']);
  expect(originalData.width * 25.4 / 72).toBeCloseTo(parseFloat(originalPlan.documentElement.getAttribute('width')));
  expect(originalData.height * 25.4 / 72).toBeCloseTo(parseFloat(originalPlan.documentElement.getAttribute('height')));
  expect(() => new dom.window.Function(originalScript)).not.toThrow();
  expect(originalScript).toContain('group.textFrames.pointText([item[1], item[2]])');
  expect(originalScript).toContain('addText(rooms, data.labels[k], true)');
  expect(originalScript).toContain('addText(scale, data.scaleLabels[s], false)');
  expect(originalScript).toContain('centered ? Justification.CENTER : Justification.LEFT');
  expect(originalData.scaleLabels.every((item) => item[2] > 0 && item[2] < originalData.height)).toBe(true);
  expect(originalScript).toContain('draft.close(SaveOptions.DONOTSAVECHANGES)');
  const roomLabels = house.roomLabels;
  house.roomLabels = () => [{ name: 'x)\nshowpage\n(é', x: 0, z: 0 }];
  const injected = dom.window.houseFloorPlanIllustratorScript(house);
  expect(scriptData(injected).labels[0][0]).toBe('x)\nshowpage\n(é');
  expect(() => new dom.window.Function(injected)).not.toThrow();
  house.roomLabels = () => [{ name: 'bad', x: Infinity, z: 0 }];
  expect(() => dom.window.houseFloorPlanIllustratorScript(house)).toThrow(/floor plan exceeds Illustrator canvas/);
  house.roomLabels = roomLabels;
  const oldFloor = house.houseRoot.getObjectByName('Interior tiled floor');
  const oldWater = house.waterTex;
  const envMesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial());
  house.miniatureEnvGroup.add(envMesh);
  oldFloor.geometry.dispose = vi.fn();
  oldFloor.material.dispose = vi.fn();
  oldFloor.material.map.dispose = vi.fn();
  oldWater.dispose = vi.fn();
  envMesh.geometry.dispose = vi.fn();
  envMesh.material.dispose = vi.fn();
  house.state.kitchenExtraMeters = 1.25;
  house.state.livingRoomExtraMeters = 2;
  house._rebuildArchitecture();
  const changedPlan = plan();
  const changedScript = dom.window.houseFloorPlanIllustratorScript(house);
  const changedFloor = changedPlan.querySelector('#floors rect');
  expect(Number(changedFloor.getAttribute('width')) - Number(originalFloor.getAttribute('width'))).toBeCloseTo(1.25);
  expect(Number(changedFloor.getAttribute('height')) - Number(originalFloor.getAttribute('height'))).toBeCloseTo(2);
  expect(scriptData(changedScript).width * 25.4 / 72)
    .toBeCloseTo(parseFloat(changedPlan.documentElement.getAttribute('width')));
  expect(changedPlan.querySelector('#labels').textContent).toContain('Kitchen & Dining');
  expect(oldFloor.geometry.dispose).toHaveBeenCalledOnce();
  expect(oldFloor.material.dispose).toHaveBeenCalledOnce();
  expect(oldFloor.material.map.dispose).toHaveBeenCalledOnce();
  expect(oldWater.dispose).toHaveBeenCalledOnce();
  expect(envMesh.geometry.dispose).not.toHaveBeenCalled();
  expect(envMesh.material.dispose).not.toHaveBeenCalled();
  expect(size().width - initial.width).toBeCloseTo(1.25);
  expect(size().depth - initial.depth).toBeCloseTo(2);
  expect(house.houseRoot.scale.x).toBe(1);
  house.viewMode = 'miniature';
  house._rebuildArchitecture();
  expect(size().width - initial.width).toBeCloseTo(1.25);
  expect(size().depth - initial.depth).toBeCloseTo(2);
});

it('honors absolute roof visibility during exploded edits and reports a no-op', () => {
  dom.window.THREE = THREE;
  dom.window.HTMLCanvasElement.prototype.getContext = () => ({
    fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, arc() {},
  });
  const source = fs.readFileSync(path.join(appRoot, 'js/workshop-house.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '')
    .replace('export class HouseWorkshop', 'class HouseWorkshop');
  dom.window.eval(`${source}\nwindow.HouseWorkshop = HouseWorkshop;`);
  const house = Object.create(dom.window.HouseWorkshop.prototype);
  house.houseRoot = new THREE.Group();
  house.miniatureEnvGroup = new THREE.Group();
  house.hemiLight = new THREE.HemisphereLight();
  house.sunLight = new THREE.DirectionalLight();
  house.renderer = { toneMappingExposure: 1 };
  house.scene = { background: null };
  house.viewMode = '3d';
  house.state = { livingRoomExtraMeters: 0, kitchenExtraMeters: 0,
    showRoof: false, roofVisibilityOverride: null, centeredDoorNoStairs: false,
    garageCars: false, poolBackPalmsAndFlowers: false,
    poolLoungeChairs: false, explodedLayers: false };
  house._rebuildArchitecture();
  house.applyEdit({ explodedHouse: true, showRoof: false });
  expect(house.stepGroups.roof.visible).toBe(false);
  house.applyEdit({ showRoof: true });
  expect(house.stepGroups.roof.visible).toBe(true);
  let noChange;
  house.applyEdit({ showRoof: true }, steps => { noChange = steps; });
  expect(noChange).toEqual([]);
  house.applyEdit({ explodedHouse: false, showRoof: false });
  expect(house.stepGroups.roof.visible).toBe(false);
});
