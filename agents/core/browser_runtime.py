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
            'console': {'action'}, 'get_images': {'action'},
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
                 driver_factory=None, control_current=None, revalidator=None,
                 dialog_worker=None, dialog_registration=None):
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
        self.dialog_worker = dialog_worker
        self.dialog_registration = dialog_registration
        self._dialog_episodes = {}
        if queue is not None:
            from .browser_dialogs import DialogPromptStore

            self.dialog_prompts = DialogPromptStore(
                task_lookup=queue.get,
                task_fingerprint=lambda task: task.mediation_task_sha256,
                on_bind=self._dialog_bound,
            )
        else:
            self.dialog_prompts = None
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
                     'browser_playwright.py', 'browser_kernel.py', 'browser_session.py',
                     'browser_dialogs.py'):
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

    def _episode_for(self, agent: str, opener_task_id: int,
                     dialog_id: str | None = None):
        from .autonomy.consent_registration import trusted_registration_key

        if type(opener_task_id) is not int or opener_task_id <= 0:
            return None
        episode = self._dialog_episodes.get(opener_task_id)
        if (episode is None or episode.agent != agent
                or (dialog_id is not None and episode.dialog_id != dialog_id)
                or episode.pending() is None):
            return None
        session = self.sessions.get(episode.session_id)
        dialog_spec = self.dialog_registration() if callable(self.dialog_registration) else None
        if (session is None or session.generation != episode.generation
                or session.active_task is None
                or session.active_task.id != episode.opener_task_id
                or not self._session_registration_current(session)
                or type(dialog_spec) is not dict
                or dialog_spec.get('_consent_registration_key') != episode.dialog_registration_key
                or dialog_spec.get('_grouping_epoch') != episode.dialog_registration_epoch
                or trusted_registration_key('browser_dialog', dialog_spec)
                   != episode.dialog_registration_key
                or self.control_current(session.active_task) is not True):
            return None
        return episode

    async def dialog_pending(self, agent: str, args: dict) -> dict:
        if type(args) is not dict or set(args) != {'opener_task_id'}:
            return {'status': 'unavailable'}
        episode = self._episode_for(agent, args['opener_task_id'])
        if episode is None or self.queue is None:
            return {'status': 'none'}
        try:
            live = await asyncio.to_thread(self.queue.get, episode.opener_task_id)
            if (live is None or live.status != 'running' or live.agent != agent
                    or self.queue.execution_fingerprint(live) != episode.opener_fingerprint
                    or not await asyncio.to_thread(
                        self.queue.validate_mediated_execution,
                        live, episode.opener_fingerprint)):
                return {'status': 'unavailable'}
        except Exception:
            return {'status': 'unavailable'}
        current = self._episode_for(agent, episode.opener_task_id, episode.dialog_id)
        return current.pending() if current is episode else {'status': 'unavailable'}

    async def owner_dialog_pending(self, owner: str, opener_task_id: int) -> dict:
        episode = self._dialog_episodes.get(opener_task_id)
        if episode is None or episode.owner != owner:
            return {'status': 'none'}
        pending = await self.dialog_pending(episode.agent, {'opener_task_id': opener_task_id})
        if pending.get('status') == 'pending' and episode.response_id is not None:
            pending = {**pending, 'response_task_id': episode.response_id}
        return pending

    async def owner_dialog_propose(self, owner: str, opener_task_id: int,
                                   raw: dict) -> int:
        from .tool_rpc import ToolRPCValidationError

        episode = self._dialog_episodes.get(opener_task_id)
        if (episode is None or episode.owner != owner or type(raw) is not dict
                or raw.get('opener_task_id') != opener_task_id):
            raise ToolRPCValidationError('dialog_unavailable')
        lease = self.dialog_seal(episode.agent, raw)
        try:
            safe = self.dialog_preflight(lease.args)
            task_id = await self.dialog_intake(episode.agent, safe)
            lease.bind(task_id)
            return task_id
        finally:
            lease.release()

    async def owner_dialog_card(self, owner: str, task_id: int) -> dict | None:
        if type(task_id) is not int or task_id <= 0 or self.queue is None:
            return None
        task = await asyncio.to_thread(self.queue.get, task_id)
        if (task is None or task.kind != 'toolrpc.browser_dialog'
                or not (task.decided_by == owner or (
                    task.status in {'proposed', 'blocked', 'deferred'}
                    and task.decided_by in {None, 'policy'}))):
            return None
        safe = task.payload.get('args')
        if type(safe) is not dict:
            return None
        episode = self._dialog_episodes.get(safe.get('opener_task_id'))
        if (episode is None or episode.owner != owner
                or episode.response_id != task_id
                or episode.dialog_id != safe.get('dialog_id')
                or self._episode_for(episode.agent, episode.opener_task_id,
                                        episode.dialog_id) is not episode):
            return None
        value = None
        if 'prompt_ref' in safe:
            value = self.dialog_prompts.peek(
                safe['prompt_ref'], task_id=task_id,
                fingerprint=task.mediation_task_sha256, agent=task.agent)
            if value is None:
                return None
        pending = episode.pending()
        return None if pending is None else {
            'task_id': task_id, 'status': task.status,
            'choice': safe.get('choice'), 'prompt_text': value,
            'dialog': pending,
        }

    def owner_stage_dialog_text(self, owner: str, opener_task_id: int,
                                dialog_id: str, text: str) -> str:
        episode = self._dialog_episodes.get(opener_task_id)
        if (episode is None or episode.owner != owner
                or episode.dialog_id != dialog_id
                or episode.observed is None or episode.observed.kind != 'prompt'
                or self._episode_for(episode.agent, opener_task_id, dialog_id)
                   is not episode):
            raise ValueError('dialog_unavailable')
        return self.dialog_prompts.stage_owner_text(
            episode.agent, opener_task_id, dialog_id, text)

    def dialog_seal(self, agent: str, raw: dict):
        from .tool_rpc import ToolRPCValidationError

        if self.dialog_prompts is None or type(raw) is not dict:
            raise ToolRPCValidationError('dialog_unavailable')
        episode = self._episode_for(agent, raw.get('opener_task_id'), raw.get('dialog_id'))
        if episode is None:
            raise ToolRPCValidationError('dialog_unavailable')
        observed = episode.observed
        has_text = ('prompt_text' in raw or 'prompt_ref' in raw)
        if (observed is None or (has_text != (
                observed.kind == 'prompt' and raw.get('choice') == 'accept'))):
            raise ToolRPCValidationError('invalid_dialog_prompt')
        return self.dialog_prompts.seal(agent, raw, binding={
            'opener_fingerprint': episode.opener_fingerprint,
            'session_id': episode.session_id,
            'session_generation': episode.generation,
            'plan_sha256': episode.plan_sha256,
            'step_index': episode.step_index,
        })

    def dialog_preflight(self, args: dict) -> dict:
        from .tool_rpc import ToolRPCValidationError

        base = {'opener_task_id', 'dialog_id', 'choice', 'opener_fingerprint',
                'session_id', 'session_generation', 'plan_sha256', 'step_index'}
        if type(args) is not dict or set(args) not in (base, base | {
                'prompt_ref', 'prompt_digest', 'prompt_length'}):
            raise ToolRPCValidationError('invalid_dialog_proposal')
        opener_id = args.get('opener_task_id')
        if type(opener_id) is not int:
            raise ToolRPCValidationError('dialog_unavailable')
        episode = self._dialog_episodes.get(opener_id)
        if (episode is None or self._episode_for(
                episode.agent, opener_id, args.get('dialog_id')) is not episode):
            raise ToolRPCValidationError('dialog_unavailable')
        return args

    def _dialog_bound(self, args: dict, task_id: int) -> None:
        episode = self._dialog_episodes.get(args['opener_task_id'])
        if (episode is None or episode.dialog_id != args['dialog_id']
                or episode.opener_fingerprint != args['opener_fingerprint']):
            raise ValueError('dialog_episode_stale')
        episode.bind_response(task_id)

    def _dialog_memory_current(self, session, episode) -> bool:
        task = session.active_task
        return bool(
            self._dialog_episodes.get(episode.opener_task_id) is episode
            and episode.pending() is not None and session.current()
            and task is not None and task.id == episode.opener_task_id
            and session.generation == episode.generation
            and session.head == self._head()
            and self._session_registration_current(session)
            and self.control_current(task) is True
        )

    async def _respond_dialog_episode(self, session, episode, bridge,
                                      step_timeout, plan_deadline) -> None:
        from .browser_dialogs import DialogObservationRefused
        from .browser_kernel import approved_dialog_scope, authorize_dialog_response

        loop = asyncio.get_running_loop()
        if not episode.capture(now=loop.time()):
            raise DialogObservationRefused('dialog_frame_unknown')
        episode.expires_at = min(loop.time() + 60, plan_deadline, session.created + 600)
        step_timeout.reschedule(episode.expires_at)
        if not self._dialog_memory_current(session, episode):
            raise DialogObservationRefused('dialog_unavailable')
        while loop.time() < episode.expires_at:
            if not self._dialog_memory_current(session, episode):
                raise DialogObservationRefused('dialog_unavailable')
            if episode.response_id is None:
                try:
                    await asyncio.wait_for(episode.response_ready.wait(),
                                           min(.2, episode.expires_at - loop.time()))
                except TimeoutError:
                    continue
            response_id = episode.response_id
            if response_id is None:
                continue
            response = await asyncio.to_thread(self.queue.get, response_id)
            if response is None or response.status in {'denied', 'failed', 'cancelled'}:
                raise DialogObservationRefused('dialog_unresolved')
            if response.status == 'approved':
                break
            await asyncio.sleep(min(.1, max(0, episode.expires_at - loop.time())))
        else:
            raise DialogObservationRefused('dialog_unresolved')
        claimed = await self.dialog_worker.claim_browser_dialog_bridge(bridge, response_id)
        if claimed is None or claimed.status != 'running':
            raise DialogObservationRefused('dialog_unresolved')
        episode.claimed_task = claimed
        safe = claimed.payload.get('args')
        if (type(safe) is not dict or safe.get('dialog_id') != episode.dialog_id
                or safe.get('session_id') != session.id
                or safe.get('session_generation') != episode.generation
                or safe.get('plan_sha256') != episode.plan_sha256
                or safe.get('step_index') != episode.step_index):
            raise DialogObservationRefused('dialog_unresolved')
        claimed_fp = self.queue.execution_fingerprint(claimed)
        opener_live, response_live = await asyncio.gather(
            asyncio.to_thread(self.queue.get, episode.opener_task_id),
            asyncio.to_thread(self.queue.get, claimed.id),
        )
        if (opener_live is None or response_live is None
                or self.queue.execution_fingerprint(opener_live) != episode.opener_fingerprint
                or self.queue.execution_fingerprint(response_live) != claimed_fp
                or not await asyncio.to_thread(self.queue.validate_mediated_execution,
                                                claimed, claimed_fp)
                or not await asyncio.to_thread(self.queue.validate_mediated_execution,
                                                opener_live, episode.opener_fingerprint)
                or not self._dialog_memory_current(session, episode)):
            raise DialogObservationRefused('dialog_unresolved')
        observed = episode.observed
        if observed is None:
            raise DialogObservationRefused('dialog_unresolved')
        prompt_text = None
        ref = safe.get('prompt_ref')
        if ref is not None:
            prompt_text = self.dialog_prompts.consume(
                ref, task_id=claimed.id, fingerprint=claimed.mediation_task_sha256,
                agent=claimed.agent)
            if prompt_text is None:
                raise DialogObservationRefused('dialog_unresolved')
        elif observed.kind == 'prompt' and safe.get('choice') == 'accept':
            raise DialogObservationRefused('dialog_unresolved')
        with approved_dialog_scope(
            claimed, opener_live, observed.dialog, session_id=session.id,
            generation=episode.generation, plan_sha256=episode.plan_sha256,
            step_index=episode.step_index,
            current=lambda: self._dialog_memory_current(session, episode),
        ):
            if not await authorize_dialog_response(self.authorizer):
                raise DialogObservationRefused('dialog_unresolved')
            if not self._dialog_memory_current(session, episode):
                raise DialogObservationRefused('dialog_unresolved')
            if not await session.driver.respond_dialog(
                    observed, safe['choice'], prompt_text=prompt_text):
                raise DialogObservationRefused('dialog_unresolved')
        episode.responded = True

    async def _settle_dialog(self, episode, *, success: bool) -> None:
        from .autonomy.queue import TaskStatus

        claimed = getattr(episode, 'claimed_task', None)
        if claimed is None:
            return
        result = {'status': 'completed'} if success else {
            'reason': 'dialog_outcome_unknown', 'possibly_applied': True}
        status = TaskStatus.DONE if success else TaskStatus.FAILED
        await asyncio.to_thread(self.queue.transition, claimed.id, status, result=result)

    async def dialog_intake(self, agent: str, args: dict) -> int:
        return await asyncio.to_thread(self._dialog_intake_sync, agent, args)

    def _dialog_intake_sync(self, agent: str, args: dict) -> int:
        from .action_origin import current_action_origin
        from .approval_outcomes import tool_approval_scope
        from .autonomy.approval_grouping import model_request_scope
        from .autonomy.consent_registration import trusted_registration_key
        from .kernel import Action, Decision, Verdict
        from .security.taint import mark_if_untrusted
        from .tool_rpc import ToolRPCValidationError

        episode = self._episode_for(agent, args.get('opener_task_id'), args.get('dialog_id'))
        spec = self.dialog_registration() if callable(self.dialog_registration) else None
        if (episode is None or spec is None or self.queue is None
                or spec.get('capability_id') != 'tool:browser_dialog'
                or trusted_registration_key('browser_dialog', spec)
                   != spec.get('_consent_registration_key')):
            raise ToolRPCValidationError('dialog_unavailable')
        opener = self.queue.get(episode.opener_task_id)
        if (opener is None or opener.status != 'running'
                or opener.agent != agent or opener.decided_by != episode.owner
                or self.queue.execution_fingerprint(opener) != episode.opener_fingerprint
                or not self.queue.validate_mediated_execution(
                    opener, episode.opener_fingerprint)):
            raise ToolRPCValidationError('dialog_unavailable')
        if (args['opener_fingerprint'] != episode.opener_fingerprint
                or args['session_id'] != episode.session_id
                or args['session_generation'] != episode.generation
                or args['plan_sha256'] != episode.plan_sha256
                or args['step_index'] != episode.step_index):
            raise ToolRPCValidationError('dialog_unavailable')
        origin = current_action_origin()
        payload = mark_if_untrusted(
            {'tool': 'browser_dialog', 'args': args, 'target': 'browser_dialog'}, origin)
        action = Action(kind='toolrpc.browser_dialog', agent=agent,
                        title='Respond to observed browser dialog', payload=payload,
                        origin=origin)
        decision = self.authorizer(action)
        if not isinstance(decision, Decision) or decision.verdict not in {
                Verdict.GRANT, Verdict.QUEUE}:
            raise ToolRPCValidationError('kernel_denied')
        with tool_approval_scope('browser_dialog'), model_request_scope(
            actor=agent, tool='browser_dialog', args=args,
            epoch=spec['_grouping_epoch'],
            registration_is_live=lambda: self.dialog_registration() is spec,
            registration_key=spec['_consent_registration_key'],
            registration_key_is_live=lambda candidate: (
                self.dialog_registration() is spec
                and trusted_registration_key('browser_dialog', spec) == candidate),
        ):
            task_id = self.enqueue(agent, 'toolrpc.browser_dialog',
                                   'Respond to observed browser dialog', payload=payload,
                                   risk_tier=3, autonomy_level='ask', origin=origin)
        task = self.queue.get(task_id)
        if (task is None or task.kind != 'toolrpc.browser_dialog'
                or task.payload != payload or task.autonomy_level != 'ask'):
            raise ToolRPCValidationError('dialog_proposal_unbound')
        return task_id

    def _session_registration_current(self, session) -> bool:
        from .autonomy.consent_registration import trusted_registration_key

        try:
            spec = self.registration() if callable(self.registration) else None
            return bool(
                type(session.registration_key) is str and bool(session.registration_key)
                and type(session.registration_epoch) is str
                and re.fullmatch(r'[0-9a-f]{32}', session.registration_epoch) is not None
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
        from .browser_dialogs import DialogEpisode, run_with_dialog_supervisor
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
                    async with asyncio.timeout(15 if step['action'] != 'wait' else 31) as step_timeout:
                        if step['action'] in {'navigate', 'extract', 'snapshot', 'wait',
                                              'console', 'get_images'}:
                            read_gate = await executor.check_read(step)
                            if read_gate.status != 'completed':
                                raise BrowserPlanRefused('browser_kernel_refused')
                        if step['action'] == 'snapshot':
                            outcome = {'action': 'snapshot', 'status': 'done',
                                       'result': await session.snapshot()}
                        elif step['action'] == 'console':
                            outcome = {'action': 'console', 'status': 'done',
                                       'result': await session.driver.console()}
                        elif step['action'] == 'get_images':
                            outcome = {'action': 'get_images', 'status': 'done',
                                       'result': await session.get_images()}
                        elif (self.dialog_worker is not None
                              and step['action'] in {'navigate', 'click', 'type', 'submit',
                                                    'scroll', 'back', 'press'}):
                            observer = await driver.start_dialog_observer()
                            await driver.arm_dialog_observer(document_epoch=session.generation)
                            bridge = self.dialog_worker.begin_browser_dialog_bridge(task)
                            if bridge is None:
                                raise BrowserPlanRefused('dialog_unavailable')
                            episode = DialogEpisode(
                                opener_task_id=task.id,
                                opener_fingerprint=self.queue.execution_fingerprint(task),
                                agent=task.agent, owner=task.decided_by,
                                session_id=session.id, generation=session.generation,
                                plan_sha256=request.sha256, step_index=index,
                                observer=observer, expires_at=deadline,
                                dialog_registration_key=(
                                    self.dialog_registration() or {}).get(
                                        '_consent_registration_key'),
                                dialog_registration_epoch=(
                                    self.dialog_registration() or {}).get('_grouping_epoch'))
                            self._dialog_episodes[task.id] = episode
                            try:
                                try:
                                    outcome = await run_with_dialog_supervisor(
                                        lambda current_step=step: browser.run_step(current_step),
                                        observer,
                                        lambda _observed, current_episode=episode,
                                               current_bridge=bridge: self._respond_dialog_episode(
                                            session, current_episode, current_bridge,
                                            step_timeout, deadline),
                                    )
                                except ExceptionGroup:
                                    raise BrowserPlanRefused('dialog_unresolved') from None
                                await self._settle_dialog(episode, success=True)
                            except BaseException:
                                await self._settle_dialog(episode, success=False)
                                raise
                            finally:
                                self._dialog_episodes.pop(task.id, None)
                                episode.close()
                                bridge.close()
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
