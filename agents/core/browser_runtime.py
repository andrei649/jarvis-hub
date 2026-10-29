"""Canonical, bounded browser plans and the owner-approved runtime boundary."""
from __future__ import annotations

import asyncio
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

MAX_STEPS = 20
MAX_PLAN_BYTES = 60_000
TOOL = 'browser_run'
KIND = 'toolrpc.browser_run'
TITLE = 'Run approved browser plan'
INPUT_SCHEMA = {
    'type': 'object',
    'properties': {'steps': {'type': 'array', 'minItems': 1, 'maxItems': MAX_STEPS,
                             'items': {'type': 'object'}}},
    'required': ['steps'], 'additionalProperties': False,
}


class BrowserPlanRefused(ValueError):
    """A browser proposal cannot be run or presented for approval."""


@dataclass(frozen=True)
class BrowserPlan:
    steps: tuple[dict, ...]
    sha256: str


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


def _server_domains() -> tuple[str, ...]:
    from .browser_transport import is_private_host_literal

    raw = os.getenv('JARVIS_BROWSER_ALLOWED_DOMAINS', '')
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
        if os.getenv('JARVIS_PLAYWRIGHT_BROWSER', 'chromium') != 'chromium':
            return False
        if fixture_origin is None:
            _server_domains()
        return importlib.util.find_spec('playwright') is not None and bool(_chrome_binary())
    except (ImportError, ValueError, BrowserPlanRefused):
        return False


class BrowserRuntime:
    """One owner-approved plan, one ephemeral Chromium profile, one cleanup owner."""

    def __init__(self, *, queue, approved_task, authorizer, enqueue,
                 execution_check, registration=None, fixture_origin=None,
                 driver_factory=None, control_current=None, revalidator=None):
        if fixture_origin is not None and not os.getenv('PYTEST_CURRENT_TEST'):
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
        self._uncertain_drivers = []

    def _head(self):
        domains = ('fixture:' + self.fixture_origin,) if self.fixture_origin else _server_domains()
        source = []
        for name in ('browser_runtime.py', 'browser_agent.py', 'browser_transport.py',
                     'browser_playwright.py', 'browser_kernel.py'):
            source.append(hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest())
        encoded = json.dumps([domains, source, _chrome_binary(),
                              os.getenv('JARVIS_PLAYWRIGHT_BROWSER', 'chromium')],
                             separators=(',', ':')).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _ready(self):
        if self._uncertain_drivers:
            raise BrowserPlanRefused('browser_cleanup_unverified')
        if not local_browser_ready(kernel=self.authorizer, queue=self.queue,
                                   fixture_origin=self.fixture_origin):
            raise BrowserPlanRefused('browser_unavailable')

    def preflight(self, args):
        from .tool_rpc import ToolRPCValidationError

        try:
            self._ready()
            task = self.approved_task()
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
                close_task = asyncio.create_task(driver.close())
                try:
                    await asyncio.shield(close_task)
                except asyncio.CancelledError:
                    try:
                        await asyncio.shield(close_task)
                    except Exception:
                        self._uncertain_drivers.append(driver)
                        raise BrowserPlanRefused('browser_cleanup_unverified') from None
                    raise
                except Exception:
                    self._uncertain_drivers.append(driver)
                    raise BrowserPlanRefused('browser_cleanup_unverified') from None
        except (BrowserPlanRefused, TimeoutError) as exc:
            return {'ok': False, 'reason': 'browser_timeout' if isinstance(exc, TimeoutError) else str(exc)}

    async def reap_uncertain(self):
        """Bounded explicit retry of retained cleanup; never forget an uncertain owner."""
        remaining = []
        for driver in self._uncertain_drivers:
            try:
                async with asyncio.timeout(10):
                    await driver.close()
            except Exception:
                remaining.append(driver)
        self._uncertain_drivers = remaining
        return not remaining
