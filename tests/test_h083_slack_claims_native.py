"""Connection ownership through actual installed Slack SDK worker settlement."""

import pytest

from agents.core.channels import polling_claims, slack


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_failure", ["none", "exception", "unknown_runner"])
async def test_native_sdk_claim_blocks_second_profile_until_workers_settle(
        tmp_path, monkeypatch, cleanup_failure):
    native = pytest.importorskip("slack_sdk.socket_mode")
    constructed = []

    class OfflineWebClient:
        def __init__(self, **kwargs):
            constructed.append(self)

        def auth_test(self):
            return {"ok": True, "team_id": "T1", "user_id": "UBOT"}

    monkeypatch.setattr(polling_claims, "install_root", lambda: tmp_path / "install")
    monkeypatch.setattr(slack, "SLACK_AVAILABLE", True)
    monkeypatch.setattr(slack, "WebClient", OfflineWebClient)
    monkeypatch.setattr(slack, "SocketModeClient", native.SocketModeClient)
    monkeypatch.setattr(native.SocketModeClient, "connect", lambda self: None)
    monkeypatch.setattr(native.SocketModeClient, "is_connected", lambda self: not self.closed)
    first = slack.SlackChannel("offline-bot", app_token="offline-app")
    second = slack.SlackChannel("different-bot", app_token="offline-app")
    restore = None
    try:
        await first.start()
        client = first._socket_client
        assert client is not None and client.message_processor.is_alive()
        await second.start()
        assert len(constructed) == 1
        assert not second._running
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        if cleanup_failure != "none":
            if cleanup_failure == "exception":
                original = client.close

                def failed_close():
                    raise RuntimeError("offline close failure")

                client.close = failed_close

                def restore():
                    client.close = original
            else:
                runner = client.current_app_monitor
                original = runner.is_alive
                runner.is_alive = lambda: None

                def restore():
                    runner.is_alive = original
            with pytest.raises(RuntimeError):
                await first.stop()
            assert first._socket_client is client
            await second.start()
            assert not second._running and len(constructed) == 1
            restore()
            restore = None
        await first.stop()
        for name in ("current_session_runner", "current_app_monitor", "message_processor"):
            assert getattr(client, name).is_alive() is False
        await second.start()
        assert second._running and len(constructed) == 2
    finally:
        if restore is not None:
            restore()
        await first.stop()
        await second.stop()
