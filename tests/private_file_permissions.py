"""Check actual access permissions of a newly written private file."""
import os
import stat
from pathlib import Path


def assert_private_file(path: str | Path) -> None:
    path = Path(path)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        return

    from agents.core.checkpoint_windows_fs import WindowsHistoryFs

    fs = WindowsHistoryFs()
    with fs.open_root(str(path.parent.resolve())) as parent, fs.open_child(
        parent, path.name, directory=False
    ) as file:
        owner, current, protected, aces = fs.api.acl_info(file.raw)
    # OWNER RIGHTS is scoped to the checked owner. SYSTEM and Administrators are trusted on Windows.
    owner_sids = {current, "S-1-3-4"}
    trusted = owner_sids | {"S-1-5-18", "S-1-5-32-544"}
    assert owner == current and protected
    assert any(sid in owner_sids and kind == "allow" for sid, kind in aces)
    assert all(sid in trusted and kind == "allow" for sid, kind in aces)
