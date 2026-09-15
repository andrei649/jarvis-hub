"""Bounded, scrubbed script snapshots with atomic pre-model detection."""
import difflib
import hashlib
import json
import re
import time

from agents.core.environments.output_limits import MAX_OUTPUT_BYTES


def install(store):
    with store._lock:
        store._conn.executescript('''
        CREATE TABLE IF NOT EXISTS job_monitor_generations (job_id TEXT PRIMARY KEY, generation INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS job_monitor_baselines
            (job_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, source_sha TEXT NOT NULL,
             output_sha TEXT NOT NULL, snapshot TEXT NOT NULL, scrubbed INTEGER NOT NULL, changed_at REAL NOT NULL);
        CREATE TRIGGER IF NOT EXISTS job_monitor_config_change
        AFTER UPDATE OF action,options,name,schedule_text ON jobs BEGIN
            INSERT INTO job_monitor_generations VALUES (NEW.id,1)
            ON CONFLICT(job_id) DO UPDATE SET generation=generation+1;
        END;
        CREATE TRIGGER IF NOT EXISTS job_monitor_delete AFTER DELETE ON jobs BEGIN
            DELETE FROM job_monitor_generations WHERE job_id=OLD.id;
            DELETE FROM job_monitor_baselines WHERE job_id=OLD.id;
        END;
        ''')
        store._conn.commit()


def generation(conn, job_id):
    row = conn.execute('SELECT generation FROM job_monitor_generations WHERE job_id=?', (job_id,)).fetchone()
    return int(row[0]) if row else 0


def current(store, row):
    with store._lock:
        return (store._conn.execute('SELECT 1 FROM jobs WHERE id=?', (row['job_id'],)).fetchone() is not None
                and generation(store._conn, row['job_id']) == row['data'].get('monitor_generation'))


def _capture(stdout, metadata, limit=MAX_OUTPUT_BYTES):
    if (not isinstance(metadata, dict) or type(metadata.get('version')) is not int or metadata['version'] != 1
            or metadata.get('complete') is not True or metadata.get('utf8_valid') is not True
            or metadata.get('snapshot_complete') is not True):
        raise ValueError('monitor requires complete successful UTF-8 stdout capture')
    count, digest = metadata.get('byte_count'), metadata.get('sha256')
    if type(count) is not int or not 0 <= count <= limit or len(stdout.encode('utf-8')) > limit:
        raise ValueError('monitor output exceeds the complete snapshot bound')
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('monitor capture digest is invalid')
    scrubbed = hashlib.sha256(stdout.encode('utf-8')).hexdigest() != digest
    return digest, scrubbed


def detect(store, row, stdout, metadata):
    """CAS the observation and baseline in one transaction, before any model await."""
    limit = MAX_OUTPUT_BYTES
    if row['data']['job']['options'].get('monitor_url'):
        from .jobs_url import MAX_BYTES
        limit = MAX_BYTES
    digest, scrubbed = _capture(stdout, metadata, limit)
    data = dict(row['data'])
    source = hashlib.sha256(json.dumps(data.get('monitor_source', data['payload'].get('args')), sort_keys=True).encode()).hexdigest()
    with store._lock:
        conn = store._conn
        conn.execute('BEGIN IMMEDIATE')
        try:
            live = conn.execute('SELECT state,updated FROM job_script_attempts WHERE id=?', (row['id'],)).fetchone()
            if not live or live['state'] != row['state'] or live['updated'] != row['updated']:
                raise ValueError('monitor attempt claim changed')
            epoch = generation(conn, row['job_id'])
            exists = conn.execute('SELECT 1 FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
            if not exists or epoch != data.get('monitor_generation'):
                data['suppressed_reason'] = 'stale_configuration'
            else:
                prior = conn.execute('SELECT * FROM job_monitor_baselines WHERE job_id=?', (row['job_id'],)).fetchone()
                same_source = prior and prior['generation'] == epoch and prior['source_sha'] == source
                if same_source and prior['output_sha'] == digest:
                    data['suppressed_reason'] = 'no_change'
                else:
                    label = 'Monitor Baseline (first run)'
                    diff = ''
                    if same_source:
                        label = 'MONITOR CHANGE DETECTED'
                        lines = difflib.unified_diff(prior['snapshot'].splitlines(keepends=True),
                            stdout.splitlines(keepends=True), fromfile='previous', tofile='current')
                        diff = ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n'
                                       for line in lines)
                    payload = {'event': label, 'diff': diff[:4000], 'current_output': stdout[:8000],
                               'diff_truncated': len(diff) > 4000, 'output_truncated': len(stdout) > 8000,
                               'snapshot_kind': 'scrubbed' if scrubbed or (same_source and prior['scrubbed']) else 'text'}
                    data['monitor_context'] = payload
                    conn.execute('INSERT INTO job_monitor_baselines VALUES (?,?,?,?,?,?,?) '
                        'ON CONFLICT(job_id) DO UPDATE SET generation=excluded.generation,source_sha=excluded.source_sha,'
                        'output_sha=excluded.output_sha,snapshot=excluded.snapshot,scrubbed=excluded.scrubbed,changed_at=excluded.changed_at',
                        (row['job_id'], epoch, source, digest, stdout, int(scrubbed), time.time()))
            conn.execute('UPDATE job_script_attempts SET data=?,updated=? WHERE id=?',
                         (json.dumps(data), time.time(), row['id']))
            conn.commit()
            return data
        except BaseException:
            conn.rollback()
            raise
