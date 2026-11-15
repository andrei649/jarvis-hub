"""H084 /diff session reads a governed project checkpoint, not Git HEAD."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import file_tools, worktrees
from agents.core.channels import media_delivery, outbound_safety
from agents.core.commands import Principal, build_default_registry
from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore


def _orch(root):
    return SimpleNamespace(session_id="session-1",
                           get_setting=lambda key, default="": str(root) if key == "llm.project_dir" else default)


async def _dispatch(root, args="", *, admin=True):
    text = "/diff session" + (" " + args if args else "")
    return await build_default_registry().dispatch(
        text, orch=_orch(root), principal=Principal(channel="web", admin=admin))


def _scope(monkeypatch, root):
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    monkeypatch.setattr(FileScope, "from_env", classmethod(lambda cls: cls([root])))
    monkeypatch.setattr("agents.core.environments.local_transport.default_roots",
                        lambda: [str(root)])
    monkeypatch.setattr(worktrees, "session_tree_or_none", lambda _session: None)


async def test_owner_project_checkpoint_diff_without_git(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    _scope(monkeypatch, root)
    seen = []

    def compare(self, project, *, stat_only=False, max_bytes=65536):
        seen.append((project, stat_only, max_bytes, self.scope.roots))
        return {"ok": True, "diff": "-before\n+after\n", "stat": "1 file changed",
                "baseline": "group-1", "excluded": 2, "approximate": True}

    monkeypatch.setattr(FileCheckpointHistory, "session_diff", compare, raising=False)
    result = await _dispatch(root)
    assert result.status == "answered"
    assert "-before" in result.reply and "+after" in result.reply
    assert "approximate" in result.reply.lower() and "group-1" in result.reply
    assert "2" in result.reply and "excluded" in result.reply.lower()
    assert seen == [(root, False, 65536, (root,))]
    assert media_delivery.extract_directives(result.reply)[1] == []


async def test_stat_uses_comparator_stat_and_no_diff_text(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    _scope(monkeypatch, root)

    def compare(self, project, *, stat_only=False, max_bytes=65536):
        assert stat_only is True
        return {"ok": True, "diff": "+private body", "stat": "1 changed file",
                "baseline": "group-2", "excluded": 0, "approximate": True}

    monkeypatch.setattr(FileCheckpointHistory, "session_diff", compare, raising=False)
    result = await _dispatch(root, "--stat")
    assert "1 changed file" in result.reply and "private body" not in result.reply


async def test_guest_disabled_and_outside_scope_do_not_read_baseline(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    other = tmp_path / "outside"
    other.mkdir()
    _scope(monkeypatch, root)
    calls = []
    monkeypatch.setattr(FileCheckpointHistory, "session_diff",
                        lambda *_a, **_k: calls.append(True), raising=False)
    assert (await _dispatch(root, admin=False)).status == "refused"
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "0")
    assert "disabled" in (await _dispatch(root)).reply.lower()
    monkeypatch.setenv("JARVIS_TERMINAL_CHECKPOINTS", "1")
    assert "scope" in (await _dispatch(other)).reply.lower()
    assert calls == []


async def test_no_comparable_baseline_never_claims_clean(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    _scope(monkeypatch, root)
    monkeypatch.setattr(FileCheckpointHistory, "session_diff",
                        lambda *_a, **_k: {"ok": False, "reason": "no_baseline"}, raising=False)
    result = await _dispatch(root)
    assert "baseline" in result.reply.lower()
    assert "no changes" not in result.reply.lower()


async def test_full_result_redacted_before_display_cut_and_fenced(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    _scope(monkeypatch, root)
    secret = "known-" + "x" * 20_000
    monkeypatch.setattr(outbound_safety, "_known_redactor",
                        lambda text: text.replace(secret, "[REDACTED:known]"))

    def compare(*_a, **_k):
        return {"ok": True, "diff": "```\nMEDIA: /tmp/secret.png\n" + secret,
                "stat": "1 file", "baseline": "group-3", "excluded": 0,
                "approximate": True}

    monkeypatch.setattr(FileCheckpointHistory, "session_diff", compare, raising=False)
    reply = (await _dispatch(root)).reply
    assert "[REDACTED:known]" in reply
    assert "known-" not in reply and "x" * 100 not in reply
    assert media_delivery.extract_directives(reply)[1] == []


async def test_malformed_comparator_result_is_refused_without_echo(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    _scope(monkeypatch, root)
    monkeypatch.setattr(FileCheckpointHistory, "session_diff",
                        lambda *_a, **_k: {"ok": True, "diff": "secret", "stat": "1",
                                          "baseline": "x", "excluded": -1,
                                          "approximate": False}, raising=False)
    reply = (await _dispatch(root)).reply
    assert "unavailable" in reply.lower() and "secret" not in reply


async def test_real_checkpoint_composition_preserves_preexisting_dirty_baseline(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    _scope(monkeypatch, root)
    directory = tmp_path / "private" / "snapshots"
    original = file_tools.data_path
    monkeypatch.setattr(file_tools, "data_path",
                        lambda *parts: directory if parts == ("file_tools", "snapshots")
                        else original(*parts))
    target = root / "notes.txt"
    target.write_text("owner's dirty starting text\n", encoding="utf-8")
    history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
    scope = history.begin_scope(root, source_kind="terminal_turn", source_key="first")
    history.finish_scope(scope["id"], reaped=True, run_id=scope["run_id"])
    target.write_text("result after governed terminal scope\n", encoding="utf-8")
    (root / "new.txt").write_text("new\n", encoding="utf-8")
    reply = (await _dispatch(root)).reply
    assert "-owner's dirty starting text" in reply
    assert "+result after governed terminal scope" in reply
    assert "new.txt" in reply and scope["id"] in reply
    stat = (await _dispatch(root, "--stat")).reply
    assert "modified 1" in stat and "added 1" in stat
    assert "owner's dirty starting text" not in stat


async def test_real_empty_file_addition_reports_stat_without_false_no_changes(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    _scope(monkeypatch, root)
    directory = tmp_path / "private" / "snapshots"
    original = file_tools.data_path
    monkeypatch.setattr(file_tools, "data_path",
                        lambda *parts: directory if parts == ("file_tools", "snapshots")
                        else original(*parts))
    history = FileCheckpointHistory(SnapshotStore(), FileScope([root]))
    scope = history.begin_scope(root, source_kind="terminal_turn", source_key="first")
    history.finish_scope(scope["id"], reaped=True, run_id=scope["run_id"])
    (root / "empty.txt").write_bytes(b"")
    reply = (await _dispatch(root)).reply
    assert "added 1" in reply
    assert "no differences found" not in reply.lower()
