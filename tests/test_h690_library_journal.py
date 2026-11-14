"""Pure rollback bookkeeping on private text files; no anchoring/staging entrypoint."""

from pathlib import Path

import pytest

from agents.core import macos_tcc_anchor as anchor


def test_library_journal_module_supports_standalone_bootstrap_loader():
    import importlib.util

    # Match the stdlib-only bootstrap loader without executing bootstrap or anchoring.
    spec = importlib.util.spec_from_file_location("_nerva_journal_import_probe", anchor.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entry = module._Replacement(Path("unused.txt"), None)
    assert entry.original_moved is False and entry.installed is False


def test_library_journal_restore_failure_retains_backup_and_destination(tmp_path, monkeypatch):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    dest = root / "current.txt"
    incoming = root / "incoming.txt"
    dest.write_text("original", encoding="utf-8")
    incoming.write_text("replacement", encoding="utf-8")
    second = root / "second.txt"
    second_incoming = root / "second-incoming.txt"
    second.write_text("second original", encoding="utf-8")
    second_incoming.write_text("second replacement", encoding="utf-8")
    journal = []
    anchor._replace_journaled_file(incoming, dest, journal)
    anchor._replace_journaled_file(second_incoming, second, journal)
    backup = journal[0].backup
    real_replace = anchor.os.replace

    def refuse_restore(source, target):
        if Path(source) == backup:
            raise PermissionError("dummy text restoration refused")
        return real_replace(source, target)

    monkeypatch.setattr(anchor.os, "replace", refuse_restore)
    assert anchor._rollback_replacements(journal) is False

    assert backup.read_text(encoding="utf-8") == "original"
    assert dest.read_text(encoding="utf-8") == "replacement"
    assert second.read_text(encoding="utf-8") == "second original"
    # Recovery can be retried without deleting already-restored original bytes.
    monkeypatch.setattr(anchor.os, "replace", real_replace)
    assert anchor._rollback_replacements(journal) is True
    assert anchor._rollback_replacements(journal) is True
    assert dest.read_text(encoding="utf-8") == "original"
    assert second.read_text(encoding="utf-8") == "second original"


def test_library_journal_missing_backup_never_removes_destination(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    dest = root / "current.txt"
    dest.write_text("original or unconfirmed replacement", encoding="utf-8")

    journal = [anchor._Replacement(dest, root / "missing.txt", original_moved=True, installed=True)]
    assert anchor._failure_after_rollback("dummy_failure", journal) == {
        "ok": False, "anchored": False, "reason": "library_rollback_incomplete",
        "failed_step": "dummy_failure",
        "binary_rollback_complete": True, "library_rollback_complete": False,
    }

    assert dest.read_text(encoding="utf-8") == "original or unconfirmed replacement"


@pytest.mark.parametrize("phase", ["backup", "install"])
def test_library_journal_survives_second_replacement_failure(tmp_path, monkeypatch, phase):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    journal = []
    first, second = root / "first.txt", root / "second.txt"
    first_incoming, second_incoming = root / "incoming-first.txt", root / "incoming-second.txt"
    first.write_text("first original", encoding="utf-8")
    second.write_text("second original", encoding="utf-8")
    first_incoming.write_text("first new", encoding="utf-8")
    second_incoming.write_text("second new", encoding="utf-8")
    anchor._replace_journaled_file(first_incoming, first, journal)
    real_replace = anchor.os.replace
    failing_source = second if phase == "backup" else second_incoming

    def fail_one_step(source, target):
        if Path(source) == failing_source:
            # Intent is available to the caller even before the first rename.
            assert len(journal) == 2
            raise PermissionError("dummy text rename refused")
        return real_replace(source, target)

    monkeypatch.setattr(anchor.os, "replace", fail_one_step)
    with pytest.raises(PermissionError):
        anchor._replace_journaled_file(second_incoming, second, journal)
    assert anchor._rollback_replacements(journal) is True
    assert first.read_text(encoding="utf-8") == "first original"
    assert second.read_text(encoding="utf-8") == "second original"
    assert list(root.glob("*.nerva-bak.*")) == []


def test_library_journal_rollback_removes_only_newly_created_file(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    incoming, dest = root / "incoming.txt", root / "new.txt"
    incoming.write_text("new contents", encoding="utf-8")
    journal = []
    anchor._replace_journaled_file(incoming, dest, journal)
    assert dest.read_text(encoding="utf-8") == "new contents"
    assert anchor._rollback_replacements(journal) is True
    assert anchor._rollback_replacements(journal) is True
    assert not dest.exists()


@pytest.mark.parametrize("destination_exists", [False, True])
def test_library_journal_never_overwrites_prior_recovery_backup(tmp_path, destination_exists):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    incoming, dest = root / "incoming.txt", root / "current.txt"
    incoming.write_text("new contents", encoding="utf-8")
    if destination_exists:
        dest.write_text("current contents", encoding="utf-8")
    backup = dest.with_name(f".{dest.name}.nerva-bak.{anchor.os.getpid()}")
    backup.write_text("irreplaceable recovery contents", encoding="utf-8")
    journal = []
    with pytest.raises(FileExistsError):
        anchor._replace_journaled_file(incoming, dest, journal)
    assert journal == []
    assert backup.read_text(encoding="utf-8") == "irreplaceable recovery contents"
    assert incoming.read_text(encoding="utf-8") == "new contents"
    assert dest.exists() is destination_exists
    if destination_exists:
        assert dest.read_text(encoding="utf-8") == "current contents"


def test_library_journal_commit_cannot_be_undone_by_later_error_reporting(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    incoming, dest = root / "incoming.txt", root / "current.txt"
    incoming.write_text("committed", encoding="utf-8")
    dest.write_text("original", encoding="utf-8")
    journal = []
    anchor._replace_journaled_file(incoming, dest, journal)
    anchor._commit_replacements(journal)
    assert anchor._rollback_replacements(journal) is True
    assert dest.read_text(encoding="utf-8") == "committed"
    assert list(root.glob("*.nerva-bak.*")) == []


@pytest.mark.parametrize("failed_group", ["binary", "library", "both"])
def test_anchor_journal_reports_both_recovery_groups_on_plain_text_files(tmp_path, monkeypatch, failed_group):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    groups = {"binary": [], "library": []}
    destinations = {}
    for index, (name, journal) in enumerate(groups.items()):
        dest, incoming = root / f"current-{index}.txt", root / f"incoming-{index}.txt"
        dest.write_text(f"original {index}", encoding="utf-8")
        incoming.write_text(f"replacement {index}", encoding="utf-8")
        anchor._replace_journaled_file(incoming, dest, journal)
        destinations[name] = dest
    real_replace = anchor.os.replace
    failed_backups = {journal[0].backup for name, journal in groups.items()
                      if name == failed_group or failed_group == "both"}

    def refuse_selected_restore(source, target):
        if Path(source) in failed_backups:
            raise PermissionError("dummy text group recovery refused")
        return real_replace(source, target)

    monkeypatch.setattr(anchor.os, "replace", refuse_selected_restore)
    result = anchor._failure_after_rollback("dummy_failure", groups["library"], groups["binary"])
    assert result == {
        "ok": False,
        "anchored": False,
        "reason": "binary_rollback_incomplete" if failed_group != "library" else "library_rollback_incomplete",
        "failed_step": "dummy_failure",
        "binary_rollback_complete": failed_group == "library",
        "library_rollback_complete": failed_group == "binary",
    }
    for index, (name, journal) in enumerate(groups.items()):
        failed = name == failed_group or failed_group == "both"
        assert destinations[name].read_text(encoding="utf-8") == (
            f"replacement {index}" if failed else f"original {index}")
        if failed:
            assert journal[0].backup.read_text(encoding="utf-8") == f"original {index}"
