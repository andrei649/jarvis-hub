"""H3.3 — opt-in cross-channel session continuity.

Default: telegram keeps per-chat_id isolation (H1.2). With
`memory.cross_channel_sessions` enabled, every channel shares
orchestrator.session_id (web<->telegram continuity).

Note: imports the orchestrator module, which pulls cryptography (oauth).
Runs under CI with full deps."""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.orchestrator import Orchestrator
from agents.core.channels.manager import ChannelManager


def _bare_orchestrator():
    """Build an Orchestrator without running its heavy __init__, wiring only
    what channel_handler touches."""
    orch = Orchestrator.__new__(Orchestrator)
    orch._channel_sessions = {}
    orch._runtime_settings = {}
    orch.session_id = "web_shared"
    orch.channel_manager = ChannelManager()  # CLN-2: registry lives here now
    captured = {}

    async def fake_handle_input(text, channel="voice", agent_override=None):
        captured["session"] = orch.session_id  # which session was active
        return "ok"

    orch.handle_input = fake_handle_input

    class FakeMem:
        async def new_session(self, session_id=None):
            return "tg_isolated"

    orch.memory = FakeMem()
    return orch, captured


async def test_telegram_isolated_by_default():
    orch, captured = _bare_orchestrator()
    await orch.channel_handler("salut", channel="telegram", chat_id="123")
    assert captured["session"] == "tg_isolated"
    assert orch.session_id == "web_shared"  # restored after the call


async def test_cross_channel_flag_shares_session():
    orch, captured = _bare_orchestrator()
    orch._runtime_settings = {"memory.cross_channel_sessions": True}
    await orch.channel_handler("salut", channel="telegram", chat_id="123")
    assert captured["session"] == "web_shared"  # shared context, not isolated


async def test_web_always_uses_shared_session():
    orch, captured = _bare_orchestrator()
    await orch.channel_handler("salut", channel="web")
    assert captured["session"] == "web_shared"
