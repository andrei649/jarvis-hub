// The keyboard map, shared by the handler (useKeyboardShortcuts) and the help overlay so the
// help can never advertise a binding that doesn't ship (spec §4).

export const SHORTCUTS: [key: string, label: string][] = [
  ["Space", "Play / pause the master clock"],
  ["L", "Snap back to LIVE"],
  ["← →", "Scrub ±30 s (enters historical)"],
  ["Esc", "Clear selection / close overlay"],
  ["1–5", "Toggle data layers"],
  ["G", "Switch 2.5D map / 3D globe"],
  ["?", "This help"],
];
