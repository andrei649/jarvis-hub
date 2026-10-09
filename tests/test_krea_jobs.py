"""Krea's durable worker can poll without repeating a paid submit."""

import httpx
import pytest

JOB_ID = "00000000-0000-0000-0000-000000000abc"
POLL_URL = "https://api.krea.ai/jobs/" + JOB_ID
IMAGE_URL = "https://krea.cdn/result.png"  # donor fixture; candidate, not trusted CDN


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


@pytest.mark.asyncio
async def test_pending_then_completed_uses_only_fixed_poll_get_and_donor_backoff():
    from agents.core.media_backends.krea_jobs import poll_job

    clock = Clock()
    urls = []
    replies = iter([
        (200, {"job_id": JOB_ID, "status": "sampling", "result": None}),
        (200, {"job_id": JOB_ID, "status": "completed", "result": {"urls": [IMAGE_URL]}}),
    ])

    async def get_status(url):
        urls.append(url)
        return next(replies)

    checks = []
    result = await poll_job(JOB_ID, get_status, check=lambda: checks.append(clock.now),
                            sleep=clock.sleep, monotonic=clock.monotonic)
    assert result == IMAGE_URL
    assert urls == [POLL_URL, POLL_URL]
    assert clock.waits == pytest.approx([2.0, 2.6])
    assert checks[0] == 0 and checks[-1] == pytest.approx(4.6)


@pytest.mark.asyncio
async def test_retryable_http_and_network_errors_then_complete_without_submit():
    from agents.core.media_backends.krea_jobs import poll_job

    clock = Clock()
    calls = []
    replies = iter([
        (429, {"error": "secret provider text"}),
        httpx.ReadTimeout("secret transport detail"),
        (200, {"status": "completed", "result": {"url": IMAGE_URL}}),
    ])

    async def get_status(url):
        assert url == POLL_URL
        calls.append(url)
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    assert await poll_job(JOB_ID, get_status, check=lambda: None,
                          sleep=clock.sleep, monotonic=clock.monotonic) == IMAGE_URL
    assert len(calls) == 3
    assert clock.waits == pytest.approx([2.0, 2.6, 3.38])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 503, 599])
async def test_only_documented_transient_http_statuses_retry(status):
    from agents.core.media_backends.krea_jobs import poll_job

    clock = Clock()
    count = 0

    async def get_status(url):
        nonlocal count
        count += 1
        return ((status, None) if count == 1 else
                (200, {"status": "completed", "result": {"url": IMAGE_URL}}))

    assert await poll_job(JOB_ID, get_status, check=lambda: None,
                          sleep=clock.sleep, monotonic=clock.monotonic) == IMAGE_URL
    assert count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 422, 499, 600])
async def test_permanent_or_unexpected_http_status_fails_without_retry(status):
    from agents.core.media_backends.krea_jobs import KreaPollResponseError, poll_job

    clock = Clock()
    count = 0

    async def get_status(url):
        nonlocal count
        count += 1
        return status, {"error": "secret provider text"}

    with pytest.raises(KreaPollResponseError) as caught:
        await poll_job(JOB_ID, get_status, check=lambda: None,
                       sleep=clock.sleep, monotonic=clock.monotonic)
    assert "secret" not in str(caught.value)
    assert count == 1 and clock.waits == [2.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    None, [], {}, {"status": "completed", "result": None},
    {"job_id": "different", "status": "completed", "result": {"url": IMAGE_URL}},
    {"job_id": "../bad", "status": "queued", "result": None},
])
async def test_invalid_poll_body_or_job_mismatch_is_final(body):
    from agents.core.media_backends.krea_jobs import KreaPollResponseError, poll_job

    clock = Clock()
    calls = 0

    async def get_status(url):
        nonlocal calls
        calls += 1
        return 200, body

    with pytest.raises(KreaPollResponseError):
        await poll_job(JOB_ID, get_status, check=lambda: None,
                       sleep=clock.sleep, monotonic=clock.monotonic)
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "cancelled"])
async def test_terminal_failed_or_cancelled_job_does_not_expose_provider_error(status):
    from agents.core.media_backends.krea_jobs import KreaJobFailed, poll_job

    clock = Clock()

    async def get_status(url):
        return 200, {"job_id": JOB_ID, "status": status,
                     "result": {"error": "secret provider text"}}

    with pytest.raises(KreaJobFailed) as caught:
        await poll_job(JOB_ID, get_status, check=lambda: None,
                       sleep=clock.sleep, monotonic=clock.monotonic)
    assert caught.value.state == status
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_deadline_stops_before_an_extra_get_and_caps_final_sleep():
    from agents.core.media_backends.krea_jobs import KreaPollDeadline, poll_job

    clock = Clock()
    calls = 0

    async def get_status(url):
        nonlocal calls
        calls += 1
        return 200, {"status": "queued", "result": None}

    with pytest.raises(KreaPollDeadline):
        await poll_job(JOB_ID, get_status, check=lambda: None,
                       sleep=clock.sleep, monotonic=clock.monotonic,
                       deadline_seconds=3)
    assert calls == 1 and clock.waits == pytest.approx([2.0, 1.0])


@pytest.mark.asyncio
async def test_transient_errors_back_off_to_five_seconds_then_deadline():
    from agents.core.media_backends.krea_jobs import KreaPollDeadline, poll_job

    clock = Clock()
    calls = 0

    async def get_status(url):
        nonlocal calls
        calls += 1
        return 503, None

    with pytest.raises(KreaPollDeadline):
        await poll_job(JOB_ID, get_status, check=lambda: None,
                       sleep=clock.sleep, monotonic=clock.monotonic,
                       deadline_seconds=23)
    assert calls == 6
    assert clock.waits == pytest.approx([2.0, 2.6, 3.38, 4.394, 5.0, 5.0, 0.626])


@pytest.mark.asyncio
async def test_unsafe_job_id_is_rejected_before_sleep_or_get():
    from agents.core.media_backends.krea_jobs import poll_job

    clock = Clock()

    async def get_status(url):
        pytest.fail("unsafe job id must not reach transport")

    with pytest.raises(ValueError):
        await poll_job("../escape", get_status, check=lambda: None,
                       sleep=clock.sleep, monotonic=clock.monotonic)
    assert clock.waits == []


@pytest.mark.asyncio
async def test_approval_revocation_during_sleep_prevents_any_get():
    from agents.core.media_backends.krea_jobs import poll_job

    clock = Clock()
    revoked = False
    calls = 0

    async def sleep(seconds):
        nonlocal revoked
        await clock.sleep(seconds)
        revoked = True

    def check():
        if revoked:
            raise PermissionError("approval revoked")

    async def get_status(url):
        nonlocal calls
        calls += 1
        return 200, {"status": "completed", "result": {"url": IMAGE_URL}}

    with pytest.raises(PermissionError, match="approval revoked"):
        await poll_job(JOB_ID, get_status, check=check,
                       sleep=sleep, monotonic=clock.monotonic)
    assert calls == 0


@pytest.mark.asyncio
async def test_approval_revocation_after_get_prevents_result_return_or_extra_get():
    from agents.core.media_backends.krea_jobs import poll_job

    clock = Clock()
    revoked = False
    calls = 0

    def check():
        if revoked:
            raise PermissionError("approval revoked")

    async def get_status(url):
        nonlocal revoked, calls
        calls += 1
        revoked = True
        return 200, {"status": "completed", "result": {"url": IMAGE_URL}}

    with pytest.raises(PermissionError, match="approval revoked"):
        await poll_job(JOB_ID, get_status, check=check,
                       sleep=clock.sleep, monotonic=clock.monotonic)
    assert calls == 1


@pytest.mark.asyncio
async def test_unexpected_transport_error_is_safe_final_response_error():
    from agents.core.media_backends.krea_jobs import KreaPollResponseError, poll_job

    clock = Clock()

    async def get_status(url):
        raise httpx.RemoteProtocolError("secret provider text")

    with pytest.raises(KreaPollResponseError) as caught:
        await poll_job(JOB_ID, get_status, check=lambda: None,
                       sleep=clock.sleep, monotonic=clock.monotonic)
    assert "secret" not in str(caught.value)
