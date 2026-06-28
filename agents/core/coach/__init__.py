"""coach — 0.43 Learning Coach Pack (spaced repetition + curriculum planning).

A pure, offline, stateless study-coach pack: SM-2 spaced repetition, a due/new
review-session builder, and a prerequisite-ordered curriculum planner. It schedules
and plans; it never generates lesson content and never persists. See :mod:`.pack`.
"""

from .pack import build_session, is_due, plan_curriculum, review

__all__ = ["review", "is_due", "build_session", "plan_curriculum"]
