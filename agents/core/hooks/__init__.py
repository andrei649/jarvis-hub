"""G17 — owner event hooks (H163, H021, H514, H408; the observation half of H080).

An owner hook is a program the owner names that Nerva runs when something happens in a
turn: before or after a tool call, when a message arrives or a turn ends, when a session
starts or ends, after a slash command, and when an approval is asked or decided.

* :mod:`.store` — the event catalogue, the hook definitions (``<data>/hooks/hooks.json``),
  the argv rules and the approval card (``hooks.define`` at the irreversible tier).
* :mod:`.runner` — one governed run (kernel ``hook.exec``, the local host transport,
  event JSON on stdin), the wire protocol, the audit trail, and the two entry points the
  hub calls: :func:`.runner.before_tool` (may block, never allow) and
  :func:`.runner.observe` (fire and forget).

Docs: ``docs/HOOKS.md``.
"""
