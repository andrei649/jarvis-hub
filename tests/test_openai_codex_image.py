"""Codex image credentials bind one OAuth JWT to the official endpoint."""

import base64
import json
import time

import pytest


def _jwt(*, exp, account="acct-test"):
    payload = {"exp": exp, "https://api.openai.com/auth": {"chatgpt_account_id": account}}
    middle = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "header." + middle + ".signature"


def test_codex_credential_is_paired_with_official_base_and_account():
    from agents.core.media_backends.codex_image import resolve_credential

    credential = resolve_credential(lambda: {
        "access_token": _jwt(exp=int(time.time()) + 3600),
        "base_url": "https://chatgpt.com/backend-api/codex",
    })
    assert credential.base_url == "https://chatgpt.com/backend-api/codex"
    assert credential.account_id == "acct-test"
    assert credential.headers["ChatGPT-Account-ID"] == "acct-test"
    assert credential.headers["originator"] == "nerva"


@pytest.mark.parametrize("source", [
    {"access_token": "sk-api-key", "base_url": "https://chatgpt.com/backend-api/codex"},
    {"access_token": _jwt(exp=1), "base_url": "https://chatgpt.com/backend-api/codex"},
    {"access_token": _jwt(exp=4102444800), "base_url": "https://example.com/backend-api/codex"},
])
def test_codex_rejects_invalid_or_mismatched_credentials(source):
    from agents.core.media_backends.codex_image import resolve_credential

    with pytest.raises(ValueError):
        resolve_credential(lambda: source)
