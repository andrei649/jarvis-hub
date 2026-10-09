"""Unsigned filesystem identifiers retain exact bytes in signed approval JSON."""

from types import SimpleNamespace

from agents.core.autonomy.mediation import payload_digest
from agents.core.voice import local_providers


def test_unsigned_inode_is_exact_and_canonical_without_widening_json(tmp_path, monkeypatch):
    path = tmp_path / "provider.py"
    path.write_text("print('fixture')\n")
    fstat = local_providers.os.fstat
    inode = [2**64 - 1]

    def unsigned_stat(fd):
        info = fstat(fd)
        return SimpleNamespace(**{name: getattr(info, name) for name in (
            "st_dev", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns"
        )}, st_ino=inode[0])

    monkeypatch.setattr(local_providers.os, "fstat", unsigned_stat)
    recorded = local_providers.file_identity(path)
    assert recorded["ino"] == str(2**64 - 1)
    assert len(payload_digest({"bound": recorded})) == 64
    assert local_providers._same_identity(recorded, local_providers.file_identity(path))
    inode[0] -= 1
    assert not local_providers._same_identity(recorded, local_providers.file_identity(path))
