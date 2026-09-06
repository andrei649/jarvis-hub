# Desktop app — HUD, command palette, command center, shell chrome, sidebars, overlays

This shard documents the Hermes Desktop (Electron) **application chrome**: HUD mode, the ⌘K command
palette (every row, page and ranking rule), the Command Center overlay (Sessions/System/Usage/
Maintenance), the shell's titlebar + statusbar (every tool id, statusbar item, and their context
menus), the approval-mode menu, the model catalog / model-edit menus and model overlays, the
context-usage panel, the right sidebar (file tree, review pane, terminal rail), the global app
context menu, Quick Entry, the wake indicator, and the shared overlay/master-detail primitives —
plus routes, layout presets (`apply_layout`) and the desktop keybind table.
Deliberately left to sibling shards: the chat surface itself (composer, transcript, message
renderers), the Settings pages (`app/settings/**` → `desktop-settings`), the plugin/contribution
registry internals, Electron main-process code (`apps/desktop/electron/**`), the pane-shell tree
engine internals, and the web dashboard SPA (`web/`).

Paths are relative to `apps/desktop/src` unless stated otherwise. All UI strings are quoted from
`src/i18n/en.ts` (locale `en`); the i18n key path is given as `i18n: <dotted key>`.

---

## 1. Shell — titlebar

### Titlebar band (window chrome strip)  `id: desktop-a.titlebar-band`
- **Surface:** Desktop app
- **Where:** The 34px strip at the very top of every Hermes desktop window; contains the OS traffic lights (macOS) or native window-controls overlay (Windows/Linux) plus three floating icon clusters.
- **What it does:** Provides a draggable window band, positions the app's three icon clusters so they never collide with the OS window buttons, and supplies the `--titlebar-height` CSS variable that every other surface clears.
- **How it works:** `app/shell/titlebar.ts` exports the geometry constants: `TITLEBAR_HEIGHT = 34` (titlebar.ts:3), `MACOS_TRAFFIC_LIGHTS_HEIGHT = 14` (:4), `TITLEBAR_CONTROL_SIZE = 24` (:6), `TITLEBAR_ICON_SIZE = 13.9` (:8), `TITLEBAR_ICON_BADGE_SCALE = 0.65` (:9), `TITLEBAR_CONTROL_OFFSET_X = 74` (:10), `TITLEBAR_CONTROLS_TOP = (34-24)/2` (:12), `TITLEBAR_FALLBACK_WINDOW_BUTTON_X = 24` (:19), `TITLEBAR_EDGE_INSET = 14` (:23), `MACOS_TAHOE_DARWIN_MAJOR = 25` (:26). `titlebarControlsPosition()` (:91) pins the left cluster at `windowButtonPosition.x + 74` on pre-Tahoe macOS and at `TITLEBAR_EDGE_INSET` when `windowButtonPosition === null` (Windows/Linux) or in fullscreen. `titlebarControlsYNudge()` (:39) applies `calc(var(--spacing) * 0.9)` only on the macOS traffic-light row (not fullscreen, not Darwin ≥ 25). `titlebarToolsRightCss()` (:52) inset the right cluster by the measured native window-controls-overlay width, else `14px` in macOS fullscreen, else `0.75rem`. The overlay width comes from `app/shell/hooks/use-window-controls-overlay-width.ts`, which reads `navigator.windowControlsOverlay.getTitlebarAreaRect()` and computes `innerWidth - rect.right`, re-measuring on `geometrychange` and `resize` (returns `null` when WCO is absent, so the static main-process reservation is used).
- **Inputs / options:** No user controls of its own; drag anywhere on the band moves the window (`-webkit-app-region: drag`). Clusters carve out `[-webkit-app-region:no-drag]` (`titlebarToolClusterClass`, titlebar.ts:74).
- **Outputs / side effects:** Sets CSS custom properties `--titlebar-height`, `--titlebar-controls-left`, `--titlebar-controls-top`, `--titlebar-controls-y-nudge`, `--titlebar-tools-right`, `--titlebar-tools-width`, `--titlebar-content-inset`, `--shell-preview-toolbar-gap`.
- **Config / env:** n/a
- **Edge cases / guards:** In HUD mode nothing may declare `-webkit-app-region: drag` on macOS/Windows (would starve `useHudClickThrough` of mouse moves — see `app/hud/click-through.ts` docstring). `PageSearchShell` explicitly must NOT set a drag region on its header (page-search-shell.tsx:300-308) because it would eat the floating clusters' clicks at the compositor level.
- **Rebuild notes:** Reserve a fixed-height frameless titlebar; compute left inset from the platform's window-button rect and right inset from the WCO rect; expose both as CSS vars; render app icon clusters as `position: fixed` no-drag rows.

### Window controls cluster (left titlebar tools)  `id: desktop-a.titlebar-left-cluster`
- **Surface:** Desktop app
- **Where:** Top-left of the window, immediately right of the macOS traffic lights. `aria-label="Window controls"` (`i18n: shell.windowControls`).
- **What it does:** Holds the sidebar toggle, the pane-flip button, and any pane-contributed left tools.
- **How it works:** `app/shell/titlebar-controls.tsx:167-190` builds `leftToolbarTools` = `[sidebar, flip-panes, ...leftTools]`; rendered at :273-285 inside a `titlebarToolClusterClass` div positioned by the CSS vars above.
- **Inputs / options:** Two built-in buttons (below) plus contributed `leftTools` passed in as a prop.
- **Outputs / side effects:** none of its own.
- **Config / env:** n/a
- **Edge cases / guards:** The whole cluster returns `null` while an overlay view is open (`isOverlayView(appViewForPath(location.pathname))`, titlebar-controls.tsx:264) so it can't bleed over the overlay card.
- **Rebuild notes:** Keep the cluster a data-driven array of `TitlebarTool`; hide the entire chrome while a modal overlay route is active.

### Titlebar button — sidebar toggle  `id: desktop-a.titlebar-tool-sidebar`
- **Surface:** Desktop app
- **Where:** Left titlebar cluster, first button. Tool `id: 'sidebar'`. Icon: codicon `layout-sidebar-left`. Tooltip: `"Hide sidebar"` when open / `"Show sidebar"` when closed (`i18n: titlebar.hideSidebar` / `titlebar.showSidebar`), plus the live `⌘B` hint.
- **What it does:** Shows/hides everything on the physical LEFT side of the main zone (the sessions rail).
- **How it works:** titlebar-controls.tsx:168-178. `actionId: 'view.toggleSidebar'`; `onSelect` fires `triggerHaptic('tap')` then `toggleSidebarOpen()` from `store/layout`. It is POSITIONAL: `$sidebarOpen` ≙ the left side of the layout tree, so it stays correct through pane flips (:157-165).
- **Inputs / options:** Click; keyboard `mod+b` (`view.toggleSidebar` default). Badge: unread session count when panes are NOT flipped (`badge: panesFlipped ? undefined : unreadBadge`).
- **Outputs / side effects:** Collapses/expands the left tree side; label gains the suffix `" · N unread sessions"` (`i18n: titlebar.unreadSessions`) while unread > 0 and panes are not flipped.
- **Config / env:** none (layout state is renderer-persisted).
- **Edge cases / guards:** Below `SIDEBAR_COLLAPSE_BREAKPOINT_PX = 768` (`app/layout-constants.ts:24`) both rails auto-collapse into the hover-reveal overlay. Never renders an active background — state reads from the layout, not the button (`aria-pressed` still carries it).
- **Rebuild notes:** One boolean per physical side; the button must key off the side, not off a named pane, so flipping doesn't invert it.

### Titlebar button — swap sidebar sides  `id: desktop-a.titlebar-tool-flip-panes`
- **Surface:** Desktop app
- **Where:** Left titlebar cluster, second button. Tool `id: 'flip-panes'`. Icon: codicon `arrow-swap`. Tooltip: `"Swap sidebar sides"` (`i18n: titlebar.swapSidebarSides`) + `⌘\` hint.
- **What it does:** Mirrors the layout so the sessions rail and the right sidebar trade sides.
- **How it works:** titlebar-controls.tsx:179-188; `actionId: 'view.flipPanes'`, calls `triggerHaptic('tap')` then `togglePanesFlipped()` (`store/layout`). Keybind default `mod+\` (`lib/keybinds/actions.ts:155`).
- **Inputs / options:** Click, or `⌘\` / `Ctrl+\`.
- **Outputs / side effects:** `$panesFlipped` flips; the unread badge moves from the left-sidebar button to the right-sidebar button; the right sidebar's border/shadow side swaps (`app/right-sidebar/index.tsx:81-84`).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Store a single `flipped` boolean and derive every "which side" question from it.

### Pane controls cluster (contributed pane tools)  `id: desktop-a.titlebar-pane-cluster`
- **Surface:** Desktop app
- **Where:** Floating cluster on the right of the titlebar, LEFT of the app controls. `aria-label="Pane controls"` (`i18n: shell.paneControls`). Typical contents: the preview pane's monitor / devtools / refresh / ✕ buttons.
- **What it does:** Hosts tools scoped to whichever pane currently owns the top-right area.
- **How it works:** titlebar-controls.tsx:295-307. Rendered only when `tools.filter(t => !t.hidden).length > 0`. Positioned `top: calc(var(--titlebar-controls-top) + var(--right-rail-top-inset,0px))`, `right: calc(var(--titlebar-tools-right) + var(--shell-preview-toolbar-gap,0))` — the AppShell sets `--shell-preview-toolbar-gap` to either the static cluster width (file browser closed) or the file-browser pane width (open).
- **Inputs / options:** Whatever `TitlebarTool[]` a pane registers through `SetTitlebarToolGroup = (id, tools, side?) => void` (titlebar-controls.tsx:60).
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** Hidden along with the rest of the chrome on overlay routes.
- **Rebuild notes:** Reserve the gap with a CSS var written by the shell, not per-tool margins.

### App controls cluster (right titlebar tools)  `id: desktop-a.titlebar-app-cluster`
- **Surface:** Desktop app
- **Where:** Top-right of the window, inset by the native window-controls-overlay width. `aria-label="App controls"` (`i18n: shell.appControls`).
- **What it does:** Holds the four static system tools plus the right-sidebar toggle, in this exact order: `layout`, `hud`, `haptics`, `settings`, `right-sidebar`.
- **How it works:** titlebar-controls.tsx:206-258 defines `systemTools`; :309-317 renders them followed by `rightSidebarTool`.
- **Inputs / options:** The five buttons below.
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** Hidden on overlay routes (:264).
- **Rebuild notes:** Keep this order stable — muscle memory; the right-sidebar toggle is always outermost so it sits against the window edge.

### Titlebar button — layout editor (⌘-click resets)  `id: desktop-a.titlebar-tool-layout`
- **Surface:** Desktop app
- **Where:** App controls cluster, first button. Tool `id: 'layout'`. Icon: codicon `layout`, which morphs into `layout` + a mirrored `refresh` badge while hovered AND ⌘/Ctrl is held.
- **What it does:** Plain click toggles the pane-shell layout edit mode (the FancyZones-style editing palette); ⌘/Ctrl-click resets the whole layout tree to the shipped default.
- **How it works:** titlebar-controls.tsx:207-226. `onSelect(event)`: if `event.metaKey || event.ctrlKey` → `triggerHaptic('warning')` + `resetLayoutTree()` (`components/pane-shell/tree/store`); else `triggerHaptic('open')` + `toggleLayoutEditMode()` (`components/pane-shell/edit-mode`). The morph is `LayoutGlyph` (:75-89): CSS `group-hover/tool` gates hover, the window-level `useModifierHeld()` hook (:111-130, listens to `keydown`/`keyup`/`blur`) gates the modifier. Badge glyph size = `titlebarIconSizeCss(0.65)`.
- **Inputs / options:** Click; ⌘/Ctrl+click. Tooltip label `"Layout editor"` (`i18n: titlebar.layoutEditor`); `title` = `"Layout editor — ⌘-click resets the layout"` (`i18n: titlebar.layoutEditorTitle`, formatted with `formatModifierToken('mod')`).
- **Outputs / side effects:** Opens/closes the edit palette (which contains the Layout Picker, see `desktop-a.layout-picker`), or replaces `$layoutTree` with the declared default.
- **Config / env:** n/a
- **Edge cases / guards:** No `actionId`, so no keybind hint. The reset is destructive but instant (no confirm) — telegraphed only by the glyph morph and the warning haptic.
- **Rebuild notes:** Telegraph destructive modifier-click affordances by morphing the glyph while the modifier is down and the pointer is on the control.

### Titlebar button — HUD mode  `id: desktop-a.titlebar-tool-hud`
- **Surface:** Desktop app
- **Where:** App controls cluster, second button. Tool `id: 'hud'`. Icon: codicon `comment-discussion`. Tooltip: `"HUD mode"` (`i18n: titlebar.enterHud`) + the live `⌘⇧H` hint.
- **What it does:** Opens (or closes) the chrome-free floating HUD window on the conversation you are currently looking at.
- **How it works:** titlebar-controls.tsx:227-240. `actionId: 'view.toggleHud'`; `onSelect` = `triggerHaptic('open')` then `toggleHud(hudTargetSessionId())`. `hudTargetSessionId()` (`app/hud/handoff.ts:44`) prefers the ACTIVE composer's tile (`tile:<storedSessionId>` prefix) and falls back to `$selectedStoredSessionId`.
- **Inputs / options:** Click; keybind `view.toggleHud` default `mod+shift+h`.
- **Outputs / side effects:** `openHud()` (`store/hud.ts:46`) flushes composer drafts (`requestComposerDraftSync('flush')`), resolves the owning gateway profile via `rememberedSessionProfile(...)`, sets `$hudActive`/`$hudSession`, and calls `window.hermesDesktop.hud.open({sessionId, profile})`. `closeHud()` (:74) clears both atoms and calls `hud.close()`.
- **Config / env:** n/a
- **Edge cases / guards:** No `title` override on purpose — a long sentence there would replace the label and crowd the ⌘⇧H hint off the tooltip (comment at :228-231). `canUseHud()` requires `window.hermesDesktop.hud.open` to exist.
- **Rebuild notes:** Model the HUD as a real second renderer, not a lookalike; hand it the session id AND the backend profile.

### Titlebar button — mute/unmute haptics  `id: desktop-a.titlebar-tool-haptics`
- **Surface:** Desktop app
- **Where:** App controls cluster, third button. Tool `id: 'haptics'`. Icon: codicon `mute` when muted, `unmute` when not. Tooltip: `"Unmute haptics"` when muted / `"Mute haptics"` when not (`i18n: titlebar.unmuteHaptics` / `titlebar.muteHaptics`).
- **What it does:** Turns the app's haptic/click feedback on or off.
- **How it works:** titlebar-controls.tsx:241-247 + the `toggleHaptics` closure at :145-155: if currently unmuted it fires `triggerHaptic('tap')` FIRST (so you feel the last tap), then `toggleHapticsMuted()` (`store/haptics`); if it was muted it schedules `triggerHaptic('success')` on the next animation frame (so you feel it come back). `active: hapticsMuted` sets `aria-pressed`.
- **Inputs / options:** Click only (no keybind).
- **Outputs / side effects:** `$hapticsMuted` (persisted) flips; every `triggerHaptic()` call site goes silent.
- **Config / env:** n/a
- **Edge cases / guards:** Haptics are a no-op on platforms without the API; the toggle still works.
- **Rebuild notes:** Play the feedback on the transition itself so the control demonstrates what it changed.

### Titlebar button — open settings  `id: desktop-a.titlebar-tool-settings`
- **Surface:** Desktop app
- **Where:** App controls cluster, fourth button. Tool `id: 'settings'`. Icon: codicon `settings-gear`. Tooltip: `"Open settings"` (`i18n: titlebar.openSettings`) + `⌘,` hint.
- **What it does:** Opens the Settings overlay.
- **How it works:** titlebar-controls.tsx:248-257. `actionId: 'nav.settings'`; `onSelect` = `triggerHaptic('open')` then the injected `onOpenSettings()` prop (the shell navigates to `/settings`).
- **Inputs / options:** Click; keybind `nav.settings` default `mod+,`.
- **Outputs / side effects:** Router navigates to `SETTINGS_ROUTE = '/settings'`; the whole titlebar cluster then hides because `settings` is an overlay view.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Titlebar button — right sidebar toggle  `id: desktop-a.titlebar-tool-right-sidebar`
- **Surface:** Desktop app
- **Where:** App controls cluster, last (outermost) button. Tool `id: 'right-sidebar'`, `data-tour="right-pane-toggle"`. Icon: codicon `layout-sidebar-right`. Tooltip: `"Hide right sidebar"` / `"Show right sidebar"` (`i18n: titlebar.hideRightSidebar` / `titlebar.showRightSidebar`) + `⌘J` hint.
- **What it does:** Shows/hides everything on the physical RIGHT side of the main zone (file browser / review / terminal column).
- **How it works:** titlebar-controls.tsx:192-203; `actionId: 'view.toggleRightSidebar'`, `onSelect` = `triggerHaptic('tap')` + `toggleFileBrowserOpen()`. The keybind handler is smarter: `view.toggleRightSidebar` → `layoutHasRootSide('right') ? toggleFileBrowserOpen() : togglePaneVisible('terminal')` (`app/hooks/use-keybinds.ts:248-249`), so on a layout with no right side (terminal-on-bottom) the chord falls back to the terminal.
- **Inputs / options:** Click; keybind `mod+j`. Badge: unread session count when panes ARE flipped.
- **Outputs / side effects:** `$fileBrowserOpen` flips.
- **Config / env:** n/a
- **Edge cases / guards:** Same 768px auto-collapse as the left rail.
- **Rebuild notes:** n/a

### Titlebar unread-session badge  `id: desktop-a.titlebar-unread-badge`
- **Surface:** Desktop app
- **Where:** Overlaid on the sidebar-toggle glyph (or the right-sidebar glyph when panes are flipped), top-right of the icon.
- **What it does:** Shows how many sessions have unread activity, in compact notation (e.g. `12`, `1.2k`).
- **How it works:** `withCountBadge()` (titlebar-controls.tsx:92-107) wraps the icon and renders `<Badge size="overlay" variant="solid">{compactNumber(count)}</Badge>` at `-top-2.5 -right-1.5`; hidden when the count is 0/undefined. Count comes from `$unreadSessionCount` (`store/session-dot-state`).
- **Inputs / options:** none (display only).
- **Outputs / side effects:** Appends `" · 1 unread session"` / `" · N unread sessions"` (`i18n: titlebar.unreadSessions`) to the button's aria-label/tooltip.
- **Config / env:** n/a
- **Edge cases / guards:** `aria-hidden` on the badge itself (the count is already in the label).
- **Rebuild notes:** n/a

### Titlebar tool contribution contract  `id: desktop-a.titlebar-tool-contract`
- **Surface:** Desktop app (extension API)
- **Where:** `app/shell/titlebar-controls.tsx:38-60`, consumed by panes and plugins.
- **What it does:** Defines the object a pane or plugin registers to add a titlebar icon button.
- **How it works:** `interface TitlebarTool { id; label; active?; className?; disabled?; hidden?; href?; icon: ReactNode; onSelect?(event?); actionId?; badge?: number; title?; to?; tour? }`. `TitlebarToolSide = 'left' | 'right'`; `SetTitlebarToolGroup = (id, tools, side?) => void`. `TitlebarToolButton` (:322-377) renders `href` tools as an `<a target="_blank" rel="noreferrer">` inside a ghost `Button size="icon-titlebar"`, otherwise a `<button>` that calls `navigate(tool.to)` then `tool.onSelect(event)`; both `stopPropagation()` on `pointerdown` so the drag region doesn't swallow the press. Tooltip content is `<TipKeybindLabel actionId text={title ?? label}/>` when `actionId` is set, else the plain string.
- **Inputs / options:** every field above.
- **Outputs / side effects:** Buttons never paint an active background — `aria-pressed` carries state instead (comment :323-325).
- **Config / env:** n/a
- **Edge cases / guards:** `hidden` tools are filtered out before render; `tour` gives a locale/theme-proof `data-tour` handle.
- **Rebuild notes:** One declarative tool type shared by app, panes and plugins; keybind hints resolved from an action registry rather than hardcoded.

---

## 2. Shell — status bar

### Status bar  `id: desktop-a.statusbar`
- **Surface:** Desktop app
- **Where:** The 20px (`h-5`) strip pinned to the bottom of the window, `data-slot="statusbar"`.
- **What it does:** Ambient chrome: gateway health, workspace, agents, timers, context meter, approvals, terminal, version/update pills. Left cluster and right cluster, each horizontally clipped.
- **How it works:** `app/shell/statusbar-controls.tsx:92-129`. `StatusbarControls` renders a `<footer>` with `bg-(--ui-sidebar-surface-background)`, `[-webkit-app-region:no-drag]`, wrapped in a Radix `ContextMenu` whose content is `StatusbarVisibilityMenu`. Left items and right items are separate arrays; each is filtered by `visible(item) = !item.hidden && (item.lockedVisible || !item.toggleLabel || !hiddenIds.includes(item.id))`. Uses `overflow-x-clip` (not auto) so a long label can never paint a horizontal scrollbar. Items are built by `useStatusbarItems()` (`app/shell/hooks/use-statusbar-items.tsx`).
- **Inputs / options:** Right-click anywhere on the bar → the visibility menu. Individual items below.
- **Outputs / side effects:** none of its own.
- **Config / env:** whole-bar visibility persists at `localStorage['hermes.desktop.statusbarVisible']` (default `true`); per-item hidden set at `localStorage['hermes.desktop.statusbarHidden']` (`store/statusbar-prefs.ts:3-9,37-43`).
- **Edge cases / guards:** Hiding the whole bar unmounts it (and its 15s status poll), so the way back is only `⌘⇧S` or the ⌘K row (comment statusbar-prefs.ts:6-8). `StatusbarItemView` is `memo`ized — measured 1,446 wasted renders of 2,174 during a five-tab streaming run without it (comment :214-219).
- **Rebuild notes:** Model the bar as `{left: Item[], right: Item[]}` where an item is data (label/detail/icon/variant/menu) plus an optional `render()` escape hatch; memoize per item.

### Status bar item contract  `id: desktop-a.statusbar-item-contract`
- **Surface:** Desktop app (extension API)
- **Where:** `app/shell/statusbar-controls.tsx:33-85`.
- **What it does:** Defines what a statusbar entry can be, including plugin-contributed ones.
- **How it works:** `interface StatusbarItem { id; render?(): ReactNode; label?; detail?; icon?; className?; disabled?; hidden?; href?; menuAlign?: 'center'|'end'|'start'; menuClassName?; menuContent?: ((close)=>ReactNode)|ReactNode; menuItems?: StatusbarMenuItem[]; onSelect?(modifiers: {shiftKey}); actionId?; title?; to?; variant?: 'action'|'link'|'menu'|'text'; toggleLabel?; lockedVisible? }`. `StatusbarMenuItem = { id; icon?; label; className?; disabled?; hidden?; href?; onSelect?; title?; to? }`. Four render paths (:236-360): `menu` → Radix DropdownMenu (`side="top"`, `sideOffset={8}`, default `align="start"`, width `w-56` unless overridden); `text` with no action → a non-interactive div; `href`/`link` → `<a target="_blank">`; else a `<button>` that navigates `to` then calls `onSelect({shiftKey})`. A `render()` item takes the whole slot via `<ContribRender>`.
- **Inputs / options:** every field above.
- **Outputs / side effects:** `toggleLabel` is what makes the item appear in the right-click show/hide menu; without one it always shows. `lockedVisible` lists it but disables the checkbox.
- **Config / env:** n/a
- **Edge cases / guards:** The `Tip` helper can't wrap a DropdownMenu root (no DOM child), so the menu path composes `TooltipTrigger` + `DropdownMenuTrigger` onto the same `<button>` (comment :245-249).
- **Rebuild notes:** Separate "is this item allowed to be hidden" (`toggleLabel`) from "is it currently hidden" (the stored id set).

### Status bar item — Command Center  `id: desktop-a.statusbar-command-center`
- **Surface:** Desktop app
- **Where:** Left cluster, first item. Item `id: 'command-center'`. Icon: lucide `Command`, 28px-wide centered square. Tooltip: `"Open Command Center"` / `"Close Command Center"` (`i18n: shell.statusbar.openCommandCenter` / `closeCommandCenter`). Toggle-menu label: `"Command Center"` (`i18n: shell.statusbar.toggleCommandCenter`).
- **What it does:** Opens/closes the Command Center overlay.
- **How it works:** use-statusbar-items.tsx:397-408; `onSelect: toggleCommandCenter` (from `useOverlayRouting`, which navigates to `/command-center` or back to the stashed previous route). While open the button gains `bg-accent/55 text-foreground`.
- **Inputs / options:** Click; keybind `nav.commandCenter` default `mod+.`.
- **Outputs / side effects:** Route change.
- **Config / env:** n/a
- **Edge cases / guards:** `lockedVisible: true` — "the way into every other surface, including the settings that would bring a hidden item back" (comment :401-402).
- **Rebuild notes:** Never let the user hide the affordance that un-hides things.

### Status bar item — gateway/profile switcher  `id: desktop-a.statusbar-gateway-switcher`
- **Surface:** Desktop app
- **Where:** Left cluster, second slot. Item `id: 'gateway-switcher'`; a full `render()` contribution — the compact `<ConnectionSwitcher compact/>` from `app/chat/sidebar/connection-switcher`.
- **What it does:** Shows and switches the active gateway connection/profile from the status bar.
- **How it works:** use-statusbar-items.tsx:409-414 + :619-623 (`StatusbarGatewaySwitcher`); `onConnect` navigates to `/settings?tab=connections`.
- **Inputs / options:** The switcher's own popover (documented in the sidebar shard).
- **Outputs / side effects:** Switches profile / opens the Connections settings tab.
- **Config / env:** n/a
- **Edge cases / guards:** `hidden: !sessionsShowing` — only rendered while the `sessions` pane is on screen; `lockedVisible: true`.
- **Rebuild notes:** n/a

### Status bar item — Gateway health  `id: desktop-a.statusbar-gateway-health`
- **Surface:** Desktop app
- **Where:** Left cluster. Item `id: 'gateway-health'`. Label: `"Gateway"` (`i18n: shell.statusbar.gateway`); detail is one of `"ready"`, `"needs setup"`, `"inference unavailable"`, `"checking"`, `"connecting"`, `"offline"`, `"restarting…"` (`i18n: shell.statusbar.gatewayReady` / `gatewayNeedsSetup` / `gatewayUnavailable` / `gatewayChecking` / `gatewayConnecting` / `gatewayOffline` / `gatewayRestarting`). Toggle-menu label: `"Gateway"`.
- **What it does:** One-glance backend health, and a click opens the Gateway popover panel.
- **How it works:** use-statusbar-items.tsx:415-434. Icon: `GlyphSpinner` while `$gatewayRestarting`, else lucide `Activity` when inference is ready, else `AlertCircle`. Colour: default when ready, `text-amber-600` while open-or-connecting but not ready, `text-destructive` when down. Detail resolution at :291-301 maps `runtimeReadinessDisplay(inferenceStatus)` (`lib/runtime-readiness`) to the four ready-state strings. `variant: 'menu'`, `menuClassName: 'w-72'`, `menuContent` = `<GatewayMenuPanel/>`. Tooltip only when `inferenceStatus.reason` is non-empty.
- **Inputs / options:** Click → panel.
- **Outputs / side effects:** none directly.
- **Config / env:** Health is polled by `useStatusSnapshot` (below).
- **Edge cases / guards:** `hidden: botsShowing` — suppressed while the `hermes-bots:pane` is visible.
- **Rebuild notes:** Separate "transport connected" from "inference ready"; never collapse them into one dot.

### Gateway menu panel  `id: desktop-a.gateway-menu-panel`
- **Surface:** Desktop app
- **Where:** Popover above the Gateway status item (`app/shell/gateway-menu-panel.tsx`).
- **What it does:** Shows connection + inference state, three actions, a live log tail, and per-platform messaging status.
- **How it works:** Header row (:162-215): two `StatusDot` lines — connection (`"Connected"` / `"Connecting"` / prettified raw state or `"Offline"`; `i18n: shell.gatewayMenu.connected|connecting|offline`) and inference (`"Inference ready"` / `"Inference not ready"` / `"Checking inference"` / `"Disconnected"`; `i18n: shell.gatewayMenu.inferenceReady|inferenceNotReady|checkingInference|disconnected`). Buttons on the right: **Reconnect gateway** (`i18n: shell.gatewayMenu.reconnectGateway`, `RefreshCw` icon, shown only while the gateway is NOT open, spins while reconnecting, calls `reconnectGateway()`); **Open system panel** (`i18n: shell.gatewayMenu.openSystem`, `LayoutDashboard` icon, closes the popover and opens Command Center → System); a vertical divider; **Restart gateway** (`i18n: commandCenter.restartGateway`, `Power` icon, `hover:text-destructive`, calls `runGatewayRestart()`). Optional reason section (`line-clamp-3`). **Recent activity** section (`i18n: shell.gatewayMenu.recentActivity`) with a `"View all logs →"` text button (`i18n: shell.gatewayMenu.viewAllLogs`) and a `LogView` capped at `max-h-40`, auto-scrolled to the bottom. **Messaging platforms** section (`i18n: shell.gatewayMenu.messagingPlatforms`) listing `statusSnapshot.gateway_platforms` alphabetically with a tone dot per state.
- **Inputs / options:** 3–4 buttons + the "View all logs →" link; no inputs.
- **Outputs / side effects:** Reconnect / restart RPCs; navigation to the System panel; `notifyError(err, "Reconnect gateway")` on a failed reconnect.
- **Config / env:** Log tail: `getLogs({file:'gui', lines:120})` every `3000 ms` while the popover is mounted, filtered by `LOG_NOISE_RE = /\bws (?:accepted|closed|response sent|ping|pong)\b/i`, last 40 lines kept, each line stripped of a leading `YYYY-MM-DD HH:MM:SS,mmm ` timestamp and a leading `[runtime_id] ` bracket.
- **Edge cases / guards:** `getLogs` THROWS (not rejects) when the desktop bridge is missing, so the loader is `async` to keep the throw inside the promise (comment :41-43). Platform tone map: `connected→good`, `connecting|retrying|pending_restart→warn`, `startup_failed|fatal→bad`, anything else `muted`.
- **Rebuild notes:** Poll logs only while the popover is mounted; strip transport chatter before showing a "recent activity" tail.

### Status bar item — Workspace (cwd)  `id: desktop-a.statusbar-workspace-cwd`
- **Surface:** Desktop app
- **Where:** Left cluster. Item `id: 'workspace-cwd'`, `FolderOpen` icon. Label: the named project, else the cwd's last path segment. Toggle-menu label: `"Workspace"` (`i18n: shell.statusbar.toggleWorkspace`).
- **What it does:** Names the working directory of the FOCUSED session and offers three path actions.
- **How it works:** use-statusbar-items.tsx:435-468. `projectName = projectNameForCwd(currentCwd)` from the cached `$projectTree`; tooltip is `displayPath(currentCwd)` (home → `~`). The cwd itself is resolved through a careful ladder (:186-216): live runtime cwd only when it provably belongs to the focused chat (`focusedStateStoredId === focusedStoredSessionId` or `idsShareLineage(...)`), else the stored session row's cwd, else `$currentCwd` when the primary is focused, else empty.
- **Inputs / options:** `variant: 'menu'` with three items — `"Copy path"` (`i18n: fileMenu.copyPath`, `copyFilePath(cwd)`), `"Open containing folder"` (`i18n: fileMenu.revealFileManager`, `revealFile(cwd)`), `"Reveal in filetree"` (`i18n: fileMenu.revealInSidebar`, `revealFileInTree(cwd)`). Each row's `title` is the displayed path.
- **Outputs / side effects:** Clipboard write; OS file-manager launch; the right sidebar's tree expands to and scrolls to the folder.
- **Config / env:** n/a
- **Edge cases / guards:** `hidden: !currentCwd`. A focused TILE must never inherit the primary's workspace — an empty tile cwd stays empty rather than naming another project (comment :186-192).
- **Rebuild notes:** Gate live cwd on ownership; a lagging runtime slice must not label the wrong session's directory.

### Status bar item — Agents  `id: desktop-a.statusbar-agents`
- **Surface:** Desktop app
- **Where:** Left cluster. Item `id: 'agents'`. Label: `"Agents"` (`i18n: shell.statusbar.agents`). Tooltip: `"Open agents"` / `"Close agents"` (`i18n: shell.statusbar.openAgents` / `closeAgents`). Toggle-menu label: `"Agents"`.
- **What it does:** Opens the Agents overlay (`/agents`) and reports running/failed subagent counts.
- **How it works:** use-statusbar-items.tsx:469-494. Detail: `"N subagents"` / `"1 subagent"` (`i18n: shell.statusbar.subagents`) while running > 0, else `"N failed"` (`i18n: shell.statusbar.failed`) while failed > 0, else nothing. Icon: `AlertCircle` on failures, spinning `Loader2` while running, else codicon `hubot`. Counts are `useStoreSelector`-derived scalars over `$subagentsBySession` (sum of `activeSubagentCount` / `failedSubagentCount`) so a progress tick in any session doesn't rebuild all nine items (comment :109-113). Failed > 0 also tints the item `text-destructive`.
- **Inputs / options:** Click → `openAgents()` → navigate `/agents`.
- **Outputs / side effects:** Route change; while open the item gains `bg-accent/55`.
- **Config / env:** n/a
- **Edge cases / guards:** Hidden by default (`STATUSBAR_HIDDEN_BY_DEFAULT` includes `'agents'`).
- **Rebuild notes:** Select scalars, not the whole map, from a high-frequency store.

### Status bar item — Cron  `id: desktop-a.statusbar-cron`
- **Surface:** Desktop app
- **Where:** Left cluster. Item `id: 'cron'`, `Clock` icon, label `"Cron"` (`i18n: shell.statusbar.cron`). Toggle-menu label: `"Cron"`.
- **What it does:** Navigates to the scheduled-jobs overlay.
- **How it works:** use-statusbar-items.tsx:495-502; `to: CRON_ROUTE` (`/cron`).
- **Inputs / options:** Click. (`i18n: shell.statusbar.openCron` = `"Open cron jobs"` exists for the tooltip variant.)
- **Outputs / side effects:** Route change.
- **Config / env:** n/a
- **Edge cases / guards:** Hidden by default.
- **Rebuild notes:** n/a

### Status bar item — Webhooks  `id: desktop-a.statusbar-webhooks`
- **Surface:** Desktop app
- **Where:** Left cluster. Item `id: 'webhooks'`, `Globe` icon, label `"Webhooks"` (`i18n: shell.statusbar.webhooks`). Toggle-menu label: `"Webhooks"`.
- **What it does:** Navigates to the webhooks overlay.
- **How it works:** use-statusbar-items.tsx:503-510; `to: WEBHOOKS_ROUTE` (`/webhooks`). (`i18n: shell.statusbar.openWebhooks` = `"Open webhooks"`.)
- **Inputs / options:** Click.
- **Outputs / side effects:** Route change.
- **Config / env:** n/a
- **Edge cases / guards:** Hidden by default.
- **Rebuild notes:** n/a

### Status bar item — turn timer ("Running")  `id: desktop-a.statusbar-running-timer`
- **Surface:** Desktop app
- **Where:** Right cluster, first. Item `id: 'running-timer'`. Label `"Running"` (`i18n: shell.statusbar.turnRunning`), detail = live elapsed clock. Toggle-menu label: `"Turn timer"` (`i18n: shell.statusbar.toggleRunningTimer`).
- **What it does:** Counts up while the focused session is mid-turn.
- **How it works:** use-statusbar-items.tsx:538-546. `variant: 'text'`, spinning `Loader2` icon, detail `<LiveDuration since={turnStartedAt}/>`. `LiveDuration` (`lib/statusbar.tsx:62-72`) ticks once a second through `useViewedInterval` and formats via `formatDuration` (`H:MM:SS` when ≥ 1h, else `M:SS`).
- **Inputs / options:** none (display only).
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** `hidden: !busy || !turnStartedAt`. Hidden by default.
- **Rebuild notes:** n/a

### Status bar item — context meter  `id: desktop-a.statusbar-context-usage`
- **Surface:** Desktop app
- **Where:** Right cluster. Item `id: 'context-usage'`. Label e.g. `18.2k/200k`; detail e.g. `[████░░░░░░] 42%`. Toggle-menu label: `"Context meter"` (`i18n: shell.statusbar.toggleContextUsage`).
- **What it does:** Shows how full the focused session's context window is, and opens a per-category breakdown.
- **How it works:** use-statusbar-items.tsx:547-559. Label from `usageContextLabel(gaugeUsage)` (`lib/statusbar.tsx:44-50`): `${compactNumber(context_used)}/${compactNumber(context_max)}` when a max is known, else `"${compactNumber(total)} tok"`, else empty. Detail from `contextBarLabel` (:52-60) which renders a 10-cell bar of `█`/`░` plus the clamped integer percent. `gaugeUsage` (:254-265) merges the measured/estimated breakdown over the streamed usage. `variant: 'menu'`, `menuAlign: 'end'`, `menuClassName: 'w-auto border-(--ui-stroke-secondary) p-0'`, content = `<ContextUsagePanel/>`.
- **Inputs / options:** Click → panel.
- **Outputs / side effects:** none.
- **Config / env:** Breakdown RPC: `session.context_breakdown { session_id }` via `useContextBreakdown` (`app/shell/hooks/use-context-breakdown.ts`) — fetched as soon as the gauge is on screen, skipped while `busy` (mid-turn the streamed usage carries the gauge) and skipped entirely when the item is hidden (`$statusbarHiddenIds.includes('context-usage')`).
- **Edge cases / guards:** `hidden: !contextUsage`. Hidden by default. Breakdown is a read-only chars/4 estimate — no provider call, no prompt-cache impact (comment use-context-breakdown.ts:224-227). Results are keyed by session id so a switch drops the old numbers.
- **Rebuild notes:** Estimate occupancy locally so a resumed session's gauge isn't blank until the first turn.

### Context Usage panel  `id: desktop-a.context-usage-panel`
- **Surface:** Desktop app
- **Where:** Popover above the context meter (`app/shell/context-usage-panel.tsx`), `data-slot="context-usage-panel"`, width `w-72`.
- **What it does:** Breaks the used context down by category with a stacked bar and a legend.
- **How it works:** Header: title `"Context Usage"` (`i18n: shell.statusbar.contextUsagePanel.title`) and `"~18.2k / 200k Tokens"` (`i18n: ...tokenSummary(used, max)`); then `"42% Full"` (`i18n: ...percentFull`); then `<ContextUsageBar>` (`data-slot="context-usage-bar"`, `h-1.5`, one `<span>` per category sized `tokens/segmentTotal`, coloured by `category.color`); then a `<ul>` legend of `swatch · label · compactNumber(tokens)`. Category labels are localised from `i18n: shell.statusbar.contextUsagePanel.categories.*`: `conversation` → `"Conversation"`, `mcp` → `"MCP"`, `memory` → `"Memory"`, `rules` → `"Rules"`, `skills` → `"Skills"`, `subagent_definitions` → `"Subagent definitions"`, `system_prompt` → `"System prompt"`, `tool_definitions` → `"Tool definitions"` (falling back to the server label for unknown ids).
- **Inputs / options:** none (read-only).
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** `"Loading breakdown…"` (`i18n: ...loading`) while loading with no categories; `"No context data yet"` (`i18n: ...empty`) when loaded and empty. `segmentTotal` falls back to `contextUsed` then `1` so the bar never divides by zero; the empty bar wears the `dither` texture.
- **Rebuild notes:** Render the header, bar and legend from ONE merged usage object so they can never disagree.

### Status bar item — session timer  `id: desktop-a.statusbar-session-timer`
- **Surface:** Desktop app
- **Where:** Right cluster. Item `id: 'session-timer'`. Label `"Session"` (`i18n: shell.statusbar.session`), detail = live elapsed clock since the session started. Toggle-menu label: `"Session timer"` (`i18n: shell.statusbar.toggleSessionTimer`).
- **What it does:** Counts up for the lifetime of the focused conversation.
- **How it works:** use-statusbar-items.tsx:560-567; `variant: 'text'`, `<LiveDuration since={sessionStartedAt}/>`. `sessionStartedAt` is the primary's `$sessionStartedAt` when the primary is focused, else the focused row's `started_at * 1000` (:225-229).
- **Inputs / options:** none.
- **Outputs / side effects:** none.
- **Config / env:** n/a
- **Edge cases / guards:** `hidden: !sessionStartedAt`. Hidden by default.
- **Rebuild notes:** n/a

### Status bar item — Approvals (approval-mode menu)  `id: desktop-a.statusbar-approval-mode`
- **Surface:** Desktop app
- **Where:** Right cluster. Item `id: 'approval-mode'`. Label is the current mode: `"Manual"` / `"Smart"` / `"Off"` (`i18n: shell.approvalMode.manual|smart|off`). Tooltip: `"Approval mode: <mode>"` (`i18n: shell.approvalMode.ariaLabel`). Toggle-menu label: `"Approvals"` (`i18n: shell.statusbar.toggleApprovalMode`).
- **What it does:** Shows and changes how the agent asks permission before risky actions, per gateway profile.
- **How it works:** `app/shell/approval-mode-menu.tsx` — `useApprovalModeStatusbarItem(profile, requestGateway)`. Mode read from `$approvalModes[profile.trim() || 'default']`, defaulting to `'smart'` (:25). On mount it calls `syncApprovalModeForProfile(requestGateway, profile)`. `variant: 'menu'`, `menuAlign: 'end'`, `menuClassName: 'w-72 p-1'`. Panel content: label `"Approval mode"` (`i18n: shell.approvalMode.title`), a separator, then a `DropdownMenuRadioGroup` over exactly `['manual','smart','off']`, each row rendering the mode name over its description.
- **Inputs / options:** Three radio items, in this order:
  1. **Manual** — `"Ask before actions that require approval"` (`i18n: shell.approvalMode.manualDescription`).
  2. **Smart** — `"Automatically assess actions and ask when needed"` (`i18n: shell.approvalMode.smartDescription`).
  3. **Off** — `"Run without approval prompts"` (`i18n: shell.approvalMode.offDescription`).
- **Outputs / side effects:** `setApprovalModeForProfile(requestGateway, profile, mode)` (errors swallowed with `.catch(() => undefined)`). In `off` mode the item paints `bg-(--chrome-action-hover) text-foreground` and swaps the `Zap` icon for the filled `ZapFilled`.
- **Config / env:** Per-profile; the store is `store/approval-mode`.
- **Edge cases / guards:** `hidden: gatewayState !== 'open'` (use-statusbar-items.tsx:568-572). Hidden by default in the bar's shipped layout.
- **Rebuild notes:** Three named modes with one-line rationales; scope the setting per backend profile, not globally.

### Status bar item — Terminal toggle  `id: desktop-a.statusbar-terminal`
- **Surface:** Desktop app
- **Where:** Right cluster. Item `id: 'terminal'`, `Terminal` icon in a 28px centred square. Tooltip: `"Show terminal"` / `"Hide terminal"` (`i18n: shell.statusbar.showTerminal` / `hideTerminal`) + the `Ctrl+\`` hint. Toggle-menu label: `"Terminal"` (`i18n: shell.statusbar.toggleTerminal`).
- **What it does:** Reveals or hides the embedded terminal pane.
- **How it works:** use-statusbar-items.tsx:573-583; `actionId: 'view.showTerminal'`, `onSelect: () => togglePaneVisible('terminal')`. The lit state reads `$paneVisible('terminal')` — whether the pane is genuinely ON SCREEN, not just the takeover flag (comment :93-96).
- **Inputs / options:** Click; keybind `view.showTerminal` default `ctrl+\``.
- **Outputs / side effects:** Pane visibility toggles; button gains `bg-accent/55` while showing.
- **Config / env:** n/a
- **Edge cases / guards:** `hidden: !chatOpen`. Hidden by default.
- **Rebuild notes:** Base a toggle's lit state on visibility in the layout tree, not on an intent flag.

### Status bar item — client version / update pill  `id: desktop-a.statusbar-version-client`
- **Surface:** Desktop app
- **Where:** Right cluster, second-to-last. Item `id: 'version-client'`. Label/detail come from `resolveVersionStatus` (`lib/version-status`), e.g. `Hermes Desktop v2026.8.31`, `client v…`, `commit abc1234`, `branch main`, `restart`, `update`, `unknown`. Toggle-menu label: `"Version & updates"` (`i18n: shell.statusbar.toggleVersion`).
- **What it does:** Reports the running desktop version, whether an update is available, and opens the update overlay.
- **How it works:** use-statusbar-items.tsx:308-351. Icon: spinning `Loader2` while applying (`updateApply.applying || stage === 'restart'`), else `Hash`. `className: 'text-primary hover:text-primary'` when `status.hasUpdate`. `onSelect: () => openUpdateOverlayFor('client')`. Copy strings live under `i18n: shell.statusbar.*`: `unknown`, `restart`, `update`, `updateInProgress` (`"Update in progress"`), `commitsBehind(count, branch)` (`"N commits behind main"`), `desktopVersion(v)` (`"Hermes Desktop vX"`), `backendVersion(v)`, `clientLabel(v)` (`"client vX"`), `backendLabel(v)`, `commit(sha)`, `branch(b)`, plus the connection variants `connectionSsh(host)` (`"SSH: host"`), `connectionRemote(host)`, `connectionCloud(host)` and their tooltip forms `connectionCloudTooltip` (`"Hermes Cloud · host"`), `connectionSshTooltip` (`"SSH · host"`), `connectionRemoteTooltip` (`"Remote · host"`).
- **Inputs / options:** Click.
- **Outputs / side effects:** Opens the Updates overlay targeting the client.
- **Config / env:** n/a
- **Edge cases / guards:** `hidden: status.unknown`; `lockedVisible: true` — "Update state is not a preference: hiding it is how a user misses that their client is behind" (comment :331-333).
- **Rebuild notes:** n/a

### Status bar item — backend version / update pill  `id: desktop-a.statusbar-version-backend`
- **Surface:** Desktop app
- **Where:** Right cluster, last. Item `id: 'version-backend'`. Toggle-menu label: `"Backend version"` (`i18n: shell.statusbar.toggleBackendVersion`).
- **What it does:** Same as the client pill but for the connected remote backend.
- **How it works:** use-statusbar-items.tsx:353-393. Rendered ONLY when `connection?.mode === 'remote'` (returns `null` otherwise). Version from `statusSnapshot?.version`; state from `$backendUpdateStatus` / `$backendUpdateApply`. `onSelect: () => openUpdateOverlayFor('backend')`. `lockedVisible: true`.
- **Inputs / options:** Click.
- **Outputs / side effects:** Opens the Updates overlay targeting the backend.
- **Config / env:** n/a
- **Edge cases / guards:** `hidden: status.unknown`.
- **Rebuild notes:** n/a

### Status bar right-click menu — "Show in status bar"  `id: desktop-a.statusbar-context-menu`
- **Surface:** Desktop app
- **Where:** Right-click anywhere on the status bar. Menu width `w-52`.
- **What it does:** Lets the user choose which items the bar shows, reset that choice, or hide the bar entirely.
- **How it works:** `StatusbarVisibilityMenu` (statusbar-controls.tsx:135-205). Rows are built from `[...leftItems, ...items]` in bar order, deduped by id, keeping only items with a `toggleLabel`. Each is a `ContextMenuCheckboxItem` whose `checked = lockedVisible || !hiddenIds.includes(id)` and which is `disabled` when `lockedVisible`. `onSelect` calls `event.preventDefault()` so the menu STAYS OPEN across several toggles (comment :176-178).
- **Inputs / options:** In shipped order the checkbox list is: `"Command Center"` (locked), `"Gateway"`, `"Workspace"`, `"Agents"`, `"Cron"`, `"Webhooks"`, `"Turn timer"`, `"Context meter"`, `"Session timer"`, `"Approvals"`, `"Terminal"`, `"Version & updates"` (locked), `"Backend version"` (locked, remote only) — plus any plugin item that declared a `toggleLabel`. Then a separator, then:
  - **"Reset to defaults"** (`i18n: shell.statusbar.resetStatusbar`) — `resetStatusbarLayout()`; DISABLED when `isStatusbarLayoutDefault(hiddenIds)`.
  - **"Hide status bar"** (`i18n: shell.statusbar.hideStatusbar`) — `toggleStatusbarVisible()`, with the live `⌘⇧S` hint rendered right-aligned by `StatusbarHideHint` (`useKeybindHint('view.toggleStatusbar')`).
  - Header label above the checkboxes: `"Show in status bar"` (`i18n: shell.statusbar.customizeTitle`).
- **Outputs / side effects:** Writes `localStorage['hermes.desktop.statusbarHidden']` / `['hermes.desktop.statusbarVisible']`.
- **Config / env:** n/a
- **Edge cases / guards:** The reset row is disabled rather than hidden so the user can discover a shipped layout exists (comment :185-187). Resetting only touches item layout, never whole-bar visibility (comment statusbar-prefs.ts:65-67).
- **Rebuild notes:** Persist the HIDDEN set, not the visible one, so items added in later versions appear for existing users (comment statusbar-prefs.ts:32-36).

### Status bar default hidden set  `id: desktop-a.statusbar-defaults`
- **Surface:** Config (renderer-local)
- **Where:** `store/statusbar-prefs.ts:21-30`.
- **What it does:** Decides which statusbar items ship switched off.
- **How it works:** `STATUSBAR_HIDDEN_BY_DEFAULT = ['agents','approval-mode','context-usage','cron','running-timer','session-timer','terminal','webhooks']`. Rationale in the comment: route shortcuts, the terminal toggle and the approval pill are navigation, not status; the per-turn readouts are diagnostics most users don't watch. `isStatusbarLayoutDefault()` compares as a SET (order/dupes are incidental). Codec is a sanitizing JSON array codec so an empty array is a real value (`Codecs.stringArray` would drop the key and resurrect the defaults).
- **Inputs / options:** `setStatusbarItemVisible(id, visible)`, `resetStatusbarLayout()`, `toggleStatusbarVisible()`.
- **Outputs / side effects:** localStorage writes.
- **Config / env:** keys `hermes.desktop.statusbarHidden`, `hermes.desktop.statusbarVisible`.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Status snapshot polling  `id: desktop-a.status-snapshot-poll`
- **Surface:** Desktop app (Core)
- **Where:** `app/shell/hooks/use-status-snapshot.ts` — feeds the Gateway item, the gateway panel and the backend version pill.
- **What it does:** Periodically fetches `/api/status` and evaluates inference readiness.
- **How it works:** `REFRESH_MS = 60_000`. Each cycle skips work unless `document.visibilityState === 'visible' && document.hasFocus()` (macOS leaves occluded windows "visible", so focus is the missing signal — comment :136-138). Runs `Promise.allSettled([getStatus(), gatewayState === 'open' ? evaluateRuntimeReadiness(requestGateway) : null])` and only schedules the next poll after both settle (no overlapping polls). Refreshes immediately on `visibilitychange` and window `focus`. Clears both snapshots on a `gatewayScope` change so a source switch can't show the previous backend's data.
- **Inputs / options:** `(gatewayState, requestGateway, gatewayScope)`.
- **Outputs / side effects:** `{statusSnapshot, inferenceStatus}`.
- **Config / env:** n/a
- **Edge cases / guards:** A `source === 'fallback'` readiness result is DISCARDED (both RPCs failed) so a gateway flap can't flash "Inference not ready" (comment :168-173).
- **Rebuild notes:** Distinguish "authoritatively not ready" from "couldn't ask".

---

## 3. Model menus and model overlays

### Model catalog menu  `id: desktop-a.model-catalog-menu`
- **Surface:** Desktop app
- **Where:** The dropdown behind the composer's model pill (and any plugin surface that picks a model). `app/shell/model-catalog-menu.tsx`.
- **What it does:** Searchable, provider-grouped model picker with `-fast` families collapsed into one row, a per-row hover submenu for thinking/effort/fast, MoA presets, and full keyboard selection.
- **How it works:** Fetches `modelOptionsQueryKey(profile, sessionId)` via `requestModelOptions({gateway, profile, request, sessionId})` — gateway-first even with no session, because a connected (possibly remote) gateway owns the catalog including virtual providers the local REST fallback cannot know about (#53817). `groupModels()` (model-catalog-menu.tsx:542-597) collapses `-fast` siblings and date-pinned snapshots (`collapseModelFamilies`, `store/model-visibility.ts:38-69`), applies the user's Edit-Models shortlist (or the first `DEFAULT_VISIBLE_PER_PROVIDER = 50` per provider when uncustomised), always pins the ACTIVE model into its provider's list when NOT searching, and sorts groups alphabetically by provider name. Keyboard selection is re-implemented on top of Radix (`kbRows`, :236-321): ArrowDown/ArrowUp step a flat list that mirrors exactly what is rendered, Enter commits, and the highlighted row carries `data-kb-active` plus `scrollIntoView({block:'nearest'})`. `usePointerQuiet()` makes rows `pointer-events-none` until the mouse actually moves, so hover cannot steal the keyboard cursor.
- **Inputs / options:**
  - **Search field** at the top — aria-label and placeholder both `"Search models"` (`i18n: shell.modelMenu.search`). ArrowDown/ArrowUp/Enter are claimed from Radix so DOM focus stays in the input.
  - **Provider heading rows** — click toggles collapse for that provider (`toggleCollapsedProvider(slug)`, `store/provider-collapse`); a `DisclosureCaret` fades in on hover. Collapse is ignored while searching.
  - **Model rows** — label is `modelDisplayParts(id).name`, followed by a muted meta string built from `"Fast"` (`i18n: shell.modelMenu.fast`) when fast is on plus the short reasoning label (`Off / Min / Low / Med / High / XHigh / Max / Ultra`, `lib/reasoning-effort.ts:19-28`). A `check` codicon marks the current model. Click (or Enter/Space) commits and closes; HOVER opens the edit submenu instead.
  - **MoA presets section** — separator, label `MoA presets` (literal, not localised), rows rendered as `MoA: <preset>`; selecting one commits provider `moa` and closes. Searchable as `"moa <preset>"`.
  - **Footer** — host-provided rows (the composer contributes **"Refresh models"**), then always **"Edit models…"** (`i18n: shell.modelMenu.editModels`, `settings-gear` codicon) which opens the model-visibility dialog.
  - Loading state: four skeleton rows. Error state: the error message as a disabled row. Empty: `"No models found"` (`i18n: shell.modelMenu.noModels`).
- **Outputs / side effects:** Calls `controller.select(model, provider)` then `controller.applyPreset({effort, fast}, {model, provider})`. Effort is only passed when `capabilities[model].reasoning !== false`; fast only when `capabilities[model].fast === true`. For variant-fast models (a `-fast` sibling, no speed param) a remembered `fast: true` preset selects the `-fast` id directly (`selectFamily`, :198-219).
- **Config / env:** Shortlist persists at `localStorage['hermes.desktop.visible-models']`; collapsed providers in `store/provider-collapse`; default effort from `$defaultReasoningEffort` falling back to `DEFAULT_REASONING_EFFORT = 'medium'`.
- **Edge cases / guards:** `isCurrentProvider()` (:47-49) also checks `provider.aliases`, because custom providers report `custom:<key>` while the row slug is the bare config key (#87035). Visibility is resolved against the fetched catalog so an empty provider list cannot read as "user hid everything" and blank the menu on first open. `ModelMenuCloseContext` (:55) lets the host hand the panel a dismiss function, so a row click closes but the hover submenu (whose items preventDefault) stays open.
- **Rebuild notes:** Collapse `-fast` siblings into one row with a toggle; keep search spanning ALL models regardless of the shortlist; drive keyboard selection off the rendered list, not the DOM.

### Model edit submenu (Options / Thinking / Fast / Effort)  `id: desktop-a.model-edit-submenu`
- **Surface:** Desktop app
- **Where:** Hover submenu on each model row (`app/shell/model-edit-submenu.tsx`), a `DropdownMenuSubContent` of `w-52 p-0` with `sideOffset={4}`.
- **What it does:** Edits one model's reasoning and speed settings without necessarily switching to it.
- **How it works:** The wrapper is hook-free and the body renders as a CHILD of `SubContent`, so Radix's Presence gate leaves it unrendered until the sub actually opens (comment :92-96) — eagerly building it per row made opening large catalogs lag. `effortValue = resolveReasoningEffort(effort, defaultEffort)`; `thinkingOn = isThinkingEnabled(effort, defaultEffort)` where the value `none` means off.
- **Inputs / options:**
  - Section label **"Options"** (`i18n: shell.modelOptions.options`).
  - **Thinking** switch (`i18n: shell.modelOptions.thinking`) — shown when `reasoning && canDisableReasoning !== false`. On writes `{effort: effortValue || defaultEffort}`; off writes `{effort: 'none'}`.
  - **Fast** switch (`i18n: shell.modelOptions.fast`) — shown when `fastControl.kind !== 'none'`.
  - Separator, section label **"Effort"** (`i18n: shell.modelOptions.effort`), then a radio group over `REASONING_EFFORTS = ['minimal','low','medium','high','xhigh','max','ultra']` labelled `"Minimal"`, `"Low"`, `"Medium"`, `"High"`, `"Extra High"`, `"Max"`, `"Ultra"` (`i18n: shell.modelOptions.minimal|low|medium|high|xhigh|max|ultra`). Every item preventDefaults so the menu stays open.
  - Empty state when neither fast nor reasoning applies: `"No options for this model"` (`i18n: shell.modelOptions.noOptions`).
- **Outputs / side effects:** Calls `onSetOptions({effort?, fast?})`. The submenu is PURE — it never writes to a session, a preset store, or the gateway (comment :80-83); that is the controller's job.
- **Config / env:** n/a
- **Edge cases / guards:** `resolveFastControl(model, providerModels, paramSupported, currentFastMode)` (:27-59) returns `{kind:'param'}` when the backend supports `speed=fast`; else `{kind:'variant', baseId, fastId}` when a `…-fast` sibling exists and there is a base to return to; else `{kind:'param', on:true}` when the session still carries the speed param from a previous model (so it can be turned off rather than stranded); else `{kind:'none'}`. For a variant control, flipping the switch on an INACTIVE row records the preference only — it does not swap models.
- **Rebuild notes:** Two independent "fast" mechanisms (request param vs sibling model id) behind one switch; keep the switch pure and let the owner decide what an edit means.

### Composer model menu panel (controller plus "Refresh models")  `id: desktop-a.model-menu-panel`
- **Surface:** Desktop app
- **Where:** `app/shell/model-menu-panel.tsx` — the composer pill's dropdown body.
- **What it does:** Binds the shared catalog to THIS surface's session: writes the pick through, remembers it as a global per-model preset, keeps optimistic stores honest, and rolls back a failed gateway write.
- **How it works:** Binds to `useSessionView()` so a tile's menu switches its own session (`view.$runtimeId / $fast / $model / $provider / $reasoningEffort`). `currentPickerSelection()` falls back to the catalog's reported current when the session store has no model yet. Controller methods (:186-236): `applyPreset` calls `setModelPreset` then `applyModelPreset` (one batched gateway write); `presetFor(provider, model)` returns `$modelPresets[modelPresetKey(provider, model)] ?? {}`; `select(model, provider)` calls `onSelectModel({model, provider, sessionId: activeSessionId || null})`; `setOptions(patch, row)` always records the GLOBAL preset keyed `provider::model` and only pushes to the session when `row.isActive`. `patchReasoning` writes `config.set { key: 'reasoning', session_id, value }` and rolls back both the store and the preset on failure, surfacing `"Model option update failed"` (`i18n: shell.modelOptions.updateFailed`). `patchFast` writes `config.set { key: 'fast', session_id, value: 'fast' | 'normal' }`, failing to `"Fast mode update failed"` (`i18n: shell.modelOptions.fastFailed`).
- **Inputs / options:** Footer row **"Refresh models"** (`i18n: shell.modelMenu.refreshModels`, `sync` codicon, spins while busy, preventDefaults so the menu stays open). It re-requests the catalog with `refresh: true`, which busts the backend's 1h provider-model disk cache and re-pulls each provider's live list; if the returned catalog no longer contains the current model, `reconcileSelectionAfterCatalogRefresh` picks a replacement and switches to it.
- **Outputs / side effects:** Gateway `config.set` writes; `queryClient.setQueryData` on the model-options key; on a network failure a plain `invalidateQueries({queryKey: ['model-options']})`.
- **Config / env:** `includeMoa` is TRUE here (MoA presets are selectable from the composer) and false on override surfaces.
- **Edge cases / guards:** With no session, a preset-only edit does NOT reach `config.set` — the gateway would fall back to global config (comment :135-137).
- **Rebuild notes:** Keep the renderer shared and the meaning pluggable; always stamp the target session id so a tile switch cannot hit the busy primary.

### Edit models dialog (model visibility overlay)  `id: desktop-a.model-visibility-overlay`
- **Surface:** Desktop app
- **Where:** Opened by the catalog footer row **"Edit models…"**. Mounted app-wide by `app/model-visibility-overlay.tsx`.
- **What it does:** Curates which models each provider shows in every model picker.
- **How it works:** `ModelVisibilityOverlay` subscribes to `$modelVisibilityOpen` and renders `<ModelVisibilityDialog gw onOpenChange={setModelVisibilityOpen} onOpenProviders open profile sessionId={$activeSessionId}/>`. Returns `null` unless `$gatewayState === 'open'`.
- **Inputs / options:** `onOpenProviders` — a jump to the provider settings page. The dialog's own rows belong to the settings shard.
- **Outputs / side effects:** Writes the shortlist to `localStorage['hermes.desktop.visible-models']` as a set of `provider::model` keys; hiding a provider's last model stores the sentinel `provider::` so "hid everything" stays distinguishable from "never customised" (`store/model-visibility.ts:16-26`).
- **Config / env:** `DEFAULT_VISIBLE_PER_PROVIDER = 50`.
- **Edge cases / guards:** The shortlist is ONE global preference read directly by the catalog menu rather than passed in, so every surface agrees on what "my models" means (comment model-catalog-menu.tsx:137-140).
- **Rebuild notes:** n/a

### Model picker dialog overlay (fallback picker)  `id: desktop-a.model-picker-overlay`
- **Surface:** Desktop app
- **Where:** `app/model-picker-overlay.tsx`, mounted app-wide; opened by the model-picker keybind when no live composer dropdown can be toggled, or by `setModelPickerOpen(true)`.
- **What it does:** Full-dialog model picker for when no chat surface is on screen.
- **How it works:** Reads `$modelPickerOpen`, `$activeSessionId`, `$currentModel`, `$currentProvider` plus the focused tile's `$focusedRuntimeId` / model / provider — the latter selected as SCALARS via `useStoreSelector`, because `$focusedSessionState` republishes on every message delta and a whole-object subscription re-rendered this app-wide overlay per token (#72163). Prefers the focused tile's runtime when the overlay opens from a tile that lacked a live menu. Renders `<ModelPickerDialog .../>` and calls `onSelect({...selection, sessionId})`.
- **Inputs / options:** Keybind `composer.modelPicker`, default `mod+shift+m`; the handler (`app/hooks/use-keybinds.ts:197-202`) first tries `requestModelMenuToggle()` (the pill under the pointer, else the active composer) and only falls back to this dialog.
- **Outputs / side effects:** Model switch on the resolved session.
- **Config / env:** n/a
- **Edge cases / guards:** Returns `null` while the gateway is not open.
- **Rebuild notes:** n/a

---

## 4. Command palette (Cmd/Ctrl+K)

### Command palette  `id: desktop-a.command-palette`
- **Surface:** Desktop app
- **Where:** Centred floating HUD pinned just under the titlebar; opened with `mod+k` or `mod+p` (`nav.commandPalette`), by the search affordances, or programmatically. Screen-reader title `"Command palette"` (`i18n: commandCenter.paletteTitle`). Placeholder `"Search sessions, views, and actions"` (`i18n: commandCenter.searchPlaceholder`).
- **What it does:** One searchable list of everywhere you can go and everything you can do — navigation, projects, contributed commands, Command Center sections, appearance, settings, and (once you type) sessions, settings fields, credentials, MCP servers, archived chats and git worktrees.
- **How it works:** `app/command-palette/index.tsx`. Two components: the always-mounted `CommandPalette` (:275-317) costs exactly one store subscription while closed, and `CommandPaletteBody` (:319 onward) holds every expensive hook — a dozen store subscriptions, three server queries, and the group builders that assemble a few hundred rows. The body is keyed by an `openCount` so search/sub-page state resets per open; it unmounts on the content's real `animationend` (`onExited`) with an `EXIT_FALLBACK_MS = 1000` backstop for environments where animations never run (jsdom, `animation: none`). Surface: `HUD_POSITION` plus `HUD_SURFACE` from `app/floating-hud.ts`, `w-[min(34rem,calc(100vw-2rem))]`, list capped at `max-h-[min(20rem,56vh)]`, transparent overlay (keeps click-away and the focus trap, but no dim or blur). Rows render through `PaletteGroups` (memo plus `useDeferredValue`) so opening paints the frame and input first and the row list arrives in an interruptible follow-up render.
- **Inputs / options:** Type to filter; ArrowUp/ArrowDown move; Enter runs; Escape closes (or steps back out of a sub-page); Backspace on an empty input inside a sub-page steps back; `mod+Enter` or mod-click selects the modifier variant; `shift+mod` opens a session in its own window. A "Back / <page title>" button appears above the input on sub-pages (`i18n: commandCenter.back` = `"Back"`).
- **Outputs / side effects:** Navigation, store writes, gateway calls — whatever the selected row does. Closing calls `releaseTypingFocus()` so the keyboard returns to the composer (`store/command-palette.ts:34-47`).
- **Config / env:** n/a
- **Edge cases / guards:** On the Settings overlay, the palette chord opens directly on the scoped `settings` page instead of the root list (`use-keybinds.ts:203-212`). A theme preview started by highlighting a theme row is cleared at close START, not at unmount, because the body stays mounted through the exit animation (:1479-1489).
- **Rebuild notes:** Split the closed cost from the open cost; defer the row list; retire the body on the real animation end so CSS owns the close duration.

### Palette ranking algorithm  `id: desktop-a.palette-ranking`
- **Surface:** Desktop app (Core)
- **Where:** `app/command-palette/index.tsx:174-237`, used with cmdk's `shouldFilter={false}`.
- **What it does:** Scores, sorts and prunes rows in React so the best match is first (and therefore auto-highlighted).
- **How it works:** `scoreItem(item, needle)` uses AND semantics — every whitespace-separated term must appear in the label or the keywords, else the score is `0`. Grades: exact label match `1`; label startsWith needle `0.9`; needle is a whole word of the label `0.85`; a label word starts with the needle `0.8`; label contains needle `0.7`; every term appears somewhere in the label `0.6`; matched only via keywords `0.4`. `rankGroups()` orders items within each group by score, orders groups by their best item, drops zero-score groups, and relies on a stable sort so curated order breaks ties. cmdk selection values are built by `paletteValue(item)` as the label, a `U+0001` separator, then the item id — labels alone can repeat (a settings field and a session can share a title). Matched terms are emphasised by `<HighlightMatches query={search.split(/\s+/)} .../>` using the same per-term split as the matcher.
- **Inputs / options:** the search string.
- **Outputs / side effects:** An ordered `PaletteGroup[]`.
- **Config / env:** n/a
- **Edge cases / guards:** cmdk's own group re-sorting silently no-ops (its `sort()` queries groups by an internal id that never matches the heading text it writes into `data-value`), which is why ranking happens in React (comment :164-171). The empty state `"No matching results found."` (`i18n: commandCenter.noResults`) is suppressed while the deferred list is still catching up, so opening never flashes it.
- **Rebuild notes:** Reward label matches over keyword-only matches; keep group declaration order as the tiebreaker and treat that order as priority.

### Palette group — "Go to"  `id: desktop-a.palette-group-goto`
- **Surface:** Desktop app
- **Where:** First group in the root list. Heading `"Go to"` (`i18n: commandCenter.goTo`).
- **What it does:** Jumps to the app's top-level destinations.
- **How it works:** index.tsx:756-826. Every row uses `navigateToWorkspacePage(navigate, path)`, which also FRONTS the workspace pane when the target renders inside it.
- **Inputs / options:** Exactly these rows, in order:
  1. `nav-new` — **"New session"** (`i18n: commandCenter.nav.newChat.title`), `Plus` icon, action `session.new` (`mod+n`), keywords `chat, create`, target `/`.
  2. `nav-new-window` — **"New window"** (`i18n: keybinds.actions['session.newWindow']`), `AppWindow` icon, action `session.newWindow` (`mod+shift+n`), keywords `window, instance, open, new`, runs `openNewWindow()`. Present only when `canOpenNewWindow()`.
  3. `nav-settings` — **"Settings"** (`i18n: commandCenter.nav.settings.title`), `Settings` icon, action `nav.settings` (`mod+,`), target `/settings`.
  4. `nav-skills` — **"Capabilities"** (`i18n: commandCenter.nav.skills.title`), `Wrench` icon, action `nav.skills`, keywords `skills, tools, toolsets, mcp, capabilities`, target `/skills`.
  5. `nav-messaging` — **"Messaging"** (`i18n: commandCenter.nav.messaging.title`), `MessageCircle` icon, action `nav.messaging`, target `/messaging`.
  6. `nav-artifacts` — **"Artifacts"** (`i18n: commandCenter.nav.artifacts.title`), `Package` icon, action `nav.artifacts`, target `/artifacts`.
  7. `nav-cron` — **"Cron"** (`i18n: shell.statusbar.cron`), `Clock` icon, action `nav.cron`, keywords `schedule, jobs`, target `/cron`.
  8. `nav-profiles` — **"Profiles"** (`i18n: profiles.title`), `Users` icon, action `nav.profiles`, target `/profiles`.
  9. `nav-agents` — **"Agents"** (`i18n: agents.title`), `Cpu` icon, action `nav.agents`, target `/agents`.
  10. `nav-starmap` — **"Memory Graph"** (`i18n: starmap.title`), `Starmap` icon, keywords `star map, memory, memories, skills, graph, learning, constellation`, target `/starmap`.
- **Outputs / side effects:** Route change plus a workspace-pane reveal for in-pane pages.
- **Config / env:** n/a
- **Edge cases / guards:** Rows with an `action` render that action's LIVE combo as a right-aligned hint via `bindingsFor()`, which resolves plugin actions registered after `$bindings` was seeded.
- **Rebuild notes:** n/a

### Palette group — "Projects"  `id: desktop-a.palette-group-projects`
- **Surface:** Desktop app
- **Where:** Second group. Heading `"Projects"` (`i18n: commandCenter.projects`).
- **What it does:** Switches the project scope, or starts a new session at a project root; plus the folder-open action.
- **How it works:** index.tsx:719-748. The first row is pinned: `project-open-folder` — **"Open folder as project…"** (`i18n: commandCenter.openFolder`), codicon `folder-opened`, action `workspace.openFolder` (`mod+o`), keywords `open, folder, directory, project, add, import, workspace`, runs `openFolderAsProject()` (native picker plus upsert). Then one row per visible project from `filterVisibleProjects($projectTree, $dismissedAutoProjectIds)`, each carrying the project's own codicon (`project.icon`, else `home` for the "no project" entry, else `folder-library`) and keywords `project, workspace, go to, <label>, <path>`.
- **Inputs / options:** Plain select is a pure scope switch (`goToProject(id, {newSession: false})`). `mod+Enter` or mod-click ALSO starts a new session at the project root (`newSession: true`), advertised by `comboHint: 'mod+enter'` and by the label swapping to **"New session in <project>"** (`i18n: commandCenter.newSessionInProject`) while the modifier is held.
- **Outputs / side effects:** The sidebar enters the project; optionally a new session is created there.
- **Config / env:** n/a
- **Edge cases / guards:** The plain path never spends the main pane.
- **Rebuild notes:** n/a

### Palette group — "Commands" (contributed rows)  `id: desktop-a.palette-group-commands`
- **Surface:** Desktop app (extension API)
- **Where:** Third group when non-empty. Heading `"Commands"` (`i18n: commandCenter.commands`).
- **What it does:** Surfaces rows contributed by core features and plugins into the `palette` registry area.
- **How it works:** `app/command-palette/contrib.ts`. `PALETTE_AREA = 'palette'`; a contribution is `{id, label, action?, icon?, keywords?, run, detail?: () => string, detailVariant?: 'muted' | 'state', keepOpen?}`. `usePaletteContributions()` prefixes render keys with `${source ?? 'core'}:` and drops entries without a label or a `run`. `detail()` is a FUNCTION because contributions register once at boot while the state they report keeps moving; the palette re-reads it on open and after every `keepOpen` select (through the `selectTick` counter, index.tsx:1002-1013).
- **Inputs / options:** The helper `paletteToggle({id, label, action?, icon?, keywords?, get, set})` (contrib.ts:44-71) builds a binary-setting row: `detail: () => get() ? 'on' : 'off'`, `detailVariant: 'state'`, `keepOpen: true`, keywords extended with `on, off, enable, disable`, and `run: () => set(!get())`.
- **Outputs / side effects:** Whatever `run` does; the note updates in place as the receipt.
- **Config / env:** n/a
- **Edge cases / guards:** The group is omitted entirely while nothing contributes. A `state` note renders underlined (not muted) and skips truncation (`HUD_NOTE_VARIANT`, `app/floating-hud.ts:338-341`).
- **Rebuild notes:** A toggle row should say the verb in the label and the current state in the note — neither alone is actionable.

### Palette group — "Command Center"  `id: desktop-a.palette-group-command-center`
- **Surface:** Desktop app
- **Where:** Heading `"Command Center"` (`i18n: commandCenter.commandCenter`).
- **What it does:** Jumps into Command Center sections and runs the system-level actions.
- **How it works:** index.tsx:869-944.
- **Inputs / options:** Exactly these rows:
  1. `cc-sessions` — **"Sessions"** (`i18n: commandCenter.sections.sessions`), `Archive` icon, keywords `command center, sessions, pin`, target `/command-center?section=sessions`.
  2. `cc-system` — **"System"** (`i18n: commandCenter.sections.system`), `Activity` icon, keywords `command center, system, status, logs`, target `/command-center?section=system`.
  3. `cc-usage` — **"Usage"** (`i18n: commandCenter.sections.usage`), `BarChart3` icon, keywords `command center, usage, tokens, cost`, target `/command-center?section=usage`.
  4. `cc-restart-gateway` — **"Restart gateway"** (`i18n: commandCenter.restartGateway`), `RefreshCw` icon, keywords `gateway, restart, messaging, reconnect, system`, runs `runGatewayRestart()`.
  5. `cc-update-hermes` — **"Update Hermes"** (`i18n: commandCenter.updateHermes`), `Download` icon, keywords `update, upgrade, hermes, version, system, restart`, `detail` is the same version label the statusbar shows (`resolveVersionStatus(...).label`, backend target when `connection.mode === 'remote'`), runs `requestActiveUpdate()`.
  6. `cc-reload-window` — **"Reload window"** (`i18n: commandCenter.reloadWindow`), `RefreshCw` icon, keywords `reload, window, refresh, restart, ui, stuck`, runs `window.location.reload()`.
  7. `cc-open-browser` — **"Open browser"** (`i18n: commandCenter.openBrowser`), codicon `globe`, action `view.showBrowser` (`mod+shift+l`), keywords `browser, web, url, address, open, navigate, internet, site`, runs `openBrowserTab()`.
- **Outputs / side effects:** Route changes, gateway restart, update dispatch, full renderer reload, a new in-app browser tab.
- **Config / env:** n/a
- **Edge cases / guards:** The update row's detail is reduced to a STRING before it enters the memo, so an in-flight apply (which rewrites the update stores on every progress line) only rebuilds the groups when the visible text changes (comment :356-359).
- **Rebuild notes:** n/a

### Palette group — "Appearance"  `id: desktop-a.palette-group-appearance`
- **Surface:** Desktop app
- **Where:** Heading `"Appearance"` (`i18n: commandCenter.appearance`). Declared BEFORE Settings on purpose so theme/colour queries rank above a fuzzy settings match.
- **What it does:** Entry points to the theme picker, colour-mode picker, pets gallery and pet generator.
- **How it works:** index.tsx:945-981.
- **Inputs / options:**
  1. `appearance-theme` — **"Change theme"** (`i18n: commandCenter.changeTheme`), `Palette` icon, keywords `theme, appearance, color, palette, skin, dark, light, look`, opens nested page `theme`.
  2. `appearance-mode` — **"Change color mode…"** (`i18n: commandCenter.changeColorMode`), `Sun` icon, keywords `appearance, color mode, brightness, dark, light, system`, opens nested page `color-mode`.
  3. `appearance-pets` — **"Pets"** (`i18n: commandCenter.pets.title`), `PawPrint` icon, keywords `pet, petdex, mascot, pets, /pet, paw`, opens nested page `pets`.
  4. `appearance-generate-pet` — **"Generate a pet"** (`i18n: commandCenter.generatePet.title`), `Egg` icon, keywords `pet, generate, create, make, new pet, mascot, hatch, ai`, runs `openPetGenerate()`.
- **Outputs / side effects:** Sub-page navigation, or opening the pet-generation flow.
- **Config / env:** n/a
- **Edge cases / guards:** Rows with a `to` show a trailing `ChevronRight`.
- **Rebuild notes:** n/a

### Palette group — "Settings"  `id: desktop-a.palette-group-settings`
- **Surface:** Desktop app
- **Where:** Last group of the root list. Heading `"Settings"` (`i18n: commandCenter.settings`).
- **What it does:** Deep-links to every settings section and to the non-config settings tabs.
- **How it works:** index.tsx:982-1001. Config sections come from `app/settings/constants` `SECTIONS`, labelled `t.settings.sections[section.id] ?? section.label`, each linking to `/settings?tab=config:<id>`. Then the eight hardcoded `NON_CONFIG_SETTINGS` entries (index.tsx:407-459).
- **Inputs / options:** The non-config rows, in declaration order, with their tab targets and keywords:
  1. `Zap` icon, label `t.settings.nav.providerAccounts`, tab `providers&pview=accounts`, keywords `accounts, sign in, oauth, login, subscription, models, anthropic, openai`.
  2. `KeyRound`, label `t.settings.nav.providerApiKeys`, tab `providers&pview=keys`, keywords `providers, api key, keys, secrets, tokens, egress, iron proxy, sandbox proxy`.
  3. `Globe`, label `t.settings.nav.gateway`, tab `gateway`, keywords `connection, connections, messaging, remote, multi, instances, ssh, cloud, add gateway, registry`.
  4. `KeyRound`, label `t.settings.nav.keysTools`, tab `keys&kview=tools`, keywords `api, secrets, tokens, credentials, browser, search`.
  5. `Settings2`, label `t.settings.nav.keysSettings`, tab `keys&kview=settings`, keywords `gateway, proxy, server, webhook, env, egress proxy, iron proxy`.
  6. `Package`, label `t.settings.nav.plugins`, tab `plugins`, keywords `plugins, extensions, desktop plugins, addon, add-on`.
  7. `Archive`, label `t.settings.nav.archivedChats`, tab `sessions`, keywords `history, archived`.
  8. `Info`, label `t.settings.nav.about`, tab `about`, keywords `version, about`.
- **Outputs / side effects:** Route change to `/settings?tab=…`.
- **Config / env:** n/a
- **Edge cases / guards:** Every row's keywords also include the literal `settings`.
- **Rebuild notes:** n/a

### Palette type-to-search groups  `id: desktop-a.palette-search-groups`
- **Surface:** Desktop app
- **Where:** Appended below the fixed groups, only while the search box is non-empty.
- **What it does:** Surfaces the long, granular lists that would otherwise bury navigation on an empty palette.
- **How it works:** index.tsx:1032-1263 (`searchGroups`). Group order is exactly:
  1. **Capabilities deep-links** — heading is `t.commandCenter.nav.skills.title` (`"Capabilities"`). Rows: `cap-skills` labelled `"Capabilities: <skills tab>"` (`i18n: skills.tabSkills`) to `/skills?tab=skills`; `cap-toolsets` labelled `"Capabilities: <toolsets tab>"` (`i18n: skills.tabToolsets`) to `/skills?tab=toolsets`; `cap-mcp` labelled `"Capabilities: <mcp tab>"` (`i18n: skills.tabMcp`) to `/skills?tab=mcp`. Icons `Wrench`, `SlidersHorizontal`, `Layers3`.
  2. **Themes** — heading `i18n: settings.appearance.themeTitle`. One row per `availableThemes` entry, `keepOpen: true`, a check on the current theme, `onHighlight` live-previews it, `run` commits with `setTheme` and flips the colour mode when the theme can only render the other side.
  3. **Colour modes** — heading `i18n: settings.appearance.colorMode`. Three rows (light / dark / system), labelled from `i18n: settings.modeOptions.<mode>.label`, `keepOpen`, with live preview on highlight.
  4. **Sessions** — heading `i18n: commandCenter.sections.sessions` (`"Sessions"`). Up to 200 recent non-archived sessions (`listAllProfileSessions(200, 1, 'exclude')`); keywords include the preview text and the git branch.
  5. **Settings fields** — heading `"Settings fields"` (`i18n: commandCenter.settingsFields`). The DEEP catalog from `useSettingsSearchCatalog(true)`: `appearanceEntries` plus `configEntries`, each row showing `entry.context` as its note and navigating to `/settings?${settingsSearchTargetQuery(entry.target)}`.
  6. **Plugins** — heading `i18n: settings.nav.plugins`; `settingsCatalog.pluginEntries`.
  7. **API keys** — heading `i18n: settings.nav.apiKeys`; `settingsCatalog.credentialEntries`.
  8. **MCP servers** — heading `"MCP servers"` (`i18n: commandCenter.mcpServers`). One row per key of `getServers(config)`, sorted; navigates to `/skills?tab=mcp&server=<name>`.
  9. **Archived chats** — heading `"Archived chats"` (`i18n: commandCenter.archivedChats`). `listAllProfileSessions(200, 0, 'only')`; navigates to `/settings?tab=sessions&session=<id>`.
- **Inputs / options:** typing.
- **Outputs / side effects:** Theme and mode rows apply live; the rest navigate.
- **Config / env:** Config/session/archived data is fetched per open through react-query keys `['command-palette','config']`, `['command-palette','sessions']`, `['command-palette','archived']`.
- **Edge cases / guards:** `getServers()` is the shared choke point that also drops malformed (null/scalar) entries, so the palette never lists a server the MCP tab dropped.
- **Rebuild notes:** Gate the huge lists behind a query so an empty palette stays a navigation surface.

### Palette — jump to a pasted session id  `id: desktop-a.palette-direct-session-id`
- **Surface:** Desktop app
- **Where:** A heading-less row pinned at the top of the search results when the query is exactly a Hermes session id.
- **What it does:** Opens a session by id even when it predates the recent-200 window.
- **How it works:** index.tsx:298 defines `SESSION_ID_RE = /^\d{8}_\d{6}_[a-f0-9]{6}$/` (that is `YYYYMMDD_HHMMSS_<6 hex>`); the row id is `goto-<id>`, label `"Go to session <id>"` (`i18n: commandCenter.goToSession` plus the id), `MessageCircle` icon, `runWithEvent: goSession(id)`.
- **Inputs / options:** Plain select opens beside what is already loaded; `mod` select (or `mod+Enter`) forces a new tab; `shift+mod` pops its own window (`openSessionIntentFromModifiers(event, 'stack')`).
- **Outputs / side effects:** The session opens.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Palette — open a pasted folder path  `id: desktop-a.palette-direct-folder-path`
- **Surface:** Desktop app
- **Where:** A heading-less row when the query looks like an absolute path.
- **What it does:** Opens that folder as a project without going through the native picker.
- **How it works:** index.tsx:302 defines `FOLDER_PATH_RE = /^(\/|[A-Za-z]:[\/\\]).+/`. Row id `open-folder-<path>`, codicon `folder-opened`, label `"Open folder as project — <path>"` (`i18n: commandCenter.openFolderAt`), runs `openFolderAsProject(path)`.
- **Inputs / options:** Enter.
- **Outputs / side effects:** Project upsert plus a fresh session anchored there.
- **Config / env:** n/a
- **Edge cases / guards:** Deliberately does NOT match a tilde home path: the upsert's membership check (`projectIdForCwd`) compares literal strings against the tree's absolute paths, so an unexpanded home path would always miss and double-create (comment :299-302).
- **Rebuild notes:** n/a

### Palette group — "Branches" (git worktrees)  `id: desktop-a.palette-branch-group`
- **Surface:** Desktop app
- **Where:** Last group of all. Heading `"Branches"` (`i18n: commandCenter.branches`).
- **What it does:** Starts a fresh conversation anchored to one of the active repo's worktrees.
- **How it works:** index.tsx:658-681. One row per `$repoWorktrees` entry, id `worktree-<path>`, `GitBranch` icon, label **"New conversation in <branch>"** (`i18n: commandCenter.startInBranch`), keywords `branch, worktree, switch, <name>, <path>`, `run: () => requestStartWorkSession(wt.path)`. The branch name falls back to the last path segment when the worktree has no branch.
- **Outputs / side effects:** A new session whose cwd is that checkout, so git is the source of truth and edits land in the right tree.
- **Config / env:** n/a
- **Edge cases / guards:** Ranked BELOW both the fixed groups and the typed-only lists, because worktrees scale with whatever happens to exist and are the least likely thing meant on a tie (comment :1265-1268).
- **Rebuild notes:** n/a

### Palette sub-page — Change theme  `id: desktop-a.palette-page-theme`
- **Surface:** Desktop app
- **Where:** Nested page `theme`. Title from `i18n: settings.appearance.themeTitle`; placeholder from `i18n: settings.appearance.themeDesc`.
- **What it does:** Picks a colour theme with live preview, and offers a way to install more.
- **How it works:** index.tsx:1337-1403. Three groups: (a) a heading-less pinned row **"Install theme…"** (`i18n: commandCenter.installTheme.title`, `Download` icon, keywords `install, marketplace, vscode, vs code, download, new, color`) drilling into the `install-theme` page; (b) the colour-mode group (light/dark/system) so one brightness switch covers the whole list instead of splitting every theme across Light and Dark groups; (c) every available theme once. Each theme row is `keepOpen`, carries an `active` check, previews on highlight via `previewTheme(name, previewMode)`, and on run calls `setTheme(name)` plus `setMode(previewMode)` when `previewMode !== resolvedMode`.
- **Inputs / options:** Type to filter; arrows preview; Enter commits; Escape or empty-Backspace returns to the root list.
- **Outputs / side effects:** Theme and mode commit.
- **Config / env:** n/a
- **Edge cases / guards:** `themeSupportsMode(name, target)` (index.tsx:468-484) returns true for built-ins (the engine synthesises the missing side); for imported VS Code themes it decides by `luminance(background) <= 0.5` for dark and `> 0.5` for light, so a dark-only import flips the app to dark rather than rendering wrong.
- **Rebuild notes:** n/a

### Palette sub-page — Change color mode  `id: desktop-a.palette-page-color-mode`
- **Surface:** Desktop app
- **Where:** Nested page `color-mode`. Title from `i18n: settings.appearance.colorMode`; placeholder from `i18n: settings.appearance.colorModeDesc`.
- **What it does:** Switches between light, dark and system.
- **How it works:** index.tsx:1404-1428. Three rows from `THEME_MODES = [{icon: Sun, mode: 'light'}, {icon: Moon, mode: 'dark'}, {icon: Monitor, mode: 'system'}]` (index.tsx:461-465), labelled from `i18n: settings.modeOptions.<mode>.label`, `keepOpen`, with an `active` check on the current mode. `onHighlight` previews `previewTheme(themeName, resolveThemeMode(mode))`, where `system` is resolved through `useMediaQuery('(prefers-color-scheme: dark)')` because `previewTheme` paints a concrete light or dark.
- **Inputs / options:** arrows preview, Enter commits.
- **Outputs / side effects:** `setMode(mode)`.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Palette sub-page — Pets (petdex gallery)  `id: desktop-a.palette-page-pets`
- **Surface:** Desktop app
- **Where:** Nested page `pets`. Title `"Pets"` (`i18n: commandCenter.pets.title`); placeholder `"Search pets…"` (`i18n: commandCenter.pets.placeholder`). Rendered by `app/command-palette/pet-palette-page.tsx`.
- **What it does:** Browses the petdex gallery, adopts or switches the active pet, and toggles pets on and off.
- **How it works:** Subscribes to `$petGallery`, `$petGalleryStatus`, `$petGalleryError`, `$petBusy` (`store/pet-gallery`) and loads via `loadPetGallery(requestGateway)` on mount. Rows come from `rankedGalleryPets(gallery, search).slice(0, 50)`; each shows a `PetThumb` (32px, fetched through `loadPetThumb`), the display name, a `"Generated"` chip (`i18n: commandCenter.pets.generatedTag`) for generated pets, the slug plus `" · Installed"` (`i18n: commandCenter.pets.installed`), and a check when active. Clicking calls `adoptPet(requestGateway, slug, ...)` then `triggerHaptic('crisp')` on success.
- **Inputs / options:**
  - Header action row **"Generate a pet"** (`i18n: commandCenter.generatePet.title`, `Egg` glyph) — closes the palette and opens the pet generator.
  - Per-pet row click adopts or switches.
  - **Inline on/off toggle** rendered in the search row's `right` slot (`PetInlineToggle`): a paw button with `aria-pressed`, aria-label and tooltip `"Turn off"` / `"Turn on"` (`i18n: commandCenter.pets.turnOff` / `turnOn`), calling `setPetEnabled(requestGateway, !enabled, {...})`.
- **Outputs / side effects:** Gateway mutations; the desktop's floating pet appears or changes.
- **Config / env:** n/a
- **Edge cases / guards:** States: `"Loading petdex gallery…"` (`i18n: commandCenter.pets.loading`), `"Restart Hermes to use pets — the backend predates this feature."` (`i18n: commandCenter.pets.staleBackend`, error tone), `"No matching pets."` (`i18n: commandCenter.pets.empty`), `"Could not reach the petdex gallery."` (`i18n: commandCenter.pets.error`), `"Could not adopt that pet."` (`i18n: commandCenter.pets.adoptFailed`), `"Could not turn the pet on."` / `"Could not turn the pet off."` (`i18n: commandCenter.pets.toggleFailed`), `"No pets available — pick one below to install."` (`i18n: commandCenter.pets.noneAvailable`). Every row calls `preventDefault` on mousedown so focus stays in the search input, and all rows except the busy one are disabled while a mutation runs.
- **Rebuild notes:** Keep fetching, caching and the thumb cache in a store so reopening the page is instant and a toggle never re-pulls the gallery.

### Palette sub-page — Install theme (VS Code Marketplace)  `id: desktop-a.palette-page-install-theme`
- **Surface:** Desktop app
- **Where:** Nested page `install-theme`; its parent is `theme` (`PAGE_PARENTS = {'install-theme': 'theme'}`, index.tsx:242). Title `"Install theme"` (`i18n: commandCenter.installTheme.pageTitle`); placeholder `"Search the VS Code Marketplace..."` (`i18n: commandCenter.installTheme.placeholder`). Rendered by `marketplace-theme-page.tsx`.
- **What it does:** Browses and installs colour themes from the VS Code Marketplace, then activates the installed one.
- **How it works:** `useDebounced(search.trim(), 300)` feeds `window.hermesDesktop.themes.searchMarketplace(q)` through react-query (`staleTime: 5 * 60 * 1000`, key `['marketplace-themes', q]`); an empty query returns the most-installed themes. Each row shows a `Palette` glyph, the `displayName`, then the `publisher` plus `" · N installs"` (`i18n: commandCenter.installTheme.installs`, formatted with `Intl.NumberFormat(undefined, {notation:'compact', maximumFractionDigits:1})`). Selecting a row that is already owned (`$marketplaceInstalls.get(extensionId)`) just re-activates it; otherwise `installVscodeThemeFromMarketplace(extensionId)` downloads, converts and installs it through the same pipeline as the settings importer, then activates it. Haptic `crisp` on success.
- **Inputs / options:** Type to search; click or Enter a row to install or activate. Trailing state per row: `"Install"` / `"Installing..."` / `"Installed"` (`i18n: commandCenter.installTheme.install|installing|installed`) with `Download`, a spinning `Loader2`, and a green `Check` glyph respectively.
- **Outputs / side effects:** A new user theme is registered and applied; the palette stays open so several can be grabbed in one pass.
- **Config / env:** n/a
- **Edge cases / guards:** `"Searching the Marketplace..."` (`i18n: commandCenter.installTheme.loading`), `"Could not reach the Marketplace."` (`i18n: commandCenter.installTheme.error`, error tone), `"No matching themes."` (`i18n: commandCenter.installTheme.empty`). While one install runs every other row is disabled; failures render inline in `--ui-red`.
- **Rebuild notes:** n/a

### Palette sub-page — Settings search  `id: desktop-a.palette-page-settings`
- **Surface:** Desktop app
- **Where:** Nested page `settings`; opened by the palette chord while the Settings overlay is up, or by the Settings search pill beside its close button. Title from `t.commandCenter.nav.settings.title` (`"Settings"`); placeholder from `i18n: settings.search.placeholder`.
- **What it does:** The same catalog as root, scoped to settings only.
- **How it works:** index.tsx:1288-1336 (`settingsPageGroups`). Always lists the `Settings` group (config sections plus the eight non-config tabs), with row ids prefixed `sp-`. On typing it appends `Settings fields`, then `Plugins`, then `API keys` — the same catalog entries the root search uses, so the two can never drift.
- **Inputs / options:** typing; Escape or empty-Backspace exits to the root list.
- **Outputs / side effects:** Navigation into `/settings?...`.
- **Config / env:** n/a
- **Edge cases / guards:** `openCommandPalettePage('settings')` is only used when the palette is CLOSED and the current view is `settings`; a second press of the chord still closes it (`use-keybinds.ts:203-212`).
- **Rebuild notes:** n/a

### Palette modifier preview and session-open contract  `id: desktop-a.palette-modifier-preview`
- **Surface:** Desktop app
- **Where:** Every palette row that carries `modLabel` or `runWithEvent`.
- **What it does:** Shows what the modifier variant will do before you press it, and routes session opens the same way the sidebar does.
- **How it works:** `modHeld` state (index.tsx:600-620) tracks the modifier with capture-phase window `keydown` and `keyup` listeners plus a `blur` clear (focus lives in the search input, so window-level listeners are required). While held, a row with a `modLabel` swaps its label to the variant copy in muted text. cmdk's `onSelect` does not forward the triggering event, so `lastSelectMods` (a ref) is captured from each row's `onMouseDown` and from the input's `onKeyDown` (index.tsx:582-597, 1546-1550) and handed to `runWithEvent`. `goSession()` (:697-702) calls `openSession(id, navigate, openSessionIntentFromModifiers(event, 'stack'))`: plain opens beside what is already loaded (focus an existing tile or main, else a new tab; main only when it is a blank draft), the modifier forces a new tab, and shift plus modifier gives it its own window.
- **Inputs / options:** `mod`, `shift+mod`, plain Enter, mouse click with modifiers.
- **Outputs / side effects:** Stashed modifiers are cleared after each select so a plain Enter after a mod-click is not sticky (:1497-1499).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Palette back navigation and highlight watcher  `id: desktop-a.palette-back-nav`
- **Surface:** Desktop app
- **Where:** The "Back / <page>" bar above the input on any sub-page.
- **What it does:** Steps up one nesting level instead of closing the palette, and reports the highlighted row so preview-capable rows can paint live.
- **How it works:** `goBack()` (:706-709) clears the search and sets `page => PAGE_PARENTS[page] ?? null`. Escape and empty-input Backspace inside a sub-page both preventDefault, stopPropagation and call it (:1552-1565). Focus is re-grabbed on every page change (:663-666) so "just start typing" works after drilling in or stepping back — Radix only autofocuses on mount, and the back-button click moves focus to the button. `HighlightWatcher` (`highlight-watcher.tsx`) subscribes to cmdk's store via `useCommandState(state => state.value)` — the root `onValueChange` only fires in controlled mode, which this palette is not — and reports each change; `handleHighlight` (:1451-1461) runs the row's `onHighlight` or otherwise clears the theme preview.
- **Inputs / options:** Click "Back", press Escape, or press Backspace on an empty query.
- **Outputs / side effects:** Page and search state; preview clear.
- **Config / env:** n/a
- **Edge cases / guards:** The preview is also cleared on page change, at close start, and on unmount (three separate effects).
- **Rebuild notes:** n/a

### Floating HUD chrome (shared palette / switcher surface)  `id: desktop-a.floating-hud-chrome`
- **Surface:** Desktop app (Core)
- **Where:** `app/floating-hud.ts` — shared by the command palette and the session switcher.
- **What it does:** Defines the look and position of the top-centre floating HUDs.
- **How it works:** `HUD_POSITION = 'fixed left-1/2 top-3 -translate-x-1/2 max-[44rem]:top-[calc(var(--titlebar-height,34px)+0.375rem)]'` — below about 44rem the whole surface drops beneath the titlebar band so the search row always clears the macOS traffic lights (these HUDs portal to `<body>`, outside the app-shell subtree that defines `--titlebar-height`, hence the fallback value). `HUD_SURFACE` adds the hairline `--stroke-nous` border, `--ui-chat-bubble-background`, `shadow-nous`, and crucially `[-webkit-app-region:no-drag]` — the HUDs overlap the titlebar's drag band, which wins hit-testing over DOM regardless of z-index, so without it the search input swallows clicks. `HUD_TEXT = 'text-xs'`; `HUD_ITEM = 'gap-2 px-2 py-1'` (tighter than shadcn's `px-2 py-1.5` CommandItem default); `HUD_HEADING` styles cmdk group headings as brand-tinted uppercase 0.64rem text with `tracking-[0.16em]` and no sticky bar; `HUD_NOTE = '-ml-1'`; `HUD_NOTE_VARIANT = { muted: 'truncate text-muted-foreground/80', state: 'shrink-0 underline decoration-current/50 underline-offset-2' }`.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** The `state` variant skips truncation because blockified flex items make `overflow: hidden` bite and the app's global 0.25rem underline offset would clip the rule away entirely (comment :332-337).
- **Rebuild notes:** n/a

---

## 5. Command Center

### Command Center overlay  `id: desktop-a.command-center`
- **Surface:** Desktop app
- **Where:** Route `/command-center`; opened by the statusbar Command icon, the `nav.commandCenter` keybind (`mod+.`), or any palette `cc-*` row. Close button aria-label `"Close command center"` (`i18n: commandCenter.close`).
- **What it does:** A four-section operations overlay: Sessions, System, Usage, Maintenance.
- **How it works:** `app/command-center/index.tsx`. Wraps `OverlayView` + `OverlaySplitLayout` + `OverlayNav` + `OverlayMain`. `SECTIONS = ['sessions','system','usage','maintenance']` (:43); the active one is bound to the `?section=` query param through `useRouteEnumParam` (:135), seeded by `initialSection`. Nav icons: `MessageCircle` (sessions), `Activity` (system), `Wrench` (maintenance), `BarChart3` (usage). The header shows `cc.sections[section]` as an `<h2>` and `cc.sectionDescriptions[section]` beneath it (both hidden below 47.5rem, where the nav dropdown already names the section).
- **Inputs / options:** Left rail (or narrow-screen dropdown) with four entries: **"Sessions"**, **"System"**, **"Usage"**, **"Maintenance"** (`i18n: commandCenter.sections.sessions|system|usage|maintenance`). Their subtitles are `"Search and manage sessions"`, `"Status, logs, and system actions"`, `"Token, cost, and skill activity over time"`, `"Diagnostics, backups, curator, and memory data"` (`i18n: commandCenter.sectionDescriptions.*`). Header trailing controls: a search field on Sessions, a 7/30/90-day segmented control on Usage. `useRefreshHotkey` re-runs the System or Usage fetch.
- **Outputs / side effects:** Query-param navigation; per-section fetches.
- **Config / env:** n/a
- **Edge cases / guards:** `$sessions` and `$pinnedSessionIds` are subscribed CONDITIONALLY (`useStoreSelector` returning module-level `EMPTY_SESSIONS`/`EMPTY_PINNED` constants when the section is not `sessions`, :53-56, :136-137), so the System/Usage/Maintenance tabs do not re-render on every streaming token.
- **Rebuild notes:** Bind the section to the URL so palette rows can deep-link; return stable empty references from conditional store selectors.

### Command Center — Sessions section  `id: desktop-a.cc-sessions`
- **Surface:** Desktop app
- **Where:** `/command-center?section=sessions`.
- **What it does:** Search, open, pin, export and delete conversations.
- **How it works:** index.tsx:360-408. Sessions sorted by `last_active || started_at` descending; filtered by a 180 ms-debounced case-insensitive substring over `"<title> <id>"`. Each row is a button showing `sessionTitle(session)` over a formatted timestamp (`fmtDateTime`), with three hover-revealed icon buttons on the right (`opacity-0 … group-hover:opacity-100 focus-within:opacity-100`).
- **Inputs / options:**
  - **Search field** — placeholder `"Search sessions, views, and actions"` (`i18n: commandCenter.searchPlaceholder`), `max-w-[40vw]`.
  - **Row click** — `onOpenSession(session.id)`.
  - **Pin / Unpin** icon button — `Bookmark` / `BookmarkFilled`; tooltip `"Pin session"` / `"Unpin session"` (`i18n: commandCenter.pinSession` / `unpinSession`); calls `pinSession(pinId)` / `unpinSession(pinId)` where `pinId = sessionPinId(session)`.
  - **Export** icon button — `Download`; tooltip `"Export session"` (`i18n: commandCenter.exportSession`); calls `exportSession(id, {session, title})`.
  - **Delete** icon button — `Trash2`, `hover:text-destructive`; tooltip `"Delete session"` (`i18n: commandCenter.deleteSession`); opens a `ConfirmDialog` titled `t.sidebar.row.deleteTitle` with description `t.sidebar.row.deleteDesc(title)`, confirm label `t.common.delete`, busy label `t.sidebar.row.deleting`, done label `t.sidebar.row.deleted`, `destructive`.
- **Outputs / side effects:** Pin store writes, a session export file, a delete RPC.
- **Config / env:** n/a
- **Edge cases / guards:** Empty state shows `"No matching results found."` (`i18n: commandCenter.noResults`) when filtering, else `"No sessions yet."` (`i18n: commandCenter.noSessions`).
- **Rebuild notes:** n/a

### Command Center — System section  `id: desktop-a.cc-system`
- **Surface:** Desktop app
- **Where:** `/command-center?section=system`.
- **What it does:** Gateway status, the two system actions, and a filtered log tail.
- **How it works:** index.tsx:421-506. `refreshSystem()` runs `getStatus()` and `getLogs({file, level, lines: 200})` in parallel whenever the section opens or the file/level filter changes.
- **Inputs / options:**
  - Status block: a green (running) or amber (stopped) dot next to `"Messaging gateway running"` / `"Messaging gateway stopped"` (`i18n: commandCenter.gatewayRunning` / `gatewayStopped`), then `"Hermes <version> · Active sessions <n>"` (`i18n: commandCenter.hermesActiveSessions`).
  - **"Restart gateway"** button (`i18n: commandCenter.restartGateway`, `variant="text"`) → `runSystemAction('restart')`.
  - **"Update Hermes"** button (`i18n: commandCenter.updateHermes`, `variant="textStrong"`) → `runSystemAction('update')`.
  - Action progress line: `"<action name> · running | done | failed"` (`i18n: commandCenter.actionRunning` = `"running"`, `actionDone` = `"done"`, `actionFailed` = `"failed"`).
  - Logs header label `"Recent logs"` (`i18n: commandCenter.recentLogs`).
  - **Log file tabs** — exactly `agent`, `errors`, `gateway`, `desktop` (`LOG_FILES`, :45), rendered by `ResponsiveTabs` with the raw ids as labels.
  - **Log level tabs** — exactly `ALL`, `INFO`, `WARNING`, `ERROR` (`LOG_LEVELS`, :46), displayed lowercased (`ALL` shows as `all`).
  - **Log search field** — placeholder `"Filter log lines..."` (`i18n: commandCenter.logSearchPlaceholder`), `w-44`, client-side substring filter over the fetched tail (matches `hermes logs --search`).
  - Empty log state `"No logs loaded yet."` (`i18n: commandCenter.noLogs`); loading state `"Loading status..."` (`i18n: commandCenter.loadingStatus`).
- **Outputs / side effects:** `restartGateway()` / `updateHermes()` spawn actions; the panel then polls `getActionStatus(name, 180)` up to 18 times at 1200 ms intervals, calling `upsertDesktopActionTask(polled)` each time so the activity rail mirrors it. If nothing came back it synthesises a pending status whose single line is `"Action started, waiting for status..."` (`i18n: commandCenter.actionStartedWaiting`).
- **Config / env:** n/a
- **Edge cases / guards:** Errors render inline next to an `AlertCircle` in `text-destructive`.
- **Rebuild notes:** n/a

### Command Center — Usage section  `id: desktop-a.cc-usage`
- **Surface:** Desktop app
- **Where:** `/command-center?section=usage`.
- **What it does:** Token, cost and skill analytics over 7, 30 or 90 days.
- **How it works:** index.tsx:527-660 (`UsagePanel`). `getUsageAnalytics(days)`, guarded by a monotonically increasing `usageRequestRef` so a slow response for an old period cannot overwrite a newer one.
- **Inputs / options:**
  - **Period segmented control** — `USAGE_PERIODS = [7, 30, 90]`, labelled `"7d"`, `"30d"`, `"90d"` (`i18n: commandCenter.days(count)`), default `30`.
  - **"Retry"** button (`i18n: commandCenter.retry`) in the empty state.
  - Stat tiles: **"Sessions"** (`i18n: commandCenter.statSessions`), **"API calls"** (`i18n: commandCenter.statApiCalls`), **"Tokens in/out"** (`i18n: commandCenter.statTokens`, rendered as `in / out` in compact notation). (`i18n: commandCenter.statCost` = `"Est. cost"` and `actualCost(cost)` = `"actual <cost>"` exist for the cost tile.)
  - **"Daily tokens"** chart (`i18n: commandCenter.dailyTokens`) — a 96px-tall bar per day, input stacked above output, legend swatches labelled `"input"` and `"output"` (`i18n: commandCenter.input` / `output`); each bar's native `title` is `"<day> · in <n> · out <n>"`; the first and last day labels sit under the chart. Empty: `"No daily activity."` (`i18n: commandCenter.noDailyActivity`).
  - **"Top models"** list (`i18n: commandCenter.topModels`) — the first 6 `by_model` rows, value = compact input+output tokens. Empty: `"No model usage yet."` (`i18n: commandCenter.noModelUsage`).
  - **"Top skills"** list (`i18n: commandCenter.topSkills`) — the first 6 `skills.top_skills` rows, value = `"N actions"` (`i18n: commandCenter.actions`). Empty: `"No skill activity yet."` (`i18n: commandCenter.noSkillActivity`).
- **Outputs / side effects:** none (read-only).
- **Config / env:** n/a
- **Edge cases / guards:** Loading shows `"Loading usage..."` (`i18n: commandCenter.loadingUsage`); no totals shows `"No usage in the last N days."` (`i18n: commandCenter.noUsage(period)`) with the Retry button.
- **Rebuild notes:** n/a

### Command Center — Maintenance section  `id: desktop-a.cc-maintenance`
- **Surface:** Desktop app
- **Where:** `/command-center?section=maintenance`. `app/command-center/maintenance.tsx`.
- **What it does:** Desktop parity for `hermes doctor` / `security audit` / `backup` / `debug share` / `curator` / memory reset, with an inline log tail.
- **How it works:** Three sections: Diagnostics, Skill curator, Memory data. Spawn-based actions are launched through `launch(label, start)` which calls the REST helper, stores the returned action name, notifies `"<label> started — tailing log..."` (`i18n: commandCenter.maintenance.actionStarted`) or `"<label> failed to start"` (`i18n: ...actionFailed`), and then polls `getActionStatus(name, 200)` every `ACTION_POLL_MS = 1200` up to `ACTION_POLL_LIMIT = 240` (about five minutes), mirroring each poll into the activity rail via `upsertDesktopActionTask`.
- **Inputs / options:** see the three entries below; plus the shared inline log block headed `"Action log"` (`i18n: commandCenter.maintenance.viewLog`) with a `"Running..."` suffix (`i18n: ...running`) while the action is live, rendered as a selectable `max-h-48` `<pre>`.
- **Outputs / side effects:** Spawned backend actions; notifications; the activity rail.
- **Config / env:** n/a
- **Edge cases / guards:** Errors render inline with an `AlertCircle`. Every op button is disabled while `actionStatus.running === true`.
- **Rebuild notes:** n/a

### Maintenance — Diagnostics ops  `id: desktop-a.cc-maintenance-ops`
- **Surface:** Desktop app
- **Where:** Maintenance section, first block. Section label `"Diagnostics"` (`i18n: commandCenter.maintenance.runOps`).
- **What it does:** Runs four one-shot maintenance operations.
- **How it works:** maintenance.tsx:201-267. Each is an `OpRow` (label + description on the left, a `textStrong` button repeating the label on the right).
- **Inputs / options:**
  1. **"Run doctor"** (`i18n: commandCenter.maintenance.doctor`) — `"Health-check the install, config, and providers"` (`i18n: ...doctorDesc`) → `runDoctor()`.
  2. **"Security audit"** (`i18n: ...securityAudit`) — `"Scan config and skills for risky settings"` (`i18n: ...securityAuditDesc`) → `runSecurityAudit()`.
  3. **"Create backup"** (`i18n: ...backup`) — `"Zip config, memories, skills, and sessions"` (`i18n: ...backupDesc`) → `runBackup()`.
  4. **"Debug share"** (`i18n: ...debugShare`, label becomes `"Uploading debug report..."` (`i18n: ...debugShareRunning`) while running) — `"Upload a redacted report + logs, get shareable links (auto-deletes in 6h)"` (`i18n: ...debugShareDesc`) → `runDebugShare()`.
- **Outputs / side effects:** Debug share renders a `"Share links"` block (`i18n: ...debugShareLinks`) listing each `key: url` in monospace with a **"Copy link"** button (`i18n: ...copyLink`) that writes to the clipboard and toasts `"Link copied"` (`i18n: ...linkCopied`, 1500 ms). Failure toasts `"Debug share failed"` (`i18n: ...debugShareFailed`).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Maintenance — Skill curator  `id: desktop-a.cc-maintenance-curator`
- **Surface:** Desktop app
- **Where:** Maintenance section, second block. Section label and row title `"Skill curator"` (`i18n: commandCenter.maintenance.curator`).
- **What it does:** Shows and controls the background review that archives stale agent-created skills.
- **How it works:** maintenance.tsx:269-313. Loads `getCuratorStatus()` on mount. A `Badge` shows the state: `"Disabled"` (grey) when `!enabled`, `"Paused"` (amber) when paused, `"Active"` (emerald) otherwise (`i18n: ...curatorDisabled|curatorPaused|curatorActive`). The subtitle is `"Background review that archives stale agent-created skills"` (`i18n: ...curatorDesc`) followed by `" · "` and either `"Last run <when>"` (`i18n: ...curatorLastRun`) or `"Never ran"` (`i18n: ...curatorNeverRan`).
- **Inputs / options:**
  - **"Pause"** / **"Resume"** button (`i18n: ...pause` / `...resume`) — only when the curator is enabled; calls `setCuratorPaused(!paused)` with optimistic local state.
  - **"Run now"** button (`i18n: ...runNow`, `textStrong`) → `launch(mm.curator, runCurator)`.
- **Outputs / side effects:** Curator pause flag; a spawned curator run tailing into the shared action log.
- **Config / env:** n/a
- **Edge cases / guards:** While the status is still loading a `PageLoader` labelled `"Skill curator"` is shown. Toggle failures notify `"Skill curator failed to start"` (`i18n: ...actionFailed(label)`).
- **Rebuild notes:** n/a

### Maintenance — Memory data  `id: desktop-a.cc-maintenance-memory`
- **Surface:** Desktop app
- **Where:** Maintenance section, third block. Section label `"Memory data"` (`i18n: commandCenter.maintenance.memoryData`).
- **What it does:** Shows and resets the built-in memory files injected into every session.
- **How it works:** maintenance.tsx:315-344. Loads `getMemoryStatus()` on mount. Caption: `"Built-in memory files injected into every session"` (`i18n: ...memoryDataDesc`) plus `" · "` plus `"Active provider: <name>"` (`i18n: ...memoryProvider`), where the name falls back to `"built-in"` (`i18n: ...builtinMemory`). Sizes are formatted by `formatBytes` (`MB` at 1 decimal from 1 MiB, `KB` from 1 KiB, else `B`), or `"empty"` (`i18n: ...empty`) at zero.
- **Inputs / options:** Two rows:
  1. **"Agent memory (MEMORY.md)"** (`i18n: ...memoryFile`) with a destructive **"Reset memory"** button (`i18n: ...resetMemory`) → `resetMemory('memory')`.
  2. **"User profile (USER.md)"** (`i18n: ...userFile`) with a destructive **"Reset profile"** button (`i18n: ...resetUser`) → `resetMemory('user')`.
  (`i18n: ...resetAll` = `"Reset both"` exists for the combined target.)
- **Outputs / side effects:** Each reset first asks `confirm({destructive: true, title: "Delete <target>? This cannot be undone."})` (`i18n: ...resetConfirm`), then on success toasts `"Deleted <files>."` (`i18n: ...resetDone`) and re-reads the status; failure toasts `"Memory reset failed"` (`i18n: ...resetFailed`).
- **Config / env:** n/a
- **Edge cases / guards:** The reset button is disabled while busy or when the file's size is 0.
- **Rebuild notes:** n/a

---

## 6. Overlay and page primitives

### OverlayView (the full-screen modal card)  `id: desktop-a.overlay-view`
- **Surface:** Desktop app (Core)
- **Where:** `app/overlays/overlay-view.tsx`; the frame behind Settings, Command Center, Agents, Cron, Profiles, Star map and Webhooks.
- **What it does:** Renders a rounded card over a dimmed, slightly blurred backdrop, with a floating close button, an optional centred header slot, optional titlebar actions, and an optional edge badge.
- **How it works:** Root is `fixed inset-0 z-50 bg-black/22 backdrop-blur-[0.125rem]` with an equidistant inset of `calc(var(--titlebar-height) + 0.625rem)` (0.875rem at `sm`). The card is `rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-chat-surface-background) shadow-md` and carries `data-glass-raised=""` so window glass keeps it near-opaque while the field behind thins. A `pointer-events-none` strip of `calc(var(--titlebar-height) + 0.1875rem)` across the card top declares `[-webkit-app-region:drag]`; the header slot (centred) and the action/close row (right, `right-3`) opt back in with `no-drag`. Escape handling uses the shared escape-layer stack: `pushEscapeLayer(ESCAPE_PRIORITY.overlay)` and a window `keydown` that only fires when `isTopEscapeLayer(...)` and the event was not already defaultPrevented, so a nested Radix dialog closes first. Both close paths fire `triggerHaptic('close')`. The root carries `data-overlay-surface=""`, which tells `composerFocusBlockedBySurface` to stand down the global type-to-focus and soft `/` / Enter bindings so keystrokes do not leak into the composer hidden beneath.
- **Inputs / options:** Props `children`, `onClose`, `closeLabel` (default `translateNow('common.close')`), `contentClassName`, `edgeBadge`, `headerContent`, `rootClassName`, `titlebarActions`. Click on the backdrop itself (`event.target === event.currentTarget`) closes. The close button is a ghost `icon-titlebar` button with the `close` codicon. `OVERLAY_TOP_CLEARANCE = 'pt-[calc(var(--titlebar-height)/2-0.4375rem)]'` is exported for columns that sit beside the floating X.
- **Outputs / side effects:** Route or state change through `onClose`.
- **Config / env:** n/a
- **Edge cases / guards:** The overlay root re-pins `--titlebar-height` to the real `TITLEBAR_HEIGHT` inline, because the contrib shell zeroes it for CONTENT areas and CSS vars inherit — a fixed overlay mounted inside a zone would otherwise read 0 and bleed to the window edges (comment :122-127). The `edgeBadge` renders as a SIBLING of the card so it can straddle the top border (the card clips its own overflow).
- **Rebuild notes:** Use an escape-priority stack rather than per-dialog stopPropagation; mark the overlay so global keyboard shortcuts targeting hidden surfaces stand down.

### OverlaySplitLayout / OverlaySidebar / OverlayMain / OverlayNav  `id: desktop-a.overlay-split-layout`
- **Surface:** Desktop app (Core)
- **Where:** `app/overlays/overlay-split-layout.tsx`; the two-column body of Settings, Command Center, Cron, Profiles and Agents.
- **What it does:** A 13rem left rail plus a flexible main column that degrades to a single column with a dropdown nav below 47.5rem.
- **How it works:** `OverlaySplitLayout` is `grid grid-cols-[13rem_minmax(0,1fr)]`, dropping to `grid-cols-1 grid-rows-[auto_minmax(0,1fr)]` at `max-[47.5rem]` (an explicit row template, because the grid's default `align-content: stretch` would otherwise split the height evenly and shove content to mid-screen). `OverlaySidebar` is an `<aside data-tour="overlay-nav">` with `OVERLAY_TOP_CLEARANCE`. `OverlayMain` is a `<main>` capped by `PAGE_MAX_W` with a taller top pad (it sits UNDER the floating X) and horizontal gutter `px-[clamp(0.8333rem,2.6667vw,2.6667rem)]` — the shared page gutter scaled by two thirds. `OverlayNav({footer, groups})` renders the rail on wide viewports and, on narrow ones, a `TabDropdown` riding the OverlayView titlebar strip (`pointer-events-none` container with `pointer-events-auto` children so the floating X underneath stays clickable, `pr-12` clearance, `no-drag`).
- **Inputs / options:** `OverlayNavGroup = OverlayNavLink & { children?: OverlayNavLink[]; gapBefore?: boolean }`; `OverlayNavLink = { active, icon, id, label, onSelect }`. A group's `children` render indented under it while the group is active on the rail, and are always flattened+indented in the dropdown. `gapBefore` inserts a spacer on the rail and a separator in the dropdown. `OverlayNavItem` accepts `nested` for the smaller indented style and `trailing` for a badge.
- **Outputs / side effects:** Each item gets `data-tour="nav-<id>"` so a product tour can address one link.
- **Config / env:** n/a
- **Edge cases / guards:** The rail-to-dropdown swap point (`47.5rem`) is exactly where the layout drops to one column, so the rail never stacks.
- **Rebuild notes:** n/a

### Panel kit (Panel / PanelHeader / PanelList / PanelDetail / …)  `id: desktop-a.overlay-panel-kit`
- **Surface:** Desktop app (Core)
- **Where:** `app/overlays/panel.tsx`; used by the non-settings overlays (cron, profiles, agents, trace).
- **What it does:** The centred capped card plus a borderless master/detail layout with dense single-line rows.
- **How it works / Inputs / options:** Exports, each documented by its props:
  - `Panel({children, className, closeLabel = translateNow('common.close'), contentClassName, onClose})` — wraps `OverlayView` with `px-4 pb-4 sm:px-5` plus `OVERLAY_TOP_CLEARANCE`.
  - `PanelHeader({actions, subtitle, title})` — `<h2>` + optional truncated subtitle; reserves `pr-8` on the right when actions are present so they clear the floating X.
  - `PanelBody({children, className})` — side-by-side above 47.5rem, stacked below.
  - `PanelList({children, className, onSearchChange, searchLabel, searchPlaceholder, searchHints, searchValue})` — a 13rem rail (full width and capped at 40% height when stacked) with an optional pinned full-bleed `SearchField`.
  - `PanelListRow({active, dotClassName, icon, lead, menu, menuItems, menuLabel, meta, onSelect, rowKey, title})` — an `h-7` container (not a `<button>`, so it can host both the select target and a kebab) carrying `data-panel-row`; leading element precedence is `lead` > `dotClassName` dot > `icon` codicon. Passing `menuItems` yields BOTH the hover kebab and a matching right-click menu from one array.
  - `PanelMenuItem = {disabled?, icon?, label, onSelect, tone?: 'danger' | 'default'}`; `PanelRowMenu({items, label = 'Actions'})` renders a `size-5` ghost trigger with the `kebab-vertical` codicon, hidden until row hover/focus or menu-open, and returns `null` with no items.
  - `PanelDetail({children, className})` — scrolling detail region, `space-y-4 pb-6 pl-1 pr-2`.
  - `PanelEmpty({action, description, icon = 'inbox', title})`.
  - `PanelSectionLabel`, `PanelMeta({rows: {label, value}[]})` (a `grid-cols-[5rem_1fr]` `<dl>`), `PanelBlock` (monospace `max-h-48` `<pre>`), `PanelPill({children, tone})` with tones `bad | good | muted | warn`, `PanelAddButton({icon = 'add', label, onClick})` (a centred `+` whose label rides aria/title only), and `PanelAction({children, disabled, icon, onClick, primary})`.
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** `ActionsContextMenu` is rendered with `disabled` when `menuItems` is empty, so the row stays bare rather than opening an empty menu.
- **Rebuild notes:** Derive the kebab and the right-click menu from one item array so they can never diverge.

### Updates overlay  `id: desktop-a.updates-overlay`
- **Surface:** Desktop app
- **Where:** `app/updates-overlay.tsx`; a `max-w-sm` Radix dialog opened by the statusbar version pills (`openUpdateOverlayFor('client' | 'backend')`), the palette's "Update Hermes" row, or the shell context menu.
- **What it does:** Checks for updates, shows the changelog, applies the update with progress, and handles the manual, GUI-skew, blocked and error outcomes.
- **How it works:** Reads `$updateOverlayOpen` / `$updateOverlayTarget` and then one of two store pairs depending on the target (`$updateStatus`/`$updateChecking`/`$updateApply` for the client, the `$backendUpdate*` trio for the backend). On open with no status and no check in flight it triggers `checkUpdates()` / `checkBackendUpdates()`. `phase` is derived from `apply.stage`: `manual` → ManualView, `guiSkew` → GuiSkewView, `applying || stage === 'restart'` → ApplyingView, `error` → BlockerView (when `apply.error === 'venv-blocked'` with blockers) else ErrorView, otherwise IdleView. Closing is blocked entirely while applying; closing out of a terminal state calls `resetUpdateApplyState()`.
- **Inputs / options:**
  - **IdleView** — the checking state shows a lemniscate `Loader` labelled `"Looking for updates…"` (`i18n: updates.checking`). Failure shows `"Couldn't check for updates"` (`i18n: updates.checkFailedTitle`) with a **"Try again"** button (`i18n: updates.tryAgain`) and, when `status.error`, the body `"Check your connection and try again."` (`i18n: updates.connectionRetry`). Unsupported installs show `"Update not available"` (`i18n: updates.notAvailableTitle`) with `status.message` or `"This version of Hermes can't update itself from inside the app."` (`i18n: updates.unsupportedMessage`). Up to date shows the brand mark, `"You're all set"` (`i18n: updates.allSetTitle`) and `"You're running the latest version."` / `"The backend is running the latest version."` (`i18n: updates.latestBody` / `latestBodyBackend`). An available update shows the title/body from `resolveUpdateCopy({target, shownItems, copy})` — `"New update available"` / `"A new version of Hermes is ready to install."` for the client, `"Backend update available"` / `"A newer version of the connected Hermes backend is ready to install."` for the backend, degrading to `"A newer version is ready. Release notes aren't available for this install type."` when there are no commit rows (`i18n: updates.availableTitle|availableBody|availableTitleBackend|availableBodyBackend|availableBodyNoChangelog`) — followed by grouped changelog bullets from `buildCommitChangelog(commits)`, then **"Update now"** (`i18n: updates.updateNow`) and **"Maybe later"** (`i18n: updates.maybeLater`), and a trailing `"+ N more changes included."` (`i18n: updates.moreChanges`) when `behind` exceeds the shown items.
  - **ApplyingView** — a lemniscate loader plus the stage title from `i18n: updates.stages.*`: `idle`/`prepare` = `"Getting ready…"`, `fetch` = `"Downloading…"`, `pull` = `"Almost there…"`, `pydeps` = `"Finishing up…"`, `update` = `"Updating Hermes…"`, `rebuild` = `"Rebuilding the desktop app…"`, `restart` = `"Restarting Hermes…"`, `done` = `"Update complete"`, `manual` = `"Update from your terminal"`, `guiSkew` = `"Update the desktop app"`, `error` = `"Update paused"`. Body is `"The Hermes updater takes over in its own window…"` (`i18n: updates.applyingBody`) or `"The remote backend is applying the update and will restart…"` (`i18n: updates.applyingBodyBackend`). A `Progress` bar is indeterminate unless `apply.percent` is finite (then clamped to 2–100). The last four log lines render in a monospace block. Footer note `"This window will close while the update runs, then Hermes reopens on its own."` (`i18n: updates.applyingClose`). The close button is hidden in this phase.
  - **ManualView** — `Terminal` glyph, title `"Update from your terminal"` (`i18n: updates.manualTitle`), body `"You installed Hermes from the command line, so updates run there too. Paste this into your terminal:"` (`i18n: updates.manualBody`), a click-to-copy `$ <command>` box whose trailing label flips between **"Copy"** and **"Copied"** (`i18n: updates.copy` / `copied`) for 1800 ms, the note `"Hermes will pick up the new version next time you launch it."` (`i18n: updates.manualPickedUp`), and a **"Done"** button (`i18n: updates.done`). With no command (e.g. the Linux sandbox-blocked relaunch) it shows the explanatory message and Done only — never a copy box.
  - **GuiSkewView** — amber `AlertCircle`, title `"Update the desktop app"` (`i18n: updates.guiSkewTitle`), body `apply.message` or `"The backend was updated, but this desktop app package wasn't changed. Update or reinstall the Hermes desktop app (your AppImage / .deb / .rpm) to match."` (`i18n: updates.guiSkewBody`), and **"Done"**.
  - **BlockerView** — title `"Close local previews to update Hermes?"` (`i18n: updates.blockerTitle`) or `"Close other processes to update Hermes"` (`i18n: updates.foreignBlockerTitle`) when any blocker is not a safe-to-stop local preview. Bodies: `"Hermes needs to stop these local previews before updating. This will not modify or delete your files."` (`i18n: updates.blockerBody`), `"Hermes can't safely close these processes automatically…"` (`i18n: updates.foreignBlockerBody`), or the mixed `"Hermes can close the local previews listed below…"` (`i18n: updates.mixedBlockerBody`). Each blocker card shows its label (or `"Local preview"`, `i18n: updates.localPreview`) with `"Port N"` (`i18n: updates.portLabel`) or `"PID N"` (`i18n: updates.pidLabel`). A collapsible **"Technical details"** `<details>` (`i18n: updates.technicalDetails`) lists `PID n · <redacted cmdline>`. Buttons: **"Close previews and update"** / **"Close previews and check again"** (`i18n: updates.closePreviewsAndUpdate` / `closePreviewsAndCheckAgain`) when at least one blocker is safe to stop, plus **"Not now"** (`i18n: updates.notNow`).
  - **ErrorView** — `"Update didn't finish"` (`i18n: updates.errorTitle`) with `apply.message` or `"No worries — nothing was lost. You can try again now."` (`i18n: updates.errorBody`), plus **"Try again"** and **"Not now"**.
- **Outputs / side effects:** `applyUpdates()` / `applyBackendUpdate()`; `applyUpdates({stopSafeBlockers: true})` from the blocker button; clipboard write from the manual copy box.
- **Config / env:** n/a
- **Edge cases / guards:** `formatBlockerCommandLine()` (exported, :445-462) redacts sensitive arguments before display: a query-string form `[?&]<name>=…` and a command-tail form matching `--api-key`, `--access-token`, `--refresh-token`, `--auth-token`, `--x-plex-token`, `--token`, `--password`, `--passwd`, `--client-secret`, `--secret`, `--authorization` (with `=`, `:` or whitespace separators, case-insensitive), replacing the value with `[REDACTED]`; the result is then truncated to `BLOCKER_COMMAND_LINE_LIMIT = 500` characters with a trailing ellipsis. The dialog uses `preventCloseButtonAutoFocus` so Radix's default autofocus does not land on the close button and pop its tooltip on open. Related copy that exists for the multi-instance fan-out: `i18n: updates.clientAlsoBehindTitle|clientAlsoBehindMessage|clientAlsoBehindAction|everythingDispatched|everythingSkipped|everythingRowFailed|everythingFanoutFailedTitle` and the backend `updates.applyStatus.*` strings (`"Updating backend…"`, `"Backend updating…"`, `"Backend restarting to load the update…"`, `"Update not available for this backend."`, `"Backend update failed."`, `"Backend didn't come back online. The update may not have completed — check the backend host."`).
- **Rebuild notes:** Model the apply as a stage machine with named terminal states (manual, gui-skew, blocked, error) rather than a boolean; redact command lines before showing them.

### Session picker overlay  `id: desktop-a.session-picker-overlay`
- **Surface:** Desktop app
- **Where:** `app/session-picker-overlay.tsx`, mounted app-wide; opened by the `/resume`, `/sessions` and `/switch` slash commands (`$sessionPickerOpen`).
- **What it does:** The desktop equivalent of the TUI sessions overlay — pick a session and resume it.
- **How it works:** Renders `<SessionPickerDialog activeStoredSessionId={$selectedStoredSessionId} onOpenChange={setSessionPickerOpen} onResume open/>`. Resuming runs through the same `resumeSession` path the sidebar uses.
- **Inputs / options:** The dialog's own rows (documented with the chat shard).
- **Outputs / side effects:** Session resume.
- **Config / env:** n/a
- **Edge cases / guards:** Returns `null` while `$gatewayState !== 'open'`.
- **Rebuild notes:** n/a

### Session switcher HUD (Ctrl+Tab)  `id: desktop-a.session-switcher`
- **Surface:** Desktop app
- **Where:** `app/session-switcher.tsx`; a compact floating list portaled to `<body>`, sharing the palette's HUD chrome (`HUD_POSITION`, `HUD_SURFACE`, `HUD_ITEM`, `HUD_TEXT`), `max-h-[min(22rem,64vh)] w-[min(19rem,calc(100vw-2rem))]`.
- **What it does:** macOS-style most-recent-first session cycling with `ctrl+tab` / `ctrl+shift+tab`.
- **How it works:** State lives in `store/session-switcher.ts`. `SWITCHER_REVEAL_MS = 220`: a quick tap jumps to the next session immediately on keydown and returns its id; the HUD only appears if Tab is HELD past the reveal delay or tapped a second time while Ctrl is still down. `openOrAdvanceSwitcher(direction)` wraps the index; `commitOnCtrlUp()` returns the highlighted id and closes; `slotSessionId(slot)` resolves `ctrl+1…9` against the switcher list while browsing and against `$sessions` otherwise. `switcherJustClosed()` reports a 400 ms grace window. Deliberately NOT a Radix Dialog, so Tab stays global.
- **Inputs / options:** `ctrl+tab` / `ctrl+pagedown` (`session.next`), `ctrl+shift+tab` / `ctrl+pageup` (`session.prev`), `ctrl+1` … `ctrl+9` (`session.slot.N`), releasing Ctrl commits, click (mousedown) on a row picks it, and clicking the transparent backdrop closes without switching. Each of the first nine rows shows its `⌃N` shortcut in a monospace tabular-nums badge.
- **Outputs / side effects:** `openSession(sessionId, navigate)`.
- **Config / env:** n/a
- **Edge cases / guards:** Returns `null` when closed or when there are fewer than one session; `openOrAdvanceSwitcher` bails when there are fewer than two sessions. The selected row is scrolled into view (`block: 'nearest'`) on every index change. Row leads with a `SessionStatusDot`.
- **Rebuild notes:** Separate "tap to jump" from "hold to browse" with a reveal timer; commit on modifier release.

### PageSearchShell (in-pane page header)  `id: desktop-a.page-search-shell`
- **Surface:** Desktop app (Core)
- **Where:** `app/page-search-shell.tsx`; the header of workspace-pane pages (Capabilities, Messaging, Artifacts, …).
- **What it does:** A uniform page header: search on the left, tabs centred, one trailing action on the right, with an optional secondary filter row.
- **How it works:** A `grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]` with `pt-[calc(var(--titlebar-height)+0.5rem)]`; the trailing `1fr` keeps the centre honest. Tabs are DATA (`PageShellTab = {id, label, meta?: string | number | null}` where `meta === null` renders a loading skeleton badge and `undefined` renders none) rendered by `ResponsiveTabs` with `wideClassName="justify-center"`, collapsing to a dropdown when the header cannot fit both search and tabs.
- **Inputs / options:** Props `tabs`, `activeTab`, `onTabChange`, `filters`, `onSearchChange`, `searchPlaceholder`, `searchHints` (rotating placeholder nudges), `searchValue`, `searchHidden`, `searchTrailingAction`. The tab row carries `data-tour="page-tabs"`.
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** The header must NOT declare `-webkit-app-region: drag` — it spans the band where the floating titlebar clusters live and an overlapping OS drag region eats their clicks at the compositor level, which `pointer-events`/`no-drag` carve-outs across separate stacking contexts do not reliably fix on macOS (comment :300-308).
- **Rebuild notes:** n/a

### MasterDetail layout (rail + detail, resizable seam)  `id: desktop-a.master-detail`
- **Surface:** Desktop app (Core)
- **Where:** `app/master-detail.tsx`; the Capabilities and Messaging pages.
- **What it does:** A dense list rail beside a roomy inspector, with an optional drag-resizable column seam and an optional docked bottom pane.
- **How it works:** `MasterDetail({children, pane, resizeId, split})`. `split='rail'` gives `sm:grid-cols-[14rem_minmax(0,1fr)]`; `split='wide'` gives the exported `MASTER_DETAIL_WIDE_COLS = 'sm:grid-cols-[minmax(0,var(--md-split,0.75fr))_minmax(0,1fr)]'`, where `--md-split` is the drag override slot. With a `resizeId`, the boundary becomes a 4px `cursor-col-resize` sash owned by the detail column; dragging writes `setPaneWidthOverride(resizeId, px)` clamped to `[SPLIT_MIN_LEFT_PX = 180, gridWidth - SPLIT_MIN_RIGHT_PX(320)]`, and double-clicking resets it to `undefined`. Width persists in the same pane store the terminal/editor panes use.
- **Inputs / options:** Drag the seam; double-click the seam to reset. Companion exports: `ListColumn({children, header})`, `DetailColumn({actionBar, children, footer})` (max-w-2xl centred body, an optional quiet caption row, an optional pinned action bar), `ListStrip({left, right})`, `ListStripButton({active, children, disabled, onClick})`, `ListStripMenu({items, label, toggle})` — a kebab whose optional `toggle` row is a label plus a `Switch` and which preventDefaults so the menu stays open while the switch is seen flipping — `ToolChip({children, title})` (monospace capability pill), and `ICON_BUTTON` (a `size-5` ghost class that must stay a class string so tailwind-merge can strip `Button size="icon"`'s larger size).
- **Outputs / side effects:** Pane-store writes.
- **Config / env:** n/a
- **Edge cases / guards:** `CapRow` (the one row used by all three Capabilities lists) is fixed-height (`h-8`, or `h-11` with a subtitle) and uses `[content-visibility:auto]` so the browser can skip offscreen rows in 80+ entry lists without the scrollbar jumping; the always-visible `Switch` means toggling never requires selecting first, and off rows dim.
- **Rebuild notes:** n/a

### DetailPane (docked bottom pane)  `id: desktop-a.detail-pane`
- **Surface:** Desktop app (Core)
- **Where:** `app/master-detail.tsx:212-310`; the JSON editor / log viewer docked under a master-detail page.
- **What it does:** A full-bleed bottom pane with a title strip, actions, collapse and close, resizable by dragging its top edge.
- **How it works:** Height persists via `$paneHeightOverride(id)` / `setPaneHeightOverride(id, px)`. `DETAIL_PANE_DEFAULT_BODY_PX = 288`, `DETAIL_PANE_MAX_VH = 0.7`, `DETAIL_PANE_COLLAPSED_PX = 4` (at or below which the pane reads as collapsed). Dragging the 4px top sash clamps to `[0, 0.7 * innerHeight]`; double-clicking resets to `undefined` (the default). `defaultCollapsed` only seeds when the id has no saved state, so it means "collapsed by default", not "always collapsed".
- **Inputs / options:** Props `actions`, `children`, `defaultCollapsed`, `defaultHeight`, `id`, `onClose` (omit for permanent panes), `title`. Header controls: host `actions`, then a collapse/expand ghost button (`chevron-up` when collapsed, `chevron-down` when open; aria-label and tooltip `t.common.expand` / `t.common.collapse`, `aria-expanded`), then an optional close button (`close` codicon, aria-label `t.common.close`).
- **Outputs / side effects:** Pane-store height writes.
- **Config / env:** n/a
- **Edge cases / guards:** No minimum height — dragging (or the chevron) collapses it down to just the header.
- **Rebuild notes:** n/a

### OverlayIconButton  `id: desktop-a.overlay-icon-button`
- **Surface:** Desktop app (Core)
- **Where:** `app/overlays/overlay-chrome.tsx`.
- **What it does:** The shared titlebar-sized ghost icon action for overlay headers and footers, so they read identically to the overlay's close X across breakpoints.
- **How it works:** A `<Button size="icon-titlebar" variant="ghost">` with `text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground`, defaulting `type="button"` and spreading the rest of the native button props.
- **Inputs / options:** any `ButtonHTMLAttributes` plus `children`.
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

---

## 7. HUD mode (the chrome-free floating chat)

### HUD mode  `id: desktop-a.hud-mode`
- **Surface:** Desktop app
- **Where:** A transparent, frameless, always-on-top window with no titlebar, statusbar, pane tree or sidebars — just the composer bar with the reply floating above it. Entered from the titlebar HUD button or `mod+shift+h`; left from the composer's exit button, `mod+shift+h` again, or `⌘W`.
- **What it does:** Lets Hermes be driven while the user works in another app (Figma, a browser, a game).
- **How it works:** `store/hud.ts` owns the mode flag and window lifecycle. It is NOT a puppet window: unlike the pet overlay or Quick Entry, the HUD is a FULL app renderer with its own gateway — the same thing `openWindow()` spawns, just reshaped — so the composer here IS the app's composer (slash commands, `@` refs, attachments, queue, voice, model pill) and the transcript is the app's transcript. `$hudActive` tracks whether a HUD window is up (in the HUD's own renderer it is always true); `$hudMode` is a constant per window; `$hudSession` names the conversation. `canUseHud()` requires `window.hermesDesktop.hud.open` to exist. `openHud(sessionId)` (:46-72) flushes composer drafts into the shared stash BEFORE the window exists (so the HUD's composer boots with the text rather than racing a cross-window storage event), resolves the backend profile through `rememberedSessionProfile($sessions, sessionId, $activeGatewayProfile)` (a session from a non-primary profile would otherwise resolve against the wrong backend and fall back to that profile's last session, #82285), and calls `hud.open({sessionId, profile})`. `watchHudState(onClosed)` (:106-116) mirrors main's broadcasts into the atoms so the titlebar toggle cannot go stale when the HUD is closed from its own side.
- **Inputs / options:** `openHud(sessionId?)`, `closeHud()`, `toggleHud(sessionId?)`, `resetHudLayout()`, `reportHudSession(id)`, `watchHudState(cb)`.
- **Outputs / side effects:** A second Electron window; the app window loses the session's event stream until the HUD closes (see the handoff entry).
- **Config / env:** `$hudActive` is deliberately NOT persisted — the HUD is a live window main owns and can never outlive the app; a remembered `true` would make the first toggle after a restart a no-op (comment :26-30).
- **Edge cases / guards:** The HUD window suppresses the floating pet, tip host, session tiles, route tiles and preview tiles (`app/contrib/controller.tsx:820`, `wiring.tsx:1133,1253,1258,1262`).
- **Rebuild notes:** Reuse the real chat surface in a reshaped window rather than building a lookalike; hand the child window both the session id and the backend profile.

### HUD shell (Spotlight layout and band visibility)  `id: desktop-a.hud-shell`
- **Surface:** Desktop app
- **Where:** `app/hud/hud-shell.tsx`; the root element carries `data-hud-shell`, `data-hud-edge`, `data-hud-game`, `data-hud-held`, `data-hud-input`, `data-hud-recent`.
- **What it does:** Lays the HUD out as macOS Spotlight — a centred composer bar at rest, with the transcript hanging below it as bare text that fades in and out on activity.
- **How it works:** Timings are published to CSS as custom properties so the module and the stylesheet cannot drift: `HUD_RECENT_HOLD_MS = 1100` (the only hold; the CSS carries no transition-delay), `HUD_REVEAL_MS = 110` (`--hud-reveal`), `HUD_FADE_MS = 180` (`--hud-fade`), `HUD_DIM_MS = round(180 * 1.5) = 270` (`--hud-dim`, the slower step down to the glanceable opacity when you let go), `HUD_COLLAPSE_MS = round(180 * 0.66) = 119` (`--hud-collapse`, the sheet rolling shut faster than the text fades). `HUD_SHEET_OVERHANG_PX = 12` is folded into the measured height so an empty transcript measures a true zero. `HUD_THREAD_ALWAYS_BELOW = true` pins the composer to the top and the thread below it regardless of which screen edge the window is parked against (the edge-aware CSS for both orientations is still present, and the `measure()` fallback flips to `'top'` when `screenY - screen.availTop <= 0` and back at `>= 4`, polled every 300 ms with that gap as hysteresis).
  `useRecentActivity()` (:68-134) sets `data-hud-recent` for a hold window after any conversation activity. It subscribes to `$messages` but only bumps when a SIGNATURE of `length:lastId:lastTextLength` actually changes (the atom is republished for session syncs, re-renders and relative timestamps, which latched the band open permanently), and to `$busy`. Re-arming is refused for ambient activity unless the composer has focus — an unfocused HUD gets one hold window and no more. The deliberate `letGo` gesture (clicking away from the composer, and window `blur`) always buys the full window.
  `useHudHeld(gameUnder)` (:159-184) sets `data-hud-held` while any of: a clarify/approval/sudo/secret prompt is pending (`$activeSessionAwaitingInput`), the session is `$busy`, a 1100 ms grace window after the turn ends, or game-overlay mode (unconditionally — an in-game chat log you look back at during a lull is useless if it erases itself).
  The height measurement effect (:288-369) finds `[data-slot="aui_thread-viewport"]`, observes it and its first child plus the composer dock with a `ResizeObserver`, measures the TIGHT bbox of `[data-slot="aui_thread-content"] > *:not([data-slot])` rows (measuring to the viewport edge counted the `min-height:100%` scroll container and painted an empty slab), adds the overhang only when there is real text, and writes `--hud-band-height` from `hudTranscriptHeight({barHeight, contentHeight, viewportHeight})` (`app/hud/layout.ts`: `0` when `contentHeight < 1`, else `round(viewportHeight - barHeight)` — so a resized HUD buys real scrollback rather than empty chrome) and `--hud-bar-height` from the dock's measured height. It also polls every 500 ms until the lazily-mounted viewport exists and re-measures on window resize.
- **Inputs / options:** No controls of its own; the composer and its buttons are the interface.
- **Outputs / side effects:** CSS variables and data attributes; `setFilled(barHeight + visible >= innerHeight - 1)` which gates the native frost.
- **Config / env:** n/a
- **Edge cases / guards:** A mount effect injects `html,body,#root{background:transparent !important;}` because `index.html`'s pre-paint anti-white-flash script writes an opaque themed background as an INLINE style, which beats any stylesheet rule (:393-399).
- **Rebuild notes:** Publish animation timings from one module into CSS vars; gate "recent activity" on a content signature, not on store writes.

### HUD click-through (window mouse transparency)  `id: desktop-a.hud-click-through`
- **Surface:** Desktop app
- **Where:** `app/hud/click-through.ts`; invisible, but it is what makes the HUD usable over another app.
- **What it does:** Makes the always-on-top window hand the mouse to whatever is behind it everywhere the HUD is not genuinely interactive.
- **How it works:** `hudIgnoresMouse(root, hit, active, windowFocused)` (:23-47) returns true (ignore the mouse) unless: a long-press drag is in progress (`root.querySelector('[data-hud-grabbing]')` — the cursor outruns the window it is moving, so the hit test goes empty mid-drag); OR the cursor is over something the HUD paints (`hit !== null && !hit.contains(root)` — anything that CONTAINS the shell is the scaffolding `#root`/`<body>`/document, so a hit on one means the cursor is over nothing); OR the composer holds focus in a focused window (`[data-slot="composer-rich-input"]`); OR a portalled overlay outside the shell holds focus (it owns the next click, including the outside click that dismisses it, which the hit test cannot see coming). `useHudClickThrough(rootRef)` (:82-158) hit-tests with `document.elementFromPoint` rather than enumerating elements (everything the HUD does not want to catch is `pointer-events: none` in the stylesheet), tracks the last cursor point so a focus change can re-decide without waiting for a move, and calls `window.hermesDesktop.hud.setIgnoreMouse(next)` only on changes. Listeners: window `mousemove`, `blur`, `focus`; document `mouseleave`, `focusin`, `focusout`. On Linux, where Electron's `forward: true` is unsupported and moves stop the moment the window starts ignoring, main polls the cursor and pushes points in through `hud.onCursor(next => …)`; `null` means the cursor left the window.
- **Inputs / options:** none (automatic).
- **Outputs / side effects:** `setIgnoreMouse(boolean)` IPC; `setIgnoreMouse(false)` on unmount.
- **Config / env:** n/a
- **Edge cases / guards:** Whenever the cursor position becomes unknown the window is handed back (solid is only ever right under a cursor we can still see). It follows that nothing in HUD mode may declare `-webkit-app-region: drag` on macOS/Windows — a drag region swallows the page's mouse events, so the moves never arrive and the window is stranded on whatever it last decided. Linux is the exception: the solidity decision is fed from main's cursor poll, which a drag region cannot starve, so the HUD composer root DOES declare a drag region there (input carved out as no-drag) and the compositor moves the window natively — the only move that works on Wayland, where `setBounds` position is a no-op.
- **Rebuild notes:** Decide window mouse-transparency from a live hit test plus focus ownership, not from a hand-maintained element list.

### HUD native frost (glass)  `id: desktop-a.hud-glass`
- **Surface:** Desktop app
- **Where:** `app/hud/glass.ts`; the blurred material behind the transcript band.
- **What it does:** Switches the OS-level window material (macOS vibrancy / Windows 11 DWM backdrop) on and off under the band.
- **How it works:** `useHudGlass(rootRef, backing)` sets the frost only when ALL of: `backing` is true (bar + band actually cover the window — the material is composited BELOW the web contents and fills the whole window rectangle, so any excess is frost over empty space); no completion drawer is open (`[data-slot="composer-completion-drawer"]`, which drops the band to 25% and blurs it — full-strength frost behind a band that has deliberately stepped back is a bare slab); and the caret is genuinely in the composer (`[data-slot="composer-rich-input"]:focus`, queried LIVE rather than tracked from `document.activeElement`, which stays put on a blurred window and would latch the frost on forever). The drawer mounts and unmounts without any focus change, so a `MutationObserver` over the whole shell schedules a re-decision, coalesced to one animation frame (a streaming reply mutates the transcript tens of times a second). Window `blur`/`focus` also schedule, because clicking away to another app fires no `focusout` yet `:focus` stops matching.
- **Inputs / options:** none.
- **Outputs / side effects:** `window.hermesDesktop.hud.setFrost(boolean)`; `setFrost(false)` on unmount.
- **Config / env:** Whether frost is wanted at all is the user's translucency setting, decided in main (`hudFrostFor`); this hook only reports what the band is doing.
- **Edge cases / guards:** `backdrop-filter` cannot work here — a transparent window's backdrop root is the document and the desktop was never in it. The material cannot animate, so it is switched while the tint is at full strength: on the moment the band engages, off the moment the hold ends and the fade begins (letting it outlive the fade leaves a grey blurred rectangle popping out at the end).
- **Rebuild notes:** Run the frost off the SAME gate as the scrim painted over it, or the two drift and you get a white slab under white ink on light themes.

### HUD resize handles  `id: desktop-a.hud-resize`
- **Surface:** Desktop app
- **Where:** `app/hud/resize-handle.ts` plus the invisible `[data-hud-resize="<dir>"]` divs rendered by `HudShell` (hud-shell.tsx:436-444).
- **What it does:** Lets the user resize the frameless HUD by dragging any edge or corner.
- **How it works:** The window is created `resizable: false` (a transparent frameless window must not expose a system resize hot-zone, or every drag grows it — the Windows transparent-frameless growth bug), so resizing is programmatic: the handle reports absolute SCREEN bounds and main flips resizable on for the `setBounds` call. `HUD_RESIZE_DIRECTIONS = ['n','ne','e','se','s','sw','w','nw']`; `hudResizeDirections(clientPlacement)` returns all eight when the platform allows client placement and only `['e','se','s']` on native Wayland, which cannot change a top-level's global x/y. `hudResizeBounds(origin, direction, dx, dy)` preserves every opposite edge and clamps to `HUD_MIN_WIDTH = 380` / `HUD_MIN_HEIGHT = 160` (the same minimums the window was created with). Deltas are read in screen coordinates because client coordinates are relative to a window that is changing position and size. Pointer capture is attempted and failures are tolerated (window capture-phase `pointermove`/`pointerup`/`pointercancel` listeners keep the gesture alive).
- **Inputs / options:** Primary-button drag on any of the eight (or three) handles. `data-hud-grabbing` is stamped while resizing so click-through does not hand the pointer away mid-gesture.
- **Outputs / side effects:** `window.hermesDesktop.hud.setBounds({x, y, width, height})` per move.
- **Config / env:** `hud.windowing.clientPlacement !== false` selects the direction set; `hud.windowing.solid` selects `data-hud-input="solid"` vs `"click-through"` (Linux X11 cannot ignore-mouse, so a visible band that also ignores the pointer would just eat the click).
- **Edge cases / guards:** A resize interrupted by unmount resets the state.
- **Rebuild notes:** n/a

### HUD composer drag (press-and-hold to move)  `id: desktop-a.hud-composer-drag`
- **Surface:** Desktop app
- **Where:** `app/hud/composer-drag.ts`; the gesture on the HUD composer bar.
- **What it does:** Press and hold the composer, then drag to move the HUD window.
- **How it works:** `LONG_PRESS_MS = 140` before the bar becomes draggable (short enough to feel like grabbing it, long enough that a click still clicks); `MOVE_TOLERANCE = 8` px of slop before the hold is re-read as a text selection and abandoned. On arm it fires `triggerHaptic('selection')`, captures the pointer so moves keep arriving once the cursor outruns the bar, blurs the active element so the drag is not also extending a selection, and calls `hud.beginMove()`; each move sends `hud.moveBy({width, height})` with the size snapshotted at press (main pins it, because a transparent frameless window drifts wider on Windows otherwise) and main parks the window at cursor-minus-grab-offset from its own native cursor sample. Release calls `hud.endMove()` and swallows the trailing `click` once (a completed hold is a grab, not a click on whatever was underneath).
- **Inputs / options:** Options `{controlDrag?, workspaceTransfer?}`. `controlDrag` (X11) makes `Ctrl` + primary button an IMMEDIATE grab that also works over selected text — it preventDefaults the pointerdown before Chromium chooses its native text-drag, and capture-phase `dragstart`/`selectstart` listeners keep the user's selection intact. `workspaceTransfer` (X11/KWin) calls `hud.setWorkspaceTransfer(true)` while grabbed so the window stays visible across virtual-desktop switches and is pinned to the destination on release.
- **Outputs / side effects:** IPC `beginMove` / `moveBy` / `endMove` / `setWorkspaceTransfer`.
- **Config / env:** n/a
- **Edge cases / guards:** Crossing a display often fires `pointercancel` without a matching `pointerup`; ending the grab there parked the HUD on the first monitor, so cancel while armed instead snaps to the native cursor, re-captures, and keeps the hold. An `-webkit-app-region: drag` handle cannot be used on macOS/Windows (see click-through).
- **Rebuild notes:** Move the window from the MAIN process's native cursor samples; client coordinates are useless when the window keeps up with the pointer.

### HUD game-overlay mode  `id: desktop-a.hud-game-overlay`
- **Surface:** Desktop app
- **Where:** `app/hud/game-overlay.ts`; expressed as `data-hud-game` on the shell.
- **What it does:** Detects that a fullscreen app (a game) is under the HUD and switches to an in-game chat-frame treatment.
- **How it works:** Main owns the answer — it polls the OS window list while the HUD is open (`startHudGameOverlayFeed` / `hud-game-overlay.ts`) and pushes changes through `window.hermesDesktop.hud.onGameOverlay(state => setActive(state.active))`. The renderer cannot know this on its own: which OS window owns the screen is not a fact a page can observe.
- **Inputs / options:** none (automatic).
- **Outputs / side effects:** The stylesheet steps the idle bar back to a glanceable overlay opacity so it reads as part of the game's HUD, and `useHudHeld` pins the transcript up UNCONDITIONALLY instead of fading it on a timer.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### HUD to app-window handoff  `id: desktop-a.hud-handoff`
- **Surface:** Desktop app
- **Where:** `app/hud/handoff.ts`; invisible, but it is why leaving HUD mode does not lose the conversation.
- **What it does:** Re-homes the session (and the half-typed draft) back into the app window when the HUD closes, and follows a retarget while it is open.
- **How it works:** The gateway binds a session's event stream to exactly ONE socket — the last to submit or resume it (`session["transport"]`). The HUD is a full renderer with its own socket, so entering HUD mode moves that binding and the app window stops hearing the session entirely (no deltas, no turn-complete, no draft clear), with nothing to poll for because mid-turn nothing is persisted. So leaving is a RE-HOME, not a window close. `useHudHandoff({navigate, resumeSession})` (:58-106, app-window side, no-ops inside the HUD) subscribes to `watchHudState`: on close it calls `reloadPersistedDrafts()`, then — if the HUD ended on a session this window is not showing — either fronts an already-open tile and re-resumes THROUGH the tile delegate (`focusOpenSession(target) === 'tile'` → `sessionTileDelegate().resumeTile(target)`, because the ordinary resume path enforces "a session is either main or a tile, never both" and would quietly close the tile), or routes to it with `openSession(target, navigate)`; otherwise it calls `requestComposerDraftSync('reload')` and `resumeSession(target)`. `useHudGoto(navigate)` (HUD side) listens on `hud.onGoto(id => navigate(sessionRoute(id)))` so asking for HUD mode from another tab switches the conversation showing in it. `useReportHudSession()` (HUD side) pushes `$selectedStoredSessionId` to main through `hud.setSession(id)` so main can hand it back in the close broadcast.
- **Inputs / options:** none (automatic).
- **Outputs / side effects:** Session resume, route change, draft repaint.
- **Config / env:** n/a
- **Edge cases / guards:** `hudTargetSessionId()` prefers the ACTIVE composer's tile over `$selectedStoredSessionId`, because reading the workspace pane's session alone sent the main tab into the HUD no matter which tile was fronted.
- **Rebuild notes:** Treat single-socket session binding explicitly: entering a second window is a transport move, and leaving must resume, not reconnect.

### HUD thread focus retention  `id: desktop-a.hud-thread-focus`
- **Surface:** Desktop app
- **Where:** `app/hud/thread-focus.ts`.
- **What it does:** Clicking the HUD's scrollback does not blur the composer, so the band does not fade mid-read.
- **How it works:** A capture-phase `pointerdown` listener on the shell: for primary-button presses inside `[data-slot="composer-bounds"]` that are NOT on an interactive element (`THREAD_INTERACTIVE = 'a[href], button, input, textarea, select, [contenteditable], [role="button"], [role="link"]'`), it preventDefaults and calls `focusComposerInput(root.querySelector('[data-slot="<RICH_INPUT_SLOT>"]'))`.
- **Inputs / options:** none.
- **Outputs / side effects:** Focus stays in the composer.
- **Config / env:** n/a
- **Edge cases / guards:** Links and buttons in the transcript keep working normally.
- **Rebuild notes:** n/a

### HUD composer buttons — reset layout and exit  `id: desktop-a.hud-buttons`
- **Surface:** Desktop app
- **Where:** The HUD composer's controls row, rendered by `HudWindowButtons` (`app/chat/composer/controls.tsx:181-213`) whenever `$hudMode` is true.
- **What it does:** Restores the HUD's default size/position, and leaves HUD mode.
- **How it works:** Two ghost icon buttons on the controls row (deliberately not a floating chip above the bar — the old chip lived in a 26px transparent strip that under glass is bare untinted material, paid for in every state, for a control invisible until hovered).
- **Inputs / options:**
  1. **"Reset HUD size and position"** (`i18n: titlebar.resetHudLayout`) — codicon `discard`; calls `resetHudLayout()` → `window.hermesDesktop.hud.resetLayout()` (restores the persisted geometry to its display-aware default).
  2. **"Exit HUD mode"** (`i18n: titlebar.exitHud`) — codicon `screen-normal`; calls `closeHud()`.
- **Outputs / side effects:** Window geometry reset; window close plus the re-home described above.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### HUD global "move to pointer" chord  `id: desktop-a.hud-snap-to-pointer`
- **Surface:** Desktop app (Env / OS-level)
- **Where:** Listed read-only in the keyboard-shortcuts panel as `hud.snapToPointer` — `"Move HUD to pointer (global, while HUD is open)"` (`i18n: keybinds.actions['hud.snapToPointer']`), category `view`, keys `mod+shift+g`.
- **What it does:** Snaps the HUD window to the mouse pointer from anywhere on the desktop, even when Hermes is not focused.
- **How it works:** Registered as an OS-global chord in the Electron main process while HUD mode is up; it is a fixed, non-rebindable entry (`KEYBIND_READONLY`, `lib/keybinds/actions.ts:276-277`) so the shortcuts map is complete.
- **Inputs / options:** `mod+shift+g`.
- **Outputs / side effects:** Window move.
- **Config / env:** n/a
- **Edge cases / guards:** Only live while a HUD window exists.
- **Rebuild notes:** n/a

---

## 8. App context menu (right-click anywhere)

### App context menu  `id: desktop-a.app-context-menu`
- **Surface:** Desktop app
- **Where:** Right-click anywhere in the app. `app/context-menu/app-context-menu.tsx`; a `w-56` Radix DropdownMenu anchored to a zero-size fixed span at the click point.
- **What it does:** One capture-phase listener, one store, one menu — replaces both the native Electron menu and the old shell fallback, so every label comes from the locale files.
- **How it works:** A window-level capture `contextmenu` listener (:600-641). It `stopPropagation()`s but never `preventDefault()`s, because Chromium only emits the main-process `context-menu` event (the spellcheck and image-coordinate source) for unprevented gestures — and with no `Menu.popup` anywhere, "default" means no menu at all. Dispatch order: (1) surfaces with their own Radix context menu keep the whole gesture (`[data-hermes-context-menu-trigger]` or `[data-slot="context-menu-trigger"]` — the dedicated marker is checked first because Radix `asChild` merges props so a child's own `data-slot` can win); (2) a terminal handle resolved via `terminalMenuHandleFor(element)`; (3) otherwise `resolveDomTarget(element)` and, when nothing is "owned" (no link, image, editable or selection) and the element sits inside `[data-context-menu-skip]` (the user-message reaction bubble), the gesture is left alone; (4) else the DOM menu opens, falling back to the shell verbs when the DOM sections come out empty. Sections render with a `DropdownMenuSeparator` between them; `onCloseAutoFocus` is prevented. When the click landed inside a dialog, the menu portals into that dialog's content node (`open.target.dialogPortalContainer`).
  `resolveDomTarget` (`app/context-menu/target.ts:173-188`) returns `{dialogPortalContainer, editable, linkUrl, imageUrl, onImage, selectionText}`. Priority is encoded by order: an editable wins over the link wrapping it (the caret is where the user is working); a link wins over the image inside it for the LINK section, but the image section still appears because the target carries both. `editableFrom` accepts enabled, non-readonly `<input>`/`<textarea>` and any `contenteditable` host. An `href` of `#` is treated as no link. `isWebUrl(url)` is `/^https?:\/\//i`.
- **Inputs / options:** Right-click; every section below.
- **Outputs / side effects:** Clipboard writes, navigation, IPC to main.
- **Config / env:** n/a
- **Edge cases / guards:** Spell-check facts arrive AFTER the menu opens (Chromium reports them on the main-process event, which fires after the DOM gesture), so `window.hermesDesktop.onContextMenuSpellcheck(augmentSpellcheck)` attaches them to the already-open menu; `augmentSpellcheck` ignores the payload unless the current menu is a DOM menu on an editable with a non-empty misspelled word (`store.ts:123-131`).
- **Rebuild notes:** Resolve ownership once, in one resolver, so every surface agrees; let late-arriving platform facts augment an open menu rather than delaying it.

### Context menu — link section  `id: desktop-a.ctx-link-section`
- **Surface:** Desktop app
- **Where:** Top section when the right-click landed inside an `<a href>`.
- **What it does:** Opens, externalises or copies the link.
- **How it works:** app-context-menu.tsx:186-215. `linkUrl = normalizeExternalUrl(target.linkUrl)`.
- **Inputs / options:**
  1. **"Open in in-app browser"** (`i18n: contextMenu.link.openInApp`, codicon `globe`) — only for `http(s)` links and only when `!hudForcesNativeLinks()`; calls `openPreview({kind:'url', label: hostPathLabel(url), source: url, url}, 'explicit-link')`.
  2. **"Open in external browser"** (`i18n: contextMenu.link.openExternal`, codicon `link-external`) — `openExternalLink(url)`.
  3. **"Copy URL"** (`i18n: contextMenu.link.copyUrl`, codicon `copy`) — `writeClipboardText(url)`.
  4. **"Copy resolved URL"** (`i18n: contextMenu.link.copyResolvedUrl`, codicon `copy`) — only when the link is a web URL AND `isRemoteGateway()` AND the host is loopback (`/^(localhost|127\.0\.0\.1|0\.0\.0\.0|\[?::1\]?)$/i`); copies `await reachablePreviewUrl(url)`.
- **Outputs / side effects:** Preview tab, OS browser launch, clipboard.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Context menu — image section  `id: desktop-a.ctx-image-section`
- **Surface:** Desktop app
- **Where:** Shown when the right-click landed on an `<img>`.
- **What it does:** Opens, copies or saves the image.
- **How it works:** app-context-menu.tsx:217-262.
- **Inputs / options:**
  1. **"Open in in-app browser"** (`i18n: contextMenu.link.openInApp`) — web image URLs only, and only when `!hudForcesNativeLinks()`.
  2. **"Open in external browser"** (`i18n: contextMenu.link.openExternal`) — web image URLs only.
  3. **"Copy image"** (`i18n: contextMenu.image.copyImage`, codicon `file-media`) — `window.hermesDesktop.contextMenuCopyImage()`, which works through the click coordinates so it also covers a broken image with no URL.
  4. **"Copy image address"** (`i18n: contextMenu.image.copyImageAddress`, codicon `copy`) — only when a URL is known.
  5. **"Save image as…"** (`i18n: contextMenu.image.saveImageAs`, codicon `save`) — `window.hermesDesktop.saveImageFromUrl(url)`; only when a URL is known.
- **Outputs / side effects:** Clipboard, a native save dialog, a preview tab.
- **Config / env:** n/a
- **Edge cases / guards:** `onImage` is true even when `imageUrl` is empty (broken image).
- **Rebuild notes:** n/a

### Context menu — editable section (Cut / Copy / Paste / Select all)  `id: desktop-a.ctx-editable-section`
- **Surface:** Desktop app
- **Where:** Shown when the right-click landed in an input, textarea or contenteditable.
- **What it does:** The standard edit verbs, with accelerators shown the way the native menu did.
- **How it works:** app-context-menu.tsx:330-361. Accelerators are DISPLAY ONLY (`EDIT_SHORTCUTS`, :54-59: `formatCombo('mod+c'|'mod+x'|'mod+v'|'mod+a')` — Chromium's before-input-event handling already executes the chords). Cut/Copy/Paste dispatch `window.hermesDesktop.contextMenuEdit(command)` in MAIN; Select all runs entirely in the renderer, scoped to the field (`.select()` for form fields, a `Range` over the node contents for contenteditable) — main's `selectAll` acts on whatever the focused FRAME considers "all" and grabbed the whole transcript on any focus slip. All four go through `withEditableFocus(action)` (:152-163), which CLOSES the menu first and dispatches on the next animation frame: the Radix content is a focus trap, so a `focus()` while it is open is immediately stolen back and the command runs against `<body>`.
- **Inputs / options:**
  1. **"Cut"** (`i18n: contextMenu.edit.cut`) — disabled unless there is a selection.
  2. **"Copy"** (`i18n: common.copy`) — disabled unless there is a selection.
  3. **"Paste"** (`i18n: contextMenu.edit.paste`) — never disabled.
  4. (separate section) **"Select all"** (`i18n: contextMenu.edit.selectAll`) — disabled when the field is empty.
- **Outputs / side effects:** Clipboard operations on the focused field.
- **Config / env:** n/a
- **Edge cases / guards:** Cut/Copy availability is computed per element kind: form fields compare `selectionStart !== selectionEnd` (Chrome never reflects an input's selection into `window.getSelection()`), contenteditable uses the document selection captured by the resolver. Paste is deliberately NOT gated on a clipboard probe: its action is `webContents.paste()` in main — the same path Ctrl+V takes — while the renderer-side `readClipboard` probe can report empty on Windows even when that path succeeds (#91553); pasting an empty clipboard is a harmless no-op, so the item fails open.
- **Rebuild notes:** Close the menu before restoring focus; never let a "select all" escape the field it was invoked on.

### Context menu — spell-check suggestions  `id: desktop-a.ctx-spellcheck`
- **Surface:** Desktop app
- **Where:** Top of the editable menu when Chromium reported a misspelled word.
- **What it does:** Offers replacements and a dictionary add.
- **How it works:** app-context-menu.tsx:280-297. Up to FIVE suggestions (`suggestions.slice(0, 5)`), each with the `edit` codicon, dispatching `window.hermesDesktop.contextMenuSpellcheck({kind:'replace', word})`; then **"Add to dictionary"** (`i18n: contextMenu.edit.addToDictionary`, codicon `book`) dispatching `{kind:'add', word: misspelledWord}`. Both run through `withEditableFocus`.
- **Inputs / options:** up to six rows.
- **Outputs / side effects:** The word is replaced in the field, or added to the user dictionary.
- **Config / env:** n/a
- **Edge cases / guards:** Facts arrive asynchronously (see `augmentSpellcheck`), so the section can appear a tick after the menu opens.
- **Rebuild notes:** n/a

### Context menu — selection copy  `id: desktop-a.ctx-selection`
- **Surface:** Desktop app
- **Where:** Shown when there is a text selection but the click did not land in an editable.
- **What it does:** Copies the selected text.
- **How it works:** app-context-menu.tsx:362-372 — one row **"Copy"** (`i18n: common.copy`, codicon `copy`) calling `writeClipboardText(target.selectionText)`.
- **Inputs / options:** one row.
- **Outputs / side effects:** Clipboard.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Context menu — shell verbs (empty-target fallback)  `id: desktop-a.ctx-shell-section`
- **Surface:** Desktop app
- **Where:** Right-click on bare app chrome — whenever the DOM sections come out empty.
- **What it does:** The window-level actions.
- **How it works:** app-context-menu.tsx:545-597, three sections.
- **Inputs / options:**
  - Section 1: **"New session"** (`i18n: commandCenter.nav.newChat.title`, codicon `add`) → `navigateToWorkspacePage(navigate, '/')`; **"New window"** (`i18n: keybinds.actions['session.newWindow']`, codicon `multiple-windows`) → `openNewWindow()`, present only when `canOpenNewWindow()`; **"Command palette"** (`i18n: commandCenter.paletteTitle`, codicon `search`) → `openCommandPalette()`.
  - Section 2: **"Toggle status bar"** (`i18n: keybinds.actions['view.toggleStatusbar']`, codicon `layout-statusbar`) → `toggleStatusbarVisible()`; **"Toggle tabs"** (`i18n: keybinds.actions['view.toggleTabStrip']`, codicon `layout-menubar`) → `toggleTargetZoneTabStrip()` — the pointer-only way back to a hidden tab strip, reachable from anywhere including a zone that has no chrome left to right-click; **"Settings"** (`i18n: commandCenter.settings`, codicon `settings-gear`) → `navigateToWorkspacePage(navigate, '/settings')`.
  - Section 3: **"Update Hermes"** (`i18n: commandCenter.updateHermes`, codicon `cloud-download`) → `requestActiveUpdate()`.
- **Outputs / side effects:** Navigation, layout toggles, update dispatch.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Context menu — in-app browser (guest) menu  `id: desktop-a.ctx-guest-section`
- **Surface:** Desktop app
- **Where:** Right-click inside the in-app browser's `<webview>`.
- **What it does:** Link / image / selection / editable verbs built from Chromium's own params, closed by Inspect element.
- **How it works:** app-context-menu.tsx:377-540. `GuestMenuParams` (`store.ts:18-35`) carries `editFlags {canCopy, canCut, canPaste, canSelectAll}` — Chromium's own availability verdict, the same source that greyed out the native menu — plus `dictionarySuggestions`, `hasImageContents`, `isEditable`, `linkURL`, `misspelledWord`, `selectionText`, `srcURL`. `GuestMenuHandle` (`store.ts:39-45`) supplies `addToDictionary`, `copyImage`, `editCommand`, `inspectElement`, `replaceMisspelling`. Edit verbs dispatch AFTER the menu closes (same focus-trap timing rule as the DOM side).
- **Inputs / options:** Link section: **"Open in in-app browser"**, **"Open in external browser"**, **"Copy URL"**. Image section: **"Open in external browser"** (web URLs), **"Copy image"** (when `hasImageContents`), **"Copy image address"**, **"Save image as…"**. Editable: up to five spelling suggestions plus **"Add to dictionary"**; then **"Cut"**, **"Copy"**, **"Paste"** (each gated by the matching `editFlags`); then **"Select all"**. Non-editable with a selection: **"Copy"**. Non-editable page: **"Select all"** (gated by `canSelectAll`). Always last, its own section: **"Inspect element"** (`i18n: contextMenu.page.inspectElement`, codicon `inspect`).
- **Outputs / side effects:** Webview edit commands, clipboard, devtools.
- **Config / env:** n/a
- **Edge cases / guards:** The page-level verbs (copy page URL — `i18n: contextMenu.page.copyPageUrl` = `"Copy page URL"` — open externally, console) live on the browser bar, not here; only Inspect element earns a place on any click.
- **Rebuild notes:** n/a

### Context menu — terminal menu  `id: desktop-a.ctx-terminal-section`
- **Surface:** Desktop app
- **Where:** Right-click inside an xterm terminal.
- **What it does:** Copy / paste / select all against the terminal's own buffer.
- **How it works:** app-context-menu.tsx:126-159. xterm paints to a canvas, so a right-click there crosses no link, image, editable or DOM selection; each terminal registers a `TerminalMenuHandle {getSelection, paste, selectAll}` for its host through `registerTerminalContextMenu(host, handle)` and the coordinator resolves a click back to it via the `[data-terminal]` focus-scope marker both terminal flavours carry (`app/right-sidebar/terminal/terminal-context-menu.ts`).
- **Inputs / options:**
  1. **"Copy"** (`i18n: common.copy`, codicon `copy`) — only rendered when there IS a selection; writes `terminal.getSelection()`.
  2. **"Paste"** (`i18n: contextMenu.edit.paste`, codicon `clippy`) — only when the handle exposes `paste` (the read-only agent mirror has no PTY); DISABLED until the async clipboard probe reports text.
  3. **"Select all"** (`i18n: contextMenu.edit.selectAll`, codicon `list-selection`) — `terminal.selectAll()`.
- **Outputs / side effects:** Clipboard read/write; text injected into the PTY.
- **Config / env:** n/a
- **Edge cases / guards:** `probeClipboard()` (`store.ts:85-96`) reads the clipboard over IPC after the menu opens and flags `clipboardHasText` only if the menu it started with is still the current one. Unlike the DOM menu — whose paste runs `webContents.paste()` in main and must NOT depend on the probe (#91553) — the terminal paste inserts the `readClipboard()` text itself, so its gate and its action share one mechanism.
- **Rebuild notes:** n/a

---

## 9. Right sidebar (file browser, review, terminal)

### Right sidebar pane  `id: desktop-a.right-sidebar-pane`
- **Surface:** Desktop app
- **Where:** The docked pane on the right side of the main zone (left side when panes are flipped). `app/right-sidebar/index.tsx`; `aria-label="Right sidebar"` (`i18n: rightSidebar.aria`).
- **What it does:** Shows the current project's file tree with refresh and collapse-all actions.
- **How it works:** An `<aside>` with `pt-(--titlebar-height)` and a side-dependent border/inset shadow (`border-r` + a left inset highlight when `$panesFlipped`, else `border-l` + a right inset highlight). It computes `hasWorkspace = Boolean(currentCwd) && (workspaceCwdOwner ?? null) === (selectedStoredSessionId ?? null)` — a transition intentionally retains the old cwd until the new session confirms its workspace, and issuing a filesystem read against that path could hit a different remote machine. Tree data comes from `useProjectTree(hasWorkspace ? currentCwd : '')`.
- **Inputs / options:**
  - Section header: the cwd's last path segment as a `SidebarPanelLabel` (uppercase, brand-tinted, with a dithered dot).
  - **Refresh tree** icon button (`i18n: rightSidebar.refreshTree` = `"Refresh tree"`, codicon `refresh`, spins while loading, disabled while loading) — hover/focus-revealed.
  - **Collapse all folders** icon button (`i18n: rightSidebar.collapseAll` = `"Collapse all folders"`, codicon `collapse-all`) — hidden (`opacity-0`, `pointer-events-none`) and disabled unless at least one folder is open.
- **Outputs / side effects:** Filesystem reads; `openPreview(preview, 'file-browser')` on file activation.
- **Config / env:** n/a
- **Edge cases / guards:** With no workspace it renders `PaneEmptyState` with `"No project open"` (`i18n: rightSidebar.noProjectOpen`) — switching workspace is a project/worktree action, never a raw folder picker. Preview failures notify `"Preview unavailable"` (`i18n: rightSidebar.previewUnavailable`) with the body `"Could not preview <path>"` (`i18n: rightSidebar.couldNotPreview`).
- **Rebuild notes:** Gate the filesystem read on the cwd provably belonging to the selected session.

### Project file tree  `id: desktop-a.file-tree`
- **Surface:** Desktop app
- **Where:** The body of the right sidebar. `app/right-sidebar/files/tree.tsx`, container `data-project-tree`.
- **What it does:** A lazy, virtualised project tree with git decorations, drag-to-chat, inline rename and a right-click menu.
- **How it works:** Built on `react-arborist` with `ROW_HEIGHT = 22`, `INDENT = 10` and a fixed base inset of `17px` layered on top of arborist's depth padding. `disableDrag`/`disableDrop`/`disableEdit` are all set (the row implements its own HTML5 drag and its own rename). The `<Tree>` is keyed `` `${cwd}:${collapseNonce}` `` so a cwd change or a collapse-all forces a fresh instance, and it is handed a stable `dndManager` from `getFileTreeDndManager()` — react-arborist mounts its own `DndProvider` with `HTML5Backend` per `<Tree>`, and on a keyed remount react-dnd v14's ref-counted global singleton can be torn down while the previous backend still owns `window.__isReactDndHtml5Backend`, making the new backend's `setup()` throw "Cannot have two HTML5 backends at the same time." and permanently trip the error boundary. Rows are re-parented by `ProjectTreeRowContainer` to `minWidth: 0; width: 100%` so long names ellipsize instead of forcing arborist's default `min-width: max-content`. Data comes from `useProjectTree` (`files/use-project-tree.ts`): a shared nanostore tree of `TreeNode {id (absolute path), name, isDirectory, children?, loading?, placeholder?: 'error' | 'loading', error?}`, lazy `readProjectDir` per folder (`files/ipc.ts`, which also resolves the git root, honours `.gitignore` rules up the ancestor chain, and filters an `ALWAYS_EXCLUDED` set), a 3 s root-error retry, in-flight de-duplication keyed by `${connectionKey}:${id}`, and reconciliation driven by `$workspaceChangeTick`.
- **Inputs / options:**
  - **Click** a folder toggles it; **click** a file selects it.
  - **Shift+click** attaches the file (or folder) to the chat — `onActivateFile` / `onActivateFolder`.
  - **Double-click** a file opens the preview.
  - **Enter** or a click through arborist's `onActivate` also opens the preview (suppressed for the row being renamed).
  - **F2** or **Enter** on the selected row begins an inline rename (`isRenameShortcut`, capture-phase so it beats arborist's Enter-to-activate; skipped while an edit is in progress and for placeholder rows).
  - **Drag** a row: `dataTransfer` gets `application/x-hermes-paths` = `[{isDirectory, path}]` and `text/plain` = the absolute path, `effectAllowed = 'copy'`.
  - **Right-click**: the shared `FileEntryContextMenu`.
- **Outputs / side effects:** Preview tabs, chat attachments, rename/delete operations.
- **Config / env:** n/a
- **Edge cases / guards:** Git decorations tint the name by `repoChangeKindForPath(path)`: `added` → `--ui-green`, `conflicted` → `--ui-red`, `modified` → `--ui-yellow`; the explicit colour wins over the row's hover/selected colour so it persists. There is deliberately no chevron column — the open/closed folder icon carries the expand state. Placeholder rows render a spinning `loading` or a `warning` codicon and are `pointer-events-none italic`. The click handler re-reads `$renamingPath` LIVE (not from the render closure), because the fall-through click from a context-menu close can fire before the editing re-render commits. `revealNode(absPath)` walks each ancestor top-down, lazy-loading children and awaiting a frame per level, then `select` + `scrollTo(target, 'start')`; it is driven by the `$revealInTreeRequest` atom (the "Reveal in filetree" action).
- **Rebuild notes:** Lazy-load per folder with in-flight dedup; keep a stable drag-drop manager across keyed remounts; drive "reveal" through an atom so any surface can request it.

### File entry context menu  `id: desktop-a.file-entry-context-menu`
- **Surface:** Desktop app
- **Where:** Right-click on any row of either file tree (browser and review/git). `app/right-sidebar/file-actions.tsx:58-105`.
- **What it does:** The shared per-file actions.
- **How it works:** Radix `ContextMenu`; `onCloseAutoFocus` is prevented so the inline rename input it can mount is not blurred immediately. `localFs = !isDesktopFsRemoteMode()` hides reveal/rename/delete on a remote backend; `remoteDownload = shouldOfferRemoteFileDownload(isDirectory)`.
- **Inputs / options:** In order, with separators between groups:
  1. **Reveal** — label picked by platform via `pickRevealLabel`: `"Reveal in Finder"` on macOS (`i18n: fileMenu.revealFinder`), `"Reveal in File Explorer"` on Windows (`i18n: fileMenu.revealExplorer`), `"Open containing folder"` elsewhere (`i18n: fileMenu.revealFileManager`). Local FS only.
  2. **"Copy path"** (`i18n: fileMenu.copyPath`) → `copyFilePath(path)`.
  3. **"Copy relative path"** (`i18n: fileMenu.copyRelativePath`) → `copyFilePath(toRelativePath(path, relativeTo))`; only when a `relativeTo` base was supplied.
  4. **"Download"** (`i18n: fileMenu.download`) → `downloadRemoteFile(path)`; remote backends, files only.
  5. **"Rename…"** (`i18n: fileMenu.rename`) → `beginInlineRename(path)`. Local FS only.
  6. **"Delete"** (`i18n: fileMenu.delete`, destructive variant) → `requestFileDelete({isDirectory, name, path})`. Local FS only.
- **Outputs / side effects:** Clipboard, OS reveal, a download, an inline rename, a delete confirmation. (`i18n: fileMenu.pathCopied` = `"Path copied"`, `downloadSaved` = `"Saved"`, `downloadFailed` = `"Download failed"` are the toasts.)
- **Config / env:** n/a
- **Edge cases / guards:** Windows is detected as `/win/i.test(navigator.platform || navigator.userAgent)`.
- **Rebuild notes:** n/a

### Inline rename editor  `id: desktop-a.inline-rename`
- **Surface:** Desktop app
- **Where:** Renders in place of a tree row's label while `$renamingPath === path`. `app/right-sidebar/file-actions.tsx:142-212`; aria-label `"New name"` (`i18n: fileMenu.renameLabel`).
- **What it does:** VS Code-style in-row rename: seeded with the current name, stem pre-selected.
- **How it works:** On focus it selects `[0, lastIndexOf('.') > 0 ? dot : length]`. Commits on Enter and on blur, cancels on Escape. A `done` ref latches on the first finish so Enter plus the resulting blur cannot both commit. A `mountedAt` ref ignores blurs within 250 ms of mount and re-grabs focus, because context-menu close, arborist refocus and the fall-through click on the row would otherwise blur-commit-cancel instantly.
- **Inputs / options:** Type; Enter to commit; Escape to cancel; click away to commit. `autoCapitalize/autoComplete/autoCorrect="off"`, `spellCheck={false}`; click and double-click are stopped so the row underneath does not react.
- **Outputs / side effects:** `executeFileRename(path, next)` when the trimmed value is non-empty and different; failures notify `translateNow('errors.genericFailure')`.
- **Config / env:** n/a
- **Edge cases / guards:** `keydown` is stopPropagated so global shortcuts do not fire while renaming.
- **Rebuild notes:** n/a

### File delete confirmation  `id: desktop-a.file-delete-dialog`
- **Surface:** Desktop app
- **Where:** `FileActionDialogs`, mounted once near the app root (`app/right-sidebar/file-actions.tsx:109-129`).
- **What it does:** Confirms a file/folder delete requested from either tree.
- **How it works:** A `ConfirmDialog` driven by the `$fileActionDialog` atom; open when `dialog.kind === 'delete'`.
- **Inputs / options:** Title `"Delete <name>?"` (`i18n: fileMenu.deleteTitle`); description `"It will be moved to the Trash — you can restore it from there."` (`i18n: fileMenu.deleteBody`); confirm label `"Delete"` (`i18n: fileMenu.delete`), destructive.
- **Outputs / side effects:** `executeFileDelete(path)` (moves to Trash).
- **Config / env:** n/a
- **Edge cases / guards:** Rename is inline, not dialog-based, so only delete lives here.
- **Rebuild notes:** n/a

### Remote folder picker  `id: desktop-a.remote-folder-picker`
- **Surface:** Desktop app
- **Where:** `app/right-sidebar/files/remote-picker.tsx`; a dialog used wherever a folder must be chosen on a REMOTE backend (no native picker available).
- **What it does:** Browses folders on the connected backend and returns the selected path.
- **How it works:** Registers a promise-based picker: a caller supplies `{defaultPath, title}` and awaits the resolved path list. The dialog shows a breadcrumb built from the current path (starting with a `/` crumb, then each segment accumulating), a parent-directory row, and one `FolderRow` per subdirectory.
- **Inputs / options:** Title `"Choose remote folder"` (`i18n: rightSidebar.remotePickerTitle`) or the caller's own; description `"Browse folders on the connected backend."` (`i18n: rightSidebar.remotePickerDescription`); breadcrumb buttons; the parent row; folder rows; a cancel button; and **"Select folder"** (`i18n: rightSidebar.remotePickerSelect`) which resolves with `[currentPath]`.
- **Outputs / side effects:** Resolves the caller's promise; cancelling resolves with nothing.
- **Config / env:** n/a
- **Edge cases / guards:** Related strings: `"No folder selected"` (`i18n: rightSidebar.noFolderSelected`), `"Change working directory"` (`i18n: rightSidebar.changeCwdTitle`), `"Open folder"` (`i18n: rightSidebar.openFolder`).
- **Rebuild notes:** n/a

### Review pane (source control)  `id: desktop-a.review-pane`
- **Surface:** Desktop app
- **Where:** A right-side pane toggled by `view.toggleReview` (`mod+g`) or `openReview()`. `app/right-sidebar/review/index.tsx`; `aria-label` = `"Review"` (`i18n: statusStack.coding.review`).
- **What it does:** Lists the working tree's changed files, shows a diff for the selected one, and offers stage/revert/refresh plus the ship bar.
- **How it works:** Driven by the `store/review` atoms (`$reviewFiles`, `$reviewLoading`, `$reviewIsRepo`, `$reviewSelectedPath`, `$reviewDiff`, `$reviewDiffLoading`, `$reviewRevertTarget`, `$reviewTreeMode`). Skeletons are delayed (`useDelayedTrue`) so a fast project switch goes blank-to-content instead of flashing.
- **Inputs / options:** Header actions (all `size-5` ghost icon buttons, disabled when there are no files except Refresh):
  - **"View as list"** / **"View as tree"** (`i18n: statusStack.coding.viewAsList` / `viewAsTree`) — codicon `list-flat` / `list-tree`; `toggleReviewTreeMode()`.
  - **"Stage all"** (`i18n: statusStack.coding.stageAll`) — codicon `add`; `stageReviewFile(null)`.
  - **"Revert all"** (`i18n: statusStack.coding.revertAll`) — codicon `discard`; `requestRevert(null)`.
  - **"Refresh tree"** (`i18n: rightSidebar.refreshTree`) — codicon `refresh`, spins while loading; `refreshReview()`.
  - **"Close"** (`i18n: statusStack.coding.close`) — codicon `close`; `closeReview()`.
  Selected-file strip (max 55% height): the display path, a `DiffCount` of added/removed, a **"Stage"** / **"Unstage"** button (`i18n: statusStack.coding.stage` / `unstage`, codicon `add` / `remove`), and a **"Close"** button clearing the selection. The diff itself renders through the shared shiki-highlighted `FileDiffPanel` (virtualized).
- **Outputs / side effects:** Git stage/unstage/revert operations; a `ConfirmDialog` for reverts titled `"Revert"` or `"Revert all"` with the bodies `"Discard changes to this file and restore it to the committed state? This cannot be undone."` (`i18n: statusStack.coding.revertConfirm`) and `"Discard every change and restore files to the committed state? This cannot be undone."` (`i18n: ...revertAllConfirm`), `destructive`, `dismissOnConfirm` (the revert then runs in the background and failures land in a toast).
- **Config / env:** n/a
- **Edge cases / guards:** With no repo, or a repo with no changes, it shows `PaneEmptyState` with `"No diffs"` (`i18n: rightSidebar.noDiffs`); an empty diff shows `"No diff to show"` (`i18n: statusStack.coding.noDiff`). The self-naming panel label carries `data-pane-self-label` so a zone tab that already says "review" hides it.
- **Rebuild notes:** n/a

### Review file tree rows  `id: desktop-a.review-file-tree`
- **Surface:** Desktop app
- **Where:** The list inside the review pane. `app/right-sidebar/review/file-tree.tsx`.
- **What it does:** Lists changed files (flat or as a tree), each with stage/revert affordances and a right-click menu.
- **How it works:** Rows show the basename plus a dimmed parent-directory suffix, a `DiffCount`, and a green dot titled `"Staged"` (`i18n: statusStack.coding.staged`) for staged files. Tree vs list is driven by `$reviewTreeMode` and built by `review/tree-data.ts`. `review/churn-bar.tsx` renders a per-row right-anchored "digital rain" churn bar whose width is the file's churn relative to `$reviewMaxChurn`.
- **Inputs / options:**
  - Hover buttons: **"Stage"** / **"Unstage"** (`i18n: statusStack.coding.stage` / `unstage`) and **"Revert"** (`i18n: statusStack.coding.revert`).
  - Right-click menu, in order: **"Open changes"** (`i18n: statusStack.coding.openChanges`), **"Open file"** (`i18n: statusStack.coding.openFile`), a stage/unstage item, **"Revert"** (destructive), **"Reveal in filetree"** (`i18n: fileMenu.revealInSidebar` → `revealFileInTree(path)`), the platform reveal item (local FS only), **"Copy path"** (`i18n: fileMenu.copyPath`), **"Copy relative path"** (`i18n: fileMenu.copyRelativePath`), and **"Download"** (`i18n: fileMenu.download`) on remote backends.
  - Rows are draggable, carrying the same `application/x-hermes-paths` payload as the browser tree.
- **Outputs / side effects:** Git operations, preview tabs, clipboard, tree reveal.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Review ship bar (commit / push / PR)  `id: desktop-a.review-ship-bar`
- **Surface:** Desktop app
- **Where:** Pinned to the bottom of the review pane. `app/right-sidebar/review/ship-bar.tsx`.
- **What it does:** Commits, pushes and opens a PR — either directly, or by handing the whole job to the agent in one click.
- **How it works:** Renders only when there are changed files. State from `$reviewShipInfo`, `$reviewScopeTarget`, `$reviewShipBusy`, `$reviewCommitMsgBusy`, `$reviewCommitDefault`.
- **Inputs / options:**
  - **Commit message textarea** — auto-growing (`field-sizing-content`, `max-h-40`), placeholder `"Message (⌘↵ to commit)"` (`i18n: statusStack.coding.commitPlaceholder(shortcut)` with `formatCombo('mod+enter')`). `mod+Enter` inside it runs the default commit action.
  - **Generate button** (top-right of the textarea) — **"Generate commit message"** (`i18n: statusStack.coding.generateCommitMessage`); while running it becomes a cancel labelled **"Stop generating"** (`i18n: ...stopGenerating`). Passes the current text so a re-press regenerates.
  - **Commit split button** — primary action `"Commit"` (`i18n: statusStack.coding.commit`) with the alternative `"Commit & Push"` (`i18n: ...commitAndPush`); choosing an entry also sets `$reviewCommitDefault`. Disabled unless there are files, the message is non-empty, and nothing is busy.
  - **"Ask Hermes to open PR"** (`i18n: statusStack.coding.agentShip`) — sends the prompt `"Review the current changes, commit them with a clear conventional-commit message, push the branch, and open a pull request."` (`i18n: ...agentShipPrompt`) through `requestComposerSubmit(prompt, {target: scopeTarget})`; if no composer owns the changes it notifies `"The chat that owns these changes isn't on screen."` (`i18n: ...agentShipUnavailable`).
  - **PR icon button** (right, out of flow) — codicon `git-pull-request`, labelled `"Open PR"` when `ship.pr?.url` exists else `"Create PR"` (`i18n: ...openPr` / `createPr`); disabled with the tooltip `"Install the GitHub CLI (gh) and sign in to open PRs"` (`i18n: ...ghMissing`) when `!ship.ghReady`. Calls `createOrOpenPr()`.
- **Outputs / side effects:** Git commit/push, a GitHub PR, or a queued agent task.
- **Config / env:** Scope strings that appear elsewhere in the coding stack: `"Uncommitted"`, `"Branch"`, `"Last turn"` (`i18n: statusStack.coding.scopeUncommitted|scopeBranch|scopeLastTurn`).
- **Edge cases / guards:** A successful commit clears the message field.
- **Rebuild notes:** Offer both the manual path and the one-click agent path from the same bar.

### Terminal pane chrome and tab rail  `id: desktop-a.terminal-rail`
- **Surface:** Desktop app
- **Where:** The right edge of the terminal pane. `app/right-sidebar/terminal/chrome.tsx` (`TerminalPaneChrome`) and `rail.tsx` (`TerminalRail`); the rail is a 36px (`w-9`) vertical strip with `aria-label="Terminals"` (`i18n: rightSidebar.terminalsAria`) and `role="tablist"`.
- **What it does:** Switches between terminals, creates new ones, and hides the pane.
- **How it works:** `TerminalPaneChrome` renders the body slot (which the persistent xterm overlay chases) plus the rail, and lives in the real pane DOM — not the z-4 terminal overlay — so the rail (z-40) sits above the collapsed sidebars' z-30 hover-reveal triggers and carries `data-suppress-pane-reveal` to make them pointer-transparent while it is hovered. The rail is shown whenever at least one terminal exists, so every tab keeps its close affordance; closing the last one hides the pane.
- **Inputs / options:**
  - **Terminal tab buttons** — one `size-7` square per terminal, `role="tab"`, `aria-selected`, tooltip `"<n>. <title>"` plus the live `view.showTerminal` hint; codicon `terminal`, or `agent` (tinted primary when inactive) for the read-only agent mirror. Plain click selects; **⌘-click** closes (`isMetaClose`); **middle-click** closes (`middleClickHandlers`). The active tab shows a 2px right-edge indicator.
  - **New terminal** button — `+` codicon, tooltip `"New terminal"` (`i18n: rightSidebar.terminalNew`) plus the `view.newTerminal` hint; calls `createTerminal()`.
  - **Hide terminal** button — codicon `chevron-down`, tooltip `"Hide terminal"` (`i18n: rightSidebar.terminalHide`), revealed on rail hover; calls `setTerminalTakeover(false)`.
  - **Per-tab right-click menu**: **"Close"** (`i18n: common.close`), **"Close others"** (`i18n: rightSidebar.terminalCloseOthers`, disabled with a single terminal), **"Close all"** (`i18n: rightSidebar.terminalCloseAll`), separator, **"Hide terminal"**.
- **Outputs / side effects:** Terminal lifecycle; pane visibility.
- **Config / env:** `$terminalTakeover` persists at `localStorage['hermes.desktop.terminalTakeover']` (default false). `runInTerminal(command)` (`app/right-sidebar/store.ts:357-366`) sets the takeover and queues `$terminalInjection`, which the pane flushes and clears once its session is live — used to disconnect CLI-managed providers so the user sees exactly what runs.
- **Edge cases / guards:** Keybinds `view.nextTerminal` / `view.prevTerminal` / `view.closeTerminal` only act while the terminal is genuinely on screen (`isPaneVisible('terminal')`), not merely when the takeover flag is true.
- **Rebuild notes:** n/a

---

## 10. Auxiliary windows

### Quick Entry window  `id: desktop-a.quick-entry`
- **Surface:** Desktop app
- **Where:** A small always-on-top capture window summoned by a global OS shortcut (default `CommandOrControl+Shift+Space`). Rendered by `app/quick-entry/quick-entry-app.tsx`, booted through `?win=quick` by `quick-entry-root.tsx`.
- **What it does:** One input plus a session-target picker: type a prompt anywhere in the OS and send it to Hermes.
- **How it works:** This window carries NO gateway connection. Its view of backend truth (is the gateway up, which recent sessions exist) is pushed in by the primary renderer through main (`quickEntry.onState`), and its text goes back the same road to the primary renderer's normal `submitText` path (`app/contrib/hooks/use-quick-entry-bridge`) — there is no second submit path and no new gateway RPC. All behaviour rides the pure, unit-tested `quickComposerReducer`; the React wrapper performs the side effects (`quickEntry.submit(send)` or `quickEntry.dismiss()`). `quickEntry.onShown` resets the draft and re-focuses the input on each re-summon, because the shell reuses the window.
- **Inputs / options:**
  - **Text input** — `aria-label="Quick Entry"`, placeholder `"Ask Hermes…"` when connected, `"Not connected — open Hermes to reconnect"` when not (both literal, not localised); `autoCapitalize/autoComplete/autoCorrect="off"`, `spellCheck={false}`; disabled while disconnected. **Enter** (without Shift) submits; **Escape** dismisses; **blur** with no `relatedTarget` dismisses (moving focus to the target picker is not leaving the window).
  - **"Send to" select** — `aria-label="Target session"`, id `quick-entry-target`; options `"Current chat"` (value `current`, `QUICK_TARGET_CURRENT`), `"New session"` (value `new`, `QUICK_TARGET_NEW`), then one option per recent session pushed by the primary. **Escape** inside it also dismisses.
- **Outputs / side effects:** A prompt submitted into the chosen session; the window hides. An EMPTY submit does neither, so a stray Enter cannot make the window vanish.
- **Config / env:** The device-local preference lives authoritatively in the MAIN process (it owns the OS registration and must restore it on a cold launch without the renderer visiting Settings). Renderer mirror: `store/quick-entry.ts` — `$quickEntry = {enabled, registered: boolean | null, error: 'invalid' | 'taken' | null, shortcut}` with `QUICK_ENTRY_DEFAULT_SHORTCUT = 'CommandOrControl+Shift+Space'`; `canUseQuickEntry()`, `loadQuickEntrySettings()`, `saveQuickEntrySettings({enabled?, shortcut?})` (optimistic, then adopts main's authoritative reply so a rejected or already-taken chord surfaces as an error state rather than a silently lost setting).
- **Edge cases / guards:** A dead gateway disables the input entirely — the reducer refuses the send AND the input paints the reconnect hint. The root injects `html,body,#root{background:transparent !important;}` so the floating card sits on a transparent backdrop despite `index.html`'s opaque anti-flash script.
- **Rebuild notes:** Keep the capture window gateway-less and route its text through the primary renderer's existing submit path; keep the decision logic in a pure reducer.

### Wake indicator window  `id: desktop-a.wake-indicator`
- **Surface:** Desktop app
- **Where:** A tiny transparent, click-through window pinned at the top-centre of the screen. `app/wake-indicator/wake-indicator-app.tsx` + `wake-indicator.css`, booted by `wake-indicator-root.tsx`.
- **What it does:** A purple glowing pill that tells the user the wake word was heard and whether Hermes is currently capturing audio.
- **How it works:** `<main aria-hidden className="wake-indicator-surface" data-state={state}>` containing a single `.wake-indicator-light` pill: 120x28px, `border-radius: 999px`, `background: rgba(124,58,237,0.62)`, `border: 1px solid rgba(216,180,254,0.82)`, `backdrop-filter: blur(20px) saturate(1.2)`, and a two-layer purple glow shadow. The surface is `pointer-events: none` with `padding-top: 5px`. Three states: `hidden` (opacity 0), `detected` (a 2.5 s `wake-indicator-breathe` ease-in-out infinite animation between opacity 0.34/scale 0.96 and opacity 0.94/scale 1), `capturing` (opacity 1, scale 1). Transitions are `opacity 500ms ease-out, transform 500ms ease-out`. The renderer subscribes to `wakeIndicator.onState` and also does one `getState()` read, ignoring the read if a live push already arrived.
- **Inputs / options:** none (it is aria-hidden, pointer-transparent chrome).
- **Outputs / side effects:** none.
- **Config / env:** Driven by `lib/wake-indicator.ts`: `WakeIndicatorState = 'capturing' | 'detected' | 'hidden'`; `activateWakeIndicator()` pushes `detected`; `syncWakeIndicatorWithVoice(active, status)` maps `status === 'listening'` to `capturing` and everything else to `detected` while a wake-started conversation is running, and pushes `hidden` when it ends; `clearWakeIndicator()` forces `hidden`. `pushState` de-duplicates so the same state is never sent twice. Voice statuses tracked: `idle | listening | speaking | thinking | transcribing`.
- **Edge cases / guards:** `@media (prefers-reduced-motion: reduce)` drops the breathing animation to a static opacity 0.72 / scale 1 and shortens the transition to 200 ms. The root injects `html,body,#root{background:transparent !important;overflow:hidden;}`.
- **Rebuild notes:** n/a

---

## 11. Routes, layout presets and keybinds

### App routes and view classification  `id: desktop-a.app-routes`
- **Surface:** Desktop app (Core)
- **Where:** `app/routes.ts`.
- **What it does:** Defines every top-level route, which ones are overlays, how a session id is parsed out of a path, and how navigation fronts the workspace pane.
- **How it works:** Route constants: `SESSION_ROUTE_PREFIX = '/'`, `NEW_CHAT_ROUTE = '/'`, `SETTINGS_ROUTE = '/settings'`, `COMMAND_CENTER_ROUTE = '/command-center'`, `SKILLS_ROUTE = '/skills'`, `MESSAGING_ROUTE = '/messaging'`, `WEBHOOKS_ROUTE = '/webhooks'`, `ARTIFACTS_ROUTE = '/artifacts'`, `CRON_ROUTE = '/cron'`, `PROFILES_ROUTE = '/profiles'`, `AGENTS_ROUTE = '/agents'`, `STARMAP_ROUTE = '/starmap'`. `APP_ROUTES` pairs each with a view: ids `new, settings, command-center, skills, messaging, webhooks, artifacts, cron, profiles, agents, starmap`. `AppView` adds `chat` and `extension` (a contributed plugin page at its own route — without this distinction contributed paths fell through the `chat` default and the sidebar kept a session highlighted). `OVERLAY_VIEWS = {agents, command-center, cron, profiles, settings, starmap, webhooks}` — these render as full-screen modal cards, and while one is open the titlebar clusters must hide. `routePathname(to)` strips any `?`/`#` before classification (an unstripped query reaches the session-id parser, so `/skills?tab=mcp` would read as the session `skills?tab=mcp`). `routeSessionId(path)` returns the decoded id for any single-segment path that is not reserved and not a contributed route. `sessionRoute(id)` percent-encodes. `primaryRouteSelectedSessionId(pathname, storeSelected)` prefers the route's stable stored id over a momentarily-null store selection mid-switch (#59305), with a genuine new-chat route always winning with `null`.
- **Inputs / options:** `contributedRoutes()` reads the `routes` registry area, where a contribution's `data.path` must be an absolute single-segment path with a `render`, and reserved paths are rejected. `SIDEBAR_NAV_AREA = 'sidebar.nav'` takes `{codicon, label, path}` to add a matching sidebar row.
- **Outputs / side effects:** `$workspaceIsPage` mirrors "the workspace pane is showing a full page"; `syncWorkspaceRoute(pathname)` sets it and FRONTS the workspace pane for page routes (a main zone parked on a session tile otherwise kept the tile on screen while the route changed behind it, #72602); `navigateToWorkspacePage(navigate, to, options)` additionally covers the RE-CLICK case that a route-change effect cannot see.
- **Config / env:** n/a
- **Edge cases / guards:** Overlays do not count as workspace pages — they float over whatever the workspace already shows.
- **Rebuild notes:** Classify by pathname only; make "navigate and reveal" one function so every entry point (sidebar, keybinds, palette, Command Center, contributed statusbar/titlebar targets, back/forward, cold-start restore) behaves identically.

### Layout presets and the `apply_layout` tool  `id: desktop-a.layout-presets`
- **Surface:** Tool / Desktop app
- **Where:** Tool `apply_layout` (toolset `desktop_ui`, emoji 🧱) at `tools/apply_layout_tool.py`; renderer side `store/pane-focus.ts` and `components/pane-shell/tree/presets.ts`.
- **What it does:** Lets the agent rearrange the desktop workspace by applying a named layout preset.
- **How it works:** The tool emits `layout.apply {preset}` over the shared `desktop_ui` bridge, which the GUI gateway enables only for desktop-sourced sessions. The renderer's `desktop-bridge.ts:261-270` handles the event ONLY for the active session (a background turn must never rearrange the user's desktop) and calls `applyDesktopLayoutPreset(preset)`, which resolves the id against the `layouts` contribution registry — the SAME list the layout picker renders, so core, plugin and user-saved presets are all addressable — and applies it through `applyLayoutPreset(id, tree)` (a `structuredClone` so live edits never mutate the preset).
- **Inputs / options:** One required string argument `preset`. Schema description: *"Apply a saved layout preset to the Hermes desktop app when the user asks to rearrange the workspace. Built-ins: default (chat + sidebars), focus (chat only), terminal-deck, quad; plugin/user presets by id. To reveal ONE pane, use focus_pane instead."* The four built-ins are registered in `app/contrib/controller.tsx:435-440`:
  - `default` — title `"Default"`, order 0: a row of `sessions | workspace | (column of (row of review | files) over terminal)` with weights `[1, 3.4, 1.25]`, inner weights `[1, 1.2]` and `[1.6, 1]`.
  - `focus` — title `"Focus"`, order 10: a row of `sessions | {workspace, files, review, terminal}` (one stacked group) with weights `[1, 4.6]`.
  - `terminal-deck` — title `"Terminal deck"`, order 20: a column of `(row of sessions | workspace | {files, review})` over `terminal`, weights `[3, 1]` and `[1, 3.2, 1.2]`.
  - `quad` — title `"Quad"`, order 30: a column of `(row of {sessions, files} | workspace)` over `(row of terminal | review)`, weights `[3, 1]`, `[1, 3]` and `[1.4, 1]`.
- **Outputs / side effects:** On success returns `{"success": true, "preset": "<name>"}`. Errors: `preset is required — a layout preset id, e.g. 'default' or 'focus'.` when blank; `Failed to apply layout '<name>': <exc>` on an emit exception; `Layout apply is only available in the Hermes desktop app.` when the bridge does not answer.
- **Config / env:** Preset ids are free-form on purpose — plugins and users mint their own.
- **Edge cases / guards:** The sibling `focus_pane` tool reveals ONE pane through `revealDesktopPane(name)`, whose `PANE_REVEALERS` map is exactly `chat` → `revealTreePane('workspace')`, `files` → `setFileBrowserOpen(true)`, `review` → `openReview()`, `sessions` → `setSidebarOpen(true)`, `terminal` → `setTerminalTakeover(true)`; `files` and `review` are workspace-gated and no-op without a project cwd.
- **Rebuild notes:** Resolve agent-addressable layout ids against the same registry the UI picker reads, so core, plugin and user presets are equally reachable; gate the effect on the ACTIVE session.

### Layout picker (preset cards)  `id: desktop-a.layout-picker`
- **Surface:** Desktop app
- **Where:** Inside the layout edit palette opened by the titlebar layout button. `components/pane-shell/tree/renderer/layout-picker.tsx`.
- **What it does:** Applies a layout preset from a card grid, saves the current arrangement as a user preset, deletes user presets, and opens the zone editor.
- **How it works:** Reads `useContributions('layouts')` and splits it into templates (`!isUserPreset`) and custom (`isUserPreset`). Each card renders a `TreeThumbnail` — a miniature recursive render of the preset's `LayoutNode`, with group leaves filled by `color-mix(in srgb, currentColor 16%, transparent)` and splits flexed by their weights — over the preset title, with an accent border when it is the active preset (`$activePresetId`). Clicking applies it.
- **Inputs / options:** Section labels **"Templates"** and **"Custom"** (`i18n: zones.templates` / `zones.custom`); a 4-column card grid per section; a hover-revealed `close` codicon on each user card (`aria-label` from `i18n: zones.deletePreset(name)`) calling `deleteUserPreset(id)`; a dashed **"New grid layout"** button (`i18n: zones.newGridLayout`, `add` codicon) opening `$zoneEditorOpen`; and a "save current arrangement" name field committing through `saveCurrentLayoutAs(name)`. The save-current control is a reveal: collapsed it is a small text button with a `save` codicon labelled **"Save current arrangement as a template"** (`i18n: zones.saveCurrentAs`, `layout-picker.tsx:198`); clicking it swaps in a `<form>` holding an autofocused `Input` whose placeholder is **"Name this layout…"** (`i18n: zones.nameLayoutPlaceholder`, `layout-picker.tsx:181`) plus a **"Save"** submit button (`i18n: common.save`, disabled while the name is blank) and a **"Cancel"** ghost button (`i18n: common.cancel`); Escape inside the input clears the name and closes the form.
- **Outputs / side effects:** `saveLayoutPresetTree(name, tree)` slugifies the name into `user-<slug>` (falling back to a base-36 timestamp), stores it in `localStorage['hermes.desktop.layoutPresets.v2']` as `{name, tree}`, registers it as a `layouts` contribution with `source: 'user'`, and marks it active. `deleteUserPreset` removes it and disposes the registration.
- **Config / env:** `hermes.desktop.layoutPresets.v1` is explicitly wiped at module load (v1 presets predate semantic placement).
- **Edge cases / guards:** Bundled plugins load AFTER core, so a same-id contribution from a plugin deliberately overrides the core default (last writer wins).
- **Rebuild notes:** n/a

### Desktop keyboard shortcuts (default bindings)  `id: desktop-a.keybinds`
- **Surface:** Desktop app / Config
- **Where:** The single source of truth is `lib/keybinds/actions.ts`; the user-facing surface is Settings → Keyboard shortcuts (`/settings?tab=keybinds`), opened by `mod+/`. Panel copy: title `"Keyboard shortcuts"` (`i18n: keybinds.title`), subtitle `"Click a shortcut to rebind it · <combo> reopens this panel."` (`i18n: keybinds.subtitle`), search `"Search shortcuts…"`, buttons `"Rebind"`, `"Reset to default"`, `"Reset all"`, capture prompt `"Press a key…"`, `"set"`, and the conflict note `"Also bound to “<label>”"` (`i18n: keybinds.rebind|reset|resetAll|pressKey|set|conflictWith`). Categories: `"Composer"`, `"Profiles"`, `"Session"`, `"Navigation"`, `"View"` (`i18n: keybinds.categories.*`).
- **What it does:** Defines every rebindable desktop hotkey, its default combo, and the read-only shortcuts listed for completeness.
- **How it works:** Each entry is pure metadata `{id, category, defaults}`; handlers are wired separately in `app/hooks/use-keybinds.ts` and labels come from `i18n: keybinds.actions[id]`. `mod` renders as Cmd on macOS and Ctrl elsewhere; a literal `ctrl` stays Control on every platform.
- **Inputs / options:** The complete rebindable table (id — label — default combos):
  - *Composer:* `composer.focus` — "Focus composer" — `/`, `enter`; `composer.modelPicker` — "Open model picker" — `mod+shift+m`; `composer.voice` — "Start / stop voice conversation" — `ctrl+b` on macOS, unbound elsewhere.
  - *Profiles:* `profile.default` — "Switch to default profile" — `mod+d`; `profile.switch.1` … `profile.switch.18` — "Switch to profile N" — `mod+1` … `mod+9` for 1-9 and `mod+alt+1` … `mod+alt+9` for 10-18; `profile.next` — "Next profile" — `mod+shift+]`; `profile.prev` — "Previous profile" — `mod+shift+[`; `profile.toggleAll` — "Toggle all-profiles view" — `mod+shift+0`; `profile.create` — "Create profile" — unbound.
  - *Session:* `session.new` — "New session" — `mod+n`; `session.newTab` — "New session tab" — `mod+t`; `session.newWindow` — "New window" — `mod+shift+n`; `session.next` — "Next session" — `ctrl+tab`, `ctrl+pagedown`; `session.prev` — "Previous session" — `ctrl+shift+tab`, `ctrl+pageup`; `session.slot.1` … `session.slot.9` — "Switch to recent session N" — `ctrl+1` … `ctrl+9`; `session.focusSearch` — "Search sessions" — `mod+shift+f`; `session.togglePin` — "Pin / unpin current session" — unbound; `session.archive` — "Archive current session" — unbound; `workspace.newWorktree` — "New worktree" — `mod+shift+b`; `workspace.openFolder` — "Open folder as project" — `mod+o`.
  - *Navigation:* `nav.commandPalette` — "Open command palette" — `mod+k`, `mod+p`; `nav.commandCenter` — "Open command center" — `mod+.`; `nav.settings` — "Open settings" — `mod+,`; `nav.profiles` — "Open profiles" — unbound; `nav.skills` — "Open skills" — unbound; `nav.messaging` — "Open messaging" — unbound; `nav.artifacts` — "Open artifacts" — unbound; `nav.cron` — "Open scheduled jobs" — unbound; `nav.agents` — "Open agents" — unbound.
  - *View:* `view.toggleSidebar` — "Toggle sessions sidebar" — `mod+b`; `view.toggleRightSidebar` — "Toggle file browser" — `mod+j`; `view.toggleStatusbar` — "Toggle status bar" — `mod+shift+s`; `view.toggleTabStrip` — "Toggle tabs" — `mod+alt+t`; `view.toggleReview` — "Toggle review pane" — `mod+g`; `view.showFiles` — "Show file browser" — unbound; `view.showBrowser` — "Open browser" — `mod+shift+l`; `view.toggleHud` — "Toggle HUD mode" — `mod+shift+h`; `view.showTerminal` — "Toggle terminal" — `` ctrl+` ``; `view.newTerminal` — "New terminal" — `` ctrl+shift+` ``; `view.nextTerminal` — "Next terminal" — `ctrl+shift+down`; `view.prevTerminal` — "Previous terminal" — `ctrl+shift+up`; `view.closeTerminal` — "Close terminal" — `ctrl+shift+w`; `view.flipPanes` — "Swap sidebar sides" — `mod+\`; `view.closeTab` — "Close tab" — `mod+w`; `view.reopenTab` — "Reopen closed tab" — `mod+shift+t`; `view.findInPage` — "Find in page" — `mod+f`; `view.findNext` — "Find next match" — unbound; `view.findPrevious` — "Find previous match" — unbound; `appearance.toggleMode` — "Toggle light / dark" — `shift+x`; `keybinds.openPanel` — "Open keyboard shortcuts" — `mod+/`.
  - Read-only rows (`KEYBIND_READONLY`, listed so the map is complete): `composer.send` — "Send message" — `enter`; `composer.newline` — "Insert newline" — `shift+enter`; `composer.steer` — "Steer the running turn" — `enter`; `composer.queue` — "Queue message" — `mod+enter`; `composer.sendQueued` — "Send next queued turn" — `mod+shift+k`; `composer.mention` — "Reference files, folders, URLs" — `@`; `composer.slash` — "Slash command palette" — `/`; `composer.help` — "Quick help" — `?`; `composer.history` — "Cycle popover / history" — `up`, `down`; `composer.cancel` — "Close popover · cancel run" — `escape`; `composer.focus` (fixed variant) — `mod+l`; `view.selectionToComposer` — "Send selection to composer" — `mod+l`; `view.terminalCopy` — "Copy terminal selection" — `mod+c` on macOS, `mod+shift+c` elsewhere; `view.terminalPaste` — "Paste into terminal" — `mod+v` on macOS, `mod+shift+v` elsewhere; `hud.snapToPointer` — "Move HUD to pointer (global, while HUD is open)" — `mod+shift+g`.
- **Outputs / side effects:** Overrides persist through `store/keybinds`; contributed keybinds (`KEYBINDS_AREA = 'keybinds'`, payload `{id, category?, defaults?, label, run}`) are first-class — they dispatch, appear in the panel, are rebindable, and their overrides persist, but they cannot shadow a built-in id.
- **Config / env:** `PROFILE_SLOT_COUNT = 18`, `SESSION_SLOT_COUNT = 9`.
- **Edge cases / guards:** `shift+n` was dropped from `session.new`'s defaults (#76185) because a bare shifted letter hijacked normal typing. `composer.voice` ships unbound off macOS because `ctrl` folds to `mod` there and would steal `⌘B`/`Ctrl+B` from the sidebar. `view.findNext`/`view.findPrevious` ship unbound because `mod+g` already belongs to `view.toggleReview`; while the find bar is OPEN its own capture-phase listener claims `mod+g`/`mod+shift+g` and stops propagation. `view.toggleTabStrip` ships BOUND (unlike VS Code's settings-only switch) because hiding the tab strip can remove every other affordance a zone had. The dispatcher ignores keystrokes while `event.isComposing` — Windows Chinese IMEs use `Ctrl+,` as a punctuation-mode toggle, which otherwise matched `nav.settings` and destroyed the unsent draft (#41079) — and swallows everything while the panel is in capture mode.
- **Rebuild notes:** Keep action metadata, handlers and labels in three separate places so adding a hotkey touches exactly two files; ship irreversible-feeling actions unbound but listed.

### Page layout constants  `id: desktop-a.layout-constants`
- **Surface:** Desktop app (Core)
- **Where:** `app/layout-constants.ts`.
- **What it does:** The shared responsive gutters, content cap and sidebar collapse breakpoint.
- **How it works:** `PAGE_INSET_X = 'px-[clamp(1.25rem,4vw,4rem)]'` (ratio-based so it scales with the window, clamped so it never collapses on narrow widths or runs away on ultrawide); `PAGE_INSET_NEG_X = '-mx-[clamp(1.25rem,4vw,4rem)]'` for bleeding a sticky header out to the gutter edges; `PAGE_MAX_W = 'max-w-[75rem]'` as the readable cap for overlay inner pages; `SIDEBAR_COLLAPSE_BREAKPOINT_PX = 768` and `SIDEBAR_COLLAPSE_MEDIA_QUERY = '(max-width: 768px)'` — below this a docked sidebar leaves no room for content, so both rails auto-collapse into the hover-reveal overlay.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** These must stay LITERAL strings — Tailwind's scanner only picks up complete class names, so they cannot be built by template interpolation.
- **Rebuild notes:** n/a

---

## 12. Small shared pieces and loose ends

### openSession — the single "open this session" door  `id: desktop-a.open-session`
- **Surface:** Desktop app (Core)
- **Where:** `app/open-session.ts`; used by the sidebar, the command palette, notifications, the session switcher, session refs, cron and artifacts.
- **What it does:** Decides whether opening a chat focuses an existing tile, loads it into main, stacks a new tab, or pops a window — so a chat that is already on screen is JUMPED TO rather than yanked into main.
- **How it works:** `OpenSessionIntent = 'in-place' | 'main' | 'stack' | 'tab' | 'window'`. `in-place` (sidebar click/Enter) focuses an existing tile or main if on screen, else loads into main. `stack` (the palette, notifications — anything opening a chat from outside the workspace) behaves like `tab` but may spend main or an open blank draft tab when either is empty. `tab` (mod-click, `mod+Enter`, session refs) focuses if already on screen, else opens a stacked session tab and never steals main. `window` (`shift+mod`-click) pops it into its own window, falling back to `tab` when the bridge has no session-window support. `mainChatOccupied(activeSessionId, selectedStoredSessionId)` decides whether main holds a conversation worth preserving — a blank draft has nothing to lose. `openSessionIntentFromModifiers(event, base)` reads meta OR ctrl for `tab` and adds shift for `window`, with `base` naming what an unmodified select means for the caller (the sidebar passes `in-place`, the palette passes `stack`).
- **Inputs / options:** `openSession(sessionId, navigate, intent?, scope?)` where `OpenSessionWorkspaceScope = {ownerRoute?, workspaceMode, workspaceOwnerKey?, workspaceTabTitle?}`.
- **Outputs / side effects:** Route navigation, tile focus/creation, `markSessionRead`, a new window.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Model "open" as an intent with a caller-supplied default, not as a boolean "new tab".

### Command-palette StatusRow  `id: desktop-a.palette-status-row`
- **Surface:** Desktop app (Core)
- **Where:** `app/command-palette/status-row.tsx`; used by the Pets and Install-theme pages.
- **What it does:** The centred loading / empty / error row inside a palette page's result list.
- **How it works:** `StatusRow({icon, text, tone})` renders a centred `px-2 py-6 text-xs` row, muted by default and `text-(--ui-red)` when `tone === 'error'`.
- **Inputs / options:** `icon` (usually a spinning `Loader2`), `text`, `tone: 'error' | undefined`.
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Overlay translucency peek scoping  `id: desktop-a.overlay-peek-scope`
- **Surface:** Desktop app (Core)
- **Where:** The CSS selector `[data-overlay-surface]:has([data-translucency-peek-scope])`, asserted by `app/overlays/peek-scope.test.ts`.
- **What it does:** Makes only the ONE overlay that owns the translucency control pay for the peek opacity transition, so the other open overlays are unaffected.
- **How it works:** The settings overlay stamps `data-translucency-peek-scope` on the row that arms the interaction; the `:has()` selector then matches that overlay's `[data-overlay-surface]` root and no other. The test asserts a marked overlay matches and an unmarked one (e.g. the command center) does not.
- **Inputs / options:** n/a
- **Outputs / side effects:** A scoped opacity transition on one overlay card.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Sidebar panel label  `id: desktop-a.sidebar-panel-label`
- **Surface:** Desktop app (Core)
- **Where:** `app/shell/sidebar-label.tsx`; the small caps heading used by the file-browser header, the review header, and pane empty states.
- **What it does:** The app's uniform panel-title voice: a dithered square dot followed by tightly-tracked uppercase text in the theme's primary colour.
- **How it works:** `SidebarPanelLabel({children, className, dotClassName, ...spanProps})` renders `flex items-center gap-2 pl-2 text-[0.64rem] font-semibold uppercase tracking-[0.16em] text-(--theme-primary)` with an `aria-hidden` `size-2 rounded-[1px] dither` dot and a truncating label span.
- **Inputs / options:** `dotClassName` recolours the dot; `PaneEmptyState` reuses it muted (`text-(--ui-text-quaternary)`, `pl-0`) and centred.
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### GroupSetter contract (pane extension point)  `id: desktop-a.group-setter`
- **Surface:** Desktop app (extension API)
- **Where:** `app/shell/group-setter.ts`; the prop shape pages take (SkillsView, MessagingView, ChatPreviewRail, …).
- **What it does:** Lets a page publish a named group of items (titlebar tools, statusbar items) into a chosen side of the shell.
- **How it works:** `type GroupSetter<T> = (id: string, items: readonly T[], side?: 'left' | 'right') => void`. The live implementation is the registry-backed `registryGroupSetter` in `app/contrib/panes.tsx`; the specialised aliases are `SetTitlebarToolGroup` and `SetStatusbarItemGroup`.
- **Inputs / options:** `id` (the group's stable key), `items`, `side`.
- **Outputs / side effects:** The shell re-renders that side's cluster.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Unreferenced chrome strings (present in the catalog, not rendered in v2026.8.31)  `id: desktop-a.orphan-strings`
- **Surface:** Docs / i18n
- **Where:** `src/i18n/en.ts`.
- **What it does:** Records the shell/titlebar strings that ship in the locale files but have no live call site in this tag, so a mechanical string-to-feature checker does not report them as missing coverage.
- **How it works:** A grep across `apps/desktop/src` (excluding `src/i18n`) finds no consumer for: `titlebar.search` (`"Search"`), `titlebar.searchTitle` (`"Search sessions, views, and actions"`), `titlebar.openStarmap` (`"Open memory graph"`), `shell.statusbar.starmap` (`"Memory Graph"`), and `shell.statusbar.openStarmap` (`"Open memory graph"`) — the memory-graph entry point currently lives only in the command palette's `nav-starmap` row and in `useOverlayRouting().openStarmap`. Several other `shell.statusbar.*` strings ARE live but belong to sibling shards' surfaces rather than to the status bar: `yoloOn` (`"YOLO on — auto-approving dangerous commands. Shift+click toggles globally."`), `yoloOff` (`"YOLO off. Shift+click toggles globally."`), `modelNone` (`"none"`), `noModel` (`"no model"`), `switchModel` (`"Switch model"`), `openModelPicker` (`"Open model picker"`), `modelPinned` (`"pinned by you; new chats use this instead of the Settings default"`), `modelTitle(provider, model)` (`"Model · <provider>: <model>"`) and `providerModelTitle(provider, model)` (`"<provider> · <model>"`) are consumed by the composer's model pill (`app/chat/composer/model-pill.tsx`) and the YOLO slash command (`app/session/hooks/use-prompt-actions/slash.ts`). Likewise `commandCenter.providerNavigate` (`"Navigate"`), `providerSessions` (`"Sessions"`), `refresh` (`"Refresh"`), `refreshing` (`"Refreshing..."`), `gatewayRestartFailed` (`"Gateway restart failed."`), `statCost` (`"Est. cost"`), `actualCost(cost)` (`"actual <cost>"`), `logFile` (`"Log file"`), `logLevel` (`"Level"`), `sectionEntries.*` (`"Sessions panel"` / `"Search, pin, and manage sessions"`, `"System panel"` / `"Gateway status, logs, restart/update"`, `"Usage panel"` / `"Token, cost, and skill activity"`), `nav.newChat.detail` (`"Start a fresh session"`), `nav.settings.detail` (`"Configure Hermes desktop"`), `nav.skills.detail` (`"Skills, tools, and MCP servers"`), `nav.messaging.detail` (`"Set up Telegram, Slack, Discord, and more"`) and `nav.artifacts.detail` (`"Browse generated outputs"`) are catalog entries the current Command Center/palette markup does not render (the `detail` strings were used by an older card-grid Command Center; the palette shows labels only).
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** The full `commandCenter.generatePet.*` sub-tree (`promptHint`, `readyHint`, `generate`, `generating`, `retry`, `hatch`, `spawning`, `hatching`, `hatchingSub`, `hatched`, `hatchRow`, `hatchComposing`, `hatchSaving`, `namePlaceholder`, `staleBackend`, `backgroundHint`, `slowProviderHint`, `remix`, `remixConfirmTitle`, `remixConfirmBody`, `genericError`, `referenceImageTooLarge`, `referenceImageInvalid`, `adopt`, `startOver`, `placeholder`) belongs to the pet-generation flow in `app/pet-generate/**`, which is outside this shard — only its entry-point label `"Generate a pet"` is documented here.
- **Rebuild notes:** Keep an automated orphan check so retired surfaces do not leave dead copy behind.

---

## Handoffs

- `app/chat/**` — the composer, transcript, message renderers, model pill, session tiles and the `shell.statusbar.yoloOn|yoloOff|modelNone|noModel|switchModel|openModelPicker|modelPinned|modelTitle|providerModelTitle` strings it consumes. (chat shard)
- `app/settings/**` and `app/settings/settings-search.ts` — the Settings overlay, its sections, the search catalog (`useSettingsSearchCatalog`) whose entries the palette lists, and the `settings.*` i18n subtree. (`desktop-settings`)
- `app/pet-generate/**` and `store/pet-gallery` — the pet generation flow behind the palette's "Generate a pet" row, plus `commandCenter.generatePet.*`. (desktop shard B)
- `app/pet-overlay/**` — the floating desktop pet window.
- `app/agents/`, `app/cron/`, `app/profiles/`, `app/starmap/`, `app/webhooks/`, `app/artifacts/`, `app/skills/`, `app/messaging/`, `app/learning/` — the overlay/page bodies that mount inside the primitives documented here.
- `components/pane-shell/**` — the layout tree engine, zone editor, tab strips, edit mode, and `zones.*` i18n beyond the layout picker.
- `app/right-sidebar/terminal/{persistent,instance,terminals,use-terminal-session,buffer,clipboard,links,selection,terminal-font,active-resize,agent-terminal-stream}.ts(x)` — the xterm runtime, PTY session lifecycle, revive buffers, font handling and agent terminal mirroring.
- `app/right-sidebar/files/use-project-tree.ts` and `files/ipc.ts` internals — gitignore rule resolution, workspace-change reconciliation, and remote FS caching.
- `store/review` — the git working-tree store behind the review pane (scopes, staging, PR/ship RPCs).
- `store/updates` — the update check/apply state machine that the updates overlay renders.
- `apps/desktop/electron/**` — main-process HUD windowing (`spawnHudWindow`, `hudFrostFor`, `startHudCursorFeed`, `startHudGameOverlayFeed`, `hud-drag.ts`), Quick Entry global-shortcut registration, wake-indicator window, `titlebar-overlay-width.ts`, and the `contextMenuEdit` / `contextMenuSpellcheck` / `saveImageFromUrl` IPC handlers.
- `tools/desktop_ui.py` and `tools/focus_pane_tool.py` — the desktop_ui bridge and the sibling `focus_pane` tool referenced by `apply_layout`.
- `web/` — the dashboard SPA (separate `web-*` shards).
