import { describe, expect, it } from 'vitest';
import routes from '../../../desktop/src-tauri/hud-routes.json';
import { HUD_MODES } from '../hud-routing';
import { CONSOLE_PANELS } from '../console-routes';

describe('native HUD route allowlist', () => {
  it('matches every registered mode and console panel without widening floating chat', () => {
    const paths = [...HUD_MODES.map(mode => '/v2/' + mode), '/v2/console', ...CONSOLE_PANELS.map(panel => '/v2/console/' + panel.id)];
    expect(routes.main).toEqual(['/v2', '/v2/', ...paths.flatMap(path => [path, path + '/'])]);
    expect(routes.floating).toEqual(['/v2', '/v2/', '/v2/chat', '/v2/chat/']);
    expect(new Set(routes.main).size).toBe(routes.main.length);
  });
});
