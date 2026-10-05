import pytest
@pytest.fixture(autouse=True)
def disable_wait_credit(monkeypatch):
    from agents.core import agent_runtime
    monkeypatch.setattr(agent_runtime, "current_human_wait_scope", lambda: None)
