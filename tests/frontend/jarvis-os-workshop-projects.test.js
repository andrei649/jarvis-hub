import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { JSDOM } from 'jsdom';
import * as THREE from '../../apps/jarvis-os/public/vendor/three/three.module.js';

const root = path.resolve(import.meta.dirname, '../../apps/jarvis-os/public');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const reply = data => ({ ok: true, json: async () => data });
const robot = {
  version: 1, view: 'robot', camera: { position: [2, 3, 8], target: [0, 1, 0] },
  state: { housingColor: '#aabbcc', ringColor: '#10b981', shellColor: '#112233',
    metalness: .84, roughness: .24, explode: .7 },
};
const house = {
  version: 1, view: 'house', camera: { position: [0, 29, 20], target: [1, 0, 0] },
  state: { mode: 'miniature', centeredDoorNoStairs: true, garageCars: true,
    livingRoomExtraMeters: 2, kitchenExtraMeters: 1, poolBackPalmsAndFlowers: true,
    poolLoungeChairs: false, showRoof: true, roofVisibilityOverride: false,
    showRoomLabels: true, explodedLayers: true },
};
let dom, app, controller, get, post, restored;

beforeEach(() => {
  dom = new JSDOM(read('index.html'), { runScripts: 'outside-only', url: 'http://localhost:4719/os/?studio=robot' });
  dom.window.HUB = true;
  dom.window.THREE = THREE;
  const projectsSource = read('js/workshop-projects.js')
    .replace(/^import .*;\r?\n/gm, '')
    .replace(/export (function|class)/g, '$1');
  dom.window.eval(`${projectsSource}\nwindow.ProjectController = WorkshopProjects; window.validProject = validWorkshopProject;`);
  const mainSource = read('js/main.js')
    .replace(/^import .*;\r?\n/gm, '')
    .replace(/window.addEventListener\("DOMContentLoaded",[\s\S]*$/, 'window.App = JarvisOSApp;');
  dom.window.eval(mainSource);
  app = Object.create(dom.window.App.prototype);
  app.activeView = 'robot';
  app.workshopViewRevision = 0;
  app.robotWorkshop = { projectSnapshot: () => structuredClone(robot), restoreProject: vi.fn(), explodeTarget: .7 };
  app.houseWorkshop = { projectSnapshot: () => structuredClone(house), restoreProject: vi.fn(), viewMode: '3d' };
  app.openRobotWorkshop = vi.fn(() => { app.activeView = 'robot'; app.workshopViewRevision++; });
  app.openHouseWorkshop = vi.fn(() => { app.activeView = 'house'; app.workshopViewRevision++; });
  app.hud = { setStatus: vi.fn(), showSubtitle: vi.fn() };
  get = vi.fn(async () => reply({ ok: true, projects: [] }));
  post = vi.fn(async () => reply({ ok: true, title: 'First', path: '08 Inbox/First.json', view: 'robot' }));
  controller = new dom.window.ProjectController(app, (...args) => get(...args), (...args) => post(...args));
  app.projects = controller;
  restored = app.robotWorkshop.restoreProject;
});

afterEach(() => dom.window.close());

it('saves only on explicit submit, lists escaped names and offers a project link', async () => {
  get.mockResolvedValue(reply({ ok: true, projects: [{ path: '08 Inbox/a & b.json', title: '<img src=x>', view: 'robot' }] }));
  app._renderRobotTopBar();
  expect(post).not.toHaveBeenCalled();
  dom.window.document.getElementById('rb-projects-btn').click();
  await vi.waitFor(() => expect(controller.list.textContent).toContain('<img src=x>'));
  expect(controller.list.querySelector('img')).toBeNull();
  expect(controller.list.querySelector('a').href).toContain('project=08+Inbox%2Fa+%26+b.json');
  controller.title.value = 'First';
  controller.form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
  expect(post.mock.calls[0]).toEqual(['/workshop/projects', { title: 'First', project: robot }]);
  await vi.waitFor(() => expect(controller.status.textContent).toContain('Saved'));
});

it('blocks duplicate saves, reports a missing vault, and keeps the scene on a failed save', async () => {
  get.mockResolvedValue({ ok: false });
  await controller.open();
  expect(controller.status.textContent).toMatch(/unavailable/);
  let finish;
  post.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  controller.title.value = 'Unsent';
  const first = controller.save();
  expect(await controller.save()).toBe(false);
  expect(post).toHaveBeenCalledTimes(1);
  finish({ ok: false });
  expect(await first).toBe(false);
  expect(controller.status.textContent).toMatch(/Could not save/);
  expect(restored).not.toHaveBeenCalled();
});

it('does not send a second save after closing and reopening during a pending write', async () => {
  await controller.open();
  let finish;
  post.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  controller.title.value = 'Pending';
  const first = controller.save();
  controller.close();
  await controller.open();
  expect(await controller.save()).toBe(false);
  expect(post).toHaveBeenCalledTimes(1);
  finish(reply({ ok: true, title: 'Pending', path: '08 Inbox/Pending.md', view: 'robot' }));
  await first;
  expect(controller.saveButton.disabled).toBe(false);
});

it('reports a note that was written but cannot be reopened and checks the list before another save', async () => {
  await controller.open();
  post.mockResolvedValue({ ok: false, json: async () => ({
    error: 'project saved but could not be reopened', path: '08 Inbox/Unindexed.md',
  }) });
  controller.title.value = 'Unindexed';
  expect(await controller.save()).toBe(false);
  expect(controller.status.textContent).toContain('08 Inbox/Unindexed.md');
  expect(controller.saveButton.disabled).toBe(true);
  controller.title.value = 'Another version';
  controller.title.dispatchEvent(new dom.window.Event('input'));
  expect(controller.saveButton.disabled).toBe(false);
  controller.title.value = 'Unindexed';
  controller.title.dispatchEvent(new dom.window.Event('input'));
  expect(controller.saveButton.disabled).toBe(true);
  get.mockResolvedValue(reply({ ok: true, projects: [
    { path: '08 Inbox/Unindexed.md', title: 'Unindexed', view: 'robot' },
  ] }));
  dom.window.document.getElementById('workshop-project-refresh').click();
  await vi.waitFor(() => expect(controller.saveButton.disabled).toBe(false));
  expect(controller.list.textContent).toContain('Unindexed');
});

it('loads the saved subtype and rejects malformed, failed or stale loads without changing the scene', async () => {
  await controller.open();
  get.mockResolvedValueOnce(reply({ ok: true, path: 'v/house.json', title: 'Home', project: house }));
  expect(await controller.load('v/house.json')).toBe(true);
  expect(app.openHouseWorkshop).toHaveBeenCalledWith(false);
  expect(app.houseWorkshop.restoreProject).toHaveBeenCalledWith(house);
  expect(dom.window.document.activeElement.id).toBe('hs-projects-btn');
  const previous = app.houseWorkshop.restoreProject.mock.calls.length;
  get.mockResolvedValueOnce(reply({ ok: true, path: 'v/bad.json', project: { ...house, state: { ...house.state, mode: 'bad' } } }));
  expect(await controller.load('v/bad.json')).toBe(false);
  get.mockResolvedValueOnce({ ok: false });
  expect(await controller.load('v/failed.json')).toBe(false);
  expect(app.houseWorkshop.restoreProject).toHaveBeenCalledTimes(previous);
  let finish;
  get.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const pending = controller.load('v/late.json');
  app.workshopViewRevision++;
  finish(reply({ ok: true, path: 'v/late.json', project: robot }));
  expect(await pending).toBe(false);
  expect(restored).not.toHaveBeenCalled();
});

it('validates exact bounded snapshots and handles an unavailable deep link without writing', async () => {
  expect(dom.window.validProject(robot)).toBe(true);
  expect(dom.window.validProject(house)).toBe(true);
  expect(dom.window.validProject({ ...robot, camera: { position: [Infinity, 0, 0], target: [0, 0, 0] } })).toBe(false);
  expect(dom.window.validProject({ ...robot, camera: { position: [2, 3, 8], target: [2, 3, 8] } })).toBe(false);
  expect(dom.window.validProject({ ...robot, camera: { position: [501, 3, 8], target: [0, 0, 0] } })).toBe(false);
  expect(dom.window.validProject({ ...robot, state: { ...robot.state, extra: 1 } })).toBe(false);
  await controller.open();
  get.mockResolvedValue({ ok: false });
  expect(await controller.load('missing.json')).toBe(false);
  expect(post).not.toHaveBeenCalled();
  expect(controller.status.textContent).toMatch(/current scene is still here/);
});

it('boots a project link through its relative path and lets the loaded record choose the subtype', async () => {
  const source = read('js/main.js');
  const boot = source.slice(source.lastIndexOf('window.addEventListener("DOMContentLoaded"'))
    .replace('window.addEventListener("DOMContentLoaded", () => {', '(() => {')
    .replace('new JarvisOSApp()', 'window.fakeApp')
    .replace(/\}\);\s*$/, '})();');
  const load = vi.fn(async () => true);
  dom.window.fakeApp = {
    openRobotWorkshop: vi.fn(), openHouseWorkshop: vi.fn(),
    projects: { open: vi.fn(async () => true), load },
  };
  dom.window.history.replaceState({}, '', '/os/?project=08+Inbox%2FScene+%26+view.md');
  dom.window.eval(boot);
  expect(dom.window.fakeApp.openRobotWorkshop).toHaveBeenCalledWith(false);
  expect(dom.window.fakeApp.projects.open).toHaveBeenCalledWith({ refresh: false });
  expect(load).toHaveBeenCalledWith('08 Inbox/Scene & view.md');
  expect(dom.window.fakeApp.openHouseWorkshop).not.toHaveBeenCalled();
});

it('starts exact-link loading without listing and leaves a later scene untouched', async () => {
  let finish;
  get.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  await controller.open({ refresh: false });
  expect(get).not.toHaveBeenCalled();
  const pending = controller.load('08 Inbox/old.md');
  expect(get).toHaveBeenCalledWith('/workshop/project?path=08%20Inbox%2Fold.md');
  expect(controller.status.textContent).toContain('Opening version');
  controller.close(false);
  app.workshopViewRevision++;
  finish(reply({ ok: true, path: '08 Inbox/old.md', title: 'Old', project: house }));
  expect(await pending).toBe(false);
  expect(app.houseWorkshop.restoreProject).not.toHaveBeenCalled();
  expect(app.openHouseWorkshop).not.toHaveBeenCalled();
});

it('restores robot materials, explode positions and camera exactly after later changes', () => {
  const source = read('js/workshop-robot.js').replace(/^import .*;\r?\n/gm, '')
    .replace('export class RobotWorkshop', 'class RobotWorkshop');
  dom.window.eval(`${source}\nwindow.RobotWorkshop = RobotWorkshop;`);
  const model = Object.create(dom.window.RobotWorkshop.prototype);
  const part = { group: new THREE.Group(), basePos: new THREE.Vector3(0, 0, 0),
    explodePos: new THREE.Vector3(0, 2, 0) };
  model.parts = [part];
  model.robotRoot = new THREE.Group();
  model.floorMesh = { visible: true };
  model.camera = { position: new THREE.Vector3(2, 3, 8) };
  model.controls = { target: new THREE.Vector3(0, 1, 0), update: vi.fn() };
  model.housingMat = { color: new THREE.Color('#aabbcc'), metalness: .84, roughness: .24 };
  model.reactorRingMat = { color: new THREE.Color('#10b981'), emissive: new THREE.Color('#10b981') };
  model.waistLedMat = { color: new THREE.Color('#10b981'), emissive: new THREE.Color('#10b981') };
  model.reactorLight = { color: new THREE.Color('#10b981') };
  model.shellMat = { color: new THREE.Color('#112233') };
  model.housingPartEntry = { label: '', group: {} };
  model.explodeTarget = .7;
  expect(model.projectSnapshot()).toEqual(robot);
  model.housingMat.color.set('#ff0000');
  model.housingMat.metalness = 0;
  model.housingMat.roughness = 1;
  model.camera.position.set(20, 20, 20);
  model.cameraGoal = { alpha: 0 };
  model.restoreProject(robot);
  expect(model.projectSnapshot()).toEqual(robot);
  expect(part.group.position.y).toBeCloseTo(1.4);
  expect(model.cameraGoal).toBeNull();
});

it('restores absolute house state and cancels an old robot build timer', () => {
  const houseSource = read('js/workshop-house.js').replace(/^import .*;\r?\n/gm, '')
    .replace('export class HouseWorkshop', 'class HouseWorkshop');
  dom.window.eval(`${houseSource}\nwindow.HouseWorkshop = HouseWorkshop;`);
  const model = Object.create(dom.window.HouseWorkshop.prototype);
  model.state = { ...house.state, mode: undefined };
  delete model.state.mode;
  model.viewMode = 'miniature';
  model.camera = { position: new THREE.Vector3(...house.camera.position) };
  model.controls = { target: new THREE.Vector3(...house.camera.target), update: vi.fn() };
  model._rebuildArchitecture = vi.fn();
  expect(model.projectSnapshot()).toEqual(house);
  model.state.livingRoomExtraMeters = 5;
  model.viewMode = '3d';
  model.restoreProject(house);
  expect(model.projectSnapshot()).toEqual(house);
  expect(model._rebuildArchitecture).toHaveBeenCalledTimes(1);

  vi.useFakeTimers();
  try {
    const robotSource = read('js/workshop-robot.js').replace(/^import .*;\r?\n/gm, '')
      .replace('export class RobotWorkshop', 'class RobotWorkshop');
    dom.window.eval(`${robotSource}\nwindow.RobotWorkshop = RobotWorkshop;`);
    const build = Object.create(dom.window.RobotWorkshop.prototype);
    const part = { group: new THREE.Group(), basePos: new THREE.Vector3(),
      explodePos: new THREE.Vector3(0, 2, 0), stepIndex: 7 };
    build.parts = [part]; build.active = true; build.robotRoot = new THREE.Group();
    build.floorMesh = { visible: true };
    build.camera = { position: new THREE.Vector3() };
    build.controls = { target: new THREE.Vector3(), update: vi.fn() };
    build.housingMat = { color: new THREE.Color(), metalness: .84, roughness: .24 };
    build.reactorRingMat = { color: new THREE.Color(), emissive: new THREE.Color() };
    build.waistLedMat = { color: new THREE.Color(), emissive: new THREE.Color() };
    build.reactorLight = { color: new THREE.Color() };
    build.shellMat = { color: new THREE.Color() };
    build.housingPartEntry = { label: '', group: {} };
    const completed = vi.fn();
    build.playProgressiveBuild(null, completed);
    build.restoreProject(robot);
    vi.runAllTimers();
    expect(part.group.visible).toBe(true);
    expect(completed).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); }
});
