import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

test('opening a saved version restores the editable miniature and camera', async ({ page }) => {
  test.skip(!await page.evaluate(() => !!document.createElement('canvas').getContext('webgl2')), 'Requires WebGL 2');
  const path = 'Inbox/Model (2).md';
  const ref = { path, title:'Model (2)', view:'house' };
  const project = { version:1, view:'house', camera:{position:[-11,18,21], target:[0.2,0.3,0.6]},
    state:{mode:'miniature', centeredDoorNoStairs:true, garageCars:false, livingRoomExtraMeters:2,
      kitchenExtraMeters:1.25, poolBackPalmsAndFlowers:true, poolLoungeChairs:false, showRoof:true,
      roofVisibilityOverride:false, showRoomLabels:true, explodedLayers:false} };
  await page.route('**/api/os/workshop/project?*', route =>
    route.fulfill({json:{ok:true,...ref,summary:'Miniature house.',project}}));
  // This browser regression can also run against an owner's hub. Keep every save in the fixture.
  await page.route('**/api/os/workshop/projects', route => route.fulfill({json:
    route.request().method() === 'POST' ? {ok:true,...ref} : {ok:true,projects:[ref]}}));
  await page.goto('/os/?project=' + encodeURIComponent(path));
  await expect(page.locator('#hs-projects-btn')).toBeVisible();
  const dialog = page.getByRole('dialog', {name:'Projects'});
  if (!await dialog.isVisible()) await page.locator('#hs-projects-btn').click();
  await dialog.getByLabel('Version name').fill('Restored copy');
  const posted = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/api/os/workshop/projects'));
  await dialog.getByRole('button',{name:'Save version'}).click();
  const copy = (await posted).postDataJSON();
  expect(copy.title).toBe('Restored copy');
  expect(copy.project.state).toEqual(project.state);
  expect(copy.project.view).toBe('house');
  for (const key of ['position','target'] as const) {
    for (const [i, axis] of project.camera[key].entries()) expect(copy.project.camera[key][i]).toBeCloseTo(axis, 7);
  }
});

test('the workshop downloads editable geometry with embedded textures', async ({ page }) => {
  const hasWebGL = await page.evaluate(() => !!document.createElement('canvas').getContext('webgl2'));
  test.skip(!hasWebGL, 'The workshop requires WebGL 2');
  await page.route('**/chat', route => route.abort());

  for (const studio of ['robot', 'house']) {
    await page.goto('/os/?studio=' + studio);
    if (studio === 'house') await page.getByRole('button', { name: 'Miniature', exact: true }).click();
    const button = page.getByRole('button', { name: 'Blender / Godot (.glb)', exact: true });
    await expect(button).toBeVisible();
    const pending = page.waitForEvent('download');
    if (studio === 'house') {
      const input = page.locator('#jarvis-prompt-input');
      await input.fill('Export my miniature for Godot');
      await input.press('Enter');
    } else {
      await button.click();
    }
    const download = await pending;
    expect(download.suggestedFilename()).toBe(studio === 'robot' ? 'jarvis-reactor-companion.glb' : 'pool-home-miniature.glb');
    await expect(page.locator('#workshop-export-status')).toContainText('Godot’s FileSystem dock');
    const file = await readFile((await download.path())!);
    expect(file.toString('ascii', 0, 4)).toBe('glTF');
    expect(file.readUInt32LE(4)).toBe(2);
    expect(file.readUInt32LE(8)).toBe(file.length);
    const model = JSON.parse(file.toString('utf8', 20, 20 + file.readUInt32LE(12)));
    const roots = model.scenes[model.scene].nodes.map((index: number) => model.nodes[index].name);
    expect(roots).toEqual(studio === 'robot' ? ['Jarvis Reactor Companion'] : ['Pool Home Plan', 'Desert diorama']);
    expect(model.meshes.length).toBeGreaterThan(1);
    expect(model.materials.length).toBeGreaterThan(1);
    expect(model.images.length).toBeGreaterThan(0);
    for (const texture of model.images) {
      expect(texture.bufferView).toEqual(expect.any(Number));
      expect(texture.uri).toBeUndefined();
    }
  }
});

test('the house downloads grouped vector footprints as SVG', async ({ page }) => {
  test.skip(!await page.evaluate(() => !!document.createElement('canvas').getContext('webgl2')), 'Requires WebGL 2');
  await page.goto('/os/?studio=house');
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Export floor plan as SVG for Illustrator (.svg)' }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('pool-home-floor-plan.svg');
  const svg = await readFile((await download.path())!, 'utf8');
  const structure = await page.evaluate(text => {
    const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
    return {
      root: doc.documentElement.localName,
      width: doc.documentElement.getAttribute('width'),
      errors: doc.querySelectorAll('parsererror').length,
      floors: doc.querySelectorAll('#floors rect').length,
      walls: doc.querySelectorAll('#walls rect').length,
      pools: doc.querySelectorAll('#pools rect').length,
      labels: doc.querySelector('#labels')?.textContent,
    };
  }, svg);
  expect(structure).toMatchObject({ root: 'svg', errors: 0, floors: 1, pools: 2 });
  expect(structure.width).toMatch(/mm$/);
  expect(structure.walls).toBeGreaterThan(10);
  expect(structure.labels).toContain('Great Room');
});

test('the house downloads its Illustrator drawing script', async ({ page }) => {
  test.skip(!await page.evaluate(() => !!document.createElement('canvas').getContext('webgl2')), 'Requires WebGL 2');
  await page.goto('/os/?studio=house');
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Illustrator script (.jsx)' }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('pool-home-floor-plan.jsx');
  const script = await readFile((await download.path())!, 'utf8');
  expect(script).toContain('app.documents.add');
  await expect(page.locator('#workshop-export-status')).toContainText('File › Scripts › Other Script');
});
