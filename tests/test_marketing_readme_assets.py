"""marketing/README.md's folder table may only name assets that exist (DRA-57).

The alpha-testing row used to advertise `jarvis-alpha-hook-vertical.mp4`, a video that is
owner-recorded and has never been in the repo, while hiding the assets that *are* there
(FAQ.md, screenshots/). Nothing else reads this file, so without this guard the index can
promise files again.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "marketing/README.md"


def _folder_table_rows() -> list[tuple[str, list[str]]]:
    """[(folder, [backticked tokens in the File column]), ...] from the folder table."""
    rows = []
    for line in README.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*\[`([^`]+)`\]\([^)]+\)\s*\|([^|]*)\|", line)
        if match:
            rows.append((match.group(1), re.findall(r"`([^`]+)`", match.group(2))))
    return rows


def test_every_file_named_in_the_folder_table_exists() -> None:
    rows = _folder_table_rows()
    assert len(rows) >= 6, rows
    for folder, tokens in rows:
        assert tokens, f"row for {folder} names no file"
        for token in tokens:
            target = ROOT / "marketing" / folder.rstrip("/") / token.rstrip("/")
            if token.endswith("/"):
                assert target.is_dir(), f"marketing/{folder}{token} named in marketing/README.md does not exist"
            else:
                assert target.is_file(), f"marketing/{folder}{token} named in marketing/README.md does not exist"


def test_alpha_testing_row_names_the_assets_that_are_actually_shipped() -> None:
    """The row must be *corrected*, not emptied — dropping the folder from the index would
    also make the first test pass."""
    rows = dict(_folder_table_rows())
    assert "alpha-testing/" in rows, "alpha-testing row disappeared from the index"
    tokens = set(rows["alpha-testing/"])
    assert {"INVITE_MESSAGE.md", "FAQ.md", "screenshots/"} <= tokens, tokens
