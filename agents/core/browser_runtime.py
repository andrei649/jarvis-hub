"""Canonical, bounded browser plans and the owner-approved runtime boundary."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .env_config import env_str

MAX_STEPS = 20
MAX_PLAN_BYTES = 60_000
CLOSE_WAIT_SECONDS = 15.0
TOOL = 'browser_run'
KIND = 'toolrpc.browser_run'
TITLE = 'Run approved browser plan'
INPUT_SCHEMA = {
    'type': 'object',
    'properties': {'mode': {'type': 'string'}, 'session_id': {'type': 'string'},
                   'steps': {'type': 'array', 'minItems': 1, 'maxItems': MAX_STEPS,
                             'items': {'type': 'object'}}},
    'additionalProperties': False,
}


class BrowserPlanRefused(ValueError):
    """A browser proposal cannot be run or presented for approval."""


@dataclass(frozen=True)
class BrowserPlan:
    steps: tuple[dict, ...]
    sha256: str


@dataclass(frozen=True)
class BrowserRequest:
    mode: str
    steps: tuple[dict, ...]
    sha256: str
    session_id: str | None = None


def _bounded_text(value, limit):
    return type(value) is str and 0 < len(value) <= limit


def _valid_url(value):
    if not _bounded_text(value, 2000):
        return False
    if any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
        return (parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and parsed.fragment == '' and (port is None or 1 <= port <= 65535))
    except ValueError:
        return False


def validate_browser_plan(args: dict) -> BrowserPlan:
    """Reject any field that could alter an approved action or server authority."""
    if type(args) is not dict or set(args) != {'steps'}:
        raise BrowserPlanRefused('invalid_browser_plan')
    steps = args['steps']
    if type(steps) is not list or not 1 <= len(steps) <= MAX_STEPS:
        raise BrowserPlanRefused('invalid_browser_plan')
    canonical = []
    for step in steps:
        if type(step) is not dict or type(step.get('action')) is not str:
            raise BrowserPlanRefused('invalid_browser_step')
        action = step['action']
        required = {
            'navigate': {'action', 'url'},
            'extract': {'action', 'selector'},
            'snapshot': {'action'},
            'wait': {'action', 'timeout_ms'},
            'click': {'action', 'selector'},
            'type': {'action', 'selector', 'text'},
            'submit': {'action', 'selector'},
        }.get(action)
        optional = {'selector'} if action in {'snapshot', 'wait'} else set()
        if required is None or not required <= set(step) or set(step) - required - optional:
            raise BrowserPlanRefused('invalid_browser_step')
        if action == 'navigate' and not _valid_url(step['url']):
            raise BrowserPlanRefused('invalid_browser_url')
        if 'selector' in step and not _bounded_text(step['selector'], 512):
            raise BrowserPlanRefused('invalid_browser_selector')
        if action == 'type' and not _bounded_text(step['text'], 4000):
            raise BrowserPlanRefused('invalid_browser_text')
        if action == 'wait' and (type(step['timeout_ms']) is not int
                                 or not 1 <= step['timeout_ms'] <= 30_000):
            raise BrowserPlanRefused('invalid_browser_wait')
        canonical.append({key: step[key] for key in sorted(step)})
    if canonical[0]['action'] != 'navigate':
        raise BrowserPlanRefused('browser_navigation_required')
    encoded = json.dumps(canonical, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_PLAN_BYTES:
        raise BrowserPlanRefused('browser_plan_too_large')
    return BrowserPlan(tuple(canonical), hashlib.sha256(encoded).hexdigest())


_SESSION_KEYS = frozenset({'Enter', 'Tab', 'Escape', 'ArrowUp', 'ArrowDown',
                           'ArrowLeft', 'ArrowRight', 'Space', 'Backspace', 'Delete'})


def validate_browser_request(args: dict) -> BrowserRequest:
    """Canonical session proposal; the id and ref are lookups, never authority."""
    if type(args) is not dict or args.get('mode') not in {'start', 'act', 'close'}:
        raise BrowserPlanRefused('invalid_browser_session')
    mode = args['mode']
    expected = {'mode', 'steps'} if mode == 'start' else (
        {'mode', 'session_id', 'steps'} if mode == 'act' else {'mode', 'session_id'})
    if set(args) != expected:
        raise BrowserPlanRefused('invalid_browser_session')
    sid = args.get('session_id')
    if sid is not None and (type(sid) is not str or re.fullmatch('[0-9a-f]{32}', sid) is None):
        raise BrowserPlanRefused('invalid_browser_session')
    if mode == 'close':
        return BrowserRequest(mode, (), hashlib.sha256(b'close').hexdigest(), sid)
    steps = args['steps']
    if type(steps) is not list or not 1 <= len(steps) <= MAX_STEPS:
        raise BrowserPlanRefused('invalid_browser_plan')
    if mode == 'start':
        plan = validate_browser_plan({'steps': steps})
        return BrowserRequest(mode, plan.steps, plan.sha256)
    canonical = []
    for step in steps:
        if type(step) is not dict or type(step.get('action')) is not str:
            raise BrowserPlanRefused('invalid_browser_step')
        action = step['action']
        required = {
            'navigate': {'action', 'url'}, 'snapshot': {'action'},
            'extract': {'action', 'selector'}, 'wait': {'action', 'timeout_ms'},
            'click': {'action', 'ref'}, 'type': {'action', 'ref', 'text'},
            'submit': {'action', 'ref'}, 'scroll': {'action', 'ref', 'direction', 'pixels'},
            'press': {'action', 'ref', 'key'}, 'back': {'action'},
        }.get(action)
        optional = {'selector'} if action in {'snapshot', 'wait'} else set()
        if required is None or not required <= set(step) or set(step) - required - optional:
            raise BrowserPlanRefused('invalid_browser_step')
        if action == 'navigate' and not _valid_url(step['url']):
            raise BrowserPlanRefused('invalid_browser_url')
        if 'selector' in step and not _bounded_text(step['selector'], 512):
            raise BrowserPlanRefused('invalid_browser_selector')
        if 'ref' in step and (type(step['ref']) is not str
                              or re.fullmatch(r'@e[1-9][0-9]{0,5}', step['ref']) is None):
            raise BrowserPlanRefused('invalid_browser_ref')
        if action == 'type' and not _bounded_text(step['text'], 4000):
            raise BrowserPlanRefused('invalid_browser_text')
        if action == 'press' and step['key'] not in _SESSION_KEYS:
            raise BrowserPlanRefused('invalid_browser_key')
        if action == 'scroll' and (step['direction'] not in {'up', 'down'}
                                   or type(step['pixels']) is not int
                                   or not 1 <= step['pixels'] <= 2000):
            raise BrowserPlanRefused('invalid_browser_scroll')
        if action == 'wait' and (type(step['timeout_ms']) is not int
                                 or not 1 <= step['timeout_ms'] <= 30_000):
            raise BrowserPlanRefused('invalid_browser_wait')
        canonical.append({key: step[key] for key in sorted(step)})
    encoded = json.dumps(canonical, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(',', ':')).encode()
    if len(encoded) > MAX_PLAN_BYTES:
        raise BrowserPlanRefused('browser_plan_too_large')
    return BrowserRequest(mode, tuple(canonical), hashlib.sha256(encoded).hexdigest(), sid)


def _server_domains() -> tuple[str, ...]:
    from .browser_transport import is_private_host_literal

    raw = env_str('JARVIS_BROWSER_ALLOWED_DOMAINS', '')
    domains = tuple(part.strip().lower() for part in raw.split(',') if part.strip())
    if not domains or len(domains) > 64 or any(
        len(domain) > 253 or is_private_host_literal(domain) or not re.fullmatch(
            r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*', domain)
        for domain in domains
    ):
        raise BrowserPlanRefused('browser_allowlist_unavailable')
    return domains


def _chrome_binary() -> str | None:
    if sys.platform == 'darwin':
        path = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        return str(path) if path.is_file() else None
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        found = shutil.which(name)
        if found:
            return found
    return None


def local_browser_ready(*, kernel=None, queue=None, fixture_origin=None) -> bool:
    """Read-only local prerequisites; never launches a browser or resolves a site."""
    from .env_config import env_flag
    from .kernel import kernel_enabled

    try:
        if not env_flag('JARVIS_PLAYWRIGHT_HOST') or not env_flag('JARVIS_UNIFIED_ACTION_API'):
            return False
        if not kernel_enabled() or not callable(kernel) or getattr(queue, 'mediation_mode', None) != 'enforce':
            return False
        if env_str('JARVIS_PLAYWRIGHT_BROWSER', 'chromium') != 'chromium':
            return False
        if fixture_origin is None:
            _server_domains()
        return (importlib.util.find_spec('playwright') is not None
                and importlib.util.find_spec('psutil') is not None and bool(_chrome_binary()))
    except (ImportError, ValueError, BrowserPlanRefused):
        return False


class BrowserRuntime:
    """One owner-approved plan, one ephemeral Chromium profile, one cleanup owner."""

    def __init__(self, *, queue, approved_task, authorizer, enqueue,
                 execution_check, registration=None, fixture_origin=None,
                 driver_factory=None, control_current=None, revalidator=None):
        if fixture_origin is not None and not env_str('PYTEST_CURRENT_TEST'):
            raise ValueError('browser fixture is test-only')
        self.queue, self.approved_task = queue, approved_task
        self.authorizer, self.enqueue = authorizer, enqueue
        self.execution_check = execution_check
        self.registration = registration
        self.fixture_origin = fixture_origin
        self.driver_factory = driver_factory
        self.control_current = control_current or (lambda _task: True)
        self.revalidator = revalidator
        self.last_profile = None
        self.last_browser_identity = None
        self._uncertain_drivers = []
        self._uncertain_sessions = {}
        self._close_tasks = {}
        self._cleanup_lock = asyncio.Lock()
        from .browser_session import BrowserOwnershipJournal
        self.sessions = {}
        self.journal = BrowserOwnershipJournal(
            Path(env_str('JARVIS_HOME', str(Path.home() / '.jarvis'))) / 'browser-ownership')
        self._journal_uncertain = bool(self.journal.entries())
        self._reaper_task = None
        self._owner_close_tasks = {}
        if self._journal_uncertain:
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(self.reap_orphans())

    def ready(self):
        return (not self._uncertain_drivers and not self._journal_uncertain
                and local_browser_ready(kernel=self.authorizer, queue=self.queue,
                                        fixture_origin=self.fixture_origin))

    def _head(self):
        domains = ('fixture:' + self.fixture_origin,) if self.fixture_origin else _server_domains()
        source = []
        for name in ('browser_runtime.py', 'browser_agent.py', 'browser_transport.py',
                     'browser_playwright.py', 'browser_kernel.py', 'browser_session.py'):
            source.append(hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest())
        encoded = json.dumps([domains, source, _chrome_binary(),
                              env_str('JARVIS_PLAYWRIGHT_BROWSER', 'chromium')],
                             separators=(',', ':')).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _ready(self):
        if self._uncertain_drivers or self._journal_uncertain:
            raise BrowserPlanRefused('browser_cleanup_unverified')
        if not self.ready():
            raise BrowserPlanRefused('browser_unavailable')

    def _settle_close(self, driver, task):
        if self._close_tasks.get(driver) is not task or not task.done():
            return False
        try:
            task.result()
        except BaseException:
            return False
        self._close_tasks.pop(driver, None)
        self._uncertain_drivers = [item for item in self._uncertain_drivers if item is not driver]
        return True

    def _start_close(self, driver):
        task = self._close_tasks.get(driver)
        if task is not None and not task.done():
            return task
        if all(item is not driver for item in self._uncertain_drivers):
            self._uncertain_drivers.append(driver)
        task = asyncio.create_task(driver.close())
        self._close_tasks[driver] = task
        task.add_done_callback(lambda finished: self._settle_close(driver, finished))
        return task

    async def _await_close(self, driver, task):
        try:
            await asyncio.wait_for(asyncio.shield(task), CLOSE_WAIT_SECONDS)
        except TimeoutError:
            task.cancel()
            return False
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            return False
        except Exception:
            return False
        return self._settle_close(driver, task) or all(
            item is not driver for item in self._uncertain_drivers)

    def preflight(self, args):
        from .tool_rpc import ToolRPCValidationError

        try:
            self._ready()
            task = self.approved_task()
            if type(args) is dict and 'mode' in args:
                if task is None:
                    request = validate_browser_request(args)
                    session = self.sessions.get(request.session_id) if request.session_id else None
                    if request.mode == 'start':
                        if len(self.sessions) >= 4:
                            raise BrowserPlanRefused('browser_session_capacity')
                        generation = 0
                    elif session is None or not session.current() or session.lock.locked():
                        raise BrowserPlanRefused('browser_session_unavailable')
                    else:
                        generation = session.generation
                    spec = self.registration() if callable(self.registration) else None
                    if spec is None:
                        raise BrowserPlanRefused('browser_registration_unavailable')
                    bound = dict(args)
                    if request.mode != 'close':
                        bound['steps'] = list(request.steps)
                    bound['_binding'] = {
                        'nonce': secrets.token_hex(16), 'head': self._head(),
                        'plan_sha256': request.sha256,
                        'registration_key': spec.get('_consent_registration_key'),
                        'registration_epoch': spec.get('_grouping_epoch'),
                        'session_generation': generation,
                    }
                    return bound
                if '_binding' not in args:
                    raise BrowserPlanRefused('approved_payload_changed')
                unbound = {key: value for key, value in args.items() if key != '_binding'}
                request = validate_browser_request(unbound)
                binding = args['_binding']
                session = self.sessions.get(request.session_id) if request.session_id else None
                generation = 0 if request.mode == 'start' else (
                    session.generation if session is not None and session.current() else None)
                if (type(binding) is not dict or set(binding) != {
                        'nonce', 'head', 'plan_sha256', 'registration_key',
                        'registration_epoch', 'session_generation'}
                        or not re.fullmatch('[0-9a-f]{32}', str(binding['nonce']))
                        or binding['head'] != self._head()
                        or binding['plan_sha256'] != request.sha256
                        or binding['session_generation'] != generation
                        or not self._registration_current(args)
                        or (request.mode != 'close' and args['steps'] != list(request.steps))):
                    raise BrowserPlanRefused('approved_payload_changed')
                return args
            if task is None:
                plan = validate_browser_plan(args)
                spec = self.registration() if callable(self.registration) else None
                if spec is None:
                    raise BrowserPlanRefused('browser_registration_unavailable')
                return {'steps': list(plan.steps), '_binding': {
                    'nonce': secrets.token_hex(16), 'head': self._head(),
                    'plan_sha256': plan.sha256,
                    'registration_key': spec.get('_consent_registration_key'),
                    'registration_epoch': spec.get('_grouping_epoch'),
                }}
            if type(args) is not dict or set(args) != {'steps', '_binding'}:
                raise BrowserPlanRefused('approved_payload_changed')
            plan = validate_browser_plan({'steps': args['steps']})
            binding = args['_binding']
            if (type(binding) is not dict or set(binding) != {
                    'nonce', 'head', 'plan_sha256', 'registration_key', 'registration_epoch'}
                    or not re.fullmatch('[0-9a-f]{32}', str(binding['nonce']))
                    or binding['head'] != self._head() or binding['plan_sha256'] != plan.sha256
                    or args['steps'] != list(plan.steps)
                    or not self._registration_current(args)):
                raise BrowserPlanRefused('approved_payload_changed')
            return args
        except BrowserPlanRefused as exc:
            raise ToolRPCValidationError(str(exc)) from None
        except OSError:
            raise ToolRPCValidationError('browser_unavailable') from None

    def intake(self, agent, args):
        from .action_origin import current_action_origin
        from .approval_outcomes import tool_approval_scope
        from .autonomy.approval_grouping import model_request_scope
        from .autonomy.consent_registration import trusted_registration_key
        from .kernel import Action, Decision, Verdict
        from .security.taint import mark_if_untrusted
        from .tool_rpc import ToolRPCValidationError

        self._ready()
        if args.get('mode') in {'act', 'close'}:
            session = self.sessions.get(args.get('session_id'))
            if session is None or session.agent != agent or not session.current():
                raise ToolRPCValidationError('browser_session_unavailable')
        spec = self.registration() if callable(self.registration) else None
        if spec is None or self.queue is None:
            raise ToolRPCValidationError('browser_registration_unavailable')
        origin = current_action_origin()
        payload = mark_if_untrusted({'tool': TOOL, 'args': args, 'target': TOOL}, origin)
        action = Action(kind=KIND, agent=agent, title=TITLE, payload=payload, origin=origin)
        decision = self.authorizer(action)
        if not isinstance(decision, Decision) or decision.verdict not in {Verdict.GRANT, Verdict.QUEUE}:
            raise ToolRPCValidationError('kernel_denied')
        with tool_approval_scope(TOOL), model_request_scope(
            actor=agent, tool=TOOL, args=args, epoch=spec['_grouping_epoch'],
            registration_is_live=lambda: self.registration() is spec,
            registration_key=spec['_consent_registration_key'],
            registration_key_is_live=lambda candidate: (
                self.registration() is spec and trusted_registration_key(TOOL, spec) == candidate),
        ):
            task_id = self.enqueue(agent, KIND, TITLE, payload=payload, risk_tier=3,
                                   autonomy_level='ask', origin=origin)
        task = self.queue.get(task_id)
        if (task is None or task.kind != KIND or task.payload != payload
                or task.autonomy_level != 'ask'):
            raise ToolRPCValidationError('browser_proposal_unbound')
        return task_id

    def _current(self, task, args):
        try:
            if task is None or self.queue is None or getattr(self.queue, 'mediation_mode', None) != 'enforce':
                return False
            live = self.queue.get(getattr(task, 'id', None))
            fingerprint = self.queue.execution_fingerprint(task)
            return bool(
                live is not None and live.status == 'running' and live.kind == KIND
                and live.autonomy_level == 'ask' and live.decision == 'accept'
                and live.decided_by and str(live.decided_by).lower() not in {'policy', 'smart_approval'}
                and live.payload == task.payload and live.payload.get('args') == args
                and fingerprint and self.queue.execution_fingerprint(live) == fingerprint
                and self.queue.validate_mediated_execution(task, fingerprint)
                and self.execution_check(task) is True
                and self.control_current(task) is True
                and self._registration_current(args)
            )
        except Exception:
            return False

    def _registration_current(self, args):
        from .autonomy.consent_registration import trusted_registration_key

        spec = self.registration() if callable(self.registration) else None
        binding = args.get('_binding') if type(args) is dict else None
        return bool(
            spec is not None and type(binding) is dict
            and spec.get('capability_id') == 'tool:browser_run'
            and binding.get('registration_key') == spec.get('_consent_registration_key')
            and binding.get('registration_epoch') == spec.get('_grouping_epoch')
            and trusted_registration_key(TOOL, spec) == spec.get('_consent_registration_key')
        )

    async def execute(self, args):
        if type(args) is dict and args.get('mode') in {'start', 'act', 'close'}:
            return await self.execute_session(args)
        from .browser_agent import BrowserPolicy, GovernedBrowser
        from .browser_kernel import BrowserActionExecutor, approved_step_scope
        from .browser_playwright import PlaywrightBrowserDriver
        from .browser_transport import PinnedResolver

        task = self.approved_task()
        deadline = asyncio.get_running_loop().time() + 120
        try:
            self.preflight(args)
            if not self._current(task, args):
                raise BrowserPlanRefused('browser_approval_invalid')
            plan = validate_browser_plan({'steps': args['steps']})
            if self.fixture_origin:
                from .browser_agent import FixtureBrowserPolicy
                policy = FixtureBrowserPolicy(self.fixture_origin)
                host = urlsplit(self.fixture_origin).hostname
                pins = PinnedResolver(mode='lan', resolver=lambda candidate, *, mode: (
                    (['127.0.0.1'], None) if candidate == host and mode == 'lan'
                    else ([], 'fixture_only')))
            else:
                policy = BrowserPolicy(list(_server_domains()))
                pins = PinnedResolver(mode='public')
            async with asyncio.timeout_at(deadline):
                for step in plan.steps:
                    if step['action'] == 'navigate':
                        allowed, _ = await asyncio.to_thread(policy.domain_allowed, step['url'])
                        if not allowed or not self._current(task, args):
                            raise BrowserPlanRefused('browser_egress_denied')
                        await pins.pin_async(step['url'])
                        if not self._current(task, args):
                            raise BrowserPlanRefused('browser_approval_invalid')
            if self.driver_factory:
                driver = self.driver_factory()
            else:
                driver = PlaywrightBrowserDriver.from_env(
                    browser='chromium', headless=True, channel='chrome',
                    allow_private_urls=bool(self.fixture_origin), transport=pins)
            driver.set_transport(pins)
            driver.set_url_guard(policy.domain_allowed)
            bind_execution = getattr(driver, 'set_execution_guard', None)
            if callable(bind_execution):
                bind_execution(lambda: self._current(task, args))
            elif self.driver_factory is None:
                raise BrowserPlanRefused('browser_execution_guard_unavailable')
            executor = BrowserActionExecutor(driver, authorizer=self.authorizer,
                                             revalidator=self.revalidator)
            browser = GovernedBrowser(driver=driver, policy=policy, agent=task.agent,
                                      action_executor=executor, transport=pins)
            trace = []
            try:
                async with asyncio.timeout_at(deadline):
                    for index, step in enumerate(plan.steps):
                        if not self._current(task, args):
                            raise BrowserPlanRefused('browser_approval_invalid')
                        with approved_step_scope(task, plan.sha256, index, step,
                                                 lambda: self._current(task, args)):
                            async with asyncio.timeout(15 if step['action'] != 'wait' else 31):
                                if (getattr(driver, 'requires_kernel', False) is True
                                        and step['action'] in {'navigate', 'extract', 'snapshot', 'wait'}):
                                    read_gate = await executor.check_read(step)
                                    if read_gate.status != 'completed':
                                        raise BrowserPlanRefused('browser_kernel_refused')
                                if step['action'] == 'snapshot':
                                    result = await driver.observe_snapshot(selector=step.get('selector', 'body'))
                                    outcome = {'action': 'snapshot', 'status': 'done', 'result': result}
                                else:
                                    outcome = await browser.run_step(step)
                        if outcome.get('status') != 'done':
                            raise BrowserPlanRefused('browser_step_refused')
                        trace.append(outcome)
                        if len(json.dumps(trace, ensure_ascii=False, default=str).encode()) > 20_000:
                            raise BrowserPlanRefused('browser_output_too_large')
                return {'ok': True, 'plan_sha256': plan.sha256, 'trace': trace}
            finally:
                self.last_profile = driver.profile_dir
                self.last_browser_identity = getattr(driver, 'owned_browser_identity', None)
                close_task = self._start_close(driver)
                if not await self._await_close(driver, close_task):
                    raise BrowserPlanRefused('browser_cleanup_unverified') from None
        except (BrowserPlanRefused, TimeoutError) as exc:
            return {'ok': False, 'reason': 'browser_timeout' if isinstance(exc, TimeoutError) else str(exc)}

    async def reap_uncertain(self):
        """Bounded explicit retry of retained cleanup; never forget an uncertain owner."""
        async with self._cleanup_lock:
            for driver in list(self._uncertain_drivers):
                task = self._close_tasks.get(driver)
                if task is not None and task.done():
                    if self._settle_close(driver, task):
                        continue
                    task = None
                if task is None:
                    task = self._start_close(driver)
                if not await self._await_close(driver, task):
                    if not task.done():
                        return False
                    task = self._start_close(driver)
                    if not await self._await_close(driver, task):
                        return False
            for driver, sid in list(self._uncertain_sessions.items()):
                if driver not in self._uncertain_drivers and driver not in self._close_tasks:
                    await asyncio.to_thread(self.journal.remove, sid)
                    self._uncertain_sessions.pop(driver, None)
            self._journal_uncertain = bool(self._uncertain_sessions or any(
                path.stem not in self.sessions for path in self.journal.entries()))
            return not self._uncertain_drivers and not self._journal_uncertain

    async def _journal_observer(self, sid, event, profile, identity):
        import psutil

        if event == 'profile':
            if identity is None or not isinstance(getattr(identity, 'pid', None), int):
                raise BrowserPlanRefused('browser_owner_unverified')
            started = await asyncio.to_thread(lambda: psutil.Process(identity.pid).create_time())
            owner_started = await asyncio.to_thread(lambda: psutil.Process(os.getpid()).create_time())
            record = {'profile': str(profile), 'controller': [identity.pid, started],
                      'owner_process': [os.getpid(), owner_started], 'native': None}
        else:
            record = await asyncio.to_thread(self.journal.read, self.journal._file(sid))
            if (type(identity) is not tuple or len(identity) != 2
                    or type(identity[0]) is not int):
                raise BrowserPlanRefused('browser_owner_unverified')
            record['native'] = list(identity)
        await asyncio.to_thread(self.journal.write, sid, record)

    def _session_authorized(self, session, task, args):
        try:
            return (session.active_task is task and session.active_args is args
                    and session.current() and session.head == self._head()
                    and session.owner == task.decided_by and session.agent == task.agent
                    and session.registration_key == args['_binding']['registration_key']
                    and self._current(task, args))
        except Exception:
            return False

    def _session_registration_current(self, session) -> bool:
        from .autonomy.consent_registration import trusted_registration_key

        try:
            spec = self.registration() if callable(self.registration) else None
            return bool(
                type(session.registration_key) is str and bool(session.registration_key)
                and type(session.registration_epoch) is int
                and type(spec) is dict and spec.get('capability_id') == 'tool:browser_run'
                and spec.get('_consent_registration_key') == session.registration_key
                and spec.get('_grouping_epoch') == session.registration_epoch
                and trusted_registration_key(TOOL, spec) == session.registration_key
            )
        except Exception:
            return False

    def _session_network_current(self, session):
        """Playwright route tasks lack the worker ContextVar; validate its live row.

        The active tuple is installed only after the worker's full execution
        context check. This narrower callback is for requests spawned by Chrome,
        not for minting a new browser-step approval.
        """
        try:
            task, args = session.active_task, session.active_args
            if task is None or args is None or not session.current() or session.head != self._head():
                return False
            live = self.queue.get(task.id)
            fingerprint = self.queue.execution_fingerprint(task)
            return bool(
                live is not None and live.status == 'running' and live.kind == KIND
                and live.decision == 'accept' and live.decided_by == session.owner
                and live.agent == session.agent and live.payload == task.payload
                and live.payload.get('args') == args and fingerprint
                and self.queue.execution_fingerprint(live) == fingerprint
                and self.queue.validate_mediated_execution(task, fingerprint)
                and self.control_current(task) is True
                and self._registration_current(args)
            )
        except Exception:
            return False

    async def _close_session(self, session):
        session.closed = True
        session.active_task = None
        session.active_args = None
        session.invalidate()
        self.sessions.pop(session.id, None)
        self.last_profile = getattr(session.driver, 'profile_dir', None)
        self.last_browser_identity = getattr(session.driver, 'owned_browser_identity', None)
        self._uncertain_sessions[session.driver] = session.id
        close_task = self._start_close(session.driver)
        settled = await self._await_close(session.driver, close_task)
        if settled:
            await asyncio.to_thread(self.journal.remove, session.id)
            self._uncertain_sessions.pop(session.driver, None)
        else:
            self._journal_uncertain = True
        return settled

    def _ensure_reaper(self):
        if self._reaper_task is not None and not self._reaper_task.done():
            return
        self._reaper_task = asyncio.create_task(self._reap_sessions())

    async def _reap_sessions(self):
        cleanup_attempts = 0
        while self.sessions or (self._uncertain_sessions and cleanup_attempts < 3):
            await asyncio.sleep(1)
            for session in list(self.sessions.values()):
                try:
                    stale = (not session.current() or session.head != self._head()
                             or not self._session_registration_current(session)
                             or self.control_current(session.owner_task) is not True)
                except Exception:
                    stale = True
                if stale:
                    await self.close_owner_session(session.id)
            if self._uncertain_sessions and cleanup_attempts < 3:
                cleanup_attempts += 1
                await self.reap_uncertain()

    async def reap_orphans(self):
        """On restart, never resume old sessions; reconcile only verified native owners."""
        try:
            paths = self.journal.entries()
            stale = [path for path in paths if path.stem not in self.sessions]
            results = [await self.journal.reap_entry(path) for path in stale]
            self._journal_uncertain = not all(results)
            return not self._journal_uncertain
        except Exception:
            self._journal_uncertain = True
            return False

    async def close_owner_session(self, sid):
        """Authenticated owner close needs no actuator approval and never opens Chrome."""
        session = self.sessions.get(sid)
        closing = self._owner_close_tasks.get(sid)
        if session is None and closing is None:
            return False
        if session is not None:
            session.closed = True
            worker = session.active_worker
            if worker is not None and worker is not asyncio.current_task():
                worker.cancel()
        if closing is None and session is not None:
            async def settle():
                async with session.lock:
                    if session.id not in self.sessions:
                        return not self._uncertain_drivers and not self._journal_uncertain
                    return await self._close_session(session)

            closing = asyncio.create_task(settle())
            self._owner_close_tasks[sid] = closing

            def finished(task):
                self._owner_close_tasks.pop(sid, None)
                try:
                    if task.result() is True and not self._uncertain_drivers:
                        self._journal_uncertain = any(
                            path.stem not in self.sessions for path in self.journal.entries())
                except BaseException:
                    self._journal_uncertain = True

            closing.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(closing), CLOSE_WAIT_SECONDS)
        except TimeoutError:
            self._journal_uncertain = True
            return False
        except asyncio.CancelledError:
            self._journal_uncertain = True
            raise

    async def _run_session_steps(self, session, task, args, request):
        from .browser_agent import GovernedBrowser
        from .browser_kernel import BrowserActionExecutor, approved_step_scope

        driver = session.driver
        executor = BrowserActionExecutor(driver, authorizer=self.authorizer,
                                         revalidator=self.revalidator)
        browser = GovernedBrowser(driver=driver, policy=session.policy, agent=task.agent,
                                  action_executor=executor, transport=session.pins)
        trace = []
        deadline = asyncio.get_running_loop().time() + 120
        async with asyncio.timeout_at(deadline):
            for index, step in enumerate(request.steps):
                if not self._session_authorized(session, task, args):
                    raise BrowserPlanRefused('browser_approval_invalid')
                if step['action'] == 'navigate':
                    host = urlsplit(step['url']).hostname
                    if host not in session.pins.pinned_hosts():
                        raise BrowserPlanRefused('browser_egress_denied')
                with approved_step_scope(task, request.sha256, index, step,
                                         lambda: self._session_authorized(session, task, args),
                                         session_id=session.id,
                                         session_generation=session.generation):
                    async with asyncio.timeout(15 if step['action'] != 'wait' else 31):
                        if step['action'] in {'navigate', 'extract', 'snapshot', 'wait'}:
                            read_gate = await executor.check_read(step)
                            if read_gate.status != 'completed':
                                raise BrowserPlanRefused('browser_kernel_refused')
                        if step['action'] == 'snapshot':
                            outcome = {'action': 'snapshot', 'status': 'done',
                                       'result': await session.snapshot()}
                        else:
                            outcome = await browser.run_step(step)
                if outcome.get('status') != 'done':
                    if outcome.get('reason') == 'stale_browser_ref':
                        raise BrowserPlanRefused('stale_browser_ref')
                    raise BrowserPlanRefused('browser_step_refused')
                if not self._session_authorized(session, task, args):
                    raise BrowserPlanRefused('browser_approval_invalid')
                if step['action'] in {'navigate', 'back'}:
                    session.invalidate()
                trace.append(outcome)
                if len(json.dumps(trace, ensure_ascii=False, default=str).encode()) > 20_000:
                    raise BrowserPlanRefused('browser_output_too_large')
        session.last_used = __import__('time').monotonic()
        return {'ok': True, 'session_id': session.id, 'generation': session.generation,
                'trace': trace}

    async def execute_session(self, args):
        from .browser_agent import BrowserPolicy, FixtureBrowserPolicy
        from .browser_playwright import PlaywrightBrowserDriver
        from .browser_session import BrowserSession
        from .browser_transport import PinnedResolver

        task = self.approved_task()
        session = None
        new = False
        entered = False
        request = None
        try:
            self.preflight(args)
            if not self._current(task, args):
                raise BrowserPlanRefused('browser_approval_invalid')
            request = validate_browser_request({key: value for key, value in args.items()
                                                if key != '_binding'})
            if request.mode == 'start':
                if len(self.sessions) >= 4:
                    raise BrowserPlanRefused('browser_session_capacity')
                if any(item.agent == task.agent and item.owner == task.decided_by
                       for item in self.sessions.values()):
                    raise BrowserPlanRefused('browser_session_capacity')
                if self.fixture_origin:
                    policy = FixtureBrowserPolicy(self.fixture_origin)
                    pins = PinnedResolver(mode='lan', resolver=lambda candidate, *, mode: (
                        (['127.0.0.1'], None) if candidate in {
                            'fixture.browser.test', 'frame.other.test'} and mode == 'lan'
                        else ([], 'fixture_only')))
                else:
                    policy = BrowserPolicy(list(_server_domains()))
                    pins = PinnedResolver(mode='public')
                async with asyncio.timeout(120):
                    for step in request.steps:
                        if step['action'] == 'navigate':
                            allowed, _ = await asyncio.to_thread(policy.domain_allowed, step['url'])
                            if not allowed or not self._current(task, args):
                                raise BrowserPlanRefused('browser_egress_denied')
                            await pins.pin_async(step['url'])
                driver = self.driver_factory() if self.driver_factory else PlaywrightBrowserDriver.from_env(
                    browser='chromium', headless=True, channel='chrome',
                    allow_private_urls=bool(self.fixture_origin), transport=pins)
                sid = secrets.token_hex(16)
                session = BrowserSession(sid, driver, policy, pins, task.agent,
                                         task.decided_by, task, self._head(),
                                         args['_binding']['registration_key'],
                                         args['_binding']['registration_epoch'])
                self.sessions[sid] = session
                new = True
                driver.set_transport(pins)
                driver.set_url_guard(policy.domain_allowed)
                driver.set_execution_guard(lambda: self._session_network_current(session))
                driver.set_ref_resolver(session.resolve_ref)
                if self.driver_factory is None:
                    driver.set_ownership_observer(lambda event, profile, identity: (
                        self._journal_observer(sid, event, profile, identity)))
            else:
                session = self.sessions.get(request.session_id)
                if (session is None or not session.current() or session.agent != task.agent
                        or session.owner != task.decided_by or session.head != self._head()
                        or args['_binding']['session_generation'] != session.generation):
                    raise BrowserPlanRefused('browser_session_unavailable')
            if session.lock.locked():
                raise BrowserPlanRefused('browser_session_busy')
            async with session.lock:
                session.active_task, session.active_args = task, args
                session.active_worker = asyncio.current_task()
                entered = True
                try:
                    if request.mode == 'close':
                        if not await self._close_session(session):
                            raise BrowserPlanRefused('browser_cleanup_unverified')
                        return {'ok': True, 'session_id': request.session_id, 'closed': True}
                    result = await self._run_session_steps(session, task, args, request)
                    self._ensure_reaper()
                    return result
                finally:
                    session.active_task = None
                    session.active_args = None
                    session.active_worker = None
        except (BrowserPlanRefused, TimeoutError) as exc:
            if session is not None and (new or (entered and request is not None and request.mode != 'close')):
                await self._close_session(session)
            return {'ok': False, 'reason': 'browser_timeout' if isinstance(exc, TimeoutError) else str(exc)}
        except asyncio.CancelledError:
            if session is not None and not session.closed:
                await self._close_session(session)
            raise
        except Exception:
            if session is not None and not session.closed:
                await self._close_session(session)
            return {'ok': False, 'reason': 'browser_failed'}
