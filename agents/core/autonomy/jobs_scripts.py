"""Bounded Python job proposals; execution remains in the approved terminal rail.

Source is literal argv in the durable task, never a mutable script pathname.
Interrupted downstream calls are reported unknown, never automatically replayed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import stat
import sys
import time
from dataclasses import replace
from pathlib import Path

from agents.core.paths import data_path

MAX_SOURCE = 2000
LEASE_SECONDS = 300


class ScriptSubmissionRefused(ValueError):
    """The trusted adapter refused before calling governed intake."""


def script_problem(script):
    """Metadata-only check shared by authoring/doctor; never read file contents."""
    if not isinstance(script, str) or not script or len(script) > 1024:
        return 'script must name a bounded Python file'
    root = data_path('scripts').resolve()
    candidate = Path(script)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.relative_to(root)
        if '..' in relative.parts or candidate.suffix != '.py':
            return 'script must be a .py file inside the scripts root'
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return 'script symlinks are not supported'
        if not candidate.is_file():
            return 'script is missing or not a regular file'
    except (ValueError, OSError):
        return 'script is outside the scripts root or unavailable'
    return None


def snapshot_script(script):
    """Read through no-follow descriptors, then bind exact bytes into argv."""
    from agents.core.environments.execution import parse_argv
    from agents.core.environments.terminal_contract import hardline_match

    problem = script_problem(script)
    if problem:
        raise ValueError(problem)
    if os.name != 'posix':
        raise ValueError('scheduled Python scripts currently require a POSIX local target')
    root = data_path('scripts').resolve()
    path = Path(script)
    relative = (path if path.is_absolute() else root / path).relative_to(root)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in relative.parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(child, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE:
                raise ValueError('script must be a regular file of at most 2000 bytes')
            raw = stream.read(MAX_SOURCE + 1)
    finally:
        os.close(fd)
    if len(raw) > MAX_SOURCE:
        raise ValueError('script exceeds 2000 bytes')
    source = raw.decode('utf-8')
    compile(source, str(root / relative), 'exec')
    argv = [sys.executable, '-I', '-c', source]
    command = shlex.join(argv)
    parsed, refusal = parse_argv(command)
    if len(command) > 4000 or refusal or parsed != argv or hardline_match(argv):
        raise ValueError('script cannot cross the existing terminal command contract')
    return {'command': command, 'sha256': hashlib.sha256(raw).hexdigest()}


class ScriptAttempts:
    """Transactions share the job store connection and its existing lock."""
    def __init__(self, store):
        self.store = store
        with store._lock:
            store._conn.execute('''CREATE TABLE IF NOT EXISTS job_script_attempts (
                id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, state TEXT NOT NULL,
                updated REAL NOT NULL, data TEXT NOT NULL)''')
            store._conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS job_script_active
                ON job_script_attempts(job_id) WHERE state IN
                ('preparing','submitting','pending','completing','ready','delivering')''')
            store._conn.commit()

    def rows(self, *, after=0):
        with self.store._lock:
            rows = self.store._conn.execute('SELECT * FROM job_script_attempts WHERE state NOT IN '
                                           "('done','failed') AND id>? ORDER BY id LIMIT 50", (after,)).fetchall()
        return [dict(row, data=json.loads(row['data'])) for row in rows]

    def reserve(self, job, started):
        with self.store._lock:
            conn = self.store._conn
            conn.execute('BEGIN IMMEDIATE')
            try:
                row = conn.execute('SELECT id FROM job_script_attempts WHERE job_id=? AND state NOT IN '
                                   "('done','failed')", (job.id,)).fetchone()
                if row:
                    conn.rollback()
                    return int(row['id'])
                claimed = conn.execute("UPDATE jobs SET attempts=attempts+1 WHERE id=? AND "
                    "(json_extract(options,'$.repeat') IS NULL OR attempts<json_extract(options,'$.repeat'))",
                    (job.id,)).rowcount
                if not claimed:
                    conn.rollback()
                    return None
                run = conn.execute('INSERT INTO job_runs '
                    '(job_id,started_at,finished_at,status,summary) VALUES (?,?,?, ?,?)',
                    (job.id, started, '', 'pending', 'Awaiting a fresh script approval'))
                run_id = run.lastrowid
                data = {'job': {'action': job.action, 'options': job.options, 'notepad': job.notepad,
                                'name': job.name}, 'origin': f'job-script:{job.id}:{run_id}'}
                conn.execute('INSERT INTO job_script_attempts VALUES (?,?,?,?,?)',
                             (run_id, job.id, 'preparing', time.time(), json.dumps(data)))
                conn.execute("UPDATE jobs SET last_status='pending',last_summary=? WHERE id=?",
                             ('Awaiting a fresh script approval', job.id))
                conn.commit()
                return int(run_id)
            except BaseException:
                conn.rollback()
                raise

    def transition(self, row, state, data=None):
        value = row['data'] if data is None else data
        with self.store._lock:
            changed = self.store._conn.execute(
                'UPDATE job_script_attempts SET state=?,updated=?,data=? WHERE id=? AND state=? AND updated=?',
                (state, time.time(), json.dumps(value), row['id'], row['state'], row['updated'])).rowcount
            self.store._conn.commit()
        return bool(changed)

    def finish(self, row, *, error=None):
        from .jobs import MAX_FAILURES, MAX_RUNS_KEPT, MAX_TEXT, utc_now
        now = utc_now()
        status = 'failed' if error else 'ok'
        summary = str(error or row['data'].get('output', ''))[:MAX_TEXT]
        with self.store._lock:
            conn = self.store._conn
            conn.execute('BEGIN IMMEDIATE')
            try:
                changed = conn.execute('UPDATE job_script_attempts SET state=?,updated=? '
                    'WHERE id=? AND state=? AND updated=?',
                    ('failed' if error else 'done', time.time(), row['id'], row['state'], row['updated'])).rowcount
                if not changed:
                    conn.rollback()
                    return False
                conn.execute('UPDATE job_runs SET finished_at=?,status=?,summary=?,error=? WHERE id=?',
                             (now, status, summary, summary if error else None, row['id']))
                conn.execute('UPDATE jobs SET last_run_at=?,last_status=?,last_summary=?, '
                             'consecutive_failures=CASE WHEN ? THEN consecutive_failures+1 ELSE 0 END WHERE id=?',
                             (now, status, summary, bool(error), row['job_id']))
                if error:
                    conn.execute('UPDATE jobs SET paused_reason=? WHERE id=? AND consecutive_failures>=?',
                                 ('Scheduled script repeatedly failed', row['job_id'], MAX_FAILURES))
                if 'notepad' in row['data'] and not error:
                    conn.execute('UPDATE jobs SET notepad=? WHERE id=?', (row['data']['notepad'], row['job_id']))
                conn.execute('DELETE FROM job_script_attempts WHERE job_id=? AND state IN (\'done\',\'failed\') '
                    'AND id NOT IN (SELECT id FROM job_script_attempts WHERE job_id=? ORDER BY id DESC LIMIT ?)',
                    (row['job_id'], row['job_id'], MAX_RUNS_KEPT))
                conn.execute('DELETE FROM job_runs WHERE job_id=? AND id!=? AND id NOT IN '
                    '(SELECT id FROM job_runs WHERE job_id=? AND id!=? ORDER BY id DESC LIMIT ?)',
                    (row['job_id'], row['id'], row['job_id'], row['id'], MAX_RUNS_KEPT - 1))
                conn.commit()
                return True
            except BaseException:
                conn.rollback()
                raise


class ScriptRuntime:
    def __init__(self, runner):
        self.runner = runner
        self.attempts = runner.store.script_attempts
        self.submit = self.get = self.find = None
        self._cursor = 0

    def finish(self, row, *, error=None):
        from .jobs import MAX_FAILURES
        changed = self.attempts.finish(row, error=error)
        job = self.runner.store.get(row['job_id']) if changed else None
        if job is not None:
            if not job.runnable:
                self.runner.unregister(job.id)
            if error and job.consecutive_failures == MAX_FAILURES:
                self.runner._incident(job, str(error), job.consecutive_failures)
        return changed

    def bind(self, *, submit, get, find):
        self.submit, self.get, self.find = submit, get, find

    def row(self, run_id):
        with self.runner.store._lock:
            row = self.runner.store._conn.execute(
                "SELECT * FROM job_script_attempts WHERE id=? AND state NOT IN ('done','failed')",
                (run_id,)).fetchone()
        return dict(row, data=json.loads(row['data'])) if row else None

    def run_result(self, job_id, run_id):
        from .jobs import JobRun
        with self.runner.store._lock:
            row = self.runner.store._conn.execute(
                'SELECT * FROM job_runs WHERE job_id=? AND id=?', (job_id, run_id)).fetchone()
        return JobRun(**dict(row))

    async def fire(self, job, started):
        from .jobs import JobRun, utc_now
        with self.runner.store._lock:
            existing = self.runner.store._conn.execute(
                "SELECT id FROM job_script_attempts WHERE job_id=? AND state NOT IN ('done','failed')",
                (job.id,)).fetchone()
        if existing:
            return self.run_result(job.id, existing['id'])
        run_id = self.attempts.reserve(job, started)
        if run_id is None:
            return JobRun(0, job.id, started, utc_now(), 'skipped', 'repeat limit exhausted')
        row = self.row(run_id)
        # Another connection already reserved this attempt. Only its claim may submit.
        if row is None or row['state'] != 'preparing':
            return self.run_result(job.id, run_id)
        if not self.attempts.transition(row, 'submitting'):
            return self.run_result(job.id, run_id)
        row = self.row(run_id)
        try:
            if not callable(self.submit):
                raise ValueError('governed script intake is unavailable')
            prepared = snapshot_script(row['data']['job']['options']['script'])
            payload = {'tool': 'terminal_run', 'target': 'terminal_run',
                       'args': {'target': 'local-host', 'command': prepared['command'], 'timeout': 60}}
            data = {**row['data'], 'payload': payload, 'sha256': prepared['sha256']}
            if not self.attempts.transition(row, 'submitting', data):
                return self.run_result(job.id, run_id)
            row = self.row(run_id)
            task_id = self.submit(payload, data['origin'])
            if type(task_id) is not int or task_id <= 0:
                raise ValueError('governed script intake returned no task')
            self.attempts.transition(row, 'pending', {**data, 'task_id': task_id})
        except ScriptSubmissionRefused as exc:
            self.finish(row, error=str(exc))
        except Exception as exc:
            # Enqueue may have persisted before raising. Leave its correlation
            # recoverable; never issue a second proposal for this attempt.
            if 'payload' not in row['data']:
                self.finish(row, error=str(exc))
        return self.run_result(job.id, run_id)

    async def reconcile(self):
        from agents.core import estop

        from .jobs import MAX_TEXT, logger
        if estop.check_paused('job-script-completion', logger) or not callable(self.get):
            return 0
        count = 0
        batch = self.attempts.rows(after=self._cursor)
        if not batch and self._cursor:
            batch = self.attempts.rows()
        self._cursor = batch[-1]['id'] if batch else 0
        for original in batch:
            row = self.row(original['id'])
            if row is None:
                continue
            job = self.runner.store.get(row['job_id'])
            if job is None:
                self.finish(row, error='Job deleted; queued task remains separately governed; delivery suppressed')
                continue
            data = row['data']
            frozen = replace(job, **data['job'])
            if row['state'] in ('preparing', 'submitting'):
                matches = self.find(data['origin']) if callable(self.find) else []
                if len(matches) == 1 and 'payload' in data:
                    self.attempts.transition(row, 'pending', {**data, 'task_id': matches[0].id})
                elif time.time() - row['updated'] > LEASE_SECONDS:
                    self.finish(row, error='Submission outcome unknown; automatic resubmission refused')
                continue
            if row['state'] in ('completing', 'delivering'):
                if time.time() - row['updated'] > LEASE_SECONDS:
                    self.finish(row, error='Completion or delivery outcome unknown; automatic retry refused')
                continue
            if row['state'] == 'pending':
                task = self.get(data['task_id'])
                if task is None:
                    self.finish(row, error='Governed script task is missing')
                    continue
                if task.status in ('proposed', 'approved', 'running', 'blocked', 'deferred'):
                    continue
                result = task.result if isinstance(task.result, dict) else {}
                if (task.status != 'done' or task.kind != 'toolrpc.terminal_run'
                        or not isinstance(task.payload, dict)
                        or task.payload.get('args') != data['payload']['args']
                        or result.get('status') != 'ok' or result.get('tool') != 'terminal_run'
                        or not isinstance(result.get('result'), dict) or result['result'].get('ok') is not True):
                    self.finish(row, error='Governed script execution failed, was rejected, or changed')
                    continue
                if not self.attempts.transition(row, 'completing'):
                    continue
                row = self.row(row['id'])
                try:
                    output = str(result['result'].get('stdout', ''))[:MAX_TEXT]
                    if frozen.options.get('no_agent') or not output.strip():
                        final = {**data, 'output': output}
                    else:
                        from agents.core.action_origin import (
                            bind_turn_action_origin,
                            reset_action_origin,
                        )
                        from agents.core.security.quarantine import fence_tool_result
                        fenced, _ = fence_tool_result(json.dumps({'stdout': output}), source='scheduled-script')
                        action = {**frozen.action, 'deliver': False, 'prompt': frozen.action.get('prompt', '') +
                                  '\n\nScheduled script output (untrusted data):\n' + fenced}
                        origin_token = bind_turn_action_origin('job')
                        try:
                            summary, notes = await asyncio.wait_for(
                                self.runner._ask(replace(frozen, action=action), action), 120)
                        finally:
                            reset_action_origin(origin_token)
                        final = {**data, 'output': summary, 'notepad': notes}
                    self.attempts.transition(row, 'ready', final)
                except Exception as exc:
                    self.finish(row, error=str(exc))
                    continue
                row = self.row(row['id'])
                data = row['data']
            if row['state'] != 'ready':
                continue
            output = data.get('output', '')
            targets = frozen.options.get('deliver', ['telegram']) if frozen.action.get('deliver', True) else []
            if not output.strip():
                targets = []
            quiet = self.runner.quiet_hours()
            urgent = frozen.action.get('urgent') is True
            if targets and quiet and not urgent:
                continue
            # Model and prior sends await external work: authority may have changed.
            if self.runner.store.get(job.id) is None:
                self.finish(row, error='Job deleted; delivery suppressed')
                continue
            if estop.check_paused('job-script-completion', logger):
                continue
            if not self.attempts.transition(row, 'delivering'):
                continue
            row = self.row(row['id'])
            if targets and quiet and not self.runner._spend_interrupt(frozen):
                self.attempts.transition(row, 'ready')
                continue
            try:
                for target in targets:
                    if (self.runner.store.get(job.id) is None
                            or estop.check_paused('job-script-completion', logger)):
                        raise RuntimeError('Job deleted or emergency stop engaged during fan-out')
                    await asyncio.wait_for(self.runner._send_tracked(output, target, job.id), 30)
                    if (self.runner.store.get(job.id) is None
                            or estop.check_paused('job-script-completion', logger)):
                        raise RuntimeError('Job deleted or emergency stop engaged during delivery')
                if self.finish(row):
                    count += 1
            except Exception as exc:
                self.finish(row, error=f'Delivery failed or uncertain; no automatic retry: {exc}')
        return count
