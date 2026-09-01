"""DRA-15 backend defect 5: the inbox reported a constant as its channel list.

`ChannelInboxStore.stats()` returned ``"channels": sorted(SUPPORTED_INBOX_CHANNELS)`` — a
module-level frozenset that is identical on every install, whether or not a single message
has ever arrived. The payload therefore carried ZERO information about the thing a reader
would take it for: which channels actually hold traffic. "email telegram web" rendered the
same on a box where email is flowing and on one where it has never been configured.

The supported set is still worth publishing — it is the vocabulary — but it must not be
the answer to "what is in the inbox".
"""

import pytest

from agents.core.channel_inbox import SUPPORTED_INBOX_CHANNELS, ChannelInboxStore


@pytest.fixture
def store(tmp_path):
    return ChannelInboxStore(path=str(tmp_path / "inbox.json"))


def test_an_empty_inbox_reports_no_active_channels(store):
    s = store.stats()
    assert s["messages"] == 0
    assert s["active_channels"] == [], "an empty inbox must not claim any channel is in use"
    assert s["by_channel"] == {}
    # the vocabulary is still published, and is still the full supported set
    assert s["channels"] == sorted(SUPPORTED_INBOX_CHANNELS)


def test_active_channels_reflect_what_is_actually_stored(store):
    store.record_inbound("telegram", "hello", sender="u1")
    store.record_inbound("telegram", "again", sender="u1")
    store.record_inbound("web", "hi", sender="u2")

    s = store.stats()
    assert s["active_channels"] == ["telegram", "web"]
    assert s["by_channel"] == {"telegram": 2, "web": 1}
    # a supported-but-silent channel is absent from the active list, not reported as 0
    assert "email" not in s["active_channels"]
    assert "email" not in s["by_channel"]


def test_the_supported_set_is_not_mistaken_for_the_active_one(store):
    """The regression itself: these two must not be the same value."""
    store.record_inbound("telegram", "hello", sender="u1")
    s = store.stats()
    assert s["channels"] != s["active_channels"], (
        "stats() is reporting the supported vocabulary as if it were live traffic"
    )
    assert set(s["active_channels"]) <= set(s["channels"])
