"""Trusted raw stream metadata never comes from child-supplied JSON."""
import hashlib

import pytest

from agents.core.environments.output_limits import read_capped_stream
from tests.test_local_transport import _FakeSpawn, _FakeStream


@pytest.mark.asyncio
@pytest.mark.parametrize('raw,cap,valid', [(b'', 8, True), ('a€b'.encode(), 8, True),
    (b'a\xffb', 8, False), (b'abcdefgh' * 100, 8, True), (b'\xe2', 8, False)])
async def test_capture_hashes_every_chunk_before_truncation(raw, cap, valid):
    from agents.core.environments.output_capture import OutputCapture
    capture = OutputCapture()
    await read_capped_stream(_FakeStream(raw), max_content_bytes=cap, chunk_size=1, sink=capture.feed)
    result = capture.seal(cap)
    assert result['sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['byte_count'] == len(raw) and result['complete'] is True
    assert result['utf8_valid'] is valid
    assert result['snapshot_complete'] is (len(raw) <= cap and valid)


@pytest.mark.asyncio
async def test_local_transport_adds_host_capture_metadata(tmp_path):
    from agents.core.environments.local_transport import LocalHostTransport
    raw = b'{"stdout_capture":{"sha256":"forged"}}'
    transport = LocalHostTransport(roots=[tmp_path], spawn=_FakeSpawn(stdout=raw))
    result = await transport.run(['python', '-V'])
    assert result['stdout_capture']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['stdout_capture']['complete'] is True


@pytest.mark.asyncio
async def test_hidden_middle_changes_have_distinct_trusted_digests(tmp_path):
    from agents.core.environments.local_transport import LocalHostTransport
    results = []
    for middle in (b'A', b'B'):
        transport = LocalHostTransport(roots=[tmp_path], spawn=_FakeSpawn(stdout=b'head' + middle * 100 + b'tail'))
        results.append(await transport.run(['python', '-V'], max_output=8))
    assert results[0]['stdout'] == results[1]['stdout']
    assert results[0]['stdout_capture']['sha256'] != results[1]['stdout_capture']['sha256']
    assert all(not result['stdout_capture']['snapshot_complete'] for result in results)


@pytest.mark.asyncio
async def test_failed_process_cannot_seal_successful_observation(tmp_path):
    from agents.core.environments.local_transport import LocalHostTransport
    transport = LocalHostTransport(roots=[tmp_path], spawn=_FakeSpawn(stdout=b'observation', returncode=1))
    result = await transport.run(['python', '-V'])
    assert not result['ok'] and result['stdout_capture']['complete'] is False
