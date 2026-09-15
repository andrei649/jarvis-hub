export const FIRST_RUN_DISMISS_KEY = 'hud.firstrun.dismissed';

export function shouldShowFirstRun(cc: any): boolean {
  if (!cc || !cc.model || !cc.wizard) return false;
  return cc.model.ready !== true || cc.wizard.complete !== true;
}

