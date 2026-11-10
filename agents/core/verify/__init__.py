"""G5 — project verification and the coding posture (Hermes H023, H405, H406).

What the owner and the model get, and where it lives:

* :mod:`.project` — which project a path belongs to (its git root, else the nearest
  folder with a manifest, never outside the owner's file roots), the project facts (the
  exact test, lint and build commands) and the run recipe. The recipe detection and the
  ``.hermes/environment.json`` manifest are Hermes's own ``agent/verify/recipes.py`` and
  ``environment.py``, adopted (``agents/vendor/hermes/agent/verify/``) behind a confined
  path stand-in (``hermes_compat.verify_fs``).
* :mod:`.runner` — runs a recipe's phases. It never starts a process: every command is a
  ``terminal_run`` call through the tool front door, so the plan-mode floor, the approval
  card, the approval mode, the target policy, the hardline denylist, the
  ``terminal.exec`` contract and the Action Kernel all apply as they do to the model's
  own commands. Refused under the e-stop and in plan mode before anything is queued.
* :mod:`.evidence` — the evidence ledger: what a verification command proved, per
  session and project, hash-chained and anchored in the signed intent log.
* :mod:`.stop` — verify-on-stop: a turn that would end while the session's edited code
  has no fresh passing evidence is handed back to the model once with a nudge.
* :mod:`.workspace` and :mod:`.coding` — the coding posture: a read-only git snapshot,
  the project facts, the coding brief and the edit-format line, in the stable prompt tier.
* :mod:`.command` — ``/verify``, the owner's surface.

Guide: ``docs/hermes/ADOPT_LANE.md`` (slice 5) and ``docs/USER_GUIDE`` verify section.
"""
