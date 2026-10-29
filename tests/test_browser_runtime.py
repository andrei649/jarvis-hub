"""The selected browser plan is exact, bounded, and inert without owner authority."""
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_real_driver_mutation_requires_exact_live_task_bound_step():
    from agents.core.browser_kernel import BrowserActionExecutor, approved_step_scope
    from agents.core.kernel import Decision, Verdict

    class Driver:
        requires_kernel = True
        def __init__(self):
            self.calls = []
        async def click(self, **kwargs):
            self.calls.append(kwargs)
            return {'clicked': kwargs['selector']}

    driver = Driver()
    actions = []
    def kernel(action, *, approval_check):
        actions.append(action)
        return Decision(Verdict.GRANT if approval_check(action) else Verdict.QUEUE, tier=3)

    executor = BrowserActionExecutor(driver, authorizer=kernel)
    task = SimpleNamespace(id=42, agent='jarvis', origin='generated')
    step = {'action': 'click', 'selector': '#submit'}
    assert (await executor.perform(step)).status == 'refused'
    with approved_step_scope(task, 'a' * 64, 2, step, lambda: True):
        from asyncio import create_task

        assert (await create_task(executor.perform(step))).status == 'refused'
        assert (await executor.perform({'action': 'click', 'selector': '#other'})).status == 'refused'
        assert (await executor.perform(step)).status == 'completed'
    assert driver.calls == [{'selector': '#submit'}]
    assert actions[0].payload == {
        'action': 'click', 'args': {'selector': '#submit'}, 'risk_tier': 3,
        'approved_task_id': 42, 'plan_sha256': 'a' * 64, 'step_index': 2,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(('method', 'kwargs'), [
    ('click', {'selector': '#go'}),
    ('type', {'selector': '#go', 'text': 'x'}),
    ('submit', {'selector': '#go'}),
    ('execute_js', {'script': '1+1'}),
    ('upload', {'selector': '#go', 'paths': '/tmp/none'}),
    ('download', {'selector': '#go'}),
])
async def test_direct_real_driver_mutation_refuses_before_browser_start(method, kwargs):
    from agents.core.browser_playwright import PlaywrightBrowserDriver, PlaywrightHostDisabled

    driver = PlaywrightBrowserDriver(host_enabled=True)
    with pytest.raises(PlaywrightHostDisabled, match='approved browser step required'):
        await getattr(driver, method)(**kwargs)
    assert driver.profile_dir is None


@pytest.mark.asyncio
async def test_close_failure_retains_owned_profile_until_verified_retry(tmp_path):
    from agents.core.browser_playwright import PlaywrightBrowserDriver, PlaywrightDriverError

    class Context:
        fails = True
        async def close(self):
            if self.fails:
                raise RuntimeError('close failed')

    context = Context()
    profile = tmp_path / 'nerva-browser-owned'
    profile.mkdir()
    (profile / 'marker').write_text('owned')
    driver = PlaywrightBrowserDriver(host_enabled=True)
    driver._context = context
    driver._profile_dir = profile
    with pytest.raises(PlaywrightDriverError, match='browser_cleanup_unverified'):
        await driver.close()
    assert driver._context is context and profile.exists()
    context.fails = False
    await driver.close()
    assert driver._context is None and driver.profile_dir is None and not profile.exists()


@pytest.mark.asyncio
async def test_runtime_retains_uncertain_driver_and_blocks_next_proposal(tmp_path, monkeypatch):
    from agents.core.browser_runtime import BrowserPlanRefused, BrowserRuntime

    profile = tmp_path / 'nerva-browser-retained'
    profile.mkdir()

    class Driver:
        requires_kernel = False
        fails = True
        profile_dir = profile
        def set_transport(self, resolver):
            self.resolver = resolver
        def set_url_guard(self, guard):
            self.guard = guard
        async def navigate(self, *, url):
            return {'url': url}
        async def close(self):
            if self.fails:
                raise RuntimeError('uncertain close')
            profile.rmdir()

    driver = Driver()
    runtime = BrowserRuntime(queue=None, approved_task=lambda: SimpleNamespace(agent='jarvis'),
                             authorizer=None, enqueue=None, execution_check=lambda _: True,
                             fixture_origin='http://fixture.browser.test:45678',
                             driver_factory=lambda: driver)
    monkeypatch.setattr(runtime, '_ready', lambda: None)
    monkeypatch.setattr(runtime, '_current', lambda task, args: True)
    monkeypatch.setattr(runtime, 'preflight', lambda args: args)
    answer = await runtime.execute({'steps': [
        {'action': 'navigate', 'url': 'http://fixture.browser.test:45678/'},
    ]})
    assert answer == {'ok': False, 'reason': 'browser_cleanup_unverified'}
    assert runtime._uncertain_drivers == [driver] and profile.exists()
    monkeypatch.undo()
    with pytest.raises(BrowserPlanRefused, match='browser_cleanup_unverified'):
        runtime._ready()
    driver.fails = False
    assert await runtime.reap_uncertain() is True
    assert runtime._uncertain_drivers == [] and not profile.exists()


@pytest.mark.parametrize('plan', [
    [],
    [{'action': 'navigate', 'url': 'https://example.com'}] * 21,
    [{'action': 'execute_js', 'script': 'alert(1)'}],
    [{'action': 'navigate', 'url': 'https://example.com', 'allowlist': ['example.com']}],
    [{'action': 'navigate', 'url': 'file:///etc/passwd'}],
    [{'action': 'navigate', 'url': 'https://exa\nmple.com/'}],
    [{'action': 'navigate', 'url': 'https://example.com/' + 'x' * 2000}],
    [{'action': 'navigate', 'url': 'https://example.com/'},
     {'action': 'click', 'selector': 'x' * 513}],
    [{'action': 'click', 'selector': '#x', 'approved_task_id': 1}],
    [{'action': 'type', 'selector': '#x', 'text': 'x' * 4001}],
    [{'action': 'wait', 'timeout_ms': 30001}],
])
def test_browser_plan_rejects_unapproved_shape_and_bounds(plan):
    from agents.core.browser_runtime import BrowserPlanRefused, validate_browser_plan

    with pytest.raises(BrowserPlanRefused):
        validate_browser_plan({'steps': plan})


def test_browser_plan_canonical_bytes_are_stable_and_preserve_exact_step():
    from agents.core.browser_runtime import validate_browser_plan

    first = validate_browser_plan({'steps': [
        {'action': 'navigate', 'url': 'https://example.com/path?x=1'},
        {'action': 'snapshot', 'selector': 'body'},
        {'action': 'click', 'selector': '#submit'},
    ]})
    second = validate_browser_plan({'steps': [
        {'url': 'https://example.com/path?x=1', 'action': 'navigate'},
        {'selector': 'body', 'action': 'snapshot'},
        {'selector': '#submit', 'action': 'click'},
    ]})
    assert first.steps == second.steps
    assert first.sha256 == second.sha256
    assert first.steps[0]['url'] == 'https://example.com/path?x=1'


def test_readiness_requires_all_server_prerequisites_and_ignores_private_optin(monkeypatch):
    from agents.core import browser_runtime as runtime

    queue = SimpleNamespace(mediation_mode='enforce')
    def gate(action):
        return action
    monkeypatch.setattr(runtime.importlib.util, 'find_spec', lambda name: object())
    monkeypatch.setattr(runtime, '_chrome_binary', lambda: '/installed/chrome')
    monkeypatch.setenv('JARVIS_UNIFIED_ACTION_API', '1')
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.setenv('JARVIS_PLAYWRIGHT_HOST', '1')
    monkeypatch.setenv('JARVIS_PLAYWRIGHT_BROWSER', 'chromium')
    monkeypatch.delenv('JARVIS_BROWSER_ALLOWED_DOMAINS', raising=False)
    monkeypatch.setenv('JARVIS_BROWSER_ALLOW_PRIVATE_URLS', '1')
    assert runtime.local_browser_ready(kernel=gate, queue=queue) is False
    monkeypatch.setenv('JARVIS_BROWSER_ALLOWED_DOMAINS', 'example.com')
    assert runtime.local_browser_ready(kernel=gate, queue=queue) is True
    monkeypatch.setenv('JARVIS_PLAYWRIGHT_BROWSER', 'firefox')
    assert runtime.local_browser_ready(kernel=gate, queue=queue) is False
    monkeypatch.setenv('JARVIS_PLAYWRIGHT_BROWSER', 'chromium')
    queue.mediation_mode = 'off'
    assert runtime.local_browser_ready(kernel=gate, queue=queue) is False


def test_browser_policy_refuses_ssrf_checker_exception_and_bad_url(monkeypatch):
    from agents.core.browser_agent import BrowserPolicy

    def broken(_url):
        raise RuntimeError('DNS unavailable')

    monkeypatch.setattr('agents.core.security.ssrf.check_ssrf', broken)
    policy = BrowserPolicy(['example.com'])
    assert policy.domain_allowed('https://example.com/')[0] is False
    for url in ('ftp://example.com/', 'https://user:pass@example.com/',
                'https://example.com:bad/', 'https://evil-example.com/'):
        assert policy.domain_allowed(url)[0] is False


def test_public_pin_rejects_mixed_or_invalid_dns_answer():
    from agents.core.browser_transport import BrowserTransportRefused, PinnedResolver

    for ips in (['93.184.216.34', '127.0.0.1'], ['93.184.216.34', 'not-an-ip']):
        pins = PinnedResolver(resolver=lambda _host, *, mode, answers=ips: (answers, None))
        with pytest.raises(BrowserTransportRefused):
            pins.pin('https://example.com/')
        assert pins.pinned_hosts() == frozenset()


@pytest.mark.asyncio
async def test_real_kernel_browser_receipt_is_exact_and_taint_still_queues():
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.browser_kernel import approved_step_scope, browser_receipt_matches
    from agents.core.kernel import Action, Verdict, authorize

    task = SimpleNamespace(id=19, agent='jarvis', origin='generated')
    step = {'action': 'click', 'selector': '#go'}
    payload = {'action': 'click', 'args': {'selector': '#go'}, 'risk_tier': 3,
               'approved_task_id': 19, 'plan_sha256': 'f' * 64, 'step_index': 1}
    action = Action(kind='browser.step', agent='jarvis', origin='generated', payload=payload)
    policy = AutonomyPolicy()
    assert authorize(action, policy=policy,
                     approval_check=browser_receipt_matches).verdict is Verdict.QUEUE
    with approved_step_scope(task, 'f' * 64, 1, step, lambda: True):
        assert authorize(action, policy=policy,
                         approval_check=browser_receipt_matches).verdict is Verdict.GRANT
        assert authorize(action, policy=AutonomyPolicy(mode='ask'),
                         approval_check=browser_receipt_matches).verdict is Verdict.QUEUE
        changed = Action(kind='browser.step', agent='jarvis', origin='generated',
                         payload={**payload, 'args': {'selector': '#other'}})
        assert authorize(changed, policy=policy,
                         approval_check=browser_receipt_matches).verdict is Verdict.QUEUE
        tainted = Action(kind='browser.step', agent='jarvis', origin='external', payload=payload)
        assert authorize(tainted, policy=policy,
                         approval_check=browser_receipt_matches).verdict is Verdict.QUEUE
    external_task = SimpleNamespace(id=19, agent='jarvis', origin='external')
    with approved_step_scope(external_task, 'f' * 64, 1, step, lambda: True):
        assert browser_receipt_matches(tainted) is True
        assert authorize(tainted, policy=policy,
                         approval_check=browser_receipt_matches).verdict is Verdict.QUEUE
