// A very small direct-DOM rendering helper — the whole "framework" this app has.
//
// Each HUD surface is a function that returns HTML for its current state; `mount` swaps that
// HTML into a host element and coalesces re-renders into one animation frame. Events are
// DELEGATED from the host via `data-act` attributes, so a re-render never has to rebind
// anything, and focus + caret position are preserved across renders so typing into the export
// panel survives the master clock ticking underneath it.

/** HTML-escape a value for interpolation into a template. Feed data is external input. */
export function esc(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Join conditional class names ("" / false / null are dropped). */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export type ActionHandler = (event: Event, element: HTMLElement, arg: string) => void;

export interface MountOptions {
  /** The surface's HTML for the current state. */
  render: () => string;
  /** Delegated handlers, keyed by the `data-act` value that triggers them. */
  actions?: Record<string, ActionHandler>;
  /** Delegated `input`/`change` handlers, keyed by the `data-input` value. */
  inputs?: Record<string, ActionHandler>;
}

export interface Surface {
  /** Request a re-render on the next frame (idempotent within a frame). */
  update(): void;
  destroy(): void;
}

function focusKeyOf(node: Element | null): string | null {
  if (!node || !(node instanceof HTMLElement)) return null;
  return node.dataset.focusKey ?? null;
}

export function mount(host: HTMLElement, options: MountOptions): Surface {
  let frame = 0;
  let disposed = false;

  function paint() {
    frame = 0;
    if (disposed) return;

    // Preserve the focused control (and its caret) across the innerHTML swap.
    const activeKey = host.contains(document.activeElement) ? focusKeyOf(document.activeElement) : null;
    const active = document.activeElement;
    const caret =
      activeKey && active instanceof HTMLInputElement ? active.selectionStart : null;

    host.innerHTML = options.render();

    if (activeKey) {
      const restored = host.querySelector<HTMLElement>(`[data-focus-key="${CSS.escape(activeKey)}"]`);
      if (restored) {
        restored.focus();
        if (caret != null && restored instanceof HTMLInputElement) {
          restored.setSelectionRange(caret, caret);
        }
      }
    }
  }

  function dispatch(map: Record<string, ActionHandler> | undefined, attribute: string) {
    return (event: Event) => {
      if (!map) return;
      const target = (event.target as HTMLElement | null)?.closest<HTMLElement>(`[data-${attribute}]`);
      if (!target || !host.contains(target)) return;
      const name = target.dataset[attribute === "act" ? "act" : "input"];
      if (!name) return;
      const handler = map[name];
      if (!handler) return;
      handler(event, target, target.dataset.arg ?? "");
    };
  }

  const onClick = dispatch(options.actions, "act");
  const onInput = dispatch(options.inputs, "input");

  host.addEventListener("click", onClick);
  host.addEventListener("input", onInput);
  host.addEventListener("change", onInput);

  paint();

  return {
    update() {
      if (disposed || frame !== 0) return;
      frame = requestAnimationFrame(paint);
    },
    destroy() {
      disposed = true;
      if (frame !== 0) cancelAnimationFrame(frame);
      host.removeEventListener("click", onClick);
      host.removeEventListener("input", onInput);
      host.removeEventListener("change", onInput);
      host.innerHTML = "";
    },
  };
}

/** Create a host element with classes, appended to `parent`. */
export function host(parent: HTMLElement, className: string, tag = "div"): HTMLElement {
  const el = document.createElement(tag);
  el.className = className;
  parent.appendChild(el);
  return el;
}

/** UTC "HH:MM:SS" for a UNIX-seconds timestamp. */
export function clockText(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(11, 19);
}

/** UTC "HH:MM" for a UNIX-seconds timestamp. */
export function shortClock(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(11, 16);
}
