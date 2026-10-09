"""Regression: a direct late annotation cannot change a decided action."""

from agents.core.autonomy.action_approvals import ActionApprovalQueue


def test_annotate_rejects_decided_item_even_without_active_judge(tmp_path):
    path = tmp_path / "action_approvals.json"
    queue = ActionApprovalQueue(path)
    item = queue.request({"tool": "shell", "args": {"cmd": "true"}, "agent": "test"})
    queue.decide(item["id"], True, by="owner")
    before = path.read_bytes()

    late = {"score": 1, "why": "late", "judge": {"provider": "lm-studio", "model": "test"}}
    assert queue.annotate(item["id"], late) is None
    assert queue.get(item["id"])["status"] == "approved"
    assert "judge" not in queue.get(item["id"])
    assert path.read_bytes() == before
