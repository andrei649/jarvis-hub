"""Tests for /chat and /chat/stream endpoints — model validation, agent_override."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.web import ChatRequest, ChatResponse


def test_chat_request_default_agent():
    req = ChatRequest(message="test")
    assert req.message == "test"
    assert req.agent == "jarvis"


def test_chat_request_custom_agent():
    req = ChatRequest(message="hello", agent="friday")
    assert req.message == "hello"
    assert req.agent == "friday"


def test_chat_request_empty_message_rejected():
    # A blank/whitespace turn must not reach the orchestrator or spend an LLM
    # call — pydantic rejects it before the endpoint runs (422 to the client).
    import pytest
    from pydantic import ValidationError

    for blank in ("", "   ", "\n\t "):
        with pytest.raises(ValidationError):
            ChatRequest(message=blank)
    # A real message still validates.
    assert ChatRequest(message="hello").message == "hello"


def test_chat_response_model():
    resp = ChatResponse(reply="hello back")
    assert resp.reply == "hello back"
    assert isinstance(resp.reply, str)
