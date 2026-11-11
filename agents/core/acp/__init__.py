"""G11 — Nerva as a coding agent inside an editor, over the Agent Client Protocol (ACP).

ACP is JSON-RPC 2.0 over the stdio of a process the editor launches (``nerva acp``).
This package is the editor-facing half and is standard library only, so the CLI can
import it in a broken install:

* :mod:`.jsonrpc` — newline-delimited JSON-RPC framing with a per-message size bound,
  request/response correlation for the agent's own requests to the editor
  (``session/request_permission``, ``fs/read_text_file``) and fail-closed teardown.
* :mod:`.paths` — every path the editor names is confined to the session's working
  directory (no traversal, no symlink escape, bounded reads).
* :mod:`.render` — what the editor shows: tool-call kinds and titles, the approval
  card as a real diff or the real command, the plan panel.
* :mod:`.server` — the ACP agent itself. It holds **no** agent loop and **no** approval
  logic of its own: every turn runs in the hub's normal runtime (``POST /chat/stream``),
  and every permission the editor answers is posted to the same decision route the HUD's
  approval card uses (``POST /autonomy/tasks/{id}/decision``). The editor is one more
  surface for the owner's decision, never a bypass.

The hub-side half — the session registry that binds a hub conversation to the editor's
folder and owns the session-scoped MCP servers — is :mod:`.sessions` (imported by the
hub only) and ``agents/core/routers/acp.py``.
"""

PROTOCOL_VERSION = 1

__all__ = ["PROTOCOL_VERSION"]
