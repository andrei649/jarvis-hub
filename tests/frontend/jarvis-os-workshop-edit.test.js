import { beforeEach, expect, it, vi } from 'vitest';
import { AgentEngine } from '../../apps/jarvis-os/public/js/agent-engine.js';
import { apiPost, chat } from '../../apps/jarvis-os/public/js/api.js';

vi.mock('../../apps/jarvis-os/public/js/api.js', () => ({
  HUB: true, apiPost: vi.fn(), chat: vi.fn(),
}));

let app, engine;
const response = params => ({ ok: true, json: async () => ({ ok: true, params }) });

beforeEach(() => {
  vi.resetAllMocks();
  app = {
    activeView: 'robot', workshopViewRevision: 2,
    hud: { logReflex: vi.fn(), setStatus: vi.fn(), showSubtitle: vi.fn(), speak: vi.fn() },
    editRobot: vi.fn(), editHouse: vi.fn(), exportWorkshopModel: vi.fn(),
    houseWorkshop: { state: { showRoof: true, kitchenExtraMeters: 0, livingRoomExtraMeters: 0 } },
  };
  engine = new AgentEngine(app);
});

it('sends only the model instruction to the local editor and applies its result', async () => {
  apiPost.mockResolvedValue(response({ shellColor: '#679987' }));
  await engine.handleCommand('Edit model: Give the shell a eucalyptus finish');
  expect(apiPost).toHaveBeenCalledWith('/workshop/edit', { view: 'robot', instruction: 'Give the shell a eucalyptus finish' });
  expect(app.editRobot).toHaveBeenCalledWith({ shellColor: '#679987' });
  expect(app.hud.showSubtitle).toHaveBeenLastCalledWith(expect.stringContaining('Shell #679987'));
  expect(chat).not.toHaveBeenCalled();
});

it('discards an edit after the original view was left and reopened', async () => {
  let finish;
  apiPost.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const first = engine.handleCommand('Edit model: change the shell');
  await engine.handleCommand('Edit model: change the shell');
  expect(apiPost).toHaveBeenCalledTimes(1);
  app.workshopViewRevision += 1;
  finish(response({ shellColor: '#679987' }));
  await first;
  expect(app.editRobot).not.toHaveBeenCalled();
});

it('applies an absolute roof edit idempotently and does not apply a failed plan', async () => {
  app.activeView = 'house';
  apiPost.mockResolvedValueOnce(response({ showRoof: true })).mockResolvedValueOnce(response({ showRoof: false }))
    .mockResolvedValueOnce({ ok: false, status: 503 });
  await engine.handleCommand('Edit model: show the roof');
  expect(app.editHouse).not.toHaveBeenCalled();
  await engine.handleCommand('Edit model: hide the roof');
  expect(app.editHouse).toHaveBeenCalledWith({ showRoof: false });
  await engine.handleCommand('Edit model: enlarge the kitchen');
  expect(app.editHouse).toHaveBeenCalledTimes(1);
  expect(chat).not.toHaveBeenCalled();
});

it('preserves the model if a relative edit would exceed the kitchen range', async () => {
  app.activeView = 'house';
  app.houseWorkshop.state.kitchenExtraMeters = 3;
  apiPost.mockResolvedValue(response({ enlargeKitchen: 2, showRoof: false }));
  await engine.handleCommand('Edit model: add two metres and hide the roof');
  expect(app.editHouse).not.toHaveBeenCalled();
  expect(app.hud.showSubtitle).toHaveBeenLastCalledWith(expect.stringContaining('4 m'));
});

it.each(['Blender', 'Godot'])('exports an explicitly requested open model for %s without asking a provider', async target => {
  await engine.handleCommand('Export this model for ' + target);
  expect(app.exportWorkshopModel).toHaveBeenCalledTimes(1);
  app.activeView = 'galaxy';
  await engine.handleCommand('Export this model for ' + target);
  await engine.handleCommand('Edit model: change the finish');
  expect(app.exportWorkshopModel).toHaveBeenCalledTimes(1);
  expect(apiPost).not.toHaveBeenCalled();
  expect(chat).not.toHaveBeenCalled();
});

it('exports explicit floor plan commands in the requested format only from the house', async () => {
  app.activeView = 'house';
  await engine.handleCommand('Export my floor plan for Illustrator');
  await engine.handleCommand('Export as SVG');
  expect(app.exportWorkshopModel).toHaveBeenNthCalledWith(1, 'jsx');
  expect(app.exportWorkshopModel).toHaveBeenNthCalledWith(2, 'svg');
  app.activeView = 'robot';
  await engine.handleCommand('Export my floor plan for Illustrator');
  expect(app.exportWorkshopModel).toHaveBeenCalledTimes(2);
  expect(app.hud.showSubtitle).toHaveBeenLastCalledWith('Open the house workshop to export its floor plan.');
  expect(chat).not.toHaveBeenCalled();
});

it('leaves ordinary floor plan chat to the conversation provider', async () => {
  app.activeView = 'house';
  app.dataset = { mode: 'private' };
  chat.mockResolvedValue({ reply: 'We can discuss the drawing.' });
  await engine.handleCommand('Can we discuss exporting my floor plan for Illustrator?');
  expect(app.exportWorkshopModel).not.toHaveBeenCalled();
  expect(chat).toHaveBeenCalledTimes(1);
});
