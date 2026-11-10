"""``hermes_cli.config`` and ``tools.delegate_tool`` for the vendored ``agent/review_engine.py``
(rules ``review-config`` and ``review-delegate``, G18 / H404).

Nerva adopts the review engine for its text: the reviewer goal, the conversation
snapshot and the briefing (``snapshot_recent_messages``, ``build_review_task``). The two
imports it makes inside functions are answered here:

* ``load_config_readonly`` returns an empty config: Nerva has no ``auxiliary.review``
  section, so ``_load_review_credentials_cfg`` answers None and the reviewer runs on
  Nerva's own sub-agent model choice (``autonomy.subagent_model`` or the agent's route).
* ``delegate_task`` refuses. Upstream's ``start_review`` would dispatch a
  full-privilege background child through it; Nerva never calls ``start_review``.
  ``agents/core/review_command.py`` spawns the reviewer itself, read-only, through the
  one spawn gate. A vendored path that reached this would get an error, never a child.
"""

from __future__ import annotations

import json
from typing import Any


def load_config_readonly() -> dict[str, Any]:
    return {}


def delegate_task(**_kwargs: Any) -> str:
    return json.dumps({"error": "Nerva dispatches /review itself: the reviewer is a read-only "
                                "sub-agent started through Nerva's spawn gate."})


__all__ = ["delegate_task", "load_config_readonly"]
