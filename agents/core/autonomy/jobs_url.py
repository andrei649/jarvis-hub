"""One signed, human-approved URL hop; never a generic HTTP capability."""
import asyncio
import contextvars
import hashlib
import json
import logging
import threading
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

from agents.core import estop
from agents.core.http_client import PluginHTTPClient
from agents.core.kernel import Action, Verdict, kernel_enabled

from .queue import TaskQueue

PLUGIN = 'job-url-monitor'
MAX_BYTES = 262144
MAX_HOPS = 5
logger = logging.getLogger(__name__)


def screen_url(value, redact):
    """Reject credential-bearing URLs rather than persisting a redacted target."""
    if not isinstance(value, str) or len(value) > 2048 or not callable(redact):
        raise ValueError('URL monitor screening unavailable or URL invalid')
    if any(ord(c) <= 32 or ord(c) >= 127 for c in value) or '\\' in value:
        raise ValueError('URL monitor requires an ASCII public URL')
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment):
        raise ValueError('URL monitor requires a credential-free HTTP URL without fragment')
    decoded = value
    for _ in range(5):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    if unquote(decoded) != decoded:
        raise ValueError('URL monitor excessive escaping refused')
    if redact(value) != value or redact(decoded) != decoded or '[secret:' in decoded.lower():
        raise ValueError('URL monitor URL contains credentials')
    if any(any(word in key.lower() for word in ('token', 'secret', 'password', 'passwd', 'auth', 'key', 'signature'))
           for key, _ in parse_qsl(urlsplit(decoded).query)):
        raise ValueError('URL monitor URL contains credential parameters')
    # Force validation of malformed ports before persistence.
    _ = parsed.port
    return value


class _Claim:
    def __init__(self, fingerprint):
        self.fingerprint, self.active = fingerprint, True
        self.lock = threading.Lock()

    def consume(self, fingerprint):
        with self.lock:
            active, self.active = self.active, False
            return active and self.fingerprint == fingerprint


class _StrictClient(PluginHTTPClient):
    def __init__(self, check, **kwargs):
        super().__init__(PLUGIN, **kwargs)
        self._check = check

    def _enforce_kernel(self, method, url, host):
        # Override the default hook's intentional allow-on-error behavior locally.
        self._check(method, url)


class URLMonitorExecutor:
    def __init__(self, worker, *, kernel, redact, current, resolver=None, transport_factory=None):
        self.worker, self.kernel, self.redact, self.current = worker, kernel, redact, current
        self.resolver, self.transport_factory = resolver, transport_factory
        self._claim = contextvars.ContextVar('job_url_claim', default=None)

    def _available(self):
        if (self.worker.queue.mediation_mode != 'enforce' or not kernel_enabled()
                or not callable(self.kernel) or not callable(self.redact) or not callable(self.current)):
            raise ValueError('URL monitor enforced mediation unavailable')
        signer = getattr(self.worker, '_mediation_signer', None)
        if not callable(getattr(signer, 'sign', None)) or signer.sign(b'job-url-monitor availability') is None:
            raise ValueError('URL monitor signing unavailable')

    def validate(self, payload):
        self._available()
        if not isinstance(payload, dict):
            raise ValueError('invalid URL monitor payload')
        if (payload.get('plugin') != PLUGIN or payload.get('method') != 'GET'
                or payload.get('representation') != 'utf-8-identity'):
            raise ValueError('invalid URL monitor identity')
        if set(payload) - {'plugin', 'method', 'url', 'representation', 'monitor', 'tainted'}:
            raise ValueError('unexpected URL monitor payload fields')
        monitor = payload.get('monitor')
        if (not isinstance(monitor, dict) or set(monitor) != {'job_id', 'generation', 'attempt_id', 'hop'}
                or not isinstance(monitor['job_id'], str) or not monitor['job_id']
                or len(monitor['job_id']) > 128
                or any(type(monitor[k]) is not int for k in ('generation', 'attempt_id', 'hop'))
                or monitor['generation'] < 0 or monitor['attempt_id'] < 1 or not 0 <= monitor['hop'] <= MAX_HOPS):
            raise ValueError('invalid URL monitor attempt')
        screen_url(payload.get('url'), self.redact)
        if not self.current(payload):
            raise ValueError('URL monitor configuration changed')

    def screen(self, url):
        self._available()
        return screen_url(url, self.redact)

    def submit(self, payload, origin):
        from .jobs_scripts import ScriptSubmissionRefused
        try:
            self.validate(payload)
        except Exception as exc:
            raise ScriptSubmissionRefused('URL monitor proposal refused') from exc
        return self.worker.govern_enqueue(agent='jarvis', kind='plugin.egress',
            title='URL monitor GET awaiting this hop approval', payload=payload,
            risk_tier=3, autonomy_level='ask', origin=origin)

    def guard(self, task):
        self._claim.set(None)
        if task.kind != 'plugin.egress':
            return self.worker.execution_allowed(task)
        try:
            self.validate(task.payload)
            if not self.worker.execution_allowed(task):
                return False
            self._claim.set(_Claim(TaskQueue.execution_fingerprint(task)))
            return True
        except Exception:
            return False

    async def execute(self, task):
        claim = self._claim.get()
        self._claim.set(None)
        fingerprint = TaskQueue.execution_fingerprint(task)
        if (task.kind != 'plugin.egress' or not isinstance(claim, _Claim)
                or not claim.consume(fingerprint)):
            return {'status':'refused', 'reason':'URL monitor execution claim required'}
        try:
            self.validate(task.payload)
            payload = task.payload
            def check(method, url):
                self.validate(payload)
                if method != 'GET' or url != payload['url'] or estop.is_engaged():
                    raise ValueError('URL monitor dispatch refused')
                if not self.worker.queue.validate_mediated_execution(task, fingerprint):
                    raise ValueError('URL monitor execution receipt invalid')
                decision = self.kernel(Action(kind='plugin.egress', agent='jarvis',
                    title='Approved URL monitor GET', payload=payload, origin=task.origin))
                # QUEUE is not the grant: the consumed signed execution claim above is.
                if decision.verdict not in {Verdict.GRANT, Verdict.QUEUE}:
                    raise ValueError('URL monitor live kernel refused')
            client = _StrictClient(check, resolver=self.resolver, transport_factory=self.transport_factory)
            try:
                async with asyncio.timeout(30):
                    async with client.stream('GET', payload['url'], follow_redirects=False,
                            headers={'Accept-Encoding':'identity', 'Accept':'text/plain'}) as response:
                        check('GET', payload['url'])
                        if response.status_code in {301,302,303,307,308}:
                            location=response.headers.get('location')
                            if not location or payload['monitor']['hop'] >= MAX_HOPS:
                                raise ValueError('URL monitor redirect limit or missing destination')
                            destination=screen_url(urljoin(payload['url'], location), self.redact)
                            return {'status':'redirect', 'url':destination, 'identity':payload}
                        if not 200 <= response.status_code < 300:
                            raise ValueError('URL monitor HTTP failure')
                        if response.headers.get('content-encoding', 'identity').strip().lower() != 'identity':
                            raise ValueError('URL monitor encoded response refused')
                        body=bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body)+len(chunk)>MAX_BYTES:
                                raise ValueError('URL monitor response exceeds bound')
                            body.extend(chunk)
                        check('GET', payload['url'])
                        text=bytes(body).decode('utf-8', errors='strict')
                        scrubbed=self.redact(text)
                        if not isinstance(scrubbed, str) or len(scrubbed.encode('utf-8'))>MAX_BYTES:
                            raise ValueError('URL monitor scrubbed response exceeds bound')
                        capture={'version':1, 'sha256':hashlib.sha256(body).hexdigest(), 'byte_count':len(body),
                                 'complete':True, 'utf8_valid':True, 'snapshot_complete':True}
                        return {'status':'ok', 'tool':'url_monitor', 'identity':payload,
                                'result':{'ok':True, 'stdout':scrubbed, 'stdout_capture':capture}}
            finally:
                await client.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never expose request URL, raw body, headers or exception text to queue storage.
            return {'status':'failed', 'reason':'URL monitor fetch failed or unavailable'}


def initial_payload(row):
    return {'plugin':PLUGIN, 'method':'GET', 'url':row['data']['job']['options']['monitor_url'],
            'representation':'utf-8-identity', 'monitor':{'job_id':row['job_id'],
            'generation':row['data']['monitor_generation'], 'attempt_id':row['id'], 'hop':0}}


def redirect_payload(payload, url, adapter):
    if adapter is None or payload['monitor']['hop'] >= MAX_HOPS:
        raise ValueError('URL monitor redirect unavailable')
    return {**payload, 'url':screen_url(url, adapter.redact),
            'monitor':{**payload['monitor'], 'hop':payload['monitor']['hop']+1}}


def matches_result(task, expected):
    result = task.result if isinstance(task.result, dict) else {}
    if (task.status != 'done' or task.kind != 'plugin.egress' or not isinstance(task.payload, dict)
            or any(task.payload.get(key) != value for key, value in expected.items())
            or result.get('identity') != task.payload):
        return False
    if result.get('status') == 'redirect':
        return isinstance(result.get('url'), str)
    return (result.get('status') == 'ok' and result.get('tool') == 'url_monitor'
            and isinstance(result.get('result'), dict) and result['result'].get('ok') is True)


def url_payload_current(store, payload):
    from .jobs_monitor import generation
    try:
        identity = payload['monitor']
        with store._lock:
            row = store._conn.execute('SELECT job_id,state,data FROM job_script_attempts WHERE id=?',
                                      (identity['attempt_id'],)).fetchone()
            return bool(row and row['job_id'] == identity['job_id']
                        and all(payload.get(key) == value for key, value in json.loads(row['data']).get('payload', {}).items())
                        and json.loads(row['data']).get('payload')
                        and row['state'] not in ('done', 'failed')
                        and store._conn.execute('SELECT 1 FROM jobs WHERE id=?', (identity['job_id'],)).fetchone()
                        and generation(store._conn, identity['job_id']) == identity['generation'])
    except (KeyError, TypeError):
        return False
