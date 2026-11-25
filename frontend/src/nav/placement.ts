/* Where a Console panel lives (PHASE_B_PLAN.md §3.3).

   A panel's area is its explicit entry in the §3.3 table (nav/areas.ts). A panel with no entry
   — any panel added to CONSOLE_PANELS later — lands in the default area for its CONSOLE_PANELS
   `group`, under "More pages", so a new panel is never unreachable. A group this table does not
   know (a new group) lands in Settings. */
import { CONSOLE_PANEL_MAP } from '../console-routes';
import type { AreaId } from './areas';

/** The default area of each CONSOLE_PANELS group. */
export const GROUP_DEFAULT_AREA: Readonly<Record<string, AreaId>> = {
  Start: 'home',
  Home: 'home',
  Memory: 'memory',
  Trust: 'trust',
  Interop: 'connect',
  Observe: 'observe',
  Build: 'build',
  'Autonomy & Agents': 'work',
  Admin: 'settings',
};

/** Where a panel from a group this table does not know lands. */
export const UNKNOWN_GROUP_AREA: AreaId = 'settings';

/** The default area for a CONSOLE_PANELS group. */
export function groupDefaultArea(group: string): AreaId {
  return Object.prototype.hasOwnProperty.call(GROUP_DEFAULT_AREA, group) ? GROUP_DEFAULT_AREA[group] : UNKNOWN_GROUP_AREA;
}

/** A panel's area: the explicit placement when there is one, else its group's default; null
 *  for an id CONSOLE_PANELS does not have. */
export function placePanel(panelId: string, explicit: ReadonlyMap<string, AreaId>): AreaId | null {
  const placed = explicit.get(panelId);
  if (placed) return placed;
  const panel = CONSOLE_PANEL_MAP.get(panelId);
  return panel ? groupDefaultArea(panel.group) : null;
}
