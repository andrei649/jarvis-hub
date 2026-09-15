"""Read-only scheduler diagnostics; never execute jobs or inspect credentials."""

from datetime import UTC, datetime


def inspect_jobs(runner) -> dict:
    now = datetime.fromtimestamp(runner._now(), UTC)
    jobs = runner.store.list()
    outcomes = runner.store.scheduler_results()
    script_attempts = {r['job_id']: r for r in runner.store.script_attempts.rows()}
    channels = sorted((getattr(runner._orch, "channels", None) or {}).keys())
    problems = []
    rows = []

    def problem(job_id, code, reason):
        problems.append({"job_id": job_id, "code": code, "reason": reason})

    scheduler = None
    registered = {}
    try:
        scheduler = runner._scheduler()
        if scheduler is not None:
            registered = {str(job.id): job for job in scheduler.get_jobs()}
    except Exception:
        problem(None, "scheduler_unreadable", "Scheduler state could not be read")
    alive = scheduler is not None and bool(getattr(scheduler, "running", False))
    if not alive or getattr(scheduler, "state", 1) != 1:
        problem(None, "scheduler_not_running", "Scheduler is stopped or paused")
    if getattr(scheduler, "_nerva_health_error", False):
        problem(None, "health_recording_failed", "Scheduler outcomes could not be persisted")

    def next_run(job_id, entry):
        value = getattr(entry, "next_run_time", None)
        if value is None:
            problem(job_id, "missing_next_run", "Active job has no next run")
            return None
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            problem(job_id, "invalid_next_run", "Next run must be a timezone-aware timestamp")
            return None
        if value < now:
            problem(job_id, "overdue", "Next run is in the past")
        return value.isoformat()

    owner_ids = {f"job-{job.id}" for job in jobs}
    for job in jobs:
        row = {"job_id": job.id, "active": bool(job.runnable), "next_run_at": None}
        rows.append(row)
        outcome = outcomes.get(f"job-{job.id}")
        row["last_outcome"] = outcome
        if outcome and outcome["status"] not in {"ok", "pending"}:
            problem(job.id, "last_run_" + outcome["status"], "Last scheduled execution did not succeed")
        if job.last_status == "failed":
            problem(job.id, "last_run_failed", "Last execution failed")
        if job.last_delivery_status == "failed":
            problem(job.id, "last_delivery_failed", "Last delivery failed")
        attempt = script_attempts.get(job.id)
        if attempt:
            row['script_state'] = attempt['state']
            row['script_task_id'] = attempt['data'].get('task_id')
        if job.options.get('no_agent') and not job.options.get('script'):
            problem(job.id, 'script_required', 'no_agent requires a script')
        if job.options.get('script'):
            from .jobs_scripts import script_problem
            issue = script_problem(job.options['script'])
            if issue:
                problem(job.id, 'script_unavailable', issue)
        if not job.runnable:
            continue
        entry = registered.get(f"job-{job.id}")
        if entry is None:
            problem(job.id, "not_registered", "Active job is not registered with the scheduler")
        else:
            row["next_run_at"] = next_run(job.id, entry)
        kind = job.action.get("type")
        if kind == "task" or (kind == "ask" and not job.action.get("deliver", True)):
            continue
        targets = job.options.get("deliver", [job.action.get("channel") or "telegram"])
        for target in targets:
            if target not in channels:
                problem(job.id, "channel_unavailable", f"channel {target!r} is not connected")
    for job_id, entry in registered.items():
        if job_id not in owner_ids:
            outcome = outcomes.get(job_id)
            rows.append({"job_id": job_id, "active": True, "next_run_at": next_run(job_id, entry),
                         "last_outcome": outcome})
            if outcome and outcome["status"] not in {"ok", "pending"}:
                problem(job_id, "last_run_" + outcome["status"], "Last scheduled execution did not succeed")

    return {
        "ok": not problems, "checked_at": now.isoformat(), "jobs": rows,
        "scheduler": {
            "alive": alive, "timezone": str(getattr(scheduler, "timezone", "unknown")),
            "registered": sorted(key[4:] for key in registered if key.startswith("job-")),
            "jobs": len(jobs), "runnable": sum(bool(job.runnable) for job in jobs),
            "paused": sum(bool(job.paused_reason) for job in jobs),
            "held": runner.store.held_count(), "quiet_hours": runner.quiet_hours(),
        },
        "channels": channels, "problems": problems,
        "supported_options": ["repeat", "deliver", "script", "no_agent"],
        "script_contract": "Bounded self-contained Python, fresh approval each run; no shell or project cwd",
        "unsupported_options": ["workdir", "model", "provider", "enabled_toolsets", "skills"],
    }
