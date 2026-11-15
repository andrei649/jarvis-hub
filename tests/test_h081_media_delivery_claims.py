"""A keyed file must have a durable attempting claim before transport."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.core.channels import delivery_ledger, media_delivery
from tests.test_g16_channel_media_sms import PNG, _telegram, _Turn


@pytest.fixture
def discord_rig(tmp_path, monkeypatch):
    # Missing optional Discord SDK skips only Discord cases, not Telegram probes.
    from tests.test_h070_discord_media import _request, rig

    fixture = rig.__wrapped__(tmp_path, monkeypatch)
    fixture.payload = _request(fixture)
    return fixture


class _Unclaimable:
    send = True
    already_sent = False

    def attempting(self):
        pass

    def attempting_checked(self):
        return False

    def finished(self, *_args):
        pass


def _broken_store(mode):
    if mode == "missing":
        return None

    def open_delivery(*_args, **_kwargs):
        if mode == "open_error":
            raise OSError("fixture storage unavailable")
        return _Unclaimable()

    return SimpleNamespace(open_delivery=open_delivery)


@pytest.mark.parametrize("mode", ["missing", "open_error", "stale_claim"])
async def test_telegram_file_withholds_when_durable_claim_is_unavailable(tmp_path, monkeypatch, mode):
    target = tmp_path / "chart.png"
    target.write_bytes(PNG)
    monkeypatch.setattr(media_delivery, "allowed_roots", lambda: [tmp_path])
    monkeypatch.setattr(delivery_ledger, "store", lambda: _broken_store(mode))
    channel = _telegram()
    with _Turn(channel):
        assert await channel._deliver_media(42, [str(target)]) is False
    assert "sendPhoto" not in channel.client.methods()
    assert "sendDocument" not in channel.client.methods()


@pytest.mark.parametrize("mode", ["missing", "open_error", "stale_claim"])
async def test_discord_approved_file_withholds_when_claim_is_unavailable(discord_rig, monkeypatch, mode):
    rig = discord_rig
    payload = rig.payload
    # The governed text reply gets a real durable receipt; only the subsequent
    # file claim fails, after the approved broker has revalidated the file.
    real = delivery_ledger.store()
    assert real is not None
    calls = 0

    def store():
        nonlocal calls
        calls += 1
        return real if calls == 1 else _broken_store(mode)

    monkeypatch.setattr(delivery_ledger, "store", store)
    outcome = await rig.broker.execute(SimpleNamespace(id=17, payload=payload))
    assert outcome["status"] == "failed"
    assert rig.dm.send.await_count == 1
    assert not any("file" in call.kwargs for call in rig.dm.send.await_args_list)


async def test_discord_raised_file_send_records_unknown_and_never_retries(discord_rig):
    rig = discord_rig
    payload = rig.payload
    rig.dm.send = AsyncMock(side_effect=[SimpleNamespace(id=99), RuntimeError("lost acknowledgement")])
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=payload)))["status"] == "failed"
    rows = delivery_ledger.store()._conn.execute(
        "SELECT state FROM deliveries WHERE key LIKE 'media:discord:%'").fetchall()
    assert [row[0] for row in rows] == ["unknown"]
    assert (await rig.broker.execute(SimpleNamespace(id=17, payload=payload)))["status"] == "failed"
    assert rig.dm.send.await_count == 2
