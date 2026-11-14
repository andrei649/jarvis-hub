"""Whole-value placeholder checks keep opaque credentials unchanged."""

import pytest

from agents.core.channels.credentials import credential_is_configured


@pytest.mark.parametrize("value", [
    None, False, 7, b"opaque", "", " \t ",
    "replace_me", "CHANGEME", "Token_Here",
    "YOUR_TOKEN", "your_slack_bot_token_here", " YOUR_APP_TOKEN ",
    "${SLACK_BOT_TOKEN}", " ${NERVA_2} ",
    "<bot-token>", " <YOUR_SLACK_APP_TOKEN> ",
])
def test_obvious_whole_credential_placeholders_are_rejected(value):
    assert credential_is_configured(value) is False


@pytest.mark.parametrize("value", [
    "bot", "app", "bot-secret", "offline-bot", " xoxb-opaque ",
    "prefix_your_bot_token_suffix", "opaque-token_here-suffix", "changeme-but-real",
    "abc${SLACK_BOT_TOKEN}def", "prefix<bot-token>suffix", "<not-a-token-template>suffix",
])
def test_valid_opaque_values_and_embedded_placeholder_like_text_pass(value):
    assert credential_is_configured(value) is True
