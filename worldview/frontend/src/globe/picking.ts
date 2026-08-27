import { ScreenSpaceEventHandler, ScreenSpaceEventType, type Viewer } from "cesium";
import { tooltipHtml } from "@/lib/tooltip";
import type { PickPayload } from "./render";

// Hover + click on the globe. Cesium hands back the `id` we attached to each mark, which is the
// PickPayload the scene builder produced — so the tooltip and the selection read the very same
// properties the Inspector will show. Feed values are HTML-escaped in lib/tooltip.ts.

export interface PickingHandlers {
  onSelect: (payload: PickPayload | null) => void;
}

function payloadOf(picked: unknown): PickPayload | null {
  const id = (picked as { id?: unknown } | undefined)?.id;
  if (!id || typeof id !== "object") return null;
  const candidate = id as Partial<PickPayload>;
  if (typeof candidate.layer !== "string" || candidate.props == null) return null;
  return candidate as PickPayload;
}

export function createPicking(viewer: Viewer, handlers: PickingHandlers) {
  const handler = new ScreenSpaceEventHandler(viewer.canvas);

  const tip = document.createElement("div");
  tip.className = "wv-tip";
  tip.style.display = "none";
  tip.setAttribute("role", "tooltip");
  viewer.container.appendChild(tip);

  handler.setInputAction((movement: ScreenSpaceEventHandler.MotionEvent) => {
    const payload = payloadOf(viewer.scene.pick(movement.endPosition));
    const html = payload ? tooltipHtml(payload.layer, payload.props) : null;
    if (!html) {
      tip.style.display = "none";
      return;
    }
    tip.innerHTML = html;
    tip.style.display = "block";
    // Offset from the cursor, flipped near the right/bottom edge so the card stays on screen.
    const { clientWidth, clientHeight } = viewer.container as HTMLElement;
    const x = movement.endPosition.x;
    const y = movement.endPosition.y;
    const flipX = x > clientWidth - 240;
    const flipY = y > clientHeight - 120;
    tip.style.left = `${flipX ? x - 16 - tip.offsetWidth : x + 16}px`;
    tip.style.top = `${flipY ? y - 16 - tip.offsetHeight : y + 16}px`;
  }, ScreenSpaceEventType.MOUSE_MOVE);

  handler.setInputAction((click: ScreenSpaceEventHandler.PositionedEvent) => {
    handlers.onSelect(payloadOf(viewer.scene.pick(click.position)));
  }, ScreenSpaceEventType.LEFT_CLICK);

  return {
    destroy() {
      handler.destroy();
      tip.remove();
    },
  };
}
