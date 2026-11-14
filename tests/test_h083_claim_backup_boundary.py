"""A data backup/forget/restore cannot replace a live polling lock inode."""

import os
import subprocess
import sys

from agents.core import backup, data_purge
from agents.core.channels.polling_claims import acquire_telegram_claim


def test_data_lifecycle_preserves_live_sibling_claim(tmp_path, monkeypatch):
    root = tmp_path / "install"
    root.mkdir()
    (root / "notes.json").write_text('{"session": {"content": "private"}}')
    monkeypatch.setenv("JARVIS_HOME", str(root))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    claim = acquire_telegram_claim("offline-backup-token")
    lockfile = next((tmp_path / ".install-channel-claims").glob("*.lock"))
    before = lockfile.stat()

    def still_exclusive():
        after = lockfile.stat()
        assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
        script = (
            "from agents.core.channels.polling_claims import acquire_telegram_claim, ClaimUnavailable\n"
            "try:\n"
            "    claim = acquire_telegram_claim('offline-backup-token')\n"
            "except ClaimUnavailable as exc:\n"
            "    print(exc.reason)\n"
            "else:\n"
            "    claim.release()\n"
            "    print('unexpected acquired')\n"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True,
                                text=True, timeout=10,
                                env={**os.environ, "JARVIS_PROFILE": "contender"})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "busy"

    try:
        archive = backup.create_backup(source_root=str(root), out_dir=str(tmp_path / "archives"))
        still_exclusive()
        assert data_purge.purge_data(source_root=str(root), backup_first=False)["ok"]
        still_exclusive()
        assert backup.restore_backup(archive["archive"], str(root), force=True)["ok"]
        still_exclusive()
    finally:
        claim.release()
