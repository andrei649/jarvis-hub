"""A keyed file must have a durable attempting claim before transport."""

from types import SimpleNamespace

import pytest

from agents.core.channels import delivery_ledger, media_delivery
from tests.test_g16_channel_media_sms import PNG, _telegram, _Turn


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
