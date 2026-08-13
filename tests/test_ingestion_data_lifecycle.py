"""ADV-131 / G35 — Howard's private ingestion data has one lifecycle contract.

The default raw-import drop and every derived archive artifact must live below the
runtime data root, be present in the portable export, be eligible for explicit
retention, and never be exempted from a full forget.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import data_export, data_purge, retention, settings_db
from agents.core.ingestion import lifecycle as ingestion_lifecycle
from agents.core.ingestion.lifecycle import (
    INGESTION_ARCHIVE_ROOT,
    INGESTION_IMPORT_ROOT,
    PRIVATE_INGESTION_ROOTS,
)
from agents.core.ingestion.normalizer import NormalizedMessage
from agents.core.ingestion.pipeline import IngestionPipeline
from agents.core.ingestion.watcher import IngestionWatcher
from agents.core.scheduler_service import SchedulerService

_DAY = 86400


def _seed_archive_db(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, text TEXT)")
    conn.execute("INSERT INTO messages (text) VALUES (?)", (marker,))
    conn.commit()
    conn.close()


def _age_tree(path: Path, *, age_days: float) -> None:
    timestamp = time.time() - age_days * _DAY
    for item in sorted(path.rglob("*"), reverse=True):
        if not item.is_symlink():
            os.utime(item, (timestamp, timestamp))
    os.utime(path, (timestamp, timestamp))


def test_default_ingestion_paths_are_inside_runtime_data_root(tmp_path, monkeypatch):
    runtime_root = tmp_path / "nerva-memory"
    monkeypatch.setenv("JARVIS_HOME", str(runtime_root))

    pipeline = IngestionPipeline()
    watcher = IngestionWatcher(pipeline=pipeline)

    assert pipeline.data_root == runtime_root / INGESTION_IMPORT_ROOT
    assert pipeline.output_root == runtime_root / INGESTION_ARCHIVE_ROOT
    assert watcher.data_root == runtime_root / INGESTION_IMPORT_ROOT
    assert watcher.state_path == runtime_root / INGESTION_ARCHIVE_ROOT / "watcher_state.json"


def test_legacy_default_is_detected_watched_and_reported_until_owner_resolves(
    tmp_path, monkeypatch
):
    repo_root = tmp_path / "checkout"
    runtime_root = tmp_path / "nerva-memory"
    legacy_root = repo_root / "data"
    marker = legacy_root / "whatsapp" / "chat.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("LEGACY-PRIVATE-MARKER", encoding="utf-8")
    monkeypatch.setattr(ingestion_lifecycle, "app_root", lambda: repo_root)
    monkeypatch.setenv("JARVIS_HOME", str(runtime_root))

    watcher = IngestionWatcher()
    export = data_export.export_data(
        source_root=str(runtime_root), out_dir=str(tmp_path / "exports")
    )
    document = json.loads(Path(export["export"]).read_text(encoding="utf-8"))
    forget = data_purge.purge_data(
        source_root=str(runtime_root), backup_first=False
    )

    assert watcher.data_root == legacy_root
    assert export["private_ingestion_complete"] is False
    assert export["legacy_private_ingestion"] == {
        "detected": True,
        "path": str(legacy_root),
        "reason": "legacy_repo_local_imports_require_owner_resolution",
    }
    assert document["legacy_private_ingestion"] == export["legacy_private_ingestion"]
    assert forget["ok"] is False
    assert str(legacy_root) in " ".join(forget["not_erased"])
    assert marker.read_text(encoding="utf-8") == "LEGACY-PRIVATE-MARKER"


def test_documented_rollback_staging_restores_old_default_discoverability(
    tmp_path, monkeypatch
):
    repo_root = tmp_path / "checkout"
    runtime_root = tmp_path / "nerva-memory"
    current_root = runtime_root / INGESTION_IMPORT_ROOT
    marker = current_root / "whatsapp" / "chat.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("ROLLBACK-DISCOVERY-MARKER", encoding="utf-8")
    legacy_root = repo_root / "data"
    monkeypatch.setattr(ingestion_lifecycle, "app_root", lambda: repo_root)
    monkeypatch.setenv("JARVIS_HOME", str(runtime_root))

    # Operational rollback rehearsal: while this candidate is still running,
    # stage a verified copy at the old version's default before reverting code.
    shutil.copytree(current_root, legacy_root)

    assert ingestion_lifecycle.default_import_root() == legacy_root
    assert (legacy_root / "whatsapp" / "chat.txt").read_text(
        encoding="utf-8"
    ) == "ROLLBACK-DISCOVERY-MARKER"


def test_private_ingestion_roots_have_identical_lifecycle_sets():
    expected = tuple(PRIVATE_INGESTION_ROOTS)
    assert expected == data_export.EXPORT_PRIVATE_DIRS
    assert expected == retention.RETENTION_PRIVATE_DIRS
    assert expected == data_purge.PURGE_PRIVATE_DIRS
    assert not (set(expected) & set(data_purge.KEEP_DIRS))


def test_export_captures_raw_imports_and_every_archive_file(tmp_path):
    root = tmp_path / "memory"
    imports = root / INGESTION_IMPORT_ROOT
    archive = root / INGESTION_ARCHIVE_ROOT
    (imports / "whatsapp").mkdir(parents=True)
    (imports / "whatsapp" / "chat.txt").write_text(
        "[01.01.2026] Andrei: RAW-PRIVATE-MARKER", encoding="utf-8"
    )
    _seed_archive_db(archive / "archive.db", "DB-PRIVATE-MARKER")
    (archive / "messages.jsonl").write_text('{"text":"JSONL-PRIVATE-MARKER"}\n', encoding="utf-8")
    (archive / "voice_profile.json").write_text(
        '{"signature":"VOICE-PRIVATE-MARKER"}', encoding="utf-8"
    )
    cache = archive / "embedding_cache" / "hash-model" / "aa"
    cache.mkdir(parents=True)
    (cache / "vector.json").write_text('{"vector":[0.1,0.2]}', encoding="utf-8")

    result = data_export.export_data(source_root=str(root), out_dir=str(tmp_path / "exports"))
    document = json.loads(Path(result["export"]).read_text(encoding="utf-8"))
    private = document["private_ingestion"]

    assert result["private_ingestion_complete"] is True
    assert result["private_ingestion_roots"] == list(PRIVATE_INGESTION_ROOTS)
    assert private[INGESTION_IMPORT_ROOT]["files"]["whatsapp/chat.txt"]["text"].endswith(
        "RAW-PRIVATE-MARKER"
    )
    db_rows = private[INGESTION_ARCHIVE_ROOT]["files"]["archive.db"]["tables"]["messages"]
    assert db_rows == [{"id": 1, "text": "DB-PRIVATE-MARKER"}]
    assert private[INGESTION_ARCHIVE_ROOT]["files"]["messages.jsonl"]["records"] == [
        {"text": "JSONL-PRIVATE-MARKER"}
    ]
    assert private[INGESTION_ARCHIVE_ROOT]["files"]["voice_profile.json"]["value"] == {
        "signature": "VOICE-PRIVATE-MARKER"
    }
    assert "embedding_cache/hash-model/aa/vector.json" in private[INGESTION_ARCHIVE_ROOT]["files"]


def test_export_does_not_follow_private_root_symlinks(tmp_path):
    root = tmp_path / "memory"
    archive = root / INGESTION_ARCHIVE_ROOT
    archive.mkdir(parents=True)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("SYMLINK-SECRET-MUST-NOT-EXPORT", encoding="utf-8")
    (archive / "outside-link.txt").symlink_to(outside)

    result = data_export.export_data(source_root=str(root), out_dir=str(tmp_path / "exports"))
    export_text = Path(result["export"]).read_text(encoding="utf-8")
    root_result = json.loads(export_text)["private_ingestion"][INGESTION_ARCHIVE_ROOT]

    assert result["private_ingestion_complete"] is False
    assert root_result["skipped"] == [{"path": "outside-link.txt", "reason": "symlink_refused"}]
    assert "SYMLINK-SECRET-MUST-NOT-EXPORT" not in export_text


def test_export_marks_a_broken_private_root_symlink_incomplete(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    (root / INGESTION_IMPORT_ROOT).symlink_to(tmp_path / "missing-target", target_is_directory=True)

    result = data_export.export_data(
        source_root=str(root), out_dir=str(tmp_path / "exports")
    )
    exported = json.loads(Path(result["export"]).read_text(encoding="utf-8"))

    assert result["private_ingestion_complete"] is False
    assert exported["private_ingestion"][INGESTION_IMPORT_ROOT]["skipped"] == [
        {"path": ".", "reason": "symlink_refused"}
    ]


def test_archive_export_quotes_sqlite_catalog_names(tmp_path):
    root = tmp_path / "memory"
    db_path = root / INGESTION_ARCHIVE_ROOT / "archive.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    table = 'odd " archive table'
    conn.execute(f'CREATE TABLE "{table.replace(chr(34), chr(34) * 2)}" (value TEXT)')
    conn.execute(
        f'INSERT INTO "{table.replace(chr(34), chr(34) * 2)}" (value) VALUES (?)',
        ("quoted-catalog-marker",),
    )
    conn.commit()
    conn.close()

    result = data_export.export_data(
        source_root=str(root), out_dir=str(tmp_path / "exports")
    )
    exported = json.loads(Path(result["export"]).read_text(encoding="utf-8"))
    tables = exported["private_ingestion"][INGESTION_ARCHIVE_ROOT]["files"]["archive.db"][
        "tables"
    ]

    assert tables[table] == [{"value": "quoted-catalog-marker"}]


def test_retention_prunes_stale_private_roots_and_keeps_fresh_one(tmp_path):
    from agents.core.ingestion import embedder
    from agents.core.ingestion import pipeline as pipeline_module

    stale_imports = tmp_path / INGESTION_IMPORT_ROOT
    fresh_archive = tmp_path / INGESTION_ARCHIVE_ROOT
    stale_imports.mkdir()
    fresh_archive.mkdir()
    (stale_imports / "chat.txt").write_text("old private import", encoding="utf-8")
    (fresh_archive / "messages.jsonl").write_text("fresh archive", encoding="utf-8")
    _age_tree(stale_imports, age_days=120)
    _age_tree(fresh_archive, age_days=2)
    pipeline = IngestionPipeline(data_root=stale_imports, output_root=fresh_archive)
    private = NormalizedMessage(
        source="whatsapp",
        conversation_id="old",
        sender="Andrei",
        is_me=True,
        text="TTL-LIVE-PRIVATE-MARKER",
        timestamp=1.0,
    )
    pipeline.messages.append(private)
    key = ("hash", "ttl-model", private.text)
    embedder._proc_cache_put(key, [0.5])
    pipeline_module._SHARED_PIPELINE = pipeline

    report = retention.purge_old_private_ingestion(90, root=tmp_path)

    assert report["deleted"] == [INGESTION_IMPORT_ROOT]
    assert report["live_ingestion"]["pipelines"] == 1
    assert report["live_ingestion"]["messages"] == 1
    assert report["live_ingestion"]["embedding_entries"] >= 1
    assert not stale_imports.exists()
    assert fresh_archive.exists()
    assert embedder._proc_cache_get(key) is None
    assert pipeline_module._SHARED_PIPELINE is None


@pytest.mark.asyncio
async def test_scheduled_retention_clears_distinct_watcher_and_shared_pipelines(
    tmp_path, monkeypatch
):
    from agents.core.ingestion import embedder
    from agents.core.ingestion import pipeline as pipeline_module

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    imports = tmp_path / INGESTION_IMPORT_ROOT
    archive = tmp_path / INGESTION_ARCHIVE_ROOT
    imports.mkdir()
    (imports / "chat.txt").write_text("old private import", encoding="utf-8")
    writer = IngestionPipeline(data_root=imports, output_root=archive)
    reader = IngestionPipeline(data_root=imports, output_root=archive)
    writer_private = NormalizedMessage(
        source="whatsapp",
        conversation_id="writer",
        sender="Andrei",
        is_me=True,
        text="WATCHER-LIVE-PRIVATE-MARKER",
        timestamp=1.0,
    )
    reader_private = NormalizedMessage(
        source="whatsapp",
        conversation_id="reader",
        sender="Andrei",
        is_me=True,
        text="RAG-LIVE-PRIVATE-MARKER",
        timestamp=1.0,
    )
    writer.messages.append(writer_private)
    writer.my_messages.append(writer_private)
    writer.stylometry.profile.total_messages = 1
    writer.knowledge.decisions.append(object())
    reader.messages.append(reader_private)
    reader.my_messages.append(reader_private)
    key = ("hash", "scheduled-retention", writer_private.text)
    embedder._proc_cache_put(key, [0.5])
    monkeypatch.setattr(pipeline_module, "_SHARED_PIPELINE", reader)
    _age_tree(imports, age_days=120)
    _age_tree(archive, age_days=120)
    settings = {
        "retention.enabled": True,
        "retention.conversation_ttl_days": 0,
        "retention.audit_ttl_days": 0,
        "retention.ingestion_ttl_days": 90,
    }
    orch = SimpleNamespace(
        audit=None,
        ingestion_watcher=SimpleNamespace(pipeline=writer),
        get_setting=lambda key, default=None: settings.get(key, default),
    )

    await SchedulerService(orch).run_retention_purge()

    assert writer.messages == []
    assert writer.my_messages == []
    assert writer.stylometry.profile.total_messages == 0
    assert writer.knowledge.decisions == []
    assert reader.messages == []
    assert reader.my_messages == []
    assert embedder._proc_cache_get(key) is None
    assert pipeline_module._SHARED_PIPELINE is None


def test_retention_ttl_zero_preserves_private_ingestion(tmp_path):
    archive = tmp_path / INGESTION_ARCHIVE_ROOT
    archive.mkdir()
    (archive / "messages.jsonl").write_text("private", encoding="utf-8")
    _age_tree(archive, age_days=999)

    report = retention.purge_old_private_ingestion(0, root=tmp_path)

    assert report == {"deleted": [], "failed": [], "ttl_days": 0}
    assert archive.exists()


def test_retention_refuses_private_root_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "private.txt"
    marker.write_text("RETENTION-OUTSIDE-MARKER", encoding="utf-8")
    root = tmp_path / "memory"
    root.mkdir()
    private_link = root / INGESTION_ARCHIVE_ROOT
    private_link.symlink_to(outside, target_is_directory=True)

    report = retention.purge_old_private_ingestion(1, root=root, now=time.time() + 10 * _DAY)

    assert report["deleted"] == []
    assert report["failed"] == [{"root": INGESTION_ARCHIVE_ROOT, "reason": "unsafe_root"}]
    assert private_link.is_symlink()
    assert marker.read_text(encoding="utf-8") == "RETENTION-OUTSIDE-MARKER"


def test_run_retention_wires_the_private_ingestion_ttl(tmp_path):
    for name in PRIVATE_INGESTION_ROOTS:
        private_root = tmp_path / name
        private_root.mkdir()
        (private_root / "private.txt").write_text("old", encoding="utf-8")
        _age_tree(private_root, age_days=120)
    settings = {
        "retention.enabled": True,
        "retention.conversation_ttl_days": 0,
        "retention.audit_ttl_days": 0,
        "retention.ingestion_ttl_days": 90,
    }

    report = retention.run_retention(lambda key, default=None: settings.get(key, default), root=tmp_path)

    assert report["private_ingestion"]["deleted"] == list(PRIVATE_INGESTION_ROOTS)


def test_forget_erases_both_private_ingestion_roots(tmp_path):
    imports = tmp_path / INGESTION_IMPORT_ROOT
    archive = tmp_path / INGESTION_ARCHIVE_ROOT
    imports.mkdir()
    archive.mkdir()
    (imports / "chat.txt").write_text("RAW-FORGET-MARKER", encoding="utf-8")
    _seed_archive_db(archive / "archive.db", "ARCHIVE-FORGET-MARKER")
    (archive / "voice_profile.json").write_text(
        '{"marker":"PROFILE-FORGET-MARKER"}', encoding="utf-8"
    )

    report = data_purge.purge_data(source_root=str(tmp_path), backup_first=False, memory=True)

    assert report["ok"] is True
    surviving = b"".join(
        path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    assert b"FORGET-MARKER" not in surviving


def test_forget_clears_live_archive_messages_and_embedding_text_keys(tmp_path, monkeypatch):
    from agents.core.ingestion import embedder
    from agents.core.ingestion import pipeline as pipeline_module

    archive = tmp_path / INGESTION_ARCHIVE_ROOT
    pipeline = IngestionPipeline(data_root=tmp_path / INGESTION_IMPORT_ROOT, output_root=archive)
    private = NormalizedMessage(
        source="whatsapp",
        conversation_id="family",
        sender="Andrei",
        is_me=True,
        text="LIVE-ARCHIVE-PRIVATE-MARKER",
        timestamp=1.0,
    )
    pipeline.messages.append(private)
    pipeline.my_messages.append(private)
    pipeline.knowledge.decisions.append(object())
    key = ("hash", "test-model", private.text)
    embedder._proc_cache_put(key, [0.5])
    monkeypatch.setattr(pipeline_module, "_SHARED_PIPELINE", pipeline)

    report = data_purge.purge_data(source_root=str(tmp_path), backup_first=False)

    assert report["purged"]["live_ingestion"]["pipelines"] == 1
    assert report["purged"]["live_ingestion"]["messages"] == 1
    assert report["purged"]["live_ingestion"]["embedding_entries"] >= 1
    assert pipeline.messages == []
    assert pipeline.my_messages == []
    assert pipeline.knowledge.decisions == []
    assert embedder._proc_cache_get(key) is None
    assert pipeline_module._SHARED_PIPELINE is None


def test_forget_fails_closed_if_a_private_root_is_ever_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(data_purge, "KEEP_DIRS", frozenset({INGESTION_ARCHIVE_ROOT}))

    with pytest.raises(data_purge.PurgeError, match="archive"):
        data_purge.purge_data(source_root=str(tmp_path), backup_first=False)


def test_forget_unlinks_private_symlinks_without_touching_external_targets(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "private.json"
    marker.write_text('{"secret":"FORGET-OUTSIDE-MARKER"}', encoding="utf-8")
    root = tmp_path / "memory"
    linked_root = root / INGESTION_ARCHIVE_ROOT
    linked_root.mkdir(parents=True)
    linked_file = linked_root / "linked-private.json"
    linked_file.symlink_to(marker)

    report = data_purge.purge_data(source_root=str(root), backup_first=False)

    assert report["ok"] is True
    assert not linked_file.exists()
    assert marker.read_text(encoding="utf-8") == '{"secret":"FORGET-OUTSIDE-MARKER"}'


def test_retention_setting_is_explicit_and_safe_by_default():
    by_key = {item["key"]: item for item in settings_db.DEFAULTS if item["category"] == "retention"}
    assert by_key["ingestion_ttl_days"]["value"] == 0
